"""Held-out mechanism classes: the family is truly absent, and the truth never reaches the engine.

absent          the reduced catalog holds no class of the family, no removed class id and no
                removed forward model (by fingerprint, whatever its name); the hypothesis
                universe built from it names none; its name does not say what was removed
aliasing        classified from the forward models alone, before any run
never reaches   the engine is handed the reduced catalog, an oracle over it and a blind
                laboratory -- and the run refuses (TruthLeak) when the catalog it would hand over
                still names the truth: the check has teeth
scoring         every run is exactly one of: correct (no claim), force-fit, false null, surrogate
deterministic   the same seeds give the same worlds and the same digests
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.loop import hypothesis_universe, investigate
from lab_brain.discovery.model import make_hypothesis, to_jsonable
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import find_truth_leaks
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)

ALIASED_CLASSES = {"cladding.index_drift", "geometry.gap_large", "geometry.width_wide"}


@pytest.fixture(scope="module")
def catalog():
    return ring_catalog()


@pytest.fixture(scope="module")
def worlds(catalog):
    return held_out.held_out_worlds(
        catalog, seeds_per_class=1, base_seed=DEVELOPMENT_BASE_SEED, protocol=DISCOVERY
    )


def _run(catalog, chosen, budget=12, arms=benchmark.ARMS):
    return held_out.run_held_out(
        catalog,
        chosen,
        arms=arms,
        budget=budget,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        protocol=DISCOVERY,
    )


def test_the_held_out_family_is_truly_absent_from_the_engine_catalog(catalog):
    families = sorted({m.family for m in catalog.mechanisms})
    versions = set()
    for family in families:
        removed = [m for m in catalog.mechanisms if m.family == family]
        reduced = held_out.without_family(catalog, family)
        versions.add(reduced.ref)
        assert len(reduced.initial) >= 2
        assert {m.family for m in reduced.mechanisms}.isdisjoint({family})
        assert {m.class_id for m in reduced.mechanisms}.isdisjoint({m.class_id for m in removed})
        assert {m.fingerprint for m in reduced.mechanisms}.isdisjoint(
            {m.fingerprint for m in removed}
        )
        universe = hypothesis_universe(reduced)
        assert all(family not in h.families for h in universe)
        assert {h.fingerprint for h in universe}.isdisjoint(
            {make_hypothesis(m).fingerprint for m in removed}
        )
        held_out.assert_family_absent(reduced, removed)
        with pytest.raises(held_out.TruthLeak):
            held_out.assert_family_absent(catalog, removed)
        # Every tier of the family is gone: initial, variant and extended alike.
        assert len(reduced.mechanisms) == len(catalog.mechanisms) - len(removed)
    # One name for every reduced catalog: the name does not say which family was removed.
    assert len(versions) == 1
    with pytest.raises(ValueError):
        held_out.without_family(catalog, "no.such.family")


def test_a_renamed_copy_of_a_removed_class_is_caught_by_its_forward_model(catalog):
    removed = [m for m in catalog.mechanisms if m.family == "leakage"]
    reduced = held_out.without_family(catalog, "leakage")
    disguised = replace(removed[0], class_id="innocent.name", family="innocent")
    smuggled = replace(reduced, mechanisms=(*reduced.mechanisms, disguised))
    with pytest.raises(held_out.TruthLeak):
        held_out.assert_family_absent(smuggled, removed)


def test_aliasing_is_classified_from_forward_models_before_any_run(worlds):
    table = held_out.aliasing_table(worlds)
    assert {c for c, row in table.items() if row["aliased"]} == ALIASED_CLASSES
    assert len(table) == 16
    for world in worlds:
        assert world.truth_class == world.spec.truth[0][0]
        assert world.spec.kind == held_out.KIND


def test_worlds_are_deterministic_and_amplitudes_stay_inside_the_inner_range(catalog, worlds):
    again = held_out.held_out_worlds(
        catalog, seeds_per_class=1, base_seed=DEVELOPMENT_BASE_SEED, protocol=DISCOVERY
    )
    assert again == worlds
    other = held_out.held_out_worlds(
        catalog, seeds_per_class=1, base_seed=DEVELOPMENT_BASE_SEED + 7, protocol=DISCOVERY
    )
    assert [w.spec.truth for w in other] != [w.spec.truth for w in worlds]
    for world in worlds:
        m = catalog.mechanism(world.truth_class)
        amplitude = world.spec.truth[0][1]
        span = m.upper - m.lower
        assert m.lower + 0.1 * span - 1e-9 <= amplitude <= m.lower + 0.9 * span + 1e-9


def test_the_engine_is_handed_nothing_that_names_the_truth(catalog, worlds, monkeypatch):
    seen: list[dict[str, object]] = []

    def spy(**kwargs):
        seen.append(kwargs)
        return investigate(**kwargs)

    arm = benchmark.Arm("spy", "spy", DISCOVERY, spy)
    chosen = [w for w in worlds if w.truth_class in ("leakage.substrate", "thermo.ambient")]
    rows = _run(catalog, chosen, arms=(arm,))
    assert len(rows) == len(chosen) == len(seen)
    for world, call in zip(chosen, seen, strict=True):
        needles = held_out.truth_needles(catalog, world)
        engine_catalog = call["catalog"]
        assert find_truth_leaks(to_jsonable(engine_catalog), needles) == []
        assert world.family not in {m.family for m in engine_catalog.mechanisms}
        assert call["oracle"].catalog is engine_catalog
        lab = call["lab"]
        assert type(lab).__name__ == "BlindLaboratory" and not hasattr(lab, "__dict__")
        assert {n for n in dir(lab) if not n.startswith("_")} == {"motivating", "measure"}
        # The negative control: the full catalog WOULD name the truth.
        assert find_truth_leaks(to_jsonable(catalog), needles)


def test_the_run_refuses_when_the_catalog_it_would_hand_over_names_the_truth(
    catalog, worlds, monkeypatch
):
    monkeypatch.setattr(held_out, "without_family", lambda c, family: c)
    with pytest.raises(held_out.TruthLeak):
        _run(catalog, worlds[:1])


def test_every_run_is_exactly_one_of_the_scored_outcomes(catalog, worlds):
    chosen = worlds[::3]
    rows = _run(catalog, chosen)
    assert len(rows) == 3 * len(chosen)
    for row in rows:
        assert sum((row.correct, row.force_fit, row.false_null, row.surrogate)) == 1, row
        assert row.spent <= row.budget
        assert "CONFIRMED" not in row.outcome
        if row.surrogate:
            assert row.aliased
        if row.with_record:
            assert row.correct
        if row.arm in ("B0", "B1"):
            assert not row.with_record  # neither records anomalies nor reframes
    assert [r.digest for r in rows] == [r.digest for r in _run(catalog, chosen)]


def test_the_summary_keeps_aliased_worlds_out_of_the_primary_rates(catalog, worlds):
    chosen = [w for w in worlds if w.aliased][:1] + [w for w in worlds if not w.aliased][:2]
    rows = _run(catalog, chosen)
    summary = held_out.summarize_held_out(rows, arms=["B0", "B1", "B2"], seed=1, resamples=100)
    cell = summary["12"]
    assert cell["worlds_primary"] == 2 and cell["worlds_aliased"] == 1
    for arm in ("B0", "B1", "B2"):
        assert cell["arms"][arm]["correct_no_claim"]["n"] == 2
        assert cell["arms"][arm]["aliased"]["n"] == 1
    assert set(cell["paired"]) == {
        "B2_minus_B1_force_fit",
        "B2_minus_B1_correct",
        "B2_minus_B0_force_fit",
        "B2_minus_B0_correct",
    }


def test_the_control_leaves_the_family_in_and_scores_by_the_class_rule(catalog, worlds):
    control = held_out.run_full_catalog_control(
        catalog,
        worlds[:2],
        arms=benchmark.ARMS,
        budget=12,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        protocol=DISCOVERY,
    )
    assert control["worlds"] == 2
    assert set(control["arms"]) == {"B0", "B1", "B2"}
    assert all(cell["correct"]["n"] == 2 for cell in control["arms"].values())


def test_descriptive_mentions_are_reported_not_hidden(catalog):
    # The FCA-dominated nonlinear regime mentions free-carrier dispersion ("FCD") by name: a
    # remaining class legitimately naming the held-out physics. Reported in the evidence.
    assert held_out.descriptive_mentions(held_out.without_family(catalog, "fcd"), "fcd")
    assert (
        held_out.descriptive_mentions(held_out.without_family(catalog, "leakage"), "leakage") == []
    )
