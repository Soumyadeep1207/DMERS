import sqlite3
from app import database

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
