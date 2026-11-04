"""The out-of-catalog safety gate: abstain, record, propose, request -- never force-fit.

Development seeds only (`DEVELOPMENT_BASE_SEED`); the evaluation seeds are exercised by the
frozen-evidence test. Every world here is synthetic and written by the engine's author lineage.

hidden family     the true family removed from the catalog: where the frozen engine claims a
                  surrogate, the safe arm abstains with an open anomaly and a reason; across the
                  development worlds it force-fits far less than the frozen engine at every budget
confounder        a measurement-chain truth with its family removed, mimicked by a physical class
                  the engine claims: not endorsed
aliases           a renamed duplicate class changes no decision, no confidence and no count
budgets           12, 24 and 48: force-fits do not rise with budget, and stay below the engine's
confidence        rises only on discriminating evidence: replicates and renamed rivals add nothing;
                  a held-out run never reaches ADEQUATE with more budget
abstention        well formed: no claim, no handover, open anomaly, reframing, request, within budget,
                  scored as no claim by the frozen scorers
proposal          stage-1 only, its signature is the residual means, it fits the data it was read
                  from, it is far from every declared forward model, and it never enters a claim
recovery          the catalog extended with the true family, or more budget for the requested
                  probes: the correct mechanism is endorsed
positive control  the truth in the catalog: correct at budget 24 and never a new false discovery
"""

from __future__ import annotations

import math
from dataclasses import replace
from functools import cache

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.metrics import Scorer
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    AnomalyState,
    Budget,
    Observation,
    make_hypothesis,
    to_jsonable,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety import evaluation as ev
from lab_brain.discovery_safety.gate import (
    discriminating_tests_passed,
    safe_investigate,
    safe_runner,
)
from lab_brain.discovery_safety.model import (
    PROPOSAL_STAGE,
    PROPOSAL_STATUS,
    SAFETY,
    AbstentionReason,
    ConfidenceLevel,
    ProbePurpose,
    RequestPurpose,
    SafeRun,
    SafetyDecision,
)
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    MOTIVATING_EXPERIMENT,
    ring_catalog,
    ring_scenario,
)

CATALOG = ring_catalog()
INCOMPLETE = {AbstentionReason.CATALOG_INCOMPLETE, AbstentionReason.CATALOG_INCOMPLETE_UNREPLICATED}


@cache
def _worlds() -> dict[str, held_out.HeldOutWorld]:
    worlds = held_out.held_out_worlds(
        CATALOG, seeds_per_class=2, base_seed=DEVELOPMENT_BASE_SEED, protocol=DISCOVERY
    )
    return {w.spec.world_id: w for w in worlds}


def _oracle(catalog: DiscoveryCatalog) -> SeparationOracle:
    return SeparationOracle(catalog, tuple(e.experiment_id for e in catalog.experiments), DISCOVERY)


@cache
def _reduced(family: str) -> tuple[DiscoveryCatalog, SeparationOracle]:
    catalog = held_out.without_family(CATALOG, family)
    return catalog, _oracle(catalog)


@cache
def held(world_id: str, budget: int) -> SafeRun:
    """The world with its family REMOVED from the engine's catalog."""
    world = _worlds()[world_id]
    catalog, oracle = _reduced(world.family)
    return safe_investigate(
        arm="B3",
        catalog=catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=SyntheticWorld(world.spec, CATALOG, MOTIVATING_EXPERIMENT),
    )


@cache
def full(world_id: str, budget: int) -> SafeRun:
    """The same world with the family LEFT IN the catalog (truth expressible)."""
    world = _worlds()[world_id]
    return safe_investigate(
        arm="B3",
        catalog=CATALOG,
        oracle=_full_oracle(),
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=SyntheticWorld(world.spec, CATALOG, MOTIVATING_EXPERIMENT),
    )


@cache
def _full_oracle() -> SeparationOracle:
    return _oracle(CATALOG)


def _correct_in_catalog(world_id: str, run: SafeRun) -> bool:
    return Scorer(CATALOG).score(_worlds()[world_id].spec, run.result, _full_oracle()).correct


#: Development worlds where the frozen engine claims a surrogate (the force-fit P3 measured).
FORCE_FIT_CASES = (
    ("held_out-geometry.thickness-00", 12),
    ("held_out-geometry.thickness-01", 24),
    ("held_out-chain.polarization_drift-00", 12),
    ("held_out-fcd.static-00", 24),
    ("held_out-scatter.sidewall-00", 24),
    ("held_out-leakage.substrate-00", 24),
)


# -- hidden mechanism families ---------------------------------------------------------------


@pytest.mark.parametrize(("world_id", "budget"), FORCE_FIT_CASES)
def test_a_hidden_family_is_not_force_fitted_where_the_engine_claims_a_surrogate(world_id, budget):
    run = held(world_id, budget)
    assert run.engine.outcome in CLAIM_OUTCOMES and run.engine.claim, "the engine force-fits here"
    row = held_out.score_held_out(_worlds()[world_id], run.engine, run.engine.spent)
    assert row.force_fit
    a = run.assessment
    assert a.decision is SafetyDecision.ABSTAIN
    assert a.confidence is ConfidenceLevel.NONE
    assert a.reason in {*INCOMPLETE, AbstentionReason.CLAIM_INADEQUATE}
    assert run.result.outcome not in CLAIM_OUTCOMES and run.result.claim == ()
    safe_row = held_out.score_held_out(_worlds()[world_id], run.result, run.result.spent)
    assert safe_row.correct and not safe_row.force_fit and safe_row.with_record


def test_catalog_incompleteness_is_detected_and_reproduced_by_a_replicate():
    a = held("held_out-geometry.thickness-00", 24).assessment
    assert a.reason is AbstentionReason.CATALOG_INCOMPLETE and a.catalog_incomplete
    assert a.inadequacy_reproduced is True
    assert a.adequate_alternatives == ()
    assert any(p.purpose is ProbePurpose.PROBE_REPLICATION for p in a.probes)
    assert a.distinct_hypotheses_checked > 100  # noise model, classes and family pairs


def test_over_the_development_held_out_worlds_force_fits_fall_at_every_budget():
    worlds = [w for w in _worlds().values() if not w.aliased]
    for budget in (12, 24, 48):
        rows = held_out.run_held_out(
            CATALOG,
            worlds,
            arms=(ev.B2, benchmark.Arm("B3", "safe", DISCOVERY, safe_runner())),
            budget=budget,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            protocol=DISCOVERY,
        )
        b2 = sum(r.force_fit for r in rows if r.arm == "B2")
        b3 = sum(r.force_fit for r in rows if r.arm == "B3")
        assert b2 >= 5, (budget, b2)
        assert b3 == 0, (budget, b3)


# -- confounders -----------------------------------------------------------------------------


def test_a_confounded_explanation_is_not_endorsed():
    """A laser-drift truth (measurement chain) with its family removed is mimicked by a cladding
    index drift on every experiment the engine runs; the gas-cell reference separates them."""
    run = held("held_out-chain.laser_drift-00", 24)
    assert run.engine.claim == ("hyp:cladding.index_drift",)
    a = run.assessment
    assert not a.endorsed and a.reason in INCOMPLETE
    assert "gas_cell_reference" in {p.experiment_id for p in a.probes}
    assert run.result.claim == ()


def test_in_catalog_confounded_measurement_chain_worlds_get_no_false_discovery():
    scenario = ring_scenario(2, base_seed=DEVELOPMENT_BASE_SEED)
    worlds = tuple(w for w in scenario.worlds if w.kind == "confounded_measurement_chain")
    subset = replace(scenario, worlds=worlds)
    rows, _ = ev.curve_evaluation(subset, (12, 24))
    assert all(not r.false_discovery for r in rows if r.arm == "B3")


# -- aliases ---------------------------------------------------------------------------------


def _with_renamed_duplicate(catalog: DiscoveryCatalog, class_id: str) -> DiscoveryCatalog:
    original = catalog.mechanism(class_id)
    twin = replace(original, class_id=class_id + "_renamed", statement="renamed duplicate")
    return replace(
        catalog, version=catalog.version + "+alias", mechanisms=(*catalog.mechanisms, twin)
    )


def test_a_renamed_duplicate_changes_no_decision_confidence_or_count():
    world = _worlds()["held_out-geometry.thickness-00"]
    base, _ = _reduced(world.family)
    aliased = _with_renamed_duplicate(base, "geometry.width_wide")

    def run(catalog: DiscoveryCatalog) -> SafeRun:
        return safe_investigate(
            arm="B3",
            catalog=catalog,
            oracle=_oracle(catalog),
            protocol=DISCOVERY,
            budget=Budget(24),
            lab=SyntheticWorld(world.spec, CATALOG, MOTIVATING_EXPERIMENT),
        )

    a, b = run(base).assessment, run(aliased).assessment
    assert (a.decision, a.reason, a.confidence) == (b.decision, b.reason, b.confidence)
    assert a.discriminating_tests_passed == b.discriminating_tests_passed
    assert [p.experiment_id for p in a.probes] == [p.experiment_id for p in b.probes]
    # One extra distinct forward model at most: the pair (class + its duplicate) is a new table
    # (twice the amplitude range); the duplicate itself and every pair with it are not counted.
    assert b.distinct_hypotheses_checked - a.distinct_hypotheses_checked <= 1


def test_renamed_rivals_and_replicates_do_not_inflate_discriminating_tests():
    world = _worlds()["held_out-geometry.thickness-00"]
    run = full(world.spec.world_id, 24)
    members = [run.engine.record(i).hypothesis for i in run.engine.claim]
    rivals = [r.hypothesis for r in run.engine.hypotheses if r.alias_of is None]
    observations = [o for o in run.result.observations if not o.motivating]
    oracle = _full_oracle()
    count = discriminating_tests_passed(members, rivals, observations, oracle, 3.0)
    assert count >= 1
    twin = _with_renamed_duplicate(CATALOG, rivals[1].components[0].class_id).mechanisms[-1]
    renamed = [*rivals, make_hypothesis(twin)]
    repeated = [
        *observations,
        *(replace(o, observation_id=o.observation_id + "r") for o in observations),
    ]
    assert discriminating_tests_passed(members, renamed, observations, oracle, 3.0) == count
    assert discriminating_tests_passed(members, rivals, repeated, oracle, 3.0) == count


# -- budgets and false confidence ------------------------------------------------------------


@pytest.mark.parametrize("world_id", [w for w, _ in FORCE_FIT_CASES])
def test_more_budget_never_buys_an_endorsement_of_a_surrogate(world_id):
    runs = [held(world_id, b) for b in (12, 24, 48)]
    assert all(r.assessment.confidence is not ConfidenceLevel.ADEQUATE for r in runs)
    assert all(r.result.claim == () for r in runs)


def test_adequate_confidence_requires_every_signal_experiment_to_have_been_run():
    for world_id in list(_worlds())[:12]:
        for budget in (10, 24):
            a = full(world_id, budget).assessment
            if a.confidence is ConfidenceLevel.ADEQUATE:
                assert set(a.signal_experiments) == set(a.signal_covered)
                assert all(t.adequate for t in a.adequacy)
            if set(a.signal_experiments) != set(a.signal_covered):
                assert a.confidence is not ConfidenceLevel.ADEQUATE


# -- safe abstention -------------------------------------------------------------------------


def test_an_abstention_is_well_formed_records_the_anomaly_and_is_not_a_discovery():
    run = held("held_out-geometry.thickness-00", 24)
    result, a = run.result, run.assessment
    assert result.outcome not in CLAIM_OUTCOMES
    assert result.claim == () and result.handover is None
    assert result.spent <= result.budget == 24
    assert result.spent == a.spent_by_engine + a.spent_on_probes
    by_id = {x.anomaly_id: x for x in result.anomalies}
    assert a.anomalies and all(by_id[i].state is AnomalyState.UNEXPLAINED for i in a.anomalies)
    assert result.reframings[-1].rationale == a.reframed_question
    assert a.reframed_question and a.reframed_question.startswith("Reframed:")
    assert a.requests
    assert any("ABSTAIN" in n for n in result.notes)
    claimed = [r for r in result.hypotheses if r.hypothesis_id in run.engine.claim]
    assert all(r.state.value == "STOPPED" for r in claimed)
    assert "CONFIRMED" not in str(to_jsonable(a)) and "CONFIRMED" not in str(result.as_json())


def test_the_engine_result_is_kept_untouched_beside_the_safe_one():
    run = held("held_out-geometry.thickness-00", 24)
    assert run.engine.observations == run.result.observations[: len(run.engine.observations)]
    assert run.engine.claim and run.engine.handover is not None


def test_the_safe_run_is_deterministic():
    world = _worlds()["held_out-chain.polarization_drift-00"]
    catalog, oracle = _reduced(world.family)

    def once() -> str:
        return safe_investigate(
            arm="B3",
            catalog=catalog,
            oracle=oracle,
            protocol=DISCOVERY,
            budget=Budget(12),
            lab=SyntheticWorld(world.spec, CATALOG, MOTIVATING_EXPERIMENT),
        ).result.digest

    assert once() == once()


# -- genuine new-mechanism proposals ---------------------------------------------------------


def test_a_proposal_is_stage_1_matches_the_residuals_and_never_enters_a_claim():
    run = held("held_out-geometry.thickness-00", 24)
    p = run.assessment.proposal
    assert p is not None
    assert (p.stage, p.status) == ("STAGE_1_EXPLORATORY_IDEA", "PROPOSAL_NOT_A_CLAIM")
    assert (p.stage, p.status) == (PROPOSAL_STAGE, PROPOSAL_STATUS)
    assert p.statement.startswith("PROPOSAL (stage-1 exploratory idea, not a claim)")
    assert p.fits_observed and p.fit_p_value >= SAFETY.alpha_adequacy
    excluded = set(run.assessment.excluded_as_noise)
    admitted = [
        o for o in run.result.observations if not o.motivating and o.observation_id not in excluded
    ]
    for s in p.signature:
        values = [o.value(s.entry_id) for o in admitted if o.experiment_id == s.experiment_id]
        assert len(values) == s.runs
        assert math.isclose(s.mean, sum(values) / len(values), rel_tol=1e-12)
    assert p.signature and p.closest_separation > 0
    assert run.assessment.catalog_incomplete and p.closest_declared not in set(
        run.assessment.adequate_alternatives
    )
    ids = {h.hypothesis_id for h in run.result.hypotheses}
    assert p.proposal_id not in ids and p.proposal_id not in run.result.claim
    assert p.proposal_id not in str(run.result.handover)
    requests = [
        r for r in run.assessment.requests if r.purpose is RequestPurpose.DISCRIMINATE_PROPOSAL
    ]
    assert requests and all(pair[0] == p.proposal_id for r in requests for pair in r.pairs)


def test_discriminating_requests_name_pairs_and_reach_the_threshold():
    requests = [
        r
        for world_id, _ in FORCE_FIT_CASES
        for budget in (12, 24, 48)
        for r in held(world_id, budget).assessment.requests
    ]
    purposes = {r.purpose for r in requests}
    assert RequestPurpose.DISCRIMINATE_PROPOSAL in purposes
    for request in requests:
        assert request.pairs and request.replicates_needed >= 1
        for x, y, separation in request.pairs:
            assert x != y and separation > 0
            reached = separation * math.sqrt(request.replicates_needed)
            assert reached >= SAFETY.discriminating_tau - 1e-9, request


def test_a_single_remaining_declared_candidate_gets_a_prospective_test_request():
    a = held("held_out-leakage.substrate-00", 24).assessment
    assert a.reason is AbstentionReason.CLAIM_INADEQUATE and len(a.adequate_alternatives) == 1
    assert a.requests and all(r.purpose is RequestPurpose.ADEQUACY_PROBE for r in a.requests)
    assert all(r.pairs[0][0] == a.adequate_alternatives[0] for r in a.requests)


# -- recovery after new evidence -------------------------------------------------------------


def test_recovery_when_the_catalog_is_extended_with_the_missing_family():
    world_id = "held_out-geometry.thickness-00"
    assert held(world_id, 24).assessment.reason is AbstentionReason.CATALOG_INCOMPLETE
    recovered = full(world_id, 24)
    assert recovered.assessment.endorsed
    assert recovered.assessment.confidence is ConfidenceLevel.ADEQUATE
    assert _correct_in_catalog(world_id, recovered)


def test_recovery_when_the_requested_probes_are_afforded():
    world_id = "held_out-geometry.thickness-00"
    short = full(world_id, 10).assessment
    assert short.reason is AbstentionReason.ADEQUACY_UNVERIFIED
    assert short.confidence is ConfidenceLevel.PROVISIONAL
    requested = {r.experiment_id for r in short.requests}
    assert requested and all(r.purpose is RequestPurpose.ADEQUACY_PROBE for r in short.requests)
    longer = full(world_id, 24)
    assert longer.assessment.endorsed and _correct_in_catalog(world_id, longer)
    assert requested <= {o.experiment_id for o in longer.result.observations}


# -- positive control ------------------------------------------------------------------------


def test_with_the_truth_in_the_catalog_the_safe_arm_stays_correct_at_budget_24():
    worlds = [w for w in _worlds().values() if not w.aliased]
    correct = sum(_correct_in_catalog(w.spec.world_id, full(w.spec.world_id, 24)) for w in worlds)
    assert correct >= len(worlds) - 2, (correct, len(worlds))


def test_the_safe_arm_adds_no_false_discovery_on_the_in_catalog_world_kinds():
    scenario = ring_scenario(2, base_seed=DEVELOPMENT_BASE_SEED)
    rows, _ = ev.curve_evaluation(scenario, (8, 12, 24))
    for cap in (8, 12, 24):
        b2 = sum(r.false_discovery for r in rows if r.cap == cap and r.arm == "B2")
        b3 = sum(r.false_discovery for r in rows if r.cap == cap and r.arm == "B3")
        assert b3 <= b2, (cap, b2, b3)
    assert all(r.spent <= r.cap for r in rows)


def test_the_null_claim_is_probed_too():
    """`NO_EFFECT_BEYOND_NOISE` is an available explanation like any other: it is not endorsed
    when a probe shows an effect."""
    run = held("held_out-nonlinear.tpa_fca-01", 24)
    assert run.engine.claim == (NULL_HYPOTHESIS.hypothesis_id,)
    assert not run.assessment.endorsed and run.result.outcome not in CLAIM_OUTCOMES


def test_observation_helpers_are_not_fooled_by_the_motivating_observation():
    run = held("held_out-geometry.thickness-00", 24)
    motivating = [o for o in run.result.observations if o.motivating]
    assert len(motivating) == 1 and isinstance(motivating[0], Observation)
    assert all(p.observation_id != motivating[0].observation_id for p in run.assessment.probes)
