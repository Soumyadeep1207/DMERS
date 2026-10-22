"""Query-optimiser laboratory: real EXPLAIN (ANALYZE, BUFFERS) plans on the synthetic history.

Every experiment is a fixed query plus a fixed set of variants (index state). A run builds the variant's
index inside a transaction, plans and executes the query with EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and
then ROLLS BACK, so the lab never leaves an index behind and every run starts from the same state.
Parallel workers are switched off for the run so plans are easy to read and to compare.
"""
from __future__ import annotations

from datetime import date

from psycopg import sql

FLAT, PART = "lab.incident_events_flat", "lab.incident_events"
LAB_INDEXES = ("ix_flat_zone_status", "ix_flat_time_btree", "ix_flat_time_brin")

EXPERIMENTS = {
    "zone_status": {
        "title": "Open incidents in one zone",
        "question": "How does a composite B-tree index change a selective filter on zone and status?",
        "query": "SELECT count(*) AS incidents, round(avg(response_minutes), 1) AS avg_response FROM lab.incident_events_flat WHERE zone_id = {zone} AND status = 'REPORTED'",
        "variants": {
            "no_index": {"label": "No index (sequential scan)", "ddl": []},
            "btree": {"label": "B-tree on (zone_id, status)", "ddl": ["CREATE INDEX ix_flat_zone_status ON lab.incident_events_flat (zone_id, status)"], "index": "ix_flat_zone_status"},
        },
    },
    "time_window": {
        "title": "Incidents in one week",
        "question": "B-tree, BRIN and partition pruning for a narrow time range on a table stored in time order.",
        "query": "SELECT count(*) AS incidents FROM {table} WHERE occurred_at >= {lo} AND occurred_at < {hi}",
        "variants": {
            "no_index": {"label": "No index (sequential scan)", "ddl": [], "table": FLAT},
            "btree": {"label": "B-tree on occurred_at", "ddl": ["CREATE INDEX ix_flat_time_btree ON lab.incident_events_flat (occurred_at)"], "index": "ix_flat_time_btree", "table": FLAT},
            "brin": {"label": "BRIN on occurred_at", "ddl": ["CREATE INDEX ix_flat_time_brin ON lab.incident_events_flat USING brin (occurred_at) WITH (pages_per_range = 16)"], "index": "ix_flat_time_brin", "table": FLAT},
            "partitioned": {"label": "Monthly partitions (no extra index)", "ddl": [], "table": PART},
        },
    },
    "monthly_rollup": {
        "title": "Monthly totals per zone",
        "question": "What does a materialised view save compared with aggregating the whole table on every request?",
        "variants": {
            "live_aggregate": {"label": "GROUP BY over the table", "ddl": [], "query": "SELECT zone_id, date_trunc('month', occurred_at) AS month, count(*) AS incidents FROM lab.incident_events_flat GROUP BY 1, 2 ORDER BY 1, 2"},
            "materialized_view": {"label": "Read lab.mv_zone_month", "ddl": [], "query": "SELECT zone_id, month, sum(incidents) AS incidents FROM lab.mv_zone_month GROUP BY 1, 2 ORDER BY 1, 2"},
        },
    },
}


def catalog() -> list[dict]:
    return [{"key": k, "title": e["title"], "question": e["question"],
             "variants": [{"key": vk, "label": v["label"]} for vk, v in e["variants"].items()]} for k, e in EXPERIMENTS.items()]


def status(conn) -> dict:
    row = conn.execute("""SELECT (SELECT count(*) FROM lab.incident_events_flat) AS flat_rows,
                                 (SELECT count(*) FROM lab.incident_events) AS partitioned_rows,
                                 (SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
                                    WHERE i.inhparent = 'lab.incident_events'::regclass AND c.reltuples > 0) AS partitions_with_rows,
                                 pg_total_relation_size('lab.incident_events_flat') AS flat_bytes,
                                 (SELECT ispopulated FROM pg_matviews WHERE schemaname = 'lab' AND matviewname = 'mv_zone_month') AS view_populated,
                                 (SELECT min(occurred_at) FROM lab.incident_events_flat) AS first_event,
                                 (SELECT max(occurred_at) FROM lab.incident_events_flat) AS last_event""").fetchone()
    return dict(row)


def _walk(node: dict, depth: int, out: list) -> dict:
    entry = {"depth": depth, "node": node.get("Node Type"), "relation": node.get("Relation Name"), "index": node.get("Index Name"),
             "rows": node.get("Actual Rows"), "loops": node.get("Actual Loops"), "ms": node.get("Actual Total Time"),
             "rows_removed": node.get("Rows Removed by Filter"), "shared_hit": node.get("Shared Hit Blocks"), "shared_read": node.get("Shared Read Blocks")}
    out.append(entry)
    for child in node.get("Plans", []):
        _walk(child, depth + 1, out)
    return entry


def summarise(plan_json: list) -> dict:
    top = plan_json[0]
    nodes: list[dict] = []
    _walk(top["Plan"], 0, nodes)
    scans = [n for n in nodes if n["node"] and "Scan" in n["node"] and n["relation"]]
    relations = sorted({n["relation"] for n in scans})
    return {
        "execution_ms": round(top.get("Execution Time", 0.0), 3), "planning_ms": round(top.get("Planning Time", 0.0), 3),
        "nodes": nodes, "scan_types": sorted({n["node"] for n in scans}),
        "uses_index": any("Index" in (n["node"] or "") or "Bitmap" in (n["node"] or "") for n in nodes),
        "relations_scanned": relations,
        "partitions_scanned": len([r for r in relations if r.startswith("incident_events_2") or r.endswith("_default")]),
        "buffers_hit": top["Plan"].get("Shared Hit Blocks", 0), "buffers_read": top["Plan"].get("Shared Read Blocks", 0),
    }


def run(conn, experiment: str, variant: str, *, zone: int = 1, week_start: date | None = None) -> dict:
    """Plan and execute one variant. The caller's connection is used inside a transaction that is rolled back."""
    if experiment not in EXPERIMENTS or variant not in EXPERIMENTS[experiment]["variants"]:
        raise ValueError("Unknown experiment or variant")
    if conn.execute("SELECT count(*) AS n FROM lab.incident_events_flat").fetchone()["n"] == 0:
        raise LookupError("Load the synthetic history first.")
    exp, var = EXPERIMENTS[experiment], EXPERIMENTS[experiment]["variants"][variant]
    week_start = week_start or date(2026, 3, 2)
    for name in LAB_INDEXES:
        conn.execute(sql.SQL("DROP INDEX IF EXISTS lab.{}").format(sql.Identifier(name)))
    for ddl in var["ddl"]:
        conn.execute(ddl)
    if var["ddl"]:
        conn.execute(f"ANALYZE {FLAT}")
    conn.execute("SET LOCAL max_parallel_workers_per_gather = 0")
    query = var.get("query") or exp["query"]
    statement = sql.SQL(query).format(
        zone=sql.Literal(int(zone)), lo=sql.Literal(week_start), hi=sql.Literal(date.fromordinal(week_start.toordinal() + 7)),
        table=sql.SQL(var.get("table", FLAT))) if "{" in query else sql.SQL(query)
    explain = sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ") + statement
    plan = conn.execute(explain).fetchone()["QUERY PLAN"]
    result = summarise(plan)
    index_bytes = None
    if var.get("index"):
        index_bytes = conn.execute("SELECT pg_relation_size(%s::regclass) AS b", (f"lab.{var['index']}",)).fetchone()["b"]
    answer = conn.execute(statement.as_string(conn) + " LIMIT 5" if experiment == "monthly_rollup" else statement).fetchall()
    return {"experiment": experiment, "variant": variant, "label": var["label"], "sql": " ".join(statement.as_string(conn).split()),
            "answer": [dict(r) for r in answer][:5], "index_bytes": index_bytes, **result}
