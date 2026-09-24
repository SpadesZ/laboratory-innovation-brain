"""T-OPS-001's §10.7 half — the resource requirement is bound to the durable Job (§17.16).

    §10.7   長時 tool 與外部動作必須 Job 化: resource_requirements(含 license seat)
    §17.16  Job { ..., retry_policy{}, timeout_policy{}, resource_requirements{}, ... }

THE DEFECT. `resource_requirements{}` is part of §17.16's canonical Job, and §10.7 says a
long-running Job carries it "including license seat". The seat requirement lived only on
`SimulationRequest.resource_demand` -- an in-flight object -- while the durable Job was submitted
with `resource_requirements = {}`. So a reloaded WAITING_RESOURCE Job could not answer the one
question a resumer in another process actually has: what is this waiting for.

THE DURABLE RECORD WINS. A resumer is a new caller, and a caller that could supply a different
demand could move a parked job to a different pool -- so what the Job says is the requirement, and
the request is checked against it rather than trusted. Five ways that check fails closed, one test
each; the paired positive controls are here too, because "refuse everything" would satisfy all five.

The Capability-side half -- a demand naming a resource the descriptor does not declare -- lives in
`tests/unit/test_capability_planning.py`, which owns VER-002's marker pair.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models.capability import ActionType, Capability
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.jobs import InMemoryJobStore
from lab_brain.domains.silicon_photonics import backend_validity
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF
from lab_brain.tool_providers.lumerical.mock import MockChargeAcBackend
from lab_brain.tools.execution import (
    ResourceBindingError,
    bound_demand,
    run_simulation,
    submit_simulation_job,
)
from lab_brain.tools.resources import InMemoryResourceBroker, ResourceDemand, ResourceLease
from lab_brain.tools.scope import ExecutionScopeMismatch
from lab_brain.tools.simulation import (
    BackendExecution,
    BackendValidityRegistry,
    SimulationRequest,
)

pytestmark = [pytest.mark.requirement("OPS-001"), pytest.mark.spec_test("T-OPS-001")]

NOW = dt.datetime(2026, 9, 24, 10, 0, tzinfo=dt.UTC)
PROJECT = "prj:sp"
ARTIFACT = "art:sha256:" + "ab" * 32
RESOURCE = "license:sp-charge-seat"


def _validity_registry() -> BackendValidityRegistry:
    registry = BackendValidityRegistry()
    registry.register(backend_validity.schema())
    return registry


def _request(**overrides: object) -> SimulationRequest:
    payload: dict[str, object] = {
        "request_id": "req:1",
        "project_id": PROJECT,
        "trace_id": "trc:1",
        "job_id": "job:1",
        "capability_id": "cap:sp.charge_ac_sweep",
        "input_artifacts": (ARTIFACT,),
        "conditions": {
            "bias_v": "-1.0",
            "frequency_hz": "1000000",
            "device_length_um": "500",
        },
        "conditions_schema_version": SCHEMA_REF,
        "resource_demand": ResourceDemand(resource_id=RESOURCE, seats=1, estimated_seat_s=30),
    }
    payload.update(overrides)
    return SimulationRequest.model_validate(payload)


def _broker(seats: int = 1) -> InMemoryResourceBroker:
    return InMemoryResourceBroker({RESOURCE: seats})


def _capability(**overrides: object) -> Capability:
    payload: dict[str, object] = {
        "capability_id": "cap:sp.charge_ac_sweep",
        "domain": "silicon_photonics",
        "action_type": ActionType.SIMULATION,
        "backend_id": "sp.charge.ac",
        "produces": ("sp.small_signal_impedance",),
        "authority_class": "SIM_STANDARD",
        "license_constraints": (RESOURCE,),
        "estimate_cost_contract": "cost:sp.charge_ac_sweep@1.0.0",
        "version": "1.0.0",
    }
    payload.update(overrides)
    return Capability.model_validate(payload)


def _demand(seats: int = 1, resource: str = RESOURCE) -> ResourceDemand:
    return ResourceDemand(resource_id=resource, seats=seats, estimated_seat_s=30)


def _store(demand: ResourceDemand | None = None) -> InMemoryJobStore:
    store = InMemoryJobStore()
    submit_simulation_job(
        jobs=store,
        job=Job(
            job_id="job:1",
            project_id=PROJECT,
            capability_id="cap:sp.charge_ac_sweep",
            trace_id="trc:1",
            idempotency_key="idem:1",
            submitted_at=NOW,
        ),
        demand=_demand() if demand is None else demand,
        capability=_capability(),
    )
    return store


# ---------------------------------------------------------------------------
# §10.7 / §17.16 — the requirement is bound to the JOB, not to the request
#
# THE DEFECT. `resource_requirements{}` is part of §17.16's canonical Job and §10.7 says a
# long-running Job carries it "including license seat". The seat requirement used to live only on
# `SimulationRequest.resource_demand` -- an in-flight object -- while the durable Job was submitted
# with `resource_requirements = {}`. So a reloaded WAITING_RESOURCE Job could not answer the one
# question a resumer in another process actually has: what is this waiting for.
# ---------------------------------------------------------------------------


def test_the_submitted_job_carries_the_canonical_resource_demand():
    """The positive control, and the shape of it is the point: `as_requirements()` exactly.

    Compared against the canonical serialisation rather than field-by-field, so a Job written with
    a differently-shaped payload -- which `from_requirements` would silently read as *no demand* --
    fails here instead of at a resume nobody is watching.
    """
    job = _store().get("job:1")
    assert job is not None
    assert job.resource_requirements == _demand().as_requirements()
    assert bound_demand(job) == _demand()


def test_a_request_declaring_a_demand_against_an_unbound_job_is_refused():
    """Case 1. The in-flight demand exists and the durable record does not."""
    store = InMemoryJobStore()
    store.submit(
        Job(
            job_id="job:1",
            project_id=PROJECT,
            capability_id="cap:sp.charge_ac_sweep",
            trace_id="trc:1",
            idempotency_key="idem:1",
            submitted_at=NOW,
        )
    )
    with pytest.raises(ResourceBindingError, match="carries no resource_requirements"):
        run_simulation(
            request=_request(),
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=store,
            broker=_broker(),
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )


def test_a_request_naming_a_different_resource_than_the_parked_job_is_refused():
    """Case 2. THE resume attack: redirecting a parked job to a pool it was never queued against."""
    with pytest.raises(ResourceBindingError, match="is bound to resource"):
        run_simulation(
            request=_request(
                resource_demand=ResourceDemand(resource_id="license:somewhere-else", seats=1)
            ),
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=_store(),
            broker=InMemoryResourceBroker({RESOURCE: 1, "license:somewhere-else": 4}),
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )


def test_a_request_demanding_more_seats_than_the_job_was_queued_against_is_refused():
    """Case 3. The seat COUNT is part of the requirement, not a detail of the call."""
    with pytest.raises(ResourceBindingError, match="seat count is part of the requirement"):
        run_simulation(
            request=_request(resource_demand=_demand(seats=2)),
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=_store(),
            broker=InMemoryResourceBroker({RESOURCE: 4}),
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )


def test_a_request_dropping_the_demand_a_parked_job_holds_is_refused():
    """Case 1's mirror. Executing would run without the seat the job was admitted on."""
    with pytest.raises(ResourceBindingError, match="the simulation request declares none"):
        run_simulation(
            request=_request(resource_demand=None),
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=_store(),
            broker=_broker(),
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )


def test_a_capability_with_no_license_constraint_may_be_submitted_with_no_demand():
    """The positive control for the two refusals above: a local action takes no seat."""
    store = InMemoryJobStore()
    submitted = submit_simulation_job(
        jobs=store,
        job=Job(
            job_id="job:1",
            project_id=PROJECT,
            capability_id="cap:sp.local",
            trace_id="trc:1",
            idempotency_key="idem:1",
            submitted_at=NOW,
        ),
        demand=None,
        capability=_capability(capability_id="cap:sp.local", license_constraints=()),
    )
    assert submitted.resource_requirements == {}
    assert bound_demand(submitted) is None


# ---------------------------------------------------------------------------
# §17.16 — the Job is the record of what was ADMITTED, so the request must be its execution
#
# THE DEFECT. `run_simulation` resolved the job id and then executed, which proves the id exists
# and nothing else. A `SimulationRequest` naming a project, trace or capability the Job was not
# submitted under still moved the job to RUNNING, took a licence seat and ran the solver;
# `JobStore.complete`'s linkage check then refused to *record* an execution that had already
# happened, inside a project that never admitted it.
#
# WHAT EACH PROBE PROVES, AND WHY THE LIST IS LONGER THAN "IT RAISED". The refusal is worth nothing
# unless the durable record survives it, so each of the three asserts the whole set: state
# unchanged, `attempt_count` unchanged, `result_run_id` still None, no lease taken, the backend
# never entered, and no Run in the store. `_untouched` is that list; the fatal broker and backend
# are what make "never entered" a claim rather than an inference.
# ---------------------------------------------------------------------------


class FatalBroker:
    """Raises on acquire. A refused scope must not reach the seat pool.

    `declared`/`available` answer, because reading the pool size is not taking from it -- and a
    spy that raised on those too would fail for the wrong reason if anything ever asked.
    """

    def declared(self, resource_id: str) -> int:
        return 1

    def available(self, resource_id: str) -> int:
        return 1

    def acquire(
        self, resource_id: str, *, job_id: str, seats: int, now: dt.datetime, lease_id: str
    ) -> ResourceLease:
        raise AssertionError(
            f"a seat on {resource_id} was taken for job {job_id} before the request was shown to "
            "be that job's execution"
        )

    def release(self, lease_id: str, *, now: dt.datetime) -> ResourceLease:
        raise AssertionError("a lease was released that should never have been taken")


class FatalBackend:
    """Raises if executed. "The scope was refused" must mean the solver did not run."""

    backend_id = "fatal.charge.ac"
    backend_version = "0.0.0"
    validity_schema_ref = "silicon_photonics/charge_ac_validity@1.0.0"

    def execute(self, request: SimulationRequest) -> BackendExecution:
        raise AssertionError(
            f"the backend was entered for request {request.request_id}, whose scope does not match "
            "its job"
        )


def _untouched(store: InMemoryJobStore, before: Job) -> None:
    """Everything a refused execution must have left exactly as it found it."""
    after = store.get(before.job_id)
    assert after is not None
    assert after.state is before.state, "the durable job was moved"
    assert after.state is JobState.QUEUED, "a refused execution must not reach RUNNING"
    assert after.attempt_count == before.attempt_count == 0, "a refused execution burned an attempt"
    assert after.result_run_id is None, "a Run was attributed to a job that did not run it"
    assert after.started_at is None and after.finished_at is None
    assert after.resume_stage is None, "the job was parked by an execution that never started"
    assert store.run_for_job(before.job_id) is None, "a Run exists for a refused execution"


def _run_against(store: InMemoryJobStore, request: SimulationRequest) -> None:
    """`run_simulation` with every side-effecting collaborator replaced by a spy that raises."""
    run_simulation(
        request=request,
        backend=FatalBackend(),
        jobs=store,
        broker=FatalBroker(),
        validity=_validity_registry(),
        run_id="run:1",
        lease_id="lse:1",
        idempotency_key="idem:1",
        now=lambda: NOW,
        reproducibility_manifest_hash="sha256:" + "cd" * 32,
    )


def test_a_request_for_another_project_does_not_touch_the_job_it_names():
    """SEC-002 through the side door, closed before the door opens rather than at the threshold.

    `JobStore.complete` would have caught this -- `_RUN_LINKAGE` checks `project_id` precisely
    because "a run scoped away from its job escapes SEC-002 through the side door". By then the
    seat has been held and the solver has run, so what it refuses is the *record* of an execution
    that already happened. Late rejection is not sufficient; this is the same refusal made while it
    is still free.
    """
    store = _store()
    before = store.get("job:1")
    assert before is not None

    with pytest.raises(ExecutionScopeMismatch) as raised:
        _run_against(store, _request(project_id="prj:elsewhere"))

    assert "SimulationRequest.project_id is 'prj:elsewhere'" in str(raised.value)
    assert "Job.project_id is 'prj:sp'" in str(raised.value)
    _untouched(store, before)


def test_a_request_on_another_trace_does_not_touch_the_job_it_names():
    """OPS-003. The Job's trace is what joins the submission to the spans that describe it."""
    store = _store()
    before = store.get("job:1")
    assert before is not None

    with pytest.raises(ExecutionScopeMismatch) as raised:
        _run_against(store, _request(trace_id="trc:elsewhere"))

    assert "Job.trace_id is 'trc:1'" in str(raised.value)
    assert "project_id" not in str(raised.value), "only the trace disagreed"
    _untouched(store, before)


def test_a_request_for_another_capability_does_not_touch_the_job_it_names():
    """§9.5 planned one capability and §17.18 priced it; a Run must not name a different one.

    The last link of the chain `ToolDescriptor -> SimulationRequest -> Job`. Its first link is held
    at the request model (`tests/unit/test_typed_tool_registry.py`), and neither is redundant: the
    model binds what one caller constructs, this binds what the durable record admitted.
    """
    store = _store()
    before = store.get("job:1")
    assert before is not None

    with pytest.raises(ExecutionScopeMismatch) as raised:
        _run_against(store, _request(capability_id="cap:sp.mesh_sensitivity"))

    assert "capability_id is 'cap:sp.mesh_sensitivity'" in str(raised.value)
    _untouched(store, before)


def test_the_scope_is_decided_before_the_resource_demand_is_even_compared():
    """Order, asserted. A mis-scoped request is refused as a scope error, not as a demand error.

    Both guards are in `run_simulation` and either would refuse this call. Which one speaks decides
    what an operator does next: `ResourceBindingError` reads as "the pools disagree, look at the
    queue", and the honest answer here is "this request is not for this job at all".
    """
    store = _store()
    before = store.get("job:1")
    assert before is not None

    with pytest.raises(ExecutionScopeMismatch):
        _run_against(
            store,
            _request(
                project_id="prj:elsewhere",
                resource_demand=_demand(resource="license:somewhere-else"),
            ),
        )
    _untouched(store, before)


def test_a_request_whose_scope_matches_its_job_executes_and_the_run_inherits_it():
    """The positive control, asserting the identity the four refusals above exist to preserve.

    Runs the real backend and the real broker: a store whose every path raised would satisfy all
    four probes, and the Run's own project/trace/capability are what the chain is FOR.
    """
    store = _store()
    outcome = run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=store,
        broker=_broker(),
        validity=_validity_registry(),
        run_id="run:1",
        lease_id="lse:1",
        idempotency_key="idem:1",
        now=lambda: NOW,
        reproducibility_manifest_hash="sha256:" + "cd" * 32,
    )

    assert outcome.executed
    job = store.get("job:1")
    assert job is not None
    assert outcome.run.project_id == job.project_id == _request().project_id
    assert outcome.run.trace_id == job.trace_id == _request().trace_id
    assert outcome.run.capability_id == job.capability_id == _request().capability_id


def test_a_simulation_against_a_job_that_does_not_resolve_is_refused():
    """A Run nobody can attribute to a submission is what the Job exists to prevent."""
    with pytest.raises(ResourceBindingError, match="does not resolve"):
        run_simulation(
            request=_request(job_id="job:ghost"),
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=_store(),
            broker=_broker(),
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )
