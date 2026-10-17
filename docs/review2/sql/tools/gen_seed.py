"""Generates sql/03_seed_data.sql: reference data plus a time-ordered replay of incident events.

Every incident event is replayed with explicit timestamps through ordinary DML, so the
triggers created in 02_plpgsql.sql (timeline, guard, stock, touch) act on the seed data
exactly as they do in live operation. All names, e-mail addresses and phone numbers are
fictitious demonstration data.
"""
from pathlib import Path
from werkzeug.security import generate_password_hash

OUT = Path(__file__).resolve().parent.parent / "sql" / "03_seed_data.sql"
DEMO_PASSWORD = "Dmers@2026"

USERS = [  # full_name, account_type, email, created_at
    ("Meena Krishnan", "ADMINISTRATOR", "meena.krishnan@dmers.example.org", "2026-09-01 09:00"),
    ("Rajesh Subramanian", "COORDINATOR", "rajesh.subramanian@dmers.example.org", "2026-09-01 09:10"),
    ("Priya Natarajan", "COORDINATOR", "priya.natarajan@dmers.example.org", "2026-09-01 09:15"),
    ("Karthik Raman", "COORDINATOR", "karthik.raman@dmers.example.org", "2026-09-02 10:00"),
    ("Suresh Babu", "UNIT_LEAD", "suresh.babu@dmers.example.org", "2026-09-03 11:00"),
    ("Lakshmi Narayanan", "UNIT_LEAD", "lakshmi.narayanan@dmers.example.org", "2026-09-03 11:05"),
    ("Arun Prakash", "UNIT_LEAD", "arun.prakash@dmers.example.org", "2026-09-03 11:10"),
    ("Divya Ramesh", "UNIT_LEAD", "divya.ramesh@dmers.example.org", "2026-09-03 11:15"),
    ("Mohammed Irfan", "UNIT_LEAD", "mohammed.irfan@dmers.example.org", "2026-09-04 10:30"),
    ("Anitha Selvam", "CITIZEN", "anitha.selvam@mail.example.com", "2026-09-08 18:20"),
    ("Gopal Iyer", "CITIZEN", "gopal.iyer@mail.example.com", "2026-09-10 08:45"),
    ("Fathima Begum", "CITIZEN", "fathima.begum@mail.example.com", "2026-09-12 20:05"),
    ("Senthil Kumar", "CITIZEN", "senthil.kumar@mail.example.com", "2026-09-15 07:30"),
    ("Revathi Shankar", "CITIZEN", "revathi.shankar@mail.example.com", "2026-09-18 12:40"),
    ("Joseph Antony", "CITIZEN", "joseph.antony@mail.example.com", "2026-09-21 16:10"),
    ("Kavya Reddy", "CITIZEN", "kavya.reddy@mail.example.com", "2026-09-25 22:15"),
]

ZONES = [  # zone_name, district, risk_level  (state takes its DEFAULT)
    ("Vellore Town", "Vellore", "HIGH"), ("Katpadi", "Vellore", "MEDIUM"),
    ("Sathuvachari", "Vellore", "HIGH"), ("Gandhi Nagar", "Vellore", "LOW"),
    ("Gudiyatham", "Vellore", "HIGH"), ("Pernambut", "Vellore", "MEDIUM"),
    ("Anaicut", "Vellore", "MEDIUM"), ("Arcot", "Ranipet", "MEDIUM"),
    ("Walajapet", "Ranipet", "LOW"), ("Ranipet", "Ranipet", "MEDIUM"),
    ("Ambur", "Tirupattur", "MEDIUM"), ("Vaniyambadi", "Tirupattur", "LOW"),
]

UNITS = [  # unit_name, unit_type, contact_phone, personnel_count, zone_id, lead_user_id
    ("Vellore Fire and Rescue", "FIRE", "9000010101", 12, 1, 5),
    ("Katpadi Fire Unit", "FIRE", "9000010102", 8, 2, 8),
    ("Gudiyatham Fire Unit", "FIRE", "9000010103", 9, 5, None),
    ("Ambulance VLR-01", "MEDICAL", "9000010104", 4, 1, 6),
    ("Ambulance KPD-02", "MEDICAL", "9000010105", 3, 2, None),
    ("Ambulance AMB-03", "MEDICAL", "9000010106", 3, 11, None),
    ("Katpadi Police Patrol", "POLICE", "9000010107", 6, 2, None),
    ("Vellore North Police", "POLICE", "9000010108", 10, 1, None),
    ("SDRF Team Alpha", "RESCUE", "9000010109", 18, 1, 7),
    ("SDRF Team Bravo", "RESCUE", "9000010110", 15, 8, None),
    ("Relief Unit Ranipet", "RELIEF", "9000010111", 7, 10, 9),
    ("Relief Unit Gudiyatham", "RELIEF", "9000010112", 6, 5, None),
]

RESOURCES = [  # resource_name, category, unit_of_measure, quantity_available, reorder_level
    ("Food packets", "FOOD", "packets", 1500, 300),
    ("Rice bags (25 kg)", "FOOD", "bags", 220, 50),
    ("Drinking water cans (20 L)", "WATER", "cans", 900, 200),
    ("Water purification tablets", "WATER", "strips", 400, 100),
    ("First-aid kits", "MEDICAL", "kits", 160, 40),
    ("ORS sachets", "MEDICAL", "sachets", 2000, 500),
    ("Blankets", "SHELTER", "pieces", 600, 150),
    ("Tarpaulin sheets", "SHELTER", "sheets", 250, 60),
    ("Family tents", "SHELTER", "tents", 40, 10),
    ("Life jackets", "EQUIPMENT", "pieces", 120, 30),
    ("Inflatable rescue boats", "EQUIPMENT", "boats", 6, 2),
    ("Portable generators", "EQUIPMENT", "units", 8, 3),
]

UNIT_NAME = {i + 1: u[0] for i, u in enumerate(UNITS)}
RES_NAME = {i + 1: r[0] for i, r in enumerate(RESOURCES)}

# Incident reports: key -> (reporter, reported_at, title, description, type, location)
REPORTS = {
    "boat":     (15, "2026-10-01 07:40", "Boat capsized in Walajapet lake",
                 "Country boat with five people capsized during strong winds", "WATER_RESCUE",
                 "Lake bund road, Walajapet"),
    "ambur":    (12, "2026-10-01 14:05", "Passenger collapsed at Ambur bus stand",
                 "Elderly passenger unconscious, breathing", "MEDICAL", "New bus stand, Ambur"),
    "godown":   (11, "2026-10-02 11:20", "Fire at textile godown",
                 "Smoke from a cotton yarn godown; workers evacuated", "FIRE", "Market Road, Gudiyatham"),
    "lpg":      (16, "2026-10-02 21:45", "LPG cylinder leak in hostel kitchen",
                 "Strong gas smell; kitchen staff left the building", "GAS_LEAK", "Gandhi Road hostel, Katpadi"),
    "collision": (14, "2026-10-05 18:20", "Two-wheeler collision at Katpadi junction",
                 "Two riders injured; traffic blocked", "ROAD_ACCIDENT", "Katpadi railway junction"),
    "tree":     (15, "2026-10-07 16:05", "Tree fall blocking Arcot Road",
                 "Large tree across both lanes after gusty wind", "TREE_FALL", "Arcot Road, Sathuvachari"),
    "palar":    (10, "2026-10-10 05:50", "Palar river overflow near Vellore Fort",
                 "Water entering low-lying streets; residents stranded", "FLOOD", "Fort Round Road, Vellore"),
    "dup":      (13, "2026-10-10 06:25", "Water entering houses near the Fort",
                 "Houses flooded near the moat", "FLOOD", "Fort Round Road, Vellore"),
    "sathu":    (14, "2026-10-10 09:30", "Waterlogging in Sathuvachari low-lying streets",
                 "Knee-deep water in three streets; drains blocked", "FLOOD", "Phase 2, Sathuvachari"),
    "anaicut":  (4, "2026-10-11 07:15", "Rising water level at Anaicut check dam",
                 "Field inspection: level near the spillway crest", "FLOOD", "Check dam road, Anaicut"),
    "efire":    (16, "2026-10-11 20:30", "Electrical fire in apartment block",
                 "Meter room on fire; smoke on two floors", "FIRE", "Officers Line, Vellore"),
    "snake":    (12, "2026-10-11 22:10", "Snake bite case in Anaicut village",
                 "Farm worker bitten; no transport available", "MEDICAL", "Ussoor Road, Anaicut"),
    "yelagiri": (15, "2026-10-12 06:30", "Boulders on Yelagiri ghat road",
                 "Rocks fallen at hairpin bend 7; road partly blocked", "LANDSLIDE", "Yelagiri ghat road"),
    "wall":     (11, "2026-10-12 08:40", "Compound wall collapse after heavy rain",
                 "Wall fell on two houses; one person trapped", "BUILDING_COLLAPSE", "Bazaar Street, Pernambut"),
}

# Events: (timestamp, kind, args...)
E = []
def ev(ts, kind, *args):
    E.append((ts, len(E), kind, args))

for key, (rep, ts, *_rest) in REPORTS.items():
    ev(ts, "report", key)

def lifecycle(key, steps):
    for s in steps:
        ev(s[0], s[1], key, *s[2:])

lifecycle("boat", [("2026-10-01 07:48", "verify", 4, "HIGH", 9),
                   ("2026-10-01 07:50", "dispatch", 9, 4), ("2026-10-01 07:53", "enroute", 9),
                   ("2026-10-01 07:55", "dispatch", 4, 4), ("2026-10-01 07:58", "enroute", 4),
                   ("2026-10-01 08:20", "cancel", 4), ("2026-10-01 08:34", "onscene", 9),
                   ("2026-10-01 09:15", "allocate", 7, 50, 4), ("2026-10-01 10:30", "complete", 9),
                   ("2026-10-01 10:40", "status", "RESOLVED", 4), ("2026-10-01 18:00", "status", "CLOSED", 4)])
lifecycle("ambur", [("2026-10-01 14:10", "verify", 3, "MODERATE", 11),
                    ("2026-10-01 14:12", "dispatch", 6, 3), ("2026-10-01 14:13", "enroute", 6),
                    ("2026-10-01 14:26", "onscene", 6), ("2026-10-01 15:05", "complete", 6),
                    ("2026-10-01 15:10", "status", "RESOLVED", 3), ("2026-10-01 17:30", "status", "CLOSED", 3)])
lifecycle("godown", [("2026-10-02 11:26", "verify", 3, "HIGH", 5),
                     ("2026-10-02 11:28", "dispatch", 3, 3), ("2026-10-02 11:29", "enroute", 3),
                     ("2026-10-02 11:41", "onscene", 3), ("2026-10-02 11:45", "dispatch", 12, 3),
                     ("2026-10-02 11:50", "enroute", 12), ("2026-10-02 12:05", "allocate", 5, 20, 3),
                     ("2026-10-02 12:15", "onscene", 12), ("2026-10-02 13:30", "allocate", 8, 40, 3),
                     ("2026-10-02 15:10", "complete", 3), ("2026-10-02 16:00", "complete", 12),
                     ("2026-10-02 16:10", "status", "RESOLVED", 3), ("2026-10-03 10:00", "status", "CLOSED", 3)])
lifecycle("lpg", [("2026-10-02 21:50", "verify", 2, "MODERATE", 2),
                  ("2026-10-02 21:52", "dispatch", 2, 2), ("2026-10-02 21:53", "enroute", 2),
                  ("2026-10-02 22:03", "onscene", 2), ("2026-10-02 23:05", "complete", 2),
                  ("2026-10-02 23:10", "status", "RESOLVED", 2), ("2026-10-03 09:00", "status", "CLOSED", 2)])
ev("2026-10-05 09:00", "offduty", 12)
lifecycle("collision", [("2026-10-05 18:24", "verify", 4, "HIGH", 2),
                        ("2026-10-05 18:25", "dispatch", 5, 4), ("2026-10-05 18:26", "enroute", 5),
                        ("2026-10-05 18:27", "dispatch", 7, 4), ("2026-10-05 18:28", "enroute", 7),
                        ("2026-10-05 18:34", "onscene", 7), ("2026-10-05 18:36", "onscene", 5),
                        ("2026-10-05 19:20", "complete", 5), ("2026-10-05 20:05", "complete", 7),
                        ("2026-10-05 20:10", "status", "RESOLVED", 4)])
lifecycle("tree", [("2026-10-07 16:15", "verify", 2, "LOW", 3),
                   ("2026-10-07 16:18", "dispatch", 1, 2), ("2026-10-07 16:20", "enroute", 1),
                   ("2026-10-07 16:37", "onscene", 1), ("2026-10-07 18:30", "complete", 1),
                   ("2026-10-07 18:35", "status", "RESOLVED", 2)])
lifecycle("palar", [("2026-10-10 06:02", "verify", 2, "CRITICAL", 1),
                    ("2026-10-10 06:05", "dispatch", 9, 2), ("2026-10-10 06:07", "enroute", 9),
                    ("2026-10-10 06:12", "dispatch", 4, 2), ("2026-10-10 06:14", "enroute", 4),
                    ("2026-10-10 06:20", "allocate", 10, 60, 2), ("2026-10-10 06:20", "allocate", 11, 6, 2),
                    ("2026-10-10 06:31", "onscene", 9), ("2026-10-10 06:35", "onscene", 4),
                    ("2026-10-10 07:45", "allocate", 1, 400, 2), ("2026-10-10 07:45", "allocate", 3, 300, 2),
                    ("2026-10-10 09:10", "allocate", 7, 200, 2), ("2026-10-10 11:00", "allocate", 12, 6, 2),
                    ("2026-10-11 08:15", "allocate", 1, 150, 3),
                    ("2026-10-12 09:20", "dispatch", 11, 3), ("2026-10-12 09:30", "enroute", 11)])
lifecycle("dup", [("2026-10-10 06:50", "reject", 2, "Duplicate of incident 7")])
lifecycle("sathu", [("2026-10-10 10:15", "verify", 3, "MODERATE", 3),
                    ("2026-10-10 11:30", "allocate", 4, 320, 3), ("2026-10-10 11:30", "allocate", 6, 600, 3)])
lifecycle("anaicut", [("2026-10-11 07:30", "verify", 4, "HIGH", 7), ("2026-10-11 08:00", "allocate", 2, 60, 4)])
lifecycle("efire", [("2026-10-11 20:36", "verify", 2, "HIGH", 1),
                    ("2026-10-11 20:38", "dispatch", 1, 2), ("2026-10-11 20:39", "enroute", 1),
                    ("2026-10-11 20:52", "onscene", 1)])
lifecycle("wall", [("2026-10-12 08:52", "verify", 3, "HIGH", 6),
                   ("2026-10-12 08:55", "dispatch", 10, 3), ("2026-10-12 08:57", "enroute", 10),
                   ("2026-10-12 09:05", "dispatch", 6, 3), ("2026-10-12 09:20", "allocate", 5, 15, 3),
                   ("2026-10-12 09:38", "onscene", 10), ("2026-10-12 10:30", "allocate", 9, 12, 3),
                   ("2026-10-12 10:30", "allocate", 8, 160, 3), ("2026-10-12 11:50", "dispatch", 3, 3),
                   ("2026-10-12 11:55", "enroute", 3)])

E.sort()
# incident ids follow the order of their INSERT (time order)
order = [args[0] for ts, _, kind, args in E if kind == "report"]
INC = {key: i + 1 for i, key in enumerate(order)}


def q(s):
    return "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"


def tz(ts):
    return q(ts + "+05:30")


lines = []
w = lines.append
w("-- =====================================================================================")
w("-- DMERS Incident-Response Database | BCSE302L Review II")
w("-- 03_seed_data.sql : reference data, then a time-ordered replay of incident events.")
w("-- Generated by tools/gen_seed.py. The triggers of 02_plpgsql.sql run on every statement,")
w("-- so timeline entries, stock levels and dispatch rules are produced by the database itself.")
w("-- All people, e-mail addresses and phone numbers are fictitious demonstration data.")
w(f"-- Every account's password hash is a Werkzeug scrypt hash of the demo password {DEMO_PASSWORD}.")
w("-- =====================================================================================")
w("SET client_min_messages = warning;")
w("SET TIME ZONE 'Asia/Kolkata';")
w("")
w("-- Users: account_type and created_at given explicitly; ids 1-16 in this order")
w("INSERT INTO users (full_name, account_type, email, password_hash, created_at) VALUES")
rows = []
for name, typ, email, ts in USERS:
    rows.append(f"    ({q(name)}, {q(typ)}, {q(email)},\n     {q(generate_password_hash(DEMO_PASSWORD))}, {tz(ts)})")
w(",\n".join(rows) + ";")
w("")
w("-- Zones: state omitted, so DEFAULT 'Tamil Nadu' applies; ids 1-12")
w("INSERT INTO zones (zone_name, district, risk_level) VALUES")
w(",\n".join(f"    ({q(a)}, {q(b)}, {q(c)})" for a, b, c in ZONES) + ";")
w("")
w("-- Response units: availability_status omitted, so DEFAULT 'AVAILABLE' applies; ids 1-12")
w("INSERT INTO response_units (unit_name, unit_type, contact_phone, personnel_count, zone_id, lead_user_id) VALUES")
w(",\n".join(f"    ({q(a)}, {q(b)}, {q(c)}, {d}, {e}, {'NULL' if f is None else f})" for a, b, c, d, e, f in UNITS) + ";")
w("")
w("-- Relief resources with opening stock; ids 1-12")
w("INSERT INTO resources (resource_name, category, unit_of_measure, quantity_available, reorder_level) VALUES")
w(",\n".join(f"    ({q(a)}, {q(b)}, {q(c)}, {d}, {e})" for a, b, c, d, e in RESOURCES) + ";")
w("")
w("-- -------------------------------------------------------------------------------------")
w("-- Event replay (1-12 October 2026). dmers.actor_id names the official for the triggers.")
w("-- -------------------------------------------------------------------------------------")

actor = None
status_of = {}
def set_actor(a):
    global actor
    if a != actor:
        w(f"SET dmers.actor_id = '{a}';")
        actor = a

for ts, _, kind, args in E:
    key = args[0]
    when = ts[8:10] + "-Oct " + ts[11:]
    if kind == "report":
        rep, rts, title, desc, typ, loc = REPORTS[key]
        iid = INC[key]
        w(f"-- {when}  incident {iid} reported")
        w("INSERT INTO incidents (title, description, incident_type, location, reported_by,")
        w("                       created_at, updated_at)")
        w(f"VALUES ({q(title)},\n        {q(desc)}, {q(typ)},\n        {q(loc)}, {rep}, {tz(ts)}, {tz(ts)});")
        status_of[iid] = "REPORTED"
        continue
    iid = INC[key] if kind != "offduty" else None
    if kind == "verify":
        a, sev, zone = args[1:]
        set_actor(a)
        w(f"-- {when}  incident {iid} verified")
        w(f"UPDATE incidents SET status = 'VERIFIED', severity = '{sev}', zone_id = {zone},")
        w(f"                     updated_at = {tz(ts)} WHERE id = {iid};")
        status_of[iid] = "VERIFIED"
    elif kind == "reject":
        a, note = args[1:]
        set_actor(a)
        w(f"-- {when}  incident {iid} rejected")
        w(f"SET dmers.note = {q(note)};")
        w(f"UPDATE incidents SET status = 'REJECTED', updated_at = {tz(ts)} WHERE id = {iid};")
        w("RESET dmers.note;")
        status_of[iid] = "REJECTED"
    elif kind == "dispatch":
        unit, a = args[1:]
        set_actor(a)
        w(f"-- {when}  {UNIT_NAME[unit]} dispatched to incident {iid}")
        w("INSERT INTO dispatches (incident_id, unit_id, dispatched_by, dispatched_at)")
        w(f"VALUES ({iid}, {unit}, {a}, {tz(ts)});")
        w(f"UPDATE response_units SET availability_status = 'DEPLOYED' WHERE id = {unit};")
        if status_of[iid] == "VERIFIED":
            w(f"UPDATE incidents SET status = 'RESPONDING', updated_at = {tz(ts)} WHERE id = {iid};")
            status_of[iid] = "RESPONDING"
    elif kind == "enroute":
        unit = args[1]
        w(f"UPDATE dispatches SET dispatch_status = 'EN_ROUTE' WHERE incident_id = {iid} AND unit_id = {unit};")
    elif kind == "onscene":
        unit = args[1]
        w(f"-- {when}  {UNIT_NAME[unit]} on scene at incident {iid}")
        w(f"UPDATE dispatches SET dispatch_status = 'ON_SCENE', arrived_at = {tz(ts)}")
        w(f"WHERE incident_id = {iid} AND unit_id = {unit};")
    elif kind in ("complete", "cancel"):
        unit = args[1]
        st = "COMPLETED" if kind == "complete" else "CANCELLED"
        w(f"-- {when}  {UNIT_NAME[unit]} {st.lower()} at incident {iid}")
        w(f"UPDATE dispatches SET dispatch_status = '{st}', cleared_at = {tz(ts)}")
        w(f"WHERE incident_id = {iid} AND unit_id = {unit};")
        w(f"UPDATE response_units SET availability_status = 'AVAILABLE' WHERE id = {unit};")
    elif kind == "allocate":
        res, qty, a = args[1:]
        set_actor(a)
        w(f"-- {when}  {qty} x {RES_NAME[res]} to incident {iid} (cumulative per incident and item)")
        w("INSERT INTO resource_allocations AS ra (incident_id, resource_id, quantity, allocated_at)")
        w(f"VALUES ({iid}, {res}, {qty}, {tz(ts)})")
        w("ON CONFLICT (incident_id, resource_id)")
        w("DO UPDATE SET quantity = ra.quantity + EXCLUDED.quantity, allocated_at = EXCLUDED.allocated_at;")
    elif kind == "status":
        st, a = args[1:]
        set_actor(a)
        w(f"-- {when}  incident {iid} {st.lower()}")
        w(f"UPDATE incidents SET status = '{st}', updated_at = {tz(ts)} WHERE id = {iid};")
        status_of[iid] = st
    elif kind == "offduty":
        unit = args[0]
        w(f"-- {when}  {UNIT_NAME[unit]} taken off duty for maintenance")
        w(f"UPDATE response_units SET availability_status = 'OFF_DUTY' WHERE id = {unit};")
    else:
        raise ValueError(kind)

w("")
w("RESET dmers.actor_id;")
OUT.write_text("\n".join(lines) + "\n")
print("wrote", OUT, "events:", len(E), "incidents:", len(INC))
print({k: v for k, v in INC.items()})
