"""§17.19.1 review items, and the atomic escalation that creates one (EPI-004).

ESCALATION IS ONE STATEMENT. The conflict and its review are one fact: a conflict escalated with
no review is a block nobody is working on, and a review whose conflict was never linked is a task
that cannot clear the block it exists for. Migration `010b` cost this project exactly that lesson
-- a span's status and its cost refs written separately and permanently divisible -- and it is
worse here, because neither row can be deleted afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence

from lab_brain.core.models.conflict import Conflict, ConflictResolutionStatus
from lab_brain.core.models.review import ReviewItem
from lab_brain.core.models.review_resolution import ReviewResolution
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError


class ReviewStoreError(RepositoryError):
    """A review could not be recorded, or an escalation would have left a half-linked block."""


_REVIEW_COLUMNS = (
    "review_id, project_id, subject_type, subject_id, stakes, reason, status, episode_id, "
    "trace_id, required_authority, required_role, assigned_actor_id, decision_ref, "
    "estimated_human_minutes, created_at, due_at, expires_at"
)


class SqlReviewItemStore:
    """Read review items, and escalate an authority conflict atomically."""

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

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
            " resolved_at, rationale, belief_revision_event_id FROM review_resolutions"
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
            }
        )


__all__ = ["ReviewStoreError", "SqlReviewItemStore"]
