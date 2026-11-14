"""§9.6's SelectionPolicy and §17.14.1's VerificationPlan (VER-001, VER-003, VER-005, VER-007).

    §9.6   After Pareto filtering, planner MUST apply a versioned deterministic SelectionPolicy.
           Identical input + identical policy version MUST return an identical ranked plan.
    §9.4   不得把全部成本壓縮成單一 normalized_cost 作為唯一決策依據（VER-003）。
    VER-001 下一個 verification action 必須有 predicted discriminatory outcome + estimated cost；
           若較便宜 evidence 已足夠，不得無理由升級到 simulator。

A POLICY ORDERS DIMENSIONS; IT NEVER WEIGHS THEM. A SelectionPolicy names which CostVector
dimensions the Pareto filter compares and the order in which the lexicographic fallback breaks
what the filter leaves. There is no weight and no sum anywhere in this module: a weighted sum is a
normalized_cost with extra steps, and VER-003 forbids it as the decision basis. A policy with a
single Pareto dimension is refused for the same reason -- one dimension is a scalar cost under
another name.

A PLAN IS THE WHOLE ARGUMENT, NOT ITS CONCLUSION. §17.14.1's VerificationPlan carries every
candidate, the ranking, the sufficiency result per candidate and the Pareto front, and the model
refuses a plan whose chosen action is not the first sufficient one in its own ranking. So "why this
check and not the cheaper one" is answerable from the stored row, and a plan that chose an expensive
action while a cheaper sufficient one ranked ahead of it cannot be recorded (VER-001).
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now


class CostDimension(StrEnum):
    """§9.4's CostVector dimensions, by field name. The only things a SelectionPolicy may order."""

    WALL_CLOCK_S = "wall_clock_s"
    HUMAN_MINUTES = "human_minutes"
    MONEY_ESTIMATE = "money_estimate"
    COMPUTE_UNITS = "compute_units"
    TOKEN_COUNT = "token_count"
    LICENSE_SEAT_S = "license_seat_s"
    EARLIEST_AVAILABLE_AT = "earliest_available_at"
    IRREVERSIBLE = "irreversible"
    DEPENDENCY_RISK = "dependency_risk"


class TieBreakRule(StrEnum):
    """What decides between candidates equal on every declared dimension. Never implied."""

    CAPABILITY_ID = "CAPABILITY_ID"


class SelectionPolicy(CoreModel):
    """§9.6, field for field (plus nothing). Immutable per (policy_id, version)."""

    policy_id: str
    version: str
    pareto_dimensions: tuple[CostDimension, ...]
    lexicographic_fallback: tuple[CostDimension, ...]
    tie_break_rule: TieBreakRule = TieBreakRule.CAPABILITY_ID
    effective_from: dt.datetime

    @model_validator(mode="after")
    def _a_policy_orders_a_vector(self) -> Self:
        if not self.policy_id.strip() or not self.version.strip():
            raise ValueError("a selection policy names its id and version (VER-005)")
        if len(self.pareto_dimensions) < 2:
            raise ValueError(
                f"selection policy {self.ref} filters on {len(self.pareto_dimensions)} dimension; "
                "a Pareto filter over one dimension is a single normalized cost under another "
                "name, which VER-003 forbids as the decision basis"
            )
        for name, dims in (
            ("pareto_dimensions", self.pareto_dimensions),
            ("lexicographic_fallback", self.lexicographic_fallback),
        ):
            if len(set(dims)) != len(dims):
                raise ValueError(f"selection policy {self.ref} repeats a dimension in {name}")
        if not self.lexicographic_fallback:
            raise ValueError(
                f"selection policy {self.ref} declares no lexicographic fallback; §9.6 exists "
                "because a Pareto front is rarely a single candidate, and a front with no declared "
                "order would be ordered by whatever the implementation happened to do"
            )
        return self

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"


class PlanDecision(StrEnum):
    """What the planner concluded. A plan that chose nothing still says why."""

    #: A sufficient action exists and the cheapest one under the policy is chosen.
    ACT = "ACT"
    #: The admitted evidence already decides a transition; spending on a new action is unjustified.
    EXISTING_EVIDENCE_DECIDES = "EXISTING_EVIDENCE_DECIDES"
    #: No candidate could change any decision. The honest outcome is to stop, not to spend.
    NO_SUFFICIENT_ACTION = "NO_SUFFICIENT_ACTION"


class SufficiencySummary(CoreModel):
    """One candidate's §9.1 result, as the plan records it."""

    sufficient: bool
    #: `InsufficientReason` value (or a planner reason) when not sufficient.
    reason: str | None = None
    #: (hypothesis_id, candidate_to_state, outcome) triples the action could produce.
    discriminating: tuple[tuple[str, str, str], ...] = ()
    #: (outcome, failed §9.1 plausibility clause) for declared outcomes set aside (VER-004).
    implausible: tuple[tuple[str, str], ...] = ()
    #: The domain's declared disagreement between rivals over this action's observable, if known.
    disagreement: str | None = None
    metric_ref: str | None = None


class EscalationStep(CoreModel):
    """A candidate that would have cost less than the chosen one, and why it was passed over."""

    action_id: str
    reason: str


class ActionTradeoff(CoreModel):
    """One candidate's full cost vector, presented rather than reduced (VER-003, VER-007)."""

    action_id: str
    action_type: str
    cost: dict[str, Any]
    pareto_layer: int
    #: Candidates this one is dominated by on the policy's Pareto dimensions (empty on the front).
    dominated_by: tuple[str, ...] = ()


class PlanRationale(CoreModel):
    decision: PlanDecision
    summary: str
    #: Cheaper candidates -- by the policy's cost order alone -- that the chosen action overtook.
    escalation: tuple[EscalationStep, ...] = ()
    #: Historical failure analyses consulted before planning (§6.9 case-based retrieval).
    precedents: tuple[str, ...] = ()
    #: Transitions the admitted evidence already decides (EXISTING_EVIDENCE_DECIDES).
    existing_evidence: tuple[str, ...] = ()
    tradeoffs: tuple[ActionTradeoff, ...] = ()


class VerificationPlan(CoreModel):
    """§17.14.1, plus `project_id` (SEC-002 scope) and the rationale `rationale_ref` names.

    `rationale_ref` is `<plan_id>#rationale`: the rationale is stored with the plan rather than as a
    separate record, so the two cannot drift, and the reference form is kept so a later milestone
    can move it to an artifact without changing the contract.
    """

    plan_id: str
    project_id: str
    episode_id: str
    candidate_action_ids: tuple[str, ...]
    ranked_action_ids: tuple[str, ...]
    sufficiency_results: dict[str, SufficiencySummary]
    pareto_front_ids: tuple[str, ...]
    selection_policy_id: str
    selection_policy_version: str
    chosen_action_id: str | None = None
    rationale_ref: str
    rationale: PlanRationale
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _the_plan_is_its_own_argument(self) -> Self:
        candidates = set(self.candidate_action_ids)
        if len(candidates) != len(self.candidate_action_ids):
            raise ValueError(f"plan {self.plan_id} lists a candidate twice")
        if sorted(self.ranked_action_ids) != sorted(self.candidate_action_ids):
            raise ValueError(
                f"plan {self.plan_id} ranks {sorted(self.ranked_action_ids)} but its candidates "
                f"are {sorted(self.candidate_action_ids)}; a ranking that drops or adds a "
                "candidate hides the comparison it claims to have made"
            )
        if set(self.sufficiency_results) != candidates:
            raise ValueError(f"plan {self.plan_id} has no sufficiency result for every candidate")
        if not set(self.pareto_front_ids) <= candidates:
            raise ValueError(f"plan {self.plan_id} puts a non-candidate on its Pareto front")
        if self.rationale_ref != f"{self.plan_id}#rationale":
            raise ValueError(f"plan {self.plan_id} names another plan's rationale")
        first_sufficient = next(
            (a for a in self.ranked_action_ids if self.sufficiency_results[a].sufficient), None
        )
        if self.rationale.decision is PlanDecision.ACT:
            if self.chosen_action_id is None or self.chosen_action_id != first_sufficient:
                raise ValueError(
                    f"plan {self.plan_id} chooses {self.chosen_action_id!r} but the first "
                    f"sufficient action in its own ranking is {first_sufficient!r}. VER-001: a "
                    "plan may not pass over a cheaper sufficient check without a recorded reason, "
                    "and the ranking IS the reason"
                )
        elif self.chosen_action_id is not None:
            raise ValueError(
                f"plan {self.plan_id} decided {self.rationale.decision.value} and still chose "
                f"{self.chosen_action_id}"
            )
        elif self.rationale.decision is PlanDecision.NO_SUFFICIENT_ACTION and first_sufficient:
            raise ValueError(
                f"plan {self.plan_id} says no action is sufficient while {first_sufficient} is"
            )
        return self


__all__ = [
    "ActionTradeoff",
    "CostDimension",
    "EscalationStep",
    "PlanDecision",
    "PlanRationale",
    "SelectionPolicy",
    "SufficiencySummary",
    "TieBreakRule",
    "VerificationPlan",
]
