-- 006_jobs_runs.sql
--
-- OPS-001 / §10.7 / §12.4 / §17.16 / §17.4.
--
-- NUMBERING. This claims the bare `006` slot because Appendix A names it `006_jobs_runs.sql` and
-- both halves are built here. `tests/spec/test_migration_numbering.py` requires a bare-numbered
-- migration's slug to match Appendix A exactly, which is why `010a` could not claim `010` and
-- this one can claim `006`.
--
-- WHAT THIS MIGRATION IS ACTUALLY FOR, in one sentence: a completion callback delivered twice
-- must not produce two Runs, and the only place that can be guaranteed is here.
--
-- The application-level version of this check is
--
--     if run_exists(job_id): return existing
--     else: create_run(...)
--
-- which is correct for one process and wrong for two. Both read "no run", both insert, and
-- afterwards the record holds two internally-consistent Runs with no fact distinguishing which
-- one the scientific evidence should cite. `runs.job_id UNIQUE` makes the second writer lose the
-- insert instead of the race, and `job_complete` below turns that loss into the *right* answer
-- rather than an error the caller has to interpret.
--
-- NOT THE SAME AS STORAGE IDEMPOTENCY. M1-P1 locked "same bytes -> same derived identity -> a
-- second write is a no-op". That needs no such constraint because the identity carries the
-- deduplication. A Run's identity is event-addressed -- minted when a completion arrives -- so
-- idempotency has to be bought. Nothing here is, or may become, the mechanism by which duplicate
-- *ingestion* is deduplicated.

-- One backend execution (§17.4 Run Manifest).
--
-- NO SOLVER/MESH/CALIBRATION COLUMNS. §17.4 states it: core MUST NOT hard-code those; domain and
-- backend validity schemas own the semantics. They arrive inside `backend_validity` and
-- `environment` as JSONB, opaque to core (§24.1). A `mesh_convergence` column here would be the
-- extension-boundary violation EXT-001 exists to detect.
CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,

    -- UNIQUE, and this single word is the requirement. See the header.
    -- No FK to jobs: the reference points the other way (`jobs.result_run_id`) and a circular
    -- pair of NOT NULL foreign keys cannot be inserted in either order. `job_complete` writes
    -- both halves in one statement pair inside one transaction, and
    -- `runs_job_must_exist` below checks this direction without creating the cycle.
    job_id          TEXT NOT NULL UNIQUE,

    project_id      TEXT NOT NULL REFERENCES projects (project_id),
    capability_id   TEXT NOT NULL,
    backend_id      TEXT NOT NULL,
    domain          TEXT,
    trace_id        TEXT NOT NULL,

    input_artifacts         TEXT[] NOT NULL DEFAULT '{}',
    input_parameters        JSONB  NOT NULL DEFAULT '{}'::jsonb,
    conditions              JSONB  NOT NULL DEFAULT '{}'::jsonb,
    conditions_schema_version TEXT NOT NULL,

    environment             JSONB  NOT NULL DEFAULT '{}'::jsonb,
    code_provenance         TEXT   NOT NULL,
    backend_validity        JSONB  NOT NULL DEFAULT '{}'::jsonb,

    status          TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'PARTIAL')),
    warnings        TEXT[] NOT NULL DEFAULT '{}',

    -- EVI-009: a run reference has to trace to produced artifacts. A SUCCEEDED run with an empty
    -- output list cannot support a MEASURED/SIMULATED attestation, so the row is refused rather
    -- than admitted and discovered at admission time.
    output_artifacts        TEXT[] NOT NULL DEFAULT '{}',
    numerical_array_refs    TEXT[] NOT NULL DEFAULT '{}',

    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    reproducibility_manifest_hash TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT runs_end_after_start CHECK (end_time >= start_time),

    CONSTRAINT runs_succeeded_produced_something
        CHECK (status <> 'SUCCEEDED' OR cardinality(output_artifacts) > 0)
);

CREATE INDEX runs_project_idx ON runs (project_id);
CREATE INDEX runs_trace_idx   ON runs (trace_id);

-- §17.16 Job / Suspend-Resume Contract.
CREATE TABLE jobs (
    job_id          TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects (project_id),

    -- No FK: §17.3's ResearchEpisode is not built in this slice. Same reasoning `010a` gives for
    -- its own `episode_id` -- an FK to a missing table is an unapplyable migration, not a
    -- stricter schema.
    episode_id      TEXT,

    capability_id   TEXT NOT NULL,
    trace_id        TEXT NOT NULL,

    -- §10.7's duplicate-callback defence. Scoped to the project rather than global: two projects
    -- legitimately submit "ingest my quarterly report" with the same caller-chosen key, and a
    -- global unique index would make the second project's submission silently collide with the
    -- first's -- the same cross-project collision `v3.3-a18` ruled on for evidence units.
    idempotency_key TEXT NOT NULL,

    state           TEXT NOT NULL DEFAULT 'QUEUED' CHECK (
        state IN ('QUEUED', 'RUNNING', 'WAITING_RESOURCE', 'SUCCEEDED', 'FAILED', 'CANCELLED')
    ),
    attempt_count   INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts    INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),

    submitted_at    TIMESTAMPTZ NOT NULL,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,

    retry_policy            JSONB NOT NULL DEFAULT '{}'::jsonb,
    timeout_policy          JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_requirements   JSONB NOT NULL DEFAULT '{}'::jsonb,

    result_run_id   TEXT REFERENCES runs (run_id),
    structured_error JSONB,
    resume_stage    TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT jobs_idempotency_key_unique_per_project UNIQUE (project_id, idempotency_key),

    CONSTRAINT jobs_terminal_has_finished_at CHECK (
        (state IN ('SUCCEEDED', 'FAILED', 'CANCELLED')) = (finished_at IS NOT NULL)
    ),
    CONSTRAINT jobs_queued_has_not_started CHECK (
        state <> 'QUEUED' OR started_at IS NULL
    ),
    CONSTRAINT jobs_started_after_submitted CHECK (
        started_at IS NULL OR started_at >= submitted_at
    ),
    CONSTRAINT jobs_finished_after_started CHECK (
        finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at
    ),
    CONSTRAINT jobs_attempts_bounded CHECK (attempt_count <= max_attempts),

    -- A Run is the product of a job that succeeded. Attaching one to a FAILED job would let the
    -- failure cite its own output as evidence.
    CONSTRAINT jobs_run_only_when_succeeded CHECK (
        result_run_id IS NULL OR state = 'SUCCEEDED'
    )
);

CREATE INDEX jobs_project_state_idx ON jobs (project_id, state);
CREATE INDEX jobs_trace_idx         ON jobs (trace_id);
CREATE INDEX jobs_episode_idx       ON jobs (episode_id) WHERE episode_id IS NOT NULL;

-- A run's job has to exist. Written as a trigger rather than a foreign key because
-- `jobs.result_run_id -> runs.run_id` already points the other way, and two NOT NULL foreign keys
-- in a cycle cannot be satisfied by any insert order. Checked at COMMIT for the same reason
-- `011d` defers its invariant: `job_complete` necessarily passes through a moment where the run
-- row exists and the job does not yet reference it.
CREATE FUNCTION runs_job_must_exist() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM jobs WHERE job_id = NEW.job_id) THEN
        RAISE EXCEPTION
            'run % names job % which does not exist; a Run with no Job is an execution nobody '
            'can attribute to a submission', NEW.run_id, NEW.job_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM jobs WHERE job_id = NEW.job_id AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'run % is in project % but job % is not; a run scoped away from its job escapes '
            'SEC-002 through the side door', NEW.run_id, NEW.project_id, NEW.job_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER runs_job_must_exist_trg
    AFTER INSERT OR UPDATE ON runs
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION runs_job_must_exist();

-- The state machine, in one place, refusing everything it does not name.
--
-- This duplicates `JOB_TRANSITIONS` in `lab_brain.core.models.job`, and duplication of a state
-- machine is how two layers end up disagreeing about what a job is. So it is not left to
-- inspection: `test_the_sql_transition_table_matches_the_python_one` parses both and compares
-- them, and adding an edge to one alone fails.
CREATE FUNCTION jobs_transition_is_legal() RETURNS TRIGGER AS $$
DECLARE
    v_legal BOOLEAN;
BEGIN
    IF OLD.state = NEW.state THEN
        RETURN NEW;
    END IF;

    v_legal := CASE OLD.state
        WHEN 'QUEUED'           THEN NEW.state IN ('RUNNING', 'CANCELLED', 'FAILED')
        WHEN 'RUNNING'          THEN NEW.state IN ('WAITING_RESOURCE', 'SUCCEEDED', 'FAILED', 'CANCELLED')
        WHEN 'WAITING_RESOURCE' THEN NEW.state IN ('RUNNING', 'FAILED', 'CANCELLED')
        ELSE FALSE
    END;

    IF NOT v_legal THEN
        RAISE EXCEPTION
            'job % cannot move % -> %; a terminal job is a finished fact and every other move '
            'is declared in JOB_TRANSITIONS', NEW.job_id, OLD.state, NEW.state;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_transition_is_legal_trg
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION jobs_transition_is_legal();

-- `result_run_id` is write-once. Rewriting it would silently change which execution a body of
-- scientific evidence traces to, and every attestation citing the old run would keep citing a
-- reference that now resolves somewhere else.
CREATE FUNCTION jobs_result_run_is_write_once() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.result_run_id IS NOT NULL AND NEW.result_run_id IS DISTINCT FROM OLD.result_run_id THEN
        RAISE EXCEPTION
            'job % already resolved to run %; rewriting it to % would move every attestation '
            'citing that run onto a different execution',
            NEW.job_id, OLD.result_run_id, NEW.result_run_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_result_run_is_write_once_trg
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION jobs_result_run_is_write_once();

-- The completion callback, made idempotent (§12.4, §10.7).
--
-- Returns the run_id that is authoritative for this job -- a newly created one on the first
-- delivery, the existing one on every redelivery. A caller therefore cannot tell the difference,
-- which is the entire point: a retrying callback deliverer must be able to keep delivering.
--
-- `FOR UPDATE` serialises concurrent callbacks; `runs.job_id UNIQUE` is the backstop if anyone
-- ever writes a second path into this table that forgets to take the lock. Both, not either:
-- the lock makes the common case give the right answer, and the constraint makes the uncommon
-- case fail loudly instead of quietly.
--
-- THE IDEMPOTENCY KEY IS CHECKED, not merely accepted. A callback carrying a different key is a
-- callback for a different submission that happens to name this job, and completing on it would
-- attribute one execution's output to another's request.
CREATE FUNCTION job_complete(
    p_job_id            TEXT,
    p_idempotency_key   TEXT,
    p_run_id            TEXT,
    p_project_id        TEXT,
    p_capability_id     TEXT,
    p_backend_id        TEXT,
    p_conditions_schema_version TEXT,
    p_code_provenance   TEXT,
    p_status            TEXT,
    p_output_artifacts  TEXT[],
    p_start_time        TIMESTAMPTZ,
    p_end_time          TIMESTAMPTZ,
    p_manifest_hash     TEXT,
    p_completed_at      TIMESTAMPTZ
) RETURNS TEXT AS $$
DECLARE
    v_job    jobs%ROWTYPE;
BEGIN
    SELECT * INTO v_job FROM jobs WHERE job_id = p_job_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'job % does not exist', p_job_id;
    END IF;

    IF v_job.idempotency_key <> p_idempotency_key THEN
        RAISE EXCEPTION
            'completion for job % carries idempotency key % but the job was submitted under %; '
            'this callback belongs to a different submission',
            p_job_id, p_idempotency_key, v_job.idempotency_key;
    END IF;

    -- The caller states the project and it is CHECKED rather than derived. Deriving it from the
    -- job would be safer against corruption and worse against confusion: a caller completing a
    -- job it believes is in project B would get a Run silently filed under A, and the returned
    -- record would disagree with the request in a way nothing surfaced. Refusing says so.
    IF v_job.project_id <> p_project_id THEN
        RAISE EXCEPTION
            'completion for job % states project % but the job is in %; a run scoped away from '
            'its job escapes SEC-002 through the side door',
            p_job_id, p_project_id, v_job.project_id;
    END IF;

    -- The redelivery path. Note it returns rather than raising: a duplicate callback is the
    -- expected behaviour of any at-least-once deliverer, not an error to surface.
    IF v_job.result_run_id IS NOT NULL THEN
        RETURN v_job.result_run_id;
    END IF;

    IF v_job.state IN ('SUCCEEDED', 'FAILED', 'CANCELLED') THEN
        RAISE EXCEPTION
            'job % is already %; a completion cannot reopen a terminal job',
            p_job_id, v_job.state;
    END IF;

    INSERT INTO runs (
        run_id, job_id, project_id, capability_id, backend_id, trace_id,
        conditions_schema_version, code_provenance, status, output_artifacts,
        start_time, end_time, reproducibility_manifest_hash
    ) VALUES (
        p_run_id, p_job_id, p_project_id, p_capability_id, p_backend_id, v_job.trace_id,
        p_conditions_schema_version, p_code_provenance, p_status, p_output_artifacts,
        p_start_time, p_end_time, p_manifest_hash
    );

    -- Neither QUEUED nor WAITING_RESOURCE may go straight to SUCCEEDED (see the transition
    -- table), and a completion can legitimately arrive from either: the work ran whether or not
    -- this process ever observed it start. So the job is walked through RUNNING rather than
    -- teleported to the end, and `started_at` is taken from the Run's own start_time below --
    -- the callback knows when the execution began and this process does not.
    IF v_job.state IN ('QUEUED', 'WAITING_RESOURCE') THEN
        UPDATE jobs
           SET state = 'RUNNING',
               started_at = COALESCE(started_at, p_start_time)
         WHERE job_id = p_job_id;
    END IF;

    UPDATE jobs
       SET state = 'SUCCEEDED',
           result_run_id = p_run_id,
           finished_at = p_completed_at,
           started_at = COALESCE(started_at, p_start_time)
     WHERE job_id = p_job_id;

    RETURN p_run_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION job_complete IS
    'OPS-001 / §12.4: idempotent completion. Returns the authoritative run_id -- newly created on '
    'first delivery, the existing one on every redelivery. Never creates a second Run.';
