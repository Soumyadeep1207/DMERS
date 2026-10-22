"""The merged AI advisory layer on PostgreSQL: both request shapes of /api/ai/assess, the audit tables written by
migration 004, authorisation, and that the AI layer never changes operational records."""
from __future__ import annotations

import psycopg

from tests.conftest import Api, scalar


def admin(app):
    return Api(app, "admin@rescue.ai", "Admin@123")


def test_ai_tables_exist_after_migrations(pg_url):
    assert scalar(pg_url, "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ai_assessments','ai_feedback')") == 2
    assert "004" in [r[0] for r in psycopg.connect(pg_url).execute("SELECT version FROM schema_migrations").fetchall()]


def test_assess_serves_both_request_shapes(pg_app, pg_url):
    api = admin(pg_app)
    made = api.post("/api/incidents", json={"disasterType": "flood", "severity": "high", "description": "water rising", "location": {"label": "Bridge"}})
    iid = made.get_json()["id"]
    by_incident = api.post("/api/ai/assess", json={"incident_id": iid})
    assert by_incident.status_code == 200 and "priority" in by_incident.get_json() and "risk" in by_incident.get_json()     # the Review III advisory
    by_text = api.post("/api/ai/assess", json={"description": "Flood water is rising around the bridge", "type": "flood", "severity": "high"})
    assert by_text.status_code == 200, by_text.get_json()
    body = by_text.get_json()
    assert isinstance(body.get("assessment_id"), int)                                               # the AI layer's own advisory, audited
    assert scalar(pg_url, "SELECT count(*) FROM ai_assessments WHERE kind = 'assessment'") == 1
    assert api.post("/api/ai/assess", json={"incident_id": "bad"}).status_code == 400
    assert api.post("/api/ai/assess", json={"incident_id": 99999}).status_code == 404


def test_ai_endpoints_persist_json_and_feedback_on_postgres(pg_app, pg_url):
    api = admin(pg_app)
    r = api.post("/api/ai/classify", json={"description": "Flood water is rising around the bridge"})
    assert r.status_code == 200 and r.get_json()["value"] == "flood"
    stored = scalar(pg_url, "SELECT output_json->>'value' FROM ai_assessments WHERE id = %s", (r.get_json()["assessment_id"],))
    assert stored == "flood"                                                                         # real JSONB, queryable
    f = api.post("/api/ai/feedback", json={"assessment_id": r.get_json()["assessment_id"], "action": "accepted", "note": "ok"})
    assert f.status_code == 201
    assert scalar(pg_url, "SELECT count(*) FROM ai_feedback") == 1
    assert api.post("/api/ai/feedback", json={"assessment_id": r.get_json()["assessment_id"], "action": "bogus"}).status_code == 400


def test_ai_authorisation_and_free_text_role_check(pg_app, people):
    anon = pg_app.test_client()
    assert anon.post("/api/ai/assess", json={"description": "flood"}).status_code == 401
    assert anon.post("/api/ai/classify", json={"description": "flood"}).status_code == 401
    citizen = people["citizen"]                                                                       # CITIZEN account: no free-text advisory
    assert citizen.post("/api/ai/assess", json={"description": "Flood near the river"}).status_code == 403
    assert citizen.post("/api/ai/classify", json={"description": "Flood near the river"}).status_code == 403


def test_the_ai_layer_never_changes_operational_records(pg_app, pg_url):
    api = admin(pg_app)
    before = [scalar(pg_url, f"SELECT count(*) FROM {t}") for t in ("incidents", "rescue_teams", "hospitals", "missions", "users")]
    api.post("/api/ai/assess", json={"description": "Fire in a warehouse", "severity": "high"})
    api.get("/api/ai/forecast?days=3")
    assert [scalar(pg_url, f"SELECT count(*) FROM {t}") for t in ("incidents", "rescue_teams", "hospitals", "missions", "users")] == before
