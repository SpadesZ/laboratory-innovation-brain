"""§17.19.3's `Conflict` as a first-class typed record (EPI-006).

    §17.19.3  Conflict 是 `blocking_conflict_policy`、`unresolved_conflicts[]` 與
              `ReviewItem(CONFLICT)` 共用的唯一物件。衝突不得只以字串或散落旗標表示。

WHAT THIS REPLACES. Until now `HypothesisView.blocking_conflict_ids` was a tuple of opaque ids the
caller had already decided were blocking, and `TransitionPolicy.blocking_conflict_policy` was a
list of `conflict_type` strings that nothing matched against. So the policy honoured whichever ids
it was handed and its declared *types* were decoration -- the caller decided what blocked, which
is precisely the arrangement §17.19.3 forbids when it says a conflict must not be "只以字串或散落
旗標表示". A caller that forgot to populate the ids got an ALLOW.

THE VOCABULARY IS CLOSED, AND THAT IS THE POINT. `conflict_type` is an enum, not a string. A
free-text conflict type cannot be matched against a policy's `blocking_conflict_policy`, and an
LLM-authored one would put the decision back where AGT-016 forbids it: a model deciding what
counts as blocking is a model deciding belief. Detection may be automated; the *type* has to be
one of seven declared kinds, and a new kind is a spec amendment.

RESOLUTION IS EVENT-SOURCED. A conflict never becomes RESOLVED because someone set a field:
§25.3's EPI-006 requires that "closing a Conflict MUST record a resolution event", so RESOLVED
without a `resolution_event_id` is refused at construction. Deleting one is not modelled at all --
there is no delete, for the same reason `BeliefEventStore` has none.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel


class ConflictType(StrEnum):
    """§17.19.3's seven kinds. Closed, because `blocking_conflict_policy` matches against it."""

    #: Missing or contradictory provenance chain.
    PROVENANCE_CONFLICT = "PROVENANCE_CONFLICT"
    #: `ConditionMatch` is INCOMPATIBLE or UNKNOWN at a required gate.
    CONDITION_CONFLICT = "CONDITION_CONFLICT"
    #: `BackendValidity` insufficient for the claimed authority.
    VALIDITY_CONFLICT = "VALIDITY_CONFLICT"
    #: `AuthorityPolicy.compare` returned INCOMPARABLE -- the EPI-004 link.
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    #: Simulated and measured evidence disagree. §10.6 forbids flattening this one.
    SIM_TO_REAL_CONFLICT = "SIM_TO_REAL_CONFLICT"
    #: A supporting source was retracted or errata-flagged.
    SOURCE_RETRACTION_CONFLICT = "SOURCE_RETRACTION_CONFLICT"
    #: DEPENDENCE_UNKNOWN blocks a required independence threshold.
    INDEPENDENCE_UNRESOLVED = "INDEPENDENCE_UNRESOLVED"


class ConflictResolutionStatus(StrEnum):
    """§17.19.3. Only the first two leave a conflict capable of blocking."""

    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    #: Recorded as a known open question rather than closed. §23.4's honest third option: the
    #: conflict is real, nobody is going to resolve it now, and the record says so.
    ACCEPTED_AS_OPEN_QUESTION = "ACCEPTED_AS_OPEN_QUESTION"
    EXPIRED = "EXPIRED"


#: The statuses under which a conflict can still stop a transition.
#:
#: This set is the **single** definition of "still blocking", and `Conflict`'s validator derives
#: the closure-event requirement from its complement. Keeping one definition is deliberate: the
#: P10 audit found the two had been written separately, so `EXPIRED` unblocked a conflict without
#: requiring the event that `RESOLVED` required.
#:
#: `UNDER_REVIEW` is included deliberately: a human looking at a conflict has not resolved it, and
#: treating "someone is on it" as cleared is how a blocking conflict stops blocking exactly when
#: it matters most. `ACCEPTED_AS_OPEN_QUESTION` is *excluded* deliberately too -- that status is a
#: decision to proceed with the conflict on the record, which is the one case where the answer is
#: not "wait".
UNRESOLVED_CONFLICT_STATUSES: frozenset[ConflictResolutionStatus] = frozenset(
    {ConflictResolutionStatus.OPEN, ConflictResolutionStatus.UNDER_REVIEW}
)


class Conflict(CoreModel):
    """One typed conflict (§17.19.3).

    Frozen like every other record on the scientific path: a conflict's resolution is a new
    record derived from an event, not a mutation of this one.
    """

    conflict_id: str
    project_id: str
    conflict_type: ConflictType
    #: Hypothesis / attestation / observation / relation ids this conflict is about.
    subject_refs: tuple[str, ...] = Field(min_length=1)
    #: Consumed by `TransitionPolicy.blocking_conflict_policy`.
    blocking: bool
    detected_at: dt.datetime
    #: Who or what detected it. An actor id or an LLM slot name -- §17.19.3 allows either, and
    #: recording which is what makes a conflict detected by a model auditable rather than
    #: indistinguishable from one a human raised.
    detected_by_actor_or_slot: str
    trace_id: str

    supporting_refs: tuple[str, ...] = ()
    episode_id: str | None = None
    #: The `ReviewItem` this was escalated to, when it was.
    review_id: str | None = None

    resolution_status: ConflictResolutionStatus = ConflictResolutionStatus.OPEN
    resolved_at: dt.datetime | None = None
    resolution_event_id: str | None = None

    @model_validator(mode="after")
    def _closing_requires_an_event(self) -> Self:
        """§25.3 EPI-006: "closing a Conflict MUST record a resolution event".

        THE P10 AUDIT FOUND THIS APPLIED TO ONE STATUS INSTEAD OF THREE. The earlier version
        required a `resolution_event_id` only for `RESOLVED`, while `blocks_transitions` treated
        `EXPIRED` and `ACCEPTED_AS_OPEN_QUESTION` as not-blocking too. So a blocking conflict
        could be unblocked by setting its status to `EXPIRED` with no event and no timestamp --
        which is precisely "只改 enum 就解除 block", and precisely what the obligation exists to
        prevent. The rule is now stated over the *consequence* rather than over one enum member:
        **any status that stops a conflict blocking must carry the event that put it there.**

        Derived from `UNRESOLVED_CONFLICT_STATUSES` rather than listed separately, so adding an
        eighth status cannot quietly create a fourth unblocking state with no closure
        requirement -- the two definitions cannot drift because there is only one.

        Enforced at construction rather than in a service method, so there is no code path that
        produces an unblocked conflict without its closure event, including a support script
        building the model directly.
        """
        closes_the_block = self.resolution_status not in UNRESOLVED_CONFLICT_STATUSES

        if closes_the_block:
            if self.resolution_event_id is None:
                raise ValueError(
                    f"conflict {self.conflict_id} is {self.resolution_status.value} with no "
                    "resolution_event_id. That status stops the conflict blocking, and a conflict "
                    "does not stop blocking because a field was set: closing it must record the "
                    "event that closed it, or the reason a belief became promotable again is "
                    "unrecoverable (§25.3 EPI-006)"
                )
            if self.resolved_at is None:
                raise ValueError(
                    f"conflict {self.conflict_id} is {self.resolution_status.value} with no "
                    "resolved_at; an as_of replay cannot place the closure in time"
                )
        elif self.resolved_at is not None or self.resolution_event_id is not None:
            raise ValueError(
                f"conflict {self.conflict_id} is {self.resolution_status.value} but carries "
                "closure details. A conflict that is still open must not look half-closed -- a "
                "reader checking `resolution_event_id` would conclude it had been dealt with"
            )

        return self

    @property
    def is_unresolved(self) -> bool:
        """Whether this conflict can still stop a transition.

        `UNDER_REVIEW` counts. See `UNRESOLVED_CONFLICT_STATUSES` for why that is deliberate.
        """
        return self.resolution_status in UNRESOLVED_CONFLICT_STATUSES

    @property
    def blocks_transitions(self) -> bool:
        """Blocking *and* unresolved. Either alone is not enough.

        A resolved blocking conflict is history, and an unresolved non-blocking one is a recorded
        disagreement that the domain has said does not gate belief. Conflating them would either
        freeze a project permanently or let the flag mean nothing.
        """
        return self.blocking and self.is_unresolved


__all__ = [
    "UNRESOLVED_CONFLICT_STATUSES",
    "Conflict",
    "ConflictResolutionStatus",
    "ConflictType",
]
