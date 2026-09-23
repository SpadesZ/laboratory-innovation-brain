"""T-SIM-001 — a run manifest missing solver/project/conditions/validity is refused (§17.4, §10.3).

    SIM-001    每次 CHARGE run 必須保存 solver version、project hash、mesh/bias/config、
               exit/convergence status。
    T-SIM-001  run manifest 缺 solver/project/conditions/validity 任一必要欄位即拒絕升級正式
               evidence。

"REFUSED PROMOTION TO FORMAL EVIDENCE" IS ENFORCED BY THE MANIFEST NEVER EXISTING. `run_simulation`
validates the backend's validity record BEFORE minting the Run, so an incomplete record does not
become a row that something later has to filter out. A filter is one query away from being
forgotten; a record that was never written is not.

WHERE EACH OF SIM-001's FOUR CLAUSES IS CHECKED, because they are not all in one place and a reader
should not have to hunt:

    solver version           `simulator_validity` required field, checked here
    project hash             `simulator_validity` required field, checked here
    mesh/bias/config         `simulator_validity` required fields (by reference), checked here
    exit/convergence status  `simulator_validity` required field, checked here
    conditions               `SimulationRequest` refuses an empty condition set, checked here
    conditions_schema_version  `Run` and `SimulationRequest` both require it (EVI-005)

CORE DOES NOT KNOW ANY OF THE FOUR NAMES. The required list lives in
`domains/silicon_photonics/backend_validity.py`; `tools/simulation.py` knows only that a schema has
required fields. `tests/unit/test_extension_boundary.py` holds that line.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from lab_brain.core.models.job import Job, JobState, RunStatus
from lab_brain.core.repositories.jobs import InMemoryJobStore
from lab_brain.domains.silicon_photonics import backend_validity
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF
from lab_brain.tool_providers.lumerical.mock import MockChargeAcBackend
from lab_brain.tools.execution import Executed, run_simulation, simulated_source
from lab_brain.tools.resources import InMemoryResourceBroker, ResourceDemand
from lab_brain.tools.simulation import (
    BackendExecution,
    BackendValidityError,
    BackendValidityRegistry,
    BackendValiditySchema,
    SimulationRequest,
    manifest_for,
    validate_backend_validity,
)
from tests.refusals import refused

pytestmark = [pytest.mark.requirement("SIM-001"), pytest.mark.spec_test("T-SIM-001")]

NOW = dt.datetime(2026, 9, 23, 10, 0, tzinfo=dt.UTC)
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


def _store() -> InMemoryJobStore:
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
    return store


def _broker(seats: int = 1) -> InMemoryResourceBroker:
    return InMemoryResourceBroker({RESOURCE: seats})


def _execute(**kwargs: object) -> Executed:
    outcome = run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT, **kwargs),  # type: ignore[arg-type]
        jobs=_store(),
        broker=_broker(),
        validity=_validity_registry(),
        run_id="run:1",
        lease_id="lse:1",
        idempotency_key="idem:1",
        now=lambda: NOW,
        domain="silicon_photonics",
        reproducibility_manifest_hash="sha256:" + "cd" * 32,
    )
    assert isinstance(outcome, Executed)
    return outcome


# ---------------------------------------------------------------------------
# The four SIM-001 clauses, one refusal each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("omitted", backend_validity.REQUIRED_FIELDS)
def test_a_validity_record_missing_any_required_field_is_refused(omitted: str):
    """T-SIM-001's "缺...任一必要欄位" -- parametrised, so all six are checked, not a sample."""
    complete = dict.fromkeys(backend_validity.REQUIRED_FIELDS, "value")
    payload = {name: value for name, value in complete.items() if name != omitted}
    execution = _execution(payload)
    with pytest.raises(BackendValidityError, match=f"missing or empty required field '{omitted}'"):
        validate_backend_validity(execution, _validity_registry())


def test_an_empty_string_counts_as_missing():
    """A `convergence_status` of "" is not a convergence status.

    Treating it as present is how a validity record becomes a set of fields nobody filled in, and
    it is the shape a template or a default produces.
    """
    payload = dict.fromkeys(backend_validity.REQUIRED_FIELDS, "value")
    payload["convergence_status"] = ""
    with pytest.raises(BackendValidityError, match="convergence_status"):
        validate_backend_validity(_execution(payload), _validity_registry())


def test_an_undeclared_validity_field_is_reported():
    """A payload that grew a field nobody declared is a schema change nobody versioned."""
    payload = dict.fromkeys(backend_validity.REQUIRED_FIELDS, "value")
    payload["secret_tuning_knob"] = "0.7"
    with pytest.raises(BackendValidityError, match="undeclared field 'secret_tuning_knob'"):
        validate_backend_validity(_execution(payload), _validity_registry())


def test_a_run_naming_an_unregistered_validity_schema_fails_closed():
    """Core ships no validity schema, so there is nothing to fall back to (§17.10, AGT-011)."""
    payload = dict.fromkeys(backend_validity.REQUIRED_FIELDS, "value")
    execution = _execution(payload, schema_ref="nobody/nothing@1.0.0")
    with pytest.raises(BackendValidityError, match="no backend-validity schema is registered"):
        validate_backend_validity(execution, _validity_registry())


def test_a_complete_validity_record_passes():
    """The positive control."""
    payload = dict.fromkeys(backend_validity.REQUIRED_FIELDS, "value")
    validate_backend_validity(_execution(payload), _validity_registry())


def test_a_schema_that_requires_nothing_cannot_be_registered():
    """A schema requiring nothing makes SIM-001's refusal unreachable -- which reads as compliance."""
    with refused("makes the refusal unreachable"):
        BackendValiditySchema(schema_id="empty", version="1.0.0", domain="d", required_fields=())


# ---------------------------------------------------------------------------
# ...and the manifest is never written when validity fails
# ---------------------------------------------------------------------------


def test_an_invalid_validity_record_produces_no_run_at_all():
    """THE ordering claim. Not written and then filtered -- never written.

    Asserted against the store rather than against the return value: a Run that existed and was
    merely not returned would be a row something else could still find and cite.
    """

    class Incomplete(MockChargeAcBackend):
        def execute(self, request: SimulationRequest) -> BackendExecution:
            execution = super().execute(request)
            return execution.model_copy(
                update={
                    "backend_validity": {
                        k: v
                        for k, v in execution.backend_validity.items()
                        if k != "convergence_status"
                    }
                }
            )

    store = _store()
    with pytest.raises(BackendValidityError, match="convergence_status"):
        run_simulation(
            request=_request(),
            backend=Incomplete(clock=NOW, artifact_id=ARTIFACT),
            jobs=store,
            broker=_broker(),
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )
    assert store.get_run("run:1") is None
    assert store.run_for_job("job:1") is None


def test_the_seat_is_released_even_when_validity_refuses_the_execution():
    """`finally`, and its failure mode is silent: the pool drains one lease per refusal."""
    broker = _broker()

    class Incomplete(MockChargeAcBackend):
        def execute(self, request: SimulationRequest) -> BackendExecution:
            execution = super().execute(request)
            return execution.model_copy(update={"backend_validity": {}})

    with pytest.raises(BackendValidityError):
        run_simulation(
            request=_request(),
            backend=Incomplete(clock=NOW, artifact_id=ARTIFACT),
            jobs=_store(),
            broker=broker,
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )
    assert broker.available(RESOURCE) == 1, "the seat leaked; the pool drains one lease per crash"


# ---------------------------------------------------------------------------
# The manifest itself
# ---------------------------------------------------------------------------


def test_the_manifest_carries_every_section_17_4_field_and_defaults_none_of_them():
    """`006a`'s audit finding, one layer up: a backend assembling its own manifest re-creates it."""
    executed = _execute()
    run = executed.run

    assert run.run_id == "run:1" and run.job_id == "job:1"
    assert run.project_id == PROJECT and run.trace_id == "trc:1"
    assert run.capability_id == "cap:sp.charge_ac_sweep"
    assert run.backend_id == "mock.charge.ac"
    assert run.domain == "silicon_photonics"
    assert run.input_artifacts == (ARTIFACT,)
    assert run.conditions["bias_v"] == "-1.0"
    assert run.conditions_schema_version == SCHEMA_REF
    assert run.code_provenance
    assert run.status is RunStatus.SUCCEEDED
    assert run.output_artifacts == (ARTIFACT,)
    assert run.numerical_array_refs
    assert run.start_time == NOW and run.end_time > NOW
    assert run.reproducibility_manifest_hash


def test_the_solver_version_reaches_the_manifest():
    """SIM-001 names the solver VERSION. A manifest identifying only the backend compares two
    runs of different solvers as if they were the same."""
    run = _execute().run
    assert run.environment["backend_version"] == "0.1.0"
    assert run.backend_validity["solver_version"] == "0.1.0"


def test_the_validity_schema_reference_travels_with_the_payload():
    """A reloaded Run must be able to say which schema its validity fields satisfy.

    Without it the fields are unverifiable after the fact: which schema they conform to is not
    derivable from the values.
    """
    run = _execute().run
    assert run.backend_validity["schema_ref"] == backend_validity.SCHEMA_REF
    assert simulated_source(_execute()).backend_validity_schema == backend_validity.SCHEMA_REF


def test_a_simulation_request_with_no_conditions_is_refused():
    """A simulated result with no conditions is not reproducible evidence (§6.8, EVI-005)."""
    with refused("not reproducible evidence"):
        _request(conditions={})


def test_a_simulation_request_with_an_unversioned_condition_schema_is_refused():
    with refused("condition schema reference must be"):
        _request(conditions_schema_version="not-a-reference")


def test_a_non_converged_run_is_still_a_run_but_is_lowered_to_coarse_fidelity():
    """§6.10 needs the execution record; SIM-002 needs it not to count as standard fidelity.

    These are different questions and this test is the seam between them: the Run SUCCEEDED as an
    *execution*, and `fidelity_for` refuses to let it carry the class the descriptor declared.
    """
    from lab_brain.domains.silicon_photonics.authority_policy import SIM_COARSE, SIM_STANDARD

    executed = _execute(fail_convergence=True)
    assert executed.run.status is RunStatus.SUCCEEDED
    assert executed.run.backend_validity["convergence_status"] == backend_validity.NOT_CONVERGED
    assert backend_validity.fidelity_for(executed.run.backend_validity, SIM_STANDARD) == SIM_COARSE
    # And a converged one keeps what it declared.
    assert (
        backend_validity.fidelity_for(_execute().run.backend_validity, SIM_STANDARD) == SIM_STANDARD
    )


def test_a_duplicate_completion_produces_no_second_run():
    """OPS-001 through the simulation seam. The authoritative Run is what `complete` returns."""
    store = _store()
    broker = _broker()
    kwargs = {
        "request": _request(),
        "jobs": store,
        "broker": broker,
        "validity": _validity_registry(),
        "idempotency_key": "idem:1",
        "now": lambda: NOW,
        "reproducibility_manifest_hash": "sha256:" + "cd" * 32,
    }
    first = run_simulation(
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        run_id="run:1",
        lease_id="lse:1",
        **kwargs,  # type: ignore[arg-type]
    )
    second = run_simulation(
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        run_id="run:2",
        lease_id="lse:2",
        **kwargs,  # type: ignore[arg-type]
    )
    assert isinstance(first, Executed) and isinstance(second, Executed)
    assert first.run.run_id == second.run.run_id == "run:1"
    assert store.get_run("run:2") is None


def test_the_mock_is_deterministic():
    """Two executions of the same request produce byte-identical series."""
    first = MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT).execute(_request())
    second = MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT).execute(_request())
    assert first.series == second.series


def test_the_extracted_capacitance_recovers_what_the_model_was_given():
    """A round trip with an exactly known answer -- the reason the mock is analytic.

    Compared against the MODEL rather than against a transcribed constant: a number copied from a
    previous run would keep passing after a change to either side.
    """
    from lab_brain.domains.silicon_photonics.extractors import CJ, CjRsExtractor
    from lab_brain.tools.extraction import ExtractionInput

    backend = MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT)
    executed = _execute()
    payload = ExtractionInput(
        project_id=PROJECT,
        trace_id="trc:1",
        source=simulated_source(executed),
        series=executed.execution.series,
    )
    extracted = CjRsExtractor().extract(payload).quantity(CJ)
    assert extracted is not None and extracted.value is not None

    expected = backend.expected_cj_per_length(Decimal("-1.0"))
    relative = abs(extracted.value - expected) / expected
    assert relative < Decimal("1e-8"), f"extracted {extracted.value}, model {expected}"


# ---------------------------------------------------------------------------


def _execution(validity: dict[str, object], *, schema_ref: str | None = None) -> BackendExecution:
    return BackendExecution(
        backend_id="mock.charge.ac",
        backend_version="0.1.0",
        status=RunStatus.SUCCEEDED,
        backend_validity_schema=schema_ref or backend_validity.SCHEMA_REF,
        backend_validity=validity,
        output_artifacts=(ARTIFACT,),
        code_provenance="mock@0.1.0",
        start_time=NOW,
        end_time=NOW + dt.timedelta(seconds=1),
    )


def test_manifest_for_refuses_a_successful_execution_that_produced_nothing():
    """EVI-009 at the seam: a SUCCEEDED run with no artifact cannot back a SIMULATED attestation."""
    with refused("cannot support one"):
        BackendExecution(
            backend_id="mock.charge.ac",
            backend_version="0.1.0",
            status=RunStatus.SUCCEEDED,
            backend_validity_schema=backend_validity.SCHEMA_REF,
            backend_validity=dict.fromkeys(backend_validity.REQUIRED_FIELDS, "v"),
            output_artifacts=(),
            code_provenance="mock@0.1.0",
            start_time=NOW,
            end_time=NOW,
        )


def test_manifest_for_is_the_only_assembler():
    """Backends do not build manifests; one function does, so providers cannot disagree."""
    executed = _execute()
    rebuilt = manifest_for(
        run_id="run:9",
        request=_request(),
        execution=executed.execution,
        domain="silicon_photonics",
        reproducibility_manifest_hash=executed.run.reproducibility_manifest_hash,
    )
    assert rebuilt.model_dump(exclude={"run_id"}) == executed.run.model_dump(exclude={"run_id"})


def test_a_job_parks_rather_than_failing_when_the_seat_is_held_by_another_job():
    """§10.7, at the contract level. The full queue story is the M2 vertical.

    CONTENTION IS MODELLED AS CONTENTION: a one-seat pool with the seat already leased to a
    different job. A zero-seat pool would be a different situation -- a capability this deployment
    does not have -- and using it here would test the wrong refusal.
    """
    from lab_brain.tools.execution import WaitingForResource

    store = _store()
    broker = _broker(seats=1)
    broker.acquire(RESOURCE, job_id="job:other", seats=1, now=NOW, lease_id="lse:other")

    outcome = run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=store,
        broker=broker,
        validity=_validity_registry(),
        run_id="run:1",
        lease_id="lse:1",
        idempotency_key="idem:1",
        now=lambda: NOW,
        reproducibility_manifest_hash="sha256:" + "cd" * 32,
    )
    assert isinstance(outcome, WaitingForResource)
    assert outcome.job.state is JobState.WAITING_RESOURCE
    assert outcome.job.attempt_count == 0, "waiting consumed an attempt"
    assert outcome.job.resume_stage == f"AWAITING_RESOURCE:{RESOURCE}"
    assert store.get_run("run:1") is None


def test_a_zero_seat_pool_is_a_configuration_error_and_not_a_queue():
    """A capability this deployment does not have must not look like a busy one.

    Nothing will ever be released to unpark the job, so parking it would put a permanent entry in
    the queue and report a healthy-but-busy resource on the health page (§17.24). The correct
    surface for "no seat exists here" is UNAVAILABLE availability, which is what `availability_for`
    returns -- see the UX-007 test below.
    """
    from lab_brain.tools.resources import ResourceError, availability_for

    broker = _broker(seats=0)
    assert availability_for(broker, RESOURCE) == "UNAVAILABLE"
    with pytest.raises(ResourceError, match="no seats for that resource"):
        run_simulation(
            request=_request(),
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=_store(),
            broker=broker,
            validity=_validity_registry(),
            run_id="run:1",
            lease_id="lse:1",
            idempotency_key="idem:1",
            now=lambda: NOW,
            reproducibility_manifest_hash="sha256:" + "cd" * 32,
        )


def test_seat_availability_reads_as_degraded_rather_than_unavailable_under_contention():
    """UX-007 / §17.24: a seat shortage is degraded availability, never an error."""
    from lab_brain.tools.resources import availability_for

    broker = _broker(seats=1)
    assert availability_for(broker, RESOURCE) == "AVAILABLE"
    lease = broker.acquire(RESOURCE, job_id="job:other", seats=1, now=NOW, lease_id="lse:other")
    assert availability_for(broker, RESOURCE) == "DEGRADED"
    broker.release(lease.lease_id, now=NOW)
    assert availability_for(broker, RESOURCE) == "AVAILABLE"
