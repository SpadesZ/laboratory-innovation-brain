"""§17.19.1's `ReviewItem`, minimum schema (EPI-004).

A SHARED FOUNDATION, AND NOT UX-005. This is the same object UX-005 requires for NEEDS_REVIEW, but
T-UX-005's pass condition is about ReviewQueue *depth* and measurably changed human-review
Capability availability, and neither exists yet. What lands here is only what T-EPI-004 needs: an
INCOMPARABLE authority comparison must auto-create a `ReviewItem(subject_type=AUTHORITY_CONFLICT)`
whose `subject_id` is a conflict_id, and a belief must stay blocked until that review resolves.

So the subject-type vocabulary below is deliberately narrow. §17.19.1 admits more kinds, and each
arrives with the requirement that needs it -- a permissive enum now would accept rows no code path
reviews, which reads as support for a feature that is not there.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel


class ReviewSubjectType(StrEnum):
    """The subject kinds this slice supports.

    §17.19.3: `ReviewItem(subject_type=CONFLICT | AUTHORITY_CONFLICT).subject_id` is a
    **conflict_id**. `AUTHORITY_CONFLICT` is the one EPI-004 creates, from an INCOMPARABLE
    comparison; `CONFLICT` is the general case the same table serves.
    """

    CONFLICT = "CONFLICT"
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"


class ReviewStatus(StrEnum):
    """§17.19.1's six."""

    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


#: The statuses under which a review is still outstanding.
#:
#: A human has not yet answered, so nothing it gates may proceed. `ASSIGNED` counts: somebody
#: having picked the task up is not somebody having finished it -- the same distinction
#: `UNDER_REVIEW` draws for a conflict, and the same mistake it would be to treat as cleared.
OUTSTANDING_REVIEW_STATUSES: frozenset[ReviewStatus] = frozenset(
    {ReviewStatus.QUEUED, ReviewStatus.ASSIGNED}
)


class ReviewItem(CoreModel):
    """One queued human decision (§17.19.1, minimum schema)."""

    review_id: str
    project_id: str
    subject_type: ReviewSubjectType
    subject_id: str
    stakes: str
    reason: str
    trace_id: str
    created_at: dt.datetime

    status: ReviewStatus = ReviewStatus.QUEUED
    episode_id: str | None = None
    required_authority: str | None = None
    required_role: str | None = None
    assigned_actor_id: str | None = None
    decision_ref: str | None = None
    estimated_human_minutes: int = Field(default=0, ge=0)
    due_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None

    #: The `ReviewQueuePolicy` version that priced this item's `due_at` and `expires_at` (`011e`).
    #:
    #: CARRIED ON THE ITEM, NOT LOOKED UP BY PROJECT, AND `v3.3-a15` IS EXPLICIT ABOUT WHY: an
    #: expiry re-interpreted under a policy the reviewer never saw is not the deadline they were
    #: given. A lab that tightens its SLA must not thereby retro-expire everything already queued,
    #: so the automatic sweep reads these two fields and `review_expire` refuses a mismatch.
    #:
    #: Optional on the model and required by the database, which is the usual split: `011e`'s
    #: trigger refuses an INSERT without them, and leaving them optional here keeps a `ReviewItem`
    #: constructible *before* it has been priced -- which is exactly what `price_review` does.
    queue_policy_id: str | None = None
    queue_policy_version: str | None = None

    @model_validator(mode="after")
    def _an_assigned_review_names_its_reviewer(self) -> Self:
        """`ASSIGNED` without an actor is a task nobody owns that looks owned.

        The queue would count it as picked up and no human would be looking at it, which is worse
        than leaving it QUEUED: a QUEUED item is visibly waiting.
        """
        if self.status is ReviewStatus.ASSIGNED and self.assigned_actor_id is None:
            raise ValueError(
                f"review {self.review_id} is ASSIGNED with no assigned_actor_id. The queue would "
                "count it as picked up while nobody is looking at it -- QUEUED is the honest "
                "state for an unowned task"
            )
        return self

    @property
    def is_outstanding(self) -> bool:
        """Whether a human still owes an answer. See `OUTSTANDING_REVIEW_STATUSES`."""
        return self.status in OUTSTANDING_REVIEW_STATUSES


__all__ = [
    "OUTSTANDING_REVIEW_STATUSES",
    "ReviewItem",
    "ReviewStatus",
    "ReviewSubjectType",
]
