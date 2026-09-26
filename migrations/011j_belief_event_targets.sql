-- 011j_belief_event_targets.sql
--
-- M3 / EPI-001 -- closes risk R-12. `v3.3-a12` (§17.13): "Genesis 不參與此義務 ... `target_id` 仍無
-- foreign key（R-12），留給 EPI-001/M3". A BeliefRevisionEvent now names a hypothesis that was
-- admitted through §8's gate, in the event's own project, for every writer -- the append functions
-- of `005a`/`005c`/`005d`, `SqlBeliefEventStore`, and raw SQL alike.
--
-- IDENTITY IS (project_id, hypothesis_id), AND THAT IS M0b's RULE, NOT A NEW ONE. M0b's replay keys
-- a history on the pair because "two projects may legitimately use the same hypothesis id"
-- (`core.belief.replay`, `SqlBeliefEventStore.history`); `005e` keyed `hypotheses` on the id alone,
-- which would have made that impossible the moment events had to resolve. So `hypotheses` is
-- re-keyed on the pair before the foreign key is added, and its two dependants follow. A global key
-- would also have been a SEC-002 oracle: project B learning that an id exists in project A by
-- failing to insert it.
--
-- EXISTING HISTORIES. A database carrying events for targets that were never admitted cannot take
-- this constraint, and silently skipping them (`NOT VALID`) would leave exactly the un-gated
-- history R-12 is about. The block below refuses with a count and the remedy instead: admit the
-- targets through `HypothesisAdmissionService` (or restore their certificates), then re-run.
--
-- ADJUDICATION IN SQL. The external-evidence half of §7.6 was held only by `HypothesisBrain` and
-- `HypothesisRevisionGate`; section 4 below holds it for any writer, reading the triggering
-- attestations' recorded types rather than trusting whoever wrote the event.
--
-- "重大 REJECT", MADE PRECISE. `011i` required an independent critique for every REJECT of a
-- certified hypothesis, which was the same thing as every REJECT of a debated one while only
-- debated hypotheses had certificates. Once every target is a certificate, that reading would also
-- demand a debate artifact before M2's hard-locked SIM-002 path may reject on a standard- or
-- validation-fidelity run. M0b's own `critique_gate` models "major" as a property of the REJECT
-- (`is_major_reject`), not as "any REJECT", and §26's SRC-002 row ties the critique path to
-- `stakes >= policy threshold`. So a REJECT is major -- and needs the independent critique -- when
-- it removes a rival from a ROOT-CAUSE set (EPI-001's concern: the conclusion space shrinks) or when
-- the set's stakes reached its SourcePolicy's threshold (`inverted_retrieval_required`). Every set a
-- debate admits is root-cause unless the Supervisor's request says otherwise, so every REJECT the M3
-- review accepted still needs its critique; a routine (non-root-cause, below-threshold) set does not.

DO $$
DECLARE
    v_orphans BIGINT;
BEGIN
    SELECT count(*) INTO v_orphans
      FROM belief_revision_events e
     WHERE NOT EXISTS (
         SELECT 1 FROM hypotheses h
          WHERE h.hypothesis_id = e.target_id AND h.project_id = e.project_id
     );
    IF v_orphans > 0 THEN
        RAISE EXCEPTION
            '011j: % belief revision event(s) target a hypothesis that was never admitted in its '
            'project. R-12 cannot be closed over them: admit those targets through §8''s gate '
            '(HypothesisAdmissionService) or restore their certificates, then re-run migrate.py',
            v_orphans;
    END IF;
END;
$$;

-- 1. Identity on the pair. Dependants first, then the key, then the dependants again.
ALTER TABLE predictions DROP CONSTRAINT predictions_hypothesis_id_fkey;
ALTER TABLE hypotheses DROP CONSTRAINT hypotheses_parent_id_fkey;
ALTER TABLE hypotheses DROP CONSTRAINT hypotheses_pkey;
ALTER TABLE hypotheses ADD CONSTRAINT hypotheses_pkey PRIMARY KEY (project_id, hypothesis_id);
ALTER TABLE predictions
    ADD CONSTRAINT predictions_hypothesis_in_project
    FOREIGN KEY (project_id, hypothesis_id) REFERENCES hypotheses (project_id, hypothesis_id);
ALTER TABLE hypotheses
    ADD CONSTRAINT hypotheses_parent_in_project
    FOREIGN KEY (project_id, parent_id) REFERENCES hypotheses (project_id, hypothesis_id);

-- 2. The belief event names an admitted hypothesis of its own project (R-12).
ALTER TABLE belief_revision_events
    ADD CONSTRAINT belief_revision_events_target_is_an_admitted_hypothesis
    FOREIGN KEY (project_id, target_id) REFERENCES hypotheses (project_id, hypothesis_id);

-- 3. `011i`'s two functions, looked up on the pair. Behaviour is otherwise `011i`'s, except the
-- "not a certificate" early return -- unreachable now, so it states R-12 instead -- and the REJECT
-- rule, scoped to a major REJECT as the header explains.

CREATE OR REPLACE FUNCTION predictions_are_admissible() RETURNS TRIGGER AS $$
DECLARE
    v_space   outcome_spaces%ROWTYPE;
    v_effect  JSONB;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM hypotheses
         WHERE hypothesis_id = NEW.hypothesis_id AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'prediction % in % is bound to hypothesis %, which that project never '
            'admitted', NEW.prediction_id, NEW.project_id, NEW.hypothesis_id;
    END IF;

    SELECT * INTO v_space FROM outcome_spaces
     WHERE outcome_space_id = NEW.outcome_space_id AND version = NEW.outcome_space_version;
    IF NOT (NEW.expected_outcome = ANY (v_space.outcomes)) THEN
        RAISE EXCEPTION
            'prediction % expects %, which is not declared by outcome space %@% (declared: %). '
            'VER-004: a planner MUST NOT invent outcomes, and neither may a prediction',
            NEW.prediction_id, NEW.expected_outcome, NEW.outcome_space_id,
            NEW.outcome_space_version, v_space.outcomes;
    END IF;
    IF NEW.expected_outcome = ANY (v_space.explicit_exclusions) THEN
        RAISE EXCEPTION
            'prediction % expects %, which outcome space %@% explicitly excludes',
            NEW.prediction_id, NEW.expected_outcome, NEW.outcome_space_id,
            NEW.outcome_space_version;
    END IF;

    FOR v_effect IN SELECT * FROM jsonb_array_elements(NEW.relation_effect_if_observed) LOOP
        IF v_effect ->> 'to_entity_id' IS DISTINCT FROM NEW.hypothesis_id THEN
            RAISE EXCEPTION
                'prediction % declares an effect on %, not on its own hypothesis % (§17.5.1)',
                NEW.prediction_id, v_effect ->> 'to_entity_id', NEW.hypothesis_id;
        END IF;
        IF NOT (v_effect ->> 'relation_type' = ANY (
            ARRAY['SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS'])) THEN
            RAISE EXCEPTION
                'prediction % declares effect type %; §17.5.1 admits SUPPORTS | CONTRADICTS | '
                'TESTS | PREDICTS', NEW.prediction_id, v_effect ->> 'relation_type';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM belief_revision_events e
         WHERE e.target_id = NEW.hypothesis_id AND e.project_id = NEW.project_id
           AND e.from_state IS NULL
    ) THEN
        RAISE EXCEPTION
            'hypothesis % is already admitted; a prediction cannot be added to the certificate '
            'afterwards. What was admitted is what was admitted -- revise by EVOLVING it',
            NEW.hypothesis_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION hypothesis_revisions_meet_m3_preconditions() RETURNS TRIGGER AS $$
DECLARE
    v_hyp       hypotheses%ROWTYPE;
    v_set       hypothesis_sets%ROWTYPE;
    v_admitted  INTEGER;
BEGIN
    SELECT * INTO v_hyp FROM hypotheses
     WHERE hypothesis_id = NEW.target_id AND project_id = NEW.project_id;
    IF NOT FOUND THEN
        -- Said here, before the foreign key speaks, so the refusal names the rule.
        RAISE EXCEPTION
            'event % targets hypothesis % in %, which was never admitted there. R-12 / EPI-001: a '
            'belief event names a hypothesis admitted through §8''s gate (a certificate with its '
            'predictions), in the event''s own project', NEW.event_id, NEW.target_id,
            NEW.project_id;
    END IF;
    SELECT * INTO v_set FROM hypothesis_sets WHERE set_id = v_hyp.hypothesis_set_id;

    IF NEW.from_state IS NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM predictions p
             WHERE p.hypothesis_id = NEW.target_id AND p.project_id = NEW.project_id
        ) THEN
            RAISE EXCEPTION
                'hypothesis % cannot be admitted: its certificate has no typed Prediction. §8 '
                'admits a hypothesis only with mechanism, prediction, falsifier, assumptions, '
                'confounders and minimum test; without a prediction it is an idea (EPI-001)',
                NEW.target_id;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.to_state = 'SUPPORTED' AND v_set.root_cause THEN
        SELECT count(DISTINCT h.hypothesis_id) INTO v_admitted
          FROM hypotheses h
          JOIN belief_revision_events e
            ON e.target_id = h.hypothesis_id AND e.project_id = h.project_id
           AND e.from_state IS NULL
         WHERE h.hypothesis_set_id = v_set.set_id AND h.project_id = v_set.project_id;
        IF v_admitted < 2 THEN
            RAISE EXCEPTION
                'hypothesis % cannot become SUPPORTED: its root-cause set % has % admitted '
                'hypothesis. EPI-001: 至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被'
                '升級成 confirmed root cause', NEW.target_id, v_set.set_id, v_admitted;
        END IF;
    END IF;

    -- §7.6's first trigger: a MAJOR REJECT (see the header) needs an independent critique path.
    IF NEW.to_state = 'CONTRADICTED'
       AND (v_set.root_cause OR v_set.inverted_retrieval_required)
       AND NOT EXISTS (
        SELECT 1 FROM critique_reports c
         WHERE NEW.target_id = ANY (c.target_ids)
           AND c.project_id = NEW.project_id
           AND cardinality(c.differs_in) >= 1
           AND c.created_at <= NEW.occurred_at
    ) THEN
        RAISE EXCEPTION
            'hypothesis % cannot be REJECTED (-> CONTRADICTED): no independent CritiqueReport '
            'targets it, and removing a rival from root-cause set % (stakes %) is a major REJECT. '
            '§7.6: 重大 REJECT 必須經 independent critique path (SRC-002)',
            NEW.target_id, v_set.set_id, v_set.stakes;
    END IF;

    IF v_set.inverted_retrieval_required AND NOT EXISTS (
        SELECT 1 FROM critique_reports c
         WHERE NEW.target_id = ANY (c.target_ids)
           AND c.project_id = NEW.project_id
           AND c.inverted_bundle_id IS NOT NULL
           AND cardinality(c.differs_in) >= 1
           AND c.created_at <= NEW.occurred_at
    ) THEN
        RAISE EXCEPTION
            'hypothesis % cannot enter BELIEF_REVISION: set % was debated at stakes % under %@%, '
            'which requires the Critic''s inverted retrieval, and no independent CritiqueReport '
            'with an inverted bundle targets it (SRC-002, §7.2)',
            NEW.target_id, v_set.set_id, v_set.stakes, v_set.source_policy_id,
            v_set.source_policy_version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- 4. §7.6's adjudication, held for a writer that skips `HypothesisBrain` (SRC-002).
--
-- A transition the critique path governs -- a major REJECT, or any transition in a set whose stakes
-- reached its policy's threshold -- must cite at least one attestation `core.adjudication` admits:
-- external evidence or a verification result, never an INFERRED record (a model's interpretation,
-- EVI-003) and never a DISPUTED one. The references are written by `belief_revision_event_append`
-- after the event row, so this is a DEFERRED constraint trigger -- `005c`'s pattern for "cites
-- evidence at all" -- checked when the statement's transaction commits.

CREATE FUNCTION belief_revisions_are_adjudicated_by_evidence() RETURNS TRIGGER AS $$
DECLARE
    v_set hypothesis_sets%ROWTYPE;
BEGIN
    IF NEW.from_state IS NULL THEN
        RETURN NULL;  -- admission is §8's gate, not an adjudication
    END IF;
    SELECT s.* INTO v_set
      FROM hypotheses h JOIN hypothesis_sets s ON s.set_id = h.hypothesis_set_id
     WHERE h.hypothesis_id = NEW.target_id AND h.project_id = NEW.project_id;
    IF NOT (
        (NEW.to_state = 'CONTRADICTED' AND (v_set.root_cause OR v_set.inverted_retrieval_required))
        OR v_set.inverted_retrieval_required
    ) THEN
        RETURN NULL;  -- a routine transition: M0b-M2 semantics
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM belief_revision_event_attestations l
          JOIN attestations a ON a.attestation_id = l.attestation_id
         WHERE l.event_id = NEW.event_id
           AND a.project_id = NEW.project_id
           AND a.epistemic_type <> 'INFERRED'
           AND a.verification_status <> 'DISPUTED'
    ) THEN
        RAISE EXCEPTION
            'event % moves hypothesis % to % on no admissible evidence: every triggering '
            'attestation is INFERRED or DISPUTED. §7.6: the adjudication MUST cite external '
            'evidence or a verification result, not another model opinion (SRC-002)',
            NEW.event_id, NEW.target_id, NEW.to_state;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER belief_revisions_are_adjudicated_by_evidence
    AFTER INSERT ON belief_revision_events
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION belief_revisions_are_adjudicated_by_evidence();
