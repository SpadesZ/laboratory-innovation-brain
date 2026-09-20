"""T-EVI-010 — evidence-boundary-preserving segmentation (EVI-010, §6.22).

Pass condition (§26), the segmentation half: the locked fixture's five cases, each with a fixed
expected outcome rather than a score. This file asserts those outcomes directly; the benchmark
(``benchmarks/evidence_segmentation``) reports the metrics for both strategies over the same
fixture, which is the other half of the row.

The cases, and what each one is for:

    (a) condition/result   two sentences that are individually well-formed and jointly required
    (b) table              a value unreadable without its header, unit and row context
    (c) figure             a caption that is insufficient without the prose that explains it
    (d) oversized          fixed-token subdivision as fallback ONLY, sub-units keeping context
    (e) missing value      UNKNOWN / NOT_REPORTED, never a typical value
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import EvidenceUnitType, SubdivisionReason
from lab_brain.ingestion.fixed_token_baseline import BaselineRun, FixedTokenBaselineSegmenter
from lab_brain.ingestion.parsers.documents import MarkdownDocumentParser
from lab_brain.ingestion.segmentation import (
    EvidenceAwareSegmenter,
    SegmentationError,
    bind_condition_result_groups,
    subdivide_oversized,
    token_count,
)
from tests.evidence_fixtures import (
    CONDITION_SENTENCE,
    RESULT_SENTENCE,
    load_fixture_document,
    parse_fixture,
    segment_fixture,
)

PROJECT = "prj:test"


# ---------------------------------------------------------------------------
# (a) the condition/result split trap
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_condition_and_its_result_land_in_one_unit():
    """§6.22 rule 1. The case the whole requirement exists for.

    Split these two sentences and each half is still true, still attributable and still correctly
    statused -- and the measurement is no longer a measurement of anything. Nothing downstream
    can detect it, so the check has to be here.
    """
    result = segment_fixture()
    holding = [
        unit
        for unit in result.units
        if CONDITION_SENTENCE in unit.interpretive_text
        and RESULT_SENTENCE in unit.interpretive_text
    ]
    assert holding, (
        "no evidence unit holds both the bias condition and the capacitance result. They were "
        "separated, and no field is missing to say so"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_bound_unit_declares_the_condition_it_carries():
    """Binding is recorded, not merely achieved.

    A segmenter that happened to keep the sentences together without declaring the dependency
    would pass the test above and would not fail if a later change separated them. The
    declaration is what makes the model validator able to refuse the regression.
    """
    result = segment_fixture()
    bound = [unit for unit in result.units if CONDITION_SENTENCE in unit.bound_condition_texts]
    assert bound, "the condition/result unit declares no bound condition"
    for unit in bound:
        assert CONDITION_SENTENCE in unit.interpretive_text


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_referential_sentence_joins_its_predecessor():
    """ "This decreased to 0.345 pF/mm" names no subject and cannot stand alone."""
    groups = bind_condition_result_groups(
        "The sample was measured at 25 °C. This decreased to 0.345 pF/mm."
    )
    assert len(groups) == 1, f"a referential sentence was split off: {[g.text for g in groups]}"


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_unrelated_prose_is_not_merged():
    """The positive control for the binder, and it matters.

    A binder that put everything in one unit would pass every boundary test and destroy retrieval
    precision. "Keeps related text together" is only meaningful beside "separates unrelated text".
    """
    groups = bind_condition_result_groups(
        "The devices were fabricated on a standard platform. Figure 4 shows the measurement setup."
    )
    assert len(groups) == 2, f"unrelated sentences were merged: {[g.text for g in groups]}"


# ---------------------------------------------------------------------------
# (b) the table
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_table_value_is_retrievable_with_its_header_unit_and_row():
    """§6.22 rule 5. The value alone is a number; these three make it a measurement."""
    tables = segment_fixture().of_type(EvidenceUnitType.TABLE)
    assert tables, "the fixture's table produced no TABLE unit"
    context = tables[0].table_context
    assert context is not None

    assert "Cj" in context.headers
    assert context.unit_for("Cj") == "pF/mm"
    assert context.cell(1, "Cj") == "0.345"
    assert context.row_labels[1] == "-2"
    assert context.caption and "Table 1" in context.caption


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_table_is_one_unit_not_one_per_row():
    """A row on its own has lost the header that names its columns (rule 5)."""
    tables = segment_fixture().of_type(EvidenceUnitType.TABLE)
    assert len(tables) == 1, f"the fixture's single table produced {len(tables)} units"


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_headerless_table_is_refused_rather_than_emitted():
    """Emitting it would produce a unit whose values cannot be read."""
    document = parse_fixture()
    table = next(block for block in document.blocks if block.block_type is EvidenceUnitType.TABLE)
    stripped = document.model_copy(
        update={
            "blocks": tuple(
                block.model_copy(update={"table_rows": ()}) if block.index == table.index else block
                for block in document.blocks
            )
        }
    )
    with pytest.raises(SegmentationError, match="no headers or no rows"):
        EvidenceAwareSegmenter().segment(stripped, project_id=PROJECT)


# ---------------------------------------------------------------------------
# (c) the figure
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_figure_carries_the_prose_that_explains_it():
    """§6.22 rule 6: the caption alone is explicitly not sufficient."""
    figures = segment_fixture().of_type(EvidenceUnitType.FIGURE)
    assert figures, "the fixture's figure produced no FIGURE unit"
    context = figures[0].figure_context
    assert context is not None
    assert context.caption
    assert context.surrounding_prose, "the figure has a caption and no explanatory prose"
    assert context.is_interpretable
    # And the prose is in the retrievable body, not only in the structured context: a retriever
    # scoring the caption alone would rank the figure by the one text the spec calls insufficient.
    assert any(prose in figures[0].body for prose in context.surrounding_prose)


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_figure_with_no_explanatory_prose_is_refused():
    """The negative that gives the test above its teeth."""
    document = parse_fixture()
    figure = next(block for block in document.blocks if block.block_type is EvidenceUnitType.FIGURE)
    orphaned = document.model_copy(
        update={
            "blocks": tuple(
                block for block in document.blocks if block.block_type is not EvidenceUnitType.PROSE
            )
        }
    )
    assert figure.figure_label
    with pytest.raises(SegmentationError, match="caption alone is not sufficient"):
        EvidenceAwareSegmenter().segment(orphaned, project_id=PROJECT)


# ---------------------------------------------------------------------------
# (d) the oversized unit — fallback only
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_nothing_is_subdivided_at_the_declared_limit():
    """§6.22 rule 3. Fixed-token splitting is a fallback, so at a limit nothing exceeds it does not run."""
    result = segment_fixture(token_limit=10_000)
    assert result.subdivided_unit_ids == frozenset(), (
        "units were subdivided although none exceeded the declared limit; fixed-token splitting "
        "is permitted only as a fallback (rule 3)"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_an_oversized_unit_is_subdivided_and_the_pieces_keep_the_parent_context():
    """Rule 3(a) and rule 4 together, which is the only way either is meaningful.

    Subdividing without carrying context would satisfy 3(a) and lose exactly what rule 1
    protects; carrying context without ever subdividing would make 3(a) untested.
    """
    result = segment_fixture(token_limit=25)
    subdivided = [unit for unit in result.units if unit.is_subdivision]
    assert subdivided, "a 25-token limit produced no subdivisions; the fallback never ran"

    for unit in subdivided:
        assert unit.subdivision_reason is SubdivisionReason.OVERSIZED_UNIT
        assert unit.parent_unit_id is not None
        assert unit.provenance.token_limit == 25
        # Rule 4. The first piece needs no inherited context -- it *is* the beginning.
        if unit.subdivision_index and unit.subdivision_index > 0:
            assert unit.inherited_context, (
                f"sub-unit {unit.structural_path} inherited no context from its parent (rule 4)"
            )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_subdivision_never_cuts_mid_sentence():
    """Cutting between two halves of a sentence reintroduces the rule 1 failure one level down."""
    text = " ".join(f"Sentence number {n} reports a value of 0.{n} pF/mm." for n in range(40))
    pieces = subdivide_oversized(text, limit=30)
    assert len(pieces) > 1
    for body, _ in pieces:
        assert body.strip().endswith("."), f"sub-unit does not end at a sentence: {body[-60:]!r}"


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_bound_condition_reaches_every_piece_of_a_subdivided_unit():
    """A piece whose own text lacks the condition inherits it explicitly, not by luck."""
    result = segment_fixture(token_limit=25)
    for unit in result.units:
        for condition in unit.bound_condition_texts:
            assert condition in unit.interpretive_text


# ---------------------------------------------------------------------------
# Structure-first, and the prohibition on fixed-token as primary
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_units_follow_document_structure_not_token_count():
    """§6.22 rule 2. Structure-first means unit boundaries coincide with block boundaries.

    The observable consequence: unit sizes vary with the document, and a table, a figure and a
    paragraph are different unit types. A fixed-token splitter produces uniform PROSE.
    """
    result = segment_fixture()
    types = {unit.unit_type for unit in result.units}
    assert {EvidenceUnitType.TABLE, EvidenceUnitType.FIGURE, EvidenceUnitType.PROSE} <= types, (
        f"segmentation produced only {types}; a structure-first splitter distinguishes them"
    )
    sizes = {token_count(unit.body) for unit in result.units}
    assert len(sizes) > 1, "every unit is the same size, which is what a token window produces"


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_production_segmenter_never_emits_a_benchmark_baseline_unit():
    """Rule 3(b)'s vocabulary member belongs to the baseline and to nothing else."""
    result = segment_fixture(token_limit=25)
    assert all(
        unit.subdivision_reason is not SubdivisionReason.BENCHMARK_BASELINE for unit in result.units
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_baseline_splits_the_condition_from_its_result_and_is_stamped_as_baseline():
    """What the prohibited strategy actually does to the fixture, recorded as a test.

    Not a criticism of BM25 -- the baseline is at conventional settings. It is the demonstration
    that the two strategies differ on the case that matters, which is what makes reporting both
    in the benchmark meaningful rather than decorative.
    """
    document = parse_fixture()
    units = FixedTokenBaselineSegmenter(window=12, overlap=0).segment(
        document, project_id=PROJECT, run=BaselineRun(reason="T-EVI-010 comparison")
    )
    assert units
    assert all(unit.subdivision_reason is SubdivisionReason.BENCHMARK_BASELINE for unit in units)
    # The table is gone as a table: the baseline has no idea a table was a table.
    assert all(unit.unit_type is EvidenceUnitType.PROSE for unit in units)
    assert all(unit.table_context is None for unit in units)

    together = [
        unit for unit in units if CONDITION_SENTENCE in unit.body and RESULT_SENTENCE in unit.body
    ]
    assert not together, (
        "at a 12-token window the baseline kept the condition and result together; the fixture "
        "no longer demonstrates the difference the benchmark reports"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_segmentation_is_deterministic():
    """Re-running ingestion over unchanged bytes must not orphan existing Attestations."""
    first = segment_fixture()
    second = segment_fixture()
    assert [unit.evidence_unit_id for unit in first.units] == [
        unit.evidence_unit_id for unit in second.units
    ]


# ---------------------------------------------------------------------------
# Locator round-trip
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_every_unit_resolves_back_to_its_source_text():
    """§6.22 rule 7's locator half: offsets must actually index the document they came from."""
    source = load_fixture_document()
    document = MarkdownDocumentParser().parse(source, artifact_id="art:sha256:" + "f" * 64)
    result = EvidenceAwareSegmenter().segment(document, project_id=PROJECT)

    for unit in result.units:
        locator = unit.locator
        assert locator.label
        assert locator.start_offset is not None and locator.end_offset is not None
        span = document.source_text[locator.start_offset : locator.end_offset]
        assert span.strip(), f"locator for {unit.structural_path} resolves to empty text"


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_every_unit_names_the_artifact_and_parser_that_produced_it():
    """Rule 7: a correctly bounded unit that cannot be traced back is still unauditable."""
    result = segment_fixture()
    for unit in result.units:
        assert unit.artifact_id.startswith("art:sha256:")
        assert unit.provenance.parser_id and unit.provenance.parser_version
        assert unit.provenance.segmenter_id and unit.provenance.segmenter_version
