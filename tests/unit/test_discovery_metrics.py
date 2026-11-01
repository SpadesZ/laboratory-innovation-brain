"""Scoring: the truth's class, not a lucky pick; diversity by classes; honest intervals.

The inseparable-pair cases are the point. Reporting width when the truth is thickness, and no
available experiment separates them, is not a discovery -- it is an overclaim. Reporting width when
the truth IS width is not correct either: the equally simple alternative was resolved by fiat.
"""

from __future__ import annotations

import pytest

from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.metrics import Scorer, bootstrap_mean, paired_difference, rate
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    DiscoveryResult,
    Hypothesis,
    HypothesisRecord,
    Origin,
    Outcome,
    StateEvent,
    make_hypothesis,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import WorldSpec
from lab_brain.domains.silicon_photonics.discovery_catalog import ring_catalog

CATALOG = ring_catalog()
SINGLE_WIDTH = (("width_array", "this die carries a single ring width"),)


def _h(*class_ids: str) -> Hypothesis:
    if not class_ids:
        return NULL_HYPOTHESIS
    return make_hypothesis(*(CATALOG.mechanism(c) for c in class_ids))


def _result(claim: tuple[Hypothesis, ...], outcome: Outcome) -> DiscoveryResult:
    records = tuple(
        HypothesisRecord(h, 0, Origin.INITIAL_CATALOG, (StateEvent(0, "SURVIVING", "test"),))
        for h in claim
    )
    return DiscoveryResult(
        arm="test",
        protocol_digest="-",
        catalog_ref=CATALOG.ref,
        budget=12,
        spent=4,
        outcome=outcome,
        claim=tuple(h.hypothesis_id for h in claim),
        hypotheses=records,
        observations=(),
        anomalies=(),
        reframings=(),
        steps=(),
        handover=None,
    )


def _score(world: WorldSpec, claim: tuple[Hypothesis, ...], outcome: Outcome):
    oracle = SeparationOracle(CATALOG, world.available(CATALOG), DISCOVERY, dict(world.removed))
    return Scorer(CATALOG).score(world, _result(claim, outcome), oracle)


SURVIVING = Outcome.SURVIVING_PENDING_WARRANT_GATE
CLASS = Outcome.INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE


def test_picking_one_member_of_an_inseparable_pair_is_an_overclaim_whichever_it_is():
    for truth in ("geometry.thickness", "geometry.width_wide"):
        world = WorldSpec("w", "inseparable_pair", 1, ((truth, 5.0),), removed=SINGLE_WIDTH)
        score = _score(world, (_h("geometry.width_wide"),), SURVIVING)
        assert not score.correct
        assert score.overclaim
        assert not score.false_discovery


def test_reporting_the_inseparable_class_is_correct():
    world = WorldSpec(
        "w", "inseparable_pair", 1, (("geometry.thickness", 5.0),), removed=SINGLE_WIDTH
    )
    score = _score(world, (_h("geometry.thickness"), _h("geometry.width_wide")), CLASS)
    assert score.correct and not score.overclaim and not score.false_discovery


def test_the_same_pick_is_correct_when_an_available_experiment_separates_the_pair():
    world = WorldSpec("w", "in_catalog_single", 1, (("geometry.width_wide", 5.0),))
    assert _score(world, (_h("geometry.width_wide"),), SURVIVING).correct


def test_claiming_an_unrelated_mechanism_is_a_false_discovery():
    world = WorldSpec("w", "confounded", 1, (("chain.laser_drift", 60.0),))
    score = _score(world, (_h("thermo.ambient"),), SURVIVING)
    assert score.false_discovery and not score.correct and not score.partial


def test_claiming_one_half_of_a_composition_is_a_partial_false_discovery():
    world = WorldSpec("w", "composition", 1, (("scatter.sidewall", 1.0), ("thermo.ambient", 1.0)))
    score = _score(world, (_h("thermo.ambient"),), SURVIVING)
    assert score.false_discovery and score.partial
    assert _score(world, (_h("scatter.sidewall", "thermo.ambient"),), SURVIVING).correct


def test_an_imprecise_class_contains_the_truth_and_something_separable():
    world = WorldSpec("w", "in_catalog_single", 1, (("geometry.width_wide", 5.0),))
    score = _score(world, (_h("geometry.width_wide"), _h("thermo.ambient")), CLASS)
    assert score.imprecise and not score.correct


def test_for_an_undeclared_truth_only_silence_is_correct():
    world = WorldSpec("w", "outside_all_declared", 1, (), undeclared="x")
    assert _score(world, (), Outcome.STOPPED_UNEXPLAINED).correct
    claimed = _score(world, (_h("thermo.ambient"),), SURVIVING)
    assert claimed.false_discovery and not claimed.correct


def test_a_noise_only_world_is_correct_only_for_the_noise_model():
    world = WorldSpec("w", "noise_only_null", 1, ())
    assert _score(world, (NULL_HYPOTHESIS,), Outcome.NO_EFFECT_BEYOND_NOISE).correct
    noise_discovery = _score(world, (_h("scatter.sidewall"),), SURVIVING)
    assert noise_discovery.false_discovery
    assert not _score(world, (), Outcome.STOPPED_INSUFFICIENT_VALIDATION).correct


def test_stopping_without_a_claim_is_never_a_false_discovery():
    world = WorldSpec("w", "in_catalog_single", 1, (("geometry.width_wide", 5.0),))
    score = _score(world, (), Outcome.STOPPED_INSUFFICIENT_VALIDATION)
    assert not score.claim_made and not score.false_discovery and not score.correct


def test_intervals_are_reproducible_and_honest_about_no_data():
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    first = bootstrap_mean(values, seed=3, resamples=500, label="m")
    assert first == bootstrap_mean(values, seed=3, resamples=500, label="m")
    assert first is not None and first[0] <= 4.0 <= first[1]
    assert bootstrap_mean([], seed=3, resamples=10, label="m") is None
    with pytest.raises(ValueError):
        bootstrap_mean(values, seed=3, resamples=0, label="m")
    assert rate([True, False, True, True]) == {
        "k": 3,
        "n": 4,
        "rate": 0.75,
        "wilson95": (0.3006, 0.9544),
    }


def test_a_paired_difference_needs_the_same_worlds():
    diff = paired_difference(
        [True, True, False, True], [False, True, False, False], seed=1, resamples=200, label="p"
    )
    assert diff["mean"] == 0.5 and diff["a_only"] == 2 and diff["b_only"] == 0
    with pytest.raises(ValueError):
        paired_difference([True], [True, False], seed=1, resamples=10, label="p")
