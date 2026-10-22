"""Risk-aware routing on the real Vellore road network (OpenStreetMap, offline).

The graph in ``data/vellore_roads.json`` holds actual road geometry, one-way rules and road
classes, so a route always follows streets a vehicle can drive. Hazard markers placed by the
operator close nearby road segments (blocks) or raise their exposure (fire, flood, ...).

Search algorithms (BFS, DFS, UCS, Greedy best-first, A*) run on this graph. All of them treat
closed segments as impassable; the weighted ones minimise ``time x (1 + lambda x exposure)``.
Travel times are planning estimates from road class / posted speed, not live traffic.
"""
from __future__ import annotations

import heapq
import itertools
import json
import math
import time
from collections import deque
from functools import lru_cache
from pathlib import Path

from . import risk_model

DATA_PATH = Path(__file__).resolve().parent / "data" / "vellore_roads.json"
CLASS_LABEL = ["Motorway", "Trunk road", "Primary road", "Secondary road", "Tertiary road", "Minor road", "Residential street", "Service lane"]
FLAG_ONEWAY, FLAG_BRIDGE, FLAG_UNPAVED = 1, 2, 4
MAX_SNAP_M = 800.0
GRID_M = 250.0

# severity: peak chance a hazard compromises a road at its centre; sigma: distance (m) at which
# that falls to 37%; closure: radius (m) inside which the segment is treated as impassable;
# delay: extra travel-time multiplier at the centre (smooth traffic/debris slowdown).
HAZARD_PROFILES = {
    "block": {"label": "Road block", "severity": 1.0, "sigma": 45.0, "closure": 35.0, "delay": 0.0},
    "fire": {"label": "Fire", "severity": 0.9, "sigma": 160.0, "closure": 45.0, "delay": 0.5},
    "flood": {"label": "Flooding", "severity": 0.8, "sigma": 260.0, "closure": 70.0, "delay": 0.8},
    "earthquake": {"label": "Earthquake damage", "severity": 0.85, "sigma": 190.0, "closure": 45.0, "delay": 0.6},
    "landslide": {"label": "Landslide", "severity": 0.8, "sigma": 200.0, "closure": 55.0, "delay": 0.6},
    "traffic": {"label": "Traffic disruption", "severity": 0.15, "sigma": 220.0, "closure": 0.0, "delay": 1.6},
}
WEATHER = {
    # (speed factor on paved roads, speed factor on unpaved roads, label)
    "clear": (1.0, 1.0, "Clear"),
    "rain": (0.85, 0.7, "Rain"),
    "heavy_rain": (0.65, 0.4, "Heavy rain / monsoon"),
}
ALGORITHMS = ("bfs", "dfs", "ucs", "greedy", "astar")
MODE_LAMBDA = {"fastest": 0.0, "balanced": 4.0, "safer": 12.0}
ALGORITHM_NOTES = {
    "bfs": "Fewest road segments; ignores distance, speed and risk.",
    "dfs": "Depth-first with nearest-to-goal ordering; finds some path, rarely a good one.",
    "ucs": "Uniform-cost: cheapest route by time-and-risk cost. Optimal.",
    "greedy": "Greedy best-first: follows straight-line closeness only. Fast, not optimal.",
    "astar": "A*: cost-so-far plus an admissible straight-line time bound. Optimal with fewer expansions than UCS.",
}


class RoadGraph:
    def __init__(self, raw: dict):
        self.meta = raw["meta"]
        self.names = raw["names"]
        self.lat = [n[0] for n in raw["nodes"]]
        self.lon = [n[1] for n in raw["nodes"]]
        lat0 = sum(self.lat) / len(self.lat)
        self.lat0 = lat0
        self._kx = 111_320.0 * math.cos(math.radians(lat0))
        self._ky = 110_574.0
        self.x = [(lon - self.lon[0]) * self._kx for lon in self.lon]
        self.y = [(lat - self.lat[0]) * self._ky for lat in self.lat]
        edges = raw["edges"]
        self.edge_count = len(edges)
        self.eu = [e[0] for e in edges]
        self.ev = [e[1] for e in edges]
        self.length = [float(e[2]) for e in edges]
        self.cls = [e[3] for e in edges]
        self.name_id = [e[4] for e in edges]
        self.flags = [e[5] for e in edges]
        self.speed = [e[6] for e in edges]
        self.out: list[list[int]] = [[] for _ in self.lat]
        self.inn: list[list[int]] = [[] for _ in self.lat]
        for index, (u, v) in enumerate(zip(self.eu, self.ev)):
            self.out[u].append(index)
            self.inn[v].append(index)
        self.max_speed_ms = max(self.speed) / 3.6
        self.grid: dict[tuple[int, int], list[int]] = {}
        for node, (px, py) in enumerate(zip(self.x, self.y)):
            self.grid.setdefault((int(px // GRID_M), int(py // GRID_M)), []).append(node)

    def project(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon[0]) * self._kx, (lat - self.lat[0]) * self._ky

    def nodes_within(self, px: float, py: float, radius: float) -> list[int]:
        reach = int(radius // GRID_M) + 1
        cx, cy = int(px // GRID_M), int(py // GRID_M)
        found = []
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for node in self.grid.get((gx, gy), ()):
                    if (self.x[node] - px) ** 2 + (self.y[node] - py) ** 2 <= radius * radius:
                        found.append(node)
        return found

    def snap(self, lat: float, lon: float) -> tuple[int, float]:
        """Nearest road node and the distance (m) from the requested point to it."""
        px, py = self.project(lat, lon)
        for radius in (100.0, 250.0, 500.0, MAX_SNAP_M):
            nodes = self.nodes_within(px, py, radius)
            if nodes:
                best = min(nodes, key=lambda n: (self.x[n] - px) ** 2 + (self.y[n] - py) ** 2)
                return best, math.hypot(self.x[best] - px, self.y[best] - py)
        raise ValueError(f"Point {lat:.5f}, {lon:.5f} is more than {int(MAX_SNAP_M)} m from any mapped road in the Vellore dataset")

    def road_label(self, edge: int) -> str:
        name = self.names[self.name_id[edge]]
        return name or CLASS_LABEL[self.cls[edge]]


@lru_cache(maxsize=1)
def graph() -> RoadGraph:
    with DATA_PATH.open(encoding="utf-8") as handle:
        return RoadGraph(json.load(handle))


def graph_available() -> bool:
    return DATA_PATH.exists()


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(h))


class Scenario:
    """Hazards + weather applied to the graph: closed edges, per-edge exposure and travel time."""

    def __init__(self, g: RoadGraph, hazards: list[dict], weather: str = "clear", open_closures: bool = False):
        if weather not in WEATHER:
            raise ValueError("Weather must be clear, rain, or heavy_rain")
        self.g, self.weather, self.hazards = g, weather, []
        paved, unpaved, _ = WEATHER[weather]
        self.free_time = [g.length[e] / (g.speed[e] / 3.6) for e in range(g.edge_count)]
        self.base_time = [
            g.length[e] / (g.speed[e] / 3.6 * (unpaved if g.flags[e] & FLAG_UNPAVED else paved))
            for e in range(g.edge_count)
        ]
        survive: dict[int, float] = {}
        delay: dict[int, float] = {}
        self.closed: set[int] = set()
        self.closure_sources: dict[int, int] = {}
        for index, hazard in enumerate(hazards):
            kind = hazard.get("type")
            profile = HAZARD_PROFILES.get(kind)
            if profile is None:
                raise ValueError(f"Unknown hazard type '{kind}'. Use one of: {', '.join(HAZARD_PROFILES)}")
            lat, lon = float(hazard["lat"]), float(hazard["lon"])
            px, py = g.project(lat, lon)
            reach = max(profile["closure"], 3 * profile["sigma"])
            touched: set[int] = set()
            for node in g.nodes_within(px, py, reach + 120.0):
                touched.update(g.out[node])
                touched.update(g.inn[node])
            affected = 0
            for e in touched:
                d = _segment_distance(px, py, g.x[g.eu[e]], g.y[g.eu[e]], g.x[g.ev[e]], g.y[g.ev[e]])
                if profile["closure"] and d <= profile["closure"]:
                    self.closed.add(e)
                    self.closure_sources.setdefault(e, index)
                    affected += 1
                falloff = math.exp(-((d / profile["sigma"]) ** 2))
                exposure = profile["severity"] * falloff
                if exposure > 0.01:
                    survive[e] = survive.get(e, 1.0) * (1.0 - exposure)
                    delay[e] = delay.get(e, 1.0) * (1.0 + profile["delay"] * falloff)
            self.hazards.append({"index": index, "type": kind, "label": profile["label"], "lat": lat, "lon": lon,
                                 "closure_radius_m": profile["closure"], "influence_radius_m": round(2 * profile["sigma"]),
                                 "closed_segments": affected})
        if open_closures:  # same hazards and slowdowns, but no road is shut: the "what if nothing were blocked" baseline
            self.closed = set()
        self.exposure = {e: 1.0 - s for e, s in survive.items()}
        self.time = list(self.base_time)
        for e, factor in delay.items():
            self.time[e] *= factor
        self._costs: dict[str, list[float]] = {}

    def costs(self, mode: str) -> list[float]:
        if mode not in MODE_LAMBDA:
            raise ValueError("Mode must be fastest, balanced, or safer")
        if mode not in self._costs:
            lam, inf = MODE_LAMBDA[mode], math.inf
            exposure = self.exposure
            self._costs[mode] = [
                inf if e in self.closed else self.time[e] * (1.0 + lam * exposure.get(e, 0.0))
                for e in range(self.g.edge_count)
            ]
        return self._costs[mode]


def _reconstruct(parent_edge: dict[int, int], g: RoadGraph, goal: int) -> list[int]:
    edges = []
    node = goal
    while node in parent_edge:
        e = parent_edge[node]
        edges.append(e)
        node = g.eu[e]
    edges.reverse()
    return edges


def search(sc: Scenario, src: int, dst: int, algorithm: str, mode: str = "fastest") -> dict:
    """Run one algorithm; returns the edge path and honest search statistics."""
    if algorithm not in ALGORITHMS:
        raise ValueError("Algorithm must be bfs, dfs, ucs, greedy, or astar")
    g, cost = sc.g, sc.costs(mode)
    began = time.perf_counter()
    goal_x, goal_y = g.x[dst], g.y[dst]
    straight = lambda n: math.hypot(g.x[n] - goal_x, g.y[n] - goal_y)
    bound = lambda n: straight(n) / g.max_speed_ms  # admissible: cost >= time >= distance / vmax
    parent: dict[int, int] = {}
    order: list[int] = []
    peak = 1
    found = src == dst
    counter = itertools.count()
    if algorithm in {"bfs", "dfs"}:
        seen = {src}
        frontier = deque([src]) if algorithm == "bfs" else [src]
        while frontier and not found:
            node = frontier.popleft() if algorithm == "bfs" else frontier.pop()
            order.append(node)
            if node == dst:
                found = True
                break
            options = [e for e in g.out[node] if cost[e] != math.inf and g.ev[e] not in seen]
            if algorithm == "dfs":
                options.sort(key=lambda e: -straight(g.ev[e]))  # nearest-to-goal is pushed last, popped first
            for e in options:
                nxt = g.ev[e]
                if nxt in seen:
                    continue
                seen.add(nxt)
                parent[nxt] = e
                frontier.append(nxt)
            peak = max(peak, len(frontier))
    else:
        best = {src: 0.0}
        done: set[int] = set()
        heap = [(0.0, next(counter), src)]
        while heap and not found:
            _, _, node = heapq.heappop(heap)
            if node in done:
                continue
            done.add(node)
            order.append(node)
            if node == dst:
                found = True
                break
            for e in g.out[node]:
                step = cost[e]
                if step == math.inf:
                    continue
                nxt = g.ev[e]
                if nxt in done:
                    continue
                candidate = best[node] + step
                if algorithm == "greedy":
                    if nxt not in best:
                        best[nxt] = candidate
                        parent[nxt] = e
                        heapq.heappush(heap, (straight(nxt), next(counter), nxt))
                elif candidate < best.get(nxt, math.inf):
                    best[nxt] = candidate
                    parent[nxt] = e
                    priority = candidate if algorithm == "ucs" else candidate + bound(nxt)
                    heapq.heappush(heap, (priority, next(counter), nxt))
            peak = max(peak, len(heap))
    edges = _reconstruct(parent, g, dst) if found and src != dst else []
    stride = max(1, len(order) // 500)
    return {
        "found": found, "edges": edges, "algorithm": algorithm, "mode": mode,
        "cost": round(sum(cost[e] for e in edges), 2), "nodes_explored": len(order), "frontier_peak": peak,
        "runtime_ms": round((time.perf_counter() - began) * 1000, 2),
        "explored_sample": [[g.lat[n], g.lon[n]] for n in order[::stride]],
        "note": ALGORITHM_NOTES[algorithm],
    }


def distances_from(sc: Scenario, src: int, mode: str) -> tuple[dict[int, float], dict[int, int]]:
    """Single-source cheapest cost to every reachable node (Dijkstra)."""
    g, cost = sc.g, sc.costs(mode)
    best, parent, done = {src: 0.0}, {}, set()
    heap = [(0.0, 0, src)]
    counter = itertools.count(1)
    while heap:
        d, _, node = heapq.heappop(heap)
        if node in done:
            continue
        done.add(node)
        for e in g.out[node]:
            step = cost[e]
            if step == math.inf:
                continue
            nxt = g.ev[e]
            candidate = d + step
            if candidate < best.get(nxt, math.inf):
                best[nxt] = candidate
                parent[nxt] = e
                heapq.heappush(heap, (candidate, next(counter), nxt))
    return best, parent


def _edge_band(exposure: float) -> str:
    return "danger" if exposure >= 0.25 else "caution" if exposure >= 0.05 else "clear"


def describe_path(sc: Scenario, edges: list[int]) -> dict:
    """Geometry, per-segment risk bands, road names and raw route metrics for an edge path."""
    g = sc.g
    if not edges:
        return {"coordinates": [], "segments": [], "roads": [], "distance_m": 0.0, "eta_s": 0.0, "free_flow_s": 0.0,
                "exposure_km": 0.0, "compromise_probability": 0.0, "unpaved_share": 0.0, "max_exposure": 0.0, "turns": 0}
    coords = [[g.lat[g.eu[edges[0]]], g.lon[g.eu[edges[0]]]]] + [[g.lat[g.ev[e]], g.lon[g.ev[e]]] for e in edges]
    segments, roads = [], []
    survive = 1.0
    exposure_m = unpaved_m = 0.0
    for position, e in enumerate(edges):
        r = sc.exposure.get(e, 0.0)
        survive *= 1.0 - r * min(1.0, g.length[e] / 150.0)
        exposure_m += r * g.length[e]
        if g.flags[e] & FLAG_UNPAVED:
            unpaved_m += g.length[e]
        band = _edge_band(r)
        if segments and segments[-1]["band"] == band:
            segments[-1]["coordinates"].append(coords[position + 1])
            segments[-1]["max_exposure"] = max(segments[-1]["max_exposure"], round(r, 3))
        else:
            segments.append({"band": band, "coordinates": [coords[position], coords[position + 1]], "max_exposure": round(r, 3)})
        label = g.road_label(e)
        if roads and roads[-1]["road"] == label:
            roads[-1]["length_m"] += g.length[e]
        else:
            roads.append({"road": label, "class": CLASS_LABEL[g.cls[e]], "length_m": g.length[e]})
    distance = sum(g.length[e] for e in edges)
    for road in roads:
        road["length_m"] = round(road["length_m"])
    return {
        "coordinates": coords, "segments": segments, "roads": roads, "distance_m": round(distance, 1),
        "eta_s": round(sum(sc.time[e] for e in edges), 1), "free_flow_s": round(sum(sc.free_time[e] for e in edges), 1),
        "exposure_km": round(exposure_m / 1000, 3), "compromise_probability": round(1.0 - survive, 4),
        "unpaved_share": round(unpaved_m / distance, 4) if distance else 0.0,
        "max_exposure": round(max((sc.exposure.get(e, 0.0) for e in edges), default=0.0), 3), "turns": len(roads) - 1,
    }


def route_risk(metrics: dict, baseline_distance_m: float | None) -> dict:
    eta = metrics["eta_s"]
    delay_ratio = (eta / metrics["free_flow_s"] - 1.0) if metrics["free_flow_s"] else 0.0
    detour = (metrics["distance_m"] / baseline_distance_m - 1.0) if baseline_distance_m else 0.0
    F = risk_model.factor
    return risk_model.compose([
        F("Chance route is compromised", f"{metrics['compromise_probability'] * 100:.1f}", "%", metrics["compromise_probability"], 0.35,
          "1 - product over segments of (1 - exposure x min(1, length/150 m)). Hazards near the line raise it."),
        F("Hazard-weighted distance", metrics["exposure_km"], "km", metrics["exposure_km"] / 1.5, 0.20,
          "Sum of segment length x hazard exposure; 1.5 km-equivalent saturates the factor."),
        F("Slowdown vs clear-weather free flow", f"{max(delay_ratio, 0) * 100:.0f}", "%", delay_ratio / 0.6, 0.15,
          "Weather, unpaved surface and traffic/debris slowdown; +60% saturates."),
        F("Unpaved surface share", f"{metrics['unpaved_share'] * 100:.0f}", "%", metrics["unpaved_share"], 0.10,
          "Share of route length on unpaved roads (OSM surface tag)."),
        F("Detour forced by hazards and closures", f"{max(detour, 0) * 100:.1f}", "%", detour / 0.5, 0.10,
          "Extra distance versus the same trip with no hazards at all; +50% saturates."),
        F("Trip duration (golden-hour pressure)", f"{eta / 60:.1f}", "min", eta / 1800.0, 0.10,
          "Longer response means longer untreated time; 30 min saturates."),
    ], "score = 100 x sum(weight x normalised factor); bands: <20 LOW, <40 MODERATE, <65 HIGH, else SEVERE", [
        "Hazard exposure is modelled as peak severity x exp(-(distance/sigma)^2) around each marker.",
        "Travel times come from road class / posted speed and weather factors, not live traffic.",
        "Only hazards the operator placed are known; unreported closures are not represented.",
    ])


def situation_risk(sc: Scenario, victims: int) -> dict:
    load = sum(HAZARD_PROFILES[h["type"]]["severity"] for h in sc.hazards)
    F = risk_model.factor
    return risk_model.compose([
        F("Active hazard load", round(load, 2), "severity units", load / 3.0, 0.40, "Sum of peak severities of placed hazards; 3.0 saturates."),
        F("Victims awaiting rescue", victims, "victims", victims / 6.0, 0.25, "More simultaneous casualties stretch teams; 6 saturates."),
        F("Weather", WEATHER[sc.weather][2], "", {"clear": 0.0, "rain": 0.5, "heavy_rain": 1.0}[sc.weather], 0.20, "Rain slows paved roads and badly degrades unpaved ones."),
        F("Closed road segments", closed_segment_count(sc), "segments", closed_segment_count(sc) / 40.0, 0.15, "40 closed segments saturate the factor; more closures mean fewer detour options."),
    ], "score = 100 x sum(weight x normalised factor)", ["Scene-level indicator for operator attention; it does not predict casualties."])


def closed_segment_count(sc: Scenario) -> int:
    """Distinct physical road segments closed (a two-way road counts once, as does a one-way road)."""
    g = sc.g
    return len({(min(g.eu[e], g.ev[e]), max(g.eu[e], g.ev[e])) for e in sc.closed})


def closure_geometry(sc: Scenario) -> list[dict]:
    g = sc.g
    seen, shapes = set(), []
    for e in sorted(sc.closed):
        key = (min(g.eu[e], g.ev[e]), max(g.eu[e], g.ev[e]))
        if key in seen:
            continue
        seen.add(key)
        hazard = sc.hazards[sc.closure_sources[e]]
        shapes.append({"coordinates": [[g.lat[g.eu[e]], g.lon[g.eu[e]]], [g.lat[g.ev[e]], g.lon[g.ev[e]]]],
                       "road": g.road_label(e), "cause": hazard["label"], "hazard_index": hazard["index"]})
    return shapes


def _parse_point(value) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Each stop must be [latitude, longitude]")
    lat, lon = float(value[0]), float(value[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinates are outside valid latitude/longitude bounds")
    return lat, lon


def _normalise_hazards(items) -> list[dict]:
    hazards = []
    for item in items or []:
        if not isinstance(item, dict) or "lat" not in item or "lon" not in item:
            raise ValueError("Each hazard needs type, lat and lon")
        hazards.append(item)
    if len(hazards) > 60:
        raise ValueError("At most 60 hazards per calculation")
    return hazards


def route_stops(stops: list, hazards: list | None, algorithm: str = "astar", mode: str = "fastest", weather: str = "clear") -> dict:
    """Route through ``stops`` in order on real roads, with closures, risk and a no-closure baseline."""
    if not isinstance(stops, list) or not 2 <= len(stops) <= 25:
        raise ValueError("Provide between 2 and 25 stops")
    g = graph()
    points = [_parse_point(stop) for stop in stops]
    hazards_list = _normalise_hazards(hazards)
    sc = Scenario(g, hazards_list, weather)
    plain = Scenario(g, [], weather) if sc.hazards else sc
    snapped = [g.snap(*p) for p in points]
    legs, all_edges, baseline_edges = [], [], []
    explored: list = []
    for index in range(len(points) - 1):
        a, b = snapped[index][0], snapped[index + 1][0]
        result = search(sc, a, b, algorithm, mode)
        base = result if plain is sc else search(plain, a, b, algorithm, mode)
        if not result["found"]:
            raise_unreachable(sc, points, index, base["found"])
        legs.append({"from": list(points[index]), "to": list(points[index + 1]), "nodes_explored": result["nodes_explored"],
                     "frontier_peak": result["frontier_peak"], "runtime_ms": result["runtime_ms"]})
        all_edges.extend(result["edges"])
        baseline_edges.extend(base["edges"])
        explored.extend(result["explored_sample"])
    metrics = describe_path(sc, all_edges)
    base_metrics = describe_path(plain, baseline_edges)
    risk = route_risk(metrics, base_metrics["distance_m"] if sc.hazards else None)
    detour = None
    if sc.hazards:
        detour = {"extra_distance_m": round(metrics["distance_m"] - base_metrics["distance_m"], 1),
                  "extra_time_s": round(metrics["eta_s"] - base_metrics["eta_s"], 1),
                  "baseline_distance_m": base_metrics["distance_m"], "baseline_eta_s": base_metrics["eta_s"],
                  "baseline_coordinates": base_metrics["coordinates"], "closed_segments": closed_segment_count(sc)}
    return {
        "source": "osm-road-graph", "algorithm": algorithm, "mode": mode, "weather": sc.weather,
        "points": metrics["coordinates"], "stops": [list(p) for p in points], "distanceMeters": metrics["distance_m"],
        "durationSeconds": metrics["eta_s"], "segments": metrics["segments"], "roads": metrics["roads"],
        "legs": legs, "snapped": [{"requested": list(p), "snap_distance_m": round(d, 1)} for p, (_, d) in zip(points, snapped)],
        "closures": closure_geometry(sc), "hazards": sc.hazards, "detour": detour, "risk": risk,
        "situation": situation_risk(sc, max(0, len(points) - 2)), "metrics": {k: metrics[k] for k in (
            "exposure_km", "compromise_probability", "unpaved_share", "max_exposure", "free_flow_s", "turns")},
        "explored": explored[:700], "attribution": g.meta["attribution"],
    }


def raise_unreachable(sc: Scenario, points, leg: int, reachable_without_closures: bool):
    why = ("The placed road blocks/hazards cut every road path between these stops. Remove or move a closure, or choose another destination."
           if reachable_without_closures else "These two points are not connected by the mapped road network.")
    raise ValueError(f"No drivable route for leg {leg + 1}. {why}")


def compare_algorithms(start: list, goal: list, hazards: list | None, mode: str = "fastest", weather: str = "clear") -> dict:
    g = graph()
    hazards_list = _normalise_hazards(hazards)
    sc = Scenario(g, hazards_list, weather)
    a, a_snap = g.snap(*_parse_point(start))
    b, b_snap = g.snap(*_parse_point(goal))
    plain = Scenario(g, [], weather) if sc.hazards else sc
    base_distance = None
    if sc.hazards:
        base = search(plain, a, b, "astar", mode)
        base_distance = describe_path(plain, base["edges"])["distance_m"] if base["found"] else None
    runs = {name: search(sc, a, b, name, mode) for name in ALGORITHMS}
    optimum = runs["ucs"]["cost"] if runs["ucs"]["found"] else None
    results = {}
    for name, run in runs.items():
        entry = {"found": run["found"], "nodes_explored": run["nodes_explored"], "frontier_peak": run["frontier_peak"],
                 "runtime_ms": run["runtime_ms"], "note": run["note"], "cost": run["cost"]}
        if run["found"]:
            metrics = describe_path(sc, run["edges"])
            risk = route_risk(metrics, base_distance)
            entry.update({"distance_m": metrics["distance_m"], "eta_s": metrics["eta_s"], "segments": metrics["turns"] + 1,
                          "risk_score": risk["score"], "risk_band": risk["band"], "coordinates": metrics["coordinates"],
                          "optimality_gap_pct": round(100 * (run["cost"] / optimum - 1), 1) if optimum else None,
                          "explored_sample": run["explored_sample"]})
        results[name] = entry
    return {"results": results, "mode": mode, "weather": weather, "closed_segments": closed_segment_count(sc),
            "optimal_cost": optimum, "snap_distance_m": [round(a_snap, 1), round(b_snap, 1)],
            "reading_guide": "Optimality gap compares each route's time-and-risk cost with the optimal UCS cost. A* and UCS should match; "
                             "BFS, DFS and Greedy usually do not."}


def plan_missions(team: list, victims: list, hospitals: list, hazards: list | None, algorithm: str = "astar",
                  mode: str = "balanced", weather: str = "clear") -> dict:
    """Order rescues and choose receiving hospitals by routed cost, then draw the real-road tour.

    Each sortie is team -> victim -> best hospital for that victim, then on to the next victim. For up to 7
    victims every visiting order is evaluated exactly; beyond that a nearest-feasible order is used.
    """
    if not victims or len(victims) > 10:
        raise ValueError("Provide between 1 and 10 victims")
    if not hospitals:
        raise ValueError("Provide at least one receiving hospital")
    g = graph()
    sc = Scenario(g, _normalise_hazards(hazards), weather)
    start = _parse_point(team)
    v_points = [_parse_point(v) for v in victims]
    h_items = []
    for item in hospitals:
        point = _parse_point(item["point"] if isinstance(item, dict) else item)
        beds = item.get("beds_available") if isinstance(item, dict) else None
        if beds is not None and float(beds) <= 0:
            continue
        h_items.append({"point": point, "name": (item.get("name") if isinstance(item, dict) else None) or f"Hospital {len(h_items) + 1}", "beds": beds})
    if not h_items:
        raise ValueError("No hospital has a free bed; choose a different receiving facility")
    t_node = g.snap(*start)[0]
    v_nodes = [g.snap(*p)[0] for p in v_points]
    h_nodes = [g.snap(*h["point"])[0] for h in h_items]
    from_node = {n: distances_from(sc, n, mode)[0] for n in {t_node, *v_nodes, *h_nodes}}
    inf = math.inf
    to_hospital = []
    for vi, vn in enumerate(v_nodes):
        options = [(from_node[vn].get(hn, inf), hi) for hi, hn in enumerate(h_nodes)]
        cost, hi = min(options)
        to_hospital.append((cost, hi))
    unreachable = [i for i, vn in enumerate(v_nodes) if from_node[t_node].get(vn, inf) == inf or to_hospital[i][0] == inf]
    todo = [i for i in range(len(v_nodes)) if i not in unreachable]

    def sortie_cost(order):
        total, here = 0.0, t_node
        for i in order:
            total += from_node[here].get(v_nodes[i], inf) + to_hospital[i][0]
            here = h_nodes[to_hospital[i][1]]
        return total

    if len(todo) <= 7:
        order = list(min(itertools.permutations(todo), key=sortie_cost)) if todo else []
        method = "exact search over every visiting order"
    else:
        order, here, remaining = [], t_node, set(todo)
        while remaining:
            nxt = min(remaining, key=lambda i: from_node[here].get(v_nodes[i], inf))
            order.append(nxt)
            remaining.discard(nxt)
            here = h_nodes[to_hospital[nxt][1]]
        method = "nearest-feasible heuristic"
    if not order:
        raise ValueError("No victim can be reached from the rescue team on the open road network")
    stops, labels = [list(start)], ["Rescue team"]
    assignments = []
    for i in order:
        hospital = h_items[to_hospital[i][1]]
        stops.extend([list(v_points[i]), list(hospital["point"])])
        labels.extend([f"Victim {i + 1}", hospital["name"]])
        assignments.append({"victim": i + 1, "hospital": hospital["name"], "hospital_cost_s": round(to_hospital[i][0])})
    route = route_stops(stops, hazards, algorithm, mode, weather)
    route["plan"] = {"order": [i + 1 for i in order], "assignments": assignments, "method": method, "labels": labels,
                     "unreachable_victims": [i + 1 for i in unreachable], "cost_basis": f"{mode} mode time-and-risk cost"}
    route["situation"] = situation_risk(sc, len(victims))
    return route
