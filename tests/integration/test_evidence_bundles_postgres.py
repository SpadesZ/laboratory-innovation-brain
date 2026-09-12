"""EvidenceBundle persistence at the schema level (EVI-006).

§22's Bundle Reproducibility criterion requires any LLM scientific output to trace to a canonical
bundle hash and **reconstruct the same ordered evidence set**. So the ordering has to survive
storage, and the constraints that protect it have to actually reject -- a constraint present in a
migration but rejecting nothing is the failure mode these tests exist to catch.

Ordering lives in a child table with an explicit position rather than an array column, so the
database can enforce contiguity and no-duplicates instead of trusting the application.
"""

from __future__ import annotations

import json

import pytest

from lab_brain.core.models import compute_content_hash
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from tests.conftest_fixtures import TOY_SCHEMA, TOY_SCHEMA_REF

pytestmark = pytest.mark.postgres

HASH_A = compute_content_hash(b"bundle source artifact")

_INSERT_BUNDLE = """
INSERT INTO evidence_bundles (bundle_id, schema_version, research_intent, stakes, query_text,
                              query_hash, source_policy_id, source_policy_version,
                              condition_filter, condition_schema_versions, project_id,
                              canonical_hash)
VALUES (%(bundle_id)s, 1, 'DIAGNOSIS', 'HIGH', %(query_text)s, %(query_hash)s,
        'sp:diagnosis', '1.0.0', %(condition_filter)s, '{}'::jsonb, 'prj:test',
        %(canonical_hash)s)
"""

_INSERT_MEMBER = """
INSERT INTO evidence_bundle_members (bundle_id, position, attestation_id)
VALUES (%(bundle_id)s, %(position)s, %(attestation_id)s)
"""


def make_bundle(**overrides) -> EvidenceBundle:
    fields = {
        "research_intent": ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        "query_text": "why is Rs weakly bias-dependent",
        "source_policy_id": "sp:diagnosis",
        "source_policy_version": "1.0.0",
        "condition_filter": {"setting": "nominal"},
        "ordered_attestation_ids": ("att:a", "att:b", "att:c"),
        "project_id": "prj:test",
    }
    fields.update(overrides)
    return EvidenceBundle(**fields)


@pytest.fixture
def db_with_attestations(db):  # type: ignore[no-untyped-def]
    """Three attestations for bundle members to reference."""
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
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, lineage_id, "
        "source_origin, sensitivity_label, project_id) "
        "VALUES (%s, %s, 'application/pdf', 'file:///p.pdf', %s, 'UPLOAD', 'INTERNAL', "
        "'prj:test')",
        (f"art:{HASH_A}", HASH_A, f"art:{HASH_A}"),
    )
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'p')")
    for suffix in ("a", "b", "c"):
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, "
            "source_artifact_id, locator, conditions, conditions_schema_version, project_id, "
            "extractor_version, extraction_provenance) "
            "VALUES (%s, 'clm:1', 'REPORTED', %s, 'p.1', '{\"setting\": \"nominal\"}'::jsonb, "
            "%s, 'prj:test', '1.0.0', "
            '\'{"extractor_id": "toy", "extractor_version": "1.0.0"}\'::jsonb)',
            (f"att:{suffix}", f"art:{HASH_A}", TOY_SCHEMA_REF),
        )
    return db


def _store(db, bundle: EvidenceBundle) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        _INSERT_BUNDLE,
        {
            "bundle_id": bundle.bundle_id,
            "query_text": bundle.query_text,
            "query_hash": bundle.query_hash,
            "condition_filter": json.dumps(bundle.condition_filter),
            "canonical_hash": bundle.canonical_hash,
        },
    )
    for position, attestation_id in enumerate(bundle.ordered_attestation_ids):
        db.execute(
            _INSERT_MEMBER,
            {
                "bundle_id": bundle.bundle_id,
                "position": position,
                "attestation_id": attestation_id,
            },
        )


# ---------------------------------------------------------------------------
# Ordering survives storage
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_stored_bundle_reconstructs_the_same_ordered_evidence_set(db_with_attestations):
    """The §22 Bundle Reproducibility criterion, end to end through the database."""
    bundle = make_bundle(ordered_attestation_ids=("att:c", "att:a", "att:b"))
    _store(db_with_attestations, bundle)

    rows = db_with_attestations.execute(
        "SELECT attestation_id FROM evidence_bundle_members WHERE bundle_id = %s ORDER BY position",
        (bundle.bundle_id,),
    ).fetchall()
    reconstructed = tuple(row[0] for row in rows)

    assert reconstructed == bundle.ordered_attestation_ids
    # And the reconstructed set hashes back to the stored hash.
    rebuilt = make_bundle(
        bundle_id=bundle.bundle_id,
        created_at=bundle.created_at,
        ordered_attestation_ids=reconstructed,
    )
    stored_hash = db_with_attestations.execute(
        "SELECT canonical_hash FROM evidence_bundles WHERE bundle_id = %s", (bundle.bundle_id,)
    ).fetchone()
    assert stored_hash is not None
    assert rebuilt.canonical_hash == stored_hash[0]


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_an_empty_bundle_can_be_stored(db_with_attestations):
    """ "We searched under this policy and found nothing" must be recordable."""
    bundle = make_bundle(ordered_attestation_ids=())
    _store(db_with_attestations, bundle)
    count = db_with_attestations.execute(
        "SELECT count(*) FROM evidence_bundle_members WHERE bundle_id = %s", (bundle.bundle_id,)
    ).fetchone()
    assert count is not None
    assert count[0] == 0


# ---------------------------------------------------------------------------
# The constraints protecting the order actually reject
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_database_rejects_a_duplicate_attestation_in_one_bundle(db_with_attestations):
    """Double-counts evidence before EVI-004's independence resolution is reached."""
    import psycopg

    bundle = make_bundle(ordered_attestation_ids=("att:a",))
    _store(db_with_attestations, bundle)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_with_attestations.execute(
            _INSERT_MEMBER,
            {"bundle_id": bundle.bundle_id, "position": 1, "attestation_id": "att:a"},
        )


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_database_rejects_a_gap_in_member_positions(db_with_attestations):
    """A gap means the stored order cannot be replayed, so the bundle no longer reconstructs."""
    import psycopg

    bundle = make_bundle(ordered_attestation_ids=())
    _store(db_with_attestations, bundle)
    # Positions 0 and 2, skipping 1. The trigger is deferred, so it fires at commit.
    with db_with_attestations.transaction():
        db_with_attestations.execute(
            _INSERT_MEMBER,
            {"bundle_id": bundle.bundle_id, "position": 0, "attestation_id": "att:a"},
        )
        db_with_attestations.execute(
            _INSERT_MEMBER,
            {"bundle_id": bundle.bundle_id, "position": 2, "attestation_id": "att:b"},
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="contiguous"):
            db_with_attestations.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_database_rejects_a_negative_position(db_with_attestations):
    import psycopg

    bundle = make_bundle(ordered_attestation_ids=())
    _store(db_with_attestations, bundle)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_with_attestations.execute(
            _INSERT_MEMBER,
            {"bundle_id": bundle.bundle_id, "position": -1, "attestation_id": "att:a"},
        )


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_database_rejects_a_member_referencing_an_unknown_attestation(db_with_attestations):
    """A bundle citing evidence that does not exist is not reproducible."""
    import psycopg

    bundle = make_bundle(ordered_attestation_ids=())
    _store(db_with_attestations, bundle)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_with_attestations.execute(
            _INSERT_MEMBER,
            {"bundle_id": bundle.bundle_id, "position": 0, "attestation_id": "att:nonexistent"},
        )


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
@pytest.mark.parametrize(
    "bad_hash", ["not-a-hash", "sha256:tooshort", "md5:" + "0" * 32, "sha256:" + "A" * 64]
)
def test_database_rejects_a_malformed_canonical_hash(db_with_attestations, bad_hash):
    """The database cannot recompute a JCS hash, so it constrains the format instead.

    Reimplementing RFC 8785 in plpgsql would give two canonicalisation implementations, which is
    precisely how hashes start disagreeing. The repository verifies the value on read.
    """
    import psycopg

    bundle = make_bundle()
    with pytest.raises(psycopg.errors.CheckViolation, match="hash_format"):
        db_with_attestations.execute(
            _INSERT_BUNDLE,
            {
                "bundle_id": bundle.bundle_id,
                "query_text": bundle.query_text,
                "query_hash": bundle.query_hash,
                "condition_filter": json.dumps(bundle.condition_filter),
                "canonical_hash": bad_hash,
            },
        )


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_the_same_retrieval_may_recur_as_a_second_bundle(db_with_attestations):
    """`canonical_hash` is indexed but not unique: the same retrieval legitimately repeats.

    Each occurrence is its own record with its own id and timestamp, and both share the hash --
    which is what makes "has this exact retrieval happened before" answerable.
    """
    first = make_bundle()
    second = make_bundle()
    assert first.canonical_hash == second.canonical_hash
    assert first.bundle_id != second.bundle_id

    _store(db_with_attestations, first)
    _store(db_with_attestations, second)

    rows = db_with_attestations.execute(
        "SELECT bundle_id FROM evidence_bundles WHERE canonical_hash = %s ORDER BY bundle_id",
        (first.canonical_hash,),
    ).fetchall()
    assert len(rows) == 2
