"""Durable external-source provenance: snapshots and their lifecycle events (`002c`, M5).

Both are append-only. The snapshot table's uniqueness is the CACHE KEY -- one snapshot per
(project, provider, pinned locator): a second retrieval of the same pinned version is a cache hit,
not a second copy, and since the locator names an immutable version, the bytes cannot differ. `002c`
holds for any writer of SQL what the model holds here: a commit-pinned snapshot names its commit and
repository, technical material is TECHNICAL_ARTIFACT, the kept artifact exists as an
EXTERNAL_CONNECTOR artifact present in the project, and a FULL_CONTENT artifact hashes to the
recorded content hash.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.external_source import ExternalSnapshot, ExternalSourceEvent
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class ExternalSourceStoreError(RepositoryError):
    pass


@runtime_checkable
class ExternalSourceStore(Protocol):
    def add_snapshot(self, snapshot: ExternalSnapshot) -> ExternalSnapshot: ...

    def snapshot(self, project_id: str, snapshot_id: str) -> ExternalSnapshot | None: ...

    def pinned(
        self, project_id: str, provider: str, canonical_locator: str
    ) -> ExternalSnapshot | None: ...

    def for_request(
        self, project_id: str, provider: str, requested_locator: str
    ) -> tuple[ExternalSnapshot, ...]: ...

    def add_event(self, event: ExternalSourceEvent) -> ExternalSourceEvent: ...

    def events(self, project_id: str) -> tuple[ExternalSourceEvent, ...]: ...


class InMemoryExternalSourceStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, ExternalSnapshot] = {}
        self._events: list[ExternalSourceEvent] = []

    def add_snapshot(self, snapshot: ExternalSnapshot) -> ExternalSnapshot:
        if snapshot.snapshot_id in self._snapshots:
            raise ExternalSourceStoreError(f"{snapshot.snapshot_id} is append-only")
        if self.pinned(snapshot.project_id, snapshot.provider, snapshot.canonical_locator):
            raise ExternalSourceStoreError(
                f"{snapshot.canonical_locator} is already snapshotted in {snapshot.project_id}"
            )
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def snapshot(self, project_id: str, snapshot_id: str) -> ExternalSnapshot | None:
        found = self._snapshots.get(snapshot_id)
        return found if found is not None and found.project_id == project_id else None

    def pinned(
        self, project_id: str, provider: str, canonical_locator: str
    ) -> ExternalSnapshot | None:
        return next(
            (
                s
                for s in self._snapshots.values()
                if (s.project_id, s.provider, s.canonical_locator)
                == (project_id, provider, canonical_locator)
            ),
            None,
        )

    def for_request(
        self, project_id: str, provider: str, requested_locator: str
    ) -> tuple[ExternalSnapshot, ...]:
        return tuple(
            sorted(
                (
                    s
                    for s in self._snapshots.values()
                    if (s.project_id, s.provider, s.requested_locator)
                    == (project_id, provider, requested_locator)
                ),
                key=lambda s: (s.created_at, s.snapshot_id),
            )
        )

    def add_event(self, event: ExternalSourceEvent) -> ExternalSourceEvent:
        self._events.append(event)
        return event

    def events(self, project_id: str) -> tuple[ExternalSourceEvent, ...]:
        return tuple(
            sorted(
                (e for e in self._events if e.project_id == project_id),
                key=lambda e: (e.occurred_at, e.event_id),
            )
        )


_SNAPSHOT_COLUMNS = (
    "snapshot_id",
    "project_id",
    "provider",
    "source_type",
    "requested_locator",
    "canonical_locator",
    "requested_ref",
    "resolved_ref",
    "repository_identity",
    "content_hash",
    "artifact_id",
    "retention",
    "retention_rule",
    "visibility",
    "trust_class",
    "sensitivity",
    "license_class",
    "license_identifier",
    "rights_status",
    "access_policy_ref",
    "retrieved_at",
    "created_at",
)

_EVENT_COLUMNS = (
    "event_id",
    "project_id",
    "provider",
    "kind",
    "locator_digest",
    "locator",
    "snapshot_id",
    "actor_id",
    "detail",
    "occurred_at",
)


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


class SqlExternalSourceStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_snapshot(self, snapshot: ExternalSnapshot) -> ExternalSnapshot:
        dumped = snapshot.model_dump(mode="python")
        self._connection.execute(
            f"INSERT INTO external_snapshots ({', '.join(_SNAPSHOT_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_SNAPSHOT_COLUMNS))})",
            tuple(_value(dumped[c]) for c in _SNAPSHOT_COLUMNS),
        )
        return snapshot

    def _snapshots(self, where: str, params: tuple[Any, ...]) -> tuple[ExternalSnapshot, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_SNAPSHOT_COLUMNS)} FROM external_snapshots WHERE {where}"
            " ORDER BY created_at, snapshot_id",
            params,
        ).fetchall()
        return tuple(
            ExternalSnapshot.model_validate(dict(zip(_SNAPSHOT_COLUMNS, r, strict=True)))
            for r in rows
        )

    def snapshot(self, project_id: str, snapshot_id: str) -> ExternalSnapshot | None:
        found = self._snapshots("project_id = %s AND snapshot_id = %s", (project_id, snapshot_id))
        return found[0] if found else None

    def pinned(
        self, project_id: str, provider: str, canonical_locator: str
    ) -> ExternalSnapshot | None:
        found = self._snapshots(
            "project_id = %s AND provider = %s AND canonical_locator = %s",
            (project_id, provider, canonical_locator),
        )
        return found[0] if found else None

    def for_request(
        self, project_id: str, provider: str, requested_locator: str
    ) -> tuple[ExternalSnapshot, ...]:
        return self._snapshots(
            "project_id = %s AND provider = %s AND requested_locator = %s",
            (project_id, provider, requested_locator),
        )

    def add_event(self, event: ExternalSourceEvent) -> ExternalSourceEvent:
        dumped = event.model_dump(mode="python")
        self._connection.execute(
            f"INSERT INTO external_source_events ({', '.join(_EVENT_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_EVENT_COLUMNS))})",
            tuple(
                json.dumps(dumped[c]) if c == "detail" else _value(dumped[c])
                for c in _EVENT_COLUMNS
            ),
        )
        return event

    def events(self, project_id: str) -> tuple[ExternalSourceEvent, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_EVENT_COLUMNS)} FROM external_source_events"
            " WHERE project_id = %s ORDER BY occurred_at, event_id",
            (project_id,),
        ).fetchall()
        return tuple(
            ExternalSourceEvent.model_validate(dict(zip(_EVENT_COLUMNS, r, strict=True)))
            for r in rows
        )


__all__ = [
    "ExternalSourceStore",
    "ExternalSourceStoreError",
    "InMemoryExternalSourceStore",
    "SqlExternalSourceStore",
]
