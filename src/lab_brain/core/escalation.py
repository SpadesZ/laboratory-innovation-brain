"""INCOMPARABLE authority becomes a typed Conflict and a queued ReviewItem (EPI-004).

§8.2.1 states the flow and stops short of saying who performs it:

    If any required AuthorityPolicy.compare() result is INCOMPARABLE:
      -> outcome = NEED_HUMAN_REVIEW
      -> auto-create ReviewItem(subject_type=AUTHORITY_CONFLICT,
                                subject_id=hypothesis_id,
                                stakes=hypothesis.stakes)
      -> no BeliefRevisionEvent may promote/reject until the review resolves

WHY THE POLICY DOES NOT DO IT. `TransitionPolicy.evaluate` is pure: no clock, no I/O, no
repository read, because `v3.3-a12` requires a stored Decision to re-derive from its snapshot and
a function that wrote rows could not be replayed. So `evaluate` returns a `ReviewItemSpec`
describing the review, and this module is the impure seam that acts on it. Until now nothing did,
and T-EPI-004's "auto-creates ReviewItem(AUTHORITY_CONFLICT)" was unmet -- recorded as such rather
than claimed.

ONE DISCREPANCY WITH §8.2.1, RESOLVED THE WAY §17.19.3 REQUIRES. §8.2.1 says the ReviewItem's
`subject_id` is the *hypothesis_id*; §17.19.3 says
`ReviewItem(subject_type=CONFLICT | AUTHORITY_CONFLICT).subject_id` is a **conflict_id**. Both are
normative and they disagree. §17.19.3 is the more specific rule -- it is the Conflict contract, and
it is the one that makes `unresolved_conflicts[]` and `blocking_conflict_policy` share a single
object -- so the review names the conflict, and the conflict names the hypothesis in
`subject_refs`. The hypothesis is therefore still reachable in one hop, which is the property
§8.2.1 was after. Recorded here rather than silently chosen.
"""

from __future__ import annotations

import datetime as dt

from lab_brain.core.models.conflict import (
    Conflict,
    ConflictResolutionStatus,
    ConflictType,
)
from lab_brain.core.models.review import ReviewItem, ReviewStatus, ReviewSubjectType
from lab_brain.core.models.transition import (
    HypothesisView,
    TransitionDecision,
    TransitionOutcome,
    TransitionReason,
)


class EscalationRefused(RuntimeError):
    """An escalation was asked for that the decision does not justify.

    Raised rather than returned, for the reason `BeliefTransitionRefused` is: the caller is
    proposing to queue human work on a premise that is not there, and a return value would let it
    continue.
    """


def authority_conflict_for(
    *,
    conflict_id: str,
    decision: TransitionDecision,
    hypothesis: HypothesisView,
    detected_at: dt.datetime,
    detected_by_actor_or_slot: str,
    trace_id: str,
    episode_id: str | None = None,
    supporting_refs: tuple[str, ...] = (),
) -> Conflict:
    """Build the `AUTHORITY_CONFLICT` an INCOMPARABLE comparison implies.

    Refuses any decision that is not NEED_HUMAN_REVIEW for AUTHORITY_INCOMPARABLE. The check is
    not defensive tidiness: a conflict manufactured from a DENY would block a hypothesis whose
    authority question was actually answered, and blocking is the expensive direction -- it queues
    human work and freezes a belief.

    `blocking=True` is not configurable here. §8.2.1 says no event may promote *or reject* until
    the review resolves, so a non-blocking AUTHORITY_CONFLICT would be a record of the escalation
    that permitted the transition anyway.
    """
    if decision.outcome is not TransitionOutcome.NEED_HUMAN_REVIEW:
        raise EscalationRefused(
            f"decision for {hypothesis.hypothesis_id} is {decision.outcome.value}, not "
            "NEED_HUMAN_REVIEW. An AUTHORITY_CONFLICT built from a decision that did not escalate "
            "would block a hypothesis whose authority question was answered"
        )
    if decision.reason_code is not TransitionReason.AUTHORITY_INCOMPARABLE:
        raise EscalationRefused(
            f"decision for {hypothesis.hypothesis_id} escalated for "
            f"{decision.reason_code.value}, not AUTHORITY_INCOMPARABLE. §17.19.3's conflict_type "
            "vocabulary is closed and this conflict would be mistyped -- a blocking policy that "
            "listed AUTHORITY_CONFLICT would then gate on a condition that is not one"
        )

    return Conflict(
        conflict_id=conflict_id,
        project_id=hypothesis.project_id,
        conflict_type=ConflictType.AUTHORITY_CONFLICT,
        subject_refs=(hypothesis.hypothesis_id,),
        supporting_refs=supporting_refs,
        blocking=True,
        detected_at=detected_at,
        detected_by_actor_or_slot=detected_by_actor_or_slot,
        trace_id=trace_id,
        episode_id=episode_id,
        resolution_status=ConflictResolutionStatus.OPEN,
    )


def review_item_for(
    *,
    review_id: str,
    conflict: Conflict,
    decision: TransitionDecision,
    created_at: dt.datetime,
    estimated_human_minutes: int = 0,
) -> ReviewItem:
    """Build the queued `ReviewItem(AUTHORITY_CONFLICT)` for a conflict.

    `subject_id` is the **conflict_id**, per §17.19.3 -- see the module docstring for why that and
    not the hypothesis_id, and what is preserved by the choice.

    `stakes` and `required_authority` come from the decision's own `ReviewItemSpec` and
    `required_authority_gap` rather than from the caller. A reviewer needs to know which threshold
    could not be answered, and a caller re-deriving it would be re-deciding the thing the policy
    already decided.
    """
    if conflict.conflict_type is not ConflictType.AUTHORITY_CONFLICT:
        raise EscalationRefused(
            f"conflict {conflict.conflict_id} is a {conflict.conflict_type.value}; this builds "
            "the AUTHORITY_CONFLICT review and mistyping it would put the item in front of a "
            "reviewer asked to answer the wrong question"
        )
    spec = decision.review_item_spec
    if spec is None:
        raise EscalationRefused(
            f"decision for {conflict.conflict_id} carries no review_item_spec, so there is "
            "nothing to queue. §8.2.1 populates it exactly when outcome is NEED_HUMAN_REVIEW"
        )

    return ReviewItem(
        review_id=review_id,
        project_id=conflict.project_id,
        subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
        subject_id=conflict.conflict_id,
        stakes=spec.stakes,
        reason=spec.reason.value,
        trace_id=conflict.trace_id,
        episode_id=conflict.episode_id,
        required_authority=decision.required_authority_gap,
        created_at=created_at,
        status=ReviewStatus.QUEUED,
        estimated_human_minutes=estimated_human_minutes,
    )


__all__ = [
    "EscalationRefused",
    "authority_conflict_for",
    "review_item_for",
]
