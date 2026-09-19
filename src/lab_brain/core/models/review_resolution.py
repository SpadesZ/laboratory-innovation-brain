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
from lab_brain.core.models.governance_event import ResolutionEventKind
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
    #:
    #: `v3.3-a15` made it **optional-in-shape and still required-in-substance**: exactly one of
    #: this and `governance_event_id` must be set, and which one is `resolution_event_kind`'s
    #: answer. Every human resolution is still a belief revision.
    belief_revision_event_id: str | None = None

    #: `v3.3-a15`: the `GovernanceEvent` an automatic expiry produced. Set only when
    #: `resolution_event_kind` is GOVERNANCE, which §17.19.1 permits for EXPIRED and nothing else.
    governance_event_id: str | None = None

    #: Which kind of event closed this. Defaults to BELIEF_REVISION because every resolution that
    #: existed before `v3.3-a15` was one, and because a default of GOVERNANCE would make the
    #: exceptional path the easy one.
    resolution_event_kind: ResolutionEventKind = ResolutionEventKind.BELIEF_REVISION

    @property
    def resolution_event_id(self) -> str:
        """The canonical closure reference, whichever kind it is.

        A property rather than a field, mirroring the `GENERATED ALWAYS AS` column `011f` adds: a
        stored copy could disagree with the typed column it summarises, and the pair
        `(kind, id)` is what §17.19.3 requires the Conflict to match.
        """
        reference = self.belief_revision_event_id or self.governance_event_id
        assert reference is not None  # the validator below makes this unreachable
        return reference

    @model_validator(mode="after")
    def _exactly_one_event_matching_the_declared_kind(self) -> Self:
        """The model half of `011f`'s two CHECKs, and it says the same thing.

        Both exist for the reason this project has written down repeatedly: a model guard holds for
        callers who go through the model, and a migration or a support script writes SQL. This one
        catches it earlier and explains it; the CHECK is the one that actually holds.
        """
        if self.resolution_event_kind is ResolutionEventKind.BELIEF_REVISION:
            if self.belief_revision_event_id is None or self.governance_event_id is not None:
                raise ValueError(
                    f"resolution {self.resolution_id} is a BELIEF_REVISION closure and must carry "
                    "exactly a belief_revision_event_id. §25.3 EPI-006 requires every status that "
                    "stops a conflict blocking to record the event that closed it"
                )
        elif self.governance_event_id is None or self.belief_revision_event_id is not None:
            raise ValueError(
                f"resolution {self.resolution_id} is a GOVERNANCE closure and must carry exactly a "
                "governance_event_id. A governance event records that nobody decided; pairing it "
                "with a belief revision would claim both at once"
            )

        # §17.19.1 as amended: GOVERNANCE is permitted for exactly one outcome. APPROVED,
        # CORRECTED and REJECTED are decisions somebody made, and a GovernanceEvent is the record
        # that nobody did -- so closing a human decision against one would misattribute it.
        if (
            self.resolution_event_kind is ResolutionEventKind.GOVERNANCE
            and self.outcome is not ReviewOutcome.EXPIRED
        ):
            raise ValueError(
                f"resolution {self.resolution_id} closes review {self.review_id} as "
                f"{self.outcome.value} against a GovernanceEvent. v3.3-a15 permits GOVERNANCE only "
                "for EXPIRED: the other three outcomes are decisions a human made"
            )
        return self

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


__all__ = ["ResolutionEventKind", "ReviewOutcome", "ReviewResolution"]
