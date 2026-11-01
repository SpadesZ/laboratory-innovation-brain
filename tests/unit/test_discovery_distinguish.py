"""Distinguishability: separated iff an AVAILABLE experiment separates them; otherwise one class.

The gaming check comes first, against the metric that fails it: counting hypotheses rises with
every renamed copy and every variant no experiment separates, and counting distinguishable classes
does not. That is the defect the diversity metric exists to avoid, shown failing before the metric
that fixes it is shown passing.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.metrics import (
    distinguishable_diversity,
    naive_hypothesis_count,
    resists_variant_gaming,
)
from lab_brain.discovery.model import NULL_HYPOTHESIS, make_hypothesis
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.domains.silicon_photonics.discovery_catalog import ring_catalog
from tests.discovery_fixtures import TOY_A, TOY_B, TOY_C, TOY_E, TOY_F, toy_catalog, toy_oracle


def _variants(base, count, scale=1.0001):
    """Variants that no available experiment separates from `base`: renamed, or a hair rescaled."""
    out = []
    for i in range(count):
        factor = 1.0 if i % 2 == 0 else scale
        out.append(
            make_hypothesis(
                replace(
                    base,
                    class_id=f"{base.class_id}.variant{i:02d}",
                    family=f"{base.family}.variant{i:02d}",
                    sensitivity=tuple((e, n, c * factor) for e, n, c in base.sensitivity),
                )
            )
        )
    return out


def test_the_naive_hypothesis_count_is_gamed_by_fifty_indistinguishable_variants():
    """THE DEFECT, demonstrated: a metric that counts hypotheses rewards padding."""
    oracle = toy_oracle(toy_catalog())
    examined = [make_hypothesis(TOY_A), make_hypothesis(TOY_B), make_hypothesis(TOY_C)]
    padding = _variants(TOY_A, 50)
    assert naive_hypothesis_count([*examined, *padding], oracle) == 53
    assert not resists_variant_gaming(naive_hypothesis_count, examined, padding, oracle)


def test_distinguishable_diversity_is_not_raised_by_fifty_indistinguishable_variants():
    oracle = toy_oracle(toy_catalog())
    examined = [make_hypothesis(TOY_A), make_hypothesis(TOY_B), make_hypothesis(TOY_C)]
    padding = _variants(TOY_A, 50)
    assert distinguishable_diversity(examined, oracle) == 3
    assert distinguishable_diversity([*examined, *padding], oracle) == 3
    assert resists_variant_gaming(distinguishable_diversity, examined, padding, oracle)


def test_the_gaming_check_refuses_padding_that_is_not_a_variant():
    oracle = toy_oracle(toy_catalog())
    with pytest.raises(ValueError):
        resists_variant_gaming(
            distinguishable_diversity, [make_hypothesis(TOY_A)], [make_hypothesis(TOY_C)], oracle
        )


def test_a_renamed_duplicate_has_zero_separation_and_shares_a_class():
    oracle = toy_oracle(toy_catalog())
    a = make_hypothesis(TOY_A)
    renamed = make_hypothesis(replace(TOY_A, class_id="toy.renamed", family="toy.renamed"))
    assert a.fingerprint == renamed.fingerprint
    assert oracle.joint_separation(a, renamed) == 0.0
    assert not oracle.distinguishable(a, renamed)
    assert oracle.classes([a, renamed, make_hypothesis(TOY_B)]) == (
        ("hyp:toy.a", "hyp:toy.renamed"),
        ("hyp:toy.b",),
    )


def test_hypotheses_identical_on_every_available_experiment_are_one_class_with_the_reason():
    oracle = toy_oracle(toy_catalog())
    e, f = make_hypothesis(TOY_E), make_hypothesis(TOY_F)
    assert e.fingerprint != f.fingerprint
    assert not oracle.distinguishable(e, f)
    assert oracle.classes([e, f]) == (("hyp:toy.e", "hyp:toy.f"),)
    # Never resolved by fiat: the only experiment that would split them is named, and it is
    # declared unavailable.
    assert oracle.would_separate(e, f) == (("e.ideal", "not built here"),)


def test_classes_do_not_depend_on_order_or_names():
    oracle = toy_oracle(toy_catalog())
    hs = [make_hypothesis(m) for m in (TOY_A, TOY_B, TOY_C, TOY_E, TOY_F)]
    assert oracle.classes(hs) == oracle.classes(list(reversed(hs)))


def test_the_noise_model_is_distinguishable_from_every_declared_class():
    """A regime that could vanish would be indistinguishable from noise by construction."""
    catalog = ring_catalog()
    oracle = SeparationOracle(catalog, [e.experiment_id for e in catalog.experiments], DISCOVERY)
    for mechanism in catalog.mechanisms:
        assert oracle.distinguishable(make_hypothesis(mechanism), NULL_HYPOTHESIS), mechanism


def test_ring_width_and_thickness_separate_only_where_widths_differ():
    catalog = ring_catalog()
    width = make_hypothesis(catalog.mechanism("geometry.width_wide"))
    thickness = make_hypothesis(catalog.mechanism("geometry.thickness"))
    everything = [e.experiment_id for e in catalog.experiments]
    full = SeparationOracle(catalog, everything, DISCOVERY)
    single_width = SeparationOracle(
        catalog,
        [e for e in everything if e != "width_array"],
        DISCOVERY,
        {"width_array": "this die carries a single ring width"},
    )
    assert full.distinguishable(width, thickness)
    assert not single_width.distinguishable(width, thickness)
    assert dict(single_width.would_separate(width, thickness)) == {
        "ellipsometry": "no ellipsometer in this lab",
        "width_array": "this die carries a single ring width",
    }


def test_the_ring_measurement_chain_artefact_mimics_thermal_drift_except_where_referenced():
    """The confound world (d): equal on the cheap re-measurement, split by the gas cell / TEC."""
    catalog = ring_catalog()
    oracle = SeparationOracle(catalog, [e.experiment_id for e in catalog.experiments], DISCOVERY)
    thermo = make_hypothesis(catalog.mechanism("thermo.ambient"))
    laser = make_hypothesis(catalog.mechanism("chain.laser_drift"))
    assert oracle.experiment_separation(thermo, laser, "baseline") == pytest.approx(0.0, abs=1e-9)
    assert oracle.experiment_separation(thermo, laser, "gas_cell_reference") > 10
    assert oracle.experiment_separation(thermo, laser, "tec_stabilized") > 5
