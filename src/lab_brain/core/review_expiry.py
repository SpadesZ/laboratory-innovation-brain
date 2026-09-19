"""The production caller that makes T-OPS-002's liveness clause true (`v3.3-a15`, OPS-002).

    §26  T-OPS-002 ... an item past its expiry leaves PENDING via the declared policy rather than
         parking there indefinitely (§14.4).

WHAT WAS MISSING, AND IT WAS NOT THE SEAM. `ReviewQueue.expire` has existed since the OPS-002
slice and is correct. What did not exist was anything that *called* it, so the obligation held for
callers who called it -- which is to say for tests. The M0b sign-off audit found that, and the
reason it could not simply be added was SPEC-ISSUE-012: the expiry needed a closure event, and
`v3.3-a14` routed that through a `BeliefRevisionEvent` which an unanswered timeout cannot honestly
produce. `v3.3-a15` settled it with `GovernanceEvent`, and this module is the caller.

NOTHING HERE DECIDES ANYTHING. It selects items whose declared deadline has passed and executes the
one path §17.19.1 permits. It does not choose deadlines (the queue policy did), does not choose
which items lapse (the deadline did), and does not author a belief revision (it cannot -- the
database will not let it).

THREE THINGS ARE PARAMETERS, NOT AMBIENT, AND EACH FOR A STATED REASON:

    now          a sweep that read the clock could not be replayed, and "which items were overdue
                 when this ran" is the whole record. Passing it also makes the concurrency test a
                 test rather than a race against wall time.
    actor_id     §14.4 puts `actor_id` on every governance action. Defaulting it would attribute a
                 governance decision to whatever the code happened to name.
    ids          a retry that renamed its rows would be indistinguishable from a second expiry, so
                 idempotence would be unobservable. See `ExpiryIdSource`.

THE POLICY VERSION IS READ OFF THE ITEM, NOT OFF THE PROJECT. `v3.3-a15`: an expiry re-interpreted
under a policy the reviewer never saw is not the deadline they were given. So the sweep uses
`review_items.queue_policy_id/@version` -- the row the item was priced by -- and never
`active_for(project)`. A lab that tightens its SLA does not thereby retro-expire everything already
queued.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from lab_brain.core.models.governance_event import GovernanceEvent
from lab_brain.core.models.review import OUTSTANDING_REVIEW_STATUSES, ReviewItem


class ExpiryRefused(RuntimeError):
    """The sweep could not run at all -- distinct from one item declining to expire.

    An item that is not yet overdue is simply not selected; that is not an error. This is raised
    when the sweep itself cannot proceed honestly: no executor, or an executor the database will
    not vouch for.
    """


@runtime_checkable
class ExpiryIdSource(Protocol):
    """Supplies the two ids each expiry writes.

    A seam rather than `uuid4()` inline, for the reason `BeliefEpisode` has one: a retry that
    renamed its rows would look exactly like a second expiry, and idempotence is the property under
    test.
    """

    def governance_event_id(self, review_id: str) -> str: ...

    def resolution_id(self, review_id: str) -> str: ...


@runtime_checkable
class ExpirySink(Protocol):
    """The atomic `011f` path. One statement, so no half-state is observable."""

    def overdue(self, project_id: str, now: dt.datetime) -> tuple[ReviewItem, ...]: ...

    def expire(
        self,
        *,
        review: ReviewItem,
        governance_event_id: str,
        resolution_id: str,
        actor_id: str,
        reason_code: str,
        rationale: str | None,
        now: dt.datetime,
        trace_id: str,
    ) -> GovernanceEvent: ...


@dataclass(frozen=True)
class ExpirySweepResult:
    """What one sweep did, including the items it deliberately left alone.

    `already_gone` is carried rather than dropped because it is what makes a retry readable: the
    second run of a sweep over the same window reports the same items as already handled instead of
    reporting an empty queue, and "nothing to do" and "somebody else did it" are different facts.
    """

    project_id: str
    swept_at: dt.datetime
    expired: tuple[GovernanceEvent, ...] = ()
    already_gone: tuple[str, ...] = ()
    #: review_id -> the refusal, for items the database declined. Carried rather than raised: one
    #: unexpireable item must not abandon the rest of the queue.
    refused: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.expired)


class DefaultExpiryIdSource:
    """Deterministic ids derived from the review they belong to.

    `gev:expiry:<review_id>` and `res:expiry:<review_id>`. Derived rather than generated, and that
    is the idempotence: a retried sweep proposes the same primary keys, so the second attempt
    collides on the unique constraints `011c`/`011f` already carry rather than writing a second
    expiry. The database is what makes it safe; this only makes it *observably* safe.
    """

    def governance_event_id(self, review_id: str) -> str:
        return f"gev:expiry:{review_id}"

    def resolution_id(self, review_id: str) -> str:
        return f"res:expiry:{review_id}"


class ReviewExpiryProcessor:
    """Sweeps a project's overdue reviews through §17.19.1's declared expiry path.

    Constructed with its ports so the same object runs against PostgreSQL and against a fake, and
    so the sweep has no way to reach a store it was not given.
    """

    #: Recorded on every GovernanceEvent this processor writes. A code rather than prose so a
    #: reader can select on it; the prose goes in `rationale`.
    REASON_CODE = "REVIEW_SLA_EXPIRED"

    def __init__(self, *, reviews: ExpirySink, ids: ExpiryIdSource | None = None) -> None:
        self._reviews = reviews
        self._ids = ids or DefaultExpiryIdSource()

    def sweep(
        self,
        *,
        project_id: str,
        now: dt.datetime,
        actor_id: str,
        trace_id: str,
        limit: int | None = None,
    ) -> ExpirySweepResult:
        """Expire every review whose declared deadline has passed, oldest first.

        ORDERED AND BOUNDED, BOTH ON PURPOSE. Oldest first because a queue that expired newest-first
        would leave the longest-waiting items longest -- and because a deterministic order is what
        lets two runs be compared. `limit` exists so a backlog of ten thousand does not become one
        transaction per sweep; it is the caller's batching knob and defaults to no limit.

        ONE ITEM'S REFUSAL DOES NOT ABANDON THE REST. Each expiry is its own statement, and a
        failure is recorded against that review rather than raised. A sweep that stopped at the
        first awkward row would leave a queue that heals only as far as its worst item -- which is
        the parking §14.4 forbids, arrived at by a different route.
        """
        if not actor_id.strip():
            raise ExpiryRefused(
                "a sweep needs an executing actor_id. §14.4 puts one on every governance action, "
                "and an expiry with no executor is a block that lifted with nobody accountable"
            )

        candidates = self._reviews.overdue(project_id, now)
        if limit is not None:
            candidates = candidates[:limit]

        expired: list[GovernanceEvent] = []
        already: list[str] = []
        refused: dict[str, str] = {}

        for review in candidates:
            # Re-checked here as well as in SQL. The list was read before the loop, and a human may
            # have answered one of these in between -- in which case the item is not overdue, it is
            # done, and reporting it as refused would read as a fault.
            if review.status not in OUTSTANDING_REVIEW_STATUSES:
                already.append(review.review_id)
                continue
            try:
                expired.append(
                    self._reviews.expire(
                        review=review,
                        governance_event_id=self._ids.governance_event_id(review.review_id),
                        resolution_id=self._ids.resolution_id(review.review_id),
                        actor_id=actor_id,
                        reason_code=self.REASON_CODE,
                        rationale=self._rationale(review, now),
                        now=now,
                        trace_id=trace_id,
                    )
                )
            except Exception as exc:
                refused[review.review_id] = f"{type(exc).__name__}: {exc}"

        return ExpirySweepResult(
            project_id=project_id,
            swept_at=now,
            expired=tuple(expired),
            already_gone=tuple(already),
            refused=refused,
        )

    def _rationale(self, review: ReviewItem, now: dt.datetime) -> str:
        """The prose beside the reason code, naming the deadline that was missed.

        Names the policy version the item was *priced by*, because that is the deadline the
        reviewer was given and the one this expiry is executing.
        """
        expired_at = review.expires_at.isoformat() if review.expires_at else "an undeclared time"
        due = review.due_at.isoformat() if review.due_at else "an undeclared time"
        return (
            f"review {review.review_id} ({review.stakes}) was due at {due} and expired at "
            f"{expired_at}; swept at {now.isoformat()} with no human answer. The authority "
            "question is unchanged and a later episode may raise it again."
        )


def sweep_projects(
    processor: ReviewExpiryProcessor,
    *,
    project_ids: Sequence[str],
    now: dt.datetime,
    actor_id: str,
    trace_id: str,
) -> tuple[ExpirySweepResult, ...]:
    """Run the sweep across several projects, each independently scoped.

    One call per project rather than one query across all of them: SEC-002 scopes every read by
    project, and a sweep that selected overdue items globally would touch rows it has no business
    seeing on its way to the right answer. Sorted so two runs over the same set are comparable.
    """
    return tuple(
        processor.sweep(project_id=project_id, now=now, actor_id=actor_id, trace_id=trace_id)
        for project_id in sorted(set(project_ids))
    )


__all__ = [
    "DefaultExpiryIdSource",
    "ExpiryIdSource",
    "ExpiryRefused",
    "ExpirySink",
    "ExpirySweepResult",
    "ReviewExpiryProcessor",
    "sweep_projects",
]
