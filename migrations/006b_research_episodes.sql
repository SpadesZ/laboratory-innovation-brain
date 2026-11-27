-- 006b_research_episodes.sql
--
-- OPS-001 / §17.3 / §12.1. The M1 exit gate's "delayed mock job resumes **episode**".
--
-- WHY A JOB RELOAD IS NOT AN EPISODE RESUME, which is the finding this migration answers.
--
-- A Job surviving a PostgreSQL restart proves the *job* is durable. The gate says the episode
-- resumes, and §12.1 makes an episode a state machine that spans many jobs: the thing that
-- suspends is the research activity, and the thing that must be found again after a restart is
-- which activity the resumed job belongs to. Substituting one for the other reads the milestone
-- wording as if it said "job", which it does not.
--
-- NUMBERING. Extends `006`, because `jobs.episode_id` is the reference this table resolves.
-- `010a`'s header records the same relationship from the span side. Appendix A has no episode
-- slot, and a suffixed migration must extend a reserved number.
--
-- THE SMALLEST COHERENT §17.3 SUBSET, and the omissions are declared rather than forgotten.
-- §17.3 lists sixteen fields; M1's suspend/resume contract needs identity, scope, trace, state
-- and timing. What is DEFERRED and why:
--
--   hypothesis_ids[]        EPI-001 is M3; a column referencing an entity that does not exist is
--                           an unapplyable migration, not a stricter schema (R-11/R-12's rule).
--   verification_plan_ids[] VER-001 is M4.
--   decision_ids[]          §17.14.1 Decisions are M0b's belief path; an episode that listed them
--                           would be a second index on a relation `belief_revision_events`
--                           already owns.
--   failure_analysis_id     §17.6 is M4.
--   human_annotations[]     no surface writes them in M1.
--   cost_ledger_id          COST-001 attributes cost to `episode_id` on the entry; an id here
--                           would be the reverse edge of a foreign key that already exists.
--
--   job_ids[] / run_ids[]   NOT a column, and this one is a design decision rather than a
--                           deferral. `jobs.episode_id` already carries the relation, and §17.8's
--                           rule -- no entity carries a parallel support array -- applies: an
--                           array here would be a second, unversioned source of truth for
--                           "which jobs belong to this episode", and the two would disagree
--                           silently. The membership is a query.

CREATE TABLE research_episodes (
    episode_id      TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects (project_id),

    -- §12.5's chain begins here: trace_id 貫穿 episode → retrieval → LLM call → job → run →
    -- artifact. Every Job in this episode carries the same trace, enforced below.
    trace_id        TEXT NOT NULL,
    goal            TEXT NOT NULL,

    -- §12.1's state machine, restricted to the states M1 reaches. The later states
    -- (HYPOTHESIS_FORMATION and onward) arrive with the slices that drive them; listing states
    -- nothing can enter would put permanently-unreachable values into the vocabulary.
    state           TEXT NOT NULL DEFAULT 'CREATED' CHECK (
        state IN ('CREATED', 'EVIDENCE_GATHERING', 'SUSPENDED', 'COMPLETED', 'ABANDONED')
    ),
    outcome_status  TEXT,

    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,

    -- What the episode was doing when it suspended, so a resumed worker knows where to pick up.
    -- The Job's `resume_stage` says where within an ingestion; this says which activity.
    suspended_at    TIMESTAMPTZ,
    suspend_reason  TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT research_episodes_end_after_start
        CHECK (end_time IS NULL OR end_time >= start_time),
    CONSTRAINT research_episodes_terminal_has_end CHECK (
        (state IN ('COMPLETED', 'ABANDONED')) = (end_time IS NOT NULL)
    ),
    CONSTRAINT research_episodes_suspended_says_when CHECK (
        (state = 'SUSPENDED') = (suspended_at IS NOT NULL)
    )
);

CREATE INDEX research_episodes_project_idx ON research_episodes (project_id, start_time DESC);
CREATE INDEX research_episodes_trace_idx   ON research_episodes (trace_id);

-- `jobs.episode_id` becomes a checked reference. `006` left it unchecked and said why: §17.3 was
-- not built, and an FK to a missing table is an unapplyable migration. It exists now.
--
-- NOT VALID is deliberate and is the narrowest compatible move: it applies the constraint to new
-- and updated rows without rewriting existing ones. `006`'s jobs were created before episodes
-- existed and legitimately carry NULL, and a validating ADD CONSTRAINT would refuse to apply
-- over any database that already holds a job naming an episode id from a test fixture.
ALTER TABLE jobs
    ADD CONSTRAINT jobs_episode_must_exist
    FOREIGN KEY (episode_id) REFERENCES research_episodes (episode_id) NOT VALID;

-- A Job must be on its episode's trace and in its episode's project.
--
-- §12.5 requires ONE trace through episode → job → run → artifact. `006a` already refuses a Run
-- that leaves its Job's trace; this closes the same gap one link earlier, so the chain cannot be
-- broken at its head. Without it an episode could hold jobs on three different traces and the
-- reassembled trace would silently contain a third of the work.
CREATE FUNCTION jobs_match_their_episode() RETURNS TRIGGER AS $$
DECLARE
    v_episode research_episodes%ROWTYPE;
BEGIN
    IF NEW.episode_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_episode FROM research_episodes WHERE episode_id = NEW.episode_id;
    IF NOT FOUND THEN
        RETURN NEW;  -- the foreign key reports this; duplicating it here would double the error
    END IF;
    IF v_episode.project_id <> NEW.project_id THEN
        RAISE EXCEPTION
            'job % is in project % but episode % is in %; an episode spanning projects would '
            'make SEC-002 scope depend on which end of the relation a reader started from',
            NEW.job_id, NEW.project_id, NEW.episode_id, v_episode.project_id;
    END IF;
    IF v_episode.trace_id <> NEW.trace_id THEN
        RAISE EXCEPTION
            'job % is on trace % but episode % is on %; §12.5 requires one trace through '
            'episode -> job -> run -> artifact, and a job off its episode''s trace drops that '
            'segment out of any reassembled trace',
            NEW.job_id, NEW.trace_id, NEW.episode_id, v_episode.trace_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_match_their_episode_trg
    BEFORE INSERT OR UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION jobs_match_their_episode();

-- Suspend and resume, as one statement each, so the state and its timestamp cannot diverge.
--
-- Idempotent on the target state for the reason `job_complete` is: the thing that resumes a
-- suspended episode is a worker that may itself have been restarted mid-resume.
CREATE FUNCTION episode_suspend(
    p_episode_id TEXT,
    p_reason     TEXT,
    p_at         TIMESTAMPTZ
) RETURNS TEXT AS $$
DECLARE
    v_state TEXT;
BEGIN
    SELECT state INTO v_state FROM research_episodes WHERE episode_id = p_episode_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'episode % does not exist', p_episode_id;
    END IF;
    IF v_state = 'SUSPENDED' THEN
        RETURN v_state;
    END IF;
    IF v_state IN ('COMPLETED', 'ABANDONED') THEN
        RAISE EXCEPTION
            'episode % is already %; a finished episode cannot be suspended',
            p_episode_id, v_state;
    END IF;
    UPDATE research_episodes
       SET state = 'SUSPENDED', suspended_at = p_at, suspend_reason = p_reason
     WHERE episode_id = p_episode_id;
    RETURN 'SUSPENDED';
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION episode_resume(
    p_episode_id TEXT
) RETURNS TEXT AS $$
DECLARE
    v_state TEXT;
BEGIN
    SELECT state INTO v_state FROM research_episodes WHERE episode_id = p_episode_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'episode % does not exist', p_episode_id;
    END IF;
    IF v_state IN ('COMPLETED', 'ABANDONED') THEN
        RAISE EXCEPTION
            'episode % is already %; a finished episode cannot be resumed', p_episode_id, v_state;
    END IF;
    UPDATE research_episodes
       SET state = 'EVIDENCE_GATHERING', suspended_at = NULL, suspend_reason = NULL
     WHERE episode_id = p_episode_id;
    RETURN 'EVIDENCE_GATHERING';
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE research_episodes IS
    'The minimum §17.3 subset M1''s suspend/resume contract needs: identity, project and trace '
    'binding, a suspendable state, and timing. Job membership is `jobs.episode_id`, not an array '
    'here -- §17.8 forbids the parallel-array shape. Deferred fields are listed in the migration '
    'header with the requirement that brings each one.';
