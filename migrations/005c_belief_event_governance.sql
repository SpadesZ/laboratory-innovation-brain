-- 005c_belief_event_governance.sql
--
-- EPI-003 / EPI-005 / §6.18 / §8.2.1. Three governance gaps found by audit of P7 (`7acb2e4`).
-- 005a and 005b are applied and are not edited (AGT-004); this migration moves the schema forward.
--
-- WHAT THIS CANNOT DO, STATED FIRST. The audit's first gap is that a stored event carries no proof
-- a policy decision authorised it. §17.13 records `policy_id`/`policy_version` -- which policy
-- *would have* authorised it -- and §8.2.1's `TransitionDecision` has no identity and is not
-- persisted. Below closes every forgery that is *inconsistent* with the cited policy. It cannot
-- close the consistent one, and inventing a durable proof would mean inventing normative
-- semantics, which AGT-015 forbids. Escalated as SPEC-ISSUE-011; residual recorded as risk R-13.

-- ============================================================================================
-- 1. An admission is an explicit, separate path -- not a hole in the transition gate.
-- ============================================================================================
--
-- §17.13 makes `from_state?` optional because a target's first record has no predecessor, and §8's
-- Hypothesis Admission Gate is what assigns that first state. But a `TransitionPolicy` always
-- declares a `from_state`, so before this migration a genesis event could cite *any* policy and
-- the database could not tell an admission from a transition that had quietly dropped its
-- predecessor. That made the one legitimately un-gated write into a general bypass.
--
-- `is_admission` marks the distinction on the policy, so it is registered once and reviewable,
-- rather than inferred per event. It is a column on `transition_policies`, which is this
-- repository's storage for §8.2.1's contract and not a §17 canonical schema, so no schema-drift
-- binding is affected.
ALTER TABLE transition_policies
    ADD COLUMN is_admission BOOLEAN NOT NULL DEFAULT FALSE;

-- An admission policy's `from_state` is a formality -- the event it backs has none -- so the
-- column stays NOT NULL and only `candidate_to_state` is load-bearing for it.
COMMENT ON COLUMN transition_policies.is_admission IS
    'TRUE for §8 Hypothesis-Admission policies, which back only genesis events (from_state IS '
    'NULL). FALSE for §8.2.1 transition policies, which back only non-genesis events. Enforced by '
    'belief_revision_events_match_their_policy.';

-- ============================================================================================
-- 2. An event must record the transition its cited policy actually governs.
-- ============================================================================================
--
-- 005b made the event cite a *registered* policy. It did not check that the policy governs the
-- transition the event records, so `pol:draft-to-admitted@1.0.0` could back an
-- ACTIVE -> SUPPORTED event. A CHECK cannot reach another table, so this is a trigger.
CREATE OR REPLACE FUNCTION belief_revision_events_match_their_policy() RETURNS TRIGGER AS $$
DECLARE
    v_from        TEXT;
    v_to          TEXT;
    v_admission   BOOLEAN;
BEGIN
    SELECT from_state, candidate_to_state, is_admission
      INTO v_from, v_to, v_admission
      FROM transition_policies
     WHERE policy_id = NEW.policy_id AND version = NEW.policy_version;

    IF NOT FOUND THEN
        -- 005b's foreign key already refuses this; kept so the trigger cannot be read as
        -- assuming a row it did not find.
        RAISE EXCEPTION
            'belief_revision_events: policy %@% is not registered', NEW.policy_id,
            NEW.policy_version;
    END IF;

    IF NEW.from_state IS NULL THEN
        IF NOT v_admission THEN
            RAISE EXCEPTION
                'belief_revision_events: event % has no from_state, so it is an admission, but '
                '%@% is a transition policy. §8''s admission gate is a separate path -- a '
                'transition policy may not back a genesis event, or every dropped predecessor '
                'looks like an admission', NEW.event_id, NEW.policy_id, NEW.policy_version;
        END IF;
        IF NEW.to_state <> v_to THEN
            RAISE EXCEPTION
                'belief_revision_events: admission event % records to_state %, but %@% admits to '
                '%', NEW.event_id, NEW.to_state, NEW.policy_id, NEW.policy_version, v_to;
        END IF;
    ELSE
        IF v_admission THEN
            RAISE EXCEPTION
                'belief_revision_events: event % has a from_state, so it is a transition, but '
                '%@% is an admission policy', NEW.event_id, NEW.policy_id, NEW.policy_version;
        END IF;
        IF NEW.from_state <> v_from OR NEW.to_state <> v_to THEN
            RAISE EXCEPTION
                'belief_revision_events: event % records % -> %, but %@% governs % -> %. An event '
                'whose transition is not the one its policy governs was never authorised by it',
                NEW.event_id, NEW.from_state, NEW.to_state, NEW.policy_id, NEW.policy_version,
                v_from, v_to;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER belief_revision_events_match_their_policy
    BEFORE INSERT ON belief_revision_events
    FOR EACH ROW EXECUTE FUNCTION belief_revision_events_match_their_policy();

-- ============================================================================================
-- 3. A cross-project trigger reference becomes unrepresentable, not merely refused.
-- ============================================================================================
--
-- `record_transition` refuses evidence from another project, but that is a Python check and the
-- audit is right that it is not enough: a support script writing SQL is not bound by it. Rather
-- than a trigger, the project is carried *into* the join table and constrained from both sides,
-- so the reference cannot be formed at all.
ALTER TABLE attestations
    ADD CONSTRAINT attestations_identity_within_project UNIQUE (attestation_id, project_id);
ALTER TABLE relation_judgments
    ADD CONSTRAINT relation_judgments_identity_within_project UNIQUE (relation_id, project_id);
ALTER TABLE belief_revision_events
    ADD CONSTRAINT belief_revision_events_identity_within_project UNIQUE (event_id, project_id);

ALTER TABLE belief_revision_event_attestations
    ADD COLUMN project_id TEXT;
ALTER TABLE belief_revision_event_relations
    ADD COLUMN project_id TEXT;

-- Existing rows would have to be back-filled. There are none: `belief_revision_events` is
-- append-only and this migration follows 005a in the same slice, so no deployment has written
-- one. Asserted rather than assumed -- a silent back-fill of a column that decides whether
-- evidence is in scope would be exactly the wrong thing to do quietly.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM belief_revision_event_attestations)
    OR EXISTS (SELECT 1 FROM belief_revision_event_relations) THEN
        RAISE EXCEPTION
            '005c expects no existing belief-event references to back-fill, but some exist. '
            'Back-fill project_id from belief_revision_events deliberately and re-run rather '
            'than letting this migration guess.';
    END IF;
END $$;

ALTER TABLE belief_revision_event_attestations
    ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE belief_revision_event_relations
    ALTER COLUMN project_id SET NOT NULL;

-- Both sides of each reference must agree on the project. The event's project and the evidence's
-- project are now the same column, so "this event cites another project's attestation" is not a
-- row that can exist.
ALTER TABLE belief_revision_event_attestations
    ADD CONSTRAINT belief_revision_event_attestations_event_in_project
        FOREIGN KEY (event_id, project_id)
        REFERENCES belief_revision_events (event_id, project_id),
    ADD CONSTRAINT belief_revision_event_attestations_attestation_in_project
        FOREIGN KEY (attestation_id, project_id)
        REFERENCES attestations (attestation_id, project_id);

ALTER TABLE belief_revision_event_relations
    ADD CONSTRAINT belief_revision_event_relations_event_in_project
        FOREIGN KEY (event_id, project_id)
        REFERENCES belief_revision_events (event_id, project_id),
    ADD CONSTRAINT belief_revision_event_relations_relation_in_project
        FOREIGN KEY (relation_id, project_id)
        REFERENCES relation_judgments (relation_id, project_id);

-- The append function has to write the new column. Redefined here rather than edited in 005a:
-- 005a is applied and checksummed, and `CREATE OR REPLACE FUNCTION` in a later migration is how a
-- function body moves forward without rewriting history.
CREATE OR REPLACE FUNCTION belief_revision_event_append(
    p_event_id                         TEXT,
    p_project_id                       TEXT,
    p_target_type                      TEXT,
    p_target_id                        TEXT,
    p_from_state                       TEXT,
    p_to_state                         TEXT,
    p_attestation_ids                  TEXT[],
    p_relation_ids                     TEXT[],
    p_policy_id                        TEXT,
    p_policy_version                   TEXT,
    p_actor_id                         TEXT,
    p_inference_provenance_id          TEXT,
    p_rationale_artifact_or_record_ref TEXT,
    p_occurred_at                      TIMESTAMPTZ,
    p_trace_id                         TEXT
) RETURNS VOID AS $$
DECLARE
    v_attestations TEXT[] := COALESCE(p_attestation_ids, ARRAY[]::TEXT[]);
    v_relations    TEXT[] := COALESCE(p_relation_ids,    ARRAY[]::TEXT[]);
BEGIN
    IF cardinality(v_attestations) + cardinality(v_relations) = 0 THEN
        RAISE EXCEPTION
            'belief_revision_event_append: event % cites no triggering attestation or relation. '
            '§6.18 replays by skipping events whose triggers were quarantined, so an event with '
            'no triggers survives every rollback and makes it quietly incomplete', p_event_id;
    END IF;

    INSERT INTO belief_revision_events (
        event_id, project_id, target_type, target_id, from_state, to_state,
        policy_id, policy_version, actor_id, inference_provenance_id,
        rationale_artifact_or_record_ref, occurred_at, trace_id
    ) VALUES (
        p_event_id, p_project_id, p_target_type, p_target_id, p_from_state, p_to_state,
        p_policy_id, p_policy_version, p_actor_id, p_inference_provenance_id,
        p_rationale_artifact_or_record_ref, p_occurred_at, p_trace_id
    );

    -- The event's project goes onto every reference, which is what the composite foreign keys
    -- above then check from both sides. A caller cannot pass a different one: there is no
    -- parameter for it.
    INSERT INTO belief_revision_event_attestations (event_id, attestation_id, project_id)
    SELECT p_event_id, ref, p_project_id FROM unnest(v_attestations) AS ref;

    INSERT INTO belief_revision_event_relations (event_id, relation_id, project_id)
    SELECT p_event_id, ref, p_project_id FROM unnest(v_relations) AS ref;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================================
-- 4. An orphan event -- one citing no evidence at all -- cannot be written by raw SQL.
-- ============================================================================================
--
-- The model refuses it and `belief_revision_event_append` refuses it, but a raw INSERT went
-- through. §6.18 replays by *skipping* events whose triggers were quarantined, so an event with no
-- triggers survives every rollback -- it is the one shape that makes a contamination rollback
-- silently incomplete.
--
-- DEFERRED, and that is what makes it work. Under the autocommit connections these stores require,
-- each statement is its own transaction, so:
--
--     raw INSERT INTO belief_revision_events      one statement -> commit with 0 refs -> REFUSED
--     SELECT belief_revision_event_append(...)    one statement, event + refs -> commit -> allowed
--
-- A non-deferred trigger would refuse both, because the event row necessarily exists before its
-- references do.
CREATE OR REPLACE FUNCTION belief_revision_events_cite_evidence() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM belief_revision_event_attestations WHERE event_id = NEW.event_id
        UNION ALL
        SELECT 1 FROM belief_revision_event_relations WHERE event_id = NEW.event_id
    ) THEN
        RAISE EXCEPTION
            'belief_revision_events: event % cites no triggering attestation or relation. §6.18 '
            'replays by skipping events whose triggers were quarantined, so an event with none '
            'survives every rollback and makes the rollback quietly incomplete. Write it with '
            'belief_revision_event_append(), which records the event and its references in one '
            'statement', NEW.event_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER belief_revision_events_cite_evidence
    AFTER INSERT ON belief_revision_events
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION belief_revision_events_cite_evidence();
