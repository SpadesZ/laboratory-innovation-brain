"""The Verification Planner: least-cost sufficient verification, with its reasons (VER-001).

    VER-001   下一個 verification action 必須有 predicted discriminatory outcome + estimated cost；
              若較便宜 evidence 已足夠，不得無理由升級到 simulator。
    T-VER-001 Planner 先檢查已存在 evidence / cheap actions；只有較便宜層不足時才升級 simulator，並
              記錄選擇理由。
    §25.4     Verification Planner 先檢查 historical case / connectivity / extraction consistency 等
              低成本動作，再在需要時升級 simulator。

THE PLANNER, IN THE ORDER IT WORKS:

    0a. precedents     §6.9's case memory is read first: past FailureAnalyses with a matching
                       symptom are recorded on the plan. They inform the person reading it; they
                       decide nothing, because a precedent from another device is not evidence
                       about this one.
    0b. existing       for every ACTIVE rival and every governed transition, does the ADMITTED
        evidence       evidence already license it (`evaluate` -> ALLOW)? If so, the plan chooses
                       nothing -- spending on a new action when the answer is already on record is
                       exactly the unjustified escalation VER-001 forbids.
    1.  candidates     M2's descriptor-only `VerificationPlanner`: capabilities that produce an
                       observable some rival predicts over and whose inputs are available.
    2.  sufficiency    `verification.sufficiency.assess_action` -- §9.1 with all four plausibility
                       clauses and the producing capability's implied authority.
    3.  disagreement   M3's `rank_by_disagreement` over the rivals' plausible predictions -- their
                       affirmative forecasts only; a falsifier is no forecast (sufficiency, step 2,
                       still reads every prediction).
    4.  selection      `verification.selection.rank` under the declared SelectionPolicy.
    5.  the choice     the first SUFFICIENT action in that ranking -- which, by the ranking's
                       construction, is the cheapest sufficient one under the policy.
    6.  the reasons    every candidate the cost order alone would have put ahead of the choice is
                       listed with why it was passed over; every candidate's full CostVector and
                       Pareto standing is presented (VER-003, VER-007). `VerificationPlan` refuses
                       a plan whose choice is not the first sufficient action it ranks.

THE PLANNER READS NO BACKEND NAME AND KNOWS NO DOMAIN. It reads Capability descriptors, declared
OutcomeSpaces, the domain's registered outcome validator and disagreement metrics, and a
SelectionPolicy. "Simulator" is `ActionType.SIMULATION` on a descriptor, nothing more.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from lab_brain.core.models.capability import Capability
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.prediction import OutcomeSpace, Prediction
from lab_brain.core.models.transition import TransitionOutcome
from lab_brain.core.models.verification import (
    ActionTradeoff,
    EscalationStep,
    PlanDecision,
    PlanRationale,
    SelectionPolicy,
    SufficiencySummary,
    VerificationPlan,
)
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.disagreement import DisagreementMetricRegistry, rank_by_disagreement
from lab_brain.verification.planner import VerificationPlanner
from lab_brain.verification.plausibility import outcome_validator_id
from lab_brain.verification.selection import (
    SelectionCandidate,
    cost_order,
    dominated_by,
    rank,
)
from lab_brain.verification.sufficiency import (
    ActionSufficiency,
    HypothesisState,
    TransitionTarget,
    assess_action,
)
from lab_brain.verification.tradeoff import ScalarJustification, require_design_space_justification

if TYPE_CHECKING:  # pragma: no cover
    from lab_brain.core.authority import AuthorityPolicy


class CaseMemory(Protocol):
    """§6.9: past FailureAnalyses are first-class retrieval targets."""

    def similar_failures(self, project_id: str, symptom: str) -> Sequence[str]: ...


class ValidatorLookup(Protocol):
    def resolve(self, validator_id: str) -> Any: ...


@dataclass(frozen=True)
class PlanningResult:
    plan: VerificationPlan
    assessments: Mapping[str, ActionSufficiency]
    costs: Mapping[str, CostVector]
    chosen: Capability | None


def _cost_record(cost: CostVector) -> dict[str, Any]:
    return cost.model_dump(mode="json")


class LeastCostPlanner:
    """Plan the next verification action for one set of rivals. Pure apart from `mint`/`now`."""

    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry,
        metrics: DisagreementMetricRegistry,
        validators: ValidatorLookup,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
        case_memory: CaseMemory | None = None,
        scalar_justifications: Mapping[str, ScalarJustification] | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._metrics = metrics
        self._validators = validators
        self._mint = mint
        self._now = now
        self._case_memory = case_memory
        self._justifications = dict(scalar_justifications or {})

    def _validator(self, domain: str | None) -> Any | None:
        if domain is None:
            return None
        try:
            return self._validators.resolve(outcome_validator_id(domain))
        except Exception:
            return None

    def plan(
        self,
        *,
        project_id: str,
        episode_id: str,
        hypotheses: Sequence[HypothesisState],
        targets: Sequence[TransitionTarget],
        policy: SelectionPolicy,
        authority_policy: AuthorityPolicy | None,
        available_inputs: frozenset[str] = frozenset(),
        conditions: Mapping[str, Any] | None = None,
        symptom: str | None = None,
        exclude: frozenset[str] = frozenset(),
        projected_condition_match: ConditionMatch | None = None,
    ) -> PlanningResult:
        """One plan for the current state.

        ``exclude`` names capabilities already executed in this episode. Re-running a check whose
        result is on record would be spending to learn what is already known; a replicate is a
        different action and would need its own descriptor.
        """
        conditions = dict(conditions or {})
        precedents = (
            tuple(self._case_memory.similar_failures(project_id, symptom))
            if self._case_memory is not None and symptom
            else ()
        )

        # 0b. Does the admitted evidence already decide something?
        decided = []
        for state in sorted(hypotheses, key=lambda s: s.view.hypothesis_id):
            for target in targets:
                if state.view.current_state is not target.policy.from_state:
                    continue
                verdict = target.policy.evaluate(
                    state.view,
                    state.admitted_relations,
                    authority_policy,
                    state.condition_matches,
                    state.independence,
                    target.to_state,
                )
                if verdict.outcome is TransitionOutcome.ALLOW:
                    decided.append(
                        f"{state.view.hypothesis_id}: {target.policy.from_state.value} -> "
                        f"{target.to_state.value} under {target.policy.policy_id}@"
                        f"{target.policy.version}"
                    )

        # 1. Candidates, from descriptors only.
        predictions = [p for s in hypotheses for p in s.predictions]
        spaces = self._spaces(predictions)
        for space in spaces.values():
            require_design_space_justification(space, self._justifications)
        matching = VerificationPlanner(self._capabilities).plan(
            goal=sorted({p.observable_ref for p in predictions}), available=available_inputs
        )
        planned = tuple(a for a in matching if a.capability_id not in exclude)
        already_run = tuple(sorted(a.capability_id for a in matching if a.capability_id in exclude))

        # 2-3. Sufficiency and disagreement per candidate.
        assessments: dict[str, ActionSufficiency] = {}
        costs: dict[str, CostVector] = {}
        summaries: dict[str, SufficiencySummary] = {}
        selection: list[SelectionCandidate] = []
        for action in planned:
            capability = action.capability
            assessed = assess_action(
                capability,
                hypotheses=hypotheses,
                targets=targets,
                spaces=spaces,
                conditions=conditions,
                validator=self._validator(capability.domain),
                authority_policy=authority_policy,
                projected_condition_match=projected_condition_match,
            )
            implausible_outcomes = {v.outcome for v in assessed.implausible}
            usable = [
                p
                for p in predictions
                if p.observable_ref in capability.produces
                and p.expected_outcome not in implausible_outcomes
            ]
            disagreement, metric_ref = _max_disagreement(capability, usable, self._metrics)
            discriminating = disagreement is not None and disagreement > 0
            assessments[capability.capability_id] = assessed
            costs[capability.capability_id] = action.cost
            summaries[capability.capability_id] = SufficiencySummary(
                sufficient=assessed.sufficient,
                reason=assessed.reason,
                discriminating=tuple(
                    (d.hypothesis_id, d.to_state.value, d.outcome) for d in assessed.discriminating
                ),
                implausible=tuple(
                    (v.outcome, v.failed_clause.value if v.failed_clause else "")
                    for v in assessed.implausible
                ),
                disagreement=None if disagreement is None else str(disagreement),
                metric_ref=metric_ref,
            )
            selection.append(
                SelectionCandidate(
                    action_id=capability.capability_id,
                    cost=action.cost,
                    sufficient=assessed.sufficient,
                    discriminating=discriminating,
                )
            )

        # 4-5. Selection and the choice.
        ranking = rank(selection, policy)
        chosen_id = None
        if decided:
            decision = PlanDecision.EXISTING_EVIDENCE_DECIDES
        else:
            chosen_id = next((a for a in ranking.ranked_ids if summaries[a].sufficient), None)
            decision = PlanDecision.ACT if chosen_id else PlanDecision.NO_SUFFICIENT_ACTION

        # 6. The reasons.
        escalation: list[EscalationStep] = []
        if chosen_id is not None:
            # Checks that ran earlier in this episode come first: they are the cheaper layer that
            # was tried, and their outcomes are on record in the evidence the rivals now carry.
            escalation.extend(
                EscalationStep(
                    action_id=action_id,
                    reason="executed earlier in this episode; its outcome is on record and is "
                    "already reflected in the rivals' admitted evidence",
                )
                for action_id in already_run
            )
            for action_id in cost_order(selection, policy):
                if action_id == chosen_id:
                    break
                escalation.append(
                    EscalationStep(
                        action_id=action_id,
                        reason=f"not sufficient: {summaries[action_id].reason}"
                        + _implausible_note(summaries[action_id]),
                    )
                )
        tradeoffs = tuple(
            ActionTradeoff(
                action_id=c.action_id,
                action_type=self._capabilities.resolve(c.action_id).action_type.value,
                cost=_cost_record(c.cost),
                pareto_layer=ranking.layers[c.action_id],
                dominated_by=dominated_by(
                    c,
                    [
                        o
                        for o in selection
                        if (o.sufficient, o.discriminating) == (c.sufficient, c.discriminating)
                    ],
                    policy.pareto_dimensions,
                ),
            )
            for c in sorted(selection, key=lambda c: c.action_id)
        )
        plan_id = self._mint("verification_plan")
        summary = _summary(decision, chosen_id, self._capabilities, escalation, decided)
        plan = VerificationPlan(
            plan_id=plan_id,
            project_id=project_id,
            episode_id=episode_id,
            candidate_action_ids=tuple(sorted(summaries)),
            ranked_action_ids=ranking.ranked_ids,
            sufficiency_results=summaries,
            pareto_front_ids=ranking.front_ids,
            selection_policy_id=policy.policy_id,
            selection_policy_version=policy.version,
            chosen_action_id=chosen_id,
            rationale_ref=f"{plan_id}#rationale",
            rationale=PlanRationale(
                decision=decision,
                summary=summary,
                escalation=tuple(escalation),
                precedents=precedents,
                existing_evidence=tuple(decided),
                tradeoffs=tradeoffs,
            ),
            created_at=self._now(),
        )
        return PlanningResult(
            plan=plan,
            assessments=assessments,
            costs=costs,
            chosen=None if chosen_id is None else self._capabilities.resolve(chosen_id),
        )

    def _spaces(self, predictions: Sequence[Prediction]) -> dict[tuple[str, str], OutcomeSpace]:
        found: dict[tuple[str, str], OutcomeSpace] = {}
        for p in predictions:
            key = (p.outcome_space_id, p.outcome_space_version)
            space = self._metrics.outcome_space(*key)
            if space is not None:
                found[key] = space
        return found


def _max_disagreement(
    capability: Capability,
    predictions: Sequence[Prediction],
    metrics: DisagreementMetricRegistry,
) -> tuple[Decimal | None, str | None]:
    ranked = rank_by_disagreement(
        [(capability.capability_id, capability.produces)], predictions, metrics
    )
    known = [r for r in ranked if r.disagreement is not None]
    if not known:
        return None, None
    best = max(known, key=lambda r: (r.disagreement, r.metric_ref or ""))
    return best.disagreement, best.metric_ref


def _implausible_note(summary: SufficiencySummary) -> str:
    if not summary.implausible:
        return ""
    return (
        " (implausible outcomes set aside: "
        + ", ".join(f"{o} [{clause}]" for o, clause in summary.implausible)
        + ")"
    )


def _summary(
    decision: PlanDecision,
    chosen_id: str | None,
    capabilities: CapabilityRegistry,
    escalation: Sequence[EscalationStep],
    decided: Sequence[str],
) -> str:
    if decision is PlanDecision.EXISTING_EVIDENCE_DECIDES:
        return (
            "the admitted evidence already licenses "
            + "; ".join(decided)
            + ". No new action is justified before that transition is attempted"
        )
    if decision is PlanDecision.NO_SUFFICIENT_ACTION or chosen_id is None:
        return (
            "no candidate has a plausible outcome that would change any governed decision; the "
            "honest next step is to stop, not to spend"
        )
    chosen = capabilities.resolve(chosen_id)
    passed = sum(1 for step in escalation if step.reason.startswith("not sufficient"))
    ran = len(escalation) - passed
    earlier = f"; {ran} check(s) already executed in this episode" if ran else ""
    return (
        f"{chosen_id} ({chosen.action_type.value}) is the cheapest SUFFICIENT action under the "
        f"selection policy; {passed} cheaper candidate(s) were considered first and could not "
        f"change any decision{earlier}"
        if passed
        else f"{chosen_id} ({chosen.action_type.value}) is sufficient and nothing cheaper "
        f"remains{earlier}"
    )


__all__ = [
    "CaseMemory",
    "LeastCostPlanner",
    "PlanningResult",
    "ValidatorLookup",
]
