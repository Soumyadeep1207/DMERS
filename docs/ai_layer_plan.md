# AI Intelligence Layer plan

## Audit and baseline

The repository uses a Flask application factory in `backend/app/app.py`, a
SQLite operational cache in `backend/app/database.py`, and a single React
Command Centre component. There are no Flask blueprints, no existing
`/api/ai/assess` endpoint, no `backend/ai` package, and no PostgreSQL runtime
adapter despite a PostgreSQL schema migration being present. Existing tests are
search and relational-integrity tests. The configured Python launcher was not
available in this workspace, so a baseline test execution could not be run.

## Files to add

- `backend/ai/`: advisory service, immutable-store guard, synthetic data,
  training and evaluation entry points, model cards and metrics.
- `backend/config/ai_ranking.yaml`: documented default ranking weights.
- `backend/migrations/002_ai_layer.sql`: PostgreSQL AI-only audit tables.
- `backend/tests/test_ai.py`: pure-function, API, fallback, and no-operational-
  mutation coverage.
- `docs/ai_layer.md`: architecture, safety, retraining, evaluation, limits.

## Files to change

- `backend/app/database.py`: SQLite-compatible `ai_assessments` and
  `ai_feedback` tables.
- `backend/app/app.py`: JWT-protected, officer-authorised AI endpoints. Route
  handlers call the AI package; AI code never imports routes.
- `backend/requirements.txt` and `README.md`: learning dependencies and setup.
- `frontend/src/RealMapApp.jsx`: advisory panel without changing command flow.

## New tables and endpoints

`ai_assessments(incident_id, kind, output_json, model_version, created_at,
created_by)` and `ai_feedback(assessment_id, officer_id, action, note,
created_at)` are the only tables AI code may write.

Endpoints: `POST /api/ai/assess`, `/classify`, `/severity`, `/credibility`,
`GET /api/ai/incidents/<id>/duplicates`, `/forecast`, and `POST /feedback`.

## Constraint handling

Because the runtime has no database-role provisioning, the AI store enforces a
code-level allow-list that permits writes only to the two AI tables. Tests
snapshot operational tables before advisory calls and prove they are unchanged.
All inference failures return a documented rules fallback, never dispatch,
assign, mutate incidents, or retrain online.
