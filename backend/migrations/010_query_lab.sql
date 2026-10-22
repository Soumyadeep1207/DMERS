-- =====================================================================================
-- Migration 010: query-optimiser laboratory (synthetic history).
--
-- lab.incident_events_flat is an ordinary heap table; lab.incident_events holds the SAME rows range
-- partitioned by month. lab.fn_load_events(n) fills both with n synthetic incidents (clearly not real
-- data), in time order, so the indexes, BRIN, partition pruning and the materialised view can be
-- compared on identical data with EXPLAIN (ANALYZE, BUFFERS). The real incident_updates table is not
-- partitioned: it is small, append-only and referenced by foreign keys.
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;
CREATE SCHEMA IF NOT EXISTS lab;

CREATE TABLE IF NOT EXISTS lab.incident_events_flat (
  id BIGINT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, zone_id INTEGER NOT NULL,
  incident_type VARCHAR(30) NOT NULL, severity VARCHAR(8) NOT NULL, status VARCHAR(10) NOT NULL,
  response_minutes NUMERIC(6, 1)
);

CREATE TABLE IF NOT EXISTS lab.incident_events (
  id BIGINT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL, zone_id INTEGER NOT NULL,
  incident_type VARCHAR(30) NOT NULL, severity VARCHAR(8) NOT NULL, status VARCHAR(10) NOT NULL,
  response_minutes NUMERIC(6, 1), PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);

DO $$
DECLARE m DATE := DATE '2025-01-01';
BEGIN
  WHILE m < DATE '2027-01-01' LOOP
    EXECUTE format('CREATE TABLE IF NOT EXISTS lab.%I PARTITION OF lab.incident_events FOR VALUES FROM (%L) TO (%L)',
                   'incident_events_' || to_char(m, 'YYYY_MM'), m, (m + INTERVAL '1 month')::date);
    m := (m + INTERVAL '1 month')::date;
  END LOOP;
  CREATE TABLE IF NOT EXISTS lab.incident_events_default PARTITION OF lab.incident_events DEFAULT;
END $$;

-- Pre-aggregated alternative to grouping a large table on every request.
CREATE MATERIALIZED VIEW IF NOT EXISTS lab.mv_zone_month AS
SELECT zone_id, date_trunc('month', occurred_at) AS month, incident_type,
       count(*)::int AS incidents, round(avg(response_minutes), 1) AS avg_response_minutes
  FROM lab.incident_events_flat GROUP BY 1, 2, 3
WITH NO DATA;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_zone_month ON lab.mv_zone_month (zone_id, month, incident_type);

-- Deterministic synthetic history: skewed incident types and three planted one-day surges
-- (so the analytics laboratory has something real to find).
CREATE OR REPLACE FUNCTION lab.fn_load_events(p_rows INTEGER, p_seed DOUBLE PRECISION DEFAULT 0.42)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
  v_zones INTEGER[] := coalesce((SELECT array_agg(id ORDER BY id) FROM response.zones), ARRAY[1, 2, 3, 4, 5, 6, 7, 8]);
  v_types TEXT[] := ARRAY['FLOOD', 'FIRE', 'MEDICAL', 'ROAD_ACCIDENT', 'GAS_LEAK', 'TREE_FALL', 'LANDSLIDE', 'BUILDING_COLLAPSE', 'WATER_RESCUE', 'OTHER'];
  v_start TIMESTAMPTZ := TIMESTAMPTZ '2025-01-01 00:00+00';
  v_span DOUBLE PRECISION := extract(epoch FROM (TIMESTAMPTZ '2026-10-01 00:00+00' - TIMESTAMPTZ '2025-01-01 00:00+00'));
  v_surge INTEGER := greatest(25, p_rows / 4000);
BEGIN
  IF p_rows < 1000 OR p_rows > 1000000 THEN RAISE EXCEPTION 'Row count must be between 1,000 and 1,000,000 (got %)', p_rows; END IF;
  TRUNCATE lab.incident_events, lab.incident_events_flat;
  PERFORM setseed(p_seed);
  INSERT INTO lab.incident_events_flat (id, occurred_at, zone_id, incident_type, severity, status, response_minutes)
  SELECT row_number() OVER (ORDER BY s.occurred_at), s.occurred_at, s.zone_id, s.incident_type, s.severity, s.status, s.response_minutes
    FROM (
      SELECT v_start + make_interval(secs => v_span * g / p_rows + random() * 60) AS occurred_at,
             v_zones[1 + floor(random() * cardinality(v_zones))::int] AS zone_id,
             v_types[1 + floor(power(random(), 1.8) * cardinality(v_types))::int] AS incident_type,
             (ARRAY['LOW', 'MODERATE', 'MODERATE', 'HIGH', 'CRITICAL'])[1 + floor(random() * 5)::int] AS severity,
             (ARRAY['CLOSED', 'CLOSED', 'CLOSED', 'RESOLVED', 'RESPONDING', 'REPORTED'])[1 + floor(random() * 6)::int] AS status,
             CASE WHEN random() < 0.15 THEN NULL ELSE round((4 + random() * 36)::numeric, 1) END AS response_minutes
        FROM generate_series(1, p_rows) g
      UNION ALL
      SELECT TIMESTAMPTZ '2025-11-10 06:00+00' + make_interval(secs => random() * 36000), v_zones[1], 'FLOOD', 'HIGH', 'CLOSED', round((8 + random() * 20)::numeric, 1)
        FROM generate_series(1, v_surge)
      UNION ALL
      SELECT TIMESTAMPTZ '2026-03-04 06:00+00' + make_interval(secs => random() * 36000), v_zones[2], 'FIRE', 'CRITICAL', 'CLOSED', round((6 + random() * 15)::numeric, 1)
        FROM generate_series(1, v_surge)
      UNION ALL
      SELECT TIMESTAMPTZ '2026-08-19 06:00+00' + make_interval(secs => random() * 36000), v_zones[3], 'ROAD_ACCIDENT', 'MODERATE', 'CLOSED', round((5 + random() * 12)::numeric, 1)
        FROM generate_series(1, v_surge)
    ) s;
  INSERT INTO lab.incident_events SELECT * FROM lab.incident_events_flat;
  DROP INDEX IF EXISTS lab.ix_flat_zone_status, lab.ix_flat_time_btree, lab.ix_flat_time_brin;
  REFRESH MATERIALIZED VIEW lab.mv_zone_month;
  ANALYZE lab.incident_events_flat;
  ANALYZE lab.incident_events;
  RETURN (SELECT count(*) FROM lab.incident_events_flat);
END $$;

INSERT INTO public.schema_migrations (version, description)
VALUES ('010', 'Query laboratory: flat and range-partitioned synthetic history, materialised view, loader')
ON CONFLICT (version) DO NOTHING;
