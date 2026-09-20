"""The fixed-token baseline — §6.22 rule 3(b), and nothing else.

THIS IS NOT A SEGMENTER. It exists so T-EVI-010 can report what the prohibited strategy would
have produced on the same locked fixture, and so the claim "structure-first is better here" is a
measurement rather than an assertion.

Three things keep it from becoming a usable alternative, and all three are deliberate:

  * every unit it emits carries ``subdivision_reason = BENCHMARK_BASELINE``, which the admission
    gate refuses outright (see ``admission_gate``). A baseline unit cannot become evidence.
  * it takes a ``BaselineRun`` marker argument that has no other caller and no default, so
    reaching this code from the ingestion path requires writing the word "baseline" there.
  * it is not exported from ``lab_brain.ingestion``'s namespace alongside the real segmenter.

The point of measuring it at all is that the two strategies are hard to tell apart by ordinary
retrieval metrics -- recall and precision over well-formed questions are largely insensitive to
whether conditions travelled with their result, because the retriever usually surfaces the
neighbouring chunk anyway. So the benchmark reports boundary-level metrics where they differ
sharply, and reports the ordinary ones beside them to show that they do not.
"""

from __future__ import annotations

from dataclasses import dataclass

from lab_brain.core.models.enums import EvidenceUnitType, SubdivisionReason
from lab_brain.core.models.evidence_unit import (
    EvidenceUnit,
    SegmenterProvenance,
    SourceLocator,
)
from lab_brain.ingestion.parsers.structure import ParsedDocument
from lab_brain.ingestion.segmentation import token_count

BASELINE_SEGMENTER_ID = "fixed_token_baseline"
BASELINE_SEGMENTER_VERSION = "1.0.0"

#: The conventional defaults, chosen to be representative rather than flattering: ~200 tokens
#: with ~15% overlap is what a default RAG pipeline does. Making the baseline weak would make the
#: comparison meaningless in the direction that matters.
BASELINE_WINDOW_TOKENS = 200
BASELINE_OVERLAP_TOKENS = 30


@dataclass(frozen=True)
class BaselineRun:
    """Explicit marker that a caller means to produce baseline units, not evidence.

    A bare boolean would be defaultable and a string would be typo-able. This has one field, no
    default, and a name that says what it is -- so the ingestion pipeline cannot reach the
    baseline path without a reviewer seeing it in the diff.
    """

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("a baseline run must state why it is being produced")


class FixedTokenBaselineSegmenter:
    """Cut every N tokens with M tokens of overlap, ignoring document structure entirely."""

    def __init__(
        self,
        window: int = BASELINE_WINDOW_TOKENS,
        overlap: int = BASELINE_OVERLAP_TOKENS,
    ) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        if not 0 <= overlap < window:
            raise ValueError(f"overlap must be in [0, {window}), got {overlap}")
        self._window = window
        self._overlap = overlap

    def segment(self, document: ParsedDocument, *, run: BaselineRun) -> tuple[EvidenceUnit, ...]:
        """Produce baseline units from the document's flat text.

        Note what is thrown away: section paths, table headers, figure captions, block types.
        That is the strategy, not an omission -- a fixed-token splitter reads a document as a
        string of tokens, and modelling it any more kindly would understate the difference the
        benchmark is measuring.
        """
        if not run.reason.strip():
            raise ValueError("BaselineRun.reason must be stated")

        provenance = SegmenterProvenance(
            segmenter_id=BASELINE_SEGMENTER_ID,
            segmenter_version=BASELINE_SEGMENTER_VERSION,
            parser_id=document.parser_id,
            parser_version=document.parser_version,
            token_limit=self._window,
        )

        flat = "\n".join(block.text for block in document.blocks)
        tokens = flat.split()
        if not tokens:
            return ()

        units: list[EvidenceUnit] = []
        step = self._window - self._overlap
        position = 0
        index = 0
        while position < len(tokens):
            body = " ".join(tokens[position : position + self._window])
            path = f"_/baseline:{index}"
            units.append(
                EvidenceUnit.build(
                    artifact_id=document.artifact_id,
                    # Everything is PROSE: the splitter has no idea a table was a table, which is
                    # itself one of the findings the benchmark reports.
                    unit_type=EvidenceUnitType.PROSE,
                    structural_path=path,
                    locator=SourceLocator(label=f"tokens {position}-{position + self._window}"),
                    body=body,
                    provenance=provenance,
                    parent_unit_id=f"evu:baseline:{document.artifact_id}",
                    subdivision_index=index,
                    subdivision_reason=SubdivisionReason.BENCHMARK_BASELINE,
                )
            )
            if position + self._window >= len(tokens):
                break
            position += step
            index += 1
        return tuple(units)

    @property
    def window(self) -> int:
        return self._window

    @property
    def overlap(self) -> int:
        return self._overlap


def baseline_token_profile(units: tuple[EvidenceUnit, ...]) -> tuple[int, int, int]:
    """``(min, median, max)`` token counts — reported so the baseline's shape is visible."""
    if not units:
        return (0, 0, 0)
    counts = sorted(token_count(unit.body) for unit in units)
    return (counts[0], counts[len(counts) // 2], counts[-1])


__all__ = [
    "BASELINE_OVERLAP_TOKENS",
    "BASELINE_SEGMENTER_ID",
    "BASELINE_SEGMENTER_VERSION",
    "BASELINE_WINDOW_TOKENS",
    "BaselineRun",
    "FixedTokenBaselineSegmenter",
    "baseline_token_profile",
]
