-- 011o: a SUPPORTS relation to a post-screening hypothesis is judged on EVERYTHING it rests on.
--
-- NUMBERING. Applied after 011n (APPLY_ORDER is explicit); 012 suffixes are spent.
--
-- THE DEFECT, DEMONSTRATED FIRST (tests/e2e/test_g0_screening_independence_postgres.py, on 011m):
-- the guard judged only the relation's `from_entity_id`, and only when it was an observation.
--
--     the screened attestation as the source       not an observation: never checked
--     a fresh observation citing the screened      the cited attestations -- the relation's
--       attestation                                evidence -- were never read
--     a fresh observation citing a repeat          the same
--     a hypothesis (or claim) as the source        not an observation: never checked
--
-- THE CLOSURE. For SUPPORTS to a hypothesis with a screening conditioning record:
--
--   * the source must be an observation: only a prospective check can support a hypothesis
--     proposed after its author saw a reading, and a claim, an attestation or another hypothesis is
--     not a check;
--   * every cited attestation must attest an observation;
--   * the source AND every observation behind a cited attestation must each pass (a) not screened,
--     (b) not older than the hypothesis, (c) not a repeat of the screened check, (d) not the
--     screened output content -- the rules of 012y and 011m, unchanged in substance.
--
-- STRICTER ONLY. Everything 011m refused is still refused with the same wording; a later reading
-- with different content, citing its own attestation, is allowed as before. Hypotheses without a
-- conditioning record are untouched.

CREATE OR REPLACE FUNCTION screening_basis_problem(
    p_conditioned screening_conditioned_hypotheses,
    p_hypothesis_created TIMESTAMPTZ,
    p_observation_id TEXT
) RETURNS TEXT AS $$
DECLARE
    v_observed TIMESTAMPTZ;
    v_run      runs%ROWTYPE;
BEGIN
    -- (a) a screened observation
    IF EXISTS (
        SELECT 1 FROM screening_observations s
         WHERE s.screening_observation_id = ANY (p_conditioned.screening_observation_ids)
           AND p_observation_id = ANY (s.observation_ids))
    THEN
        RETURN format('%s was proposed after its author saw observation %s; that observation '
                      'cannot SUPPORT it (exploratory evidence, 012y)',
                      p_conditioned.hypothesis_id, p_observation_id);
    END IF;
    -- (b) older than the hypothesis
    SELECT created_at INTO v_observed FROM observations WHERE observation_id = p_observation_id;
    IF v_observed IS NOT NULL AND p_hypothesis_created IS NOT NULL
       AND v_observed < p_hypothesis_created THEN
        RETURN format('observation %s (%s) predates hypothesis %s (%s), which was proposed after '
                      'screening; only a prospective check can SUPPORT it (012y)',
                      p_observation_id, v_observed, p_conditioned.hypothesis_id,
                      p_hypothesis_created);
    END IF;
    SELECT r.* INTO v_run FROM runs r JOIN observations o ON o.run_id = r.run_id
     WHERE o.observation_id = p_observation_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    -- (c) the same check of the same input, whichever backend ran it
    IF EXISTS (
        SELECT 1 FROM screening_observations s JOIN runs sr ON sr.run_id = s.run_id
         WHERE s.screening_observation_id = ANY (p_conditioned.screening_observation_ids)
           AND sr.capability_id = v_run.capability_id
           AND sr.input_parameters = v_run.input_parameters
           AND (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(sr.input_artifacts) x)
             = (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(v_run.input_artifacts) x))
    THEN
        RETURN format('run %s repeats the screened reading %s was conditioned on (same '
                      'capability, inputs and parameters, any backend); a deterministic repeat '
                      'is not corroboration (011m)', v_run.run_id, p_conditioned.hypothesis_id);
    END IF;
    -- (d) the screened bytes under another identity
    IF EXISTS (
        SELECT 1 FROM screening_observations s JOIN runs sr ON sr.run_id = s.run_id
         WHERE s.screening_observation_id = ANY (p_conditioned.screening_observation_ids)
           AND sr.output_artifacts && v_run.output_artifacts)
    THEN
        RETURN format('run %s has the same output content as the screened reading %s was '
                      'conditioned on; the same bytes under another identity are not a second '
                      'reading (011m)', v_run.run_id, p_conditioned.hypothesis_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION relation_judgments_screening_guard() RETURNS TRIGGER AS $$
DECLARE
    v_conditioned  screening_conditioned_hypotheses%ROWTYPE;
    v_created      TIMESTAMPTZ;
    v_attestation  TEXT;
    v_cited        TEXT;
    v_problem      TEXT;
BEGIN
    IF NEW.relation_type <> 'SUPPORTS' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_conditioned FROM screening_conditioned_hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.to_entity_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    SELECT created_at INTO v_created FROM hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.to_entity_id;
    -- The source: an observation, and an admissible one.
    IF NOT EXISTS (SELECT 1 FROM observations WHERE observation_id = NEW.from_entity_id) THEN
        RAISE EXCEPTION
            'relation %: % is not an observation; only an observation can SUPPORT % , which was '
            'proposed after screening (011o)', NEW.relation_id, NEW.from_entity_id,
            NEW.to_entity_id;
    END IF;
    v_problem := screening_basis_problem(v_conditioned, v_created, NEW.from_entity_id);
    IF v_problem IS NOT NULL THEN
        RAISE EXCEPTION 'relation %: %', NEW.relation_id, v_problem;
    END IF;
    -- Its evidence: every cited attestation attests an admissible observation.
    FOREACH v_attestation IN ARRAY NEW.supporting_attestation_ids LOOP
        SELECT observation_id INTO v_cited FROM attestations WHERE attestation_id = v_attestation;
        IF v_cited IS NULL THEN
            RAISE EXCEPTION
                'relation %: it cites %, which attests no observation; only a prospective check '
                'can SUPPORT %, which was proposed after screening (011o)',
                NEW.relation_id, v_attestation, NEW.to_entity_id;
        END IF;
        v_problem := screening_basis_problem(v_conditioned, v_created, v_cited);
        IF v_problem IS NOT NULL THEN
            RAISE EXCEPTION 'relation %: it cites % of %: %',
                NEW.relation_id, v_attestation, v_cited, v_problem;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
