"""Review III: migration 002, the ten transactions (success and rolled-back failure), authorisation,
trace honesty, concurrency and regression of the existing endpoints, on a real PostgreSQL 16."""
from __future__ import annotations

import filecmp
import threading
from pathlib import Path

import psycopg
import pytest

from tests.conftest import Api, PEOPLE, scalar

BACKEND = Path(__file__).resolve().parents[1]
BASE = "/api/response"


def ids(api):
    ref = api.get(f"{BASE}/reference").get_json()
    unit = {u["unit_name"]: u for u in ref["units"]}
    res = {r["resource_name"]: r for r in ref["resources"]}
    zone = {z["zone_name"]: z["id"] for z in ref["zones"]}
    return unit, res, zone


def new_incident(citizen, title="Smoke near the fort"):
    r = citizen.post(f"{BASE}/incidents", json={"title": title, "incident_type": "FIRE", "location": "Fort Road"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["incident"]["id"]


def count(url, table, where="true", params=()):
    return scalar(url, f"SELECT count(*) FROM response.{table} WHERE {where}", params)   # table names are test constants


# ------------------------------------------------------------------ migration and regression
def test_review2_sql_copies_are_identical():
    a, b = BACKEND.parent / "docs" / "review2" / "sql", BACKEND / "db" / "review2"
    for name in ("01_schema.sql", "02_plpgsql.sql", "03_seed_data.sql", "05_queries.sql", "run_all.sql"):
        assert filecmp.cmp(a / name, b / name, shallow=False), name


def test_migration_002_on_a_database_with_existing_rows(pg_admin_url):
    from db import migrate
    from db.pool import close_pool
    name = "dmers_mig_" + __import__("uuid").uuid4().hex[:8]
    with psycopg.connect(pg_admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = pg_admin_url.rsplit("/", 1)[0] + "/" + name
    try:
        with psycopg.connect(url) as conn:
            conn.execute((migrate.MIGRATIONS_DIR / "001_initial_postgresql.sql").read_text(encoding="utf-8"))
            conn.cursor().executemany("INSERT INTO roles(name) VALUES (%s)", [(r,) for r in ("admin", "official", "responder", "volunteer", "citizen")])
            conn.execute("INSERT INTO users(name,email,password,role) VALUES ('A','a@x.org','h','admin'),('O','o@x.org','h','official'),('R','r@x.org','h','responder'),('V','v@x.org','h','volunteer'),('C','c@x.org','h','citizen')")
            loc = conn.execute("INSERT INTO locations(label) VALUES ('Old place') RETURNING id").fetchone()[0]
            conn.execute("INSERT INTO incidents(reference,disaster_type,severity,description,location_id) VALUES ('INC-OLD','flood','high','kept',%s)", (loc,))
        applied = migrate.apply_pending(url)
        assert "002" in applied and migrate.apply_pending(url) == []          # recorded, second run is a no-op
        with psycopg.connect(url) as conn:
            conn.execute((migrate.MIGRATIONS_DIR / "002_incident_response.sql").read_text(encoding="utf-8"))   # idempotent re-run
            assert conn.execute("SELECT reference, severity FROM public.incidents").fetchall() == [("INC-OLD", "high")]
            mapping = dict(conn.execute("SELECT role, account_type FROM users").fetchall())
            assert mapping == {"admin": "ADMINISTRATOR", "official": "COORDINATOR", "responder": "UNIT_LEAD", "volunteer": "CITIZEN", "citizen": "CITIZEN"}
            assert conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='response'").fetchone()[0] == 7
    finally:
        close_pool()
        with psycopg.connect(pg_admin_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_existing_endpoints_unchanged_on_postgres(pg_app):
    c = pg_app.test_client()
    health = c.get("/health").get_json()
    assert {"status", "backend", "database", "review2_database"} <= set(health) and health["status"] == "ok"
    assert health["response_model"]["installed"] and health["response_model"]["migration_level"] == "002" and health["response_model"]["ok"]
    assert health["response_model"]["row_counts"]["incidents"] == 14
    reg = c.post("/api/auth/register", json={"name": "New Person", "email": "new.person@example.org", "password": "secret1", "role": "volunteer"})
    assert reg.status_code == 201 and {"token", "user"} <= set(reg.get_json()) and "password" not in reg.get_json()["user"]
    assert reg.get_json()["db_trace"]["effects"][0]["after"]["account_type"] == "CITIZEN"
    dup = c.post("/api/auth/register", json={"name": "New Person", "email": "new.person@example.org", "password": "secret1"})
    assert dup.status_code == 409 and "already registered" in dup.get_json()["error"] and dup.get_json()["db_trace"]["rolled_back"]
    assert c.post("/api/auth/login", json={"email": "new.person@example.org", "password": "wrong"}).status_code == 401
    admin = Api(pg_app, "admin@rescue.ai", "Admin@123")
    made = admin.post("/api/incidents", json={"disasterType": "flood", "severity": "high", "description": "legacy report", "location": {"label": "Bridge"}})
    assert made.status_code == 201
    assert any(i["reference"] == made.get_json()["reference"] for i in admin.get("/api/incidents").get_json()["incidents"])
    patched = admin.patch(f"/api/incidents/{made.get_json()['id']}", json={"status": "verified", "severity": "high"})
    assert patched.status_code == 200      # the legacy table has no zone rule: unchanged behaviour
    assert c.post("/api/public/reports", json={"kind": "Fire", "description": "public report text", "location": {"label": "Market"}}).status_code == 201


def test_account_types_are_derived_and_constrained(pg_url):
    with psycopg.connect(pg_url) as conn:
        with pytest.raises(psycopg.errors.GeneratedAlways):
            conn.execute("UPDATE users SET account_type = 'ADMINISTRATOR' WHERE id = 1")


# ------------------------------------------------------------------ T1 .. T10, success and rollback
def test_full_incident_life_cycle(people, pg_url):
    citizen, coord, lead, admin = (people[k] for k in ("citizen", "coordinator", "lead", "admin"))
    unit, res, zone = ids(coord)
    iid = new_incident(citizen)
    assert count(pg_url, "incident_updates", "incident_id = %s", (iid,)) == 1                    # trigger T1 wrote entry 1
    v = coord.post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": zone["Vellore Town"], "severity": "HIGH", "note": "Confirmed"})
    assert v.status_code == 200 and "trigger trg_incidents_timeline" in v.get_json()["db_trace"]["components"]
    assert scalar(pg_url, "SELECT note FROM response.incident_updates WHERE incident_id=%s AND update_no=2", (iid,)) == "Confirmed"
    assert scalar(pg_url, "SELECT logged_by FROM response.incident_updates WHERE incident_id=%s AND update_no=2", (iid,)) == coord.user["id"]
    d = coord.post(f"{BASE}/incidents/{iid}/dispatch", json={"unit_id": unit["Katpadi Fire Unit"]["id"]})
    assert d.status_code == 201
    trace = d.get_json()["db_trace"]
    assert trace["components"][:2] == ["CALL sp_dispatch_unit", "trigger trg_dispatches_guard"] and any("dispatched to incident" in n for n in trace["notices"])
    assert scalar(pg_url, "SELECT status FROM response.incidents WHERE id=%s", (iid,)) == "RESPONDING"
    uid = unit["Katpadi Fire Unit"]["id"]
    for status in ("EN_ROUTE", "ON_SCENE"):
        assert lead.patch(f"{BASE}/dispatches/{iid}/{uid}", json={"status": status}).status_code == 200
    a1 = coord.post(f"{BASE}/incidents/{iid}/allocations", json={"resource_id": res["Blankets"]["id"], "quantity": 30})
    a2 = coord.post(f"{BASE}/incidents/{iid}/allocations", json={"resource_id": res["Blankets"]["id"], "quantity": 20})
    assert a1.status_code == a2.status_code == 201 and a2.get_json()["allocation"]["quantity"] == 50   # cumulative upsert
    assert scalar(pg_url, "SELECT quantity_available FROM response.resources WHERE id=%s", (res["Blankets"]["id"],)) == res["Blankets"]["quantity_available"] - 50
    w = coord.delete(f"{BASE}/incidents/{iid}/allocations/{res['Blankets']['id']}")
    assert w.status_code == 200 and scalar(pg_url, "SELECT quantity_available FROM response.resources WHERE id=%s", (res["Blankets"]["id"],)) == res["Blankets"]["quantity_available"]
    c = coord.post(f"{BASE}/incidents/{iid}/close", json={"note": "Fire out"})
    assert c.status_code == 200 and "cursor c_open" in c.get_json()["db_trace"]["components"]
    assert any("Unit" in n and "released" in n for n in c.get_json()["db_trace"]["notices"])
    assert scalar(pg_url, "SELECT availability_status FROM response.response_units WHERE id=%s", (uid,)) == "AVAILABLE"
    assert scalar(pg_url, "SELECT status FROM response.incidents WHERE id=%s", (iid,)) == "CLOSED"
    r = admin.post(f"{BASE}/resources/{res['Blankets']['id']}/restock", json={"quantity": 500})
    assert r.status_code == 200 and r.get_json()["resource"]["stock_status"] == "ADEQUATE" and "function fn_stock_status" in r.get_json()["db_trace"]["components"]


@pytest.mark.parametrize("case", ["unverified_dispatch", "busy_unit", "citizen_dispatch", "wrong_lead", "skip_state", "over_allocate", "negative_stock",
                                  "restricted_delete", "illegal_transition", "append_only", "bad_zone", "duplicate_email"])
def test_failure_paths_roll_everything_back(case, people, pg_url, pg_app):
    citizen, coord, lead, admin = (people[k] for k in ("citizen", "coordinator", "lead", "admin"))
    unit, res, zone = ids(coord)
    iid = new_incident(citizen)
    snapshot = lambda: [scalar(pg_url, f"SELECT count(*) FROM response.{t}") for t in ("incidents", "incident_updates", "dispatches", "resource_allocations")] + \
                       [scalar(pg_url, "SELECT sum(quantity_available) FROM response.resources"), scalar(pg_url, "SELECT count(*) FROM response.response_units WHERE availability_status='AVAILABLE'")]
    if case in ("busy_unit", "skip_state", "wrong_lead", "over_allocate", "illegal_transition"):
        coord.post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": zone["Vellore Town"], "severity": "LOW"})
    before = snapshot()
    calls = {
        "unverified_dispatch": (400 + 22, lambda: coord.post(f"{BASE}/incidents/{iid}/dispatch", json={"unit_id": unit["Katpadi Fire Unit"]["id"]})),
        "busy_unit": (422, lambda: coord.post(f"{BASE}/incidents/{iid}/dispatch", json={"unit_id": unit["SDRF Team Alpha"]["id"]})),
        "citizen_dispatch": (403, lambda: citizen.post(f"{BASE}/incidents/{iid}/dispatch", json={"unit_id": unit["Katpadi Fire Unit"]["id"]})),
        "wrong_lead": (422, lambda: lead.patch(f"{BASE}/dispatches/7/{unit['SDRF Team Alpha']['id']}", json={"status": "EN_ROUTE"})),
        "skip_state": (422, lambda: lead.patch(f"{BASE}/dispatches/11/{unit['Vellore Fire and Rescue']['id']}", json={"status": "COMPLETED"})),
        "over_allocate": (422, lambda: coord.post(f"{BASE}/incidents/{iid}/allocations", json={"resource_id": res["Inflatable rescue boats"]["id"], "quantity": 1})),
        "negative_stock": (422, lambda: admin.post(f"{BASE}/resources/{res['Blankets']['id']}/restock", json={"quantity": -10_000_000})),
        "restricted_delete": (409, lambda: coord.delete(f"{BASE}/incidents/1")),
        "illegal_transition": (422, lambda: coord.post(f"{BASE}/incidents/{iid}/reject", json={})),
        "append_only": (422, lambda: admin.post(f"{BASE}/debug/edit-timeline", json={"incident_id": 1, "update_no": 1, "note": "x"})),
        "bad_zone": (422, lambda: coord.post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": 9999, "severity": "HIGH"})),
        "duplicate_email": (409, lambda: pg_app.test_client().post("/api/auth/register", json={"name": "X", "email": PEOPLE["citizen"], "password": "secret1"})),
    }
    expected, call = calls[case]
    response = call()
    if case == "unverified_dispatch":
        expected = 422
    assert response.status_code == expected, (case, response.get_json())
    assert snapshot() == before                                  # nothing partial remains
    body = response.get_json()
    if response.status_code != 403:
        assert body.get("db_trace", {}).get("rolled_back") is True or case == "duplicate_email"
    assert "Traceback" not in str(body) and "psycopg" not in str(body)    # nothing raw leaks


def test_constraint_names_are_reported(people):
    unit, res, zone = ids(people["coordinator"])
    iid = new_incident(people["citizen"])
    r = people["coordinator"].post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": 9999, "severity": "HIGH"})
    assert r.get_json()["constraint"] == "fk_incidents_zone"
    r = people["admin"].post(f"{BASE}/resources/{res['Blankets']['id']}/restock", json={"quantity": -10_000_000})
    assert r.get_json()["constraint"] == "ck_resources_quantity" and r.status_code == 422


def test_failed_trace_lists_only_what_ran(people):
    unit, _, _ = ids(people["coordinator"])
    iid = new_incident(people["citizen"])
    people["coordinator"].post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": 1, "severity": "LOW"})
    r = people["coordinator"].post(f"{BASE}/incidents/{iid}/dispatch", json={"unit_id": unit["SDRF Team Alpha"]["id"]})
    t = r.get_json()["db_trace"]
    assert t["components"] == ["CALL sp_dispatch_unit", "trigger trg_dispatches_guard"]       # the timeline trigger never ran
    assert all(e.get("unchanged") for e in t["effects"]) and t["rows_affected"] == 0 and t["failure"]["sqlstate"] == "P0001"


def test_trace_matches_catalogue(pg_url, pg_app):
    from db.pool import get_pool
    from db import trace
    with get_pool().connection() as conn:
        assert trace.verify_manifest(conn) == []
        names = {t.name for t in trace.load(conn)}
    assert names == {"trg_incidents_timeline", "trg_incidents_touch", "trg_dispatches_guard", "trg_allocations_stock",
                     "trg_incident_updates_append_only", "trg_incidents_transition_guard"}


# ------------------------------------------------------------------ authorisation and exposure
def test_roles_are_enforced_on_the_server(people, pg_app):
    unit, res, zone = ids(people["coordinator"])
    iid = new_incident(people["citizen"])
    assert people["citizen"].post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": 1, "severity": "LOW"}).status_code == 403
    assert people["lead"].post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": 1, "severity": "LOW"}).status_code == 403
    assert people["coordinator"].post(f"{BASE}/resources/{res['Blankets']['id']}/restock", json={"quantity": 5}).status_code == 403
    assert people["citizen"].get(f"{BASE}/reports").status_code == 403
    assert pg_app.test_client().get(f"{BASE}/incidents").status_code == 401
    mine = people["citizen"].get(f"{BASE}/incidents").get_json()["incidents"]
    assert mine and all(i["reported_by"] == people["citizen"].user["id"] for i in mine)
    other = next(i for i in people["coordinator"].get(f"{BASE}/incidents").get_json()["incidents"] if i["reported_by"] != people["citizen"].user["id"])
    assert people["citizen"].get(f"{BASE}/incidents/{other['id']}").status_code == 404        # not theirs: hidden, not forbidden


def test_demo_endpoints_are_gated(people, pg_app, monkeypatch):
    assert people["admin"].get(f"{BASE}/demo/personas").status_code == 200
    assert people["coordinator"].get(f"{BASE}/demo/personas").status_code == 403
    monkeypatch.delenv("DMERS_DEMO_MODE")
    assert people["admin"].get(f"{BASE}/demo/personas").status_code == 404
    assert people["admin"].post(f"{BASE}/debug/edit-timeline", json={"incident_id": 1, "update_no": 1, "note": "x"}).status_code == 404


def test_sql_injection_text_is_stored_literally(people, pg_url):
    evil = "x'); DROP TABLE response.incidents; --"
    iid = new_incident(people["citizen"], title=evil[:100])
    assert scalar(pg_url, "SELECT title FROM response.incidents WHERE id=%s", (iid,)) == evil[:100]
    assert count(pg_url, "incidents") >= 15


def test_seed_is_guarded_and_matches_review2(pg_url, monkeypatch):
    from db.seed import REVIEW2_COUNTS, seed
    for table, expected in REVIEW2_COUNTS.items():
        assert count(pg_url, table) == expected, table
    with pytest.raises(RuntimeError):
        seed()                                                    # already populated
    monkeypatch.delenv("DMERS_ALLOW_DEMO_SEED")
    with pytest.raises(PermissionError):
        seed(reset=True)


def test_demo_reset_restores_data(people, pg_url):
    iid = new_incident(people["citizen"])
    assert count(pg_url, "incidents") == 15
    assert people["admin"].post(f"{BASE}/demo/reset").status_code == 200
    assert count(pg_url, "incidents") == 14
    assert scalar(pg_url, "SELECT count(*) FROM response.incidents WHERE title = 'Smoke near the fort'") == 0


# ------------------------------------------------------------------ concurrency
def test_concurrent_dispatch_of_one_unit_has_exactly_one_winner(pg_app, pg_url):
    coord_a, coord_b = Api(pg_app, PEOPLE["coordinator"]), Api(pg_app, "karthik.raman@dmers.example.org")
    citizen = Api(pg_app, PEOPLE["citizen"])
    unit, _, zone = ids(coord_a)
    first, second = new_incident(citizen, "First"), new_incident(citizen, "Second")
    for i in (first, second):
        assert coord_a.post(f"{BASE}/incidents/{i}/verify", json={"zone_id": 1, "severity": "HIGH"}).status_code == 200
    uid = unit["Katpadi Fire Unit"]["id"]
    barrier, results = threading.Barrier(2), []

    def go(api, incident):
        barrier.wait()
        results.append(api.post(f"{BASE}/incidents/{incident}/dispatch", json={"unit_id": uid}).status_code)

    threads = [threading.Thread(target=go, args=(coord_a, first)), threading.Thread(target=go, args=(coord_b, second))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201, 422], results
    assert count(pg_url, "dispatches", "unit_id = %s AND dispatch_status IN ('ASSIGNED','EN_ROUTE','ON_SCENE')", (uid,)) == 1
