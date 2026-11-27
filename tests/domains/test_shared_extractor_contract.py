"""T-DOM-SP-002 and T-EVI-001 — the one extractor contract, and what EVI-001 requires around it.

§26's two rows:

    DOM-SP-002  同一 `extract_cj_rs` contract 通過 simulated impedance 與 measured impedance
                fixtures。
    EVI-001     Cj/Rs fixture missing unit、normalization basis、bias/frequency condition 或
                extraction method 時 admission fail；完整 fixture 可 round-trip。

THE EXIT-GATE CLAUSE IS STRUCTURAL HERE, NOT BEHAVIOURAL. "Simulated and measured fixtures use the
same extractor contract" is satisfied trivially by two implementations that happen to return
similarly-shaped dictionaries, and that arrangement fails the moment one of them is corrected. So
the tests below assert the *types* are one type -- same `ExtractionInput`, same `ExtractionResult`,
same `MetricExtractor` protocol, one registered extractor instance -- and separately assert that
the provenance is NOT shared: a simulated result and a measured result over identical arrays are
distinguishable, and mislabelling one as the other is refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from lab_brain.core.models.enums import EpistemicType
from lab_brain.domains.silicon_photonics.extractors import CJ, RS, CjRsExtractor
from lab_brain.tools.extraction import (
    ExtractionContractError,
    ExtractionInput,
    ExtractionResult,
    ExtractionSource,
    MetricExtractor,
)
from tests import sp_fixtures as fx

pytestmark = [
    pytest.mark.requirement("DOM-SP-002"),
    pytest.mark.spec_test("T-DOM-SP-002"),
]

EXTRACTOR = fx.extractor()


@contextmanager
def refused(match: str) -> Iterator[None]:
    """Assert a contract refusal by its MESSAGE, whichever wrapper carries it.

    pydantic re-raises a `ValueError` thrown inside a `model_validator` as its own
    `ValidationError` with the original text embedded, so a refusal raised from a validator and one
    raised from a plain helper arrive as different types carrying the same sentence. Matching on
    the sentence is what these tests are actually about -- a refusal that changed its reason would
    pass a type-only check while no longer refusing what it was written to refuse.
    """
    with pytest.raises((ExtractionContractError, ValidationError)) as raised:
        yield
    assert match in str(raised.value), f"expected {match!r} in: {raised.value}"


# ---------------------------------------------------------------------------
# DOM-SP-002 clause: the SAME contract, proven structurally
# ---------------------------------------------------------------------------


def test_one_extractor_instance_serves_both_modalities():
    """THE clause. The same object, the same call, both fixtures -- and equal numbers.

    Equal numbers matter as much as equal types: §10.2.2 says splitting this tool "would allow
    simulated and measured paths to diverge in normalization", and the fixtures carry identical
    arrays precisely so a divergence in the reduction would show up as a difference here.
    """
    simulated = EXTRACTOR.extract(fx.simulated_input())
    measured = EXTRACTOR.extract(fx.measured_input())

    assert type(simulated) is type(measured) is ExtractionResult
    for name in (CJ, RS):
        left, right = simulated.quantity(name), measured.quantity(name)
        assert left is not None and right is not None
        assert left.value == right.value, f"{name} diverged between the two paths"
        assert left.unit == right.unit
        assert left.normalization_basis == right.normalization_basis
        assert left.method == right.method


def test_there_is_exactly_one_extraction_protocol_and_one_input_type():
    """No `SimulatedExtractor`, no `MeasuredExtractor`, no second payload type.

    Structural, and it is the assertion that survives a refactor: every behavioural test above
    would still pass if someone added a parallel protocol and left this extractor on the old one.
    """
    assert isinstance(EXTRACTOR, MetricExtractor)
    assert EXTRACTOR.request_model is ExtractionInput
    assert EXTRACTOR.result_model is ExtractionResult

    import lab_brain.tools.extraction as extraction

    parallel = [
        name
        for name in dir(extraction)
        if name.endswith(("Extractor", "ExtractionInput", "ExtractionResult"))
        and name not in {"MetricExtractor", "ExtractionInput", "ExtractionResult"}
    ]
    assert not parallel, (
        f"a second extraction type appeared: {parallel}. One contract means one type -- two makes "
        "'the same extractor contract' a claim about two things that currently agree"
    )


def test_the_extractor_source_never_branches_on_modality():
    """`if source.is_simulated:` inside a reduction is the divergence, before it has happened."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(CjRsExtractor))
    reads = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"is_simulated", "modality"}
    ]
    assert not reads, (
        f"the extractor reads {reads}; a reduction that knows which modality produced its arrays "
        "is one that can be corrected for one and not the other (DOM-SP-002)"
    )


# ---------------------------------------------------------------------------
# ...and the provenance is NOT shared
# ---------------------------------------------------------------------------


def test_simulated_and_measured_results_remain_distinguishable():
    """Uniform interface, distinct provenance. §10.6 needs two things to be able to disagree."""
    simulated = EXTRACTOR.extract(fx.simulated_input())
    measured = EXTRACTOR.extract(fx.measured_input())

    assert simulated.modality is EpistemicType.SIMULATED
    assert measured.modality is EpistemicType.MEASURED
    assert simulated.source.run_id is not None and simulated.source.source_artifact_id is None
    assert measured.source.source_artifact_id is not None and measured.source.run_id is None
    assert simulated.source.provenance_ref != measured.source.provenance_ref


def test_a_simulated_source_with_no_run_is_refused():
    """EVI-009 through the extraction boundary: a solver result must name its Run."""
    with refused("names no run_id"):
        ExtractionSource(
            modality=EpistemicType.SIMULATED,
            project_id=fx.PROJECT,
            backend_id="mock.charge.ac",
            backend_version="0.1.0",
            conditions=dict(fx.CONDITIONS),
            conditions_schema_version=fx.simulated_source().conditions_schema_version,
            backend_validity_schema="x/y@1.0.0",
            backend_validity=dict(fx.VALIDITY),
        )


def test_a_measured_source_with_no_artifact_is_refused():
    """The opposite number. A measurement's primary record is the instrument's artifact."""
    with refused("names no source_artifact_id"):
        ExtractionSource(
            modality=EpistemicType.MEASURED,
            project_id=fx.PROJECT,
            backend_id="lab.impedance_analyzer",
            backend_version="fixture-1",
            conditions=dict(fx.CONDITIONS),
            conditions_schema_version=fx.simulated_source().conditions_schema_version,
        )


def test_measured_provenance_cannot_be_relabelled_as_simulated():
    """THE mislabelling attack the exit gate's "distinct provenance kind" clause is about.

    Taking a measured source and stamping SIMULATED on it does not produce a simulation: the
    contract demands a Run and a validity record, and a measurement has neither. Refused at the
    boundary rather than discovered when someone asks the Run id to resolve.
    """
    measured = fx.measured_source()
    with refused("names no run_id"):
        measured.model_copy(update={"modality": EpistemicType.SIMULATED}).model_validate(
            {**measured.model_dump(), "modality": EpistemicType.SIMULATED}
        )


def test_simulated_provenance_cannot_be_relabelled_as_measured():
    """And the reverse. A Run is not an instrument record."""
    simulated = fx.simulated_source()
    with refused("names no source_artifact_id"):
        ExtractionSource.model_validate(
            {**simulated.model_dump(), "modality": EpistemicType.MEASURED, "run_id": None}
        )


def test_an_inferred_payload_cannot_enter_the_extraction_boundary():
    """EVI-003 at this seam: an LLM interpretation must not acquire normalization provenance."""
    with refused("accepts only"):
        ExtractionSource.model_validate(
            {**fx.simulated_source().model_dump(), "modality": EpistemicType.INFERRED}
        )
