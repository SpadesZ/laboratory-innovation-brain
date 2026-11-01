-- 011w: a verification authorization is a statement its person SIGNED.
--
-- 011s made post-screening support depend on a pre-registered test: an authorization naming the
-- hypothesis, the capability, the declaration and the predictions, by "an active HUMAN member of
-- the project". Who that member was rested on `actor_id` -- a string. Every service connects with
-- the same database role, so anyone who could write a row could authorize a test in a real
-- member's name, and the pre-registration a post-screening support rests on proved nothing about
-- a person (SPEC-ISSUE-018; the owner-boundary audit's risk 2).
--
-- The Causal Warrant Gate solved the same problem for warrant answers (012p): an Ed25519 key that
-- a review AUTHORITY enrolled for that person in that project, the authority's public key pinned
-- OUTSIDE the database (`LAB_BRAIN_REVIEW_AUTHORITIES`), and the signature verified in Python on
-- every read that counts it. This migration reuses that design for authorizations, in tables of
-- its own -- the warrant gate's tables and rules are not touched:
--
--   verification_authorizer_enrolments   an authority's signed statement that a key authorizes
--       verifications for one person in one project. Scope VERIFICATION_AUTHORIZATION only (the
--       scope is inside the authority's signature, so a warrant enrolment is never one of these).
--   verification_authorizer_revocations  an authority's signed revocation of such an enrolment.
--   verification_authorizations.{enrolment_id, signature, signed_at}   the person's signature over
--       the whole authorization (`core.models.reviewer.authorization_statement`): id, project,
--       episode, hypothesis, predictions, capability, declaration hash, person, rationale, time,
--       enrolment. Required for every authorization written from now on.
--
-- WHERE IT IS CHECKED. SQL cannot verify Ed25519, so SQL holds the FRAME and Python the signature:
--   at write (trigger): signed, under an unrevoked enrolment of the person named, in that
--       project, signed after the enrolment and after the hypothesis, not in the future;
--   at admission (`prospective_authorization_problem`, rule (l)): the frame again, on the rows as
--       they are now -- an unsigned authorization (one written before 011w), or one whose
--       enrolment was revoked with effect at or before its signature, licenses nothing;
--   on every read that counts it (Python, `verification.prospective.authorization_problem`, the
--       evidence sink and the evaluation collector's `unverified_authorization` fact): the
--       authority's signature on the enrolment and the person's on the authorization.
--
-- WHAT IT DOES NOT COVER (SPEC-ISSUE-018): the holder of an authority key can enrol anyone; the
-- deployment's configuration chooses the authorities; a person's own key is theirs to misuse.
--
-- Applied after 011v.

-- -- enrolments and revocations ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS verification_authorizer_enrolments (
    enrolment_id         TEXT PRIMARY KEY CHECK (btrim(enrolment_id) <> ''),
    project_id           TEXT NOT NULL REFERENCES projects (project_id),
    actor_id             TEXT NOT NULL REFERENCES actors (actor_id),
    public_key           TEXT NOT NULL CHECK (public_key ~ '^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$'),
    key_id               TEXT NOT NULL,
    scope                TEXT NOT NULL CHECK (scope = 'VERIFICATION_AUTHORIZATION'),
    enrolled_at          TIMESTAMPTZ NOT NULL,
    authority_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),
    authority_key_id     TEXT NOT NULL CHECK (authority_key_id ~ '^rk:[0-9a-f]{32}$'),
    authority_signature  TEXT NOT NULL CHECK (authority_signature ~ '^[A-Za-z0-9+/]{85}[AQgw]==$'),
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT verification_authorizer_enrolments_key_id_is_the_key CHECK (
        key_id = 'rk:' || left(encode(sha256(decode(public_key, 'base64')), 'hex'), 32)
    ),
    CONSTRAINT verification_authorizer_enrolments_not_self_authorized
        CHECK (authority_actor_id <> actor_id),
    CONSTRAINT verification_authorizer_enrolments_authority_key_is_not_the_key
        CHECK (authority_key_id <> key_id),
    CONSTRAINT verification_authorizer_enrolments_one_key_per_project UNIQUE (project_id, key_id),
    CONSTRAINT verification_authorizer_enrolments_id_project_unique UNIQUE (enrolment_id, project_id)
);

CREATE TABLE IF NOT EXISTS verification_authorizer_revocations (
    revocation_id        TEXT PRIMARY KEY CHECK (btrim(revocation_id) <> ''),
    enrolment_id         TEXT NOT NULL,
    project_id           TEXT NOT NULL,
    -- Authorizations signed before this instant still count; none signed at or after it does,
    -- and none is accepted at all once this row is recorded.
    effective_at         TIMESTAMPTZ NOT NULL,
    reason               TEXT NOT NULL CHECK (btrim(reason) <> ''),
    authority_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),
    authority_key_id     TEXT NOT NULL CHECK (authority_key_id ~ '^rk:[0-9a-f]{32}$'),
    authority_signature  TEXT NOT NULL CHECK (authority_signature ~ '^[A-Za-z0-9+/]{85}[AQgw]==$'),
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT verification_authorizer_revocations_one_per_enrolment UNIQUE (enrolment_id),
    CONSTRAINT verification_authorizer_revocations_enrolment_in_project
        FOREIGN KEY (enrolment_id, project_id)
        REFERENCES verification_authorizer_enrolments (enrolment_id, project_id)
);

CREATE OR REPLACE FUNCTION verification_authorizer_enrolments_are_for_members()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM actors a
          JOIN project_memberships m ON m.actor_id = a.actor_id
         WHERE a.actor_id = NEW.actor_id AND a.actor_type = 'HUMAN' AND a.active
           AND m.project_id = NEW.project_id AND m.active
    ) THEN
        RAISE EXCEPTION
            '% is not an active human member of %, so no authorizer key can be enrolled for them '
            'there', NEW.actor_id, NEW.project_id;
    END IF;
    -- One key, one person -- across both kinds of enrolment.
    IF EXISTS (SELECT 1 FROM verification_authorizer_enrolments
                WHERE key_id = NEW.key_id AND actor_id <> NEW.actor_id)
       OR EXISTS (SELECT 1 FROM warrant_reviewer_enrolments
                   WHERE key_id = NEW.key_id AND actor_id <> NEW.actor_id) THEN
        RAISE EXCEPTION 'key % is already enrolled for another person', NEW.key_id;
    END IF;
    IF EXISTS (SELECT 1 FROM verification_authorizer_enrolments e
                 JOIN verification_authorizer_revocations v ON v.enrolment_id = e.enrolment_id
                WHERE e.key_id = NEW.key_id)
       OR EXISTS (SELECT 1 FROM warrant_reviewer_enrolments e
                    JOIN warrant_reviewer_revocations v ON v.enrolment_id = e.enrolment_id
                   WHERE e.key_id = NEW.key_id) THEN
        RAISE EXCEPTION 'key % was revoked; a revoked key is not enrolled again', NEW.key_id;
    END IF;
    -- An authority's key and a person's key are different keys, everywhere.
    IF EXISTS (SELECT 1 FROM verification_authorizer_enrolments
                WHERE key_id = NEW.authority_key_id OR authority_key_id = NEW.key_id)
       OR EXISTS (SELECT 1 FROM warrant_reviewer_enrolments
                   WHERE key_id = NEW.authority_key_id OR authority_key_id = NEW.key_id) THEN
        RAISE EXCEPTION 'key % or % is used both as a review authority and as a person''s key',
            NEW.key_id, NEW.authority_key_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS verification_authorizer_enrolments_are_for_members
    ON verification_authorizer_enrolments;
CREATE TRIGGER verification_authorizer_enrolments_are_for_members
    BEFORE INSERT ON verification_authorizer_enrolments
    FOR EACH ROW EXECUTE FUNCTION verification_authorizer_enrolments_are_for_members();

DROP TRIGGER IF EXISTS verification_authorizer_enrolments_no_update
    ON verification_authorizer_enrolments;
CREATE TRIGGER verification_authorizer_enrolments_no_update
    BEFORE UPDATE OR DELETE ON verification_authorizer_enrolments
    FOR EACH ROW EXECUTE FUNCTION warrant_reviewer_records_are_append_only();

DROP TRIGGER IF EXISTS verification_authorizer_revocations_no_update
    ON verification_authorizer_revocations;
CREATE TRIGGER verification_authorizer_revocations_no_update
    BEFORE UPDATE OR DELETE ON verification_authorizer_revocations
    FOR EACH ROW EXECUTE FUNCTION warrant_reviewer_records_are_append_only();

-- -- the signed authorization ------------------------------------------------------------------

ALTER TABLE verification_authorizations ADD COLUMN IF NOT EXISTS enrolment_id TEXT;
ALTER TABLE verification_authorizations ADD COLUMN IF NOT EXISTS signature TEXT;
-- The signer's own time, inside the signature. The row's `created_at` stays the database's clock.
ALTER TABLE verification_authorizations ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ;

ALTER TABLE verification_authorizations
    DROP CONSTRAINT IF EXISTS verification_authorizations_signature_is_ed25519;
ALTER TABLE verification_authorizations
    ADD CONSTRAINT verification_authorizations_signature_is_ed25519
    CHECK (signature IS NULL OR signature ~ '^[A-Za-z0-9+/]{85}[AQgw]==$');

ALTER TABLE verification_authorizations
    DROP CONSTRAINT IF EXISTS verification_authorizations_enrolment_in_project;
ALTER TABLE verification_authorizations
    ADD CONSTRAINT verification_authorizations_enrolment_in_project
    FOREIGN KEY (enrolment_id, project_id)
    REFERENCES verification_authorizer_enrolments (enrolment_id, project_id);

-- How far the signer's clock may run ahead of the database's.
CREATE OR REPLACE FUNCTION verification_authorization_clock_skew() RETURNS INTERVAL
    LANGUAGE sql IMMUTABLE AS $$ SELECT interval '2 minutes' $$;

CREATE OR REPLACE FUNCTION verification_authorization_is_signed() RETURNS TRIGGER AS $$
DECLARE
    v_enrolment verification_authorizer_enrolments%ROWTYPE;
    v_hypothesis_created TIMESTAMPTZ;
BEGIN
    IF NEW.enrolment_id IS NULL OR NEW.signature IS NULL OR NEW.signed_at IS NULL THEN
        RAISE EXCEPTION
            'authorization % is unsigned. A verification authorization is signed with the '
            'person''s enrolled authorizer key; an actor id alone proves nobody authorized it '
            '(011w)', NEW.authorization_id;
    END IF;
    SELECT * INTO v_enrolment FROM verification_authorizer_enrolments
     WHERE enrolment_id = NEW.enrolment_id AND project_id = NEW.project_id;
    IF NOT FOUND OR v_enrolment.actor_id <> NEW.actor_id THEN
        RAISE EXCEPTION
            'authorization % is signed under enrolment %, which is not %''s authorizer key in %',
            NEW.authorization_id, NEW.enrolment_id, NEW.actor_id, NEW.project_id;
    END IF;
    IF EXISTS (SELECT 1 FROM verification_authorizer_revocations
                WHERE enrolment_id = NEW.enrolment_id) THEN
        RAISE EXCEPTION 'enrolment % is revoked; its key authorizes nothing more',
            NEW.enrolment_id;
    END IF;
    IF NEW.signed_at < v_enrolment.enrolled_at THEN
        RAISE EXCEPTION 'authorization % is signed before enrolment % existed',
            NEW.authorization_id, NEW.enrolment_id;
    END IF;
    IF NEW.signed_at > clock_timestamp() + verification_authorization_clock_skew() THEN
        RAISE EXCEPTION 'authorization % is signed at %, in the future', NEW.authorization_id,
            NEW.signed_at;
    END IF;
    SELECT created_at INTO v_hypothesis_created FROM hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.hypothesis_id;
    IF v_hypothesis_created IS NOT NULL
       AND NEW.signed_at + verification_authorization_clock_skew() < v_hypothesis_created THEN
        RAISE EXCEPTION 'authorization % is signed at %, before hypothesis % existed (%)',
            NEW.authorization_id, NEW.signed_at, NEW.hypothesis_id, v_hypothesis_created;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS verification_authorization_is_signed_trg ON verification_authorizations;
CREATE TRIGGER verification_authorization_is_signed_trg
    BEFORE INSERT ON verification_authorizations
    FOR EACH ROW EXECUTE FUNCTION verification_authorization_is_signed();

-- -- admission: rule (l), with the signed frame --------------------------------------------------

-- 011s's rule (l), unchanged, after one more condition: the authorization is signed under an
-- enrolment of its person in its project, not revoked with effect at or before its signature.
-- -> `unauthorized_verification`
CREATE OR REPLACE FUNCTION prospective_authorization_problem(
    p_conditioned screening_conditioned_hypotheses,
    p_run runs,
    p_prediction_id TEXT,
    p_check_prediction BOOLEAN DEFAULT TRUE
) RETURNS TEXT AS $$
DECLARE
    v_auth    verification_authorizations%ROWTYPE;
    v_bound   TIMESTAMPTZ;
    v_hash    TEXT;
    v_kind    TEXT;
    v_early   TEXT;
BEGIN
    SELECT a.* INTO v_auth
      FROM verification_authorization_jobs b
      JOIN verification_authorizations a ON a.authorization_id = b.authorization_id
     WHERE b.job_id = p_run.job_id;
    IF NOT FOUND THEN
        RETURN format('run %s was not pre-registered: no verification authorization names its '
                      'job %s, so it is not an authorized test of %s, which was proposed after '
                      'screening (011s)', p_run.run_id, p_run.job_id, p_conditioned.hypothesis_id);
    END IF;
    IF v_auth.signature IS NULL OR v_auth.enrolment_id IS NULL OR v_auth.signed_at IS NULL THEN
        RETURN format('run %s: authorization %s is unsigned, so nobody is shown to have '
                      'authorized it (011w)', p_run.run_id, v_auth.authorization_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM verification_authorizer_enrolments e
                    WHERE e.enrolment_id = v_auth.enrolment_id
                      AND e.project_id = v_auth.project_id
                      AND e.actor_id = v_auth.actor_id
                      AND e.enrolled_at <= v_auth.signed_at) THEN
        RETURN format('run %s: authorization %s is not signed under an enrolment of %s in %s '
                      '(011w)', p_run.run_id, v_auth.authorization_id, v_auth.actor_id,
                      v_auth.project_id);
    END IF;
    IF EXISTS (SELECT 1 FROM verification_authorizer_revocations v
                WHERE v.enrolment_id = v_auth.enrolment_id
                  AND v.effective_at <= v_auth.signed_at) THEN
        RETURN format('run %s: authorization %s is signed with a key revoked before it signed '
                      '(011w)', p_run.run_id, v_auth.authorization_id);
    END IF;
    SELECT bound_at INTO v_bound FROM verification_authorization_jobs WHERE job_id = p_run.job_id;
    IF v_auth.project_id <> p_conditioned.project_id
       OR v_auth.hypothesis_id <> p_conditioned.hypothesis_id THEN
        RETURN format('run %s was authorized (%s) as a test of %s, not of %s (011s)',
                      p_run.run_id, v_auth.authorization_id, v_auth.hypothesis_id,
                      p_conditioned.hypothesis_id);
    END IF;
    IF v_auth.capability_id <> p_run.capability_id THEN
        RETURN format('run %s is of %s; its authorization %s licensed %s (011s)',
                      p_run.run_id, p_run.capability_id, v_auth.authorization_id,
                      v_auth.capability_id);
    END IF;
    SELECT declaration_hash, action_type INTO v_hash, v_kind FROM capability_declarations
     WHERE capability_id = p_run.capability_id;
    IF v_hash IS DISTINCT FROM v_auth.declaration_hash THEN
        RETURN format('run %s: authorization %s was made under another declaration of %s (011s)',
                      p_run.run_id, v_auth.authorization_id, p_run.capability_id);
    END IF;
    IF p_check_prediction
       AND (p_prediction_id IS NULL OR NOT (p_prediction_id = ANY (v_auth.prediction_ids))) THEN
        RETURN format('run %s: authorization %s pre-registered predictions %s of %s, not %s; a '
                      'test supports only what it was registered to test (011s)',
                      p_run.run_id, v_auth.authorization_id, v_auth.prediction_ids,
                      p_conditioned.hypothesis_id, coalesce(p_prediction_id, 'an unnamed one'));
    END IF;
    IF p_run.start_time < v_auth.created_at OR p_run.created_at < v_bound THEN
        RETURN format('run %s started at %s, before its authorization %s was made (%s): a test '
                      'authorized after it began is not pre-registered (011s)',
                      p_run.run_id, p_run.start_time, v_auth.authorization_id, v_auth.created_at);
    END IF;
    IF v_kind IN ('MEASUREMENT', 'FABRICATION') THEN
        SELECT a.artifact_id INTO v_early FROM artifacts a
         WHERE a.artifact_id = ANY (p_run.output_artifacts)
           AND (a.captured_at IS NULL OR a.captured_at < v_auth.created_at)
         ORDER BY a.artifact_id LIMIT 1;
        IF v_early IS NOT NULL THEN
            RETURN format('run %s emits %s, whose data was captured before its authorization %s '
                          'was made (%s): not a pre-registered measurement (011s)',
                          p_run.run_id, v_early, v_auth.authorization_id, v_auth.created_at);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;
