-- A debate that failed before it produced a hypothesis set is retried in the same episode.
--
-- A model call can fail for an operational reason -- a provider that times out, a route that is
-- unavailable -- before the Hypothesis Engine has admitted anything. That is not a scientific
-- conclusion, so the episode is SUSPENDED rather than closed, and a continuation debates again over
-- the evidence the opening run already admitted. Two things `012c` did not allow make that possible,
-- and neither weakens its one-reasoning-history rule:
--
--   * The opening run's admitted statements are recorded (`research_run_statements`), BY REFERENCE:
--     the attestation the run admitted, with the trust class and source name it was admitted
--     under. A continuation reasons over exactly those -- nothing is ingested or admitted again.
--   * The episode's hypothesis set may be recorded by the run that debated it, whichever run that
--     is -- still ONCE per episode. A continuation carries the set any earlier run recorded (none,
--     until a debate succeeds); and once one is recorded, `012c`'s backstop refuses a second set.
--
-- A debate that failed AFTER admitting a set is not retried: that set is unrecorded, and a
-- continuation still refuses an episode whose reasoning history is incomplete.

CREATE TABLE IF NOT EXISTS research_run_statements (
    research_run_id  TEXT NOT NULL REFERENCES research_runs (research_run_id),
    ordinal          INTEGER NOT NULL CHECK (ordinal >= 1),
    attestation_id   TEXT NOT NULL REFERENCES attestations (attestation_id),
    trust_class      TEXT NOT NULL CHECK (btrim(trust_class) <> ''),
    source_name      TEXT NOT NULL CHECK (btrim(source_name) <> ''),
    recorded_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (research_run_id, ordinal),
    UNIQUE (research_run_id, attestation_id)
);

CREATE FUNCTION research_run_statements_guard() RETURNS TRIGGER AS $$
DECLARE
    v_run research_runs%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'research_run_statements is append-only: what a run admitted is history';
    END IF;
    SELECT * INTO v_run FROM research_runs WHERE research_run_id = NEW.research_run_id;
    IF v_run.finished_at IS NOT NULL THEN
        RAISE EXCEPTION 'research run % is finished; its admitted statements are final',
            NEW.research_run_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM attestations
         WHERE attestation_id = NEW.attestation_id AND project_id = v_run.project_id
    ) THEN
        RAISE EXCEPTION 'attestation % is not evidence of project %', NEW.attestation_id,
            v_run.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_run_statements_guard_trg
    BEFORE INSERT OR UPDATE OR DELETE ON research_run_statements
    FOR EACH ROW EXECUTE FUNCTION research_run_statements_guard();

-- `012c`'s INSERT rule, with one change: a continuation carries the set ANY earlier run of the
-- episode recorded (the opener's, as before, or the run whose retried debate produced it).
CREATE OR REPLACE FUNCTION research_runs_continue_the_opener() RETURNS TRIGGER AS $$
DECLARE
    v_state     TEXT;
    v_last      INTEGER;
    v_opener    research_runs%ROWTYPE;
    v_recorded  TEXT;
BEGIN
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
    SELECT hypothesis_set_id INTO v_recorded FROM research_runs
     WHERE episode_id = NEW.episode_id AND hypothesis_set_id IS NOT NULL
     LIMIT 1;
    IF NEW.hypothesis_set_id IS DISTINCT FROM v_recorded THEN
        RAISE EXCEPTION
            'a continuation of episode % reasons over the episode''s own hypothesis set %, not %',
            NEW.episode_id, v_recorded, NEW.hypothesis_set_id;
    END IF;
    IF NEW.verification_artifact_id IS DISTINCT FROM v_opener.verification_artifact_id THEN
        RAISE EXCEPTION
            'a continuation of episode % verifies against the episode''s own input %, not %',
            NEW.episode_id, v_opener.verification_artifact_id, NEW.verification_artifact_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- `012c`'s UPDATE rule, with one change: the set is recorded once PER EPISODE by the run that
-- debated it -- no longer only by the opening run.
CREATE OR REPLACE FUNCTION research_runs_record_once() RETURNS TRIGGER AS $$
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
        IF OLD.hypothesis_set_id IS NOT NULL OR EXISTS (
            SELECT 1 FROM research_runs
             WHERE episode_id = OLD.episode_id AND hypothesis_set_id IS NOT NULL
               AND research_run_id <> OLD.research_run_id
        ) THEN
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

COMMENT ON TABLE research_run_statements IS
    'The statements a research run admitted, by reference (attestation, trust class, source name), '
    'in order: what a continuation retrying a failed debate reasons over -- never re-ingested or '
    're-admitted. Append-only; written only while the run is live (012k).';
