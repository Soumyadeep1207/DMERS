"""Health information about the Review II model inside the application database."""
from __future__ import annotations

from psycopg import sql

from . import trace as tracing
from .migrate import applied_versions
from .pool import get_pool

TABLES = ("zones", "incidents", "response_units", "resources", "incident_updates", "dispatches", "resource_allocations")
FUNCTIONS = ("fn_stock_status", "fn_active_incidents", "fn_response_minutes")
PROCEDURES = ("sp_dispatch_unit", "sp_close_incident", "sp_update_dispatch")
TRIGGERS = ("trg_incidents_timeline", "trg_incidents_touch", "trg_dispatches_guard", "trg_allocations_stock",
            "trg_incident_updates_append_only", "trg_incidents_transition_guard")
VIEWS = ("v_zone_situation",)


def response_model_health() -> dict:
    with get_pool().connection() as conn:
        versions = applied_versions(conn)
        have_tables = {r["relname"] for r in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='response' AND c.relkind IN ('r','v')")}
        routines = {(r["proname"], r["prokind"]) for r in conn.execute(
            "SELECT p.proname, p.prokind FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='response'")}
        triggers = {r["tgname"] for r in conn.execute(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='response' AND NOT t.tgisinternal")}
        has_account_type = bool(conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='account_type'").fetchone())
        counts = {}
        for table in TABLES:
            if table in have_tables:       # names come from the constant above, composed as identifiers
                counts[table] = conn.execute(sql.SQL("SELECT count(*) AS n FROM response.{}").format(sql.Identifier(table))).fetchone()["n"]
        objects = {
            "tables": {t: t in have_tables for t in TABLES},
            "functions": {f: (f, "f") in routines for f in FUNCTIONS},
            "procedures": {p: (p, "p") in routines for p in PROCEDURES},
            "triggers": {t: t in triggers for t in TRIGGERS},
            "views": {v: v in have_tables for v in VIEWS},
            "users.account_type": has_account_type,
        }
        missing = [f"{kind}:{name}" for kind, group in objects.items() if isinstance(group, dict) for name, ok in group.items() if not ok]
        if not has_account_type:
            missing.append("column:users.account_type")
        problems = tracing.verify_manifest(conn) if not missing else []
    return {
        "installed": not missing, "migration_level": versions[-1] if versions else None, "applied_migrations": versions,
        "row_counts": counts, "objects": objects, "missing": missing, "manifest_problems": problems,
        "ok": not missing and not problems,
    }
