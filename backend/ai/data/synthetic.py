"""Clearly labelled, deterministic development-only training rows."""
from __future__ import annotations
import random

def generate(seed: int = 7, per_type: int = 12) -> list[dict]:
    random.seed(seed); rows=[]
    samples={"flood":"Flood water rising near bridge", "fire":"Fire and smoke reported in building", "medical emergency":"Injured person needs ambulance", "earthquake damage":"Earthquake rubble blocks access", "road obstruction":"Road blocked by landslide"}
    for kind, text in samples.items():
        for index in range(per_type): rows.append({"description": f"{text} sector {index}", "type":kind, "severity":random.choice(["moderate","high","critical"]), "is_synthetic":True})
    return rows
