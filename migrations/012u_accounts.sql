-- 012u_accounts.sql
--
-- Accounts: who may sign in to the research workspace, in which laboratory role, in which state.
--
-- WHY. The workspace served one actor, named when it was started, and had no login: whoever
-- reached it acted as that actor. A laboratory needs each person to sign in as themselves, with
-- exactly two system roles, and every research record to name the person who actually acted.
--
-- WHAT. One account per person, bound to their HUMAN actor -- the identity every existing record
-- names (episodes, research runs, memberships, warrant reviews, provenance). Authorization keeps
-- living where it lives: project memberships and their clearance. An account adds:
--   system_role   ADMIN or MEMBER. Exactly two roles; pending, active and suspended are STATES.
--   status        PENDING (registered; not yet verified and approved), ACTIVE, SUSPENDED.
--                 ACTIVE requires a verified email AND an approval -- verification first.
--   password      a scrypt hash; never the password.
--   sessions      sign-ins, stored as the SHA-256 of the cookie's random token, revocable.
--   tokens        single-use, expiring: email verification, password reset, first password.
--   events        what happened to an account and who did it; append-only.
--   admin access  every time an administrator opens another person's research; append-only.
--
-- RULES FOR EVERY WRITER (the triggers below), not only for the workspace:
--   - an account's id, actor, email and creation time never change;
--   - an approval names an ACTIVE administrator other than the person approved; the one
--     exception is the operator's bootstrap of the first administrator, which writes an ACTIVE
--     ADMIN directly, and only while there is no active administrator;
--   - the last active administrator cannot be demoted or suspended;
--   - a token is used at most once and never "unused" again; events and access records are
--     append-only, and an account is never deleted.

CREATE TABLE IF NOT EXISTS accounts (
    account_id            TEXT PRIMARY KEY CHECK (account_id ~ '^acc:[0-9a-f-]{36}$'),
    actor_id              TEXT NOT NULL UNIQUE REFERENCES actors (actor_id),
    email                 TEXT NOT NULL CHECK (
        email = lower(btrim(email)) AND length(email) <= 254
        AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
    ),
    display_name          TEXT NOT NULL CHECK (
        btrim(display_name) <> '' AND length(display_name) <= 120
    ),
    system_role           TEXT NOT NULL DEFAULT 'MEMBER' CHECK (system_role IN ('ADMIN', 'MEMBER')),
    status                TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'ACTIVE', 'SUSPENDED')),
    email_verified_at     TIMESTAMPTZ,
    email_verified_by     TEXT CHECK (email_verified_by IN ('EMAIL_LINK', 'OPERATOR')),
    approved_at           TIMESTAMPTZ,
    approved_by_actor_id  TEXT REFERENCES actors (actor_id),
    password_hash         TEXT CHECK (password_hash IS NULL OR password_hash ~ '^scrypt\$'),
    password_changed_at   TIMESTAMPTZ,
    failed_logins         INTEGER NOT NULL DEFAULT 0 CHECK (failed_logins >= 0),
    locked_until          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT accounts_verified_together
        CHECK ((email_verified_at IS NULL) = (email_verified_by IS NULL)),
    -- Verification precedes approval, and an active account has both.
    CONSTRAINT accounts_approved_only_when_verified
        CHECK (approved_at IS NULL OR email_verified_at IS NOT NULL),
    CONSTRAINT accounts_active_is_verified_and_approved
        CHECK (status <> 'ACTIVE' OR (email_verified_at IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS accounts_email_key ON accounts (email);

COMMENT ON TABLE accounts IS
    'Who may sign in to the workspace (012u): one account per person, bound to their HUMAN actor. '
    'Two system roles (ADMIN, MEMBER); PENDING, ACTIVE and SUSPENDED are states.';

CREATE OR REPLACE FUNCTION accounts_active_admin_exists(p_except TEXT) RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM accounts
         WHERE system_role = 'ADMIN' AND status = 'ACTIVE'
           AND account_id IS DISTINCT FROM p_except
    )
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION accounts_follow_their_rules() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status = 'PENDING' AND NEW.approved_at IS NULL
           AND NEW.approved_by_actor_id IS NULL AND NEW.email_verified_at IS NULL THEN
            RETURN NEW;
        END IF;
        -- The operator's bootstrap of the first administrator: the one account written ACTIVE.
        IF NEW.status = 'ACTIVE' AND NEW.system_role = 'ADMIN'
           AND NEW.email_verified_by = 'OPERATOR' AND NEW.approved_by_actor_id IS NULL
           AND NOT accounts_active_admin_exists(NEW.account_id) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'account % is created PENDING and becomes active by verification and an '
            'administrator''s approval; only the first administrator is bootstrapped active '
            '(012u)', NEW.account_id;
    END IF;
    IF (NEW.account_id, NEW.actor_id, NEW.email, NEW.created_at)
       IS DISTINCT FROM (OLD.account_id, OLD.actor_id, OLD.email, OLD.created_at) THEN
        RAISE EXCEPTION 'account %''s id, actor, email and creation time never change',
            OLD.account_id;
    END IF;
    IF OLD.email_verified_at IS NOT NULL
       AND (NEW.email_verified_at, NEW.email_verified_by)
           IS DISTINCT FROM (OLD.email_verified_at, OLD.email_verified_by) THEN
        RAISE EXCEPTION 'account %''s email verification is recorded once', OLD.account_id;
    END IF;
    IF OLD.approved_at IS NOT NULL
       AND (NEW.approved_at, NEW.approved_by_actor_id)
           IS DISTINCT FROM (OLD.approved_at, OLD.approved_by_actor_id) THEN
        RAISE EXCEPTION 'account %''s approval is recorded once', OLD.account_id;
    END IF;
    IF OLD.approved_at IS NULL AND NEW.approved_at IS NOT NULL THEN
        IF NEW.approved_by_actor_id IS NULL OR NEW.approved_by_actor_id = NEW.actor_id
           OR NOT EXISTS (
               SELECT 1 FROM accounts a
                WHERE a.actor_id = NEW.approved_by_actor_id
                  AND a.system_role = 'ADMIN' AND a.status = 'ACTIVE'
           ) THEN
            RAISE EXCEPTION
                'account % is approved only by an active administrator other than its holder',
                OLD.account_id;
        END IF;
    END IF;
    IF OLD.system_role = 'ADMIN' AND OLD.status = 'ACTIVE'
       AND (NEW.system_role <> 'ADMIN' OR NEW.status <> 'ACTIVE')
       AND NOT accounts_active_admin_exists(OLD.account_id) THEN
        RAISE EXCEPTION
            'account % is the last active administrator; appoint another before it is demoted '
            'or suspended', OLD.account_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_follow_their_rules ON accounts;
CREATE TRIGGER accounts_follow_their_rules
    BEFORE INSERT OR UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION accounts_follow_their_rules();

CREATE OR REPLACE FUNCTION account_records_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only (012u)', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_no_delete ON accounts;
CREATE TRIGGER accounts_no_delete
    BEFORE DELETE ON accounts
    FOR EACH ROW EXECUTE FUNCTION account_records_are_append_only();

CREATE TABLE IF NOT EXISTS account_sessions (
    session_hash   TEXT PRIMARY KEY CHECK (session_hash ~ '^[0-9a-f]{64}$'),
    account_id     TEXT NOT NULL REFERENCES accounts (account_id),
    created_at     TIMESTAMPTZ NOT NULL,
    last_seen_at   TIMESTAMPTZ NOT NULL,
    expires_at     TIMESTAMPTZ NOT NULL,
    revoked_at     TIMESTAMPTZ,
    CONSTRAINT account_sessions_expire_after_creation CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS account_sessions_account_idx ON account_sessions (account_id);

CREATE OR REPLACE FUNCTION account_sessions_stay_revoked() RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.session_hash, NEW.account_id, NEW.created_at)
       IS DISTINCT FROM (OLD.session_hash, OLD.account_id, OLD.created_at) THEN
        RAISE EXCEPTION 'a session''s identity never changes';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'a revoked session stays revoked';
    END IF;
    IF NEW.expires_at > OLD.expires_at THEN
        RAISE EXCEPTION 'a session is never extended past its expiry';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS account_sessions_stay_revoked ON account_sessions;
CREATE TRIGGER account_sessions_stay_revoked
    BEFORE UPDATE ON account_sessions
    FOR EACH ROW EXECUTE FUNCTION account_sessions_stay_revoked();

CREATE TABLE IF NOT EXISTS account_tokens (
    token_hash   TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    account_id   TEXT NOT NULL REFERENCES accounts (account_id),
    purpose      TEXT NOT NULL CHECK (purpose IN ('VERIFY_EMAIL', 'RESET_PASSWORD', 'SET_PASSWORD')),
    created_at   TIMESTAMPTZ NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    used_at      TIMESTAMPTZ,
    CONSTRAINT account_tokens_expire_after_creation CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS account_tokens_account_idx ON account_tokens (account_id, purpose);

CREATE OR REPLACE FUNCTION account_tokens_are_used_once() RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.token_hash, NEW.account_id, NEW.purpose, NEW.created_at, NEW.expires_at)
       IS DISTINCT FROM
       (OLD.token_hash, OLD.account_id, OLD.purpose, OLD.created_at, OLD.expires_at) THEN
        RAISE EXCEPTION 'a token never changes; only its use is recorded';
    END IF;
    IF OLD.used_at IS NOT NULL THEN
        RAISE EXCEPTION 'a token is used at most once';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS account_tokens_are_used_once ON account_tokens;
CREATE TRIGGER account_tokens_are_used_once
    BEFORE UPDATE ON account_tokens
    FOR EACH ROW EXECUTE FUNCTION account_tokens_are_used_once();

CREATE TABLE IF NOT EXISTS account_events (
    event_id      TEXT PRIMARY KEY,
    -- The order events were written in, which a shared clock reading cannot give.
    seq           BIGINT GENERATED ALWAYS AS IDENTITY,
    account_id    TEXT NOT NULL REFERENCES accounts (account_id),
    kind          TEXT NOT NULL CHECK (kind IN (
        'REGISTERED', 'BOOTSTRAPPED', 'EMAIL_VERIFIED', 'APPROVED', 'REJECTED', 'SUSPENDED',
        'REACTIVATED', 'ROLE_CHANGED', 'PASSWORD_SET', 'PASSWORD_RESET_REQUESTED',
        'PASSWORD_RESET', 'PASSWORD_CHANGED', 'SIGNED_IN', 'SIGN_IN_REFUSED', 'LOCKED',
        'SIGNED_OUT', 'PROJECT_CREATED', 'MEMBERSHIP_GRANTED', 'MEMBERSHIP_REVOKED'
    )),
    -- Who acted: the account holder, an administrator, or NULL for the operator's command line.
    by_actor_id   TEXT REFERENCES actors (actor_id),
    detail        JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS account_events_account_idx ON account_events (account_id, seq);

DROP TRIGGER IF EXISTS account_events_append_only ON account_events;
CREATE TRIGGER account_events_append_only
    BEFORE UPDATE OR DELETE ON account_events
    FOR EACH ROW EXECUTE FUNCTION account_records_are_append_only();

CREATE TABLE IF NOT EXISTS admin_access_log (
    access_id        TEXT PRIMARY KEY,
    admin_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),
    project_id       TEXT REFERENCES projects (project_id),
    subject          TEXT NOT NULL CHECK (btrim(subject) <> ''),
    accessed_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS admin_access_log_project_idx ON admin_access_log (project_id, accessed_at);

CREATE OR REPLACE FUNCTION admin_access_is_by_an_admin() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM accounts
         WHERE actor_id = NEW.admin_actor_id AND system_role = 'ADMIN' AND status = 'ACTIVE'
    ) THEN
        RAISE EXCEPTION '% is not an active administrator; only one opens another person''s '
            'research for oversight', NEW.admin_actor_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS admin_access_is_by_an_admin ON admin_access_log;
CREATE TRIGGER admin_access_is_by_an_admin
    BEFORE INSERT ON admin_access_log
    FOR EACH ROW EXECUTE FUNCTION admin_access_is_by_an_admin();

DROP TRIGGER IF EXISTS admin_access_log_append_only ON admin_access_log;
CREATE TRIGGER admin_access_log_append_only
    BEFORE UPDATE OR DELETE ON admin_access_log
    FOR EACH ROW EXECUTE FUNCTION account_records_are_append_only();

-- An administrator also administers the deployment's language-model routes (`012f`): the grant
-- follows the ADMIN role, and says so, beside the operator's own grants from the command line.
ALTER TABLE llm_administrators DROP CONSTRAINT IF EXISTS llm_administrators_granted_through_check;
ALTER TABLE llm_administrators ADD CONSTRAINT llm_administrators_granted_through_check
    CHECK (granted_through IN ('OPERATOR_CLI', 'ADMIN_ROLE'));
