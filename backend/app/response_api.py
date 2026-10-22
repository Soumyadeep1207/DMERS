"""REST endpoints for the incident-response model (Review II objects, schema ``response``).

Every write is one database transaction (``db.tx.transaction``). Flask validates the shape of the
request and checks who may call the endpoint (from ``users.account_type`` in the database); every
rule about the data (busy unit, unverified incident, stock, lead-only, illegal transition, ...) is
enforced by PostgreSQL and merely translated into an HTTP status. Responses carry a ``db_trace``.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from functools import update_wrapper

from flask import Blueprint, Response, jsonify, request

from db import reports as report_module
from db.errors import ApiError, map_error
from db.health import response_model_health
from db.pool import available, get_pool
from db.tx import transaction

COORDINATOR, UNIT_LEAD, ADMIN, CITIZEN = "COORDINATOR", "UNIT_LEAD", "ADMINISTRATOR", "CITIZEN"
INCIDENT_TYPES = ("FIRE", "FLOOD", "MEDICAL", "ROAD_ACCIDENT", "GAS_LEAK", "TREE_FALL", "LANDSLIDE", "BUILDING_COLLAPSE", "WATER_RESCUE", "OTHER")
SEVERITIES = ("LOW", "MODERATE", "HIGH", "CRITICAL")
PROGRESS = ("EN_ROUTE", "ON_SCENE", "COMPLETED")
DEMO_EMAIL_PATTERNS = ["%@dmers.example.org", "%@mail.example.com"]     # the fictitious Review II people


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def demo_mode() -> bool:
    return os.getenv("DMERS_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _int(data: dict, name: str, *, minimum: int | None = None, required: bool = True):
    raw = data.get(name)
    if raw in (None, ""):
        if required:
            raise ApiError(400, "missing_field", f"{name} is required.")
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_field", f"{name} must be a whole number.") from None
    if minimum is not None and value < minimum:
        raise ApiError(400, "bad_field", f"{name} must be at least {minimum}.")
    return value


def _text(data: dict, name: str, *, required: bool = True, upper: bool = False) -> str | None:
    value = str(data.get(name) or "").strip()
    if not value:
        if required:
            raise ApiError(400, "missing_field", f"{name} is required.")
        return None
    return value.upper() if upper else value


def register_response_api(app, token_required, issue_token):
    bp = Blueprint("response_model", __name__, url_prefix="/api/response")

    def endpoint(*allowed, demo_only: bool = False):
        """Decorator: auth, PostgreSQL check, account-type check, JSON conversion, error translation."""
        def decorator(fn):
            def inner(*args, **kwargs):
                if not available():
                    return jsonify(error="The incident-response model needs PostgreSQL; this server is using the SQLite fallback.", code="postgres_required"), 501
                if demo_only and not demo_mode():
                    return jsonify(error="Not found"), 404
                try:
                    with get_pool().connection() as conn:
                        actor = conn.execute("SELECT id, name, email, role, account_type FROM public.users WHERE id = %s", (request.user["id"],)).fetchone()
                    if actor is None:
                        raise ApiError(401, "unknown_user", "Your account no longer exists. Sign in again.")
                    if allowed and actor["account_type"] not in allowed:
                        names = " or ".join(a.replace("_", " ").lower() for a in allowed)
                        article = "an" if names[:1] in "aeiou" else "a"
                        raise ApiError(403, "forbidden", f"This action requires {article} {names} account.")
                    request.actor = actor
                    result = fn(*args, **kwargs)
                    if isinstance(result, Response):
                        return result
                    payload, status = result
                    return jsonify(jsonable(payload)), status
                except Exception as exc:  # noqa: BLE001 - every database exception is translated
                    error = map_error(exc)
                    return jsonify(jsonable(error.body())), error.status
            update_wrapper(inner, fn)
            return token_required(inner)
        return decorator

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def ok(payload: dict, tx, status: int = 200):
        return {**payload, "db_trace": tx.trace()}, status

    # ------------------------------------------------------------------ reference and reads
    @bp.get("/reference")
    @endpoint()
    def reference():
        with get_pool().connection() as conn:
            zones = conn.execute("SELECT id, zone_name, district, risk_level, fn_active_incidents(id) AS active_incidents FROM zones ORDER BY zone_name").fetchall()
            units = conn.execute("SELECT r.id, r.unit_name, r.unit_type, r.availability_status, r.zone_id, r.lead_user_id, u.name AS lead_name "
                                 "FROM response_units r LEFT JOIN users u ON u.id = r.lead_user_id ORDER BY r.unit_name").fetchall()
            resources = conn.execute("SELECT id, resource_name, category, unit_of_measure, quantity_available, reorder_level, fn_stock_status(id) AS stock_status "
                                     "FROM resources ORDER BY resource_name").fetchall()
        return {"zones": zones, "units": units, "resources": resources, "incident_types": INCIDENT_TYPES, "severities": SEVERITIES,
                "me": {k: request.actor[k] for k in ("id", "name", "account_type")}}, 200

    @bp.get("/incidents")
    @endpoint()
    def list_incidents():
        actor = request.actor
        status = request.args.get("status", "").strip().upper() or None
        only_user = actor["id"] if actor["account_type"] == CITIZEN else None     # citizens see only their own reports
        with get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT i.id, i.title, i.incident_type, i.severity, i.status, i.location, i.zone_id, z.zone_name, i.reported_by, "
                "u.name AS reporter, i.created_at, i.updated_at, fn_response_minutes(i.id) AS response_minutes "
                "FROM incidents i LEFT JOIN zones z ON z.id = i.zone_id JOIN users u ON u.id = i.reported_by "
                "WHERE (%(user)s::bigint IS NULL OR i.reported_by = %(user)s::bigint) AND (%(status)s::text IS NULL OR i.status = %(status)s::text) "
                "ORDER BY i.id DESC LIMIT 200", {"user": only_user, "status": status}).fetchall()
        return {"incidents": rows}, 200

    @bp.get("/incidents/<int:incident_id>")
    @endpoint()
    def incident_detail(incident_id: int):
        actor = request.actor
        with get_pool().connection() as conn:
            incident = conn.execute(
                "SELECT i.*, z.zone_name, u.name AS reporter FROM incidents i LEFT JOIN zones z ON z.id = i.zone_id "
                "JOIN users u ON u.id = i.reported_by WHERE i.id = %s", (incident_id,)).fetchone()
            if incident is None or (actor["account_type"] == CITIZEN and incident["reported_by"] != actor["id"]):
                raise ApiError(404, "not_found", "Incident not found.")
            timeline = conn.execute(
                "SELECT t.update_no, t.previous_status, t.new_status, t.note, u.name AS logged_by, t.logged_at "
                "FROM incident_updates t LEFT JOIN users u ON u.id = t.logged_by WHERE t.incident_id = %s ORDER BY t.update_no", (incident_id,)).fetchall()
            dispatches = conn.execute(
                "SELECT d.unit_id, r.unit_name, r.unit_type, r.lead_user_id, d.dispatch_status, d.dispatched_at, d.arrived_at, d.cleared_at, "
                "u.name AS dispatched_by FROM dispatches d JOIN response_units r ON r.id = d.unit_id JOIN users u ON u.id = d.dispatched_by "
                "WHERE d.incident_id = %s ORDER BY d.dispatched_at, d.unit_id", (incident_id,)).fetchall()
            allocations = conn.execute(
                "SELECT a.resource_id, s.resource_name, s.unit_of_measure, a.quantity, a.allocated_at FROM resource_allocations a "
                "JOIN resources s ON s.id = a.resource_id WHERE a.incident_id = %s ORDER BY s.resource_name", (incident_id,)).fetchall()
        return {"incident": incident, "timeline": timeline, "dispatches": dispatches, "allocations": allocations}, 200

    # ------------------------------------------------------------------ T2 report an incident
    @bp.post("/incidents")
    @endpoint()
    def report_incident():
        data = body()
        title, location = _text(data, "title"), _text(data, "location")
        incident_type = _text(data, "incident_type", upper=True)
        description = _text(data, "description", required=False)
        with transaction(request.actor["id"], "Report an incident") as tx:
            row = tx.one("INSERT INTO incidents (title, description, incident_type, location, reported_by) "
                         "VALUES (%s, %s, %s, %s, %s) RETURNING id, title, incident_type, severity, status, location, created_at",
                         (title, description, incident_type, location, request.actor["id"]), writes=[("incidents", "INSERT", None)])
            tx.observe("Incident timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry, min(new_status) AS first_status "
                       "FROM incident_updates WHERE incident_id = %s", (row["id"],), before={"entries": 0})
        return ok({"incident": row}, tx, 201)

    # ------------------------------------------------------------------ T3 verify / reject
    @bp.post("/incidents/<int:incident_id>/verify")
    @endpoint(COORDINATOR)
    def verify(incident_id: int):
        data = body()
        zone_id, severity = _int(data, "zone_id", minimum=1), _text(data, "severity", upper=True)
        note = _text(data, "note", required=False)
        with transaction(request.actor["id"], "Verify an incident", note=note) as tx:
            tx.watch("Incident", "SELECT status, severity, zone_id, updated_at FROM incidents WHERE id = %s", (incident_id,))
            tx.watch("Timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry FROM incident_updates WHERE incident_id = %s", (incident_id,))
            row = tx.one("UPDATE incidents SET status = 'VERIFIED', severity = %s, zone_id = %s WHERE id = %s RETURNING id, status, severity, zone_id",
                         (severity, zone_id, incident_id), writes=[("incidents", "UPDATE", ("status", "severity", "zone_id"))])
            if row is None:
                raise ApiError(404, "not_found", "Incident not found.")
        return ok({"incident": row}, tx)

    @bp.post("/incidents/<int:incident_id>/reject")
    @endpoint(COORDINATOR)
    def reject(incident_id: int):
        note = _text(body(), "note", required=False)
        with transaction(request.actor["id"], "Reject a report", note=note) as tx:
            tx.watch("Incident", "SELECT status, updated_at FROM incidents WHERE id = %s", (incident_id,))
            tx.watch("Timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry FROM incident_updates WHERE incident_id = %s", (incident_id,))
            row = tx.one("UPDATE incidents SET status = 'REJECTED' WHERE id = %s RETURNING id, status",
                         (incident_id,), writes=[("incidents", "UPDATE", ("status",))])
            if row is None:
                raise ApiError(404, "not_found", "Incident not found.")
        return ok({"incident": row}, tx)

    # ------------------------------------------------------------------ T4 dispatch a unit
    @bp.post("/incidents/<int:incident_id>/dispatch")
    @endpoint(COORDINATOR)
    def dispatch(incident_id: int):
        unit_id = _int(body(), "unit_id", minimum=1)
        with transaction(request.actor["id"], "Dispatch a unit") as tx:
            tx.watch("Unit", "SELECT unit_name, availability_status FROM response_units WHERE id = %s", (unit_id,))
            tx.watch("Incident", "SELECT status FROM incidents WHERE id = %s", (incident_id,))
            tx.watch("Timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry FROM incident_updates WHERE incident_id = %s", (incident_id,))
            tx.call("sp_dispatch_unit", (incident_id, unit_id, request.actor["id"]))
        return ok({"dispatched": {"incident_id": incident_id, "unit_id": unit_id}}, tx, 201)

    # ------------------------------------------------------------------ T5 unit progress
    @bp.patch("/dispatches/<int:incident_id>/<int:unit_id>")
    @endpoint()
    def progress(incident_id: int, unit_id: int):
        status = _text(body(), "status", upper=True)
        if status not in PROGRESS:
            raise ApiError(400, "bad_field", "status must be EN_ROUTE, ON_SCENE or COMPLETED.")
        with transaction(request.actor["id"], "Record unit progress") as tx:
            tx.watch("Dispatch", "SELECT dispatch_status, arrived_at, cleared_at FROM dispatches WHERE incident_id = %s AND unit_id = %s", (incident_id, unit_id))
            tx.watch("Unit", "SELECT unit_name, availability_status FROM response_units WHERE id = %s", (unit_id,))
            tx.call("sp_update_dispatch", (incident_id, unit_id, request.actor["id"], status))
        return ok({"dispatch": {"incident_id": incident_id, "unit_id": unit_id, "status": status}}, tx)

    # ------------------------------------------------------------------ T6 allocate relief / T9 withdraw
    @bp.post("/incidents/<int:incident_id>/allocations")
    @endpoint(COORDINATOR)
    def allocate(incident_id: int):
        data = body()
        resource_id, quantity = _int(data, "resource_id", minimum=1), _int(data, "quantity", minimum=1)
        with transaction(request.actor["id"], "Allocate relief") as tx:
            tx.watch("Stock", "SELECT resource_name, quantity_available, fn_stock_status(id) AS stock_status FROM resources WHERE id = %s", (resource_id,))
            tx.watch("Allocation", "SELECT quantity FROM resource_allocations WHERE incident_id = %s AND resource_id = %s", (incident_id, resource_id))
            tx.watch("Timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry FROM incident_updates WHERE incident_id = %s", (incident_id,))
            row = tx.one("INSERT INTO resource_allocations AS ra (incident_id, resource_id, quantity) VALUES (%s, %s, %s) "
                         "ON CONFLICT (incident_id, resource_id) DO UPDATE SET quantity = ra.quantity + EXCLUDED.quantity, allocated_at = now() "
                         "RETURNING incident_id, resource_id, quantity", (incident_id, resource_id, quantity),
                         writes=[("resource_allocations", "INSERT", None), ("resource_allocations", "UPDATE", ("quantity",))])
        return ok({"allocation": row}, tx, 201)

    @bp.delete("/incidents/<int:incident_id>/allocations/<int:resource_id>")
    @endpoint(COORDINATOR)
    def withdraw(incident_id: int, resource_id: int):
        with transaction(request.actor["id"], "Withdraw an allocation") as tx:
            tx.watch("Stock", "SELECT resource_name, quantity_available, fn_stock_status(id) AS stock_status FROM resources WHERE id = %s", (resource_id,))
            tx.watch("Allocation", "SELECT quantity FROM resource_allocations WHERE incident_id = %s AND resource_id = %s", (incident_id, resource_id))
            tx.watch("Timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry FROM incident_updates WHERE incident_id = %s", (incident_id,))
            row = tx.one("DELETE FROM resource_allocations WHERE incident_id = %s AND resource_id = %s RETURNING quantity",
                         (incident_id, resource_id), writes=[("resource_allocations", "DELETE", None)])
            if row is None:
                raise ApiError(404, "not_found", "That allocation does not exist.")
        return ok({"returned": row["quantity"]}, tx)

    # ------------------------------------------------------------------ T7 close an incident
    @bp.post("/incidents/<int:incident_id>/close")
    @endpoint(COORDINATOR)
    def close(incident_id: int):
        note = _text(body(), "note", required=False)
        with transaction(request.actor["id"], "Close an incident") as tx:
            tx.watch("Incident", "SELECT status FROM incidents WHERE id = %s", (incident_id,))
            tx.watch("Active dispatches", "SELECT count(*) AS active FROM dispatches WHERE incident_id = %s AND dispatch_status IN ('ASSIGNED', 'EN_ROUTE', 'ON_SCENE')", (incident_id,))
            tx.watch("Timeline", "SELECT count(*) AS entries, max(update_no) AS last_entry FROM incident_updates WHERE incident_id = %s", (incident_id,))
            tx.call("sp_close_incident", (incident_id, request.actor["id"], note))
        return ok({"closed": incident_id}, tx)

    # ------------------------------------------------------------------ T8 restock
    @bp.post("/resources/<int:resource_id>/restock")
    @endpoint(ADMIN)
    def restock(resource_id: int):
        change = _int(body(), "quantity")
        if change == 0:
            raise ApiError(400, "bad_field", "quantity must not be zero.")
        with transaction(request.actor["id"], "Adjust relief stock") as tx:
            tx.watch("Stock", "SELECT resource_name, quantity_available FROM resources WHERE id = %s", (resource_id,))
            row = tx.one("UPDATE resources SET quantity_available = quantity_available + %s WHERE id = %s RETURNING id, resource_name, quantity_available, reorder_level",
                         (change, resource_id), writes=[("resources", "UPDATE", ("quantity_available",))])
            if row is None:
                raise ApiError(404, "not_found", "Relief item not found.")
            # A STABLE function sees the snapshot taken when the statement that calls it starts.
            # Called inside the UPDATE it would still report the old quantity, so it is read in a
            # separate SELECT after the update, within the same transaction.
            status = tx.one("SELECT fn_stock_status(%s) AS stock_status", (resource_id,), uses=["fn_stock_status"])
        return ok({"resource": {**row, "stock_status": status["stock_status"]}}, tx)

    # ------------------------------------------------------------------ T9 delete an incident
    @bp.delete("/incidents/<int:incident_id>")
    @endpoint(COORDINATOR)
    def delete_incident(incident_id: int):
        with transaction(request.actor["id"], "Delete an incident") as tx:
            tx.watch("Incident", "SELECT status, title FROM incidents WHERE id = %s", (incident_id,))
            tx.watch("Timeline", "SELECT count(*) AS entries FROM incident_updates WHERE incident_id = %s", (incident_id,))
            row = tx.one("DELETE FROM incidents WHERE id = %s RETURNING id",
                         (incident_id,), writes=[("incidents", "DELETE", None), ("incident_updates", "DELETE", None)])
            if row is None:
                raise ApiError(404, "not_found", "Incident not found.")
        return ok({"deleted": incident_id}, tx)

    # ------------------------------------------------------------------ T10 negative demo (demo mode only)
    @bp.post("/debug/edit-timeline")
    @endpoint(ADMIN, demo_only=True)
    def edit_timeline():
        data = body()
        incident_id, update_no = _int(data, "incident_id", minimum=1), _int(data, "update_no", minimum=1)
        note = _text(data, "note")
        with transaction(request.actor["id"], "Attempt to edit the timeline") as tx:
            tx.execute("UPDATE incident_updates SET note = %s WHERE incident_id = %s AND update_no = %s",
                       (note, incident_id, update_no), writes=[("incident_updates", "UPDATE", ("note",))])
        return ok({"edited": True}, tx)

    # ------------------------------------------------------------------ reports
    @bp.get("/reports")
    @endpoint(COORDINATOR, ADMIN, UNIT_LEAD)
    def report_catalogue():
        return {"reports": report_module.catalogue()}, 200

    @bp.get("/reports/<key>")
    @endpoint(COORDINATOR, ADMIN, UNIT_LEAD)
    def run_report(key: str):
        result = report_module.run(key, dict(request.args))
        if request.args.get("format") == "csv":
            name = f"dmers-{result['key']}.csv"
            return Response(report_module.to_csv(result), mimetype="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
        return result, 200

    # ------------------------------------------------------------------ demo support
    @bp.get("/demo/status")
    @endpoint()
    def demo_status():
        return {"demo_mode": demo_mode(), "me": {k: request.actor[k] for k in ("id", "name", "account_type")}}, 200

    @bp.get("/demo/personas")
    @endpoint(ADMIN, demo_only=True)
    def demo_personas():
        with get_pool().connection() as conn:
            rows = conn.execute("SELECT u.id, u.name, u.email, u.account_type, r.id AS leads_unit_id, r.unit_name AS leads_unit "
                                "FROM public.users u LEFT JOIN response_units r ON r.lead_user_id = u.id "
                                "WHERE u.email LIKE ANY (%s) ORDER BY u.id", (DEMO_EMAIL_PATTERNS,)).fetchall()
        return {"personas": rows}, 200

    @bp.post("/demo/token")
    @endpoint(ADMIN, demo_only=True)
    def demo_token():
        user_id = _int(body(), "user_id", minimum=1)
        with get_pool().connection() as conn:
            user = conn.execute("SELECT id, name, email, role FROM public.users WHERE id = %s AND email LIKE ANY (%s)", (user_id, DEMO_EMAIL_PATTERNS)).fetchone()
        if user is None:
            raise ApiError(404, "not_found", "Only demonstration accounts can be used in demo mode.")
        return {"token": issue_token(dict(user)), "user": dict(user)}, 200

    @bp.post("/demo/reset")
    @endpoint(ADMIN, demo_only=True)
    def demo_reset():
        from db.seed import seed, seed_allowed
        if not seed_allowed():
            raise ApiError(403, "seed_disabled", "Demo seeding is disabled (DMERS_ALLOW_DEMO_SEED).")
        return {"reset": seed(reset=True)}, 200

    @bp.get("/health")
    def model_health():
        if not available():
            return jsonify(installed=False, reason="PostgreSQL is required"), 200
        return jsonify(jsonable(response_model_health())), 200

    app.register_blueprint(bp)
