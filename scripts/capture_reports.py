"""Reset the demonstration data and print every report as a Markdown table (real output for the Review III report).

    python scripts/capture_reports.py > docs/review3/report_outputs.md
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.getenv("DMERS_API", "http://127.0.0.1:5003")


def call(method, path, token=None, body=None):
    request = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def main() -> None:
    admin = call("POST", "/api/auth/login", body={"email": "admin@rescue.ai", "password": os.getenv("DMERS_ADMIN_PASSWORD", "Admin@123")})["token"]
    call("POST", "/api/response/demo/reset", admin)
    people = {p["name"]: p for p in call("GET", "/api/response/demo/personas", admin)["personas"]}
    coordinator = call("POST", "/api/response/demo/token", admin, {"user_id": people["Priya Natarajan"]["id"]})["token"]
    runs = [("active-incidents", ""), ("zone-situation", ""), ("command-board", ""), ("stock-status", "?only_low=true"), ("response-time", ""),
            ("unit-utilisation", ""), ("busiest-by-type", ""), ("incident-timeline", "?incident_id=3"), ("accountability", "?incident_id=7")]
    print("Reports run against the freshly reset demonstration data (the Review II history of 1-12 October 2026). Times are Asia/Kolkata.\n")
    for key, query in runs:
        report = call("GET", f"/api/response/reports/{key}{query}", coordinator)
        print(f"### {report['title']}\n")
        print(f"Requirement {report['requirement']} · Review II {report['review2_query']} · {report['sql_feature']}  \nParameters: {report['parameters'] or 'none'}\n")
        print("| " + " | ".join(report["columns"]) + " |")
        print("|" + "---|" * len(report["columns"]))
        for row in report["rows"]:
            print("| " + " | ".join("" if v is None else str(v).replace("|", "/") for v in row) + " |")
        print(f"\n{report['row_count']} row(s).\n")


if __name__ == "__main__":
    sys.exit(main())
