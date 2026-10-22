"""Tests for the database laboratories (migrations 005-012): hash chain, RLS, isolation, reservations,
routing, query optimiser, analytics, privacy export and LISTEN/NOTIFY. They need PostgreSQL (see conftest)."""
from __future__ import annotations

import statistics
import threading
import time

import psycopg
import pytest


def rows(url, sql, params=()):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, params).fetchall()


def load_history(people, count=60000):
    r = people["admin"].post("/api/response/lab/query/load", json={"rows": count})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


# ============================================================ 1. hash-chained timeline
def test_seeded_history_chain_is_intact(people):
    body = people["coordinator"].get("/api/response/lab/chain").get_json()
    assert body["broken"] == 0 and body["incidents_checked"] == 14 and body["entries_checked"] == 61


def test_tampering_is_detected_and_pinpointed_then_restored(people):
    admin, coordinator = people["admin"], people["coordinator"]
    before = coordinator.get("/api/response/lab/chain/1").get_json()["entries"]
    note = before[2]["note"]
    edited = admin.post("/api/response/lab/chain/tamper", json={"incident_id": 1, "update_no": 3, "note": "Nothing happened here"})
    assert edited.status_code == 200 and edited.get_json()["previous_note"] == note
    # the append-only trigger was bypassed, not obeyed: the trace says no trigger fired on the edit
    assert not any(c.startswith("trigger ") for c in edited.get_json()["db_trace"]["components"])
    overview = coordinator.get("/api/response/lab/chain").get_json()
    bad = [i for i in overview["incidents"] if not i["intact"]]
    assert [(i["incident_id"], i["first_bad_update_no"], i["problem"]) for i in bad] == [(1, 3, "entry content was changed")]
    detail = coordinator.get("/api/response/lab/chain/1").get_json()["entries"]
    assert [e["content_ok"] for e in detail] == [True, True, False] + [True] * (len(detail) - 3)
    assert admin.post("/api/response/lab/chain/restore", json={"incident_id": 1, "update_no": 3, "note": note}).status_code == 200
    assert coordinator.get("/api/response/lab/chain").get_json()["broken"] == 0


def test_normal_sql_still_cannot_edit_the_timeline_and_new_entries_extend_the_chain(people, pg_url):
    with psycopg.connect(pg_url) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("UPDATE response.incident_updates SET note = 'x' WHERE incident_id = 1 AND update_no = 1")
    citizen = people["citizen"]
    created = citizen.post("/api/response/incidents", json={"title": "Chain check", "incident_type": "FIRE", "location": "Test lane"}).get_json()["incident"]
    verify = people["coordinator"].post(f"/api/response/incidents/{created['id']}/verify", json={"zone_id": 1, "severity": "HIGH"})
    assert verify.status_code == 200
    entries = people["coordinator"].get(f"/api/response/lab/chain/{created['id']}").get_json()["entries"]
    assert len(entries) == 2 and entries[0]["prev_hash"] is None and entries[1]["prev_hash"] == entries[0]["row_hash"]
    assert all(e["content_ok"] and e["link_ok"] for e in entries)


def test_anchoring_makes_truncation_detectable(people, pg_url):
    assert people["admin"].post("/api/response/lab/chain/anchor").get_json()["anchored"] == 14
    with psycopg.connect(pg_url) as conn:
        conn.execute("SET session_replication_role = replica")                 # superuser removes the newest entry of incident 2
        conn.execute("DELETE FROM response.incident_updates WHERE incident_id = 2 AND update_no = (SELECT max(update_no) FROM response.incident_updates WHERE incident_id = 2)")
        conn.commit()
    bad = [i for i in people["coordinator"].get("/api/response/lab/chain").get_json()["incidents"] if not i["intact"]]
    assert len(bad) == 1 and bad[0]["incident_id"] == 2 and "anchored entry" in bad[0]["problem"]


def test_chain_tools_are_guarded(people, monkeypatch):
    assert people["coordinator"].post("/api/response/lab/chain/tamper", json={"incident_id": 1, "update_no": 1, "note": "x"}).status_code == 403
    assert people["citizen"].get("/api/response/lab/chain").status_code == 403
    monkeypatch.setenv("DMERS_DEMO_MODE", "0")
    assert people["admin"].post("/api/response/lab/chain/tamper", json={"incident_id": 1, "update_no": 1, "note": "x"}).status_code == 404


# ============================================================ 2. row-level security
def test_row_level_security_filters_rows_without_a_where_clause(people):
    body = people["admin"].get("/api/response/lab/rls").get_json()
    by_type = {s["person"]["account_type"]: {o["probe"]: o for o in s["outcomes"]} for s in body["subjects"]}
    total = body["owner_baseline"]["Incidents visible"]
    assert by_type["COORDINATOR"]["Incidents visible"]["outcome"] == total == by_type["ADMINISTRATOR"]["Incidents visible"]["outcome"]
    assert 0 < by_type["CITIZEN"]["Incidents visible"]["outcome"] < total          # only their own reports
    assert by_type["(none)"]["Incidents visible"]["outcome"] == 0                  # no actor, no rows
    assert by_type["CITIZEN"]["Dispatches visible"]["outcome"] == 0 and by_type["COORDINATOR"]["Dispatches visible"]["outcome"] == body["owner_baseline"]["Dispatches visible"]
    assert by_type["CITIZEN"]["Timeline entries visible"]["outcome"] < body["owner_baseline"]["Timeline entries visible"]
    assert by_type["CITIZEN"]["Change every incident's severity"]["outcome"] == 0       # policy hides every row from the UPDATE
    assert by_type["COORDINATOR"]["Change every incident's severity"]["outcome"] == total
    for person in by_type.values():
        assert person["Read password hashes"]["outcome"] == "refused" and person["Read password hashes"]["sqlstate"] == "42501"
        assert person["Report an incident as somebody else"]["outcome"] == "refused"


def test_the_application_role_is_not_restricted_so_existing_flows_are_unchanged(pg_url):
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM response.incidents").fetchone()[0] == 14
        conn.execute("SET LOCAL ROLE dmers_rls")
        assert conn.execute("SELECT count(*) FROM response.incidents").fetchone()[0] == 0     # same connection, restricted role, no actor


# ============================================================ 3. isolation levels
def test_isolation_matrix_matches_postgresql_behaviour(people):
    matrix = {m["scenario"]: m["levels"] for m in people["coordinator"].get("/api/response/lab/isolation/matrix").get_json()["matrix"]}
    refused = "prevented (error 40001)"
    assert matrix["lost_update"] == {"READ COMMITTED": "anomaly", "REPEATABLE READ": refused, "SERIALIZABLE": refused}
    assert matrix["write_skew"] == {"READ COMMITTED": "anomaly", "REPEATABLE READ": "anomaly", "SERIALIZABLE": refused}
    assert matrix["phantom_read"] == {"READ COMMITTED": "anomaly", "REPEATABLE READ": "no anomaly", "SERIALIZABLE": "no anomaly"}
    assert matrix["non_repeatable_read"] == {"READ COMMITTED": "anomaly", "REPEATABLE READ": "no anomaly", "SERIALIZABLE": "no anomaly"}


def run_isolation(people, scenario, level, mode="naive"):
    r = people["admin"].post("/api/response/lab/isolation/run", json={"scenario": scenario, "level": level, "mode": mode})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_lost_update_and_its_two_cures(people):
    naive = run_isolation(people, "lost_update", "READ COMMITTED")
    assert naive["anomaly"] and naive["final_state"][0]["qty"] == 8             # 10 - 2: A's allocation of 3 was overwritten
    atomic = run_isolation(people, "lost_update", "READ COMMITTED", "atomic")
    assert not atomic["anomaly"] and atomic["final_state"][0]["qty"] == 5
    retried = run_isolation(people, "lost_update", "REPEATABLE READ", "retry")
    assert not retried["anomaly"] and retried["final_state"][0]["qty"] == 5 and retried["retries"] == 1
    assert any(s.get("error", {}).get("sqlstate") == "40001" for s in retried["steps"])


def test_write_skew_is_stopped_only_by_serializable_and_retry_restores_the_rule(people):
    assert run_isolation(people, "write_skew", "REPEATABLE READ")["anomaly"]
    skew = run_isolation(people, "write_skew", "REPEATABLE READ")
    assert all(not row["on_duty"] for row in skew["final_state"])                  # nobody on duty
    safe = run_isolation(people, "write_skew", "SERIALIZABLE", "retry")
    assert not safe["anomaly"] and sum(r["on_duty"] for r in safe["final_state"]) == 1 and safe["retries"] == 1


def test_isolation_rejects_unknown_input(people):
    for payload in ({"scenario": "nope", "level": "READ COMMITTED"}, {"scenario": "lost_update", "level": "DROP TABLE"},
                    {"scenario": "phantom_read", "level": "READ COMMITTED", "mode": "retry"}):
        assert people["admin"].post("/api/response/lab/isolation/run", json=payload).status_code == 400
    assert people["lead"].post("/api/response/lab/isolation/run", json={"scenario": "lost_update", "level": "READ COMMITTED"}).status_code == 403


# ============================================================ 4. exclusion-constraint reservations
def reserve(client, unit, start, end, purpose="STANDBY"):
    return client.post("/api/response/lab/reservations", json={"unit_id": unit, "purpose": purpose, "starts_at": start, "ends_at": end})


def test_overlapping_reservations_are_refused_by_the_database(people):
    c = people["coordinator"]
    first = reserve(c, 1, "2026-11-01T08:00+05:30", "2026-11-01T20:00+05:30")
    assert first.status_code == 201 and "ex_reservations_no_overlap" in first.get_json()["db_trace"]["constraints_checked"]
    clash = reserve(c, 1, "2026-11-01T19:00+05:30", "2026-11-02T02:00+05:30", "TRAINING")
    body = clash.get_json()
    assert clash.status_code == 409 and body["code"] == "exclusion_violation" and body["constraint"] == "ex_reservations_no_overlap"
    assert body["sqlstate"] == "23P01" and body["db_trace"]["rolled_back"]
    assert reserve(c, 1, "2026-11-01T20:00+05:30", "2026-11-01T22:00+05:30").status_code == 201      # touching end/start is allowed ([) ranges)
    assert reserve(c, 2, "2026-11-01T19:00+05:30", "2026-11-02T02:00+05:30").status_code == 201      # another unit, same time


def test_cancelled_booking_frees_the_slot_and_free_windows_are_exact(people):
    c = people["coordinator"]
    booked = reserve(c, 3, "2026-11-05T00:00+05:30", "2026-11-05T12:00+05:30").get_json()["reservation"]
    free = c.get("/api/response/lab/reservations/free", query_string={"unit_id": 3, "from": "2026-11-05T00:00+05:30", "to": "2026-11-06T00:00+05:30"}).get_json()["free_windows"]
    assert len(free) == 1 and free[0]["starts_at"].startswith("2026-11-05T06:30:00") and free[0]["ends_at"].startswith("2026-11-05T18:30:00")
    assert c.post(f"/api/response/lab/reservations/{booked['id']}/cancel").status_code == 200
    assert reserve(c, 3, "2026-11-05T06:00+05:30", "2026-11-05T09:00+05:30").status_code == 201


def test_reservation_validation_and_permissions(people):
    c = people["coordinator"]
    assert reserve(c, 1, "2026-11-01T10:00+05:30", "2026-11-01T09:00+05:30").status_code == 400
    assert reserve(c, 1, "not a time", "2026-11-01T09:00+05:30").status_code == 400
    assert reserve(c, 1, "2026-11-01T08:00+05:30", "2026-11-01T09:00+05:30", "PARTY").status_code == 422
    assert reserve(c, 999, "2026-11-01T08:00+05:30", "2026-11-01T09:00+05:30").status_code == 422
    assert reserve(people["lead"], 1, "2026-11-01T08:00+05:30", "2026-11-01T09:00+05:30").status_code == 403
    assert people["lead"].get("/api/response/lab/reservations").status_code == 200
    assert people["citizen"].get("/api/response/lab/reservations").status_code == 403


def test_two_simultaneous_bookings_exactly_one_wins(pg_url):
    first, second = psycopg.connect(pg_url), psycopg.connect(pg_url)
    insert = ("INSERT INTO response.unit_reservations (unit_id, purpose, period, booked_by) VALUES (4, 'STANDBY', "
              "tstzrange('2026-12-01 08:00+05:30', '2026-12-01 12:00+05:30', '[)'), 4)")
    first.execute(insert)                                                        # uncommitted: holds the slot
    outcome = {}

    def second_booking():
        try:
            second.execute(insert)
            second.commit()
            outcome["second"] = "booked"
        except psycopg.errors.ExclusionViolation:
            outcome["second"] = "refused"

    worker = threading.Thread(target=second_booking)
    worker.start()
    time.sleep(0.5)
    assert worker.is_alive()                                                     # the second insert is WAITING for the first transaction
    first.commit()
    worker.join(5)
    assert outcome["second"] == "refused"
    assert psycopg.connect(pg_url).execute("SELECT count(*) FROM response.unit_reservations WHERE unit_id = 4").fetchone()[0] == 1
    first.close(); second.close()


# ============================================================ 5. routing inside the database
@pytest.fixture
def roads(people):
    r = people["admin"].post("/api/response/lab/routing/load")
    assert r.status_code == 200 and r.get_json()["loaded"] == {"nodes": 16352, "edges": 35388, "facilities": 68}
    return people["coordinator"]


FIRE_STATION, ASA_HOSPITAL = (12.914123, 79.131245), (12.937004, 79.162903)


def route(client, hazards=()):
    r = client.post("/api/response/lab/routing/route", json={"from_lat": FIRE_STATION[0], "from_lon": FIRE_STATION[1], "to_lat": ASA_HOSPITAL[0], "to_lon": ASA_HOSPITAL[1], "hazards": list(hazards)})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_database_route_equals_the_python_route(roads):
    body = route(roads)
    assert body["same_answer"] and body["database"]["found"]
    assert abs(body["database"]["seconds"] - body["python"]["seconds"]) < 0.02 and abs(body["database"]["metres"] - body["python"]["metres"]) < 0.5
    assert body["database"]["segments"] == body["python"]["segments"] and 4000 < body["database"]["metres"] < 9000
    assert body["database"]["path"][0] and len(body["database"]["path"]) == body["database"]["segments"] + 1


def test_road_block_closes_segments_in_both_implementations(roads):
    clear = route(roads)
    mid = clear["database"]["path"][len(clear["database"]["path"]) // 2]
    blocked = route(roads, [{"lat": mid[0], "lon": mid[1]}])
    assert blocked["database"]["closed_segments"] > 0 and blocked["database"]["closed_segments"] == blocked["python"]["closed_segments"]
    assert blocked["same_answer"] and blocked["database"]["seconds"] >= clear["database"]["seconds"]
    assert blocked["database"]["path"] != clear["database"]["path"]


def test_nearest_facilities_are_ranked_by_road_not_only_by_straight_line(roads):
    r = roads.post("/api/response/lab/routing/nearest", json={"lat": 12.9231, "lon": 79.1389, "kind": "hospital", "k": 3})
    assert r.status_code == 200
    candidates = r.get_json()["candidates"]
    assert len(candidates) == 3 and sorted(c["straight_rank"] for c in candidates) == [1, 2, 3]
    assert [c["drive_rank"] for c in candidates] == sorted(c["drive_rank"] for c in candidates) and candidates[0]["drive_rank"] == 1
    assert roads.post("/api/response/lab/routing/nearest", json={"lat": 12.9231, "lon": 79.1389, "kind": "spaceport"}).status_code == 404


def test_routing_needs_the_graph_and_a_point_on_the_network(people):
    assert people["coordinator"].post("/api/response/lab/routing/route", json={"from_lat": 12.9, "from_lon": 79.1, "to_lat": 12.93, "to_lon": 79.15}).status_code == 409
    people["admin"].post("/api/response/lab/routing/load")
    far = people["coordinator"].post("/api/response/lab/routing/route", json={"from_lat": 13.5, "from_lon": 80.5, "to_lat": 12.93, "to_lon": 79.15})
    assert far.status_code == 422 and far.get_json()["code"] == "off_network"
    assert people["coordinator"].post("/api/response/lab/routing/load").status_code == 403


# ============================================================ 6. query optimiser
def test_loader_fills_flat_and_partitioned_tables_identically(people, pg_url):
    load_history(people, 5000)
    status = people["coordinator"].get("/api/response/lab/query/catalog").get_json()["status"]
    assert status["flat_rows"] == status["partitioned_rows"] >= 5000 and status["view_populated"]
    assert rows(pg_url, "SELECT count(*) FROM lab.incident_events_default")[0][0] == 0        # every row found a monthly partition
    assert people["coordinator"].post("/api/response/lab/query/load", json={"rows": 5000}).status_code == 403
    assert people["admin"].post("/api/response/lab/query/load", json={"rows": 10}).status_code == 400


def test_experiments_need_history_and_leave_no_index_behind(people, pg_url):
    assert people["coordinator"].post("/api/response/lab/query/run", json={"experiment": "zone_status", "variant": "btree"}).status_code == 409
    load_history(people, 60000)
    run = lambda e, v: people["coordinator"].post("/api/response/lab/query/run", json={"experiment": e, "variant": v}).get_json()
    plain, indexed = run("zone_status", "no_index"), run("zone_status", "btree")
    assert plain["scan_types"] == ["Seq Scan"] and indexed["uses_index"] and indexed["index_bytes"] > 0
    assert plain["answer"] == indexed["answer"]                                           # same result, different plan
    brin, btree = run("time_window", "brin"), run("time_window", "btree")
    assert brin["index_bytes"] * 10 < btree["index_bytes"]                                # BRIN is tiny on time-ordered data
    part = run("time_window", "partitioned")
    assert 1 <= part["partitions_scanned"] <= 2 and part["answer"] == run("time_window", "no_index")["answer"]
    live, view = run("monthly_rollup", "live_aggregate"), run("monthly_rollup", "materialized_view")
    assert live["answer"] == view["answer"]
    assert rows(pg_url, "SELECT count(*) FROM pg_indexes WHERE schemaname = 'lab' AND indexname LIKE 'ix_flat_%%'")[0][0] == 0


def test_experiment_input_is_validated(people):
    load_history(people, 2000)
    assert people["coordinator"].post("/api/response/lab/query/run", json={"experiment": "x; DROP TABLE y", "variant": "btree"}).status_code == 400
    assert people["coordinator"].post("/api/response/lab/query/run", json={"experiment": "time_window", "variant": "btree", "week_start": "tomorrow"}).status_code == 400


# ============================================================ 8. analytics
def test_planted_surges_are_the_top_spikes_and_match_a_python_calculation(people, pg_url):
    load_history(people, 60000)
    zones = [r[0] for r in rows(pg_url, "SELECT id FROM response.zones ORDER BY id")]
    body = people["coordinator"].get("/api/response/lab/analytics", query_string={"window": 14, "threshold": 6}).get_json()
    found = {(s["zone_id"], s["day"]) for s in body["spikes"]}
    assert {(zones[0], "2025-11-10"), (zones[1], "2026-03-04"), (zones[2], "2026-08-19")} <= found
    # independent check of one z-score and of the regression, computed here in Python from the daily series
    series = people["coordinator"].get("/api/response/lab/analytics/series", query_string={"zone_id": zones[0], "window": 14}).get_json()["series"]
    index = next(i for i, d in enumerate(series) if d["day"] == "2025-11-10")
    trailing = [d["n"] for d in series[index - 14:index]]
    expected = (series[index]["n"] - statistics.mean(trailing)) / statistics.stdev(trailing)
    assert abs(series[index]["z_score"] - expected) < 0.01
    last28 = series[-28:]
    xs, ys = list(range(-27, 1)), [d["n"] for d in last28]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    forecast = next(f for f in body["forecast"] if f["zone_id"] == zones[0])
    assert abs(forecast["slope_per_day"] - slope) < 0.001
    assert people["coordinator"].get("/api/response/lab/analytics", query_string={"window": 2}).status_code == 400


def test_analytics_asks_for_history_first(people):
    assert people["coordinator"].get("/api/response/lab/analytics").status_code == 409


# ============================================================ 9. privacy-safe export
def test_small_cells_are_suppressed_and_counts_are_exact_without_noise(people):
    load_history(people, 60000)
    body = people["admin"].get("/api/response/lab/privacy", query_string={"k": 5}).get_json()
    assert body["summary"]["suppressed_cells"] > 0 and body["summary"]["mean_abs_error"] == 0
    for row in body["rows"]:
        assert (row["released_count"] is None and row["true_count"] < 5) or row["released_count"] == row["true_count"] >= 5
    stricter = people["admin"].get("/api/response/lab/privacy", query_string={"k": 40}).get_json()["summary"]
    assert stricter["suppressed_cells"] > body["summary"]["suppressed_cells"]


def test_noise_is_reproducible_with_a_seed_and_scales_with_epsilon(people):
    load_history(people, 60000)
    get = lambda **q: people["admin"].get("/api/response/lab/privacy", query_string={"k": 1, **q}).get_json()
    a, b = get(epsilon=1, seed=0.25), get(epsilon=1, seed=0.25)
    assert a["rows"] == b["rows"] and a["rows"] != get(epsilon=1, seed=0.5)["rows"]
    loose, tight = get(epsilon=0.2, seed=0.3)["summary"]["mean_abs_error"], get(epsilon=5, seed=0.3)["summary"]["mean_abs_error"]
    assert tight < loose and 0.5 < get(epsilon=1, seed=0.3)["summary"]["mean_abs_error"] < 2.0     # Laplace(b = 1/epsilon): mean |noise| is about 1


def test_citizens_get_the_released_view_only_and_live_data_is_mostly_suppressed(people):
    load_history(people, 5000)
    body = people["citizen"].get("/api/response/lab/privacy", query_string={"k": 5}).get_json()
    assert not body["admin_view"] and all("true_count" not in r for r in body["rows"]) and "true_total" not in body["summary"]
    live = people["citizen"].get("/api/response/lab/privacy", query_string={"source": "live", "k": 5}).get_json()
    assert live["summary"]["suppressed_percent"] == 100.0                      # 14 real incidents: every cell is below k
    csv = people["citizen"].get("/api/response/lab/privacy", query_string={"k": 5, "format": "csv"})
    assert csv.mimetype == "text/csv" and csv.get_data(as_text=True).splitlines()[0] == "zone,incident_type,month,count"
    assert people["citizen"].get("/api/response/lab/privacy", query_string={"k": 0}).status_code == 400


# ============================================================ 7. LISTEN / NOTIFY
def listener(url):
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("LISTEN dmers_events")
    return conn


def test_a_committed_change_is_pushed_and_a_rolled_back_one_is_not(people, pg_url):
    import json
    conn = listener(pg_url)
    created = people["citizen"].post("/api/response/incidents", json={"title": "Push test", "incident_type": "FLOOD", "location": "Test lane"}).get_json()["incident"]
    verified = people["coordinator"].post(f"/api/response/incidents/{created['id']}/verify", json={"zone_id": 1, "severity": "HIGH"})
    assert verified.status_code == 200 and "trigger trg_incidents_notify" in verified.get_json()["db_trace"]["components"]
    messages = [json.loads(n.payload) for n in conn.notifies(timeout=2, stop_after=3)]
    assert [(m["table"], m["op"], m["status"]) for m in messages] == [("incidents", "INSERT", "REPORTED"), ("incidents", "UPDATE", "VERIFIED")]
    assert messages[-1] == {"table": "incidents", "op": "UPDATE", "incident_id": created["id"], "status": "VERIFIED", "severity": "HIGH"}
    assert all(set(m) <= {"table", "op", "incident_id", "unit_id", "status", "severity"} for m in messages)       # no personal data in the payload
    # a transaction that rolls back publishes nothing
    with psycopg.connect(pg_url) as other:
        other.execute("UPDATE response.incidents SET severity = 'LOW' WHERE id = %s", (created["id"],))
        other.rollback()
    assert list(conn.notifies(timeout=1)) == []
    conn.close()


def test_dispatch_is_pushed_and_the_stream_endpoint_is_role_guarded(people, pg_app, pg_url):
    import json
    conn = listener(pg_url)
    dispatched = people["coordinator"].post("/api/response/incidents/9/dispatch", json={"unit_id": 2})
    assert dispatched.status_code == 201, dispatched.get_json()
    pushed = [json.loads(n.payload) for n in conn.notifies(timeout=2, stop_after=3)]
    assert {"table": "dispatches", "op": "INSERT", "incident_id": 9, "unit_id": 2, "status": "ASSIGNED"} in pushed
    assert people["citizen"].get("/api/response/stream").status_code == 403
    stream = people["coordinator"].get("/api/response/stream", buffered=False)
    first = next(iter(stream.response))
    assert stream.mimetype == "text/event-stream" and b"connected" in first
    stream.close()
    conn.close()


def test_a_facility_on_the_incident_node_has_zero_driving_time(roads):
    r = roads.post("/api/response/lab/routing/nearest", json={"lat": 12.916289, "lon": 79.136317, "kind": "hospital", "k": 3})      # BPR Hospital's own position
    nearest = next(c for c in r.get_json()["candidates"] if c["straight_rank"] == 1)
    assert nearest["name"] == "BPR Hospital" and nearest["drive_seconds"] == 0 and nearest["drive_m"] == 0 and nearest["drive_rank"] == 1
