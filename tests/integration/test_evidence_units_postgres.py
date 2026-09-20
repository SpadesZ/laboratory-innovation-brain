"""T-EVI-010 — the evidence-unit schema actually rejects (EVI-010, §17.25).

Every CHECK and trigger in ``003a`` and ``009a`` is exercised through raw SQL rather than through
the Pydantic models. The models already refuse these shapes; the question this file answers is
whether the *database* does, because a guard only the application holds is a guard a migration,
a support script or a bulk import walks straight past.

That is the same reasoning ``005c``/``011d``/``011g`` were each written down for, and the reason
the belief-transition work ended up with both a write gate and a read gate.
"""

from __future__ import annotations

import psycopg
import pytest

from lab_brain.core.models import compute_content_hash, evidence_unit_id_for

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EVI-010"),
    pytest.mark.spec_test("T-EVI-010"),
]

PROJECT = "prj:test"
BODY = "Reverse bias increased from 0 to -2 V. Cj decreased from 0.515 to 0.345 pF/mm."
CONDITION = "Reverse bias increased from 0 to -2 V."


def _artifact(db, content: bytes = b"the locked fixture") -> str:
    digest = compute_content_hash(content)
    artifact_id = f"art:{digest}"
    # `lineage_id` is NOT NULL: every artifact is revision 1 of its own lineage unless it says
    # otherwise, which the model defaults and raw SQL must state.
    db.execute(
        "INSERT INTO artifacts "
        "(artifact_id, content_hash, media_type, uri, source_origin, lineage_id) "
        "VALUES (%s, %s, 'text/markdown', 'file:///f.md', 'UPLOAD', %s) "
        "ON CONFLICT (artifact_id) DO NOTHING",
        (artifact_id, digest, artifact_id),
    )
    return artifact_id


def _insert_unit(db, artifact_id: str, **overrides):
    body = overrides.pop("body", BODY)
    path = overrides.pop("structural_path", "3/prose:1/0")
    digest = overrides.pop("content_digest", compute_content_hash(body.encode("utf-8")))
    unit_id = overrides.pop("evidence_unit_id", evidence_unit_id_for(artifact_id, path, digest))
    row = {
        "evidence_unit_id": unit_id,
        "project_id": PROJECT,
        "artifact_id": artifact_id,
        "unit_type": "PROSE",
        "structural_path": path,
        "locator": '{"label": "\\u00a73"}',
        "body": body,
        "content_digest": digest,
        "parser_id": "local_markdown",
        "parser_version": "1.0.0",
        "segmenter_id": "evidence_aware_hierarchical",
        "segmenter_version": "1.0.0",
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    db.execute(
        f"INSERT INTO evidence_units ({columns}) VALUES ({placeholders})", tuple(row.values())
    )
    return unit_id


# ---------------------------------------------------------------------------
# The boundary trigger (§6.22 rule 1)
# ---------------------------------------------------------------------------


def test_a_unit_declaring_a_condition_it_does_not_contain_is_rejected_by_the_database(db):
    """The rule 1 trigger. This is the failure with no other symptom.

    Enforced in SQL as well as in the model because the whole point of EVI-010 is that a severed
    condition leaves no missing field: nothing downstream detects it, so the write path is the
    last place it can be caught.
    """
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="separated from what makes it"):
        _insert_unit(
            db,
            artifact,
            body="Cj decreased from 0.515 to 0.345 pF/mm.",
            bound_condition_texts=[CONDITION],
        )


def test_a_unit_whose_body_contains_its_declared_condition_is_accepted(db):
    """The positive control; without it the trigger could reject everything and still pass."""
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact, bound_condition_texts=[CONDITION])
    stored = db.execute(
        "SELECT body FROM evidence_units WHERE evidence_unit_id = %s", (unit_id,)
    ).fetchone()
    assert stored is not None and CONDITION in stored[0]


def test_inherited_context_satisfies_the_condition_check(db):
    """Rule 4: a condition carried in inherited context is still bound to the result."""
    artifact = _artifact(db)
    parent = _insert_unit(db, artifact, structural_path="3/prose:1/0")
    _insert_unit(
        db,
        artifact,
        structural_path="3/prose:1/0#sub1",
        body="Cj decreased from 0.515 to 0.345 pF/mm.",
        bound_condition_texts=[CONDITION],
        inherited_context=[CONDITION],
        parent_unit_id=parent,
        subdivision_index=1,
        subdivision_reason="OVERSIZED_UNIT",
    )


# ---------------------------------------------------------------------------
# Identity and lineage
# ---------------------------------------------------------------------------


def test_an_identity_that_is_not_shaped_like_a_derived_one_is_rejected(db):
    """The DDL pins the shape; the derivation itself stays in one place, in Python."""
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="evidence_unit_id_is_derived"):
        _insert_unit(db, artifact, evidence_unit_id="evu:not-a-hash")


@pytest.mark.parametrize(
    "partial",
    [
        {"parent_unit_id": "evu:sha256:" + "d" * 64},
        {"subdivision_index": 0},
        {"subdivision_reason": "OVERSIZED_UNIT"},
        {"parent_unit_id": "evu:sha256:" + "d" * 64, "subdivision_index": 0},
    ],
)
def test_partial_subdivision_lineage_is_rejected_by_the_database(db, partial):
    """A sub-unit with a parent and no reason is a token splitter that recorded a parent."""
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="all_or_nothing"):
        _insert_unit(db, artifact, **partial)


def test_an_unknown_subdivision_reason_is_rejected(db):
    """The vocabulary is closed: exactly two permitted reasons (§6.22 rule 3)."""
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="subdivision_reason_is_known"):
        _insert_unit(
            db,
            artifact,
            parent_unit_id="evu:sha256:" + "d" * 64,
            subdivision_index=0,
            subdivision_reason="CHUNKED_FOR_RETRIEVAL",
        )


def test_inherited_context_without_a_parent_is_rejected(db):
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="inherits_only_from_a_parent"):
        _insert_unit(db, artifact, inherited_context=[CONDITION])


# ---------------------------------------------------------------------------
# Typed context (§6.22 rules 5-6)
# ---------------------------------------------------------------------------


def test_a_table_unit_without_table_context_is_rejected(db):
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="table_context_matches_type"):
        _insert_unit(db, artifact, unit_type="TABLE", structural_path="3/table:2")


def test_a_prose_unit_carrying_table_context_is_rejected(db):
    """Both directions: a mislabel would propagate into retrieval unchallenged."""
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="table_context_matches_type"):
        _insert_unit(db, artifact, table_context='{"headers": ["Bias"]}')


def test_a_figure_unit_without_figure_context_is_rejected(db):
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="figure_context_matches_type"):
        _insert_unit(db, artifact, unit_type="FIGURE", structural_path="3/figure:4")


def test_an_unknown_unit_type_is_rejected(db):
    artifact = _artifact(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="unit_type_is_known"):
        _insert_unit(db, artifact, unit_type="CHUNK")


# ---------------------------------------------------------------------------
# ADR-0011's guarantee, at the schema level
# ---------------------------------------------------------------------------


def _insert_representation(db, unit_id: str, **overrides):
    row = {
        "representation_id": overrides.pop("representation_id", f"rrp:{unit_id[-12:]}"),
        "evidence_unit_id": unit_id,
        "project_id": PROJECT,
        "index_id": "idx:lexical:v1",
        "index_kind": "LEXICAL",
        "payload_digest": compute_content_hash(BODY.encode("utf-8")),
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    db.execute(
        f"INSERT INTO retrieval_representations ({columns}) VALUES ({placeholders})",
        tuple(row.values()),
    )
    return row["representation_id"]


def test_dropping_every_representation_for_an_index_changes_no_evidence_unit(db):
    """§17.25, as a SQL statement rather than as a claim about the application.

    This is the schema-level form of "rebuilding an index changes no scientific evidence
    identity", and it is why 009a is a separate table rather than columns on 003a.
    """
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact)
    _insert_representation(db, unit_id)

    before = db.execute(
        "SELECT evidence_unit_id, content_digest, body FROM evidence_units ORDER BY 1"
    ).fetchall()

    db.execute("DELETE FROM retrieval_representations WHERE index_id = 'idx:lexical:v1'")

    after = db.execute(
        "SELECT evidence_unit_id, content_digest, body FROM evidence_units ORDER BY 1"
    ).fetchall()
    assert after == before
    assert db.execute("SELECT count(*) FROM retrieval_representations").fetchone()[0] == 0


def test_a_lexical_representation_naming_an_embedding_space_is_rejected(db):
    """Nothing was embedded, so the name describes no space (EVI-007)."""
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact)
    with pytest.raises(psycopg.errors.CheckViolation, match="embedding_space_is_complete"):
        _insert_representation(
            db, unit_id, embedding_model="text-embedding-3-large", embedding_version="1"
        )


def test_a_dense_representation_without_a_complete_space_is_rejected(db):
    """An unidentified space cannot be filtered on, so mixing spaces becomes possible."""
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact)
    with pytest.raises(psycopg.errors.CheckViolation, match="embedding_space_is_complete"):
        _insert_representation(
            db, unit_id, index_kind="DENSE", embedding_model="text-embedding-3-large"
        )


def test_a_representation_in_another_project_than_its_unit_is_rejected(db):
    """SEC-002 / R-7 through a different door, closed by a trigger because it reads two tables."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other') "
        "ON CONFLICT DO NOTHING"
    )
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact)
    with pytest.raises(psycopg.errors.CheckViolation, match="grants nothing in another"):
        _insert_representation(db, unit_id, project_id="prj:other")


def test_a_representation_for_a_unit_that_does_not_exist_is_rejected(db):
    artifact = _artifact(db)
    _insert_unit(db, artifact)
    with pytest.raises((psycopg.errors.ForeignKeyViolation, psycopg.errors.RaiseException)):
        _insert_representation(db, "evu:sha256:" + "0" * 64)


def test_one_representation_per_unit_per_index(db):
    """Two rows would mean a rebuild appended rather than replaced, ranking a unit twice."""
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact)
    _insert_representation(db, unit_id, representation_id="rrp:1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_representation(db, unit_id, representation_id="rrp:2")


def test_two_indexes_may_hold_the_same_unit(db):
    """The positive control for the constraint above: per-index, not global."""
    artifact = _artifact(db)
    unit_id = _insert_unit(db, artifact)
    _insert_representation(db, unit_id, representation_id="rrp:1", index_id="idx:a")
    _insert_representation(db, unit_id, representation_id="rrp:2", index_id="idx:b")
    assert db.execute("SELECT count(*) FROM retrieval_representations").fetchone()[0] == 2


def test_the_same_structural_path_cannot_be_occupied_twice_in_one_project(db):
    """Re-segmentation is a known limitation (ADR-0011); attempting it fails loudly.

    Without this a second segmenter version would write a parallel set of units at the same
    paths, and a query by path would silently return whichever came back first.
    """
    artifact = _artifact(db)
    _insert_unit(db, artifact, body="First boundary.")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_unit(db, artifact, body="A differently cut boundary.")
