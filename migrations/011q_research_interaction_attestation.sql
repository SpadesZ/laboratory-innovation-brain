-- 011q_research_interaction_attestation.sql
--
-- A research run started on the web carries the web tier's SIGNED statement that an authenticated,
-- CSRF-verified request started it -- stored once, bound to the row, and verified outside the
-- database against keys the database does not hold.
--
-- WHY. `011n` binds each WEB_SESSION run to a `session_audit_ref` and checks, for every writer,
-- that the reference names a live session of the run's own actor, an active member of the
-- project cleared for the question. The Independent Chief Auditor (G0 closure, 2026-10-28): "A
-- valid session audit reference does not independently prove that a research run originated
-- through authenticated user interaction." Correct: a reference is NOT a secret. It is readable
-- in `account_sessions` and printed in every report. A database writer holding only the
-- application role's privileges can insert a WEB_SESSION row naming another live session's
-- reference, for that session's own actor and project, at a valid time -- and `011n` accepts it
-- (`tests/e2e/test_g0_interaction_attestation_postgres.py` shows it). Until now such a row was
-- rendered as a "signed-in web session" run.
--
-- WHAT IS ADDED. Three columns on `research_runs`, all NULL or all set, only on WEB_SESSION rows:
--   interaction_statement  the exact canonical JSON text the web tier signed (RFC 8785 profile):
--                          kind 'lab-brain/research-interaction', version 1, research_run_id,
--                          episode_id, trace_id, actor_id, project_id, session_audit_ref, route,
--                          method, csrf_verified = true, signed_at, a 128-bit random nonce;
--   interaction_signature  its Ed25519 signature, base64;
--   interaction_key_id     'ik:' + 32 hex digits, the id of the web tier's public key.
-- The PRIVATE key lives only in the web tier (the file `LAB_BRAIN_INTERACTION_SIGNING_KEY`
-- names); the PUBLIC keys are pinned OUTSIDE the database (the file
-- `LAB_BRAIN_INTERACTION_AUTHORITIES` names), with `until=` for rotation, like the review
-- authorities of `security.reviewer_identity`.
--
-- WHAT THE DATABASE CHECKS, FOR EVERY WRITER:
--   - all three or none; only on a WEB_SESSION row; the key id and signature have their forms;
--   - the statement's fields ARE the row's columns (CHECK): run id, episode, actor, project,
--     session reference; kind and version; csrf_verified true; method POST; route '/runs' or
--     '/episodes/<this episode>/continue'. A valid signature for one run, pasted onto another
--     row, is refused here -- the run id differs, and the signature covers it;
--   - the statement's trace is the trace of the row's episode (trigger: another table);
--   - a nonce is used once, across all runs (unique index);
--   - the three columns are written with the row and never changed, filled in later or erased
--     (trigger); the row itself is never deleted (`011n`);
--   - a report recorded for a run (`012d`) carries the run's own attestation in
--     `session_provenance`, or none when the run has none -- never another.
--
-- WHAT THE DATABASE DOES NOT AND CANNOT DO: verify Ed25519. It must not be asked to: anything it
-- holds, a database writer can rewrite, including any key it could check against. Verification
-- is `security.interaction_attestation.InteractionTrust.verify`, in Python, against the pinned
-- public keys. The claim levels are computed there, whenever a run or report is shown -- never
-- stored:
--   INTERACTION_VERIFIED         signature verifies under a key pinned and valid at signed_at,
--                                and the statement names exactly this row. The ONLY level shown
--                                as "originated from an authenticated interaction".
--   SESSION_RECORDED_UNVERIFIED  WEB_SESSION with a valid reference, but no attestation, or one
--                                that does not verify (including: no key pinned).
--   OPERATOR_UNATTESTED          OPERATOR_WORKSPACE / OPERATOR_CLI.
--   LEGACY_UNATTESTED            stored before `011n`.
-- The audit view gains the three columns and `database_claim_ceiling`: the highest level the
-- database ALONE supports, which is never INTERACTION_VERIFIED.
--
-- THE TRUST ROOT THAT REMAINS, PLAINLY. Whoever holds the web tier's signing key, or controls the
-- deployment's configuration (which keys are pinned), can make a statement verify. A database
-- writer with migration rights can still change roles and state directly: A12 of the account-
-- security audit (2026-10-20, §7/§8) is the operator trust root and remains an OWNER DECISION;
-- this migration does not defeat it. A stolen session cookie used through the real web tier
-- yields a verified interaction: an authentication risk, not a provenance one.
--
-- SECRETS. None of the three columns holds a private key, a session token or a `session_hash`;
-- the statement names only the non-secret `session_audit_ref`.
--
-- Existing rows keep NULL in all three (no attestation is invented); adding the columns fires no
-- row trigger. Idempotent.

ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS interaction_statement TEXT;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS interaction_signature TEXT;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS interaction_key_id TEXT;

ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_interaction_all_or_none;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_interaction_all_or_none
    CHECK ((interaction_statement IS NULL) = (interaction_signature IS NULL)
       AND (interaction_statement IS NULL) = (interaction_key_id IS NULL));

ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_interaction_is_web_session;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_interaction_is_web_session
    CHECK (interaction_statement IS NULL OR run_origin = 'WEB_SESSION');

ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_interaction_forms;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_interaction_forms
    CHECK (interaction_statement IS NULL
        OR (interaction_key_id ~ '^ik:[0-9a-f]{32}$'
            AND interaction_signature ~ '^[A-Za-z0-9+/]{86}==$'));

-- The statement is the row's: a signature for one run cannot be pasted onto another.
ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_interaction_names_this_row;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_interaction_names_this_row
    CHECK (interaction_statement IS NULL
        OR (    (interaction_statement::jsonb ->> 'kind') = 'lab-brain/research-interaction'
            AND (interaction_statement::jsonb ->> 'version') = '1'
            AND (interaction_statement::jsonb ->> 'research_run_id') = research_run_id
            AND (interaction_statement::jsonb ->> 'episode_id') = episode_id
            AND (interaction_statement::jsonb ->> 'actor_id') = actor_id
            AND (interaction_statement::jsonb ->> 'project_id') = project_id
            AND (interaction_statement::jsonb ->> 'session_audit_ref') = session_audit_ref
            AND (interaction_statement::jsonb -> 'csrf_verified') = 'true'::jsonb
            AND (interaction_statement::jsonb ->> 'method') = 'POST'
            AND (interaction_statement::jsonb ->> 'route')
                IN ('/runs', '/episodes/' || episode_id || '/continue')
            AND (interaction_statement::jsonb ->> 'nonce') ~ '^[0-9a-f]{32}$'));

CREATE UNIQUE INDEX IF NOT EXISTS research_runs_interaction_nonce_key
    ON research_runs ((interaction_statement::jsonb ->> 'nonce'))
    WHERE interaction_statement IS NOT NULL;

COMMENT ON COLUMN research_runs.interaction_statement IS
    'The canonical statement the web tier signed on the authenticated, CSRF-verified request that '
    'started or continued this run (011q). Its fields are this row''s (CHECK). A claim verified in '
    'Python against keys pinned outside the database; never a verdict. Immutable.';
COMMENT ON COLUMN research_runs.interaction_signature IS
    'Ed25519 signature (base64) over interaction_statement (011q). Immutable.';
COMMENT ON COLUMN research_runs.interaction_key_id IS
    'Id (ik:...) of the web-tier public key that signed interaction_statement (011q). Immutable.';

CREATE OR REPLACE FUNCTION research_runs_interaction_attestation() RETURNS TRIGGER AS $$
DECLARE
    v_trace TEXT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.interaction_statement, NEW.interaction_signature, NEW.interaction_key_id)
           IS DISTINCT FROM
           (OLD.interaction_statement, OLD.interaction_signature, OLD.interaction_key_id) THEN
            RAISE EXCEPTION
                'research run %''s interaction attestation is recorded with the run and never '
                'changed, added or erased (011q)', OLD.research_run_id;
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.interaction_statement IS NULL
       OR (NEW.interaction_statement::jsonb ->> 'episode_id') IS DISTINCT FROM NEW.episode_id THEN
        -- None, or a statement for another episode: `research_runs_interaction_names_this_row`
        -- refuses the latter by name, after this trigger.
        RETURN NEW;
    END IF;
    SELECT trace_id INTO v_trace FROM research_episodes WHERE episode_id = NEW.episode_id;
    IF v_trace IS DISTINCT FROM (NEW.interaction_statement::jsonb ->> 'trace_id') THEN
        RAISE EXCEPTION
            'research run %''s interaction statement names trace %, not its episode''s (%) (011q)',
            NEW.research_run_id, NEW.interaction_statement::jsonb ->> 'trace_id', v_trace;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS research_runs_interaction_attestation_trg ON research_runs;
CREATE TRIGGER research_runs_interaction_attestation_trg
    BEFORE INSERT OR UPDATE ON research_runs
    FOR EACH ROW EXECUTE FUNCTION research_runs_interaction_attestation();

-- ---------------------------------------------------------------------------------------------
-- The report carries the run's own attestation, or none.
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION research_run_reports_carry_interaction() RETURNS TRIGGER AS $$
DECLARE
    v_run research_runs%ROWTYPE;
    v_said JSONB := NEW.report -> 'session_provenance';
BEGIN
    SELECT * INTO v_run FROM research_runs WHERE research_run_id = NEW.research_run_id;
    IF NOT FOUND OR v_said IS NULL OR jsonb_typeof(v_said) <> 'object' THEN
        RETURN NEW;  -- `012d` and `011n` decide these
    END IF;
    IF (v_said ->> 'interaction_statement', v_said ->> 'interaction_signature',
        v_said ->> 'interaction_key_id')
       IS DISTINCT FROM
       (v_run.interaction_statement, v_run.interaction_signature, v_run.interaction_key_id) THEN
        RAISE EXCEPTION
            'the report recorded for research run % misstates its interaction attestation: it '
            'carries the run''s own, or none when the run has none (011q)', NEW.research_run_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS research_run_reports_carry_interaction_trg ON research_run_reports;
CREATE TRIGGER research_run_reports_carry_interaction_trg
    BEFORE INSERT ON research_run_reports
    FOR EACH ROW EXECUTE FUNCTION research_run_reports_carry_interaction();

-- ---------------------------------------------------------------------------------------------
-- The audit trail: what the database holds, and the most it alone can claim.
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
       s.revoked_at        AS session_revoked_at_now,
       r.interaction_statement,
       r.interaction_signature,
       r.interaction_key_id,
       CASE r.run_origin
           WHEN 'WEB_SESSION' THEN 'SESSION_RECORDED_UNVERIFIED'
           WHEN 'LEGACY_UNATTESTED' THEN 'LEGACY_UNATTESTED'
           ELSE 'OPERATOR_UNATTESTED'
       END                 AS database_claim_ceiling
  FROM research_runs r
  JOIN research_episodes e ON e.episode_id = r.episode_id
  LEFT JOIN account_sessions s ON s.session_audit_ref = r.session_audit_ref;

COMMENT ON VIEW research_run_session_audit IS
    'Per research run: actor, project, run, episode, trace, how it was started, the non-secret '
    'session reference with that session''s account and current revocation (011n), and the web '
    'tier''s signed interaction attestation (011q). No session_hash. database_claim_ceiling is the '
    'most the database alone supports and is never INTERACTION_VERIFIED: that level is computed '
    'by security.interaction_attestation.audit_claims against keys pinned outside the database.';
