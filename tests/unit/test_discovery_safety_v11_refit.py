"""Signal coverage after refitting: can a prediction that appears only after a refit bypass it?

THE QUESTION (Independent Chief Auditor, v1.1). v1.0 endorses a claim only when every experiment it
"predicts a signal in" (>= z_signal sigma at its FITTED amplitudes) was run. The fitted amplitudes
move as observations arrive: the probes themselves, and the exclusion of an observation attributed
to noise. An experiment that was "no signal" at the fit made before the probes can become "signal"
at the fit made after them. If coverage is judged against the earlier fit only, such an experiment
can stay unrun and the claim still be endorsed.

REPRODUCTION BEFORE THE FIX (v1.0, `lab_brain.discovery_safety.gate`, unchanged). Development seeds
only: base 7_000_000 is a development range declared for v1.1 (never an evaluation seed), base
5_000_000 is v1.0's development range. On both, v1.0 endorses a claim while the claim's FINAL fit
predicts a signal in an experiment that was never run:

    7_000_000  held-out world, truth geometry.width_narrow, its family REMOVED from the catalog,
               budget 12: v1.0 endorses fcd.static + geometry.gap_large -- a FORCE-FIT. The fcd
               amplitude rises from 0.570 to 0.625 over the probes, which puts `cutback` above
               3 sigma; `cutback` (cost 3) was never run
    5_000_000  the same kind of world with the family LEFT IN, budget 12: v1.0 endorses
               leakage.substrate (the truth) while its final fit predicts a signal in the never-run
               `tec_stabilized`. A correct answer, reached through the same hole

These tests pin the v1.0 behaviour (arm B3) so the vulnerability stays documented: they must keep
passing as long as v1.0 is frozen. The v1.1 behaviour (arm B4) is tested in the same file below.
"""

from __future__ import annotations

from functools import cache

import pytest

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.model import Budget, ExperimentSpec, Observation
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety.gate import safe_investigate, signal_experiments
from lab_brain.discovery_safety.model import SAFETY, SafeRun, SafetyDecision
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)

CATALOG = ring_catalog()
EXPERIMENTS: dict[str, ExperimentSpec] = {
    e.experiment_id: e for e in (*CATALOG.experiments, *(u.experiment for u in CATALOG.unavailable))
}
#: (development base seed, world id, family removed?, budget) -- the two v1.0 reproductions.
FORCE_FIT_CASE = (7_000_000, "held_out-geometry.width_narrow-00", True, 12)
IN_CATALOG_CASE = (5_000_000, "held_out-leakage.substrate-04", False, 12)


def _oracle(catalog: DiscoveryCatalog) -> SeparationOracle:
    return SeparationOracle(catalog, tuple(e.experiment_id for e in catalog.experiments), DISCOVERY)


@cache
def world(base_seed: int, world_id: str) -> held_out.HeldOutWorld:
    worlds = held_out.held_out_worlds(
        CATALOG, seeds_per_class=8, base_seed=base_seed, protocol=DISCOVERY
    )
    return next(w for w in worlds if w.spec.world_id == world_id)


@cache
def setting(
    base_seed: int, world_id: str, removed: bool
) -> tuple[DiscoveryCatalog, SeparationOracle]:
    catalog = (
        held_out.without_family(CATALOG, world(base_seed, world_id).family) if removed else CATALOG
    )
    return catalog, _oracle(catalog)


@cache
def v10(base_seed: int, world_id: str, removed: bool, budget: int) -> SafeRun:
    catalog, oracle = setting(base_seed, world_id, removed)
    return safe_investigate(
        arm="B3",
        catalog=catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=SyntheticWorld(world(base_seed, world_id).spec, CATALOG, MOTIVATING_EXPERIMENT),
    )


def admitted(run: SafeRun) -> list[Observation]:
    excluded = set(run.assessment.excluded_as_noise)
    return [
        o for o in run.result.observations if not o.motivating and o.observation_id not in excluded
    ]


def final_fit_signals(run: SafeRun, oracle: SeparationOracle) -> tuple[str, ...]:
    """The claim's signal experiments at the fit to EVERY admitted observation (after the probes)."""
    members = [run.engine.record(i).hypothesis for i in run.engine.claim]
    return signal_experiments(members, admitted(run), EXPERIMENTS, oracle.available, SAFETY)


def never_run(run: SafeRun, experiments: tuple[str, ...]) -> list[str]:
    observed = {o.experiment_id for o in admitted(run)}
    return [e for e in experiments if e not in observed]


# -- reproduction before the fix: v1.0 is vulnerable ------------------------------------------


def test_v10_endorses_a_force_fit_whose_refitted_signal_was_never_run():
    base, world_id, removed, budget = FORCE_FIT_CASE
    run = v10(base, world_id, removed, budget)
    _, oracle = setting(base, world_id, removed)
    a = run.assessment
    assert a.decision is SafetyDecision.ENDORSE_PENDING_WARRANT_GATE
    assert run.result.claim == ("hyp:fcd.static+geometry.gap_large",)
    row = held_out.score_held_out(world(base, world_id), run.result, run.result.spent)
    assert row.force_fit and not world(base, world_id).aliased
    # Coverage as v1.0 judges it (the fit made BEFORE the probes): complete.
    assert set(a.signal_experiments) == set(a.signal_covered)
    assert "cutback" not in a.signal_experiments
    # Coverage under the claim's FINAL fit: `cutback` is a signal experiment and was never run.
    final = final_fit_signals(run, oracle)
    assert "cutback" in final
    assert never_run(run, final) == ["cutback"]
    assert run.result.spent == budget


def test_v10_endorses_an_in_catalog_claim_through_the_same_hole():
    base, world_id, removed, budget = IN_CATALOG_CASE
    run = v10(base, world_id, removed, budget)
    _, oracle = setting(base, world_id, removed)
    assert run.assessment.endorsed and run.result.claim == ("hyp:leakage.substrate",)
    assert run.assessment.signal_experiments == ("radius_array",)
    assert never_run(run, final_fit_signals(run, oracle)) == ["tec_stabilized"]


@pytest.mark.parametrize(("base", "world_id", "removed", "budget"), [FORCE_FIT_CASE])
def test_the_bypass_needs_the_refit_the_pre_probe_fit_predicts_nothing_there(
    base, world_id, removed, budget
):
    run = v10(base, world_id, removed, budget)
    _, oracle = setting(base, world_id, removed)
    members = [run.engine.record(i).hypothesis for i in run.engine.claim]
    engine_only = [o for o in run.engine.observations if not o.motivating]
    before = signal_experiments(members, engine_only, EXPERIMENTS, oracle.available, SAFETY)
    assert "cutback" not in before and "cutback" in final_fit_signals(run, oracle)
