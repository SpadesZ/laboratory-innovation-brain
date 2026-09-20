"""The local ingestion vertical — SEC-003, UX-004, OPS-004.

    local source -> secret scan -> raw artifact -> project occurrence
                 -> structured parse -> evidence-aware segmentation -> evidence units

Three requirements constrain this ordering and they do not all pull the same way, which is why
the pipeline is one object rather than three composable steps.

**SEC-003 / §14.5.** The scan runs *before* the bytes become addressable. A credential in a
content-addressed append-only store is permanently there; scanning afterwards can only report it.

**UX-004.** The raw artifact is durably stored *before* any parsing stage runs, so a parser
failure never requires re-upload. This pulls against SEC-003 -- one wants storage early, the
other wants it late -- and §17.22 resolves it: the scan comes first, and "durably stored" starts
immediately after it, not after parsing.

**OPS-004 / §12.3.** The artifact store and PostgreSQL are two stores with no transaction between
them. A failure in the middle must leave no dangling reference. There is no distributed
transaction here and none is faked: the sequence is stage -> commit rows -> promote, and a
failure at the last step compensates by removing the rows the commit added.

WHY THE STAGES ARE RECORDED EVEN WHEN THEY SUCCEED. §17.22's ``IngestionItem`` state is derived
from ``StageResult``s, never assigned. This module emits them; deriving the seven-state projection
from them is UX-001 and is a later slice. What matters here is that the results are real records
of what ran, so the projection has something truthful to derive from.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import (
    SecretScanStatus,
    SensitivityLabel,
    SourceOrigin,
)
from lab_brain.core.models.evidence_unit import EvidenceUnit
from lab_brain.core.models.identifiers import artifact_id_for, compute_content_hash, new_id
from lab_brain.ingestion.parsers.documents import MarkdownDocumentParser
from lab_brain.ingestion.parsers.structure import ParsedDocument
from lab_brain.ingestion.secret_scanner import SecretScanner, SecretScanResult
from lab_brain.ingestion.segmentation import EvidenceAwareSegmenter, SegmentationResult
from lab_brain.storage.artifacts.interface import ArtifactStore


class IngestionStage(StrEnum):
    """§17.22's stage vocabulary, restricted to the stages this slice runs.

    ``CLAIM_EXTRACT``, ``EMBED`` and ``INDEX`` are declared by §17.22 and deliberately absent:
    they belong to later M1 slices, and listing a stage this pipeline never runs would put a
    permanently PENDING result into every item's history.
    """

    SECRET_SCAN = "SECRET_SCAN"
    RAW_STORE = "RAW_STORE"
    PARSE_TEXT = "PARSE_TEXT"
    PARSE_TABLE = "PARSE_TABLE"
    PARSE_FIGURE = "PARSE_FIGURE"
    SEGMENT = "SEGMENT"


class StageStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PENDING = "PENDING"
    DEGRADED = "DEGRADED"


class ErrorClass(StrEnum):
    """§17.23's FROZEN five. Listed here because SEC-003's branch needs POLICY_BLOCK.

    §23.4 forbids adding a sixth without a maintainer decision, so the enum is closed and the
    full taxonomy's behaviour (retry policy, disclosure) is UX-002/UX-003 and a later slice.
    """

    USER_INPUT_ERROR = "USER_INPUT_ERROR"
    EXTRACTION_WARNING = "EXTRACTION_WARNING"
    POLICY_BLOCK = "POLICY_BLOCK"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


@dataclass(frozen=True)
class StageResult:
    """One stage's outcome (§17.22)."""

    stage: IngestionStage
    status: StageStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    output_refs: tuple[str, ...] = ()
    error_class: ErrorClass | None = None
    reason_code: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is StageStatus.SUCCEEDED


@dataclass
class IngestionOutcome:
    """What one ingestion produced, successful or not.

    Not a projection: §17.22's seven-state ``IngestionItem`` is derived from these results plus
    Job/Conflict/ReviewItem state, and deriving it is UX-001. This is the raw material.
    """

    item_id: str
    project_id: str
    stage_results: list[StageResult] = field(default_factory=list)
    artifact: Artifact | None = None
    occurrence: ArtifactOccurrence | None = None
    parsed: ParsedDocument | None = None
    segmentation: SegmentationResult | None = None
    scan: SecretScanResult | None = None
    quarantined: bool = False

    @property
    def evidence_units(self) -> tuple[EvidenceUnit, ...]:
        return self.segmentation.units if self.segmentation else ()

    def result_for(self, stage: IngestionStage) -> StageResult | None:
        for result in self.stage_results:
            if result.stage is stage:
                return result
        return None

    def ran(self, stage: IngestionStage) -> bool:
        return self.result_for(stage) is not None

    @property
    def raw_artifact_is_durable(self) -> bool:
        """UX-004: is the raw artifact retrievable regardless of what happened afterwards?"""
        result = self.result_for(IngestionStage.RAW_STORE)
        return result is not None and result.succeeded


class IngestionError(RuntimeError):
    """Ingestion failed in a way that left no partial state."""


class CompensationFailed(RuntimeError):
    """A compensating action failed. The inconsistency it was called to remove may remain.

    Separate from ``IngestionError`` because the operational response differs: an ingestion
    failure means retry, this means a human looks at two stores. OPS-004 requires the compensating
    path to be verified, and a compensator that fails silently would satisfy any test that only
    checked the happy path.
    """


@dataclass
class _ArtifactRecord:
    """The rows one ingestion commits, so compensation knows exactly what to undo."""

    artifact: Artifact
    occurrence: ArtifactOccurrence


class IngestionPipeline:
    """Runs the local ingestion vertical for one document.

    ``commit_rows`` and ``rollback_rows`` are injected rather than imported. The pipeline must
    work against both the in-memory repositories (AGT-007) and PostgreSQL, and -- more
    importantly -- OPS-004 requires the compensating path to be *exercised by fault injection*,
    which means the seam where the fault is injected has to be a parameter.
    """

    def __init__(
        self,
        store: ArtifactStore,
        commit_rows: Callable[[Artifact, ArtifactOccurrence], None],
        rollback_rows: Callable[[Artifact, ArtifactOccurrence], None],
        *,
        scanner: SecretScanner | None = None,
        parser: MarkdownDocumentParser | None = None,
        segmenter: EvidenceAwareSegmenter | None = None,
        quarantine: Callable[[bytes, SecretScanResult], None] | None = None,
    ) -> None:
        self._store = store
        self._commit_rows = commit_rows
        self._rollback_rows = rollback_rows
        self._scanner = scanner or SecretScanner()
        self._parser = parser or MarkdownDocumentParser()
        self._segmenter = segmenter or EvidenceAwareSegmenter()
        self._quarantine = quarantine

    def ingest(
        self,
        data: bytes,
        *,
        project_id: str,
        actor_id: str,
        sensitivity_label: SensitivityLabel,
        media_type: str = "text/markdown",
        uri: str,
        source_origin: SourceOrigin = SourceOrigin.UPLOAD,
        source_metadata: dict[str, str] | None = None,
    ) -> IngestionOutcome:
        outcome = IngestionOutcome(item_id=new_id("ingestion_item"), project_id=project_id)

        # --- 1. SECRET_SCAN, before anything becomes addressable (SEC-003) -----------------
        scan = self._run_secret_scan(data, outcome)
        if not scan.may_reach_normal_storage:
            return outcome

        # A redacted derivative is what gets stored, and it is a *different artifact* -- different
        # bytes, different hash, different id. §14.5's "quarantine/redaction" keeps the audit
        # linkage through the scan record, not by storing the original under the same identity.
        storable = scan.redacted_bytes if scan.redacted_bytes is not None else data

        # --- 2. RAW_STORE, before any parsing stage (UX-004), compensated (OPS-004) --------
        record = self._store_raw(
            storable,
            outcome,
            scan=scan,
            project_id=project_id,
            actor_id=actor_id,
            sensitivity_label=sensitivity_label,
            media_type=media_type,
            uri=uri,
            source_origin=source_origin,
        )
        if record is None:
            return outcome

        # From here on, every failure leaves the raw artifact durable and retrievable. That is
        # UX-004's whole point: a parser failure is a stage to retry, not an upload to redo.
        self._parse_and_segment(record, outcome, source_metadata=source_metadata)
        return outcome

    # -- stages -------------------------------------------------------------

    def _run_secret_scan(self, data: bytes, outcome: IngestionOutcome) -> SecretScanResult:
        started = utc_now()
        scan = self._scanner.scan(data)
        outcome.scan = scan

        if scan.status is SecretScanStatus.QUARANTINED:
            # BLOCKED, not FAILED (§17.22). The distinction is user-facing: a policy outcome is
            # actionable, a failure invites a retry that will do exactly the same thing.
            if self._quarantine is not None:
                self._quarantine(data, scan)
            outcome.quarantined = True
            outcome.stage_results.append(
                StageResult(
                    stage=IngestionStage.SECRET_SCAN,
                    status=StageStatus.FAILED,
                    started_at=started,
                    finished_at=utc_now(),
                    error_class=ErrorClass.POLICY_BLOCK,
                    reason_code="SEC003_SUSPECTED_CREDENTIAL",
                )
            )
            return scan

        outcome.stage_results.append(
            StageResult(
                stage=IngestionStage.SECRET_SCAN,
                # A redaction is a real change to the bytes the researcher supplied, so it is
                # reported as DEGRADED rather than SUCCEEDED. Silently returning success would
                # mean the stored document differs from the uploaded one with no signal.
                status=(
                    StageStatus.DEGRADED
                    if scan.status is SecretScanStatus.REDACTED
                    else StageStatus.SUCCEEDED
                ),
                started_at=started,
                finished_at=utc_now(),
                reason_code=(
                    "SEC003_REDACTED" if scan.status is SecretScanStatus.REDACTED else None
                ),
            )
        )
        return scan

    def _store_raw(
        self,
        data: bytes,
        outcome: IngestionOutcome,
        *,
        scan: SecretScanResult,
        project_id: str,
        actor_id: str,
        sensitivity_label: SensitivityLabel,
        media_type: str,
        uri: str,
        source_origin: SourceOrigin,
    ) -> _ArtifactRecord | None:
        """Stage bytes, commit rows, promote bytes. Compensate if the promotion fails.

        The order is the OPS-004 contract and the comments say which half is authoritative at
        each point, because getting it wrong is invisible in a passing test.
        """
        started = utc_now()
        staged = self._store.stage(data)

        artifact = Artifact(
            artifact_id=artifact_id_for(staged.content_hash),
            content_hash=staged.content_hash,
            media_type=media_type,
            uri=uri,
            source_origin=source_origin,
            actor_id=actor_id,
            secret_scan_status=scan.status,
        )
        occurrence = artifact.occurrence_in(
            project_id, sensitivity_label, ingested_by_actor_id=actor_id
        )

        try:
            self._commit_rows(artifact, occurrence)
        except Exception as exc:
            # Nothing has been promoted, so nothing references these bytes. Dropping the staged
            # blob is the whole compensation -- there is no dangling reference to clean up
            # because the reference was never committed.
            self._store.discard(staged.staging_id)
            outcome.stage_results.append(
                StageResult(
                    stage=IngestionStage.RAW_STORE,
                    status=StageStatus.FAILED,
                    started_at=started,
                    finished_at=utc_now(),
                    error_class=ErrorClass.SYSTEM_ERROR,
                    reason_code="OPS004_DB_COMMIT_FAILED",
                )
            )
            raise IngestionError(
                f"database commit failed during ingest; staged bytes discarded, no artifact row "
                f"exists: {exc}"
            ) from exc

        try:
            self._store.promote(staged.staging_id, staged.content_hash)
        except Exception as exc:
            # THE case OPS-004 is about. The database already says this artifact exists and the
            # bytes are not addressable, so a reader would resolve the row to nothing. Undo the
            # commit; if that also fails, say so loudly rather than returning a half state.
            try:
                self._rollback_rows(artifact, occurrence)
            except Exception as compensation_error:
                raise CompensationFailed(
                    f"artifact store promotion failed ({exc}) and the compensating database "
                    f"rollback also failed ({compensation_error}). Artifact "
                    f"{artifact.artifact_id} may have a row with no bytes -- two stores need "
                    "manual reconciliation"
                ) from compensation_error
            finally:
                self._store.discard(staged.staging_id)

            outcome.stage_results.append(
                StageResult(
                    stage=IngestionStage.RAW_STORE,
                    status=StageStatus.FAILED,
                    started_at=started,
                    finished_at=utc_now(),
                    error_class=ErrorClass.SYSTEM_ERROR,
                    reason_code="OPS004_PROMOTE_FAILED_COMPENSATED",
                )
            )
            raise IngestionError(
                f"artifact store promotion failed; database rows rolled back, no dangling "
                f"reference remains: {exc}"
            ) from exc

        outcome.artifact = artifact
        outcome.occurrence = occurrence
        outcome.stage_results.append(
            StageResult(
                stage=IngestionStage.RAW_STORE,
                status=StageStatus.SUCCEEDED,
                started_at=started,
                finished_at=utc_now(),
                output_refs=(artifact.artifact_id,),
            )
        )
        return _ArtifactRecord(artifact=artifact, occurrence=occurrence)

    def _parse_and_segment(
        self,
        record: _ArtifactRecord,
        outcome: IngestionOutcome,
        *,
        source_metadata: dict[str, str] | None,
    ) -> None:
        started = utc_now()
        try:
            text = self._store.open(record.artifact.content_hash).decode("utf-8")
            parsed = self._parser.parse(
                text,
                artifact_id=record.artifact.artifact_id,
                source_metadata=source_metadata,
            )
        except Exception:
            # UX-004: the raw artifact stays durable. The item is PARTIAL, not FAILED, and a
            # retry re-runs this stage against the stored bytes.
            outcome.stage_results.append(
                StageResult(
                    stage=IngestionStage.PARSE_TEXT,
                    status=StageStatus.FAILED,
                    started_at=started,
                    finished_at=utc_now(),
                    error_class=ErrorClass.EXTRACTION_WARNING,
                    reason_code="PARSE_TEXT_FAILED",
                )
            )
            return

        outcome.parsed = parsed
        from lab_brain.core.models.enums import EvidenceUnitType

        for stage, unit_type in (
            (IngestionStage.PARSE_TEXT, EvidenceUnitType.PROSE),
            (IngestionStage.PARSE_TABLE, EvidenceUnitType.TABLE),
            (IngestionStage.PARSE_FIGURE, EvidenceUnitType.FIGURE),
        ):
            blocks = parsed.blocks_of(unit_type)
            outcome.stage_results.append(
                StageResult(
                    stage=stage,
                    # SKIPPED, not SUCCEEDED, when the document has none. §17.22 derives PARTIAL
                    # from "at least one value-producing stage failed", and a SUCCEEDED stage that
                    # produced nothing makes that derivation read a no-op as a result.
                    status=StageStatus.SUCCEEDED if blocks else StageStatus.SKIPPED,
                    started_at=started,
                    finished_at=utc_now(),
                    output_refs=tuple(block.structural_key for block in blocks),
                )
            )

        segment_started = utc_now()
        try:
            segmentation = self._segmenter.segment(parsed, project_id=outcome.project_id)
        except Exception:
            outcome.stage_results.append(
                StageResult(
                    stage=IngestionStage.SEGMENT,
                    status=StageStatus.FAILED,
                    started_at=segment_started,
                    finished_at=utc_now(),
                    error_class=ErrorClass.EXTRACTION_WARNING,
                    reason_code="SEGMENT_FAILED",
                )
            )
            return

        outcome.segmentation = segmentation
        outcome.stage_results.append(
            StageResult(
                stage=IngestionStage.SEGMENT,
                status=StageStatus.SUCCEEDED,
                started_at=segment_started,
                finished_at=utc_now(),
                output_refs=tuple(unit.evidence_unit_id for unit in segmentation.units),
            )
        )


def redacted_derivative_of(original: bytes, redacted: bytes) -> tuple[str, str]:
    """``(original_hash, redacted_hash)`` — the audit linkage §26's T-SEC-003 asks for.

    The redacted file is a different artifact with a different identity, and the link between it
    and what was received is the pair of hashes. Recording it as a function rather than a comment
    so a test can assert the linkage rather than the intention.
    """
    return compute_content_hash(original), compute_content_hash(redacted)


__all__ = [
    "CompensationFailed",
    "ErrorClass",
    "IngestionError",
    "IngestionOutcome",
    "IngestionPipeline",
    "IngestionStage",
    "StageResult",
    "StageStatus",
    "redacted_derivative_of",
]
