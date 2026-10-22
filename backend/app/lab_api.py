"""Database-laboratory endpoints (``/api/response/lab/*`` and ``/api/response/stream``).

Each laboratory shows something PostgreSQL does for DMERS that application code would otherwise have to
imitate: a hash-chained timeline, row-level security, isolation levels, range-exclusion bookings,
routing and nearest-facility search inside the database, EXPLAIN plans, in-database analytics, a privacy
export and LISTEN/NOTIFY push. The same rules as the rest of the API apply: authorisation by account
type from the database, every write in one transaction with a ``db_trace``, errors translated by
``db.errors``. Laboratory data lives in schemas ``lab`` and ``routing`` (synthetic or reference data).
"""
from __future__ import annotations

import csv
import io
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import psycopg
from flask import Response, request, stream_with_context

from db.errors import ApiError
from db.lab import isolation, optimiser, road_loader
from db.pool import database_url, get_pool
from db.tx import transaction

from .response_api import ADMIN, CITIZEN, COORDINATOR, UNIT_LEAD, _int, _text  # noqa: F401  (CITIZEN kept for symmetry)

IST = timezone(timedelta(hours=5, minutes=30))
BLOCK_RADIUS_M = 35.0          # road_network.HAZARD_PROFILES["block"]["closure"]
MAX_SNAP_M = 800.0
_streams = threading.BoundedSemaphore(int(os.getenv("DMERS_MAX_STREAMS", "6")))


def _moment(data: dict, name: str) -> datetime:
    raw = str(data.get(name) or "").strip()
    if not raw:
        raise ApiError(400, "missing_field", f"{name} is required.")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise ApiError(400, "bad_field", f"{name} must be a date and time such as 2026-11-01T08:00.") from None
    return value if value.tzinfo else value.replace(tzinfo=IST)


def _number(data: dict, name: str, low: float, high: float, default: float | None = None) -> float:
    raw = data.get(name)
    if raw in (None, ""):
        if default is None:
            raise ApiError(400, "missing_field", f"{name} is required.")
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_field", f"{name} must be a number.") from None
    if not low <= value <= high:
        raise ApiError(400, "bad_field", f"{name} must be between {low:g} and {high:g}.")
    return value


def _hazards(data: dict) -> list[dict]:
    items = data.get("hazards") or []
    if not isinstance(items, list) or len(items) > 10:
        raise ApiError(400, "bad_field", "hazards must be a list of at most 10 road blocks.")
    out = []
    for item in items:
        lat, lon = _number(item, "lat", -90, 90), _number(item, "lon", -180, 180)
        out.append({"lat": lat, "lon": lon, "radius_m": BLOCK_RADIUS_M})
    return out


def register_lab_routes(bp, endpoint, body, ok):
    history_hint = "Load the synthetic history first (Query optimiser tab, 'Load synthetic history')."

    def history_loaded(conn) -> int:
        return conn.execute("SELECT count(*) AS n FROM lab.incident_events_flat").fetchone()["n"]

    # ============================================================ 1. tamper-evident timeline
    @bp.get("/lab/chain")
    @endpoint(COORDINATOR, ADMIN)
    def chain_status():
        with get_pool().connection() as conn:
            rows = conn.execute("SELECT * FROM fn_verify_timeline()").fetchall()
            anchors = conn.execute("SELECT count(*) AS anchored, max(anchored_at) AS last_anchored FROM timeline_anchors").fetchone()
        broken = [r for r in rows if not r["intact"]]
        return {"incidents": rows, "incidents_checked": len(rows), "entries_checked": sum(r["entries"] for r in rows),
                "broken": len(broken), "anchors": anchors,
                "how": "Each entry stores SHA-256(previous entry's hash + its own content). fn_verify_timeline() recomputes every hash."}, 200

    @bp.get("/lab/chain/<int:incident_id>")
    @endpoint(COORDINATOR, ADMIN)
    def chain_detail(incident_id: int):
        with get_pool().connection() as conn:
            entries = conn.execute(
                "SELECT u.update_no, u.previous_status, u.new_status, u.note, encode(u.prev_hash, 'hex') AS prev_hash, encode(u.row_hash, 'hex') AS row_hash, "
                "u.row_hash = fn_timeline_hash(u.prev_hash, u.incident_id, u.update_no, u.previous_status, u.new_status, u.note, u.logged_by, u.logged_at) AS content_ok, "
                "u.prev_hash IS NOT DISTINCT FROM lag(u.row_hash) OVER (ORDER BY u.update_no) AS link_ok "
                "FROM incident_updates u WHERE u.incident_id = %s ORDER BY u.update_no", (incident_id,)).fetchall()
        if not entries:
            raise ApiError(404, "not_found", "Incident not found.")
        return {"incident_id": incident_id, "entries": entries}, 200

    @bp.post("/lab/chain/anchor")
    @endpoint(ADMIN)
    def chain_anchor():
        with transaction(request.actor["id"], "Anchor the timeline chains") as tx:
            row = tx.one("SELECT fn_anchor_timelines() AS anchored", writes=[("timeline_anchors", "INSERT", None)], uses=("fn_anchor_timelines",))
        return ok({"anchored": row["anchored"]}, tx)

    def bypass_edit(operation: str):
        data = body()
        incident_id, update_no = _int(data, "incident_id", minimum=1), _int(data, "update_no", minimum=1)
        note = _text(data, "note")[:200]
        try:
            with transaction(request.actor["id"], operation) as tx:
                old = tx.one("SELECT note FROM incident_updates WHERE incident_id = %s AND update_no = %s", (incident_id, update_no), reads=("incident_updates",))
                if old is None:
                    raise ApiError(404, "not_found", "That timeline entry does not exist.")
                tx.execute("SET LOCAL session_replication_role = replica")      # a superuser can switch triggers off: this is the attack
                tx.execute("UPDATE incident_updates SET note = %s WHERE incident_id = %s AND update_no = %s", (note, incident_id, update_no))
        except psycopg.errors.InsufficientPrivilege:
            raise ApiError(403, "needs_superuser", "Bypassing triggers needs a superuser database connection; this connection cannot do it.") from None
        return ok({"incident_id": incident_id, "update_no": update_no, "previous_note": old["note"], "note": note,
                   "warning": "The append-only trigger was bypassed with session_replication_role = replica (superuser only)."}, tx)

    @bp.post("/lab/chain/tamper")
    @endpoint(ADMIN, demo_only=True)
    def chain_tamper():
        return bypass_edit("Tamper with a timeline entry (trigger bypass)")

    @bp.post("/lab/chain/restore")
    @endpoint(ADMIN, demo_only=True)
    def chain_restore():
        return bypass_edit("Restore a timeline entry (trigger bypass)")

    # ============================================================ 2. row-level security
    PROBES = [
        ("Incidents visible", "SELECT count(*) AS n FROM incidents", "rows"),
        ("Timeline entries visible", "SELECT count(*) AS n FROM incident_updates", "rows"),
        ("Dispatches visible", "SELECT count(*) AS n FROM dispatches", "rows"),
        ("Allocations visible", "SELECT count(*) AS n FROM resource_allocations", "rows"),
        ("Read password hashes", "SELECT password FROM public.users LIMIT 1", "rows"),
        ("Change every incident's severity", "UPDATE incidents SET severity = severity", "affected"),
        ("Report an incident as somebody else", "INSERT INTO incidents (title, incident_type, location, reported_by) VALUES ('RLS probe', 'OTHER', 'nowhere', %(other)s)", "affected"),
    ]

    @bp.get("/lab/rls")
    @endpoint(COORDINATOR, ADMIN)
    def rls_probe():
        results = []
        with get_pool().connection() as conn:
            baseline = {label: (conn.execute(sql).fetchone()["n"] if "count(*)" in sql else None) for label, sql, _ in PROBES[:4]}
            people = conn.execute(
                "SELECT DISTINCT ON (u.account_type) u.id, u.name, u.account_type FROM public.users u WHERE u.account_type IS NOT NULL "
                "ORDER BY u.account_type, (SELECT count(*) FROM incidents i WHERE i.reported_by = u.id) DESC, u.id").fetchall()
            others = {p["id"]: next(q["id"] for q in people if q["id"] != p["id"]) for p in people}
            subjects = [{"id": None, "name": "No signed-in user", "account_type": "(none)"}] + [dict(p) for p in people]
            for person in subjects:
                outcomes = []
                with conn.transaction(force_rollback=True):
                    conn.execute("SET LOCAL ROLE dmers_rls")
                    conn.execute("SELECT set_config('dmers.actor_id', %s, true)", (str(person["id"]) if person["id"] else "",))
                    for label, sql, kind in PROBES:
                        try:
                            with conn.transaction():          # a savepoint: one refusal must not abort the rest
                                cursor = conn.execute(sql, {"other": others.get(person["id"], 1)} if "%(other)s" in sql else None)
                                value = cursor.fetchone()["n"] if kind == "rows" and "count(*)" in sql else (cursor.rowcount if kind == "affected" else "returned")
                                outcomes.append({"probe": label, "outcome": value})
                        except psycopg.errors.InsufficientPrivilege as exc:
                            outcomes.append({"probe": label, "outcome": "refused", "sqlstate": exc.sqlstate, "message": (exc.diag.message_primary or "")})
                results.append({"person": person, "outcomes": outcomes})
        return {"owner_baseline": baseline, "subjects": results, "probes": [{"label": p[0], "sql": p[1]} for p in PROBES],
                "how": "Each row ran the SAME SQL after SET LOCAL ROLE dmers_rls and set_config('dmers.actor_id', ...). No WHERE clause names the user: the policies do. Everything was rolled back."}, 200

    # ============================================================ 3. isolation levels
    @bp.get("/lab/isolation/catalog")
    @endpoint(COORDINATOR, ADMIN)
    def isolation_catalog():
        return {"levels": isolation.LEVELS, "scenarios": [{"key": k, **{f: v[f] for f in ("title", "story", "modes", "modes_help")}} for k, v in isolation.CATALOG.items()]}, 200

    @bp.post("/lab/isolation/run")
    @endpoint(COORDINATOR, ADMIN)
    def isolation_run():
        data = body()
        try:
            return isolation.run(str(data.get("scenario", "")), str(data.get("level", "")).upper(), str(data.get("mode") or "naive")), 200
        except ValueError as exc:
            raise ApiError(400, "bad_field", str(exc)) from None

    @bp.get("/lab/isolation/matrix")
    @endpoint(COORDINATOR, ADMIN)
    def isolation_matrix():
        return {"matrix": isolation.matrix(), "levels": isolation.LEVELS}, 200

    # ============================================================ 4. time-range reservations
    @bp.get("/lab/reservations")
    @endpoint(COORDINATOR, UNIT_LEAD, ADMIN)
    def list_reservations():
        unit = _int(dict(request.args), "unit_id", minimum=1, required=False)
        with get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT r.id, r.unit_id, u.unit_name, r.purpose, r.note, lower(r.period) AS starts_at, upper(r.period) AS ends_at, r.status, "
                "b.name AS booked_by FROM unit_reservations r JOIN response_units u ON u.id = r.unit_id JOIN public.users b ON b.id = r.booked_by "
                "WHERE (%(u)s::int IS NULL OR r.unit_id = %(u)s::int) ORDER BY lower(r.period), r.id LIMIT 200", {"u": unit}).fetchall()
        return {"reservations": rows}, 200

    @bp.post("/lab/reservations")
    @endpoint(COORDINATOR, ADMIN)
    def create_reservation():
        data = body()
        unit_id, purpose = _int(data, "unit_id", minimum=1), _text(data, "purpose", upper=True)
        start, end = _moment(data, "starts_at"), _moment(data, "ends_at")
        if end <= start:
            raise ApiError(400, "bad_field", "The end must be after the start.")
        with transaction(request.actor["id"], "Reserve a unit") as tx:
            row = tx.one("INSERT INTO unit_reservations (unit_id, purpose, note, period, booked_by) VALUES (%s, %s, %s, tstzrange(%s, %s, '[)'), %s) "
                         "RETURNING id, unit_id, purpose, status, lower(period) AS starts_at, upper(period) AS ends_at",
                         (unit_id, purpose, _text(data, "note", required=False), start, end, request.actor["id"]), writes=[("unit_reservations", "INSERT", None)])
        return ok({"reservation": row}, tx, 201)

    @bp.post("/lab/reservations/<int:reservation_id>/cancel")
    @endpoint(COORDINATOR, ADMIN)
    def cancel_reservation(reservation_id: int):
        with transaction(request.actor["id"], "Cancel a reservation") as tx:
            tx.watch("Reservation", "SELECT status FROM unit_reservations WHERE id = %s", (reservation_id,))
            row = tx.one("UPDATE unit_reservations SET status = 'CANCELLED' WHERE id = %s RETURNING id, status", (reservation_id,),
                         writes=[("unit_reservations", "UPDATE", ("status",))])
            if row is None:
                raise ApiError(404, "not_found", "Reservation not found.")
        return ok({"reservation": row}, tx)

    @bp.get("/lab/reservations/free")
    @endpoint(COORDINATOR, UNIT_LEAD, ADMIN)
    def free_windows():
        args = dict(request.args)
        unit_id = _int(args, "unit_id", minimum=1)
        start, end = _moment(args, "from"), _moment(args, "to")
        if end <= start or end - start > timedelta(days=62):
            raise ApiError(400, "bad_field", "Choose a range of up to 62 days with the end after the start.")
        with get_pool().connection() as conn:
            rows = conn.execute("SELECT lower(w) AS starts_at, upper(w) AS ends_at FROM fn_unit_free_windows(%s, %s, %s) w", (unit_id, start, end)).fetchall()
        return {"unit_id": unit_id, "free_windows": rows}, 200

    # ============================================================ 5. routing inside the database
    @bp.get("/lab/routing/status")
    @endpoint(COORDINATOR, ADMIN)
    def routing_status():
        with get_pool().connection() as conn:
            counts = road_loader.loaded(conn)
            kinds = conn.execute("SELECT kind, count(*) AS n FROM routing.facilities GROUP BY kind ORDER BY kind").fetchall()
            facilities = conn.execute("SELECT id, kind, name, lat, lon FROM routing.facilities ORDER BY kind, name").fetchall()
        return {**counts, "facility_kinds": kinds, "facilities": facilities, "loaded": counts["nodes"] > 0}, 200

    @bp.post("/lab/routing/load")
    @endpoint(ADMIN)
    def routing_load():
        with transaction(request.actor["id"], "Load the road graph into PostgreSQL") as tx:
            counts = road_loader.load(tx.conn)
        return ok({"loaded": counts}, tx)

    def snap(conn, lat: float, lon: float) -> tuple[int, float]:
        row = conn.execute("SELECT node_id, distance_m FROM routing.fn_nearest_nodes(%s, %s, 1)", (lat, lon)).fetchone()
        if row is None:
            raise ApiError(409, "graph_not_loaded", "Load the road graph into PostgreSQL first.")
        if row["distance_m"] > MAX_SNAP_M:
            raise ApiError(422, "off_network", f"That point is {row['distance_m']:.0f} m from the nearest mapped road (limit {MAX_SNAP_M:.0f} m).")
        return row["node_id"], row["distance_m"]

    @bp.post("/lab/routing/route")
    @endpoint(COORDINATOR, ADMIN)
    def routing_route():
        from . import road_network
        data = body()
        lat_a, lon_a = _number(data, "from_lat", -90, 90), _number(data, "from_lon", -180, 180)
        lat_b, lon_b = _number(data, "to_lat", -90, 90), _number(data, "to_lon", -180, 180)
        hazards = _hazards(data)
        import json
        with get_pool().connection() as conn:
            src, src_m = snap(conn, lat_a, lon_a)
            dst, dst_m = snap(conn, lat_b, lon_b)
            started = time.perf_counter()
            closed = conn.execute("SELECT routing.fn_closed_edges(%s::jsonb) AS ids", (json.dumps(hazards),)).fetchone()["ids"]
            rows = conn.execute("SELECT * FROM routing.fn_route(%s, %s, %s::int[]) ORDER BY step", (src, dst, closed)).fetchall()
            explored = int(conn.execute("SELECT current_setting('routing.last_explored', true) AS n").fetchone()["n"] or 0)
            db_ms = (time.perf_counter() - started) * 1000
            node_ids = [rows[0]["from_node"]] + [r["to_node"] for r in rows] if rows else []
            coords = {r["id"]: [r["lat"], r["lon"]] for r in conn.execute("SELECT id, lat, lon FROM routing.nodes WHERE id = ANY(%s)", (node_ids,)).fetchall()}
            conn.rollback()
        database = {"found": bool(rows) or src == dst, "seconds": round(sum(r["time_s"] for r in rows), 2), "metres": round(sum(r["length_m"] for r in rows), 1),
                    "segments": len(rows), "nodes_explored": explored, "runtime_ms": round(db_ms, 1), "closed_segments": len(closed),
                    "path": [coords[n] for n in node_ids if n in coords]}
        graph = road_network.graph()
        scenario = road_network.Scenario(graph, [{"type": "block", "lat": h["lat"], "lon": h["lon"]} for h in hazards])
        a, _ = graph.snap(lat_a, lon_a)
        b, _ = graph.snap(lat_b, lon_b)
        found = road_network.search(scenario, a, b, "astar", "fastest")
        cost = scenario.costs("fastest")
        python = {"found": found["found"], "seconds": round(sum(cost[e] for e in found["edges"]), 2), "metres": round(sum(graph.length[e] for e in found["edges"]), 1),
                  "segments": len(found["edges"]), "nodes_explored": found["nodes_explored"], "runtime_ms": found["runtime_ms"], "closed_segments": len(scenario.closed)}
        same = database["found"] == python["found"] and (not python["found"] or abs(database["seconds"] - python["seconds"]) < 0.02)
        return {"database": database, "python": python, "same_answer": same, "snapped_m": {"from": round(src_m, 1), "to": round(dst_m, 1)},
                "note": "Both searches minimise travel time and close a segment when a road block lies within 35 m of it. Exposure weighting of fire/flood hazards is Python-only."}, 200

    @bp.post("/lab/routing/nearest")
    @endpoint(COORDINATOR, ADMIN)
    def routing_nearest():
        import json
        data = body()
        lat, lon = _number(data, "lat", -90, 90), _number(data, "lon", -180, 180)
        kind, k = _text(data, "kind"), int(_number(data, "k", 1, 5, 3))
        with get_pool().connection() as conn:
            if not conn.execute("SELECT 1 FROM routing.facilities WHERE kind = %s LIMIT 1", (kind,)).fetchone():
                raise ApiError(404, "not_found", "No facilities of that kind are loaded.")
            snap(conn, lat, lon)
            closed = conn.execute("SELECT routing.fn_closed_edges(%s::jsonb) AS ids", (json.dumps(_hazards(data)),)).fetchone()["ids"]
            rows = conn.execute("SELECT * FROM routing.fn_dispatch_candidates(%s, %s, %s, %s, %s::int[])", (lat, lon, kind, k, closed)).fetchall()
            conn.rollback()
        reordered = bool(rows) and rows[0]["straight_rank"] != 1
        return {"candidates": rows, "straight_line_winner_differs": reordered,
                "note": "Candidates are the k nearest by straight line (GiST KNN); each is then routed by road. The best by road is not always the nearest on the map."}, 200

    # ============================================================ 6. query optimiser
    @bp.get("/lab/query/catalog")
    @endpoint(COORDINATOR, ADMIN)
    def query_catalog():
        with get_pool().connection() as conn:
            return {"experiments": optimiser.catalog(), "status": optimiser.status(conn)}, 200

    @bp.post("/lab/query/load")
    @endpoint(ADMIN)
    def query_load():
        rows = _int(body(), "rows", minimum=1000)
        if rows > 1_000_000:
            raise ApiError(400, "bad_field", "rows must be at most 1,000,000.")
        with transaction(request.actor["id"], "Load synthetic incident history") as tx:
            loaded = tx.one("SELECT lab.fn_load_events(%s) AS rows", (rows,))["rows"]
        return ok({"rows": loaded, "note": "Synthetic data generated inside PostgreSQL; it is not real incident history."}, tx, 201)

    @bp.post("/lab/query/run")
    @endpoint(COORDINATOR, ADMIN)
    def query_run():
        data = body()
        week = None
        if data.get("week_start"):
            try:
                week = date.fromisoformat(str(data["week_start"]))
            except ValueError:
                raise ApiError(400, "bad_field", "week_start must be a date such as 2026-03-02.") from None
        try:
            with get_pool().connection() as conn:
                result = optimiser.run(conn, str(data.get("experiment", "")), str(data.get("variant", "")), zone=_int(data, "zone_id", minimum=1, required=False) or 1, week_start=week)
                conn.rollback()
        except LookupError as exc:
            raise ApiError(409, "no_history", str(exc)) from None
        except ValueError as exc:
            raise ApiError(400, "bad_field", str(exc)) from None
        return result, 200

    # ============================================================ 8. analytics in the database
    @bp.get("/lab/analytics")
    @endpoint(COORDINATOR, ADMIN)
    def analytics():
        args = dict(request.args)
        window = int(_number(args, "window", 7, 60, 14))
        threshold = _number(args, "threshold", 1, 20, 4)
        with get_pool().connection() as conn:
            if not history_loaded(conn):
                raise ApiError(409, "no_history", history_hint)
            spikes = conn.execute(
                "SELECT s.zone_id, coalesce(z.zone_name, 'Zone ' || s.zone_id) AS zone, s.day, s.n, s.trailing_mean, s.trailing_sd, s.z_score "
                "FROM lab.fn_zone_daily_zscores(%s::int, %s::numeric) s LEFT JOIN zones z ON z.id = s.zone_id WHERE s.spike ORDER BY s.z_score DESC LIMIT 25", (window, threshold)).fetchall()
            forecast = conn.execute(
                "SELECT f.*, coalesce(z.zone_name, 'Zone ' || f.zone_id) AS zone FROM lab.fn_zone_forecast(28, 7) f LEFT JOIN zones z ON z.id = f.zone_id ORDER BY f.forecast_horizon_total DESC").fetchall()
        return {"window_days": window, "threshold": threshold, "spikes": spikes, "forecast": forecast,
                "note": "Computed by window functions (avg/stddev over the trailing window) and regr_slope/regr_intercept in PostgreSQL. A z-score threshold flags chance spikes as well as real ones; raise it to be stricter."}, 200

    @bp.get("/lab/analytics/series")
    @endpoint(COORDINATOR, ADMIN)
    def analytics_series():
        args = dict(request.args)
        zone_id, window = _int(args, "zone_id", minimum=1), int(_number(args, "window", 7, 60, 14))
        with get_pool().connection() as conn:
            if not history_loaded(conn):
                raise ApiError(409, "no_history", history_hint)
            rows = conn.execute("SELECT day, n, trailing_mean, z_score, spike FROM lab.fn_zone_daily_zscores(%s::int, %s::numeric) WHERE zone_id = %s ORDER BY day",
                                (window, _number(args, "threshold", 1, 20, 4), zone_id)).fetchall()
        return {"zone_id": zone_id, "series": rows}, 200

    # ============================================================ 9. privacy-safe export
    @bp.get("/lab/privacy")
    @endpoint()
    def privacy_export():
        args = dict(request.args)
        source = args.get("source", "history")
        if source not in ("history", "live"):
            raise ApiError(400, "bad_field", "source must be history or live.")
        k = int(_number(args, "k", 1, 100, 5))
        epsilon = _number(args, "epsilon", 0.05, 10, 0) or None
        seed = _number(args, "seed", -1, 1, 0.0) if args.get("seed") not in (None, "") else None
        is_admin = request.actor["account_type"] == ADMIN
        with get_pool().connection() as conn:
            if source == "history" and not history_loaded(conn):
                raise ApiError(409, "no_history", history_hint)
            rows = conn.execute("SELECT * FROM lab.fn_public_export(%s::text, %s::int, %s::numeric, %s::float8)", (source, k, epsilon, seed)).fetchall()
            conn.rollback()
        released = [r for r in rows if r["released_count"] is not None]
        summary = {"cells": len(rows), "suppressed_cells": len(rows) - len(released),
                   "suppressed_percent": round(100 * (len(rows) - len(released)) / len(rows), 1) if rows else 0.0,
                   "true_total": sum(r["true_count"] for r in rows), "released_total": sum(r["released_count"] for r in released),
                   "mean_abs_error": round(sum(abs(r["released_count"] - r["true_count"]) for r in released) / len(released), 3) if released else None,
                   "k": k, "epsilon": epsilon}
        if args.get("format") == "csv":
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["zone", "incident_type", "month", "count"])
            for r in rows:
                writer.writerow([r["zone_name"], r["incident_type"], r["month"].isoformat(), "" if r["released_count"] is None else r["released_count"]])
            return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="dmers-public-export.csv"', "Cache-Control": "no-store"})
        public = [{k_: v for k_, v in r.items() if is_admin or k_ != "true_count"} for r in rows]
        if not is_admin:
            summary = {k_: v for k_, v in summary.items() if k_ not in ("true_total", "mean_abs_error")}
        return {"rows": public[:400], "row_count": len(rows), "summary": summary, "admin_view": is_admin,
                "method": "Cells below k are suppressed; with epsilon, Laplace noise of scale 1/epsilon is added to each count before the threshold (counting query, sensitivity 1)."}, 200

    # ============================================================ 7. LISTEN / NOTIFY push
    @bp.get("/stream")
    @endpoint(COORDINATOR, UNIT_LEAD, ADMIN)
    def stream():
        if not _streams.acquire(blocking=False):
            raise ApiError(429, "too_many_streams", "Too many live connections on this server. Close another tab and retry.")

        def generate():
            conn = None
            try:
                conn = psycopg.connect(database_url(), autocommit=True)
                conn.execute("LISTEN dmers_events")
                yield "retry: 3000\n\n: connected\n\n"
                while True:
                    for note in conn.notifies(timeout=15):
                        yield f"data: {note.payload}\n\n"
                    yield ": keep-alive\n\n"
            finally:
                if conn is not None:
                    conn.close()
                _streams.release()

        return Response(stream_with_context(generate()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
