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
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from lab_brain.cognition.aliases import AliasTable, aliased
from lab_brain.cognition.budgeted import (
    BudgetedInference,
    BudgetedInferenceDispatcher,
    InferenceBudgetBlocked,
    InferenceCall,
    token_count,
)
from lab_brain.cognition.coverage import CoverageGap, discriminated, unaddressed_checks
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
from lab_brain.cognition.overlap import overlapping_pairs
from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    COVERAGE_REVIEW,
    HYPOTHESIS_ENGINE,
    QUERY_REWRITER,
    SCREENING_REVIEW,
    SPECIALIST_REQUIRES,
    CoverageDraft,
    HypothesisProposal,
    RoleOutputRefused,
    binding_context,
    normalize_reply,
    parse_coverage_review,
    parse_critique,
    parse_hypothesis_engine,
    parse_query_terms,
    parse_screening_review,
    parse_specialist,
    require_input,
)
from lab_brain.cognition.routing import CognitiveRole, ModelRouter
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.hypothesis_admission import (
    HypothesisAdmissionRefused,
    HypothesisAdmissionService,
    mechanism_key,
)
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
from lab_brain.core.models.hypothesis_set import (
    HypothesisCertificate,
    HypothesisSet,
    typed_falsifier_text,
)
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
from lab_brain.verification.screening import ScreeningOutcome


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
    #: Replies asked per role call. 1: a refused reply ends the call, as M3 did. 2: a refused
    #: reply is asked for once more, with the parser's reason -- a new, separately recorded
    #: inference that must pass the same parser. Never more than 3: a model that cannot meet a
    #: contract in three tries is not one research should keep paying.
    max_attempts: int = 1
    #: After Stage A, ask the Hypothesis Engine once about the low-cost executable checks no
    #: hypothesis discriminates on (`cognition.coverage`, `roles.COVERAGE_REVIEW`).
    coverage_review: bool = False
    #: After the coverage review, run an exploratory screening stage over the low-cost checks no
    #: hypothesis predicts (`verification.screening`), and -- if a reading is ABNORMAL -- ask the
    #: Hypothesis Engine once for rivals that account for it (`roles.SCREENING_REVIEW`).
    screening: bool = False
    #: Tokens held back for the Adversarial Critic. Before Stage B, an OPTIONAL call (the coverage
    #: review, the screening review) or a RETRY of a refused reply is not made when it would leave
    #: less than this under the budget's token cap: whatever else happens, the critique is
    #: affordable. 0: nothing is reserved (the earlier behaviour).
    critic_reserve_tokens: int = 0

    def __post_init__(self) -> None:
        if self.max_rounds < 1 or self.minimum_hypotheses < 1:
            raise ValueError("a debate policy needs at least one round and one hypothesis")
        if self.critic_reserve_tokens < 0:
            raise ValueError("a debate policy cannot reserve a negative number of tokens")
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("a debate policy asks for a reply between one and three times")

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"


class ScreeningHook(Protocol):
    """What the debate needs from a screening stage. The research service supplies it: it owns the
    verification input, the Jobs and the stores; the debate decides only when to ask."""

    def screen(
        self,
        *,
        hypothesis_set_id: str,
        certificates: Sequence[HypothesisCertificate],
        bindings: Mapping[str, OutcomeSpace],
    ) -> ScreeningOutcome: ...

    def condition(
        self,
        *,
        hypothesis_id: str,
        plan_id: str,
        screening_observation_ids: Sequence[str],
        inference_id: str,
    ) -> object: ...

    def atomic(self) -> AbstractContextManager[object]:
        """Admission and its conditioning record commit together, or neither does."""
        ...


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
    #: Where a screening stage runs, when the policy asks for one; `None` means none can run.
    screening: ScreeningHook | None = None
    #: The device structure summary every Hypothesis Engine call is shown, when the deployment
    #: enables it (`research.structure`): design-declared fields with units and source locators,
    #: never an inspected or measured outcome, never citable as evidence.
    structure: Mapping[str, object] | None = None

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
        # The domain's prediction vocabulary: what the engine is shown and its parser admits.
        bindings = self._metrics.observable_bindings(request.domain)
        if not bindings:
            raise ValueError(
                f"domain {request.domain} declares no prediction vocabulary (observable -> "
                "OutcomeSpace); the Hypothesis Engine would have nothing to bind a prediction to"
            )

        # Evidence: the FAST_UTILITY query rewrite over a seed bundle, then the primary retrieval.
        seed = self._researcher.seed(
            question=request.question,
            policy=source_policy,
            stakes=request.stakes,
            project_id=request.project_id,
            trace_id=request.trace_id,
        )
        _, terms = self._ask(
            state,
            role=CognitiveRole.EVIDENCE_RESEARCHER,
            prompt=QUERY_REWRITER.prompt,
            requires=QUERY_REWRITER.requires,
            bundle=seed,
            context={"question": request.question, "mode": "PRIMARY"},
            parse=lambda text, iid: parse_query_terms(text, inference_id=iid),
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
            bindings,
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
        for certificate in admitted.certificates:
            state.hypotheses.add(certificate.hypothesis_id)
        positions: list[Position] = [
            self._position(
                request,
                CognitiveRole.HYPOTHESIS_ENGINE.value,
                engine[2],
                admitted.hypothesis_ids,
                primary,
                engine[0],
            )
        ]
        # Still Stage A: what the review certifies is a rival every later role sees, and is
        # counted among the initial set -- the Critic did not add it.
        covered = (
            self._coverage_review(state, primary, bindings, hypothesis_set)
            if self._policy.coverage_review
            else ()
        )
        screened = (
            self._screening(state, primary, bindings, hypothesis_set)
            if self._policy.screening and request.screening is not None
            else ()
        )
        initial_ids = (*admitted.hypothesis_ids, *covered, *screened)
        stage_a_positions = list(positions)
        specialist_bundles: list[EvidenceBundle] = []
        if self._policy.specialists_enabled:
            stage_a = self._hypotheses.certificates_in_set(hypothesis_set.set_id)
            for role in self._selected_specialists(request):
                position, bundle = self._specialist(state, role, source_policy, stage_a)
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
        state.critic_started = True
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
                        bindings,
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
                    state.hypotheses.add(certificate.hypothesis_id)
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
            reliability={
                "debate_policy": self._policy.ref,
                "max_attempts": self._policy.max_attempts,
                "reply_attempts": list(state.attempts),
                "coverage_review": state.coverage,
                "screening": state.screening,
                "critic_reserve_tokens": self._policy.critic_reserve_tokens,
                "withheld_for_critic": list(state.withheld),
                "structure_summary": (
                    None if request.structure is None else request.structure.get("digest")
                ),
                "overlap": overlapping_pairs(final),
            },
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
        bindings: Mapping[str, OutcomeSpace],
        *,
        alternatives: Sequence[str],
        existing: Sequence[str],
        minimum: int,
    ) -> tuple[BudgetedInference, tuple[HypothesisProposal, ...], _Draft]:
        context = {
            "question": state.request.question,
            "evidence": self._researcher.evidence_context(bundle),
            "prediction_bindings": binding_context(bindings),
            "minimum_hypotheses": minimum,
            "alternatives_to_certify": list(alternatives),
            "existing_mechanisms": list(existing),
            **self._structure(state),
        }
        call, (proposals, draft) = self._ask(
            state,
            role=CognitiveRole.HYPOTHESIS_ENGINE,
            prompt=HYPOTHESIS_ENGINE.prompt,
            requires=HYPOTHESIS_ENGINE.requires,
            bundle=bundle,
            context=context,
            parse=lambda text, iid: parse_hypothesis_engine(
                text, bindings=bindings, minimum=minimum, inference_id=iid
            ),
        )
        return (
            call,
            proposals,
            _Draft(draft.mechanism_view, draft.uncertainties, draft.confounders, ()),
        )

    def _coverage_review(
        self,
        state: _RunState,
        primary: EvidenceBundle,
        bindings: Mapping[str, OutcomeSpace],
        hypothesis_set: HypothesisSet,
    ) -> tuple[str, ...]:
        """Stage A's coverage review: the cheap executable checks no hypothesis discriminates on,
        put once to the Hypothesis Engine. Returns the ids of the rivals it certified and §8
        admitted; records everything in `state.coverage`.

        A review that cannot be completed -- refused after its attempts, or stopped by the budget
        -- costs the debate nothing it already had: the Stage A set stands, and the record says the
        checks stayed unaddressed and why. A rival the admission gate refuses is recorded as
        refused, never admitted another way.
        """
        request = state.request
        certificates = self._hypotheses.certificates_in_set(hypothesis_set.set_id)
        gaps = unaddressed_checks(
            certificates, bindings, self._capabilities, request.available_inputs
        )
        state.coverage = {
            "status": "NOT_NEEDED",
            "prompt": f"{COVERAGE_REVIEW.prompt.prompt_id}@{COVERAGE_REVIEW.prompt.prompt_version}",
            "gaps": [_gap_record(g) for g in gaps],
            "certified": [],
            "declined": [],
            "refused": [],
        }
        if not gaps:
            return ()
        unaddressed = [g.observable_ref for g in gaps]
        existing = sorted(c.hypothesis.mechanism for c in certificates)
        shown_evidence = self._researcher.evidence_context(primary)
        context, shown_h, shown_e = coverage_context(
            question=request.question,
            hypotheses=[
                {
                    "hypothesis_id": c.hypothesis_id,
                    "statement": c.hypothesis.statement,
                    "mechanism": c.hypothesis.mechanism,
                    "discriminates_on": sorted(discriminated((c,))),
                }
                for c in certificates
            ],
            evidence=shown_evidence,
            bindings=bindings,
            unaddressed_checks=[g.as_context(bindings[g.observable_ref]) for g in gaps],
            hypothesis_aliases=state.hypotheses,
            evidence_aliases=state.evidence,
        )
        context.update(self._structure(state))
        if self._withheld(state, COVERAGE_REVIEW.prompt, context, "coverage review"):
            state.coverage.update(status="RESERVED_FOR_CRITIC")
            return ()
        try:
            call, draft = self._ask(
                state,
                role=CognitiveRole.HYPOTHESIS_ENGINE,
                prompt=COVERAGE_REVIEW.prompt,
                requires=COVERAGE_REVIEW.requires,
                bundle=primary,
                context=context,
                parse=lambda text, iid: parse_coverage_review(
                    text,
                    bindings=bindings,
                    unaddressed=unaddressed,
                    existing_mechanisms=existing,
                    evidence_refs=shown_e,
                    shown_attestation_ids=primary.ordered_attestation_ids,
                    evidence_texts={
                        str(e["attestation_id"]): str(e["text"]) for e in shown_evidence
                    },
                    inference_id=iid,
                ),
                parameters={"aliases": {**shown_h, **shown_e}},
            )
        except RoleOutputRefused as refused:
            state.coverage.update(status="FAILED", detail=refused.detail)
            return ()
        except _Blocked:
            state.coverage.update(status="BUDGET_BLOCKED")
            return ()
        return self._admit_coverage(state, call, draft, hypothesis_set)

    def _admit_coverage(
        self,
        state: _RunState,
        call: BudgetedInference,
        draft: CoverageDraft,
        hypothesis_set: HypothesisSet,
    ) -> tuple[str, ...]:
        request = state.request
        state.coverage["status"] = "DONE"
        state.coverage["inference_id"] = call.inference.inference_id
        state.coverage["declined"] = [
            {"observable_ref": d.observable_ref, "reason": d.reason, "evidence": list(d.evidence)}
            for d in draft.declined
        ]
        admitted: list[str] = []
        for proposal in draft.proposals:
            certificate = self._certificate(proposal, hypothesis_set, call.inference.inference_id)
            addresses = sorted(
                {g["observable_ref"] for g in state.coverage["gaps"]}
                & discriminated((certificate,))
            )
            try:
                self._admission.admit_alternative(
                    hypothesis_set,
                    certificate,
                    # What the rival rests on: the evidence it cited, never the whole bundle.
                    basis=draft.grounding[proposal.key],
                    policy=request.admission_policy,
                    event_id=self._mint("belief_revision_event"),
                    occurred_at=self._now(),
                    trace_id=request.trace_id,
                    actor_id=request.actor_id,
                )
            except HypothesisAdmissionRefused as refused:
                state.coverage["refused"].append(
                    {
                        "mechanism": proposal.mechanism,
                        "addresses": addresses,
                        "detail": str(refused),
                    }
                )
                continue
            state.hypotheses.add(certificate.hypothesis_id)
            admitted.append(certificate.hypothesis_id)
            state.coverage["certified"].append(
                {
                    "hypothesis_id": certificate.hypothesis_id,
                    "mechanism": proposal.mechanism,
                    "addresses": addresses,
                    "grounding": list(draft.grounding[proposal.key]),
                    "relevance": {
                        k: list(v) for k, v in draft.relevance.get(proposal.key, {}).items()
                    },
                }
            )
        return tuple(admitted)

    def _screening(
        self,
        state: _RunState,
        primary: EvidenceBundle,
        bindings: Mapping[str, OutcomeSpace],
        hypothesis_set: HypothesisSet,
    ) -> tuple[str, ...]:
        """The exploratory screening stage, and -- if it saw something abnormal -- the one review
        that may add rivals accounting for it. Returns the ids of rivals admitted after screening.

        The readings are taken by the research service's `ScreeningHook` under its declared
        policy; this decides only that a stage happens here, after the coverage review and before
        the Critic, so a post-screening rival is critiqued like every other. A stage or a review
        that cannot complete costs the debate nothing it had: the set stands, and the record says
        what ran, what was seen and why nothing more was asked.
        """
        request = state.request
        hook = request.screening
        assert hook is not None
        certificates = self._hypotheses.certificates_in_set(hypothesis_set.set_id)
        try:
            outcome = hook.screen(
                hypothesis_set_id=hypothesis_set.set_id,
                certificates=certificates,
                bindings=bindings,
            )
        except Exception as failed:  # recorded; the debate goes on without the stage
            state.screening = {"status": "FAILED", "detail": f"{type(failed).__name__}: {failed}"}
            return ()
        state.screening = {
            "status": "DONE",
            "plan_id": outcome.plan.plan_id,
            "policy": f"{outcome.plan.policy_id}@{outcome.plan.policy_version}",
            "unaddressed": list(outcome.plan.unaddressed_observables),
            "selected": [c.capability_id for c in outcome.plan.selected],
            "observations": [
                {
                    "screening_observation_id": o.screening_observation_id,
                    "check": o.capability_id,
                    "status": o.status.value,
                    "readings": [
                        {
                            "observable_ref": r.observable_ref,
                            "outcome": r.outcome,
                            "reference_outcome": r.reference_outcome,
                            "finding": r.finding.value,
                            "observation_id": r.observation_id,
                        }
                        for r in o.readings
                    ],
                }
                for o in outcome.observations
            ],
            "review": {"status": "NOT_NEEDED", "certified": [], "declined": [], "refused": []},
        }
        review: dict[str, Any] = state.screening["review"]
        if not outcome.abnormal:
            return ()
        readings = [(o, r) for o in outcome.executed for r in o.readings]
        abnormal = {
            r.observation_id: r.observable_ref for _, r in readings if r.finding.value == "ABNORMAL"
        }
        holder = {r.observation_id: o.screening_observation_id for o, r in readings}
        attestation_of = {r.observation_id: r.attestation_id for _, r in readings}
        shown_evidence = self._researcher.evidence_context(primary)
        shown_hypotheses, shown_h = aliased(
            [
                {
                    "hypothesis_id": c.hypothesis_id,
                    "statement": c.hypothesis.statement,
                    "mechanism": c.hypothesis.mechanism,
                    "discriminates_on": sorted(discriminated((c,))),
                }
                for c in self._hypotheses.certificates_in_set(hypothesis_set.set_id)
            ],
            "hypothesis_id",
            state.hypotheses,
        )
        evidence, shown_e = aliased(shown_evidence, "attestation_id", state.evidence)
        observations, shown_o = aliased(
            [
                {
                    "observation_ref": r.observation_id,
                    "check": o.capability_id,
                    "observable_ref": r.observable_ref,
                    "outcome_space_id": r.outcome_space_id,
                    "outcome_space_version": r.outcome_space_version,
                    "outcome": r.outcome,
                    "reference_outcome": r.reference_outcome,
                    "finding": r.finding.value,
                }
                for o, r in readings
            ],
            "observation_ref",
            state.observations,
        )
        existing = sorted(
            c.hypothesis.mechanism
            for c in self._hypotheses.certificates_in_set(hypothesis_set.set_id)
        )
        context: dict[str, object] = {
            "question": request.question,
            "evidence": evidence,
            "prediction_bindings": binding_context(bindings),
            "hypotheses": shown_hypotheses,
            "existing_mechanisms": existing,
            "screening_observations": observations,
            **self._structure(state),
        }
        if self._withheld(state, SCREENING_REVIEW.prompt, context, "screening review"):
            review["status"] = "RESERVED_FOR_CRITIC"
            return ()
        try:
            call, draft = self._ask(
                state,
                role=CognitiveRole.HYPOTHESIS_ENGINE,
                prompt=SCREENING_REVIEW.prompt,
                requires=SCREENING_REVIEW.requires,
                bundle=primary,
                context=context,
                parse=lambda text, iid: parse_screening_review(
                    text,
                    bindings=bindings,
                    abnormal=abnormal,
                    existing_mechanisms=existing,
                    evidence_refs=shown_e,
                    observation_refs=shown_o,
                    shown_attestation_ids=primary.ordered_attestation_ids,
                    evidence_texts={
                        str(e["attestation_id"]): str(e["text"]) for e in shown_evidence
                    },
                    inference_id=iid,
                ),
                parameters={"aliases": {**shown_h, **shown_e, **shown_o}},
            )
        except RoleOutputRefused as refused:
            review.update(status="FAILED", detail=refused.detail)
            return ()
        except _Blocked:
            review.update(status="BUDGET_BLOCKED")
            return ()
        review["status"] = "DONE"
        review["inference_id"] = call.inference.inference_id
        review["declined"] = [
            {"observation_id": d.observation, "reason": d.reason} for d in draft.declined
        ]
        admitted: list[str] = []
        for proposal in draft.proposals:
            certificate = self._certificate(proposal, hypothesis_set, call.inference.inference_id)
            seen = draft.responds_to[proposal.key]
            entry = {
                "mechanism": proposal.mechanism,
                "responds_to": list(seen),
                "grounding": list(draft.grounding[proposal.key]),
                "relevance": {k: list(v) for k, v in draft.relevance.get(proposal.key, {}).items()},
            }
            try:
                with hook.atomic():
                    self._admission.admit_alternative(
                        hypothesis_set,
                        certificate,
                        # What it was admitted on: the evidence it cited and the readings it
                        # accounts for. Admission is not support; the readings never will be.
                        basis=(
                            *draft.grounding[proposal.key],
                            *(attestation_of[o] for o in seen),
                        ),
                        policy=request.admission_policy,
                        event_id=self._mint("belief_revision_event"),
                        occurred_at=self._now(),
                        trace_id=request.trace_id,
                        actor_id=request.actor_id,
                    )
                    hook.condition(
                        hypothesis_id=certificate.hypothesis_id,
                        plan_id=outcome.plan.plan_id,
                        screening_observation_ids=sorted({holder[o] for o in seen}),
                        inference_id=call.inference.inference_id,
                    )
            except HypothesisAdmissionRefused as refused:
                review["refused"].append({**entry, "detail": str(refused)})
                continue
            state.hypotheses.add(certificate.hypothesis_id)
            admitted.append(certificate.hypothesis_id)
            review["certified"].append({"hypothesis_id": certificate.hypothesis_id, **entry})
        return tuple(admitted)

    def _structure(self, state: _RunState) -> dict[str, object]:
        """The device structure summary for a Hypothesis Engine context, when there is one."""
        structure = state.request.structure
        return {} if structure is None else {"device_structure": dict(structure)}

    def _withheld(
        self, state: _RunState, prompt: PromptTemplate, context: Mapping[str, object], what: str
    ) -> bool:
        """Whether an optional call before the Critic would eat into the Critic's reserve.

        Priced the way the dispatcher prices it (whitespace tokens of the prompt and context),
        against the budget's token cap less what the debate has spent. No cap or no reserve: never.
        """
        if self._reserve_short(
            state, token_count(prompt.template) + token_count(canonicalize(dict(context)))
        ):
            state.withheld.append(what)
            return True
        return False

    def _reserve_short(self, state: _RunState, estimate: int) -> bool:
        reserve = self._policy.critic_reserve_tokens
        policy = state.request.budget_policy
        if state.critic_started or not reserve or policy is None:
            return False
        cap = policy.caps.token_count
        if cap is None:
            return False
        return state.consumed.token_count + estimate + reserve > cap

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
        context, shown_h, shown_e = specialist_context(
            question=request.question,
            specialist=role.role_id,
            hypotheses=[
                {
                    "hypothesis_id": c.hypothesis_id,
                    "statement": c.hypothesis.statement,
                    "mechanism": c.hypothesis.mechanism,
                }
                for c in certificates
            ],
            evidence=self._researcher.evidence_context(bundle),
            hypothesis_aliases=state.hypotheses,
            evidence_aliases=state.evidence,
        )
        call, draft = self._ask(
            state,
            role=CognitiveRole.DOMAIN_SPECIALIST,
            prompt=PromptTemplate(role.prompt_id, role.prompt_version, role.prompt_template),
            requires=SPECIALIST_REQUIRES,
            bundle=bundle,
            context=context,
            role_label=role.role_id,
            parse=lambda text, iid: parse_specialist(
                text, role_id=role.role_id, hypothesis_ids=ids, shown=shown_h, inference_id=iid
            ),
            parameters={"aliases": {**shown_h, **shown_e}},
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
        # The designated typed falsifiers, never the prose: what is searched against is what
        # verification would adjudicate.
        falsifiers = [
            typed_falsifier_text(p) for c in in_contention for p in c.falsifier_predictions
        ]
        _, terms = self._ask(
            state,
            role=CognitiveRole.EVIDENCE_RESEARCHER,
            prompt=QUERY_REWRITER.prompt,
            requires=QUERY_REWRITER.requires,
            bundle=primary,
            context={"question": request.question, "mode": "INVERTED", "falsifiers": falsifiers},
            parse=lambda text, iid: parse_query_terms(text, inference_id=iid),
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
        context, shown_h, shown_e = critique_context(
            question=request.question,
            hypotheses=[
                {
                    "hypothesis_id": c.hypothesis_id,
                    "statement": c.hypothesis.statement,
                    "mechanism": c.hypothesis.mechanism,
                    # The designation, rendered -- the prose is the author's explanation only.
                    "falsifier": "; ".join(
                        shown_falsifier(p, state.hypotheses.add(c.hypothesis_id))
                        for p in c.falsifier_predictions
                    ),
                    "assumptions": list(c.hypothesis.assumptions),
                }
                for c in in_contention
            ],
            positions=[
                {
                    "role_id": p.role_id,
                    "mechanism_view": p.mechanism_view,
                    "hypothesis_refs": list(p.hypothesis_refs),
                }
                for p in positions
            ],
            evidence=self._researcher.evidence_context(cross),
            inverted_attestation_ids=[] if inverted is None else inverted.ordered_attestation_ids,
            hypothesis_aliases=state.hypotheses,
            evidence_aliases=state.evidence,
        )
        call, draft = self._ask(
            state,
            role=CognitiveRole.ADVERSARIAL_CRITIC,
            prompt=ADVERSARIAL_CRITIC.prompt,
            requires=ADVERSARIAL_CRITIC.requires,
            bundle=cross,
            context=context,
            critique_of=original,
            parse=lambda text, iid: parse_critique(
                text,
                targets=targets,
                shown_attestation_ids=cross.ordered_attestation_ids,
                hypothesis_refs=shown_h,
                evidence_refs=shown_e,
                inference_id=iid,
            ),
            parameters={"aliases": {**shown_h, **shown_e}},
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

    # -- asking -------------------------------------------------------------------------------

    def _ask(
        self,
        state: _RunState,
        *,
        role: CognitiveRole,
        prompt: PromptTemplate,
        requires: frozenset[str],
        bundle: EvidenceBundle,
        context: Mapping[str, object],
        parse: Callable[[str, str], _T],
        critique_of: InferenceProvenance | None = None,
        role_label: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> tuple[BudgetedInference, _T]:
        """One role call, read by its parser -- asked again, at most `max_attempts` in all, when
        the parser refuses the reply.

        Each attempt is its own budgeted, durable inference: a refused reply is kept verbatim, and
        the next one is told the parser's reason (`previous_reply_refused`) and names the one it
        replaces (`retry_of`). The only change made to a reply before parsing is
        `normalize_reply`'s envelope repair, and it is recorded. Nothing is taken from a refused
        reply, and the last refusal is raised with every earlier reason.
        """
        label = role_label or role.value
        refusals: list[RoleOutputRefused] = []
        previous: str | None = None
        for attempt in range(1, self._policy.max_attempts + 1):
            asked = dict(context)
            recorded: dict[str, object] = {**dict(parameters or {}), "attempt": attempt}
            if refusals and previous is not None:
                if role is not CognitiveRole.ADVERSARIAL_CRITIC and self._reserve_short(
                    state, token_count(prompt.template) + token_count(canonicalize(asked))
                ):
                    # A retry before Stage B that would leave the Critic short is not made.
                    state.withheld.append(f"retry of {label}")
                    break
                asked["previous_reply_refused"] = {
                    "reason": refusals[-1].detail,
                    "instruction": "Reply again, meeting the contract; change nothing else.",
                }
                recorded["retry_of"] = previous
            call = self._call(
                state,
                role=role,
                prompt=prompt,
                requires=requires,
                bundle=bundle,
                context=asked,
                critique_of=critique_of,
                role_label=role_label,
                parameters=recorded,
            )
            text, repair = normalize_reply(call.inference.text)
            entry: dict[str, Any] = {
                "role": label,
                "prompt_id": prompt.prompt_id,
                "inference_id": call.inference.inference_id,
                "attempt": attempt,
                "repair": repair,
            }
            try:
                result = parse(text, call.inference.inference_id)
            except RoleOutputRefused as refused:
                state.attempts.append({**entry, "outcome": "REFUSED", "detail": refused.detail})
                refusals.append(refused)
                previous = call.inference.inference_id
                continue
            state.attempts.append({**entry, "outcome": "ACCEPTED"})
            return call, result
        last = refusals[-1]
        if len(refusals) == 1:
            raise last
        raise RoleOutputRefused(
            last.role,
            f"{last.detail} -- refused on all {len(refusals)} attempts; earlier: "
            + "; ".join(r.detail for r in refusals[:-1]),
            inference_id=last.inference_id,
        )

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
        parameters: Mapping[str, object] | None = None,
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
            parameters=dict(parameters or {}),
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
        # The engine's prediction keys -> minted ids, so its falsifier designation survives intact.
        minted = {p.key: self._mint("prediction") for p in proposal.predictions}
        predictions = tuple(
            Prediction(
                prediction_id=minted[p.key],
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
            falsifier_prediction_ids=tuple(minted[k] for k in proposal.falsifier_prediction_keys),
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
    #: One alias table per kind for the whole debate, so a hypothesis is H3 in every call.
    hypotheses: AliasTable = field(default_factory=lambda: AliasTable("H"))
    evidence: AliasTable = field(default_factory=lambda: AliasTable("E"))
    #: Every reply attempt (`StructuredDebate._ask`), in order.
    attempts: list[dict[str, Any]] = field(default_factory=list)
    #: The coverage review's record; `DISABLED` unless the policy asks for one.
    coverage: dict[str, Any] = field(default_factory=lambda: {"status": "DISABLED"})
    #: Readings taken by screening, aliased O1, O2, ... in every call that shows them.
    observations: AliasTable = field(default_factory=lambda: AliasTable("O"))
    #: The screening stage's record; `DISABLED` unless the policy asks for one.
    screening: dict[str, Any] = field(default_factory=lambda: {"status": "DISABLED"})
    #: Set when Stage B begins: the Critic's reserve no longer holds anything back.
    critic_started: bool = False
    #: Optional calls and retries not made because they would have left the Critic short.
    withheld: list[str] = field(default_factory=list)


_T = TypeVar("_T")


def specialist_context(
    *,
    question: str,
    specialist: str,
    hypotheses: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    hypothesis_aliases: AliasTable,
    evidence_aliases: AliasTable,
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    """A Domain Specialist's context as research builds it -- and as its capability probe does,
    by calling this -- with the aliases each id was shown as (hypotheses, evidence)."""
    shown_hypotheses, shown_h = aliased(hypotheses, "hypothesis_id", hypothesis_aliases)
    shown_evidence, shown_e = aliased(evidence, "attestation_id", evidence_aliases)
    return (
        {
            "question": question,
            "specialist": specialist,
            "hypotheses": shown_hypotheses,
            "evidence": shown_evidence,
        },
        shown_h,
        shown_e,
    )


def coverage_context(
    *,
    question: str,
    hypotheses: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    bindings: Mapping[str, OutcomeSpace],
    unaddressed_checks: Sequence[Mapping[str, Any]],
    hypothesis_aliases: AliasTable,
    evidence_aliases: AliasTable,
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    """The coverage review's context as research builds it -- and as its capability probe does."""
    shown_hypotheses, shown_h = aliased(hypotheses, "hypothesis_id", hypothesis_aliases)
    shown_evidence, shown_e = aliased(evidence, "attestation_id", evidence_aliases)
    return (
        {
            "question": question,
            "evidence": shown_evidence,
            "prediction_bindings": binding_context(bindings),
            "hypotheses": shown_hypotheses,
            "existing_mechanisms": sorted(str(h["mechanism"]) for h in hypotheses),
            "unaddressed_checks": [dict(u) for u in unaddressed_checks],
        },
        shown_h,
        shown_e,
    )


def critique_context(
    *,
    question: str,
    hypotheses: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    inverted_attestation_ids: Sequence[str],
    hypothesis_aliases: AliasTable,
    evidence_aliases: AliasTable,
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    """The Adversarial Critic's context as research builds it -- and as its capability probe
    does -- with every hypothesis and attestation id shown as its alias."""
    shown_hypotheses, shown_h = aliased(hypotheses, "hypothesis_id", hypothesis_aliases)
    shown_evidence, shown_e = aliased(evidence, "attestation_id", evidence_aliases)
    for p in positions:
        for ref in p["hypothesis_refs"]:
            shown_h[hypothesis_aliases.add(ref)] = ref
    return (
        {
            "question": question,
            "hypotheses": shown_hypotheses,
            "positions": [
                {
                    **p,
                    "hypothesis_refs": [hypothesis_aliases.alias(r) for r in p["hypothesis_refs"]],
                }
                for p in positions
            ],
            "evidence": shown_evidence,
            "inverted_attestation_ids": [evidence_aliases.add(a) for a in inverted_attestation_ids],
        },
        shown_h,
        shown_e,
    )


def shown_falsifier(prediction: Prediction, alias: str) -> str:
    """`typed_falsifier_text` as a model is shown it: the hypothesis by its alias, and no
    prediction id -- nothing a role would have to copy back is ever a canonical id."""
    text = typed_falsifier_text(prediction).replace(prediction.hypothesis_id, alias)
    return text.rsplit(" (", 1)[0]


def _gap_record(gap: CoverageGap) -> dict[str, object]:
    return {
        "observable_ref": gap.observable_ref,
        "check": gap.capability_id,
        "action_type": gap.action_type,
        "estimated_wall_clock_s": gap.cost.wall_clock_s,
    }


__all__ = [
    "DebateOutcome",
    "DebatePolicy",
    "DebateRequest",
    "StopReason",
    "StructuredDebate",
    "Trigger",
    "coverage_context",
    "critique_context",
    "shown_falsifier",
    "specialist_context",
]
