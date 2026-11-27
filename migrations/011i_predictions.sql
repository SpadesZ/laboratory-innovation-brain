-- 011i_predictions.sql
--
-- M3 / EPI-001, VER-006, SRC-002. The Prediction half of Appendix A's `011_predictions_conflicts`
-- slot, which `011a`'s header left for "a later migration", and the belief-revision guard for
-- hypotheses that have a certificate.
--
-- PREDICTIONS. §17.5.1's typed Prediction, bound to a declared OutcomeSpace VERSION (`010c`), with
-- the membership rule VER-006 puts "at admission" enforced where every writer passes: an
-- `expected_outcome` outside the declared space, or explicitly excluded by it, is refused by the
-- database. Every declared effect lands on the prediction's own hypothesis and is one of §17.8's
-- epistemic four. And a prediction may not be ADDED to a hypothesis that has already been admitted:
-- the certificate is what was admitted, and back-filling it afterwards is the admit-first-and-fix-
-- later shape EVI-009 refuses for evidence.
--
-- THE REVISION GUARD. `belief_revision_events` is M0b's table and M0b's semantics are unchanged:
-- the guard acts ONLY on events whose target has a row in `hypotheses` -- a certificate admitted
-- through M3's gate. For those, four storage-checkable rules (`v3.3-a13`'s split: the semantic
-- half -- whether a critique's objections are right -- is evidence's, through TransitionPolicy):
--
--   genesis           the certificate has at least one typed Prediction. §8 admits a hypothesis
--                     only with its predictions; a genesis event on a certificate with none would
--                     admit an idea (EPI-001).
--   -> SUPPORTED      in a root-cause set, the set holds at least two ADMITTED hypotheses.
--                     EPI-001: 單一看似合理原因不得直接被升級成 confirmed root cause.
--   -> CONTRADICTED   whatever the stakes, an independent CritiqueReport (non-empty `differs_in`,
--                     written before the event) targets the hypothesis. §7.6's first trigger:
--                     重大 REJECT 必須經 independent critique path. Every REJECT of an admitted
--                     certificate is read as major -- it removes a rival from contention, which is
--                     the one outcome EPI-001 guards -- so no stakes floor is applied.
--   any transition    in a set whose policy required inverted retrieval (SRC-002, frozen on the
--                     set at creation), a CritiqueReport targeting the hypothesis exists with an
--                     inverted bundle and a non-empty independence exhibit, written BEFORE the
--                     event. Otherwise the decision "不得進入 BELIEF_REVISION".
--
-- Why a trigger and not only a Python gate: `lab_brain.core.revision_gate` refuses all three on the
-- write path, and a migration, a support script or a future service writes SQL. This project has
-- learned that sentence four times (see `011a`'s header).

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id               TEXT PRIMARY KEY,
    project_id                  TEXT NOT NULL REFERENCES projects (project_id),
    hypothesis_id               TEXT NOT NULL REFERENCES hypotheses (hypothesis_id),
    observable_ref              TEXT NOT NULL CHECK (btrim(observable_ref) <> ''),
    outcome_space_id            TEXT NOT NULL,
    outcome_space_version       TEXT NOT NULL,
    expected_outcome            TEXT NOT NULL,
    direction                   TEXT,
    conditions                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    conditions_schema_version   TEXT,
    relation_effect_if_observed JSONB NOT NULL,
    inference_provenance_id     TEXT REFERENCES inference_provenance (inference_id),
    created_at                  TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (outcome_space_id, outcome_space_version)
        REFERENCES outcome_spaces (outcome_space_id, version),
    CONSTRAINT predictions_declare_an_effect CHECK (
        jsonb_typeof(relation_effect_if_observed) = 'array'
        AND jsonb_array_length(relation_effect_if_observed) >= 1
    )
);

CREATE INDEX IF NOT EXISTS predictions_hypothesis_idx ON predictions (hypothesis_id);

CREATE FUNCTION predictions_are_admissible() RETURNS TRIGGER AS $$
DECLARE
    v_space        outcome_spaces%ROWTYPE;
    v_hyp_project  TEXT;
    v_effect       JSONB;
BEGIN
    SELECT project_id INTO v_hyp_project FROM hypotheses WHERE hypothesis_id = NEW.hypothesis_id;
    IF v_hyp_project <> NEW.project_id THEN
        RAISE EXCEPTION 'prediction % in % is bound to hypothesis % of project %',
            NEW.prediction_id, NEW.project_id, NEW.hypothesis_id, v_hyp_project;
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
         WHERE e.target_id = NEW.hypothesis_id AND e.from_state IS NULL
    ) THEN
        RAISE EXCEPTION
            'hypothesis % is already admitted; a prediction cannot be added to the certificate '
            'afterwards. What was admitted is what was admitted -- revise by EVOLVING it',
            NEW.hypothesis_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER predictions_are_admissible_trg
    BEFORE INSERT ON predictions
    FOR EACH ROW EXECUTE FUNCTION predictions_are_admissible();

CREATE FUNCTION predictions_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'prediction % is immutable; it is part of an admitted certificate',
        OLD.prediction_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER predictions_are_immutable_trg
    BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION predictions_are_immutable();

-- ---------------------------------------------------------------------------------------------
-- The M3 belief-revision guard (acts only on certificates admitted through M3's gate)
-- ---------------------------------------------------------------------------------------------

CREATE FUNCTION hypothesis_revisions_meet_m3_preconditions() RETURNS TRIGGER AS $$
DECLARE
    v_hyp       hypotheses%ROWTYPE;
    v_set       hypothesis_sets%ROWTYPE;
    v_admitted  INTEGER;
BEGIN
    SELECT * INTO v_hyp FROM hypotheses WHERE hypothesis_id = NEW.target_id;
    IF NOT FOUND THEN
        RETURN NEW;  -- not an M3 certificate: M0b's semantics apply unchanged
    END IF;
    IF v_hyp.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'event % in % targets hypothesis % of project %',
            NEW.event_id, NEW.project_id, NEW.target_id, v_hyp.project_id;
    END IF;
    SELECT * INTO v_set FROM hypothesis_sets WHERE set_id = v_hyp.hypothesis_set_id;

    IF NEW.from_state IS NULL THEN
        IF NOT EXISTS (SELECT 1 FROM predictions p WHERE p.hypothesis_id = NEW.target_id) THEN
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
            ON e.target_id = h.hypothesis_id AND e.from_state IS NULL
         WHERE h.hypothesis_set_id = v_set.set_id;
        IF v_admitted < 2 THEN
            RAISE EXCEPTION
                'hypothesis % cannot become SUPPORTED: its root-cause set % has % admitted '
                'hypothesis. EPI-001: 至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被'
                '升級成 confirmed root cause', NEW.target_id, v_set.set_id, v_admitted;
        END IF;
    END IF;

    -- §7.6's FIRST trigger: a REJECT (-> CONTRADICTED) of a certificate needs an independent
    -- critique path whatever the stakes. The second trigger, irreversible dispatch, is guarded at
    -- the dispatcher; the stakes threshold below is §7.2's inverted-retrieval MUST on top of both.
    IF NEW.to_state = 'CONTRADICTED' AND NOT EXISTS (
        SELECT 1 FROM critique_reports c
         WHERE NEW.target_id = ANY (c.target_ids)
           AND c.project_id = NEW.project_id
           AND cardinality(c.differs_in) >= 1
           AND c.created_at <= NEW.occurred_at
    ) THEN
        RAISE EXCEPTION
            'hypothesis % cannot be REJECTED (-> CONTRADICTED): no independent CritiqueReport '
            'targets it. §7.6: 重大 REJECT 必須經 independent critique path (SRC-002)',
            NEW.target_id;
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

CREATE TRIGGER hypothesis_revisions_meet_m3_preconditions_trg
    BEFORE INSERT ON belief_revision_events
    FOR EACH ROW EXECUTE FUNCTION hypothesis_revisions_meet_m3_preconditions();
