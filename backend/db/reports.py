"""Reports: the Review II queries (05_queries.sql) run against live data.

SQL text is copied from Review II; literals that were hard-coded there (an incident number, a row
limit) became named parameters. Everything is read-only and parameterised.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .errors import ApiError
from .pool import get_pool


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    requirement: str
    review2_query: str
    sql_feature: str
    description: str
    sql: str
    params: dict = field(default_factory=dict)   # name -> (type, default, label)
    emphasise: tuple = ()                         # (column, set of values) shown in bold, never colour


REPORTS: tuple[Report, ...] = (
    Report("active-incidents", "Active incidents, most severe first", "FR-04", "Q1", "selection, CASE inside ORDER BY",
           "Every VERIFIED or RESPONDING incident ordered by severity, then by report time.",
           """SELECT id, title, severity, status FROM incidents WHERE status IN ('VERIFIED', 'RESPONDING')
              ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MODERATE' THEN 3 ELSE 4 END, created_at"""),
    Report("zone-situation", "Situation report by zone", "FR-13", "Q15", "VIEW v_zone_situation, scalar subquery, stored function fn_active_incidents",
           "Active incidents and available units per zone. By default only zones with an active incident or a HIGH risk level.",
           """SELECT * FROM v_zone_situation
              WHERE %(all_zones)s OR active_incidents > 0 OR risk_level = 'HIGH'
              ORDER BY active_incidents DESC, zone_name""",
           {"all_zones": ("bool", False, "Show every zone")}, ("risk_level", {"HIGH"})),
    Report("command-board", "Command board for open incidents", "FR-13", "Q14", "two CTEs, left outer joins",
           "For each open incident: units on scene, units on the way and relief items allocated.",
           """WITH units AS (SELECT incident_id,
                                   count(*) FILTER (WHERE dispatch_status = 'ON_SCENE') AS on_scene,
                                   count(*) FILTER (WHERE dispatch_status IN ('ASSIGNED', 'EN_ROUTE')) AS on_the_way
                            FROM dispatches GROUP BY incident_id),
                   relief AS (SELECT incident_id, count(*) AS relief_items FROM resource_allocations GROUP BY incident_id)
              SELECT i.id, i.severity, coalesce(u.on_scene, 0) AS on_scene, coalesce(u.on_the_way, 0) AS on_the_way,
                     coalesce(r.relief_items, 0) AS relief_items
              FROM incidents i LEFT JOIN units u ON u.incident_id = i.id LEFT JOIN relief r ON r.incident_id = i.id
              WHERE i.status IN ('VERIFIED', 'RESPONDING') ORDER BY i.id""", {}, ("severity", {"CRITICAL"})),
    Report("stock-status", "Relief stock status", "FR-13", "Q5", "stored function fn_stock_status in WHERE and SELECT",
           "Relief items with their derived stock status. Low and out-of-stock items are printed in bold.",
           """SELECT resource_name, quantity_available AS available, reorder_level, fn_stock_status(id) AS stock_status
              FROM resources WHERE (NOT %(only_low)s) OR fn_stock_status(id) <> 'ADEQUATE'
              ORDER BY quantity_available""",
           {"only_low": ("bool", False, "Only items at or below the reorder level")}, ("stock_status", {"LOW", "OUT_OF_STOCK"})),
    Report("response-time", "Average response time per zone", "FR-13", "Q10", "AVG over the stored function fn_response_minutes",
           "Minutes from report to first unit arrival, averaged per zone.",
           """SELECT z.zone_name, count(*) AS incidents_reached, round(avg(fn_response_minutes(i.id)), 1) AS avg_minutes
              FROM incidents i JOIN zones z ON z.id = i.zone_id
              WHERE fn_response_minutes(i.id) IS NOT NULL
              GROUP BY z.zone_name ORDER BY avg_minutes"""),
    Report("unit-utilisation", "Unit utilisation", "FR-13", "Q9", "join, GROUP BY, aggregate FILTER, interval arithmetic, LIMIT",
           "Dispatches, completed dispatches and hours on scene for the busiest units.",
           """SELECT r.unit_name, count(*) AS dispatches,
                     count(*) FILTER (WHERE d.dispatch_status = 'COMPLETED') AS completed,
                     round(sum(extract(epoch FROM d.cleared_at - d.arrived_at) / 3600)
                           FILTER (WHERE d.dispatch_status = 'COMPLETED'), 2) AS hours_on_scene
              FROM dispatches d JOIN response_units r ON r.id = d.unit_id
              GROUP BY r.unit_name ORDER BY dispatches DESC, hours_on_scene DESC NULLS LAST LIMIT %(limit)s""",
           {"limit": ("int", 5, "Rows to show")}),
    Report("busiest-by-type", "Busiest unit of each type", "FR-13", "Q13", "derived table, window function ROW_NUMBER",
           "The unit with the most dispatches within each unit type.",
           """SELECT unit_type, unit_name, dispatches
              FROM (SELECT r.unit_type, r.unit_name, count(d.unit_id) AS dispatches,
                           row_number() OVER (PARTITION BY r.unit_type ORDER BY count(d.unit_id) DESC, r.unit_name) AS rn
                    FROM response_units r LEFT JOIN dispatches d ON d.unit_id = r.id
                    GROUP BY r.unit_type, r.unit_name) ranked
              WHERE rn = 1 ORDER BY unit_type"""),
    Report("incident-timeline", "Incident timeline", "FR-12", "Q11", "left outer join, string expressions, to_char",
           "Every status change and note of one incident, with the person who made it.",
           """SELECT t.update_no AS no, to_char(t.logged_at, 'DD-Mon HH24:MI') AS logged_at,
                     coalesce(t.previous_status, '-') || ' > ' || t.new_status AS change, u.name AS logged_by, t.note
              FROM incident_updates t LEFT JOIN users u ON u.id = t.logged_by
              WHERE t.incident_id = %(incident_id)s ORDER BY t.update_no""",
           {"incident_id": ("int", 3, "Incident number")}),
    Report("accountability", "Everyone accountable for an incident", "FR-12", "Q12", "UNION of three joins",
           "The reporter, the dispatching coordinator(s) and the leads of dispatched units.",
           """SELECT u.name AS full_name, 'reporter' AS role
              FROM incidents i JOIN users u ON u.id = i.reported_by WHERE i.id = %(incident_id)s
              UNION
              SELECT u.name, 'dispatching coordinator'
              FROM dispatches d JOIN users u ON u.id = d.dispatched_by WHERE d.incident_id = %(incident_id)s
              UNION
              SELECT u.name, 'lead of a dispatched unit'
              FROM dispatches d JOIN response_units r ON r.id = d.unit_id JOIN users u ON u.id = r.lead_user_id
              WHERE d.incident_id = %(incident_id)s
              ORDER BY role, full_name""",
           {"incident_id": ("int", 7, "Incident number")}),
)
BY_KEY = {r.key: r for r in REPORTS}


def catalogue() -> list[dict]:
    return [{"key": r.key, "title": r.title, "requirement": r.requirement, "review2_query": r.review2_query,
             "sql_feature": r.sql_feature, "description": r.description,
             "params": [{"name": n, "type": t, "default": d, "label": label} for n, (t, d, label) in r.params.items()]}
            for r in REPORTS]


def _coerce(report: Report, raw: dict) -> dict:
    values = {}
    for name, (kind, default, _label) in report.params.items():
        value = raw.get(name, default)
        try:
            if kind == "int":
                value = int(value)
                if not 1 <= value <= 100000:
                    raise ValueError
            elif kind == "bool":
                value = value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes", "on"}
        except (TypeError, ValueError):
            raise ApiError(400, "bad_parameter", f"Parameter {name} is invalid.") from None
        values[name] = value
    return values


def run(key: str, raw_params: dict) -> dict:
    """Execute one report inside a read-only transaction and return rows, columns and metadata."""
    report = BY_KEY.get(key)
    if report is None:
        raise ApiError(404, "unknown_report", "There is no such report.")
    params = _coerce(report, raw_params)
    with get_pool().connection() as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL TIME ZONE 'Asia/Kolkata'")
            cursor = conn.execute(report.sql, params)
            columns = [c.name for c in cursor.description]
            rows = [[row[c] for c in columns] for row in cursor.fetchall()]
    return {"key": report.key, "title": report.title, "requirement": report.requirement, "review2_query": report.review2_query,
            "sql_feature": report.sql_feature, "description": report.description, "sql": " ".join(report.sql.split()),
            "parameters": params, "columns": columns, "rows": rows, "row_count": len(rows),
            "emphasise": {"column": report.emphasise[0], "values": sorted(report.emphasise[1])} if report.emphasise else None,
            "time_zone": "Asia/Kolkata"}


def safe_cell(value) -> str:
    text = "" if value is None else (value.isoformat() if hasattr(value, "isoformat") else str(value))
    return "'" + text if text[:1] in "=+-@" and text else text


def to_csv(result: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow([result["title"]])
    writer.writerow(["Requirement", result["requirement"], "Review II query", result["review2_query"]])
    writer.writerow(["Parameters", ", ".join(f"{k}={v}" for k, v in result["parameters"].items()) or "none"])
    writer.writerow([])
    writer.writerow(result["columns"])
    for row in result["rows"]:
        writer.writerow([safe_cell(v) for v in row])
    return "﻿" + out.getvalue()
