-- 006a_run_completion_integrity.sql
--
-- OPS-001 / EVI-009 / §17.4. Two audit findings against `006`, repaired together because both
-- land on the same function.
--
-- Separate from `006` rather than an edit to it, for the reason `007b` gives about `007a`: an
-- applied migration is checksummed and must not be edited. `006` has been applied by CI.
--
-- FINDING A — `job_complete` persisted a SUBSET of the Run manifest.
--
-- It took thirteen parameters and §17.4 declares twenty-one fields. The seven it omitted --
-- `domain`, `input_artifacts`, `input_parameters`, `conditions`, `environment`,
-- `backend_validity`, `warnings`, `numerical_array_refs` -- were not rejected. They were silently
-- replaced with column defaults. `InMemoryJobStore` kept them, so the two stores disagreed about
-- what a Run *is*, and the backend-free suite was green on the store that remembered.
--
-- The fields lost are exactly the ones that make a Run reproducible. §10.3: "每次 backend 執行必
-- 須產生可重播的 manifest（§17.4）。缺少任一必要欄位即拒絕升級為正式 evidence". An execution
-- whose `environment` and `backend_validity` were dropped on the way to the database is a Run
-- that cannot be replayed, and nothing anywhere said so.
--
-- FINDING B — `add_run()` was a second, weaker completion path.
--
-- `job_complete` is atomic and idempotent. `add_run` was INSERT-then-UPDATE with no commit-time
-- guarantee, so a durable state existed in which a Run row was present and its Job still had
-- `result_run_id IS NULL`. Such a Run is readable, joinable and citable while nothing records
-- that it is the authoritative output of anything.
--
-- The repair is ONE mechanism, not a hardened second one. `add_run` is deleted from the
-- repository, failed runs go through `job_complete` like every other run, and the
-- Job -> Run resolution is enforced at COMMIT by a deferred constraint trigger. That is `011d`'s
-- shape and `011d`'s reasoning: a guard inside a function holds for callers who call the
-- function.

-- Failed executions get a Run too (§6.10 needs them, §17.4 requires a manifest per execution),
-- and that Run is just as much the job's authoritative output as a successful one. The original
-- CHECK allowed `result_run_id` only on SUCCEEDED, which is what forced failed runs down the
-- second path in the first place.
ALTER TABLE jobs DROP CONSTRAINT jobs_run_only_when_succeeded;

ALTER TABLE jobs ADD CONSTRAINT jobs_run_only_when_finished_executing
    CHECK (result_run_id IS NULL OR state IN ('SUCCEEDED', 'FAILED'));

-- THE FINDING-B INVARIANT, at the commit boundary.
--
-- Deferred, and the reason is the same one `011d` gives: the one valid operation necessarily
-- passes through a forbidden intermediate state. `job_complete` inserts the Run before the Job
-- can reference it -- the reference is a foreign key, so the row has to exist first -- and
-- between those two statements the pair reads exactly like the defect. A per-statement trigger
-- would look stricter, pass every bypass test, and make completion impossible.
--
-- What survives COMMIT is the obligation: a Run exists only if its Job resolves to it.
CREATE FUNCTION runs_must_be_claimed_by_their_job() RETURNS TRIGGER AS $$
DECLARE
    v_claimed TEXT;
BEGIN
    SELECT result_run_id INTO v_claimed FROM jobs WHERE job_id = NEW.job_id;
    IF v_claimed IS DISTINCT FROM NEW.run_id THEN
        RAISE EXCEPTION
            'run % exists but job % resolves to % instead. A Run whose Job does not durably '
            'point at it is readable, joinable and citable while nothing records that it is the '
            'authoritative output of anything (OPS-001)',
            NEW.run_id, NEW.job_id, COALESCE(v_claimed, 'nothing');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER runs_must_be_claimed_by_their_job_trg
    AFTER INSERT OR UPDATE ON runs
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION runs_must_be_claimed_by_their_job();

-- The same obligation from the Job side. Without it, clearing `result_run_id` back to NULL would
-- re-create the forbidden pair without touching `runs`, so the trigger above would never fire.
-- `jobs_result_run_is_write_once` already refuses a *change* between two non-null values; this
-- closes the change to NULL.
CREATE FUNCTION jobs_may_not_abandon_their_run() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.result_run_id IS NOT NULL AND NEW.result_run_id IS NULL THEN
        RAISE EXCEPTION
            'job % cannot stop resolving to run %; the run row would remain, citable, with '
            'nothing recording whose output it is', NEW.job_id, OLD.result_run_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_may_not_abandon_their_run_trg
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION jobs_may_not_abandon_their_run();

-- LINKAGE. `006` checked that a Run's Job exists and shares its project. Two more fields must
-- agree, and both were free to contradict the Job:
--
--   capability_id  §17.16 records what the Job asked for and §17.4 records what ran. A Run that
--                  names a different capability is an execution of something nobody requested,
--                  and its authority class (§17.18) is then read from the wrong descriptor.
--   trace_id       §12.5 requires `trace_id` to run episode -> job -> run -> artifact. A Run on
--                  another trace silently detaches the second half of that chain, and the only
--                  symptom is a trace that appears to stop at the job.
--
-- Replaces `006`'s function rather than adding a second trigger, so there is one place a reader
-- has to look to know what a Run must agree with.
CREATE OR REPLACE FUNCTION runs_job_must_exist() RETURNS TRIGGER AS $$
DECLARE
    v_job jobs%ROWTYPE;
BEGIN
    SELECT * INTO v_job FROM jobs WHERE job_id = NEW.job_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'run % names job % which does not exist; a Run with no Job is an execution nobody '
            'can attribute to a submission', NEW.run_id, NEW.job_id;
    END IF;
    IF v_job.project_id <> NEW.project_id THEN
        RAISE EXCEPTION
            'run % is in project % but job % is in %; a run scoped away from its job escapes '
            'SEC-002 through the side door',
            NEW.run_id, NEW.project_id, NEW.job_id, v_job.project_id;
    END IF;
    IF v_job.capability_id <> NEW.capability_id THEN
        RAISE EXCEPTION
            'run % reports capability % but job % requested %; an execution of something nobody '
            'asked for reads its authority class from the wrong descriptor',
            NEW.run_id, NEW.capability_id, NEW.job_id, v_job.capability_id;
    END IF;
    IF v_job.trace_id <> NEW.trace_id THEN
        RAISE EXCEPTION
            'run % is on trace % but job % is on %; §12.5 requires one trace through episode -> '
            'job -> run -> artifact, and a detached run makes the chain appear to stop at the job',
            NEW.run_id, NEW.trace_id, NEW.job_id, v_job.trace_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The old thirteen-parameter signature is DROPPED, not left beside the new one. PostgreSQL
-- overloads by argument list, so leaving it would keep the lossy path callable -- and a caller
-- that omitted the manifest would still succeed, which is the defect.
DROP FUNCTION job_complete(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], TIMESTAMPTZ, TIMESTAMPTZ, TEXT,
    TIMESTAMPTZ
);

-- The whole §17.4 manifest, in one idempotent call.
--
-- `p_status` now decides the JOB's terminal state as well as the Run's: a FAILED run finishes
-- its job FAILED. That is what makes one mechanism sufficient and lets `add_run` go away.
CREATE FUNCTION job_complete(
    p_job_id            TEXT,
    p_idempotency_key   TEXT,
    p_run_id            TEXT,
    p_project_id        TEXT,
    p_capability_id     TEXT,
    p_backend_id        TEXT,
    p_domain            TEXT,
    p_trace_id          TEXT,
    p_input_artifacts   TEXT[],
    p_input_parameters  JSONB,
    p_conditions        JSONB,
    p_conditions_schema_version TEXT,
    p_environment       JSONB,
    p_code_provenance   TEXT,
    p_backend_validity  JSONB,
    p_status            TEXT,
    p_warnings          TEXT[],
    p_output_artifacts  TEXT[],
    p_numerical_array_refs TEXT[],
    p_start_time        TIMESTAMPTZ,
    p_end_time          TIMESTAMPTZ,
    p_manifest_hash     TEXT,
    p_completed_at      TIMESTAMPTZ
) RETURNS TEXT AS $$
DECLARE
    v_job   jobs%ROWTYPE;
    v_state TEXT;
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

    -- Every linkage field the caller states is CHECKED, never derived. Deriving would be safer
    -- against corruption and worse against confusion: a caller completing a job it believes is
    -- on another trace would get a Run silently filed on this one, and the returned record would
    -- disagree with the request with nothing surfaced. The trigger holds the same rules against
    -- writers that never call this function; these give the caller the better message.
    IF v_job.project_id <> p_project_id THEN
        RAISE EXCEPTION
            'completion for job % states project % but the job is in %; a run scoped away from '
            'its job escapes SEC-002 through the side door',
            p_job_id, p_project_id, v_job.project_id;
    END IF;
    IF v_job.capability_id <> p_capability_id THEN
        RAISE EXCEPTION
            'completion for job % reports capability % but the job requested %',
            p_job_id, p_capability_id, v_job.capability_id;
    END IF;
    IF v_job.trace_id <> p_trace_id THEN
        RAISE EXCEPTION
            'completion for job % is on trace % but the job is on %; §12.5 requires one trace '
            'through episode -> job -> run -> artifact',
            p_job_id, p_trace_id, v_job.trace_id;
    END IF;

    -- The redelivery path. Returns rather than raising: a duplicate callback is the expected
    -- behaviour of any at-least-once deliverer, not an error to surface.
    IF v_job.result_run_id IS NOT NULL THEN
        RETURN v_job.result_run_id;
    END IF;

    IF v_job.state IN ('SUCCEEDED', 'FAILED', 'CANCELLED') THEN
        RAISE EXCEPTION
            'job % is already %; a completion cannot reopen a terminal job',
            p_job_id, v_job.state;
    END IF;

    INSERT INTO runs (
        run_id, job_id, project_id, capability_id, backend_id, domain, trace_id,
        input_artifacts, input_parameters, conditions, conditions_schema_version,
        environment, code_provenance, backend_validity,
        status, warnings, output_artifacts, numerical_array_refs,
        start_time, end_time, reproducibility_manifest_hash
    ) VALUES (
        p_run_id, p_job_id, p_project_id, p_capability_id, p_backend_id, p_domain, p_trace_id,
        COALESCE(p_input_artifacts, '{}'), COALESCE(p_input_parameters, '{}'::jsonb),
        COALESCE(p_conditions, '{}'::jsonb), p_conditions_schema_version,
        COALESCE(p_environment, '{}'::jsonb), p_code_provenance,
        COALESCE(p_backend_validity, '{}'::jsonb),
        p_status, COALESCE(p_warnings, '{}'), COALESCE(p_output_artifacts, '{}'),
        COALESCE(p_numerical_array_refs, '{}'),
        p_start_time, p_end_time, p_manifest_hash
    );

    -- Neither QUEUED nor WAITING_RESOURCE may go straight to a terminal state, and a completion
    -- can arrive from either: the work ran whether or not this process observed it start.
    IF v_job.state IN ('QUEUED', 'WAITING_RESOURCE') THEN
        UPDATE jobs
           SET state = 'RUNNING',
               started_at = COALESCE(started_at, p_start_time)
         WHERE job_id = p_job_id;
    END IF;

    v_state := CASE WHEN p_status = 'FAILED' THEN 'FAILED' ELSE 'SUCCEEDED' END;

    UPDATE jobs
       SET state = v_state,
           result_run_id = p_run_id,
           finished_at = p_completed_at,
           started_at = COALESCE(started_at, p_start_time)
     WHERE job_id = p_job_id;

    RETURN p_run_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION job_complete IS
    'OPS-001 / §12.4 / §17.4: the ONE completion mechanism. Idempotent -- returns the '
    'authoritative run_id, newly created on first delivery and the existing one on every '
    'redelivery. Persists the whole Run manifest; a field omitted here is lost, so every §17.4 '
    'field is a parameter. A FAILED run finishes its job FAILED, which is why no second path is '
    'needed for unsuccessful executions.';
