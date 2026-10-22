-- =====================================================================================
-- Migration 003: administrator maintenance of zones, units and relief items (FR-06, FR-09).
--
-- One rule that Review I states ("an official leads at most one unit", Table 9) and Review II left
-- to the application: the account that leads a unit must be a UNIT_LEAD account. It is enforced in
-- the database so every client is held to it. Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;

CREATE OR REPLACE FUNCTION response.trg_fn_unit_lead_type()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_type public.users.account_type%TYPE;
BEGIN
  IF NEW.lead_user_id IS NOT NULL THEN
    SELECT account_type INTO v_type FROM public.users WHERE id = NEW.lead_user_id;
    IF v_type IS DISTINCT FROM 'UNIT_LEAD' THEN
      RAISE EXCEPTION 'User % cannot lead a unit: account type is %, not UNIT_LEAD',
        NEW.lead_user_id, coalesce(v_type, 'missing');
    END IF;
  END IF;
  RETURN NEW;
END $$;
ALTER FUNCTION response.trg_fn_unit_lead_type() SET search_path = response, public;

CREATE OR REPLACE TRIGGER trg_units_lead_type
BEFORE INSERT OR UPDATE OF lead_user_id ON response.response_units
FOR EACH ROW EXECUTE FUNCTION response.trg_fn_unit_lead_type();

INSERT INTO public.schema_migrations (version, description)
VALUES ('003', 'Unit lead must be a UNIT_LEAD account (trg_units_lead_type)')
ON CONFLICT (version) DO NOTHING;
