"""FR-06 and FR-09: administrator maintenance of zones, response units and relief items."""
from __future__ import annotations

import psycopg
import pytest

from tests.conftest import Api, PEOPLE, scalar

BASE = "/api/response"


def reference(api):
    return api.get(f"{BASE}/reference").get_json()


def audit_count(url, action, subject=None):
    if subject:
        return scalar(url, "SELECT count(*) FROM public.audit_entries WHERE action=%s AND subject=%s", (action, subject))
    return scalar(url, "SELECT count(*) FROM public.audit_entries WHERE action=%s", (action,))


def user_id(people, key):
    return people[key].user["id"]


# ------------------------------------------------------------------ zones
def test_create_and_edit_a_zone_with_trace_and_audit(people, pg_url):
    admin = people["admin"]
    r = admin.post(f"{BASE}/zones", json={"zone_name": "Katpadi North", "district": "Vellore", "risk_level": "high"})
    assert r.status_code == 201, r.get_json()
    zone = r.get_json()["zone"]
    assert zone["state"] == "Tamil Nadu" and zone["risk_level"] == "HIGH"          # DEFAULT state, upper-cased risk
    trace = r.get_json()["db_trace"]
    assert set(trace["tables_touched"]) >= {"zones", "audit_entries"} and trace["rows_affected"] == 2
    assert any(c.startswith("ck_zones") or c == "uq_zones_name" for c in trace["constraints_checked"])
    assert audit_count(pg_url, "ZONE_CREATED", "Katpadi North") == 1
    e = admin.patch(f"{BASE}/zones/{zone['id']}", json={"risk_level": "LOW"})
    assert e.status_code == 200 and e.get_json()["zone"]["risk_level"] == "LOW" and e.get_json()["zone"]["district"] == "Vellore"
    effect = e.get_json()["db_trace"]["effects"][0]
    assert effect["before"]["risk_level"] == "HIGH" and effect["after"]["risk_level"] == "LOW"
    assert audit_count(pg_url, "ZONE_UPDATED") == 1


@pytest.mark.parametrize("body,status,constraint", [
    ({"zone_name": "Vellore Town", "district": "Vellore", "risk_level": "LOW"}, 409, "uq_zones_name"),
    ({"zone_name": "Odd Zone", "district": "Vellore", "risk_level": "SEVERE"}, 422, "ck_zones_risk_level"),
    ({"zone_name": "", "district": "Vellore", "risk_level": "LOW"}, 400, None),
])
def test_zone_failures_leave_nothing_behind(body, status, constraint, people, pg_url):
    before = (scalar(pg_url, "SELECT count(*) FROM response.zones"), audit_count(pg_url, "ZONE_CREATED"))
    r = people["admin"].post(f"{BASE}/zones", json=body)
    assert r.status_code == status and r.get_json().get("constraint") == constraint
    assert (scalar(pg_url, "SELECT count(*) FROM response.zones"), audit_count(pg_url, "ZONE_CREATED")) == before
    if status != 400:
        assert r.get_json()["db_trace"]["rolled_back"] is True


def test_zone_edit_edge_cases(people):
    admin = people["admin"]
    assert admin.patch(f"{BASE}/zones/9999", json={"risk_level": "LOW"}).status_code == 404
    assert admin.patch(f"{BASE}/zones/1", json={}).status_code == 400
    assert admin.patch(f"{BASE}/zones/1", json={"zone_name": "Katpadi"}).get_json()["constraint"] == "uq_zones_name"


# ------------------------------------------------------------------ units
def new_unit(people, **over):
    ref = reference(people["admin"])
    zone = next(z["id"] for z in ref["zones"] if z["zone_name"] == "Vellore Town")
    body = {"unit_name": "Vellore Boat Team", "unit_type": "rescue", "contact_phone": "9000099999", "personnel_count": 6, "zone_id": zone, **over}
    return people["admin"].post(f"{BASE}/units", json=body)


def test_create_unit_without_lead_then_assign_a_lead(pg_app, people, pg_url):
    r = new_unit(people)
    assert r.status_code == 201, r.get_json()
    unit = r.get_json()["unit"]
    assert unit["availability_status"] == "AVAILABLE" and unit["unit_type"] == "RESCUE" and unit["lead_user_id"] is None   # DEFAULT availability
    assert audit_count(pg_url, "UNIT_CREATED", "Vellore Boat Team") == 1
    reg = pg_app.test_client().post("/api/auth/register", json={"name": "New Lead", "email": "new.lead@example.org", "password": "secret1", "role": "responder"})
    assert reg.status_code == 201
    lead_id = reg.get_json()["user"]["id"]
    e = people["admin"].patch(f"{BASE}/units/{unit['id']}", json={"lead_user_id": lead_id})
    assert e.status_code == 200 and e.get_json()["unit"]["lead_user_id"] == lead_id
    trace = e.get_json()["db_trace"]
    assert "trigger trg_units_lead_type" in trace["components"]                  # the new rule really fired
    assert trace["effects"][0]["before"]["lead_user_id"] is None and trace["effects"][0]["after"]["lead_user_id"] == lead_id
    cleared = people["admin"].patch(f"{BASE}/units/{unit['id']}", json={"lead_user_id": None})
    assert cleared.status_code == 200 and cleared.get_json()["unit"]["lead_user_id"] is None        # explicit null clears the lead
    kept = people["admin"].patch(f"{BASE}/units/{unit['id']}", json={"personnel_count": 9})
    assert kept.get_json()["unit"]["personnel_count"] == 9                       # omitted lead is left alone


def test_the_new_lead_can_then_record_progress(pg_app, people):
    """End to end: the lead the administrator assigns is the person sp_update_dispatch accepts."""
    unit = new_unit(people).get_json()["unit"]
    reg = pg_app.test_client().post("/api/auth/register", json={"name": "Field Lead", "email": "field.lead@example.org", "password": "secret1", "role": "responder"})
    people["admin"].patch(f"{BASE}/units/{unit['id']}", json={"lead_user_id": reg.get_json()["user"]["id"]})
    coord, citizen = people["coordinator"], people["citizen"]
    iid = citizen.post(f"{BASE}/incidents", json={"title": "Boat needed", "incident_type": "WATER_RESCUE", "location": "Lake"}).get_json()["incident"]["id"]
    coord.post(f"{BASE}/incidents/{iid}/verify", json={"zone_id": unit["zone_id"], "severity": "HIGH"})
    assert coord.post(f"{BASE}/incidents/{iid}/dispatch", json={"unit_id": unit["id"]}).status_code == 201
    lead = Api(pg_app, "field.lead@example.org", "secret1")
    assert lead.patch(f"{BASE}/dispatches/{iid}/{unit['id']}", json={"status": "EN_ROUTE"}).status_code == 200


@pytest.mark.parametrize("case", ["citizen_as_lead", "lead_already_leads", "bad_phone", "bad_type", "bad_zone", "zero_people", "duplicate_name"])
def test_unit_failures_are_refused_by_the_database_and_roll_back(case, people, pg_url):
    ref = reference(people["admin"])
    divya = next(l for l in ref["lead_candidates"] if l["name"] == "Divya Ramesh")
    over = {"citizen_as_lead": {"lead_user_id": user_id(people, "citizen")}, "lead_already_leads": {"lead_user_id": divya["id"]},
            "bad_phone": {"contact_phone": "12345"}, "bad_type": {"unit_type": "TANK"}, "bad_zone": {"zone_id": 9999},
            "zero_people": {"personnel_count": 0}, "duplicate_name": {"unit_name": "Katpadi Fire Unit"}}[case]
    before = (scalar(pg_url, "SELECT count(*) FROM response.response_units"), audit_count(pg_url, "UNIT_CREATED"))
    r = new_unit(people, **over)
    expected = {"citizen_as_lead": (422, None), "lead_already_leads": (409, "uq_units_lead"), "bad_phone": (422, "ck_units_phone"),
                "bad_type": (422, "ck_units_type"), "bad_zone": (422, "fk_units_zone"), "zero_people": (400, None), "duplicate_name": (409, "uq_units_name")}[case]
    assert (r.status_code, r.get_json().get("constraint")) == expected, r.get_json()
    if case == "citizen_as_lead":
        assert "UNIT_LEAD" in r.get_json()["error"]                       # the trigger's own message
        assert "trigger trg_units_lead_type" in r.get_json()["db_trace"]["components"]
    assert (scalar(pg_url, "SELECT count(*) FROM response.response_units"), audit_count(pg_url, "UNIT_CREATED")) == before


def test_moving_a_unit_to_another_zone(people):
    ref = reference(people["admin"])
    unit = next(u for u in ref["units"] if u["unit_name"] == "Katpadi Fire Unit")
    other = next(z["id"] for z in ref["zones"] if z["id"] != unit["zone_id"])
    r = people["admin"].patch(f"{BASE}/units/{unit['id']}", json={"zone_id": other})
    assert r.status_code == 200 and r.get_json()["unit"]["zone_id"] == other
    assert people["admin"].patch(f"{BASE}/units/{unit['id']}", json={"zone_id": 9999}).get_json()["constraint"] == "fk_units_zone"


# ------------------------------------------------------------------ relief catalogue
def test_add_and_edit_a_relief_item(people, pg_url):
    admin = people["admin"]
    r = admin.post(f"{BASE}/resources", json={"resource_name": "Life buoys", "category": "equipment", "unit_of_measure": "pieces", "quantity_available": 8, "reorder_level": 10})
    assert r.status_code == 201, r.get_json()
    item = r.get_json()["resource"]
    assert item["stock_status"] == "LOW" and "function fn_stock_status" in r.get_json()["db_trace"]["components"]      # 8 <= 10
    assert audit_count(pg_url, "RESOURCE_CREATED", "Life buoys") == 1
    e = admin.patch(f"{BASE}/resources/{item['id']}", json={"reorder_level": 5, "unit_of_measure": "buoys"})
    assert e.status_code == 200 and e.get_json()["resource"]["stock_status"] == "ADEQUATE"
    assert e.get_json()["resource"]["quantity_available"] == 8             # stock is never edited here
    assert admin.patch(f"{BASE}/resources/{item['id']}", json={"quantity_available": 999}).status_code == 400
    admin.post(f"{BASE}/resources/{item['id']}/restock", json={"quantity": 2})
    assert scalar(pg_url, "SELECT quantity_available FROM response.resources WHERE id=%s", (item["id"],)) == 10


@pytest.mark.parametrize("body,status,constraint", [
    ({"resource_name": "Blankets", "category": "SHELTER", "unit_of_measure": "pieces"}, 409, "uq_resources_name"),
    ({"resource_name": "Odd", "category": "TOYS", "unit_of_measure": "pieces"}, 422, "ck_resources_category"),
    ({"resource_name": "Odd", "category": "FOOD", "unit_of_measure": "pieces", "quantity_available": -5}, 422, "ck_resources_quantity"),
    ({"resource_name": "Odd", "category": "FOOD", "unit_of_measure": "pieces", "reorder_level": -1}, 422, "ck_resources_reorder"),
])
def test_relief_item_failures_roll_back(body, status, constraint, people, pg_url):
    before = (scalar(pg_url, "SELECT count(*) FROM response.resources"), audit_count(pg_url, "RESOURCE_CREATED"))
    r = people["admin"].post(f"{BASE}/resources", json=body)
    assert (r.status_code, r.get_json().get("constraint")) == (status, constraint), r.get_json()
    assert (scalar(pg_url, "SELECT count(*) FROM response.resources"), audit_count(pg_url, "RESOURCE_CREATED")) == before


# ------------------------------------------------------------------ authorisation
@pytest.mark.parametrize("who", ["coordinator", "lead", "citizen"])
def test_only_administrators_may_maintain_reference_data(who, people, pg_app):
    api = people[who]
    calls = [("post", f"{BASE}/zones", {"zone_name": "X", "district": "Y", "risk_level": "LOW"}), ("patch", f"{BASE}/zones/1", {"risk_level": "LOW"}),
             ("post", f"{BASE}/units", {"unit_name": "X"}), ("patch", f"{BASE}/units/1", {"personnel_count": 3}),
             ("post", f"{BASE}/resources", {"resource_name": "X"}), ("patch", f"{BASE}/resources/1", {"reorder_level": 3})]
    for verb, path, body in calls:
        assert getattr(api, verb)(path, json=body).status_code == 403, (who, verb, path)
    assert getattr(pg_app.test_client(), "post")(f"{BASE}/zones", json={}).status_code == 401


def test_reference_lists_lead_candidates(people):
    ref = reference(people["admin"])
    names = {l["name"]: l["leads_unit"] for l in ref["lead_candidates"]}
    assert names["Divya Ramesh"] == "Katpadi Fire Unit" and "Gopal Iyer" not in names      # only UNIT_LEAD accounts are offered


# ------------------------------------------------------------------ migration 003
def test_migration_003_is_recorded_and_enforced_in_sql(pg_url):
    with psycopg.connect(pg_url) as conn:
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY 1").fetchall()] == ["001", "002", "003"]
        with pytest.raises(psycopg.errors.RaiseException, match="not UNIT_LEAD"):
            conn.execute("UPDATE response.response_units SET lead_user_id = (SELECT id FROM public.users WHERE email = 'gopal.iyer@mail.example.com') WHERE id = 3")


def test_every_seeded_lead_satisfies_the_rule(pg_url):
    assert scalar(pg_url, "SELECT count(*) FROM response.response_units r JOIN public.users u ON u.id = r.lead_user_id WHERE u.account_type <> 'UNIT_LEAD'") == 0
