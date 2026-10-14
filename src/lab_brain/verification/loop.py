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
    TransitionReason,
)
from lab_brain.core.models.verification import SelectionPolicy, VerificationPlan
from lab_brain.core.models.warrant import (
    DiagnosticDeclaration,
    DiagnosticDeclarationSet,
    parse_domain_ref,
)
from lab_brain.core.repositories.failures import FailureStore
from lab_brain.core.repositories.jobs import JobStore
from lab_brain.core.repositories.protocols import RepositoryError
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
from lab_brain.core.warrant import evidence_line, observed_link
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
    #: Causal Warrant Gate. A person owes an answer on whether an observed outcome diagnoses a
    #: hypothesis's mechanism, and nothing else the loop could do would settle the question.
    AWAITING_REVIEW = "AWAITING_REVIEW"
    #: A member is SUPPORTED, but its support does not discriminate it: a rival affirms the same
    #: observation and nothing warranted excludes that rival, or the support itself is unwarranted.
    SUPPORTED_UNDISCRIMINATED = "SUPPORTED_UNDISCRIMINATED"
    #: Two members of different classes are SUPPORTED. The loop names both and confirms neither --
    #: never the one whose id happens to sort first.
    COMPETING_SUPPORT = "COMPETING_SUPPORT"


#: Stops that wait on something outside the loop; the analysis stays OPEN.
_WAITING = frozenset(
    {
        StopReason.HUMAN_ACTION_REQUIRED,
        StopReason.AWAITING_RESOURCE,
        StopReason.BUDGET_BLOCKED,
        StopReason.AWAITING_REVIEW,
        StopReason.SUPPORTED_UNDISCRIMINATED,
    }
)

#: Planner stops that mean "nothing more to do here" -- where an unconfirmed SUPPORTED member or
#: an unanswered warrant review is the more precise account of why the loop ended.
_EXHAUSTED = frozenset(
    {StopReason.NO_SUFFICIENT_ACTION, StopReason.REVISION_REFUSED, StopReason.MAX_STEPS}
)

#: Relation types that affirm an outcome: a rival holding one from the observation that supports
#: a candidate means that observation does not tell the two apart.
_AFFIRMING = frozenset({RelationType.SUPPORTS, RelationType.PREDICTS})


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


class WarrantReviews(Protocol):
    """Where the loop asks a person for a diagnostic warrant (`012o`)."""

    def enqueue_warrant_review(
        self,
        *,
        review_id: str,
        project_id: str,
        relation_id: str,
        stakes: str,
        reason: str,
        trace_id: str,
        episode_id: str | None,
        created_at: dt.datetime,
        estimated_minutes: int,
    ) -> str: ...


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
    #: Outstanding DIAGNOSTIC_WARRANT reviews. None means none can exist, so none are waited on.
    warrant_reviews: WarrantReviews | None = None
    #: The active diagnostic declaration set, so the planner can project which results a DOMAIN
    #: warrant would cover. The same set the belief path's resolver uses.
    declarations: DiagnosticDeclarationSet | None = None


@dataclass(frozen=True)
class Standing:
    """Where the root-cause set stands after a revision, for the confirmation rule.

    A cause is confirmed only when exactly one class is SUPPORTED by warranted support, no other
    member affirms the observation that support rests on unless a warranted refutation excludes
    it, the candidate carries no warranted refutation of its own, and no person still owes an
    answer that could overturn the conclusion. Confirmation is relative to the members proposed
    and the domain's declarations -- a mechanism nobody named is not excluded by any of this.
    """

    supported: tuple[str, ...] = ()
    confirmable: str | None = None
    competing: tuple[str, ...] = ()
    undischarged: tuple[str, ...] = ()
    awaiting: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


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
        asked: set[tuple[str, str, tuple[str, ...]]] = set()
        for index in range(request.max_steps):
            transitions = self._revise(request, notes, asked)
            standing = self.standing(request)
            self._ask(request, standing.awaiting, notes)
            if standing.confirmable is not None:
                steps.append(LoopStep(index=index, transitions=transitions))
                stop = StopReason.CONFIRMED
                break
            if standing.competing:
                steps.append(LoopStep(index=index, transitions=transitions))
                stop = StopReason.COMPETING_SUPPORT
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
        if stop in _EXHAUSTED:
            standing = self.standing(request)
            self._ask(request, standing.awaiting, notes)
            if standing.awaiting:
                stop = StopReason.AWAITING_REVIEW
            elif standing.supported:
                stop = StopReason.SUPPORTED_UNDISCRIMINATED
        return self._conclude(request, stop, tuple(steps), tuple(notes))

    # -- reads for callers ----------

    def planning_inputs(
        self, request: LoopRequest
    ) -> tuple[tuple[HypothesisState, ...], ConditionMatch]:
        """The planner's inputs for `request` as they stand now -- the states and the projected
        ConditionMatch the loop itself plans from. Read-only.

        Public so a caller can ask the planner a SEPARATE question over exactly the state the loop
        acted on -- e.g. which action it would choose if a capability this deployment cannot run
        were available -- without re-deriving the evidence, matches or independence here.
        """
        return self._states(request), self._projected_match(request)

    # -- 1. revise ----------

    def _revise(
        self,
        request: LoopRequest,
        notes: list[str],
        asked: set[tuple[str, str, tuple[str, ...]]],
    ) -> tuple[Transition, ...]:
        d = self._d
        done: list[Transition] = []
        for certificate in sorted(request.certificates, key=lambda c: c.hypothesis_id):
            hypothesis_id = certificate.hypothesis_id
            for _ in range(len(request.targets)):
                state = self._state(request, hypothesis_id)
                if state is None:
                    break
                admitted = d.evidence.admitted_for_subject(request.project_id, hypothesis_id)
                view = d.belief.hypothesis_view(
                    project_id=request.project_id,
                    hypothesis_id=hypothesis_id,
                    current_state=state,
                    stakes=request.hypothesis_set.stakes,
                    admitted_relations=admitted,
                )
                # Evidence on both sides stops the loop choosing -- but only evidence that counts.
                # An unwarranted relation must not veto a warranted move; it goes to a person.
                records = view.relation_evidence
                kinds = (
                    {r.relation_type for r in records if r.warranted}
                    if records
                    else {r.relation_type for r in admitted}
                )
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
                unsettled = tuple(
                    sorted(r.relation_id for r in records if not r.warranted and not r.refused)
                )
                moved = False
                for target in request.targets:
                    policy = target.policy
                    if policy.from_state is not state:
                        continue
                    verdict = policy.evaluate(
                        view, admitted, d.authority_policy, matches, independence, target.to_state
                    )
                    if (
                        verdict.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
                        and verdict.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_MISSING
                        and (hypothesis_id, policy.policy_id, unsettled) not in asked
                    ):
                        # A warrant would decide this move, so a person is asked -- once per run
                        # for the same unsettled relations, again when a new one appears: the
                        # attempt records the decision and queues one review per relation.
                        asked.add((hypothesis_id, policy.policy_id, unsettled))
                        for note in self._unclaimed_signatures(request, certificate, admitted):
                            if note not in notes:
                                notes.append(note)
                        done.append(
                            self._attempt(
                                request,
                                hypothesis_id,
                                target,
                                state,
                                admitted,
                                matches,
                                independence,
                            )
                        )
                        continue
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
        refusal = None if event is not None else result.decision.reason_code.value
        if refusal is not None and result.warrant_review_refusal is not None:
            refusal = f"{refusal}: {result.warrant_review_refusal}"
        return Transition(
            hypothesis_id,
            ref,
            state.value,
            target.to_state.value,
            None if event is None else event.event_id,
            refusal,
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
            bound = (
                None
                if d.declarations is None
                else d.declarations.bound_class(
                    certificate.hypothesis.mechanism, certificate.predictions
                )
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
                    declaration=bound,
                    declaration_ref=(
                        None
                        if bound is None or d.declarations is None
                        else d.declarations.domain_ref(bound)
                    ),
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

    def standing(self, request: LoopRequest) -> Standing:
        """The confirmation rule over the set as it stands now (see `Standing`). Read-only.

        Everything is read off the per-relation records, never off which reviews happened to be
        queued: a project with no review queue, or a refutation that arrived after a promotion,
        must not make a threat invisible. A member's CLASS is its binding to a declared class, so
        a copy of a class is not a rival that can be "excluded" by a refutation of that class.
        """
        d = self._d
        certificates = {c.hypothesis_id: c for c in request.certificates}
        ids = sorted(certificates)
        states = {h: self._state(request, h) for h in ids}
        admitted = {h: d.evidence.admitted_for_subject(request.project_id, h) for h in ids}
        views = {
            h: d.belief.hypothesis_view(
                project_id=request.project_id,
                hypothesis_id=h,
                current_state=states[h] or BeliefState.ACTIVE,
                stakes=request.hypothesis_set.stakes,
                admitted_relations=admitted[h],
            )
            for h in ids
        }

        def with_warrant(h: str, kind: RelationType) -> set[str]:
            return {
                r.relation_id
                for r in views[h].relation_evidence
                if r.relation_type is kind and r.warranted
            }

        def unsettled(h: str, kind: RelationType) -> set[str]:
            return {
                r.relation_id
                for r in views[h].relation_evidence
                if r.relation_type is kind and not r.warranted and not r.refused
            }

        def bound(h: str) -> str:
            declaration = (
                None
                if d.declarations is None
                else d.declarations.bound_class(
                    certificates[h].hypothesis.mechanism, certificates[h].predictions
                )
            )
            return h if declaration is None else f"class:{declaration.class_id}"

        # Excluded: rejected through the governed policy -- fidelity, conditions, independence and
        # all -- on a refutation an accountable source warranted. A coarse result that only
        # challenged a rival has not excluded it (SIM-002), and neither has a rejection resting on
        # an author's own falsifier.
        excluded = {
            h
            for h in ids
            if states[h] is BeliefState.CONTRADICTED and with_warrant(h, RelationType.CONTRADICTS)
        }
        refuted = {h for h in ids if with_warrant(h, RelationType.CONTRADICTS)}
        supported = tuple(h for h in ids if states[h] is BeliefState.SUPPORTED)
        if not supported:
            # Nothing to confirm; what a person could still change is every unsettled relation of
            # a member nothing warranted has refuted.
            open_ = sorted(
                r
                for h in ids
                if h not in excluded
                for kind in (RelationType.SUPPORTS, RelationType.CONTRADICTS)
                for r in unsettled(h, kind)
            )
            return Standing(awaiting=tuple(open_))

        keys = {h: bound(h) for h in ids}
        if len({keys[h] for h in supported}) > 1:
            return Standing(
                supported=supported,
                competing=supported,
                notes=(
                    f"{', '.join(supported)} are SUPPORTED as different mechanisms; the loop "
                    "confirms neither -- they may co-occur",
                ),
            )
        family = {h for h in ids if keys[h] == keys[supported[0]]}
        candidate = supported[0]
        notes: list[str] = []
        if len(family) > 1:
            notes.append(
                f"{', '.join(sorted(family))} state one declared class; {candidate} stands for it"
            )
        undischarged: list[str] = []
        contested = sorted(family & refuted)
        if contested:
            undischarged.append(candidate)
            notes.append(
                f"{', '.join(contested)} -- the candidate's own class -- hold a warranted "
                "refutation; it is not confirmed"
            )
        support = {
            relation_id
            for h in family
            if states[h] is BeliefState.SUPPORTED
            for relation_id in with_warrant(h, RelationType.SUPPORTS)
        }
        observations = {
            r.from_entity_id for h in family for r in admitted[h] if r.relation_id in support
        }
        if not support:
            undischarged.append(candidate)
            notes.append(
                f"{candidate} is SUPPORTED on support nobody accountable has warranted -- a "
                "policy that did not require a warrant moved it; it is not confirmed"
            )
        rivals = [h for h in ids if h not in family]
        # An observed outcome the domain declares to be ANOTHER class's signature is evidence of
        # that mechanism, whoever claimed it and whatever a person said about their claim: the
        # failure may have two causes, or the candidate may be the wrong one. Not confirmed.
        # Unless the candidate's own class accounts for it with a warranted relation: then a
        # person has accountably said the candidate explains that outcome (a paraphrase of the
        # declared class, say), and the note asks them to make the identity explicit.
        accounted = {r for h in family for r in with_warrant(h, RelationType.SUPPORTS)}
        for h in ids:
            for relation in admitted[h]:
                owner = self._signature_owner(certificates[h], relation)
                if owner is None or f"class:{owner.class_id}" == keys[candidate]:
                    continue
                if relation.relation_id in accounted:
                    note = (
                        f"{relation.relation_id}: the observed "
                        f"{relation.attributes.get('outcome')} is the declared signature of "
                        f"'{owner.mechanism}', and a person warranted it for {h} -- say whether "
                        f"{h} is that declared mechanism"
                    )
                    if note not in notes:
                        notes.append(note)
                    continue
                undischarged.append(candidate)
                note = (
                    f"{relation.relation_id}: the observed {relation.attributes.get('outcome')}"
                    f" is the declared signature of '{owner.mechanism}', another mechanism "
                    f"than {candidate}'s -- evidence of a second or a different cause"
                )
                if note not in notes:
                    notes.append(note)
        for rival in rivals:
            if rival in excluded:
                continue
            affirming = sorted(
                r.relation_id
                for r in admitted[rival]
                if r.from_entity_id in observations and r.relation_type in _AFFIRMING
            )
            if affirming:
                undischarged.append(rival)
                notes.append(
                    f"{rival} affirms the observation supporting {candidate} "
                    f"({', '.join(affirming)}) and nothing warranted excludes it, so that "
                    "observation does not tell them apart"
                )
        # What a person's answer could still overturn: support for a rival nothing warranted has
        # excluded, or a refutation of the candidate's class. Read off the records -- queued or
        # not -- so a missing queue or a late refutation cannot hide it.
        threats = sorted(
            {r for h in rivals if h not in excluded for r in unsettled(h, RelationType.SUPPORTS)}
            | {r for h in family for r in unsettled(h, RelationType.CONTRADICTS)}
        )
        if threats:
            notes.append(
                f"a person's answer on {', '.join(threats)} could change whether {candidate} is "
                "the cause"
            )
        # A rival whose warranted support is held only by a blocking conflict's review.
        held = sorted(
            h
            for h in rivals
            if h not in excluded
            and states[h] is not BeliefState.SUPPORTED
            and with_warrant(h, RelationType.SUPPORTS)
            and any(c.blocks_transitions for c in views[h].conflicts)
        )
        if held:
            notes.append(
                f"{', '.join(held)} hold warranted support blocked only by an open conflict review"
            )
        confirmable = None if undischarged or threats or held else candidate
        if confirmable is not None:
            untested = sorted(h for h in rivals if not admitted[h])
            if untested:
                notes.append(
                    "confirmed relative to the rivals proposed; never tested: "
                    f"{', '.join(untested)} -- they are excluded only by not predicting the "
                    "observation"
                )
        return Standing(
            supported=supported,
            confirmable=confirmable,
            undischarged=tuple(dict.fromkeys(undischarged)),
            awaiting=tuple(threats),
            notes=tuple(notes),
        )

    def _signature_owner(
        self, certificate: HypothesisCertificate, relation: RelationJudgment
    ) -> DiagnosticDeclaration | None:
        """The declared class whose signature this relation observed, if any."""
        declarations = self._d.declarations
        if declarations is None:
            return None
        prediction = next(
            (
                p
                for p in certificate.predictions
                if p.prediction_id == relation.attributes.get("prediction_id")
            ),
            None,
        )
        link = None if prediction is None else observed_link(relation, prediction)
        return None if link is None else declarations.signature_of(link)

    def _ask(self, request: LoopRequest, relation_ids: Sequence[str], notes: list[str]) -> None:
        """Queue the warrant reviews the confirmation rule is waiting on, idempotently.

        `_revise` asks through the governed attempt; this covers what no attempt reaches -- a
        refutation that arrived after a promotion (no policy starts from SUPPORTED). If nobody can
        be asked, the note says so and the episode waits rather than concluding.
        """
        reviews = self._d.warrant_reviews
        if reviews is None or not relation_ids:
            return
        for relation_id in relation_ids:
            try:
                reviews.enqueue_warrant_review(
                    # The research service's convention for review ids (`UuidEpisodeIds`).
                    review_id=f"rvw:{self._d.mint('trace').split(':', 1)[1]}",
                    project_id=request.project_id,
                    relation_id=relation_id,
                    stakes=request.hypothesis_set.stakes,
                    reason=TransitionReason.DIAGNOSTIC_WARRANT_MISSING.value,
                    trace_id=request.trace_id,
                    episode_id=request.episode_id,
                    created_at=self._d.now(),
                    estimated_minutes=15,
                )
            except RepositoryError as refused:
                note = f"the diagnostic warrant for {relation_id} cannot be asked for: {refused}"
                if note not in notes:
                    notes.append(note)

    def _unclaimed_signatures(
        self,
        request: LoopRequest,
        certificate: HypothesisCertificate,
        admitted: Sequence[RelationJudgment],
    ) -> tuple[str, ...]:
        """Say so when an outcome a person is asked about is a declared class's signature that no
        rival states.

        In `epi:7b56877f` the observed DISAGREES was the declared signature of a length
        normalization error -- the true cause, which nobody had proposed. The note names it for the
        reviewer and the report; it moves no belief and adds no hypothesis.
        """
        declarations = self._d.declarations
        if declarations is None:
            return ()
        stated = {c.hypothesis.mechanism for c in request.certificates}
        predictions = {p.prediction_id: p for p in certificate.predictions}
        notes: list[str] = []
        for relation in sorted(admitted, key=lambda r: r.relation_id):
            prediction = predictions.get(str(relation.attributes.get("prediction_id")))
            if relation.relation_type is not RelationType.SUPPORTS or prediction is None:
                continue
            link = observed_link(relation, prediction)
            owner = None if link is None else declarations.signature_of(link)
            if owner is None or owner.mechanism in stated:
                continue
            notes.append(
                f"{relation.relation_id}: the observed {link[3] if link else ''} is the declared "
                f"signature of '{owner.mechanism}' ({declarations.domain_ref(owner)}), which no "
                f"hypothesis in this set states -- {certificate.hypothesis_id} claims it for "
                f"'{certificate.hypothesis.mechanism}'"
            )
        return tuple(notes)

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
        """WORK independence over evidence LINES: replicates of one computation count once.

        A line is the execution's capability, backend, input artefacts (content-addressed) and
        parameters -- `core.warrant.evidence_line`. Re-running a deterministic check on the same
        file is not a second piece of evidence, and counting it as one is how a repeated proxy
        observation could stand in for independent support.
        """
        lines: set[str] = set()
        unknown = 0
        for attestation in self._supporting_attestations(project_id, admitted):
            run_id = attestation.run_id
            if run_id is None and attestation.observation_id is not None:
                observation = self._d.evidence.observation(project_id, attestation.observation_id)
                run_id = None if observation is None else observation.run_id
            run = None if run_id is None else self._d.jobs.get_run(run_id)
            line = None if run is None else evidence_line((run,))
            if line is None:
                unknown += 1
            else:
                lines.add(line)
        return IndependenceSummary(
            basis=IndependenceBasis.WORK, independent_count=len(lines), unknown_count=unknown
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
        standing = self.standing(request)
        supported = standing.confirmable
        trace: RootCauseTrace | None = None
        extra: list[str] = list(notes)
        extra.extend(n for n in standing.notes if n not in extra)
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
                    warrant_refs=self._warrant_refs(request, supported, trace),
                    created_at=d.now(),
                )
            except RootCauseRefused as refused:
                extra.append(f"{supported} is SUPPORTED but not confirmable: {refused}")
                stop = StopReason.NO_SUFFICIENT_ACTION
            else:
                extra.extend(self._declared_statements(analysis.warrant_refs, certificate))
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

    def _declared_statements(
        self, refs: Sequence[str], certificate: HypothesisCertificate
    ) -> list[str]:
        """What a DOMAIN-warranted conclusion confirms is the declared class, so say it in the
        class's words -- beside, never in place of, the hypothesis author's own account."""
        declarations = self._d.declarations
        if declarations is None:
            return []
        notes = []
        for ref in refs:
            parsed = parse_domain_ref(ref)
            declaration = None if parsed is None else declarations.by_class(parsed[2])
            if declaration is not None:
                notes.append(
                    f"confirmed as the declared class '{declaration.mechanism}' ({ref}): "
                    f"{declaration.statement} -- {certificate.hypothesis_id}'s own statement is "
                    "its author's account"
                )
        return notes

    def _warrant_refs(
        self, request: LoopRequest, hypothesis_id: str, trace: RootCauseTrace
    ) -> tuple[str, ...]:
        """The warrants behind the trace's relations: what the confirmation rests on."""
        d = self._d
        state = self._state(request, hypothesis_id) or BeliefState.ACTIVE
        admitted = d.evidence.admitted_for_subject(request.project_id, hypothesis_id)
        view = d.belief.hypothesis_view(
            project_id=request.project_id,
            hypothesis_id=hypothesis_id,
            current_state=state,
            stakes=request.hypothesis_set.stakes,
            admitted_relations=admitted,
        )
        traced = {link.relation_id for link in trace.links}
        return tuple(
            sorted(
                {
                    r.warrant_ref
                    for r in view.relation_evidence
                    if r.relation_id in traced and r.warrant_ref is not None
                }
            )
        )

    def _mine(self, project_id: str) -> tuple[CandidateHeuristic, ...]:
        d = self._d
        # Only conclusions that name their warrants generalise. A confirmation recorded before the
        # Causal Warrant Gate stays on record and is not mined: nothing says its support diagnosed
        # its mechanism.
        confirmed = [
            f
            for f in d.failures.analyses(project_id)
            if f.resolution_status is ResolutionStatus.CONFIRMED and f.warrant_refs
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
    "Standing",
    "StopReason",
    "Transition",
    "VerificationLoop",
]
