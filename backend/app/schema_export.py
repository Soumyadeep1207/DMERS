"""Self-documenting schema exports for DMERS (data dictionary, relationships, row data).

Works on both SQLite (offline) and PostgreSQL. Everything is read from the live catalogue, so the
CSV always reflects the database that is actually running, with real row counts and statistics.
Sensitive columns are never exported: password hashes are omitted and e-mail samples are masked.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone

TABLES = ("roles", "users", "locations", "incidents", "rescue_teams", "hospitals", "partner_profiles", "missions", "simulations", "audit_entries")
SENSITIVE = {("users", "password")}
MASKED = {("users", "email")}

TABLE_PURPOSE = {
    "roles": "Lookup of permitted account roles; referenced by users.role.",
    "users": "Every person who can sign in: administrators, officials, responders, volunteers and citizens.",
    "locations": "Named places with optional GPS coordinates, shared by incidents and hospitals.",
    "incidents": "Reported emergencies with severity and a verified-to-closed workflow status.",
    "rescue_teams": "Deployable response teams with a capability description and availability.",
    "hospitals": "Receiving facilities with total and currently available beds and a reception status.",
    "partner_profiles": "Links a partner (NGO, dispatch, hospital) login to its institution and, for hospitals, its facility.",
    "missions": "A rescue team's assignment to an incident, optionally with a receiving hospital; one active mission per incident.",
    "simulations": "Saved AI-planner scenarios (JSON) owned by the user who created them.",
    "audit_entries": "Append-only record of who did what and when; used for accountability review.",
}
COLUMN_MEANING = {
    ("roles", "name"): "Role name: admin, official, responder, volunteer or citizen.",
    ("users", "name"): "Display name of the account holder.",
    ("users", "email"): "Unique sign-in address (masked in exports).",
    ("users", "password"): "Salted password hash. Never exported.",
    ("users", "role"): "Access level; foreign key to roles.name and checked against the permitted list.",
    ("locations", "label"): "Human-readable place name or landmark.",
    ("locations", "latitude"): "WGS-84 latitude in degrees, -90 to 90; NULL when only a landmark is known.",
    ("locations", "longitude"): "WGS-84 longitude in degrees, -180 to 180; NULL when only a landmark is known.",
    ("incidents", "reference"): "Public case reference such as INC-123456 or PUB-123456; unique.",
    ("incidents", "disaster_type"): "Kind of emergency, e.g. Flood, Fire, Medical emergency.",
    ("incidents", "severity"): "low, moderate, high or critical; drives triage priority points.",
    ("incidents", "status"): "Workflow state: reported, verified, dispatched, resolved or closed.",
    ("incidents", "location_id"): "Where it happened; mandatory foreign key to locations.",
    ("incidents", "reported_by"): "Reporting user; NULL for anonymous public reports.",
    ("rescue_teams", "capability"): "Free-text skills used to match teams to incident types.",
    ("rescue_teams", "availability"): "available, deployed or unavailable.",
    ("hospitals", "total_beds"): "Staffed bed capacity.",
    ("hospitals", "available_beds"): "Beds free right now; constrained to 0..total_beds.",
    ("hospitals", "status"): "accepting, limited or divert; divert blocks new transfers.",
    ("partner_profiles", "portal"): "ngo, dispatch or hospital portal the account may use.",
    ("partner_profiles", "hospital_id"): "Facility a hospital-portal account manages; must be NULL for other portals.",
    ("missions", "status"): "assigned, acknowledged, en_route, on_scene, in_progress, at_hospital, completed, escalated or aborted.",
    ("missions", "hospital_id"): "Receiving hospital chosen for transport; optional.",
    ("simulations", "scenario"): "JSON document of the saved scenario.",
    ("audit_entries", "action"): "Machine-readable action code such as MISSION_ASSIGNED.",
}


def _quote(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Unsafe identifier")
    return f'"{name}"'


def _balanced_checks(sql: str) -> list[str]:
    found = []
    for match in re.finditer(r"CHECK\s*\(", sql, re.IGNORECASE):
        depth, i = 1, match.end()
        while i < len(sql) and depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        found.append(sql[match.end():i - 1].strip())
    return found


def _sqlite_catalogue(db) -> dict:
    cat: dict = {}
    for table in TABLES:
        sql_row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not sql_row:
            continue
        ddl = sql_row[0] or ""
        cols = db.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        fks = db.execute(f"PRAGMA foreign_key_list({_quote(table)})").fetchall()
        uniques = set()
        indexes = []
        for idx in db.execute(f"PRAGMA index_list({_quote(table)})").fetchall():
            names = [r[2] for r in db.execute(f"PRAGMA index_info({_quote(idx[1])})").fetchall()]
            indexes.append({"name": idx[1], "unique": bool(idx[2]), "columns": names})
            if idx[2] and len(names) == 1 and not (len(idx) > 4 and idx[4]):
                uniques.add(names[0])
        cat[table] = {
            "columns": [{"ord": c[0] + 1, "name": c[1], "type": (c[2] or "").upper() or "ANY", "nullable": not c[3] and not c[5], "default": c[4], "pk": bool(c[5])} for c in cols],
            "fks": [{"column": f[3], "ref_table": f[2], "ref_column": f[4] or "id", "on_delete": f[6]} for f in fks],
            "uniques": uniques, "checks": _balanced_checks(ddl), "indexes": indexes,
        }
    return cat


def _pg_catalogue(db) -> dict:
    cat: dict = {}
    marks = ",".join("?" * len(TABLES))
    columns = db.execute(f"""
        SELECT c.relname AS tbl, a.attname AS col, a.attnum AS ord, format_type(a.atttypid, a.atttypmod) AS dtype,
               NOT a.attnotnull AS nullable, pg_get_expr(d.adbin, d.adrelid) AS dflt
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname IN ({marks})
        ORDER BY c.relname, a.attnum""", TABLES).fetchall()
    constraints = db.execute(f"""
        SELECT c.relname AS tbl, con.contype AS kind, pg_get_constraintdef(con.oid) AS definition,
               ARRAY(SELECT a.attname FROM unnest(con.conkey) k JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k) AS cols,
               fc.relname AS ref_table,
               ARRAY(SELECT a.attname FROM unnest(con.confkey) k JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k) AS ref_cols,
               con.confdeltype AS del
        FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_class fc ON fc.oid = con.confrelid
        WHERE n.nspname = 'public' AND c.relname IN ({marks})""", TABLES).fetchall()
    indexes = db.execute(f"""
        SELECT tablename AS tbl, indexname AS name, indexdef AS definition FROM pg_indexes
        WHERE schemaname = 'public' AND tablename IN ({marks})""", TABLES).fetchall()
    for row in columns:
        entry = cat.setdefault(row["tbl"], {"columns": [], "fks": [], "uniques": set(), "checks": [], "indexes": []})
        entry["columns"].append({"ord": row["ord"], "name": row["col"], "type": row["dtype"].upper(), "nullable": row["nullable"], "default": row["dflt"], "pk": False})
    actions = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
    for row in constraints:
        entry = cat.get(row["tbl"])
        if not entry:
            continue
        cols = list(row["cols"] or [])
        if row["kind"] == "p":
            for column in entry["columns"]:
                if column["name"] in cols:
                    column["pk"], column["nullable"] = True, False
        elif row["kind"] == "u" and len(cols) == 1:
            entry["uniques"].add(cols[0])
        elif row["kind"] == "f":
            entry["fks"].append({"column": cols[0], "ref_table": row["ref_table"], "ref_column": (row["ref_cols"] or ["id"])[0], "on_delete": actions.get(row["del"], "NO ACTION")})
        elif row["kind"] == "c":
            entry["checks"].append(re.sub(r"^CHECK\s*\((.*)\)$", r"\1", row["definition"], flags=re.S).strip())
    for row in indexes:
        if row["tbl"] in cat:
            unique = " UNIQUE " in row["definition"].upper()
            cols = re.findall(r"\(([^)]*)\)", row["definition"])
            cat[row["tbl"]]["indexes"].append({"name": row["name"], "unique": unique, "columns": [c.strip() for c in cols[0].split(",")] if cols else []})
            if unique and cols and "," not in cols[0] and "WHERE" not in row["definition"].upper():
                cat[row["tbl"]]["uniques"].add(cols[0].strip())
    return cat


def catalogue(db) -> dict:
    return _pg_catalogue(db) if getattr(db, "dialect", "sqlite") == "postgresql" else _sqlite_catalogue(db)


def _mask_email(value) -> str:
    text = str(value)
    if "@" not in text:
        return "***"
    local, domain = text.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _stat(db, table: str, column: str) -> dict:
    t, c = _quote(table), _quote(column)
    row = db.execute(f"SELECT COUNT(*) AS total, COUNT({c}) AS filled, COUNT(DISTINCT {c}) AS distinct_values FROM {t}").fetchone()
    total, filled, distinct = row[0], row[1], row[2]
    low = high = sample = None
    if (table, column) not in SENSITIVE and filled:
        extreme = db.execute(f"SELECT MIN(CAST({c} AS TEXT)) AS low, MAX(CAST({c} AS TEXT)) AS high FROM {t}").fetchone()
        low, high = extreme[0], extreme[1]
        first = db.execute(f"SELECT CAST({c} AS TEXT) AS v FROM {t} WHERE {c} IS NOT NULL ORDER BY 1 LIMIT 1").fetchone()
        sample = first[0] if first else None
        if (table, column) in MASKED:
            low = high = None
            sample = _mask_email(sample) if sample else None
    if (table, column) in SENSITIVE:
        sample = "[REDACTED]"
    return {"rows": total, "null_count": total - filled, "distinct": distinct, "min": low, "max": high, "sample": sample}


def _which_check(column: str, checks: list[str]) -> str:
    return " | ".join(check for check in checks if re.search(rf'(?<![A-Za-z_]){re.escape(column)}(?![A-Za-z_])', check))


def dictionary(db) -> list[dict]:
    """One row per column with type, keys, constraints, meaning, live statistics and masked sample."""
    cat = catalogue(db)
    rows = []
    for table in TABLES:
        if table not in cat:
            continue
        entry = cat[table]
        fk_by_col = {f["column"]: f for f in entry["fks"]}
        indexed = {c for index in entry["indexes"] for c in index["columns"]}
        for column in entry["columns"]:
            name = column["name"]
            fk = fk_by_col.get(name)
            stats = _stat(db, table, name)
            keys = []
            if column["pk"]:
                keys.append("PK")
            if fk:
                keys.append("FK")
            if name in entry["uniques"]:
                keys.append("UNIQUE")
            rows.append({
                "table": table, "table_purpose": TABLE_PURPOSE.get(table, ""), "ordinal": column["ord"], "column": name,
                "data_type": column["type"], "nullable": "YES" if column["nullable"] else "NO", "default": column["default"] or "",
                "keys": " ".join(keys), "references": f"{fk['ref_table']}.{fk['ref_column']}" if fk else "",
                "on_delete": fk["on_delete"] if fk else "", "check_constraint": _which_check(name, entry["checks"]),
                "indexed": "YES" if name in indexed or column["pk"] else "NO", "business_meaning": COLUMN_MEANING.get((table, name), ""),
                "sensitivity": "SECRET" if (table, name) in SENSITIVE else "PERSONAL" if (table, name) in MASKED or name in {"latitude", "longitude"} else "OPERATIONAL",
                "row_count": stats["rows"], "null_count": stats["null_count"], "distinct_values": stats["distinct"],
                "min_value": stats["min"], "max_value": stats["max"], "sample_value": stats["sample"],
            })
    return rows


def relationships(db) -> list[dict]:
    """Foreign keys with cardinality, optionality and a live orphan check (rows violating the link)."""
    cat = catalogue(db)
    rows = []
    for table in TABLES:
        entry = cat.get(table)
        if not entry:
            continue
        nullable = {c["name"]: c["nullable"] for c in entry["columns"]}
        for fk in entry["fks"]:
            if fk["ref_table"] not in cat:
                continue
            child, parent = _quote(table), _quote(fk["ref_table"])
            c_col, p_col = _quote(fk["column"]), _quote(fk["ref_column"])
            orphans = db.execute(f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON c.{c_col} = p.{p_col} WHERE c.{c_col} IS NOT NULL AND p.{p_col} IS NULL").fetchone()[0]
            linked = db.execute(f"SELECT COUNT(*) FROM {child} WHERE {c_col} IS NOT NULL").fetchone()[0]
            one_to_one = fk["column"] in entry["uniques"]
            rows.append({
                "child_table": table, "child_column": fk["column"], "parent_table": fk["ref_table"], "parent_column": fk["ref_column"],
                "cardinality": "one-to-one" if one_to_one else "many-to-one", "participation": "optional (0..1)" if nullable[fk["column"]] else "mandatory (1)",
                "on_delete": fk["on_delete"], "linked_rows": linked, "orphan_rows": orphans,
                "integrity": "OK" if orphans == 0 else "VIOLATION",
                "join_sql": f"SELECT * FROM {table} c JOIN {fk['ref_table']} p ON c.{fk['column']} = p.{fk['ref_column']}",
            })
    return rows


def constraints_report(db) -> list[dict]:
    cat = catalogue(db)
    rows = []
    for table in TABLES:
        entry = cat.get(table)
        if not entry:
            continue
        for column in entry["columns"]:
            if column["pk"]:
                rows.append({"table": table, "type": "PRIMARY KEY", "columns": column["name"], "rule": "Unique, non-null row identifier"})
        for name in sorted(entry["uniques"]):
            rows.append({"table": table, "type": "UNIQUE", "columns": name, "rule": "No two rows may share this value"})
        for fk in entry["fks"]:
            rows.append({"table": table, "type": "FOREIGN KEY", "columns": fk["column"], "rule": f"Must exist in {fk['ref_table']}.{fk['ref_column']} (on delete {fk['on_delete']})"})
        for check in entry["checks"]:
            rows.append({"table": table, "type": "CHECK", "columns": "", "rule": check})
        for column in entry["columns"]:
            if not column["nullable"] and not column["pk"]:
                rows.append({"table": table, "type": "NOT NULL", "columns": column["name"], "rule": "A value is required"})
        for index in entry["indexes"]:
            rows.append({"table": table, "type": "INDEX" + (" (unique)" if index["unique"] else ""), "columns": ", ".join(index["columns"]), "rule": index["name"]})
    return rows


def table_rows(db, table: str, limit: int = 5000) -> tuple[list[str], list[list]]:
    if table not in TABLES:
        raise ValueError("Unknown table")
    cat = catalogue(db)
    names = [c["name"] for c in cat[table]["columns"] if (table, c["name"]) not in SENSITIVE]
    cursor = db.execute(f"SELECT {', '.join(_quote(n) for n in names)} FROM {_quote(table)} ORDER BY 1 LIMIT {int(limit)}")
    data = []
    for row in cursor.fetchall():
        values = [row[n] for n in names] if hasattr(row, "keys") else list(row)
        data.append([_mask_email(v) if (table, n) in MASKED and v else v for n, v in zip(names, values)])
    return names, data


def _safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if re.match(r"^\s*[=+\-@]", text) else text


def to_csv(rows: list[dict] | tuple[list[str], list[list]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    if isinstance(rows, tuple):
        header, body = rows
        writer.writerow(header)
        writer.writerows([[_safe_cell(v) for v in row] for row in body])
    elif rows:
        writer.writerow(list(rows[0].keys()))
        writer.writerows([[_safe_cell(v) for v in row.values()] for row in rows])
    return "﻿" + buffer.getvalue()


def bundle(db, engine: str) -> bytes:
    """ZIP with the dictionary, relationships, constraints, every table's rows, a manifest and checksums."""
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    files = {
        "01_schema_dictionary.csv": to_csv(dictionary(db)),
        "02_relationships.csv": to_csv(relationships(db)),
        "03_constraints.csv": to_csv(constraints_report(db)),
    }
    counts = {}
    for position, table in enumerate(TABLES):
        header, body = table_rows(db, table)
        counts[table] = len(body)
        files[f"data/{position + 4:02d}_{table}.csv"] = to_csv((header, body))
    manifest = [
        "DMERS database export", f"Generated (UTC): {stamp}", f"Engine: {engine}", "",
        "Contents", "  01_schema_dictionary.csv  one row per column: type, keys, constraints, meaning, live statistics, masked sample",
        "  02_relationships.csv      every foreign key with cardinality, optionality and a live orphan check",
        "  03_constraints.csv        primary keys, unique, foreign keys, checks, not-null and indexes",
        "  data/*.csv                row data per table (password hashes omitted, e-mail addresses masked)", "",
        "Row counts", *[f"  {name}: {count}" for name, count in counts.items()], "",
        "Notes: spreadsheet formulas in cell text are neutralised with a leading apostrophe; files are UTF-8 with BOM.",
        "Each data file is capped at 5000 rows.",
    ]
    files["00_README.txt"] = "\n".join(manifest) + "\n"
    files["checksums.sha256"] = "".join(f"{hashlib.sha256(content.encode('utf-8')).hexdigest()}  {name}\n" for name, content in sorted(files.items()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return out.getvalue()
