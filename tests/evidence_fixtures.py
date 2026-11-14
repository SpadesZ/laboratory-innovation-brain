"""The locked T-EVI-010 fixture, and the helpers that load it.

§26's row requires a **fixed, locked** fixture: the pass condition is per case, and a fixture
that drifted would make the expected outcomes unfalsifiable. The document lives at
``fixtures/evidence/rs_anomaly_report.md`` and is loaded rather than constructed, so the same
bytes drive the contract tests, the e2e story and the benchmark report.

``test_the_fixture_is_locked`` pins its digest. Editing the document is allowed -- it is a
fixture, not a contract -- but doing so fails that test with the new digest, so a change to what
the benchmark measures cannot happen silently as a side effect of an unrelated edit.

Deliberately not a conftest fixture: the benchmark runner is a script, not a pytest session, and
it must read the same document by the same code path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from lab_brain.core.models.identifiers import artifact_id_for, compute_content_hash
from lab_brain.ingestion.parsers.documents import MarkdownDocumentParser
from lab_brain.ingestion.parsers.structure import ParsedDocument
from lab_brain.ingestion.segmentation import EvidenceAwareSegmenter, SegmentationResult

#: Case (a). The two sentences that are individually well-formed and jointly required. Quoted
#: exactly as the fixture states them, so a test asserting they travelled together is asserting
#: about the document rather than about a paraphrase.
CONDITION_SENTENCE = "Reverse bias increased from 0 to -2 V."
RESULT_SENTENCE = "The junction capacitance decreased from 0.515 to 0.345 pF/mm."

#: Case (e). Two scientific values the document explicitly does not record. An extractor that
#: supplies a typical implant dose or a plausible wafer id has invented evidence (EVI-002).
MISSING_FIELDS = ("wafer_identifier", "implant_dose")

FIXTURE_NAME = "rs_anomaly_report.md"


def fixtures_root() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "evidence"


@lru_cache(maxsize=1)
def load_fixture_document() -> str:
    path = fixtures_root() / FIXTURE_NAME
    if not path.is_file():
        raise FileNotFoundError(f"locked T-EVI-010 fixture not found at {path}")
    # newline="" would preserve CRLF on Windows and change the digest by platform, which would
    # make "the fixture is locked" a statement about the checkout rather than the content.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def fixture_bytes() -> bytes:
    return load_fixture_document().encode("utf-8")


def fixture_digest() -> str:
    return compute_content_hash(fixture_bytes())


def fixture_artifact_id() -> str:
    return artifact_id_for(fixture_digest())


def parse_fixture() -> ParsedDocument:
    return MarkdownDocumentParser().parse(
        load_fixture_document(), artifact_id=fixture_artifact_id()
    )


def segment_fixture(*, token_limit: int | None = None) -> SegmentationResult:
    segmenter = (
        EvidenceAwareSegmenter(token_limit=token_limit)
        if token_limit is not None
        else EvidenceAwareSegmenter()
    )
    return segmenter.segment(parse_fixture())


__all__ = [
    "CONDITION_SENTENCE",
    "FIXTURE_NAME",
    "MISSING_FIELDS",
    "RESULT_SENTENCE",
    "fixture_artifact_id",
    "fixture_bytes",
    "fixture_digest",
    "fixtures_root",
    "load_fixture_document",
    "parse_fixture",
    "segment_fixture",
]
