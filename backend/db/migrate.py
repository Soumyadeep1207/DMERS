"""Ordered, recorded, idempotent migrations (replaces the old split-on-semicolon runner)."""
from __future__ import annotations

import re
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
LOCK_KEY = 7_424_001  # advisory-lock key: two workers starting together must not race
FILE_PATTERN = re.compile(r"^(\d{3})_[\w-]+\.sql$")


def discover() -> list[tuple[str, Path]]:
    found = [(m.group(1), p) for p in MIGRATIONS_DIR.glob("*.sql") if (m := FILE_PATTERN.match(p.name))]
    return sorted(found)


def apply_pending(url: str) -> list[str]:
    """Apply every migration not yet recorded in schema_migrations; return the versions applied."""
    applied_now: list[str] = []
    with psycopg.connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                          version TEXT PRIMARY KEY, description TEXT NOT NULL,
                          applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, path in discover():
            if version in done:
                continue
            # Each file is executed whole: PL/pgSQL bodies contain semicolons, so it is never split.
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations(version, description) VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                         (version, path.stem))
            applied_now.append(version)
    return applied_now


def applied_versions(conn) -> list[str]:
    try:
        return [row["version"] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return []
