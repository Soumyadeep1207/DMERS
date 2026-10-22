-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 04_dml_demo.sql : INSERT, UPDATE and DELETE on the loaded data (run after 03).
-- =====================================================================================
\set VERBOSITY terse
\pset footer off
SET TIME ZONE 'Asia/Kolkata';
SET client_min_messages = notice;   -- show NOTICE messages

-- @block D1 Rows per relation after the data load
SELECT 'users' AS relation, count(*) AS row_count FROM users
UNION ALL SELECT 'zones', count(*) FROM zones
UNION ALL SELECT 'incidents', count(*) FROM incidents
UNION ALL SELECT 'response_units', count(*) FROM response_units
UNION ALL SELECT 'resources', count(*) FROM resources
UNION ALL SELECT 'incident_updates', count(*) FROM incident_updates
UNION ALL SELECT 'dispatches', count(*) FROM dispatches
UNION ALL SELECT 'resource_allocations', count(*) FROM resource_allocations;

-- @block D2 INSERT: a citizen reports an incident (FR-03); defaults and the timeline trigger apply
INSERT INTO incidents (title, description, incident_type, location, reported_by)
VALUES ('Waterlogging under Katpadi railway underpass', 'Two-wheelers stalled in water',
        'FLOOD', 'Railway underpass, Katpadi', 16)
RETURNING id, status, severity, zone_id, to_char(created_at, 'DD-Mon HH24:MI') AS reported;
SELECT update_no, previous_status, new_status, note, logged_by
FROM incident_updates WHERE incident_id = 15;

-- @block D3 UPDATE: a coordinator verifies the report (FR-05) and a unit lead records arrival (FR-08)
SET dmers.actor_id = '3';           -- coordinator acting
UPDATE incidents
SET status = 'VERIFIED', severity = 'HIGH', zone_id = 2
WHERE id = 15
RETURNING id, status, severity, zone_id,
          to_char(updated_at, 'DD-Mon HH24:MI') AS updated;
UPDATE dispatches
SET dispatch_status = 'ON_SCENE', arrived_at = now()
WHERE incident_id = 7 AND unit_id = 11
RETURNING incident_id, unit_id, dispatch_status;

-- @block D4 UPDATE: the administrator restocks tarpaulin sheets (FR-09)
UPDATE resources
SET quantity_available = quantity_available + 100
WHERE resource_name = 'Tarpaulin sheets';
SELECT resource_name, quantity_available,
       fn_stock_status(id) AS stock_status
FROM resources WHERE resource_name = 'Tarpaulin sheets';

-- @block D5 DELETE: the rejected duplicate report is removed; its timeline rows cascade
SELECT count(*) AS timeline_rows FROM incident_updates WHERE incident_id = 8;
DELETE FROM incidents WHERE id = 8 AND status = 'REJECTED';
SELECT count(*) AS timeline_rows FROM incident_updates WHERE incident_id = 8;
