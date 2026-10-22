"""Shared, explainable risk scoring for every DMERS calculation.

A risk score is always the weighted sum of named factors, each normalised to 0..1, so the
operator can see exactly which input moved the number. Weights in one model sum to 1.
These scores are decision-support indicators, not calibrated probabilities of harm.
"""
from __future__ import annotations

BANDS = ((20, "LOW"), (40, "MODERATE"), (65, "HIGH"), (101, "SEVERE"))
BAND_GUIDANCE = {
    "LOW": "Proceed with standard checks.",
    "MODERATE": "Proceed, but brief the crew on the flagged factors and keep an alternate ready.",
    "HIGH": "Commander review recommended before dispatch; prefer the safer alternative if time allows.",
    "SEVERE": "Do not dispatch on this plan without a commander decision and a verified alternate.",
}


def band(score: float) -> str:
    for ceiling, label in BANDS:
        if score < ceiling:
            return label
    return "SEVERE"


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def factor(name: str, raw, unit: str, normalised: float, weight: float, note: str) -> dict:
    normalised = clamp01(normalised)
    return {
        "name": name, "value": raw, "unit": unit, "normalised": round(normalised, 3),
        "weight": weight, "points": round(100 * weight * normalised, 1), "note": note,
    }


def compose(factors: list[dict], formula: str, assumptions: list[str]) -> dict:
    total_weight = round(sum(item["weight"] for item in factors), 6)
    if total_weight != 1.0:
        raise ValueError(f"Risk weights must sum to 1 (got {total_weight})")
    score = round(min(100.0, sum(item["points"] for item in factors)), 1)
    label = band(score)
    ranked = sorted(factors, key=lambda item: -item["points"])
    return {
        "score": score, "band": label, "guidance": BAND_GUIDANCE[label], "formula": formula,
        "factors": factors, "top_factor": ranked[0]["name"] if ranked and ranked[0]["points"] > 0 else None,
        "assumptions": assumptions,
    }
