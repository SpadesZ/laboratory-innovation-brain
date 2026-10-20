"""T-OPS-004 / T-UX-004 — the cross-store unit of work, and raw-artifact-first.

Pass conditions (§26):

    T-OPS-004  fault injection between the artifact-store write and the database commit leaves no
               dangling artifact reference; the compensating path is exercised and the partial
               state is either completed or removed.
    T-UX-004   Parser-failure fixture leaves a retrievable raw artifact; stage retry re-runs only
               the failed stage, reusing raw_artifact_id.

§26 types T-OPS-004 as *integration* and its subject is the seam between two stores, not
PostgreSQL specifically. These run backend-free so the AGT-007 guarantee covers them, and the
same compensation is exercised against real PostgreSQL in
``tests/e2e/test_ingestion_vertical_postgres.py``.

THE FAULT IS INJECTED, NOT SIMULATED. OPS-004 says the compensating path MUST be verified by
fault injection, so these tests make a real call fail and let the pipeline respond, rather than
calling the compensator directly and asserting it works. A compensator that is never reached by
a failure is not a verified compensating path.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import SensitivityLabel
from lab_brain.ingestion.pipeline import (
    CompensationFailed,
    IngestionError,
    IngestionPipeline,
    IngestionStage,
    StageStatus,
)
from lab_brain.storage.artifacts.interface import ArtifactStoreError
from lab_brain.storage.artifacts.local import InMemoryArtifactStore

PROJECT = "prj:test"
ACTOR = "act:test"

DOCUMENT = b"# 3. Bias\n\nReverse bias increased from 0 to -2 V. Cj decreased to 0.345 pF/mm.\n"

# Deliberately NO module-level `postgres` marker, unlike every other file in this directory.
# OPS-004's subject is the seam between two stores, and the failure it governs happens *before*
# either store commits -- so gating these behind a database would mean the AGT-007 backend-free
# run, the one that proves the suite is verifiable without infrastructure, never exercises the
# compensating path at all. The same compensation runs against real PostgreSQL in
# tests/e2e/test_ingestion_vertical_postgres.py.


class _Rows:
    """A stand-in for the PostgreSQL side, with the two failure modes OPS-004 names."""

    def __init__(self) -> None:
        self.committed: dict[str, tuple] = {}
        self.fail_commit = False
        self.fail_rollback = False
        self.rollback_calls = 0

    def commit(self, artifact, occurrence) -> None:
        if self.fail_commit:
            raise RuntimeError("injected database commit failure")
        self.committed[artifact.artifact_id] = (artifact, occurrence)

    def rollback(self, artifact, occurrence) -> None:
        self.rollback_calls += 1
        if self.fail_rollback:
            raise RuntimeError("injected rollback failure")
        self.committed.pop(artifact.artifact_id, None)


def _ingest(store: InMemoryArtifactStore, rows: _Rows, **overrides):
    pipeline = IngestionPipeline(store, rows.commit, rows.rollback, **overrides)
    return pipeline.ingest(
        DOCUMENT,
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///report.md",
    )


# ---------------------------------------------------------------------------
# OPS-004 — no dangling reference in either direction
# ---------------------------------------------------------------------------


@pytest.mark.requirement("OPS-004")
@pytest.mark.spec_test("T-OPS-004")
def test_a_failed_database_commit_leaves_no_staged_blob():
    """Failure before the authoritative moment. Nothing ever referenced these bytes."""
    store, rows = InMemoryArtifactStore(), _Rows()
    rows.fail_commit = True

    with pytest.raises(IngestionError, match="staged bytes discarded"):
        _ingest(store, rows)

    assert store.list_staged() == (), "a staged blob survived a failed commit"
    assert rows.committed == {}


@pytest.mark.requirement("OPS-004")
@pytest.mark.spec_test("T-OPS-004")
def test_a_failed_promotion_rolls_the_database_back():
    """THE case OPS-004 is about, and the harder direction.

    The commit has already happened, so the database says the artifact exists while the bytes are
    not addressable. A reader would resolve the row to nothing -- which is a dangling reference
    that reads as admitted evidence. The rows must go.
    """
    store, rows = InMemoryArtifactStore(), _Rows()
    store.fail_next_promote = True

    with pytest.raises(IngestionError, match="no dangling reference remains"):
        _ingest(store, rows)

    assert rows.rollback_calls == 1, "the compensating path was not exercised"
    assert rows.committed == {}, "a database row survived a failed promotion"
    assert store.list_staged() == (), "the staged blob was not discarded after compensation"


@pytest.mark.requirement("OPS-004")
@pytest.mark.spec_test("T-OPS-004")
def test_a_failed_compensation_is_reported_rather_than_swallowed():
    """A compensator that can fail silently makes "no dangling reference" conditional.

    This is the one state the system cannot repair itself, so it must be loud: a distinct
    exception type, naming the artifact, saying two stores need reconciliation.
    """
    store, rows = InMemoryArtifactStore(), _Rows()
    store.fail_next_promote = True
    rows.fail_rollback = True

    with pytest.raises(CompensationFailed, match="manual reconciliation"):
        _ingest(store, rows)

    assert rows.rollback_calls == 1
    # The staged blob is still discarded -- the `finally` runs even when compensation raises.
    assert store.list_staged() == ()


@pytest.mark.requirement("OPS-004")
@pytest.mark.spec_test("T-OPS-004")
def test_discard_is_total_and_idempotent():
    """The compensating action must not be able to fail, or the compensation can fail."""
    store = InMemoryArtifactStore()
    staged = store.stage(b"some bytes")
    store.discard(staged.staging_id)
    store.discard(staged.staging_id)  # again: must not raise
    store.discard("stg:never-existed")  # never staged: must not raise
    assert store.list_staged() == ()


@pytest.mark.requirement("OPS-004")
@pytest.mark.spec_test("T-OPS-004")
def test_promotion_refuses_bytes_that_do_not_hash_to_the_named_identity():
    """The database row names a content hash; promotion must not attach other bytes to it."""
    store = InMemoryArtifactStore()
    staged = store.stage(b"the real bytes")
    with pytest.raises(ArtifactStoreError, match="hashes to"):
        store.promote(staged.staging_id, "sha256:" + "0" * 64)


@pytest.mark.requirement("OPS-004")
@pytest.mark.spec_test("T-OPS-004")
def test_a_successful_ingest_leaves_no_staged_blob_and_a_resolvable_row():
    """The positive control: both stores agree, and the staging area is empty."""
    store, rows = InMemoryArtifactStore(), _Rows()
    outcome = _ingest(store, rows)

    assert outcome.artifact is not None
    assert store.list_staged() == ()
    assert outcome.artifact.artifact_id in rows.committed
    assert store.exists(outcome.artifact.content_hash)
    assert rows.rollback_calls == 0


# ---------------------------------------------------------------------------
# UX-004 — the raw artifact is durable before any parser runs
# ---------------------------------------------------------------------------


@pytest.mark.requirement("UX-004")
@pytest.mark.spec_test("T-UX-004")
def test_a_parser_failure_leaves_a_retrievable_raw_artifact():
    """The whole point of UX-004: a parser failure is a stage to retry, not an upload to redo."""

    class _BrokenParser:
        parser_id = "broken"
        parser_version = "0.0.0"

        def parse(self, *args, **kwargs):
            raise RuntimeError("injected parser failure")

    store, rows = InMemoryArtifactStore(), _Rows()
    outcome = _ingest(store, rows, parser=_BrokenParser())

    assert outcome.raw_artifact_is_durable, "the raw artifact is not durable after a parse failure"
    assert outcome.artifact is not None
    assert store.open(outcome.artifact.content_hash) == DOCUMENT
    assert outcome.artifact.artifact_id in rows.committed

    parse_result = outcome.result_for(IngestionStage.PARSE_TEXT)
    assert parse_result is not None
    assert parse_result.status is StageStatus.FAILED
    assert outcome.evidence_units == ()


@pytest.mark.requirement("UX-004")
@pytest.mark.spec_test("T-UX-004")
def test_raw_store_precedes_every_parsing_stage():
    """Asserted positionally, so reordering the pipeline fails here rather than in production."""
    store, rows = InMemoryArtifactStore(), _Rows()
    outcome = _ingest(store, rows)

    order = [result.stage for result in outcome.stage_results]
    raw_at = order.index(IngestionStage.RAW_STORE)
    for stage in (
        IngestionStage.PARSE_TEXT,
        IngestionStage.PARSE_TABLE,
        IngestionStage.PARSE_FIGURE,
        IngestionStage.SEGMENT,
    ):
        assert order.index(stage) > raw_at, f"{stage} ran before RAW_STORE"


@pytest.mark.requirement("UX-004")
@pytest.mark.spec_test("T-UX-004")
def test_a_retry_reuses_the_stored_bytes_rather_than_requiring_re_upload():
    """ "Retry resumes at the failed stage reusing raw_artifact_id, never requiring re-upload."

    Modelled at the seam this slice owns: the parse stage reads from the artifact store, so the
    bytes needed to re-run it are already there and the same ``artifact_id`` addresses them. The
    Job-level resume that drives the retry is OPS-001 and is a later slice.
    """
    from lab_brain.ingestion.parsers.documents import MarkdownDocumentParser
    from lab_brain.ingestion.segmentation import EvidenceAwareSegmenter

    class _FailsOnce:
        parser_id = "flaky"
        parser_version = "1.0.0"

        def __init__(self) -> None:
            self.calls = 0
            self._real = MarkdownDocumentParser()

        def parse(self, text, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("injected transient parser failure")
            return self._real.parse(text, **kwargs)

    store, rows = InMemoryArtifactStore(), _Rows()
    parser = _FailsOnce()
    first = _ingest(store, rows, parser=parser)
    assert first.artifact is not None
    assert first.evidence_units == ()

    # The retry: same bytes, read back out of the store by the id the first attempt recorded.
    retried_text = store.open(first.artifact.content_hash).decode("utf-8")
    parsed = parser.parse(retried_text, artifact_id=first.artifact.artifact_id)
    units = EvidenceAwareSegmenter().segment(parsed).units

    assert parser.calls == 2
    assert units, "the retry produced no evidence units"
    assert all(unit.artifact_id == first.artifact.artifact_id for unit in units), (
        "the retry produced units against a different artifact id, so the raw artifact was not "
        "reused"
    )


@pytest.mark.requirement("UX-004")
@pytest.mark.spec_test("T-UX-004")
def test_a_secret_scan_quarantine_surfaces_as_blocked_not_failed():
    """§26's T-UX-004 names this case explicitly, and it interacts with SEC-003's ordering."""
    from lab_brain.ingestion.pipeline import ErrorClass

    store, rows = InMemoryArtifactStore(), _Rows()
    pipeline = IngestionPipeline(store, rows.commit, rows.rollback)
    outcome = pipeline.ingest(
        b"-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n",
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///key.md",
    )
    scan = outcome.result_for(IngestionStage.SECRET_SCAN)
    assert scan is not None
    assert scan.error_class is ErrorClass.POLICY_BLOCK
    assert not outcome.raw_artifact_is_durable
    assert rows.committed == {}
