"""The production write side, through `IngestionPipeline.ingest()` (ART-001, EVI-010, ADR-0010/0012).

WHAT THIS FILE IS FOR, AND WHY IT IS NOT `test_duplicate_ingest_postgres.py`.

That file proves the pipeline is idempotent and the schema accepts its output, using persistence
helpers it defines itself. It says so in its own header, and the M1-P1 readiness document records
the remaining gap as a P2 limitation: *no production repository contract on the write side*.

This file is the same claims with the helpers replaced by `PostgresIngestionWriter`. Nothing in
it defines SQL. If a guarantee held there and fails here, the guarantee belonged to the test
helper rather than to the system -- which is exactly the distinction the limitation was about.

THE CRITICAL LOCK. Idempotency here comes from derived identity, never from a "have I seen this"
branch. The behavioural tests establish that the outcome is right;
`test_the_writer_never_reads_before_it_writes` establishes that it is right for the locked
reason, because a lookup that happens to be correct produces identical behaviour.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from lab_brain.core.models import SensitivityLabel
from lab_brain.ingestion.pipeline import IngestionPipeline
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.storage.postgres import PostgresEvidenceUnitReader, PostgresIngestionWriter
from lab_brain.storage.postgres import ingestion_writer as writer_module
from tests.evidence_fixtures import fixture_bytes

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EVI-010"),
    pytest.mark.spec_test("T-EVI-010"),
]

PROJECT_A = "prj:test"
PROJECT_B = "prj:other"
ACTOR = "act:test"


@pytest.fixture
def two_projects(db):
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (PROJECT_B, "Other Project"),
    )
    return db


def _ingest(connection, store, project_id: str):
    """One ingestion, persisted entirely by the production writer."""
    writer = PostgresIngestionWriter(connection)

    def commit(artifact, occurrence) -> None:
        with connection.transaction():
            writer.commit_rows(artifact, occurrence)

    def rollback(artifact, occurrence) -> None:  # pragma: no cover - no fault injected here
        raise AssertionError("no compensation should be needed in this test")

    pipeline = IngestionPipeline(store, commit, rollback)
    outcome = pipeline.ingest(
        fixture_bytes(),
        project_id=project_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert outcome.artifact is not None
    writer.persist_evidence(outcome.evidence_units, outcome.evidence_occurrences)
    return outcome


def _counts(connection) -> dict[str, int]:
    return {
        name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in (
            "artifacts",
            "artifact_occurrences",
            "evidence_units",
            "evidence_unit_occurrences",
        )
    }


def test_the_production_writer_persists_a_whole_ingestion(two_projects, tmp_path):
    """The baseline: one pass through the real writer leaves a complete, readable record."""
    store = LocalArtifactStore(tmp_path)
    outcome = _ingest(two_projects, store, PROJECT_A)

    counts = _counts(two_projects)
    assert counts["artifacts"] == 1
    assert counts["artifact_occurrences"] == 1
    assert counts["evidence_units"] == len(outcome.evidence_units)
    assert counts["evidence_unit_occurrences"] == len(outcome.evidence_occurrences)

    # Read back through the locked reader, which revalidates every invariant on the way out.
    reader = PostgresEvidenceUnitReader(two_projects)
    rebuilt = reader.load_for_project(PROJECT_A)
    assert len(rebuilt) == len(outcome.evidence_units)
    assert {u.evidence_unit_id for u in rebuilt} == {
        u.evidence_unit_id for u in outcome.evidence_units
    }


def test_the_same_bytes_twice_change_nothing(two_projects, tmp_path):
    """Case A, through production code.

    The second ingest is not skipped -- the pipeline runs end to end and writes again. Every id it
    computes is the same id, so every write asserts a row that already exists. Counts identical is
    the observable consequence of derived identity, not of a lookup.
    """
    store = LocalArtifactStore(tmp_path)
    first = _ingest(two_projects, store, PROJECT_A)
    before = _counts(two_projects)

    second = _ingest(two_projects, store, PROJECT_A)
    after = _counts(two_projects)

    assert before == after
    assert second.artifact.artifact_id == first.artifact.artifact_id
    assert {u.evidence_unit_id for u in second.evidence_units} == {
        u.evidence_unit_id for u in first.evidence_units
    }


def test_provenance_and_witness_survive_a_second_ingest(two_projects, tmp_path):
    """`DO NOTHING` must not mean "the second write silently replaced the first".

    Asserted on the fields a wrong `DO UPDATE` would quietly rewrite: the segmentation witness
    and the recorded implementation versions. Those are what Repair-2 bound re-derivation to, so
    an overwrite here would break a locked invariant one layer down and look like nothing.
    """
    store = LocalArtifactStore(tmp_path)
    first = _ingest(two_projects, store, PROJECT_A)
    target = first.evidence_units[0]

    _ingest(two_projects, store, PROJECT_A)

    row = two_projects.execute(
        "SELECT segmentation_witness, parser_version, segmenter_version, token_limit "
        "FROM evidence_units WHERE evidence_unit_id = %s",
        (target.evidence_unit_id,),
    ).fetchone()
    assert row[0] == target.segmentation_witness
    assert row[1] == target.provenance.parser_version
    assert row[2] == target.provenance.segmenter_version
    assert row[3] == target.provenance.token_limit


def test_two_projects_share_one_body_and_hold_their_own_occurrence(two_projects, tmp_path):
    """Case B, through production code (ADR-0010 + ADR-0012).

    One global artifact, one canonical body per evidence identity, an occurrence each, and
    neither project loses anything because the other ingested first.
    """
    store = LocalArtifactStore(tmp_path)
    first = _ingest(two_projects, store, PROJECT_A)
    second = _ingest(two_projects, store, PROJECT_B)

    counts = _counts(two_projects)
    assert counts["artifacts"] == 1
    assert counts["artifact_occurrences"] == 2
    assert counts["evidence_units"] == len(first.evidence_units)
    assert counts["evidence_unit_occurrences"] == 2 * len(first.evidence_units)

    reader = PostgresEvidenceUnitReader(two_projects)
    for project in (PROJECT_A, PROJECT_B):
        units = reader.load_for_project(project)
        assert len(units) == len(first.evidence_units), f"{project} lost evidence"
    assert {u.evidence_unit_id for u in second.evidence_units} == {
        u.evidence_unit_id for u in first.evidence_units
    }


def test_a_second_ingest_cannot_relabel_an_existing_occurrence(two_projects, tmp_path):
    """A security property, not a convenience one.

    If the occurrence write were `DO UPDATE`, re-ingesting the same bytes under a looser label
    would downgrade an existing classification with no approval and no audit record -- which
    §17.15 forbids outright ("explicit authorized action is required to lower classification").
    So the second ingest, declaring PUBLIC, must leave RESTRICTED_NDA standing.
    """
    store = LocalArtifactStore(tmp_path)
    writer = PostgresIngestionWriter(two_projects)

    def commit(artifact, occurrence) -> None:
        with two_projects.transaction():
            writer.commit_rows(artifact, occurrence)

    pipeline = IngestionPipeline(store, commit, lambda a, o: None)
    pipeline.ingest(
        fixture_bytes(),
        project_id=PROJECT_A,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.RESTRICTED_NDA,
        uri="file:///secret.md",
    )
    pipeline.ingest(
        fixture_bytes(),
        project_id=PROJECT_A,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.PUBLIC,
        uri="file:///secret.md",
    )

    label = two_projects.execute(
        "SELECT sensitivity_label FROM artifact_occurrences "
        "WHERE artifact_id = (SELECT artifact_id FROM artifacts LIMIT 1) AND project_id = %s",
        (PROJECT_A,),
    ).fetchone()
    assert label[0] == "RESTRICTED_NDA", "a re-ingest downgraded a classification"


def test_the_writer_never_reads_before_it_writes():
    """The locked rule, checked structurally rather than by grepping prose.

    M1-P1 locked "same bytes -> same derived identity -> idempotent persistence" and explicitly
    forbade `if already_seen: skip_ingestion()`. A future edit that added a lookup would keep every
    behavioural test above green -- the outcome is the same whenever the lookup happens to be
    right -- so the behavioural tests cannot catch the substitution. This one can.

    The property asserted is sharper than "no `already_seen` identifier": **the writer issues no
    SELECT at all.** A writer that reads in order to decide whether to write is doing the lookup
    under some other name, and there is no legitimate reason for this class to read.

    The first version of this test grepped the module text and failed on its own docstring, which
    names the forbidden pattern in order to forbid it. Parsing the AST looks at the code.
    """
    tree = ast.parse(inspect.getsource(writer_module))

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    sql = " ".join(literals)

    assert "SELECT" not in sql.upper(), (
        "the production writer issues a SELECT. Idempotency here is a property of derived "
        "identity; reading in order to decide whether to write moves the decision somewhere "
        "that can be stale or racing"
    )
    assert "DO UPDATE" not in sql.upper(), (
        "an upsert would let a re-ingest rewrite provenance or downgrade a classification"
    )
    assert sql.upper().count("ON CONFLICT") == 4, (
        "expected exactly four conflict clauses, one per derived or composite identity"
    )

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not {n for n in names if "seen" in n.lower() or "exists" in n.lower()}
