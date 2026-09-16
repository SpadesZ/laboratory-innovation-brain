"""§17.19.3 conflicts: record, read by project, resolve by event (EPI-006).

NO DELETE, AND NO SET-STATUS. The two operations a conflict store must not offer are the two a
naive one offers first. Deleting a conflict erases the reason a belief was blocked; setting its
status directly closes it without the event §25.3 requires. So `resolve` takes the event id, and
removal is not modelled at all -- the same shape as `BeliefEventStore`, and for the same reason.

RESOLUTION PRODUCES A NEW RECORD. `Conflict` is frozen, so resolving one returns the resolved
conflict rather than mutating the stored one. The store keeps the latest by id and the transition
from open to resolved is carried by `resolution_event_id`, which is what makes the close auditable
rather than merely recorded.

PROJECT SCOPE IS PART OF THE QUERY, NOT A FILTER AFTERWARDS. SEC-002 scopes every read by project,
and `for_subject` takes the project first for the same reason `BeliefEventStore.history` does: two
projects may legitimately reference the same hypothesis id, and a query keyed only on the subject
would read rows the caller has no business seeing on its way to the right answer.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from lab_brain.core.models.conflict import (
    UNRESOLVED_CONFLICT_STATUSES,
    Conflict,
    ConflictResolutionStatus,
)
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError


class ConflictStoreError(RepositoryError):
    """A conflict could not be recorded, or a resolution would have lost its justification."""


@runtime_checkable
class ConflictStore(Protocol):
    """§17.19.3. Record, read, resolve. Deliberately no delete and no status setter."""

    def record(self, conflict: Conflict) -> Conflict: ...

    def get(self, project_id: str, conflict_id: str) -> Conflict | None: ...

    def for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]: ...

    def resolve(
        self,
        *,
        project_id: str,
        conflict_id: str,
        resolution_event_id: str,
        resolved_at: dt.datetime,
        status: ConflictResolutionStatus = ConflictResolutionStatus.RESOLVED,
    ) -> Conflict: ...


class InMemoryConflictStore:
    """The contract in process, enforcing every invariant the table will have to."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[tuple[str, str], Conflict] = {}

    def record(self, conflict: Conflict) -> Conflict:
        """Record a new conflict. A second one under the same id is refused, not merged.

        Re-recording would let a detector overwrite a conflict that a human had already put
        UNDER_REVIEW, which is a silent reopen in the other direction.
        """
        key = (conflict.project_id, conflict.conflict_id)
        with self._lock:
            if key in self._by_key:
                raise ConflictStoreError(
                    f"conflict {conflict.conflict_id} already exists in {conflict.project_id}. "
                    "Conflicts are not re-recorded: a detector overwriting one a human had put "
                    "UNDER_REVIEW would discard the review without saying so"
                )
            self._by_key[key] = conflict
        return conflict

    def get(self, project_id: str, conflict_id: str) -> Conflict | None:
        return self._by_key.get((project_id, conflict_id))

    def for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]:
        """Every conflict in this project naming ``subject_ref``, ordered deterministically.

        Sorted on ``(detected_at, conflict_id)`` -- a total order, so two conflicts detected in
        the same microsecond still come back in the same sequence on every run. The result feeds
        `TransitionPolicy.evaluate`, whose determinism guarantee is only as good as its inputs'.
        """
        return tuple(
            sorted(
                (
                    conflict
                    for (project, _), conflict in self._by_key.items()
                    if project == project_id and subject_ref in conflict.subject_refs
                ),
                key=lambda conflict: (conflict.detected_at, conflict.conflict_id),
            )
        )

    def unresolved_for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]:
        """The subset that can still stop a transition. See `Conflict.blocks_transitions`."""
        return tuple(
            conflict
            for conflict in self.for_subject(project_id, subject_ref)
            if conflict.is_unresolved
        )

    def resolve(
        self,
        *,
        project_id: str,
        conflict_id: str,
        resolution_event_id: str,
        resolved_at: dt.datetime,
        status: ConflictResolutionStatus = ConflictResolutionStatus.RESOLVED,
    ) -> Conflict:
        """Close a conflict, and require the event that closed it.

        ``resolution_event_id`` is a required keyword with no default. A default of ``None`` would
        make the §25.3 obligation opt-in, and the caller that opted out would be the one under
        time pressure.
        """
        if not resolution_event_id:
            raise ConflictStoreError(
                f"refusing to resolve {conflict_id} with no resolution_event_id. §25.3 EPI-006 "
                "requires closing a conflict to record the event that closed it; without one the "
                "reason a belief became promotable again is unrecoverable"
            )
        if status in (ConflictResolutionStatus.OPEN, ConflictResolutionStatus.UNDER_REVIEW):
            raise ConflictStoreError(
                f"{status.value} is not a resolution. `resolve` closes a conflict; moving one to "
                "UNDER_REVIEW is a different operation and must not carry a resolution event"
            )

        with self._lock:
            existing = self._by_key.get((project_id, conflict_id))
            if existing is None:
                raise ConflictStoreError(
                    f"conflict {conflict_id} does not exist in {project_id}. Resolving an absent "
                    "conflict would report success for a block that is still in place somewhere "
                    "else -- or in another project, which is why this is keyed on both"
                )
            if not existing.is_unresolved:
                raise ConflictStoreError(
                    f"conflict {conflict_id} is already {existing.resolution_status.value}, "
                    f"closed by {existing.resolution_event_id}. Re-resolving would overwrite the "
                    "event that justified the first close"
                )
            resolved = existing.model_copy(
                update={
                    "resolution_status": status,
                    "resolved_at": resolved_at,
                    "resolution_event_id": resolution_event_id,
                }
            )
            # Re-validate: `model_copy` does not re-run validators, and this is exactly the
            # transition whose invariants matter most. Learned the hard way in `v3.3-a12`, where a
            # `model_copy` bypassed the `input_hash` check.
            resolved = Conflict.model_validate(resolved.model_dump())
            self._by_key[(project_id, conflict_id)] = resolved
        return resolved


_CONFLICT_COLUMNS = (
    "conflict_id, project_id, conflict_type, resolution_status, blocking, subject_refs, "
    "supporting_refs, detected_at, detected_by_actor_or_slot, trace_id, episode_id, review_id, "
    "resolved_at, resolution_event_id"
)


class SqlConflictStore:
    """The same contract against PostgreSQL (migration `011a`).

    Every invariant the in-memory store enforces is also a constraint or trigger, because a
    Python-only guard holds for callers who go through Python and this project has now found four
    separate places where something wrote SQL instead. What this class adds on top of the schema
    is the *ordering* -- closure goes through `conflict_close`, which is one statement conditioned
    on the row still being unresolved, so two callers racing cannot both succeed.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def record(self, conflict: Conflict) -> Conflict:
        require_durable_connection(self._connection)
        self._connection.execute(
            f"INSERT INTO conflicts ({_CONFLICT_COLUMNS})"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                conflict.conflict_id,
                conflict.project_id,
                conflict.conflict_type.value,
                conflict.resolution_status.value,
                conflict.blocking,
                list(conflict.subject_refs),
                list(conflict.supporting_refs),
                conflict.detected_at,
                conflict.detected_by_actor_or_slot,
                conflict.trace_id,
                conflict.episode_id,
                conflict.review_id,
                conflict.resolved_at,
                conflict.resolution_event_id,
            ),
        )
        return conflict

    def get(self, project_id: str, conflict_id: str) -> Conflict | None:
        row = self._connection.execute(
            f"SELECT {_CONFLICT_COLUMNS} FROM conflicts WHERE project_id = %s AND conflict_id = %s",
            (project_id, conflict_id),
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]:
        """Both columns in the WHERE, and the subject test done by the database.

        Not a fetch-then-filter: SEC-002 scopes every read by project, so a query that read every
        project's conflicts and narrowed afterwards would touch rows the caller has no business
        seeing on its way to the right answer.
        """
        rows = self._connection.execute(
            f"SELECT {_CONFLICT_COLUMNS} FROM conflicts"
            " WHERE project_id = %s AND %s = ANY (subject_refs)"
            " ORDER BY detected_at, conflict_id",
            (project_id, subject_ref),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def unresolved_for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]:
        """The subset that can still stop a transition.

        Filtered in SQL on the same two statuses `UNRESOLVED_CONFLICT_STATUSES` names, so the
        database and the model cannot disagree about which conflicts a policy should see.
        """
        rows = self._connection.execute(
            f"SELECT {_CONFLICT_COLUMNS} FROM conflicts"
            " WHERE project_id = %s AND %s = ANY (subject_refs)"
            " AND resolution_status = ANY (%s)"
            " ORDER BY detected_at, conflict_id",
            (
                project_id,
                subject_ref,
                [status.value for status in sorted(UNRESOLVED_CONFLICT_STATUSES)],
            ),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def resolve(
        self,
        *,
        project_id: str,
        conflict_id: str,
        resolution_event_id: str,
        resolved_at: dt.datetime,
        status: ConflictResolutionStatus = ConflictResolutionStatus.RESOLVED,
    ) -> Conflict:
        """Close through `conflict_close`, then read the row back and re-validate it.

        Reading it back is not paranoia about the database: it is how the caller gets a `Conflict`
        that has been through the model's validator, so a row the schema accepted and the model
        would not is caught here rather than handed on as if it were valid.
        """
        require_durable_connection(self._connection)
        if not resolution_event_id:
            raise ConflictStoreError(
                f"refusing to resolve {conflict_id} with no resolution_event_id. §25.3 EPI-006 "
                "requires closing a conflict to record the event that closed it"
            )
        try:
            self._connection.execute(
                "SELECT conflict_close(%s, %s, %s, %s, %s)",
                (conflict_id, project_id, status.value, resolution_event_id, resolved_at),
            )
        except Exception as exc:
            raise ConflictStoreError(
                f"conflict_close refused to close {conflict_id} in {project_id}: {exc}"
            ) from exc

        closed = self.get(project_id, conflict_id)
        if closed is None:  # pragma: no cover - `conflict_close` raises before this is reachable
            raise ConflictStoreError(
                f"{conflict_id} vanished from {project_id} between closing and reading it back"
            )
        return closed

    def _hydrate(self, row: Sequence[object]) -> Conflict:
        return Conflict.model_validate(
            {
                "conflict_id": row[0],
                "project_id": row[1],
                "conflict_type": row[2],
                "resolution_status": row[3],
                "blocking": row[4],
                "subject_refs": tuple(row[5]),  # type: ignore[arg-type]
                "supporting_refs": tuple(row[6]),  # type: ignore[arg-type]
                "detected_at": row[7],
                "detected_by_actor_or_slot": row[8],
                "trace_id": row[9],
                "episode_id": row[10],
                "review_id": row[11],
                "resolved_at": row[12],
                "resolution_event_id": row[13],
            }
        )


__all__ = [
    "ConflictStore",
    "ConflictStoreError",
    "InMemoryConflictStore",
    "SqlConflictStore",
]
