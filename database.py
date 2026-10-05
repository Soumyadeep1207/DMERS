"""DMERS persistence boundary.

PostgreSQL is provisioned for the shared deployment; SQLite is deliberately
retained as a local offline cache so field workstations still operate offline.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).resolve().parent.parent / "disaster_response.db"
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'responder', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(role IN ('admin','official','responder','volunteer','citizen')));
CREATE TABLE IF NOT EXISTS locations (id INTEGER PRIMARY KEY, label TEXT NOT NULL, latitude REAL, longitude REAL, address TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(latitude IS NULL OR latitude BETWEEN -90 AND 90), CHECK(longitude IS NULL OR longitude BETWEEN -180 AND 180));
CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE, disaster_type TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'reported', description TEXT NOT NULL, location_id INTEGER NOT NULL, reported_by INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(location_id) REFERENCES locations(id), FOREIGN KEY(reported_by) REFERENCES users(id), CHECK(severity IN ('low','moderate','high','critical')), CHECK(status IN ('reported','verified','dispatched','resolved','closed')));
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status); CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity); CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at);
CREATE TABLE IF NOT EXISTS rescue_teams (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, capability TEXT NOT NULL, availability TEXT NOT NULL DEFAULT 'available', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(availability IN ('available','deployed','unavailable')));
CREATE TABLE IF NOT EXISTS hospitals (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, location_id INTEGER, total_beds INTEGER NOT NULL DEFAULT 0, available_beds INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'accepting', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(location_id) REFERENCES locations(id), CHECK(total_beds >= 0), CHECK(available_beds BETWEEN 0 AND total_beds), CHECK(status IN ('accepting','limited','divert')));
CREATE TABLE IF NOT EXISTS missions (id INTEGER PRIMARY KEY, incident_id INTEGER, report_id TEXT, team_name TEXT, team_id INTEGER, hospital_id INTEGER, status TEXT NOT NULL DEFAULT 'assigned', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, assigned_by INTEGER, FOREIGN KEY(incident_id) REFERENCES incidents(id), FOREIGN KEY(team_id) REFERENCES rescue_teams(id), FOREIGN KEY(hospital_id) REFERENCES hospitals(id), FOREIGN KEY(assigned_by) REFERENCES users(id), CHECK(status IN ('assigned','acknowledged','en_route','on_scene','in_progress','at_hospital','completed','escalated','aborted')));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_mission_per_incident ON missions(incident_id) WHERE incident_id IS NOT NULL AND status NOT IN ('completed','aborted'); CREATE UNIQUE INDEX IF NOT EXISTS one_active_mission_per_report ON missions(report_id) WHERE report_id IS NOT NULL AND status NOT IN ('completed','aborted');
CREATE TABLE IF NOT EXISTS simulations (id INTEGER PRIMARY KEY, name TEXT NOT NULL, scenario TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, user_id INTEGER, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS audit_entries (id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, subject TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(actor_id) REFERENCES users(id)); CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_entries(created_at);
"""

def connection() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row; db.execute("PRAGMA foreign_keys = ON"); return db

def init_db() -> None:
    with connection() as db:
        db.executescript(SCHEMA)
        for role in ('admin','official','responder','volunteer','citizen'): db.execute('INSERT OR IGNORE INTO roles(name) VALUES(?)', (role,))
        if not db.execute("SELECT 1 FROM users WHERE email='admin@rescue.ai'").fetchone(): db.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)', ('System Admin','admin@rescue.ai',generate_password_hash('Admin@123'),'admin'))
        if not db.execute('SELECT 1 FROM rescue_teams').fetchone(): db.executemany('INSERT INTO rescue_teams(name,capability) VALUES(?,?)', [('Rescue Team A','urban rescue'),('Rescue Team B','flood rescue'),('Medical Response Unit','medical evacuation')])
        if not db.execute('SELECT 1 FROM hospitals').fetchone():
            loc = db.execute('INSERT INTO locations(label,latitude,longitude,address) VALUES(?,?,?,?)', ('Vellore Government Hospital',12.9165,79.1325,'Vellore')).lastrowid
            db.execute('INSERT INTO hospitals(name,location_id,total_beds,available_beds,status) VALUES(?,?,?,?,?)', ('Vellore Government Hospital',loc,300,84,'accepting'))

def save_simulation(name: str, scenario: dict, user_id: int | None) -> int:
    with connection() as db: return db.execute('INSERT INTO simulations(name,scenario,user_id) VALUES(?,?,?)', (name,json.dumps(scenario),user_id)).lastrowid
def simulations() -> list[dict]:
    with connection() as db: return [{**dict(row), 'scenario': json.loads(row['scenario'])} for row in db.execute('SELECT * FROM simulations ORDER BY created_at DESC')]
def database_health() -> dict:
    try:
        with connection() as db: db.execute('SELECT 1').fetchone()
        return {'connected': True, 'engine': 'SQLite offline cache', 'mode': 'local'}
    except sqlite3.Error as error: return {'connected': False, 'engine': 'SQLite offline cache', 'error': str(error)}
