-- 012o_causal_warrant_gate.sql
--
-- Causal Warrant Gate V1: a SUPPORTS or CONTRADICTS relation moves a belief only when an
-- accountable source other than its author warrants that the observed outcome diagnoses the
-- hypothesis's mechanism.
--
-- WHY. A relation's type is copied from the effect its prediction's author declared
-- (`verification/evidence.py`). For a language-model author that is the model's own claim about
-- what the outcome means for its mechanism. `epi:7b56877f` confirmed a mechanism on an observable
-- it cannot change, and every CONTRADICTED event in the same project rested on a falsifier on that
-- same observable. EPI-002 already refuses a model statement as evidence at the attestation layer;
-- this closes the same door one layer up. The check itself is in `TransitionPolicy` (pure,
-- replayable); this migration stores what it needs and what a person's answer produces:
--
--   1. `transition_policies.diagnostic_warrant_required`  the policy flag; FALSE reproduces
--                                                          every version registered before this
--   2. review subject `DIAGNOSTIC_WARRANT`                 one review per gated relation, in the
--                                                          ONE queue (UX-005), priced by the active
--                                                          queue policy like every other item
--   3. `diagnostic_warrant_grants`                         a person's answer, append-only, scoped
--                                                          to exactly one relation
--   4. closure kind `WARRANT_GRANT`                        how such a review resolves: the grant is
--                                                          its closure record. A BeliefRevisionEvent
--                                                          cannot be -- the transition the grant
--                                                          enables comes after it -- and a
--                                                          GovernanceEvent records that nobody
--                                                          decided (v3.3-a15)
--   5. `failure_analyses.warrant_refs`                     a new CONFIRMED analysis names the
--                                                          warrants behind it
--
-- HISTORY IS NOT REWRITTEN. Existing policies read FALSE, existing analyses carry no warrant refs,
-- and no existing review, resolution or decision changes. Which earlier conclusions may still feed
-- the miner and case memory is decided by reading `warrant_refs`, not by editing rows.

-- ---------------------------------------------------------------------------------------------
-- 1. The policy flag
-- ---------------------------------------------------------------------------------------------

ALTER TABLE transition_policies
    ADD COLUMN IF NOT EXISTS diagnostic_warrant_required BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN transition_policies.diagnostic_warrant_required IS
    'Causal Warrant Gate (012o): a required SUPPORTS or CONTRADICTS counts only with a diagnostic '
    'warrant (DOMAIN declaration or REVIEW grant). FALSE for every version registered before 012o.';

-- ---------------------------------------------------------------------------------------------
-- 2. DIAGNOSTIC_WARRANT review items
-- ---------------------------------------------------------------------------------------------

ALTER TABLE review_items DROP CONSTRAINT review_items_subject_type_check;

ALTER TABLE review_items ADD CONSTRAINT review_items_subject_type_check
    CHECK (subject_type IN (
        'CONFLICT',
        'AUTHORITY_CONFLICT',
        'EXTRACTION_UNCERTAINTY',
        -- 012o. The subject is one SUPPORTS or CONTRADICTS RelationJudgment: one observed
        -- outcome of one prediction of one hypothesis. A reviewer judges a link, never a
        -- hypothesis wholesale.
        'DIAGNOSTIC_WARRANT'
    ));

-- One live question per relation. A refused warrant is an answer, and asking again would spend
-- reviewer capacity to re-open it; an EXPIRED one is not an answer -- nobody decided -- so the
-- relation may be asked about again, or it would block its hypothesis forever.
CREATE UNIQUE INDEX IF NOT EXISTS review_items_one_diagnostic_warrant_per_relation
    ON review_items (project_id, subject_id)
    WHERE subject_type = 'DIAGNOSTIC_WARRANT' AND status <> 'EXPIRED';

CREATE OR REPLACE FUNCTION review_items_warrant_subject_is_a_gated_relation()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.subject_type <> 'DIAGNOSTIC_WARRANT' THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM relation_judgments
         WHERE relation_id = NEW.subject_id
           AND project_id = NEW.project_id
           AND relation_type IN ('SUPPORTS', 'CONTRADICTS')
    ) THEN
        RAISE EXCEPTION
            'review % asks for a diagnostic warrant on %, which is not a SUPPORTS or CONTRADICTS '
            'relation of %. '
            'A warrant is for one observed link; there is nothing else to warrant',
            NEW.review_id, NEW.subject_id, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_items_warrant_subject_is_a_gated_relation ON review_items;
CREATE TRIGGER review_items_warrant_subject_is_a_gated_relation
    BEFORE INSERT ON review_items
    FOR EACH ROW EXECUTE FUNCTION review_items_warrant_subject_is_a_gated_relation();

-- The production enqueue path, mirroring `extraction_review_enqueue`: priced from the active
-- queue policy, never from the caller; idempotent on the RELATION, so a retried episode -- or a
-- later one over the same evidence -- gets the review that already exists, whatever its status.
CREATE OR REPLACE FUNCTION diagnostic_warrant_review_enqueue(
    p_review_id         TEXT,
    p_project_id        TEXT,
    p_relation_id       TEXT,
    p_stakes            TEXT,
    p_reason            TEXT,
    p_trace_id          TEXT,
    p_episode_id        TEXT,
    p_created_at        TIMESTAMPTZ,
    p_estimated_minutes INTEGER
) RETURNS TEXT AS $$
DECLARE
    v_policy   review_queue_policies%ROWTYPE;
    v_existing TEXT;
BEGIN
    IF p_estimated_minutes <= 0 THEN
        RAISE EXCEPTION
            'review % would cost 0 reviewer minutes; 14.4.1 prices human attention from the sum '
            'of these', p_review_id;
    END IF;

    SELECT review_id INTO v_existing
      FROM review_items
     WHERE project_id = p_project_id
       AND subject_type = 'DIAGNOSTIC_WARRANT'
       AND subject_id = p_relation_id
       AND status <> 'EXPIRED';
    IF FOUND THEN
        RETURN v_existing;
    END IF;

    SELECT * INTO v_policy
      FROM review_queue_policies
     WHERE project_id = p_project_id AND active
     ORDER BY effective_from DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'project % has no active review queue policy, so the diagnostic warrant for % cannot be '
            'asked for: it would have no deadline (§14.4). The belief stays where it is',
            p_project_id, p_relation_id;
    END IF;

    INSERT INTO review_items (
        review_id, project_id, subject_type, subject_id, stakes, reason, trace_id, episode_id,
        created_at, queue_policy_id, queue_policy_version, due_at, expires_at, status,
        estimated_human_minutes
    ) VALUES (
        p_review_id, p_project_id, 'DIAGNOSTIC_WARRANT', p_relation_id, p_stakes, p_reason,
        p_trace_id, p_episode_id, p_created_at, v_policy.policy_id, v_policy.version,
        p_created_at + make_interval(mins => v_policy.default_sla_minutes),
        p_created_at + make_interval(mins => v_policy.default_expiry_minutes),
        'QUEUED', p_estimated_minutes
    );
    RETURN p_review_id;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- 3. Grants
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS diagnostic_warrant_grants (
    grant_id              TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL REFERENCES projects (project_id),
    review_id             TEXT NOT NULL,
    relation_id           TEXT NOT NULL,
    relation_type         TEXT NOT NULL CHECK (relation_type IN ('SUPPORTS', 'CONTRADICTS')),
    hypothesis_id         TEXT NOT NULL,
    prediction_id         TEXT NOT NULL,
    verdict               TEXT NOT NULL CHECK (verdict IN ('WARRANTED', 'NOT_WARRANTED')),
    granted_by_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),
    granted_at            TIMESTAMPTZ NOT NULL,
    rationale             TEXT NOT NULL CHECK (btrim(rationale) <> ''),
    considered_rival_ids  TEXT[] NOT NULL DEFAULT '{}'
                          CHECK (array_position(considered_rival_ids, NULL) IS NULL),
    -- The reviewer's explicit statement that the hypothesis IS a declared class (a `dds:` ref):
    -- a model's paraphrase of a catalog mechanism, said to be that mechanism by a person. Only
    -- with a WARRANTED support; the DomainPack re-checks that the class exists and that the
    -- observed outcome is its signature, which SQL cannot.
    identifies_class_ref  TEXT
                          CHECK (identifies_class_ref IS NULL
                                 OR (verdict = 'WARRANTED' AND relation_type = 'SUPPORTS'
                                     AND identifies_class_ref
                                         ~ '^dds:[^@#[:space:]]+@[^@#[:space:]]+#[^@#[:space:]]+$')),
    CONSTRAINT diagnostic_warrant_grants_one_per_review UNIQUE (review_id),
    CONSTRAINT diagnostic_warrant_grants_one_per_relation UNIQUE (project_id, relation_id),
    CONSTRAINT diagnostic_warrant_grants_id_project_unique UNIQUE (grant_id, project_id),
    CONSTRAINT diagnostic_warrant_grants_review_in_project
        FOREIGN KEY (review_id, project_id) REFERENCES review_items (review_id, project_id)
);

COMMENT ON TABLE diagnostic_warrant_grants IS
    'Causal Warrant Gate (012o): a person''s answer to one DIAGNOSTIC_WARRANT review -- whether one '
    'observed outcome bears on one hypothesis''s mechanism as its author declared (SUPPORTS: '
    'produced by it and not its rivals; CONTRADICTS: impossible under it). Scoped to exactly one '
    'relation, never reusable, append-only. NOT_WARRANTED is terminal for that relation.';

-- A grant answers the question its review asked, about the relation the review names, from an
-- accountable person -- for EVERY writer, not only through `diagnostic_warrant_resolve`. A rule
-- held only inside the function is a rule a direct INSERT walks past.
CREATE OR REPLACE FUNCTION diagnostic_warrant_grants_match_their_review()
RETURNS TRIGGER AS $$
DECLARE
    v_review   review_items%ROWTYPE;
    v_relation relation_judgments%ROWTYPE;
    v_author   TEXT;
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
    -- Not the person who ran the episode behind the relation, and not the hypothesis's author:
    -- the warrant exists because the claim's author is not an accountable source for it, and
    -- the actor whose run is being judged is not an independent one.
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
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- A grant exists only as the closure of its review. Checked at commit, because the resolve
-- function writes the grant before the resolution that cites it; a grant inserted on its own --
-- with its review left QUEUED and no resolution -- is refused when its transaction commits.
CREATE OR REPLACE FUNCTION diagnostic_warrant_grants_are_closures()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM review_resolutions r
          JOIN review_items i ON i.review_id = r.review_id AND i.project_id = r.project_id
         WHERE r.warrant_grant_id = NEW.grant_id AND r.project_id = NEW.project_id
           AND r.review_id = NEW.review_id AND r.resolution_event_kind = 'WARRANT_GRANT'
           AND i.status = r.outcome AND i.decision_ref = r.resolution_id
    ) THEN
        RAISE EXCEPTION
            'grant % is not the closure of review %: a warrant is written only by answering the '
            'review, with its resolution, in one statement (diagnostic_warrant_resolve)',
            NEW.grant_id, NEW.review_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diagnostic_warrant_grants_are_closures ON diagnostic_warrant_grants;
CREATE CONSTRAINT TRIGGER diagnostic_warrant_grants_are_closures
    AFTER INSERT ON diagnostic_warrant_grants
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION diagnostic_warrant_grants_are_closures();

-- A relation is what a warrant, a grant and a stored decision all point at, so its content cannot
-- change underneath them. Only an invalidation (`valid_to`, `invalidation_reason`, and the actor
-- who made it) may be written later; anything else is a different relation, and gets a new id.
CREATE OR REPLACE FUNCTION relation_judgments_content_is_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.relation_id, NEW.project_id, NEW.from_entity_id, NEW.to_entity_id, NEW.relation_type,
        NEW.attributes, NEW.supporting_attestation_ids, NEW.condition_match_ref,
        NEW.inference_provenance_id, NEW.valid_from, NEW.created_at)
       IS DISTINCT FROM
       (OLD.relation_id, OLD.project_id, OLD.from_entity_id, OLD.to_entity_id, OLD.relation_type,
        OLD.attributes, OLD.supporting_attestation_ids, OLD.condition_match_ref,
        OLD.inference_provenance_id, OLD.valid_from, OLD.created_at) THEN
        RAISE EXCEPTION
            'relation %''s content is immutable; only an invalidation may be recorded on it',
            OLD.relation_id;
    END IF;
    -- The actor column names who ran the episode while the relation is current -- the person a
    -- warrant must not come from -- and who invalidated it afterwards. It changes only with that.
    IF NEW.actor_id IS DISTINCT FROM OLD.actor_id AND NEW.valid_to IS NULL THEN
        RAISE EXCEPTION
            'relation %''s actor changes only with its invalidation', OLD.relation_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- A relation that names a prediction is the system's record that THIS observation matched THAT
-- prediction. Checked for every writer: the prediction is the target hypothesis's own; the
-- relation's outcome is the one predicted; and each cited attestation records that outcome, of the
-- prediction's observable and outcome space, for the observation the relation comes from, made by a
-- run of the hypothesis's own episode. Otherwise one INSERT could lend another episode's -- or
-- another observable's -- observation to a hypothesis it never tested.
CREATE OR REPLACE FUNCTION relation_judgments_describe_their_observation()
RETURNS TRIGGER AS $$
DECLARE
    v_prediction predictions%ROWTYPE;
    v_episode    TEXT;
    v_attestation TEXT;
    v_found      BOOLEAN;
BEGIN
    IF NEW.relation_type NOT IN ('SUPPORTS', 'CONTRADICTS')
       OR NOT (NEW.attributes ? 'prediction_id') THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_prediction FROM predictions
     WHERE prediction_id = NEW.attributes ->> 'prediction_id';
    IF NOT FOUND OR v_prediction.hypothesis_id <> NEW.to_entity_id THEN
        RAISE EXCEPTION 'relation % names prediction %, which is not a prediction of %',
            NEW.relation_id, NEW.attributes ->> 'prediction_id', NEW.to_entity_id;
    END IF;
    IF NEW.attributes ->> 'outcome' IS DISTINCT FROM v_prediction.expected_outcome THEN
        RAISE EXCEPTION 'relation % records outcome %, but its prediction expected %',
            NEW.relation_id, NEW.attributes ->> 'outcome', v_prediction.expected_outcome;
    END IF;
    SELECT created_in_episode INTO v_episode FROM hypotheses
     WHERE hypothesis_id = NEW.to_entity_id;
    FOREACH v_attestation IN ARRAY NEW.supporting_attestation_ids LOOP
        SELECT EXISTS (
            SELECT 1
              FROM attestations a
              JOIN observations o ON o.observation_id = a.observation_id
              JOIN runs r ON r.run_id = o.run_id
              JOIN jobs j ON j.job_id = r.job_id
             WHERE a.attestation_id = v_attestation
               AND a.observation_id = NEW.from_entity_id
               AND o.metric_or_event = v_prediction.observable_ref
               AND a.method ->> 'outcome_space'
                   = v_prediction.outcome_space_id || '@' || v_prediction.outcome_space_version
               AND a.method ->> 'outcome' = v_prediction.expected_outcome
               AND (v_episode IS NULL OR j.episode_id = v_episode)
        ) INTO v_found;
        IF NOT v_found THEN
            RAISE EXCEPTION
                'relation % cites %, which does not record % of % for observation % in the '
                'episode of %', NEW.relation_id, v_attestation, v_prediction.expected_outcome,
                v_prediction.observable_ref, NEW.from_entity_id, NEW.to_entity_id;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS relation_judgments_describe_their_observation ON relation_judgments;
CREATE TRIGGER relation_judgments_describe_their_observation
    BEFORE INSERT ON relation_judgments
    FOR EACH ROW EXECUTE FUNCTION relation_judgments_describe_their_observation();

DROP TRIGGER IF EXISTS relation_judgments_content_is_immutable ON relation_judgments;
CREATE TRIGGER relation_judgments_content_is_immutable
    BEFORE UPDATE ON relation_judgments
    FOR EACH ROW EXECUTE FUNCTION relation_judgments_content_is_immutable();

DROP TRIGGER IF EXISTS diagnostic_warrant_grants_match_their_review ON diagnostic_warrant_grants;
CREATE TRIGGER diagnostic_warrant_grants_match_their_review
    BEFORE INSERT ON diagnostic_warrant_grants
    FOR EACH ROW EXECUTE FUNCTION diagnostic_warrant_grants_match_their_review();

CREATE OR REPLACE FUNCTION diagnostic_warrant_grants_are_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'diagnostic_warrant_grants is append-only; a grant is a person''s recorded answer';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diagnostic_warrant_grants_no_update ON diagnostic_warrant_grants;
CREATE TRIGGER diagnostic_warrant_grants_no_update
    BEFORE UPDATE OR DELETE ON diagnostic_warrant_grants
    FOR EACH ROW EXECUTE FUNCTION diagnostic_warrant_grants_are_append_only();

-- ---------------------------------------------------------------------------------------------
-- 4. The WARRANT_GRANT closure kind
-- ---------------------------------------------------------------------------------------------

ALTER TABLE review_resolutions ADD COLUMN IF NOT EXISTS warrant_grant_id TEXT;

ALTER TABLE review_resolutions DROP CONSTRAINT IF EXISTS review_resolutions_event_kind_known;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_event_kind_known
    CHECK (resolution_event_kind IN ('BELIEF_REVISION', 'GOVERNANCE', 'WARRANT_GRANT'));

-- Exactly one closure record, and it is the one the kind names.
ALTER TABLE review_resolutions DROP CONSTRAINT IF EXISTS review_resolutions_event_matches_kind;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_event_matches_kind
    CHECK (
        (resolution_event_kind = 'BELIEF_REVISION')
            = (belief_revision_event_id IS NOT NULL AND governance_event_id IS NULL
               AND warrant_grant_id IS NULL)
        AND (resolution_event_kind = 'GOVERNANCE')
            = (governance_event_id IS NOT NULL AND belief_revision_event_id IS NULL
               AND warrant_grant_id IS NULL)
        AND (resolution_event_kind = 'WARRANT_GRANT')
            = (warrant_grant_id IS NOT NULL AND belief_revision_event_id IS NULL
               AND governance_event_id IS NULL)
    );

ALTER TABLE review_resolutions DROP CONSTRAINT IF EXISTS review_resolutions_grant_in_project;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_grant_in_project
    FOREIGN KEY (warrant_grant_id, project_id)
    REFERENCES diagnostic_warrant_grants (grant_id, project_id);

-- A grant is a person's decision: APPROVED (warranted) or REJECTED (not). Nobody deciding is an
-- EXPIRED review closed against a GovernanceEvent, as for every other subject.
ALTER TABLE review_resolutions DROP CONSTRAINT IF EXISTS review_resolutions_grant_is_a_decision;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_grant_is_a_decision
    CHECK (resolution_event_kind <> 'WARRANT_GRANT' OR outcome IN ('APPROVED', 'REJECTED'));

-- The kind and the subject agree, and the grant's verdict is the outcome recorded.
CREATE OR REPLACE FUNCTION review_resolutions_warrant_kind_matches_subject()
RETURNS TRIGGER AS $$
DECLARE
    v_subject TEXT;
    v_grant   diagnostic_warrant_grants%ROWTYPE;
BEGIN
    SELECT subject_type INTO v_subject FROM review_items
     WHERE review_id = NEW.review_id AND project_id = NEW.project_id;
    IF v_subject = 'DIAGNOSTIC_WARRANT'
       AND NEW.resolution_event_kind NOT IN ('WARRANT_GRANT', 'GOVERNANCE') THEN
        RAISE EXCEPTION
            'resolution % closes DIAGNOSTIC_WARRANT review % against a %; such a review closes with '
            'its grant, or expires', NEW.resolution_id, NEW.review_id, NEW.resolution_event_kind;
    END IF;
    IF NEW.resolution_event_kind = 'WARRANT_GRANT' THEN
        IF v_subject IS DISTINCT FROM 'DIAGNOSTIC_WARRANT' THEN
            RAISE EXCEPTION 'resolution % closes % review % with a warrant grant',
                NEW.resolution_id, v_subject, NEW.review_id;
        END IF;
        SELECT * INTO v_grant FROM diagnostic_warrant_grants
         WHERE grant_id = NEW.warrant_grant_id AND project_id = NEW.project_id;
        IF NOT FOUND OR v_grant.review_id <> NEW.review_id THEN
            RAISE EXCEPTION 'resolution % cites grant %, which does not answer review %',
                NEW.resolution_id, NEW.warrant_grant_id, NEW.review_id;
        END IF;
        IF (NEW.outcome = 'APPROVED') <> (v_grant.verdict = 'WARRANTED') THEN
            RAISE EXCEPTION 'resolution % records % but its grant % records %',
                NEW.resolution_id, NEW.outcome, v_grant.grant_id, v_grant.verdict;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_resolutions_warrant_kind_matches_subject ON review_resolutions;
CREATE TRIGGER review_resolutions_warrant_kind_matches_subject
    BEFORE INSERT ON review_resolutions
    FOR EACH ROW EXECUTE FUNCTION review_resolutions_warrant_kind_matches_subject();

-- The one supported way to answer a DIAGNOSTIC_WARRANT review: grant, resolution and terminal
-- review in one statement, so no reader can see a grant without its resolution or a terminal
-- review without its grant. Conditioned on the review still being outstanding, so two concurrent
-- answers produce exactly one.
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

    -- The person answering is a person in this project. Which role may answer is the lab's call;
    -- that it is an accountable member is not.
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

    -- Not the person who ran the episode that produced the relation. The warrant exists because
    -- the claim's author is not an accountable source for it; the actor whose run is being judged
    -- is not an independent one either.
    IF v_relation.actor_id IS NOT NULL AND v_relation.actor_id = p_actor_id THEN
        RAISE EXCEPTION
            '% ran the episode that recorded % and cannot also warrant what it means; another '
            'member of % answers', p_actor_id, v_relation.relation_id, p_project_id;
    END IF;

    INSERT INTO diagnostic_warrant_grants (
        grant_id, project_id, review_id, relation_id, relation_type, hypothesis_id,
        prediction_id, verdict, granted_by_actor_id, granted_at, rationale, considered_rival_ids,
        identifies_class_ref
    ) VALUES (
        p_grant_id, p_project_id, p_review_id, v_relation.relation_id, v_relation.relation_type,
        v_relation.to_entity_id,
        v_relation.attributes ->> 'prediction_id',
        CASE p_outcome WHEN 'APPROVED' THEN 'WARRANTED' ELSE 'NOT_WARRANTED' END,
        p_actor_id, p_resolved_at, p_rationale, COALESCE(p_considered_rival_ids, '{}'),
        p_identifies_class_ref
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

-- A superseded policy version stays registered so every decision recorded under it re-derives; a
-- new event under it is refused, for every writer. Events already stored are not re-inserted.
CREATE OR REPLACE FUNCTION belief_revision_events_not_under_a_superseded_policy()
RETURNS TRIGGER AS $$
DECLARE
    v_successor TEXT;
BEGIN
    SELECT policy_id || '@' || version INTO v_successor FROM transition_policies
     WHERE supersedes = NEW.policy_id || '@' || NEW.policy_version
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION
            'event % cites %@%, which % supersedes; a new transition is authorised under the '
            'version that replaced it', NEW.event_id, NEW.policy_id, NEW.policy_version,
            v_successor;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS belief_revision_events_not_under_a_superseded_policy
    ON belief_revision_events;
CREATE TRIGGER belief_revision_events_not_under_a_superseded_policy
    BEFORE INSERT ON belief_revision_events
    FOR EACH ROW EXECUTE FUNCTION belief_revision_events_not_under_a_superseded_policy();

-- ---------------------------------------------------------------------------------------------
-- 5. What a confirmation rests on
-- ---------------------------------------------------------------------------------------------

ALTER TABLE failure_analyses
    ADD COLUMN IF NOT EXISTS warrant_refs TEXT[] NOT NULL DEFAULT '{}'
    CHECK (array_position(warrant_refs, NULL) IS NULL);

COMMENT ON COLUMN failure_analyses.warrant_refs IS
    'Causal Warrant Gate (012o): the diagnostic warrants (dds:...#class or grant ids) behind a '
    'CONFIRMED cause. Required for a CONFIRMED row written after 012o; empty on earlier rows, '
    'which the miner and case memory therefore no longer read.';

-- For every writer: a new confirmation names its warrants. Rows already stored are not inserted
-- again, so they are untouched; what they may still feed is decided by reading this column.
CREATE OR REPLACE FUNCTION failure_analyses_confirmation_is_warranted()
RETURNS TRIGGER AS $$
DECLARE
    v_ref TEXT;
BEGIN
    IF NEW.resolution_status <> 'CONFIRMED' THEN
        RETURN NEW;
    END IF;
    IF cardinality(NEW.warrant_refs) = 0 THEN
        RAISE EXCEPTION
            'failure analysis % confirms % with no diagnostic warrant. A confirmed cause rests on '
            'support an accountable source warranted, not on a declared effect alone (012o)',
            NEW.failure_analysis_id, NEW.confirmed_root_cause;
    END IF;
    -- Each reference must be one the decision that moved the cause to SUPPORTED recorded for a
    -- SUPPORTS relation -- the snapshot the read path re-checks against the declarations and the
    -- grants. A reference shaped like a warrant but recorded nowhere is not one.
    FOREACH v_ref IN ARRAY NEW.warrant_refs LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM belief_revision_events e
              JOIN belief_transition_decisions d
                ON d.decision_id = e.authorization_decision_id
             CROSS JOIN LATERAL jsonb_array_elements(
                   COALESCE(d.decision_input_snapshot::jsonb -> 'hypothesis' -> 'relation_evidence',
                            '[]'::jsonb)) AS r
             WHERE e.project_id = NEW.project_id
               AND e.target_id = NEW.confirmed_root_cause
               AND e.to_state = 'SUPPORTED'
               AND r ->> 'relation_type' = 'SUPPORTS'
               AND r ->> 'warrant_ref' = v_ref
        ) THEN
            RAISE EXCEPTION
                'failure analysis % cites warrant %, which no decision promoting % recorded for '
                'its support', NEW.failure_analysis_id, v_ref, NEW.confirmed_root_cause;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Named to fire after `failure_analyses_trace_to_execution_trg` (BEFORE triggers run in name
-- order): a confirmation with no execution trace is refused for that, the more basic reason, first.
DROP TRIGGER IF EXISTS failure_analyses_warranted_confirmation_trg ON failure_analyses;
CREATE TRIGGER failure_analyses_warranted_confirmation_trg
    BEFORE INSERT ON failure_analyses
    FOR EACH ROW EXECUTE FUNCTION failure_analyses_confirmation_is_warranted();
