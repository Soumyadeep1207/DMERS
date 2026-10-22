"""Headless Review III demonstration: User Operation -> SQL/PL-SQL -> Database processing -> Result.

Runs transactions T1-T10 against the running API, each as the right person, including the failure
paths that must roll back. Every step prints its ``db_trace`` (what the database really did) and the
whole output is written to docs/review3/demo_run_log.txt, the evidence used in the report.

    python scripts/demo_transactions.py [--base http://127.0.0.1:5003] [--no-reset]

Needs the stack running with DMERS_DEMO_MODE=1 (the default in docker-compose.yml) and the seeded
admin account. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "docs" / "review3" / "demo_run_log.txt"
lines: list[str] = []
failures: list[str] = []


def out(text: str = "") -> None:
    print(text)
    lines.append(text)


class Api:
    def __init__(self, base: str, token: str | None = None):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")


def show_trace(trace: dict | None) -> None:
    if not trace:
        return
    out(f"      operation   : {trace['operation']} ({trace['outcome'].upper()}, {trace['duration_ms']} ms)")
    out(f"      components  : {', '.join(trace['components']) or '(none beyond the statement itself)'}")
    out(f"      tables      : {', '.join(trace['tables_touched'])}")
    changes = trace.get("row_changes") or {}
    if changes:
        out("      rows changed: " + "; ".join(f"{t} " + "/".join(f"{k} {v}" for k, v in c.items()) for t, c in changes.items()) + f"  (total {trace['rows_affected']})")
    for note in trace.get("notices", []):
        out(f"      NOTICE      : {note}")
    for e in trace.get("effects", []):
        tag = "unchanged (rolled back)" if e.get("unchanged") else "now"
        out(f"      {e['label']:<18}: {json.dumps(e['before'], default=str)} -> {json.dumps(e['after'], default=str)}  [{tag}]")
    if trace.get("failure"):
        f = trace["failure"]
        out(f"      failed with : sqlstate {f.get('sqlstate')} {('constraint ' + f['constraint']) if f.get('constraint') else ''}".rstrip())
    out("      statements  :")
    for sql, status in zip(trace["statements"], trace.get("statement_status", [])):
        out(f"        [{status}] {sql[:150]}")


step_no = 0


def step(title: str, api: Api, method: str, path: str, body: dict | None = None, expect: int = 200, who: str = "") -> dict:
    global step_no
    step_no += 1
    status, payload = api.call(method, path, body)
    ok = status == expect
    out(f"\n[{step_no:02d}] {title}")
    out(f"      user        : {who or 'anonymous'}")
    out(f"      request     : {method} {path}")
    out(f"      result      : HTTP {status} {'(as expected)' if ok else f'(EXPECTED {expect})'}" + (f" - {payload.get('error')}" if payload.get("error") else ""))
    if payload.get("constraint"):
        out(f"      constraint  : {payload['constraint']}")
    show_trace(payload.get("db_trace"))
    if not ok:
        failures.append(f"step {step_no}: {title} -> HTTP {status}, wanted {expect}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("DMERS_API", "http://127.0.0.1:5003"))
    parser.add_argument("--no-reset", action="store_true", help="do not reload the demonstration data first")
    args = parser.parse_args()

    out("DMERS Review III - transaction demonstration")
    out(f"Run at {datetime.now().astimezone().isoformat(timespec='seconds')} against {args.base}")
    out("Flow shown for each step: user operation -> SQL / PL-pgSQL -> database processing -> update or retrieval -> result")

    anon = Api(args.base)
    status, health = anon.call("GET", "/health")
    model = health.get("response_model", {})
    out(f"\nHealth: HTTP {status}, database {health.get('database', {}).get('engine')}, migration level {model.get('migration_level')}, "
        f"response model ok={model.get('ok')}, rows {model.get('row_counts')}")
    if not model.get("installed"):
        out("The response model is not installed; aborting.")
        return 2

    status, login = anon.call("POST", "/api/auth/login", {"email": "admin@rescue.ai", "password": os.getenv("DMERS_ADMIN_PASSWORD", "Admin@123")})
    if status != 200:
        out(f"Could not sign in as the seeded administrator (HTTP {status}).")
        return 2
    admin = Api(args.base, login["token"])
    if not args.no_reset:
        status, reset = admin.call("POST", "/api/response/demo/reset")
        out(f"Demonstration data reset: HTTP {status} {reset.get('reset', {}).get('counts') or reset.get('error')}")
    status, personas = admin.call("GET", "/api/response/demo/personas")
    if status != 200:
        out(f"Demo mode is off or the administrator is not an ADMINISTRATOR account (HTTP {status}).")
        return 2
    by_name = {p["name"]: p for p in personas["personas"]}

    def as_person(name: str) -> Api:
        status, token = admin.call("POST", "/api/response/demo/token", {"user_id": by_name[name]["id"]})
        assert status == 200, token
        return Api(args.base, token["token"])

    citizen, coordinator, lead, admin_person = (as_person(n) for n in ("Gopal Iyer", "Priya Natarajan", "Divya Ramesh", "Meena Krishnan"))
    ref = coordinator.call("GET", "/api/response/reference")[1]
    unit = {u["unit_name"]: u for u in ref["units"]}
    res = {r["resource_name"]: r for r in ref["resources"]}
    zone = {z["zone_name"]: z["id"] for z in ref["zones"]}
    stamp = int(time.time())
    out("\nPeople: citizen Gopal Iyer, coordinator Priya Natarajan, unit lead Divya Ramesh (Katpadi Fire Unit), administrator Meena Krishnan")

    out("\n=== T1  Register and sign in  (users: UNIQUE e-mail, derived account_type, password hash only)")
    email = f"demo.citizen.{stamp}@example.org"
    step("Register a new citizen", anon, "POST", "/api/auth/register", {"name": "Demo Citizen", "email": email, "password": "Demo@12345", "role": "citizen"}, 201, "anonymous")
    step("Register the same e-mail again (UNIQUE rejects, rolled back)", anon, "POST", "/api/auth/register", {"name": "Demo Citizen", "email": email, "password": "Demo@12345"}, 409, "anonymous")
    step("Sign in", anon, "POST", "/api/auth/login", {"email": email, "password": "Demo@12345"}, 200, "Demo Citizen")

    out("\n=== T2  Report an incident  (INSERT -> trigger T1 writes timeline entry 1)")
    r = step("Citizen reports a fire", citizen, "POST", "/api/response/incidents", {"title": "Smoke from a warehouse near the Fort", "incident_type": "FIRE", "location": "Fort Round Road, Vellore", "description": "Heavy smoke, people outside"}, 201, "Gopal Iyer (CITIZEN)")
    iid = r["incident"]["id"]

    out("\n=== T3  Verify a report  (CHECK ck_incidents_zone_when_verified, triggers T2 and T1)")
    step("A citizen cannot verify (server-side role check)", citizen, "POST", f"/api/response/incidents/{iid}/verify", {"zone_id": zone["Vellore Town"], "severity": "HIGH"}, 403, "Gopal Iyer (CITIZEN)")
    step("Dispatch before verification (guard trigger T3 rejects)", coordinator, "POST", f"/api/response/incidents/{iid}/dispatch", {"unit_id": unit["Katpadi Fire Unit"]["id"]}, 422, "Priya Natarajan (COORDINATOR)")
    step("Verify with a non-existent zone (foreign key rejects)", coordinator, "POST", f"/api/response/incidents/{iid}/verify", {"zone_id": 9999, "severity": "HIGH"}, 422, "Priya Natarajan (COORDINATOR)")
    step("Coordinator verifies: zone Vellore Town, severity HIGH", coordinator, "POST", f"/api/response/incidents/{iid}/verify", {"zone_id": zone["Vellore Town"], "severity": "HIGH", "note": "Confirmed by caller and photos"}, 200, "Priya Natarajan (COORDINATOR)")

    out("\n=== T4  Dispatch a unit  (CALL sp_dispatch_unit -> guard trigger T3 -> unit DEPLOYED -> incident RESPONDING)")
    step("Dispatch SDRF Team Alpha, already deployed (BR-05 rejects, rolled back)", coordinator, "POST", f"/api/response/incidents/{iid}/dispatch", {"unit_id": unit["SDRF Team Alpha"]["id"]}, 422, "Priya Natarajan (COORDINATOR)")
    step("Dispatch Katpadi Fire Unit", coordinator, "POST", f"/api/response/incidents/{iid}/dispatch", {"unit_id": unit["Katpadi Fire Unit"]["id"]}, 201, "Priya Natarajan (COORDINATOR)")

    out("\n=== T5  Record unit progress  (CALL sp_update_dispatch: only the unit's lead, legal order only)")
    uid = unit["Katpadi Fire Unit"]["id"]
    step("A citizen tries to move the dispatch (not the lead)", citizen, "PATCH", f"/api/response/dispatches/{iid}/{uid}", {"status": "EN_ROUTE"}, 422, "Gopal Iyer (CITIZEN)")
    step("Lead: EN_ROUTE", lead, "PATCH", f"/api/response/dispatches/{iid}/{uid}", {"status": "EN_ROUTE"}, 200, "Divya Ramesh (UNIT_LEAD)")
    step("Lead: jump to COMPLETED (illegal order, rolled back)", lead, "PATCH", f"/api/response/dispatches/{iid}/{uid}", {"status": "COMPLETED"}, 422, "Divya Ramesh (UNIT_LEAD)")
    step("Lead: ON_SCENE (arrival time recorded, CHECK ck_dispatches_arrival)", lead, "PATCH", f"/api/response/dispatches/{iid}/{uid}", {"status": "ON_SCENE"}, 200, "Divya Ramesh (UNIT_LEAD)")

    out("\n=== T6  Allocate relief  (INSERT ... ON CONFLICT DO UPDATE -> AFTER trigger T4 moves stock)")
    blankets = res["Blankets"]["id"]
    step("Allocate 30 blankets", coordinator, "POST", f"/api/response/incidents/{iid}/allocations", {"resource_id": blankets, "quantity": 30}, 201, "Priya Natarajan (COORDINATOR)")
    step("Allocate 20 more (cumulative: quantity becomes 50)", coordinator, "POST", f"/api/response/incidents/{iid}/allocations", {"resource_id": blankets, "quantity": 20}, 201, "Priya Natarajan (COORDINATOR)")
    step("Allocate an inflatable boat, none in stock (trigger refuses, rolled back)", coordinator, "POST", f"/api/response/incidents/{iid}/allocations", {"resource_id": res["Inflatable rescue boats"]["id"], "quantity": 1}, 422, "Priya Natarajan (COORDINATOR)")

    out("\n=== T9a Withdraw a mistaken allocation  (DELETE -> trigger T4 returns the stock)")
    step("Withdraw the blanket allocation", coordinator, "DELETE", f"/api/response/incidents/{iid}/allocations/{blankets}", None, 200, "Priya Natarajan (COORDINATOR)")

    out("\n=== T7  Close the incident  (CALL sp_close_incident: explicit cursor releases every active unit)")
    step("Close the incident", coordinator, "POST", f"/api/response/incidents/{iid}/close", {"note": "Fire out, area made safe"}, 200, "Priya Natarajan (COORDINATOR)")
    step("Close it again (status CLOSED cannot be closed, rolled back)", coordinator, "POST", f"/api/response/incidents/{iid}/close", {"note": "again"}, 422, "Priya Natarajan (COORDINATOR)")

    out("\n=== T8  Restock relief items  (UPDATE resources; fn_stock_status read in a separate SELECT)")
    boats = res["Inflatable rescue boats"]["id"]
    step("A coordinator cannot restock (administrator only)", coordinator, "POST", f"/api/response/resources/{boats}/restock", {"quantity": 3}, 403, "Priya Natarajan (COORDINATOR)")
    step("Administrator adds 3 boats (stock status OUT_OF_STOCK -> LOW)", admin_person, "POST", f"/api/response/resources/{boats}/restock", {"quantity": 3}, 200, "Meena Krishnan (ADMINISTRATOR)")
    step("Remove more boats than exist (CHECK ck_resources_quantity, rolled back)", admin_person, "POST", f"/api/response/resources/{boats}/restock", {"quantity": -50}, 422, "Meena Krishnan (ADMINISTRATOR)")

    out("\n=== T9b Delete a rejected duplicate report  (ON DELETE CASCADE removes its timeline; RESTRICT protects history)")
    dup = step("Citizen files a duplicate report", citizen, "POST", "/api/response/incidents", {"title": "Same fire, second report", "incident_type": "FIRE", "location": "Fort Round Road, Vellore"}, 201, "Gopal Iyer (CITIZEN)")["incident"]["id"]
    step("Coordinator rejects it as a duplicate", coordinator, "POST", f"/api/response/incidents/{dup}/reject", {"note": f"Duplicate of incident {iid}"}, 200, "Priya Natarajan (COORDINATOR)")
    step("Delete the rejected duplicate (timeline removed by cascade)", coordinator, "DELETE", f"/api/response/incidents/{dup}", None, 200, "Priya Natarajan (COORDINATOR)")
    step("Delete incident with dispatch history (ON DELETE RESTRICT, HTTP 409)", coordinator, "DELETE", f"/api/response/incidents/{iid}", None, 409, "Priya Natarajan (COORDINATOR)")

    out("\n=== T10 Edit the timeline  (append-only trigger T5, negative demonstration)")
    step("Try to rewrite timeline entry 1", admin_person, "POST", "/api/response/debug/edit-timeline", {"incident_id": iid, "update_no": 1, "note": "tampered"}, 422, "Meena Krishnan (ADMINISTRATOR)")

    out("\n=== T11 Administrator maintenance of reference data  (FR-06 zones and units, FR-09 relief catalogue)")
    zname, uname, rname = f"Demo Zone {stamp}", f"Demo Unit {stamp}", f"Demo item {stamp}"
    zone_new = step("Administrator adds a zone", admin_person, "POST", "/api/response/zones", {"zone_name": zname, "district": "Vellore", "risk_level": "MEDIUM"}, 201, "Meena Krishnan (ADMINISTRATOR)")["zone"]["id"]
    step("Add the same zone again (UNIQUE rejects, rolled back)", admin_person, "POST", "/api/response/zones", {"zone_name": zname, "district": "Vellore", "risk_level": "LOW"}, 409, "Meena Krishnan (ADMINISTRATOR)")
    unit_new = step("Administrator adds a response unit in the new zone", admin_person, "POST", "/api/response/units", {"unit_name": uname, "unit_type": "RESCUE", "contact_phone": "9000088888", "personnel_count": 5, "zone_id": zone_new}, 201, "Meena Krishnan (ADMINISTRATOR)")["unit"]["id"]
    step("Make a citizen the unit lead (trigger trg_units_lead_type refuses)", admin_person, "PATCH", f"/api/response/units/{unit_new}", {"lead_user_id": by_name["Gopal Iyer"]["id"]}, 422, "Meena Krishnan (ADMINISTRATOR)")
    step("Give the unit a lead who already leads another (UNIQUE uq_units_lead)", admin_person, "PATCH", f"/api/response/units/{unit_new}", {"lead_user_id": by_name["Divya Ramesh"]["id"]}, 409, "Meena Krishnan (ADMINISTRATOR)")
    step("Administrator adds a relief item (stock 5, reorder level 10: LOW)", admin_person, "POST", "/api/response/resources", {"resource_name": rname, "category": "WATER", "unit_of_measure": "cans", "quantity_available": 5, "reorder_level": 10}, 201, "Meena Krishnan (ADMINISTRATOR)")
    step("Add an item with negative opening stock (CHECK rejects)", admin_person, "POST", "/api/response/resources", {"resource_name": rname + " B", "category": "FOOD", "unit_of_measure": "packets", "quantity_available": -5}, 422, "Meena Krishnan (ADMINISTRATOR)")
    step("A coordinator cannot add a zone", coordinator, "POST", "/api/response/zones", {"zone_name": "X", "district": "Y", "risk_level": "LOW"}, 403, "Priya Natarajan (COORDINATOR)")

    out("\n=== Reports  (read-only SQL from Review II, run against live data)")
    for key, params in (("zone-situation", ""), ("command-board", ""), ("stock-status", "?only_low=true"), ("incident-timeline", f"?incident_id={iid}")):
        status, report = coordinator.call("GET", f"/api/response/reports/{key}{params}")
        out(f"\n  {report.get('title')} - {report.get('requirement')} / Review II {report.get('review2_query')} / {report.get('sql_feature')}")
        out("  " + " | ".join(report.get("columns", [])))
        for row in report.get("rows", [])[:8]:
            out("  " + " | ".join("" if v is None else str(v) for v in row))
        if status != 200:
            failures.append(f"report {key}: HTTP {status}")

    out("\n" + ("All steps behaved as expected." if not failures else "UNEXPECTED RESULTS:\n  " + "\n  ".join(failures)))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nLog written to {LOG}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
