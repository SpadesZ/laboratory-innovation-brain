"""The ReviewQueue as a priced Capability, not an unbounded inbox (OPS-002, §14.4 / §14.4.1).

    §14.4    Human ReviewQueue 必須有 stakes、created_at、SLA/expiry policy 與 queue capacity，
             避免所有 uncertain item 永久卡在 PENDING。
    §14.4.1  Human review 是一個 **Capability**，不是無限免費資源。
             HumanReviewCapability.availability <- ReviewQueue capacity + actor schedule

THE SENTENCE THIS MODULE EXISTS FOR is §14.4.1's second clause: human review is a Capability and
not an infinite free resource. A planner that could queue unlimited reviews would rank "ask a
human" as costless and choose it every time -- and the cost it is ignoring is a professor's
attention, which is the one input a lab cannot buy more of. So the queue reports depth against a
declared capacity, and a full queue makes human review *unavailable* rather than merely slow.

CAPACITY DOES NOT REFUSE AN ESCALATION, AND THE ASYMMETRY IS DELIBERATE. §26 says depth and
capacity change *availability*; it does not say a full queue rejects work. It must not, either: a
blocking conflict whose review was refused would sit OPEN with nobody assigned -- still blocking
the belief, and now invisible to the very queue that is supposed to report the backlog. So
escalation always succeeds and always prices the item, and the planner reads `available` before it
decides to spend a human.

WHAT `expire` DOES NOT DO, WHICH IS THE PART WORTH READING TWICE. It does not set
`status = 'EXPIRED'`. §17.19.1 as amended by `v3.3-a14` makes EXPIRED a *terminal* review status,
and migrations `011c`/`011d` require every terminal review to carry a durable `ReviewResolution`
whose linked Conflict is terminal against that resolution's own event. An expiry is therefore a
real governance act with a real record, not a status flip -- which is correct: letting a review
lapse *unblocks a belief nobody adjudicated*, and §6.18 says unblocking is itself recordable. The
closure event is a required argument for exactly that reason. There is deliberately no convenience
overload that invents one.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.conflict import ConflictResolutionStatus
from lab_brain.core.models.review import OUTSTANDING_REVIEW_STATUSES, ReviewItem
from lab_brain.core.models.review_resolution import ReviewOutcome, ReviewResolution


class ReviewQueueError(RuntimeError):
    """An item could not be priced, or an expiry was asked for that the policy does not justify."""


class ReviewQueuePolicy(CoreModel):
    """§14.4's declared capacity, SLA and expiry for one project's queue.

    VERSIONED, AND THE VERSION IS RECORDED ON EVERY ITEM IT PRICES. An SLA is a governance decision
    a lab makes and revises; a review that expired under a 48-hour rule must not look wrong because
    the lab later moved to 72. Same shape as `v3.3-a11` putting `policy_version` on the event.

    `capacity = 0` is legal and means "this project is not accepting human review right now". That
    it is expressible at all is the `v3.3-a10` lesson about budget caps: absent and zero are two
    different facts, and a field where omission means "no limit" cannot say the second one.
    """

    policy_id: str
    version: str
    project_id: str
    capacity: int = Field(ge=0)
    default_sla_minutes: int = Field(gt=0)
    default_expiry_minutes: int = Field(gt=0)
    #: stakes -> minutes. Free-text keys because §17.19.1 does not enumerate `stakes`, and core
    #: must not fix a vocabulary the domain owns.
    sla_minutes_by_stakes: dict[str, int] = Field(default_factory=dict)
    expiry_minutes_by_stakes: dict[str, int] = Field(default_factory=dict)
    #: §14.4.1's "actor schedule", as the one number a planner can actually use.
    reviewer_minutes_per_day: int = Field(default=0, ge=0)
    effective_from: dt.datetime
    active: bool = True

    @model_validator(mode="after")
    def _nothing_expires_before_it_is_due(self) -> Self:
        """An item that expires before its SLA closes unanswered while reporting no breach.

        Checked for the defaults and for every declared stakes value, because a per-stakes override
        is exactly where the inversion would go unnoticed -- the defaults look right and one class
        of item quietly self-closes.
        """
        if self.default_expiry_minutes < self.default_sla_minutes:
            raise ValueError(
                f"queue policy {self.policy_id}@{self.version} expires items after "
                f"{self.default_expiry_minutes} minutes but marks them due after "
                f"{self.default_sla_minutes}. Every item would close unanswered while the queue "
                "reported no SLA breach at all"
            )
        inverted = sorted(
            stakes
            for stakes in {*self.sla_minutes_by_stakes, *self.expiry_minutes_by_stakes}
            if self.expiry_minutes_for(stakes) < self.sla_minutes_for(stakes)
        )
        if inverted:
            raise ValueError(
                f"queue policy {self.policy_id}@{self.version} prices {inverted} to expire before "
                "they are due; those items would self-close and never appear as breaches"
            )
        return self

    def sla_minutes_for(self, stakes: str) -> int:
        """Per-stakes, then the declared default. There is deliberately no third fallback."""
        return self.sla_minutes_by_stakes.get(stakes, self.default_sla_minutes)

    def expiry_minutes_for(self, stakes: str) -> int:
        return self.expiry_minutes_by_stakes.get(stakes, self.default_expiry_minutes)

    def due_at(self, *, stakes: str, created_at: dt.datetime) -> dt.datetime:
        return created_at + dt.timedelta(minutes=self.sla_minutes_for(stakes))

    def expires_at(self, *, stakes: str, created_at: dt.datetime) -> dt.datetime:
        return created_at + dt.timedelta(minutes=self.expiry_minutes_for(stakes))


@dataclass(frozen=True)
class HumanReviewCapability:
    """§9.5's Capability descriptor, for the one Capability that is a person (§14.4.1).

    `estimated_human_minutes` is the **backlog**, not the cost of one review: §14.4.1 feeds queue
    depth into the Capability, and what a planner needs to know before adding work is how much
    human time is already committed. A descriptor reporting only the marginal item would say human
    review costs thirty minutes whether the queue holds one item or forty.
    """

    project_id: str
    available: bool
    earliest_available_at: dt.datetime
    #: Total outstanding reviewer minutes already queued.
    estimated_human_minutes: int
    depth: int
    capacity: int
    #: Outstanding items already past their SLA. Reported separately from `depth` because a queue
    #: that is within capacity and entirely overdue is not a healthy queue, and one number hides it.
    breached: int = 0
    policy_ref: str | None = None


@runtime_checkable
class ReviewItemSource(Protocol):
    """The reads a queue needs. Structural, so the SQL store satisfies it without knowing."""

    def outstanding(self, project_id: str) -> tuple[ReviewItem, ...]: ...


@runtime_checkable
class ResolutionSink(Protocol):
    """The locked `011c` resolve-and-close path. Expiry goes through it and nothing else."""

    def resolve_and_close_conflict(
        self, *, resolution: ReviewResolution, conflict_status: ConflictResolutionStatus
    ) -> ReviewResolution: ...


class ReviewQueue:
    """Depth, availability and expiry for one project's human ReviewQueue."""

    def __init__(self, *, policy: ReviewQueuePolicy, reviews: ReviewItemSource) -> None:
        self._policy = policy
        self._reviews = reviews

    @property
    def policy(self) -> ReviewQueuePolicy:
        return self._policy

    def outstanding(self, project_id: str) -> tuple[ReviewItem, ...]:
        """Queued and assigned items, oldest first.

        `ASSIGNED` counts. Somebody having picked a task up is not somebody having finished it, and
        a queue that stopped counting assigned items would report depth 0 while forty reviews sat
        half-done -- the same distinction `v3.3-a14` draws for the outstanding-review invariant.
        """
        return tuple(
            sorted(
                (
                    item
                    for item in self._reviews.outstanding(project_id)
                    if item.status in OUTSTANDING_REVIEW_STATUSES
                ),
                key=lambda item: (item.created_at, item.review_id),
            )
        )

    def depth(self, project_id: str) -> int:
        return len(self.outstanding(project_id))

    def overdue(self, project_id: str, now: dt.datetime) -> tuple[ReviewItem, ...]:
        """Outstanding items past their **expiry**, in the order they will be swept.

        Distinct from breached, which is past the *SLA*. A breached item is late and still worth a
        human's answer; an expired one is what §14.4 says must not park in PENDING.
        """
        return tuple(
            item
            for item in self.outstanding(project_id)
            if item.expires_at is not None and item.expires_at <= now
        )

    def capability(self, project_id: str, now: dt.datetime) -> HumanReviewCapability:
        """§14.4.1: queue depth and capacity become Capability availability.

        `earliest_available_at` is computed, not guessed, and the rule is stated rather than tuned:

        * room in the queue -> `now`. Work can be accepted immediately.
        * full -> the earliest `due_at` among outstanding items, which is the next moment a slot is
          expected to free. Falling back to `now` when the queue is full would tell a planner human
          review is instantaneous at precisely the moment it is saturated.
        * full with no dated items -> `now` plus the policy's default SLA, because there is nothing
          to read a date off and reporting `now` would again be the optimistic lie.

        Items already past their expiry are *not* discounted from depth. They are still occupying
        the queue until something sweeps them, and a capability that assumed the sweep had happened
        would report room that does not exist.
        """
        items = self.outstanding(project_id)
        depth = len(items)
        capacity = self._policy.capacity
        breached = sum(1 for item in items if item.due_at is not None and item.due_at <= now)

        if depth < capacity:
            earliest = now
        else:
            dated = [item.due_at for item in items if item.due_at is not None]
            earliest = (
                min(dated)
                if dated
                else now + dt.timedelta(minutes=self._policy.default_sla_minutes)
            )

        return HumanReviewCapability(
            project_id=project_id,
            available=depth < capacity,
            earliest_available_at=earliest,
            estimated_human_minutes=sum(item.estimated_human_minutes for item in items),
            depth=depth,
            capacity=capacity,
            breached=breached,
            policy_ref=f"{self._policy.policy_id}@{self._policy.version}",
        )

    def expire(
        self,
        *,
        item: ReviewItem,
        now: dt.datetime,
        resolutions: ResolutionSink,
        resolution_id: str,
        closure_event_id: str,
        resolved_by_actor_id: str,
        rationale: str | None = None,
    ) -> ReviewResolution:
        """Take one expired item out of the queue, through the locked resolution path.

        `closure_event_id` IS REQUIRED AND THERE IS NO OVERLOAD THAT INVENTS ONE. An expiry closes
        the linked Conflict, which unblocks a belief that no human adjudicated -- §6.18 makes that
        a recordable act and `011c` makes the event NOT NULL for all four outcomes precisely so no
        status can stop a conflict blocking without one. A queue sweep that minted its own event
        would be a background job quietly authoring the record of a governance decision.

        Refuses an item that is not actually expired. A sweep that could expire anything on request
        is a way to clear an inconvenient review, and the deadline the policy declared is the only
        thing that makes an expiry legitimate.
        """
        if item.status not in OUTSTANDING_REVIEW_STATUSES:
            raise ReviewQueueError(
                f"review {item.review_id} is {item.status.value} and has already left the queue. "
                "Expiring it again would overwrite the record of how it was actually resolved"
            )
        if item.expires_at is None:
            raise ReviewQueueError(
                f"review {item.review_id} carries no expires_at, so no policy has priced it and "
                "there is no declared moment at which it lapses (§14.4)"
            )
        if item.expires_at > now:
            raise ReviewQueueError(
                f"review {item.review_id} expires at {item.expires_at.isoformat()}, which is after "
                f"{now.isoformat()}. Expiring an item early is a way to clear an inconvenient "
                "review, and the declared deadline is what makes an expiry legitimate"
            )

        return resolutions.resolve_and_close_conflict(
            resolution=ReviewResolution(
                resolution_id=resolution_id,
                review_id=item.review_id,
                project_id=item.project_id,
                outcome=ReviewOutcome.EXPIRED,
                resolved_by_actor_id=resolved_by_actor_id,
                resolved_at=now,
                rationale=rationale
                or (
                    f"expired unanswered at {now.isoformat()} under queue policy "
                    f"{self._policy.policy_id}@{self._policy.version}; the item was due at "
                    f"{item.due_at.isoformat() if item.due_at else 'an undeclared time'}"
                ),
                belief_revision_event_id=closure_event_id,
            ),
            # §17.19.3's honest status for a disagreement nobody settled. Not RESOLVED: the
            # authority question is exactly as open as it was, and recording it as resolved would
            # claim an answer the timeout did not produce.
            conflict_status=ConflictResolutionStatus.ACCEPTED_AS_OPEN_QUESTION,
        )


def price_review(
    *, review: ReviewItem, policy: ReviewQueuePolicy, now: dt.datetime | None = None
) -> ReviewItem:
    """Attach the policy's deadlines to a review, or refuse it (§26's "refused at creation").

    The Python half of `011e`'s trigger. Both exist for the reason this project has now written
    down five times: a model guard holds for callers who go through the model, and a migration, a
    support script or a future service writes SQL. This one produces a better message and catches
    it earlier; the trigger is the one that actually holds.
    """
    del now  # deadlines are priced from `created_at`, not from when the pricing happens
    if not review.stakes.strip():
        raise ReviewQueueError(
            f"review {review.review_id} has no stakes. §14.4 requires them on every queued item: "
            "stakes is what a reviewer prioritises by and what the SLA is priced from, and a blank "
            "one makes the item indistinguishable from the least urgent thing in the queue"
        )
    if review.project_id != policy.project_id:
        raise ReviewQueueError(
            f"review {review.review_id} is in {review.project_id} but queue policy "
            f"{policy.policy_id}@{policy.version} governs {policy.project_id}. One project's SLA "
            "does not price another's work (SEC-002)"
        )
    if not policy.active:
        raise ReviewQueueError(
            f"queue policy {policy.policy_id}@{policy.version} is not active, so it declares no "
            "current deadline. An item priced by a retired policy has an expiry nobody stands "
            "behind"
        )
    updates: dict[str, Any] = {
        "due_at": policy.due_at(stakes=review.stakes, created_at=review.created_at),
        "expires_at": policy.expires_at(stakes=review.stakes, created_at=review.created_at),
    }
    return ReviewItem.model_validate(review.model_dump() | updates)


def outstanding_of(items: Sequence[ReviewItem]) -> tuple[ReviewItem, ...]:
    """The subset a human still owes an answer for. One definition, used everywhere."""
    return tuple(item for item in items if item.status in OUTSTANDING_REVIEW_STATUSES)


__all__ = [
    "HumanReviewCapability",
    "ResolutionSink",
    "ReviewItemSource",
    "ReviewQueue",
    "ReviewQueueError",
    "ReviewQueuePolicy",
    "outstanding_of",
    "price_review",
]
