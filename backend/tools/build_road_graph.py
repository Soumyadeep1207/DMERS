"""Build DMERS's offline Vellore road graph from an OpenStreetMap Overpass export.

Usage (run once, on a machine with the raw export):
    python -I tools/build_road_graph.py raw_overpass.json app/data/vellore_roads.json

The raw export comes from this Overpass query (bounding box south,west,north,east):
    [out:json][timeout:120];
    way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|
                    residential|living_street|*_link)$"](12.875,79.095,12.960,79.175);
    out body; >; out skel qt;

The output is a compact directed-edge list. Only the largest connected component is kept
so every routable node can reach every other, which keeps "no route" results meaningful.
Map data (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict, deque
from datetime import date

BBOX = (12.875, 79.095, 12.960, 79.175)
CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"]
# Planning free-flow speeds (km/h) when OSM has no maxspeed tag. Urban Indian roads rarely
# sustain posted limits, so these are deliberately conservative.
DEFAULT_SPEED = {"motorway": 70, "trunk": 50, "primary": 40, "secondary": 35, "tertiary": 30,
                 "unclassified": 25, "residential": 20, "living_street": 10}
FLAG_ONEWAY, FLAG_BRIDGE, FLAG_UNPAVED = 1, 2, 4
UNPAVED = {"unpaved", "dirt", "gravel", "ground", "sand", "mud", "earth", "grass", "compacted", "fine_gravel"}


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(h))


def parse_speed(value: str | None) -> int:
    if not value:
        return 0
    digits = "".join(ch for ch in value.split(";")[0] if ch.isdigit())
    return int(digits) if digits and 5 <= int(digits) <= 120 else 0


def build(raw: dict) -> dict:
    coords = {e["id"]: (e["lat"], e["lon"]) for e in raw["elements"] if e["type"] == "node"}
    names: list[str] = [""]
    name_ids = {"": 0}
    arcs: dict[tuple[int, int], list] = {}
    for way in (e for e in raw["elements"] if e["type"] == "way"):
        tags = way.get("tags", {})
        highway = tags.get("highway", "").removesuffix("_link")
        if highway not in CLASSES or tags.get("access") in {"private", "no"}:
            continue
        label = tags.get("name") or tags.get("ref") or ""
        name_id = name_ids.setdefault(label, len(names))
        if name_id == len(names):
            names.append(label)
        oneway = tags.get("oneway") in {"yes", "1", "true"}
        reverse = tags.get("oneway") == "-1"
        speed = parse_speed(tags.get("maxspeed")) or DEFAULT_SPEED[highway]
        flags = (FLAG_ONEWAY if oneway or reverse else 0) | (FLAG_BRIDGE if tags.get("bridge") in {"yes", "viaduct"} else 0) \
            | (FLAG_UNPAVED if tags.get("surface") in UNPAVED else 0)
        refs = [n for n in way["nodes"] if n in coords]
        if reverse:
            refs.reverse()
        for a, b in zip(refs, refs[1:]):
            if a == b:
                continue
            length = round(haversine(coords[a], coords[b]), 1)
            record = [a, b, length, CLASSES.index(highway), name_id, flags, speed]
            arcs[(a, b)] = record
            if not (oneway or reverse):
                arcs[(b, a)] = [b, a, *record[2:]]

    # Largest weakly connected component, so every node can be reached by every other.
    neighbours: dict[int, set[int]] = defaultdict(set)
    for a, b in arcs:
        neighbours[a].add(b)
        neighbours[b].add(a)
    best: set[int] = set()
    seen: set[int] = set()
    for root in neighbours:
        if root in seen:
            continue
        component, queue = {root}, deque([root])
        seen.add(root)
        while queue:
            for nxt in neighbours[queue.popleft()]:
                if nxt not in seen:
                    seen.add(nxt)
                    component.add(nxt)
                    queue.append(nxt)
        if len(component) > len(best):
            best = component

    order = sorted(best)
    index = {osm_id: i for i, osm_id in enumerate(order)}
    edges = [[index[a], index[b], *rest] for (a, b), (_, _, *rest) in arcs.items() if a in best and b in best]
    edges.sort()
    used_names = sorted({edge[4] for edge in edges})
    remap = {old: new for new, old in enumerate(used_names)}
    for edge in edges:
        edge[4] = remap[edge[4]]
    return {
        "meta": {
            "source": "OpenStreetMap contributors via Overpass API", "license": "ODbL 1.0",
            "attribution": "(c) OpenStreetMap contributors", "built": date.today().isoformat(),
            "bbox": BBOX, "classes": CLASSES, "edge_fields": ["from", "to", "length_m", "class", "name", "flags", "speed_kmh"],
            "flags": {"oneway": FLAG_ONEWAY, "bridge": FLAG_BRIDGE, "unpaved": FLAG_UNPAVED},
        },
        "names": [names[i] for i in used_names],
        "nodes": [[round(coords[osm_id][0], 6), round(coords[osm_id][1], 6)] for osm_id in order],
        "edges": edges,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as source:
        graph = build(json.load(source))
    with open(sys.argv[2], "w", encoding="utf-8") as target:
        json.dump(graph, target, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(graph['nodes'])} nodes, {len(graph['edges'])} directed edges, {len(graph['names'])} road names")
