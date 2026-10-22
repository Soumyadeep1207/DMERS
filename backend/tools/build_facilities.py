"""Bundle real Vellore emergency facilities from an OpenStreetMap Overpass export.

Usage:  python -I tools/build_facilities.py raw_facilities.json app/data/vellore_facilities.json

Overpass query (bounding box south,west,north,east):
    [out:json][timeout:60];
    ( node["amenity"~"^(hospital|fire_station|police|shelter)$"](12.875,79.095,12.960,79.175);
      way["amenity"~"^(hospital|fire_station|police|shelter)$"](12.875,79.095,12.960,79.175); );
    out center tags;

OpenStreetMap does not hold live bed counts, so none are invented here: capacity is entered by the
hospital portal or the Hospital capacity module. Hospitals whose name marks a single speciality
(eye, dental, yoga/nature cure, diabetes, herbal) are flagged as not emergency-capable so they are
not offered as casualty receiving sites by default.
Map data (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date

SPECIALITY = re.compile(r"\b(eye|dental|yoga|naturecure|nature cure|diabetes|herbo[a-z]*|clinic|ayush|physio[a-z]*)\b", re.IGNORECASE)
LABELS = {"hospital": "Hospital", "fire_station": "Fire station", "police": "Police station", "shelter": "Shelter"}


def build(raw: dict) -> dict:
    items = []
    for element in raw["elements"]:
        tags = element.get("tags", {})
        kind = tags.get("amenity")
        if kind not in LABELS:
            continue
        centre = element.get("center") or element
        name = (tags.get("name") or "").strip()
        emergency = kind == "hospital" and (tags.get("emergency") == "yes" or not SPECIALITY.search(name))
        if not name:
            name = "Unnamed emergency facility" if tags.get("emergency") == "yes" else f"Unnamed {LABELS[kind].lower()}"
        items.append({
            "id": f"osm-{element['type']}-{element['id']}", "type": kind, "name": name,
            "lat": round(centre["lat"], 6), "lon": round(centre["lon"], 6),
            "emergency_capable": emergency if kind == "hospital" else True,
            "beds": None, "phone": tags.get("phone") or tags.get("contact:phone"),
        })
    items.sort(key=lambda item: (item["type"], not item["emergency_capable"], item["name"]))
    return {"source": "OpenStreetMap contributors via Overpass API", "license": "ODbL 1.0", "attribution": "(c) OpenStreetMap contributors",
            "built": date.today().isoformat(), "note": "Bed counts are not in OpenStreetMap; enter live capacity in DMERS.", "facilities": items}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as source:
        data = build(json.load(source))
    with open(sys.argv[2], "w", encoding="utf-8") as target:
        json.dump(data, target, indent=1, ensure_ascii=False)
    kinds = {}
    for item in data["facilities"]:
        kinds[item["type"]] = kinds.get(item["type"], 0) + 1
    print(kinds, "emergency-capable hospitals:", sum(1 for i in data["facilities"] if i["type"] == "hospital" and i["emergency_capable"]))
