-- 012p_causal_warrant_gate_v1_1.sql
--
-- Causal Warrant Gate V1.1: verifiable reviewers, the confirmation rule for every writer, and a
-- recorded flag on the one false confirmation the deployment holds.
--
-- WHY. The V1 audit left four gaps this migration closes in the database:
--
--   1. The answering actor was a parameter. `diagnostic_warrant_resolve(..., 'act:pi', ...)` from
--      any connection answered as the PI. An answer is now signed with an Ed25519 key enrolled for
--      that person in that project by a review authority, and the row records the enrolment and
--      the signature. SQL cannot verify Ed25519; it checks everything around it (the enrolment
--      exists, is that person's, is not revoked, predates the answer). The signature itself is
--      verified every time the answer is counted (`lab_brain.security.reviewer_identity`), against
--      authority keys pinned OUTSIDE the database -- so a database writer can write an enrolment
--      or an answer row, and neither will verify.
--   2. A CONFIRMED failure analysis written directly was checked for warrant references, not for
--      the confirmation rule. `confirmation_rule_breaches` evaluates the rule the loop applies
--      (`VerificationLoop.standing`) over the recorded evidence, and a CONFIRMED row is refused
--      unless it holds. It needs the domain's declarations, so registered declaration sets are
--      stored here, append-only, by version.
--   3. (No SQL needed: the review-queue command and the expiry sweep are in Python.)
--   4. `fan:30d9407f` is CONFIRMED on record and wrong. It stays as written; an append-only flag,
--      bound to the row's exact content, says so wherever it is read.
--
-- HISTORY IS NOT REWRITTEN. No existing row changes. Grants written before this migration carry
-- no signature; they never verify, so they count as no answer (fail closed). The deployment holds
-- none: V1 was never deployed.

-- ---------------------------------------------------------------------------------------------
-- 1. Reviewer keys, enrolled by an authority
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS warrant_reviewer_enrolments (
    enrolment_id         TEXT PRIMARY KEY CHECK (btrim(enrolment_id) <> ''),
    project_id           TEXT NOT NULL REFERENCES projects (project_id),
    actor_id             TEXT NOT NULL REFERENCES actors (actor_id),
    -- Raw Ed25519 public key, canonical base64 (32 bytes: the last character carries two zero
    -- padding bits), so one key has one spelling.
    public_key           TEXT NOT NULL CHECK (public_key ~ '^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$'),
    key_id               TEXT NOT NULL,
    scope                TEXT NOT NULL CHECK (scope = 'DIAGNOSTIC_WARRANT'),
    enrolled_at          TIMESTAMPTZ NOT NULL,
    authority_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),
    authority_key_id     TEXT NOT NULL CHECK (authority_key_id ~ '^rk:[0-9a-f]{32}$'),
    -- Ed25519 signature, base64 (64 bytes), over `core.models.reviewer.enrolment_statement`.
    authority_signature  TEXT NOT NULL CHECK (authority_signature ~ '^[A-Za-z0-9+/]{85}[AQgw]==$'),
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT warrant_reviewer_enrolments_key_id_is_the_key CHECK (
        key_id = 'rk:' || left(encode(sha256(decode(public_key, 'base64')), 'hex'), 32)
    ),
    -- Independent authorization: nobody enrols their own key.
    CONSTRAINT warrant_reviewer_enrolments_not_self_authorized
        CHECK (authority_actor_id <> actor_id),
    CONSTRAINT warrant_reviewer_enrolments_authority_key_is_not_the_reviewer_key
        CHECK (authority_key_id <> key_id),
    CONSTRAINT warrant_reviewer_enrolments_one_key_per_project UNIQUE (project_id, key_id),
    CONSTRAINT warrant_reviewer_enrolments_id_project_unique UNIQUE (enrolment_id, project_id)
);

COMMENT ON TABLE warrant_reviewer_enrolments IS
    'Causal Warrant Gate V1.1 (012p): a review authority''s signed statement that a public key '
    'answers DIAGNOSTIC_WARRANT reviews for one person in one project. The signature is verified '
    'against authority keys pinned outside the database; a row alone authorises nothing.';

CREATE OR REPLACE FUNCTION warrant_reviewer_enrolments_are_for_members()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM actors a
          JOIN project_memberships m ON m.actor_id = a.actor_id
         WHERE a.actor_id = NEW.actor_id AND a.actor_type = 'HUMAN' AND a.active
           AND m.project_id = NEW.project_id AND m.active
    ) THEN
        RAISE EXCEPTION
            '% is not an active human member of %, so no reviewer key can be enrolled for them '
            'there', NEW.actor_id, NEW.project_id;
    END IF;
    -- One key, one person: a key two people share proves neither of them answered.
    IF EXISTS (
        SELECT 1 FROM warrant_reviewer_enrolments
         WHERE key_id = NEW.key_id AND actor_id <> NEW.actor_id
    ) THEN
        RAISE EXCEPTION 'key % is already enrolled for another person', NEW.key_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM warrant_reviewer_enrolments e
          JOIN warrant_reviewer_revocations v ON v.enrolment_id = e.enrolment_id
         WHERE e.key_id = NEW.key_id
    ) THEN
        RAISE EXCEPTION 'key % was revoked; a revoked key is not enrolled again', NEW.key_id;
    END IF;
    -- An authority's key and a reviewer's key are different keys, everywhere.
    IF EXISTS (
        SELECT 1 FROM warrant_reviewer_enrolments
         WHERE key_id = NEW.authority_key_id OR authority_key_id = NEW.key_id
    ) THEN
        RAISE EXCEPTION
            'key % or % is used both as a review authority and as a reviewer key',
            NEW.key_id, NEW.authority_key_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS warrant_reviewer_revocations (
    revocation_id        TEXT PRIMARY KEY CHECK (btrim(revocation_id) <> ''),
    enrolment_id         TEXT NOT NULL,
    project_id           TEXT NOT NULL,
    -- Answers signed before this instant still count; none signed at or after it does, and none
    -- is accepted at all once this row is recorded.
    effective_at         TIMESTAMPTZ NOT NULL,
    reason               TEXT NOT NULL CHECK (btrim(reason) <> ''),
    authority_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),
    authority_key_id     TEXT NOT NULL CHECK (authority_key_id ~ '^rk:[0-9a-f]{32}$'),
    authority_signature  TEXT NOT NULL CHECK (authority_signature ~ '^[A-Za-z0-9+/]{85}[AQgw]==$'),
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT warrant_reviewer_revocations_one_per_enrolment UNIQUE (enrolment_id),
    CONSTRAINT warrant_reviewer_revocations_enrolment_in_project
        FOREIGN KEY (enrolment_id, project_id)
        REFERENCES warrant_reviewer_enrolments (enrolment_id, project_id)
);

DROP TRIGGER IF EXISTS warrant_reviewer_enrolments_are_for_members
    ON warrant_reviewer_enrolments;
CREATE TRIGGER warrant_reviewer_enrolments_are_for_members
    BEFORE INSERT ON warrant_reviewer_enrolments
    FOR EACH ROW EXECUTE FUNCTION warrant_reviewer_enrolments_are_for_members();

CREATE OR REPLACE FUNCTION warrant_reviewer_records_are_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: a key is revoked by a new revocation, never edited',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS warrant_reviewer_enrolments_no_update ON warrant_reviewer_enrolments;
CREATE TRIGGER warrant_reviewer_enrolments_no_update
    BEFORE UPDATE OR DELETE ON warrant_reviewer_enrolments
    FOR EACH ROW EXECUTE FUNCTION warrant_reviewer_records_are_append_only();

DROP TRIGGER IF EXISTS warrant_reviewer_revocations_no_update ON warrant_reviewer_revocations;
CREATE TRIGGER warrant_reviewer_revocations_no_update
    BEFORE UPDATE OR DELETE ON warrant_reviewer_revocations
    FOR EACH ROW EXECUTE FUNCTION warrant_reviewer_records_are_append_only();

-- ---------------------------------------------------------------------------------------------
-- 2. Signed answers
-- ---------------------------------------------------------------------------------------------

ALTER TABLE diagnostic_warrant_grants ADD COLUMN IF NOT EXISTS enrolment_id TEXT;
ALTER TABLE diagnostic_warrant_grants ADD COLUMN IF NOT EXISTS signature TEXT;

ALTER TABLE diagnostic_warrant_grants
    DROP CONSTRAINT IF EXISTS diagnostic_warrant_grants_signature_is_ed25519;
ALTER TABLE diagnostic_warrant_grants
    ADD CONSTRAINT diagnostic_warrant_grants_signature_is_ed25519
    CHECK (signature IS NULL OR signature ~ '^[A-Za-z0-9+/]{85}[AQgw]==$');

ALTER TABLE diagnostic_warrant_grants
    DROP CONSTRAINT IF EXISTS diagnostic_warrant_grants_enrolment_in_project;
ALTER TABLE diagnostic_warrant_grants
    ADD CONSTRAINT diagnostic_warrant_grants_enrolment_in_project
    FOREIGN KEY (enrolment_id, project_id)
    REFERENCES warrant_reviewer_enrolments (enrolment_id, project_id);

COMMENT ON COLUMN diagnostic_warrant_grants.signature IS
    'Causal Warrant Gate V1.1 (012p): the reviewer''s Ed25519 signature over the answer '
    '(core.models.reviewer.grant_statement), under the key of `enrolment_id`. Required for every '
    'answer written after 012p; verified on every read that counts the answer.';

-- 012o's rules, and V1.1's: every new answer is signed under an unrevoked enrolment of the person
-- named, made after that enrolment and after the question was asked.
CREATE OR REPLACE FUNCTION diagnostic_warrant_grants_match_their_review()
RETURNS TRIGGER AS $$
DECLARE
    v_review    review_items%ROWTYPE;
    v_relation  relation_judgments%ROWTYPE;
    v_author    TEXT;
    v_enrolment warrant_reviewer_enrolments%ROWTYPE;
BEGIN
    SELECT * INTO v_review FROM review_items
     WHERE review_id = NEW.review_id AND project_id = NEW.project_id;
    IF NOT FOUND OR v_review.subject_type <> 'DIAGNOSTIC_WARRANT' THEN
        RAISE EXCEPTION 'grant % names %, which is not a DIAGNOSTIC_WARRANT review of %',
            NEW.grant_id, NEW.review_id, NEW.project_id;
    END IF;
    IF v_review.subject_id <> NEW.relation_id THEN
        RAISE EXCEPTION 'grant % is for relation % but review % asked about %',
            NEW.grant_id, NEW.relation_id, NEW.review_id, v_review.subject_id;
    END IF;
    SELECT * INTO v_relation FROM relation_judgments
     WHERE relation_id = NEW.relation_id AND project_id = NEW.project_id;
    IF NOT FOUND OR v_relation.relation_type <> NEW.relation_type
       OR v_relation.to_entity_id <> NEW.hypothesis_id
       OR v_relation.attributes ->> 'prediction_id' IS DISTINCT FROM NEW.prediction_id THEN
        RAISE EXCEPTION
            'grant % names relation %, hypothesis % and prediction %, which do not describe one '
            '% relation of %', NEW.grant_id, NEW.relation_id, NEW.hypothesis_id,
            NEW.prediction_id, NEW.relation_type, NEW.project_id;
    END IF;
    IF v_review.status NOT IN ('QUEUED', 'ASSIGNED') THEN
        RAISE EXCEPTION 'review % is already %; a warrant is answered once',
            NEW.review_id, v_review.status;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM actors a
          JOIN project_memberships m ON m.actor_id = a.actor_id
         WHERE a.actor_id = NEW.granted_by_actor_id AND a.actor_type = 'HUMAN' AND a.active
           AND m.project_id = NEW.project_id AND m.active
    ) THEN
        RAISE EXCEPTION
            '% is not an active human member of %, so cannot answer a diagnostic warrant there',
            NEW.granted_by_actor_id, NEW.project_id;
    END IF;
    IF v_relation.actor_id IS NOT NULL AND v_relation.actor_id = NEW.granted_by_actor_id THEN
        RAISE EXCEPTION
            '% ran the episode that recorded % and cannot also warrant what it means; another '
            'member of % answers', NEW.granted_by_actor_id, NEW.relation_id, NEW.project_id;
    END IF;
    SELECT authored_by_actor_id INTO v_author FROM hypotheses
     WHERE hypothesis_id = NEW.hypothesis_id;
    IF v_author IS NOT NULL AND v_author = NEW.granted_by_actor_id THEN
        RAISE EXCEPTION '% authored % and cannot warrant its own claim',
            NEW.granted_by_actor_id, NEW.hypothesis_id;
    END IF;
    -- V1.1. Who answered is what a signature proves, not what a parameter says.
    IF NEW.enrolment_id IS NULL OR NEW.signature IS NULL THEN
        RAISE EXCEPTION
            'grant % is unsigned. An answer is signed with the reviewer''s enrolled key '
            '(`lab-brain review resolve --key`); an actor id alone proves nobody answered (012p)',
            NEW.grant_id;
    END IF;
    SELECT * INTO v_enrolment FROM warrant_reviewer_enrolments
     WHERE enrolment_id = NEW.enrolment_id AND project_id = NEW.project_id;
    IF NOT FOUND OR v_enrolment.actor_id <> NEW.granted_by_actor_id THEN
        RAISE EXCEPTION
            'grant % is signed under enrolment %, which is not %''s reviewer key in %',
            NEW.grant_id, NEW.enrolment_id, NEW.granted_by_actor_id, NEW.project_id;
    END IF;
    IF EXISTS (SELECT 1 FROM warrant_reviewer_revocations WHERE enrolment_id = NEW.enrolment_id)
    THEN
        RAISE EXCEPTION 'enrolment % is revoked; its key answers nothing more', NEW.enrolment_id;
    END IF;
    IF NEW.granted_at < v_enrolment.enrolled_at THEN
        RAISE EXCEPTION 'grant % is dated before enrolment % existed', NEW.grant_id,
            NEW.enrolment_id;
    END IF;
    IF NEW.granted_at < v_review.created_at THEN
        RAISE EXCEPTION 'grant % is dated before review % was asked', NEW.grant_id,
            NEW.review_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The answering path, signed. The unsigned V1 signature of this function is removed: it is the
-- path an impersonation took.
DROP FUNCTION IF EXISTS diagnostic_warrant_resolve(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], TIMESTAMPTZ, TEXT
);

CREATE OR REPLACE FUNCTION diagnostic_warrant_resolve(
    p_resolution_id        TEXT,
    p_grant_id             TEXT,
    p_review_id            TEXT,
    p_project_id           TEXT,
    p_outcome              TEXT,
    p_actor_id             TEXT,
    p_rationale            TEXT,
    p_considered_rival_ids TEXT[],
    p_resolved_at          TIMESTAMPTZ,
    p_enrolment_id         TEXT,
    p_signature            TEXT,
    p_identifies_class_ref TEXT DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_review   review_items%ROWTYPE;
    v_relation relation_judgments%ROWTYPE;
BEGIN
    IF p_outcome NOT IN ('APPROVED', 'REJECTED') THEN
        RAISE EXCEPTION 'a diagnostic warrant is APPROVED or REJECTED by a person, not %', p_outcome;
    END IF;

    SELECT * INTO v_review FROM review_items
     WHERE review_id = p_review_id AND project_id = p_project_id
     FOR UPDATE;
    IF NOT FOUND OR v_review.subject_type <> 'DIAGNOSTIC_WARRANT' THEN
        RAISE EXCEPTION 'review % is not a DIAGNOSTIC_WARRANT review of %', p_review_id, p_project_id;
    END IF;
    IF v_review.status NOT IN ('QUEUED', 'ASSIGNED') THEN
        RAISE EXCEPTION 'review % is already %; a warrant is answered once',
            p_review_id, v_review.status;
    END IF;
    IF v_review.expires_at IS NOT NULL AND v_review.expires_at <= p_resolved_at THEN
        RAISE EXCEPTION 'review % expired at %; an expired question is closed by expiry, not '
            'answered late', p_review_id, v_review.expires_at;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM actors a
          JOIN project_memberships m ON m.actor_id = a.actor_id
         WHERE a.actor_id = p_actor_id AND a.actor_type = 'HUMAN' AND a.active
           AND m.project_id = p_project_id AND m.active
    ) THEN
        RAISE EXCEPTION
            '% is not an active human member of %, so cannot answer a diagnostic warrant there',
            p_actor_id, p_project_id;
    END IF;

    SELECT * INTO v_relation FROM relation_judgments
     WHERE relation_id = v_review.subject_id AND project_id = p_project_id;

    IF v_relation.actor_id IS NOT NULL AND v_relation.actor_id = p_actor_id THEN
        RAISE EXCEPTION
            '% ran the episode that recorded % and cannot also warrant what it means; another '
            'member of % answers', p_actor_id, v_relation.relation_id, p_project_id;
    END IF;

    INSERT INTO diagnostic_warrant_grants (
        grant_id, project_id, review_id, relation_id, relation_type, hypothesis_id,
        prediction_id, verdict, granted_by_actor_id, granted_at, rationale, considered_rival_ids,
        identifies_class_ref, enrolment_id, signature
    ) VALUES (
        p_grant_id, p_project_id, p_review_id, v_relation.relation_id, v_relation.relation_type,
        v_relation.to_entity_id,
        v_relation.attributes ->> 'prediction_id',
        CASE p_outcome WHEN 'APPROVED' THEN 'WARRANTED' ELSE 'NOT_WARRANTED' END,
        p_actor_id, p_resolved_at, p_rationale, COALESCE(p_considered_rival_ids, '{}'),
        p_identifies_class_ref, p_enrolment_id, p_signature
    );

    INSERT INTO review_resolutions (
        resolution_id, review_id, project_id, outcome, resolved_by_actor_id, resolved_at,
        rationale, resolution_event_kind, warrant_grant_id
    ) VALUES (
        p_resolution_id, p_review_id, p_project_id, p_outcome, p_actor_id, p_resolved_at,
        p_rationale, 'WARRANT_GRANT', p_grant_id
    );

    UPDATE review_items
       SET status = p_outcome, decision_ref = p_resolution_id
     WHERE review_id = p_review_id AND project_id = p_project_id;

    RETURN p_grant_id;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- 3. The domain's declarations, as registered
-- ---------------------------------------------------------------------------------------------

-- The confirmation rule reads which declared class a hypothesis is of, which outcome is whose
-- signature, and what a class cannot produce. Those live in the DomainPack (code, digest-pinned);
-- each composition root registers the versions it may cite here, and refuses to run if a row
-- for one of its sets differs from its code (`SqlDeclarationSetStore.ensure`).
CREATE TABLE IF NOT EXISTS diagnostic_declaration_sets (
    set_id         TEXT NOT NULL CHECK (set_id ~ '^[^@#[:space:]]+$'),
    version        TEXT NOT NULL CHECK (version ~ '^[^@#[:space:]]+$'),
    domain         TEXT NOT NULL CHECK (btrim(domain) <> ''),
    digest         TEXT NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
    declarations   JSONB NOT NULL CHECK (
        jsonb_typeof(declarations) = 'array' AND jsonb_array_length(declarations) >= 1
    ),
    -- `set_id@version` of the earlier version this one replaces for new conclusions. The earlier
    -- one stays registered so what was concluded under it re-checks.
    supersedes     TEXT,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (set_id, version)
);

CREATE OR REPLACE FUNCTION diagnostic_declaration_sets_are_well_formed()
RETURNS TRIGGER AS $$
DECLARE
    v_bad TEXT;
BEGIN
    IF NEW.supersedes IS NOT NULL AND (
        NEW.supersedes = NEW.set_id || '@' || NEW.version
        OR NOT EXISTS (
            SELECT 1 FROM diagnostic_declaration_sets
             WHERE set_id || '@' || version = NEW.supersedes AND set_id = NEW.set_id
        )
    ) THEN
        RAISE EXCEPTION 'declaration set %@% supersedes %, which is not an earlier registered '
            'version of %', NEW.set_id, NEW.version, NEW.supersedes, NEW.set_id;
    END IF;
    SELECT d ->> 'class_id' INTO v_bad
      FROM jsonb_array_elements(NEW.declarations) d
     WHERE jsonb_typeof(d) <> 'object'
        OR coalesce(d ->> 'class_id', '') = '' OR coalesce(d ->> 'mechanism', '') = ''
        OR coalesce(d ->> 'observable_ref', '') = '' OR coalesce(d ->> 'outcome_space_id', '') = ''
        OR coalesce(d ->> 'outcome_space_version', '') = ''
        OR coalesce(d ->> 'supports_outcome', '') = ''
        OR jsonb_typeof(d -> 'refutes_outcomes') IS DISTINCT FROM 'array'
        OR jsonb_array_length(d -> 'refutes_outcomes') = 0
        OR (d -> 'refutes_outcomes') ? (d ->> 'supports_outcome')
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'declaration set %@% has a malformed declaration (%)', NEW.set_id,
            NEW.version, coalesce(v_bad, '?');
    END IF;
    -- The model's own rule: class ids, mechanisms and signatures are each unique in a set.
    IF (SELECT count(*) <> count(DISTINCT d ->> 'class_id')
                 OR count(*) <> count(DISTINCT d ->> 'mechanism')
                 OR count(*) <> count(DISTINCT jsonb_build_array(
                        d ->> 'observable_ref', d ->> 'outcome_space_id',
                        d ->> 'outcome_space_version', d ->> 'supports_outcome'))
          FROM jsonb_array_elements(NEW.declarations) d) THEN
        RAISE EXCEPTION 'declaration set %@% declares a class, mechanism or signature twice',
            NEW.set_id, NEW.version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diagnostic_declaration_sets_are_well_formed ON diagnostic_declaration_sets;
CREATE TRIGGER diagnostic_declaration_sets_are_well_formed
    BEFORE INSERT ON diagnostic_declaration_sets
    FOR EACH ROW EXECUTE FUNCTION diagnostic_declaration_sets_are_well_formed();

CREATE OR REPLACE FUNCTION diagnostic_declaration_sets_are_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'diagnostic_declaration_sets is append-only: a changed declaration is a new '
        'version';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diagnostic_declaration_sets_no_update ON diagnostic_declaration_sets;
CREATE TRIGGER diagnostic_declaration_sets_no_update
    BEFORE UPDATE OR DELETE ON diagnostic_declaration_sets
    FOR EACH ROW EXECUTE FUNCTION diagnostic_declaration_sets_are_append_only();

-- One row per declared class. `active`: no registered version supersedes its set version, which
-- is what new conclusions are reasoned under; identity statements may cite any version.
CREATE OR REPLACE VIEW diagnostic_declarations AS
SELECT s.set_id,
       s.version,
       s.set_id || '@' || s.version                                   AS set_ref,
       d ->> 'class_id'                                               AS class_id,
       d ->> 'mechanism'                                              AS mechanism,
       d ->> 'statement'                                              AS statement,
       d ->> 'observable_ref'                                         AS observable_ref,
       d ->> 'outcome_space_id'                                       AS outcome_space_id,
       d ->> 'outcome_space_version'                                  AS outcome_space_version,
       d ->> 'supports_outcome'                                       AS supports_outcome,
       ARRAY(SELECT jsonb_array_elements_text(d -> 'refutes_outcomes')) AS refutes_outcomes,
       NOT EXISTS (
           SELECT 1 FROM diagnostic_declaration_sets x
            WHERE x.supersedes = s.set_id || '@' || s.version
       )                                                              AS active
  FROM diagnostic_declaration_sets s
 CROSS JOIN LATERAL jsonb_array_elements(s.declarations) d;

-- ---------------------------------------------------------------------------------------------
-- 4. The confirmation rule, for every writer
-- ---------------------------------------------------------------------------------------------
--
-- Each function mirrors one piece of the Python rule, named beside it. They read only the
-- records; the differential check in the PostgreSQL suite holds the two to the same verdicts.

-- A hypothesis's current belief state: the latest event, ordered as `history` orders it.
CREATE OR REPLACE FUNCTION cwg_state(p_project TEXT, p_hypothesis TEXT)
RETURNS TEXT AS $$
    SELECT e.to_state FROM belief_revision_events e
     WHERE e.project_id = p_project AND e.target_id = p_hypothesis
     ORDER BY e.occurred_at DESC, e.event_id DESC
     LIMIT 1
$$ LANGUAGE sql STABLE;

-- `DiagnosticDeclaration.binds`: the hypothesis's predictions on the class's observable state the
-- whole declaration -- signature as SUPPORTS, every refuting outcome as CONTRADICTS -- and nothing
-- that disagrees.
CREATE OR REPLACE FUNCTION cwg_binds(
    p_hypothesis TEXT,
    p_observable TEXT,
    p_space      TEXT,
    p_version    TEXT,
    p_supports   TEXT,
    p_refutes    TEXT[]
) RETURNS BOOLEAN AS $$
DECLARE
    v_prediction RECORD;
    v_effect     TEXT;
    v_meaning    TEXT;
    v_declared   TEXT[] := '{}';
BEGIN
    FOR v_prediction IN
        SELECT expected_outcome, relation_effect_if_observed FROM predictions
         WHERE hypothesis_id = p_hypothesis AND observable_ref = p_observable
           AND outcome_space_id = p_space AND outcome_space_version = p_version
    LOOP
        v_meaning := CASE
            WHEN v_prediction.expected_outcome = p_supports THEN 'SUPPORTS'
            WHEN v_prediction.expected_outcome = ANY (p_refutes) THEN 'CONTRADICTS'
        END;
        FOR v_effect IN
            SELECT e ->> 'relation_type'
              FROM jsonb_array_elements(v_prediction.relation_effect_if_observed) e
        LOOP
            IF v_effect IN ('SUPPORTS', 'PREDICTS') AND v_meaning IS DISTINCT FROM 'SUPPORTS' THEN
                RETURN FALSE;
            END IF;
            IF v_effect = 'CONTRADICTS' AND v_meaning IS DISTINCT FROM 'CONTRADICTS' THEN
                RETURN FALSE;
            END IF;
            v_declared := v_declared || (v_prediction.expected_outcome || chr(31) || v_effect);
        END LOOP;
    END LOOP;
    IF NOT ((p_supports || chr(31) || 'SUPPORTS') = ANY (v_declared)) THEN
        RETURN FALSE;
    END IF;
    RETURN NOT EXISTS (
        SELECT 1 FROM unnest(p_refutes) o
         WHERE NOT ((o || chr(31) || 'CONTRADICTS') = ANY (v_declared))
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- `DiagnosticDeclarationSet.bound_class` over the active sets: exact mechanism, whole declaration.
CREATE OR REPLACE FUNCTION cwg_bound_class(p_hypothesis TEXT)
RETURNS TABLE (set_ref TEXT, class_id TEXT) AS $$
    SELECT d.set_ref, d.class_id
      FROM hypotheses h
      JOIN diagnostic_declarations d ON d.active AND d.mechanism = h.mechanism
     WHERE h.hypothesis_id = p_hypothesis
       AND cwg_binds(p_hypothesis, d.observable_ref, d.outcome_space_id,
                     d.outcome_space_version, d.supports_outcome, d.refutes_outcomes)
     ORDER BY d.set_ref, d.class_id
     LIMIT 1
$$ LANGUAGE sql STABLE;

-- `WarrantResolver._observed`'s agreement: every attestation the relation cites records the
-- outcome it claims, of the observation it comes from, in its prediction's space and observable.
CREATE OR REPLACE FUNCTION cwg_relation_agrees(p_relation relation_judgments)
RETURNS BOOLEAN AS $$
DECLARE
    v_prediction  predictions%ROWTYPE;
    v_predicted   BOOLEAN;
    v_attestation RECORD;
    v_observable  TEXT;
BEGIN
    IF cardinality(p_relation.supporting_attestation_ids) = 0 THEN
        RETURN FALSE;
    END IF;
    SELECT * INTO v_prediction FROM predictions
     WHERE prediction_id = p_relation.attributes ->> 'prediction_id'
       AND hypothesis_id = p_relation.to_entity_id;
    v_predicted := FOUND;
    FOR v_attestation IN
        SELECT a.observation_id, a.method FROM attestations a
         WHERE a.project_id = p_relation.project_id
           AND a.attestation_id = ANY (p_relation.supporting_attestation_ids)
    LOOP
        IF v_attestation.method ->> 'outcome' IS NOT NULL
           AND v_attestation.method ->> 'outcome'
               IS DISTINCT FROM p_relation.attributes ->> 'outcome' THEN
            RETURN FALSE;
        END IF;
        IF v_attestation.observation_id IS DISTINCT FROM p_relation.from_entity_id THEN
            RETURN FALSE;
        END IF;
        IF v_predicted AND v_attestation.method ->> 'outcome_space' IS NOT NULL
           AND v_attestation.method ->> 'outcome_space'
               <> v_prediction.outcome_space_id || '@' || v_prediction.outcome_space_version THEN
            RETURN FALSE;
        END IF;
        IF v_predicted AND v_attestation.observation_id IS NOT NULL THEN
            SELECT metric_or_event INTO v_observable FROM observations
             WHERE observation_id = v_attestation.observation_id
               AND project_id = p_relation.project_id;
            IF FOUND AND v_observable <> v_prediction.observable_ref THEN
                RETURN FALSE;
            END IF;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql STABLE;

-- `core.warrant.observed_link`: the (observable, space, version, outcome) a relation records, or
-- NULLs when it does not instantiate its prediction.
CREATE OR REPLACE FUNCTION cwg_observed_link(
    p_relation relation_judgments,
    OUT observable TEXT, OUT space_id TEXT, OUT space_version TEXT, OUT outcome TEXT
) AS $$
DECLARE
    v_prediction predictions%ROWTYPE;
BEGIN
    SELECT * INTO v_prediction FROM predictions
     WHERE prediction_id = p_relation.attributes ->> 'prediction_id'
       AND hypothesis_id = p_relation.to_entity_id;
    IF NOT FOUND
       OR p_relation.attributes ->> 'outcome' IS DISTINCT FROM v_prediction.expected_outcome
       OR (p_relation.attributes ->> 'outcome_space' IS NOT NULL
           AND p_relation.attributes ->> 'outcome_space'
               <> v_prediction.outcome_space_id || '@' || v_prediction.outcome_space_version) THEN
        RETURN;
    END IF;
    observable := v_prediction.observable_ref;
    space_id := v_prediction.outcome_space_id;
    space_version := v_prediction.outcome_space_version;
    outcome := v_prediction.expected_outcome;
END;
$$ LANGUAGE plpgsql STABLE;

-- An answer the gate counts: signed, under the answering person's enrolment, not revoked at its
-- time. The signature itself is verified in Python on every read; here, its frame.
CREATE OR REPLACE FUNCTION cwg_counted_grant(p_relation relation_judgments)
RETURNS diagnostic_warrant_grants AS $$
    SELECT g.*
      FROM diagnostic_warrant_grants g
      JOIN warrant_reviewer_enrolments en
        ON en.enrolment_id = g.enrolment_id AND en.project_id = g.project_id
       AND en.actor_id = g.granted_by_actor_id
     WHERE g.project_id = p_relation.project_id
       AND g.relation_id = p_relation.relation_id
       AND g.hypothesis_id = p_relation.to_entity_id
       AND g.relation_type = p_relation.relation_type
       AND g.prediction_id IS NOT DISTINCT FROM p_relation.attributes ->> 'prediction_id'
       AND g.signature IS NOT NULL
       AND g.granted_at >= en.enrolled_at
       AND NOT EXISTS (
           SELECT 1 FROM warrant_reviewer_revocations v
            WHERE v.enrolment_id = g.enrolment_id AND v.effective_at <= g.granted_at
       )
     LIMIT 1
$$ LANGUAGE sql STABLE;

-- `WarrantResolver.resolve` for one admitted relation: DOMAIN, REVIEW, REFUSED or none, its
-- reference, and the declared class a person said the hypothesis is.
CREATE OR REPLACE FUNCTION cwg_relation_warrant(
    p_relation relation_judgments,
    OUT warrant TEXT, OUT ref TEXT, OUT identifies TEXT
) AS $$
DECLARE
    v_link   RECORD;
    v_bound  RECORD;
    v_decl   RECORD;
    v_grant  diagnostic_warrant_grants%ROWTYPE;
    v_domain BOOLEAN := FALSE;
BEGIN
    IF p_relation.relation_type NOT IN ('SUPPORTS', 'CONTRADICTS')
       OR NOT cwg_relation_agrees(p_relation) THEN
        RETURN;
    END IF;
    SELECT * INTO v_link FROM cwg_observed_link(p_relation);
    SELECT * INTO v_bound FROM cwg_bound_class(p_relation.to_entity_id);
    IF FOUND AND v_link.outcome IS NOT NULL THEN
        SELECT * INTO v_decl FROM diagnostic_declarations
         WHERE set_ref = v_bound.set_ref AND class_id = v_bound.class_id;
        v_domain := (v_link.observable, v_link.space_id, v_link.space_version)
                        = (v_decl.observable_ref, v_decl.outcome_space_id,
                           v_decl.outcome_space_version)
                    AND CASE
                        WHEN v_link.outcome = v_decl.supports_outcome THEN 'SUPPORTS'
                        WHEN v_link.outcome = ANY (v_decl.refutes_outcomes) THEN 'CONTRADICTS'
                    END IS NOT DISTINCT FROM p_relation.relation_type;
    END IF;
    v_grant := cwg_counted_grant(p_relation);
    -- A person's refusal of this link outranks a declaration about the class.
    IF v_grant.grant_id IS NOT NULL AND v_grant.verdict = 'NOT_WARRANTED' THEN
        warrant := 'REFUSED';
        RETURN;
    END IF;
    IF v_domain THEN
        warrant := 'DOMAIN';
        ref := 'dds:' || v_bound.set_ref || '#' || v_bound.class_id;
        RETURN;
    END IF;
    IF v_grant.grant_id IS NOT NULL THEN
        warrant := 'REVIEW';
        ref := v_grant.grant_id;
        IF v_grant.identifies_class_ref IS NOT NULL AND v_link.outcome IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM diagnostic_declarations d
                WHERE 'dds:' || d.set_ref || '#' || d.class_id = v_grant.identifies_class_ref
                  AND (d.observable_ref, d.outcome_space_id, d.outcome_space_version,
                       d.supports_outcome)
                      = (v_link.observable, v_link.space_id, v_link.space_version, v_link.outcome)
           ) THEN
            identifies := v_grant.identifies_class_ref;
        END IF;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;

-- Every admitted SUPPORTS/CONTRADICTS relation of a hypothesis, with its warrant.
CREATE OR REPLACE FUNCTION cwg_evidence(p_project TEXT, p_hypothesis TEXT)
RETURNS TABLE (
    relation_id TEXT, relation_type TEXT, from_entity_id TEXT,
    warrant TEXT, ref TEXT, identifies TEXT
) AS $$
    SELECT r.relation_id, r.relation_type, r.from_entity_id, w.warrant, w.ref, w.identifies
      FROM relation_judgments r
     CROSS JOIN LATERAL cwg_relation_warrant(r) w
     WHERE r.project_id = p_project AND r.to_entity_id = p_hypothesis AND r.valid_to IS NULL
       AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS')
$$ LANGUAGE sql STABLE;

-- `VerificationLoop.standing`'s `bound`: a declared class, by binding or by one person's identity
-- statement, as `class:<id>`; otherwise the hypothesis itself.
CREATE OR REPLACE FUNCTION cwg_member_key(p_project TEXT, p_hypothesis TEXT)
RETURNS TEXT AS $$
DECLARE
    v_class TEXT;
    v_said  TEXT[];
BEGIN
    SELECT class_id INTO v_class FROM cwg_bound_class(p_hypothesis);
    IF FOUND THEN
        RETURN 'class:' || v_class;
    END IF;
    SELECT array_agg(DISTINCT split_part(e.identifies, '#', 2)) INTO v_said
      FROM cwg_evidence(p_project, p_hypothesis) e
     WHERE e.warrant IN ('DOMAIN', 'REVIEW') AND e.identifies IS NOT NULL;
    IF cardinality(v_said) = 1 THEN
        RETURN 'class:' || v_said[1];
    END IF;
    RETURN p_hypothesis;
END;
$$ LANGUAGE plpgsql STABLE;

-- What a CONFIRMED conclusion for `p_candidate` in `p_episode` would breach, or nothing.
CREATE OR REPLACE FUNCTION confirmation_rule_breaches(
    p_project   TEXT,
    p_episode   TEXT,
    p_candidate TEXT
) RETURNS TEXT[] AS $$
DECLARE
    v_set        TEXT;
    v_breaches   TEXT[] := '{}';
    v_members    TEXT[];
    v_states     JSONB := '{}'::jsonb;
    v_keys       JSONB := '{}'::jsonb;
    v_h          TEXT;
    v_supported  TEXT[];
    v_family     TEXT[];
    v_rivals     TEXT[];
    v_excluded   TEXT[];
    v_refuted    TEXT[];
    v_candidate  TEXT;
    v_key        TEXT;
    v_support    TEXT[];
    v_observed   TEXT[];
    v_found      TEXT[];
    v_own        RECORD;
    v_row        RECORD;
BEGIN
    SELECT h.hypothesis_set_id INTO v_set FROM hypotheses h
     WHERE h.project_id = p_project AND h.hypothesis_id = p_candidate;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM hypothesis_sets s
         WHERE s.set_id = v_set AND s.project_id = p_project AND s.episode_id = p_episode
    ) THEN
        RETURN ARRAY[format('%s is not a member of a hypothesis set of %s', p_candidate,
                            p_episode)];
    END IF;
    SELECT array_agg(h.hypothesis_id ORDER BY h.hypothesis_id) INTO v_members
      FROM hypotheses h WHERE h.hypothesis_set_id = v_set AND h.project_id = p_project;
    FOREACH v_h IN ARRAY v_members LOOP
        v_states := v_states || jsonb_build_object(v_h, cwg_state(p_project, v_h));
        v_keys := v_keys || jsonb_build_object(v_h, cwg_member_key(p_project, v_h));
    END LOOP;

    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_supported
      FROM unnest(v_members) m WHERE v_states ->> m = 'SUPPORTED';
    IF cardinality(v_supported) = 0 THEN
        RETURN ARRAY[format('no member of %s is SUPPORTED', v_set)];
    END IF;
    IF (SELECT count(DISTINCT v_keys ->> s) FROM unnest(v_supported) s) > 1 THEN
        RETURN ARRAY[format('%s are SUPPORTED as different mechanisms: competing support',
                            array_to_string(v_supported, ', '))];
    END IF;
    v_candidate := v_supported[1];
    v_key := v_keys ->> v_candidate;
    IF p_candidate <> v_candidate THEN
        v_breaches := v_breaches || format('the rule''s candidate is %s, not %s', v_candidate,
                                           p_candidate);
    END IF;
    SELECT array_agg(m ORDER BY m) INTO v_family
      FROM unnest(v_members) m WHERE v_keys ->> m = v_key;
    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_rivals
      FROM unnest(v_members) m WHERE NOT (m = ANY (v_family));

    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_refuted
      FROM unnest(v_members) m
     WHERE EXISTS (SELECT 1 FROM cwg_evidence(p_project, m) e
                    WHERE e.relation_type = 'CONTRADICTS' AND e.warrant IN ('DOMAIN', 'REVIEW'));
    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_excluded
      FROM unnest(v_refuted) m WHERE v_states ->> m = 'CONTRADICTED';

    -- The candidate's own class holds a warranted refutation.
    SELECT array_agg(m ORDER BY m) INTO v_found FROM unnest(v_family) m WHERE m = ANY (v_refuted);
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('%s -- the candidate''s own class -- hold a warranted '
                                           'refutation', array_to_string(v_found, ', '));
    END IF;

    -- Warranted support, and the observations it rests on.
    SELECT coalesce(array_agg(DISTINCT e.relation_id), '{}'),
           coalesce(array_agg(DISTINCT e.from_entity_id), '{}')
      INTO v_support, v_observed
      FROM unnest(v_family) m
     CROSS JOIN LATERAL cwg_evidence(p_project, m) e
     WHERE v_states ->> m = 'SUPPORTED' AND e.relation_type = 'SUPPORTS'
       AND e.warrant IN ('DOMAIN', 'REVIEW');
    IF cardinality(v_support) = 0 THEN
        v_breaches := v_breaches || format('%s is SUPPORTED on support nobody accountable '
                                           'warranted', v_candidate);
    END IF;

    -- Every outcome the episode observed: its runs' attestations, and what each admitted relation
    -- of a member records. Another declared class's signature among them, or an outcome the
    -- candidate's own class cannot produce, is evidence against a unique confirmation.
    FOR v_row IN
        WITH observed AS (
            SELECT o.observation_id, o.metric_or_event AS observable,
                   left(a.method ->> 'outcome_space',
                        length(a.method ->> 'outcome_space')
                        - strpos(reverse(a.method ->> 'outcome_space'), '@')) AS space_id,
                   right(a.method ->> 'outcome_space',
                         strpos(reverse(a.method ->> 'outcome_space'), '@') - 1) AS space_version,
                   a.method ->> 'outcome' AS outcome
              FROM attestations a
              JOIN observations o ON o.observation_id = a.observation_id
              JOIN runs r ON r.run_id = o.run_id
              JOIN jobs j ON j.job_id = r.job_id
             WHERE a.project_id = p_project AND j.episode_id = p_episode
               AND strpos(coalesce(a.method ->> 'outcome_space', ''), '@') > 0
               AND a.method ->> 'outcome' IS NOT NULL
            UNION
            SELECT r.from_entity_id, l.observable, l.space_id, l.space_version, l.outcome
              FROM unnest(v_members) m
              JOIN relation_judgments r
                ON r.project_id = p_project AND r.to_entity_id = m AND r.valid_to IS NULL
               AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS')
             CROSS JOIN LATERAL cwg_observed_link(r) l
             WHERE l.outcome IS NOT NULL
        )
        SELECT DISTINCT ob.observation_id, ob.outcome, d.class_id, d.mechanism
          FROM observed ob
          JOIN diagnostic_declarations d
            ON d.active
           AND (d.observable_ref, d.outcome_space_id, d.outcome_space_version, d.supports_outcome)
               = (ob.observable, ob.space_id, ob.space_version, ob.outcome)
         WHERE 'class:' || d.class_id IS DISTINCT FROM v_key
         ORDER BY ob.observation_id, d.class_id
    LOOP
        v_breaches := v_breaches || format('%s: the observed %s is the declared signature of '
                                           '''%s'', another mechanism than %s''s', v_row.observation_id,
                                           v_row.outcome, v_row.mechanism, v_candidate);
    END LOOP;
    IF v_key LIKE 'class:%' THEN
        SELECT * INTO v_own FROM diagnostic_declarations
         WHERE active AND class_id = substr(v_key, 7)
         ORDER BY set_ref LIMIT 1;
        IF FOUND THEN
            FOR v_row IN
                WITH observed AS (
                    SELECT o.observation_id, o.metric_or_event AS observable,
                           a.method ->> 'outcome_space' AS space, a.method ->> 'outcome' AS outcome
                      FROM attestations a
                      JOIN observations o ON o.observation_id = a.observation_id
                      JOIN runs r ON r.run_id = o.run_id
                      JOIN jobs j ON j.job_id = r.job_id
                     WHERE a.project_id = p_project AND j.episode_id = p_episode
                    UNION
                    SELECT r.from_entity_id, l.observable, l.space_id || '@' || l.space_version,
                           l.outcome
                      FROM unnest(v_members) m
                      JOIN relation_judgments r
                        ON r.project_id = p_project AND r.to_entity_id = m
                       AND r.valid_to IS NULL
                       AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS')
                     CROSS JOIN LATERAL cwg_observed_link(r) l
                     WHERE l.outcome IS NOT NULL
                )
                SELECT DISTINCT observation_id, outcome FROM observed
                 WHERE observable = v_own.observable_ref
                   AND space = v_own.outcome_space_id || '@' || v_own.outcome_space_version
                   AND outcome = ANY (v_own.refutes_outcomes)
                 ORDER BY observation_id, outcome
            LOOP
                v_breaches := v_breaches || format('%s: the observed %s is an outcome the declared '
                                                   'class ''%s'' cannot produce',
                                                   v_row.observation_id, v_row.outcome,
                                                   v_own.mechanism);
            END LOOP;
        END IF;
    END IF;

    -- A rival affirming the observation the support rests on, unless a warranted refutation
    -- excluded it. Invalidated affirmations count.
    SELECT array_agg(DISTINCT r.to_entity_id ORDER BY r.to_entity_id) INTO v_found
      FROM relation_judgments r
     WHERE r.project_id = p_project AND r.from_entity_id = ANY (v_observed)
       AND r.relation_type IN ('SUPPORTS', 'PREDICTS')
       AND r.to_entity_id = ANY (v_rivals) AND NOT (r.to_entity_id = ANY (v_excluded));
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('%s affirm the observation supporting %s and nothing '
                                           'warranted excludes them', array_to_string(v_found, ', '),
                                           v_candidate);
    END IF;

    -- An unsettled relation a person's answer could turn against the conclusion.
    SELECT array_agg(e.relation_id ORDER BY e.relation_id) INTO v_found
      FROM (
          SELECT e.relation_id FROM unnest(v_rivals) m
           CROSS JOIN LATERAL cwg_evidence(p_project, m) e
           WHERE NOT (m = ANY (v_excluded)) AND e.relation_type = 'SUPPORTS'
             AND e.warrant IS NULL
          UNION
          SELECT e.relation_id FROM unnest(v_family) m
           CROSS JOIN LATERAL cwg_evidence(p_project, m) e
           WHERE e.relation_type = 'CONTRADICTS' AND e.warrant IS NULL
      ) e;
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('a person''s answer on %s could change whether %s is '
                                           'the cause', array_to_string(v_found, ', '), v_candidate);
    END IF;

    -- A rival whose warranted support only an open blocking conflict holds back.
    SELECT array_agg(m ORDER BY m) INTO v_found
      FROM unnest(v_rivals) m
     WHERE NOT (m = ANY (v_excluded)) AND v_states ->> m IS DISTINCT FROM 'SUPPORTED'
       AND EXISTS (SELECT 1 FROM cwg_evidence(p_project, m) e
                    WHERE e.relation_type = 'SUPPORTS' AND e.warrant IN ('DOMAIN', 'REVIEW'))
       AND EXISTS (SELECT 1 FROM conflicts c
                    WHERE c.project_id = p_project AND m = ANY (c.subject_refs) AND c.blocking
                      AND c.resolution_status IN ('OPEN', 'UNDER_REVIEW'));
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('%s hold warranted support blocked only by an open '
                                           'conflict review', array_to_string(v_found, ', '));
    END IF;
    RETURN v_breaches;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION confirmation_rule_breaches(TEXT, TEXT, TEXT) IS
    'Causal Warrant Gate V1.1 (012p): the loop''s confirmation rule (VerificationLoop.standing) '
    'over the recorded evidence. Empty when a CONFIRMED conclusion for the candidate holds.';

-- For every writer: a CONFIRMED analysis holds the rule, lists every member of its set as a
-- candidate, cites only warrants of its support, and records a declared class's member as the
-- class. Named to fire after the trace and warrant-reference checks (BEFORE triggers run in name
-- order), so the more basic refusal is the one reported.
CREATE OR REPLACE FUNCTION failure_analyses_confirmation_holds_the_rule()
RETURNS TRIGGER AS $$
DECLARE
    v_breaches TEXT[];
    v_missing  TEXT[];
    v_key      TEXT;
    v_class    TEXT;
    v_ref      TEXT;
BEGIN
    IF NEW.resolution_status <> 'CONFIRMED' THEN
        RETURN NEW;
    END IF;
    v_breaches := confirmation_rule_breaches(NEW.project_id, NEW.episode_id,
                                             NEW.confirmed_root_cause);
    IF cardinality(v_breaches) > 0 THEN
        RAISE EXCEPTION
            'failure analysis % confirms %, but the confirmation rule does not hold: %',
            NEW.failure_analysis_id, NEW.confirmed_root_cause,
            array_to_string(v_breaches, '; ');
    END IF;
    SELECT coalesce(array_agg(h.hypothesis_id ORDER BY h.hypothesis_id), '{}') INTO v_missing
      FROM hypotheses h
      JOIN hypotheses c ON c.hypothesis_set_id = h.hypothesis_set_id
     WHERE c.hypothesis_id = NEW.confirmed_root_cause AND c.project_id = NEW.project_id
       AND NOT (h.hypothesis_id = ANY (NEW.candidate_causes));
    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'failure analysis % omits rivals % from its candidate causes; a '
            'confirmation is relative to every member of its set', NEW.failure_analysis_id,
            v_missing;
    END IF;
    FOREACH v_ref IN ARRAY NEW.warrant_refs LOOP
        IF NOT EXISTS (
            SELECT 1 FROM cwg_evidence(NEW.project_id, NEW.confirmed_root_cause) e
             WHERE e.relation_type = 'SUPPORTS' AND e.warrant IN ('DOMAIN', 'REVIEW')
               AND e.ref = v_ref
        ) THEN
            RAISE EXCEPTION 'failure analysis % cites %, which is not a current warrant of %''s '
                'support', NEW.failure_analysis_id, v_ref, NEW.confirmed_root_cause;
        END IF;
    END LOOP;
    v_key := cwg_member_key(NEW.project_id, NEW.confirmed_root_cause);
    IF v_key LIKE 'class:%' THEN
        SELECT mechanism INTO v_class FROM diagnostic_declarations
         WHERE active AND class_id = substr(v_key, 7) ORDER BY set_ref LIMIT 1;
        IF FOUND AND NEW.failure_class IS DISTINCT FROM v_class THEN
            RAISE EXCEPTION 'failure analysis % records % as ''%''; a member of the declared '
                'class ''%'' is recorded as that class', NEW.failure_analysis_id,
                NEW.confirmed_root_cause, NEW.failure_class, v_class;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS failure_analyses_with_the_confirmation_rule_trg ON failure_analyses;
CREATE TRIGGER failure_analyses_with_the_confirmation_rule_trg
    BEFORE INSERT ON failure_analyses
    FOR EACH ROW EXECUTE FUNCTION failure_analyses_confirmation_holds_the_rule();

-- ---------------------------------------------------------------------------------------------
-- 5. Flags on recorded conclusions
-- ---------------------------------------------------------------------------------------------

-- A conclusion is append-only, so a wrong one is never edited: it is flagged. The flag names the
-- row's exact content (`failure_analysis_digest`) so it cannot be moved onto another row, and it
-- is read wherever the conclusion is: case memory and the miner skip a flagged analysis, and the
-- episode page shows the flag beside it.
CREATE OR REPLACE FUNCTION failure_analysis_digest(p_analysis failure_analyses)
RETURNS TEXT AS $$
    SELECT 'sha256:' || encode(sha256(convert_to(to_jsonb(p_analysis)::text, 'UTF8')), 'hex')
$$ LANGUAGE sql STABLE;

CREATE TABLE IF NOT EXISTS failure_analysis_flags (
    flag_id              TEXT PRIMARY KEY CHECK (btrim(flag_id) <> ''),
    project_id           TEXT NOT NULL REFERENCES projects (project_id),
    failure_analysis_id  TEXT NOT NULL REFERENCES failure_analyses (failure_analysis_id),
    kind                 TEXT NOT NULL CHECK (kind IN (
                             -- The conclusion is wrong: its recorded cause is not the cause.
                             'FALSE_CONFIRMATION',
                             -- The conclusion may be right but nothing accountable warranted it.
                             'UNWARRANTED_CONFIRMATION')),
    statement            TEXT NOT NULL CHECK (btrim(statement) <> ''),
    evidence_refs        TEXT[] NOT NULL CHECK (cardinality(evidence_refs) >= 1
                                                AND array_position(evidence_refs, NULL) IS NULL),
    analysis_digest      TEXT NOT NULL CHECK (analysis_digest ~ '^sha256:[0-9a-f]{64}$'),
    -- A person (`act:`) or the migration that carried a recorded audit finding (`migration:`).
    recorded_by          TEXT NOT NULL CHECK (recorded_by ~ '^(act|migration):[^[:space:]]+$'),
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT failure_analysis_flags_one_per_kind UNIQUE (failure_analysis_id, kind)
);

COMMENT ON TABLE failure_analysis_flags IS
    'Causal Warrant Gate V1.1 (012p): a recorded statement that a stored conclusion is wrong or '
    'unwarranted, bound to the row''s exact content. Append-only; the conclusion is never edited.';

CREATE OR REPLACE FUNCTION failure_analysis_flags_match_their_analysis()
RETURNS TRIGGER AS $$
DECLARE
    v_analysis failure_analyses%ROWTYPE;
BEGIN
    SELECT * INTO v_analysis FROM failure_analyses
     WHERE failure_analysis_id = NEW.failure_analysis_id;
    IF NOT FOUND OR v_analysis.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'flag % names %, which is not a failure analysis of %', NEW.flag_id,
            NEW.failure_analysis_id, NEW.project_id;
    END IF;
    IF v_analysis.resolution_status <> 'CONFIRMED' THEN
        RAISE EXCEPTION 'flag % names %, which is % -- only a confirmation can be a false one',
            NEW.flag_id, NEW.failure_analysis_id, v_analysis.resolution_status;
    END IF;
    IF failure_analysis_digest(v_analysis) <> NEW.analysis_digest THEN
        RAISE EXCEPTION 'flag % was written for content % of %, which is not what is stored',
            NEW.flag_id, NEW.analysis_digest, NEW.failure_analysis_id;
    END IF;
    IF NEW.recorded_by LIKE 'act:%' AND NOT EXISTS (
        SELECT 1 FROM actors WHERE actor_id = NEW.recorded_by AND actor_type = 'HUMAN' AND active
    ) THEN
        RAISE EXCEPTION 'flag % is recorded by %, who is not an active person', NEW.flag_id,
            NEW.recorded_by;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS failure_analysis_flags_match_their_analysis ON failure_analysis_flags;
CREATE TRIGGER failure_analysis_flags_match_their_analysis
    BEFORE INSERT ON failure_analysis_flags
    FOR EACH ROW EXECUTE FUNCTION failure_analysis_flags_match_their_analysis();

DROP TRIGGER IF EXISTS failure_analysis_flags_are_append_only ON failure_analysis_flags;
CREATE TRIGGER failure_analysis_flags_are_append_only
    BEFORE UPDATE OR DELETE ON failure_analysis_flags
    FOR EACH ROW EXECUTE FUNCTION failure_memory_is_append_only();

-- The recorded false confirmation: `epi:7b56877f` (2026-10-13, `prj:bench-gemini`) CONFIRMED
-- "missing correction artefact" on `sp.normalization_basis = DISAGREES`, an outcome that mechanism
-- cannot produce; the true cause was a taper-inclusive normalization length (1000 um against the
-- drawn 500 um). Flagged only where that exact row exists, as recorded -- a deployment without it
-- gets nothing -- and idempotently, so re-running writes nothing new.
CREATE OR REPLACE FUNCTION flag_known_false_confirmations()
RETURNS INTEGER AS $$
DECLARE
    v_written INTEGER;
BEGIN
    INSERT INTO failure_analysis_flags (
        flag_id, project_id, failure_analysis_id, kind, statement, evidence_refs,
        analysis_digest, recorded_by
    )
    SELECT 'flg:30d9407f-false-confirmation', fa.project_id, fa.failure_analysis_id,
           'FALSE_CONFIRMATION',
           'The confirmed cause is wrong. A model-declared SUPPORTS on '
           || 'sp.normalization_basis = DISAGREES confirmed "missing correction artefact", a '
           || 'mechanism that cannot change the normalization basis. The observed DISAGREES is '
           || 'the declared signature of a length normalization error (taper-inclusive 1000 um '
           || 'against the drawn 500 um), which no hypothesis in the set proposed. Recorded '
           || 'before the Causal Warrant Gate; no accountable source warranted its support.',
           ARRAY[
               'docs/audit/causal-warrant-gate-v1/REPORT.zh-TW.md#1',
               'docs/implementation/causal-warrant-gate-v1.md#1-root-cause',
               'rel:51f1fdc4-e2cb-484f-b39b-fae90313d249',
               'dec:7d6d7411-c9e9-4bbd-80e2-7c81185299e4'
           ],
           failure_analysis_digest(fa), 'migration:012p_causal_warrant_gate_v1_1'
      FROM failure_analyses fa
     WHERE fa.failure_analysis_id = 'fan:30d9407f-f7ad-4b40-af4c-290edd5cc296'
       AND fa.project_id = 'prj:bench-gemini'
       AND fa.episode_id = 'epi:7b56877f-9287-4075-a3c6-9980abab8eef'
       AND fa.confirmed_root_cause = 'hyp:7c899579-5702-4307-b92d-0215496ea6ff'
       AND fa.failure_class = 'missing correction artefact'
       AND fa.resolution_status = 'CONFIRMED'
       AND cardinality(fa.warrant_refs) = 0
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_written = ROW_COUNT;
    RETURN v_written;
END;
$$ LANGUAGE plpgsql;

SELECT flag_known_false_confirmations();
