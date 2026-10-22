-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 06_plpgsql_demo.sql : executes the functions, procedures, cursor and triggers (run after 05)
-- =====================================================================================
\set VERBOSITY terse
\pset footer off
SET TIME ZONE 'Asia/Kolkata';
SET client_min_messages = notice;   -- show the procedures' NOTICE lines

-- @block P1 Functions called directly
SELECT fn_stock_status(11) AS boats, fn_stock_status(12) AS generators,
       fn_active_incidents(1) AS active_in_vellore_town, fn_response_minutes(7) AS palar_response_min;

-- @block P2 sp_dispatch_unit: Katpadi Fire Unit (2) to incident 9 by coordinator 3
CALL sp_dispatch_unit(9, 2, 3);
SELECT d.dispatch_status,
       r.availability_status AS unit_now,
       i.status AS incident_now
FROM dispatches d
JOIN response_units r ON r.id = d.unit_id
JOIN incidents i ON i.id = d.incident_id
WHERE d.incident_id = 9 AND d.unit_id = 2;

-- @block P3 sp_dispatch_unit rejects calls that break BR-05 or come from a citizen
CALL sp_dispatch_unit(10, 9, 3);     -- SDRF Team Alpha is still deployed at incident 7
CALL sp_dispatch_unit(12, 5, 3);     -- incident 12 has not been verified
CALL sp_dispatch_unit(10, 5, 10);    -- user 10 is a citizen

-- @block C1 sp_close_incident: the cursor releases every unit still at incident 14
CALL sp_close_incident(14, 3, 'Debris cleared; structure declared safe');
SELECT d.unit_id, r.unit_name, d.dispatch_status, r.availability_status
FROM dispatches d JOIN response_units r ON r.id = d.unit_id
WHERE d.incident_id = 14 ORDER BY d.unit_id;
SELECT update_no, previous_status, new_status, note, logged_by
FROM incident_updates WHERE incident_id = 14 AND update_no >= 7 ORDER BY update_no;

-- @block T1 Stock trigger: an allocation that adds to an existing one, then one larger than the stock
SET dmers.actor_id = '2';
SELECT quantity_available AS cans_in_stock FROM resources WHERE id = 3;
INSERT INTO resource_allocations AS ra (incident_id, resource_id, quantity) VALUES (7, 3, 40)
ON CONFLICT (incident_id, resource_id)
DO UPDATE SET quantity = ra.quantity + EXCLUDED.quantity, allocated_at = now();
SELECT ra.quantity AS allocated_to_7, r.quantity_available AS cans_in_stock, t.note
FROM resource_allocations ra JOIN resources r ON r.id = ra.resource_id
JOIN incident_updates t ON t.incident_id = ra.incident_id
WHERE ra.incident_id = 7 AND ra.resource_id = 3 ORDER BY t.update_no DESC LIMIT 1;
INSERT INTO resource_allocations (incident_id, resource_id, quantity) VALUES (10, 12, 5);

-- @block T2 Append-only trigger: timeline rows cannot be edited or deleted directly
UPDATE incident_updates SET note = 'edited'
WHERE incident_id = 3 AND update_no = 1;
DELETE FROM incident_updates WHERE incident_id = 3;
