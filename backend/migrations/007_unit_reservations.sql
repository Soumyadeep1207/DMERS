-- =====================================================================================
-- Migration 007: planned reservations of response units (standby, training, maintenance, exercise).
--
-- "A unit cannot be booked twice for overlapping time" is a rule about ranges, and a UNIQUE index
-- cannot express it. An EXCLUDE constraint on a GiST index can: two BOOKED rows for the same unit
-- may not have overlapping periods, even when two coordinators book at the same instant (the second
-- insert waits for the first to commit, then fails with SQLSTATE 23P01). Cancelled bookings are
-- ignored by the constraint, so a slot becomes free again.
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS response.unit_reservations (
  id        INTEGER GENERATED ALWAYS AS IDENTITY CONSTRAINT pk_unit_reservations PRIMARY KEY,
  unit_id   INTEGER NOT NULL
            CONSTRAINT fk_reservations_unit REFERENCES response.response_units (id) ON DELETE CASCADE,
  purpose   VARCHAR(12) NOT NULL
            CONSTRAINT ck_reservations_purpose CHECK (purpose IN ('STANDBY', 'TRAINING', 'MAINTENANCE', 'EXERCISE')),
  note      VARCHAR(200),
  period    TSTZRANGE NOT NULL
            CONSTRAINT ck_reservations_period
              CHECK (NOT isempty(period) AND NOT lower_inf(period) AND NOT upper_inf(period)),
  status    VARCHAR(10) NOT NULL DEFAULT 'BOOKED'
            CONSTRAINT ck_reservations_status CHECK (status IN ('BOOKED', 'CANCELLED')),
  booked_by INTEGER NOT NULL CONSTRAINT fk_reservations_user REFERENCES public.users (id) ON DELETE RESTRICT,
  booked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ex_reservations_no_overlap
    EXCLUDE USING gist (unit_id WITH =, period WITH &&) WHERE (status = 'BOOKED')
);
CREATE INDEX IF NOT EXISTS ix_reservations_period ON response.unit_reservations USING gist (period);

-- Free windows of one unit inside a range: the range minus the union of its bookings (multirange arithmetic).
CREATE OR REPLACE FUNCTION response.fn_unit_free_windows(p_unit INTEGER, p_from TIMESTAMPTZ, p_to TIMESTAMPTZ)
RETURNS SETOF TSTZRANGE LANGUAGE sql STABLE AS $$
  SELECT unnest(
    tstzmultirange(tstzrange(p_from, p_to))
    - coalesce((SELECT range_agg(period) FROM response.unit_reservations
                 WHERE unit_id = p_unit AND status = 'BOOKED' AND period && tstzrange(p_from, p_to)),
               '{}'::tstzmultirange))
$$;

ALTER TABLE response.unit_reservations ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON response.unit_reservations TO dmers_rls;
DROP POLICY IF EXISTS rls_reservations_select ON response.unit_reservations;
CREATE POLICY rls_reservations_select ON response.unit_reservations FOR SELECT TO dmers_rls
  USING (response.fn_actor_type() IN ('COORDINATOR', 'UNIT_LEAD', 'ADMINISTRATOR'));

INSERT INTO public.schema_migrations (version, description)
VALUES ('007', 'Unit reservations with an EXCLUDE (gist) no-overlap constraint on tstzrange')
ON CONFLICT (version) DO NOTHING;
