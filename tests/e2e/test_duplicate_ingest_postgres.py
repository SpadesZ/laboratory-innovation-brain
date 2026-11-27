"""Duplicate ingestion through the REAL vertical, not through raw SQL (EVI-010, ART-001).

WHY THIS FILE EXISTS SEPARATELY FROM THE SCHEMA TESTS. Repair-1 proved duplicate behaviour with
raw `INSERT`s, which establishes what the *schema* does and says nothing about whether
``IngestionPipeline.ingest()`` can be run twice. Those are different claims, and the second is the
one an operator relies on when a watcher re-delivers a file or two projects receive the same
paper.

So every case here calls the pipeline. The assertions are about what the *system* ends up holding.

WHAT IS STILL A TEST HELPER, STATED PLAINLY. ``_commit_rows`` / ``_persist_units`` below are this
file's persistence seam. There is no production repository contract for artifacts or evidence
units yet -- the pipeline takes ``commit_rows`` as an injected callable precisely because OPS-004
required the fault-injection point to be a parameter, and nothing has since supplied a production
implementation. So these tests prove the *pipeline* is idempotent and that the schema accepts
what it produces; they do not prove a production writer exists that does this correctly. That gap
is a P2 limitation recorded in the readiness document, not something this file closes.
"""

from __future__ import annotations

import json

import pytest

from lab_brain.core.models import SensitivityLabel
from lab_brain.ingestion.pipeline import IngestionPipeline
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.storage.postgres import PostgresEvidenceUnitReader
from tests.evidence_fixtures import fixture_bytes

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EVI-010"),
    pytest.mark.spec_test("T-EVI-010"),
]

PROJECT_A = "prj:test"
PROJECT_B = "prj:other"
ACTOR = "act:test"


def _commit_rows(connection):
    """Artifact + occurrence, idempotently.

    ``ON CONFLICT DO NOTHING`` on the artifact is not laziness: `artifact_id` is content-addressed,
    so a second ingest of the same bytes is asserting a row that already exists and is *identical*.
    Failing there would make re-delivery an error, which is precisely the behaviour ART-001's
    content addressing exists to avoid.
    """

    def commit(artifact, occurrence) -> None:
        with connection.transaction():
            connection.execute(
                "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, "
                "source_origin, lineage_id, actor_id, secret_scan_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (artifact_id) DO NOTHING",
                (
                    artifact.artifact_id,
                    artifact.content_hash,
                    artifact.media_type,
                    artifact.uri,
                    artifact.source_origin.value,
                    artifact.lineage_id,
                    artifact.actor_id,
                    artifact.secret_scan_status.value,
                ),
            )
            connection.execute(
                "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label, "
                "ingested_by_actor_id) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (artifact_id, project_id) DO NOTHING",
                (
                    occurrence.artifact_id,
                    occurrence.project_id,
                    occurrence.sensitivity_label.value,
                    occurrence.ingested_by_actor_id,
                ),
            )

    return commit


def _rollback_rows(connection):
    def rollback(artifact, occurrence) -> None:
        with connection.transaction():
            connection.execute(
                "DELETE FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
                (occurrence.artifact_id, occurrence.project_id),
            )
            connection.execute(
                "DELETE FROM artifacts WHERE artifact_id = %s", (artifact.artifact_id,)
            )

    return rollback


def _persist(connection, outcome) -> None:
    """Write units and occurrences, idempotently.

    The unit conflict target is the derived primary key. Re-ingesting unchanged bytes produces
    the same ids by construction -- that is what ADR-0011's derived identity buys -- so the second
    write is a no-op rather than a duplicate. A *changed* boundary set would produce a different
    id at the same structural path and hit the unique path index instead, which is the loud
    failure ADR-0012 wants for an attempted re-segmentation.
    """
    for unit in outcome.evidence_units:
        connection.execute(
            "INSERT INTO evidence_units (evidence_unit_id, artifact_id, unit_type, "
            "structural_path, locator, body, content_digest, parent_unit_id, subdivision_index, "
            "subdivision_reason, inherited_context, conditions, bound_condition_texts, "
            "segmentation_witness, table_context, figure_context, parser_id, parser_version, "
            "segmenter_id, segmenter_version, token_limit) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s) ON CONFLICT (evidence_unit_id) DO NOTHING",
            (
                unit.evidence_unit_id,
                unit.artifact_id,
                unit.unit_type.value,
                unit.structural_path,
                unit.locator.model_dump_json(),
                unit.body,
                unit.content_digest,
                unit.parent_unit_id,
                unit.subdivision_index,
                unit.subdivision_reason.value if unit.subdivision_reason else None,
                list(unit.inherited_context),
                json.dumps(unit.conditions),
                list(unit.bound_condition_texts),
                unit.segmentation_witness,
                unit.table_context.model_dump_json() if unit.table_context else None,
                unit.figure_context.model_dump_json() if unit.figure_context else None,
                unit.provenance.parser_id,
                unit.provenance.parser_version,
                unit.provenance.segmenter_id,
                unit.provenance.segmenter_version,
                unit.provenance.token_limit,
            ),
        )
    for occurrence in outcome.evidence_occurrences:
        connection.execute(
            "INSERT INTO evidence_unit_occurrences (evidence_unit_id, project_id, artifact_id, "
            "ingested_by_actor_id) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (evidence_unit_id, project_id) DO NOTHING",
            (
                occurrence.evidence_unit_id,
                occurrence.project_id,
                occurrence.artifact_id,
                occurrence.ingested_by_actor_id,
            ),
        )


def _ingest(connection, store, project_id: str):
    pipeline = IngestionPipeline(store, _commit_rows(connection), _rollback_rows(connection))
    outcome = pipeline.ingest(
        fixture_bytes(),
        project_id=project_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert outcome.artifact is not None, "ingestion did not produce an artifact"
    _persist(connection, outcome)
    return outcome


def _counts(connection) -> dict[str, int]:
    return {
        "artifacts": connection.execute("SELECT count(*) FROM artifacts").fetchone()[0],
        "artifact_occurrences": connection.execute(
            "SELECT count(*) FROM artifact_occurrences"
        ).fetchone()[0],
        "evidence_units": connection.execute("SELECT count(*) FROM evidence_units").fetchone()[0],
        "evidence_occurrences": connection.execute(
            "SELECT count(*) FROM evidence_unit_occurrences"
        ).fetchone()[0],
    }


# ---------------------------------------------------------------------------
# Case A — same bytes, same project, twice
# ---------------------------------------------------------------------------


def test_ingesting_the_same_bytes_twice_into_one_project_creates_no_duplicates(db, tmp_path):
    """The whole vertical, run twice. Nothing doubles and nothing errors."""
    store = LocalArtifactStore(tmp_path / "artifacts")

    first = _ingest(db, store, PROJECT_A)
    after_first = _counts(db)

    second = _ingest(db, store, PROJECT_A)
    after_second = _counts(db)

    assert after_second == after_first, (
        f"a second identical ingest changed the stored counts: {after_first} -> {after_second}"
    )
    assert second.artifact is not None and first.artifact is not None
    assert second.artifact.artifact_id == first.artifact.artifact_id, (
        "content addressing did not produce the same artifact identity for the same bytes"
    )
    assert [unit.evidence_unit_id for unit in second.evidence_units] == [
        unit.evidence_unit_id for unit in first.evidence_units
    ], "re-segmenting unchanged bytes produced different evidence identities"


def test_the_second_ingest_does_not_fail_on_the_existing_artifact(db, tmp_path):
    """Re-delivery is normal. A watcher re-sending a file must not be an error.

    Asserted as "the pipeline completed and produced units", not merely "no exception": a
    pipeline that swallowed the second run and returned an empty outcome would also not raise.
    """
    store = LocalArtifactStore(tmp_path / "artifacts")
    _ingest(db, store, PROJECT_A)
    second = _ingest(db, store, PROJECT_A)

    assert second.raw_artifact_is_durable
    assert second.evidence_units, "the second ingest produced no evidence units"
    assert second.evidence_occurrences, "the second ingest produced no occurrences"


def test_the_project_occurrence_survives_a_second_ingest(db, tmp_path):
    """Exactly one occurrence per (unit, project) afterwards, and it still resolves."""
    store = LocalArtifactStore(tmp_path / "artifacts")
    first = _ingest(db, store, PROJECT_A)
    _ingest(db, store, PROJECT_A)

    reader = PostgresEvidenceUnitReader(db)
    for unit in first.evidence_units:
        rows = db.execute(
            "SELECT count(*) FROM evidence_unit_occurrences WHERE evidence_unit_id = %s",
            (unit.evidence_unit_id,),
        ).fetchone()[0]
        assert rows == 1, f"{unit.structural_path} has {rows} occurrences in one project"
        assert reader.present_in(unit.evidence_unit_id, PROJECT_A)


def test_provenance_survives_the_second_ingest(db, tmp_path):
    """The stored provenance is still the one re-verification will resolve against.

    Read through the canonical reader, so the assertion is about revalidated units rather than
    about rows -- a row whose provenance had been overwritten would fail to rebuild or would
    rebuild with different provenance, and either shows up here.
    """
    store = LocalArtifactStore(tmp_path / "artifacts")
    first = _ingest(db, store, PROJECT_A)
    _ingest(db, store, PROJECT_A)

    reader = PostgresEvidenceUnitReader(db)
    for unit in first.evidence_units:
        stored = reader.load(unit.evidence_unit_id)
        assert stored is not None
        assert stored.provenance.parser_id == unit.provenance.parser_id
        assert stored.provenance.parser_version == unit.provenance.parser_version
        assert stored.provenance.segmenter_id == unit.provenance.segmenter_id
        assert stored.provenance.segmenter_version == unit.provenance.segmenter_version
        assert stored.segmentation_witness == unit.segmentation_witness
        assert stored.bound_condition_texts == unit.bound_condition_texts


# ---------------------------------------------------------------------------
# Case B — same bytes, two projects
# ---------------------------------------------------------------------------


@pytest.fixture
def project_b(db):
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (PROJECT_B, "Other Project"),
    )
    return db


def test_the_same_bytes_ingest_into_two_projects_independently(project_b, tmp_path):
    """SPEC-ISSUE-014's scenario, through the vertical rather than through raw SQL."""
    db = project_b
    store = LocalArtifactStore(tmp_path / "artifacts")

    first = _ingest(db, store, PROJECT_A)
    second = _ingest(db, store, PROJECT_B)

    # One global artifact identity.
    assert second.artifact is not None and first.artifact is not None
    assert first.artifact.artifact_id == second.artifact.artifact_id
    assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1

    # One canonical body per evidence identity, two presences each.
    unit_count = db.execute("SELECT count(*) FROM evidence_units").fetchone()[0]
    assert unit_count == len(first.evidence_units)
    occurrence_count = db.execute("SELECT count(*) FROM evidence_unit_occurrences").fetchone()[0]
    assert occurrence_count == 2 * unit_count

    # Each project has its own artifact occurrence too.
    assert db.execute("SELECT count(*) FROM artifact_occurrences").fetchone()[0] == 2


def test_each_project_reads_the_evidence_through_its_own_occurrence(project_b, tmp_path):
    """Independently scoped: the same units, reached separately by each project."""
    db = project_b
    store = LocalArtifactStore(tmp_path / "artifacts")
    _ingest(db, store, PROJECT_A)
    _ingest(db, store, PROJECT_B)

    reader = PostgresEvidenceUnitReader(db)
    in_a = {unit.evidence_unit_id for unit in reader.load_for_project(PROJECT_A)}
    in_b = {unit.evidence_unit_id for unit in reader.load_for_project(PROJECT_B)}

    assert in_a, "project A sees no evidence"
    assert in_a == in_b, "the two projects resolved different evidence from the same bytes"
    for unit_id in in_a:
        assert reader.present_in(unit_id, PROJECT_A)
        assert reader.present_in(unit_id, PROJECT_B)


def test_neither_project_loses_access_because_the_other_ingested_first(project_b, tmp_path):
    """THE regression SPEC-ISSUE-014 was about, at the vertical level.

    Before ADR-0012 the second project's evidence rows collided on the primary key: its
    ``SEGMENT`` stage reported success and it ended up with a readable artifact and no evidence
    at all. Order must not matter.
    """
    db = project_b
    store = LocalArtifactStore(tmp_path / "artifacts")

    _ingest(db, store, PROJECT_A)
    second = _ingest(db, store, PROJECT_B)

    reader = PostgresEvidenceUnitReader(db)
    assert second.evidence_units, "the later project produced no evidence units"
    assert reader.load_for_project(PROJECT_B), (
        "the later project has an artifact but no evidence -- the SPEC-ISSUE-014 symptom"
    )
    assert len(reader.load_for_project(PROJECT_B)) == len(reader.load_for_project(PROJECT_A))


def test_removing_one_projects_presence_leaves_the_other_reading_normally(project_b, tmp_path):
    """Revoking B must not disturb A, nor delete the shared canonical body."""
    db = project_b
    store = LocalArtifactStore(tmp_path / "artifacts")
    _ingest(db, store, PROJECT_A)
    _ingest(db, store, PROJECT_B)

    db.execute("DELETE FROM evidence_unit_occurrences WHERE project_id = %s", (PROJECT_B,))

    reader = PostgresEvidenceUnitReader(db)
    assert reader.load_for_project(PROJECT_B) == ()
    assert reader.load_for_project(PROJECT_A), "revoking B removed A's access"


# ---------------------------------------------------------------------------
# The canonical read boundary
# ---------------------------------------------------------------------------


def test_the_reader_refuses_a_row_that_no_longer_revalidates(db, tmp_path):
    """A drifted row is refused rather than returned as evidence.

    Written under a new structural path so the unique index does not intercept it first, with a
    consistent digest and witness so every row-level guard the database holds is satisfied --
    only the derived identity disagrees, which is exactly what a repair script or a partial
    restore would leave behind.
    """
    from lab_brain.core.models import compute_content_hash, segmentation_witness_for
    from lab_brain.storage.postgres import EvidenceUnitReadError

    store = LocalArtifactStore(tmp_path / "artifacts")
    outcome = _ingest(db, store, PROJECT_A)
    assert outcome.artifact is not None

    body = "Cj increased to 9.999 pF/mm."
    digest = compute_content_hash(body.encode("utf-8"))
    path = "9/prose:9/0#drifted"
    witness = segmentation_witness_for(
        artifact_id=outcome.artifact.artifact_id,
        structural_path=path,
        body=body,
        inherited_context=(),
        bound_condition_texts=(),
        parser_id="local_markdown",
        parser_version="1.0.0",
        segmenter_id="evidence_aware_hierarchical",
        segmenter_version="1.0.0",
    )
    drifted = "evu:sha256:" + "b" * 64
    db.execute(
        "INSERT INTO evidence_units (evidence_unit_id, artifact_id, unit_type, structural_path, "
        "locator, body, content_digest, segmentation_witness, parser_id, parser_version, "
        "segmenter_id, segmenter_version) "
        "VALUES (%s, %s, 'PROSE', %s, '{\"label\": \"drifted\"}', %s, %s, %s, "
        "'local_markdown', '1.0.0', 'evidence_aware_hierarchical', '1.0.0')",
        (drifted, outcome.artifact.artifact_id, path, body, digest, witness),
    )

    with pytest.raises(EvidenceUnitReadError, match="does not revalidate"):
        PostgresEvidenceUnitReader(db).load(drifted)


def test_the_reader_returns_none_for_a_unit_that_does_not_exist(db):
    """Absent and corrupt are different answers: one is None, the other raises."""
    assert PostgresEvidenceUnitReader(db).load("evu:sha256:" + "0" * 64) is None
