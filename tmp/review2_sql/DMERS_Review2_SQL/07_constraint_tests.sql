-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 07_constraint_tests.sql : every statement below must be REJECTED by a constraint.
-- Run after 06. Nothing is changed: each failing statement is rolled back.
-- =====================================================================================
\set VERBOSITY terse
\set ON_ERROR_STOP off
SET TIME ZONE 'Asia/Kolkata';
SET client_min_messages = notice;   -- show NOTICE messages

-- @test K1 uq_users_email | Duplicate e-mail address
INSERT INTO users (full_name, email, password_hash)
VALUES ('Test User', 'anitha.selvam@mail.example.com', 'x');

-- @test K2 ck_users_account_type | Account type outside the domain
INSERT INTO users (full_name, account_type, email, password_hash)
VALUES ('Guest User', 'GUEST', 'guest.user@mail.example.com', 'x');

-- @test K3 ck_users_email_format | Malformed e-mail address
INSERT INTO users (full_name, email, password_hash) VALUES ('Test User', 'not-an-email', 'x');

-- @test K4 ck_incidents_severity | Severity outside the domain
UPDATE incidents SET severity = 'EXTREME' WHERE id = 12;

-- @test K5 ck_incidents_zone_when_verified | Verifying an incident without a zone
UPDATE incidents SET status = 'VERIFIED' WHERE id = 12;

-- @test K6 fk_incidents_reporter | Report from a user that does not exist
INSERT INTO incidents (title, incident_type, location, reported_by) VALUES ('Test', 'FIRE', 'Katpadi', 999);

-- @test K7 ck_units_personnel | Response unit with no personnel
INSERT INTO response_units (unit_name, unit_type, contact_phone, personnel_count, zone_id)
VALUES ('Test Unit', 'FIRE', '9000010199', 0, 1);

-- @test K8 ck_units_phone | Malformed contact number
INSERT INTO response_units (unit_name, unit_type, contact_phone, personnel_count, zone_id)
VALUES ('Test Unit', 'FIRE', '12345', 4, 1);

-- @test K9 ck_resources_quantity | Negative stock
UPDATE resources SET quantity_available = -5 WHERE id = 1;

-- @test K10 ck_allocations_quantity | Allocation of zero items
INSERT INTO resource_allocations (incident_id, resource_id, quantity) VALUES (13, 1, 0);

-- @test K11 ck_dispatches_arrival | Arrival recorded before the dispatch time
INSERT INTO dispatches (incident_id, unit_id, dispatched_by, arrived_at)
VALUES (10, 5, 3, now() - interval '1 hour');

-- @test K12 uq_dispatches_one_active_per_unit | Second active dispatch for one unit (direct inserts)
BEGIN;
INSERT INTO dispatches (incident_id, unit_id, dispatched_by) VALUES (10, 7, 3);
INSERT INTO dispatches (incident_id, unit_id, dispatched_by) VALUES (15, 7, 3);
ROLLBACK;

-- @test K13 fk_incidents_reporter | Deleting a user who reported incidents (RESTRICT)
DELETE FROM users WHERE id = 10;

-- @test K14 fk_dispatches_incident | Deleting an incident with dispatch history (BR-09)
DELETE FROM incidents WHERE id = 3;
