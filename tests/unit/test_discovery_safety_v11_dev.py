"""v1.1 on development worlds: the three design decisions, each with the case that motivated it.

Development seeds only (bases 1, 5_000_000 and 7_000_000, declared in `PLAN.development`). No
evaluation seed is run here; the v1.1 held-out evaluation is in the frozen evidence and its test.

localized check     v1.0 endorses leakage.substrate claimed as scatter.sidewall: the deviation sits in
                    one experiment and passes the global test. v1.1's per-experiment check rejects it
deferral            replicating a localized false alarm FIRST spent the unit a decisive probe needed
                    (a force-fit). Deferring the replicate until nothing is left to probe keeps it
exclusion ratchet   v1.0 can exclude a systematic deviation one observation at a time. v1.1 allows
                    one exclusion per experiment
aggregate           on the development held-out worlds v1.1 force-fits no more than v1.0, and with the
                    truth in the catalog it stays correct at budget 24

Every world here is synthetic and written by the engine's author lineage. ENGINEERING EVIDENCE ONLY.
"""

from __future__ import annotations

from dataclasses import replace
from functools import cache

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.metrics import Scorer
from lab_brain.discovery.model import CLAIM_OUTCOMES, Budget
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety import evaluation as ev
from lab_brain.discovery_safety.gate import safe_investigate
from lab_brain.discovery_safety.model import AbstentionReason, SafeRun
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11, safe_runner_v11
from lab_brain.discovery_safety.v11.model import (
    DEVELOPMENT,
    PLAN,
    SAFETY_V11,
    SafeRunV11,
    SafetyProtocolV11,
)
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)

CATALOG = ring_catalog()
INCOMPLETE = {AbstentionReason.CATALOG_INCOMPLETE, AbstentionReason.CATALOG_INCOMPLETE_UNREPLICATED}


def _oracle(catalog: DiscoveryCatalog) -> SeparationOracle:
    return SeparationOracle(catalog, tuple(e.experiment_id for e in catalog.experiments), DISCOVERY)


@cache
def _world(base: int, world_id: str) -> held_out.HeldOutWorld:
    worlds = held_out.held_out_worlds(
        CATALOG, seeds_per_class=16, base_seed=base, protocol=DISCOVERY
    )
    return next(w for w in worlds if w.spec.world_id == world_id)


@cache
def _reduced(family: str) -> tuple[DiscoveryCatalog, SeparationOracle]:
    catalog = held_out.without_family(CATALOG, family)
    return catalog, _oracle(catalog)


def _held(
    base: int, world_id: str, budget: int
) -> tuple[DiscoveryCatalog, SeparationOracle, SyntheticWorld]:
    w = _world(base, world_id)
    catalog, oracle = _reduced(w.family)
    return catalog, oracle, SyntheticWorld(w.spec, CATALOG, MOTIVATING_EXPERIMENT)


@cache
def b3(base: int, world_id: str, budget: int) -> SafeRun:
    catalog, oracle, lab = _held(base, world_id, budget)
    return safe_investigate(
        arm="B3", catalog=catalog, oracle=oracle, protocol=DISCOVERY, budget=Budget(budget), lab=lab
    )


@cache
def b4(base: int, world_id: str, budget: int, safety: SafetyProtocolV11 = SAFETY_V11) -> SafeRunV11:
    catalog, oracle, lab = _held(base, world_id, budget)
    return safe_investigate_v11(
        arm="B4",
        catalog=catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=lab,
        safety=safety,
    )


def _force_fit(base: int, world_id: str, result_run: SafeRun | SafeRunV11) -> bool:
    r = result_run.result
    return held_out.score_held_out(_world(base, world_id), r, r.spent).force_fit


def test_the_development_seeds_are_the_declared_ones():
    declared = {r.base_seed for r in PLAN.development if r.role == DEVELOPMENT}
    assert {1, 5_000_000, 7_000_000} == declared
    assert DEVELOPMENT_BASE_SEED in declared
    for fresh in (*PLAN.held_out, PLAN.benchmark_worlds):
        assert fresh.base_seed >= 3_000_000_000


# -- localized check -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("world_id", "experiment"),
    [
        ("held_out-leakage.substrate-09", "radius_array"),
        ("held_out-leakage.substrate-14", "cutback"),
    ],
)
def test_a_deviation_confined_to_one_experiment_is_no_longer_endorsed(world_id, experiment):
    v10 = b3(7_000_000, world_id, 24)
    assert v10.assessment.endorsed and _force_fit(7_000_000, world_id, v10)
    run = b4(7_000_000, world_id, 24)
    assert not run.assessment.endorsed and run.result.claim == ()
    assert run.assessment.reason in INCOMPLETE
    (test,) = run.member_tests
    assert test.global_adequate and not test.adequate
    assert test.localized_failed == (experiment,)
    assert any("fails the localized check" in n for n in run.assessment.notes)
    # Without the check, v1.1 endorses the same surrogate.
    off = b4(7_000_000, world_id, 24, replace(SAFETY_V11, localized_check=False))
    assert off.assessment.endorsed


# -- deferral of a localized-only replicate --------------------------------------------------


def test_a_localized_false_alarm_does_not_spend_the_decisive_probe():
    world_id = "held_out-nonlinear.tpa_fca-04"
    eager = b4(7_000_000, world_id, 12, replace(SAFETY_V11, defer_localized_replication=False))
    assert eager.assessment.endorsed and _force_fit(7_000_000, world_id, eager)
    assert [p.purpose.value for p in eager.assessment.probes] == ["PROBE_REPLICATION"]
    run = b4(7_000_000, world_id, 12)
    assert not run.assessment.endorsed and run.result.claim == ()
    assert [p.experiment_id for p in run.assessment.probes] == ["power_sweep"]


# -- the exclusion ratchet -------------------------------------------------------------------


def test_one_experiment_cannot_be_excluded_as_noise_twice():
    world_id = "held_out-leakage.substrate-03"
    ratchet = b4(
        5_000_000, world_id, 24, replace(SAFETY_V11, max_noise_exclusions_per_experiment=99)
    )
    assert ratchet.assessment.endorsed and _force_fit(5_000_000, world_id, ratchet)
    excluded = set(ratchet.assessment.excluded_as_noise)
    cutback = [
        o.observation_id
        for o in ratchet.result.observations
        if o.experiment_id == "cutback" and o.observation_id in excluded
    ]
    assert len(cutback) == 2
    run = b4(5_000_000, world_id, 24)
    assert not run.assessment.endorsed and run.result.claim == ()
    assert run.assessment.reason in INCOMPLETE and run.assessment.inadequacy_reproduced
    assert any("already had" in n for n in run.assessment.notes)


# -- aggregate and positive control ----------------------------------------------------------


@cache
def _dev_worlds() -> tuple[held_out.HeldOutWorld, ...]:
    return held_out.held_out_worlds(
        CATALOG, seeds_per_class=2, base_seed=DEVELOPMENT_BASE_SEED, protocol=DISCOVERY
    )


@pytest.mark.parametrize("budget", [12, 24, 48])
def test_over_development_held_out_worlds_v11_force_fits_no_more_than_v10(budget):
    worlds = [w for w in _dev_worlds() if not w.aliased]
    arms = (
        ev.B2,
        benchmark.Arm("B3", "v1.0", DISCOVERY, ev.SafeArmRecorder()),
        benchmark.Arm("B4", "v1.1", DISCOVERY, safe_runner_v11()),
    )
    rows = held_out.run_held_out(
        CATALOG,
        worlds,
        arms=arms,
        budget=budget,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        protocol=DISCOVERY,
    )
    count = {a.arm_id: sum(r.force_fit for r in rows if r.arm == a.arm_id) for a in arms}
    assert count["B4"] <= count["B3"] < count["B2"], count
    assert count["B4"] == 0, count
    assert all(r.spent <= budget for r in rows)
    assert all(
        r.claim == ()
        for r in rows
        if r.arm == "B4" and r.outcome not in {o.value for o in CLAIM_OUTCOMES}
    )


def test_with_the_truth_in_the_catalog_v11_stays_correct_at_budget_24():
    oracle = _oracle(CATALOG)
    scorer = Scorer(CATALOG)
    worlds = [w for w in _dev_worlds() if not w.aliased]
    correct = false = 0
    for w in worlds:
        run = safe_investigate_v11(
            arm="B4",
            catalog=CATALOG,
            oracle=oracle,
            protocol=DISCOVERY,
            budget=Budget(24),
            lab=SyntheticWorld(w.spec, CATALOG, MOTIVATING_EXPERIMENT),
        )
        s = scorer.score(w.spec, run.result, oracle)
        correct += s.correct
        false += s.false_discovery
    assert correct >= len(worlds) - 2, (correct, len(worlds))
    assert false == 0


def test_the_v11_run_is_deterministic_and_never_overspends():
    a = b4(7_000_000, "held_out-leakage.substrate-09", 24)
    catalog, oracle, lab = _held(7_000_000, "held_out-leakage.substrate-09", 24)
    again = safe_investigate_v11(
        arm="B4", catalog=catalog, oracle=oracle, protocol=DISCOVERY, budget=Budget(24), lab=lab
    )
    assert a.result.digest == again.result.digest
    assert a.result.spent <= 24
    assert a.assessment.protocol_digest == SAFETY_V11.digest
