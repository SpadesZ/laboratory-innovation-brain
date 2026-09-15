-- 005b_transition_policies.sql
--
-- EPI-005 / §8.2.1. The policies half of Appendix A's 005 slot; 005a took the events half and is
-- applied, so it is not edited (AGT-004).
--
-- WHY THE POLICY IS STORED AT ALL. §8.2.1 calls it a *versioned* policy, and `v3.3-a11` put
-- `(policy_id, policy_version)` on the event so a past decision can be re-run. Both are empty
-- promises if the policy itself is not durable: re-running version 1.0.0 requires 1.0.0 to still
-- exist, unchanged, after 2.0.0 superseded it. So policies are rows keyed on (policy_id, version),
-- and old versions are never edited or removed.
CREATE TABLE transition_policies (
    policy_id       TEXT NOT NULL,
    version         TEXT NOT NULL,
    domain          TEXT,

    from_state      TEXT NOT NULL CHECK (from_state IN (
        'DRAFT', 'ADMITTED', 'ACTIVE', 'SUPPORTED', 'CHALLENGED',
        'CONTRADICTED', 'INCONCLUSIVE', 'EVOLVED', 'SUPERSEDED'
    )),
    candidate_to_state TEXT NOT NULL CHECK (candidate_to_state IN (
        'DRAFT', 'ADMITTED', 'ACTIVE', 'SUPPORTED', 'CHALLENGED',
        'CONTRADICTED', 'INCONCLUSIVE', 'EVOLVED', 'SUPERSEDED'
    )),

    required_relation_types   TEXT[] NOT NULL DEFAULT '{}',
    required_authority_rule   TEXT,
    required_condition_match  TEXT[] NOT NULL DEFAULT '{}',
    min_independent_attestations INTEGER CHECK (min_independent_attestations >= 0),

    -- §6.17 / FIX-6: only WORK is modelled. The others are storable because a policy may declare
    -- them -- `evaluate` then returns NEED_HUMAN_REVIEW rather than pretending to be satisfied,
    -- which is the required behaviour. Forbidding them in the schema would make the rule
    -- untestable instead of enforced.
    independence_basis TEXT CHECK (
        independence_basis IN ('WORK', 'GROUP', 'SAMPLE', 'INSTRUMENT', 'METHOD')
    ),

    blocking_conflict_policy TEXT[] NOT NULL DEFAULT '{}',
    human_gate      BOOLEAN NOT NULL DEFAULT FALSE,
    effective_from  TIMESTAMPTZ,
    supersedes      TEXT,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (policy_id, version),

    -- A policy governing a transition out of a terminal state could authorise an event the event
    -- table would then refuse, so the two agree here rather than disagreeing at write time.
    CONSTRAINT transition_policies_do_not_leave_a_terminal_state
        CHECK (from_state NOT IN ('EVOLVED', 'SUPERSEDED')),
    CONSTRAINT transition_policies_actually_transition
        CHECK (from_state <> candidate_to_state),
    CONSTRAINT transition_policies_do_not_supersede_themselves
        CHECK (supersedes IS NULL OR supersedes <> version)
);

CREATE INDEX transition_policies_governs_idx
    ON transition_policies (from_state, candidate_to_state);

-- A POLICY VERSION IS IMMUTABLE ONCE REGISTERED. This is the same rule as the event log and for
-- the same reason: if 1.0.0 could be edited, re-running it would compare today's rules against
-- yesterday's evidence and call the difference a bug in the record. Superseding is a new row.
CREATE OR REPLACE FUNCTION transition_policies_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'transition_policies is immutable (EPI-005): cannot % %@%. A changed rule is a new '
        'version -- editing one in place makes every event that cites it unreplayable',
        lower(TG_OP), OLD.policy_id, OLD.version;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER transition_policies_no_update
    BEFORE UPDATE ON transition_policies
    FOR EACH ROW EXECUTE FUNCTION transition_policies_are_immutable();

CREATE TRIGGER transition_policies_no_delete
    BEFORE DELETE ON transition_policies
    FOR EACH ROW EXECUTE FUNCTION transition_policies_are_immutable();

-- AND NOW THE POINT OF STORING THEM: an event must cite a policy version that exists.
--
-- Added here rather than in 005a because the policies table did not exist yet. With this, "the
-- event names a policy version nobody registered" stops being a Python-side check and becomes
-- unrepresentable -- which is what Phase C needs in order to refuse an event whose authorisation
-- cannot be re-derived.
ALTER TABLE belief_revision_events
    ADD CONSTRAINT belief_revision_events_cite_a_registered_policy
        FOREIGN KEY (policy_id, policy_version)
        REFERENCES transition_policies (policy_id, version);
