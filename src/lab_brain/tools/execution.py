"""Seat, execute, validate, mint the Run — in that order (SIM-001, OPS-001, §10.7).

THE ORDER IS THE CONTRACT, and each step exists because skipping it produces a specific wrong
record:

    0. bind the scope        the request and the Job must be the same execution (`scope.py`).
    1. RUNNING               a worker has picked the job up; the seat request is its first act.
    2. acquire a seat        no seat -> WAITING_RESOURCE. The Job survives; nothing executed.
    3. execute               the provider adapter's only line of this function.
    4. validate validity     SIM-001. An incomplete validity record never becomes a manifest.
    5. mint the Run          through `JobStore.complete`, so a duplicate callback yields one Run.
    6. release the seat      in a `finally`, so a raising backend does not leak the pool.

STEP 0 IS NUMBERED FROM ZERO BECAUSE IT IS NOT A STEP OF THE EXECUTION; it is the question of
whether this execution is entitled to happen at all. Everything from step 1 onwards is visible to
someone else -- a durable row, a seat out of a finite pool, a solver -- so the last moment at which
a wrong answer costs nothing is before step 1.

STEP 1 BEFORE STEP 2, AND AN EARLIER VERSION OF THIS FILE HAD IT THE OTHER WAY ROUND. The argument
for acquiring first was that a job marked RUNNING and then refused a seat has told every reader
that execution began. §17.16's declared transition graph says otherwise, and it is right:
WAITING_RESOURCE is reachable only from RUNNING -- `JOB_TRANSITIONS` calls that edge the suspend
edge and its reverse the resume -- because a job nobody has picked up is QUEUED, waiting for the
*scheduler*, and a job waiting for a seat is waiting for the *world*. §17.16's own docstring draws
exactly that distinction, and collapsing the two would make queue depth unreadable.

So the worker takes the job (RUNNING), asks for a seat, and parks if there is none. What the
earlier ordering was protecting -- that waiting must not look like failing -- is preserved by the
things that actually carry it: the state is WAITING_RESOURCE rather than FAILED, `attempt_count`
is untouched, and §17.24 reads the parked job as degraded availability.

STEP 4 BEFORE STEP 5 IS SIM-001. "Refuse to promote to formal evidence" is stronger when the
manifest is never written than when it is written and filtered afterwards: a Run in the table is a
Run something will eventually cite, and the filter is one query away from being forgotten.

STEP 6 IN A `finally` IS THE ONE THAT IS EASY TO GET WRONG, and its failure mode is silent. A
backend that raises leaves the seat held, the pool drains one lease per crash, and the symptom --
every subsequent job parking in WAITING_RESOURCE -- looks exactly like a busy licence server.

WHAT THIS DOES NOT DO. It does not budget, does not open a span and does not write evidence.
`core.dispatch.dispatch_action` owns the first two and admission owns the third; a runner that also
gated cost would be a second entrance to the seam that gates external effects.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from lab_brain.core.models.capability import Capability
from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.models.job import Job, JobState, Run
from lab_brain.core.repositories.jobs import JobStore
from lab_brain.tools.extraction import ExtractionSource, NumericalSeries
from lab_brain.tools.resources import (
    ResourceBroker,
    ResourceDemand,
    ResourceLease,
    ResourceUnavailable,
)
from lab_brain.tools.scope import ExecutionScope, require_same_scope
from lab_brain.tools.simulation import (
    BackendExecution,
    BackendValidityRegistry,
    SimulationBackend,
    SimulationRequest,
    manifest_for,
    validate_backend_validity,
)


@dataclass(frozen=True)
class WaitingForResource:
    """The job is parked. **Not a failure** -- see `resources.ResourceUnavailable`.

    Carries the Job so the caller cannot accidentally read a stale one, and the contention numbers
    so a UX-007 health view does not have to ask the broker again.
    """

    job: Job
    resource_id: str
    requested: int
    available: int

    @property
    def executed(self) -> bool:
        return False


@dataclass(frozen=True)
class Executed:
    """The backend ran and the Run is durable."""

    job: Job
    run: Run
    execution: BackendExecution
    lease: ResourceLease | None

    @property
    def executed(self) -> bool:
        return True


ExecutionOutcome = Executed | WaitingForResource


def simulated_source(executed: Executed) -> ExtractionSource:
    """The `ExtractionSource` for a simulation, derived from the Run that was actually minted.

    DERIVED, NOT PASSED IN, and that is the EVI-009 half of the shared extractor contract. A caller
    assembling its own source could name any run id; this one can only name the Run that
    `JobStore.complete` returned, so a simulated extraction cannot be attributed to an execution
    that did not produce it.

    The validity schema reference comes off the manifest rather than from an argument, for the same
    reason: `manifest_for` writes `schema_ref` into `backend_validity` precisely so a reloaded Run
    carries which schema its validity fields satisfy, and re-supplying it here would let a caller
    claim a different one.
    """
    run = executed.run
    schema_ref = run.backend_validity.get("schema_ref")
    return ExtractionSource(
        modality=EpistemicType.SIMULATED,
        run_id=run.run_id,
        project_id=run.project_id,
        backend_id=run.backend_id,
        backend_version=str(run.environment.get("backend_version", "")),
        conditions=dict(run.conditions),
        conditions_schema_version=run.conditions_schema_version,
        backend_validity_schema=str(schema_ref) if schema_ref is not None else None,
        backend_validity={k: v for k, v in run.backend_validity.items() if k != "schema_ref"},
    )


class ResourceBindingError(RuntimeError):
    """The Job and the request disagree about what resource this execution needs (§10.7, §17.16).

    A wiring error rather than contention, and the distinction matters for the same reason it does
    in `resources.py`: a job parked for contention resumes when a seat frees, and a job whose
    declared requirement contradicts its request will never resume correctly no matter how many
    seats appear.
    """


def bound_demand(job: Job) -> ResourceDemand | None:
    """The canonical requirement, reconstructed from the durable Job (§17.16).

    THIS IS WHAT A RELOADED `WAITING_RESOURCE` JOB IS ASKED. §10.7 requires a long-running Job to
    carry `resource_requirements (including license seat)`, and the reason is exactly this call: a
    resumer in a different process has the Job row and nothing else, and "what is this job waiting
    for" has to be answerable from it.
    """
    return ResourceDemand.from_requirements(dict(job.resource_requirements))


def submit_simulation_job(
    *,
    jobs: JobStore,
    job: Job,
    demand: ResourceDemand | None,
    capability: Capability,
) -> Job:
    """Submit a simulation Job with its ResourceDemand BOUND to the durable record.

    THE DEFECT THIS CLOSES. The requirement used to live only on `SimulationRequest.resource_demand`
    -- an in-flight object -- while the Job was submitted with `resource_requirements = {}`. So a
    reloaded WAITING_RESOURCE Job could not say what it was waiting for, and §17.16's canonical
    field was empty on every simulation this system ran.

    THE CAPABILITY IS CHECKED HERE because this is where it is selected. §17.18's
    `license_constraints` says which seats an action contends for; a demand naming a different
    resource would park the job behind a pool the capability has nothing to do with, and a
    seat-requiring capability dispatched with no demand would take a seat nobody accounted for.
    Both are refused, and both are refusals a later stage could not make -- by then the capability
    is a string on a Run.
    """
    if job.capability_id != capability.capability_id:
        raise ResourceBindingError(
            f"job {job.job_id} names capability {job.capability_id} but is being submitted against "
            f"{capability.capability_id}; the descriptor whose license constraints are being "
            "checked must be the one the job will execute"
        )
    declared = tuple(capability.license_constraints)
    if demand is None:
        if declared:
            raise ResourceBindingError(
                f"capability {capability.capability_id} declares license constraints "
                f"{list(declared)} and job {job.job_id} was submitted with no ResourceDemand. The "
                "execution would take a seat nobody accounted for, and §10.7's WAITING_RESOURCE "
                "would never be reached because nothing asked for one"
            )
        return jobs.submit(job)

    if demand.resource_id not in declared:
        raise ResourceBindingError(
            f"job {job.job_id} demands {demand.resource_id!r}, which capability "
            f"{capability.capability_id} does not declare among its license constraints "
            f"{list(declared)}. A demand for a resource the action does not contend for parks the "
            "job behind a pool that will never release it on this action's account (§17.18)"
        )
    return jobs.submit(job.model_copy(update={"resource_requirements": demand.as_requirements()}))


def _require_bound_demand(job: Job, request: SimulationRequest) -> ResourceDemand | None:
    """The request may restate the Job's requirement; it may not contradict or replace it.

    THE DURABLE RECORD WINS, and that is the whole point of binding it. A resumer is a new caller
    in a new process, and a caller that could supply a different demand could move a parked job to
    a different pool -- so what the Job says is the requirement, and the request is checked against
    it rather than trusted.
    """
    parked = bound_demand(job)
    declared = request.resource_demand

    if declared is None:
        if parked is not None:
            raise ResourceBindingError(
                f"job {job.job_id} carries a resource requirement for {parked.resource_id} but the "
                "simulation request declares none. Executing would run without the seat the job "
                "was admitted on (§10.7)"
            )
        return None

    if parked is None:
        raise ResourceBindingError(
            f"simulation request {request.request_id} demands {declared.seats} seat(s) of "
            f"{declared.resource_id!r} but job {job.job_id} carries no resource_requirements. "
            "§17.16 makes the requirement part of the Job; a demand that exists only on the "
            "in-flight request leaves a reloaded WAITING_RESOURCE job unable to say what it is "
            "waiting for -- submit through `submit_simulation_job`"
        )
    if parked.resource_id != declared.resource_id:
        raise ResourceBindingError(
            f"job {job.job_id} is bound to resource {parked.resource_id!r} and the request demands "
            f"{declared.resource_id!r}. A resumer that could redirect a parked job to a different "
            "pool could take a seat the job was never admitted against"
        )
    if parked.seats != declared.seats:
        raise ResourceBindingError(
            f"job {job.job_id} is bound to {parked.seats} seat(s) of {parked.resource_id} and the "
            f"request demands {declared.seats}. The seat count is part of the requirement: a "
            "resume that asked for more would exceed what the job was queued against"
        )
    # The DURABLE one is returned, not the request's. They agree on identity and count; returning
    # the stored record means the execution runs against what the Job says even if some other field
    # of the in-flight demand drifts.
    return parked


def run_simulation(
    *,
    request: SimulationRequest,
    backend: SimulationBackend,
    jobs: JobStore,
    broker: ResourceBroker | None,
    validity: BackendValidityRegistry,
    run_id: str,
    lease_id: str,
    idempotency_key: str,
    now: Callable[[], dt.datetime],
    domain: str | None = None,
    reproducibility_manifest_hash: str,
) -> ExecutionOutcome:
    """Execute ``request`` on ``backend``, or park the Job if there is no seat.

    ``broker`` may be `None` only when the request declares no resource demand. A request that
    names a resource with no broker to ask fails closed by raising -- an unverifiable seat is not
    a held seat, the same rule the admission gate applies to an unverifiable reference.

    THE REQUIREMENT COMES OFF THE JOB, not off the request. See `_require_bound_demand`.
    """
    lease: ResourceLease | None = None

    # A TERMINAL job is not moved, and that is the duplicate-callback path rather than an edge
    # case. §12.4 requires a redelivered completion to be idempotent; `JobStore.complete` already
    # makes it so by returning the authoritative Run, but a transition to RUNNING would raise
    # `JobTransitionError` before it was ever reached -- turning a correct at-least-once delivery
    # into an error the deliverer would then retry.
    current = jobs.get(request.job_id)
    if current is None:
        raise ResourceBindingError(
            f"simulation request {request.request_id} names job {request.job_id}, which does not "
            "resolve. §17.16 makes the Job the durable record of the submission; executing against "
            "one that does not exist would produce a Run nobody can attribute"
        )
    # STEP 0, AND IT IS STEP 0 BECAUSE EVERY LATER STEP IS IRREVERSIBLE. The Job resolved; that
    # only proves the id exists. Whether it is THIS execution's job is a different question, and
    # until it is answered nothing below may run: `jobs.transition` mutates a durable row,
    # `broker.acquire` takes a seat out of a finite pool, and `backend.execute` reaches a
    # simulator. All three are visible to someone else.
    #
    # `JobStore.complete` DOES detect a project mismatch, and that is not sufficient. By the time it
    # speaks the Job has been moved to RUNNING, a licence seat has been held, and the backend has
    # run to completion -- so the refusal it issues is a refusal to *record* an execution that
    # already happened, inside a project that never admitted it. The requirement is that the
    # execution not happen, which can only be decided here.
    require_same_scope(
        ExecutionScope(
            layer="SimulationRequest",
            project_id=request.project_id,
            trace_id=request.trace_id,
            capability_id=request.capability_id,
        ),
        ExecutionScope(
            layer="Job",
            project_id=current.project_id,
            trace_id=current.trace_id,
            capability_id=current.capability_id,
        ),
        detail=(
            f"simulation request {request.request_id} would have executed against job "
            f"{current.job_id}, which was submitted under a different scope. §17.16 makes the Job "
            "the durable record of what was admitted, and a Run minted here would be attributed to "
            "it: the job is left exactly as it was found, no seat is taken and the backend is not "
            "entered"
        ),
    )
    demand = _require_bound_demand(current, request)
    already_finished = current.is_terminal
    if not already_finished and current.state is not JobState.RUNNING:
        jobs.transition(request.job_id, JobState.RUNNING, now())

    if demand is not None and not already_finished:
        if broker is None:
            raise ResourceUnavailable(demand.resource_id, demand.seats, 0, 0)
        try:
            lease = broker.acquire(
                demand.resource_id,
                job_id=request.job_id,
                seats=demand.seats,
                now=now(),
                lease_id=lease_id,
            )
        except ResourceUnavailable as unavailable:
            # §10.7: WAITING_RESOURCE, not FAILED, and `attempt_count` is untouched. The job keeps
            # its identity and its place; `resume_stage` records what it is waiting for so a
            # resumer does not have to re-derive it.
            parked = jobs.transition(
                request.job_id,
                JobState.WAITING_RESOURCE,
                now(),
                resume_stage=f"AWAITING_RESOURCE:{demand.resource_id}",
            )
            return WaitingForResource(
                job=parked,
                resource_id=unavailable.resource_id,
                requested=unavailable.requested,
                available=unavailable.available,
            )

    try:
        execution = backend.execute(request)

        # SIM-001, before the manifest exists. See the module docstring for why the order matters.
        validate_backend_validity(execution, validity)

        proposed = manifest_for(
            run_id=run_id,
            request=request,
            execution=execution,
            domain=domain,
            reproducibility_manifest_hash=reproducibility_manifest_hash,
        )
        # `complete` returns the AUTHORITATIVE Run: on a redelivered callback the proposal is
        # discarded and the existing Run comes back, so a duplicate completion produces no second
        # Run (§12.4, OPS-001). The caller must use what comes back.
        run = jobs.complete(request.job_id, idempotency_key, proposed)
        job = jobs.get(request.job_id)
        assert job is not None  # `complete` succeeded, so the job exists
        return Executed(job=job, run=run, execution=execution, lease=lease)
    finally:
        if lease is not None and broker is not None:
            broker.release(lease.lease_id, now=now())


def series_by_name(execution: BackendExecution) -> dict[str, NumericalSeries]:
    """The execution's numerical payload, keyed for an extractor. Deterministic ordering."""
    return {series.name: series for series in execution.series}


__all__ = [
    "Executed",
    "ExecutionOutcome",
    "ResourceBindingError",
    "WaitingForResource",
    "bound_demand",
    "run_simulation",
    "series_by_name",
    "simulated_source",
    "submit_simulation_job",
]
