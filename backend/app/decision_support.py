"""Explainable, deterministic incident triage recommendations for DMERS.

This is a rules-based decision-support component, not a trained predictive model.
It only ranks records using the incident, team, mission, and hospital data supplied
by the application database. It never assigns a team or changes incident state.
"""
from __future__ import annotations


SEVERITY_POINTS = {"critical": 45, "high": 34, "moderate": 22, "low": 10}
STATUS_POINTS = {"reported": 15, "verified": 8, "dispatched": 0, "resolved": 0, "closed": 0}

CAPABILITY_TERMS = {
    "flood": ("flood", "water", "rescue"),
    "water rescue": ("flood", "water", "rescue"),
    "fire": ("fire", "hazmat", "structural"),
    "gas": ("fire", "hazmat"),
    "medical": ("medical", "ambulance", "health", "evacuation"),
    "road": ("rescue", "medical", "police", "traffic"),
    "accident": ("rescue", "medical", "ambulance", "police"),
    "earthquake": ("structural", "rescue", "fire"),
    "collapse": ("structural", "rescue", "fire"),
    "landslide": ("rescue", "structural", "earthquake"),
}


def _capability_terms(incident: dict) -> tuple[str, ...]:
    text = " ".join(str(incident.get(key) or "") for key in ("disaster_type", "description")).lower()
    for label, terms in CAPABILITY_TERMS.items():
        if label in text:
            return terms
    return ("rescue", "medical")


def build_advisory(incident: dict, teams: list[dict], hospitals: list[dict]) -> dict:
    """Build a human-readable priority, team, and hospital advisory."""
    severity = str(incident.get("severity") or "low").lower()
    status = str(incident.get("status") or "reported").lower()
    severity_points = SEVERITY_POINTS.get(severity, SEVERITY_POINTS["low"])
    status_points = STATUS_POINTS.get(status, 0)
    score = min(100, severity_points + status_points)
    priority = "CRITICAL" if score >= 55 else "HIGH" if score >= 40 else "MODERATE" if score >= 25 else "LOW"
    risk_factors = [
        {"factor": "Recorded severity", "evidence": severity.title(), "points": severity_points},
        {"factor": "Workflow status", "evidence": status.replace("_", " ").title(), "points": status_points},
    ]
    if incident.get("latitude") is None or incident.get("longitude") is None:
        risk_factors.append({"factor": "Location confidence", "evidence": "Coordinates missing; location needs confirmation", "points": None})

    terms = _capability_terms(incident)
    ranked_teams = []
    for team in teams:
        capability = str(team.get("capability") or "").lower()
        matched = [term for term in terms if term in capability]
        availability = str(team.get("availability") or "unavailable").lower()
        workload = int(team.get("active_missions") or 0)
        capability_points = min(40, (20 if matched else 0) + (15 if terms[0] in matched else 0) + 5 * max(0, len(matched) - 1))
        availability_points = {"available": 25, "deployed": 5, "unavailable": 0}.get(availability, 0)
        workload_penalty = min(workload * 10, 30)
        team_score = max(0, capability_points + availability_points - workload_penalty)
        reasons = []
        reasons.append(f"Capability match: {', '.join(matched)}" if matched else f"No direct match for {', '.join(terms)}")
        reasons.append(f"Availability: {availability}")
        reasons.append(f"Active missions: {workload}")
        ranked_teams.append({
            "id": team.get("id"), "name": team.get("name"), "capability": team.get("capability"),
            "availability": availability, "active_missions": workload, "score": team_score,
            "matched_terms": matched, "reasons": reasons,
        })
    ranked_teams.sort(key=lambda item: (-item["score"], -len(item["matched_terms"]), item["active_missions"], item["name"] or ""))

    ranked_hospitals = []
    for hospital in hospitals:
        beds = int(hospital.get("available_beds") or 0)
        hospital_status = str(hospital.get("status") or "unknown").lower()
        accepting = hospital_status in {"accepting", "limited"} and beds > 0
        ranked_hospitals.append({
            "id": hospital.get("id"), "name": hospital.get("name"), "status": hospital_status,
            "available_beds": beds, "location": hospital.get("location"),
            "recommended": accepting,
            "reason": f"{beds} beds available; status {hospital_status}" if accepting else f"Not recommended: {beds} beds available; status {hospital_status}",
        })
    ranked_hospitals.sort(key=lambda item: (not item["recommended"], -item["available_beds"], item["name"] or ""))

    return {
        "incident": {key: incident.get(key) for key in ("id", "reference", "disaster_type", "severity", "status", "description", "location", "latitude", "longitude")},
        "priority": {"score": score, "label": priority, "explanation": f"{severity_points} severity points + {status_points} status points, capped at 100."},
        "risk_factors": risk_factors,
        "team_candidates": ranked_teams,
        "hospital_candidates": ranked_hospitals,
        "capability_basis": list(terms),
        "limitations": [
            "This is a transparent rules-based advisory, not a trained AI model or a prediction.",
            "Team records do not contain current coordinates, so candidates are not ranked by travel distance.",
            "Hospital capacity is only as current as its recorded bed count and status.",
            "An authorised officer must verify the report and choose whether to act; no dispatch is made.",
        ],
    }
