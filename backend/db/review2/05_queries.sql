-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 05_queries.sql : fifteen application queries (run after 04)
-- =====================================================================================
\set VERBOSITY terse
\pset footer off
SET TIME ZONE 'Asia/Kolkata';
SET client_min_messages = notice;   -- show NOTICE messages

-- @block Q1 Active incidents, most severe first | FR-04 | selection, CASE in ORDER BY
SELECT id, title, severity, status FROM incidents WHERE status IN ('VERIFIED', 'RESPONDING')
ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MODERATE' THEN 3 ELSE 4 END, created_at;

-- @block Q2 Reports since 11 October with reporter and zone | FR-04 | inner join, left outer join
SELECT i.id, u.full_name AS reporter,
       coalesce(z.zone_name, '(unassigned)') AS zone, i.status
FROM incidents i
JOIN users u ON u.id = i.reported_by
LEFT JOIN zones z ON z.id = i.zone_id
WHERE i.created_at >= DATE '2026-10-11'
ORDER BY i.id;

-- @block Q3 Zones with two or more incidents | FR-13 | GROUP BY, HAVING, aggregate FILTER
SELECT z.zone_name, count(*) AS incidents,
       count(*) FILTER (WHERE i.status IN ('VERIFIED', 'RESPONDING'))
         AS active
FROM incidents i JOIN zones z ON z.id = i.zone_id
GROUP BY z.zone_name HAVING count(*) >= 2
ORDER BY incidents DESC, z.zone_name;

-- @block Q4 Units with no dispatch since 6 October | FR-13 | outer join with IS NULL (anti-join)
SELECT r.unit_name, r.unit_type, r.availability_status
FROM response_units r
LEFT JOIN dispatches d
       ON d.unit_id = r.id
      AND d.dispatched_at >= DATE '2026-10-06'
WHERE d.unit_id IS NULL
ORDER BY r.unit_name;

-- @block Q5 Relief items at or below the reorder level | FR-13 | function in WHERE and SELECT
SELECT resource_name, quantity_available AS available, reorder_level, fn_stock_status(id) AS stock_status
FROM resources WHERE fn_stock_status(id) <> 'ADEQUATE' ORDER BY quantity_available;

-- @block Q6 Units larger than the average of their type | FR-06 | correlated subquery
SELECT r.unit_name, r.unit_type, r.personnel_count
FROM response_units r
WHERE r.personnel_count >
      (SELECT avg(x.personnel_count)
       FROM response_units x
       WHERE x.unit_type = r.unit_type)
ORDER BY r.unit_type, r.unit_name;

-- @block Q7 Coordinators who sent units to CRITICAL incidents | FR-13 | nested IN subqueries
SELECT u.full_name, u.email
FROM users u
WHERE u.id IN
      (SELECT d.dispatched_by FROM dispatches d
       WHERE d.incident_id IN
             (SELECT id FROM incidents
              WHERE severity = 'CRITICAL'))
ORDER BY u.full_name;

-- @block Q8 Verified incidents still waiting for a unit | FR-07 | NOT EXISTS
SELECT i.id, i.title, i.severity, z.zone_name FROM incidents i JOIN zones z ON z.id = i.zone_id
WHERE i.status = 'VERIFIED' AND NOT EXISTS (SELECT 1 FROM dispatches d WHERE d.incident_id = i.id)
ORDER BY i.id;

-- @block Q9 Unit utilisation | FR-13 | join, GROUP BY, aggregate FILTER, interval arithmetic, LIMIT
SELECT r.unit_name, count(*) AS dispatches,
       count(*) FILTER (WHERE d.dispatch_status = 'COMPLETED') AS completed,
       round(sum(extract(epoch FROM d.cleared_at - d.arrived_at) / 3600)
             FILTER (WHERE d.dispatch_status = 'COMPLETED'), 2) AS hours_on_scene
FROM dispatches d JOIN response_units r ON r.id = d.unit_id
GROUP BY r.unit_name ORDER BY dispatches DESC, hours_on_scene DESC NULLS LAST LIMIT 5;

-- @block Q10 Average response time per zone | FR-13 | AVG over a stored function
SELECT z.zone_name, count(*) AS incidents_reached,
       round(avg(fn_response_minutes(i.id)), 1) AS avg_minutes
FROM incidents i JOIN zones z ON z.id = i.zone_id
WHERE fn_response_minutes(i.id) IS NOT NULL
GROUP BY z.zone_name
ORDER BY avg_minutes;

-- @block Q11 Timeline of incident 3 | FR-12 | left outer join, string expressions, to_char
SELECT t.update_no AS no, to_char(t.logged_at, 'DD-Mon HH24:MI') AS logged_at,
       coalesce(t.previous_status, '-') || ' > ' || t.new_status AS change, u.full_name AS logged_by, t.note
FROM incident_updates t LEFT JOIN users u ON u.id = t.logged_by
WHERE t.incident_id = 3 ORDER BY t.update_no;

-- @block Q12 Everyone accountable for incident 7 | FR-12 | UNION of three joins
SELECT u.full_name, 'reporter' AS role
FROM incidents i JOIN users u ON u.id = i.reported_by
WHERE i.id = 7
UNION
SELECT u.full_name, 'dispatching coordinator'
FROM dispatches d JOIN users u ON u.id = d.dispatched_by
WHERE d.incident_id = 7
UNION
SELECT u.full_name, 'lead of a dispatched unit'
FROM dispatches d
JOIN response_units r ON r.id = d.unit_id
JOIN users u ON u.id = r.lead_user_id
WHERE d.incident_id = 7
ORDER BY role, full_name;

-- @block Q13 Busiest unit of each type | FR-13 | derived table, window function ROW_NUMBER
SELECT unit_type, unit_name, dispatches
FROM (SELECT r.unit_type, r.unit_name,
             count(d.unit_id) AS dispatches,
             row_number() OVER (PARTITION BY r.unit_type
               ORDER BY count(d.unit_id) DESC, r.unit_name) AS rn
      FROM response_units r
      LEFT JOIN dispatches d ON d.unit_id = r.id
      GROUP BY r.unit_type, r.unit_name) ranked
WHERE rn = 1
ORDER BY unit_type;

-- @block Q14 Command board for open incidents | FR-13 | two CTEs, left outer joins
WITH units AS (SELECT incident_id,
                      count(*) FILTER (WHERE dispatch_status = 'ON_SCENE') AS on_scene,
                      count(*) FILTER (WHERE dispatch_status IN ('ASSIGNED', 'EN_ROUTE')) AS on_the_way
               FROM dispatches GROUP BY incident_id),
     relief AS (SELECT incident_id, count(*) AS relief_items FROM resource_allocations GROUP BY incident_id)
SELECT i.id, i.severity, coalesce(u.on_scene, 0) AS on_scene, coalesce(u.on_the_way, 0) AS on_the_way,
       coalesce(r.relief_items, 0) AS relief_items
FROM incidents i LEFT JOIN units u ON u.incident_id = i.id LEFT JOIN relief r ON r.incident_id = i.id
WHERE i.status IN ('VERIFIED', 'RESPONDING') ORDER BY i.id;

-- @block Q15 Zone situation view | FR-13 | VIEW, scalar subquery, stored function
CREATE OR REPLACE VIEW v_zone_situation AS
SELECT z.zone_name, z.risk_level,
       fn_active_incidents(z.id) AS active_incidents,
       (SELECT count(*) FROM response_units r
        WHERE r.zone_id = z.id
          AND r.availability_status = 'AVAILABLE')
         AS units_available
FROM zones z;
SELECT * FROM v_zone_situation
WHERE active_incidents > 0 OR risk_level = 'HIGH'
ORDER BY active_incidents DESC, zone_name;
