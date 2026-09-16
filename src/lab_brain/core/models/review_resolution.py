"""The durable record §17.19.1's `decision_ref` points at (`v3.3-a14`).

WHY THIS TYPE EXISTS. `decision_ref` appeared once in §17.19.1's field list, optional, with no
prose saying what it referenced or when it was required -- so "no BeliefRevisionEvent may
promote/reject until the review resolves" (§8.2.1) had no definition to enforce. P11's own
end-to-end test proved that: it left the `ReviewItem` at `QUEUED` and closed the conflict against
a pre-existing, unrelated `BeliefRevisionEvent`. `v3.3-a14` defines the reference, and this is it.

RATIONALE IS FREE TEXT AND THAT IS DELIBERATE. It is a human's reasoning -- the one field in this
area that should not be a closed vocabulary. No gate reads it, which is what keeps it honest:
a field a policy consulted would become a place to encode a verdict, and AGT-016 puts verdicts in
policies rather than prose.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.review import ReviewStatus


class ReviewOutcome(StrEnum):
    """The terminal `ReviewStatus` values a resolution can put a review into.

    A separate enum rather than reusing `ReviewStatus` because the two outstanding values are not
    outcomes: a resolution that "resolved" a review to QUEUED is not a resolution, and making that
    unrepresentable is cheaper than checking for it.
    """

    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    def as_review_status(self) -> ReviewStatus:
        """The `ReviewStatus` this outcome leaves the review in."""
        return ReviewStatus(self.value)


class ReviewResolution(CoreModel):
    """How one `ReviewItem` was resolved, and what it produced."""

    resolution_id: str
    review_id: str
    project_id: str
    outcome: ReviewOutcome
    resolved_by_actor_id: str
    resolved_at: dt.datetime
    rationale: str

    #: The belief revision event this resolution produced. **Required.**
    #:
    #: The first draft made this optional, reasoning that a REJECTED review might settle nothing.
    #: A test written against that draft then tried to close a conflict as
    #: ACCEPTED_AS_OPEN_QUESTION with no event, and the database refused -- correctly. The P10
    #: ruling is that *every* status which stops a conflict blocking carries its closure event,
    #: with no per-status exemption, because a per-status exemption is exactly how the
    #: terminal-state hole appeared. Unblocking a belief is itself a recordable act (§6.18): "the
    #: reviewer decided to proceed with the disagreement on the record" needs an event just as
    #: much as "the reviewer settled it".
    belief_revision_event_id: str

    @model_validator(mode="after")
    def _a_rationale_is_required_in_substance_not_only_in_shape(self) -> Self:
        """Blank rationale is refused.

        A required field satisfied by an empty string is an optional field with extra steps, and
        this is the only record of why a human unblocked a belief.
        """
        if not self.rationale.strip():
            raise ValueError(
                f"resolution {self.resolution_id} records no rationale. It is the only account of "
                "why a human lifted a block, and an empty one makes the review unauditable while "
                "looking complete"
            )
        return self

    @property
    def settled_the_question(self) -> bool:
        """Whether the reviewer settled the disagreement rather than recording it as open.

        Read off the *outcome*, not off the presence of an event -- every resolution produces one.
        `APPROVED` and `CORRECTED` mean the question was answered; `REJECTED` and `EXPIRED` mean
        the conflict is closed for a different reason, which the conflict's own status then says.
        """
        return self.outcome in (ReviewOutcome.APPROVED, ReviewOutcome.CORRECTED)


__all__ = ["ReviewOutcome", "ReviewResolution"]
