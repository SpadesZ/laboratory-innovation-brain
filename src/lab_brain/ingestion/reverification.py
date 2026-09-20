"""Re-derive an artifact's evidence units, so admission can verify rather than trust.

SPEC-ISSUE-015's semantic layer, and the reason it can exist at all:

    the artifact is content-addressed   -> its bytes are pinned by its identity
    the segmenter is deterministic      -> the same bytes always give the same units
    parser/segmenter versions are on
      every unit's provenance           -> "which segmenter" is not a guess

Therefore *what segmentation produces from this artifact* is computable at admission time, and a
unit that is not among the answers was written by something other than the path it claims. No
component has to read the prose to establish that -- which is what makes this the honest answer
where a SQL-side check would have meant a second, drifting copy of the segmenter (`v3.3-a13`).

WHAT THIS IS NOT. A cache, and not an optimisation. It re-parses on every call by design. A cache
keyed on `(artifact_id, parser_version, segmenter_version)` is the available mitigation if the
cost ever matters, and ADR-0012 records that it must remain a cache *of the re-derivation* rather
than becoming trust in the stored witness -- which would delete this layer and restore the issue.
"""

from __future__ import annotations

from collections.abc import Callable

from lab_brain.core.models.evidence_unit import EvidenceUnit
from lab_brain.ingestion.parsers.documents import MarkdownDocumentParser
from lab_brain.ingestion.segmentation import EvidenceAwareSegmenter


class SegmentationReverifier:
    """Re-runs parse + segmentation over an artifact's own bytes.

    Returns ``None`` -- never an empty tuple -- when the bytes cannot be loaded, because the two
    mean opposite things to the caller: "this document genuinely yields no evidence units" is a
    verdict, "we could not check" is a refusal. Collapsing them would let an unreachable artifact
    store read as a document with no evidence, and the admission gate would refuse for the wrong
    reason with the wrong remedy.
    """

    def __init__(
        self,
        load_bytes: Callable[[str], bytes | None],
        *,
        parser: MarkdownDocumentParser | None = None,
        segmenter: EvidenceAwareSegmenter | None = None,
    ) -> None:
        self._load_bytes = load_bytes
        self._parser = parser or MarkdownDocumentParser()
        self._segmenter = segmenter or EvidenceAwareSegmenter()

    def __call__(self, artifact_id: str) -> tuple[EvidenceUnit, ...] | None:
        try:
            raw = self._load_bytes(artifact_id)
        except Exception:
            # A store that raises and a store that returns None are the same fact to the gate:
            # the check could not be performed. Swallowing the exception here keeps that fact from
            # arriving as an unrelated 500 halfway up the admission path.
            return None
        if raw is None:
            return None

        try:
            document = self._parser.parse(raw.decode("utf-8"), artifact_id=artifact_id)
            return self._segmenter.segment(document).units
        except Exception:
            # A document that no longer parses cannot be used to verify anything. Refusing is the
            # only safe reading: "the parser broke" must not become "the unit is fine".
            return None


__all__ = ["SegmentationReverifier"]
