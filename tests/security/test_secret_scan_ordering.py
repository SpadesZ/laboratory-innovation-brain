"""T-SEC-003 — secret scanning before immutable ingest (SEC-003, §14.5, §17.22).

Pass condition (§26):

    fixture secret is quarantined before immutable normal ingest; redacted derivative preserves
    audit linkage.

THE ORDERING IS THE REQUIREMENT, and the test has to prove the order rather than the outcome. A
pipeline that stored the bytes and then quarantined them would leave the store in exactly the
same visible state as one that never stored them -- except that a content-addressed append-only
store still holds the credential. So the assertions below are about what the store contains and
what it never contained, not about the status the item ends up with.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import SecretScanStatus, SensitivityLabel
from lab_brain.ingestion.pipeline import (
    ErrorClass,
    IngestionPipeline,
    IngestionStage,
    StageStatus,
    redacted_derivative_of,
)
from lab_brain.ingestion.secret_scanner import REDACTION, SecretScanner
from lab_brain.storage.artifacts.local import InMemoryArtifactStore

PROJECT = "prj:test"
ACTOR = "act:test"

CLEAN = b"# Report\n\nReverse bias increased from 0 to -2 V.\n"

PRIVATE_KEY = (
    b"# Deployment notes\n\n"
    b"-----BEGIN RSA PRIVATE KEY-----\n"
    b"MIIEowIBAAKCAQEAwJqxT7ZkR9vQ1example0key0material0not0real0at0all\n"
    b"-----END RSA PRIVATE KEY-----\n"
)

INLINE_TOKEN = (
    b"# Setup\n\n"
    b"Connect with api_key = 'sk_live_abcdef0123456789abcdef' before running the sweep.\n"
)


def _pipeline(store: InMemoryArtifactStore, rows: dict, quarantined: list):
    return IngestionPipeline(
        store,
        commit_rows=lambda artifact, occurrence: rows.__setitem__(
            artifact.artifact_id, (artifact, occurrence)
        ),
        rollback_rows=lambda artifact, _: rows.pop(artifact.artifact_id, None),
        quarantine=lambda data, scan: quarantined.append((data, scan)),
    )


def _ingest(data: bytes, store=None, rows=None, quarantined=None):
    store = store if store is not None else InMemoryArtifactStore()
    rows = rows if rows is not None else {}
    quarantined = quarantined if quarantined is not None else []
    outcome = _pipeline(store, rows, quarantined).ingest(
        data,
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///notes.md",
    )
    return outcome, store, rows, quarantined


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_a_suspected_credential_never_reaches_permanent_storage():
    """The load-bearing assertion: the store is empty, and no row references anything.

    Not "the item is BLOCKED" -- a pipeline that stored first and flagged after would also be
    BLOCKED, and the credential would be permanently in a content-addressed append-only store.
    """
    outcome, store, rows, quarantined = _ingest(PRIVATE_KEY)

    assert store.list_staged() == (), "a staged blob was left behind holding the credential"
    assert rows == {}, "a database row was written for a quarantined artifact"
    assert outcome.artifact is None
    assert len(quarantined) == 1


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_no_parsing_stage_runs_after_a_quarantine():
    """§17.22's ordering: quarantine replaces RAW_STORE, it does not follow it."""
    outcome, _, _, _ = _ingest(PRIVATE_KEY)

    assert outcome.ran(IngestionStage.SECRET_SCAN)
    for stage in (
        IngestionStage.RAW_STORE,
        IngestionStage.PARSE_TEXT,
        IngestionStage.PARSE_TABLE,
        IngestionStage.PARSE_FIGURE,
        IngestionStage.SEGMENT,
    ):
        assert not outcome.ran(stage), f"{stage} ran after the scan quarantined the file"
    assert outcome.evidence_units == ()


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_the_secret_scan_is_the_first_stage_recorded():
    """Ordering asserted positionally, so reordering the pipeline fails here."""
    outcome, _, _, _ = _ingest(CLEAN)
    assert outcome.stage_results[0].stage is IngestionStage.SECRET_SCAN
    assert outcome.stage_results[1].stage is IngestionStage.RAW_STORE


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_a_quarantine_is_a_policy_block_not_a_failure():
    """§17.22: it surfaces as BLOCKED, not FAILED.

    User-facing and load-bearing: POLICY_BLOCK is actionable and must not be auto-retried
    (UX-002), while FAILED invites a retry that would do exactly the same thing.
    """
    outcome, _, _, _ = _ingest(PRIVATE_KEY)
    scan_result = outcome.result_for(IngestionStage.SECRET_SCAN)
    assert scan_result is not None
    assert scan_result.error_class is ErrorClass.POLICY_BLOCK
    assert scan_result.reason_code == "SEC003_SUSPECTED_CREDENTIAL"


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_a_redacted_derivative_is_stored_and_the_secret_is_not():
    """A redactable finding is removed and the rest of the document survives."""
    outcome, store, _, quarantined = _ingest(INLINE_TOKEN)

    assert quarantined == []
    assert outcome.artifact is not None
    assert outcome.artifact.secret_scan_status is SecretScanStatus.REDACTED

    stored = store.open(outcome.artifact.content_hash)
    assert b"sk_live_abcdef0123456789abcdef" not in stored
    assert REDACTION.encode() in stored
    assert b"before running the sweep" in stored, "redaction removed more than the credential"


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_the_redacted_derivative_preserves_audit_linkage():
    """§26's second clause. The derivative is a different artifact; the link is the hash pair."""
    outcome, _, _, _ = _ingest(INLINE_TOKEN)
    assert outcome.artifact is not None
    assert outcome.scan is not None

    original_hash, redacted_hash = redacted_derivative_of(
        INLINE_TOKEN, outcome.scan.redacted_bytes or b""
    )
    assert original_hash != redacted_hash
    assert outcome.artifact.content_hash == redacted_hash, (
        "the stored artifact is not the redacted derivative"
    )
    assert outcome.scan.findings, "the scan recorded no finding to link the redaction to"
    assert all(
        finding.pattern_name and finding.end_offset > finding.start_offset
        for finding in outcome.scan.findings
    )


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_a_finding_never_carries_the_secret_itself():
    """Putting the match into the finding re-leaks it through the machinery that reports it."""
    result = SecretScanner().scan(INLINE_TOKEN)
    for finding in result.findings:
        assert "sk_live" not in repr(finding)


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_one_unredactable_finding_quarantines_the_whole_file():
    """Redacting the rest would store a file whose reason for existing cannot be removed."""
    mixed = PRIVATE_KEY + b"\napi_key = 'sk_live_abcdef0123456789abcdef'\n"
    result = SecretScanner().scan(mixed)
    assert result.status is SecretScanStatus.QUARANTINED
    assert not result.may_reach_normal_storage
    assert result.redacted_bytes is None


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_a_clean_document_passes_through_untouched():
    """The positive control. Without it every test above passes on a scanner that refuses all."""
    outcome, store, _, quarantined = _ingest(CLEAN)

    assert quarantined == []
    assert outcome.artifact is not None
    assert outcome.artifact.secret_scan_status is SecretScanStatus.CLEAN
    assert store.open(outcome.artifact.content_hash) == CLEAN
    assert outcome.result_for(IngestionStage.SECRET_SCAN).status is StageStatus.SUCCEEDED


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_a_redaction_is_reported_as_degraded_not_as_success():
    """The stored document differs from the uploaded one; a silent SUCCEEDED hides that."""
    outcome, _, _, _ = _ingest(INLINE_TOKEN)
    result = outcome.result_for(IngestionStage.SECRET_SCAN)
    assert result is not None
    assert result.status is StageStatus.DEGRADED
    assert result.reason_code == "SEC003_REDACTED"


@pytest.mark.requirement("SEC-003")
@pytest.mark.spec_test("T-SEC-003")
def test_binary_content_is_not_blocked_by_a_text_scanner():
    """A binary simulation output has no text to hold a credential in these shapes.

    Failing it would block the most common artifact in the lab; the honest statement is that
    this scanner does not cover binary, not that binary is suspicious.
    """
    result = SecretScanner().scan(b"\x00\x01\x02\xff\xfe binary sweep output")
    assert result.status is SecretScanStatus.CLEAN
