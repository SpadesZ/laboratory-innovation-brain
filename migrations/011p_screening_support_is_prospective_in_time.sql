-- 011p: prospective support is judged by when its evidence came to be, not when its row was written.
--
-- NUMBERING. Applied after 011o (APPLY_ORDER is explicit); 012 suffixes are spent.
--
-- THE DEFECT, DEMONSTRATED FIRST (tests/e2e/test_g0_evidence_timing_postgres.py, on 011o): 012y (b)
-- compared the hypothesis with the OBSERVATION's `created_at` -- the database's clock. Evidence that
-- existed before the hypothesis, written today, passed as a new and independent reading:
--
--     a late-recorded run       the run STARTED before the hypothesis; its observation is new
--     old captured data         a new run whose output artifact was CAPTURED years ago
--     re-read screened output   a new run of another check whose INPUT is the screened output
--     an evidence lookup        a run of a capability whose kind is to look up what exists
--
-- THE CLOSURE. For a hypothesis with a screening conditioning record, each basis observation must
-- also be prospective in TIME and in KIND (added to `screening_basis_problem`, so the source and
-- every cited observation are judged alike, as 011o made them):
--
--   (e) its run started at or after the hypothesis was created;
--   (f) no input or output artifact of its run was captured before the hypothesis (`captured_at`,
--       the time the data was taken -- distinct from the row's `created_at`);
--   (g) no input artifact of its run is the output of a run that started before the hypothesis --
--       which includes every conditioned (screened) run: re-reading the screened reading, or any
--       older data, is analysis of what was already there, not a new check;
--   (h) its capability is registered with a kind that produces new evidence. EXISTING_EVIDENCE_LOOKUP
--       and HISTORICAL_CASE_COMPARISON read what exists, and a capability not registered in
--       `capabilities` has no declared kind: both are refused (fail closed).
--
-- RETROSPECTIVE EVIDENCE IS KEPT, NOT UPGRADED. Nothing here touches hypotheses formed before
-- screening, or relation types other than SUPPORTS: old evidence may still be recorded against a
-- post-screening hypothesis as context (CITES), and still SUPPORT a pre-screening hypothesis.
-- Stricter only: everything 011o refused is refused with the same wording.

CREATE OR REPLACE FUNCTION screening_basis_problem(
    p_conditioned screening_conditioned_hypotheses,
    p_hypothesis_created TIMESTAMPTZ,
    p_observation_id TEXT
) RETURNS TEXT AS $$
DECLARE
    v_observed TIMESTAMPTZ;
    v_run      runs%ROWTYPE;
    v_kind     TEXT;
    v_found    BOOLEAN;
    v_artifact TEXT;
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
    -- (b) recorded before the hypothesis
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
        RETURN format('observation %s has no run; only a prospective check can SUPPORT %s, '
                      'which was proposed after screening (011p)',
                      p_observation_id, p_conditioned.hypothesis_id);
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
    -- (e) the run itself began before the hypothesis
    IF p_hypothesis_created IS NOT NULL AND v_run.start_time < p_hypothesis_created THEN
        RETURN format('run %s started at %s, before the hypothesis %s was proposed (%s): '
                      'retrospective evidence, not a prospective check (011p)',
                      v_run.run_id, v_run.start_time, p_conditioned.hypothesis_id,
                      p_hypothesis_created);
    END IF;
    -- (f) data captured before the hypothesis
    SELECT a.artifact_id INTO v_artifact FROM artifacts a
     WHERE a.artifact_id = ANY (v_run.input_artifacts || v_run.output_artifacts)
       AND a.captured_at IS NOT NULL AND a.captured_at < p_hypothesis_created
     ORDER BY a.artifact_id LIMIT 1;
    IF v_artifact IS NOT NULL THEN
        RETURN format('run %s reads or emits %s, whose data was captured before the hypothesis '
                      '%s was proposed: retrospective evidence, not a prospective check (011p)',
                      v_run.run_id, v_artifact, p_conditioned.hypothesis_id);
    END IF;
    -- (g) derived from the output of an earlier run (the screened ones included)
    SELECT earlier.run_id INTO v_artifact FROM runs earlier
     WHERE earlier.project_id = v_run.project_id
       AND earlier.run_id <> v_run.run_id
       AND earlier.output_artifacts && v_run.input_artifacts
       AND earlier.start_time < p_hypothesis_created
     ORDER BY earlier.run_id LIMIT 1;
    IF v_artifact IS NOT NULL THEN
        RETURN format('run %s reads the output of run %s, which ran before the hypothesis %s was '
                      'proposed: it is derived from evidence that already existed (011p)',
                      v_run.run_id, v_artifact, p_conditioned.hypothesis_id);
    END IF;
    -- (h) the capability's kind
    SELECT action_type INTO v_kind FROM capabilities WHERE capability_id = v_run.capability_id;
    v_found := FOUND;
    IF NOT v_found THEN
        RETURN format('run %s is of capability %s, which is not registered with a kind; only a '
                      'check registered as producing new evidence can SUPPORT %s (011p)',
                      v_run.run_id, v_run.capability_id, p_conditioned.hypothesis_id);
    END IF;
    IF v_kind IN ('EXISTING_EVIDENCE_LOOKUP', 'HISTORICAL_CASE_COMPARISON') THEN
        RETURN format('run %s is of capability %s, a %s: it reads existing evidence, which is '
                      'retrospective, not a prospective check of %s (011p)',
                      v_run.run_id, v_run.capability_id, v_kind, p_conditioned.hypothesis_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;
