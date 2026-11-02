"""Realized-cost curves: the statistics are right, and the cap invariants hold by construction.

    statistics      area under the curve, censored budget-to-first-correct, exact McNemar, Holm,
                    the ratio bootstrap -- against hand-computed values
    realized cost   is the laboratory meter's count, never above the cap, equal to what the engine
                    reports; a runner that ignores its budget is stopped by the meter itself
    exposure        the blind laboratory refuses experiments the world cannot run and readings
                    that are not exactly the declared entries as finite numbers
    monotone        where it must be: a run left unconstrained by its cap is the same run at every
                    larger cap; the share of such runs, and the cumulative share solved, never fall
    determinism     the same seeds give the same digests

Development seeds only; the frozen evaluation is checked in
`tests/e2e/test_discovery_independent_eval_frozen.py`.
"""

from __future__ import annotations

import math

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.benchmark import Arm
from lab_brain.discovery.model import Budget, DiscoveryResult, Outcome
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import curves
from lab_brain.discovery_eval.blind import (
    CostMeter,
    ExposureRefused,
    RealizedCostExceeded,
    blind_laboratory,
    find_truth_leaks,
)
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    ring_scenario,
)

CAPS = (4, 8, 16)


@pytest.fixture(scope="module")
def grid():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)
    return scenario, curves.run_grid(scenario, CAPS, benchmark.ARMS)


# -- statistics ----------------------------------------------------------------------------------


def test_normalized_auc_is_the_trapezoid_over_the_cap_range():
    assert curves.normalized_auc([4, 8, 16], [1.0, 1.0, 1.0]) == 1.0
    assert curves.normalized_auc([4, 8, 16], [0.0, 0.0, 0.0]) == 0.0
    # (4 * 0.5 + 8 * 1.0) / 12
    assert math.isclose(curves.normalized_auc([4, 8, 16], [0.0, 1.0, 1.0]), 10 / 12)
    with pytest.raises(ValueError):
        curves.normalized_auc([4], [1.0])
    with pytest.raises(ValueError):
        curves.normalized_auc([4, 8], [1.0])


def test_budget_to_first_correct_is_censored_beyond_the_grid():
    assert curves.first_correct([4, 8, 16], [False, True, True]) == 8
    assert curves.first_correct([4, 8, 16], [False, False, False]) is None
    assert curves.lower_median([4, 8, None]) == 8
    assert curves.lower_median([4, None, None]) is None
    assert curves.lower_median([4, 8, 12, 16]) == 8
    assert curves.lower_median([]) is None
    once = curves.bootstrap_lower_median([4, 8, None, 8], seed=1, resamples=200, label="x")
    assert once == curves.bootstrap_lower_median([4, 8, None, 8], seed=1, resamples=200, label="x")


def test_exact_mcnemar_matches_hand_values():
    assert curves.exact_mcnemar(0, 0) == 1.0
    assert math.isclose(curves.exact_mcnemar(10, 0), 2 / 1024)
    assert curves.exact_mcnemar(5, 5) == 1.0
    assert curves.exact_mcnemar(3, 9) == curves.exact_mcnemar(9, 3)
    # n = 12, k <= 3: (1 + 12 + 66 + 220) / 4096, doubled
    assert math.isclose(curves.exact_mcnemar(3, 9), 2 * 299 / 4096)


def test_holm_is_step_down_and_monotone():
    adjusted = curves.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})
    assert curves.holm({"a": 0.9, "b": 0.8}) == {"b": 1.0, "a": 1.0}


def test_ratio_bootstrap_reports_undefined_resamples():
    out = curves.ratio_bootstrap([4.0, 6.0], [1.0, 0.0], seed=1, resamples=400, label="r")
    assert out["point"] == 10.0
    assert out["undefined_resamples"] > 0
    none = curves.ratio_bootstrap([4.0, 6.0], [0.0, 0.0], seed=1, resamples=50, label="r")
    assert none == {"point": None, "bootstrap95": None, "undefined_resamples": 50}


# -- realized cost and exposure ------------------------------------------------------------------


def test_realized_cost_is_metered_never_above_the_cap_and_equals_the_engine_report(grid):
    _, rows = grid
    assert len(rows) == 8 * len(CAPS) * 3
    assert all(r.spent <= r.cap for r in rows)
    assert all(r.spent == r.reported_spent for r in rows)
    invariants = curves.grid_invariants(rows, CAPS)
    assert invariants["realized_within_cap"] and invariants["meter_equals_engine_report"]


def test_a_runner_that_ignores_its_budget_is_stopped_by_the_laboratory_meter():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)
    world = scenario.worlds[0]
    experiments = curves.all_experiments(scenario)
    meter = CostMeter({k: e.cost for k, e in experiments.items()}, 5)
    lab = blind_laboratory(benchmark.lab_for(scenario, world), experiments=experiments, meter=meter)
    with pytest.raises(RealizedCostExceeded):
        for session in range(1, 100):
            lab.measure("baseline", replicate=session - 1, session=session)
    assert meter.spent == 5
    assert meter.runs == ["baseline"] * 5


def test_the_blind_laboratory_exposes_two_methods_and_refuses_what_it_should():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)
    experiments = curves.all_experiments(scenario)
    lab = blind_laboratory(
        benchmark.lab_for(scenario, scenario.worlds[0]),
        experiments=experiments,
        available=("baseline", "power_sweep"),
    )
    assert not hasattr(lab, "__dict__")
    public = {n for n in dir(lab) if not n.startswith("_")}
    assert public == {"motivating", "measure"}
    assert repr(lab) == "BlindLaboratory()"
    # Nothing about the world is an attribute of the object the engine holds.
    assert not find_truth_leaks([repr(lab), *dir(lab)], [scenario.worlds[0].world_id, "truth"])
    with pytest.raises(ExposureRefused):
        lab.measure("cutback", replicate=0, session=1)
    with pytest.raises(ExposureRefused):
        lab.measure("ellipsometry", replicate=0, session=1)

    class Liar:
        def __init__(self, values):
            self.values = values

        def motivating(self):
            return "baseline", self.values

        def measure(self, experiment_id, *, replicate, session):
            return self.values

    good = (("shift", 1.0), ("loss", 0.1), ("kappa", 0.0), ("il", 0.0))
    for bad in (
        (*good, ("truth", 1.0)),
        good[:3],
        (("shift", float("nan")), *good[1:]),
        (("shift", True), *good[1:]),
        (("shift", "1.0"), *good[1:]),
        "shift=1",
    ):
        liar = blind_laboratory(Liar(bad), experiments=experiments)
        with pytest.raises(ExposureRefused):
            liar.measure("baseline", replicate=0, session=1)
    honest = blind_laboratory(Liar(good), experiments=experiments)
    assert honest.motivating() == ("baseline", good)


def test_the_engine_touches_only_motivating_and_measure():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)

    class Trap:
        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)
            object.__setattr__(self, "touched", [])

        def __getattribute__(self, name):
            if name in ("_inner", "touched", "__class__"):
                return object.__getattribute__(self, name)
            object.__getattribute__(self, "touched").append(name)
            if name in ("motivating", "measure"):
                return getattr(object.__getattribute__(self, "_inner"), name)
            raise AttributeError(name)

    oracles = benchmark.Oracles(scenario.catalog, DISCOVERY)
    for world in scenario.worlds:
        for arm in benchmark.ARMS:
            trap = Trap(benchmark.lab_for(scenario, world))
            arm.runner(
                arm=arm.arm_id,
                catalog=scenario.catalog,
                oracle=oracles.for_world(world),
                protocol=arm.protocol,
                budget=Budget(12),
                lab=trap,
            )
            assert set(object.__getattribute__(trap, "touched")) <= {"motivating", "measure"}


# -- monotone where expected ---------------------------------------------------------------------


def test_an_unconstrained_run_is_the_same_run_at_every_larger_cap(grid):
    _, rows = grid
    invariants = curves.grid_invariants(rows, CAPS)
    checked = invariants["unconstrained_runs_identical_at_larger_caps"]
    assert checked["comparisons"] > 0
    assert checked["violations"] == []
    assert invariants["unconstrained_share_non_decreasing"]


def test_the_invariant_check_has_teeth(grid):
    _, rows = grid
    from dataclasses import replace

    victim = next(r for r in rows if r.unconstrained and r.cap == CAPS[0])
    tampered = [
        replace(r, outcome="TAMPERED", claim=("hyp:tampered",))
        if (r.world_id, r.arm, r.cap) == (victim.world_id, victim.arm, CAPS[-1])
        else r
        for r in rows
    ]
    violations = curves.grid_invariants(tampered, CAPS)[
        "unconstrained_runs_identical_at_larger_caps"
    ]["violations"]
    assert violations == [f"{victim.world_id}:{victim.arm} {CAPS[0]}->{CAPS[-1]}"]
    over = [replace(rows[0], spent=rows[0].cap + 1), *rows[1:]]
    assert curves.grid_invariants(over, CAPS)["realized_within_cap"] is False


def test_early_stopping_arms_are_flat_once_every_run_is_unconstrained(grid):
    _, rows = grid
    for arm in ("B0", "B1"):
        free = [
            c for c in CAPS if all(r.unconstrained for r in rows if r.arm == arm and r.cap == c)
        ]
        assert free, arm
        start = free[0]
        rates = {
            c: sum(r.correct for r in rows if r.arm == arm and r.cap == c)
            for c in CAPS
            if c >= start
        }
        assert len(set(rates.values())) == 1, (arm, rates)


def test_summary_is_consistent_with_its_rows(grid):
    _, rows = grid
    summary = curves.summarize_grid(rows, caps=CAPS, arms=["B0", "B1", "B2"], seed=7, resamples=200)
    for arm in ("B0", "B1", "B2"):
        rates = [summary["per_cap"][str(c)][arm]["correct"]["rate"] for c in CAPS]
        assert summary["auc_correct_vs_cap"][arm]["mean"] == pytest.approx(
            curves.normalized_auc(CAPS, rates), abs=1e-4
        )
        cumulative = [summary["cumulative_solved_by_cap"][arm][str(c)] for c in CAPS]
        assert cumulative == sorted(cumulative)
        for c in CAPS:
            cell = summary["per_cap"][str(c)][arm]
            assert cell["realized_cost_max"] <= c
            assert cell["realized_total"] <= cell["nominal_total"]
    assert set(summary["paired_per_cap"]) == {
        f"B2_minus_{b}@{c}" for b in ("B1", "B0") for c in CAPS
    }
    for cell in summary["paired_per_cap"].values():
        assert cell["holm_p"] >= cell["mcnemar_p"]
        low, high = cell["correct_ci_bonferroni"]
        low95, high95 = cell["correct_ci95"]
        assert low <= low95 and high >= high95


def test_the_grid_is_deterministic_per_seed():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)
    subset = type(scenario)(**{**scenario.__dict__, "worlds": scenario.worlds[:3]})
    first = [r.digest for r in curves.run_grid(subset, (6, 12), benchmark.ARMS)]
    again = [r.digest for r in curves.run_grid(subset, (6, 12), benchmark.ARMS)]
    assert first == again
    other = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED + 1)
    other = type(other)(**{**other.__dict__, "worlds": other.worlds[:3]})
    assert first != [r.digest for r in curves.run_grid(other, (6, 12), benchmark.ARMS)]


def test_caps_must_increase_and_arms_share_one_distinguishability_definition():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)
    with pytest.raises(ValueError):
        curves.run_grid(scenario, (8, 4), benchmark.ARMS)
    from dataclasses import replace

    odd = Arm("odd", "odd", replace(DISCOVERY, distinguish_tau=9.0), benchmark.ARMS[2].runner)
    with pytest.raises(ValueError):
        curves.run_grid(scenario, (4,), (*benchmark.ARMS, odd))


def test_discriminating_experiments_counts_steps_followed_by_a_refutation(grid):
    scenario, _ = grid
    world = scenario.worlds[0]
    oracle = benchmark.Oracles(scenario.catalog, DISCOVERY).for_world(world)
    result: DiscoveryResult = benchmark.ARMS[2].runner(
        arm="B2",
        catalog=scenario.catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(12),
        lab=benchmark.lab_for(scenario, world),
    )
    count = curves.discriminating_experiments(result)
    assert 0 <= count <= len(result.steps)
    refuted_steps = {e.step for h in result.hypotheses for e in h.history if e.state == "REFUTED"}
    assert count == len({s.step for s in result.steps} & refuted_steps)
    assert result.outcome is not None and isinstance(result.outcome, Outcome)
