"""`ExternalArtifactSink` over PostgreSQL and an `ArtifactStore` -- where kept external bytes go.

The same unit of work as `run_outputs` (§12.3, OPS-004): secret scan, stage, rows in one
transaction, promote, compensate on a failed promotion. Two differences, both provenance:

    origin      EXTERNAL_CONNECTOR, not RUN_OUTPUT -- ADR-0010's artifact row says where bytes came
                from, and `002c` checks a snapshot's artifact has this origin
    label and   the project occurrence carries the record's sensitivity (a private repository's file
    rights      is not PUBLIC), and the artifact row carries its RightsMetadata (licence class,
                identifier, source locator, retrieval time) -- SEC-004 reads it

Bytes that fail the secret scan raise `SecretsFound`; the snapshot service then keeps provenance
only (SEC-003). Nothing here decides retention.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from lab_brain.core.models.artifact import Artifact, RightsMetadata
from lab_brain.core.models.enums import SecretScanStatus, SensitivityLabel, SourceOrigin
from lab_brain.ingestion.secret_scanner import SecretScanner
from lab_brain.sources.snapshots import SecretsFound
from lab_brain.storage.artifacts.interface import ArtifactStore
from lab_brain.storage.postgres.ingestion_writer import PostgresIngestionWriter


class SqlExternalArtifactSink:
    def __init__(
        self,
        *,
        connection: Any,
        store: ArtifactStore,
        now: Callable[[], dt.datetime],
        scanner: SecretScanner | None = None,
    ) -> None:
        self._connection = connection
        self._store = store
        self._now = now
        self._scanner = scanner or SecretScanner()
        self._writer = PostgresIngestionWriter(connection)

    def store(
        self,
        *,
        project_id: str,
        media_type: str,
        data: bytes,
        label: SensitivityLabel,
        rights: RightsMetadata,
    ) -> str:
        scan = self._scanner.scan(data)
        if scan.status is not SecretScanStatus.CLEAN:
            raise SecretsFound(f"{scan.scanner_id}@{scan.scanner_version}: {scan.status.value}")
        staged = self._store.stage(data)
        artifact = Artifact.from_bytes(
            data,
            media_type=media_type,
            uri=f"cas://{staged.content_hash}",
            source_origin=SourceOrigin.EXTERNAL_CONNECTOR,
            lineage_id=f"lin:{staged.content_hash}",
            created_at=self._now(),
            secret_scan_status=SecretScanStatus.CLEAN,
            rights_metadata=rights,
        )
        occurrence = artifact.occurrence_in(project_id, label)
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

    def read(self, artifact_id: str) -> bytes:
        row = self._connection.execute(
            "SELECT content_hash FROM artifacts WHERE artifact_id = %s", (artifact_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"artifact {artifact_id} has no row")
        return self._store.open(str(row[0]))

    def _exists(self, query: str, params: tuple[Any, ...]) -> bool:
        return self._connection.execute(query, params).fetchone() is not None


__all__ = ["SqlExternalArtifactSink"]
