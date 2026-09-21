"""§17.19.1 review items, and the atomic escalation that creates one (EPI-004).

ESCALATION IS ONE STATEMENT. The conflict and its review are one fact: a conflict escalated with
no review is a block nobody is working on, and a review whose conflict was never linked is a task
that cannot clear the block it exists for. Migration `010b` cost this project exactly that lesson
-- a span's status and its cost refs written separately and permanently divisible -- and it is
worse here, because neither row can be deleted afterwards.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence

from lab_brain.core.models.conflict import Conflict, ConflictResolutionStatus
from lab_brain.core.models.governance_event import GovernanceEvent
from lab_brain.core.models.review import OUTSTANDING_REVIEW_STATUSES, ReviewItem
from lab_brain.core.models.review_resolution import ReviewResolution
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError
from lab_brain.core.review_queue import ReviewQueuePolicy


class ReviewStoreError(RepositoryError):
    """A review could not be recorded, or an escalation would have left a half-linked block."""


_REVIEW_COLUMNS = (
    "review_id, project_id, subject_type, subject_id, stakes, reason, status, episode_id, "
    "trace_id, required_authority, required_role, assigned_actor_id, decision_ref, "
    "estimated_human_minutes, created_at, due_at, expires_at, queue_policy_id, "
    "queue_policy_version"
)

_GOVERNANCE_EVENT_COLUMNS = (
    "event_id, project_id, event_type, subject_type, subject_id, related_conflict_id, "
    "policy_id, policy_version, declared_by_actor_id, actor_id, reason_code, rationale, "
    "occurred_at, trace_id, episode_id"
)

_QUEUE_POLICY_COLUMNS = (
    "policy_id, version, project_id, capacity, default_sla_minutes, default_expiry_minutes, "
    "sla_minutes_by_stakes, expiry_minutes_by_stakes, reviewer_minutes_per_day, "
    "declared_by_actor_id, effective_from, active"
)


class SqlReviewQueuePolicyStore:
    """§14.4's queue policy against the `011e` table (OPS-002).

    `active_for` is the read that matters, and it returns at most one row by construction: `011e`
    carries a partial unique index on `(project_id) WHERE active`, so "which deadline applies" can
    never depend on read order. A second active policy is not something this class has to choose
    between -- it cannot exist.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def register(self, policy: ReviewQueuePolicy) -> ReviewQueuePolicy:
        require_durable_connection(self._connection)
        try:
            self._connection.execute(
                f"INSERT INTO review_queue_policies ({_QUEUE_POLICY_COLUMNS})"
                " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)",
                (
                    policy.policy_id,
                    policy.version,
                    policy.project_id,
                    policy.capacity,
                    policy.default_sla_minutes,
                    policy.default_expiry_minutes,
                    json.dumps(policy.sla_minutes_by_stakes, sort_keys=True),
                    json.dumps(policy.expiry_minutes_by_stakes, sort_keys=True),
                    policy.reviewer_minutes_per_day,
                    policy.declared_by_actor_id,
                    policy.effective_from,
                    policy.active,
                ),
            )
        except Exception as exc:
            raise ReviewStoreError(
                f"queue policy {policy.policy_id}@{policy.version} was refused: {exc}"
            ) from exc
        return policy

    def active_for(self, project_id: str) -> ReviewQueuePolicy | None:
        row = self._connection.execute(
            f"SELECT {_QUEUE_POLICY_COLUMNS} FROM review_queue_policies"
            " WHERE project_id = %s AND active",
            (project_id,),
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def get(self, policy_id: str, version: str) -> ReviewQueuePolicy | None:
        row = self._connection.execute(
            f"SELECT {_QUEUE_POLICY_COLUMNS} FROM review_queue_policies"
            " WHERE policy_id = %s AND version = %s",
            (policy_id, version),
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def _hydrate(self, row: Sequence[object]) -> ReviewQueuePolicy:
        return ReviewQueuePolicy.model_validate(
            {
                "policy_id": row[0],
                "version": row[1],
                "project_id": row[2],
                "capacity": row[3],
                "default_sla_minutes": row[4],
                "default_expiry_minutes": row[5],
                "sla_minutes_by_stakes": row[6],
                "expiry_minutes_by_stakes": row[7],
                "reviewer_minutes_per_day": row[8],
                "declared_by_actor_id": row[9],
                "effective_from": row[10],
                "active": row[11],
            }
        )


class SqlReviewItemStore:
    """Read review items, and escalate an authority conflict atomically."""

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def enqueue_extraction_review(
        self,
        *,
        review_id: str,
        project_id: str,
        item_id: str,
        stakes: str,
        reason: str,
        trace_id: str,
        created_at: dt.datetime,
        estimated_minutes: int = 30,
    ) -> str:
        """UX-005: put a low-confidence extraction into the ONE queue.

        Thin, because the invariants are `011h`'s: pricing comes from the active policy rather
        than from the caller (a caller supplying its own `due_at` could grant itself an SLA
        nobody agreed to), and the insert is idempotent on `review_id` so a retrying ingestion
        worker cannot consume reviewer capacity twice for the same item.

        Returns the authoritative review id -- the existing one on a repeat, exactly as
        `JobStore.complete` returns the authoritative Run.
        """
        row = self._connection.execute(
            "SELECT extraction_review_enqueue(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                review_id,
                project_id,
                item_id,
                stakes,
                reason,
                trace_id,
                created_at,
                estimated_minutes,
            ),
        ).fetchone()
        if row is None:  # pragma: no cover - the function returns an id or raises
            raise ReviewStoreError(f"extraction_review_enqueue returned nothing for {review_id}")
        return str(row[0])

    def escalate_authority_conflict(self, *, conflict: Conflict, review: ReviewItem) -> ReviewItem:
        """Create the review and link it to the conflict in one statement.

        The conflict must already be stored and still unresolved; `authority_conflict_escalate`
        refuses otherwise, because queueing a review for a block that has already lifted gives a
        human a task with nothing behind it.
        """
        require_durable_connection(self._connection)
        if review.subject_id != conflict.conflict_id:
            raise ReviewStoreError(
                f"review {review.review_id} names subject {review.subject_id} but is being "
                f"linked to conflict {conflict.conflict_id}. §17.19.3 makes the subject a "
                "conflict_id, and a mismatch would queue a review that cannot clear its block"
            )
        try:
            row = self._connection.execute(
                "SELECT authority_conflict_escalate( %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    review.review_id,
                    conflict.conflict_id,
                    conflict.project_id,
                    review.stakes,
                    review.reason,
                    review.trace_id,
                    review.created_at,
                    review.required_authority,
                    review.episode_id,
                    review.estimated_human_minutes,
                ),
            )
        except Exception as exc:
            raise ReviewStoreError(
                f"escalation of {conflict.conflict_id} in {conflict.project_id} was refused: {exc}"
            ) from exc

        # IDEMPOTENT, AND THE RETURNED ID IS THE ONE THAT MATTERS. A retried episode gets the
        # review that already gates this conflict, not the one it just proposed -- so the caller
        # must read the function's answer rather than assume its own `review_id` won. Returning
        # the proposed id here would make a duplicate escalation look successful.
        linked_review_id = str(row.fetchone()[0])  # type: ignore[index]
        stored = self.get(conflict.project_id, linked_review_id)
        if stored is None:  # pragma: no cover - the function raises before this is reachable
            raise ReviewStoreError(f"{linked_review_id} vanished between writing and reading back")
        return stored

    def resolve_and_close_conflict(
        self,
        *,
        resolution: ReviewResolution,
        conflict_status: ConflictResolutionStatus,
    ) -> ReviewResolution:
        """Record the resolution, terminalize the review and close its conflict, atomically.

        One database statement, so neither half-state `v3.3-a14` names is observable: not "review
        terminal, conflict still open" and not "review outstanding, conflict closed". The close
        inside it is conditioned on the conflict still being unresolved, which is what makes two
        concurrent resolutions produce exactly one winner.

        This is the only supported way to resolve a review that gates a conflict. There is
        deliberately no `resolve_review` that stops short of the conflict: a review terminalized
        on its own would satisfy the audit trail and leave the belief blocked forever.
        """
        require_durable_connection(self._connection)
        if conflict_status in (
            ConflictResolutionStatus.OPEN,
            ConflictResolutionStatus.UNDER_REVIEW,
        ):
            raise ReviewStoreError(
                f"{conflict_status.value} is not a closure. Resolving a review moves its conflict "
                "to a terminal status; leaving it open would record a human decision that changed "
                "nothing"
            )
        try:
            self._connection.execute(
                "SELECT review_resolve_and_close_conflict( %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    resolution.resolution_id,
                    resolution.review_id,
                    resolution.project_id,
                    resolution.outcome.value,
                    resolution.resolved_by_actor_id,
                    resolution.rationale,
                    resolution.belief_revision_event_id,
                    conflict_status.value,
                    resolution.resolved_at,
                ),
            )
        except Exception as exc:
            raise ReviewStoreError(
                f"resolving review {resolution.review_id} in {resolution.project_id} was "
                f"refused: {exc}"
            ) from exc
        return resolution

    def resolution_for(self, project_id: str, review_id: str) -> ReviewResolution | None:
        """The durable resolution for a review, or None while it is still outstanding."""
        row = self._connection.execute(
            "SELECT resolution_id, review_id, project_id, outcome, resolved_by_actor_id,"
            " resolved_at, rationale, belief_revision_event_id, governance_event_id,"
            " resolution_event_kind FROM review_resolutions"
            " WHERE project_id = %s AND review_id = %s",
            (project_id, review_id),
        ).fetchone()
        if row is None:
            return None
        return ReviewResolution.model_validate(
            {
                "resolution_id": row[0],
                "review_id": row[1],
                "project_id": row[2],
                "outcome": row[3],
                "resolved_by_actor_id": row[4],
                "resolved_at": row[5],
                "rationale": row[6],
                "belief_revision_event_id": row[7],
                "governance_event_id": row[8],
                "resolution_event_kind": row[9],
            }
        )

    # -- OPS-002 automatic expiry (`v3.3-a15`) ----------------------------------------------

    def overdue(self, project_id: str, now: dt.datetime) -> tuple[ReviewItem, ...]:
        """Outstanding items whose declared expiry has passed, oldest first.

        Filtered in SQL on the same two statuses `OUTSTANDING_REVIEW_STATUSES` names, so the
        database and the model cannot disagree about what is still owed. Ordered on
        `(expires_at, review_id)` -- a total order, so a sweep over the same window twice visits
        the same items in the same sequence and two runs can be compared.
        """
        rows = self._connection.execute(
            f"SELECT {_REVIEW_COLUMNS} FROM review_items"
            " WHERE project_id = %s AND status = ANY (%s)"
            "   AND expires_at IS NOT NULL AND expires_at <= %s"
            " ORDER BY expires_at, review_id",
            (project_id, sorted(status.value for status in OUTSTANDING_REVIEW_STATUSES), now),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

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
    ) -> GovernanceEvent:
        """Expire one review through `011f`'s atomic path, and read the event back.

        THE POLICY VERSION COMES OFF THE ITEM. `review.queue_policy_id/@version` is the row this
        item was *priced by*, not whichever policy is active now -- `v3.3-a15` is explicit that an
        expiry re-interpreted under a policy the reviewer never saw is not the deadline they were
        given. `review_expire` re-checks the pair against the stored item and refuses a mismatch,
        so a caller cannot pass a convenient version instead.

        One statement, so the GovernanceEvent, the EXPIRED resolution, the terminal review and the
        conflict closure are all or none -- the `v3.3-a14` atomicity clause, which an expiry is the
        most likely path to break because nobody is watching it run.
        """
        require_durable_connection(self._connection)
        if review.queue_policy_id is None or review.queue_policy_version is None:
            raise ReviewStoreError(
                f"review {review.review_id} names no queue policy, so no declared deadline "
                "authorises expiring it (§14.4)"
            )
        try:
            self._connection.execute(
                "SELECT review_expire(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    resolution_id,
                    governance_event_id,
                    review.review_id,
                    review.project_id,
                    review.queue_policy_id,
                    review.queue_policy_version,
                    actor_id,
                    reason_code,
                    rationale,
                    now,
                    trace_id,
                ),
            )
        except Exception as exc:
            raise ReviewStoreError(
                f"expiry of review {review.review_id} in {review.project_id} was refused: {exc}"
            ) from exc

        written = self.governance_event(review.project_id, governance_event_id)
        if written is None:  # pragma: no cover - `review_expire` raises before this is reachable
            raise ReviewStoreError(
                f"{governance_event_id} vanished between writing and reading it back"
            )
        return written

    def governance_event(self, project_id: str, event_id: str) -> GovernanceEvent | None:
        """Read a §17.19.1 governance event back through the model's validator."""
        row = self._connection.execute(
            f"SELECT {_GOVERNANCE_EVENT_COLUMNS} FROM governance_events"
            " WHERE project_id = %s AND event_id = %s",
            (project_id, event_id),
        ).fetchone()
        if row is None:
            return None
        return GovernanceEvent.model_validate(
            {
                "event_id": row[0],
                "project_id": row[1],
                "event_type": row[2],
                "subject_type": row[3],
                "subject_id": row[4],
                "related_conflict_id": row[5],
                "policy_id": row[6],
                "policy_version": row[7],
                "declared_by_actor_id": row[8],
                "actor_id": row[9],
                "reason_code": row[10],
                "rationale": row[11],
                "occurred_at": row[12],
                "trace_id": row[13],
                "episode_id": row[14],
            }
        )

    def get(self, project_id: str, review_id: str) -> ReviewItem | None:
        row = self._connection.execute(
            f"SELECT {_REVIEW_COLUMNS} FROM review_items WHERE project_id = %s AND review_id = %s",
            (project_id, review_id),
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def for_subject(self, project_id: str, subject_id: str) -> tuple[ReviewItem, ...]:
        """Project-scoped, like every read: SEC-002 does not exempt the review queue."""
        rows = self._connection.execute(
            f"SELECT {_REVIEW_COLUMNS} FROM review_items"
            " WHERE project_id = %s AND subject_id = %s ORDER BY created_at, review_id",
            (project_id, subject_id),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def outstanding(self, project_id: str) -> tuple[ReviewItem, ...]:
        """Everything a human still owes an answer for, oldest first (OPS-002, §14.4.1).

        Filtered in SQL on the same two statuses `OUTSTANDING_REVIEW_STATUSES` names, so the
        database and the model cannot disagree about what "depth" counts -- the same arrangement
        `SqlConflictStore.unresolved_for_subject` uses and for the same reason.

        `ASSIGNED` is included. A queue that stopped counting picked-up items would report depth 0
        while forty reviews sat half-done, which is the distinction `v3.3-a14` draws when it makes
        ASSIGNED outstanding.
        """
        rows = self._connection.execute(
            f"SELECT {_REVIEW_COLUMNS} FROM review_items"
            " WHERE project_id = %s AND status = ANY (%s)"
            " ORDER BY created_at, review_id",
            (project_id, sorted(status.value for status in OUTSTANDING_REVIEW_STATUSES)),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def _hydrate(self, row: Sequence[object]) -> ReviewItem:
        return ReviewItem.model_validate(
            {
                "review_id": row[0],
                "project_id": row[1],
                "subject_type": row[2],
                "subject_id": row[3],
                "stakes": row[4],
                "reason": row[5],
                "status": row[6],
                "episode_id": row[7],
                "trace_id": row[8],
                "required_authority": row[9],
                "required_role": row[10],
                "assigned_actor_id": row[11],
                "decision_ref": row[12],
                "estimated_human_minutes": row[13],
                "created_at": row[14],
                "due_at": row[15],
                "expires_at": row[16],
                "queue_policy_id": row[17],
                "queue_policy_version": row[18],
            }
        )


__all__ = ["ReviewStoreError", "SqlReviewItemStore", "SqlReviewQueuePolicyStore"]
