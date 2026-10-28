-- 011n_research_session_provenance.sql
--
-- Every research run says how it was started, and a run started by a signed-in person names the
-- session it was started in -- by a reference that cannot sign anyone in.
--
-- WHY. `012u` gave the workspace accounts and sessions, and `012c` records who ran research
-- (`research_runs.actor_id`). Nothing joined the two: a run row could not say whether its actor
-- was a person signed in at that moment, an operator at the command line, or a direct database
-- writer that filled `actor_id` in by hand (G0 offline-integrity audit 2026-10-27, §G0-A:
-- "research_runs has no session column; account_sessions.session_hash is linked to no run"). SAI
-- 3.4 acceptance G0-A asks for exactly that link -- a valid ADMIN/MEMBER sign-in, the project's
-- membership and clearance, and the session's NON-SECRET audit reference saved with actor,
-- project, run and trace -- and says manual database edits and calls to internal functions that
-- skip the sign-in must not count as such a run.
--
-- THE REFERENCE. `account_sessions.session_hash` is SHA-256 of the cookie's token. It is not the
-- token, but it IS the lookup key a session is resolved by, and anyone holding a database dump
-- and a stolen hash could match a cookie offline; it must never be copied into research records,
-- reports, logs or exports. Neither may anything derived from the token. So each session gets a
-- SEPARATE reference, `session_audit_ref` ('sar:' + 32 hex digits):
--   - minted BY THE DATABASE at insert, from `gen_random_uuid()` (a CSPRNG), whatever the writer
--     supplied -- so no writer can make it a function of the token or of the hash;
--   - unique, and immutable once minted;
--   - never consulted to authenticate: `AccountService.session` resolves a cookie by
--     `session_hash` alone. Knowing a session's audit reference signs nobody in;
--   - cross-checkable: it names exactly one `account_sessions` row, whose account and actor a
--     reviewer can join to.
-- Sessions that already exist are given one here; that is a session's reference, not a run's.
--
-- HOW A RUN WAS STARTED: `research_runs.run_origin`, NOT NULL, no default -- a writer declares it.
--   WEB_SESSION         the workspace with accounts (`lab-brain web --accounts`): a person signed
--                       in. `session_audit_ref` is REQUIRED, and checked below.
--   OPERATOR_WORKSPACE  the workspace without accounts, started by the operator for one named
--                       actor. No session exists; none is claimed.
--   OPERATOR_CLI        `lab-brain research run`, or any process holding database credentials that
--                       calls the research service or writes this table itself. The database
--                       cannot tell these apart, and none of them attests a person's sign-in.
--   LEGACY_UNATTESTED   a run stored before this migration. Given here to every existing row and
--                       refused for any new one. No reference is invented for it.
-- Only WEB_SESSION rows are evidence of an authenticated person's run; the other origins say, in
-- the row and in the report, that they are not.
--
-- RULES FOR EVERY WRITER (the triggers below):
--   - a WEB_SESSION run names a session (a) of an account bound to the run's OWN actor, (b) whose
--     account is ACTIVE, (c) that is not revoked, not expired and not idle past its two hours at
--     the moment the row is written (the database's clock), and that began no later than the run;
--     and the actor is (d) an ACTIVE member of the run's project (e) cleared for the question's
--     classification. An ADMIN role grants none of this: an administrator who is not a member is
--     refused like anyone else. The session and the membership rows are locked FOR SHARE, so a
--     revocation racing the run either commits first (and the run is refused) or waits for it;
--   - a row with another origin carries no reference (CHECK);
--   - `run_origin` and `session_audit_ref` never change and are never deleted. Revoking or
--     expiring the session later leaves the run's record exactly as it was: the reference records
--     that the session was valid when the run began, not that it still is;
--   - a report recorded for a run (`012d`) carries the run's own origin and reference in
--     `session_provenance`, with the run's id, actor and project, and contains no session's
--     `session_hash` anywhere in its text.
--
-- THE AUDIT TRAIL: the view `research_run_session_audit` lists, per run, actor, project, run,
-- episode, trace, origin and reference, with the referenced session's account and its CURRENT
-- revocation -- and never a `session_hash`.

-- ---------------------------------------------------------------------------------------------
-- The session's audit reference.
-- ---------------------------------------------------------------------------------------------

ALTER TABLE account_sessions ADD COLUMN IF NOT EXISTS session_audit_ref TEXT;

-- Existing sessions are given a reference before the rules below exist. This UPDATE passes
-- `account_sessions_stay_revoked` (`012u`): identity, revocation and expiry are untouched.
UPDATE account_sessions
   SET session_audit_ref = 'sar:' || replace(gen_random_uuid()::text, '-', '')
 WHERE session_audit_ref IS NULL;

ALTER TABLE account_sessions ALTER COLUMN session_audit_ref SET NOT NULL;

ALTER TABLE account_sessions DROP CONSTRAINT IF EXISTS account_sessions_audit_ref_form;
ALTER TABLE account_sessions ADD CONSTRAINT account_sessions_audit_ref_form
    CHECK (session_audit_ref ~ '^sar:[0-9a-f]{32}$');

CREATE UNIQUE INDEX IF NOT EXISTS account_sessions_audit_ref_key
    ON account_sessions (session_audit_ref);

COMMENT ON COLUMN account_sessions.session_audit_ref IS
    'The session''s non-secret audit reference (011n): random, minted by the database at insert, '
    'immutable; never used to authenticate. Research runs started in this session name it.';

CREATE OR REPLACE FUNCTION account_sessions_audit_ref_is_minted() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Whatever the writer sent is discarded: a reference a writer chose could be the token,
        -- the hash, or anything derived from them.
        NEW.session_audit_ref := 'sar:' || replace(gen_random_uuid()::text, '-', '');
        RETURN NEW;
    END IF;
    IF NEW.session_audit_ref IS DISTINCT FROM OLD.session_audit_ref THEN
        RAISE EXCEPTION 'a session''s audit reference never changes (011n)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS account_sessions_audit_ref_is_minted ON account_sessions;
CREATE TRIGGER account_sessions_audit_ref_is_minted
    BEFORE INSERT OR UPDATE ON account_sessions
    FOR EACH ROW EXECUTE FUNCTION account_sessions_audit_ref_is_minted();

-- ---------------------------------------------------------------------------------------------
-- How each research run was started.
-- ---------------------------------------------------------------------------------------------

-- The default fills the rows already stored -- without firing a row trigger, so a finished run's
-- final record is not "updated" -- and is then dropped: every new row declares its origin.
ALTER TABLE research_runs
    ADD COLUMN IF NOT EXISTS run_origin TEXT NOT NULL DEFAULT 'LEGACY_UNATTESTED';
ALTER TABLE research_runs ALTER COLUMN run_origin DROP DEFAULT;

ALTER TABLE research_runs
    ADD COLUMN IF NOT EXISTS session_audit_ref TEXT
        REFERENCES account_sessions (session_audit_ref);

ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_origin_is_known;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_origin_is_known
    CHECK (run_origin IN ('WEB_SESSION', 'OPERATOR_WORKSPACE', 'OPERATOR_CLI',
                          'LEGACY_UNATTESTED'));

ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_session_ref_iff_web_session;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_session_ref_iff_web_session
    CHECK ((run_origin = 'WEB_SESSION') = (session_audit_ref IS NOT NULL));

CREATE INDEX IF NOT EXISTS research_runs_session_audit_ref_idx
    ON research_runs (session_audit_ref) WHERE session_audit_ref IS NOT NULL;

COMMENT ON COLUMN research_runs.run_origin IS
    'How this run was started (011n): WEB_SESSION (a signed-in person; session_audit_ref names the '
    'session), OPERATOR_WORKSPACE (the workspace without accounts), OPERATOR_CLI (the command line '
    'or any direct database writer), LEGACY_UNATTESTED (stored before 011n). Immutable.';
COMMENT ON COLUMN research_runs.session_audit_ref IS
    'For a WEB_SESSION run, the non-secret audit reference of the session it was started in: a '
    'session of the run''s own actor, valid when the run began, the actor an active, cleared '
    'member of the project (011n). Never a token or a session_hash. Immutable.';

CREATE OR REPLACE FUNCTION research_runs_session_provenance() RETURNS TRIGGER AS $$
DECLARE
    v_session  account_sessions%ROWTYPE;
    v_actor    TEXT;
    v_status   TEXT;
    v_now      TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'research run %''s session provenance is never deleted (011n)',
            OLD.research_run_id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.run_origin, NEW.session_audit_ref)
           IS DISTINCT FROM (OLD.run_origin, OLD.session_audit_ref) THEN
            RAISE EXCEPTION
                'research run %''s origin (%) and session reference are recorded once and never '
                'changed (011n)', OLD.research_run_id, OLD.run_origin;
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.run_origin = 'LEGACY_UNATTESTED' THEN
        RAISE EXCEPTION
            'research run % cannot be LEGACY_UNATTESTED: that origin marks runs stored before '
            '011n; a new run declares how it was started', NEW.research_run_id;
    END IF;
    IF NEW.run_origin <> 'WEB_SESSION' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_session FROM account_sessions
     WHERE session_audit_ref = NEW.session_audit_ref
       FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'research run % names session reference %, which names no session',
            NEW.research_run_id, NEW.session_audit_ref;
    END IF;
    SELECT a.actor_id, a.status INTO v_actor, v_status FROM accounts a
     WHERE a.account_id = v_session.account_id
       FOR SHARE;
    IF v_actor IS DISTINCT FROM NEW.actor_id THEN
        RAISE EXCEPTION
            'research run % of actor % names a session of another account; a run started in '
            'the workspace names its own actor''s session', NEW.research_run_id, NEW.actor_id;
    END IF;
    IF v_status IS DISTINCT FROM 'ACTIVE' THEN
        RAISE EXCEPTION 'research run % names a session of an account that is %, not ACTIVE',
            NEW.research_run_id, v_status;
    END IF;
    IF v_session.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'research run % names a session revoked at %; it signs in nobody',
            NEW.research_run_id, v_session.revoked_at;
    END IF;
    IF v_session.expires_at <= v_now OR v_session.last_seen_at <= v_now - interval '2 hours' THEN
        RAISE EXCEPTION 'research run % names a session that has expired', NEW.research_run_id;
    END IF;
    IF NEW.started_at < v_session.created_at THEN
        RAISE EXCEPTION 'research run % starts at %, before its session began (%)',
            NEW.research_run_id, NEW.started_at, v_session.created_at;
    END IF;
    PERFORM 1 FROM project_memberships m
      WHERE m.actor_id = NEW.actor_id AND m.project_id = NEW.project_id AND m.active
        AND NEW.question_label = ANY (m.sensitivity_clearance)
        FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'research run %: % is not an active member of % cleared for %; a system role grants '
            'no project membership', NEW.research_run_id, NEW.actor_id, NEW.project_id,
            coalesce(NEW.question_label, 'an unclassified question');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS research_runs_session_provenance_trg ON research_runs;
CREATE TRIGGER research_runs_session_provenance_trg
    BEFORE INSERT OR UPDATE OR DELETE ON research_runs
    FOR EACH ROW EXECUTE FUNCTION research_runs_session_provenance();

-- ---------------------------------------------------------------------------------------------
-- The report carries the run's provenance, and no session's lookup key.
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION research_run_reports_carry_session_provenance() RETURNS TRIGGER AS $$
DECLARE
    v_run research_runs%ROWTYPE;
    v_said JSONB := NEW.report -> 'session_provenance';
BEGIN
    SELECT * INTO v_run FROM research_runs WHERE research_run_id = NEW.research_run_id;
    IF NOT FOUND THEN
        RETURN NEW;  -- `research_run_reports_are_their_runs` (012d) refuses it
    END IF;
    IF v_said IS NULL OR jsonb_typeof(v_said) = 'null' THEN
        IF v_run.run_origin = 'LEGACY_UNATTESTED' THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'the report recorded for research run % does not say how the run was started; it '
            'carries the run''s session_provenance (011n)', NEW.research_run_id;
    END IF;
    IF (v_said ->> 'origin', v_said ->> 'session_audit_ref', v_said ->> 'research_run_id',
        v_said ->> 'actor_id', v_said ->> 'project_id')
       IS DISTINCT FROM
       (v_run.run_origin, v_run.session_audit_ref, v_run.research_run_id, v_run.actor_id,
        v_run.project_id) THEN
        RAISE EXCEPTION
            'the report recorded for research run % misstates its session provenance: the run '
            'was started % with reference %', NEW.research_run_id, v_run.run_origin,
            coalesce(v_run.session_audit_ref, 'none');
    END IF;
    IF EXISTS (
        SELECT 1 FROM account_sessions s WHERE strpos(NEW.report::text, s.session_hash) > 0
    ) THEN
        RAISE EXCEPTION
            'the report recorded for research run % contains a session''s lookup key; reports '
            'carry only the non-secret session_audit_ref', NEW.research_run_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS research_run_reports_carry_session_provenance_trg ON research_run_reports;
CREATE TRIGGER research_run_reports_carry_session_provenance_trg
    BEFORE INSERT ON research_run_reports
    FOR EACH ROW EXECUTE FUNCTION research_run_reports_carry_session_provenance();

-- ---------------------------------------------------------------------------------------------
-- The audit trail.
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE VIEW research_run_session_audit AS
SELECT r.research_run_id,
       r.episode_id,
       e.trace_id,
       r.project_id,
       r.actor_id,
       r.ordinal,
       r.started_at,
       r.run_origin,
       r.session_audit_ref,
       s.account_id        AS session_account_id,
       s.created_at        AS session_created_at,
       s.revoked_at        AS session_revoked_at_now
  FROM research_runs r
  JOIN research_episodes e ON e.episode_id = r.episode_id
  LEFT JOIN account_sessions s ON s.session_audit_ref = r.session_audit_ref;

COMMENT ON VIEW research_run_session_audit IS
    'Per research run: actor, project, run, episode, trace, how it was started and the non-secret '
    'session reference, with that session''s account and its current revocation (011n). No '
    'session_hash. session_revoked_at_now is today''s state; the run row records that the session '
    'was valid when the run began.';
