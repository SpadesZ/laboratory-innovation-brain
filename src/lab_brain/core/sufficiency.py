"""§9.1's `sufficient(action)`, restricted to the half VER-006 puts in M0b.

    §9.1  sufficient(action) =
            exists y in declared_outcome_space(action) such that
                plausible(y)
            and ( evaluate_hypothetical(state, relations_from(y)).outcome != evaluate(state).outcome
               or y resolves at least one Conflict where blocking = true )

          If no ACTIVE hypothesis declares a Prediction over action.produces,
          the action is NOT sufficient. Absence of a declared prediction is not
          evidence of discriminative power.

WHAT IS IMPLEMENTED AND WHAT IS NOT, STATED SO NOBODY LOOKS FOR THE REST. VER-006's §26 row names
four things: an out-of-space `expected_outcome` refused at admission, `evaluate_hypothetical`
persisting nothing, an action with no bound Prediction over its `produces` reported NOT sufficient,
and identical inputs returning an identical decision. Those are here.

`plausible(y)` in full is **VER-004**, which is M3: clauses 3 and 4 need a DomainPack validator
returning a `ValidationReport` and a Capability that can say whether it could actually yield `y`
under current conditions, and neither exists yet. What is honoured here is the part that does not
need them and that VER-006 depends on -- `y` must be a member of the declared, versioned
OutcomeSpace and must not be explicitly excluded. The rest is refused *open*: this function reports
what it can check and names what it did not, rather than reporting "sufficient" on two clauses out
of four.

THE SECOND DISJUNCT -- "y resolves at least one blocking Conflict" -- is also deferred, and for a
reason worth writing down rather than a limitation of effort. Deciding that an outcome *resolves* a
conflict is a scientific judgment: it is what a reviewer does in §17.19.1, and `v3.3-a14` made the
resolution a durable human record precisely so that nothing could infer it. A planner that inferred
"this measurement would resolve the authority conflict" would be pre-empting the review.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotation only; see `belief.py` for the cycle it avoids
    from lab_brain.core.authority import AuthorityPolicy

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.prediction import OutcomeSpace, Prediction
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionDecision,
    TransitionPolicy,
)


class InsufficientReason(StrEnum):
    """Why an action was not found sufficient. An enum, not prose, for the reason
    `VerificationFailure` is one: this is the assertion surface, and a test matching on wording
    would pass while the code refused for the wrong reason."""

    #: §9.1's explicit rule. The one that must never be silently treated as "maybe".
    NO_PREDICTION_OVER_PRODUCES = "NO_PREDICTION_OVER_PRODUCES"
    #: Every declared outcome would leave the verdict exactly where it is.
    NO_OUTCOME_CHANGES_THE_DECISION = "NO_OUTCOME_CHANGES_THE_DECISION"
    #: The prediction names a space version that was not supplied.
    OUTCOME_SPACE_UNRESOLVED = "OUTCOME_SPACE_UNRESOLVED"


@dataclass(frozen=True)
class SufficiencyResult:
    """Whether an action could change the verdict, and the evidence for the answer.

    `baseline` and `discriminating_outcomes` are carried rather than reduced to a boolean because
    "this measurement is worth doing" is a claim a human will be asked to fund. The outcomes that
    would move the belief, and what they would move it to, are the argument.
    """

    sufficient: bool
    baseline: TransitionDecision
    #: Outcome -> the decision it would produce, for each outcome that differs from `baseline`.
    #: Sorted by outcome so two runs compare equal (§26: identical inputs, identical result).
    discriminating_outcomes: tuple[tuple[str, TransitionDecision], ...] = ()
    reason: InsufficientReason | None = None
    #: §9.1 clauses this run did **not** evaluate. Non-empty means the answer is narrower than
    #: §9.1's, and a caller that treats it as the whole rule is overclaiming.
    unevaluated_clauses: tuple[str, ...] = ()


#: Clauses of §9.1 that M0b does not evaluate. See the module docstring.
_DEFERRED_CLAUSES = (
    "plausible(y) clauses 3-4: DomainPack ValidationReport and Capability feasibility "
    "(VER-004, M3)",
    "y resolves a blocking Conflict: a resolution is a durable human record (v3.3-a14), not an "
    "inference",
)


def evaluate_sufficiency(
    *,
    policy: TransitionPolicy,
    hypothesis: HypothesisView,
    admitted_relations: Sequence[RelationJudgment],
    candidate_to_state: BeliefState,
    action_produces: str,
    predictions: Sequence[Prediction],
    outcome_spaces: Sequence[OutcomeSpace],
    authority_policy: AuthorityPolicy | None = None,
    condition_matches: Sequence[ConditionMatch] = (),
    independence_summary: IndependenceSummary | None = None,
) -> SufficiencyResult:
    """Would any declared outcome of this action change the transition verdict?

    SIDE-EFFECT FREE, because everything it touches is. It takes no store, persists nothing and
    calls only `evaluate` and `evaluate_hypothetical` -- both of which are methods on a frozen
    model with no I/O capability at all.

    `predictions` are **supplied**, and that is §17.5.1's rule rather than an API convenience:
    hypothetical relations "MUST be instantiated from declared Predictions, never invented by the
    planner or by an LLM at planning time". A function that accepted free-form outcomes and built
    relations for them would be the invention the sentence forbids, so the only way in is a typed
    `Prediction` already bound to a versioned space.
    """
    independence = independence_summary or IndependenceSummary()
    baseline = policy.evaluate(
        hypothesis,
        tuple(admitted_relations),
        authority_policy,
        tuple(condition_matches),
        independence,
        candidate_to_state,
    )

    # §9.1's explicit rule, checked first and answered with its own reason code. "No prediction"
    # is not "we could not tell": the section says absence of a declared prediction is not evidence
    # of discriminative power, so this is a definite NOT sufficient rather than an unknown.
    relevant = tuple(
        prediction
        for prediction in sorted(predictions, key=lambda p: p.prediction_id)
        if prediction.observable_ref == action_produces
        and prediction.hypothesis_id == hypothesis.hypothesis_id
    )
    if not relevant:
        return SufficiencyResult(
            sufficient=False,
            baseline=baseline,
            reason=InsufficientReason.NO_PREDICTION_OVER_PRODUCES,
            unevaluated_clauses=_DEFERRED_CLAUSES,
        )

    spaces = {(space.outcome_space_id, space.version): space for space in outcome_spaces}
    discriminating: list[tuple[str, TransitionDecision]] = []
    for prediction in relevant:
        space = spaces.get((prediction.outcome_space_id, prediction.outcome_space_version))
        if space is None:
            # Fail closed. Evaluating against a space nobody supplied would mean deciding
            # membership by assumption, and VER-004's whole point is that membership is declared.
            return SufficiencyResult(
                sufficient=False,
                baseline=baseline,
                reason=InsufficientReason.OUTCOME_SPACE_UNRESOLVED,
                unevaluated_clauses=_DEFERRED_CLAUSES,
            )
        if not space.admits(prediction.expected_outcome):
            # Admission should have caught this; reaching it means the prediction was never bound.
            continue

        hypothetical = prediction.hypothetical_relations(project_id=hypothesis.project_id)
        projected = policy.evaluate_hypothetical(
            hypothesis,
            tuple(admitted_relations),
            hypothetical,
            authority_policy,
            tuple(condition_matches),
            independence,
            candidate_to_state,
        )
        if projected.outcome is not baseline.outcome:
            discriminating.append((prediction.expected_outcome, projected))

    ordered = tuple(sorted(discriminating, key=lambda pair: pair[0]))
    return SufficiencyResult(
        sufficient=bool(ordered),
        baseline=baseline,
        discriminating_outcomes=ordered,
        reason=None if ordered else InsufficientReason.NO_OUTCOME_CHANGES_THE_DECISION,
        unevaluated_clauses=_DEFERRED_CLAUSES,
    )


__all__ = [
    "InsufficientReason",
    "SufficiencyResult",
    "evaluate_sufficiency",
]
