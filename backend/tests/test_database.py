import sqlite3
from app import database
from app.route_advisor import plan_response_route

def test_schema_enforces_incident_foreign_key(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "dmers.db")
    database.init_db()
    with database.connection() as db:
        try:
            db.execute("INSERT INTO incidents(reference,disaster_type,severity,description,location_id) VALUES(?,?,?,?,?)", ("INC-BAD", "flood", "high", "invalid relationship", 99999))
        except sqlite3.IntegrityError:
            return
    assert False, "foreign keys must reject an incident without a location"

def test_seeded_relational_data(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "dmers.db")
    database.init_db()
    with database.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rescue_teams").fetchone()[0] >= 3
        assert db.execute("SELECT available_beds FROM hospitals").fetchone()[0] >= 0

def test_legacy_sqlite_missions_upgrade_preserves_existing_rows(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE missions (id INTEGER PRIMARY KEY, report_id TEXT NOT NULL, team_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'assigned', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, assigned_by INTEGER)")
        legacy.execute("INSERT INTO missions(report_id,team_name) VALUES(?,?)", ("SOS-OLD-1", "Rescue Team A"))
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    with database.connection() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(missions)")}
        assert {"incident_id", "team_id", "hospital_id"} <= columns
        assert db.execute("SELECT report_id,team_name FROM missions WHERE report_id='SOS-OLD-1'").fetchone()[0] == "SOS-OLD-1"

def authenticated_client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "api.db")
    from app.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    response = client.post("/api/auth/login", json={"email": "admin@rescue.ai", "password": "Admin@123"})
    assert response.status_code == 200
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {response.json['token']}"
    return client

def test_data_management_endpoints_show_schema_joins_and_health(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    tables = client.get("/api/data/tables")
    assert tables.status_code == 200
    assert {table["name"] for table in tables.json["tables"]} >= {"incidents", "missions", "hospitals", "audit_entries"}
    health = client.get("/api/data/health")
    assert health.json["connected"] is True
    assert health.json["engine"] == "SQLite offline cache"
    joins = client.get("/api/data/relationships")
    assert any(row["incident_reference"] == "INC-TRAIN-003" and row["team_name"] for row in joins.json["missions"])

def test_incident_crud_persists_location_and_audit_transactionally(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    created = client.post("/api/incidents", json={"disasterType": "Flood", "severity": "critical", "description": "Training incident", "location": {"label": "North bank", "latitude": 12.9, "longitude": 79.1}})
    assert created.status_code == 201
    incident_id = created.json["id"]
    listed = client.get("/api/incidents")
    record = next(row for row in listed.json["incidents"] if row["id"] == incident_id)
    assert record["location"] == "North bank"
    updated = client.patch(f"/api/incidents/{incident_id}", json={"status": "verified", "severity": "high"})
    assert updated.status_code == 200
    audit = client.get("/api/audit")
    assert any(row["subject"] == created.json["reference"] and row["action"] == "INCIDENT_UPDATED" for row in audit.json["entries"])

def test_duplicate_account_registration_returns_json_and_sign_in_guidance(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    response = client.post("/api/auth/register", json={"name": "Duplicate", "email": "admin@rescue.ai", "password": "Training@123"})
    assert response.status_code == 409
    assert "Sign in" in response.json["error"]

def test_explainable_ai_advisory_uses_incident_team_and_hospital_records(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    incident = next(item for item in client.get("/api/incidents").json["incidents"] if item["disaster_type"].lower() == "flood")
    before_missions = client.get("/api/data/overview").json["counts"]["missions"]
    response = client.post("/api/ai/assess", json={"incident_id": incident["id"]})
    assert response.status_code == 200
    advisory = response.json
    assert advisory["incident"]["reference"] == incident["reference"]
    assert advisory["priority"]["label"] in {"CRITICAL", "HIGH", "MODERATE", "LOW"}
    assert advisory["risk_factors"]
    assert advisory["team_candidates"][0]["name"] == "Rescue Team B"
    assert advisory["team_candidates"][0]["score"] > advisory["team_candidates"][1]["score"]
    assert advisory["hospital_candidates"][0]["recommended"] is True
    assert any("not a trained" in item for item in advisory["limitations"])
    assert client.get("/api/data/overview").json["counts"]["missions"] == before_missions

def test_explainable_ai_advisory_requires_authentication_and_valid_incident(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "unauthenticated.db")
    from app.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/api/ai/assess", json={"incident_id": 1}).status_code == 401
    authenticated = authenticated_client(tmp_path, monkeypatch)
    assert authenticated.post("/api/ai/assess", json={"incident_id": "bad"}).status_code == 400
    assert authenticated.post("/api/ai/assess", json={"incident_id": 99999}).status_code == 404

def test_public_report_intake_needs_no_login_and_enters_pending_staff_queue(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "public-report.db")
    from app.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    public = app.test_client()
    response = public.post("/api/public/reports", json={
        "kind": "Flooding", "description": "Flood water is entering homes near the east bridge.",
        "location": {"label": "East bridge, Katpadi", "latitude": 12.98, "longitude": 79.14},
        "immediate_danger": True,
    })
    assert response.status_code == 201
    assert response.json["state"] == "pending_review"
    assert response.json["reference"].startswith("PUB-")
    login = public.post("/api/auth/login", json={"email": "admin@rescue.ai", "password": "Admin@123"})
    staff = app.test_client()
    staff.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {login.json['token']}"
    record = next(item for item in staff.get("/api/incidents").json["incidents"] if item["reference"] == response.json["reference"])
    assert record["status"] == "reported"
    assert record["severity"] == "critical"
    assert record["reporter"] is None

def test_public_report_intake_rejects_incomplete_or_invalid_input(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "public-validation.db")
    from app.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    response = app.test_client().post("/api/public/reports", json={"kind": "Other", "description": "Help", "location": {"label": "Vellore"}})
    assert response.status_code == 400

def test_route_advisor_trades_hazard_exposure_against_resource_speed():
    grid = [[1 for _ in range(5)] for _ in range(5)]
    grid[2][1] = 3  # A dangerous shortcut on the direct route.
    grid[1][2] = -1  # A closure must never be used.
    start, targets = (2, 0), [(2, 4)]
    fast = plan_response_route(grid, start, targets, "auto", 1, "high")
    safe = plan_response_route(grid, start, targets, "safer", 4, "critical")
    assert fast["recommended_mode"] == "fastest"
    assert safe["selected_plan"]["hazard_cells"] == 0
    assert fast["selected_plan"]["hazard_cells"] == 1
    assert fast["selected_plan"]["blocked_cells_on_path"] == 0
    assert safe["selected_plan"]["steps"] > fast["selected_plan"]["steps"]
