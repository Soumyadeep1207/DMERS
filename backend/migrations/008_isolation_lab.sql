-- =====================================================================================
-- Migration 008: scratch tables for the transaction-isolation laboratory.
--
-- The laboratory runs two real PostgreSQL sessions in a scripted interleaving and records what each
-- one sees. It uses these tables only, never the incident-response data, and resets them before
-- every run. Schema "lab" is shared by the isolation, query-optimiser and analytics laboratories.
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;
CREATE SCHEMA IF NOT EXISTS lab;

CREATE TABLE IF NOT EXISTS lab.stock (        -- lost update: one relief item, two coordinators allocate from it
  id   INTEGER PRIMARY KEY,
  item TEXT NOT NULL,
  qty  INTEGER NOT NULL CONSTRAINT ck_lab_stock_qty CHECK (qty >= 0)
);
CREATE TABLE IF NOT EXISTS lab.oncall (       -- write skew: rule "at least one medic stays on duty"
  medic   TEXT PRIMARY KEY,
  on_duty BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS lab.tickets (      -- phantom / non-repeatable read
  id       SERIAL PRIMARY KEY,
  zone     TEXT NOT NULL,
  severity TEXT NOT NULL
);

INSERT INTO public.schema_migrations (version, description)
VALUES ('008', 'Schema lab: scratch tables for the isolation-level laboratory')
ON CONFLICT (version) DO NOTHING;
