import csv
import io
import time
import zipfile

import jwt

from app import database
from tests.test_database import authenticated_client


def parse(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def test_schema_dictionary_csv_is_detailed_and_safe(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    response = client.get("/api/data/schema.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv" and "attachment" in response.headers["Content-Disposition"]
    rows = parse(response.get_data(as_text=True))
    columns = set(rows[0])
    assert {"table", "column", "data_type", "nullable", "keys", "references", "check_constraint", "business_meaning",
            "sensitivity", "row_count", "null_count", "distinct_values", "min_value", "max_value", "sample_value"} <= columns
    by = {(r["table"], r["column"]): r for r in rows}
    assert by[("incidents", "location_id")]["references"] == "locations.id" and "FK" in by[("incidents", "location_id")]["keys"]
    assert "critical" in by[("incidents", "severity")]["check_constraint"]
    assert by[("users", "password")]["sample_value"] == "[REDACTED]" and by[("users", "password")]["sensitivity"] == "SECRET"
    assert "@" in by[("users", "email")]["sample_value"] and "***" in by[("users", "email")]["sample_value"]
    assert "UNIQUE" in by[("incidents", "reference")]["keys"]
    assert int(by[("incidents", "severity")]["row_count"]) >= 3


def test_relationship_csv_reports_cardinality_and_orphans(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    rows = parse(client.get("/api/data/relationships.csv").get_data(as_text=True))
    link = next(r for r in rows if (r["child_table"], r["child_column"]) == ("incidents", "location_id"))
    assert link["parent_table"] == "locations" and link["participation"].startswith("mandatory")
    assert all(r["integrity"] == "OK" and r["orphan_rows"] == "0" for r in rows)
    optional = next(r for r in rows if (r["child_table"], r["child_column"]) == ("incidents", "reported_by"))
    assert optional["participation"].startswith("optional")


def test_bundle_contains_dictionary_data_and_checksums_without_secrets(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    response = client.get("/api/data/bundle.zip")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    names = set(archive.namelist())
    assert {"00_README.txt", "01_schema_dictionary.csv", "02_relationships.csv", "03_constraints.csv", "checksums.sha256"} <= names
    assert any(name.startswith("data/") and name.endswith("_incidents.csv") for name in names)
    users = archive.read(next(n for n in names if n.endswith("_users.csv"))).decode("utf-8")
    assert "password" not in users.splitlines()[0].lower() and "scrypt" not in users and "pbkdf2" not in users
    assert "admin@rescue.ai" not in users  # masked


def test_export_requires_privileged_role_and_audits(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    assert client.get("/api/data/export.csv?table=incidents").status_code == 200
    assert client.get("/api/data/export.csv?table=sqlite_master").status_code == 400
    with database.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_entries WHERE action='DATA_EXPORTED'").fetchone()[0] >= 1
    anon = client.application.test_client()
    assert anon.get("/api/data/schema.csv").status_code == 401


def test_formula_injection_is_neutralised():
    from app.schema_export import to_csv
    text = to_csv([{"a": "=cmd|' /C calc'!A0", "b": "ok"}])
    assert "'=cmd" in text


def test_tokens_expire(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    secret = client.application.config["SECRET_KEY"]
    expired = jwt.encode({"id": 1, "email": "admin@rescue.ai", "role": "admin", "exp": int(time.time()) - 5}, secret, algorithm="HS256")
    response = client.get("/api/data/tables", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and "expired" in response.json["error"].lower()


def test_map_endpoints_return_road_routes_risk_and_comparison(tmp_path, monkeypatch):
    client = authenticated_client(tmp_path, monkeypatch)
    start, goal = [12.9249, 79.1355], [12.9300, 79.1500]
    route = client.post("/api/map/route", json={"stops": [start, goal], "algorithm": "ASTAR", "mode": "balanced"}).json
    assert route["source"] == "osm-road-graph" and route["risk"]["band"] in {"LOW", "MODERATE", "HIGH", "SEVERE"}
    mid = route["points"][len(route["points"]) // 2]
    blocked = client.post("/api/map/route", json={"stops": [start, goal], "hazards": [{"type": "block", "lat": mid[0], "lon": mid[1]}]}).json
    assert blocked["closures"] and blocked["detour"] is not None
    compare = client.post("/api/map/compare-algorithms", json={"start": start, "goal": goal}).json
    assert set(compare["results"]) == {"bfs", "dfs", "ucs", "greedy", "astar"}
    plan = client.post("/api/map/mission-plan", json={"team": start, "victims": [goal], "hospitals": [{"name": "H", "point": [12.9166, 79.1328], "beds_available": 3}]}).json
    assert plan["plan"]["assignments"][0]["hospital"] == "H"
    assert client.post("/api/map/route", json={"stops": [[0, 0], start]}).status_code == 400
    assert client.get("/api/map/facilities").json["facilities"]
    assert client.get("/api/map/coverage").json["available"] is True
