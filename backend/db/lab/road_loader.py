"""Load the offline Vellore road graph (OpenStreetMap) into the ``routing`` schema.

The projection and edge travel time are the same formulas road_network.py uses, so a route computed
in PostgreSQL can be compared number-for-number with the Python search.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"
CLASS_LABEL = ["Motorway", "Trunk road", "Primary road", "Secondary road", "Tertiary road", "Minor road", "Residential street", "Service lane"]


def loaded(conn) -> dict:
    row = conn.execute("SELECT (SELECT count(*) FROM routing.nodes) AS nodes, (SELECT count(*) FROM routing.edges) AS edges, "
                       "(SELECT count(*) FROM routing.facilities) AS facilities").fetchone()
    return dict(row)


def load(conn) -> dict:
    """Replace the contents of the routing tables from the bundled JSON files (one transaction, caller commits)."""
    raw = json.loads((DATA_DIR / "vellore_roads.json").read_text(encoding="utf-8"))
    facilities = json.loads((DATA_DIR / "vellore_facilities.json").read_text(encoding="utf-8"))["facilities"]
    lat = [n[0] for n in raw["nodes"]]
    lon = [n[1] for n in raw["nodes"]]
    lat0 = sum(lat) / len(lat)
    kx, ky = 111_320.0 * math.cos(math.radians(lat0)), 110_574.0
    x = [(v - lon[0]) * kx for v in lon]
    y = [(v - lat[0]) * ky for v in lat]
    conn.execute("TRUNCATE routing.edges, routing.nodes, routing.facilities, routing.meta")
    conn.cursor().executemany("INSERT INTO routing.meta (key, value) VALUES (%s, %s)",
                              [("lat0", lat[0]), ("lon0", lon[0]), ("kx", kx), ("ky", ky)])
    with conn.cursor().copy("COPY routing.nodes (id, lat, lon, x, y) FROM STDIN") as copy:
        for i in range(len(lat)):
            copy.write_row((i, lat[i], lon[i], x[i], y[i]))
    with conn.cursor().copy("COPY routing.edges (id, u, v, length_m, class, road, flags, speed_kmh, time_s, mx, my) FROM STDIN") as copy:
        for i, (u, v, length, cls, name_id, flags, speed) in enumerate(raw["edges"]):
            road = raw["names"][name_id] or CLASS_LABEL[cls]
            copy.write_row((i, u, v, float(length), cls, road, flags, speed, float(length) / (speed / 3.6), (x[u] + x[v]) / 2, (y[u] + y[v]) / 2))
    conn.cursor().executemany("INSERT INTO routing.facilities (id, kind, name, lat, lon) VALUES (%s, %s, %s, %s, %s)",
                              [(f["id"], f["type"], f["name"], f["lat"], f["lon"]) for f in facilities])
    conn.execute("ANALYZE routing.nodes")
    conn.execute("ANALYZE routing.edges")
    return loaded(conn)
