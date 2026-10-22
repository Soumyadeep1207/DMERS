"""Report correctness. The oracle is the unmodified Review II package: its scripts 01-03 build a
separate database and the ORIGINAL text of 05_queries.sql runs there. The application's reports,
run against the app database seeded through the Review III seed, must return the same rows."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from tests.conftest import _with_db

REVIEW2 = Path(__file__).resolve().parents[1] / "db" / "review2"
BASE = "/api/response"


def blocks() -> dict[str, str]:
    text = (REVIEW2 / "05_queries.sql").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"-- @block (Q\d+) [^\n]*\n(.*?)(?=\n-- @block|\Z)", text, re.S):
        out[m.group(1)] = m.group(2).strip().rstrip(";")
    return out


@pytest.fixture(scope="module")
def oracle(pg_admin_url):
    name = "dmers_oracle_" + uuid.uuid4().hex[:8]
    with psycopg.connect(pg_admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _with_db(pg_admin_url, name)
    try:
        with psycopg.connect(url) as conn:
            for script in ("01_schema.sql", "02_plpgsql.sql", "03_seed_data.sql"):
                conn.execute((REVIEW2 / script).read_text(encoding="utf-8"))
            q15 = blocks()["Q15"]
            conn.execute(q15[: q15.index("SELECT * FROM v_zone_situation")])      # the view definition
        yield url
    finally:
        with psycopg.connect(pg_admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def norm(value):
    if value is None:
        return None
    if isinstance(value, (Decimal, float)):
        return round(float(value), 3)
    return value if isinstance(value, int) else str(value)


def oracle_rows(url, query):
    with psycopg.connect(url) as conn:
        conn.execute("SET TIME ZONE 'Asia/Kolkata'")
        return [[norm(v) for v in row] for row in conn.execute(query).fetchall()]


def report_rows(api, key, **params):
    response = api.get(f"{BASE}/reports/{key}", query_string=params)
    assert response.status_code == 200, response.get_json()
    return [[norm(v) for v in row] for row in response.get_json()["rows"]], response.get_json()


@pytest.mark.parametrize("key,query_id,params", [
    ("active-incidents", "Q1", {}),
    ("command-board", "Q14", {}),
    ("stock-status", "Q5", {"only_low": "true"}),
    ("response-time", "Q10", {}),
    ("unit-utilisation", "Q9", {}),
    ("busiest-by-type", "Q13", {}),
    ("incident-timeline", "Q11", {"incident_id": 3}),
    ("accountability", "Q12", {"incident_id": 7}),
])
def test_report_equals_review2_query(key, query_id, params, oracle, people):
    expected = oracle_rows(oracle, blocks()[query_id])
    got, body = report_rows(people["coordinator"], key, **params)
    assert expected, f"{query_id} returned no rows; the comparison would prove nothing"
    assert got == expected
    assert body["requirement"] and body["review2_query"] == query_id and body["sql_feature"]


def test_zone_situation_report_equals_q15(oracle, people):
    select = blocks()["Q15"]
    expected = oracle_rows(oracle, select[select.index("SELECT * FROM v_zone_situation"):])
    got, _ = report_rows(people["coordinator"], "zone-situation")
    assert got == expected and expected


def test_known_facts_from_the_review2_execution_log(people):
    """Independent anchors taken from the printed Review II run (execution_log.txt), not from any query."""
    rows, _ = report_rows(people["coordinator"], "stock-status", only_low="true")
    names = {r[0]: r[3] for r in rows}
    assert names["Inflatable rescue boats"] == "OUT_OF_STOCK"
    board, _ = report_rows(people["coordinator"], "command-board")
    assert sorted(r[0] for r in board) == [7, 9, 10, 11, 14]


def test_csv_export_and_formula_safety(people):
    r = people["coordinator"].get(f"{BASE}/reports/stock-status", query_string={"format": "csv"})
    assert r.status_code == 200 and r.mimetype == "text/csv" and "attachment" in r.headers["Content-Disposition"]
    text = r.get_data(as_text=True)
    assert text.startswith("﻿") and "Requirement" in text and "OUT_OF_STOCK" in text
    from db.reports import safe_cell
    assert safe_cell("=1+1") == "'=1+1" and safe_cell(None) == ""


def test_bad_parameters_and_unknown_reports(people):
    assert people["coordinator"].get(f"{BASE}/reports/incident-timeline", query_string={"incident_id": "abc"}).status_code == 400
    assert people["coordinator"].get(f"{BASE}/reports/nope").status_code == 404
    catalogue = people["coordinator"].get(f"{BASE}/reports").get_json()["reports"]
    assert len(catalogue) >= 6 and all(r["requirement"] and r["sql_feature"] for r in catalogue)
