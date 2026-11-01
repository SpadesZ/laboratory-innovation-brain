"""The offline Discovery Loop's adversarial and regression properties.

Each test names a way a discovery loop goes wrong and holds the line against it:

    counted twice        a renamed duplicate is merged; an inseparable pair is one class
    resolved by fiat     an inseparable pair is reported as a class with what would split it
    dropped anomaly      every anomaly record survives to the result, in order, with its history
    reframing as support refuted stays refuted unless its sole basis is attributed to noise, and
                         even then it returns to UNDER_TEST, never to SURVIVING
    retrospective support  only observations taken after registration count -- and the naive rule
                         that ignores registration time is shown to count them
    confirmation         no state, outcome or record says CONFIRMED
    budget               never exceeded; refused outright if asked
    stop                 STOPPED_INSUFFICIENT_VALIDATION when nothing affordable discriminates
    determinism          the same seed gives the same digest, a different seed a different run
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.loop import BudgetExceeded, _Action, _Investigation
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    AnomalyKind,
    AnomalyRecord,
    AnomalyState,
    Budget,
    DiscoveryState,
    HypothesisRecord,
    Origin,
    Outcome,
    Purpose,
    ReframingKind,
    ReproductionResult,
    StateEvent,
    TransitionRefused,
    anomaly_transition,
    make_hypothesis,
    reinstatement_reason,
    transition,
)
from lab_brain.discovery.protocol import DISCOVERY, EXISTING_LIB_STYLE
from lab_brain.discovery.worlds import SyntheticWorld
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    ring_scenario,
)
from tests.discovery_fixtures import (
    TOY_A,
    TOY_E,
    run_toy,
    toy_catalog,
    toy_oracle,
    toy_world,
)

# -- counted twice / resolved by fiat --------------------------------------------------------------


def test_a_renamed_duplicate_is_merged_and_never_counted_or_tested_twice():
    renamed = replace(TOY_A, class_id="toy.a_renamed", family="toy.a_renamed")
    result = run_toy(toy_catalog(renamed), toy_world((("toy.a", 1.5),)))
    alias = result.record("hyp:toy.a_renamed")
    assert alias.alias_of == "hyp:toy.a"
    assert alias.state is DiscoveryState.INDISTINGUISHABLE
    assert "identical forward model" in alias.history[0].reason
    assert "hyp:toy.a_renamed" not in {h.hypothesis_id for h in result.examined}
    assert result.claim == ("hyp:toy.a",)


def test_an_inseparable_pair_is_reported_as_one_class_never_resolved_by_fiat():
    result = run_toy(toy_catalog(initial_ef=True, with_cd=False), toy_world((("toy.e", 1.5),)))
    assert result.outcome is Outcome.INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE
    assert result.claim == ("hyp:toy.e", "hyp:toy.f")
    change = [r for r in result.reframings if r.kind is ReframingKind.CHANGE_OBSERVABLE]
    assert change and "e.ideal (not built here)" in change[0].rationale
    assert change[0].subjects == ("hyp:toy.e", "hyp:toy.f")
    assert result.handover is not None
    assert result.handover.would_separate == (("e.ideal", "not built here"),)


def test_widening_finds_a_declared_class_outside_the_prior_and_closure_names_its_twin():
    """Truth outside the initial set: every initial hypothesis fails, the space is widened, and
    the twin no available experiment separates from the survivor joins its class."""
    result = run_toy(toy_catalog(with_cd=False), toy_world((("toy.e", 1.5),)))
    widen = [r for r in result.reframings if r.kind is ReframingKind.WIDEN_MECHANISM_SPACE]
    assert widen and "hyp:toy.e" in widen[0].added_hypotheses
    assert set(widen[0].failed_hypotheses) >= {"hyp:null", "hyp:toy.a", "hyp:toy.b"}
    twin = result.record("hyp:toy.f")
    assert twin.origin is Origin.INDISTINGUISHABILITY_CLOSURE
    assert result.claim == ("hyp:toy.e", "hyp:toy.f")
    # The failure history that motivated the widening is intact.
    for failed in widen[0].failed_hypotheses:
        assert result.record(failed).ever_refuted


# -- stop -----------------------------------------------------------------------------------------


def test_the_loop_stops_insufficient_when_nothing_affordable_discriminates():
    result = run_toy(toy_catalog(), toy_world((("toy.c", 1.5),)), budget=12)
    assert result.outcome is Outcome.STOPPED_INSUFFICIENT_VALIDATION
    assert result.claim == ()
    kinds = [r.kind for r in result.reframings]
    assert ReframingKind.STOP_INSUFFICIENT in kinds
    assert result.record("hyp:toy.c").state is DiscoveryState.STOPPED
    assert result.record("hyp:toy.d").state is DiscoveryState.STOPPED
    assert result.spent <= result.budget


def test_the_existing_lib_style_arm_records_no_reframing_and_reports_no_class():
    result = run_toy(
        toy_catalog(initial_ef=True, with_cd=False),
        toy_world((("toy.e", 1.5),)),
        protocol=EXISTING_LIB_STYLE,
    )
    assert result.reframings == ()
    assert result.anomalies == ()
    assert result.outcome not in CLAIM_OUTCOMES


# -- support, refutation, reframing ----------------------------------------------------------------


def _investigation(budget=12):
    catalog = toy_catalog(with_cd=False)
    run = _Investigation(
        arm="toy",
        catalog=catalog,
        oracle=toy_oracle(catalog),
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=SyntheticWorld(toy_world((("toy.e", 1.5),)), catalog, "e.cheap"),
    )
    run.register(make_hypothesis(TOY_A), Origin.INITIAL_CATALOG, "initial")
    return run


def test_retrospective_observations_never_count_as_support():
    run = _investigation()
    run.run(_Action("e.cheap", Purpose.DISCRIMINATE, 0.0))
    run.run(_Action("e.split", Purpose.DISCRIMINATE, 0.0))
    run.evaluate()
    # Registered AFTER both observations, which it fits by construction.
    run.register(make_hypothesis(TOY_E), Origin.EXTENDED_LIBRARY, "proposed after the data")
    late = run.records["hyp:toy.e"]
    run.evaluate()
    assert run.records["hyp:toy.e"].state is DiscoveryState.UNDER_TEST
    assert run.prospective_support(late) == ()
    # THE DEFECT a naive rule would have: counting every admitted observation it could have
    # failed, whatever its time, it would already call the hypothesis tested on two experiments.
    naive = {o.experiment_id for o in run.admitted() if run.risky(late.hypothesis, o.experiment_id)}
    assert len(naive) >= DISCOVERY.min_prospective_tests
    # Only new observations move it, and only on two distinct experiments.
    run.run(_Action("e.cheap", Purpose.PROSPECTIVE_TEST, 0.0))
    run.evaluate()
    assert run.records["hyp:toy.e"].state is DiscoveryState.UNDER_TEST
    run.run(_Action("e.split", Purpose.PROSPECTIVE_TEST, 0.0))
    run.evaluate()
    assert run.records["hyp:toy.e"].state is DiscoveryState.SURVIVING
    assert all(
        run.observation(o).taken_at > late.registered_at
        for o in run.records["hyp:toy.e"].history[-1].basis
    )


def test_the_motivating_observation_supports_and_refutes_nothing():
    result = run_toy(toy_catalog(with_cd=False), toy_world((("toy.e", 1.5),)))
    motivating = [o for o in result.observations if o.motivating]
    assert [o.observation_id for o in motivating] == ["obs:0"]
    for record in result.hypotheses:
        for event in record.history:
            assert "obs:0" not in event.basis


def test_the_budget_is_never_exceeded_even_when_asked():
    run = _investigation(budget=2)
    run.run(_Action("e.split", Purpose.DISCRIMINATE, 0.0))
    with pytest.raises(BudgetExceeded):
        run.run(_Action("e.cheap", Purpose.DISCRIMINATE, 0.0))
    assert run.spent == 2


def _record(state: DiscoveryState) -> HypothesisRecord:
    return HypothesisRecord(
        hypothesis=make_hypothesis(TOY_A),
        registered_at=0,
        origin=Origin.INITIAL_CATALOG,
        history=(StateEvent(0, state.value, "start"),),
    )


def test_a_refuted_hypothesis_never_becomes_support():
    refuted = _record(DiscoveryState.REFUTED)
    with pytest.raises(TransitionRefused):
        transition(refuted, 1, DiscoveryState.SURVIVING, "reframed", ())
    with pytest.raises(TransitionRefused):
        transition(refuted, 1, DiscoveryState.UNDER_TEST, "reframed", ())
    with pytest.raises(TransitionRefused):
        transition(refuted, 1, DiscoveryState.SURVIVING, reinstatement_reason("obs:1"), ())
    back = transition(refuted, 1, DiscoveryState.UNDER_TEST, reinstatement_reason("obs:1"), ())
    assert [e.state for e in back.history] == ["REFUTED", "UNDER_TEST"]


def test_an_anomaly_attributed_to_noise_stays_attributed():
    anomaly = AnomalyRecord(
        anomaly_id="anm:1",
        kind=AnomalyKind.UNEXPLAINED_OBSERVATION,
        observation_id="obs:1",
        detected_at=1,
        hypotheses_at_detection=(),
        max_abs_z=7.0,
        history=(StateEvent(1, AnomalyState.ATTRIBUTED_TO_NOISE.value, "replication"),),
    )
    for state in (AnomalyState.UNEXPLAINED, AnomalyState.EXPLAINED, AnomalyState.ACCOMMODATED):
        with pytest.raises(TransitionRefused):
            anomaly_transition(anomaly, 2, state, "changed its mind", ())


@pytest.mark.parametrize("seed", range(1, 8))
def test_a_glitch_is_tested_attributed_to_noise_and_its_refutations_withdrawn(seed):
    """Regression: the first replication rule compared only original and replicate, and the
    first reinstatement rule only re-examined refutations resting on the glitch ALONE. Seeds 3
    (a refutation resting jointly on the glitch and a good observation: UNSTABLE, no claim) and 5
    (a 7-sigma glitch offset by -2.4 sigma of noise: "REPRODUCED", every hypothesis refuted)
    ended STOPPED_UNEXPLAINED under those rules."""
    result = run_toy(toy_catalog(), toy_world((("toy.a", 1.5),), seed=seed, glitch_first=True))
    noise_tests = [
        *(t for a in result.anomalies for t in a.tests),
        *result.replications,
    ]
    attributed = [t for t in noise_tests if t.result is ReproductionResult.NOT_REPRODUCED_NOISE]
    assert attributed, "the glitch was never tested"
    glitched = attributed[0].original_observation_id
    assert glitched == "obs:1"
    reinstated = [
        e for r in result.hypotheses for e in r.history if e.reason.startswith("reinstated:")
    ]
    assert all(glitched in e.basis for e in reinstated)
    assert result.claim == ("hyp:toy.a",)


# -- properties over the development worlds -------------------------------------------------------


@pytest.fixture(scope="module")
def dev_runs():
    scenario = ring_scenario(3, base_seed=DEVELOPMENT_BASE_SEED)
    return benchmark.run(scenario, 12, (*benchmark.ARMS, *benchmark.ABLATIONS))


def _results(dev_runs):
    return [(w, r) for w in dev_runs.worlds for r in w.results]


def test_nothing_anywhere_is_ever_confirmed(dev_runs):
    assert "CONFIRMED" not in {o.value for o in Outcome}
    assert "CONFIRMED" not in {s.value for s in DiscoveryState}
    for _, result in _results(dev_runs):
        assert "CONFIRMED" not in result.outcome.value
        for record in result.hypotheses:
            assert all("CONFIRMED" not in e.state for e in record.history)
        if result.handover is not None:
            assert result.handover.status == "PENDING_CAUSAL_WARRANT_GATE"


def test_no_arm_ever_exceeds_its_budget(dev_runs):
    for _, result in _results(dev_runs):
        assert result.spent <= result.budget == 12
        assert sum(s.cost for s in result.steps) == result.spent


def test_survival_rests_only_on_observations_taken_after_registration(dev_runs):
    for _, result in _results(dev_runs):
        taken = {o.observation_id: o for o in result.observations}
        for record in result.hypotheses:
            for event in record.history:
                if event.state != DiscoveryState.SURVIVING:
                    continue
                assert event.basis, record.hypothesis_id
                for observation_id in event.basis:
                    observation = taken[observation_id]
                    assert not observation.motivating
                    assert observation.taken_at > record.registered_at


def test_refutations_are_withdrawn_only_when_their_sole_basis_was_attributed_to_noise(dev_runs):
    for _, result in _results(dev_runs):
        noise = {
            t.original_observation_id
            for t in (*(t for a in result.anomalies for t in a.tests), *result.replications)
            if t.result is ReproductionResult.NOT_REPRODUCED_NOISE
        }
        for record in result.hypotheses:
            states = [e.state for e in record.history]
            for i, state in enumerate(states[:-1]):
                if state == DiscoveryState.REFUTED and states[i + 1] != DiscoveryState.REFUTED:
                    event = record.history[i + 1]
                    assert event.state == DiscoveryState.UNDER_TEST
                    assert event.reason.startswith("reinstated:")
                    assert event.basis[1] in noise


def test_reframing_keeps_the_failure_history_it_cites(dev_runs):
    for _, result in _results(dev_runs):
        for reframing in result.reframings:
            for failed in reframing.failed_hypotheses:
                assert result.record(failed).ever_refuted
            for anomaly_id in reframing.anomalies:
                assert anomaly_id in {a.anomaly_id for a in result.anomalies}


def test_no_anomaly_is_ever_dropped(dev_runs):
    seen_noise_free = 0
    for _, result in _results(dev_runs):
        ids = [a.anomaly_id for a in result.anomalies]
        assert ids == [f"anm:{i}" for i in range(1, len(ids) + 1)]
        for anomaly in result.anomalies:
            assert anomaly.history[0].state == AnomalyState.UNEXPLAINED
        if result.handover is not None:
            open_ = {
                a.anomaly_id
                for a in result.anomalies
                if a.state in (AnomalyState.UNEXPLAINED, AnomalyState.ACCOMMODATED)
            }
            assert set(result.handover.open_anomalies) == open_
        seen_noise_free += not result.anomalies
    assert seen_noise_free  # non-vacuity in the other direction: not every run is anomalous


def test_a_claimed_class_is_one_class_of_distinct_forward_models(dev_runs):
    oracles = benchmark.Oracles(dev_runs.scenario.catalog, DISCOVERY)
    for world, result in _results(dev_runs):
        examined = result.examined
        assert len({h.fingerprint for h in examined}) == len(examined)
        if result.outcome not in CLAIM_OUTCOMES:
            continue
        members = [result.record(i).hypothesis for i in result.claim]
        assert len({h.fingerprint for h in members}) == len(members)
        assert all(result.record(i).state is not DiscoveryState.REFUTED for i in result.claim)
        if len(members) > 1:
            assert len(oracles.for_world(world.world).classes(members)) == 1


def test_the_same_seed_gives_the_same_run_and_another_seed_another(dev_runs):
    scenario = dev_runs.scenario
    world = scenario.worlds[0]
    oracle = benchmark.Oracles(scenario.catalog, DISCOVERY).for_world(world)

    def once(spec):
        from lab_brain.discovery.loop import investigate

        return investigate(
            arm="B2",
            catalog=scenario.catalog,
            oracle=oracle,
            protocol=DISCOVERY,
            budget=Budget(12),
            lab=benchmark.lab_for(scenario, spec),
        ).digest

    assert once(world) == once(world) == dev_runs.worlds[0].results[2].digest
    assert once(replace(world, seed=world.seed + 99)) != once(world)


def test_a_noise_only_world_can_end_with_the_noise_model(dev_runs):
    b2 = [w.results[2] for w in dev_runs.worlds if w.world.kind == "noise_only_null"]
    assert any(r.outcome is Outcome.NO_EFFECT_BEYOND_NOISE for r in b2)
    for result in b2:
        if result.outcome is Outcome.NO_EFFECT_BEYOND_NOISE:
            assert result.claim == ("hyp:null",)
            assert result.handover is None
