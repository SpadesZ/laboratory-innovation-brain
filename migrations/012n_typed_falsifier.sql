-- 012n_typed_falsifier.sql
--
-- Every admitted hypothesis carries a MACHINE-CHECKABLE falsifier.
--
-- `hypotheses.falsifier` is prose (`005e`), kept for explanation and the Critic's inverted
-- retrieval. A belief moves only by a relation a prediction declared before the check ran -- a
-- relation is never inferred from an observed outcome that merely differs from a SUPPORTS
-- prediction -- so a certificate whose falsifier was only prose had no outcome that could refute
-- it. The certificate now DESIGNATES its falsifier: `falsifier_prediction_ids`, predictions of the
-- same hypothesis in the same project whose every declared effect is CONTRADICTS. Merely holding
-- some CONTRADICTS prediction does not count; the designation is what is checked.
--
-- WHERE IT IS CHECKED. Predictions are written after their hypothesis (they reference it), so the
-- designation is checked when the hypothesis is ADMITTED -- its genesis BeliefRevisionEvent, the
-- same place `011i` requires a typed Prediction -- for every writer, raw SQL included.
-- `hypotheses` and `predictions` are immutable, so what was admitted stays what was checked.
--
-- A TRANSITION WRITTEN AROUND ADMISSION. Nothing requires a transition's target to have a genesis
-- event (the M0b-M2 suites write transitions on hypotheses that have only their identity row), so a
-- raw writer who also records an ALLOW decision can store one for a hypothesis never admitted. It
-- moves no belief -- the read side re-derives every decision and replays no transition without its
-- predecessor -- and requiring a genesis event here would change those suites' invariants.
--
-- HISTORY. Rows written before carry an empty designation and are not rewritten; their genesis
-- events were checked under the rule then in force. Only a NEW admission must designate.

ALTER TABLE hypotheses
    ADD COLUMN IF NOT EXISTS falsifier_prediction_ids TEXT[] NOT NULL DEFAULT '{}'
    CHECK (array_position(falsifier_prediction_ids, NULL) IS NULL);

COMMENT ON COLUMN hypotheses.falsifier_prediction_ids IS
    'The typed falsifier (012n): this hypothesis''s own CONTRADICTS predictions its certificate '
    'designates. Required at admission; empty only on rows admitted before 012n.';

-- `011j`'s function, restated with the genesis falsifier check; every other branch is unchanged.
CREATE OR REPLACE FUNCTION hypothesis_revisions_meet_m3_preconditions() RETURNS TRIGGER AS $$
DECLARE
    v_hyp       hypotheses%ROWTYPE;
    v_set       hypothesis_sets%ROWTYPE;
    v_admitted  INTEGER;
    v_unfit     TEXT;
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
        IF cardinality(v_hyp.falsifier_prediction_ids) = 0 THEN
            RAISE EXCEPTION
                'hypothesis % cannot be admitted: its certificate has no typed falsifier. A '
                'falsifier in prose cannot be adjudicated; the certificate designates at least one '
                'of its own CONTRADICTS predictions (falsifier_prediction_ids)', NEW.target_id;
        END IF;
        SELECT string_agg(f.prediction_id, ', ' ORDER BY f.prediction_id) INTO v_unfit
          FROM unnest(v_hyp.falsifier_prediction_ids) AS f (prediction_id)
         WHERE NOT EXISTS (
            SELECT 1 FROM predictions p
             WHERE p.prediction_id = f.prediction_id
               AND p.hypothesis_id = NEW.target_id AND p.project_id = NEW.project_id
               AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(p.relation_effect_if_observed) e
                     WHERE e ->> 'relation_type' IS DISTINCT FROM 'CONTRADICTS'
               )
         );
        IF v_unfit IS NOT NULL THEN
            RAISE EXCEPTION
                'hypothesis % cannot be admitted: its designated falsifier % is not a CONTRADICTS '
                'prediction of its own. A falsifier is one of the hypothesis''s typed predictions, '
                'declaring only CONTRADICTS on it', NEW.target_id, v_unfit;
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
