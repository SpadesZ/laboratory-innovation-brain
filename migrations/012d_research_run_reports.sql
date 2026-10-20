-- Research workspace (web). The report each research run returned, kept so the episode can be
-- reopened later.
--
-- `ResearchEpisodeService.run` returns an `EpisodeReport`: the one account of a run, assembled from
-- the rows the authorities wrote. The CLI prints it and forgets it. A workspace that shows an
-- episode again tomorrow must show THAT account, not a second one recomputed by a web layer -- so
-- the report is recorded as it was returned, bound to the run that returned it, and never edited.
-- The episode's live state (suspended, completed, continued) is read from `research_episodes` and
-- `research_runs`, not from here: this table is what a run SAID, those are what IS.
--
--   * one report per research run, and only for a run that finished by returning one: not for a
--     run that is still live, was INTERRUPTED, or FAILED with an error;
--   * the report must be that run's: same episode, project and actor, the outcome the ledger
--     recorded for it (`<episode state>:<conclusion>`), and the run's own id in its provenance;
--   * append-only.

CREATE TABLE IF NOT EXISTS research_run_reports (
    research_run_id  TEXT PRIMARY KEY REFERENCES research_runs (research_run_id),
    episode_id       TEXT NOT NULL REFERENCES research_episodes (episode_id),
    project_id       TEXT NOT NULL REFERENCES projects (project_id),
    report           JSONB NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    recorded_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS research_run_reports_episode_idx
    ON research_run_reports (project_id, episode_id);

CREATE FUNCTION research_run_reports_are_their_runs() RETURNS TRIGGER AS $$
DECLARE
    v_run research_runs%ROWTYPE;
BEGIN
    SELECT * INTO v_run FROM research_runs WHERE research_run_id = NEW.research_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'research run % does not exist', NEW.research_run_id;
    END IF;
    IF (NEW.episode_id, NEW.project_id) IS DISTINCT FROM (v_run.episode_id, v_run.project_id) THEN
        RAISE EXCEPTION
            'the report of research run % names episode % in %, and the run is of episode % in %',
            NEW.research_run_id, NEW.episode_id, NEW.project_id, v_run.episode_id,
            v_run.project_id;
    END IF;
    IF v_run.finished_at IS NULL OR v_run.outcome = 'INTERRUPTED'
       OR v_run.outcome LIKE 'FAILED:%' THEN
        RAISE EXCEPTION
            'research run % did not return a report (%); only a finished run''s report is recorded',
            NEW.research_run_id, coalesce(v_run.outcome, 'still running');
    END IF;
    IF (NEW.report ->> 'episode_id', NEW.report ->> 'project_id', NEW.report ->> 'actor_id')
       IS DISTINCT FROM (v_run.episode_id, v_run.project_id, v_run.actor_id) THEN
        RAISE EXCEPTION
            'the report recorded for research run % is not about its episode, project and actor',
            NEW.research_run_id;
    END IF;
    IF (NEW.report ->> 'episode_state') || ':' || (NEW.report #>> '{conclusion,status}')
       IS DISTINCT FROM v_run.outcome THEN
        RAISE EXCEPTION
            'the report recorded for research run % concludes %:%, and the run recorded %',
            NEW.research_run_id, NEW.report ->> 'episode_state',
            NEW.report #>> '{conclusion,status}', v_run.outcome;
    END IF;
    IF position(NEW.research_run_id IN coalesce(NEW.report #>> '{provenance,0}', '')) = 0 THEN
        RAISE EXCEPTION
            'the report recorded for research run % does not name that run in its provenance',
            NEW.research_run_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_run_reports_are_their_runs_trg BEFORE INSERT ON research_run_reports
    FOR EACH ROW EXECUTE FUNCTION research_run_reports_are_their_runs();

CREATE FUNCTION research_run_reports_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'research_run_reports is append-only: a report is what run % returned', OLD.research_run_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_run_reports_are_append_only_trg
    BEFORE UPDATE OR DELETE ON research_run_reports
    FOR EACH ROW EXECUTE FUNCTION research_run_reports_are_append_only();

COMMENT ON TABLE research_run_reports IS
    'The EpisodeReport each finished research run returned, as returned: the research workspace '
    'shows an episode again from this, never from a recomputation. Bound to its run (episode, '
    'project, actor, recorded outcome, run id in provenance); append-only.';
