import math

import pytest

from app import road_network as rn

START = [12.9249, 79.1355]
GOAL = [12.9300, 79.1500]


@pytest.fixture(scope="module")
def g():
    return rn.graph()


def test_graph_is_real_and_connected(g):
    assert len(g.lat) > 10_000 and g.edge_count > 20_000
    assert any(name for name in g.names)
    # every edge endpoint is a valid node and lengths are physical
    assert all(0 <= u < len(g.lat) and 0 <= v < len(g.lat) for u, v in zip(g.eu, g.ev))
    assert all(0 < length < 3000 for length in g.length)


def test_route_follows_graph_edges(g):
    route = rn.route_stops([START, GOAL], [])
    nodes = {(round(la, 6), round(lo, 6)) for la, lo in zip(g.lat, g.lon)}
    assert route["source"] == "osm-road-graph"
    assert all((round(la, 6), round(lo, 6)) in nodes for la, lo in route["points"])
    assert route["distanceMeters"] >= rn.haversine_m(*[tuple(p) for p in route["points"][:1]], tuple(route["points"][-1]))


def test_astar_matches_ucs_optimum_and_expands_less():
    result = rn.compare_algorithms(START, GOAL, [], "fastest")["results"]
    assert result["astar"]["cost"] == pytest.approx(result["ucs"]["cost"], rel=1e-9)
    assert result["astar"]["nodes_explored"] <= result["ucs"]["nodes_explored"]
    assert result["bfs"]["cost"] >= result["ucs"]["cost"] - 1e-9
    assert result["greedy"]["cost"] >= result["ucs"]["cost"] - 1e-9
    assert result["dfs"]["cost"] >= result["ucs"]["cost"] - 1e-9
    assert result["ucs"]["optimality_gap_pct"] == 0


def test_block_marker_closes_road_and_forces_detour():
    clear = rn.route_stops([START, GOAL], [])
    mid = clear["points"][len(clear["points"]) // 2]
    blocked = rn.route_stops([START, GOAL], [{"type": "block", "lat": mid[0], "lon": mid[1]}])
    assert blocked["closures"], "block must produce visible closed segments"
    assert blocked["detour"]["extra_time_s"] >= 0
    closed = {tuple(map(tuple, shape["coordinates"])) for shape in blocked["closures"]}
    closed |= {tuple(reversed(shape)) for shape in closed}
    pts = [tuple(p) for p in blocked["points"]]
    # no consecutive pair of the route may be a closed segment
    assert not any((a, b) in closed for a, b in zip(pts, pts[1:]))
    assert blocked["risk"]["factors"][4]["name"].startswith("Detour")


def test_hazard_increases_risk_and_safer_mode_reduces_exposure():
    clear = rn.route_stops([START, GOAL], [])
    mid = clear["points"][len(clear["points"]) // 2]
    fire = [{"type": "fire", "lat": mid[0] + 0.0004, "lon": mid[1]}]
    fast = rn.route_stops([START, GOAL], fire, "astar", "fastest")
    safe = rn.route_stops([START, GOAL], fire, "astar", "safer")
    assert fast["risk"]["score"] > clear["risk"]["score"]
    assert safe["metrics"]["exposure_km"] <= fast["metrics"]["exposure_km"] + 1e-9


def test_weather_slows_travel():
    dry = rn.route_stops([START, GOAL], [], weather="clear")
    wet = rn.route_stops([START, GOAL], [], weather="heavy_rain")
    assert wet["durationSeconds"] > dry["durationSeconds"]
    assert wet["distanceMeters"] == pytest.approx(dry["distanceMeters"], rel=0.5)


def test_risk_factor_weights_sum_to_one_and_points_match():
    risk = rn.route_stops([START, GOAL], [])["risk"]
    assert math.isclose(sum(f["weight"] for f in risk["factors"]), 1.0)
    assert risk["score"] == pytest.approx(sum(f["points"] for f in risk["factors"]), abs=0.2)
    assert risk["band"] in {"LOW", "MODERATE", "HIGH", "SEVERE"} and risk["formula"] and risk["assumptions"]


def test_unreachable_when_enclosed_by_blocks(g):
    node, _ = g.snap(*GOAL)
    ring = []
    for e in g.out[node] + g.inn[node]:
        for end in (g.eu[e], g.ev[e]):
            ring.append({"type": "block", "lat": g.lat[end], "lon": g.lon[end]})
    with pytest.raises(ValueError, match="No drivable route"):
        rn.route_stops([START, GOAL], ring)


def test_point_outside_coverage_is_rejected():
    with pytest.raises(ValueError, match="mapped road"):
        rn.route_stops([[13.5, 80.5], START], [])


def test_mission_plan_orders_victims_and_picks_hospitals():
    plan = rn.plan_missions(START, [[12.9300, 79.1500], [12.9180, 79.1300]],
                            [{"name": "A", "point": [12.9250, 79.1350], "beds_available": 5},
                             {"name": "B", "point": [12.9400, 79.1600], "beds_available": 0}], [])
    assert sorted(plan["plan"]["order"]) == [1, 2]
    assert {a["hospital"] for a in plan["plan"]["assignments"]} == {"A"}  # B has no free bed
    assert plan["plan"]["method"].startswith("exact")
