-- 005d — Decision as the durable, re-derivable authorization for a belief transition
--
-- Implements `v3.3-a12` (SPEC-ISSUE-011, maintainer ruling: Option 1 + Option 2 plus
-- re-derivable authorization input). Forward-only: 005a, 005b and 005c are applied and are not
-- touched.
--
-- WHAT 005c COULD NOT DO. 005c made an event prove that its cited policy governs the transition
-- it records. What it could not refuse was the *consistent* forgery: an event naming a real
-- policy and recording exactly the transition that policy governs, for which no evaluation ever
-- happened. There was nothing to compare it against -- `TransitionDecision` had no identity and
-- was never stored. This migration stores it.
--
-- WHY THE SNAPSHOT IS THE LOAD-BEARING COLUMN. A `result = 'ALLOW'` column alone would move the
-- forgery up one level: write the Decision row too. `decision_input_snapshot` closes that,
-- because the row must carry the six inputs of §8.2.1's canonical operator, and those inputs
-- must genuinely evaluate to the stored decision (§17.14.1 re-derivability, checked in Python --
-- see the note on the limits below). Forging an authorization then requires supplying inputs that
-- really do evaluate to ALLOW, which is not a forgery but an authorization.
--
-- WHY THE SNAPSHOT IS TEXT AND NOT JSONB. `input_hash` is verified *here*, by hashing the stored
-- bytes. `jsonb` normalises whitespace, key order and number formatting on input, so a round-trip
-- would not reproduce the bytes Python hashed and the check would have to trust the writer's
-- hash instead of computing it. Storing the canonical serialization as TEXT means the database
-- verifies the binding without agreeing with the writer about anything.
--
-- WHAT THIS MIGRATION STILL CANNOT DO, STATED PLAINLY. Postgres cannot run
-- `TransitionPolicy.evaluate`, so the re-derivation itself (`v3.3-a12` (d)) is enforced in the
-- creation path, not here. What the database does enforce is everything that makes re-derivation
-- meaningful: the authorization exists, it is ALLOW, it belongs to the same
-- project/subject/policy/from→to, its hash binds its inputs, and neither the decision nor the
-- linkage can be edited afterwards. A snapshot that does not re-derive is refused in Python and
-- can never have been written by the supported path.

-- ---------------------------------------------------------------------------------------------
-- 1. The authorization record itself (§17.14.1 `Decision`, decision_type = BELIEF_TRANSITION)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS belief_transition_decisions (
    decision_id              TEXT PRIMARY KEY,
    project_id               TEXT NOT NULL REFERENCES projects (project_id),
    subject_id               TEXT NOT NULL,

    -- §17.14.1 reserves `Decision` for other decision types; this table is only the belief
    -- transition one, and the CHECK keeps a future type from being stored here by accident.
    decision_type            TEXT NOT NULL DEFAULT 'BELIEF_TRANSITION'
                                  CHECK (decision_type = 'BELIEF_TRANSITION'),

    -- §17.14.1's vocabulary, identical to §8.2.1's TransitionDecision.outcome. DENY and the two
    -- NEED_* outcomes are legitimate rows: they record that a transition was considered and
    -- refused. They simply authorise nothing, which the linkage trigger below enforces.
    result                   TEXT NOT NULL
                                  CHECK (result IN ('ALLOW', 'DENY',
                                                    'NEED_MORE_EVIDENCE', 'NEED_HUMAN_REVIEW')),

    policy_id                TEXT NOT NULL,
    policy_version           TEXT NOT NULL,
    from_state               TEXT NOT NULL,
    to_state                 TEXT NOT NULL,

    -- §10.5's comparator by identity and version, never by result. Both or neither: half an
    -- identity cannot locate a comparator, so it is not a record of one.
    authority_policy_id      TEXT,
    authority_policy_version TEXT,
    CONSTRAINT belief_transition_decisions_authority_identity_is_whole
        CHECK ((authority_policy_id IS NULL) = (authority_policy_version IS NULL)),

    -- The canonical serialization of the six inputs, and of the decision they produced.
    decision_input_snapshot  TEXT NOT NULL,
    input_hash               TEXT NOT NULL,
    evaluated_decision       TEXT NOT NULL,

    episode_id               TEXT,
    actor_id                 TEXT REFERENCES actors (actor_id),
    created_at               TIMESTAMPTZ NOT NULL,

    -- The hash is verified against the stored bytes rather than trusted. `sha256`, `convert_to`
    -- and `encode` are all immutable, so this is a legal CHECK and is re-checked on every write.
    CONSTRAINT belief_transition_decisions_input_hash_binds_the_snapshot
        CHECK (input_hash = 'sha256:' ||
               encode(sha256(convert_to(decision_input_snapshot, 'UTF8')), 'hex')),

    -- A transition that revises nothing is not a transition (same rule as §17.13's events).
    CONSTRAINT belief_transition_decisions_change_state
        CHECK (from_state <> to_state),

    -- §8.2.1 keys a policy on (policy_id, version); the authorization must name a registered one.
    CONSTRAINT belief_transition_decisions_policy_fkey
        FOREIGN KEY (policy_id, policy_version)
        REFERENCES transition_policies (policy_id, version),

    -- Lets the event reference this row *with* its project, so a cross-project authorization is
    -- unrepresentable rather than merely rejected -- the same technique 005c used for evidence.
    CONSTRAINT belief_transition_decisions_id_project_unique
        UNIQUE (decision_id, project_id)
);

COMMENT ON TABLE belief_transition_decisions IS
    'v3.3-a12 / SPEC-ISSUE-011: the durable authorization behind a non-genesis '
    'BeliefRevisionEvent. decision_input_snapshot holds the six inputs of TransitionPolicy.'
    'evaluate so the authorization can be recomputed rather than believed.';

COMMENT ON COLUMN belief_transition_decisions.decision_input_snapshot IS
    'Canonical JSON (RFC 8785 profile) of the six §8.2.1 inputs. TEXT, not jsonb: input_hash is '
    'verified by hashing these exact bytes, and jsonb would normalise them.';

CREATE INDEX IF NOT EXISTS belief_transition_decisions_subject_idx
    ON belief_transition_decisions (project_id, subject_id, created_at);

-- ---------------------------------------------------------------------------------------------
-- 2. Append-only. An authorization that can be edited afterwards is not evidence of anything.
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION belief_transition_decisions_are_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'belief_transition_decisions is append-only: % on decision % is refused. A stored '
        'authorization is the record that a transition was evaluated; editing it rewrites the '
        'reason a belief changed, which is what §17.13''s append-only rule exists to prevent',
        TG_OP, COALESCE(OLD.decision_id, NEW.decision_id);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS belief_transition_decisions_no_update ON belief_transition_decisions;
CREATE TRIGGER belief_transition_decisions_no_update
    BEFORE UPDATE OR DELETE ON belief_transition_decisions
    FOR EACH ROW EXECUTE FUNCTION belief_transition_decisions_are_append_only();

-- ---------------------------------------------------------------------------------------------
-- 3. The event's required back-reference (§17.13, `v3.3-a12`)
-- ---------------------------------------------------------------------------------------------

ALTER TABLE belief_revision_events
    ADD COLUMN IF NOT EXISTS authorization_decision_id TEXT;

COMMENT ON COLUMN belief_revision_events.authorization_decision_id IS
    'v3.3-a12: the §17.14.1 Decision that authorised this transition. Required for every '
    'non-genesis event; NULL exactly for genesis, because admission is a separate gate (§8) and '
    'must not borrow transition authority.';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM belief_revision_events
        WHERE from_state IS NOT NULL AND authorization_decision_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'refusing to add the authorization requirement: this database already holds '
            'non-genesis belief_revision_events with no authorization_decision_id. There is no '
            'correct value to back-fill -- inventing one would manufacture the very proof '
            'v3.3-a12 exists to require. Re-create the database from empty instead';
    END IF;
END;
$$;

-- NULL exactly for genesis, present exactly otherwise. Written as an equality between two
-- predicates rather than two separate CHECKs so neither direction can be relaxed alone.
ALTER TABLE belief_revision_events
    DROP CONSTRAINT IF EXISTS belief_revision_events_genesis_has_no_authorization;
ALTER TABLE belief_revision_events
    ADD CONSTRAINT belief_revision_events_genesis_has_no_authorization
    CHECK ((from_state IS NULL) = (authorization_decision_id IS NULL));

-- Composite, so an event cannot cite an authorization belonging to another project.
ALTER TABLE belief_revision_events
    DROP CONSTRAINT IF EXISTS belief_revision_events_authorization_in_project;
ALTER TABLE belief_revision_events
    ADD CONSTRAINT belief_revision_events_authorization_in_project
    FOREIGN KEY (authorization_decision_id, project_id)
    REFERENCES belief_transition_decisions (decision_id, project_id);

-- ---------------------------------------------------------------------------------------------
-- 4. The linkage check: the authorization must actually cover *this* transition, and allow it
-- ---------------------------------------------------------------------------------------------
--
-- Named `..._require_authorization` deliberately: BEFORE INSERT row triggers fire in name order,
-- so 005c's `..._match_their_policy` still reports a policy mismatch first. Attribution stays
-- where it was rather than every refusal collapsing into this one message.

CREATE OR REPLACE FUNCTION belief_revision_events_require_authorization()
RETURNS TRIGGER AS $$
DECLARE
    v_decision belief_transition_decisions;
BEGIN
    IF NEW.from_state IS NULL THEN
        RETURN NEW;   -- genesis: §8's admission gate, checked by 005c's admission pairing
    END IF;

    IF NEW.authorization_decision_id IS NULL THEN
        -- The CHECK below would also refuse this, but a BEFORE INSERT trigger runs first and a
        -- constraint name is not an explanation. This is the headline case of `v3.3-a12`:
        -- everything legal except that nothing ever authorised it.
        RAISE EXCEPTION
            'belief_revision_events: event % records % -> % with no authorization_decision_id. '
            'v3.3-a12 requires every non-genesis event to name a stored BELIEF_TRANSITION '
            'Decision with result=ALLOW; a legal policy, a legal transition and legal evidence '
            'are not an authorization, and before this the difference was unrepresentable',
            NEW.event_id, NEW.from_state, NEW.to_state;
    END IF;

    SELECT * INTO v_decision
    FROM belief_transition_decisions
    WHERE decision_id = NEW.authorization_decision_id;

    IF NOT FOUND THEN
        -- The foreign key would also catch this; the trigger says it in language an operator can
        -- act on, and fires whether or not the FK is deferred.
        RAISE EXCEPTION
            'belief_revision_events: event % cites authorization %, which does not exist. '
            'v3.3-a12 requires every non-genesis event to name a stored BELIEF_TRANSITION '
            'Decision -- naming a policy only says which policy would have authorised this',
            NEW.event_id, NEW.authorization_decision_id;
    END IF;

    IF v_decision.result <> 'ALLOW' THEN
        RAISE EXCEPTION
            'belief_revision_events: event % is backed by authorization %, whose result is %. '
            'Only ALLOW authorises; the other three outcomes record that the transition was '
            'refused, and writing the event anyway is the bypass EPI-005 forbids',
            NEW.event_id, v_decision.decision_id, v_decision.result;
    END IF;

    IF v_decision.project_id <> NEW.project_id OR v_decision.subject_id <> NEW.target_id THEN
        RAISE EXCEPTION
            'belief_revision_events: event % is % in %, but authorization % covers % in %. '
            'An ALLOW is for one subject in one project and does not transfer',
            NEW.event_id, NEW.target_id, NEW.project_id,
            v_decision.decision_id, v_decision.subject_id, v_decision.project_id;
    END IF;

    IF v_decision.policy_id <> NEW.policy_id
       OR v_decision.policy_version <> NEW.policy_version THEN
        RAISE EXCEPTION
            'belief_revision_events: event % cites policy %@% but authorization % was computed '
            'under %@%. §8.2.1''s determinism guarantee holds within one policy version and says '
            'nothing across two, so the ALLOW does not carry over',
            NEW.event_id, NEW.policy_id, NEW.policy_version,
            v_decision.decision_id, v_decision.policy_id, v_decision.policy_version;
    END IF;

    IF v_decision.from_state <> NEW.from_state OR v_decision.to_state <> NEW.to_state THEN
        RAISE EXCEPTION
            'belief_revision_events: event % records % -> % but authorization % covers % -> %',
            NEW.event_id, NEW.from_state, NEW.to_state,
            v_decision.decision_id, v_decision.from_state, v_decision.to_state;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS belief_revision_events_require_authorization ON belief_revision_events;
CREATE TRIGGER belief_revision_events_require_authorization
    BEFORE INSERT ON belief_revision_events
    FOR EACH ROW EXECUTE FUNCTION belief_revision_events_require_authorization();

-- ---------------------------------------------------------------------------------------------
-- 5. Atomic append, now carrying the authorization
-- ---------------------------------------------------------------------------------------------
--
-- Still one statement, so the DEFERRED evidence trigger 005c installed is satisfied at commit
-- and the event/reference/authorization linkage lands together or not at all.
--
-- The 15-argument signature is dropped rather than left beside the new one. Adding the parameter
-- with a DEFAULT created a second overload instead of replacing the first, and every existing
-- 15-argument call then failed with `AmbiguousFunction` -- caught by the integration suite, not
-- by review. The new parameter is therefore required: an append whose authorization was forgotten
-- should not silently become a genesis event.

DROP FUNCTION IF EXISTS belief_revision_event_append(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], TEXT[], TEXT, TEXT, TEXT, TEXT, TEXT,
    TIMESTAMPTZ, TEXT
);

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
    p_trace_id                         TEXT,
    p_authorization_decision_id        TEXT
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
        policy_id, policy_version, authorization_decision_id, actor_id,
        inference_provenance_id, rationale_artifact_or_record_ref, occurred_at, trace_id
    ) VALUES (
        p_event_id, p_project_id, p_target_type, p_target_id, p_from_state, p_to_state,
        p_policy_id, p_policy_version, p_authorization_decision_id, p_actor_id,
        p_inference_provenance_id, p_rationale_artifact_or_record_ref, p_occurred_at, p_trace_id
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
