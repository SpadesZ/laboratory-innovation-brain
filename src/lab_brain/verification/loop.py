"""VS-SP-001's research loop: plan -> Job -> evidence -> belief event -> failure memory (M4).

    §26.1 M4   competing hypotheses -> capability/cost planning -> Job -> evidence -> belief event
               -> failure/heuristic candidate
    §25.1      choose cheapest discriminative check -> run typed tool -> confirmed finding ->
               FailureAnalysis + Heuristic candidate -> belief update + provenance graph

A COMPOSITION OF GOVERNED PARTS, NOT A NEW AUTHORITY. Every decision this loop acts on is made
somewhere that already decides it, and is reused unchanged:

    what to do next         `LeastCostPlanner` -- §9.1 sufficiency, Pareto, SelectionPolicy;
                            persisted as a VerificationPlan (`011k` checks VER-001 in SQL)
    how to do it            the DomainPack's `VerificationWorkflow`, through the typed ToolRegistry
                            and `BudgetedToolDispatcher` (COST-001), producing a Job and a Run
    what the result is      the workflow's versioned rule, over the Run's STORED output
    whether it is evidence  M1's `EvidenceAdmissionGate` (EVI-003, EVI-009)
    what it supports        the hypotheses' own admitted Predictions (`verification.evidence`)
    whether belief moves    `TransitionPolicy.evaluate`, through the reviser -- M3's
                            `HypothesisBrain`, which runs the EPI-001/SRC-002/§7.6 preconditions
                            and then M1's governed `BeliefEpisode`, unchanged
    whether it is a cause   `core.root_cause` (EPI-002), and `011l` again in SQL

The loop decides only what the pieces cannot: when to stop.

THE LOOP, PER STEP:

    1. revise     for each rival, every governed move whose `evaluate` on the ADMITTED evidence is
                  ALLOW is attempted through the reviser, in the pack's declared target order. The
                  loop evaluates first so it never asks the governed path for a move the evidence
                  cannot license, and never forces one: a precondition the reviser refuses (an
                  un-critiqued REJECT, say) is recorded and the rival stays where it is. A rival
                  holding both SUPPORTS and CONTRADICTS evidence is not moved at all -- that is a
                  disagreement for a person, not an ordering for the loop.
    2. stop?      a SUPPORTED rival ends the loop: a root cause is confirmable.
    3. plan       the planner sees every rival's current state, excludes capabilities already
                  executed in this episode, and records a plan -- including when it chooses
                  nothing, because "no action can change any decision" is a finding.
    4. execute    the chosen capability's workflow runs against a durable Job. A capability with no
                  workflow (a measurement, a fabrication) stops the loop: a person must act.
                  A seat that is not free stops it as AWAITING_RESOURCE; the Job is parked, not
                  failed (§10.7). A budget refusal stops it as BUDGET_BLOCKED.
    5. admit      each outcome becomes Observation -> Attestation (through the admission gate) ->
                  the relations its predictions declare, with the ConditionMatch between the Run's
                  conditions and the diagnosis's.

INDEPENDENCE, FOR RUN-DERIVED EVIDENCE, IS COUNTED BY EXECUTION. §6.17's WORK basis counts
attestations of one work once. A verification result's work is the execution that produced it: two
attestations read off one Run are one source, two Runs are two. Evidence that reaches no Run
contributes to `unknown_count`, never to the independent count (EVI-004).

AT THE END, ALWAYS A FAILURE ANALYSIS. CONFIRMED when a SUPPORTED rival's support traces to a Run
and its Artifacts; OPEN when the loop stopped waiting on a person, a seat or a budget; INCONCLUSIVE
when nothing sufficient remained. After a confirmation the miner proposes PENDING_REVIEW candidates
from recurring confirmed failures (HEU-001's approval is M7's).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from lab_brain.core.belief import EpistemicStateProjection
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.episode import EpisodeRefused, EpisodeResult
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefRevisionEvent, BeliefState
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.enums import IndependenceBasis, RelationType
from lab_brain.core.models.failure import CandidateHeuristic, FailureAnalysis, ResolutionStatus
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.job import Job
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionOutcome,
)
from lab_brain.core.models.verification import SelectionPolicy, VerificationPlan
from lab_brain.core.repositories.failures import FailureStore
from lab_brain.core.repositories.jobs import JobStore
from lab_brain.core.repositories.verification_plans import VerificationPlanStore
from lab_brain.core.revision_gate import RevisionPreconditionFailed
from lab_brain.core.root_cause import (
    MinedEvidence,
    RootCauseRefused,
    RootCauseTrace,
    confirm_root_cause,
    mine_candidate_heuristics,
    trace_root_cause,
)
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.ingestion.admission_gate import AdmissionRequest
from lab_brain.tools.contracts import ToolRequest
from lab_brain.tools.dispatch import BudgetedToolDispatcher, ToolAction, ToolDispatchResult
from lab_brain.tools.execution import submit_simulation_job
from lab_brain.tools.resources import ResourceDemand
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.evidence import RunEvidence, evidence_from_run
from lab_brain.verification.least_cost import PlanningResult
from lab_brain.verification.sufficiency import HypothesisState, TransitionTarget
from lab_brain.verification.workflows import (
    ObservedOutcome,
    WorkflowContext,
    WorkflowRegistry,
    WorkflowResult,
    WorkflowStatus,
)

if TYPE_CHECKING:  # pragma: no cover
    from lab_brain.core.authority import AuthorityPolicy


class StopReason(StrEnum):
    CONFIRMED = "CONFIRMED"
    NO_SUFFICIENT_ACTION = "NO_SUFFICIENT_ACTION"
    #: The planner found the admitted evidence already licenses a move the reviser then refused.
    REVISION_REFUSED = "REVISION_REFUSED"
    HUMAN_ACTION_REQUIRED = "HUMAN_ACTION_REQUIRED"
    AWAITING_RESOURCE = "AWAITING_RESOURCE"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    MAX_STEPS = "MAX_STEPS"


#: Stops that wait on something outside the loop; the analysis stays OPEN.
_WAITING = frozenset(
    {StopReason.HUMAN_ACTION_REQUIRED, StopReason.AWAITING_RESOURCE, StopReason.BUDGET_BLOCKED}
)


class Planner(Protocol):
    def plan(self, **kwargs: Any) -> PlanningResult: ...


class Reviser(Protocol):
    """M3's `HypothesisBrain.attempt_revision`, which is the only path for a certified rival."""

    def attempt_revision(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        policy_id: str,
        policy_version: str,
        candidate_to_state: BeliefState,
        occurred_at: dt.datetime,
        trace_id: str,
        triggering_attestations: Sequence[Attestation],
        actor_id: str | None = None,
        authority_policy_ref: tuple[str, str] | None = None,
        condition_matches: Sequence[ConditionMatch] = (),
        independence_summary: IndependenceSummary | None = None,
        inference_provenance_id: str | None = None,
        rationale_artifact_or_record_ref: str | None = None,
    ) -> EpisodeResult: ...


class BeliefReader(Protocol):
    """The read half of M1's `BeliefEpisode`."""

    def project(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        quarantined_attestation_ids: Sequence[str] = (),
        projected_at: dt.datetime | None = None,
    ) -> EpistemicStateProjection: ...

    def hypothesis_view(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        current_state: BeliefState,
        stakes: str,
        admitted_relations: Sequence[RelationJudgment],
    ) -> HypothesisView: ...


class EvidenceSink(Protocol):
    """Where admitted evidence is written. The SQL stores satisfy it together."""

    def add_observation(self, observation: Observation) -> Observation: ...

    def add_attestation(self, attestation: Attestation) -> Attestation: ...

    def add_relation(self, relation: RelationJudgment) -> RelationJudgment: ...

    def add_condition_match(self, match: ConditionMatch) -> ConditionMatch: ...

    def attestation(self, project_id: str, attestation_id: str) -> Attestation | None: ...

    def observation(self, project_id: str, observation_id: str) -> Observation | None: ...

    def relation(self, project_id: str, relation_id: str) -> RelationJudgment | None: ...

    def admitted_for_subject(
        self, project_id: str, subject_id: str
    ) -> tuple[RelationJudgment, ...]: ...

    def condition_match(self, condition_match_id: str) -> ConditionMatch | None: ...

    def artifact_exists(self, artifact_id: str) -> bool: ...

    def read_artifact(self, artifact_id: str) -> bytes: ...


class AdmissionGate(Protocol):
    def admit(self, request: AdmissionRequest) -> Attestation: ...


@dataclass(frozen=True)
class LoopDependencies:
    planner: Planner
    plans: VerificationPlanStore
    workflows: WorkflowRegistry
    capabilities: CapabilityRegistry
    conditions: ConditionSchemaRegistry
    authority_policy: AuthorityPolicy
    belief: BeliefReader
    reviser: Reviser
    history: Callable[[str, str], Sequence[BeliefRevisionEvent]]
    evidence: EvidenceSink
    admission: AdmissionGate
    jobs: JobStore
    dispatcher: BudgetedToolDispatcher
    failures: FailureStore
    mint: Callable[[str], str]
    now: Callable[[], dt.datetime]


@dataclass(frozen=True)
class LoopRequest:
    project_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    hypothesis_set: HypothesisSet
    certificates: tuple[HypothesisCertificate, ...]
    symptom: str
    expected_behavior: str
    observed_behavior: str
    input_artifacts: tuple[str, ...]
    available_inputs: frozenset[str]
    conditions: Mapping[str, Any]
    conditions_schema_version: str
    selection_policy: SelectionPolicy
    targets: tuple[TransitionTarget, ...]
    budget_policy: BudgetPolicy | None
    max_steps: int = 8


@dataclass(frozen=True)
class Transition:
    hypothesis_id: str
    policy_ref: str
    from_state: str
    to_state: str
    #: The BeliefRevisionEvent written, or `None` with the refusal recorded.
    event_id: str | None
    refusal: str | None = None


@dataclass(frozen=True)
class LoopStep:
    index: int
    transitions: tuple[Transition, ...]
    plan: VerificationPlan | None = None
    chosen: str | None = None
    estimated_cost: CostVector | None = None
    status: WorkflowStatus | None = None
    job_id: str | None = None
    run_id: str | None = None
    outcomes: tuple[ObservedOutcome, ...] = ()
    attestation_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class LoopResult:
    stop_reason: StopReason
    steps: tuple[LoopStep, ...]
    failure_analysis: FailureAnalysis
    trace: RootCauseTrace | None = None
    candidates: tuple[CandidateHeuristic, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def executed(self) -> tuple[str, ...]:
        return tuple(
            s.chosen
            for s in self.steps
            if s.chosen is not None and s.status is WorkflowStatus.EXECUTED
        )

    @property
    def plans(self) -> tuple[VerificationPlan, ...]:
        return tuple(s.plan for s in self.steps if s.plan is not None)

    @property
    def confirmed_root_cause(self) -> str | None:
        return self.failure_analysis.confirmed_root_cause


class VerificationLoop:
    def __init__(self, dependencies: LoopDependencies) -> None:
        self._d = dependencies

    # -- the loop ----------

    def run(self, request: LoopRequest) -> LoopResult:
        d = self._d
        d.plans.add_policy(request.selection_policy)
        executed: list[str] = []
        steps: list[LoopStep] = []
        notes: list[str] = []
        stop = StopReason.MAX_STEPS
        for index in range(request.max_steps):
            transitions = self._revise(request, notes)
            if self._supported(request):
                steps.append(LoopStep(index=index, transitions=transitions))
                stop = StopReason.CONFIRMED
                break
            result = d.planner.plan(
                project_id=request.project_id,
                episode_id=request.episode_id,
                hypotheses=self._states(request),
                targets=request.targets,
                policy=request.selection_policy,
                authority_policy=d.authority_policy,
                available_inputs=request.available_inputs,
                conditions=request.conditions,
                symptom=request.symptom,
                exclude=frozenset(executed),
                projected_condition_match=self._projected_match(request),
            )
            plan = d.plans.add_plan(result.plan)
            decision = plan.rationale.decision.value
            if decision == "EXISTING_EVIDENCE_DECIDES":
                steps.append(LoopStep(index=index, transitions=transitions, plan=plan))
                stop = StopReason.REVISION_REFUSED
                break
            chosen = plan.chosen_action_id
            if chosen is None:
                steps.append(LoopStep(index=index, transitions=transitions, plan=plan))
                stop = StopReason.NO_SUFFICIENT_ACTION
                break
            estimate = result.costs.get(chosen)
            workflow = d.workflows.resolve(chosen)
            if workflow is None:
                steps.append(
                    LoopStep(
                        index=index,
                        transitions=transitions,
                        plan=plan,
                        chosen=chosen,
                        estimated_cost=estimate,
                        detail=(
                            f"{chosen} has no workflow in any installed pack: executing it is a "
                            "person's act, and the plan says which one"
                        ),
                    )
                )
                stop = StopReason.HUMAN_ACTION_REQUIRED
                break
            job = self._submit(request, chosen, index)
            outcome = workflow.execute(self._context(request, chosen, job, index))
            step = LoopStep(
                index=index,
                transitions=transitions,
                plan=plan,
                chosen=chosen,
                estimated_cost=estimate,
                status=outcome.status,
                job_id=job.job_id,
                run_id=outcome.run_id,
                outcomes=outcome.outcomes,
                detail=outcome.detail,
            )
            if outcome.status is not WorkflowStatus.EXECUTED:
                steps.append(step)
                stop = {
                    WorkflowStatus.AWAITING_RESOURCE: StopReason.AWAITING_RESOURCE,
                    WorkflowStatus.BUDGET_BLOCKED: StopReason.BUDGET_BLOCKED,
                    WorkflowStatus.FAILED: StopReason.EXECUTION_FAILED,
                }[outcome.status]
                break
            executed.append(chosen)
            admitted = self._admit(request, outcome)
            steps.append(
                LoopStep(
                    **{
                        **step.__dict__,
                        "attestation_ids": tuple(e.attestation.attestation_id for e in admitted),
                        "relation_ids": tuple(r.relation_id for e in admitted for r in e.relations),
                    }
                )
            )
        return self._conclude(request, stop, tuple(steps), tuple(notes))

    # -- 1. revise ----------

    def _revise(self, request: LoopRequest, notes: list[str]) -> tuple[Transition, ...]:
        d = self._d
        done: list[Transition] = []
        for certificate in sorted(request.certificates, key=lambda c: c.hypothesis_id):
            hypothesis_id = certificate.hypothesis_id
            for _ in range(len(request.targets)):
                state = self._state(request, hypothesis_id)
                if state is None:
                    break
                admitted = d.evidence.admitted_for_subject(request.project_id, hypothesis_id)
                kinds = {r.relation_type for r in admitted}
                if {RelationType.SUPPORTS, RelationType.CONTRADICTS} <= kinds:
                    note = (
                        f"{hypothesis_id} holds both SUPPORTS and CONTRADICTS evidence; the loop "
                        "does not choose between them"
                    )
                    if note not in notes:
                        notes.append(note)
                    break
                matches = self._matches(admitted)
                independence = self._independence(request.project_id, admitted)
                view = d.belief.hypothesis_view(
                    project_id=request.project_id,
                    hypothesis_id=hypothesis_id,
                    current_state=state,
                    stakes=request.hypothesis_set.stakes,
                    admitted_relations=admitted,
                )
                moved = False
                for target in request.targets:
                    policy = target.policy
                    if policy.from_state is not state:
                        continue
                    verdict = policy.evaluate(
                        view, admitted, d.authority_policy, matches, independence, target.to_state
                    )
                    if verdict.outcome is not TransitionOutcome.ALLOW:
                        continue
                    transition = self._attempt(
                        request, hypothesis_id, target, state, admitted, matches, independence
                    )
                    done.append(transition)
                    moved = transition.event_id is not None
                    break
                if not moved:
                    break
        return tuple(done)

    def _attempt(
        self,
        request: LoopRequest,
        hypothesis_id: str,
        target: TransitionTarget,
        state: BeliefState,
        admitted: Sequence[RelationJudgment],
        matches: tuple[ConditionMatch, ...],
        independence: IndependenceSummary,
    ) -> Transition:
        d = self._d
        policy = target.policy
        ref = f"{policy.policy_id}@{policy.version}"
        triggering = self._supporting_attestations(request.project_id, admitted)
        try:
            result = d.reviser.attempt_revision(
                project_id=request.project_id,
                hypothesis_id=hypothesis_id,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                candidate_to_state=target.to_state,
                occurred_at=d.now(),
                trace_id=request.trace_id,
                triggering_attestations=triggering,
                actor_id=request.actor_id,
                authority_policy_ref=(
                    d.authority_policy.policy_id,
                    d.authority_policy.policy_version,
                ),
                condition_matches=matches,
                independence_summary=independence,
            )
        except (RevisionPreconditionFailed, EpisodeRefused) as refused:
            return Transition(
                hypothesis_id, ref, state.value, target.to_state.value, None, str(refused)
            )
        event = result.event
        return Transition(
            hypothesis_id,
            ref,
            state.value,
            target.to_state.value,
            None if event is None else event.event_id,
            None if event is not None else result.decision.reason_code.value,
        )

    # -- 3/4. plan inputs and execution ----------

    def _states(self, request: LoopRequest) -> tuple[HypothesisState, ...]:
        d = self._d
        states: list[HypothesisState] = []
        for certificate in sorted(request.certificates, key=lambda c: c.hypothesis_id):
            state = self._state(request, certificate.hypothesis_id)
            if state is None:
                continue
            admitted = d.evidence.admitted_for_subject(
                request.project_id, certificate.hypothesis_id
            )
            states.append(
                HypothesisState(
                    view=d.belief.hypothesis_view(
                        project_id=request.project_id,
                        hypothesis_id=certificate.hypothesis_id,
                        current_state=state,
                        stakes=request.hypothesis_set.stakes,
                        admitted_relations=admitted,
                    ),
                    admitted_relations=admitted,
                    predictions=certificate.predictions,
                    condition_matches=self._matches(admitted),
                    independence=self._independence(request.project_id, admitted),
                )
            )
        return tuple(states)

    def _projected_match(self, request: LoopRequest) -> ConditionMatch:
        """The match a planned execution will have: the loop runs it under the diagnosis's own
        conditions, so this is computed -- by the registered comparator -- before it runs."""
        return self._d.conditions.compare(
            request.conditions, request.conditions, request.conditions_schema_version
        )

    def _submit(self, request: LoopRequest, capability_id: str, index: int) -> Job:
        d = self._d
        capability = d.capabilities.resolve(capability_id)
        demand = (
            ResourceDemand(resource_id=capability.license_constraints[0], seats=1)
            if capability.license_constraints
            else None
        )
        job = Job(
            job_id=d.mint("job"),
            project_id=request.project_id,
            episode_id=request.episode_id,
            capability_id=capability_id,
            trace_id=request.trace_id,
            idempotency_key=f"vs:{request.episode_id}:{index}:{capability_id}",
            submitted_at=d.now(),
        )
        return submit_simulation_job(jobs=d.jobs, job=job, demand=demand, capability=capability)

    def _context(
        self, request: LoopRequest, capability_id: str, job: Job, index: int
    ) -> WorkflowContext:
        d = self._d
        capability = d.capabilities.resolve(capability_id)

        def dispatch(tool_id: str, tool_request: ToolRequest) -> ToolDispatchResult:
            key = f"{job.job_id.split(':', 1)[-1]}-{tool_id.lower()}"
            return d.dispatcher.dispatch(
                ToolAction(
                    tool_id=tool_id,
                    request=tool_request,
                    project_id=request.project_id,
                    episode_id=request.episode_id,
                    actor_or_slot=request.actor_id,
                    action_ref=f"act:{key}",
                    trace_id=request.trace_id,
                    span_id=f"spn:{key}",
                    estimate_entry_id=f"cst:{key}-est",
                    actual_entry_id=f"cst:{key}-act",
                    actor_id=request.actor_id,
                ),
                policy=request.budget_policy,
            )

        return WorkflowContext(
            project_id=request.project_id,
            episode_id=request.episode_id,
            trace_id=request.trace_id,
            actor_id=request.actor_id,
            capability=capability,
            job_id=job.job_id,
            request_id=f"req:{job.job_id.split(':', 1)[-1]}",
            input_artifacts=request.input_artifacts,
            conditions=request.conditions,
            conditions_schema_version=request.conditions_schema_version,
            resource_demand=(
                ResourceDemand(resource_id=capability.license_constraints[0], seats=1)
                if capability.license_constraints
                else None
            ),
            dispatch=dispatch,
            read_artifact=d.evidence.read_artifact,
            load_run=d.jobs.get_run,
        )

    # -- 5. admit ----------

    def _admit(self, request: LoopRequest, outcome: WorkflowResult) -> tuple[RunEvidence, ...]:
        d = self._d
        assert outcome.run_id is not None
        run = d.jobs.get_run(outcome.run_id)
        assert run is not None  # the workflow just read it
        capability = d.capabilities.resolve(run.capability_id)
        match = d.conditions.compare(
            dict(run.conditions), request.conditions, request.conditions_schema_version
        )
        stored_match = d.evidence.add_condition_match(
            match.model_copy(
                update={
                    "condition_match_id": d.mint("condition_match"),
                    "created_at": d.now(),
                }
            )
        )
        predictions = tuple(p for c in request.certificates for p in c.predictions)
        admitted: list[RunEvidence] = []
        for observed in outcome.outcomes:
            if observed.observable_ref not in capability.produces:
                raise ValueError(
                    f"{run.capability_id} reported {observed.observable_ref}, which it does not "
                    "declare it produces; a workflow may not report undeclared observables"
                )
            evidence = evidence_from_run(
                run=run,
                outcome=observed,
                predictions=predictions,
                condition_match=stored_match,
                actor_id=request.actor_id,
                mint=d.mint,
                at=d.now(),
            )
            # EVI-003 / EVI-009 first: refused evidence raises before anything is written.
            attestation = d.admission.admit(AdmissionRequest(attestation=evidence.attestation))
            d.evidence.add_observation(evidence.observation)
            d.evidence.add_attestation(attestation)
            for relation in evidence.relations:
                d.evidence.add_relation(relation)
            admitted.append(evidence)
        return tuple(admitted)

    # -- reads ----------

    def _state(self, request: LoopRequest, hypothesis_id: str) -> BeliefState | None:
        projection = self._d.belief.project(
            project_id=request.project_id, hypothesis_id=hypothesis_id, projected_at=self._d.now()
        )
        return projection.current_state

    def _supported(self, request: LoopRequest) -> str | None:
        for certificate in sorted(request.certificates, key=lambda c: c.hypothesis_id):
            if self._state(request, certificate.hypothesis_id) is BeliefState.SUPPORTED:
                return certificate.hypothesis_id
        return None

    def _matches(self, admitted: Sequence[RelationJudgment]) -> tuple[ConditionMatch, ...]:
        refs = sorted({r.condition_match_ref for r in admitted if r.condition_match_ref})
        found = [self._d.evidence.condition_match(ref) for ref in refs]
        return tuple(m for m in found if m is not None)

    def _supporting_attestations(
        self, project_id: str, admitted: Sequence[RelationJudgment]
    ) -> tuple[Attestation, ...]:
        ids = sorted({a for r in admitted for a in r.supporting_attestation_ids})
        found = [self._d.evidence.attestation(project_id, a) for a in ids]
        return tuple(a for a in found if a is not None)

    def _independence(
        self, project_id: str, admitted: Sequence[RelationJudgment]
    ) -> IndependenceSummary:
        runs: set[str] = set()
        unknown = 0
        for attestation in self._supporting_attestations(project_id, admitted):
            run_id = attestation.run_id
            if run_id is None and attestation.observation_id is not None:
                observation = self._d.evidence.observation(project_id, attestation.observation_id)
                run_id = None if observation is None else observation.run_id
            if run_id is None:
                unknown += 1
            else:
                runs.add(run_id)
        return IndependenceSummary(
            basis=IndependenceBasis.WORK, independent_count=len(runs), unknown_count=unknown
        )

    # -- conclusion ----------

    def _trace(self, project_id: str, hypothesis_id: str) -> RootCauseTrace:
        d = self._d
        return trace_root_cause(
            project_id=project_id,
            hypothesis_id=hypothesis_id,
            history=d.history,
            relation=d.evidence.relation,
            attestation=d.evidence.attestation,
            observation=d.evidence.observation,
            run=d.jobs.get_run,
            artifact_exists=d.evidence.artifact_exists,
        )

    def _conclude(
        self,
        request: LoopRequest,
        stop: StopReason,
        steps: tuple[LoopStep, ...],
        notes: tuple[str, ...],
    ) -> LoopResult:
        d = self._d
        causes = tuple(sorted(c.hypothesis_id for c in request.certificates))
        supported = self._supported(request)
        trace: RootCauseTrace | None = None
        extra: list[str] = list(notes)
        analysis: FailureAnalysis | None = None
        if stop is StopReason.CONFIRMED and supported is not None:
            certificate = next(c for c in request.certificates if c.hypothesis_id == supported)
            try:
                trace = self._trace(request.project_id, supported)
                analysis = confirm_root_cause(
                    hypothesis_set=request.hypothesis_set,
                    hypothesis_id=supported,
                    candidate_causes=causes,
                    trace=trace,
                    failure_analysis_id=d.mint("failure_analysis"),
                    symptom=request.symptom,
                    expected_behavior=request.expected_behavior,
                    observed_behavior=request.observed_behavior,
                    failure_class=certificate.hypothesis.mechanism,
                    created_at=d.now(),
                )
            except RootCauseRefused as refused:
                extra.append(f"{supported} is SUPPORTED but not confirmable: {refused}")
                stop = StopReason.NO_SUFFICIENT_ACTION
        if analysis is None:
            analysis = FailureAnalysis(
                failure_analysis_id=d.mint("failure_analysis"),
                project_id=request.project_id,
                episode_id=request.episode_id,
                symptom=request.symptom,
                expected_behavior=request.expected_behavior,
                observed_behavior=request.observed_behavior,
                candidate_causes=causes,
                failure_class="UNRESOLVED",
                resolution_status=(
                    ResolutionStatus.OPEN if stop in _WAITING else ResolutionStatus.INCONCLUSIVE
                ),
                created_at=d.now(),
            )
        stored = d.failures.add_analysis(analysis)
        candidates: tuple[CandidateHeuristic, ...] = ()
        if stored.resolution_status is ResolutionStatus.CONFIRMED:
            candidates = self._mine(request.project_id)
        return LoopResult(
            stop_reason=stop,
            steps=steps,
            failure_analysis=stored,
            trace=trace,
            candidates=candidates,
            notes=tuple(extra),
        )

    def _mine(self, project_id: str) -> tuple[CandidateHeuristic, ...]:
        d = self._d
        confirmed = [
            f
            for f in d.failures.analyses(project_id)
            if f.resolution_status is ResolutionStatus.CONFIRMED
        ]
        evidence: dict[str, MinedEvidence] = {}
        usable: list[FailureAnalysis] = []
        for failure in confirmed:
            assert failure.confirmed_root_cause is not None
            try:
                trace = self._trace(project_id, failure.confirmed_root_cause)
            except RootCauseRefused:
                # The cause is no longer SUPPORTED (a later event moved it). Its analysis stays on
                # record; it no longer supports a generalisation.
                continue
            evidence[failure.failure_analysis_id] = MinedEvidence(
                capability_ids=trace.capability_ids,
                artifact_ids=trace.artifact_ids,
                run_ids=trace.run_ids,
            )
            usable.append(failure)
        proposed = mine_candidate_heuristics(
            usable,
            evidence_for=evidence,
            existing=d.failures.candidates(project_id),
            mint=d.mint,
            now=d.now,
        )
        return tuple(d.failures.add_candidate(c) for c in proposed)


__all__ = [
    "AdmissionGate",
    "BeliefReader",
    "EvidenceSink",
    "LoopDependencies",
    "LoopRequest",
    "LoopResult",
    "LoopStep",
    "Planner",
    "Reviser",
    "StopReason",
    "Transition",
    "VerificationLoop",
]
