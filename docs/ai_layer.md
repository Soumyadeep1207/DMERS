# AI-DMERS intelligence layer

This repository has two decision-support layers, both rule-based and
advisory-only. Neither trains, loads, or calls a machine-learning model.

1. **Backend incident classification** (`backend/ai/`, documented below):
   Flask-exposed classification, severity, duplicate and credibility checks
   for incoming incident reports.
2. **Frontend route/triage decision support** (`frontend/src/modules/ai/`):
   weighted-grid routing, the five search algorithms, route policies,
   multi-target planning, scenario/playback, and team/hospital ranking. See
   [`ai_decision_support.md`](ai_decision_support.md) for that layer; it runs
   entirely client-side and does not call the backend.

## Backend incident classification

AI-DMERS is decision support only. Flask routes authenticate and authorise the
caller, then call the independent `backend/ai` package. The package reads
incident, team and hospital records, while `ai.store` can write only
`ai_assessments` and `ai_feedback`. It cannot assign resources, create a
mission, dispatch personnel, or alter incident status.

## Endpoints

- `POST /api/ai/classify` — incident type with candidates and terms.
- `POST /api/ai/severity` — predicted severity next to, never instead of,
  operational priority.
- `POST /api/ai/assess` — combined decision brief, team and hospital ranking.
- `GET /api/ai/incidents/<id>/duplicates` — suggested duplicates only.
- `POST /api/ai/credibility` — verification flag, never rejection.
- `GET /api/ai/forecast` — explicitly low-confidence seasonal-naive baseline.
- `POST /api/ai/feedback` — officer audit feedback; no online retraining.

## No training step

`backend/ai/service.py` is fixed, keyword-based rule logic (`classify`,
`severity`, `assess`, `duplicates`, `credibility`); no model is trained,
loaded, or fitted anywhere in this package, so there is no training or
evaluation command to run. `backend/ai/data/synthetic.py` exists only to
generate development fixtures for exercising the endpoints, and is unrelated
to any learned model.

## Limits

The project has no live validation and no trained model. Every endpoint
returns the documented `rules_fallback` source with evidence, confidence,
version and limitations.
