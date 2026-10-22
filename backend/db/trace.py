"""Truthful ``db_trace`` support.

For each statement we know which tables it writes; the triggers that fire are read from
``pg_trigger`` (not hard-coded), so the trace can never claim a trigger that does not exist.
Procedures write several tables internally, so ``PROCEDURE_WRITES`` declares those (the design),
and ``verify_manifest`` checks that every name used here exists in the database.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

SCHEMA = "response"
EVENT_BITS = {4: "INSERT", 8: "DELETE", 16: "UPDATE", 32: "TRUNCATE"}

# table, event, columns in the SET clause (None = not relevant)
PROCEDURE_WRITES: dict[str, list[tuple[str, str, tuple[str, ...] | None]]] = {
    "sp_dispatch_unit": [("dispatches", "INSERT", None), ("response_units", "UPDATE", ("availability_status",)), ("incidents", "UPDATE", ("status",))],
    "sp_close_incident": [("dispatches", "UPDATE", ("dispatch_status", "cleared_at")), ("response_units", "UPDATE", ("availability_status",)), ("incidents", "UPDATE", ("status",))],
    "sp_update_dispatch": [("dispatches", "UPDATE", ("dispatch_status", "arrived_at", "cleared_at")), ("response_units", "UPDATE", ("availability_status",))],
}
PROCEDURE_EXTRAS = {"sp_close_incident": ["cursor c_open (FOR UPDATE, WHERE CURRENT OF)"]}

NOTES = {
    "sp_dispatch_unit": "FR-07: only a coordinator dispatches; marks the unit DEPLOYED and the incident RESPONDING.",
    "sp_close_incident": "FR-11: a cursor releases every unit still active at the incident, then RESOLVED and CLOSED.",
    "sp_update_dispatch": "R3-2: only the unit's lead moves ASSIGNED > EN_ROUTE > ON_SCENE > COMPLETED; frees the unit.",
    "fn_stock_status": "BR-10: derived stock status (OUT_OF_STOCK, LOW, ADEQUATE).",
    "fn_active_incidents": "Derived count of VERIFIED or RESPONDING incidents in a zone.",
    "fn_response_minutes": "Minutes from report to first unit arrival.",
    "trg_incidents_timeline": "T1 (FR-03, BR-08): writes a timeline entry on INSERT and on every status change.",
    "trg_incidents_touch": "T2: keeps incidents.updated_at current.",
    "trg_dispatches_guard": "T3 (BR-05): locks the unit row; refuses a unit that is not AVAILABLE or an incident that is not VERIFIED/RESPONDING.",
    "trg_allocations_stock": "T4 (FR-10, BR-07): moves stock, refuses over-allocation, adds a timeline note.",
    "trg_incident_updates_append_only": "T5 (BR-08): timeline entries cannot be edited or deleted directly.",
    "trg_incidents_transition_guard": "R3-1: only legal status transitions are accepted.",
    "trg_units_lead_type": "R3-3 (FR-06): the lead of a unit must hold a UNIT_LEAD account.",
}


@dataclass(frozen=True)
class TriggerInfo:
    name: str
    table: str
    timing: str
    events: frozenset
    columns: frozenset
    function: str = ""

    def fires_for(self, table: str, event: str, set_columns) -> bool:
        if table != self.table or event not in self.events:
            return False
        if event == "UPDATE" and self.columns:       # UPDATE OF col, ...
            return bool(set(set_columns or ()) & self.columns)
        return True

    def label(self) -> str:
        return f"{self.timing} {'/'.join(sorted(self.events))} on {self.table}"


_lock = threading.Lock()
_catalogue: list[TriggerInfo] | None = None
_constraints: dict[str, list[str]] | None = None


def load(conn, force: bool = False) -> list[TriggerInfo]:
    """Read the trigger and constraint catalogue of the response schema (cached)."""
    global _catalogue, _constraints
    with _lock:
        if _catalogue is not None and not force:
            return _catalogue
        rows = conn.execute("""
            SELECT t.tgname AS name, c.relname AS tbl, t.tgtype::int AS tgtype, p.proname AS fn,
                   ARRAY(SELECT a.attname FROM unnest(t.tgattr::int2[]) k
                         JOIN pg_attribute a ON a.attrelid = t.tgrelid AND a.attnum = k) AS cols
              FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_proc p ON p.oid = t.tgfoid
             WHERE n.nspname = %s AND NOT t.tgisinternal ORDER BY c.relname, t.tgname""", (SCHEMA,)).fetchall()
        _catalogue = [TriggerInfo(r["name"], r["tbl"], "BEFORE" if r["tgtype"] & 2 else "AFTER",
                                  frozenset(v for bit, v in EVENT_BITS.items() if r["tgtype"] & bit),
                                  frozenset(r["cols"] or ()), r["fn"]) for r in rows]
        cons = conn.execute("""
            SELECT c.relname AS tbl, k.conname AS name FROM pg_constraint k
              JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %s AND k.contype IN ('c', 'u', 'f', 'p') ORDER BY c.relname, k.conname""", (SCHEMA,)).fetchall()
        _constraints = {}
        for r in cons:
            _constraints.setdefault(r["tbl"], []).append(r["name"])
        return _catalogue


def static_trace(operation: str, *, tables, statements, constraints=(), components=(), rows_affected=0, effects=(), outcome="committed", duration_ms=0.0) -> dict:
    """A db_trace for an endpoint whose statements are fixed and known (account registration and sign-in)."""
    return {
        "operation": operation, "outcome": outcome, "tables_touched": list(tables), "components": list(components),
        "component_details": [{"kind": c.split(" ", 1)[0], "name": c.split(" ", 1)[1], "note": None, "fires": None} for c in components],
        "constraints_checked": list(constraints), "statements": list(statements), "statement_status": ["ok" if outcome == "committed" else "failed"] * len(statements),
        "notices": [], "rows_affected": rows_affected, "effects": list(effects), "duration_ms": round(duration_ms, 2), "rolled_back": outcome != "committed",
    }


def reset_cache() -> None:
    global _catalogue, _constraints
    with _lock:
        _catalogue, _constraints = None, None


def triggers_for(conn, table: str, event: str, set_columns=None) -> list[TriggerInfo]:
    found = [t for t in load(conn) if t.fires_for(table, event, set_columns)]
    return sorted(found, key=lambda t: (t.timing != "BEFORE", t.name))   # BEFORE triggers fire first, each group by name


def constraints_for(conn, table: str) -> list[str]:
    load(conn)
    return list((_constraints or {}).get(table, []))


def verify_manifest(conn) -> list[str]:
    """Return problems: manifest entries that name an object missing from the database."""
    problems = []
    known_triggers = {t.name for t in load(conn, force=True)}
    for name in NOTES:
        if name.startswith("trg_") and name not in known_triggers:
            problems.append(f"trigger {name} is documented but missing")
    for proc in PROCEDURE_WRITES:
        row = conn.execute("SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                           "WHERE n.nspname = %s AND p.proname = %s", (SCHEMA, proc)).fetchone()
        if not row:
            problems.append(f"procedure {proc} is declared but missing")
    return problems
