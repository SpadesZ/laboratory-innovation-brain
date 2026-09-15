-- 005a_belief_revision_events.sql
--
-- EPI-003 / §6.18 / §17.13, as amended by `v3.3-a11` (SPEC-ISSUE-010).
--
-- NUMBERING. Appendix A reserves 005 for `005_epistemic_events_transition_policies.sql` -- one
-- migration covering both the epistemic events (EPI-003) and the transition policies (EPI-005).
-- This is the events half only, so it takes the `005a` suffix rather than claiming the whole slot;
-- the policies half lands as `005b`. Same convention as 007a/007b and 010a/010b, and
-- tests/spec/test_migration_numbering.py enforces that a *bare*-numbered migration's slug matches
-- Appendix A exactly -- so claiming `005` here would be wrong, not merely premature.
--
-- WHY THIS TABLE IS THE TRUTH. §6.18: an extractor version turns out to be systematically wrong,
-- its Attestations are quarantined, the events are replayed skipping the quarantined triggers, and
-- the result is a new checkable state. The line that shapes the schema is 「不得靠手改 current
-- status」: if the current status were stored as the truth, that rollback would be a hand edit and
-- nobody could later tell which beliefs were derived and which were asserted.
--
-- NO FOREIGN KEY ON target_id, and the absence is deliberate rather than forgotten. §8.2's
-- lifecycle belongs to `Hypothesis`, which is EPI-001 in M3; an FK to a table that does not exist
-- is not a stricter schema, it is an unapplyable migration. The residual -- an event may name a
-- hypothesis nobody can resolve -- is stated in IMPLEMENTATION_STATUS.md rather than implied by a
-- column that looks checked and is not. Same reasoning as 010a's job_id.
CREATE TABLE belief_revision_events (
    event_id        TEXT PRIMARY KEY,

    -- v3.3-a11. Without this a replay is installation-wide, and "this event cites another
    -- project's evidence" is not a statement the schema can make, let alone refuse (cf. R-7).
    project_id      TEXT NOT NULL REFERENCES projects (project_id),

    target_type     TEXT NOT NULL CHECK (target_type IN ('HYPOTHESIS')),
    target_id       TEXT NOT NULL,

    -- §8.2's lifecycle, exactly. There is no REJECTED: §8.2.1's prose says "SUPPORTED/REJECTED"
    -- but §8.2's diagram -- the normative one -- has CONTRADICTED as the negative terminal.
    -- NULL from_state is §17.13's `from_state?`: a target's first event has no predecessor.
    from_state      TEXT CHECK (from_state IN (
        'DRAFT', 'ADMITTED', 'ACTIVE', 'SUPPORTED', 'CHALLENGED',
        'CONTRADICTED', 'INCONCLUSIVE', 'EVOLVED', 'SUPERSEDED'
    )),
    to_state        TEXT NOT NULL CHECK (to_state IN (
        'DRAFT', 'ADMITTED', 'ACTIVE', 'SUPPORTED', 'CHALLENGED',
        'CONTRADICTED', 'INCONCLUSIVE', 'EVOLVED', 'SUPERSEDED'
    )),

    -- v3.3-a11. §8.2.1 keys a policy on (policy_id, version); a version alone cannot select what
    -- to re-run, and versions are per-policy, so two policies at 1.0.0 would be indistinguishable.
    policy_id       TEXT NOT NULL,
    policy_version  TEXT NOT NULL,

    -- Set when a human authored the revision. §6.18's manual correction is an event like any
    -- other, never an edit to the projection (AGT-009).
    actor_id                          TEXT REFERENCES actors (actor_id),
    inference_provenance_id           TEXT,
    rationale_artifact_or_record_ref  TEXT,

    occurred_at     TIMESTAMPTZ NOT NULL,
    trace_id        TEXT NOT NULL,

    -- A revision that revises nothing replays as a no-op, so a history could be padded with
    -- events that mean nothing and a projection's last_event_id would stop identifying what
    -- produced the state.
    CONSTRAINT belief_revision_events_actually_change_state
        CHECK (from_state IS NULL OR from_state <> to_state),

    -- §8.2 draws EVOLVED and SUPERSEDED as exits. A transition *out* of one would mean a
    -- superseded hypothesis came back, and the replay would produce a state the lifecycle does
    -- not contain.
    CONSTRAINT belief_revision_events_do_not_leave_a_terminal_state
        CHECK (from_state IS NULL OR from_state NOT IN ('EVOLVED', 'SUPERSEDED'))
);

-- Replay is always "this target's history, in order", and quarantine replay is "this project's".
CREATE INDEX belief_revision_events_target_idx
    ON belief_revision_events (target_id, occurred_at, event_id);
CREATE INDEX belief_revision_events_project_idx
    ON belief_revision_events (project_id, occurred_at);
CREATE INDEX belief_revision_events_trace_idx ON belief_revision_events (trace_id);
CREATE INDEX belief_revision_events_policy_idx ON belief_revision_events (policy_id, policy_version);

-- §17.13's two triggering arrays, as joins rather than TEXT[] columns.
--
-- Not a style choice. §6.18's contamination rollback is exactly the query "which events were
-- triggered by an Attestation produced by extractor version X" -- so the references have to be
-- joinable and they have to resolve. An array of TEXT can name an attestation that does not
-- exist, and a trigger reference that resolves to nothing makes the rollback silently incomplete,
-- which is the one failure this requirement exists to prevent. Same argument as 010a's cost refs.
CREATE TABLE belief_revision_event_attestations (
    event_id        TEXT NOT NULL REFERENCES belief_revision_events (event_id),
    attestation_id  TEXT NOT NULL REFERENCES attestations (attestation_id),
    PRIMARY KEY (event_id, attestation_id)
);

CREATE INDEX belief_revision_event_attestations_attestation_idx
    ON belief_revision_event_attestations (attestation_id);

CREATE TABLE belief_revision_event_relations (
    event_id     TEXT NOT NULL REFERENCES belief_revision_events (event_id),
    relation_id  TEXT NOT NULL REFERENCES relation_judgments (relation_id),
    PRIMARY KEY (event_id, relation_id)
);

CREATE INDEX belief_revision_event_relations_relation_idx
    ON belief_revision_event_relations (relation_id);

-- APPEND-ONLY, ENFORCED. The whole design rests on the events being the record, so a path that
-- edits or deletes one is a path that rewrites history -- which is what §6.18 forbids in the
-- sentence 「不得靠手改 current status」.
CREATE OR REPLACE FUNCTION belief_revision_events_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'belief_revision_events is append-only (EPI-003): cannot % %. A correction is a NEW '
        'event, never an edit to an old one -- otherwise nobody can tell later which beliefs '
        'were derived and which were asserted',
        lower(TG_OP), OLD.event_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER belief_revision_events_no_update
    BEFORE UPDATE ON belief_revision_events
    FOR EACH ROW EXECUTE FUNCTION belief_revision_events_are_append_only();

CREATE TRIGGER belief_revision_events_no_delete
    BEFORE DELETE ON belief_revision_events
    FOR EACH ROW EXECUTE FUNCTION belief_revision_events_are_append_only();

-- The trigger references are part of the event, so they are append-only too. Without this an
-- event's citations could be edited after the fact, which is the same rewrite one level down:
-- the event would still say it was authorised by evidence it no longer names.
CREATE OR REPLACE FUNCTION belief_revision_refs_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'belief revision trigger references are append-only (EPI-003): cannot % the references '
        'of event %', lower(TG_OP), OLD.event_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER belief_revision_event_attestations_no_change
    BEFORE UPDATE OR DELETE ON belief_revision_event_attestations
    FOR EACH ROW EXECUTE FUNCTION belief_revision_refs_are_append_only();

CREATE TRIGGER belief_revision_event_relations_no_change
    BEFORE UPDATE OR DELETE ON belief_revision_event_relations
    FOR EACH ROW EXECUTE FUNCTION belief_revision_refs_are_append_only();

-- AN EVENT AND ITS TRIGGER REFERENCES ARE ONE FACT, so they are written by one statement.
--
-- This is the lesson 010b cost: the span close committed its status and then its cost refs
-- separately, and an invalid ref left the two permanently divided. Here it would be worse,
-- because the table is append-only in both directions: a half-written event could never be
-- completed *or* removed. So the append is a single function call, and under the autocommit
-- connection these stores require, the statement's own atomicity is the guarantee.
--
-- It also gives the "at least one trigger" rule a home in the database. A CHECK cannot span the
-- join tables, and a DEFERRABLE constraint trigger would fire at each statement's commit under
-- autocommit -- i.e. before the references exist. Validating inside the one statement that writes
-- all three rows is the only place the rule can actually hold.
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

    INSERT INTO belief_revision_event_attestations (event_id, attestation_id)
    SELECT p_event_id, ref FROM unnest(v_attestations) AS ref;

    INSERT INTO belief_revision_event_relations (event_id, relation_id)
    SELECT p_event_id, ref FROM unnest(v_relations) AS ref;
END;
$$ LANGUAGE plpgsql;
