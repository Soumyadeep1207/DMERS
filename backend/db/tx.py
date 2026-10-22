"""One database transaction per user operation, with a truthful ``db_trace``.

Usage::

    with transaction(actor_id, "Dispatch a unit") as tx:
        tx.watch("Unit status", "SELECT availability_status FROM response_units WHERE id = %s", (unit_id,))
        tx.call("sp_dispatch_unit", (incident_id, unit_id, actor_id))
    trace = tx.trace()

Inside the block the first statement has already run ``set_config('dmers.actor_id', ..., true)`` so
the triggers record the acting official. Business rules are never checked here: the database
raises, the transaction rolls back, and ``errors.map_error`` translates the exception.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager

from psycopg import sql as psql

from . import trace as tracing
from .pool import get_pool


class NoticeCollector:
    """psycopg notice handler: keeps RAISE NOTICE lines from procedures so they can be returned."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, diag) -> None:
        self.messages.append(diag.message_primary or "")


class Tx:
    def __init__(self, conn, operation: str, notices: NoticeCollector, actor_id):
        self.conn, self.operation, self.notices, self.actor_id = conn, operation, notices, actor_id
        self.statements: list[dict] = []
        self.components: list[str] = []
        self.details: list[dict] = []
        self.tables: list[str] = []
        self.constraints: list[str] = []

        self.effects: list[dict] = []
        self._watches: list[dict] = []
        self.duration_ms = 0.0
        self.outcome = "committed"
        self.failure: dict | None = None
        self.row_changes: dict[str, dict] = {}
        self._baseline = self._xact_stats()
        tracing.load(conn)           # catalogue is read before any statement so failures can still be traced

    # ---- real row counters from PostgreSQL itself ------------------------------------------------
    def _xact_stats(self) -> dict[str, tuple[int, int, int]]:
        """Per-table tuples inserted / updated / deleted by THIS transaction so far (pg_stat_xact_user_tables)."""
        rows = self.conn.execute("SELECT relname, n_tup_ins::int AS ins, n_tup_upd::int AS upd, n_tup_del::int AS del "
                                 "FROM pg_stat_xact_user_tables WHERE schemaname IN ('response', 'public')").fetchall()
        return {r["relname"]: (r["ins"], r["upd"], r["del"]) for r in rows}

    def _count_changes(self) -> None:
        now = self._xact_stats()
        for table, (ins, upd, dele) in now.items():
            b = self._baseline.get(table, (0, 0, 0))
            change = {k: v for k, v in (("inserted", ins - b[0]), ("updated", upd - b[1]), ("deleted", dele - b[2])) if v}
            if change:
                self.row_changes[table] = change
                self._once(self.tables, table)

    # ---- trace bookkeeping -------------------------------------------------------------------
    @staticmethod
    def _once(items: list, value) -> None:
        if value not in items:
            items.append(value)

    def _component(self, kind: str, name: str, fires: str | None = None) -> None:
        label = f"{kind} {name}"
        if label in self.components:
            return
        self.components.append(label)
        self.details.append({"kind": kind, "name": name, "note": tracing.NOTES.get(name), "fires": fires})

    def _planned(self, writes) -> list[tuple[str, str, str | None]]:
        """Triggers (in firing order) that the given writes can fire, read from pg_trigger."""
        out = []
        for table, event, columns in writes:
            self._once(self.tables, table)
            for name in tracing.constraints_for(self.conn, table):
                self._once(self.constraints, name)
            for trig in tracing.triggers_for(self.conn, table, event, columns):
                out.append(("trigger", trig.name, trig.label()))
        return out

    def _reached_after_failure(self, planned, exc, call) -> list[tuple[str, str, str | None]]:
        """Only what really ran before the error: derived from the PL/pgSQL call stack, never assumed."""
        context = getattr(getattr(exc, "diag", None), "context", None) or ""
        functions = re.findall(r"PL/pgSQL function (\w+)\(", context)
        by_function = {t.function: t.name for t in tracing.load(self.conn)}
        reached = [("trigger", by_function[f], None) for f in functions if f in by_function]
        if functions and not reached and not call:
            reached = []
        failing_trigger = reached[0][1] if reached else None
        if not call and failing_trigger is None:
            # a constraint or type error: BEFORE triggers had already run, AFTER triggers had not
            before = {t.name for t in tracing.load(self.conn) if t.timing == "BEFORE"}
            return [p for p in planned if p[1] in before]
        if not call:
            names = [p[1] for p in planned]
            cut = names.index(failing_trigger) + 1 if failing_trigger in names else len(planned)
            return planned[:cut]
        return reached

    # ---- statements ---------------------------------------------------------------------------
    def execute(self, query, params=None, *, writes=(), reads=(), uses=(), call: str | None = None):
        """Run one parameterised statement. ``writes`` = (table, EVENT, set_columns) it modifies."""
        text = " ".join((query if isinstance(query, str) else query.as_string(self.conn)).split())
        entry = {"sql": text, "status": "running"}
        self.statements.append(entry)
        for table in reads:
            self._once(self.tables, table)
        if call:
            writes = tuple(tracing.PROCEDURE_WRITES.get(call, []))
        planned = self._planned(writes)
        head = [("function", fn, None) for fn in uses] + ([("CALL", call, None)] if call else [])
        try:
            cursor = self.conn.execute(query, params)
        except Exception as exc:
            entry["status"] = "failed"
            for kind, name, fires in head + self._reached_after_failure(planned, exc, call):
                self._component(kind, name, fires)
            diag = getattr(exc, "diag", None)
            self.failure = {"statement": len(self.statements), "constraint": getattr(diag, "constraint_name", None),
                            "message": getattr(diag, "message_primary", None), "sqlstate": getattr(exc, "sqlstate", None)}
            raise
        entry["status"] = "ok"
        for kind, name, fires in head + planned:
            self._component(kind, name, fires)
        if call:
            for extra in tracing.PROCEDURE_EXTRAS.get(call, []):
                self._component("cursor", extra.split(" ")[1])
        return cursor

    def one(self, query, params=None, **kw):
        return self.execute(query, params, **kw).fetchone()

    def all(self, query, params=None, **kw):
        return self.execute(query, params, **kw).fetchall()

    def call(self, procedure: str, args: tuple):
        """CALL a stored procedure; its internal writes and the triggers they fire are listed in the trace."""
        if procedure not in tracing.PROCEDURE_WRITES:       # only known procedures can be called
            raise ValueError(f"unknown procedure {procedure}")
        statement = psql.SQL("CALL {}({})").format(psql.Identifier(procedure), psql.SQL(", ").join(psql.Placeholder() for _ in args))
        return self.execute(statement, args, call=procedure)

    # ---- before / after observation ---------------------------------------------------------------
    def watch(self, label: str, sql: str, params=()) -> None:
        """Record what a row looks like now and again just before commit (instrumentation, not a statement)."""
        row = self.conn.execute(sql, params).fetchone()
        self._watches.append({"label": label, "sql": " ".join(sql.split()), "params": params, "before": dict(row) if row else None})

    def observe(self, label: str, query: str, params=(), *, before=None) -> None:
        """Record the state after the statements ran, with an explicit "before" (for rows that did not exist yet)."""
        row = self.conn.execute(query, params).fetchone()
        self.effects.append({"label": label, "before": before, "after": dict(row) if row else None})

    def _finish_watches(self) -> None:
        self._count_changes()
        for w in self._watches:
            row = self.conn.execute(w["sql"], w["params"]).fetchone()
            self.effects.append({"label": w["label"], "before": w["before"], "after": dict(row) if row else None})

    # ---- result ---------------------------------------------------------------------------------
    def trace(self) -> dict:
        return {
            "operation": self.operation,
            "outcome": self.outcome,
            "tables_touched": list(self.tables),
            "components": list(self.components),
            "component_details": list(self.details),
            "constraints_checked": list(self.constraints),
            "statements": [s["sql"] for s in self.statements],
            "statement_status": [s["status"] for s in self.statements],
            "notices": list(self.notices.messages),
            "rows_affected": sum(sum(c.values()) for c in self.row_changes.values()),
            "row_changes": dict(self.row_changes),
            "effects": [{"label": e["label"], "before": _jsonable(e["before"]), "after": _jsonable(e["after"]), **({"unchanged": True} if e.get("unchanged") else {})} for e in self.effects],
            "duration_ms": round(self.duration_ms, 2),
            "rolled_back": self.outcome != "committed",
            "failure": self.failure,
        }


def _jsonable(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        out[key] = value.isoformat() if hasattr(value, "isoformat") else (float(value) if value.__class__.__name__ == "Decimal" else value)
    return out


@contextmanager
def transaction(actor_id, operation: str, note: str | None = None):
    """Open one pooled transaction and name the acting user for the audit triggers."""
    started = time.perf_counter()
    pool = get_pool()
    tx: Tx | None = None
    with pool.connection() as conn:
        collector = NoticeCollector()
        conn.add_notice_handler(collector)
        try:
            with conn.transaction():
                tx = Tx(conn, operation, collector, actor_id)
                conn.execute("SELECT set_config('dmers.actor_id', %s, true)", (str(actor_id) if actor_id is not None else "",))
                if note:
                    conn.execute("SELECT set_config('dmers.note', %s, true)", (note,))
                yield tx
                tx._finish_watches()
        except Exception as exc:
            if tx is not None:
                tx.outcome = "rolled_back"
                tx.effects = [{"label": w["label"], "before": w["before"], "after": w["before"], "unchanged": True} for w in tx._watches]
                tx.duration_ms = (time.perf_counter() - started) * 1000
                exc.db_trace = tx.trace()
            raise
        finally:
            conn.remove_notice_handler(collector)
    if tx is not None:
        tx.duration_ms = (time.perf_counter() - started) * 1000
