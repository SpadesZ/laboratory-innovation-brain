-- 012y: exploratory screening -- a governed look where no hypothesis is looking, and the record
-- that keeps it from becoming support for whatever is proposed after the look.
--
-- WHY. A real model's five rivals for an open-via device all missed contact connectivity, and it
-- declined, on the evidence, to propose a mechanism there. Verification plans only over predicted
-- observables (§9.1, VER-001), so the seconds-long inspection that shows the fault never ran.
-- Screening runs such low-cost readings when NO hypothesis predicts them, under a declared policy,
-- as its own operation -- never as a VerificationPlan (`011k` would refuse an unpredicted choice,
-- rightly). `lab_brain.core.models.screening` states the contract; these tables hold it.
--
--   screening_plans                   which readings a stage took and why every other candidate
--                                     was not taken; the policy and the hypotheses it read
--   screening_observations            one row per selected check: its Job, Run, readings (each an
--                                     Observation + Attestation already admitted), how each
--                                     compares with the domain's reference outcome, and the Run's
--                                     evidence line
--   screening_conditioned_hypotheses  a hypothesis proposed AFTER its author was shown readings
--
-- THE GUARD THAT MATTERS (`relation_judgments_screening_guard`). A SUPPORTS relation to a
-- conditioned hypothesis is refused, for any writer, when it rests on
--   (a) a screened observation itself -- the look that prompted the hypothesis;
--   (b) an observation recorded before the hypothesis existed;
--   (c) a Run of the same evidence line as a reading the hypothesis was conditioned on -- the same
--       capability, backend, inputs and parameters: a deterministic repeat is not corroboration.
-- A post-screening mechanism can therefore gain support only from a prospective, different check.
-- Every Causal Warrant Gate rule still applies on top of that, unchanged.
--
-- All three tables are append-only and project-scoped.

CREATE TABLE IF NOT EXISTS screening_plans (
    plan_id                    TEXT PRIMARY KEY,
    project_id                 TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                 TEXT NOT NULL REFERENCES research_episodes (episode_id),
    trace_id                   TEXT NOT NULL,
    actor_id                   TEXT NOT NULL REFERENCES actors (actor_id),
    hypothesis_set_id          TEXT NOT NULL,
    policy_id                  TEXT NOT NULL CHECK (btrim(policy_id) <> ''),
    policy_version             TEXT NOT NULL CHECK (btrim(policy_version) <> ''),
    considered_hypothesis_ids  TEXT[] NOT NULL,
    unaddressed_observables    TEXT[] NOT NULL,
    input_artifacts            TEXT[] NOT NULL,
    candidates                 JSONB NOT NULL CHECK (jsonb_typeof(candidates) = 'array'),
    selected_capability_ids    TEXT[] NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (hypothesis_set_id, project_id) REFERENCES hypothesis_sets (set_id, project_id),
    CONSTRAINT screening_plans_id_project_unique UNIQUE (plan_id, project_id)
);

CREATE INDEX IF NOT EXISTS screening_plans_episode_idx ON screening_plans (project_id, episode_id);

CREATE TRIGGER screening_plans_episode_in_project_trg BEFORE INSERT ON screening_plans
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE TABLE IF NOT EXISTS screening_observations (
    screening_observation_id   TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL,
    project_id                 TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                 TEXT NOT NULL REFERENCES research_episodes (episode_id),
    rank                       INTEGER NOT NULL CHECK (rank >= 1),
    capability_id              TEXT NOT NULL,
    status                     TEXT NOT NULL CHECK (status IN (
                                   'EXECUTED', 'AWAITING_RESOURCE', 'BUDGET_BLOCKED', 'FAILED',
                                   'NOT_RUN')),
    job_id                     TEXT REFERENCES jobs (job_id),
    run_id                     TEXT REFERENCES runs (run_id),
    readings                   JSONB NOT NULL DEFAULT '[]'::jsonb
                               CHECK (jsonb_typeof(readings) = 'array'),
    -- Observation ids of the readings, for the guard below and for joins.
    observation_ids            TEXT[] NOT NULL DEFAULT '{}',
    estimated_cost             JSONB NOT NULL CHECK (jsonb_typeof(estimated_cost) = 'object'),
    evidence_line              TEXT,
    detail                     TEXT NOT NULL DEFAULT '',
    recorded_at                TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (plan_id, project_id) REFERENCES screening_plans (plan_id, project_id),
    CONSTRAINT screening_observations_one_per_rank UNIQUE (plan_id, rank),
    -- An executed reading names its Run, its evidence line and at least one Observation; nothing
    -- else observed anything.
    CONSTRAINT screening_observations_executed_is_traced CHECK (
        (status = 'EXECUTED') = (evidence_line IS NOT NULL)
        AND (status <> 'EXECUTED' OR (run_id IS NOT NULL AND cardinality(observation_ids) >= 1))
        AND (status = 'EXECUTED' OR cardinality(observation_ids) = 0)
    ),
    CONSTRAINT screening_observations_unexecuted_observed_nothing CHECK (
        status = 'EXECUTED' OR jsonb_array_length(readings) = 0
    )
);

-- One executed reading per evidence line per episode: a repeat is not a second observation.
CREATE UNIQUE INDEX IF NOT EXISTS screening_observations_one_line_per_episode
    ON screening_observations (project_id, episode_id, evidence_line)
    WHERE status = 'EXECUTED';

CREATE TRIGGER screening_observations_episode_in_project_trg
    BEFORE INSERT ON screening_observations
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE FUNCTION screening_observation_is_its_plans() RETURNS TRIGGER AS $$
DECLARE
    v_plan screening_plans%ROWTYPE;
    v_run  runs%ROWTYPE;
BEGIN
    SELECT * INTO v_plan FROM screening_plans WHERE plan_id = NEW.plan_id;
    IF v_plan.episode_id IS DISTINCT FROM NEW.episode_id THEN
        RAISE EXCEPTION 'screening observation %: its plan % is of episode %, not %',
            NEW.screening_observation_id, NEW.plan_id, v_plan.episode_id, NEW.episode_id;
    END IF;
    IF NOT (NEW.capability_id = ANY (v_plan.selected_capability_ids)) THEN
        RAISE EXCEPTION
            'screening observation %: % is not a check its plan % selected; a screening stage '
            'runs only what its plan chose',
            NEW.screening_observation_id, NEW.capability_id, NEW.plan_id;
    END IF;
    IF NEW.run_id IS NOT NULL THEN
        SELECT * INTO v_run FROM runs WHERE run_id = NEW.run_id;
        IF v_run.project_id IS DISTINCT FROM NEW.project_id
           OR v_run.capability_id IS DISTINCT FROM NEW.capability_id THEN
            RAISE EXCEPTION 'screening observation %: run % is not this project''s % run',
                NEW.screening_observation_id, NEW.run_id, NEW.capability_id;
        END IF;
    END IF;
    IF cardinality(NEW.observation_ids) > 0 AND EXISTS (
        SELECT 1 FROM unnest(NEW.observation_ids) x
         WHERE NOT EXISTS (
            SELECT 1 FROM observations o
             WHERE o.observation_id = x AND o.project_id = NEW.project_id
               AND o.run_id = NEW.run_id))
    THEN
        RAISE EXCEPTION
            'screening observation %: every reading must be an Observation of its own Run %',
            NEW.screening_observation_id, NEW.run_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER screening_observation_is_its_plans_trg BEFORE INSERT ON screening_observations
    FOR EACH ROW EXECUTE FUNCTION screening_observation_is_its_plans();

CREATE TABLE IF NOT EXISTS screening_conditioned_hypotheses (
    hypothesis_id              TEXT NOT NULL,
    project_id                 TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                 TEXT NOT NULL REFERENCES research_episodes (episode_id),
    plan_id                    TEXT NOT NULL,
    screening_observation_ids  TEXT[] NOT NULL CHECK (cardinality(screening_observation_ids) >= 1),
    inference_id               TEXT NOT NULL REFERENCES inference_provenance (inference_id),
    recorded_at                TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (project_id, hypothesis_id),
    FOREIGN KEY (project_id, hypothesis_id) REFERENCES hypotheses (project_id, hypothesis_id),
    FOREIGN KEY (plan_id, project_id) REFERENCES screening_plans (plan_id, project_id)
);

CREATE TRIGGER screening_conditioned_episode_in_project_trg
    BEFORE INSERT ON screening_conditioned_hypotheses
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE FUNCTION screening_conditioned_is_consistent() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM hypotheses h
         WHERE h.hypothesis_id = NEW.hypothesis_id AND h.project_id = NEW.project_id
           AND h.created_in_episode = NEW.episode_id
           AND h.inference_provenance_id = NEW.inference_id)
    THEN
        RAISE EXCEPTION
            'conditioned hypothesis %: not a hypothesis of episode % proposed by inference %',
            NEW.hypothesis_id, NEW.episode_id, NEW.inference_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM unnest(NEW.screening_observation_ids) x
         WHERE NOT EXISTS (
            SELECT 1 FROM screening_observations s
             WHERE s.screening_observation_id = x AND s.plan_id = NEW.plan_id
               AND s.status = 'EXECUTED'))
    THEN
        RAISE EXCEPTION
            'conditioned hypothesis %: it may be conditioned only on executed readings of plan %',
            NEW.hypothesis_id, NEW.plan_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER screening_conditioned_is_consistent_trg
    BEFORE INSERT ON screening_conditioned_hypotheses
    FOR EACH ROW EXECUTE FUNCTION screening_conditioned_is_consistent();

CREATE FUNCTION screening_rows_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% is append-only: a screening record says what was looked at, what was seen and what '
        'was proposed after seeing it; rewriting it would hide which evidence came first',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER screening_plans_are_append_only_trg BEFORE UPDATE OR DELETE ON screening_plans
    FOR EACH ROW EXECUTE FUNCTION screening_rows_are_append_only();
CREATE TRIGGER screening_observations_are_append_only_trg
    BEFORE UPDATE OR DELETE ON screening_observations
    FOR EACH ROW EXECUTE FUNCTION screening_rows_are_append_only();
CREATE TRIGGER screening_conditioned_are_append_only_trg
    BEFORE UPDATE OR DELETE ON screening_conditioned_hypotheses
    FOR EACH ROW EXECUTE FUNCTION screening_rows_are_append_only();

-- The guard. See the header.
CREATE FUNCTION relation_judgments_screening_guard() RETURNS TRIGGER AS $$
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
    -- (c) a deterministic repeat of a reading it was conditioned on
    SELECT r.* INTO v_run FROM runs r
      JOIN observations o ON o.run_id = r.run_id
     WHERE o.observation_id = NEW.from_entity_id;
    IF FOUND AND EXISTS (
        SELECT 1 FROM screening_observations s JOIN runs sr ON sr.run_id = s.run_id
         WHERE s.screening_observation_id = ANY (v_conditioned.screening_observation_ids)
           AND sr.capability_id = v_run.capability_id
           AND sr.backend_id = v_run.backend_id
           AND sr.input_parameters = v_run.input_parameters
           AND (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(sr.input_artifacts) x)
             = (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(v_run.input_artifacts) x))
    THEN
        RAISE EXCEPTION
            'relation %: run % repeats the screened reading % was conditioned on (same capability, '
            'backend, inputs and parameters); a deterministic repeat is not corroboration (012y)',
            NEW.relation_id, v_run.run_id, NEW.to_entity_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER relation_judgments_screening_guard_trg BEFORE INSERT ON relation_judgments
    FOR EACH ROW EXECUTE FUNCTION relation_judgments_screening_guard();
