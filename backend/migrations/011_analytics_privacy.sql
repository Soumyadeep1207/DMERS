-- =====================================================================================
-- Migration 011: analytics inside the database, and a privacy-safe public export.
--
-- Window functions and regression aggregates replace the Python forecast loop: trailing mean and
-- standard deviation per zone (spike detection by z-score) and a least-squares trend per zone
-- (regr_slope / regr_intercept / regr_r2). fn_public_export() releases counts per zone, incident type and
-- month with small cells suppressed (k-anonymity style) and, optionally, Laplace noise (epsilon-differential
-- privacy for counting queries, sensitivity 1).
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;

CREATE OR REPLACE FUNCTION lab.fn_zone_daily_zscores(p_window INTEGER DEFAULT 14, p_threshold NUMERIC DEFAULT 3.0)
RETURNS TABLE (zone_id INTEGER, day DATE, n INTEGER, trailing_mean NUMERIC, trailing_sd NUMERIC, z_score NUMERIC, spike BOOLEAN)
LANGUAGE sql STABLE AS $$
  WITH bounds AS (SELECT min(occurred_at AT TIME ZONE 'UTC')::date AS lo, max(occurred_at AT TIME ZONE 'UTC')::date AS hi FROM lab.incident_events_flat),
  agg AS (SELECT e.zone_id, (e.occurred_at AT TIME ZONE 'UTC')::date AS day, count(*)::int AS n
            FROM lab.incident_events_flat e GROUP BY 1, 2),
  grid AS (SELECT z.zone_id, d::date AS day FROM (SELECT DISTINCT a.zone_id FROM agg a) z, bounds b, generate_series(b.lo, b.hi, INTERVAL '1 day') d),
  daily AS (SELECT g.zone_id, g.day, coalesce(a.n, 0) AS n FROM grid g LEFT JOIN agg a USING (zone_id, day)),
  w AS (SELECT d.*, avg(d.n) OVER win AS mean, stddev_samp(d.n) OVER win AS sd, count(*) OVER win AS seen
          FROM daily d WINDOW win AS (PARTITION BY d.zone_id ORDER BY d.day ROWS BETWEEN p_window PRECEDING AND 1 PRECEDING))
  SELECT w.zone_id, w.day, w.n, round(w.mean, 2), round(w.sd, 2),
         CASE WHEN w.seen = p_window AND w.sd > 0 THEN round((w.n - w.mean) / w.sd, 2) END,
         coalesce(w.seen = p_window AND w.sd > 0 AND (w.n - w.mean) / w.sd >= p_threshold, false)
    FROM w ORDER BY w.zone_id, w.day
$$;

CREATE OR REPLACE FUNCTION lab.fn_zone_forecast(p_history INTEGER DEFAULT 28, p_horizon INTEGER DEFAULT 7)
RETURNS TABLE (zone_id INTEGER, avg_last_7 NUMERIC, avg_history NUMERIC, slope_per_day NUMERIC, r_squared NUMERIC,
               forecast_next_day NUMERIC, forecast_horizon_total NUMERIC)
LANGUAGE sql STABLE AS $$
  WITH agg AS (SELECT e.zone_id, (e.occurred_at AT TIME ZONE 'UTC')::date AS day, count(*)::int AS n
                 FROM lab.incident_events_flat e GROUP BY 1, 2),
  hi AS (SELECT max(day) AS hi FROM agg),
  grid AS (SELECT z.zone_id, d::date AS day, (d::date - (SELECT hi FROM hi)) AS x
             FROM (SELECT DISTINCT a.zone_id FROM agg a) z, hi,
                  generate_series(hi.hi - (p_history - 1), hi.hi, INTERVAL '1 day') d),
  daily AS (SELECT g.zone_id, g.x, coalesce(a.n, 0) AS n FROM grid g LEFT JOIN agg a USING (zone_id, day)),
  fit AS (SELECT zone_id, regr_slope(n, x) AS b, regr_intercept(n, x) AS a, regr_r2(n, x) AS r2,
                 avg(n) AS mean_all, avg(n) FILTER (WHERE x > -7) AS mean7
            FROM daily GROUP BY zone_id)
  SELECT f.zone_id, round(f.mean7, 2), round(f.mean_all, 2), round(f.b::numeric, 3), round(f.r2::numeric, 3),
         round(greatest(0, f.a + f.b)::numeric, 2),
         round((SELECT sum(greatest(0, f.a + f.b * h)) FROM generate_series(1, p_horizon) h)::numeric, 1)
    FROM fit f ORDER BY f.zone_id
$$;

CREATE OR REPLACE FUNCTION lab.fn_public_export(p_source TEXT DEFAULT 'history', p_k INTEGER DEFAULT 5,
                                                p_epsilon NUMERIC DEFAULT NULL, p_seed DOUBLE PRECISION DEFAULT NULL)
RETURNS TABLE (zone_name TEXT, incident_type TEXT, month DATE, true_count INTEGER, released_count INTEGER, suppressed BOOLEAN)
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
  IF p_source NOT IN ('history', 'live') THEN RAISE EXCEPTION 'source must be history or live'; END IF;
  IF p_k < 1 THEN RAISE EXCEPTION 'k must be at least 1'; END IF;
  IF p_epsilon IS NOT NULL AND p_epsilon <= 0 THEN RAISE EXCEPTION 'epsilon must be positive'; END IF;
  IF p_seed IS NOT NULL THEN PERFORM setseed(p_seed); END IF;
  RETURN QUERY
  WITH cells AS (
    SELECT coalesce(z.zone_name, 'Zone ' || e.zone_id)::text AS zone_name, e.incident_type::text AS incident_type,
           date_trunc('month', e.occurred_at AT TIME ZONE 'UTC')::date AS month, count(*)::int AS n
      FROM lab.incident_events_flat e LEFT JOIN response.zones z ON z.id = e.zone_id
     WHERE p_source = 'history' GROUP BY 1, 2, 3
    UNION ALL
    SELECT z.zone_name::text, i.incident_type::text, date_trunc('month', i.created_at AT TIME ZONE 'UTC')::date, count(*)::int
      FROM response.incidents i JOIN response.zones z ON z.id = i.zone_id
     WHERE p_source = 'live' AND i.status <> 'REJECTED' GROUP BY 1, 2, 3),
  noisy AS (
    SELECT c.zone_name, c.incident_type, c.month, c.n,
           CASE WHEN p_epsilon IS NULL THEN c.n::numeric
                ELSE c.n + (-(1.0 / p_epsilon) * sign(u.v) * ln(1 - 2 * abs(u.v)))::numeric END AS released
      FROM cells c CROSS JOIN LATERAL (SELECT random() - 0.5 + c.n * 0 AS v) u)
  SELECT nz.zone_name, nz.incident_type, nz.month, nz.n,
         CASE WHEN greatest(0, round(nz.released))::int < p_k THEN NULL ELSE greatest(0, round(nz.released))::int END,
         greatest(0, round(nz.released))::int < p_k
    FROM noisy nz ORDER BY nz.zone_name, nz.incident_type, nz.month;
END $$;

INSERT INTO public.schema_migrations (version, description)
VALUES ('011', 'In-database analytics (z-score spikes, regression forecast) and a k-suppressed / Laplace-noised public export')
ON CONFLICT (version) DO NOTHING;
