"""SPEC-ISSUE-014 / ADR-0012 — the same evidence in two projects, against PostgreSQL.

The defect this file pins was reproduced before it was fixed:

    insert into prj:a: OK
    insert into prj:b: UniqueViolation   <-- project B cannot hold the same evidence

`evidence_unit_id` is derived from `(artifact_id, structural_path, content_digest)` and is
project-independent by design, while `003a` made it the primary key of a table that also carried
`project_id`. The visible symptom was a constraint error; the real one was that the first project
to ingest a document owned its evidence and the second got a readable artifact with no evidence.

`003b` splits presence onto `evidence_unit_occurrences`, the ADR-0010 move one layer down. What
follows is the four things §17.25.1 has to make true, plus the leakage negatives.
"""

from __future__ import annotations

import psycopg
import pytest

from lab_brain.core.models import compute_content_hash, evidence_unit_id_for
from lab_brain.core.models.identifiers import segmentation_witness_for

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EVI-010"),
    pytest.mark.spec_test("T-EVI-010"),
]

PROJECT_A = "prj:test"
PROJECT_B = "prj:other"

BODY = "Reverse bias increased from 0 to -2 V. Cj decreased from 0.515 to 0.345 pF/mm."
PATH = "3/prose:1/0"
PARSER = ("local_markdown", "1.0.0")
SEGMENTER = ("evidence_aware_hierarchical", "1.0.0")


@pytest.fixture
def two_projects(db):
    """One artifact, present in two projects — the ADR-0010 situation, one layer down."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (PROJECT_B, "Other Project"),
    )
    digest = compute_content_hash(b"one paper, two projects")
    artifact_id = f"art:{digest}"
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, source_origin, "
        "lineage_id) VALUES (%s, %s, 'text/markdown', 'file:///p.md', 'UPLOAD', %s)",
        (artifact_id, digest, artifact_id),
    )
    for project in (PROJECT_A, PROJECT_B):
        db.execute(
            "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label) "
            "VALUES (%s, %s, 'INTERNAL')",
            (artifact_id, project),
        )
    return db, artifact_id


def _insert_unit(db, artifact_id: str, *, body: str = BODY, path: str = PATH, **overrides) -> str:
    digest = compute_content_hash(body.encode("utf-8"))
    unit_id = evidence_unit_id_for(artifact_id, path, digest)
    bound = overrides.pop("bound_condition_texts", [])
    inherited = overrides.pop("inherited_context", [])
    witness = overrides.pop(
        "segmentation_witness",
        segmentation_witness_for(
            artifact_id=artifact_id,
            structural_path=path,
            body=body,
            inherited_context=inherited,
            bound_condition_texts=bound,
            parser_id=PARSER[0],
            parser_version=PARSER[1],
            segmenter_id=SEGMENTER[0],
            segmenter_version=SEGMENTER[1],
        ),
    )
    db.execute(
        "INSERT INTO evidence_units (evidence_unit_id, artifact_id, unit_type, structural_path, "
        "locator, body, content_digest, inherited_context, bound_condition_texts, "
        "segmentation_witness, parser_id, parser_version, segmenter_id, segmenter_version) "
        "VALUES (%s, %s, 'PROSE', %s, '{\"label\": \"s3\"}', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            unit_id,
            artifact_id,
            path,
            body,
            digest,
            inherited,
            bound,
            witness,
            PARSER[0],
            PARSER[1],
            SEGMENTER[0],
            SEGMENTER[1],
        ),
    )
    return unit_id


def _place(db, unit_id: str, artifact_id: str, project_id: str) -> None:
    db.execute(
        "INSERT INTO evidence_unit_occurrences (evidence_unit_id, project_id, artifact_id) "
        "VALUES (%s, %s, %s)",
        (unit_id, project_id, artifact_id),
    )


# ---------------------------------------------------------------------------
# The four things §17.25.1 must make true
# ---------------------------------------------------------------------------


def test_the_same_evidence_is_representable_in_two_projects_at_once(two_projects):
    """THE regression. Before `003b` the second placement was a UniqueViolation."""
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    _place(db, unit_id, artifact_id, PROJECT_A)
    _place(db, unit_id, artifact_id, PROJECT_B)

    projects = [
        row[0]
        for row in db.execute(
            "SELECT project_id FROM evidence_unit_occurrences WHERE evidence_unit_id = %s "
            "ORDER BY project_id",
            (unit_id,),
        ).fetchall()
    ]
    assert projects == sorted([PROJECT_A, PROJECT_B])


def test_there_is_exactly_one_canonical_body_for_the_two_presences(two_projects):
    """Reading C's whole point, and why Reading B was rejected.

    A composite primary key would have stored the body once per project, so two rows with one
    identity could diverge under a repair script while each stayed internally consistent. One
    row, two occurrences, means "resolve by identity, get *the* body" survives.
    """
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    _place(db, unit_id, artifact_id, PROJECT_A)
    _place(db, unit_id, artifact_id, PROJECT_B)

    assert (
        db.execute(
            "SELECT count(*) FROM evidence_units WHERE evidence_unit_id = %s", (unit_id,)
        ).fetchone()[0]
        == 1
    )


def test_each_project_retrieves_the_unit_independently(two_projects):
    """Independent retrieval: one representation per project, and a search sees only its own."""
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    for project in (PROJECT_A, PROJECT_B):
        _place(db, unit_id, artifact_id, project)
        db.execute(
            "INSERT INTO retrieval_representations (representation_id, evidence_unit_id, "
            "project_id, index_id, index_kind, payload_digest) "
            "VALUES (%s, %s, %s, 'idx:lexical:v1', 'LEXICAL', %s)",
            (f"rrp:{project}", unit_id, project, compute_content_hash(BODY.encode())),
        )

    for project in (PROJECT_A, PROJECT_B):
        rows = db.execute(
            "SELECT evidence_unit_id FROM retrieval_representations WHERE project_id = %s",
            (project,),
        ).fetchall()
        assert [row[0] for row in rows] == [unit_id]


def test_no_primary_key_collision_and_no_project_column_remains(two_projects):
    """The column is DROPPED, not nullable -- a stale project would look authoritative."""
    db, _ = two_projects
    columns = {
        row[0]
        for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'evidence_units'"
        ).fetchall()
    }
    assert "project_id" not in columns, (
        "evidence_units still has a project column; a column that exists will be read, and a "
        "stale project on the identity row is worse than none (ADR-0010's reasoning, ADR-0012)"
    )
    assert "segmentation_witness" in columns


# ---------------------------------------------------------------------------
# Leakage negatives
# ---------------------------------------------------------------------------


def test_evidence_cannot_be_placed_in_a_project_that_does_not_hold_the_artifact(db):
    """Evidence readable where its source is not would be R-7, one layer down."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (PROJECT_B, "Other"),
    )
    digest = compute_content_hash(b"single project paper")
    artifact_id = f"art:{digest}"
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, source_origin, "
        "lineage_id) VALUES (%s, %s, 'text/markdown', 'file:///s.md', 'UPLOAD', %s)",
        (artifact_id, digest, artifact_id),
    )
    db.execute(
        "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label) "
        "VALUES (%s, %s, 'INTERNAL')",
        (artifact_id, PROJECT_A),
    )
    unit_id = _insert_unit(db, artifact_id)

    with pytest.raises(psycopg.errors.CheckViolation, match="has no occurrence in project"):
        _place(db, unit_id, artifact_id, PROJECT_B)


def test_an_occurrence_naming_a_different_artifact_than_its_unit_is_rejected(two_projects):
    """The read gate resolves the artifact through the occurrence, so a mismatch misauthorises."""
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)

    other_digest = compute_content_hash(b"a different document entirely")
    other_artifact = f"art:{other_digest}"
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, source_origin, "
        "lineage_id) VALUES (%s, %s, 'text/markdown', 'file:///o.md', 'UPLOAD', %s)",
        (other_artifact, other_digest, other_artifact),
    )
    db.execute(
        "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label) "
        "VALUES (%s, %s, 'INTERNAL')",
        (other_artifact, PROJECT_A),
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="authorise against the wrong bytes"):
        _place(db, unit_id, other_artifact, PROJECT_A)


def test_a_representation_for_a_project_with_no_occurrence_is_rejected(two_projects):
    """009b's replacement trigger: presence is the authority, not a column on the unit."""
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    _place(db, unit_id, artifact_id, PROJECT_A)

    with pytest.raises(psycopg.errors.CheckViolation, match="cannot be indexed for retrieval"):
        db.execute(
            "INSERT INTO retrieval_representations (representation_id, evidence_unit_id, "
            "project_id, index_id, index_kind, payload_digest) "
            "VALUES ('rrp:leak', %s, %s, 'idx:lexical:v1', 'LEXICAL', %s)",
            (unit_id, PROJECT_B, compute_content_hash(BODY.encode())),
        )


def test_removing_one_occurrence_leaves_the_other_and_the_evidence_intact(two_projects):
    """Revoking a project's access to evidence must not delete the evidence."""
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    _place(db, unit_id, artifact_id, PROJECT_A)
    _place(db, unit_id, artifact_id, PROJECT_B)

    db.execute(
        "DELETE FROM evidence_unit_occurrences WHERE evidence_unit_id = %s AND project_id = %s",
        (unit_id, PROJECT_B),
    )
    remaining = db.execute(
        "SELECT project_id FROM evidence_unit_occurrences WHERE evidence_unit_id = %s",
        (unit_id,),
    ).fetchall()
    assert [row[0] for row in remaining] == [PROJECT_A]
    assert (
        db.execute(
            "SELECT body FROM evidence_units WHERE evidence_unit_id = %s", (unit_id,)
        ).fetchone()[0]
        == BODY
    )


# ---------------------------------------------------------------------------
# Duplicate ingest
# ---------------------------------------------------------------------------


def test_duplicate_ingest_into_the_same_project_is_idempotent_not_a_second_unit(two_projects):
    """Re-ingesting the same document must not double the evidence.

    Identity is derived, so the second segmentation produces the same ids -- which is the
    property that makes re-ingest safe rather than duplicating. The unique index turns a genuine
    re-segmentation attempt (different boundaries, same path) into a loud failure instead.
    """
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    _place(db, unit_id, artifact_id, PROJECT_A)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_unit(db, artifact_id)

    db.execute(
        "INSERT INTO evidence_unit_occurrences (evidence_unit_id, project_id, artifact_id) "
        "VALUES (%s, %s, %s) ON CONFLICT (evidence_unit_id, project_id) DO NOTHING",
        (unit_id, PROJECT_A, artifact_id),
    )
    assert (
        db.execute(
            "SELECT count(*) FROM evidence_unit_occurrences WHERE evidence_unit_id = %s",
            (unit_id,),
        ).fetchone()[0]
        == 1
    )


def test_duplicate_ingest_across_projects_adds_a_presence_not_a_unit(two_projects):
    """The cross-project duplicate: a second presence, the same single body."""
    db, artifact_id = two_projects
    unit_id = _insert_unit(db, artifact_id)
    _place(db, unit_id, artifact_id, PROJECT_A)

    units_before = db.execute("SELECT count(*) FROM evidence_units").fetchone()[0]
    _place(db, unit_id, artifact_id, PROJECT_B)
    units_after = db.execute("SELECT count(*) FROM evidence_units").fetchone()[0]

    assert units_after == units_before
    assert (
        db.execute(
            "SELECT count(*) FROM evidence_unit_occurrences WHERE evidence_unit_id = %s",
            (unit_id,),
        ).fetchone()[0]
        == 2
    )


def test_re_segmentation_with_different_boundaries_fails_loudly(two_projects):
    """ADR-0012's known limitation, pinned.

    A second segmenter version writing different boundaries at the same structural path would
    otherwise insert a parallel unit set, and a query by path would return whichever came back
    first. Re-segmentation is not supported; attempting it must not half-succeed.
    """
    db, artifact_id = two_projects
    _insert_unit(db, artifact_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_unit(db, artifact_id, body="A differently cut boundary.")


# ---------------------------------------------------------------------------
# The witness, in SQL
# ---------------------------------------------------------------------------


def test_the_sql_witness_agrees_with_the_python_one(two_projects):
    """Two implementations of one digest, forced to agree.

    `003b` recomputes the witness in plpgsql so the store can reject a partially forged row
    without calling Python. Two implementations of a hash is exactly the drift this repository
    keeps writing down, so they are compared here rather than trusted to match.
    """
    db, artifact_id = two_projects
    cases = [
        ("simple body", [], []),
        ("with context", ["Reverse bias was -2 V.", "second"], ["Reverse bias was -2 V."]),
        # Unicode, embedded colons and digits: the length prefix counts characters in both
        # languages, and a byte-vs-codepoint disagreement would show up here and nowhere else.
        ("溫度 25 °C，Cj = 0.345 pF/mm。", ["a:1", "12:xy"], ["3:abc"]),
    ]
    for body, inherited, bound in cases:
        expected = segmentation_witness_for(
            artifact_id=artifact_id,
            structural_path=PATH,
            body=body,
            inherited_context=inherited,
            bound_condition_texts=bound,
            parser_id=PARSER[0],
            parser_version=PARSER[1],
            segmenter_id=SEGMENTER[0],
            segmenter_version=SEGMENTER[1],
        )
        actual = db.execute(
            "SELECT evidence_unit_expected_witness(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (artifact_id, PATH, body, inherited, bound, *PARSER, *SEGMENTER),
        ).fetchone()[0]
        assert actual == expected, f"SQL and Python disagree on the witness for {body!r}"


def test_a_row_whose_witness_does_not_bind_its_body_is_rejected(two_projects):
    """The partial forgery the storage layer is responsible for: body edited, witness left."""
    db, artifact_id = two_projects
    with pytest.raises(psycopg.errors.CheckViolation, match="does not bind its contents"):
        _insert_unit(
            db,
            artifact_id,
            segmentation_witness=compute_content_hash(b"a witness for something else"),
        )
