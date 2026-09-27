"""§9.1's `sufficient(action)` for a planned Capability, with plausibility and implied authority.

    sufficient(action) =
      exists y in declared_outcome_space(action) such that
          plausible(y)
      and ( TransitionPolicy.evaluate_hypothetical(state, relations_from(y)).outcome
              != TransitionPolicy.evaluate(state).outcome
         or y resolves at least one Conflict where blocking = true )

    §17.5.1  RelationJudgmentTemplate.implied_authority_class -- "the authority class the producing
             Capability would yield -- declared, because the planner must be able to ask 'would
             evidence of THIS quality clear the gate' before spending on it."

WHY THIS IS NOT M0b's `evaluate_sufficiency`, AND WHY IT IS STILL THE SAME RULE. M0b built VER-006's
half: membership, explicit exclusion, no-prediction-is-not-sufficient, determinism. Two things a
planner needs were left out on purpose and named there -- plausibility clauses 3-4 (VER-004, owned
here) -- and one was left out without being named: `evaluate_hypothetical` is handed the same
HypothesisView as the baseline, so the authority the observation WOULD carry never reaches the
authority gate. A planner built on it cannot tell a simulation from a reading of a lab note, and
after one low-authority result nothing is ever sufficient again. So this module asks exactly §9.1's
question with the hypothetical view §17.5.1 describes: the current view, plus the authority class
the producing Capability would yield (the template's `implied_authority_class` when it declares
one, the Capability descriptor's `authority_class` otherwise).

NOT A SECOND TRANSITION OPERATOR. The baseline is `policy.evaluate(...)` and the projection is
`policy.evaluate_hypothetical(...)` -- the canonical operator's two methods, unchanged. Nothing here
decides a transition; `BeliefEpisode` still re-derives every real one from admitted relations.

The blocking-Conflict disjunct stays unevaluated, for M0b's reason: whether an outcome RESOLVES a
conflict is a reviewer's durable decision (`v3.3-a14`), not a planning inference.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.capability import Capability
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.prediction import OutcomeSpace, Prediction
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionDecision,
    TransitionPolicy,
)
from lab_brain.core.sufficiency import InsufficientReason
from lab_brain.verification.plausibility import PlausibilityVerdict, assess_outcome

if TYPE_CHECKING:  # pragma: no cover
    from lab_brain.core.authority import AuthorityPolicy

#: §9.1's second disjunct, and why it is not evaluated (see the module docstring).
UNEVALUATED_CLAUSES: tuple[str, ...] = (
    "y resolves a blocking Conflict: a resolution is a durable human record (v3.3-a14), not an "
    "inference",
)


@dataclass(frozen=True)
class HypothesisState:
    """One rival as the planner sees it: view, admitted relations, predictions, and the
    ConditionMatches and independence rollup its admitted evidence carries -- the six inputs
    `evaluate` takes, so the baseline the planner compares against is the decision the governed
    path would actually reach today."""

    view: HypothesisView
    admitted_relations: tuple[RelationJudgment, ...]
    predictions: tuple[Prediction, ...]
    condition_matches: tuple[ConditionMatch, ...] = ()
    independence: IndependenceSummary = field(default_factory=IndependenceSummary)


@dataclass(frozen=True)
class TransitionTarget:
    """A transition a result could license: the policy that governs it and its target state."""

    policy: TransitionPolicy
    to_state: BeliefState


@dataclass(frozen=True)
class Discrimination:
    hypothesis_id: str
    to_state: BeliefState
    outcome: str
    projected: TransitionDecision


@dataclass(frozen=True)
class ActionSufficiency:
    """§9.1 for one action across every rival and every governed transition."""

    capability_id: str
    sufficient: bool
    discriminating: tuple[Discrimination, ...]
    implausible: tuple[PlausibilityVerdict, ...]
    reason: str | None
    unevaluated_clauses: tuple[str, ...] = UNEVALUATED_CLAUSES


def _stamp(prediction: Prediction, authority_class: str) -> Prediction:
    """The prediction's effects, carrying the authority the producing action would yield."""
    effects = tuple(
        effect
        if effect.implied_authority_class is not None
        else effect.model_copy(update={"implied_authority_class": authority_class})
        for effect in prediction.relation_effect_if_observed
    )
    return prediction.model_copy(update={"relation_effect_if_observed": effects})


def assess_action(
    capability: Capability,
    *,
    hypotheses: Sequence[HypothesisState],
    targets: Sequence[TransitionTarget],
    spaces: Mapping[tuple[str, str], OutcomeSpace],
    conditions: Mapping[str, Any],
    validator: Any | None,
    authority_policy: AuthorityPolicy | None,
    projected_condition_match: ConditionMatch | None = None,
) -> ActionSufficiency:
    """Would any plausible outcome of this action change any governed decision for any rival?

    THE PROJECTION IS THE STATE PLUS WHAT THE ACTION WOULD ADD, and nothing else: the relations
    its declared predictions instantiate, the authority class the producing capability would yield,
    the ConditionMatch its planned execution conditions have against the diagnosis's (known before
    it runs, because the loop chooses those conditions), and one more independent work -- a new
    execution is a new source (see `verification.loop` for why a Run is the work unit).
    """
    discriminating: list[Discrimination] = []
    implausible: dict[str, PlausibilityVerdict] = {}
    saw_prediction = False
    unresolved = False
    for state in sorted(hypotheses, key=lambda s: s.view.hypothesis_id):
        relevant = [
            p
            for p in sorted(state.predictions, key=lambda p: p.prediction_id)
            if p.observable_ref in capability.produces
            and p.hypothesis_id == state.view.hypothesis_id
        ]
        if not relevant:
            continue
        saw_prediction = True
        for target in targets:
            if state.view.current_state is not target.policy.from_state:
                continue
            baseline = target.policy.evaluate(
                state.view,
                state.admitted_relations,
                authority_policy,
                state.condition_matches,
                state.independence,
                target.to_state,
            )
            projected_matches = state.condition_matches + (
                () if projected_condition_match is None else (projected_condition_match,)
            )
            projected_independence = state.independence.model_copy(
                update={"independent_count": state.independence.independent_count + 1}
            )
            for prediction in relevant:
                space = spaces.get((prediction.outcome_space_id, prediction.outcome_space_version))
                if space is None:
                    unresolved = True
                    continue
                verdict = assess_outcome(
                    prediction.expected_outcome,
                    space=space,
                    observable_ref=prediction.observable_ref,
                    capability=capability,
                    conditions=conditions,
                    validator=validator,
                )
                if not verdict.plausible:
                    implausible.setdefault(prediction.expected_outcome, verdict)
                    continue
                stamped = _stamp(prediction, capability.authority_class)
                implied = sorted(
                    {
                        e.implied_authority_class
                        for e in stamped.relation_effect_if_observed
                        if e.implied_authority_class is not None
                    }
                )
                hypothetical_view = state.view.model_copy(
                    update={
                        "admitted_authority_classes": tuple(
                            sorted({*state.view.admitted_authority_classes, *implied})
                        )
                    }
                )
                projected = target.policy.evaluate_hypothetical(
                    hypothetical_view,
                    state.admitted_relations,
                    stamped.hypothetical_relations(project_id=state.view.project_id),
                    authority_policy,
                    projected_matches,
                    projected_independence,
                    target.to_state,
                )
                if projected.outcome is not baseline.outcome:
                    discriminating.append(
                        Discrimination(
                            state.view.hypothesis_id,
                            target.to_state,
                            prediction.expected_outcome,
                            projected,
                        )
                    )
    ordered = tuple(
        sorted(discriminating, key=lambda d: (d.hypothesis_id, d.to_state.value, d.outcome))
    )
    if ordered:
        reason = None
    elif not saw_prediction:
        reason = InsufficientReason.NO_PREDICTION_OVER_PRODUCES.value
    elif unresolved and not implausible:
        reason = InsufficientReason.OUTCOME_SPACE_UNRESOLVED.value
    elif implausible and not _any_plausible(hypotheses, capability, implausible):
        reason = "NO_PLAUSIBLE_OUTCOME"
    else:
        reason = InsufficientReason.NO_OUTCOME_CHANGES_THE_DECISION.value
    return ActionSufficiency(
        capability_id=capability.capability_id,
        sufficient=bool(ordered),
        discriminating=ordered,
        implausible=tuple(implausible[k] for k in sorted(implausible)),
        reason=reason,
    )


def _any_plausible(
    hypotheses: Sequence[HypothesisState],
    capability: Capability,
    implausible: Mapping[str, PlausibilityVerdict],
) -> bool:
    return any(
        p.expected_outcome not in implausible
        for s in hypotheses
        for p in s.predictions
        if p.observable_ref in capability.produces
    )


__all__ = [
    "UNEVALUATED_CLAUSES",
    "ActionSufficiency",
    "Discrimination",
    "HypothesisState",
    "TransitionTarget",
    "assess_action",
]
