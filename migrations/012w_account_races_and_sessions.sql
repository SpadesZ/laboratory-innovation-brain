-- 012w: the last active administrator is kept under concurrency, and a session's bounds hold for
-- every writer (adversarial audit A5, A12).
--
-- WHY (A5). `accounts_follow_their_rules` (012u) refuses to demote or suspend the last active
-- administrator by asking whether ANOTHER active administrator exists. Two administrators who
-- demote or suspend each other at the same moment each see the other still active, both
-- transactions commit, and none is left: the workspace serves requests on several threads, so
-- this is two clicks at once. Every change that takes an active administrator out of that state
-- now first takes one transaction-scoped lock. The second waits for the first to commit, and its
-- check -- a new statement, so a new snapshot -- then sees the first one's change and refuses.
-- The lock is taken by a trigger named to fire before `accounts_follow_their_rules`.
--
-- WHY (A12). A session's twelve-hour lifetime and its idle limit were the application's alone: a
-- writer could insert a session valid for ten years, or last seen in the future, and it would
-- sign in. The lifetime is now a constraint, and a session is never seen before it began or after
-- it ends.

CREATE OR REPLACE FUNCTION accounts_admin_changes_one_at_a_time() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.system_role = 'ADMIN' AND OLD.status = 'ACTIVE'
       AND (NEW.system_role <> 'ADMIN' OR NEW.status <> 'ACTIVE') THEN
        PERFORM pg_advisory_xact_lock(hashtext('lab_brain.accounts.last_active_administrator'));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_admin_changes_one_at_a_time ON accounts;
CREATE TRIGGER accounts_admin_changes_one_at_a_time
    BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION accounts_admin_changes_one_at_a_time();

ALTER TABLE account_sessions DROP CONSTRAINT IF EXISTS account_sessions_last_at_most_twelve_hours;
ALTER TABLE account_sessions ADD CONSTRAINT account_sessions_last_at_most_twelve_hours
    CHECK (expires_at <= created_at + interval '12 hours');

ALTER TABLE account_sessions DROP CONSTRAINT IF EXISTS account_sessions_seen_within_their_life;
ALTER TABLE account_sessions ADD CONSTRAINT account_sessions_seen_within_their_life
    CHECK (last_seen_at >= created_at AND last_seen_at <= expires_at);
