"""Transaction-isolation laboratory: two real PostgreSQL sessions in a scripted interleaving.

Each scenario resets its scratch table in schema ``lab``, opens sessions A and B at the chosen
isolation level, runs the statements in a fixed order and records what every statement returned or
which error PostgreSQL raised. Nothing is simulated: the anomaly (or its prevention) is what the
server actually did. The levels, scenarios and modes are fixed allow-lists; no user text reaches SQL.
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from ..pool import database_url

LEVELS = ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE")

CATALOG = {
    "lost_update": {
        "title": "Lost update", "modes": ("naive", "atomic", "retry"),
        "story": "Two coordinators allocate relief from the same stock of 10. A takes 3, B takes 2: 5 must remain.",
        "modes_help": {"naive": "read the quantity, compute in the application, write it back",
                       "atomic": "UPDATE ... SET qty = qty - n (the arithmetic happens inside the statement)",
                       "retry": "naive, but the application repeats the whole transaction after a serialization failure (40001)"},
    },
    "write_skew": {
        "title": "Write skew", "modes": ("naive", "retry"),
        "story": "Rule: at least one of two medics stays on duty. Each medic checks 'is someone else on duty?' and then goes off duty.",
        "modes_help": {"naive": "check, then update own row, no retry",
                       "retry": "the application repeats the transaction after a serialization failure and re-checks the rule"},
    },
    "phantom_read": {
        "title": "Phantom read", "modes": ("naive",),
        "story": "A counts the HIGH tickets in zone North twice inside one transaction; B inserts a new HIGH ticket in between.",
        "modes_help": {"naive": "count, wait for B's committed insert, count again"},
    },
    "non_repeatable_read": {
        "title": "Non-repeatable read", "modes": ("naive",),
        "story": "A reads one ticket's severity twice inside one transaction; B changes it and commits in between.",
        "modes_help": {"naive": "read, wait for B's committed update, read again"},
    },
}
SQLSTATE_NAME = {"40001": "serialization_failure", "40P01": "deadlock_detected", "55P03": "lock_not_available"}


class _Session:
    """One PostgreSQL connection that records every statement it runs."""

    def __init__(self, name: str, level: str, log: list):
        self.name, self.level, self.log = name, level, log
        self.conn = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.conn.execute("SET lock_timeout = '2s'")          # a scripting mistake must never hang the request
        self.open = False
        self.failed = False

    def begin(self):
        self.step(f"BEGIN ISOLATION LEVEL {self.level}")
        self.open, self.failed = True, False

    def step(self, sql: str, params=(), note: str | None = None):
        entry = {"n": len(self.log) + 1, "session": self.name, "sql": " ".join(sql.split()), "params": list(params), "note": note}
        self.log.append(entry)
        if self.failed and not sql.startswith(("ROLLBACK", "COMMIT")):
            entry["skipped"] = "this transaction was already aborted"
            return None
        try:
            cursor = self.conn.execute(sql, params)
            rows = cursor.fetchall() if cursor.description else None
            entry["result"] = _plain(rows) if rows is not None else (cursor.statusmessage or "OK")
            if sql.startswith("COMMIT") and self.failed:
                entry["result"] = "ROLLBACK (the transaction had already failed)"
            if sql.startswith(("COMMIT", "ROLLBACK")):
                self.open = False
            return rows
        except psycopg.Error as exc:
            code = getattr(exc, "sqlstate", None)
            entry["error"] = {"sqlstate": code, "name": SQLSTATE_NAME.get(code, type(exc).__name__),
                              "message": (getattr(exc.diag, "message_primary", None) or str(exc)).split("\n")[0]}
            self.failed = True
            return None

    def finish(self):
        if self.open:
            self.step("ROLLBACK" if self.failed else "COMMIT")
        self.conn.close()


def _plain(rows):
    return [{k: (float(v) if v.__class__.__name__ == "Decimal" else v) for k, v in row.items()} for row in rows]


def _reset(conn, scenario: str) -> None:
    if scenario == "lost_update":
        conn.execute("TRUNCATE lab.stock")
        conn.execute("INSERT INTO lab.stock VALUES (1, 'Drinking water (cartons)', 10)")
    elif scenario == "write_skew":
        conn.execute("TRUNCATE lab.oncall")
        conn.execute("INSERT INTO lab.oncall VALUES ('medic_a', true), ('medic_b', true)")
    else:
        conn.execute("TRUNCATE lab.tickets RESTART IDENTITY")
        conn.execute("INSERT INTO lab.tickets (zone, severity) VALUES ('North', 'HIGH'), ('North', 'HIGH'), ('South', 'LOW')")


def _final(conn, scenario: str):
    if scenario == "lost_update":
        return _plain(conn.execute("SELECT item, qty FROM lab.stock").fetchall())
    if scenario == "write_skew":
        return _plain(conn.execute("SELECT medic, on_duty FROM lab.oncall ORDER BY medic").fetchall())
    return _plain(conn.execute("SELECT id, zone, severity FROM lab.tickets ORDER BY id").fetchall())


def run(scenario: str, level: str, mode: str = "naive") -> dict:
    if scenario not in CATALOG:
        raise ValueError("Unknown scenario")
    if level not in LEVELS:
        raise ValueError("Level must be READ COMMITTED, REPEATABLE READ or SERIALIZABLE")
    if mode not in CATALOG[scenario]["modes"]:
        raise ValueError(f"Mode for {scenario} must be one of {', '.join(CATALOG[scenario]['modes'])}")
    log: list = []
    with psycopg.connect(database_url(), autocommit=True, row_factory=dict_row) as admin:
        _reset(admin, scenario)
        a, b = _Session("A", level, log), _Session("B", level, log)
        try:
            result = {"lost_update": _lost_update, "write_skew": _write_skew, "phantom_read": _phantom, "non_repeatable_read": _non_repeatable}[scenario](a, b, admin, mode)
        finally:
            a.finish()
            b.finish()
        final = _final(admin, scenario)
    anomaly, verdict = _judge(scenario, final, log, result)
    return {"scenario": scenario, "title": CATALOG[scenario]["title"], "story": CATALOG[scenario]["story"], "level": level, "mode": mode,
            "steps": log, "final_state": final, "anomaly": anomaly, "verdict": verdict, "retries": result.get("retries", 0),
            "refused": any("error" in s for s in log)}


def _lost_update(a, b, admin, mode):
    a.begin(); b.begin()
    ra = a.step("SELECT qty FROM lab.stock WHERE id = 1", note="A reads the stock")
    rb = b.step("SELECT qty FROM lab.stock WHERE id = 1", note="B reads the same stock before A writes")
    qa = ra[0]["qty"] if ra else 10
    qb = rb[0]["qty"] if rb else 10
    a.step("UPDATE lab.stock SET qty = %s WHERE id = 1", (qa - 3,), note="A allocates 3")
    a.step("COMMIT")
    if mode == "atomic":
        b.step("UPDATE lab.stock SET qty = qty - 2 WHERE id = 1", note="B allocates 2 inside the statement")
    else:
        b.step("UPDATE lab.stock SET qty = %s WHERE id = 1", (qb - 2,), note="B allocates 2 from the value it read earlier")
    b.step("COMMIT")
    retries = 0
    if mode == "retry" and b.failed:
        retries = 1
        b.begin()
        r = b.step("SELECT qty FROM lab.stock WHERE id = 1", note="B retries from the start and sees A's committed value")
        b.step("UPDATE lab.stock SET qty = %s WHERE id = 1", ((r[0]["qty"] if r else 0) - 2,), note="B allocates 2 again")
        b.step("COMMIT")
    return {"retries": retries}


def _write_skew(a, b, admin, mode):
    check = "SELECT count(*) AS on_duty FROM lab.oncall WHERE on_duty"
    a.begin(); b.begin()
    ra = a.step(check, note="A: is someone else on duty?")
    rb = b.step(check, note="B: is someone else on duty? (A has not changed anything yet)")
    if ra and ra[0]["on_duty"] >= 2:
        a.step("UPDATE lab.oncall SET on_duty = false WHERE medic = 'medic_a'", note="A goes off duty")
    if rb and rb[0]["on_duty"] >= 2:
        b.step("UPDATE lab.oncall SET on_duty = false WHERE medic = 'medic_b'", note="B goes off duty")
    a.step("COMMIT")
    b.step("COMMIT")
    retries = 0
    for session, medic in ((a, "medic_a"), (b, "medic_b")):
        if mode == "retry" and session.failed:
            retries += 1
            session.begin()
            r = session.step(check, note=f"{session.name} retries and re-checks the rule")
            if r and r[0]["on_duty"] >= 2:
                session.step("UPDATE lab.oncall SET on_duty = false WHERE medic = %s", (medic,), note=f"{session.name} goes off duty")
            else:
                session.step("SELECT 1", note=f"{session.name} sees only one medic on duty: the rule forbids leaving, so it does nothing")
            session.step("COMMIT")
    return {"retries": retries}


def _phantom(a, b, admin, mode):
    count = "SELECT count(*) AS high_tickets FROM lab.tickets WHERE zone = 'North' AND severity = 'HIGH'"
    a.begin()
    a.step(count, note="A counts the HIGH tickets in North")
    b.step("INSERT INTO lab.tickets (zone, severity) VALUES ('North', 'HIGH')", note="B (autocommit) inserts and commits a new matching row")
    a.step(count, note="A counts again inside the same transaction")
    a.step("COMMIT")
    return {}


def _non_repeatable(a, b, admin, mode):
    read = "SELECT severity FROM lab.tickets WHERE id = 1"
    a.begin()
    a.step(read, note="A reads ticket 1")
    b.step("UPDATE lab.tickets SET severity = 'CRITICAL' WHERE id = 1", note="B (autocommit) changes it and commits")
    a.step(read, note="A reads ticket 1 again inside the same transaction")
    a.step("COMMIT")
    return {}


def _judge(scenario: str, final, log, result) -> tuple[bool, str]:
    refused = [s for s in log if "error" in s]
    if scenario == "lost_update":
        qty = final[0]["qty"]
        if refused and not result.get("retries"):
            return False, f"Nothing lost: PostgreSQL refused B's stale write (40001), so only A's allocation applied ({qty} remain). B must retry."
        if qty != 5:
            return True, f"Lost update: {qty} remain but 10 - 3 - 2 = 5. A's allocation was overwritten."
        return False, "Correct: 5 remain." + (" PostgreSQL refused the stale write (40001) and the application retried." if result.get("retries") else "")
    if scenario == "write_skew":
        on_duty = sum(1 for r in final if r["on_duty"])
        if on_duty == 0:
            return True, "Write skew: nobody is on duty. Each transaction was valid on its own snapshot; together they broke the rule."
        return False, f"Rule kept: {on_duty} medic on duty." + (" PostgreSQL aborted one transaction (40001) instead of allowing the skew." if refused else "")
    counts = [s["result"][0] for s in log if s["session"] == "A" and s.get("result") and isinstance(s["result"], list)]
    if len(counts) >= 2 and counts[0] != counts[1]:
        kind = "Phantom read" if scenario == "phantom_read" else "Non-repeatable read"
        return True, f"{kind}: the same query returned {list(counts[0].values())[0]} and then {list(counts[1].values())[0]} inside one transaction."
    return False, "Repeatable: both reads inside A's transaction returned the same value (it keeps its snapshot)."


def matrix() -> list[dict]:
    """Run every scenario x level (naive mode) and summarise what PostgreSQL did."""
    rows = []
    for key, info in CATALOG.items():
        cells = {}
        for level in LEVELS:
            r = run(key, level, "naive")
            cells[level] = "anomaly" if r["anomaly"] else ("prevented (error 40001)" if r["refused"] else "no anomaly")
        rows.append({"scenario": key, "title": info["title"], "levels": cells})
    return rows
