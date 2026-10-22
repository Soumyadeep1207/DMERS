-- =====================================================================================
-- Migration 005: tamper-evident incident timeline (hash chain).
--
-- trg_incident_updates_append_only (T5) already refuses UPDATE and DELETE through SQL, but a
-- superuser can switch triggers off (session_replication_role = replica) and edit history. Each
-- timeline entry therefore also carries SHA-256( previous entry's hash || this entry's content ).
-- Changing, removing or inserting an entry afterwards breaks every later link, and
-- fn_verify_timeline() finds the first bad entry. fn_anchor_timelines() records the current head
-- of every chain so that truncating the end of a chain is detected too.
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE response.incident_updates
  ADD COLUMN IF NOT EXISTS prev_hash BYTEA,
  ADD COLUMN IF NOT EXISTS row_hash  BYTEA;

CREATE OR REPLACE FUNCTION response.fn_timeline_hash(
  p_prev BYTEA, p_incident INTEGER, p_no INTEGER, p_prev_status TEXT, p_new_status TEXT,
  p_note TEXT, p_by INTEGER, p_at TIMESTAMPTZ)
RETURNS BYTEA LANGUAGE sql STABLE AS $$
  SELECT public.digest(
    coalesce(p_prev, ''::bytea) ||
    convert_to(concat_ws('|', p_incident, p_no, coalesce(p_prev_status, ''), p_new_status,
                         coalesce(p_note, ''), coalesce(p_by::text, ''),
                         to_char(p_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')), 'UTF8'),
    'sha256')
$$;

CREATE OR REPLACE FUNCTION response.trg_fn_timeline_chain()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  -- the writer already holds the incident row lock (the timeline row comes from trg_incidents_timeline)
  SELECT row_hash INTO NEW.prev_hash
    FROM response.incident_updates
   WHERE incident_id = NEW.incident_id AND update_no = NEW.update_no - 1;
  NEW.row_hash := response.fn_timeline_hash(NEW.prev_hash, NEW.incident_id, NEW.update_no,
                    NEW.previous_status, NEW.new_status, NEW.note, NEW.logged_by, NEW.logged_at);
  RETURN NEW;
END $$;
ALTER FUNCTION response.trg_fn_timeline_chain() SET search_path = response, public;

CREATE OR REPLACE TRIGGER trg_incident_updates_chain
BEFORE INSERT ON response.incident_updates
FOR EACH ROW EXECUTE FUNCTION response.trg_fn_timeline_chain();

-- Seal the entries that existed before this migration (the append-only trigger is paused for the backfill only).
DO $$
DECLARE r RECORD; v_prev BYTEA; v_incident INTEGER := NULL; v_hash BYTEA;
BEGIN
  IF EXISTS (SELECT 1 FROM response.incident_updates WHERE row_hash IS NULL) THEN
    ALTER TABLE response.incident_updates DISABLE TRIGGER trg_incident_updates_append_only;
    FOR r IN SELECT * FROM response.incident_updates ORDER BY incident_id, update_no LOOP
      IF r.incident_id IS DISTINCT FROM v_incident THEN v_prev := NULL; v_incident := r.incident_id; END IF;
      v_hash := response.fn_timeline_hash(v_prev, r.incident_id, r.update_no, r.previous_status, r.new_status,
                                          r.note, r.logged_by, r.logged_at);
      UPDATE response.incident_updates SET prev_hash = v_prev, row_hash = v_hash
       WHERE incident_id = r.incident_id AND update_no = r.update_no;
      v_prev := v_hash;
    END LOOP;
    ALTER TABLE response.incident_updates ENABLE TRIGGER trg_incident_updates_append_only;
  END IF;
END $$;
ALTER TABLE response.incident_updates ALTER COLUMN row_hash SET NOT NULL;

-- Heads recorded at a point in time (publish them elsewhere to make truncation detectable).
CREATE TABLE IF NOT EXISTS response.timeline_anchors (
  incident_id INTEGER NOT NULL CONSTRAINT fk_anchors_incident REFERENCES response.incidents (id) ON DELETE CASCADE,
  update_no   INTEGER NOT NULL,
  row_hash    BYTEA   NOT NULL,
  anchored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_timeline_anchors PRIMARY KEY (incident_id, update_no)
);

CREATE OR REPLACE FUNCTION response.fn_anchor_timelines()
RETURNS INTEGER LANGUAGE sql AS $$
  WITH heads AS (
    SELECT DISTINCT ON (incident_id) incident_id, update_no, row_hash
      FROM response.incident_updates ORDER BY incident_id, update_no DESC),
  ins AS (
    INSERT INTO response.timeline_anchors (incident_id, update_no, row_hash)
    SELECT incident_id, update_no, row_hash FROM heads
    ON CONFLICT DO NOTHING RETURNING 1)
  SELECT count(*)::int FROM ins
$$;

-- One row per incident: is its chain intact, and if not, where does it first break and why.
CREATE OR REPLACE FUNCTION response.fn_verify_timeline(p_incident INTEGER DEFAULT NULL)
RETURNS TABLE (incident_id INTEGER, entries INTEGER, intact BOOLEAN, first_bad_update_no INTEGER,
               problem TEXT, head_hash TEXT)
LANGUAGE sql STABLE AS $$
  WITH ordered AS (
    SELECT u.*, lag(u.row_hash) OVER w AS lag_hash, row_number() OVER w AS rn
      FROM response.incident_updates u
     WHERE p_incident IS NULL OR u.incident_id = p_incident
    WINDOW w AS (PARTITION BY u.incident_id ORDER BY u.update_no)),
  checked AS (
    SELECT o.*, CASE
        WHEN o.update_no <> o.rn THEN 'numbering gap: an entry was removed or inserted'
        WHEN o.prev_hash IS DISTINCT FROM o.lag_hash THEN 'link to the previous entry is broken'
        WHEN o.row_hash <> response.fn_timeline_hash(o.prev_hash, o.incident_id, o.update_no, o.previous_status,
                             o.new_status, o.note, o.logged_by, o.logged_at) THEN 'entry content was changed'
      END AS why
      FROM ordered o),
  anchored AS (
    SELECT a.incident_id, a.update_no,
           'anchored entry ' || a.update_no || ' is missing or was changed since it was anchored' AS why
      FROM response.timeline_anchors a
     WHERE (p_incident IS NULL OR a.incident_id = p_incident)
       AND NOT EXISTS (SELECT 1 FROM response.incident_updates u
                        WHERE u.incident_id = a.incident_id AND u.update_no = a.update_no AND u.row_hash = a.row_hash)),
  per_incident AS (
    SELECT c.incident_id, count(*)::int AS entries,
           min(c.update_no) FILTER (WHERE c.why IS NOT NULL) AS bad_no,
           (array_agg(c.why ORDER BY c.update_no) FILTER (WHERE c.why IS NOT NULL))[1] AS why,
           encode((array_agg(c.row_hash ORDER BY c.update_no DESC))[1], 'hex') AS head
      FROM checked c GROUP BY c.incident_id)
  SELECT p.incident_id, p.entries, (p.bad_no IS NULL AND x.why IS NULL), coalesce(p.bad_no, x.update_no),
         coalesce(p.why, x.why), p.head
    FROM per_incident p
    LEFT JOIN LATERAL (SELECT an.update_no, an.why FROM anchored an WHERE an.incident_id = p.incident_id
                        ORDER BY an.update_no LIMIT 1) x ON true
   ORDER BY p.incident_id
$$;

INSERT INTO public.schema_migrations (version, description)
VALUES ('005', 'Tamper-evident timeline: SHA-256 hash chain, anchors and fn_verify_timeline')
ON CONFLICT (version) DO NOTHING;
