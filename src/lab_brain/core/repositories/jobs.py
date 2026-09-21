"""Durable Job and Run storage (OPS-001, §10.7, §12.4, §17.16, §17.4).

THE ONE METHOD THAT MATTERS is :meth:`JobStore.complete`. Everything else here is bookkeeping
around it.

Its signature is the design: it takes the Run the caller *proposes* and returns the Run that is
*authoritative*. On a first delivery those are the same object. On a redelivery the proposal is
discarded and the existing Run comes back, so a caller cannot tell the two apart -- which is the
entire point, because an at-least-once callback deliverer has to be free to keep delivering.

    proposed = Run(run_id=new_id(), ...)
    actual = store.complete(job_id, key, proposed)
    # actual.run_id may not be proposed.run_id, and the caller must use `actual`.

Returning the Run rather than a bool is deliberate. A bool would make the caller ask "did I win?"
and then go look up the winner, and the lookup is a second read that can observe a different
state. The one call answers the only question worth asking: which execution is this job's.

WHY TWO IMPLEMENTATIONS. The Protocol/InMemory/Sql shape is this package's existing idiom
(`belief_events`, `conflicts`, `reviews`) and exists so one conformance suite runs against both.
That matters more here than elsewhere: the in-memory store is the one a backend-free test uses,
so if it were *more* permissive than PostgreSQL the suite would pass on a fake and the invariant
would fail in production. `InMemoryJobStore` therefore takes a lock and enforces the same state
machine, and the shared suite in `tests/contract/test_job_lifecycle.py` runs against both.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from typing import Protocol, cast, runtime_checkable

from lab_brain.core.models.job import (
    JOB_TRANSITIONS,
    TERMINAL_JOB_STATES,
    Job,
    JobState,
    JobTransitionError,
    Run,
)
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class JobStoreError(RepositoryError):
    """A job or run write violated a lifecycle invariant."""


class IdempotencyKeyMismatch(JobStoreError):
    """A completion named a job that was submitted under a different key.

    Separate from the generic error because the operational meaning is specific and actionable:
    something is delivering callbacks for submission A against job B. Completing anyway would
    attribute one execution's output to another's request, which is a provenance corruption that
    nothing downstream could detect -- the Run would be perfectly well-formed.
    """


@runtime_checkable
class JobStore(Protocol):
    """The durable Job/Run boundary. See the module docstring for ``complete``."""

    def submit(self, job: Job) -> Job:
        """Register a job. Idempotent on ``(project_id, idempotency_key)``.

        A resubmission returns the existing job rather than raising: a client that retries a
        submission it is unsure landed is behaving correctly, and punishing it would push the
        retry logic back out to every caller.
        """
        ...

    def get(self, job_id: str) -> Job | None: ...

    def find_by_idempotency_key(self, project_id: str, key: str) -> Job | None: ...

    def transition(
        self,
        job_id: str,
        state: JobState,
        at: dt.datetime,
        *,
        structured_error: dict[str, object] | None = None,
        resume_stage: str | None = None,
        attempt_count: int | None = None,
    ) -> Job:
        """Move a job. Refuses any edge ``JOB_TRANSITIONS`` does not declare."""
        ...

    def complete(self, job_id: str, idempotency_key: str, proposed: Run) -> Run:
        """Finish a job with exactly one logical Run. Idempotent. See the module docstring."""
        ...

    def get_run(self, run_id: str) -> Run | None: ...

    def run_for_job(self, job_id: str) -> Run | None: ...

    def active_depth(self, project_id: str) -> int:
        """QUEUED + RUNNING + WAITING_RESOURCE, for UX-007's queue depth."""
        ...

    def list_active(self, project_id: str) -> tuple[Job, ...]: ...


def _check_transition(job: Job, state: JobState) -> None:
    allowed = JOB_TRANSITIONS[job.state]
    if state not in allowed:
        permitted = ", ".join(sorted(s.value for s in allowed)) or "nothing (terminal)"
        raise JobTransitionError(
            f"job {job.job_id} cannot move {job.state.value} -> {state.value}; "
            f"permitted from {job.state.value}: {permitted}"
        )


class InMemoryJobStore:
    """Backend-free implementation with the same guarantees.

    THE LOCK IS NOT DECORATION, for the reason `InMemoryBudgetApprovalClaims` gives about its own:
    without it every sequential test passes and the single property this class exists to provide
    fails, first in production. ``complete`` is a read-modify-write across two dicts, which is
    exactly the shape that loses a race.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._runs: dict[str, Run] = {}
        self._run_by_job: dict[str, str] = {}

    def submit(self, job: Job) -> Job:
        with self._lock:
            key = (job.project_id, job.idempotency_key)
            existing_id = self._by_key.get(key)
            if existing_id is not None:
                return self._jobs[existing_id]
            if job.job_id in self._jobs:
                raise JobStoreError(
                    f"job {job.job_id} already exists under a different idempotency key"
                )
            self._jobs[job.job_id] = job
            self._by_key[key] = job.job_id
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def find_by_idempotency_key(self, project_id: str, key: str) -> Job | None:
        with self._lock:
            job_id = self._by_key.get((project_id, key))
            return None if job_id is None else self._jobs[job_id]

    def transition(
        self,
        job_id: str,
        state: JobState,
        at: dt.datetime,
        *,
        structured_error: dict[str, object] | None = None,
        resume_stage: str | None = None,
        attempt_count: int | None = None,
    ) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobStoreError(f"job {job_id} does not exist")
            moved = job.transitioned(
                state,
                at,
                structured_error=structured_error,
                resume_stage=resume_stage,
                attempt_count=attempt_count,
            )
            self._jobs[job_id] = moved
            return moved

    def complete(self, job_id: str, idempotency_key: str, proposed: Run) -> Run:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobStoreError(f"job {job_id} does not exist")
            if job.idempotency_key != idempotency_key:
                raise IdempotencyKeyMismatch(
                    f"completion for job {job_id} carries idempotency key {idempotency_key} but "
                    f"the job was submitted under {job.idempotency_key}; this callback belongs "
                    "to a different submission"
                )

            existing_run_id = self._run_by_job.get(job_id)
            if existing_run_id is not None:
                return self._runs[existing_run_id]

            if job.state in TERMINAL_JOB_STATES:
                raise JobStoreError(
                    f"job {job_id} is already {job.state.value}; a completion cannot reopen a "
                    "terminal job"
                )
            if proposed.job_id != job_id:
                raise JobStoreError(
                    f"run {proposed.run_id} names job {proposed.job_id} but is being used to "
                    f"complete {job_id}"
                )
            if proposed.project_id != job.project_id:
                raise JobStoreError(
                    f"run {proposed.run_id} is in project {proposed.project_id} but job "
                    f"{job_id} is in {job.project_id}; a run scoped away from its job escapes "
                    "SEC-002 through the side door"
                )

            # Same walk the SQL function performs, and for the same reason: the work ran whether
            # or not this process observed it start.
            current = job
            if current.state in (JobState.QUEUED, JobState.WAITING_RESOURCE):
                current = current.transitioned(JobState.RUNNING, proposed.start_time)
            self._runs[proposed.run_id] = proposed
            self._run_by_job[job_id] = proposed.run_id
            self._jobs[job_id] = current.transitioned(
                JobState.SUCCEEDED, proposed.end_time, result_run_id=proposed.run_id
            )
            return proposed

    def get_run(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def run_for_job(self, job_id: str) -> Run | None:
        with self._lock:
            run_id = self._run_by_job.get(job_id)
            return None if run_id is None else self._runs[run_id]

    def active_depth(self, project_id: str) -> int:
        with self._lock:
            return sum(
                1 for job in self._jobs.values() if job.project_id == project_id and job.is_active
            )

    def list_active(self, project_id: str) -> tuple[Job, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (j for j in self._jobs.values() if j.project_id == project_id and j.is_active),
                    key=lambda j: j.submitted_at,
                )
            )


_JOB_COLUMNS = (
    "job_id",
    "project_id",
    "episode_id",
    "capability_id",
    "trace_id",
    "idempotency_key",
    "state",
    "attempt_count",
    "max_attempts",
    "submitted_at",
    "started_at",
    "finished_at",
    "retry_policy",
    "timeout_policy",
    "resource_requirements",
    "result_run_id",
    "structured_error",
    "resume_stage",
)

_RUN_COLUMNS = (
    "run_id",
    "job_id",
    "project_id",
    "capability_id",
    "backend_id",
    "domain",
    "trace_id",
    "input_artifacts",
    "input_parameters",
    "conditions",
    "conditions_schema_version",
    "environment",
    "code_provenance",
    "backend_validity",
    "status",
    "warnings",
    "output_artifacts",
    "numerical_array_refs",
    "start_time",
    "end_time",
    "reproducibility_manifest_hash",
)


class SqlJobStore:
    """PostgreSQL implementation. The invariants live in `006_jobs_runs.sql`, not here.

    ``complete`` is one call to the `job_complete` stored function rather than a
    read-check-write in Python, and that is the whole reason this class is thin. A Python
    implementation would hold the check and the write in separate statements, and two processes
    would interleave between them. The function takes a row lock, and `runs.job_id UNIQUE` is
    the backstop behind it.

    Reads rebuild through the Pydantic model, so a row that drifted -- a repair script, a partial
    restore -- raises rather than being handed back as a Job. Same boundary reasoning as
    `PostgresEvidenceUnitReader`.
    """

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    # -- jobs ---------------------------------------------------------------

    def submit(self, job: Job) -> Job:
        # ON CONFLICT on the idempotency key, not on the primary key: a resubmission carries a
        # *new* job_id and the same key, so a primary-key conflict target would let it through
        # and create a second job for one logical submission.
        self._connection.execute(
            "INSERT INTO jobs (job_id, project_id, episode_id, capability_id, trace_id, "
            "idempotency_key, state, attempt_count, max_attempts, submitted_at, started_at, "
            "finished_at, retry_policy, timeout_policy, resource_requirements, result_run_id, "
            "structured_error, resume_stage) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, idempotency_key) DO NOTHING",
            (
                job.job_id,
                job.project_id,
                job.episode_id,
                job.capability_id,
                job.trace_id,
                job.idempotency_key,
                job.state.value,
                job.attempt_count,
                job.max_attempts,
                job.submitted_at,
                job.started_at,
                job.finished_at,
                _json(job.retry_policy),
                _json(job.timeout_policy),
                _json(job.resource_requirements),
                job.result_run_id,
                _json(job.structured_error) if job.structured_error is not None else None,
                job.resume_stage,
            ),
        )
        stored = self.find_by_idempotency_key(job.project_id, job.idempotency_key)
        if stored is None:  # pragma: no cover - the insert either landed or conflicted
            raise JobStoreError(f"job {job.job_id} vanished immediately after being written")
        return stored

    def get(self, job_id: str) -> Job | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM jobs WHERE job_id = %s", (job_id,)
        ).fetchone()
        return None if row is None else _job_from_row(row)

    def find_by_idempotency_key(self, project_id: str, key: str) -> Job | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM jobs "
            "WHERE project_id = %s AND idempotency_key = %s",
            (project_id, key),
        ).fetchone()
        return None if row is None else _job_from_row(row)

    def transition(
        self,
        job_id: str,
        state: JobState,
        at: dt.datetime,
        *,
        structured_error: dict[str, object] | None = None,
        resume_stage: str | None = None,
        attempt_count: int | None = None,
    ) -> Job:
        job = self.get(job_id)
        if job is None:
            raise JobStoreError(f"job {job_id} does not exist")
        # Checked here as well as by the trigger. Not redundancy for its own sake: the model
        # produces the *message* naming the permitted edges, which a CHECK cannot, and the
        # trigger holds the same rule against writers that never come through this class.
        _check_transition(job, state)
        moved = job.transitioned(
            state,
            at,
            structured_error=structured_error,
            resume_stage=resume_stage,
            attempt_count=attempt_count,
        )
        self._connection.execute(
            "UPDATE jobs SET state = %s, started_at = %s, finished_at = %s, "
            "structured_error = %s, resume_stage = %s, attempt_count = %s WHERE job_id = %s",
            (
                moved.state.value,
                moved.started_at,
                moved.finished_at,
                _json(moved.structured_error) if moved.structured_error is not None else None,
                moved.resume_stage,
                moved.attempt_count,
                job_id,
            ),
        )
        return moved

    def complete(self, job_id: str, idempotency_key: str, proposed: Run) -> Run:
        # Pre-checked here, and re-checked by `job_complete`. Not belt-and-braces for its own
        # sake: the two answer different questions. The function holds the line against every
        # writer, including ones that never touch this class; these raise the *typed* errors the
        # in-memory store raises, so a caller can catch `IdempotencyKeyMismatch` without knowing
        # which backend it is talking to. A driver exception with a matching message is not the
        # same thing -- callers would have to parse strings to tell the cases apart.
        job = self.get(job_id)
        if job is None:
            raise JobStoreError(f"job {job_id} does not exist")
        if job.idempotency_key != idempotency_key:
            raise IdempotencyKeyMismatch(
                f"completion for job {job_id} carries idempotency key {idempotency_key} but the "
                f"job was submitted under {job.idempotency_key}; this callback belongs to a "
                "different submission"
            )
        if proposed.job_id != job_id:
            raise JobStoreError(
                f"run {proposed.run_id} names job {proposed.job_id} but is being used to "
                f"complete {job_id}"
            )
        if proposed.project_id != job.project_id:
            raise JobStoreError(
                f"run {proposed.run_id} is in project {proposed.project_id} but job {job_id} is "
                f"in {job.project_id}; a run scoped away from its job escapes SEC-002 through "
                "the side door"
            )

        try:
            row = self._connection.execute(
                "SELECT job_complete(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    job_id,
                    idempotency_key,
                    proposed.run_id,
                    proposed.project_id,
                    proposed.capability_id,
                    proposed.backend_id,
                    proposed.conditions_schema_version,
                    proposed.code_provenance,
                    proposed.status.value,
                    list(proposed.output_artifacts),
                    proposed.start_time,
                    proposed.end_time,
                    proposed.reproducibility_manifest_hash,
                    proposed.end_time,
                ),
            ).fetchone()
        except Exception as exc:
            raise JobStoreError(f"job_complete refused to complete {job_id}: {exc}") from exc
        if row is None:  # pragma: no cover - the function always returns a run_id or raises
            raise JobStoreError(f"job_complete returned nothing for job {job_id}")
        authoritative_id = str(row[0])
        run = self.get_run(authoritative_id)
        if run is None:  # pragma: no cover
            raise JobStoreError(
                f"job_complete returned run {authoritative_id} which does not exist"
            )
        return run

    # -- runs ---------------------------------------------------------------

    def get_run(self, run_id: str) -> Run | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_RUN_COLUMNS)} FROM runs WHERE run_id = %s", (run_id,)
        ).fetchone()
        return None if row is None else _run_from_row(row)

    def run_for_job(self, job_id: str) -> Run | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_RUN_COLUMNS)} FROM runs WHERE job_id = %s", (job_id,)
        ).fetchone()
        return None if row is None else _run_from_row(row)

    def add_run(self, run: Run) -> Run:
        """Record a Run that did not come from a job completion callback.

        Exists for the ingestion path, where this process *is* the executor: there is no external
        callback to be idempotent about, and requiring one would mean inventing a fake delivery.
        The `runs.job_id UNIQUE` constraint still holds, so this cannot be used to give a job a
        second Run -- it is a different entry point, not a weaker one.
        """
        self._connection.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, domain, "
            "trace_id, input_artifacts, input_parameters, conditions, conditions_schema_version, "
            "environment, code_provenance, backend_validity, status, warnings, output_artifacts, "
            "numerical_array_refs, start_time, end_time, reproducibility_manifest_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s)",
            (
                run.run_id,
                run.job_id,
                run.project_id,
                run.capability_id,
                run.backend_id,
                run.domain,
                run.trace_id,
                list(run.input_artifacts),
                _json(run.input_parameters),
                _json(run.conditions),
                run.conditions_schema_version,
                _json(run.environment),
                run.code_provenance,
                _json(run.backend_validity),
                run.status.value,
                list(run.warnings),
                list(run.output_artifacts),
                list(run.numerical_array_refs),
                run.start_time,
                run.end_time,
                run.reproducibility_manifest_hash,
            ),
        )
        self._connection.execute(
            "UPDATE jobs SET state = 'SUCCEEDED', result_run_id = %s, finished_at = %s, "
            "started_at = COALESCE(started_at, %s) WHERE job_id = %s",
            (run.run_id, run.end_time, run.start_time, run.job_id),
        )
        return run

    # -- projections --------------------------------------------------------

    def active_depth(self, project_id: str) -> int:
        row = self._connection.execute(
            "SELECT count(*) FROM jobs WHERE project_id = %s "
            "AND state IN ('QUEUED', 'RUNNING', 'WAITING_RESOURCE')",
            (project_id,),
        ).fetchone()
        return 0 if row is None else cast(int, row[0])

    def list_active(self, project_id: str) -> tuple[Job, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM jobs WHERE project_id = %s "
            "AND state IN ('QUEUED', 'RUNNING', 'WAITING_RESOURCE') ORDER BY submitted_at",
            (project_id,),
        ).fetchall()
        return tuple(_job_from_row(row) for row in rows)


def _json(value: object) -> str:
    return json.dumps(value)


def _job_from_row(row: tuple[object, ...]) -> Job:
    values = dict(zip(_JOB_COLUMNS, row, strict=True))
    return Job.model_validate(values)


def _run_from_row(row: tuple[object, ...]) -> Run:
    values = dict(zip(_RUN_COLUMNS, row, strict=True))
    for name in ("input_artifacts", "warnings", "output_artifacts", "numerical_array_refs"):
        values[name] = tuple(values[name] or ())  # type: ignore[arg-type]
    return Run.model_validate(values)


__all__ = [
    "IdempotencyKeyMismatch",
    "InMemoryJobStore",
    "JobStore",
    "JobStoreError",
    "SqlJobStore",
]
