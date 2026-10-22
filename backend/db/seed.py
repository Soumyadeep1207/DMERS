"""Demonstration data for the incident-response model, replayed through the real triggers.

The data (16 people, 12 zones, 12 units, 12 relief items and the 14-incident history of 1-12 October
2026) comes from the Review II generator ``review2/tools/gen_seed.py``: its data section is executed
here, so Review II and Review III cannot drift apart. Each event is replayed as ordinary DML with
explicit timestamps, so the timeline, dispatch-guard, stock and updated_at triggers run exactly as
they do in live operation.

The 16 people become application users (public.users) with the role that maps to their Review II
account type; their password is the Review II demo password. Guard: ``DMERS_ALLOW_DEMO_SEED=1``.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

from .pool import SEARCH_PATH, database_url

GEN_SEED = Path(__file__).resolve().parent / "review2" / "tools" / "gen_seed.py"
ROLE_OF = {"ADMINISTRATOR": "admin", "COORDINATOR": "official", "UNIT_LEAD": "responder", "CITIZEN": "citizen"}
RESPONSE_TABLES = ("resource_allocations", "dispatches", "incident_updates", "resources", "response_units", "incidents", "zones")
TRUNCATE_ALSO = ("unit_reservations", "timeline_anchors")      # dependent lab tables, cleared with the rest on a reset
REVIEW2_COUNTS = {"incidents": 14, "incident_updates": 61, "dispatches": 16, "resource_allocations": 15, "zones": 12, "response_units": 12, "resources": 12}


def demo_password() -> str:
    return os.getenv("DMERS_DEMO_PASSWORD", "Dmers@2026")


def seed_allowed() -> bool:
    return os.getenv("DMERS_ALLOW_DEMO_SEED", "").strip().lower() in {"1", "true", "yes", "on"}


def load_review2_model() -> dict:
    """Execute only the data section of gen_seed.py (everything before it starts writing SQL)."""
    source = GEN_SEED.read_text(encoding="utf-8")
    data_part = source.split("lines = []", 1)[0]
    namespace = {"__file__": str(GEN_SEED), "__name__": "review2_gen_seed"}
    exec(compile(data_part, str(GEN_SEED), "exec"), namespace)      # trusted, repository-owned source
    return namespace


def _ts(value: str) -> str:
    return value + "+05:30"


def reset_response_data(conn) -> None:
    """Remove every response-model row (identity restarts). Application users are kept."""
    tables = sql.SQL(", ").join(sql.SQL("response.{}").format(sql.Identifier(t)) for t in RESPONSE_TABLES + TRUNCATE_ALSO)
    conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(tables))


def seed(reset: bool = False) -> dict:
    if not seed_allowed():
        raise PermissionError("Demo seeding is disabled. Set DMERS_ALLOW_DEMO_SEED=1 to enable it.")
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured; the response model needs PostgreSQL")
    model = load_review2_model()
    password_hash = generate_password_hash(demo_password())
    with psycopg.connect(url, row_factory=dict_row, options=f"-c search_path={SEARCH_PATH}") as conn:
        conn.execute("SET LOCAL TIME ZONE 'Asia/Kolkata'")
        if reset:
            reset_response_data(conn)
        elif conn.execute("SELECT 1 FROM incidents LIMIT 1").fetchone():
            raise RuntimeError("The response model already contains data; run with reset=True to rebuild it.")

        uid: dict[int, int] = {}                       # Review II user number -> application user id
        for number, (name, account_type, email, created) in enumerate(model["USERS"], start=1):
            row = conn.execute("SELECT id FROM public.users WHERE email = %s", (email,)).fetchone()
            if not row:
                row = conn.execute("INSERT INTO public.users (name, email, password, role, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                                   (name, email, password_hash, ROLE_OF[account_type], _ts(created))).fetchone()
            uid[number] = row["id"]

        zone = {n: conn.execute("INSERT INTO zones (zone_name, district, risk_level) VALUES (%s, %s, %s) RETURNING id", z).fetchone()["id"]
                for n, z in enumerate(model["ZONES"], start=1)}
        unit = {}
        for n, (name, kind, phone, people, zone_no, lead_no) in enumerate(model["UNITS"], start=1):
            unit[n] = conn.execute("INSERT INTO response_units (unit_name, unit_type, contact_phone, personnel_count, zone_id, lead_user_id) "
                                   "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                                   (name, kind, phone, people, zone[zone_no], uid[lead_no] if lead_no else None)).fetchone()["id"]
        resource = {n: conn.execute("INSERT INTO resources (resource_name, category, unit_of_measure, quantity_available, reorder_level) "
                                    "VALUES (%s, %s, %s, %s, %s) RETURNING id", r).fetchone()["id"]
                    for n, r in enumerate(model["RESOURCES"], start=1)}

        incident: dict[str, int] = {}
        status_of: dict[int, str] = {}
        actor = None

        def set_actor(number):
            nonlocal actor
            if number != actor:
                conn.execute("SELECT set_config('dmers.actor_id', %s, true)", (str(uid[number]),))
                actor = number

        for ts, _order, kind, args in model["E"]:
            key = args[0]
            if kind == "report":
                reporter, reported_at, title, description, incident_type, location = model["REPORTS"][key]
                incident[key] = conn.execute(
                    "INSERT INTO incidents (title, description, incident_type, location, reported_by, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (title, description, incident_type, location, uid[reporter], _ts(ts), _ts(ts))).fetchone()["id"]
                status_of[incident[key]] = "REPORTED"
                continue
            if kind == "offduty":
                conn.execute("UPDATE response_units SET availability_status = 'OFF_DUTY' WHERE id = %s", (unit[args[0]],))
                continue
            iid = incident[key]
            if kind == "verify":
                who, severity, zone_no = args[1:]
                set_actor(who)
                conn.execute("UPDATE incidents SET status = 'VERIFIED', severity = %s, zone_id = %s, updated_at = %s WHERE id = %s",
                             (severity, zone[zone_no], _ts(ts), iid))
                status_of[iid] = "VERIFIED"
            elif kind == "reject":
                who, note = args[1:]
                set_actor(who)
                conn.execute("SELECT set_config('dmers.note', %s, true)", (note,))
                conn.execute("UPDATE incidents SET status = 'REJECTED', updated_at = %s WHERE id = %s", (_ts(ts), iid))
                conn.execute("SELECT set_config('dmers.note', '', true)")
                status_of[iid] = "REJECTED"
            elif kind == "dispatch":
                unit_no, who = args[1:]
                set_actor(who)
                conn.execute("INSERT INTO dispatches (incident_id, unit_id, dispatched_by, dispatched_at) VALUES (%s, %s, %s, %s)",
                             (iid, unit[unit_no], uid[who], _ts(ts)))
                conn.execute("UPDATE response_units SET availability_status = 'DEPLOYED' WHERE id = %s", (unit[unit_no],))
                if status_of[iid] == "VERIFIED":
                    conn.execute("UPDATE incidents SET status = 'RESPONDING', updated_at = %s WHERE id = %s", (_ts(ts), iid))
                    status_of[iid] = "RESPONDING"
            elif kind == "enroute":
                conn.execute("UPDATE dispatches SET dispatch_status = 'EN_ROUTE' WHERE incident_id = %s AND unit_id = %s", (iid, unit[args[1]]))
            elif kind == "onscene":
                conn.execute("UPDATE dispatches SET dispatch_status = 'ON_SCENE', arrived_at = %s WHERE incident_id = %s AND unit_id = %s",
                             (_ts(ts), iid, unit[args[1]]))
            elif kind in ("complete", "cancel"):
                outcome = "COMPLETED" if kind == "complete" else "CANCELLED"
                conn.execute("UPDATE dispatches SET dispatch_status = %s, cleared_at = %s WHERE incident_id = %s AND unit_id = %s",
                             (outcome, _ts(ts), iid, unit[args[1]]))
                conn.execute("UPDATE response_units SET availability_status = 'AVAILABLE' WHERE id = %s", (unit[args[1]],))
            elif kind == "allocate":
                res_no, quantity, who = args[1:]
                set_actor(who)
                conn.execute("INSERT INTO resource_allocations AS ra (incident_id, resource_id, quantity, allocated_at) VALUES (%s, %s, %s, %s) "
                             "ON CONFLICT (incident_id, resource_id) DO UPDATE SET quantity = ra.quantity + EXCLUDED.quantity, "
                             "allocated_at = EXCLUDED.allocated_at", (iid, resource[res_no], quantity, _ts(ts)))
            elif kind == "status":
                new_status, who = args[1:]
                set_actor(who)
                conn.execute("UPDATE incidents SET status = %s, updated_at = %s WHERE id = %s", (new_status, _ts(ts), iid))
                status_of[iid] = new_status
            else:
                raise ValueError(f"Unknown seed event kind {kind}")

        counts = {t: conn.execute(sql.SQL("SELECT count(*) AS n FROM response.{}").format(sql.Identifier(t))).fetchone()["n"] for t in RESPONSE_TABLES}
    return {"users": len(uid), "counts": counts, "expected_counts": REVIEW2_COUNTS, "password_note": "demo accounts use the Review II demo password"}
