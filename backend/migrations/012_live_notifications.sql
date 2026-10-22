-- =====================================================================================
-- Migration 012: live push with LISTEN / NOTIFY.
--
-- Changes to incidents and dispatches publish a small JSON message (ids and status only, no personal
-- data) on the channel dmers_events. PostgreSQL delivers a NOTIFY only when the transaction COMMITS and
-- drops it when the transaction rolls back, so subscribers never hear about changes that did not happen.
-- The API turns the channel into a server-sent-event stream (GET /api/response/stream).
-- Idempotent; also valid under psql (initdb.d).
-- =====================================================================================
SET client_min_messages = warning;

CREATE OR REPLACE FUNCTION response.trg_fn_notify_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'incidents' THEN
    PERFORM pg_notify('dmers_events', json_build_object('table', 'incidents', 'op', TG_OP, 'incident_id', NEW.id,
                      'status', NEW.status, 'severity', NEW.severity)::text);
  ELSE
    PERFORM pg_notify('dmers_events', json_build_object('table', 'dispatches', 'op', TG_OP, 'incident_id', NEW.incident_id,
                      'unit_id', NEW.unit_id, 'status', NEW.dispatch_status)::text);
  END IF;
  RETURN NULL;
END $$;
ALTER FUNCTION response.trg_fn_notify_change() SET search_path = response, public;

CREATE OR REPLACE TRIGGER trg_incidents_notify
AFTER INSERT OR UPDATE ON response.incidents
FOR EACH ROW EXECUTE FUNCTION response.trg_fn_notify_change();

CREATE OR REPLACE TRIGGER trg_dispatches_notify
AFTER INSERT OR UPDATE ON response.dispatches
FOR EACH ROW EXECUTE FUNCTION response.trg_fn_notify_change();

INSERT INTO public.schema_migrations (version, description)
VALUES ('012', 'LISTEN/NOTIFY: incident and dispatch changes published on dmers_events at commit')
ON CONFLICT (version) DO NOTHING;
