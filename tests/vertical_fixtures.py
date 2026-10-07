"""VS-SP-001's world: M3's debate forms the rivals, M4's loop verifies them (T-E2E-SP-001, M4).

    §26.1 M4  intent-aware retrieval -> competing hypotheses -> capability/cost planning -> Job ->
              evidence -> belief event -> failure/heuristic candidate

WHAT IS COMPOSED, AND FROM WHERE:

    the debate      `tests.debate_fixtures.build_world` -- M3's StructuredDebate, admission service,
                    revision gate and stores over PostgreSQL, with a `VerticalScientist`: M3's
                    deterministic `MockScientist` answering from THIS fixture's mechanism catalog,
                    whose certificates carry one SUPPORTS and one CONTRADICTS prediction per check
    the pack        a second `DomainPackRegistry` install of `SiliconPhotonicsPack`, whose runner is
                    a `CapabilityRoutedRunner` over the local readers and the mock solvers. The
                    debate's install has a no-op runner (it never executes tools); the declarations
                    of both installs are the same pack's
    the belief path M1's `BeliefEpisode` with both comparator versions registered, behind M3's
                    `HypothesisBrain` -- the reviser the loop drives
    the loop        `lab_brain.verification.loop.VerificationLoop`, with its SQL stores

TWO STRATEGIES. `least_cost` is M4's planner. `simulate_first` is the benchmark's baseline: the
same planner, sufficiency and loop, with the ranking reordered to put SIMULATION candidates first --
the "re-run the solver" habit VER-001 exists to break. Its plans go to an in-memory store: they are
not VerificationPlans a SelectionPolicy produced, and they are never persisted as if they were.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lab_brain.cognition.brain import HypothesisBrain
from lab_brain.cognition.debate import DebateOutcome, DebatePolicy, DebateRequest
from lab_brain.cognition.evidence import EvidenceItem
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models.capability import ActionType, Availability
from lab_brain.core.models.cost import BudgetCaps, CostVector
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.models.verification import PlanDecision
from lab_brain.core.repositories.belief_events import (
    SqlBeliefEventStore,
    SqlBeliefTransitionDecisionStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.budget import SqlBudgetApprovalClaims, SqlCostLedger
from lab_brain.core.repositories.conditions import SqlConditionSchemaStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.failures import SqlFailureStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.observability import SqlSpanRepository
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.repositories.verification_plans import (
    InMemoryVerificationPlanStore,
    SqlVerificationPlanStore,
)
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics import vertical as sp_vertical
from lab_brain.domains.silicon_photonics.authority_policy import (
    SiliconPhotonicsAuthorityPolicy,
    transition_policies,
)
from lab_brain.domains.silicon_photonics.diagnosis import (
    DEVICE_PROJECT_MEDIA_TYPE,
    ContactConnectivityReader,
    DeviceProject,
    NormalizationBasisReader,
)
from lab_brain.domains.silicon_photonics.tools import INPUT_DEVICE_PROJECT, SIMULATOR_RESOURCE_ID
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.capabilities import PostgresResourceBroker
from lab_brain.storage.postgres.run_outputs import SqlRunOutputSink
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from lab_brain.tool_providers.lumerical.mock_vertical import (
    MockChargeDcBackend,
    MockMeshSensitivityBackend,
)
from lab_brain.tools.dispatch import BudgetedToolDispatcher
from lab_brain.tools.execution import submit_simulation_job
from lab_brain.tools.resources import ResourceDemand
from lab_brain.tools.routing import CapabilityRoutedRunner
from lab_brain.verification.least_cost import LeastCostPlanner, PlanningResult
from lab_brain.verification.loop import (
    LoopDependencies,
    LoopRequest,
    LoopResult,
    VerificationLoop,
)
from lab_brain.verification.root_cause_benchmark import (
    BenchmarkRun,
    CaseRecord,
    StepRecord,
    evaluate,
)
from lab_brain.verification.sufficiency import TransitionTarget
from lab_brain.verification.workflows import WorkflowStatus
from tests.debate_fixtures import (
    ACTOR,
    ADMISSION_POLICY,
    EPISODE,
    PROJECT,
    TRACE,
    MockScientist,
    World,
    budget_policy,
    build_world,
    fixture_falsifier,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "vertical" / "sp_rs_root_cause_benchmark.json"
DOMAIN = "silicon_photonics"

LEAST_COST = "least_cost"
SIMULATE_FIRST = "simulate_first"
STRATEGIES = (LEAST_COST, SIMULATE_FIRST)

#: §9.3's high-cost action types: what "unnecessary high-cost action" counts.
HIGH_COST_TYPES = frozenset({ActionType.SIMULATION, ActionType.MEASUREMENT, ActionType.FABRICATION})


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def fixture_digest() -> str:
    """Over LF-normalised bytes, so a checkout's line endings cannot move the benchmark's identity."""
    data = FIXTURE_PATH.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def case_by_id(fx: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(c for c in fx["cases"] if c["case_id"] == case_id)
    return found


def device_for(fx: Mapping[str, Any], case: Mapping[str, Any]) -> DeviceProject:
    return DeviceProject.model_validate({**fx["nominal_device"], **case.get("device", {})})


def evidence_items(fx: Mapping[str, Any]) -> tuple[EvidenceItem, ...]:
    return tuple(
        EvidenceItem(
            attestation_id=e["attestation_id"],
            project_id=PROJECT,
            text=e["text"],
            trust_class=TrustClass(e["trust_class"]),
            domain=DOMAIN,
            source_work_id=e.get("source_work_id"),
        )
        for e in fx["evidence"]
    )


@dataclass
class VerticalScientist(MockScientist):
    """M3's deterministic scientist, reading a catalog whose mechanisms declare their predictions.

    Its typed falsifier is the declared prediction that is the pack's designated falsifier for the
    same mechanism (`fixture_falsifier`) -- named, never inferred from which predictions contradict.
    """

    def _certificate(self, key: str) -> dict[str, Any]:
        m = self.mechanisms[key]
        predictions = [{"key": f"p{n}", **p} for n, p in enumerate(m["predictions"])]
        falsifier = fixture_falsifier(key)
        return {
            "key": key,
            "statement": m["statement"],
            "mechanism": m["mechanism"],
            "assumptions": list(m["assumptions"]),
            "falsifier": m["falsifier"],
            "falsifier_prediction_keys": [
                p["key"]
                for p in predictions
                if p["relation_effect"] == "CONTRADICTS"
                and all(p[k] == v for k, v in falsifier.items())
            ],
            "confounders": list(m["confounders"]),
            "minimal_test_ref": m["minimal_test_ref"],
            "predictions": predictions,
        }


class ScopedCountingIds:
    """`BeliefEpisode`'s ids, scoped: two episodes in one transaction must not reuse a decision id."""

    def __init__(self, scope: str) -> None:
        self._scope = scope
        self._counts: dict[str, int] = {}

    def _next(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}:{self._scope}-{self._counts[prefix]:04d}"

    def decision_id(self) -> str:
        return self._next("dec")

    def event_id(self) -> str:
        return self._next("bre")

    def conflict_id(self) -> str:
        return self._next("cfl")

    def review_id(self) -> str:
        return self._next("rvw")


class SimulateFirstPlanner:
    """The baseline: the least-cost planner's candidates and sufficiency, re-ranked solver-first.

    Among the SAME sufficient candidates, SIMULATION is tried first (longest solve first, the
    "run the full simulation" habit), then everything else in the least-cost order. The chosen
    action is still a sufficient one -- the baseline is not wasteful by construction, only
    cost-blind -- which isolates exactly what VER-001's ranking contributes.
    """

    def __init__(self, inner: LeastCostPlanner, capabilities: Any) -> None:
        self._inner = inner
        self._capabilities = capabilities

    def plan(self, **kwargs: Any) -> PlanningResult:
        result = self._inner.plan(**kwargs)
        plan = result.plan

        def solver_first(action_id: str) -> tuple[int, int, int]:
            capability = self._capabilities.resolve(action_id)
            is_solve = capability.action_type is ActionType.SIMULATION
            wall = result.costs[action_id].wall_clock_s
            return (
                0 if is_solve else 1,
                -wall if is_solve else 0,
                plan.ranked_action_ids.index(action_id),
            )

        ranked = tuple(sorted(plan.ranked_action_ids, key=solver_first))
        chosen = next((a for a in ranked if plan.sufficiency_results[a].sufficient), None)
        decision = plan.rationale.decision
        if decision is PlanDecision.ACT:
            rationale = plan.rationale.model_copy(
                update={"summary": f"baseline (simulate-first): {chosen}"}
            )
        else:
            rationale = plan.rationale
        rebuilt = plan.model_copy(
            update={
                "ranked_action_ids": ranked,
                "chosen_action_id": chosen if decision is PlanDecision.ACT else None,
                "selection_policy_id": BASELINE_POLICY.policy_id,
                "selection_policy_version": BASELINE_POLICY.version,
                "rationale": rationale,
            }
        )
        return PlanningResult(
            plan=type(plan).model_validate(rebuilt.model_dump()),
            assessments=result.assessments,
            costs=result.costs,
            chosen=None if chosen is None else self._capabilities.resolve(chosen),
        )


BASELINE_POLICY = sp_vertical.selection_policy().model_copy(
    update={"policy_id": "slp:benchmark.simulate-first"}
)


@dataclass
class VerticalRun:
    case_id: str
    strategy: str
    debate: DebateOutcome
    result: LoopResult
    device_artifact_id: str
    world: World
    registry: DomainPackRegistry
    brain: HypothesisBrain
    certificates_by_mechanism: dict[str, str] = field(default_factory=dict)

    def mechanism_of(self, hypothesis_id: str | None) -> str | None:
        if hypothesis_id is None:
            return None
        return next(
            (m for m, h in self.certificates_by_mechanism.items() if h == hypothesis_id), None
        )


def _mechanism_key(fx: Mapping[str, Any], mechanism: str) -> str:
    key: str = next(k for k, m in fx["mechanisms"].items() if m["mechanism"] == mechanism)
    return key


def _ensure_episode(connection: Any, episode_id: str) -> None:
    connection.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, start_time)"
        " VALUES (%s, %s, %s, 'diagnose the Rs anomaly', %s) ON CONFLICT DO NOTHING",
        (episode_id, PROJECT, TRACE, dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.UTC)),
    )


def run_case(
    connection: Any,
    fx: Mapping[str, Any],
    case: Mapping[str, Any],
    *,
    strategy: str = LEAST_COST,
    scope: str | None = None,
    episode_id: str | None = None,
) -> VerticalRun:
    """One diagnosis episode, end to end, against `connection`. Writes durable rows."""
    scope = scope or f"{case['case_id']}-{strategy}"
    episode_id = episode_id or f"epi:{scope}"
    scientist = VerticalScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space={},
    )
    world = build_world(
        connection=connection,
        scientist=scientist,
        items=evidence_items(fx),
        scope=scope,
        policy=DebatePolicy(minimum_hypotheses=len(fx["mechanisms"]), max_rounds=2),
        transition_policies=(
            *transition_policies(),
            *sp_vertical.vertical_transition_policies(),
        ),
    )
    _ensure_episode(connection, episode_id)
    SqlConditionSchemaStore(connection).ensure(sp_vertical.device_schema_registration())

    # -- 1. competing hypotheses, through M3's debate ------------------------------------------
    debate = world.debate.run(
        DebateRequest(
            project_id=PROJECT,
            episode_id=episode_id,
            trace_id=TRACE,
            actor_id=ACTOR,
            question=fx["question"],
            intent=fx["intent"],
            stakes=fx["stakes"],
            domain=DOMAIN,
            admission_policy=ADMISSION_POLICY,
            budget_policy=budget_policy(),
            question_label=SensitivityLabel.INTERNAL,
            available_inputs=frozenset({INPUT_DEVICE_PROJECT}),
        )
    )

    # -- 2. the pack, executing: readers and mock solvers behind one routed runner --------------
    store = InMemoryArtifactStore()
    outputs = SqlRunOutputSink(connection=connection, store=store, now=world.now)
    jobs = SqlJobStore(connection)
    broker = PostgresResourceBroker(connection)
    broker.declare(SIMULATOR_RESOURCE_ID, display_name="SiPh solver seat (mock)", seats=1)
    if case.get("seat_held_elsewhere"):
        # A licence outage, as §10.7 models it: the one seat is leased to another project job, so
        # a solve parks in WAITING_RESOURCE rather than failing.
        rival = submit_simulation_job(
            jobs=jobs,
            job=Job(
                job_id=f"job:{scope}-rival",
                project_id=PROJECT,
                episode_id=episode_id,
                capability_id=sp_vertical.CAP_CHARGE_DC,
                trace_id=TRACE,
                idempotency_key=f"idem:{scope}-rival",
                submitted_at=world.now(),
            ),
            demand=ResourceDemand(resource_id=SIMULATOR_RESOURCE_ID, seats=1),
            capability=next(
                c
                for c in sp_vertical.capabilities()
                if c.capability_id == sp_vertical.CAP_CHARGE_DC
            ),
        )
        jobs.transition(rival.job_id, JobState.RUNNING, world.now())
        broker.acquire(
            SIMULATOR_RESOURCE_ID,
            job_id=rival.job_id,
            seats=1,
            now=world.now(),
            lease_id=f"lse:{scope}-rival",
        )
    registry = DomainPackRegistry()
    runner = CapabilityRoutedRunner(
        backends={
            sp_vertical.CAP_INSPECT_CONNECTIVITY: ContactConnectivityReader(
                sink=outputs, now=world.now
            ),
            sp_vertical.CAP_EXTRACTION_CONSISTENCY: NormalizationBasisReader(
                sink=outputs, now=world.now
            ),
            sp_vertical.CAP_MESH_SENSITIVITY: MockMeshSensitivityBackend(
                sink=outputs, now=world.now
            ),
            sp_vertical.CAP_CHARGE_DC: MockChargeDcBackend(sink=outputs, now=world.now),
        },
        jobs=jobs,
        broker=broker,
        validity=registry.registries.backend_validity,
        now=world.now,
        domain=DOMAIN,
    )
    registry.install(SiliconPhotonicsPack(runner=runner, conditions=registry.registries.conditions))
    regs = registry.registries
    for capability_id in case.get("unavailable", ()):
        regs.capabilities.set_availability(capability_id, Availability.UNAVAILABLE)

    device = device_for(fx, case)
    device_artifact = outputs.put(
        project_id=PROJECT, media_type=DEVICE_PROJECT_MEDIA_TYPE, data=device.to_bytes()
    )

    # -- 3. the governed belief path, both comparator versions registered ------------------------
    authority = sp_vertical.VerticalAuthorityPolicy()
    v1 = SiliconPhotonicsAuthorityPolicy()
    episode = BeliefEpisode(
        policies=SqlTransitionPolicyStore(connection),
        decisions=SqlBeliefTransitionDecisionStore(connection),
        events=SqlBeliefEventStore(connection),
        relations=SqlRelationStore(connection),
        authority_classes=SqlAttestationStore(connection),
        conflicts=SqlConflictStore(connection),
        reviews=SqlReviewItemStore(connection),
        ids=ScopedCountingIds(scope),
        authority_policies={
            (v1.policy_id, v1.policy_version): v1,
            (authority.policy_id, authority.policy_version): authority,
        },
    )
    brain = HypothesisBrain(
        debate=world.debate,
        hypotheses=world.hypotheses,
        revision_gate=world.revision_gate,
        episode=episode,
        attestations=world.find_attestation,
    )
    evidence = SqlEvidenceSink(connection=connection, outputs=outputs)
    failures = SqlFailureStore(connection)
    inner = LeastCostPlanner(
        capabilities=regs.capabilities,
        metrics=regs.disagreement_metrics,
        validators=regs.validators,
        mint=world.mint,
        now=world.now,
        case_memory=failures,
    )
    planner: Any = (
        inner if strategy == LEAST_COST else SimulateFirstPlanner(inner, regs.capabilities)
    )
    plans: Any = SqlVerificationPlanStore(connection)
    if strategy == SIMULATE_FIRST:
        plans = InMemoryVerificationPlanStore()
        plans.add_policy(BASELINE_POLICY)
    deps = LoopDependencies(
        planner=planner,
        plans=plans,
        workflows=regs.workflows,
        capabilities=regs.capabilities,
        conditions=regs.conditions,
        authority_policy=authority,
        belief=episode,
        reviser=brain,
        history=SqlBeliefEventStore(connection).history,
        evidence=evidence,
        admission=EvidenceAdmissionGate(
            load_artifact=evidence.load_artifact,
            load_evidence_unit=lambda _unit: None,
            load_run=jobs.get_run,
            is_artifact_in_project=evidence.artifact_in_project,
        ),
        jobs=jobs,
        dispatcher=BudgetedToolDispatcher(
            tools=regs.tools,
            capabilities=regs.capabilities,
            spans=SqlSpanRepository(connection),
            ledger=SqlCostLedger(connection),
            jobs=jobs,
            claims=SqlBudgetApprovalClaims(connection),
            now=world.now,
        ),
        failures=failures,
        mint=world.mint,
        now=world.now,
    )
    request = LoopRequest(
        project_id=PROJECT,
        episode_id=episode_id,
        trace_id=TRACE,
        actor_id=ACTOR,
        hypothesis_set=debate.hypothesis_set,
        certificates=debate.certificates,
        symptom=fx["symptom"],
        expected_behavior=fx["expected_behavior"],
        observed_behavior=fx["observed_behavior"],
        input_artifacts=(device_artifact,),
        available_inputs=frozenset({INPUT_DEVICE_PROJECT}),
        conditions=device.conditions(),
        conditions_schema_version=sp_vertical.DEVICE_SCHEMA_REF,
        selection_policy=(
            sp_vertical.selection_policy() if strategy == LEAST_COST else BASELINE_POLICY
        ),
        targets=tuple(
            TransitionTarget(policy=policy, to_state=to_state)
            for policy, to_state in sp_vertical.diagnosis_targets()
        ),
        budget_policy=BudgetPolicy(
            policy_id="bp:vs001",
            policy_version="1.0.0",
            project_id=PROJECT,
            caps=BudgetCaps(wall_clock_s=10**8, license_seat_s=10**7, human_minutes=10**4),
        ),
    )
    result = VerificationLoop(deps).run(request)
    return VerticalRun(
        case_id=str(case["case_id"]),
        strategy=strategy,
        debate=debate,
        result=result,
        device_artifact_id=device_artifact,
        world=world,
        registry=registry,
        brain=brain,
        certificates_by_mechanism={
            _mechanism_key(fx, c.hypothesis.mechanism): c.hypothesis_id for c in debate.certificates
        },
    )


def run_with_history(
    connection: Any,
    fx: Mapping[str, Any],
    case: Mapping[str, Any],
    *,
    strategy: str = LEAST_COST,
) -> tuple[VerticalRun, tuple[VerticalRun, ...]]:
    """The case, after replaying every case its `history` names -- in order, same project."""
    earlier = tuple(
        run_case(connection, fx, case_by_id(fx, prior), strategy=strategy)
        for prior in case.get("history", ())
    )
    return run_case(connection, fx, case, strategy=strategy), earlier


# -- the benchmark ---------------------------------------------------------------------------


def record_for(run: VerticalRun, case: Mapping[str, Any]) -> CaseRecord:
    """What `root_cause_benchmark` judges, read off one episode's loop result."""
    capabilities = run.registry.registries.capabilities
    steps: list[StepRecord] = []
    for step in run.result.steps:
        if step.chosen is None or step.plan is None:
            continue
        chosen = capabilities.resolve(step.chosen)
        steps.append(
            StepRecord(
                action_id=step.chosen,
                action_type=chosen.action_type,
                executed=step.status is WorkflowStatus.EXECUTED,
                estimate=step.estimated_cost or CostVector(),
                sufficient_alternatives=tuple(
                    (action_id, capabilities.resolve(action_id).action_type)
                    for action_id, summary in sorted(step.plan.sufficiency_results.items())
                    if summary.sufficient and action_id != step.chosen
                ),
            )
        )
    last = run.result.steps[-1] if run.result.steps else None
    pending = (
        last.chosen
        if last is not None
        and last.chosen is not None
        and last.status is not WorkflowStatus.EXECUTED
        else None
    )
    return CaseRecord(
        case_id=run.case_id,
        strategy=run.strategy,
        stop=run.result.stop_reason.value,
        confirmed=run.mechanism_of(run.result.confirmed_root_cause),
        steps=tuple(steps),
        pending_action=pending,
        heuristic_candidates=len(run.result.candidates),
        expected=dict(case["expected"]),
        cheap_resolvable=bool(case["cheap_resolvable"]),
    )


def run_benchmark(connection: Any, reset: Callable[[Any], Any]) -> BenchmarkRun:
    """Every case under both strategies, each from a freshly reset database."""
    fx = load_fixture()
    records: list[CaseRecord] = []
    for strategy in STRATEGIES:
        for case in fx["cases"]:
            reset(connection)
            run, _ = run_with_history(connection, fx, case, strategy=strategy)
            records.append(record_for(run, case))
    return evaluate(
        records,
        benchmark_set_id=fx["benchmark_set_id"],
        fixture_digest=fixture_digest(),
        primary=LEAST_COST,
        baseline=SIMULATE_FIRST,
    )


__all__ = [
    "EPISODE",
    "FIXTURE_PATH",
    "HIGH_COST_TYPES",
    "LEAST_COST",
    "SIMULATE_FIRST",
    "STRATEGIES",
    "SimulateFirstPlanner",
    "VerticalRun",
    "VerticalScientist",
    "case_by_id",
    "device_for",
    "fixture_digest",
    "load_fixture",
    "record_for",
    "run_benchmark",
    "run_case",
    "run_with_history",
]
