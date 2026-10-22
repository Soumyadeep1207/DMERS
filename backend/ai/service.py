"""Explainable, advisory-only AI-DMERS decision support.

No function in this module creates missions, dispatches teams, or changes an
incident. Ranking defaults retain the historic operational heuristic: flood
reports prefer flood capability; hospitals rank by available beds.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
import json

TYPES = ("medical emergency", "trapped or missing person", "fire", "flood", "earthquake damage", "need shelter or relief", "road obstruction", "public safety advisory")
SEVERITIES = ("low", "moderate", "high", "critical")
VERSION = "ai-dmers-rules-1.0"
LIMITATIONS = "Rules-based advisory only; not a trained model. Officers must independently verify every recommendation."

def _envelope(value, confidence, evidence, source="rules_fallback", **extra):
    return {"value": value, "confidence": round(float(confidence), 3), "evidence": evidence, "model_version": VERSION, "limitations": LIMITATIONS, "source": source, **extra}

def _terms(text: str) -> list[str]: return [word.lower().strip(".,!?;:") for word in text.split() if len(word) > 2]

def classify(description: str, reported_type: str = "") -> dict:
    """Classify with transparent fixed rules; no learned model is loaded or used."""
    text = (description + " " + reported_type).lower()
    keys = {"flood": ("flood", "water", "inundat", "river"), "fire": ("fire", "smoke", "burn", "flame"), "earthquake damage": ("earthquake", "collapse", "tremor", "rubble"), "medical emergency": ("medical", "injur", "ambulance", "bleed"), "road obstruction": ("road", "blocked", "landslide", "bridge"), "trapped or missing person": ("trapped", "missing", "stuck"), "need shelter or relief": ("shelter", "food", "relief", "homeless")}
    scores = {kind: sum(token in text for token in words) for kind, words in keys.items()}
    if reported_type.lower() in TYPES: scores[reported_type.lower()] = scores.get(reported_type.lower(), 0) + 1
    best = max(scores, key=scores.get) if max(scores.values()) else (reported_type.lower() if reported_type.lower() in TYPES else "public safety advisory")
    candidates = sorted(({"type": k, "score": v} for k, v in scores.items()), key=lambda item: item["score"], reverse=True)[:3]
    confidence = .75 if scores.get(best, 0) >= 2 else .55 if scores.get(best, 0) else .35
    return _envelope(best, confidence, {"matched_terms": [term for term in _terms(text) if any(term in words for words in keys.values())], "reported_type": reported_type or None}, top_candidates=candidates)

def severity(payload: dict) -> dict:
    text = payload.get("description", "").lower(); reported = payload.get("reported_severity", "").lower()
    score = (2 if any(w in text for w in ("trapped", "collapse", "multiple", "unconscious")) else 0) + (1 if any(w in text for w in ("fire", "flood", "injured", "blocked")) else 0)
    predicted = SEVERITIES[min(3, score)]
    if reported in SEVERITIES: predicted = max((predicted, reported), key=SEVERITIES.index)
    return _envelope(predicted, .6 if score else .4, {"risk_terms": [w for w in ("trapped", "collapse", "multiple", "fire", "flood", "injured") if w in text], "reported_severity": reported or None}, feature_importances={"risk_terms": .7, "reported_severity": .3})

def assess(payload: dict, teams: list[dict], hospitals: list[dict]) -> dict:
    classification = classify(payload.get("description", ""), payload.get("type", ""))
    predicted = severity({"description": payload.get("description", ""), "reported_severity": payload.get("severity", "")})
    severity_value = payload.get("severity", "moderate").lower()
    priority = {"low": 20, "moderate": 40, "high": 50, "critical": 60}.get(severity_value, 40)
    ranked_teams = sorted(teams, key=lambda t: (classification["value"] == "flood" and "flood" in t["capability"].lower(), t["availability"] == "available"), reverse=True)
    ranked_hospitals = sorted(hospitals, key=lambda h: h.get("available_beds", 0), reverse=True)
    return {"priority": "Critical" if priority >= 60 else severity_value.title(), "priority_score": priority, "ranked_teams": ranked_teams, "ranked_hospitals": ranked_hospitals, "predicted_severity": predicted, "classification": classification, "decision_brief": {"advisory": True, "officer_decides": True, "classification": classification, "predicted_severity": predicted}, "model_version": VERSION, "limitations": LIMITATIONS, "source": "rules_fallback"}

def duplicates(target: dict, incidents: list[dict]) -> list[dict]:
    target_terms = set(_terms(target.get("description", ""))); candidates=[]
    for incident in incidents:
        if incident["id"] == target["id"]: continue
        other_terms=set(_terms(incident.get("description", ""))); similarity=len(target_terms & other_terms)/max(1, len(target_terms | other_terms))
        if similarity >= .2: candidates.append({"incident_id": incident["id"], "reference": incident["reference"], "similarity": round(similarity,3), "reasons": ["overlapping report terms"], "confidence": round(similarity,3), "model_version": VERSION, "limitations": LIMITATIONS})
    return sorted(candidates, key=lambda c:c["similarity"], reverse=True)

def credibility(payload: dict) -> dict:
    text=payload.get("description", "").strip(); signals=[]; score=.5
    if len(text) >= 30: score += .2; signals.append("report includes operational detail")
    if payload.get("location"): score += .15; signals.append("location supplied")
    if text.count("!") > 3: score -= .15; signals.append("excessive punctuation requires review")
    band = "high" if score >= .75 else "medium" if score >= .5 else "low"
    return _envelope(band, abs(score-.5)+.4, {"signals": signals, "completeness": min(1, len(text)/100)})

def forecast(incidents: list[dict], region: str, incident_type: str, days: int) -> dict:
    matching=[i for i in incidents if (not incident_type or i["disaster_type"] == incident_type)]
    baseline=len(matching)/max(1, 30); values=[round(baseline,2) for _ in range(days)]
    return _envelope(values, .3, {"historical_rows": len(matching), "method": "seasonal-naive baseline", "region": region or "all"}, baseline=values, interval=[max(0, round(baseline*.5,2)), round(baseline*1.5+1,2)])
