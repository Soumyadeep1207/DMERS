-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 00_reset.sql : removes every Review II object so the scripts can be run again.
-- Run only in the course database (dmers_course); the guard below refuses the
-- application database used by the Flask backend.
-- =====================================================================================
DO $$
BEGIN
    IF current_database() = 'dmers' THEN
        RAISE EXCEPTION 'Refusing to reset the application database "dmers"; use dmers_course';
    END IF;
END $$;

SET client_min_messages = warning;

DROP VIEW  IF EXISTS v_zone_situation;
DROP TABLE IF EXISTS resource_allocations, dispatches, incident_updates,
                     resources, response_units, incidents, zones, users CASCADE;

DROP PROCEDURE IF EXISTS sp_dispatch_unit(INTEGER, INTEGER, INTEGER);
DROP PROCEDURE IF EXISTS sp_close_incident(INTEGER, INTEGER, VARCHAR);
DROP FUNCTION  IF EXISTS fn_stock_status(INTEGER);
DROP FUNCTION  IF EXISTS fn_active_incidents(INTEGER);
DROP FUNCTION  IF EXISTS fn_response_minutes(INTEGER);
DROP FUNCTION  IF EXISTS trg_fn_incident_timeline();
DROP FUNCTION  IF EXISTS trg_fn_touch_updated_at();
DROP FUNCTION  IF EXISTS trg_fn_dispatch_guard();
DROP FUNCTION  IF EXISTS trg_fn_allocation_stock();
DROP FUNCTION  IF EXISTS trg_fn_timeline_append_only();
