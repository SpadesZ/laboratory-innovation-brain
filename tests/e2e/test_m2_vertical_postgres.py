"""The M2 vertical, and the exit gate's two clauses through durable rows.

    M2 exit gate  simulated + measured fixtures use the same extractor contract;
                  license/resource queue mock pass.

THE CHAIN, with the durable object each step leaves behind:

     1  ResearchEpisode                      `research_episodes`     (006b)
     2  Capability descriptor registered     `capabilities`          (007c)
     3  seat pool declared with ONE seat     `resource_pools`        (007c)
     4  a rival job takes the seat           `resource_leases`       (007c)
     5  simulation requested -> no seat      `jobs.state`            = WAITING_RESOURCE
     6  the rival releases                   `resource_leases`       released_at set
     7  the SAME job resumes                 same `job_id`, attempt_count unchanged
     8  mock backend executes                (no vendor SDK; see the module's mock)
     9  SIM-001 validity checked BEFORE      -- an invalid record mints no manifest
    10  Run minted                           `runs`                  (006/006a)
    11  extractor over the SIMULATED source  shared `ExtractionInput`
    12  extractor over a MEASURED source     the SAME type, the SAME call
    13  conditions preserved on both         `runs.conditions` + `ExtractionSource.conditions`
    14  a duplicate completion callback      one Run, not two        (§12.4)
    15  retrieval/canonical evidence         unchanged -- asserted, not assumed

WHAT IS DELIBERATELY *NOT* HERE. No Attestation is written and no belief moves. §26's M2 row is the
TOOL LAYER; admitting a simulated observation as evidence needs the Claim/Observation identity work
that M4's VS-SP-001 vertical owns, and writing one here would be claiming a later requirement from
this slice. What IS asserted is that the M2 layer leaves the M1 evidence tables untouched -- step
15 -- because "the tool layer did not quietly become a second writer of scientific fact" is a claim
this milestone can and should make.

NO REAL LUMERICAL. `MockChargeAcBackend` is deterministic and says so in its own docstring; TST-001's
licensed half is open (risk R-1).
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from lab_brain.core.models.capability import ActionType, Availability, Capability
from lab_brain.core.models.enums import EpistemicType, FieldStatus
from lab_brain.core.models.episode import EpisodeState, ResearchEpisode
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.episodes import SqlEpisodeStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack, backend_validity
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF, registration
from lab_brain.domains.silicon_photonics.extractors import CJ, RS
from lab_brain.domains.silicon_photonics.tools import (
    CHARGE_AC_CAPABILITY,
    CHARGE_AC_TOOL_ID,
    SIMULATOR_RESOURCE_ID,
    ChargeAcSweepRequest,
    ChargeAcSweepResult,
)
from lab_brain.domains.silicon_photonics.validators import TrendSample, TrendSubject
from lab_brain.storage.postgres.capabilities import (
    PostgresCapabilityStore,
    PostgresResourceBroker,
)
from lab_brain.tool_providers.lumerical.mock import MockChargeAcBackend
from lab_brain.tools.execution import Executed, WaitingForResource, run_simulation, simulated_source
from lab_brain.tools.extraction import ExtractionInput
from lab_brain.tools.resources import ResourceDemand
from lab_brain.tools.simulation import BackendValidityRegistry, SimulationRequest
from lab_brain.verification.planner import VerificationPlanner
from tests import sp_fixtures as fx

#: Only the backend gate is module-level. Traceability markers go on each function, because a
#: module claiming two requirements and two test ids claims the CROSS PRODUCT of them -- and
#: (SIM-001, T-DOM-SP-002) is not a pair §26 maps. `check_marker_pairs_in_matrix` catches it, which
#: is the right answer: a pair the matrix does not declare is coverage nobody asked for.
pytestmark = [pytest.mark.postgres]

NOW = dt.datetime(2026, 9, 23, 11, 0, tzinfo=dt.UTC)
PROJECT = "prj:m2"
EPISODE = "epi:m2"
TRACE = "trc:m2"
JOB = "job:m2"
RIVAL_JOB = "job:m2-rival"
ARTIFACT = "art:sha256:" + "5c" * 32


def _clock() -> dt.datetime:
    return NOW


@pytest.fixture
def wired(db):
    """Project, episode, condition schema, capability and seat pool -- all durable."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'M2') ON CONFLICT DO NOTHING",
        (PROJECT,),
    )
    schema = registration()
    # `schema_ref` is a GENERATED column in `008` -- the application and the database cannot
    # disagree about the format because only one of them writes it.
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema, "
        "comparator_version) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (
            schema.domain,
            schema.schema_id,
            schema.version,
            json.dumps(schema.json_schema),
            schema.comparator_version,
        ),
    )
    # The device project the run consumes and re-emits. Inserted directly rather than ingested:
    # M1's ingestion path is not what this vertical is about, and a real ingest here would make
    # the M2 assertions depend on M1 machinery they are not testing.
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, lineage_id, "
        "source_origin) VALUES (%s,%s,'application/octet-stream','file:///device.ldev',%s,'UPLOAD')"
        " ON CONFLICT DO NOTHING",
        (ARTIFACT, ARTIFACT.removeprefix("art:"), "lin:m2"),
    )
    db.execute(
        "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label) "
        "VALUES (%s, %s, 'INTERNAL') ON CONFLICT DO NOTHING",
        (ARTIFACT, PROJECT),
    )
    # `006b` makes `jobs.episode_id` a real foreign key, so the episode has to exist before any
    # Job does. Created here rather than in each test: the vertical's step 1 asserts against it,
    # and the other tests need it only as the Job's scope.
    SqlEpisodeStore(db).open(
        ResearchEpisode(
            episode_id=EPISODE,
            project_id=PROJECT,
            trace_id=TRACE,
            goal="extract Cj/Rs from a small-signal sweep",
            start_time=NOW,
        )
    )
    return db


def _capability() -> Capability:
    return Capability(
        capability_id=CHARGE_AC_CAPABILITY,
        domain="silicon_photonics",
        action_type=ActionType.SIMULATION,
        backend_id="sp.charge.ac",
        requires=("sp.device_project",),
        produces=("sp.small_signal_impedance",),
        authority_class="SIM_STANDARD",
        conditions_schema_version=SCHEMA_REF,
        license_constraints=(SIMULATOR_RESOURCE_ID,),
        estimate_cost_contract="cost:sp.charge_ac_sweep@1.0.0",
        version="1.0.0",
    )


def _request(job_id: str = JOB, request_id: str = "req:m2") -> SimulationRequest:
    return SimulationRequest(
        request_id=request_id,
        project_id=PROJECT,
        trace_id=TRACE,
        job_id=job_id,
        capability_id=CHARGE_AC_CAPABILITY,
        input_artifacts=(ARTIFACT,),
        conditions=dict(fx.CONDITIONS),
        conditions_schema_version=SCHEMA_REF,
        resource_demand=ResourceDemand(
            resource_id=SIMULATOR_RESOURCE_ID, seats=1, estimated_seat_s=30
        ),
    )


def _validity() -> BackendValidityRegistry:
    registry = BackendValidityRegistry()
    registry.register(backend_validity.schema())
    return registry


def _submit(jobs: SqlJobStore, job_id: str, key: str) -> Job:
    return jobs.submit(
        Job(
            job_id=job_id,
            project_id=PROJECT,
            episode_id=EPISODE,
            capability_id=CHARGE_AC_CAPABILITY,
            trace_id=TRACE,
            idempotency_key=key,
            submitted_at=NOW,
        )
    )


@pytest.mark.requirement("DOM-SP-002")
@pytest.mark.spec_test("T-DOM-SP-002")
def test_the_whole_m2_vertical_runs_through_durable_rows(wired, db):
    """Steps 1-15. Each assertion names the durable object it is reading."""
    episodes = SqlEpisodeStore(db)
    jobs = SqlJobStore(db)
    capabilities = PostgresCapabilityStore(db)
    broker = PostgresResourceBroker(db)

    # 1. ResearchEpisode -- durable, and the Job's foreign key (006b). Created by the fixture,
    #    reloaded here through the store so the assertion is against a row and not a local object.
    episode = episodes.get(EPISODE)
    assert episode is not None and episode.state is EpisodeState.CREATED

    # 2. Capability descriptor -- and it round-trips through the MODEL, not a dict.
    stored = capabilities.upsert(_capability())
    assert stored == _capability()
    assert capabilities.get(CHARGE_AC_CAPABILITY) is not None

    # 3-4. One seat, and a rival job holds it.
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)
    _submit(jobs, RIVAL_JOB, "idem:rival")
    jobs.transition(RIVAL_JOB, JobState.RUNNING, NOW)
    rival_lease = broker.acquire(
        SIMULATOR_RESOURCE_ID, job_id=RIVAL_JOB, seats=1, now=NOW, lease_id="lse:rival"
    )
    assert broker.available(SIMULATOR_RESOURCE_ID) == 0

    # 5. The simulation is requested and there is no seat. WAITING_RESOURCE, not FAILED.
    _submit(jobs, JOB, "idem:m2")
    parked = run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=jobs,
        broker=broker,
        validity=_validity(),
        run_id="run:m2",
        lease_id="lse:m2",
        idempotency_key="idem:m2",
        now=_clock,
        domain="silicon_photonics",
        reproducibility_manifest_hash="sha256:" + "77" * 32,
    )
    assert isinstance(parked, WaitingForResource)
    reloaded = jobs.get(JOB)
    assert reloaded is not None
    assert reloaded.state is JobState.WAITING_RESOURCE
    assert reloaded.attempt_count == 0, "waiting must not consume an attempt"
    assert reloaded.structured_error is None, "waiting is not an error"
    assert jobs.run_for_job(JOB) is None, "nothing executed"

    # 6. The rival releases. The lease row survives -- "who was holding it" stays answerable.
    broker.release(rival_lease.lease_id, now=NOW + dt.timedelta(minutes=1))
    assert broker.available(SIMULATOR_RESOURCE_ID) == 1
    held = [lease for lease in broker.leases_for(SIMULATOR_RESOURCE_ID) if lease.held]
    assert held == [] and len(broker.leases_for(SIMULATOR_RESOURCE_ID)) == 1

    # 7-10. The SAME logical job resumes and executes.
    executed = run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=jobs,
        broker=broker,
        validity=_validity(),
        run_id="run:m2",
        lease_id="lse:m2",
        idempotency_key="idem:m2",
        now=_clock,
        domain="silicon_photonics",
        reproducibility_manifest_hash="sha256:" + "77" * 32,
    )
    assert isinstance(executed, Executed)
    assert executed.job.job_id == JOB, "a new Job was created instead of resuming this one"
    assert executed.job.attempt_count == 0
    assert executed.run.job_id == JOB and executed.run.trace_id == TRACE

    # The Run is durable and carries §17.4 in full, including SIM-001's validity record.
    durable_run = jobs.run_for_job(JOB)
    assert durable_run is not None and durable_run.run_id == "run:m2"
    assert durable_run.conditions_schema_version == SCHEMA_REF
    for field in backend_validity.REQUIRED_FIELDS:
        assert durable_run.backend_validity[field], f"{field} missing from the durable manifest"
    assert durable_run.backend_validity["schema_ref"] == backend_validity.SCHEMA_REF
    assert durable_run.output_artifacts == (ARTIFACT,)

    # ...and the seat was returned.
    assert broker.available(SIMULATOR_RESOURCE_ID) == 1

    # 11-13. The SAME extractor over both modalities, from the Run that was actually minted.
    pack = SiliconPhotonicsPack(runner=lambda request: executed)
    extractor = pack.extractor

    simulated = extractor.extract(
        ExtractionInput(
            project_id=PROJECT,
            trace_id=TRACE,
            source=simulated_source(executed),
            series=executed.execution.series,
        )
    )
    measured = extractor.extract(
        ExtractionInput(
            project_id=PROJECT,
            trace_id=TRACE,
            source=fx.measured_source().model_copy(update={"project_id": PROJECT}),
            series=executed.execution.series,
        )
    )

    assert type(simulated) is type(measured)
    assert simulated.modality is EpistemicType.SIMULATED
    assert measured.modality is EpistemicType.MEASURED
    for name in (CJ, RS):
        left, right = simulated.quantity(name), measured.quantity(name)
        assert left is not None and right is not None
        assert left.status is FieldStatus.DERIVED and right.status is FieldStatus.DERIVED
        assert left.value == right.value, f"{name} diverged between the two paths"
        assert left.normalization_basis == right.normalization_basis

    # Provenance is NOT shared, and the simulated one points at the durable Run.
    assert simulated.source.run_id == durable_run.run_id
    assert measured.source.source_artifact_id is not None
    assert simulated.source.provenance_ref != measured.source.provenance_ref

    # Conditions survive from the request through the Run to the extraction.
    assert simulated.source.conditions == durable_run.conditions == dict(fx.CONDITIONS)

    # 14. A duplicate completion callback creates no second Run (§12.4, OPS-001).
    again = run_simulation(
        request=_request(request_id="req:m2-dup"),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=jobs,
        broker=broker,
        validity=_validity(),
        run_id="run:m2-second",
        lease_id="lse:m2-second",
        idempotency_key="idem:m2",
        now=_clock,
        domain="silicon_photonics",
        reproducibility_manifest_hash="sha256:" + "77" * 32,
    )
    assert isinstance(again, Executed)
    assert again.run.run_id == "run:m2"
    assert jobs.get_run("run:m2-second") is None
    assert db.execute("SELECT count(*) FROM runs WHERE job_id = %s", (JOB,)).fetchone()[0] == 1

    # 15. The M1 evidence tables are untouched. The tool layer did not become a second writer.
    for table in ("attestations", "evidence_units", "belief_revision_events", "observations"):
        count = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        assert count == 0, (
            f"the M2 vertical wrote {count} row(s) to {table}. Admitting a simulated observation "
            "as evidence is M4's VS-SP-001 loop, and a tool layer that wrote one would be the "
            "second evidence model the extension boundary exists to prevent"
        )


@pytest.mark.requirement("SIM-001")
@pytest.mark.spec_test("T-SIM-001")
def test_the_durable_run_manifest_carries_every_sim_001_validity_field(wired, db):
    """SIM-001 against the stored ROW, not the in-memory object.

    `tests/contract/test_simulation_contract.py` holds the refusals -- one per missing field, plus
    the ordering claim that an invalid record mints no manifest. What can only be checked here is
    that a complete record SURVIVES the write: a validity payload that round-tripped through JSONB
    with a field dropped would satisfy every backend-free test and leave a Run nobody can validate.
    """
    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)
    _submit(jobs, JOB, "idem:m2")

    run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=jobs,
        broker=broker,
        validity=_validity(),
        run_id="run:m2",
        lease_id="lse:m2",
        idempotency_key="idem:m2",
        now=_clock,
        domain="silicon_photonics",
        reproducibility_manifest_hash="sha256:" + "77" * 32,
    )

    stored = db.execute(
        "SELECT backend_validity, conditions, conditions_schema_version, code_provenance, "
        "environment, output_artifacts FROM runs WHERE run_id = %s",
        ("run:m2",),
    ).fetchone()
    assert stored is not None
    validity, conditions, schema_ref, provenance, environment, outputs = stored

    for field in backend_validity.REQUIRED_FIELDS:
        assert validity.get(field), f"{field} did not survive the write"
    assert validity["schema_ref"] == backend_validity.SCHEMA_REF
    assert validity["solver_id"].startswith("mock."), "the manifest claims a vendor solver"
    assert conditions == dict(fx.CONDITIONS)
    assert schema_ref == SCHEMA_REF
    assert provenance and environment["backend_version"] == "0.1.0"
    assert list(outputs) == [ARTIFACT]


@pytest.mark.requirement("VER-002")
@pytest.mark.spec_test("T-VER-002")
def test_the_planner_selects_the_capability_from_the_durable_descriptor(wired, db):
    """VER-002 over stored rows: the planner reads descriptors, and here they came from `007c`."""
    from lab_brain.verification.capability_registry import CapabilityRegistry

    store = PostgresCapabilityStore(db)
    store.upsert(_capability())

    registry = CapabilityRegistry()
    registry.register_estimator(
        "cost:sp.charge_ac_sweep@1.0.0",
        lambda params: __import__("lab_brain.core.models.cost", fromlist=["CostVector"]).CostVector(
            wall_clock_s=30, license_seat_s=30
        ),
    )
    for capability in store.list_all():
        registry.register(capability)

    planned = VerificationPlanner(registry).plan(
        goal=("sp.small_signal_impedance",), available=frozenset({"sp.device_project"})
    )
    assert [action.capability_id for action in planned] == [CHARGE_AC_CAPABILITY]
    assert planned[0].cost.license_seat_s == 30


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_a_seat_exhausted_capability_reads_as_degraded_and_never_as_an_error(wired, db):
    """UX-007 / §17.24 over the durable pool: seat exhaustion is degraded availability."""
    from lab_brain.surface.health import (
        CapabilityAvailability,
        ComponentStatus,
        derive_health,
    )

    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    store = PostgresCapabilityStore(db)
    store.upsert(_capability())
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)

    _submit(jobs, RIVAL_JOB, "idem:rival")
    jobs.transition(RIVAL_JOB, JobState.RUNNING, NOW)
    broker.acquire(SIMULATOR_RESOURCE_ID, job_id=RIVAL_JOB, seats=1, now=NOW, lease_id="lse:rival")
    _submit(jobs, JOB, "idem:m2")
    run_simulation(
        request=_request(),
        backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
        jobs=jobs,
        broker=broker,
        validity=_validity(),
        run_id="run:m2",
        lease_id="lse:m2",
        idempotency_key="idem:m2",
        now=_clock,
        domain="silicon_photonics",
        reproducibility_manifest_hash="sha256:" + "77" * 32,
    )

    health = derive_health(
        capabilities=(CapabilityAvailability(capability_id=CHARGE_AC_CAPABILITY, available=True),),
        adapters=(),
        jobs=jobs.list_active(PROJECT),
        review_queue_depth=0,
        review_queue_capacity=10,
    )
    component = health.component(CHARGE_AC_CAPABILITY)
    assert component is not None
    assert component.status is ComponentStatus.DEGRADED
    assert component.reason_code == "AWAITING_RESOURCE"
    assert component.waiting_on_resource == 1
    assert health.overall is not ComponentStatus.UNAVAILABLE


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_the_database_holds_the_seat_ceiling_against_a_writer_outside_python(wired, db):
    """The ceiling is `007c`'s, not this broker's -- so raw SQL cannot over-lease.

    A check-then-insert in Python is correct for one scheduler and wrong for two. This inserts
    directly, skipping the broker entirely, which is what a second process or a maintenance script
    would do.
    """
    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)
    _submit(jobs, RIVAL_JOB, "idem:rival")
    _submit(jobs, JOB, "idem:m2")
    broker.acquire(SIMULATOR_RESOURCE_ID, job_id=RIVAL_JOB, seats=1, now=NOW, lease_id="lse:rival")

    with pytest.raises(Exception, match="would exceed the pool"):
        db.execute(
            "INSERT INTO resource_leases (lease_id, resource_id, job_id, seats, acquired_at) "
            "VALUES ('lse:raw', %s, %s, 1, %s)",
            (SIMULATOR_RESOURCE_ID, JOB, NOW),
        )


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_one_job_cannot_hold_two_seats_of_one_resource(wired, db):
    """§12.4's idempotent callback, one resource over: a duplicate acquisition drains the pool."""
    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=4)
    _submit(jobs, JOB, "idem:m2")
    broker.acquire(SIMULATOR_RESOURCE_ID, job_id=JOB, seats=1, now=NOW, lease_id="lse:a")

    from lab_brain.tools.resources import ResourceUnavailable

    with pytest.raises(ResourceUnavailable):
        broker.acquire(SIMULATOR_RESOURCE_ID, job_id=JOB, seats=1, now=NOW, lease_id="lse:b")


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_released_lease_may_be_re_acquired_by_the_same_job(wired, db):
    """The uniqueness above is on HELD leases; a resumed job takes a seat again."""
    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)
    _submit(jobs, JOB, "idem:m2")
    first = broker.acquire(SIMULATOR_RESOURCE_ID, job_id=JOB, seats=1, now=NOW, lease_id="lse:a")
    broker.release(first.lease_id, now=NOW)
    second = broker.acquire(SIMULATOR_RESOURCE_ID, job_id=JOB, seats=1, now=NOW, lease_id="lse:b")
    assert second.held and second.lease_id != first.lease_id


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_releasing_twice_is_idempotent(wired, db):
    """A release delivered twice is the same class of event as a duplicate completion."""
    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)
    _submit(jobs, JOB, "idem:m2")
    lease = broker.acquire(SIMULATOR_RESOURCE_ID, job_id=JOB, seats=1, now=NOW, lease_id="lse:a")
    first = broker.release(lease.lease_id, now=NOW)
    second = broker.release(lease.lease_id, now=NOW + dt.timedelta(hours=1))
    assert first.released_at == second.released_at, "the second release moved the timestamp"


@pytest.mark.requirement("SIM-003")
@pytest.mark.spec_test("T-SIM-003")
def test_the_full_tool_chain_runs_through_the_typed_registry(wired, db):
    """SIM-003 in the vertical: run, extract and validate are all reached through `invoke`.

    The point is that no step reaches an implementation directly. A tool chain that called the
    extractor as a Python object would be a chain the registry's type checks never saw.
    """
    jobs = SqlJobStore(db)
    broker = PostgresResourceBroker(db)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat", seats=1)
    _submit(jobs, JOB, "idem:m2")

    def runner(request: SimulationRequest):
        return run_simulation(
            request=request,
            backend=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT),
            jobs=jobs,
            broker=broker,
            validity=_validity(),
            run_id="run:m2",
            lease_id="lse:m2",
            idempotency_key="idem:m2",
            now=_clock,
            domain="silicon_photonics",
            reproducibility_manifest_hash="sha256:" + "77" * 32,
        )

    registry = DomainPackRegistry()
    registry.install(SiliconPhotonicsPack(runner=runner))
    tools = registry.registries.tools

    ran = tools.invoke(
        CHARGE_AC_TOOL_ID,
        ChargeAcSweepRequest(project_id=PROJECT, trace_id=TRACE, simulation=_request()),
    )
    assert isinstance(ran, ChargeAcSweepResult)
    assert ran.executed and ran.run_id == "run:m2"

    durable_run = jobs.get_run("run:m2")
    assert durable_run is not None
    executed = Executed(
        job=jobs.get(JOB),  # type: ignore[arg-type]
        run=durable_run,
        execution=MockChargeAcBackend(clock=NOW, artifact_id=ARTIFACT).execute(_request()),
        lease=None,
    )

    extracted = tools.invoke(
        "DOM-SP-TOOL-004",
        ExtractionInput(
            project_id=PROJECT,
            trace_id=TRACE,
            source=simulated_source(executed),
            series=executed.execution.series,
        ),
    )
    cj = extracted.quantity(CJ)  # type: ignore[attr-defined]
    assert cj is not None and cj.value is not None

    from lab_brain.domains.silicon_photonics.tools import TrendValidationRequest

    reported = tools.invoke(
        "DOM-SP-TOOL-006",
        TrendValidationRequest(
            project_id=PROJECT,
            trace_id=TRACE,
            subject=TrendSubject(
                subject_id="sweep:m2",
                samples=(
                    TrendSample(
                        bias_v=Decimal("-1"),
                        rs_per_length=Decimal("1200"),
                        cj_per_length=Decimal("150"),
                    ),
                    TrendSample(
                        bias_v=Decimal("0"),
                        rs_per_length=Decimal("1210"),
                        cj_per_length=Decimal("200"),
                    ),
                ),
                provenance_refs=(durable_run.run_id,),
            ),
        ),
    )
    assert reported.report.passed  # type: ignore[attr-defined]
    assert reported.report.provenance_refs == (durable_run.run_id,)  # type: ignore[attr-defined]


@pytest.mark.requirement("VER-002")
@pytest.mark.spec_test("T-VER-002")
def test_a_capability_contract_cannot_be_replaced_in_place(wired, db):
    """§17.18's versioning, enforced at the durable boundary rather than only in memory."""
    from lab_brain.storage.postgres.capabilities import CapabilityStoreError

    store = PostgresCapabilityStore(db)
    store.upsert(_capability())
    with pytest.raises(CapabilityStoreError, match="unreproducible"):
        store.upsert(_capability().model_copy(update={"authority_class": "SIM_VALIDATION"}))

    # ...but availability is state and may change without a version.
    updated = store.set_availability(CHARGE_AC_CAPABILITY, Availability.DEGRADED)
    assert updated.availability is Availability.DEGRADED
    assert updated.version == "1.0.0"
