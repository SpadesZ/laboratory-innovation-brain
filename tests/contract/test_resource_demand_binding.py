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
from lab_brain.core.models.job import Job
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
from lab_brain.tools.resources import InMemoryResourceBroker, ResourceDemand
from lab_brain.tools.simulation import BackendValidityRegistry, SimulationRequest

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
