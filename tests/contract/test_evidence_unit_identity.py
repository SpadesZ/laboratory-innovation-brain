"""T-EVI-010 — canonical evidence identity vs retrieval representation (EVI-010, ADR-0011).

Pass condition (§26), the identity half:

    deleting and rebuilding an index changes no `evidence_unit_id`; a retrieved payload cannot be
    admitted as an Attestation without passing the ordinary admission gates.

The boundary-preservation half is in ``test_evidence_segmentation.py`` and the benchmark; this
file is about the two objects and what each may and may not carry.

Every test here is a negative or an invariance claim. "The model has the fields we expect" is not
one of them -- a schema assertion passes on a model that happens to compile, and what EVI-010
needs is that the wrong thing is *impossible*.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lab_brain.core.models import (
    EvidenceUnit,
    EvidenceUnitType,
    RetrievalCandidate,
    RetrievalIndexKind,
    RetrievalRepresentation,
    SegmenterProvenance,
    SourceLocator,
    SubdivisionReason,
    TableContext,
    compute_content_hash,
    evidence_unit_id_for,
)
from lab_brain.evidence.retriever import LexicalEvidenceIndex

ARTIFACT = "art:sha256:" + "a" * 64
PROJECT = "prj:test"


def _provenance() -> SegmenterProvenance:
    return SegmenterProvenance(
        segmenter_id="evidence_aware_hierarchical",
        segmenter_version="1.0.0",
        parser_id="local_markdown",
        parser_version="1.0.0",
        token_limit=320,
    )


def _unit(
    body: str = "Cj fell to 0.345 pF/mm.", path: str = "3/prose:1/0", **extra
) -> EvidenceUnit:
    return EvidenceUnit.build(
        artifact_id=ARTIFACT,
        unit_type=EvidenceUnitType.PROSE,
        structural_path=path,
        locator=SourceLocator(label="§3"),
        body=body,
        provenance=_provenance(),
        **extra,
    )


# ---------------------------------------------------------------------------
# Identity is derived, and derived from exactly three things
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_identity_is_recomputed_and_a_mismatch_is_refused():
    """An id that does not match its content cannot be constructed.

    The same guarantee ``Artifact`` has. Without it a unit could be addressed as one thing and
    hold another, and every re-resolution at admission would be checking the wrong record.
    """
    good = _unit()
    with pytest.raises(ValidationError, match="not the derived identity"):
        EvidenceUnit.model_validate(
            good.model_dump() | {"evidence_unit_id": "evu:sha256:" + "b" * 64}
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_body_that_disagrees_with_its_digest_is_refused():
    """The digest is not a free parameter; it must be the digest of *this* body.

    Constructed so the identity check cannot fire first and mask the one under test: the id is
    recomputed for the substituted digest, so the record is internally consistent about its own
    identity and wrong only about what it holds. That is the interesting forgery -- a row whose
    id resolves correctly and whose body is somebody else's.
    """
    unit = _unit()
    foreign = compute_content_hash(b"something else")
    with pytest.raises(ValidationError, match="content_digest does not match body"):
        EvidenceUnit.model_validate(
            unit.model_dump()
            | {
                "content_digest": foreign,
                "evidence_unit_id": evidence_unit_id_for(
                    unit.artifact_id, unit.structural_path, foreign
                ),
            }
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_same_text_at_two_positions_is_two_units():
    """``structural_path`` is part of identity, so a repeated sentence is not one unit.

    An abstract and a conclusion routinely say the same sentence. Collapsing them would make a
    citation ambiguous about which one was read, and would count one document twice.
    """
    abstract = _unit(path="1/prose:0/0")
    conclusion = _unit(path="7/prose:9/0")
    assert abstract.body == conclusion.body
    assert abstract.evidence_unit_id != conclusion.evidence_unit_id


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_identity_does_not_depend_on_any_retrieval_parameter():
    """THE ADR-0011 invariant, asserted against the derivation directly.

    ``evidence_unit_id_for`` takes three arguments and none of them is an embedding model, a
    version, a dimensionality, a reranker or a token window. Stated as a test rather than a
    comment so that widening the signature fails here.
    """
    import inspect

    parameters = list(inspect.signature(evidence_unit_id_for).parameters)
    assert parameters == ["artifact_id", "structural_path", "content_digest"], (
        f"evidence identity derivation takes {parameters}; EVI-010 fixes it at exactly "
        "(artifact_id, structural_path, content_digest) so no retrieval parameter can enter it"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_rebuilding_an_index_changes_no_evidence_identity():
    """§17.25: dropping every representation for an index MUST NOT touch any EvidenceUnit."""
    units = [
        _unit(body=f"Measurement {n} was 0.3{n} pF/mm.", path=f"3/prose:{n}/0") for n in range(4)
    ]
    before = [unit.evidence_unit_id for unit in units]
    digests_before = [unit.content_digest for unit in units]

    index = LexicalEvidenceIndex()
    index.add_all(units, project_id=PROJECT)
    assert index.size == 4

    index.drop()
    assert index.size == 0
    index.add_all(units, project_id=PROJECT)

    assert [unit.evidence_unit_id for unit in units] == before
    assert [unit.content_digest for unit in units] == digests_before


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_two_indexes_over_the_same_unit_share_its_identity():
    """A unit is one unit however many indexes hold it -- the representations differ, not it."""
    unit = _unit()
    lexical = LexicalEvidenceIndex("idx:a")
    other = LexicalEvidenceIndex("idx:b")
    first = lexical.add(unit, project_id=PROJECT)
    second = other.add(unit, project_id=PROJECT)

    assert first.representation_id != second.representation_id
    assert first.evidence_unit_id == second.evidence_unit_id == unit.evidence_unit_id


# ---------------------------------------------------------------------------
# What each object may not carry
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
@pytest.mark.parametrize(
    "field", ["embedding", "vector", "embedding_model", "embedding_version", "dimensions"]
)
def test_an_evidence_unit_cannot_carry_an_embedding(field: str):
    """The field whose absence ADR-0011 is about.

    ``CoreModel`` forbids extra fields, so this is a ValidationError rather than a silently
    accepted kwarg -- which is the difference between a rule and a convention.
    """
    with pytest.raises(ValidationError):
        EvidenceUnit.model_validate(_unit().model_dump() | {field: "text-embedding-3-large"})


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_retrieval_candidate_has_no_body_to_read():
    """Give a candidate a body and admission can read evidence out of the retriever's output."""
    assert "body" not in RetrievalCandidate.model_fields
    assert "text" not in RetrievalCandidate.model_fields
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            evidence_unit_id="evu:sha256:" + "c" * 64,
            representation_id="rrp:1",
            project_id=PROJECT,
            score=1.0,
            rank=1,
            body="whatever the index happened to hold",
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_lexical_representation_may_not_name_an_embedding_space():
    """Recording a model on a lexical index invites a later cosine against a space nothing is in."""
    with pytest.raises(ValidationError, match="lexical index has no embedding space"):
        RetrievalRepresentation(
            evidence_unit_id="evu:sha256:" + "c" * 64,
            project_id=PROJECT,
            index_id="idx:lexical",
            index_kind=RetrievalIndexKind.LEXICAL,
            embedding_model="text-embedding-3-large",
            embedding_version="1",
            payload_digest=compute_content_hash(b"x"),
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_dense_representation_must_name_its_space_completely():
    """EVI-007 filters on model+version; an unidentified space makes that impossible."""
    with pytest.raises(ValidationError, match="embedding_model and embedding_version"):
        RetrievalRepresentation(
            evidence_unit_id="evu:sha256:" + "c" * 64,
            project_id=PROJECT,
            index_id="idx:dense",
            index_kind=RetrievalIndexKind.DENSE,
            embedding_model="text-embedding-3-large",
            payload_digest=compute_content_hash(b"x"),
        )


# ---------------------------------------------------------------------------
# Subdivision lineage (§6.22 rules 3-4)
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
@pytest.mark.parametrize(
    "partial",
    [
        {"parent_unit_id": "evu:sha256:" + "d" * 64},
        {"subdivision_index": 0},
        {"subdivision_reason": SubdivisionReason.OVERSIZED_UNIT},
        {"parent_unit_id": "evu:sha256:" + "d" * 64, "subdivision_index": 0},
    ],
)
def test_partial_subdivision_lineage_is_refused(partial: dict):
    """A sub-unit with a parent and no reason is a token splitter that recorded a parent.

    Rule 3 permits subdivision for exactly two reasons and requires the record to say which.
    Accepting partial lineage would let the practice the rule forbids wear the shape it allows.
    """
    with pytest.raises(ValidationError, match="together"):
        _unit(**partial)


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_inherited_context_requires_a_parent():
    """Context is inherited from a parent unit, or it is this unit's own body."""
    with pytest.raises(ValidationError, match="inherited_context is set on a unit with no parent"):
        _unit(inherited_context=("Reverse bias was -2 V.",))


# ---------------------------------------------------------------------------
# Typed context (§6.22 rules 5-6)
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_table_unit_without_table_context_is_refused():
    """Rule 5: without headers, units and row/column context the values cannot be read."""
    with pytest.raises(ValidationError, match="TABLE evidence unit must carry table_context"):
        EvidenceUnit.build(
            artifact_id=ARTIFACT,
            unit_type=EvidenceUnitType.TABLE,
            structural_path="3/table:2",
            locator=SourceLocator(label="§3 / Table 1"),
            body="| 0 | 0.515 |",
            provenance=_provenance(),
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_figure_unit_without_figure_context_is_refused():
    """Rule 6: a caption alone is not sufficient to read a figure."""
    with pytest.raises(ValidationError, match="FIGURE evidence unit must carry figure_context"):
        EvidenceUnit.build(
            artifact_id=ARTIFACT,
            unit_type=EvidenceUnitType.FIGURE,
            structural_path="3/figure:4",
            locator=SourceLocator(label="§3 / Fig. 2"),
            body="Fig. 2. Cj versus bias.",
            provenance=_provenance(),
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_prose_unit_carrying_table_context_is_refused():
    """The other direction. A mislabel would propagate into retrieval unchallenged."""
    with pytest.raises(ValidationError, match="only TABLE may"):
        _unit(table_context=TableContext(headers=("Bias",), rows=(("0",),)))


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_units_row_misaligned_with_its_headers_is_refused():
    """A drifted unit list labels every value with its neighbour's unit -- worse than none."""
    with pytest.raises(ValidationError, match="positionally misaligned"):
        TableContext(headers=("Bias", "Cj", "Rs"), units=("V", "pF/mm"), rows=(("0", "1", "2"),))


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_ragged_table_is_refused():
    """A table that cannot be read by column is one whose units do not apply to anything."""
    with pytest.raises(ValidationError, match="do not have 3 cells"):
        TableContext(headers=("Bias", "Cj", "Rs"), rows=(("0", "0.515"),))


# ---------------------------------------------------------------------------
# The boundary declaration (§6.22 rule 1)
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_unit_declaring_a_condition_it_does_not_contain_is_refused():
    """The check that turns segmenter behaviour into a property of the record.

    This is the failure with no other symptom: every field is present and correctly statused, and
    the only thing wrong is that the result no longer sits beside what makes it readable.
    """
    with pytest.raises(ValidationError, match="separated from what makes it interpretable"):
        _unit(
            body="The junction capacitance decreased from 0.515 to 0.345 pF/mm.",
            bound_condition_texts=("Reverse bias increased from 0 to -2 V.",),
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_subdivided_unit_satisfies_the_declaration_through_inherited_context():
    """Rule 4: a condition carried in inherited context is still bound to the result.

    The positive control for the test above. Without it the boundary check could be satisfied by
    refusing every subdivision, which would make rule 3(a) unusable rather than exceptional.
    """
    condition = "Reverse bias increased from 0 to -2 V."
    unit = _unit(
        body="The junction capacitance decreased from 0.515 to 0.345 pF/mm.",
        path="3/prose:1/0#sub1",
        parent_unit_id="evu:sha256:" + "e" * 64,
        subdivision_index=1,
        subdivision_reason=SubdivisionReason.OVERSIZED_UNIT,
        inherited_context=(condition,),
        bound_condition_texts=(condition,),
    )
    assert condition in unit.interpretive_text
    assert condition not in unit.body
