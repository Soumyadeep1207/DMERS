-- AI advisory audit records. These tables are the only database write target
-- for the AI application role; operational tables remain read-only to AI.
CREATE TABLE IF NOT EXISTS ai_assessments (
  id BIGSERIAL PRIMARY KEY,
  incident_id BIGINT REFERENCES incidents(id),
  kind TEXT NOT NULL,
  output_json JSONB NOT NULL,
  model_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by BIGINT REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_ai_assessments_incident ON ai_assessments(incident_id, created_at DESC);
CREATE TABLE IF NOT EXISTS ai_feedback (
  id BIGSERIAL PRIMARY KEY,
  assessment_id BIGINT NOT NULL REFERENCES ai_assessments(id),
  officer_id BIGINT NOT NULL REFERENCES users(id),
  action TEXT NOT NULL CHECK(action IN ('accepted','overridden','dismissed')),
  note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- recorded here as well so a psql run (docker-entrypoint-initdb.d) and the application runner agree
CREATE TABLE IF NOT EXISTS public.schema_migrations (version TEXT PRIMARY KEY, description TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO public.schema_migrations (version, description) VALUES ('004', 'AI advisory audit tables (ai_assessments, ai_feedback)') ON CONFLICT (version) DO NOTHING;
