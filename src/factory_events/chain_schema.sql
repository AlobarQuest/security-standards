-- The factory-events chain of record: its table, its append-only triggers and its two roles.
--
-- The database owner runs this once, as an announced act (orchestrator ADR-0055 amendment 24
-- items 2, 3 and 14; ADR-0059 amendment 7 act 2), through `python -m factory_events.db_setup`.
-- It never runs in an image build step, and neither the append path nor a verifier runs DDL.
-- It runs in one transaction and is safe to run again. It needs Postgres 14 or later.
--
-- It sets no password. The owner sets each role's password afterwards with psql's
-- `\password <role>`, which sends only a SCRAM verifier, so no password is in this file, in a
-- statement or in the server log.

-- Each row links to the one before it as a line of ~/.factory/events.jsonl does:
-- hash = sha256(canonical_json({"seq", "prev_hash", "event"})), store.line_hash's formula.
-- `event` holds the event's canonical JSON text (envelope.canonical_json), not jsonb: jsonb
-- normalizes numbers and refuses some strings, so a hash recomputed from it could differ.
CREATE TABLE IF NOT EXISTS public.factory_events (
    event_id  text   PRIMARY KEY,
    seq       bigint NOT NULL UNIQUE CHECK (seq >= 1),
    prev_hash text   NOT NULL UNIQUE CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash      text   NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
    event     text   NOT NULL
);

-- Append-only, whatever the role: refuse every UPDATE, DELETE and TRUNCATE.
CREATE OR REPLACE FUNCTION public.factory_events_refuse_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'factory_events is append-only: % refused', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE OR REPLACE TRIGGER factory_events_no_update_delete
    BEFORE UPDATE OR DELETE ON public.factory_events
    FOR EACH ROW EXECUTE FUNCTION public.factory_events_refuse_change();

CREATE OR REPLACE TRIGGER factory_events_no_truncate
    BEFORE TRUNCATE ON public.factory_events
    FOR EACH STATEMENT EXECUTE FUNCTION public.factory_events_refuse_change();

-- Linear, whatever the writer: a row must link to the row before it (seq 1 to the genesis
-- hash). With seq and prev_hash each unique, the chain can't fork or skip.
CREATE OR REPLACE FUNCTION public.factory_events_check_link() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.seq = 1 THEN
        IF NEW.prev_hash <> repeat('0', 64) THEN
            RAISE EXCEPTION 'factory_events: seq 1 must link to the genesis hash'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.factory_events WHERE seq = NEW.seq - 1 AND hash = NEW.prev_hash
    ) THEN
        RAISE EXCEPTION 'factory_events: seq % does not link to seq %', NEW.seq, NEW.seq - 1
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER factory_events_link
    BEFORE INSERT ON public.factory_events
    FOR EACH ROW EXECUTE FUNCTION public.factory_events_check_link();

-- The two roles (item 3). The owner is the role running this script.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'factory_events_append') THEN
        CREATE ROLE factory_events_append LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'factory_events_read') THEN
        CREATE ROLE factory_events_read LOGIN;
    END IF;
END
$$;

ALTER ROLE factory_events_append
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE factory_events_read
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE factory_events_read SET default_transaction_read_only = on;

-- No DDL for either role: Postgres before 15 grants CREATE on public to PUBLIC.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Append-only: SELECT and INSERT, nothing else. Read-only: SELECT, nothing else.
REVOKE ALL ON public.factory_events FROM PUBLIC, factory_events_append, factory_events_read;
GRANT SELECT, INSERT ON public.factory_events TO factory_events_append;
GRANT SELECT ON public.factory_events TO factory_events_read;
