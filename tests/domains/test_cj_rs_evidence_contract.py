"""T-EVI-001 — what Cj/Rs evidence must carry around the number (§25.3, §10.2.2).

    EVI-001    Cj/Rs evidence 必須含 unit、normalization basis、bias/frequency conditions 與
               extraction method。
    T-EVI-001  Cj/Rs fixture missing unit、normalization basis、bias/frequency condition 或
               extraction method 時 admission fail；完整 fixture 可 round-trip。

FOUR CLAUSES, AND THE ONE THAT LOOKS LIKE BOOKKEEPING IS THE NORMALIZATION BASIS. A capacitance
with a unit and no basis is a number that cannot be compared to another laboratory's -- which is
the only reason to extract it. So the model refuses a present value that is missing any of the
four, rather than leaving the refusal to admission: a quantity that can be CONSTRUCTED without a
basis is one that will reach admission and be refused there, by which point every layer in between
has already trusted the extractor that made it.

THE FIXTURES ARE SYNTHETIC. Every value in `tests/sp_fixtures.py` is a round decimal chosen so the
extractor's output is exactly predictable; none of it is measured, and none of it comes from any
real project. What the tests assert against is the declared model, not a transcribed constant.

The paired simulated/measured half of DOM-SP-002 lives in `test_shared_extractor_contract.py`;
this file is about what each extracted quantity must carry.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lab_brain.core.models.enums import FieldStatus
from lab_brain.domains.silicon_photonics.extractors import CJ, RS, CjRsExtractor
from lab_brain.tools.extraction import ExtractionInput
from tests import sp_fixtures as fx
from tests.refusals import refused

pytestmark = [pytest.mark.requirement("EVI-001"), pytest.mark.spec_test("T-EVI-001")]

EXTRACTOR = CjRsExtractor()

# ---------------------------------------------------------------------------
# EVI-001: unit, normalization basis, conditions, extraction method
# ---------------------------------------------------------------------------


def test_a_complete_fixture_round_trips_with_all_four_evi_001_clauses():
    """The positive control, checked clause by clause rather than "it returned something"."""
    for payload in (fx.simulated_input(), fx.measured_input()):
        result = EXTRACTOR.extract(payload)
        for name in (CJ, RS):
            quantity = result.quantity(name)
            assert quantity is not None and quantity.value is not None
            assert quantity.unit, f"{name} has no unit"
            assert quantity.normalization_basis, f"{name} has no normalization basis"
            assert quantity.method, f"{name} records no extraction method"
            assert quantity.method["model"] == "series_rc"
            assert quantity.method["formula"]
        # The bias/frequency conditions travel on the source, shared by both quantities so that
        # two metrics from one sweep cannot disagree about the bias they were taken at.
        assert result.source.conditions["bias_v"] == str(fx.BIAS_V)
        assert result.source.conditions["frequency_hz"] == str(fx.FREQUENCY_HZ)


def test_a_value_without_a_unit_or_a_basis_or_a_method_is_unrepresentable():
    """EVI-001's four clauses, each refused on its own.

    At the MODEL rather than at admission, deliberately: a quantity that can be constructed without
    a normalization basis is one that will reach admission and be refused there, at which point the
    extractor that produced it has already been trusted by everything in between.
    """
    from lab_brain.tools.extraction import ExtractedQuantity

    complete = {
        "name": CJ,
        "value": Decimal("1.5"),
        "unit": "fF/um",
        "status": FieldStatus.DERIVED,
        "normalization_basis": "per_unit_device_length_um",
        "method": {"model": "series_rc"},
    }
    assert ExtractedQuantity(**complete).value == Decimal("1.5")

    for omitted in ("unit", "normalization_basis", "method"):
        partial = dict(complete)
        partial[omitted] = None if omitted != "method" else {}
        with refused("EVI-001"):
            ExtractedQuantity(**partial)


def test_a_missing_normalization_condition_yields_unknown_and_not_a_number():
    """EVI-002 inside EVI-001. No length means no basis, and no basis means no value.

    The alternative -- emitting the un-normalized total and calling it per-length -- is the failure
    the normalization-basis clause exists to make impossible, and it is the one a careless
    implementation reaches for because it produces a plausible number.
    """
    conditions = {k: v for k, v in fx.CONDITIONS.items() if k != "device_length_um"}
    result = EXTRACTOR.extract(fx.extraction_input(fx.simulated_source(conditions=conditions)))
    for name in (CJ, RS):
        quantity = result.quantity(name)
        assert quantity is not None
        assert quantity.status is FieldStatus.UNKNOWN
        assert quantity.value is None
    assert any("device_length_um" in warning for warning in result.warnings)


def test_a_missing_impedance_series_yields_unknown_rather_than_raising():
    """An incomplete sweep must not be indistinguishable from a broken extractor."""
    payload = ExtractionInput(
        project_id=fx.PROJECT,
        trace_id=fx.TRACE,
        source=fx.simulated_source(),
        series=fx.series()[:2],  # bias and frequency only
    )
    result = EXTRACTOR.extract(payload)
    assert all(q.status is FieldStatus.UNKNOWN for q in result.quantities)
    assert any("impedance_real_ohm" in warning for warning in result.warnings)


def test_a_non_capacitive_sample_reports_unknown_cj_and_still_reports_rs():
    """A positive reactance is not a capacitance. UNKNOWN, never a negative Cj.

    Rs survives, because Re(Z) is still a resistance -- reporting both as UNKNOWN would discard a
    number that is perfectly good, and reporting a negative Cj would put a plausible-looking value
    into every downstream comparison.
    """
    result = EXTRACTOR.extract(fx.simulated_input(imag=Decimal("1200")))
    cj, rs = result.quantity(CJ), result.quantity(RS)
    assert cj is not None and cj.status is FieldStatus.UNKNOWN and cj.value is None
    assert rs is not None and rs.value is not None
    assert any("not negative" in warning for warning in result.warnings)


def test_the_two_quantities_normalize_in_opposite_directions():
    """Cj scales with length, Rs against it. Getting this backwards is silently plausible.

    Asserted by doubling the device length and checking which way each value moves: a
    normalization that multiplied both would produce numbers that pass every shape check and are
    not comparable between devices.
    """
    base = EXTRACTOR.extract(fx.simulated_input())
    doubled_conditions = {
        **fx.CONDITIONS,
        "device_length_um": str(fx.DEVICE_LENGTH_UM * 2),
    }
    doubled = EXTRACTOR.extract(
        fx.extraction_input(fx.simulated_source(conditions=doubled_conditions))
    )

    base_cj, base_rs = base.quantity(CJ), base.quantity(RS)
    long_cj, long_rs = doubled.quantity(CJ), doubled.quantity(RS)
    assert base_cj and base_rs and long_cj and long_rs
    assert base_cj.value and base_rs.value and long_cj.value and long_rs.value

    # Same total impedance over twice the length: half the capacitance per unit length, twice the
    # resistance per unit length.
    assert long_cj.value < base_cj.value
    assert long_rs.value > base_rs.value


def test_extraction_is_deterministic():
    """Two runs, identical values. `Decimal` at a declared precision, not float arithmetic."""
    first = EXTRACTOR.extract(fx.simulated_input())
    second = EXTRACTOR.extract(fx.simulated_input())
    assert first.quantities == second.quantities


def test_a_payload_whose_source_belongs_to_another_project_is_refused():
    """SEC-002 at the extraction boundary."""
    with refused("SEC-002"):
        ExtractionInput(
            project_id="prj:other",
            trace_id=fx.TRACE,
            source=fx.simulated_source(),
            series=fx.series(),
        )
