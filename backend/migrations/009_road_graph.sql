-- =====================================================================================
-- Migration 009: the Vellore road network inside PostgreSQL (schema "routing").
--
-- Routing normally runs in Python (road_network.py). Here the same graph lives in tables and the
-- search runs in the database: nearest road node and nearest facility by k-nearest-neighbour search
-- on a GiST index (cube + earthdistance, both shipped with PostgreSQL), closed segments from hazard
-- circles, and A* in PL/pgSQL. PostGIS / pgRouting are deliberately NOT required, so the existing
-- database image and data volume stay untouched. Data is loaded by db/lab/road_loader.py.
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;
CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;
CREATE SCHEMA IF NOT EXISTS routing;

CREATE TABLE IF NOT EXISTS routing.meta (key TEXT PRIMARY KEY, value DOUBLE PRECISION NOT NULL);

CREATE TABLE IF NOT EXISTS routing.nodes (
  id  INTEGER PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL,
  x   DOUBLE PRECISION NOT NULL, y   DOUBLE PRECISION NOT NULL,       -- planar metres, same projection as road_network.py
  geo public.earth GENERATED ALWAYS AS (public.ll_to_earth(lat, lon)) STORED
);
CREATE INDEX IF NOT EXISTS ix_nodes_geo ON routing.nodes USING gist (geo);

CREATE TABLE IF NOT EXISTS routing.edges (
  id        INTEGER PRIMARY KEY,
  u         INTEGER NOT NULL REFERENCES routing.nodes (id),
  v         INTEGER NOT NULL REFERENCES routing.nodes (id),
  length_m  REAL NOT NULL,
  class     SMALLINT NOT NULL,
  road      TEXT NOT NULL,
  flags     SMALLINT NOT NULL,
  speed_kmh SMALLINT NOT NULL,
  time_s    DOUBLE PRECISION NOT NULL,                                 -- length / speed, clear weather
  mx        DOUBLE PRECISION NOT NULL, my DOUBLE PRECISION NOT NULL    -- planar midpoint, for the hazard pre-filter
);
CREATE INDEX IF NOT EXISTS ix_edges_u ON routing.edges (u);

CREATE TABLE IF NOT EXISTS routing.facilities (
  id   TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  lat  DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL,
  geo  public.earth GENERATED ALWAYS AS (public.ll_to_earth(lat, lon)) STORED
);
CREATE INDEX IF NOT EXISTS ix_facilities_geo ON routing.facilities USING gist (geo);

-- Planar projection used by road_network.py: metres east/north of the first node.
CREATE OR REPLACE FUNCTION routing.fn_project(p_lat DOUBLE PRECISION, p_lon DOUBLE PRECISION, OUT x DOUBLE PRECISION, OUT y DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
  SELECT (p_lon - (SELECT value FROM routing.meta WHERE key = 'lon0')) * (SELECT value FROM routing.meta WHERE key = 'kx'),
         (p_lat - (SELECT value FROM routing.meta WHERE key = 'lat0')) * (SELECT value FROM routing.meta WHERE key = 'ky')
$$;

CREATE OR REPLACE FUNCTION routing.fn_segment_distance(px DOUBLE PRECISION, py DOUBLE PRECISION, ax DOUBLE PRECISION, ay DOUBLE PRECISION,
                                                       bx DOUBLE PRECISION, by DOUBLE PRECISION)
RETURNS DOUBLE PRECISION LANGUAGE sql IMMUTABLE AS $$
  WITH s AS (SELECT (bx - ax) ^ 2 + (by - ay) ^ 2 AS span),
       t AS (SELECT CASE WHEN span = 0 THEN 0.0
                         ELSE greatest(0.0, least(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / span)) END AS t FROM s)
  SELECT sqrt((px - (ax + t * (bx - ax))) ^ 2 + (py - (ay + t * (by - ay))) ^ 2) FROM t
$$;

-- k nearest road nodes by great-circle distance (GiST KNN scan, no sort of the whole table).
CREATE OR REPLACE FUNCTION routing.fn_nearest_nodes(p_lat DOUBLE PRECISION, p_lon DOUBLE PRECISION, p_k INTEGER DEFAULT 1)
RETURNS TABLE (node_id INTEGER, distance_m DOUBLE PRECISION) LANGUAGE sql STABLE AS $$
  SELECT n.id, public.earth_distance(n.geo, public.ll_to_earth(p_lat, p_lon))
    FROM routing.nodes n ORDER BY n.geo OPERATOR(public.<->) public.ll_to_earth(p_lat, p_lon) LIMIT p_k
$$;

-- Edge ids closed by hazard circles: [{"lat":..,"lon":..,"radius_m":..}] (distance to the real segment, not its midpoint).
CREATE OR REPLACE FUNCTION routing.fn_closed_edges(p_hazards JSONB)
RETURNS INTEGER[] LANGUAGE sql STABLE AS $$
  SELECT coalesce(array_agg(DISTINCT e.id), '{}'::integer[])
    FROM jsonb_to_recordset(p_hazards) AS h(lat DOUBLE PRECISION, lon DOUBLE PRECISION, radius_m DOUBLE PRECISION)
    CROSS JOIN LATERAL routing.fn_project(h.lat, h.lon) p
    JOIN routing.edges e ON abs(e.mx - p.x) <= h.radius_m + e.length_m AND abs(e.my - p.y) <= h.radius_m + e.length_m
    JOIN routing.nodes a ON a.id = e.u
    JOIN routing.nodes b ON b.id = e.v
   WHERE routing.fn_segment_distance(p.x, p.y, a.x, a.y, b.x, b.y) <= h.radius_m
$$;

-- A* from p_src to p_dst on travel time, skipping closed edges. Straight-line time at the fastest speed is the
-- admissible heuristic. The number of nodes expanded is left in the transaction setting routing.last_explored.
CREATE OR REPLACE FUNCTION routing.fn_route(p_src INTEGER, p_dst INTEGER, p_closed INTEGER[] DEFAULT '{}')
RETURNS TABLE (step INTEGER, edge_id INTEGER, from_node INTEGER, to_node INTEGER, length_m REAL, time_s DOUBLE PRECISION, road TEXT)
LANGUAGE plpgsql AS $$
DECLARE
  v_vmax DOUBLE PRECISION; v_goal public.earth; v_cur INTEGER; v_g DOUBLE PRECISION;
  v_found BOOLEAN := false; v_explored INTEGER := 0; v_edges INTEGER[] := '{}'; v_edge INTEGER;
BEGIN
  SELECT max(speed_kmh) / 3.6 INTO v_vmax FROM routing.edges;
  SELECT geo INTO v_goal FROM routing.nodes WHERE id = p_dst;
  IF v_goal IS NULL OR NOT EXISTS (SELECT 1 FROM routing.nodes WHERE id = p_src) THEN
    RAISE EXCEPTION 'Unknown road node (source %, destination %). Load the road graph first.', p_src, p_dst;
  END IF;
  DROP TABLE IF EXISTS pg_temp._astar;
  CREATE TEMP TABLE _astar (node INTEGER PRIMARY KEY, g DOUBLE PRECISION NOT NULL, f DOUBLE PRECISION NOT NULL,
                            parent_edge INTEGER, done BOOLEAN NOT NULL DEFAULT false) ON COMMIT DROP;
  CREATE INDEX ON _astar (f) WHERE NOT done;
  INSERT INTO _astar (node, g, f) VALUES (p_src, 0, 0);
  LOOP
    v_cur := NULL;
    SELECT a.node, a.g INTO v_cur, v_g FROM _astar a WHERE NOT a.done ORDER BY a.f LIMIT 1;
    EXIT WHEN v_cur IS NULL;
    UPDATE _astar SET done = true WHERE node = v_cur;
    v_explored := v_explored + 1;
    IF v_cur = p_dst THEN v_found := true; EXIT; END IF;
    INSERT INTO _astar (node, g, f, parent_edge)
    SELECT e.v, v_g + e.time_s, v_g + e.time_s + public.earth_distance(n.geo, v_goal) / v_vmax, e.id
      FROM routing.edges e JOIN routing.nodes n ON n.id = e.v
     WHERE e.u = v_cur AND NOT (e.id = ANY (p_closed))
    ON CONFLICT (node) DO UPDATE SET g = EXCLUDED.g, f = EXCLUDED.f, parent_edge = EXCLUDED.parent_edge
      WHERE NOT _astar.done AND EXCLUDED.g < _astar.g;
  END LOOP;
  PERFORM set_config('routing.last_explored', v_explored::text, true);
  IF NOT v_found OR p_src = p_dst THEN RETURN; END IF;
  v_cur := p_dst;
  LOOP
    SELECT a.parent_edge INTO v_edge FROM _astar a WHERE a.node = v_cur;
    EXIT WHEN v_edge IS NULL;
    v_edges := v_edge || v_edges;
    SELECT e.u INTO v_cur FROM routing.edges e WHERE e.id = v_edge;
  END LOOP;
  RETURN QUERY
    SELECT t.ord::integer, e.id, e.u, e.v, e.length_m, e.time_s, e.road
      FROM unnest(v_edges) WITH ORDINALITY AS t(eid, ord) JOIN routing.edges e ON e.id = t.eid ORDER BY t.ord;
END $$;

-- The k nearest facilities of one kind by straight line, then ranked by real driving time (a route per candidate).
CREATE OR REPLACE FUNCTION routing.fn_dispatch_candidates(p_lat DOUBLE PRECISION, p_lon DOUBLE PRECISION, p_kind TEXT,
                                                          p_k INTEGER DEFAULT 3, p_closed INTEGER[] DEFAULT '{}')
RETURNS TABLE (facility_id TEXT, name TEXT, straight_line_m DOUBLE PRECISION, straight_rank INTEGER,
               drive_seconds DOUBLE PRECISION, drive_m DOUBLE PRECISION, drive_rank INTEGER)
LANGUAGE plpgsql AS $$
DECLARE v_dst INTEGER; v_src INTEGER; r RECORD; v_t DOUBLE PRECISION; v_d DOUBLE PRECISION;
BEGIN
  SELECT node_id INTO v_dst FROM routing.fn_nearest_nodes(p_lat, p_lon, 1);
  CREATE TEMP TABLE IF NOT EXISTS _candidates (facility_id TEXT, name TEXT, straight_line_m DOUBLE PRECISION,
                                               straight_rank INTEGER, drive_seconds DOUBLE PRECISION, drive_m DOUBLE PRECISION) ON COMMIT DROP;
  TRUNCATE _candidates;
  FOR r IN SELECT f.id, f.name, f.lat, f.lon, public.earth_distance(f.geo, public.ll_to_earth(p_lat, p_lon)) AS d,
                  row_number() OVER (ORDER BY f.geo OPERATOR(public.<->) public.ll_to_earth(p_lat, p_lon))::integer AS rk
             FROM routing.facilities f WHERE f.kind = p_kind
            ORDER BY f.geo OPERATOR(public.<->) public.ll_to_earth(p_lat, p_lon) LIMIT p_k LOOP
    SELECT node_id INTO v_src FROM routing.fn_nearest_nodes(r.lat, r.lon, 1);
    IF v_src = v_dst THEN
      v_t := 0; v_d := 0;                         -- the facility is already on the incident's road node
    ELSE
      SELECT sum(x.time_s), sum(x.length_m) INTO v_t, v_d FROM routing.fn_route(v_src, v_dst, p_closed) x;   -- NULL: unreachable
    END IF;
    INSERT INTO _candidates VALUES (r.id, r.name, r.d, r.rk, v_t, v_d);
  END LOOP;
  RETURN QUERY SELECT c.facility_id, c.name, c.straight_line_m, c.straight_rank, c.drive_seconds, c.drive_m,
                      (CASE WHEN c.drive_seconds IS NULL THEN NULL ELSE rank() OVER (ORDER BY c.drive_seconds) END)::integer
                 FROM _candidates c ORDER BY c.drive_seconds NULLS LAST, c.straight_rank;
END $$;

INSERT INTO public.schema_migrations (version, description)
VALUES ('009', 'Schema routing: road graph tables, KNN nearest node/facility, hazard closures, A* in PL/pgSQL')
ON CONFLICT (version) DO NOTHING;
