"""Shared fixtures: disposable PostgreSQL 16 databases for the response-model tests.

A migrated and demo-seeded *template* database is built once per session; every test that needs
PostgreSQL gets its own copy (``CREATE DATABASE ... TEMPLATE``), which is dropped afterwards.
The server is taken from ``TEST_PG_ADMIN_URL`` or, by default, the Docker Compose PostgreSQL
(127.0.0.1:5433, user dmers, password from the project's .env). If it is not reachable the
PostgreSQL tests are skipped, unless ``DMERS_REQUIRE_PG=1`` is set (then they fail).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]


def _admin_url() -> str:
    explicit = os.getenv("TEST_PG_ADMIN_URL", "").strip()
    if explicit:
        return explicit
    env_file = ROOT / ".env"
    password = os.getenv("POSTGRES_PASSWORD", "")
    if not password and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                password = line.split("=", 1)[1].strip()
    return f"postgresql://dmers:{password}@127.0.0.1:5433/postgres"


def _with_db(admin_url: str, name: str) -> str:
    base, _, _ = admin_url.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture(scope="session")
def pg_admin_url():
    url = _admin_url()
    try:
        with psycopg.connect(url, connect_timeout=3, autocommit=True) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as error:
        message = f"PostgreSQL is not reachable for the response-model tests ({type(error).__name__}). Start `docker compose up -d postgres` or set TEST_PG_ADMIN_URL."
        if os.getenv("DMERS_REQUIRE_PG") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return url


def _drop(admin_url: str, name: str) -> None:
    from db.pool import close_pool
    close_pool()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def template_db(pg_admin_url):
    """A database with migrations 001 and 002 applied and the Review II demo data loaded."""
    from db import migrate
    from db.pool import close_pool
    from db.seed import seed
    name = f"dmers_tpl_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _with_db(pg_admin_url, name)
    old = {k: os.environ.get(k) for k in ("DATABASE_URL", "DMERS_ALLOW_DEMO_SEED")}

    def restore():                      # never leave DATABASE_URL set: the SQLite tests must keep seeing SQLite
        for key, value in old.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)

    os.environ["DATABASE_URL"], os.environ["DMERS_ALLOW_DEMO_SEED"] = url, "1"
    try:
        migrate.apply_pending(url)
        with psycopg.connect(url) as conn:           # the roles lookup rows normally written by init_db
            conn.cursor().executemany("INSERT INTO roles(name) VALUES (%s) ON CONFLICT DO NOTHING", [(r,) for r in ("admin", "official", "responder", "volunteer", "citizen")])
        seed()
        close_pool()
    finally:
        restore()
    try:
        yield name
    finally:
        _drop(pg_admin_url, name)


@pytest.fixture
def pg_url(pg_admin_url, template_db, monkeypatch):
    """A private copy of the seeded template for one test."""
    name = f"dmers_t_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(template_db)))
    url = _with_db(pg_admin_url, name)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DMERS_ALLOW_DEMO_SEED", "1")
    monkeypatch.setenv("DMERS_DEMO_MODE", "1")
    monkeypatch.setenv("DMERS_SEED_DEMO_DATA", "true")
    monkeypatch.delenv("COURSE_DATABASE_URL", raising=False)
    yield url
    _drop(pg_admin_url, name)


@pytest.fixture
def pg_app(pg_url):
    from app.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


class Api:
    """Small helper: a Flask test client signed in as one demo person."""

    def __init__(self, app, email, password="Dmers@2026"):
        self.client = app.test_client()
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, (email, response.status_code, response.get_json())
        self.client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {response.get_json()['token']}"
        self.user = response.get_json()["user"]

    def __getattr__(self, verb):
        return getattr(self.client, verb)


PEOPLE = {
    "admin": "meena.krishnan@dmers.example.org",
    "coordinator": "priya.natarajan@dmers.example.org",
    "lead": "divya.ramesh@dmers.example.org",          # leads Katpadi Fire Unit
    "citizen": "gopal.iyer@mail.example.com",
}


@pytest.fixture
def people(pg_app):
    return {role: Api(pg_app, email) for role, email in PEOPLE.items()}


def scalar(url, query, params=()):
    with psycopg.connect(url) as conn:
        row = conn.execute(query, params).fetchone()
        return row[0] if row else None
