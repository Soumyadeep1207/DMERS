-- =====================================================================================
-- Migration 006: row-level security, so that "who may see or change which rows" is a property
-- of the database and not only of the Flask code.
--
-- A NOLOGIN role, dmers_rls, is subject to policies that read the acting user from the same
-- session variable the audit triggers use (dmers.actor_id). The application's own connection role
-- owns the tables and is not subject to them (RLS is ENABLEd, not FORCEd), so every existing
-- transaction behaves exactly as before. A connection that runs "SET LOCAL ROLE dmers_rls" gets the
-- policies, plus column-level privileges that hide users.password.
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dmers_rls') THEN
    CREATE ROLE dmers_rls NOLOGIN NOINHERIT;
  END IF;
  IF NOT pg_has_role(current_user, 'dmers_rls', 'MEMBER') THEN
    EXECUTE format('GRANT dmers_rls TO %I', current_user);   -- so the owner may SET ROLE
  END IF;
END $$;

CREATE OR REPLACE FUNCTION response.fn_actor_id() RETURNS INTEGER
LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('dmers.actor_id', true), '')::integer $$;

-- SECURITY DEFINER: the restricted role may learn the account type of the acting user, nothing else about users.
CREATE OR REPLACE FUNCTION response.fn_actor_type() RETURNS TEXT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = response, public AS
$$ SELECT account_type FROM public.users WHERE id = response.fn_actor_id() $$;

GRANT USAGE ON SCHEMA response, public TO dmers_rls;
GRANT EXECUTE ON FUNCTION response.fn_actor_id(), response.fn_actor_type() TO dmers_rls;
GRANT SELECT ON response.zones, response.incidents, response.response_units, response.resources,
                response.incident_updates, response.dispatches, response.resource_allocations TO dmers_rls;
GRANT INSERT, UPDATE ON response.incidents TO dmers_rls;
GRANT UPDATE ON response.dispatches TO dmers_rls;
GRANT SELECT (id, name, role, account_type) ON public.users TO dmers_rls;   -- never the password hash

ALTER TABLE response.incidents            ENABLE ROW LEVEL SECURITY;
ALTER TABLE response.incident_updates     ENABLE ROW LEVEL SECURITY;
ALTER TABLE response.dispatches           ENABLE ROW LEVEL SECURITY;
ALTER TABLE response.resource_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE response.response_units       ENABLE ROW LEVEL SECURITY;
ALTER TABLE response.zones                ENABLE ROW LEVEL SECURITY;
ALTER TABLE response.resources            ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_incidents_select ON response.incidents;
CREATE POLICY rls_incidents_select ON response.incidents FOR SELECT TO dmers_rls
  USING (response.fn_actor_type() IS NOT NULL
         AND (response.fn_actor_type() <> 'CITIZEN' OR reported_by = response.fn_actor_id()));

DROP POLICY IF EXISTS rls_incidents_insert ON response.incidents;
CREATE POLICY rls_incidents_insert ON response.incidents FOR INSERT TO dmers_rls
  WITH CHECK (reported_by = response.fn_actor_id() AND status = 'REPORTED');

DROP POLICY IF EXISTS rls_incidents_update ON response.incidents;
CREATE POLICY rls_incidents_update ON response.incidents FOR UPDATE TO dmers_rls
  USING (response.fn_actor_type() IN ('COORDINATOR', 'ADMINISTRATOR'))
  WITH CHECK (response.fn_actor_type() IN ('COORDINATOR', 'ADMINISTRATOR'));

DROP POLICY IF EXISTS rls_timeline_select ON response.incident_updates;
CREATE POLICY rls_timeline_select ON response.incident_updates FOR SELECT TO dmers_rls
  USING (EXISTS (SELECT 1 FROM response.incidents i WHERE i.id = incident_id));   -- inherits the incident's visibility

DROP POLICY IF EXISTS rls_dispatches_select ON response.dispatches;
CREATE POLICY rls_dispatches_select ON response.dispatches FOR SELECT TO dmers_rls
  USING (response.fn_actor_type() IN ('COORDINATOR', 'UNIT_LEAD', 'ADMINISTRATOR'));

DROP POLICY IF EXISTS rls_dispatches_update ON response.dispatches;
CREATE POLICY rls_dispatches_update ON response.dispatches FOR UPDATE TO dmers_rls
  USING (EXISTS (SELECT 1 FROM response.response_units u WHERE u.id = unit_id AND u.lead_user_id = response.fn_actor_id()));

DROP POLICY IF EXISTS rls_allocations_select ON response.resource_allocations;
CREATE POLICY rls_allocations_select ON response.resource_allocations FOR SELECT TO dmers_rls
  USING (response.fn_actor_type() IN ('COORDINATOR', 'ADMINISTRATOR'));

DROP POLICY IF EXISTS rls_units_select ON response.response_units;
CREATE POLICY rls_units_select ON response.response_units FOR SELECT TO dmers_rls USING (response.fn_actor_type() IS NOT NULL);
DROP POLICY IF EXISTS rls_zones_select ON response.zones;
CREATE POLICY rls_zones_select ON response.zones FOR SELECT TO dmers_rls USING (response.fn_actor_type() IS NOT NULL);
DROP POLICY IF EXISTS rls_resources_select ON response.resources;
CREATE POLICY rls_resources_select ON response.resources FOR SELECT TO dmers_rls USING (response.fn_actor_type() IS NOT NULL);

INSERT INTO public.schema_migrations (version, description)
VALUES ('006', 'Row-level security: dmers_rls role, policies on dmers.actor_id, column grants on users')
ON CONFLICT (version) DO NOTHING;
