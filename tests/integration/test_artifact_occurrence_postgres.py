"""The database must enforce the R-7 split, not merely permit it (SEC-002).

A Python model that separates content identity from project scope is worth little if the schema
still lets a project-scoped fact be written onto the global artifact row. These tests assert the
separation where it actually has to hold.

The sharpest one is `test_the_same_bytes_carry_independent_labels_in_two_projects`: before migration
005 it could not have been written at all. `artifacts.content_hash` is UNIQUE, so the second project
could not have inserted a second row, and the first project's `sensitivity_label` was the only
answer the schema could give.
"""

from __future__ import annotations

import psycopg
import pytest

from lab_brain.core.models import artifact_id_for, compute_content_hash

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("SEC-002"),
    pytest.mark.spec_test("T-SEC-002"),
]

SHARED = b"foundry PDK rev 3: ring radius table"
ARTIFACT = artifact_id_for(compute_content_hash(SHARED))
CONTENT_HASH = compute_content_hash(SHARED)


@pytest.fixture
def seeded(db):  # type: ignore[no-untyped-def]
    """One artifact, two projects, one actor. Nothing classified yet.

    Uses `db` rather than `postgres_connection`: `db` wraps each test in a transaction that is
    rolled back, so these fixtures do not leak into the next test.
    """
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO actors (actor_id, actor_type) VALUES (%s, 'HUMAN')", ("actor:alice",)
        )
        for project in ("proj:nda", "proj:teaching"):
            cur.execute(
                "INSERT INTO projects (project_id, name) VALUES (%s, %s)", (project, project)
            )
        cur.execute(
            """
            INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, lineage_id,
                                   source_origin)
            VALUES (%s, %s, 'application/pdf', 'file:///pdk.pdf', %s, 'UPLOAD')
            """,
            (ARTIFACT, CONTENT_HASH, ARTIFACT),
        )
    return db


def test_the_global_artifact_row_no_longer_carries_project_scoped_columns(seeded):
    """Dropped rather than left nullable.

    A column that still exists will be read, and reading a project-scoped fact off the global row
    is the defect. Making it impossible is the fix; making it discouraged is not.
    """
    with seeded.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'artifacts' AND column_name IN ('project_id', 'sensitivity_label')
            """
        )
        assert cur.fetchall() == [], (
            "artifacts still carries project-scoped columns; R-7 is not closed"
        )


def test_the_same_bytes_carry_independent_labels_in_two_projects(seeded):
    """R-7 itself. This test could not have been written before migration 005.

    `artifacts.content_hash` is UNIQUE, so the second project had no row of its own to classify.
    """
    with seeded.cursor() as cur:
        for project, label in (
            ("proj:nda", "RESTRICTED_NDA"),
            ("proj:teaching", "INTERNAL"),
        ):
            cur.execute(
                """
                INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label)
                VALUES (%s, %s, %s)
                """,
                (ARTIFACT, project, label),
            )
        cur.execute(
            """
            SELECT project_id, sensitivity_label FROM artifact_occurrences
            WHERE artifact_id = %s ORDER BY project_id
            """,
            (ARTIFACT,),
        )
        assert cur.fetchall() == [
            ("proj:nda", "RESTRICTED_NDA"),
            ("proj:teaching", "INTERNAL"),
        ]


def test_an_occurrence_is_unique_per_artifact_and_project(seeded):
    """One classification per project, so "what is this labelled here" has one answer."""
    with seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label)"
            " VALUES (%s, 'proj:nda', 'RESTRICTED_NDA')",
            (ARTIFACT,),
        )
    with pytest.raises(psycopg.errors.UniqueViolation), seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label)"
            " VALUES (%s, 'proj:nda', 'PUBLIC')",
            (ARTIFACT,),
        )


def test_an_occurrence_requires_a_classification(seeded):
    """NOT NULL with no default: unclassified presence must not be representable."""
    with pytest.raises(psycopg.errors.NotNullViolation), seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO artifact_occurrences (artifact_id, project_id) VALUES (%s, 'proj:nda')",
            (ARTIFACT,),
        )


def test_an_occurrence_requires_a_real_project(seeded):
    """The foreign key, so an occurrence cannot be filed against a project that does not exist."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation), seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label)"
            " VALUES (%s, 'proj:does-not-exist', 'PUBLIC')",
            (ARTIFACT,),
        )


def test_membership_clearance_defaults_to_empty(seeded):
    """Fail-closed at the column level, not only in the Python model.

    An actor added directly in SQL -- a migration, a support script -- must start with no clearance.
    If the default were "unrestricted", every such insert would be a silent grant.
    """
    with seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role)"
            " VALUES ('actor:alice', 'proj:nda', 'researcher')"
        )
        cur.execute(
            "SELECT sensitivity_clearance, active FROM project_memberships"
            " WHERE actor_id = 'actor:alice' AND project_id = 'proj:nda'"
        )
        clearance, active = cur.fetchone()
        assert clearance == [], "a new membership must grant no clearance"
        assert active is True


def test_clearance_must_contain_only_real_labels(seeded):
    """A typo in a grant should be a loud error, not a denial nobody can explain.

    Without the constraint an unrecognised string compares against nothing and grants nothing --
    fail-closed, but silently, and the operator sees an access denial with no visible cause.
    """
    with pytest.raises(psycopg.errors.CheckViolation), seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role,"
            " sensitivity_clearance) VALUES ('actor:alice', 'proj:nda', 'researcher',"
            " ARRAY['RESTRICTED_NDAA'])"
        )


def test_revocation_keeps_the_row(seeded):
    """`active = false` rather than DELETE, so "who could read this in March" stays answerable."""
    with seeded.cursor() as cur:
        cur.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance)"
            " VALUES ('actor:alice', 'proj:nda', 'researcher', ARRAY['RESTRICTED_NDA'])"
        )
        cur.execute(
            "UPDATE project_memberships SET active = FALSE"
            " WHERE actor_id = 'actor:alice' AND project_id = 'proj:nda'"
        )
        cur.execute(
            "SELECT active, sensitivity_clearance FROM project_memberships"
            " WHERE actor_id = 'actor:alice' AND project_id = 'proj:nda'"
        )
        active, clearance = cur.fetchone()
        assert active is False
        assert clearance == ["RESTRICTED_NDA"], "the historical grant must survive revocation"
