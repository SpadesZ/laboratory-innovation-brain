"""T-ART-001 — content-addressed artifact identity (ART-001).

Pass condition (§26):

    同一 bytes 得到同一 content hash/artifact identity；修改 1 byte 必須產生新
    artifact_id/hash；若同一人類文件 lineage，lineage_revision 遞增並保留
    previous_artifact_id。

Three claims, each tested directly: identity is a function of content, it is sensitive to a
single byte, and human versioning is expressed by lineage without disturbing either.
"""

from __future__ import annotations

import io

import pytest
from pydantic import ValidationError

from lab_brain.core.models import (
    Artifact,
    ArtifactOccurrence,
    ContentHashError,
    SecretScanStatus,
    SensitivityLabel,
    SourceOrigin,
    artifact_id_for,
    compute_content_hash,
    compute_content_hash_from_path,
    compute_content_hash_from_stream,
    content_hash_for,
)
from tests.conftest_fixtures import make_artifact


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_same_bytes_yield_the_same_identity():
    """Identity is a function of content, so metadata differences cannot split it."""
    first = make_artifact(b"identical payload", uri="file:///a.bin")
    second = make_artifact(
        b"identical payload",
        uri="file:///elsewhere/b.bin",
        media_type="text/plain",
        author_or_device="another machine",
    )
    assert first.content_hash == second.content_hash
    assert first.artifact_id == second.artifact_id


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_one_byte_difference_yields_a_new_identity():
    original = make_artifact(b"payload-A")
    mutated = make_artifact(b"payload-B")
    assert original.content_hash != mutated.content_hash
    assert original.artifact_id != mutated.artifact_id


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_empty_payload_has_a_stable_identity():
    """An empty file is content, not a missing artifact."""
    assert make_artifact(b"").artifact_id == make_artifact(b"").artifact_id


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_identity_is_derived_not_assigned():
    """An artifact whose id disagrees with its content must be unconstructible.

    Without this, content addressing is a convention the application is trusted to follow rather
    than a property of the record.
    """
    genuine = make_artifact(b"payload")
    with pytest.raises(ValueError, match="content-addressed identity"):
        Artifact(
            artifact_id=artifact_id_for(compute_content_hash(b"different payload")),
            content_hash=genuine.content_hash,
            media_type="application/octet-stream",
            uri="file:///x",
            source_origin=SourceOrigin.UPLOAD,
        )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_content_hash_round_trips_through_the_artifact_id():
    artifact = make_artifact(b"payload")
    assert content_hash_for(artifact.artifact_id) == artifact.content_hash


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
@pytest.mark.parametrize(
    "malformed",
    [
        "deadbeef",  # no algorithm
        "md5:d41d8cd98f00b204e9800998ecf8427e",  # unsupported algorithm
        "sha256:tooshort",
        "sha256:" + "0" * 63,  # one hex character short
        "sha256:" + "A" * 64,  # uppercase
    ],
)
def test_malformed_content_hashes_are_rejected(malformed):
    with pytest.raises(ContentHashError):
        artifact_id_for(malformed)


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_streaming_and_path_hashes_match_the_in_memory_hash(tmp_path):
    """Large simulation outputs are hashed in chunks; the result must not depend on how."""
    payload = b"x" * (3 * 1024 * 1024 + 7)  # spans several chunks, not a chunk multiple
    expected = compute_content_hash(payload)

    assert compute_content_hash_from_stream(io.BytesIO(payload)) == expected

    path = tmp_path / "large.bin"
    path.write_bytes(payload)
    assert compute_content_hash_from_path(path) == expected


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_every_artifact_starts_its_own_lineage_at_revision_one():
    artifact = make_artifact(b"v1")
    assert artifact.lineage_id == artifact.artifact_id
    assert artifact.lineage_revision == 1
    assert artifact.previous_artifact_id is None


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_lineage_revision_increments_and_preserves_the_predecessor():
    v1 = make_artifact(b"report v1", uri="file:///report_v1.pdf")
    v2 = v1.next_revision(b"report v2", uri="file:///report_v2.pdf")
    v3 = v2.next_revision(b"report v3", uri="file:///report_v3.pdf")

    assert (v1.lineage_revision, v2.lineage_revision, v3.lineage_revision) == (1, 2, 3)
    assert v2.previous_artifact_id == v1.artifact_id
    assert v3.previous_artifact_id == v2.artifact_id
    # One lineage, three distinct content-addressed identities.
    assert v1.lineage_id == v2.lineage_id == v3.lineage_id
    assert len({v1.artifact_id, v2.artifact_id, v3.artifact_id}) == 3


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_identical_bytes_are_not_a_new_revision():
    """The same content is the same artifact, not version n+1 of itself."""
    v1 = make_artifact(b"unchanged")
    with pytest.raises(ValueError, match="identical bytes"):
        v1.next_revision(b"unchanged", uri="file:///same.bin")


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_a_revision_chain_with_a_gap_is_rejected():
    """A revision above 1 with no predecessor cannot be traced back."""
    artifact = make_artifact(b"payload")
    with pytest.raises(ValueError, match="previous_artifact_id"):
        artifact.model_copy(update={"lineage_revision": 2}).model_validate(
            artifact.model_dump() | {"lineage_revision": 2, "previous_artifact_id": None}
        )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_revision_one_must_not_claim_a_predecessor():
    artifact = make_artifact(b"payload")
    other = make_artifact(b"other")
    with pytest.raises(ValueError, match="revision 1"):
        Artifact.model_validate(
            artifact.model_dump()
            | {"lineage_revision": 1, "previous_artifact_id": other.artifact_id}
        )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_artifact_records_the_four_mandatory_provenance_fields():
    """ART-001: immutable id + hash + source + timestamp, all required."""
    artifact = make_artifact(b"payload")
    assert artifact.artifact_id
    assert artifact.content_hash
    assert artifact.source_origin is SourceOrigin.UPLOAD
    assert artifact.created_at.tzinfo is not None


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_an_artifact_cannot_carry_project_scope_or_classification():
    """Identity is a property of the bytes (§17.1, ADR-0010, amendment v3.3-a8).

    `project_id` and `sensitivity_label` describe a project's *copy* of the bytes, and the same
    bytes may sit in several projects under different labels. Passing either here used to be
    accepted and stored; now `CoreModel` forbids extra fields, so it is a loud error rather than a
    record that answers the wrong project's question.

    Both routes are checked, because bypassing the helper must not bypass the rule.
    """
    content_hash = compute_content_hash(b"payload")
    for rejected in ("sensitivity_label", "project_id"):
        with pytest.raises(ValidationError, match=rejected):
            Artifact(
                artifact_id=artifact_id_for(content_hash),
                content_hash=content_hash,
                media_type="text/plain",
                uri="file:///x",
                source_origin=SourceOrigin.UPLOAD,
                **{rejected: "prj:test"},
            )
        with pytest.raises(ValidationError, match=rejected):
            Artifact.from_bytes(
                b"payload",
                media_type="text/plain",
                uri="file:///x",
                source_origin=SourceOrigin.UPLOAD,
                **{rejected: "prj:test"},
            )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_classification_is_mandatory_on_the_occurrence():
    """P28 survives the split: the obligation moved, it did not disappear.

    An occurrence is where "this project holds these bytes, classified thus" is recorded, so that
    is where an unclassified value must be unconstructible.
    """
    artifact = make_artifact(b"payload")
    with pytest.raises(ValidationError, match="sensitivity_label"):
        ArtifactOccurrence(artifact_id=artifact.artifact_id, project_id="prj:test")

    placed = artifact.occurrence_in("prj:test", SensitivityLabel.INTERNAL)
    assert placed.occurrence_key == (artifact.artifact_id, "prj:test")
    assert placed.sensitivity_label is SensitivityLabel.INTERNAL


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_a_revision_does_not_inherit_its_predecessors_occurrences():
    """Revision n+1 is different bytes, so where it lives and how it is labelled are new facts.

    Copying the predecessor's classification into every project would classify content nobody has
    looked at -- the inverse of P28, arrived at by convenience.
    """
    first = make_artifact(b"v1")
    second = first.next_revision(b"v2", uri="file:///v2")
    assert second.lineage_id == first.lineage_id
    assert second.previous_artifact_id == first.artifact_id
    assert not hasattr(second, "sensitivity_label")
    assert not hasattr(second, "project_id")


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_artifact_is_not_parseable_until_the_secret_scan_clears():
    """SEC-003 ordering: secret scan precedes any parsing stage."""
    pending = make_artifact(b"payload")
    assert pending.secret_scan_status is SecretScanStatus.PENDING
    assert not pending.is_parseable

    assert make_artifact(b"payload", secret_scan_status=SecretScanStatus.CLEAN).is_parseable
    assert make_artifact(b"payload", secret_scan_status=SecretScanStatus.REDACTED).is_parseable
    assert not make_artifact(
        b"payload", secret_scan_status=SecretScanStatus.QUARANTINED
    ).is_parseable


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_artifacts_are_immutable_in_memory():
    """P2 append-only, enforced at the object level as well as in storage."""
    artifact = make_artifact(b"payload")
    with pytest.raises(ValueError, match=r"frozen|Instance is frozen"):
        artifact.sensitivity_label = SensitivityLabel.PUBLIC  # type: ignore[misc]


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_unknown_fields_are_rejected_rather_than_dropped():
    """A typo'd classification field must not be silently discarded.

    A dropped ``sensitivity_lable`` produces a record that looks classified and is not.
    """
    artifact = make_artifact(b"payload")
    with pytest.raises(ValueError, match=r"sensitivity_lable|Extra inputs"):
        Artifact.model_validate(artifact.model_dump() | {"sensitivity_lable": "PUBLIC"})


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_naive_timestamps_are_rejected():
    """A naive timestamp cannot be ordered against an aware one, breaking as_of replay."""
    import datetime as dt

    artifact = make_artifact(b"payload")
    with pytest.raises(ValueError, match="timezone-aware"):
        Artifact.model_validate(
            artifact.model_dump() | {"created_at": dt.datetime(2026, 1, 1, 12, 0, 0)}
        )
