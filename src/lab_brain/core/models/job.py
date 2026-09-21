"""Jobs and Runs — the suspend/resume contract (OPS-001, §10.7, §12.4, §17.16, §17.4).

WHY A JOB IS NOT A FUNCTION CALL.

A long-running tool call has a property an in-process call does not: the process that started it
may not be the process that learns it finished. Between the two there is a callback, and a
callback is delivered by something that retries. §12.4 states the consequence as one sentence --
"所有外部 callback 與 retry 必須 idempotent" -- and §10.7 names the mechanism: `idempotency_key`
防止重複 callback 產生第二個 run.

So the entity that survives is the **Job**, and the thing a Job is accountable for producing is
exactly one logical **Run**. Everything in this module follows from that sentence.

WHY "EXACTLY ONE RUN" IS A STORAGE INVARIANT AND NOT A PYTHON ONE.

The obvious implementation is to check whether a Run already exists and skip if it does. That is
correct for one process and wrong for two: both read "no run", both write, and the job has two.
Nothing in the record afterwards says which one the scientific evidence should cite, and both are
internally consistent. The check has to be the database's -- `runs.job_id` is UNIQUE, and the
second writer loses the insert rather than the race.

This is the same reasoning ADR-0010 and `v3.3-a18` applied to evidence identity, arriving at a
different answer for a different reason. There the identity was *derived*, so a duplicate write is
a no-op and idempotency is free. Here the Run's identity is **event-addressed** -- it is minted
when a completion arrives -- so idempotency has to be bought with a constraint.

TWO IDEMPOTENCIES THAT ARE NOT THE SAME IDEMPOTENCY. Worth stating because conflating them is the
mistake this module is most likely to invite:

    storage idempotency   same bytes -> same derived identity -> a second write is a no-op.
                          M1-P1 locked this. It needs no "have I seen this" branch and must not
                          grow one.
    callback idempotency  the same completion delivered twice -> one Run. This is that, and it is
                          a different invariant with a different mechanism.

A Job is NOT the mechanism by which duplicate ingestion is deduplicated. Ingesting the same bytes
under two different Jobs correctly produces one Artifact and one set of EvidenceUnits, because the
identities are derived -- not because a Job noticed.

WHAT DOES NOT LIVE HERE. Retry *policy* evaluation (UX-002 owns when a class of error may be
retried), budget (COST-001's gate decides whether an attempt may be afforded), and the ingestion
stages themselves. This module owns the lifecycle and the identity of its Run, and nothing else.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel


class JobState(StrEnum):
    """§17.16's state vocabulary, exactly.

    ``WAITING_RESOURCE`` is the one worth explaining: §10.7 introduces it for license/seat
    contention, and it is deliberately not a flavour of QUEUED. A job that has never started and a
    job that started, needed a Lumerical seat and parked are different operational situations --
    the first is waiting for the scheduler, the second is waiting for the world. UX-007 surfaces
    seat exhaustion as *degraded availability* rather than as an error, and it can only do that if
    the two are distinguishable in the record.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: States from which no further transition is legal. A terminal job is a finished fact.
TERMINAL_JOB_STATES: frozenset[JobState] = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
)

#: States UX-001's derivation reads as "still moving" (§17.22: QUEUED/RUNNING/WAITING_RESOURCE).
ACTIVE_JOB_STATES: frozenset[JobState] = frozenset(
    {JobState.QUEUED, JobState.RUNNING, JobState.WAITING_RESOURCE}
)

#: The legal transition graph. Declared as data rather than as a chain of ``if``s so that the SQL
#: trigger in `006_jobs_runs.sql` and this model can be compared against one table by a test --
#: two hand-written copies of a state machine drift, and the drift shows up as a job that is
#: RUNNING in PostgreSQL and QUEUED in memory.
JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED, JobState.FAILED}),
    # RUNNING -> WAITING_RESOURCE is the suspend edge; the reverse is resume.
    JobState.RUNNING: frozenset(
        {
            JobState.WAITING_RESOURCE,
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.WAITING_RESOURCE: frozenset({JobState.RUNNING, JobState.FAILED, JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


class RunStatus(StrEnum):
    """§17.4's ``status``. A Run is the record of one backend execution.

    ``FAILED`` is kept: §17.4 requires a manifest per execution, and an execution that failed
    still happened. Discarding it would make "this capability fails on these inputs" unanswerable,
    which is exactly the failure-analysis material §6.10 is about.
    """

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class JobTransitionError(ValueError):
    """An illegal lifecycle move. Raised, never returned as a bool.

    A caller that gets ``False`` back tends to continue; a caller that gets an exception does not.
    The moves this refuses are all cases where continuing writes a record that contradicts itself.
    """


class Job(CoreModel):
    """§17.16, field-for-field.

    ``project_id`` is present and §17.16 does not declare it, which is the kind of addition
    ADR-0010 exists to be suspicious of -- so the reason is stated rather than assumed. SEC-002
    scopes every read by project membership, and a Job surfaces through UX-001's IngestionItem and
    UX-003's error lookup, both of which are project-scoped by requirement. §17.16's block reaches
    the project through ``episode_id``, but Episodes are not built (§17.3 is M1's orchestration
    half and nothing in this slice creates one), so a Job that could only be scoped transitively
    could not be scoped at all. Recorded in `schema_drift.UNBOUND` rather than bound field-for-field
    for this reason.
    """

    job_id: str
    project_id: str
    episode_id: str | None = None
    capability_id: str
    trace_id: str

    #: §10.7's duplicate-callback defence. Unique per project in the table; see the module
    #: docstring for why the constraint is the mechanism and a Python check is not.
    idempotency_key: str

    state: JobState = JobState.QUEUED
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)

    submitted_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None

    retry_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_policy: dict[str, Any] = Field(default_factory=dict)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)

    #: Set exactly once, when the job's Run is created. Write-once is enforced by the table.
    result_run_id: str | None = None

    #: §10.7's "structured_error 供 ErrorRecord 投影". Kept as the structured payload rather than a
    #: rendered string: UX-002 classifies from it and UX-006 forbids rendering text anywhere except
    #: the catalog, so a message stored here would be a second, unversioned source of user text.
    structured_error: dict[str, Any] | None = None

    #: The stage a resumable job is parked at, so UX-004's retry resumes rather than restarts.
    #: §17.22's StageResult vocabulary; typed as a string because the stage enum lives with the
    #: ingestion surface and importing it here would point core at the surface that projects it.
    resume_stage: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.state in TERMINAL_JOB_STATES and self.finished_at is None:
            raise ValueError(
                f"job {self.job_id} is {self.state.value} with no finished_at; a terminal job "
                "with no end is indistinguishable from one still running"
            )
        if self.state not in TERMINAL_JOB_STATES and self.finished_at is not None:
            raise ValueError(
                f"job {self.job_id} is {self.state.value} but carries finished_at; a job that "
                "finished has a terminal state, and a contradiction here makes queue depth wrong"
            )
        if self.state is JobState.QUEUED and self.started_at is not None:
            raise ValueError(
                f"job {self.job_id} is QUEUED but has started_at; QUEUED means not yet started"
            )
        if self.started_at is not None and self.started_at < self.submitted_at:
            raise ValueError(f"job {self.job_id} started before it was submitted")
        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError(f"job {self.job_id} finished before it started")
        if self.result_run_id is not None and self.state is not JobState.SUCCEEDED:
            raise ValueError(
                f"job {self.job_id} is {self.state.value} but names result_run_id "
                f"{self.result_run_id}; a Run is the product of a job that succeeded, and "
                "attaching one to a failed job makes the failure cite its own output as evidence"
            )
        if self.attempt_count > self.max_attempts:
            raise ValueError(
                f"job {self.job_id} has attempt_count {self.attempt_count} over max_attempts "
                f"{self.max_attempts}; UX-002 stops retrying at max_attempts, so exceeding it "
                "means the bound was not enforced"
            )
        return self

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_JOB_STATES

    @property
    def is_active(self) -> bool:
        """Whether UX-001 should read this job as still moving (§17.22)."""
        return self.state in ACTIVE_JOB_STATES

    @property
    def attempts_remaining(self) -> int:
        """How many more attempts UX-002's bounded retry may make."""
        return max(0, self.max_attempts - self.attempt_count)

    def transitioned(
        self,
        state: JobState,
        at: dt.datetime,
        *,
        result_run_id: str | None = None,
        structured_error: dict[str, Any] | None = None,
        resume_stage: str | None = None,
        attempt_count: int | None = None,
    ) -> Job:
        """A copy of this job in ``state``. Frozen model, so a move writes a new value.

        Validated through ``model_validate`` rather than ``model_copy`` for the reason
        ``ExecutionSpan.closed`` gives: ``model_copy`` skips validation, so the one method whose
        job is to produce a valid transition would be the one path that could produce an invalid
        one.
        """
        allowed = JOB_TRANSITIONS[self.state]
        if state not in allowed:
            permitted = ", ".join(sorted(s.value for s in allowed)) or "nothing (terminal)"
            raise JobTransitionError(
                f"job {self.job_id} cannot move {self.state.value} -> {state.value}; "
                f"permitted from {self.state.value}: {permitted}"
            )
        payload = dict(self.model_dump())
        payload["state"] = state
        if state is JobState.RUNNING and self.started_at is None:
            payload["started_at"] = at
        payload["finished_at"] = at if state in TERMINAL_JOB_STATES else None
        if result_run_id is not None:
            payload["result_run_id"] = result_run_id
        if structured_error is not None:
            payload["structured_error"] = structured_error
        if resume_stage is not None:
            payload["resume_stage"] = resume_stage
        if attempt_count is not None:
            payload["attempt_count"] = attempt_count
        return Job.model_validate(payload)


class Run(CoreModel):
    """§17.4's Run Manifest.

    NO DOMAIN FIELDS. §17.4 states it outright: core MUST NOT hard-code solver_settings /
    mesh_convergence / calibration. Those arrive through ``backend_validity`` and ``environment``,
    which are opaque here on purpose -- the moment core declares a ``mesh_convergence`` column,
    §24.1's boundary is gone and EXT-001 has something real to detect.

    ``job_id`` is required and not optional. §17.4 declares it, and a Run with no Job is an
    execution nobody can attribute to a submission -- which is precisely the state the duplicate
    callback would create.
    """

    run_id: str
    job_id: str
    project_id: str
    capability_id: str
    backend_id: str
    domain: str | None = None
    trace_id: str

    input_artifacts: tuple[str, ...] = ()
    input_parameters: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str

    environment: dict[str, Any] = Field(default_factory=dict)
    code_provenance: str
    backend_validity: dict[str, Any] = Field(default_factory=dict)

    status: RunStatus
    warnings: tuple[str, ...] = ()

    #: EVI-009's "Run provenance must trace to produced Artifact(s)". A SUCCEEDED run that
    #: produced nothing is refused below: an execution that yielded no artifact cannot back a
    #: MEASURED or SIMULATED attestation, and admitting one would let a reference resolve to a
    #: record with nothing behind it.
    output_artifacts: tuple[str, ...] = ()
    numerical_array_refs: tuple[str, ...] = ()

    start_time: dt.datetime
    end_time: dt.datetime
    reproducibility_manifest_hash: str

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.end_time < self.start_time:
            raise ValueError(f"run {self.run_id} ends before it starts")
        if self.status is RunStatus.SUCCEEDED and not self.output_artifacts:
            raise ValueError(
                f"run {self.run_id} is SUCCEEDED with no output_artifacts; EVI-009 requires a "
                "MEASURED/SIMULATED attestation's run reference to trace to produced artifacts, "
                "and a successful run that produced nothing cannot support one"
            )
        for name, values in (
            ("input_artifacts", self.input_artifacts),
            ("output_artifacts", self.output_artifacts),
            ("numerical_array_refs", self.numerical_array_refs),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"run {self.run_id} lists a duplicate in {name}")
        return self

    def produced(self, artifact_id: str) -> bool:
        """Whether this run is provenance for ``artifact_id`` (EVI-009)."""
        return artifact_id in self.output_artifacts


__all__ = [
    "ACTIVE_JOB_STATES",
    "JOB_TRANSITIONS",
    "TERMINAL_JOB_STATES",
    "Job",
    "JobState",
    "JobTransitionError",
    "Run",
    "RunStatus",
]
