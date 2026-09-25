"""§7.2's Structured Scientific Debate: stake-adaptive, Critic-inverted, and measured (M3).

    Default 3-stage protocol (stake-adaptive):
      Stage A - Independent positions from selected roles / specialists
      Stage B - Critic performs inverted retrieval + cross-examination
      Stage C - Surviving disagreement becomes explicit predictions + VerificationPlan

    Escalate to deeper rounds only when:
      - decision may REJECT a hypothesis,
      - action is expensive/irreversible,
      - evidence bundles materially conflict, or
      - human requests deeper debate.

    系統 MUST 記錄 position diversity、bundle divergence、Critic 是否改變決策；簡單問題不得固定跑
    8 rounds。

WHERE THE ANTI-GROUPTHINK COMES FROM, AND IT IS NOT THE NUMBER OF ROLES. §7.2 names four sources and
each is a mechanism here, not a label:

    independent initial position   Stage A roles each see only the question, the rivals under
                                   consideration and THEIR OWN bundle -- never another's position
    Critic re-runs inverted        Stage B's retrieval is the Critic's own, over the SourcePolicy's
      retrieval                    *inverted* classes, for evidence against the rivals' falsifiers,
                                   excluding everything the primary retrieval found
    different EvidenceBundle       every position names its bundle, and `005e` checks the model saw
                                   exactly that bundle
    external evidence              a critique cannot move belief; it can only cite evidence, and
      adjudication                 `revision_gate` refuses a transition resting on model opinion

ROUNDS ARE EARNED. A round ends; another begins only if a §7.2 trigger fired AND something changed
that a further round could examine -- a newly contradicted rival (its falsifier leaves the inverted
query), a new alternative mechanism (now certified and admitted), or a human's request. A case with
no trigger stops after one round, which is how a simple question gets one round and a hard one
gets more: the count is a consequence of the evidence, bounded by the declared `max_rounds`, never
aimed at.

THE CRITIC DOES NOT DECIDE. A hypothesis the Critic contradicts WITH CITED EVIDENCE leaves the
debate's surviving set -- that is debate bookkeeping, recorded as such -- and stays ACTIVE in belief
state until evidence moves it through `TransitionPolicy`. Stage C therefore ranks verification over
every active rival, challenged ones included: the challenge is what verification has to settle.
An alternative the Critic names enters the set only after the Hypothesis Engine certifies it and
§8's admission gate admits it.

WHAT THIS MODULE WRITES: bundles (through the researcher), certificates and genesis events (through
the admission service), Positions, CritiqueReports and one DebateRecord (through the debate store),
and -- through `BudgetedInferenceDispatcher` -- one LLM_CALL span and two ledger rows per model
call.
It writes no Attestation and no transition. That is EVI-003 and EPI-005, held by construction.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from lab_brain.cognition.budgeted import (
    BudgetedInference,
    BudgetedInferenceDispatcher,
    InferenceBudgetBlocked,
    InferenceCall,
)
from lab_brain.cognition.debate_metrics import (
    CRITIC_BUNDLE_DIVERGENCE,
    DebateGate,
    Embed,
    bundle_divergence,
    mean_pairwise_distance,
    metric_versions,
)
from lab_brain.cognition.evidence import EvidenceResearcher
from lab_brain.cognition.llm import PromptTemplate
from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    HYPOTHESIS_ENGINE,
    QUERY_REWRITER,
    SPECIALIST_REQUIRES,
    HypothesisProposal,
    parse_critique,
    parse_hypothesis_engine,
    parse_query_terms,
    parse_specialist,
    require_input,
)
from lab_brain.cognition.routing import CognitiveRole, ModelRouter
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.hypothesis_admission import HypothesisAdmissionService, mechanism_key
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.debate import (
    CritiqueReport,
    DebateRecord,
    Position,
    ProposedPrediction,
    ResearchContract,
)
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.hypothesis import Hypothesis
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.inference import InferenceProvenance
from lab_brain.core.models.prediction import OutcomeSpace, Prediction, RelationJudgmentTemplate
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.repositories.debate import DebateStore, independence_axes
from lab_brain.core.repositories.hypotheses import HypothesisStore
from lab_brain.core.specialists import SpecialistRegistry, SpecialistRole
from lab_brain.evidence.dense_index import EmbeddingSpace
from lab_brain.evidence.source_policy import IntentSourcePolicy, SourcePolicyRegistry
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.disagreement import (
    DisagreementMetricRegistry,
    RankedAction,
    rank_by_disagreement,
)
from lab_brain.verification.planner import VerificationPlanner


class StopReason:
    """Why the debate ended. Strings, because they are stored and read by people."""

    NO_ESCALATION_TRIGGER = "NO_ESCALATION_TRIGGER"
    STABLE = "STABLE"
    MAX_ROUNDS = "MAX_ROUNDS"
    CRITIC_DISABLED = "CRITIC_DISABLED"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"


class Trigger:
    """§7.2's four escalation triggers."""

    MAY_REJECT = "MAY_REJECT"
    BUNDLES_MATERIALLY_CONFLICT = "BUNDLES_MATERIALLY_CONFLICT"
    IRREVERSIBLE_ACTION = "IRREVERSIBLE_ACTION"
    HUMAN_REQUEST = "HUMAN_REQUEST"


@dataclass(frozen=True)
class DebatePolicy:
    """The debate's declared, versioned bounds. `max_rounds` is a ceiling, not a target."""

    policy_id: str = "debate:default"
    version: str = "1.0.0"
    max_rounds: int = 4
    #: The Critic's inverted retrieval (§7.2 Stage B). Switching it off is an ablation: the debate
    #: records it, and `revision_gate` later refuses any decision the SourcePolicy required it for.
    perform_inverted_retrieval: bool = True
    #: Stage B at all. Off is the LLM-002 benchmark's baseline / disabled condition.
    critic_enabled: bool = True
    specialists_enabled: bool = True
    minimum_hypotheses: int = 2

    def __post_init__(self) -> None:
        if self.max_rounds < 1 or self.minimum_hypotheses < 1:
            raise ValueError("a debate policy needs at least one round and one hypothesis")


@dataclass(frozen=True)
class DebateRequest:
    project_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    question: str
    intent: str
    stakes: str
    domain: str
    admission_policy: TransitionPolicy
    budget_policy: BudgetPolicy | None
    #: The question's own classification. Every call's context carries it, so it is escalated into
    #: every call's egress decision (SEC-001): the union can only add labels.
    question_label: SensitivityLabel
    root_cause: bool = True
    #: §26.1's "selected Domain Specialists". Empty selects every specialist of the domain.
    specialist_ids: tuple[str, ...] = ()
    human_requested_rounds: int = 0
    #: Inputs available to candidate verification actions (VER-002's `requires` half).
    available_inputs: frozenset[str] = frozenset()

    @classmethod
    def from_contract(
        cls,
        contract: ResearchContract,
        *,
        episode_id: str,
        trace_id: str,
        stakes: str,
        domain: str,
        admission_policy: TransitionPolicy,
        budget_policy: BudgetPolicy | None,
        question_label: SensitivityLabel,
        **options: object,
    ) -> DebateRequest:
        """§7.4's Supervisor/PI output as the debate's input: question, intent, owner, budget.

        In M3 the contract is authored by a person (P12) -- no Supervisor model call is made, and
        the task order, termination and gates are this module's deterministic code, which is the
        strict reading of §7.1's "不能自行宣告物理真理". What the contract fixes, a request cannot
        restate: the question, the research intent that selects the SourcePolicy, who asked, and
        -- when it names one -- the budget the debate is charged to.
        """
        if contract.budget_id is not None and (
            budget_policy is None or budget_policy.policy_id != contract.budget_id
        ):
            raise ValueError(
                f"research contract {contract.contract_id} is charged to budget "
                f"{contract.budget_id}, and the debate was handed "
                f"{None if budget_policy is None else budget_policy.policy_id}; the Supervisor's "
                "budget is part of the contract, not a parameter a caller may swap"
            )
        return cls(
            project_id=contract.project_id,
            episode_id=episode_id,
            trace_id=trace_id,
            actor_id=contract.actor_id,
            question=contract.question,
            intent=contract.intent,
            stakes=stakes,
            domain=domain,
            admission_policy=admission_policy,
            budget_policy=budget_policy,
            question_label=question_label,
            **options,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DebateOutcome:
    record: DebateRecord
    hypothesis_set: HypothesisSet
    certificates: tuple[HypothesisCertificate, ...]
    positions: tuple[Position, ...]
    critiques: tuple[CritiqueReport, ...]
    primary_bundle: EvidenceBundle
    inverted_bundles: tuple[EvidenceBundle, ...]
    ranking: tuple[RankedAction, ...]
    surviving_ids: tuple[str, ...]
    contradicted_ids: tuple[str, ...]
    calls: tuple[BudgetedInference, ...] = field(default_factory=tuple)

    @property
    def competing_before_verification(self) -> int:
        """T-EPI-001: how many ACTIVE rivals the set carries into verification (all admitted ones).

        A critique moves no belief, so every admitted certificate is still ACTIVE here; the ones the
        Critic challenged are exactly the ones verification must now adjudicate (§7.6).
        """
        return len(self.certificates)


class StructuredDebate:
    """One debate over one question. Construct per deployment; call `run` per question."""

    def __init__(
        self,
        *,
        router: ModelRouter,
        dispatcher: BudgetedInferenceDispatcher,
        researcher: EvidenceResearcher,
        source_policies: SourcePolicyRegistry,
        admission: HypothesisAdmissionService,
        hypotheses: HypothesisStore,
        debates: DebateStore,
        specialists: SpecialistRegistry,
        metrics: DisagreementMetricRegistry,
        capabilities: CapabilityRegistry,
        gate: DebateGate,
        embed: Embed,
        embedding_space: EmbeddingSpace,
        policy: DebatePolicy,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._router = router
        self._dispatcher = dispatcher
        self._researcher = researcher
        self._source_policies = source_policies
        self._admission = admission
        self._hypotheses = hypotheses
        self._debates = debates
        self._specialists = specialists
        self._metrics = metrics
        self._capabilities = capabilities
        self._gate = gate
        self._embed = embed
        self._embedding_space = embedding_space
        self._policy = policy
        self._mint = mint
        self._now = now

    # -- the protocol ---------------------------------------------------------------------------

    def run(self, request: DebateRequest) -> DebateOutcome:
        state = _RunState(request=request, debate_id=self._mint("debate"))
        source_policy = self._source_policies.for_intent(request.intent)
        spaces = {
            (s.outcome_space_id, s.version): s
            for s in self._metrics.declared_spaces()
            if s.domain == request.domain
        }

        # Evidence: the FAST_UTILITY query rewrite over a seed bundle, then the primary retrieval.
        seed = self._researcher.seed(
            question=request.question,
            policy=source_policy,
            stakes=request.stakes,
            project_id=request.project_id,
            trace_id=request.trace_id,
        )
        rewrite = self._call(
            state,
            role=CognitiveRole.EVIDENCE_RESEARCHER,
            prompt=QUERY_REWRITER.prompt,
            requires=QUERY_REWRITER.requires,
            bundle=seed,
            context={"question": request.question, "mode": "PRIMARY"},
        )
        terms = parse_query_terms(
            rewrite.inference.text, inference_id=rewrite.inference.inference_id
        )
        primary = self._researcher.retrieve(
            query_text=" ".join((request.question, *terms)),
            policy=source_policy,
            stakes=request.stakes,
            project_id=request.project_id,
            trace_id=request.trace_id,
        )

        # Stage A: the Hypothesis Engine's competing certificates, admitted as one set.
        engine = self._engine(
            state,
            primary,
            spaces,
            alternatives=(),
            existing=(),
            minimum=self._policy.minimum_hypotheses,
        )
        proposals = engine[1]
        hypothesis_set = HypothesisSet(
            set_id=self._mint("hypothesis_set"),
            project_id=request.project_id,
            episode_id=request.episode_id,
            question=request.question,
            research_intent=request.intent,
            stakes=request.stakes,
            root_cause=request.root_cause,
            source_policy_id=source_policy.policy_id,
            source_policy_version=source_policy.version,
            inverted_retrieval_required=source_policy.requires_inverted_retrieval(request.stakes),
            created_at=self._now(),
        )
        certificates = [
            self._certificate(p, hypothesis_set, engine[0].inference.inference_id)
            for p in proposals
        ]
        admitted = self._admission.admit_set(
            hypothesis_set,
            certificates,
            basis=primary.ordered_attestation_ids,
            policy=request.admission_policy,
            event_ids=[self._mint("belief_revision_event") for _ in certificates],
            occurred_at=self._now(),
            trace_id=request.trace_id,
            actor_id=request.actor_id,
        )
        initial_ids = admitted.hypothesis_ids
        positions: list[Position] = [
            self._position(
                request,
                CognitiveRole.HYPOTHESIS_ENGINE.value,
                engine[2],
                initial_ids,
                primary,
                engine[0],
            )
        ]
        stage_a_positions = list(positions)
        specialist_bundles: list[EvidenceBundle] = []
        if self._policy.specialists_enabled:
            for role in self._selected_specialists(request):
                position, bundle = self._specialist(
                    state, role, source_policy, admitted.certificates
                )
                positions.append(position)
                stage_a_positions.append(position)
                specialist_bundles.append(bundle)

        # Stage B, round by round.
        original: InferenceProvenance = engine[0].inference.provenance
        contradicted: set[str] = set()
        critiques: list[CritiqueReport] = []
        inverted_bundles: list[EvidenceBundle] = []
        per_round: list[dict[str, object]] = []
        gate_verdicts: list[dict[str, object]] = []
        triggers_seen: list[str] = []
        stage_b_calls_start = len(state.calls)
        rounds = 1
        stop_reason = StopReason.CRITIC_DISABLED if not self._policy.critic_enabled else ""
        ranking: tuple[RankedAction, ...] = ()
        while self._policy.critic_enabled:
            try:
                in_contention = [
                    c
                    for c in self._hypotheses.certificates_in_set(hypothesis_set.set_id)
                    if c.hypothesis_id not in contradicted
                ]
                inverted: EvidenceBundle | None = None
                if self._policy.perform_inverted_retrieval:
                    inverted = self._inverted_retrieval(
                        state, source_policy, primary, in_contention
                    )
                    inverted_bundles.append(inverted)
                cross = self._cross_examination_bundle(
                    request, source_policy, primary, inverted, specialist_bundles
                )
                critique, draft_alternatives = self._cross_examine(
                    state, cross, primary, inverted, in_contention, positions, original
                )
            except _Blocked:
                stop_reason = StopReason.BUDGET_BLOCKED
                break
            critiques.append(critique)
            divergence = (
                bundle_divergence(primary.ordered_attestation_ids, inverted.ordered_attestation_ids)
                if inverted is not None
                else None
            )
            verdict = self._gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, divergence)
            gate_verdicts.append({"round": rounds, **verdict.as_record()})

            newly_contradicted = sorted(critique.contradicted_targets - contradicted)
            contradicted.update(newly_contradicted)
            existing = {
                mechanism_key(c)
                for c in self._hypotheses.certificates_in_set(hypothesis_set.set_id)
            }
            new_alternatives = [
                m for m in draft_alternatives if " ".join(m.lower().split()) not in existing
            ]
            ranking = self._rank(hypothesis_set, request)
            triggers: list[str] = []
            if newly_contradicted:
                triggers.append(Trigger.MAY_REJECT)
            if new_alternatives:
                triggers.append(Trigger.BUNDLES_MATERIALLY_CONFLICT)
            if ranking and self._irreversible(ranking[0].capability_id):
                triggers.append(Trigger.IRREVERSIBLE_ACTION)
            if rounds < request.human_requested_rounds:
                triggers.append(Trigger.HUMAN_REQUEST)
            triggers_seen.extend(t for t in triggers if t not in triggers_seen)

            admitted_now: list[str] = []
            round_entry: dict[str, object] = {
                "round": rounds,
                "critique_id": critique.critique_id,
                "inverted_bundle_id": None if inverted is None else inverted.bundle_id,
                "critic_bundle_divergence": None if divergence is None else str(divergence),
                "triggers": list(triggers),
                "contradicted": newly_contradicted,
                "alternatives": list(new_alternatives),
                "admitted": admitted_now,
            }
            per_round.append(round_entry)
            if not triggers:
                stop_reason = StopReason.NO_ESCALATION_TRIGGER
                break
            if rounds >= self._policy.max_rounds:
                stop_reason = StopReason.MAX_ROUNDS
                break
            if new_alternatives:
                try:
                    later = self._engine(
                        state,
                        primary if inverted is None else cross,
                        spaces,
                        alternatives=tuple(new_alternatives),
                        existing=tuple(sorted(existing)),
                        minimum=1,
                    )
                except _Blocked:
                    stop_reason = StopReason.BUDGET_BLOCKED
                    break
                shown = primary if inverted is None else cross
                for proposal in later[1]:
                    if " ".join(proposal.mechanism.lower().split()) in existing:
                        continue
                    certificate = self._certificate(
                        proposal, hypothesis_set, later[0].inference.inference_id
                    )
                    self._admission.admit_alternative(
                        hypothesis_set,
                        certificate,
                        basis=shown.ordered_attestation_ids,
                        policy=request.admission_policy,
                        event_id=self._mint("belief_revision_event"),
                        occurred_at=self._now(),
                        trace_id=request.trace_id,
                        actor_id=request.actor_id,
                    )
                    existing.add(mechanism_key(certificate))
                    admitted_now.append(certificate.hypothesis_id)
                if admitted_now:
                    positions.append(
                        self._position(
                            request,
                            CognitiveRole.HYPOTHESIS_ENGINE.value,
                            later[2],
                            tuple(admitted_now),
                            primary if inverted is None else cross,
                            later[0],
                        )
                    )
                    original = later[0].inference.provenance
            changed = bool(newly_contradicted) or bool(admitted_now)
            if not changed and Trigger.HUMAN_REQUEST not in triggers:
                stop_reason = StopReason.STABLE
                break
            rounds += 1

        # Stage C: surviving disagreement, ranked by the domain's declared metric (VER-008).
        final = self._hypotheses.certificates_in_set(hypothesis_set.set_id)
        surviving = tuple(c.hypothesis_id for c in final if c.hypothesis_id not in contradicted)
        ranking = self._rank(hypothesis_set, request)
        additional = frozenset(
            a for b in inverted_bundles for a in b.ordered_attestation_ids
        ) - frozenset(primary.ordered_attestation_ids)
        extra_tokens = sum(c.actual.token_count for c in state.calls[stage_b_calls_start:])
        # The DEBATE's divergence: everything the Critic's inverted retrievals added, across rounds.
        # Per-round values are in `per_round`; this is the one a calibrated gate reads.
        debate_divergence = (
            bundle_divergence(
                primary.ordered_attestation_ids,
                [a for b in inverted_bundles for a in b.ordered_attestation_ids],
            )
            if inverted_bundles
            else None
        )
        final_verdict = self._gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, debate_divergence)
        gate_verdicts.append({"round": "debate", **final_verdict.as_record()})
        record = DebateRecord(
            debate_id=state.debate_id,
            project_id=request.project_id,
            episode_id=request.episode_id,
            set_id=hypothesis_set.set_id,
            rounds=rounds,
            max_rounds=self._policy.max_rounds,
            stop_reason=stop_reason,
            escalation_triggers=tuple(triggers_seen),
            position_ids=tuple(p.position_id for p in positions),
            critique_ids=tuple(c.critique_id for c in critiques),
            position_diversity=mean_pairwise_distance(
                [p.mechanism_view for p in stage_a_positions], self._embed
            ),
            critic_bundle_divergence=debate_divergence,
            critic_changed_final_set=set(surviving) != set(initial_ids),
            initial_hypothesis_ids=tuple(initial_ids),
            surviving_hypothesis_ids=surviving,
            surviving_hypothesis_diversity=mean_pairwise_distance(
                [c.hypothesis.mechanism for c in final if c.hypothesis_id in surviving],
                self._embed,
            ),
            additional_evidence_items=len(additional),
            additional_token_count=extra_tokens,
            metric_versions=metric_versions(self._embedding_space),
            gate_evaluations=tuple(gate_verdicts),
            per_round=tuple(per_round),
            created_at=self._now(),
        )
        stored = self._debates.add_debate_record(record)
        return DebateOutcome(
            record=stored,
            hypothesis_set=hypothesis_set,
            certificates=final,
            positions=tuple(positions),
            critiques=tuple(critiques),
            primary_bundle=primary,
            inverted_bundles=tuple(inverted_bundles),
            ranking=ranking,
            surviving_ids=surviving,
            contradicted_ids=tuple(sorted(contradicted)),
            calls=tuple(state.calls),
        )

    # -- roles ----------------------------------------------------------------------------------

    def _engine(
        self,
        state: _RunState,
        bundle: EvidenceBundle,
        spaces: Mapping[tuple[str, str], OutcomeSpace],
        *,
        alternatives: Sequence[str],
        existing: Sequence[str],
        minimum: int,
    ) -> tuple[BudgetedInference, tuple[HypothesisProposal, ...], _Draft]:
        context = {
            "question": state.request.question,
            "evidence": self._researcher.evidence_context(bundle),
            "outcome_spaces": [
                {
                    "outcome_space_id": s.outcome_space_id,
                    "outcome_space_version": s.version,
                    "outcomes": list(s.outcomes),
                    "action_type": s.action_type,
                }
                for _, s in sorted(spaces.items())
            ],
            "minimum_hypotheses": minimum,
            "alternatives_to_certify": list(alternatives),
            "existing_mechanisms": list(existing),
        }
        call = self._call(
            state,
            role=CognitiveRole.HYPOTHESIS_ENGINE,
            prompt=HYPOTHESIS_ENGINE.prompt,
            requires=HYPOTHESIS_ENGINE.requires,
            bundle=bundle,
            context=context,
        )
        proposals, draft = parse_hypothesis_engine(
            call.inference.text,
            spaces=spaces,
            minimum=minimum,
            inference_id=call.inference.inference_id,
        )
        return (
            call,
            proposals,
            _Draft(draft.mechanism_view, draft.uncertainties, draft.confounders, ()),
        )

    def _specialist(
        self,
        state: _RunState,
        role: SpecialistRole,
        source_policy: IntentSourcePolicy,
        certificates: Sequence[HypothesisCertificate],
    ) -> tuple[Position, EvidenceBundle]:
        request = state.request
        bundle = self._researcher.retrieve(
            query_text=" ".join((request.question, *role.focus_terms)),
            policy=source_policy,
            stakes=request.stakes,
            project_id=request.project_id,
            trace_id=request.trace_id,
            domains=role.evidence_domains,
        )
        ids = [c.hypothesis_id for c in certificates]
        context = {
            "question": request.question,
            "specialist": role.role_id,
            "hypotheses": [
                {
                    "hypothesis_id": c.hypothesis_id,
                    "statement": c.hypothesis.statement,
                    "mechanism": c.hypothesis.mechanism,
                }
                for c in certificates
            ],
            "evidence": self._researcher.evidence_context(bundle),
        }
        call = self._call(
            state,
            role=CognitiveRole.DOMAIN_SPECIALIST,
            prompt=PromptTemplate(role.prompt_id, role.prompt_version, role.prompt_template),
            requires=SPECIALIST_REQUIRES,
            bundle=bundle,
            context=context,
            role_label=role.role_id,
        )
        draft = parse_specialist(
            call.inference.text,
            role_id=role.role_id,
            hypothesis_ids=ids,
            inference_id=call.inference.inference_id,
        )
        position = self._position(
            request,
            role.role_id,
            _Draft(
                draft.mechanism_view,
                draft.uncertainties,
                draft.confounders,
                draft.proposed_predictions,
            ),
            draft.favoured,
            bundle,
            call,
        )
        return position, bundle

    def _inverted_retrieval(
        self,
        state: _RunState,
        source_policy: IntentSourcePolicy,
        primary: EvidenceBundle,
        in_contention: Sequence[HypothesisCertificate],
    ) -> EvidenceBundle:
        request = state.request
        falsifiers = [c.hypothesis.falsifier for c in in_contention]
        rewrite = self._call(
            state,
            role=CognitiveRole.EVIDENCE_RESEARCHER,
            prompt=QUERY_REWRITER.prompt,
            requires=QUERY_REWRITER.requires,
            bundle=primary,
            context={"question": request.question, "mode": "INVERTED", "falsifiers": falsifiers},
        )
        terms = parse_query_terms(
            rewrite.inference.text, inference_id=rewrite.inference.inference_id
        )
        return self._researcher.retrieve(
            query_text=" ".join((*falsifiers, *terms)),
            policy=source_policy,
            stakes=request.stakes,
            project_id=request.project_id,
            trace_id=request.trace_id,
            inverted=True,
            exclude=primary.ordered_attestation_ids,
        )

    def _cross_examine(
        self,
        state: _RunState,
        cross: EvidenceBundle,
        primary: EvidenceBundle,
        inverted: EvidenceBundle | None,
        in_contention: Sequence[HypothesisCertificate],
        positions: Sequence[Position],
        original: InferenceProvenance,
    ) -> tuple[CritiqueReport, tuple[str, ...]]:
        request = state.request
        targets = [c.hypothesis_id for c in in_contention]
        context = {
            "question": request.question,
            "hypotheses": [
                {
                    "hypothesis_id": c.hypothesis_id,
                    "statement": c.hypothesis.statement,
                    "mechanism": c.hypothesis.mechanism,
                    "falsifier": c.hypothesis.falsifier,
                    "assumptions": list(c.hypothesis.assumptions),
                }
                for c in in_contention
            ],
            "positions": [
                {
                    "role_id": p.role_id,
                    "mechanism_view": p.mechanism_view,
                    "hypothesis_refs": list(p.hypothesis_refs),
                }
                for p in positions
            ],
            "evidence": self._researcher.evidence_context(cross),
            "inverted_attestation_ids": []
            if inverted is None
            else list(inverted.ordered_attestation_ids),
        }
        call = self._call(
            state,
            role=CognitiveRole.ADVERSARIAL_CRITIC,
            prompt=ADVERSARIAL_CRITIC.prompt,
            requires=ADVERSARIAL_CRITIC.requires,
            bundle=cross,
            context=context,
            critique_of=original,
        )
        draft = parse_critique(
            call.inference.text,
            targets=targets,
            shown_attestation_ids=cross.ordered_attestation_ids,
            inference_id=call.inference.inference_id,
        )
        critique = CritiqueReport(
            critique_id=self._mint("critique"),
            project_id=request.project_id,
            episode_id=request.episode_id,
            target_ids=tuple(targets),
            objections=draft.objections,
            alternative_mechanisms=draft.alternative_mechanisms,
            falsifier_challenges=draft.falsifier_challenges,
            primary_bundle_id=primary.bundle_id,
            inverted_bundle_id=None if inverted is None else inverted.bundle_id,
            original_inference_id=original.inference_id,
            differs_in=independence_axes(original, call.inference.provenance),
            inference_provenance_id=call.inference.inference_id,
            created_at=self._now(),
        )
        return self._debates.add_critique(critique), draft.alternative_mechanisms

    # -- helpers --------------------------------------------------------------------------------

    def _cross_examination_bundle(
        self,
        request: DebateRequest,
        source_policy: IntentSourcePolicy,
        primary: EvidenceBundle,
        inverted: EvidenceBundle | None,
        specialist_bundles: Sequence[EvidenceBundle],
    ) -> EvidenceBundle:
        """Everything the Critic is shown: its inverted retrieval, then what the positions saw.

        WHEN THAT IS EXACTLY THE PRIMARY EVIDENCE, THE PRIMARY BUNDLE ITSELF IS USED. A bundle's
        identity covers its query text, so re-storing the same evidence under a "cross-examination"
        query would give the critique a different bundle hash -- and §7.6's RETRIEVAL_BUNDLE axis
        would be satisfied by a change of wording. Reusing the primary bundle makes the critique
        rely on what actually differs (its model route) or be refused as not independent.
        """
        combined_ids: list[str] = []
        for bundle in (inverted, primary, *specialist_bundles):
            if bundle is None:
                continue
            for attestation_id in bundle.ordered_attestation_ids:
                if attestation_id not in combined_ids:
                    combined_ids.append(attestation_id)
        if tuple(combined_ids) == primary.ordered_attestation_ids:
            return primary
        return self._researcher.combined(
            [b for b in (inverted, primary, *specialist_bundles) if b is not None],
            query_text=f"cross-examination: {request.question}",
            policy=source_policy,
            stakes=request.stakes,
            project_id=request.project_id,
            trace_id=request.trace_id,
        )

    def _call(
        self,
        state: _RunState,
        *,
        role: CognitiveRole,
        prompt: PromptTemplate,
        requires: frozenset[str],
        bundle: EvidenceBundle,
        context: Mapping[str, object],
        critique_of: InferenceProvenance | None = None,
        role_label: str | None = None,
    ) -> BudgetedInference:
        label = role_label or role.value
        require_input(label, requires, context)
        request = state.request
        number = len(state.calls) + 1
        call = InferenceCall(
            slot=self._router.route(role),
            role=label,
            prompt_id=prompt.prompt_id,
            prompt_text=prompt.template,
            bundle=bundle,
            context=context,
            project_id=request.project_id,
            episode_id=request.episode_id,
            trace_id=request.trace_id,
            actor_id=request.actor_id,
            action_ref=f"{state.debate_id}:{number:03d}:{label}",
            span_id=self._mint("execution_span"),
            estimate_entry_id=f"cst:{state.debate_id}:{number:03d}:est",
            actual_entry_id=f"cst:{state.debate_id}:{number:03d}:act",
            inference_id=self._mint("inference"),
            escalate=frozenset({request.question_label}),
            critique_of=critique_of,
        )
        try:
            result = self._dispatcher.infer(
                call, policy=request.budget_policy, consumed=state.consumed
            )
        except InferenceBudgetBlocked as blocked:
            if state.calls:
                raise _Blocked() from blocked
            raise
        state.consumed = state.consumed.plus(result.actual)
        state.calls.append(result)
        return result

    def _certificate(
        self, proposal: HypothesisProposal, hypothesis_set: HypothesisSet, inference_id: str
    ) -> HypothesisCertificate:
        hypothesis_id = self._mint("hypothesis")
        predictions = tuple(
            Prediction(
                prediction_id=self._mint("prediction"),
                hypothesis_id=hypothesis_id,
                project_id=hypothesis_set.project_id,
                observable_ref=p.observable_ref,
                outcome_space_id=p.outcome_space_id,
                outcome_space_version=p.outcome_space_version,
                expected_outcome=p.expected_outcome,
                direction=p.direction,
                relation_effect_if_observed=(
                    RelationJudgmentTemplate(
                        relation_type=p.relation_effect, to_entity_id=hypothesis_id
                    ),
                ),
                inference_provenance_id=inference_id,
            )
            for p in proposal.predictions
        )
        return HypothesisCertificate(
            hypothesis=Hypothesis(
                hypothesis_id=hypothesis_id,
                project_id=hypothesis_set.project_id,
                statement=proposal.statement,
                mechanism=proposal.mechanism,
                assumptions=proposal.assumptions,
                prediction_ids=tuple(p.prediction_id for p in predictions),
                falsifier=proposal.falsifier,
                confounders=proposal.confounders,
                minimal_test_ref=proposal.minimal_test_ref,
                created_in_episode=hypothesis_set.episode_id,
                inference_provenance_id=inference_id,
            ),
            hypothesis_set_id=hypothesis_set.set_id,
            predictions=predictions,
            created_at=self._now(),
        )

    def _position(
        self,
        request: DebateRequest,
        role_id: str,
        draft: _Draft,
        hypothesis_refs: Sequence[str],
        bundle: EvidenceBundle,
        call: BudgetedInference,
    ) -> Position:
        position = Position(
            position_id=self._mint("position"),
            project_id=request.project_id,
            role_id=role_id,
            episode_id=request.episode_id,
            hypothesis_refs=tuple(hypothesis_refs),
            mechanism_view=draft.mechanism_view,
            uncertainties=draft.uncertainties,
            proposed_predictions=draft.proposed_predictions,
            confounders=draft.confounders,
            bundle_id=bundle.bundle_id,
            inference_provenance_id=call.inference.inference_id,
            created_at=self._now(),
        )
        return self._debates.add_position(position)

    def _selected_specialists(self, request: DebateRequest) -> tuple[SpecialistRole, ...]:
        roles = self._specialists.for_domain(request.domain)
        if not request.specialist_ids:
            return roles
        known = {r.role_id: r for r in roles}
        unknown = sorted(set(request.specialist_ids) - set(known))
        if unknown:
            raise ValueError(
                f"specialists {unknown} are not registered for domain {request.domain}; §7.1's "
                "specialists are DomainPack-registered, and an unregistered one has no declared "
                "evidence scope"
            )
        return tuple(known[i] for i in request.specialist_ids)

    def _rank(
        self, hypothesis_set: HypothesisSet, request: DebateRequest
    ) -> tuple[RankedAction, ...]:
        """Stage C over EVERY active rival, the challenged ones included.

        A contradiction the Critic cites is still a model's reading of evidence, and §7.6 requires
        it to be adjudicated by external evidence or a verification result -- so the actions that
        would adjudicate it are ranked with the rest rather than dropped with the rival.
        """
        active = self._hypotheses.certificates_in_set(hypothesis_set.set_id)
        predictions = [p for c in active for p in c.predictions]
        observables = sorted({p.observable_ref for p in predictions})
        if not observables:
            return ()
        planned = VerificationPlanner(self._capabilities).plan(
            goal=observables, available=request.available_inputs
        )
        return rank_by_disagreement(
            [(a.capability_id, a.capability.produces) for a in planned], predictions, self._metrics
        )

    def _irreversible(self, capability_id: str) -> bool:
        return self._capabilities.resolve(capability_id).irreversible


@dataclass(frozen=True)
class _Draft:
    mechanism_view: str
    uncertainties: tuple[str, ...]
    confounders: tuple[str, ...]
    proposed_predictions: tuple[ProposedPrediction, ...]


class _Blocked(Exception):
    """A later call was refused by the budget gate; the debate stops and records why."""


@dataclass
class _RunState:
    request: DebateRequest
    debate_id: str
    calls: list[BudgetedInference] = field(default_factory=list)
    consumed: CostVector = field(default_factory=CostVector)


__all__ = [
    "DebateOutcome",
    "DebatePolicy",
    "DebateRequest",
    "StopReason",
    "StructuredDebate",
    "Trigger",
]
