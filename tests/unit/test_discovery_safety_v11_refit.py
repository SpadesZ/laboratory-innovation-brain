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
passing as long as v1.0 is frozen. The v1.1 behaviour (arm B4) is tested in the same file below: it abstains
(ADEQUACY_UNVERIFIED) on the force-fit, and on development worlds no v1.1 endorsement leaves a
signal experiment of ANY fit unrun.
"""

from __future__ import annotations

from dataclasses import replace
from functools import cache

import pytest

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.model import Budget, ExperimentSpec, Observation
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety.gate import safe_investigate, signal_experiments
from lab_brain.discovery_safety.model import (
    SAFETY,
    AbstentionReason,
    ConfidenceLevel,
    ProbePurpose,
    SafeRun,
    SafetyDecision,
)
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v11.model import SAFETY_V11, SafeRunV11, SafetyProtocolV11
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


def admitted(run: SafeRun | SafeRunV11) -> list[Observation]:
    excluded = set(run.assessment.excluded_as_noise)
    return [
        o for o in run.result.observations if not o.motivating and o.observation_id not in excluded
    ]


def final_fit_signals(run: SafeRun | SafeRunV11, oracle: SeparationOracle) -> tuple[str, ...]:
    """The claim's signal experiments at the fit to EVERY admitted observation (after the probes)."""
    members = [run.engine.record(i).hypothesis for i in run.engine.claim]
    return signal_experiments(members, admitted(run), EXPERIMENTS, oracle.available, SAFETY)


def never_run(run: SafeRun | SafeRunV11, experiments: tuple[str, ...]) -> list[str]:
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


# -- verification after the fix: v1.1 (arm B4) ------------------------------------------------


@cache
def v11(
    base_seed: int,
    world_id: str,
    removed: bool,
    budget: int,
    safety: SafetyProtocolV11 = SAFETY_V11,
) -> SafeRunV11:
    catalog, oracle = setting(base_seed, world_id, removed)
    return safe_investigate_v11(
        arm="B4",
        catalog=catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=SyntheticWorld(world(base_seed, world_id).spec, CATALOG, MOTIVATING_EXPERIMENT),
        safety=safety,
    )


def test_v11_does_not_endorse_the_force_fit_the_refit_exposed():
    run = v11(*FORCE_FIT_CASE)
    a, refit = run.assessment, run.refit
    assert not a.endorsed and run.result.claim == ()
    assert a.reason is AbstentionReason.ADEQUACY_UNVERIFIED
    assert a.confidence is ConfidenceLevel.PROVISIONAL
    assert refit is not None and not refit.stable
    assert "cutback" in refit.emerged_after_refit and refit.uncovered == ("cutback",)
    assert "cutback" not in refit.initial_signals and "cutback" in refit.final_signals
    assert "cutback" in a.signal_experiments and "cutback" not in a.signal_covered
    # The abstention asks for exactly the missing experiment.
    assert {r.experiment_id for r in a.requests} == {"cutback"}
    row = held_out.score_held_out(world(*FORCE_FIT_CASE[:2]), run.result, run.result.spent)
    assert row.correct and not row.force_fit
    assert run.result.spent <= FORCE_FIT_CASE[3]


def test_v11_withholds_the_in_catalog_endorsement_until_the_new_signal_is_run():
    short = v11(*IN_CATALOG_CASE)
    assert short.assessment.reason is AbstentionReason.ADEQUACY_UNVERIFIED
    assert short.refit is not None and short.refit.uncovered == ("tec_stabilized",)
    base, world_id, removed, _ = IN_CATALOG_CASE
    longer = v11(base, world_id, removed, 24)
    assert longer.assessment.endorsed and longer.result.claim == ("hyp:leakage.substrate",)
    assert "tec_stabilized" in {o.experiment_id for o in admitted(longer)}


def test_without_the_fixpoint_v11_reopens_the_hole():
    """The ablation: the same v1.1 gate with `refit_fixpoint` off endorses the force-fit again."""
    off = replace(SAFETY_V11, refit_fixpoint=False)
    run = v11(*FORCE_FIT_CASE, safety=off)
    assert run.assessment.endorsed
    assert "cutback" not in run.assessment.signal_experiments  # judged at the pre-probe fit
    assert run.refit is not None and not run.refit.stable and run.refit.uncovered == ("cutback",)


def test_an_emerged_signal_experiment_is_probed_before_any_null_one():
    run = v11(5_000_000, "held_out-leakage.substrate-03", True, 24)
    assert run.refit is not None and "width_array" in run.refit.emerged_after_refit
    probes = [p for p in run.assessment.probes if p.purpose is ProbePurpose.ADEQUACY_PROBE]
    order = [p.experiment_id for p in probes]
    first_null = next(i for i, p in enumerate(probes) if not p.claim_signal)
    assert order.index("width_array") < first_null
    assert next(p for p in probes if p.experiment_id == "width_array").claim_signal


#: Development worlds for the exhaustive invariant: every class, two seeds, both settings.
INVARIANT_BASE = 7_000_000


@cache
def _invariant_worlds() -> tuple[held_out.HeldOutWorld, ...]:
    return held_out.held_out_worlds(
        CATALOG, seeds_per_class=2, base_seed=INVARIANT_BASE, protocol=DISCOVERY
    )


@pytest.mark.parametrize("budget", [8, 12, 24, 48])
def test_no_v11_endorsement_leaves_a_signal_experiment_of_any_fit_unrun(budget):
    """Exhaustive over the applicable cases on development worlds: every claim the engine made,
    family removed and left in. Whatever the refits did, an endorsement covers the union of every
    signal set computed AND the signal set recomputed here from the final admitted data."""
    endorsed = 0
    for w in _invariant_worlds():
        for removed in (True, False):
            run = v11(INVARIANT_BASE, w.spec.world_id, removed, budget)
            if run.refit is None:
                continue
            assert set(run.refit.initial_signals) <= set(run.refit.signal_history)
            assert set(run.refit.final_signals) <= set(run.refit.signal_history)
            if not run.assessment.endorsed:
                continue
            endorsed += 1
            _, oracle = setting(INVARIANT_BASE, w.spec.world_id, removed)
            observed = {o.experiment_id for o in admitted(run)}
            assert run.refit.stable and not run.refit.uncovered
            assert set(run.refit.signal_history) <= observed, w.spec.world_id
            assert set(final_fit_signals(run, oracle)) <= observed, w.spec.world_id
            assert run.assessment.confidence is ConfidenceLevel.ADEQUATE
    assert endorsed >= 10, endorsed
