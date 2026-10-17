"""DMERS persistence boundary: PostgreSQL online, SQLite local/offline."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).resolve().parent.parent / "disaster_response.db"
MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "001_initial_postgresql.sql"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'responder' REFERENCES roles(name), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(role IN ('admin','official','responder','volunteer','citizen')));
CREATE TABLE IF NOT EXISTS locations (id INTEGER PRIMARY KEY, label TEXT NOT NULL, latitude REAL, longitude REAL, address TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(latitude IS NULL OR latitude BETWEEN -90 AND 90), CHECK(longitude IS NULL OR longitude BETWEEN -180 AND 180));
CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE, disaster_type TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'reported', description TEXT NOT NULL, location_id INTEGER NOT NULL, reported_by INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(location_id) REFERENCES locations(id), FOREIGN KEY(reported_by) REFERENCES users(id), CHECK(severity IN ('low','moderate','high','critical')), CHECK(status IN ('reported','verified','dispatched','resolved','closed')));
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status); CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity); CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at);
CREATE TABLE IF NOT EXISTS rescue_teams (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, capability TEXT NOT NULL, availability TEXT NOT NULL DEFAULT 'available', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(availability IN ('available','deployed','unavailable')));
CREATE TABLE IF NOT EXISTS hospitals (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, location_id INTEGER, total_beds INTEGER NOT NULL DEFAULT 0, available_beds INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'accepting', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(location_id) REFERENCES locations(id), CHECK(total_beds >= 0), CHECK(available_beds BETWEEN 0 AND total_beds), CHECK(status IN ('accepting','limited','divert')));
CREATE TABLE IF NOT EXISTS partner_profiles (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, portal TEXT NOT NULL CHECK(portal IN ('ngo','dispatch','hospital')), institution TEXT NOT NULL, hospital_id INTEGER REFERENCES hospitals(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK((portal = 'hospital' AND hospital_id IS NOT NULL) OR (portal <> 'hospital' AND hospital_id IS NULL)));
CREATE TABLE IF NOT EXISTS missions (id INTEGER PRIMARY KEY, incident_id INTEGER, report_id TEXT, team_name TEXT, team_id INTEGER, hospital_id INTEGER, status TEXT NOT NULL DEFAULT 'assigned', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, assigned_by INTEGER, FOREIGN KEY(incident_id) REFERENCES incidents(id), FOREIGN KEY(team_id) REFERENCES rescue_teams(id), FOREIGN KEY(hospital_id) REFERENCES hospitals(id), FOREIGN KEY(assigned_by) REFERENCES users(id), CHECK(status IN ('assigned','acknowledged','en_route','on_scene','in_progress','at_hospital','completed','escalated','aborted')));
CREATE TABLE IF NOT EXISTS simulations (id INTEGER PRIMARY KEY, name TEXT NOT NULL, scenario TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, user_id INTEGER, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS audit_entries (id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, subject TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(actor_id) REFERENCES users(id)); CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_entries(created_at);
"""


class CompatRow(dict):
    """Keep SQLite's both-name-and-index row access on PostgreSQL too."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PgResult:
    def __init__(self, cursor):
        self.cursor = cursor
        self._insert_id = None

    @staticmethod
    def _row(row):
        return CompatRow(row) if row is not None else None

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        if self._insert_id is None:
            row = self.fetchone()
            self._insert_id = row["id"] if row else None
        return self._insert_id


class PgConnection:
    dialect = "postgresql"

    def __init__(self, raw):
        self.raw = raw

    @staticmethod
    def _sql(query: str, returning: bool = True) -> str:
        query = query.replace("?", "%s")
        if returning and query.lstrip().upper().startswith("INSERT") and " RETURNING " not in query.upper():
            query = query.rstrip().rstrip(";") + " RETURNING id"
        return query

    def execute(self, query, params=()):
        cursor = self.raw.execute(self._sql(query), params or ())
        return PgResult(cursor)

    def executemany(self, query, params):
        return self.raw.cursor().executemany(self._sql(query, returning=False), params)

    def table_info(self, name):
        return self.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=? ORDER BY ordinal_position", (name,)).fetchall()

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.raw.__exit__(exc_type, exc, traceback)


class SQLiteConnection:
    dialect = "sqlite"

    def __init__(self, raw):
        self.raw = raw

    def execute(self, *args, **kwargs): return self.raw.execute(*args, **kwargs)
    def executemany(self, *args, **kwargs): return self.raw.executemany(*args, **kwargs)
    def executescript(self, *args, **kwargs): return self.raw.executescript(*args, **kwargs)
    def table_info(self, name): return self.raw.execute(f"PRAGMA table_info({name})").fetchall()
    def __enter__(self):
        self.raw.__enter__()
        return self
    def __exit__(self, exc_type, exc, traceback): return self.raw.__exit__(exc_type, exc, traceback)


def using_postgres() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


def review2_connection():
    """Connect to the isolated PostgreSQL database built from Review II SQL."""
    url = os.getenv("COURSE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("COURSE_DATABASE_URL is not configured")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:
        raise RuntimeError("COURSE_DATABASE_URL is set but psycopg is not installed") from error
    return psycopg.connect(url, row_factory=dict_row)


def review2_database_health() -> dict:
    configured = bool(os.getenv("COURSE_DATABASE_URL", "").strip())
    if not configured:
        return {"configured": False, "connected": False, "engine": "PostgreSQL Review II"}
    try:
        with review2_connection() as db:
            db.execute("SELECT 1").fetchone()
        return {"configured": True, "connected": True, "engine": "PostgreSQL Review II"}
    except Exception:
        return {"configured": True, "connected": False, "engine": "PostgreSQL Review II"}


def connection():
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("DATABASE_URL is set but psycopg is not installed") from error
        return PgConnection(psycopg.connect(url, row_factory=dict_row))
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return SQLiteConnection(db)


def is_integrity_error(error: Exception) -> bool:
    if isinstance(error, sqlite3.IntegrityError):
        return True
    try:
        import psycopg
        return isinstance(error, psycopg.IntegrityError)
    except ImportError:
        return False


def init_db() -> None:
    seed_demo_data = os.getenv("DMERS_SEED_DEMO_DATA", "false" if using_postgres() else "true").strip().lower() in {"1", "true", "yes", "on"}
    with connection() as db:
        if using_postgres():
            # The checked-in SQL migration is idempotent and is also mounted into
            # PostgreSQL's init directory by docker-compose.
            migration = "\n".join(line for line in MIGRATION_PATH.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
            for statement in migration.split(";"):
                if statement.strip():
                    db.execute(statement)
            ignore = " ON CONFLICT(name) DO NOTHING"
            db.executemany("INSERT INTO roles(name) VALUES(?)" + ignore, [(r,) for r in ('admin','official','responder','volunteer','citizen')])
        else:
            db.executescript(SCHEMA)
            # Upgrade databases created by the original local-only schema.
            # ALTER TABLE adds nullable FK columns without deleting old missions.
            mission_columns = {row[1] for row in db.execute("PRAGMA table_info(missions)")}
            for column, definition in (
                ("incident_id", "INTEGER REFERENCES incidents(id)"),
                ("team_id", "INTEGER REFERENCES rescue_teams(id)"),
                ("hospital_id", "INTEGER REFERENCES hospitals(id)"),
            ):
                if column not in mission_columns:
                    db.execute(f"ALTER TABLE missions ADD COLUMN {column} {definition}")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_mission_per_incident ON missions(incident_id) WHERE incident_id IS NOT NULL AND status NOT IN ('completed','aborted')")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_mission_per_report ON missions(report_id) WHERE report_id IS NOT NULL AND status NOT IN ('completed','aborted')")
            db.executemany('INSERT OR IGNORE INTO roles(name) VALUES(?)', [(r,) for r in ('admin','official','responder','volunteer','citizen')])
        admin_email = os.getenv("DMERS_BOOTSTRAP_ADMIN_EMAIL", "admin@rescue.ai").strip().lower()
        admin_password = os.getenv("DMERS_BOOTSTRAP_ADMIN_PASSWORD", "")
        if not db.execute('SELECT 1 FROM users WHERE email=?', (admin_email,)).fetchone():
            if admin_password:
                db.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)', ('System Admin',admin_email,generate_password_hash(admin_password),'admin'))
            elif seed_demo_data:
                db.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)', ('System Admin',admin_email,generate_password_hash('Admin@123'),'admin'))
        if seed_demo_data:
            seed_users = [('District Duty Officer','officer@dmers.test','official'),('Field Responder','responder@dmers.test','responder')]
            for name, email, role in seed_users:
                if not db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
                    db.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)', (name,email,generate_password_hash('Training@123'),role))
        if not db.execute('SELECT 1 FROM rescue_teams').fetchone():
            db.executemany('INSERT INTO rescue_teams(name,capability) VALUES(?,?)', [('Rescue Team A','urban rescue'),('Rescue Team B','flood rescue'),('Fire & Rescue Unit','fire and structural rescue'),('Medical Response Unit','medical evacuation')])
        if not db.execute('SELECT 1 FROM hospitals').fetchone():
            loc = db.execute('INSERT INTO locations(label,latitude,longitude,address) VALUES(?,?,?,?)', ('Vellore Government Hospital',12.9165,79.1325,'Vellore')).lastrowid
            db.execute('INSERT INTO hospitals(name,location_id,total_beds,available_beds,status) VALUES(?,?,?,?,?)', ('Vellore Government Hospital',loc,300,84,'accepting'))
        if seed_demo_data and not db.execute('SELECT 1 FROM incidents').fetchone():
            officer_row = db.execute("SELECT id FROM users WHERE email='officer@dmers.test'").fetchone()
            officer = officer_row[0] if officer_row else None
            team = db.execute("SELECT id FROM rescue_teams ORDER BY id LIMIT 1").fetchone()[0]
            hospital = db.execute("SELECT id FROM hospitals ORDER BY id LIMIT 1").fetchone()[0]
            samples = [('INC-TRAIN-001','Flood','critical','reported','Water entering homes near the river.','Katpadi riverbank',12.98,79.14),('INC-TRAIN-002','Road obstruction','high','verified','Debris is blocking the east access road.','East access road',12.93,79.16),('INC-TRAIN-003','Medical emergency','moderate','dispatched','Training record for a medical response.','Vellore central',12.916,79.133)]
            for reference, kind, severity, status, description, label, lat, lon in samples:
                location_id = db.execute('INSERT INTO locations(label,latitude,longitude,address) VALUES(?,?,?,?)', (label,lat,lon,'Vellore district')).lastrowid
                incident_id = db.execute('INSERT INTO incidents(reference,disaster_type,severity,status,description,location_id,reported_by) VALUES(?,?,?,?,?,?,?)', (reference,kind,severity,status,description,location_id,officer)).lastrowid
                if reference == 'INC-TRAIN-003':
                    db.execute('INSERT INTO missions(incident_id,report_id,team_id,team_name,hospital_id,status,assigned_by) VALUES(?,?,?,?,?,?,?)', (incident_id,reference,team,'Rescue Team A',hospital,'assigned',officer))
                db.execute('INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)', (officer,'SEED_INCIDENT',reference,'Deterministic synthetic training record'))


def save_simulation(name: str, scenario: dict, user_id: int | None) -> int:
    with connection() as db:
        return db.execute('INSERT INTO simulations(name,scenario,user_id) VALUES(?,?,?)', (name,json.dumps(scenario),user_id)).lastrowid


def simulations() -> list[dict]:
    with connection() as db:
        return [{**dict(row), 'scenario': json.loads(row['scenario'])} for row in db.execute('SELECT * FROM simulations ORDER BY created_at DESC')]


def database_health() -> dict:
    engine = 'PostgreSQL' if using_postgres() else 'SQLite offline cache'
    try:
        with connection() as db:
            db.execute('SELECT 1').fetchone()
        return {'connected': True, 'engine': engine, 'mode': 'shared' if using_postgres() else 'local'}
    except Exception:
        return {'connected': False, 'engine': engine, 'error': 'Database connection unavailable'}
