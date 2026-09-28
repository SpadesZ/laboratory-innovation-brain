-- Product vertical / episode continuation. The research runs of an episode.
--
-- `lab-brain research run` opens a ResearchEpisode, and an episode it parks (SUSPENDED: waiting on
-- a simulator, a person, a seat or a budget) is continued later as THE SAME EPISODE. `006b`'s
-- lifecycle says which states may resume; it does not say WHO may continue an episode, or that a
-- continuation reasons over the same hypotheses as the run that opened it. A continuation that
-- could name any episode id would reach another project's episode, and one that debated again would
-- start a second, parallel reasoning history under the old episode's name. This table is where
-- both are decided, and it holds them against every writer, not only the service that uses it.
--
-- ONE ROW PER RUN of an episode. Ordinal 1 opened it; every later ordinal continued it.
--
--   * Only the actor who opened an episode continues it (the opener binding). Episodes carry no
--     actor, so the opening run's row IS the binding.
--   * A run starts only on an episode that is gathering evidence: a new one, or a suspended one
--     after `episode_resume` -- so a continuation cannot skip the authoritative lifecycle, and a
--     COMPLETED or ABANDONED episode receives no run at all.
--   * One live run per episode (the partial unique index): two continuations racing on one parked
--     episode cannot both proceed.
--   * One reasoning history per episode: the hypothesis set is recorded once, by the run that
--     debated it; every continuation carries that same set; and an episode whose set is recorded
--     admits no second hypothesis set -- the backstop against a parallel debate under its name.
--   * The verification input is the opener's, recorded once.
--
-- A run's identity is immutable; the only writes after insert are recording the set and the
-- verification input once, and finishing it once. Rows are never deleted.

CREATE TABLE IF NOT EXISTS research_runs (
    research_run_id           TEXT PRIMARY KEY CHECK (btrim(research_run_id) <> ''),
    episode_id                TEXT NOT NULL REFERENCES research_episodes (episode_id),
    project_id                TEXT NOT NULL REFERENCES projects (project_id),
    actor_id                  TEXT NOT NULL REFERENCES actors (actor_id),
    ordinal                   INTEGER NOT NULL CHECK (ordinal >= 1),
    hypothesis_set_id         TEXT,
    verification_artifact_id  TEXT REFERENCES artifacts (artifact_id),
    -- The framing the verification loop plans and records its failure analysis under. A
    -- continuation carries the opener's, so every analysis in the episode describes one problem.
    symptom                   TEXT,
    expected_behavior         TEXT,
    observed_behavior         TEXT,
    started_at                TIMESTAMPTZ NOT NULL,
    finished_at               TIMESTAMPTZ,
    outcome                   TEXT CHECK (outcome IS NULL OR btrim(outcome) <> ''),

    UNIQUE (episode_id, ordinal),
    FOREIGN KEY (hypothesis_set_id, project_id) REFERENCES hypothesis_sets (set_id, project_id),
    CONSTRAINT research_runs_finished_says_how CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CONSTRAINT research_runs_finish_after_start
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS research_runs_one_live_run_per_episode
    ON research_runs (episode_id) WHERE finished_at IS NULL;

CREATE TRIGGER research_runs_episode_in_project_trg BEFORE INSERT ON research_runs
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE FUNCTION research_runs_continue_the_opener() RETURNS TRIGGER AS $$
DECLARE
    v_state   TEXT;
    v_last    INTEGER;
    v_opener  research_runs%ROWTYPE;
BEGIN
    -- The episode row is locked so the state read here is the state the run starts on.
    SELECT state INTO v_state FROM research_episodes WHERE episode_id = NEW.episode_id FOR UPDATE;
    IF v_state IS DISTINCT FROM 'EVIDENCE_GATHERING' THEN
        RAISE EXCEPTION
            'episode % is %; a research run starts only on an episode gathering evidence -- a new '
            'one, or a suspended one resumed through episode_resume. A finished episode receives '
            'no new run', NEW.episode_id, v_state;
    END IF;
    SELECT coalesce(max(ordinal), 0) INTO v_last FROM research_runs
     WHERE episode_id = NEW.episode_id;
    IF NEW.ordinal <> v_last + 1 THEN
        RAISE EXCEPTION
            'research run % of episode % is numbered %, and the next run of that episode is %',
            NEW.research_run_id, NEW.episode_id, NEW.ordinal, v_last + 1;
    END IF;
    IF NEW.hypothesis_set_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM hypothesis_sets
         WHERE set_id = NEW.hypothesis_set_id AND episode_id = NEW.episode_id
    ) THEN
        RAISE EXCEPTION
            'hypothesis set % is not a set of episode %', NEW.hypothesis_set_id, NEW.episode_id;
    END IF;
    IF NEW.ordinal = 1 THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_opener FROM research_runs WHERE episode_id = NEW.episode_id AND ordinal = 1;
    IF NEW.actor_id IS DISTINCT FROM v_opener.actor_id THEN
        RAISE EXCEPTION
            'episode % was opened by another actor; only the actor who opened an episode '
            'continues it', NEW.episode_id;
    END IF;
    IF NEW.hypothesis_set_id IS DISTINCT FROM v_opener.hypothesis_set_id THEN
        RAISE EXCEPTION
            'a continuation of episode % reasons over the episode''s own hypothesis set %, not %',
            NEW.episode_id, v_opener.hypothesis_set_id, NEW.hypothesis_set_id;
    END IF;
    IF NEW.verification_artifact_id IS DISTINCT FROM v_opener.verification_artifact_id THEN
        RAISE EXCEPTION
            'a continuation of episode % verifies against the episode''s own input %, not %',
            NEW.episode_id, v_opener.verification_artifact_id, NEW.verification_artifact_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_runs_continue_the_opener_trg BEFORE INSERT ON research_runs
    FOR EACH ROW EXECUTE FUNCTION research_runs_continue_the_opener();

CREATE FUNCTION research_runs_record_once() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'research_runs is append-only: run % is part of its episode''s history',
            OLD.research_run_id;
    END IF;
    IF (NEW.research_run_id, NEW.episode_id, NEW.project_id, NEW.actor_id, NEW.ordinal,
        NEW.symptom, NEW.expected_behavior, NEW.observed_behavior, NEW.started_at)
       IS DISTINCT FROM
       (OLD.research_run_id, OLD.episode_id, OLD.project_id, OLD.actor_id, OLD.ordinal,
        OLD.symptom, OLD.expected_behavior, OLD.observed_behavior, OLD.started_at) THEN
        RAISE EXCEPTION 'research run %''s identity is immutable', OLD.research_run_id;
    END IF;
    IF OLD.finished_at IS NOT NULL THEN
        RAISE EXCEPTION 'research run % is finished (%); its record is final',
            OLD.research_run_id, OLD.outcome;
    END IF;
    IF NEW.hypothesis_set_id IS DISTINCT FROM OLD.hypothesis_set_id THEN
        IF OLD.hypothesis_set_id IS NOT NULL OR OLD.ordinal <> 1 THEN
            RAISE EXCEPTION
                'episode %''s hypothesis set is recorded once, by the run that debated it',
                OLD.episode_id;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM hypothesis_sets
             WHERE set_id = NEW.hypothesis_set_id AND episode_id = OLD.episode_id
        ) THEN
            RAISE EXCEPTION
                'hypothesis set % is not a set of episode %', NEW.hypothesis_set_id, OLD.episode_id;
        END IF;
    END IF;
    IF NEW.verification_artifact_id IS DISTINCT FROM OLD.verification_artifact_id
       AND (OLD.verification_artifact_id IS NOT NULL OR OLD.ordinal <> 1) THEN
        RAISE EXCEPTION
            'episode %''s verification input is recorded once, by the run that opened it',
            OLD.episode_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_runs_record_once_trg BEFORE UPDATE OR DELETE ON research_runs
    FOR EACH ROW EXECUTE FUNCTION research_runs_record_once();

-- The backstop for one reasoning history: once research runs have recorded an episode's hypothesis
-- set, a second set in that episode would be a parallel debate carrying the episode's name.
CREATE FUNCTION hypothesis_sets_one_history_per_research_episode() RETURNS TRIGGER AS $$
DECLARE
    v_recorded TEXT;
BEGIN
    SELECT hypothesis_set_id INTO v_recorded FROM research_runs
     WHERE episode_id = NEW.episode_id AND hypothesis_set_id IS NOT NULL
     LIMIT 1;
    IF v_recorded IS NOT NULL AND v_recorded <> NEW.set_id THEN
        RAISE EXCEPTION
            'episode % reasons over hypothesis set %; a second set % would be a parallel reasoning '
            'history under the same episode', NEW.episode_id, v_recorded, NEW.set_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hypothesis_sets_one_history_per_research_episode_trg
    BEFORE INSERT ON hypothesis_sets
    FOR EACH ROW EXECUTE FUNCTION hypothesis_sets_one_history_per_research_episode();

COMMENT ON TABLE research_runs IS
    'The research runs of an episode (lab-brain research run): ordinal 1 opened it and binds it to '
    'its actor; later ordinals continued it after episode_resume, over the same hypothesis set and '
    'verification input. One live run per episode; append-only apart from recording the set and '
    'the input once and finishing each run once.';
