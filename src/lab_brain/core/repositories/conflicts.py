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
from typing import Protocol, runtime_checkable

from lab_brain.core.models.conflict import (
    Conflict,
    ConflictResolutionStatus,
)
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


__all__ = [
    "ConflictStore",
    "ConflictStoreError",
    "InMemoryConflictStore",
]
