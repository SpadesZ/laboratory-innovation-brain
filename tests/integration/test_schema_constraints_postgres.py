"""Database-level enforcement of the M0a invariants (ART-001, EVI-005).

The Python models already reject these. That is not enough on its own: a migration script, a
bulk load, or a future service writing SQL directly bypasses Pydantic entirely. If ART-001 holds
only in the application layer then it holds only for callers who go through the application
layer.

So each invariant is asserted twice -- once in ``tests/contract`` against the models, once here
against the schema. A constraint that exists in the migration but does not actually reject
anything is the failure mode these tests exist to catch.
"""

from __future__ import annotations

import json

import pytest

from lab_brain.core.models import compute_content_hash
from tests.conftest_fixtures import TOY_SCHEMA, TOY_SCHEMA_REF

pytestmark = pytest.mark.postgres

HASH_A = compute_content_hash(b"payload A")
HASH_B = compute_content_hash(b"payload B")

_INSERT_ARTIFACT = """
INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, lineage_id,
                       lineage_revision, previous_artifact_id, source_origin,
                       sensitivity_label, project_id)
VALUES (%(artifact_id)s, %(content_hash)s, 'application/octet-stream', %(uri)s,
        %(lineage_id)s, %(lineage_revision)s, %(previous_artifact_id)s, 'UPLOAD',
        %(sensitivity_label)s, 'prj:test')
"""


def _artifact_params(content_hash: str, **overrides: object) -> dict[str, object]:
    artifact_id = f"art:{content_hash}"
    params: dict[str, object] = {
        "artifact_id": artifact_id,
        "content_hash": content_hash,
        "uri": "file:///payload.bin",
        "lineage_id": artifact_id,
        "lineage_revision": 1,
        "previous_artifact_id": None,
        "sensitivity_label": "INTERNAL",
    }
    params.update(overrides)
    return params


def _register_toy_schema(db) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema, "
        "comparator_version) VALUES (%s, %s, %s, %s, %s)",
        (
            TOY_SCHEMA.domain,
            TOY_SCHEMA.schema_id,
            TOY_SCHEMA.version,
            json.dumps(TOY_SCHEMA.json_schema),
            TOY_SCHEMA.comparator_version,
        ),
    )


# ---------------------------------------------------------------------------
# ART-001 at the schema level
# ---------------------------------------------------------------------------


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_rejects_an_artifact_id_that_is_not_its_content_hash(db):
    """Content addressing is a CHECK constraint, not an application convention."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation, match="content_addressed"):
        db.execute(
            _INSERT_ARTIFACT,
            _artifact_params(HASH_A, artifact_id=f"art:{HASH_B}", lineage_id=f"art:{HASH_B}"),
        )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_rejects_a_malformed_content_hash(db):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation, match="content_hash_format"):
        db.execute(_INSERT_ARTIFACT, _artifact_params("sha256:not-hex"))


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_rejects_two_identities_for_the_same_bytes(db):
    """One set of bytes is one artifact. A second row would be a second identity for it."""
    import psycopg

    db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A, uri="file:///elsewhere.bin"))


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_rejects_a_revision_chain_with_a_gap(db):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation, match="revision_chain_complete"):
        db.execute(
            _INSERT_ARTIFACT,
            _artifact_params(HASH_A, lineage_revision=2, previous_artifact_id=None),
        )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_rejects_revision_one_claiming_a_predecessor(db):
    import psycopg

    db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A))
    with pytest.raises(psycopg.errors.CheckViolation, match="revision_chain_complete"):
        db.execute(
            _INSERT_ARTIFACT,
            _artifact_params(HASH_B, lineage_revision=1, previous_artifact_id=f"art:{HASH_A}"),
        )


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_stores_a_valid_lineage_chain(db):
    """Positive control: the constraints must not reject the legitimate case."""
    db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A))
    db.execute(
        _INSERT_ARTIFACT,
        _artifact_params(
            HASH_B,
            lineage_id=f"art:{HASH_A}",
            lineage_revision=2,
            previous_artifact_id=f"art:{HASH_A}",
            uri="file:///payload_v2.bin",
        ),
    )
    rows = db.execute(
        "SELECT artifact_id, lineage_revision FROM artifacts "
        "WHERE lineage_id = %s ORDER BY lineage_revision",
        (f"art:{HASH_A}",),
    ).fetchall()
    assert [row[1] for row in rows] == [1, 2]


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_requires_a_sensitivity_label(db):
    """P28: classification is NOT NULL with no default, so it cannot be skipped."""
    import psycopg

    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A, sensitivity_label=None))


@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_database_rejects_an_unknown_sensitivity_label(db):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A, sensitivity_label="PROBABLY_FINE"))


# ---------------------------------------------------------------------------
# EVI-005 at the schema level
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_database_rejects_an_unregistered_condition_schema_version(db):
    """EVI-005 becomes a storage guarantee via a foreign key, not just a write-time check."""
    import psycopg

    db.execute(_INSERT_ARTIFACT, _artifact_params(HASH_A))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "INSERT INTO observations (observation_id, artifact_id, metric_or_event, "
            "conditions, conditions_schema_version, method_ref, project_id) "
            "VALUES ('obs:1', %s, 'toy_metric', '{}'::jsonb, 'toy/basic@9.9.9', "
            "'toy@1.0.0', 'prj:test')",
            (f"art:{HASH_A}",),
        )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_condition_schema_ref_is_generated_not_supplied(db):
    """The application and the database cannot disagree on the reference format."""
    _register_toy_schema(db)
    row = db.execute("SELECT schema_ref FROM condition_schemas WHERE domain = 'toy'").fetchone()
    assert row is not None
    assert row[0] == TOY_SCHEMA_REF


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_database_rejects_a_non_semver_schema_version(db):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation, match="version_is_semver"):
        db.execute(
            "INSERT INTO condition_schemas (domain, schema_id, version, json_schema, "
            "comparator_version) VALUES ('toy', 'basic', '1.0', '{}'::jsonb, 'c1')"
        )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_database_rejects_a_condition_match_contradicting_its_findings(db):
    """A comparator bug reporting EXACT alongside mismatches must not be storable."""
    import psycopg

    _register_toy_schema(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="exact_has_no_findings"):
        db.execute(
            "INSERT INTO condition_matches (condition_match_id, state, mismatches, "
            "tolerance_policy_version, schema_ref) VALUES ('cmt:1', 'EXACT', "
            "'[{\"field\": \"setting\"}]'::jsonb, 'c1', %s)",
            (TOY_SCHEMA_REF,),
        )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_database_accepts_a_consistent_condition_match(db):
    _register_toy_schema(db)
    db.execute(
        "INSERT INTO condition_matches (condition_match_id, state, matched_fields, "
        "tolerance_policy_version, schema_ref) VALUES ('cmt:1', 'EXACT', "
        "ARRAY['setting'], %s, %s)",
        (TOY_SCHEMA.comparator_version, TOY_SCHEMA_REF),
    )
    row = db.execute(
        "SELECT state, tolerance_policy_version FROM condition_matches WHERE "
        "condition_match_id = 'cmt:1'"
    ).fetchone()
    assert row == ("EXACT", TOY_SCHEMA.comparator_version)
