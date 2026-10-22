-- AI advisory audit records. These tables are the only database write target
-- for the AI application role; operational tables remain read-only to AI.
CREATE TABLE ai_assessments (
  id BIGSERIAL PRIMARY KEY,
  incident_id BIGINT REFERENCES incidents(id),
  kind TEXT NOT NULL,
  output_json JSONB NOT NULL,
  model_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by BIGINT REFERENCES users(id)
);
CREATE INDEX idx_ai_assessments_incident ON ai_assessments(incident_id, created_at DESC);
CREATE TABLE ai_feedback (
  id BIGSERIAL PRIMARY KEY,
  assessment_id BIGINT NOT NULL REFERENCES ai_assessments(id),
  officer_id BIGINT NOT NULL REFERENCES users(id),
  action TEXT NOT NULL CHECK(action IN ('accepted','overridden','dismissed')),
  note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
