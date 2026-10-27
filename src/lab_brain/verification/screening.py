"""Exploratory screening: which low-cost readings to take where no hypothesis looks; taking them.

    selection   `select_screening` -- pure. From the admitted hypotheses' predictions (which
                observables someone discriminates on), the domain's prediction vocabulary, the
                registered typed capabilities, the pack's screening declarations, the inputs on
                hand and the declared `ScreeningPolicy`. Never from a device's content, a benchmark,
                a fixture label or an expected answer: the same hypotheses and the same deployment
                give the same plan for every device.
    execution   `ScreeningExecutor` -- each selected check runs as a durable Job through the
                pack's workflow and `BudgetedToolDispatcher` (COST-001), producing a Run whose
                outcome is read from its STORED output; the outcome is admitted as an Observation
                and an Attestation through the admission gate (EVI-003, EVI-009), with NO relation
                to any hypothesis; the plan and every result are persisted before the stage ends.

CHEAPEST-SUFFICIENT, NOT "RUN EVERYTHING CHEAP". A screening stage considers only observables no
admitted hypothesis makes a SUPPORTS or CONTRADICTS prediction over -- whatever someone predicts is
verification's to plan, by the cheapest sufficient action. Of those, only capabilities the pack
declares screenable, in the cheapest tiers, available here, local, needing no person, money, seat
or irreversible act, are eligible; they are ordered by estimated wall clock, then compute, then
capability id (deterministic), and cut by `max_checks` and the stage's wall-clock budget. A reading
already taken in this episode on the same input is not taken again (`ALREADY_SCREENED`): a repeat of
a deterministic reading is not a second piece of evidence.

STOPPING. The stage ends when every selected check has run, or -- under `stop_on_failure` -- at the
first check that failed, found no seat or was refused by the budget gate; the checks after it are
recorded NOT_RUN. An abnormal reading does not stop the stage: two faults in one device must not be
decided by which check id sorts first.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.capability import Availability
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.hypothesis_set import HypothesisCertificate
from lab_brain.core.models.job import Job
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.core.models.screening import (
    SCREENING_ACTION_TYPES,
    CandidateDisposition,
    ConditionedHypothesis,
    ScreeningCandidate,
    ScreeningFinding,
    ScreeningNorm,
    ScreeningObservation,
    ScreeningPlan,
    ScreeningPolicy,
    ScreeningReading,
    ScreeningStatus,
    inputs_key,
)
from lab_brain.core.warrant import evidence_line
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.ingestion.admission_gate import AdmissionRequest
from lab_brain.tools.contracts import ToolRequest
from lab_brain.tools.dispatch import BudgetedToolDispatcher, ToolAction, ToolDispatchResult
from lab_brain.tools.execution import submit_simulation_job
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.evidence import evidence_from_run
from lab_brain.verification.workflows import (
    WorkflowContext,
    WorkflowRegistry,
    WorkflowStatus,
)

#: The policy research runs screen under. Two checks, a minute of estimated wall clock in all, ten
#: seconds for any one -- fixed before any evaluation, the same for every device.
RESEARCH_SCREENING_POLICY = ScreeningPolicy(
    policy_id="screening:research-run",
    version="1.0.0",
    max_checks=2,
    max_wall_clock_s=60,
    max_check_wall_clock_s=10,
    stop_on_failure=True,
)

#: The Job key prefix of a screening check: never a verification key (`vs:`), so a continuation's
#: reading of what verification executed is never confused with what screening looked at.
SCREENING_KEY_PREFIX = "scr:"


def discriminated_observables(certificates: Sequence[HypothesisCertificate]) -> frozenset[str]:
    """Observables some admitted hypothesis makes a SUPPORTS or CONTRADICTS prediction over --
    `cognition.coverage.discriminated`'s rule, which the coverage review reads too."""
    return frozenset(
        p.observable_ref
        for c in certificates
        for p in c.predictions
        if any(
            t.relation_type in (RelationType.SUPPORTS, RelationType.CONTRADICTS)
            for t in p.relation_effect_if_observed
        )
    )


def select_screening(
    *,
    plan_id: str,
    project_id: str,
    episode_id: str,
    trace_id: str,
    actor_id: str,
    hypothesis_set_id: str,
    certificates: Sequence[HypothesisCertificate],
    bindings: Mapping[str, OutcomeSpace],
    capabilities: CapabilityRegistry,
    workflows: WorkflowRegistry,
    norms: Mapping[str, ScreeningNorm],
    available_inputs: Collection[str],
    input_artifacts: Sequence[str],
    already_screened: Collection[str],
    policy: ScreeningPolicy,
    now: dt.datetime,
) -> ScreeningPlan:
    """The screening plan for this state. Pure and deterministic; see the module docstring."""
    covered = discriminated_observables(certificates)
    vocabulary = frozenset(bindings)
    unaddressed = tuple(sorted(vocabulary - covered))
    available = frozenset(available_inputs)
    taken = frozenset(already_screened)
    considered: list[ScreeningCandidate] = []
    eligible: list[ScreeningCandidate] = []
    for capability in sorted(capabilities, key=lambda c: c.capability_id):
        observables = tuple(sorted(frozenset(capability.produces) & vocabulary))
        if not observables:
            continue
        cost = capabilities.estimate(capability.capability_id, {})
        norm = norms.get(capability.capability_id)
        disposition, detail = _disposition(
            capability=capability,
            observables=observables,
            covered=covered,
            norm=norm,
            cost=cost,
            available=available,
            has_workflow=workflows.resolve(capability.capability_id) is not None,
            already=inputs_key(capability.capability_id, input_artifacts) in taken,
            policy=policy,
        )
        candidate = ScreeningCandidate(
            capability_id=capability.capability_id,
            action_type=capability.action_type,
            observables=observables,
            estimated_cost=cost,
            disposition=disposition,
            detail=detail,
        )
        (eligible if disposition is CandidateDisposition.SELECTED else considered).append(candidate)
    spent = 0
    rank = 0
    for candidate in sorted(eligible, key=_order):
        cost = candidate.estimated_cost
        if rank >= policy.max_checks:
            considered.append(
                candidate.model_copy(
                    update={
                        "disposition": CandidateDisposition.OVER_MAX_CHECKS,
                        "detail": f"the policy takes at most {policy.max_checks} check(s)",
                    }
                )
            )
            continue
        if spent + cost.wall_clock_s > policy.max_wall_clock_s:
            considered.append(
                candidate.model_copy(
                    update={
                        "disposition": CandidateDisposition.OVER_STAGE_BUDGET,
                        "detail": (
                            f"{spent}s already selected; another {cost.wall_clock_s}s exceeds the "
                            f"stage's {policy.max_wall_clock_s}s"
                        ),
                    }
                )
            )
            continue
        rank += 1
        spent += cost.wall_clock_s
        considered.append(
            candidate.model_copy(
                update={
                    "rank": rank,
                    "detail": (
                        "no admitted hypothesis predicts "
                        + ", ".join(candidate.observables)
                        + "; outcome-independent low-cost reading"
                        + (f" -- {norms[candidate.capability_id].purpose}")
                    ),
                }
            )
        )
    return ScreeningPlan(
        plan_id=plan_id,
        project_id=project_id,
        episode_id=episode_id,
        trace_id=trace_id,
        actor_id=actor_id,
        hypothesis_set_id=hypothesis_set_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        considered_hypothesis_ids=tuple(sorted(c.hypothesis_id for c in certificates)),
        unaddressed_observables=unaddressed,
        input_artifacts=tuple(sorted(input_artifacts)),
        candidates=tuple(sorted(considered, key=lambda c: c.capability_id)),
        created_at=now,
    )


def _disposition(
    *,
    capability: Any,
    observables: tuple[str, ...],
    covered: frozenset[str],
    norm: ScreeningNorm | None,
    cost: CostVector,
    available: frozenset[str],
    has_workflow: bool,
    already: bool,
    policy: ScreeningPolicy,
) -> tuple[CandidateDisposition, str]:
    """The first rule a capability fails, in a fixed order, or SELECTED (eligible, not yet cut)."""
    if all(o in covered for o in observables):
        return (
            CandidateDisposition.ADDRESSED_BY_HYPOTHESIS,
            "an admitted hypothesis predicts what it observes; verification decides whether to run "
            "it",
        )
    if norm is None:
        return (
            CandidateDisposition.NOT_DECLARED_FOR_SCREENING,
            "the pack declares no reference outcome for it, so a reading could not be judged "
            "normal or abnormal",
        )
    if missing := sorted(set(observables) - set(norm.reference_outcomes)):
        return (
            CandidateDisposition.NOT_DECLARED_FOR_SCREENING,
            f"no reference outcome is declared for {', '.join(missing)}",
        )
    if capability.action_type not in SCREENING_ACTION_TYPES:
        return (
            CandidateDisposition.ACTION_TYPE_NOT_SCREENABLE,
            f"{capability.action_type.value} is not a reading of what is already there",
        )
    if capability.availability is not Availability.AVAILABLE:
        return (
            CandidateDisposition.UNAVAILABLE,
            f"it is {capability.availability.value} in this deployment",
        )
    if capability.license_constraints or cost.license_seat_s:
        return CandidateDisposition.LICENSED, "it needs a licence seat"
    if capability.irreversible or cost.irreversible:
        return CandidateDisposition.IRREVERSIBLE, "it cannot be undone"
    if cost.human_minutes or cost.money_estimate:
        return CandidateDisposition.NEEDS_PERSON_OR_MONEY, "it needs a person's time or money"
    if capability.privacy_constraints:
        return (
            CandidateDisposition.PRIVACY_CONSTRAINED,
            f"it declares privacy constraints {list(capability.privacy_constraints)}",
        )
    if not capability.satisfied_by(available):
        return (
            CandidateDisposition.INPUT_MISSING,
            f"it needs {', '.join(sorted(set(capability.requires) - available))}",
        )
    if not has_workflow:
        return CandidateDisposition.NO_WORKFLOW, "no installed workflow executes it here"
    if cost.wall_clock_s > policy.max_check_wall_clock_s:
        return (
            CandidateDisposition.OVER_CHECK_CEILING,
            f"estimated {cost.wall_clock_s}s, above the policy's {policy.max_check_wall_clock_s}s",
        )
    if already:
        return (
            CandidateDisposition.ALREADY_SCREENED,
            "the same reading of the same input was already taken in this episode",
        )
    return CandidateDisposition.SELECTED, ""


def _order(candidate: ScreeningCandidate) -> tuple[int, int, str]:
    return (
        candidate.estimated_cost.wall_clock_s,
        candidate.estimated_cost.compute_units,
        candidate.capability_id,
    )


# -- persistence seam ---------------------------------------------------------------------------


class ScreeningStore(Protocol):
    def add_plan(self, plan: ScreeningPlan) -> ScreeningPlan: ...

    def add_observation(self, observation: ScreeningObservation) -> ScreeningObservation: ...

    def add_conditioned(self, record: ConditionedHypothesis) -> ConditionedHypothesis: ...

    def screened_keys(self, project_id: str, episode_id: str) -> frozenset[str]: ...


class EvidenceWriter(Protocol):
    def add_observation(self, observation: Observation) -> Observation: ...

    def add_attestation(self, attestation: Attestation) -> Attestation: ...

    def add_condition_match(self, match: ConditionMatch) -> ConditionMatch: ...

    def read_artifact(self, artifact_id: str) -> bytes: ...


class AdmissionGate(Protocol):
    def admit(self, request: AdmissionRequest) -> Attestation: ...


@dataclass(frozen=True)
class ScreeningOutcome:
    plan: ScreeningPlan
    observations: tuple[ScreeningObservation, ...]

    @property
    def abnormal(self) -> tuple[ScreeningObservation, ...]:
        return tuple(o for o in self.observations if o.abnormal)

    @property
    def executed(self) -> tuple[ScreeningObservation, ...]:
        return tuple(o for o in self.observations if o.status is ScreeningStatus.EXECUTED)


@dataclass(frozen=True)
class ScreeningContext:
    """Where a screening stage runs: the episode, its actor, its input and its conditions."""

    project_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    input_artifacts: tuple[str, ...]
    available_inputs: frozenset[str]
    conditions: Mapping[str, Any]
    conditions_schema_version: str
    budget_policy: BudgetPolicy | None


class ScreeningExecutor:
    """Runs a `ScreeningPlan`'s selected checks. See the module docstring."""

    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry,
        workflows: WorkflowRegistry,
        conditions: ConditionSchemaRegistry,
        jobs: Any,
        dispatcher: BudgetedToolDispatcher,
        evidence: EvidenceWriter,
        admission: AdmissionGate,
        store: ScreeningStore,
        norms: Mapping[str, ScreeningNorm],
        policy: ScreeningPolicy,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._capabilities = capabilities
        self._workflows = workflows
        self._conditions = conditions
        self._jobs = jobs
        self._dispatcher = dispatcher
        self._evidence = evidence
        self._admission = admission
        self._store = store
        self._norms = norms
        self._policy = policy
        self._mint = mint
        self._now = now

    def screen(
        self,
        context: ScreeningContext,
        *,
        hypothesis_set_id: str,
        certificates: Sequence[HypothesisCertificate],
        bindings: Mapping[str, OutcomeSpace],
    ) -> ScreeningOutcome:
        """Select, persist the plan, run each selected check in order, persist each result."""
        plan = self._store.add_plan(
            select_screening(
                plan_id=self._mint("screening_plan"),
                project_id=context.project_id,
                episode_id=context.episode_id,
                trace_id=context.trace_id,
                actor_id=context.actor_id,
                hypothesis_set_id=hypothesis_set_id,
                certificates=certificates,
                bindings=bindings,
                capabilities=self._capabilities,
                workflows=self._workflows,
                norms=self._norms,
                available_inputs=context.available_inputs,
                input_artifacts=context.input_artifacts,
                already_screened=self._store.screened_keys(context.project_id, context.episode_id),
                policy=self._policy,
                now=self._now(),
            )
        )
        observations: list[ScreeningObservation] = []
        stopped: str | None = None
        for candidate in plan.selected:
            if stopped is not None:
                observations.append(
                    self._store.add_observation(
                        ScreeningObservation(
                            screening_observation_id=self._mint("screening_observation"),
                            plan_id=plan.plan_id,
                            project_id=plan.project_id,
                            episode_id=plan.episode_id,
                            rank=candidate.rank or 0,
                            capability_id=candidate.capability_id,
                            status=ScreeningStatus.NOT_RUN,
                            estimated_cost=candidate.estimated_cost,
                            detail=f"the stage stopped before it: {stopped}",
                            recorded_at=self._now(),
                        )
                    )
                )
                continue
            observation = self._store.add_observation(self._run(context, plan, candidate))
            observations.append(observation)
            if observation.status is not ScreeningStatus.EXECUTED and self._policy.stop_on_failure:
                stopped = f"{candidate.capability_id} {observation.status.value}"
        return ScreeningOutcome(plan=plan, observations=tuple(observations))

    def _run(
        self, context: ScreeningContext, plan: ScreeningPlan, candidate: ScreeningCandidate
    ) -> ScreeningObservation:
        capability = self._capabilities.resolve(candidate.capability_id)
        workflow = self._workflows.resolve(candidate.capability_id)
        assert workflow is not None  # NO_WORKFLOW candidates are never selected
        key = inputs_key(candidate.capability_id, context.input_artifacts)
        job = submit_simulation_job(
            jobs=self._jobs,
            job=Job(
                job_id=self._mint("job"),
                project_id=context.project_id,
                episode_id=context.episode_id,
                capability_id=candidate.capability_id,
                trace_id=context.trace_id,
                idempotency_key=f"{SCREENING_KEY_PREFIX}{context.episode_id}:{key}",
                submitted_at=self._now(),
            ),
            demand=None,
            capability=capability,
        )
        result = workflow.execute(self._context(context, capability, job))
        base: dict[str, Any] = {
            "screening_observation_id": self._mint("screening_observation"),
            "plan_id": plan.plan_id,
            "project_id": plan.project_id,
            "episode_id": plan.episode_id,
            "rank": candidate.rank or 0,
            "capability_id": candidate.capability_id,
            "job_id": job.job_id,
            "run_id": result.run_id,
            "estimated_cost": candidate.estimated_cost,
            "recorded_at": self._now(),
        }
        if result.status is not WorkflowStatus.EXECUTED:
            return ScreeningObservation(
                **base,
                status=ScreeningStatus(result.status.value),
                detail=result.detail or f"the check ended {result.status.value}",
            )
        assert result.run_id is not None
        run = self._jobs.get_run(result.run_id)
        assert run is not None  # the workflow just read it
        if str(run.environment.get("execution", "")) != "local":
            # The pack declared a local reading; a Run that says otherwise is not screened
            # evidence, whatever it observed.
            return ScreeningObservation(
                **{**base, "run_id": run.run_id},
                status=ScreeningStatus.FAILED,
                detail=(
                    f"the Run records execution {run.environment.get('execution')!r}; a screening "
                    "check must be a local reading that sends nothing out"
                ),
            )
        match = self._conditions.compare(
            dict(run.conditions), dict(context.conditions), context.conditions_schema_version
        )
        stored_match = self._evidence.add_condition_match(
            match.model_copy(
                update={
                    "condition_match_id": self._mint("condition_match"),
                    "created_at": self._now(),
                }
            )
        )
        norm = self._norms[candidate.capability_id]
        readings: list[ScreeningReading] = []
        for observed in result.outcomes:
            if observed.observable_ref not in capability.produces:
                raise ValueError(
                    f"{capability.capability_id} reported {observed.observable_ref}, which it does "
                    "not declare it produces"
                )
            # NO predictions: a screening reading relates to no hypothesis, ever.
            evidence = evidence_from_run(
                run=run,
                outcome=observed,
                predictions=(),
                condition_match=stored_match,
                actor_id=context.actor_id,
                mint=self._mint,
                at=self._now(),
            )
            assert not evidence.relations
            attestation = self._admission.admit(AdmissionRequest(attestation=evidence.attestation))
            self._evidence.add_observation(evidence.observation)
            self._evidence.add_attestation(attestation)
            reference = norm.reference_outcomes.get(observed.observable_ref)
            if reference is None:  # pragma: no cover - selection requires every observable's norm
                raise ValueError(f"no reference outcome for {observed.observable_ref}")
            readings.append(
                ScreeningReading(
                    observable_ref=observed.observable_ref,
                    outcome_space_id=observed.outcome_space_id,
                    outcome_space_version=observed.outcome_space_version,
                    outcome=observed.outcome,
                    reference_outcome=reference,
                    finding=(
                        ScreeningFinding.NORMAL
                        if observed.outcome == reference
                        else ScreeningFinding.ABNORMAL
                    ),
                    observation_id=evidence.observation.observation_id,
                    attestation_id=attestation.attestation_id,
                    method_ref=observed.method_ref,
                    detail=dict(observed.detail),
                )
            )
        return ScreeningObservation(
            **base,
            status=ScreeningStatus.EXECUTED,
            readings=tuple(readings),
            evidence_line=evidence_line((run,)),
            detail=result.detail,
        )

    def _context(self, context: ScreeningContext, capability: Any, job: Job) -> WorkflowContext:
        def dispatch(tool_id: str, tool_request: ToolRequest) -> ToolDispatchResult:
            key = f"{job.job_id.split(':', 1)[-1]}-{tool_id.lower()}"
            return self._dispatcher.dispatch(
                ToolAction(
                    tool_id=tool_id,
                    request=tool_request,
                    project_id=context.project_id,
                    episode_id=context.episode_id,
                    actor_or_slot=context.actor_id,
                    action_ref=f"act:{key}",
                    trace_id=context.trace_id,
                    span_id=f"spn:{key}",
                    estimate_entry_id=f"cst:{key}-est",
                    actual_entry_id=f"cst:{key}-act",
                    actor_id=context.actor_id,
                ),
                policy=context.budget_policy,
            )

        return WorkflowContext(
            project_id=context.project_id,
            episode_id=context.episode_id,
            trace_id=context.trace_id,
            actor_id=context.actor_id,
            capability=capability,
            job_id=job.job_id,
            request_id=f"req:{job.job_id.split(':', 1)[-1]}",
            input_artifacts=context.input_artifacts,
            conditions=context.conditions,
            conditions_schema_version=context.conditions_schema_version,
            resource_demand=None,
            dispatch=dispatch,
            read_artifact=self._evidence.read_artifact,
            load_run=self._jobs.get_run,
        )

    def condition(
        self,
        *,
        hypothesis_id: str,
        project_id: str,
        episode_id: str,
        plan_id: str,
        screening_observation_ids: Sequence[str],
        inference_id: str,
    ) -> ConditionedHypothesis:
        """Record that `hypothesis_id` was proposed after its author saw these observations."""
        return self._store.add_conditioned(
            ConditionedHypothesis(
                hypothesis_id=hypothesis_id,
                project_id=project_id,
                episode_id=episode_id,
                plan_id=plan_id,
                screening_observation_ids=tuple(screening_observation_ids),
                inference_id=inference_id,
                recorded_at=self._now(),
            )
        )


__all__ = [
    "RESEARCH_SCREENING_POLICY",
    "SCREENING_KEY_PREFIX",
    "ScreeningContext",
    "ScreeningExecutor",
    "ScreeningOutcome",
    "ScreeningStore",
    "discriminated_observables",
    "inputs_key",
    "select_screening",
]
