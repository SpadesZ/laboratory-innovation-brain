"""Ingestion — local source to canonical evidence units (M1).

    local source -> secret scan -> raw artifact -> project occurrence
                 -> structured parse -> evidence-aware segmentation -> evidence units
                 -> scientific evidence admission

The ordering is three requirements at once and they do not all pull the same way: SEC-003 wants
the scan before anything is addressable, UX-004 wants the raw artifact durable before any parser
runs, and OPS-004 wants the two stores compensated as one unit of work. ``pipeline`` is where
they are reconciled, and §17.22's ordering rule is the resolution.

``FixedTokenBaselineSegmenter`` is deliberately NOT re-exported here. It exists for T-EVI-010's
comparison and its output is refused by the admission gate; importing it from this namespace
would make it look like an alternative to ``EvidenceAwareSegmenter``, which §6.22 rule 3 says it
is not.
"""

from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    EvidenceAdmissionGate,
    RefusalReason,
)
from lab_brain.ingestion.parsers import MarkdownDocumentParser, ParsedBlock, ParsedDocument
from lab_brain.ingestion.pipeline import (
    IngestionError,
    IngestionOutcome,
    IngestionPipeline,
    IngestionStage,
    StageResult,
    StageStatus,
)
from lab_brain.ingestion.reverification import SegmentationReverifier
from lab_brain.ingestion.secret_scanner import SecretScanner, SecretScanResult
from lab_brain.ingestion.segmentation import (
    EvidenceAwareSegmenter,
    SegmentationError,
    SegmentationResult,
)
from lab_brain.ingestion.source_work_resolution import (
    SourceWorkResolution,
    SourceWorkResolver,
    WorkMatchBasis,
)

__all__ = [
    "AdmissionRefusal",
    "EvidenceAdmissionGate",
    "EvidenceAwareSegmenter",
    "IngestionError",
    "IngestionOutcome",
    "IngestionPipeline",
    "IngestionStage",
    "MarkdownDocumentParser",
    "ParsedBlock",
    "ParsedDocument",
    "RefusalReason",
    "SecretScanResult",
    "SecretScanner",
    "SegmentationError",
    "SegmentationResult",
    "SegmentationReverifier",
    "SourceWorkResolution",
    "SourceWorkResolver",
    "StageResult",
    "StageStatus",
    "WorkMatchBasis",
]
