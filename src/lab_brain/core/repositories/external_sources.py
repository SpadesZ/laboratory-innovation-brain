"""Durable external-source provenance: snapshots and their lifecycle events (`002c`, M5).

Both are append-only. The snapshot table's uniqueness is the CACHE KEY -- one snapshot per
(project, provider, pinned locator): a second retrieval of the same pinned version is a cache hit,
not a second copy, and since the locator names an immutable version, the bytes cannot differ. `002c`
holds for any writer of SQL what the model holds here: a commit-pinned snapshot names its commit and
repository, technical material is TECHNICAL_ARTIFACT, the kept artifact exists as an
EXTERNAL_CONNECTOR artifact present in the project, and a FULL_CONTENT artifact hashes to the
recorded content hash.

ACCESS SCOPES (`002d`, GH-002). The authorization an adapter read under is recorded before any
snapshot that names it, and is immutable per policy version: one `policy_ref` is bound to one
project, one provider and one allowlist forever. Re-recording the same scope is a no-op; recording a
different scope under the same ref is refused -- a policy reference cannot be quietly re-pointed at
another project, which is exactly the substitution the scope exists to prevent.

QUARANTINE (`002e`, GH-002 upgrade safety). A snapshot whose project and access scope cannot be
proven coherent -- every row the vulnerable pre-`002d` model could have written -- is quarantined,
append-only, with its reason. A quarantined snapshot stays readable as provenance but is never a
cache hit (`pinned` skips it, so a fresh read under the project's own scope supersedes it), and
nothing is admitted from it. The attestations admitted from quarantined snapshots before the upgrade
are the §6.18 quarantine selection (`quarantined_attestation_ids`).
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.external_source import (
    ExternalAccessScope,
    ExternalSnapshot,
    ExternalSourceEvent,
)
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

    def record_access_scope(self, scope: ExternalAccessScope) -> ExternalAccessScope: ...

    def quarantine(self, project_id: str, snapshot_id: str, reason_code: str) -> None:
        """Quarantine a snapshot (append-only; quarantining more is the fail-safe direction)."""
        ...

    def quarantine_reason(self, project_id: str, snapshot_id: str) -> str | None:
        """Why this snapshot is quarantined, or `None` when it is trusted."""
        ...


def _same_scope(stored: ExternalAccessScope, scope: ExternalAccessScope) -> ExternalAccessScope:
    if stored != scope:
        raise ExternalSourceStoreError(
            f"access scope {scope.policy_ref} is recorded for project {stored.project_id} / "
            f"{stored.provider}; a policy version is bound to one project and one allowlist and "
            "cannot be re-pointed (GH-002)"
        )
    return stored


class InMemoryExternalSourceStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, ExternalSnapshot] = {}
        self._events: list[ExternalSourceEvent] = []
        self._scopes: dict[str, ExternalAccessScope] = {}
        self._quarantine: dict[str, str] = {}

    def quarantine(self, project_id: str, snapshot_id: str, reason_code: str) -> None:
        if self.snapshot(project_id, snapshot_id) is None:
            raise ExternalSourceStoreError(f"{snapshot_id} is not a snapshot of {project_id}")
        self._quarantine.setdefault(snapshot_id, reason_code)

    def quarantine_reason(self, project_id: str, snapshot_id: str) -> str | None:
        if self.snapshot(project_id, snapshot_id) is None:
            return None
        return self._quarantine.get(snapshot_id)

    def record_access_scope(self, scope: ExternalAccessScope) -> ExternalAccessScope:
        stored = self._scopes.setdefault(scope.policy_ref, scope)
        return _same_scope(stored, scope)

    def add_snapshot(self, snapshot: ExternalSnapshot) -> ExternalSnapshot:
        if snapshot.access_policy_ref is not None:
            scope = self._scopes.get(snapshot.access_policy_ref)
            if scope is None or scope.project_id != snapshot.project_id:
                raise ExternalSourceStoreError(
                    f"{snapshot.snapshot_id} in {snapshot.project_id} names access scope "
                    f"{snapshot.access_policy_ref}, which is not recorded for that project (GH-002)"
                )
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
                and s.snapshot_id not in self._quarantine
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

_SCOPE_COLUMNS = (
    "policy_ref",
    "project_id",
    "provider",
    "declared_by_actor_id",
    "private_allowlist",
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

    def record_access_scope(self, scope: ExternalAccessScope) -> ExternalAccessScope:
        self._connection.execute(
            "INSERT INTO external_access_scopes (policy_ref, project_id, provider,"
            " declared_by_actor_id, private_allowlist) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (policy_ref) DO NOTHING",
            (
                scope.policy_ref,
                scope.project_id,
                scope.provider,
                scope.declared_by_actor_id,
                sorted(scope.private_allowlist),
            ),
        )
        row = self._connection.execute(
            f"SELECT {', '.join(_SCOPE_COLUMNS)} FROM external_access_scopes WHERE policy_ref = %s",
            (scope.policy_ref,),
        ).fetchone()
        if row is None:
            raise ExternalSourceStoreError(f"access scope {scope.policy_ref} was not recorded")
        stored = ExternalAccessScope.model_validate(dict(zip(_SCOPE_COLUMNS, row, strict=True)))
        return _same_scope(stored, scope)

    def quarantine(self, project_id: str, snapshot_id: str, reason_code: str) -> None:
        self._connection.execute(
            "INSERT INTO external_snapshot_quarantine (snapshot_id, project_id, reason_code)"
            " VALUES (%s, %s, %s) ON CONFLICT (snapshot_id) DO NOTHING",
            (snapshot_id, project_id, reason_code),
        )

    def quarantine_reason(self, project_id: str, snapshot_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT reason_code FROM external_snapshot_quarantine"
            " WHERE project_id = %s AND snapshot_id = %s",
            (project_id, snapshot_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def snapshot_artifact_of_attestation(self, attestation_id: str, project_id: str) -> str | None:
        """The kept artifact behind an attestation admitted from an external snapshot.

        External evidence cites a SourceWork (EVI-004's identity), so the attestation records no
        `source_artifact_id`; the bytes it was read from are the snapshot its `method` names.
        Resolved only within the attestation's own project, and never for a quarantined snapshot
        -- quarantined material is not trusted anywhere, classification included.
        """
        row = self._connection.execute(
            "SELECT s.artifact_id FROM attestations a JOIN external_snapshots s"
            " ON s.snapshot_id = a.method ->> 'snapshot_id' AND s.project_id = a.project_id"
            " WHERE a.attestation_id = %s AND a.project_id = %s AND NOT EXISTS"
            " (SELECT 1 FROM external_snapshot_quarantine q WHERE q.snapshot_id = s.snapshot_id)",
            (attestation_id, project_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def quarantined_attestation_ids(self, project_id: str) -> tuple[str, ...]:
        """The §6.18 selection: attestations admitted from snapshots quarantined since (`002e`).

        Passed to belief replay as `quarantined_attestation_ids`, so events they triggered before
        the upgrade are skipped rather than kept.
        """
        rows = self._connection.execute(
            "SELECT attestation_id FROM external_quarantined_attestations"
            " WHERE project_id = %s ORDER BY attestation_id",
            (project_id,),
        ).fetchall()
        return tuple(str(r[0]) for r in rows)

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
            "project_id = %s AND provider = %s AND canonical_locator = %s AND NOT EXISTS"
            " (SELECT 1 FROM external_snapshot_quarantine q"
            " WHERE q.snapshot_id = external_snapshots.snapshot_id)",
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
