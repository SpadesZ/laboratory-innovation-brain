"""`RunOutputSink` over PostgreSQL and an `ArtifactStore` -- the storage half of a Run's output.

The same unit of work `IngestionService` uses for an upload (§12.3, OPS-004), applied to bytes a
backend emitted:

    0. secret scan   SEC-003 runs first for every immutable write, including a backend's. A solver
                     that echoed a credential into its log would otherwise put it in permanent
                     storage; a run output that is not CLEAN is refused, not redacted -- a
                     verification result whose bytes were edited is not the result.
    1. stage bytes   reversible, content hash computed by the store
    2. rows          `artifacts` (source_origin RUN_OUTPUT) and its `artifact_occurrences` row in
                     the Run's project, in one transaction -- presence is the occurrence (ADR-0010)
    3. promote       makes the bytes addressable; a failure here compensates step 2

Re-emitting identical bytes is idempotent: content addressing makes the second write the same
artifact, and `ON CONFLICT DO NOTHING` keeps the first row's provenance.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.enums import SecretScanStatus, SensitivityLabel, SourceOrigin
from lab_brain.ingestion.secret_scanner import SecretScanner
from lab_brain.storage.artifacts.interface import ArtifactStore
from lab_brain.storage.postgres.ingestion_writer import PostgresIngestionWriter


class RunOutputRefused(RuntimeError):
    """A backend's output could not be stored as a run artifact."""


class SqlRunOutputSink:
    def __init__(
        self,
        *,
        connection: Any,
        store: ArtifactStore,
        now: Callable[[], dt.datetime],
        sensitivity: SensitivityLabel = SensitivityLabel.INTERNAL,
        scanner: SecretScanner | None = None,
    ) -> None:
        self._connection = connection
        self._store = store
        self._now = now
        self._sensitivity = sensitivity
        self._scanner = scanner or SecretScanner()
        self._writer = PostgresIngestionWriter(connection)

    def emit(self, *, project_id: str, media_type: str, data: bytes) -> str:
        scan = self._scanner.scan(data)
        if scan.status is not SecretScanStatus.CLEAN:
            raise RunOutputRefused(
                f"run output for {project_id} is {scan.status.value} under "
                f"{scan.scanner_id}@{scan.scanner_version}; a backend's output is stored as "
                "emitted or not at all (SEC-003)"
            )
        return self._store_bytes(
            project_id=project_id,
            media_type=media_type,
            data=data,
            origin=SourceOrigin.RUN_OUTPUT,
        )

    def put(self, *, project_id: str, media_type: str, data: bytes) -> str:
        """Store an INPUT (a device project) the same way -- the harness's upload path."""
        scan = self._scanner.scan(data)
        if scan.status is not SecretScanStatus.CLEAN:
            raise RunOutputRefused(f"input for {project_id} is {scan.status.value} (SEC-003)")
        return self._store_bytes(
            project_id=project_id, media_type=media_type, data=data, origin=SourceOrigin.UPLOAD
        )

    def read(self, artifact_id: str) -> bytes:
        row = self._connection.execute(
            "SELECT content_hash FROM artifacts WHERE artifact_id = %s", (artifact_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"artifact {artifact_id} has no row")
        return self._store.open(str(row[0]))

    def _store_bytes(
        self, *, project_id: str, media_type: str, data: bytes, origin: SourceOrigin
    ) -> str:
        at = self._now()
        staged = self._store.stage(data)
        artifact = Artifact.from_bytes(
            data,
            media_type=media_type,
            uri=f"cas://{staged.content_hash}",
            source_origin=origin,
            lineage_id=f"lin:{staged.content_hash}",
            created_at=at,
            secret_scan_status=SecretScanStatus.CLEAN,
        )
        if artifact.content_hash != staged.content_hash:  # pragma: no cover - one hash function
            self._store.discard(staged.staging_id)
            raise RunOutputRefused("the store and the model disagree about the content hash")
        occurrence = artifact.occurrence_in(project_id, self._sensitivity)
        # What already existed is not ours to compensate: identical bytes emitted twice are one
        # artifact, and a failed second promotion must not delete the first one's rows.
        had_artifact = self._exists(
            "SELECT 1 FROM artifacts WHERE artifact_id = %s", (artifact.artifact_id,)
        )
        had_occurrence = self._exists(
            "SELECT 1 FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
            (artifact.artifact_id, project_id),
        )
        try:
            with self._connection.transaction():
                self._writer.commit_rows(artifact, occurrence)
        except Exception:
            self._store.discard(staged.staging_id)
            raise
        try:
            self._store.promote(staged.staging_id, staged.content_hash)
        except Exception:
            # OPS-004: the rows say the bytes exist and the store says they do not. Undo the rows
            # this call created, in a separate transaction -- the one that wrote them has closed.
            with self._connection.transaction():
                if not had_occurrence:
                    self._connection.execute(
                        "DELETE FROM artifact_occurrences"
                        " WHERE artifact_id = %s AND project_id = %s",
                        (artifact.artifact_id, project_id),
                    )
                if not had_artifact:
                    self._connection.execute(
                        "DELETE FROM artifacts WHERE artifact_id = %s", (artifact.artifact_id,)
                    )
            raise
        return artifact.artifact_id

    def _exists(self, query: str, params: tuple[Any, ...]) -> bool:
        return self._connection.execute(query, params).fetchone() is not None


__all__ = ["RunOutputRefused", "SqlRunOutputSink"]
