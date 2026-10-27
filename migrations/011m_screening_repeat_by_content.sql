-- 011m: a screened reading cannot SUPPORT its conditioned hypothesis under another identity.
--
-- NUMBERING. Applied after 012z (APPLY_ORDER is explicit). The 012 suffixes are spent -- 012t is
-- taken by another branch's migration -- so this extends 011, the predictions/relations family the
-- guard protects.
--
-- THE DEFECT, DEMONSTRATED FIRST (tests/e2e/test_g0_screening_independence_postgres.py, run on
-- 012y before this file existed): 012y's (c) treated a run as a deterministic repeat only when its
-- capability, backend, inputs AND parameters all matched the screened run's. The same bytes passed
-- through any other identity:
--
--     a relabelled backend id          same reader, same input, same parameters
--     an inert parameter               the readers write no parameter into their output
--     another capability               emitting the screened output artifact itself
--     every identity changed at once   only the output content was the screened content
--
-- Artifact ids were never a route: `artifact_id = 'art:' || content_hash` (002) is a CHECK and the
-- hash is UNIQUE, so content-identical input cannot carry two ids.
--
-- THE CLOSURE. Two refusals replace (c); (a) and (b) are unchanged.
--
--   (c) same capability, same inputs, same parameters -- ANY backend. A capability names the check;
--       the backend that ran it is not a second check of the device.
--   (d) the supporting run shares an output artifact with a run the hypothesis was conditioned on.
--       The id is the content hash, so a shared id is byte-identical output: the screened reading
--       itself, whatever capability, backend, parameters or provenance it was recorded under.
--
-- STRICTER ONLY. Nothing that 012y refused is allowed here; a later reading with genuinely
-- different output content and a different check is allowed exactly as before. Append-only rows,
-- signed review, the Budget Gate and TransitionPolicy are untouched.

CREATE OR REPLACE FUNCTION relation_judgments_screening_guard() RETURNS TRIGGER AS $$
DECLARE
    v_conditioned  screening_conditioned_hypotheses%ROWTYPE;
    v_created      TIMESTAMPTZ;
    v_observed     TIMESTAMPTZ;
    v_run          runs%ROWTYPE;
BEGIN
    IF NEW.relation_type <> 'SUPPORTS' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_conditioned FROM screening_conditioned_hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.to_entity_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    -- (a) the screened observation itself
    IF EXISTS (
        SELECT 1 FROM screening_observations s
         WHERE s.screening_observation_id = ANY (v_conditioned.screening_observation_ids)
           AND NEW.from_entity_id = ANY (s.observation_ids))
    THEN
        RAISE EXCEPTION
            'relation %: % was proposed after its author saw observation %; that observation '
            'cannot SUPPORT it (exploratory evidence, 012y)',
            NEW.relation_id, NEW.to_entity_id, NEW.from_entity_id;
    END IF;
    -- (b) an observation older than the hypothesis
    SELECT created_at INTO v_created FROM hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.to_entity_id;
    SELECT created_at INTO v_observed FROM observations WHERE observation_id = NEW.from_entity_id;
    IF v_observed IS NOT NULL AND v_created IS NOT NULL AND v_observed < v_created THEN
        RAISE EXCEPTION
            'relation %: observation % (%) predates hypothesis % (%), which was proposed after '
            'screening; only a prospective check can SUPPORT it (012y)',
            NEW.relation_id, NEW.from_entity_id, v_observed, NEW.to_entity_id, v_created;
    END IF;
    SELECT r.* INTO v_run FROM runs r
      JOIN observations o ON o.run_id = r.run_id
     WHERE o.observation_id = NEW.from_entity_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    -- (c) a deterministic repeat: the same check of the same input, whichever backend ran it
    IF EXISTS (
        SELECT 1 FROM screening_observations s JOIN runs sr ON sr.run_id = s.run_id
         WHERE s.screening_observation_id = ANY (v_conditioned.screening_observation_ids)
           AND sr.capability_id = v_run.capability_id
           AND sr.input_parameters = v_run.input_parameters
           AND (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(sr.input_artifacts) x)
             = (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(v_run.input_artifacts) x))
    THEN
        RAISE EXCEPTION
            'relation %: run % repeats the screened reading % was conditioned on (same capability, '
            'inputs and parameters, any backend); a deterministic repeat is not corroboration (011m)',
            NEW.relation_id, v_run.run_id, NEW.to_entity_id;
    END IF;
    -- (d) the screened bytes under another identity
    IF EXISTS (
        SELECT 1 FROM screening_observations s JOIN runs sr ON sr.run_id = s.run_id
         WHERE s.screening_observation_id = ANY (v_conditioned.screening_observation_ids)
           AND sr.output_artifacts && v_run.output_artifacts)
    THEN
        RAISE EXCEPTION
            'relation %: run % has the same output content as the screened reading % was '
            'conditioned on; the same bytes under another identity are not a second reading (011m)',
            NEW.relation_id, v_run.run_id, NEW.to_entity_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
