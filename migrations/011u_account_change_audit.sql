-- 011u_account_change_audit.sql
--
-- A12 (account-security audit 2026-10-20, §7/§8): a database writer can change an account's role
-- or state, or a project membership, directly in SQL, and no account event records it. This
-- migration makes such a change TAMPER-EVIDENT for every writer the triggers bind. It does NOT
-- make it impossible, and it does NOT bind a superuser or the tables' owner. A12 stays OPEN as an
-- Owner decision (docs/audit/g0-owner-boundary-closure-2026-10-28/a12-boundary.md).
--
-- WHAT IS RECORDED, FOR EVERY WRITER, IN `account_change_audit`:
--   accounts             INSERT; UPDATE of system_role, status, email verification, approval or
--                        password hash (recorded as `password_replaced`, never the hash);
--                        DELETE (refused by 012u while its trigger stands); TRUNCATE.
--   project_memberships  INSERT; UPDATE of role, clearance, approval scopes, active or grantor;
--                        DELETE; TRUNCATE.
--   account_events       INSERT (the application's own record), and TRUNCATE -- so a change can
--                        be matched to the event its own transaction wrote.
-- Each row holds the old and new values, the login role (`session_user`), the role set with SET
-- ROLE (`role_setting`), `application_name`, the transaction id and the database clock. A change
-- with no account event in the same transaction for the same account is listed by
-- `lab-brain admin account-audit` (`lab_brain.accounts.change_audit`).
--
-- WHY THE APPLICATION ROLE CANNOT ERASE IT.
--   - The recording trigger functions are SECURITY DEFINER, owned by the migrator; the audit row
--     is inserted as the migrator. A direct INSERT by any other role is refused (a forged row);
--     UPDATE, DELETE and TRUNCATE of the audit table are refused for everyone the triggers bind.
--   - Every trigger here is ENABLE ALWAYS: `session_replication_role = replica` does not skip it.
--     (Only a superuser may set that parameter in the first place.)
--   - Each row is chained: `row_digest` = SHA-256 over the previous row's digest and this row's
--     fields, serialized through the one-row `account_change_audit_head`. A head the operator
--     copied OUT of the database earlier exposes any later rewrite of the rows before it.
--
-- WHAT IT DOES NOT STOP -- PLAINLY.
--   - A superuser, or the owner of these tables (the migrator), can `ALTER TABLE ... DISABLE
--     TRIGGER`, drop the triggers, TRUNCATE or rewrite the audit table and recompute the chain.
--     Only a head recorded outside the database, before the rewrite, reveals that.
--   - The application role may write an account event for its own direct change in the same
--     transaction; the audit row then reads "explained", and still shows the role, the old and
--     new values and who wrote it. An event is an application's claim, not a proof.
--   - It detects; it prevents nothing. The change itself still happens.

CREATE TABLE IF NOT EXISTS account_change_audit (
    audit_seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name       TEXT NOT NULL
        CHECK (table_name IN ('accounts', 'project_memberships', 'account_events')),
    operation        TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')),
    account_id       TEXT,
    actor_id         TEXT,
    project_id       TEXT,
    old_values       JSONB,
    new_values       JSONB,
    db_session_user  TEXT NOT NULL,
    role_setting     TEXT NOT NULL,
    application_name TEXT NOT NULL,
    txid             BIGINT NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL,
    previous_seq     BIGINT UNIQUE,
    previous_digest  TEXT NOT NULL CHECK (previous_digest ~ '^[0-9a-f]{64}$'),
    row_digest       TEXT NOT NULL UNIQUE CHECK (row_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS account_change_audit_txid_idx
    ON account_change_audit (txid, table_name, account_id);

COMMENT ON TABLE account_change_audit IS
    'Every direct or application change of an account''s role, state, verification, approval or '
    'password, and of a project membership, by any writer the triggers bind (011u). Append-only '
    'and hash-chained. Tamper-EVIDENT, not tamper-proof: a superuser or the tables'' owner can '
    'disable the triggers. A12 stays an Owner decision.';

-- The chain's head: one row, moved only by the recording function, serialized by its row lock.
CREATE TABLE IF NOT EXISTS account_change_audit_head (
    singleton    BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    last_seq     BIGINT,
    last_digest  TEXT NOT NULL CHECK (last_digest ~ '^[0-9a-f]{64}$')
);

-- Seeded once, before its guard exists (a re-run inserts nothing, so the guard never fires).
INSERT INTO account_change_audit_head (singleton, last_seq, last_digest)
SELECT TRUE, NULL, repeat('0', 64)
 WHERE NOT EXISTS (SELECT 1 FROM account_change_audit_head);

-- The exact text each row's digest covers. `lab_brain.accounts.change_audit` builds the same
-- text from the stored columns, in Python, to verify the chain without trusting this function.
CREATE OR REPLACE FUNCTION account_change_audit_digest_text(
    p_previous_digest TEXT, p_seq BIGINT, p_table TEXT, p_operation TEXT, p_account TEXT,
    p_actor TEXT, p_project TEXT, p_old JSONB, p_new JSONB, p_session_user TEXT, p_role TEXT,
    p_application TEXT, p_txid BIGINT, p_at TIMESTAMPTZ
) RETURNS TEXT AS $$
    SELECT concat_ws(E'\n',
        'lab-brain/account-change-audit/1', p_previous_digest, p_seq::text, p_table, p_operation,
        coalesce(p_account, ''), coalesce(p_actor, ''), coalesce(p_project, ''),
        coalesce(p_old::text, 'null'), coalesce(p_new::text, 'null'),
        p_session_user, p_role, p_application, p_txid::text,
        to_char(p_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION account_change_audit_owner() RETURNS NAME AS $$
    SELECT pg_get_userbyid(relowner) FROM pg_class
     WHERE oid = 'public.account_change_audit'::regclass
$$ LANGUAGE sql STABLE;

-- Fills, and chains, every audit row; refuses one not written by the recording functions. NOT
-- security definer: it runs as whoever inserts, so `current_user` is the owner only when the
-- insert comes from a recording function (which is), and the application role's own is refused.
CREATE OR REPLACE FUNCTION account_change_audit_seal() RETURNS TRIGGER AS $$
DECLARE
    head account_change_audit_head%ROWTYPE;
BEGIN
    IF current_user <> account_change_audit_owner() THEN
        RAISE EXCEPTION
            'account_change_audit is written only by its recording triggers, not by % (011u)',
            current_user;
    END IF;
    SELECT * INTO head FROM account_change_audit_head WHERE singleton FOR UPDATE;
    NEW.txid := txid_current();
    NEW.recorded_at := clock_timestamp();
    NEW.previous_seq := head.last_seq;
    NEW.previous_digest := head.last_digest;
    NEW.row_digest := encode(sha256(convert_to(account_change_audit_digest_text(
        NEW.previous_digest, NEW.audit_seq, NEW.table_name, NEW.operation, NEW.account_id,
        NEW.actor_id, NEW.project_id, NEW.old_values, NEW.new_values, NEW.db_session_user,
        NEW.role_setting, NEW.application_name, NEW.txid, NEW.recorded_at), 'UTF8')), 'hex');
    UPDATE account_change_audit_head SET last_seq = NEW.audit_seq, last_digest = NEW.row_digest
     WHERE singleton;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

DROP TRIGGER IF EXISTS account_change_audit_seal ON account_change_audit;
CREATE TRIGGER account_change_audit_seal
    BEFORE INSERT ON account_change_audit
    FOR EACH ROW EXECUTE FUNCTION account_change_audit_seal();
ALTER TABLE account_change_audit ENABLE ALWAYS TRIGGER account_change_audit_seal;

CREATE OR REPLACE FUNCTION account_change_audit_is_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is refused (011u)', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS account_change_audit_append_only ON account_change_audit;
CREATE TRIGGER account_change_audit_append_only
    BEFORE UPDATE OR DELETE ON account_change_audit
    FOR EACH ROW EXECUTE FUNCTION account_change_audit_is_append_only();
ALTER TABLE account_change_audit ENABLE ALWAYS TRIGGER account_change_audit_append_only;

DROP TRIGGER IF EXISTS account_change_audit_no_truncate ON account_change_audit;
CREATE TRIGGER account_change_audit_no_truncate
    BEFORE TRUNCATE ON account_change_audit
    FOR EACH STATEMENT EXECUTE FUNCTION account_change_audit_is_append_only();
ALTER TABLE account_change_audit ENABLE ALWAYS TRIGGER account_change_audit_no_truncate;

-- The head moves only inside the seal (run as the owner), never by another role's UPDATE.
CREATE OR REPLACE FUNCTION account_change_audit_head_moves_by_seal() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP <> 'UPDATE' OR current_user <> account_change_audit_owner() THEN
        RAISE EXCEPTION 'account_change_audit_head moves only with a sealed audit row (011u)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS account_change_audit_head_moves_by_seal ON account_change_audit_head;
CREATE TRIGGER account_change_audit_head_moves_by_seal
    BEFORE INSERT OR UPDATE OR DELETE ON account_change_audit_head
    FOR EACH ROW EXECUTE FUNCTION account_change_audit_head_moves_by_seal();
ALTER TABLE account_change_audit_head ENABLE ALWAYS TRIGGER account_change_audit_head_moves_by_seal;

DROP TRIGGER IF EXISTS account_change_audit_head_no_truncate ON account_change_audit_head;
CREATE TRIGGER account_change_audit_head_no_truncate
    BEFORE TRUNCATE ON account_change_audit_head
    FOR EACH STATEMENT EXECUTE FUNCTION account_change_audit_is_append_only();
ALTER TABLE account_change_audit_head ENABLE ALWAYS TRIGGER account_change_audit_head_no_truncate;

-- The recording triggers. SECURITY DEFINER: the row is written as the owner, so the seal admits
-- it; `session_user` and the `role` setting still name who connected and what role they set.
CREATE OR REPLACE FUNCTION account_change_audit_record_row() RETURNS TRIGGER AS $$
DECLARE
    old_row JSONB := NULL;
    new_row JSONB := NULL;
    row_account TEXT;
    row_actor TEXT;
    row_project TEXT;
BEGIN
    IF TG_TABLE_NAME = 'accounts' THEN
        IF TG_OP <> 'INSERT' THEN
            old_row := jsonb_build_object(
                'system_role', OLD.system_role, 'status', OLD.status,
                'email_verified_at', OLD.email_verified_at,
                'email_verified_by', OLD.email_verified_by, 'approved_at', OLD.approved_at,
                'approved_by_actor_id', OLD.approved_by_actor_id,
                'password_set', OLD.password_hash IS NOT NULL);
        END IF;
        IF TG_OP <> 'DELETE' THEN
            new_row := jsonb_build_object(
                'system_role', NEW.system_role, 'status', NEW.status,
                'email_verified_at', NEW.email_verified_at,
                'email_verified_by', NEW.email_verified_by, 'approved_at', NEW.approved_at,
                'approved_by_actor_id', NEW.approved_by_actor_id,
                'password_set', NEW.password_hash IS NOT NULL,
                'password_replaced', TG_OP = 'UPDATE'
                    AND OLD.password_hash IS DISTINCT FROM NEW.password_hash);
            row_account := NEW.account_id;
            row_actor := NEW.actor_id;
        ELSE
            row_account := OLD.account_id;
            row_actor := OLD.actor_id;
        END IF;
    ELSIF TG_TABLE_NAME = 'project_memberships' THEN
        IF TG_OP <> 'INSERT' THEN
            old_row := jsonb_build_object(
                'role', OLD.role, 'sensitivity_clearance', OLD.sensitivity_clearance,
                'approval_scopes', OLD.approval_scopes, 'active', OLD.active,
                'granted_by_actor_id', OLD.granted_by_actor_id);
        END IF;
        IF TG_OP <> 'DELETE' THEN
            new_row := jsonb_build_object(
                'role', NEW.role, 'sensitivity_clearance', NEW.sensitivity_clearance,
                'approval_scopes', NEW.approval_scopes, 'active', NEW.active,
                'granted_by_actor_id', NEW.granted_by_actor_id);
            row_actor := NEW.actor_id;
            row_project := NEW.project_id;
        ELSE
            row_actor := OLD.actor_id;
            row_project := OLD.project_id;
        END IF;
        SELECT a.account_id INTO row_account FROM accounts a WHERE a.actor_id = row_actor;
    ELSE  -- account_events, INSERT only
        new_row := jsonb_build_object(
            'event_id', NEW.event_id, 'kind', NEW.kind, 'by_actor_id', NEW.by_actor_id);
        row_account := NEW.account_id;
    END IF;
    INSERT INTO account_change_audit (table_name, operation, account_id, actor_id, project_id,
        old_values, new_values, db_session_user, role_setting, application_name, txid,
        recorded_at, previous_digest, row_digest)
    VALUES (TG_TABLE_NAME, TG_OP, row_account, row_actor, row_project, old_row, new_row,
        session_user, current_setting('role'), coalesce(current_setting('application_name', TRUE), ''),
        0, clock_timestamp(), repeat('0', 64), repeat('0', 64));
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION account_change_audit_record_truncate() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO account_change_audit (table_name, operation, db_session_user, role_setting,
        application_name, txid, recorded_at, previous_digest, row_digest)
    VALUES (TG_TABLE_NAME, 'TRUNCATE', session_user, current_setting('role'),
        coalesce(current_setting('application_name', TRUE), ''), 0, clock_timestamp(),
        repeat('0', 64), repeat('0', 64));
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

-- accounts
DROP TRIGGER IF EXISTS account_change_audit_insert ON accounts;
CREATE TRIGGER account_change_audit_insert
    AFTER INSERT OR DELETE ON accounts
    FOR EACH ROW EXECUTE FUNCTION account_change_audit_record_row();
ALTER TABLE accounts ENABLE ALWAYS TRIGGER account_change_audit_insert;

DROP TRIGGER IF EXISTS account_change_audit_update ON accounts;
CREATE TRIGGER account_change_audit_update
    AFTER UPDATE ON accounts
    FOR EACH ROW
    WHEN ((OLD.system_role, OLD.status, OLD.email_verified_at, OLD.email_verified_by,
           OLD.approved_at, OLD.approved_by_actor_id, OLD.password_hash)
          IS DISTINCT FROM
          (NEW.system_role, NEW.status, NEW.email_verified_at, NEW.email_verified_by,
           NEW.approved_at, NEW.approved_by_actor_id, NEW.password_hash))
    EXECUTE FUNCTION account_change_audit_record_row();
ALTER TABLE accounts ENABLE ALWAYS TRIGGER account_change_audit_update;

DROP TRIGGER IF EXISTS account_change_audit_truncate ON accounts;
CREATE TRIGGER account_change_audit_truncate
    AFTER TRUNCATE ON accounts
    FOR EACH STATEMENT EXECUTE FUNCTION account_change_audit_record_truncate();
ALTER TABLE accounts ENABLE ALWAYS TRIGGER account_change_audit_truncate;

-- project_memberships
DROP TRIGGER IF EXISTS account_change_audit_insert ON project_memberships;
CREATE TRIGGER account_change_audit_insert
    AFTER INSERT OR DELETE ON project_memberships
    FOR EACH ROW EXECUTE FUNCTION account_change_audit_record_row();
ALTER TABLE project_memberships ENABLE ALWAYS TRIGGER account_change_audit_insert;

DROP TRIGGER IF EXISTS account_change_audit_update ON project_memberships;
CREATE TRIGGER account_change_audit_update
    AFTER UPDATE ON project_memberships
    FOR EACH ROW
    WHEN ((OLD.actor_id, OLD.project_id, OLD.role, OLD.sensitivity_clearance,
           OLD.approval_scopes, OLD.active, OLD.granted_by_actor_id)
          IS DISTINCT FROM
          (NEW.actor_id, NEW.project_id, NEW.role, NEW.sensitivity_clearance,
           NEW.approval_scopes, NEW.active, NEW.granted_by_actor_id))
    EXECUTE FUNCTION account_change_audit_record_row();
ALTER TABLE project_memberships ENABLE ALWAYS TRIGGER account_change_audit_update;

DROP TRIGGER IF EXISTS account_change_audit_truncate ON project_memberships;
CREATE TRIGGER account_change_audit_truncate
    AFTER TRUNCATE ON project_memberships
    FOR EACH STATEMENT EXECUTE FUNCTION account_change_audit_record_truncate();
ALTER TABLE project_memberships ENABLE ALWAYS TRIGGER account_change_audit_truncate;

-- account_events: the application's own record, to match a change to its transaction's event.
DROP TRIGGER IF EXISTS account_change_audit_insert ON account_events;
CREATE TRIGGER account_change_audit_insert
    AFTER INSERT ON account_events
    FOR EACH ROW EXECUTE FUNCTION account_change_audit_record_row();
ALTER TABLE account_events ENABLE ALWAYS TRIGGER account_change_audit_insert;

DROP TRIGGER IF EXISTS account_change_audit_truncate ON account_events;
CREATE TRIGGER account_change_audit_truncate
    AFTER TRUNCATE ON account_events
    FOR EACH STATEMENT EXECUTE FUNCTION account_change_audit_record_truncate();
ALTER TABLE account_events ENABLE ALWAYS TRIGGER account_change_audit_truncate;
