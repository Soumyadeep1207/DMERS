-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 02_plpgsql.sql : functions, procedures (one with an explicit cursor) and triggers.
-- Created before the data load so that every seeded row passes through the same rules.
-- Session settings read by the triggers (set by the procedures or by the application):
--   dmers.actor_id  id of the official making the change (author of timeline entries)
--   dmers.note      optional text stored with the next timeline entry
-- =====================================================================================
SET client_min_messages = warning;

-- -------------------------------------------------------
-- [F1] fn_stock_status: derived stock_status (BR-10)
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_stock_status(
    p_resource_id INTEGER)
RETURNS VARCHAR LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_qty INTEGER;  v_reorder INTEGER;
BEGIN
  SELECT quantity_available, reorder_level
    INTO v_qty, v_reorder
    FROM resources WHERE id = p_resource_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Resource % does not exist',
                    p_resource_id;
  END IF;
  RETURN CASE WHEN v_qty = 0 THEN 'OUT_OF_STOCK'
              WHEN v_qty <= v_reorder THEN 'LOW'
              ELSE 'ADEQUATE' END;
END $$;

-- -------------------------------------------------------
-- [F2] fn_active_incidents: derived active_incidents
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_active_incidents(
    p_zone_id INTEGER)
RETURNS INTEGER LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_count INTEGER;
BEGIN
  SELECT count(*) INTO v_count FROM incidents
  WHERE zone_id = p_zone_id
    AND status IN ('VERIFIED', 'RESPONDING');
  RETURN v_count;
END $$;

-- -------------------------------------------------------
-- [F3] fn_response_minutes: report to first arrival
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_response_minutes(
    p_incident_id INTEGER)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_reported TIMESTAMPTZ;  v_arrival TIMESTAMPTZ;
BEGIN
  SELECT created_at INTO v_reported
    FROM incidents WHERE id = p_incident_id;
  SELECT min(arrived_at) INTO v_arrival
    FROM dispatches WHERE incident_id = p_incident_id;
  IF v_reported IS NULL OR v_arrival IS NULL THEN
    RETURN NULL;          -- unknown, or no unit on scene
  END IF;
  RETURN round(extract(epoch FROM v_arrival - v_reported)
               / 60, 1);
END $$;

-- -------------------------------------------------------
-- [P1] sp_dispatch_unit: dispatch a unit (FR-07)
-- -------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_dispatch_unit(
    p_incident_id INTEGER, p_unit_id INTEGER,
    p_coordinator_id INTEGER)
LANGUAGE plpgsql AS $$
DECLARE
  v_role   users.account_type%TYPE;
  v_status incidents.status%TYPE;
  v_unit   response_units.unit_name%TYPE;
BEGIN
  SELECT account_type INTO v_role
    FROM users WHERE id = p_coordinator_id;
  IF v_role IS DISTINCT FROM 'COORDINATOR' THEN
    RAISE EXCEPTION       -- only coordinators (FR-07)
      'User % is not authorised to dispatch units',
      p_coordinator_id;
  END IF;
  -- author recorded by the timeline trigger T1
  PERFORM set_config('dmers.actor_id',
                     p_coordinator_id::TEXT, true);

  -- trigger T3 checks BR-05 on this INSERT
  INSERT INTO dispatches (incident_id, unit_id,
                          dispatched_by)
  VALUES (p_incident_id, p_unit_id, p_coordinator_id);
  UPDATE response_units
     SET availability_status = 'DEPLOYED'
   WHERE id = p_unit_id RETURNING unit_name INTO v_unit;

  SELECT status INTO v_status
    FROM incidents WHERE id = p_incident_id;
  IF v_status = 'VERIFIED' THEN      -- first unit sent
    UPDATE incidents SET status = 'RESPONDING'
     WHERE id = p_incident_id;
  END IF;
  RAISE NOTICE 'Unit % (%) dispatched to incident % '
    'by user %', p_unit_id, v_unit, p_incident_id,
    p_coordinator_id;
END $$;

-- -------------------------------------------------------
-- [P2] sp_close_incident: cursor releases units (FR-11)
-- -------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_close_incident(
    p_incident_id INTEGER, p_coordinator_id INTEGER,
    p_note VARCHAR DEFAULT NULL)
LANGUAGE plpgsql AS $$
DECLARE
  c_open CURSOR FOR       -- active dispatches of incident
    SELECT unit_id, dispatch_status FROM dispatches
     WHERE incident_id = p_incident_id
       AND dispatch_status IN ('ASSIGNED', 'EN_ROUTE',
                               'ON_SCENE')
     ORDER BY unit_id
       FOR UPDATE;
  r_disp     RECORD;
  v_status   incidents.status%TYPE;
  v_released INTEGER := 0;
BEGIN
  SELECT status INTO v_status FROM incidents
   WHERE id = p_incident_id FOR UPDATE;
  IF v_status IS NULL OR v_status NOT IN
     ('VERIFIED', 'RESPONDING', 'RESOLVED') THEN
    RAISE EXCEPTION
      'Incident % cannot be closed from status %',
      p_incident_id, coalesce(v_status, 'missing');
  END IF;
  PERFORM set_config('dmers.actor_id',
                     p_coordinator_id::TEXT, true);

  OPEN c_open;
  LOOP
    FETCH c_open INTO r_disp;
    EXIT WHEN NOT FOUND;
    UPDATE dispatches
       SET dispatch_status =
             CASE WHEN r_disp.dispatch_status = 'ON_SCENE'
                  THEN 'COMPLETED' ELSE 'CANCELLED' END,
           cleared_at = now()
     WHERE CURRENT OF c_open;
    UPDATE response_units
       SET availability_status = 'AVAILABLE'
     WHERE id = r_disp.unit_id;
    v_released := v_released + 1;
    RAISE NOTICE 'Unit % released (dispatch was %)',
      r_disp.unit_id, r_disp.dispatch_status;
  END LOOP;
  CLOSE c_open;

  IF v_status <> 'RESOLVED' THEN
    UPDATE incidents SET status = 'RESOLVED'
     WHERE id = p_incident_id;
  END IF;
  -- the closing note is stored with the CLOSED entry
  PERFORM set_config('dmers.note',
                     coalesce(p_note, ''), true);
  UPDATE incidents SET status = 'CLOSED'
   WHERE id = p_incident_id;
  PERFORM set_config('dmers.note', '', true);
  RAISE NOTICE 'Incident % closed; % unit(s) released',
    p_incident_id, v_released;
END $$;

-- -------------------------------------------------------
-- [T1] timeline of status changes (FR-03, BR-08)
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_fn_incident_timeline()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_note  TEXT := nullif(current_setting('dmers.note',
                                         true), '');
  v_actor TEXT := nullif(current_setting('dmers.actor_id',
                                         true), '');
BEGIN
  IF TG_OP = 'INSERT' THEN          -- entry 1: the report
    INSERT INTO incident_updates (incident_id, update_no,
      new_status, note, logged_by, logged_at)
    VALUES (NEW.id, 1, NEW.status, 'Incident reported',
            NEW.reported_by, NEW.created_at);
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    INSERT INTO incident_updates (incident_id, update_no,
      previous_status, new_status, note, logged_by,
      logged_at)
    SELECT NEW.id, coalesce(max(update_no), 0) + 1,
      OLD.status, NEW.status,
      coalesce(v_note, 'Status set to ' || NEW.status),
      v_actor::INTEGER, NEW.updated_at
      FROM incident_updates WHERE incident_id = NEW.id;
  END IF;                   -- unchanged status: no entry
  RETURN NULL;             -- ignored in an AFTER trigger
END $$;

CREATE TRIGGER trg_incidents_timeline
AFTER INSERT OR UPDATE OF status ON incidents
FOR EACH ROW EXECUTE FUNCTION trg_fn_incident_timeline();

-- -------------------------------------------------------
-- [T2] maintains incidents.updated_at
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_fn_touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.updated_at = OLD.updated_at THEN  -- not supplied
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_incidents_touch
BEFORE UPDATE ON incidents
FOR EACH ROW EXECUTE FUNCTION trg_fn_touch_updated_at();

-- -------------------------------------------------------
-- [T3] dispatch guard (BR-05)
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_fn_dispatch_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_unit_state response_units.availability_status%TYPE;
  v_incident   incidents.status%TYPE;
BEGIN
  SELECT availability_status INTO v_unit_state
    FROM response_units WHERE id = NEW.unit_id
     FOR UPDATE;                     -- lock the unit row
  IF v_unit_state IS DISTINCT FROM 'AVAILABLE' THEN
    RAISE EXCEPTION 'Unit % is %, not AVAILABLE',
      NEW.unit_id, coalesce(v_unit_state, 'missing');
  END IF;
  SELECT status INTO v_incident
    FROM incidents WHERE id = NEW.incident_id;
  IF v_incident IS NULL
     OR v_incident NOT IN ('VERIFIED', 'RESPONDING') THEN
    RAISE EXCEPTION 'Incident % is %; only VERIFIED or '
      'RESPONDING incidents receive units',
      NEW.incident_id, coalesce(v_incident, 'missing');
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_dispatches_guard
BEFORE INSERT ON dispatches
FOR EACH ROW EXECUTE FUNCTION trg_fn_dispatch_guard();

-- -------------------------------------------------------
-- [T4] stock movement and timeline note (FR-10, BR-07)
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_fn_allocation_stock()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_delta INTEGER;  v_iid INTEGER;  v_rid INTEGER;
  v_left  INTEGER;  v_next INTEGER;
  v_item   resources.resource_name%TYPE;
  v_status incidents.status%TYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN    -- withdrawn: stock returns
    v_delta := -OLD.quantity;
    v_iid := OLD.incident_id;  v_rid := OLD.resource_id;
  ELSE                       -- new allocation or increase
    v_delta := NEW.quantity - CASE TG_OP
      WHEN 'UPDATE' THEN OLD.quantity ELSE 0 END;
    v_iid := NEW.incident_id;  v_rid := NEW.resource_id;
  END IF;
  IF v_delta = 0 THEN RETURN NULL; END IF;
  UPDATE resources
     SET quantity_available = quantity_available - v_delta
   WHERE id = v_rid AND quantity_available >= v_delta
  RETURNING quantity_available, resource_name
       INTO v_left, v_item;
  IF NOT FOUND THEN
    SELECT quantity_available INTO v_left
      FROM resources WHERE id = v_rid;
    RAISE EXCEPTION 'Insufficient stock for resource %: '
      'requested %, available %', v_rid, v_delta, v_left;
  END IF;
  -- lock the incident so timeline numbers stay unique
  SELECT status INTO v_status FROM incidents
   WHERE id = v_iid FOR UPDATE;
  SELECT coalesce(max(update_no), 0) + 1 INTO v_next
    FROM incident_updates WHERE incident_id = v_iid;
  INSERT INTO incident_updates (incident_id, update_no,
    previous_status, new_status, note, logged_by,
    logged_at)
  VALUES (v_iid, v_next, v_status, v_status,
    CASE WHEN v_delta > 0 THEN 'Allocated '
         ELSE 'Returned ' END
      || abs(v_delta) || ' ' || v_item,
    nullif(current_setting('dmers.actor_id', true),
           '')::INTEGER,
    CASE WHEN TG_OP = 'DELETE' THEN now()
         ELSE NEW.allocated_at END);
  RETURN NULL;
END $$;

CREATE TRIGGER trg_allocations_stock
AFTER INSERT OR UPDATE OF quantity OR DELETE
ON resource_allocations
FOR EACH ROW EXECUTE FUNCTION trg_fn_allocation_stock();

-- -------------------------------------------------------
-- [T5] append-only timeline (BR-08)
-- -------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_fn_timeline_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
    RETURN OLD;     -- cascade from DELETE on incidents
  END IF;
  RAISE EXCEPTION 'Timeline entries are append-only '
    '(incident %, update %)', OLD.incident_id,
    OLD.update_no;
END $$;

CREATE TRIGGER trg_incident_updates_append_only
BEFORE UPDATE OR DELETE ON incident_updates
FOR EACH ROW
EXECUTE FUNCTION trg_fn_timeline_append_only();
