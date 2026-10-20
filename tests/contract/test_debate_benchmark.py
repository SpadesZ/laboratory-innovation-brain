"""T-LLM-002: the fixed SiPho debate benchmark, against a baseline, with a refutable verdict.

    §26 T-LLM-002  fixed SiPho benchmark produces baseline distributions; the benchmark MUST
                   compare the debate mechanism against a baseline/disabled condition on the same
                   cases, so a claim of groupthink reduction can be refuted by the result and not
                   merely illustrated; BenchmarkPolicy schema stores metric/threshold/sample size/
                   calibration artifacts/version; no hard gate before calibration; the benchmark
                   MUST record per-case round count and show it varies with case difficulty, so an
                   implementation that always runs the configured maximum number of rounds FAILS
                   even when every metric is recorded correctly (§7.2).

Each clause of that row is one test below, and two of them run the benchmark against a deliberately
broken debate -- a yes-man Critic, and a debate forced to its maximum rounds -- because a pass
condition that cannot be seen to fail has not been shown to discriminate.
"""

from __future__ import annotations

import functools
from decimal import Decimal

import pytest

from lab_brain.cognition.debate_benchmark import (
    BenchmarkRun,
    CalibrationError,
    Condition,
    Verdict,
    calibrate,
    calibration_samples,
    compare,
    distributions,
    evaluate,
    round_count_problems,
    rounds_by_difficulty,
)
from lab_brain.cognition.debate_metrics import CRITIC_BUNDLE_DIVERGENCE, DebateGate
from lab_brain.core.benchmark_gate import evaluate_gate
from lab_brain.core.repositories.benchmark import InMemoryBenchmarkStore
from lab_brain.domains.silicon_photonics.plugin import DEBATE_BENCHMARK_FIXTURE, DEBATE_BENCHMARK_ID
from tests.debate_fixtures import (
    CALIBRATED_AT,
    CALIBRATION_POLICY_ID,
    CALIBRATION_VERSION,
    DOMAIN,
    FIXTURE_PATH,
    FIXTURE_SHA256,
    ROOT,
    benchmark_runner,
    fixture_digest,
    load_fixture,
)

pytestmark = [pytest.mark.requirement("LLM-002"), pytest.mark.spec_test("T-LLM-002")]


@functools.cache
def _run() -> BenchmarkRun:
    return evaluate(load_fixture(), benchmark_runner(), fixture_digest=fixture_digest())


def _policy():  # type: ignore[no-untyped-def]
    return calibrate(
        _run(),
        domain=DOMAIN,
        policy_id=CALIBRATION_POLICY_ID,
        version=CALIBRATION_VERSION,
        calibrated_at=CALIBRATED_AT,
    )


# -- the benchmark is fixed ----------------------------------------------------------------------


def test_the_benchmark_fixture_is_locked():
    """Editing a case changes the digest; this fails until the change is made visibly, here."""
    assert fixture_digest() == FIXTURE_SHA256
    assert FIXTURE_PATH.relative_to(ROOT).as_posix() == DEBATE_BENCHMARK_FIXTURE
    fx = load_fixture()
    assert fx["benchmark_set_id"] == DEBATE_BENCHMARK_ID
    assert fx["domain"] == DOMAIN
    assert {c["difficulty"] for c in fx["cases"]} == set(fx["difficulty_order"])


def test_the_run_is_reproducible():
    again = evaluate(load_fixture(), benchmark_runner(), fixture_digest=fixture_digest())
    assert again.digest == _run().digest


# -- same cases, three conditions, baseline distributions ---------------------------------------


def test_every_case_runs_under_the_debate_the_baseline_and_the_ablation():
    run = _run()
    cases = [c["case_id"] for c in load_fixture()["cases"]]
    for condition in Condition:
        assert [r.case_id for r in run.under(condition)] == cases


def test_the_baseline_is_the_disabled_condition():
    for r in _run().under(Condition.BASELINE):
        assert r.stop_reason == "CRITIC_DISABLED"
        assert r.critic_bundle_divergence is None and r.additional_token_count == 0


def test_the_benchmark_produces_baseline_distributions_of_every_section_15_4_metric():
    dists = distributions(_run())
    assert set(dists) == set(Condition)
    for metric in (
        "position_diversity",
        CRITIC_BUNDLE_DIVERGENCE,
        "critic_changed_final_set",
        "surviving_hypothesis_diversity",
        "additional_evidence_items",
        "additional_token_count",
        "rounds",
    ):
        for condition in Condition:
            assert dists[condition][metric].n == len(load_fixture()["cases"])
    # Measured where the mechanism exists, unmeasured -- not zero -- where it does not.
    assert dists[Condition.DEBATE][CRITIC_BUNDLE_DIVERGENCE].unmeasured == 0
    assert dists[Condition.BASELINE][CRITIC_BUNDLE_DIVERGENCE].unmeasured == len(
        _run().under(Condition.BASELINE)
    )


# -- the verdict is refutable --------------------------------------------------------------------


def test_the_debate_beats_the_baseline_on_the_hard_cases_and_loses_none():
    comparison = compare(_run())
    assert comparison.verdict is Verdict.SUPPORTED, comparison.reasons
    assert comparison.losses == ()
    hard = {r.case_id for r in _run().under(Condition.DEBATE) if r.difficulty == "HARD"}
    assert set(comparison.wins) == hard
    assert comparison.changed_final_set == len(hard)


def test_the_inverted_retrieval_is_the_mechanism_that_matters():
    """§15.3's question: more calls, or the mechanism? The Critic without its own retrieval loses."""
    assert compare(_run(), against=Condition.NO_INVERTED).verdict is Verdict.SUPPORTED
    for r in _run().under(Condition.NO_INVERTED):
        if r.difficulty == "HARD":
            assert not r.truth_retained


def test_a_yes_man_critic_is_refuted_by_the_same_benchmark():
    """The benchmark can say NO: a Critic that objects to nothing buys tokens and nothing else."""
    passive = evaluate(
        load_fixture(),
        benchmark_runner(scientist_flags={"passive_critic": True}),
        fixture_digest=fixture_digest(),
        conditions=(Condition.DEBATE, Condition.BASELINE),
    )
    comparison = compare(passive)
    assert comparison.verdict is Verdict.REFUTED
    assert comparison.wins == () and comparison.changed_final_set == 0
    assert comparison.token_ratio is not None and comparison.token_ratio > 1


# -- per-case rounds vary with difficulty ----------------------------------------------------------


def test_per_case_round_count_is_recorded_and_rises_with_difficulty():
    run = _run()
    assert round_count_problems(run) == []
    by_level = rounds_by_difficulty(run, Condition.DEBATE)
    assert set(by_level["EASY"]) == {1}
    assert min(by_level["HARD"]) >= 2
    assert all(r.rounds < r.max_rounds for r in run.under(Condition.DEBATE))


def test_an_implementation_that_always_runs_the_maximum_fails_even_with_every_metric_recorded():
    """§7.2 / v3.3-a6: the configured maximum on every case is the failure, whatever else is right."""
    forced = evaluate(
        load_fixture(),
        benchmark_runner(human_requested_rounds=10),
        fixture_digest=fixture_digest(),
        conditions=(Condition.DEBATE,),
    )
    rounds = {r.rounds for r in forced.under(Condition.DEBATE)}
    assert rounds == {forced.results[0].max_rounds}
    assert all(r.critic_bundle_divergence is not None for r in forced.results)  # metrics recorded
    problems = round_count_problems(forced)
    assert any("configured maximum" in p for p in problems)
    assert any("does not vary" in p for p in problems)


# -- the BenchmarkPolicy is calibrated, not typed ---------------------------------------------------


def test_the_calibrated_policy_stores_metric_threshold_sample_size_artifacts_and_version():
    policy = _policy()
    samples = calibration_samples(_run())
    assert policy.metric_key == CRITIC_BUNDLE_DIVERGENCE
    assert policy.threshold == min(samples)
    assert policy.sample_size == len(samples) == len(load_fixture()["cases"])
    assert policy.version == CALIBRATION_VERSION
    assert policy.benchmark_set_id == DEBATE_BENCHMARK_ID
    assert policy.calibration_artifact_refs == (
        f"fixture:{DEBATE_BENCHMARK_ID}@1.0.0#sha256:{FIXTURE_SHA256}",
        f"benchmark-run:{DEBATE_BENCHMARK_ID}#sha256:{_run().digest}",
    )
    assert not policy.active, "running a benchmark never arms a gate by itself"


def test_a_run_with_nothing_to_calibrate_on_refuses_to_produce_a_threshold():
    passive = evaluate(
        load_fixture(),
        benchmark_runner(),
        fixture_digest=fixture_digest(),
        conditions=(Condition.BASELINE,),
    )
    with pytest.raises(CalibrationError, match="forbids typing one"):
        calibrate(
            passive,
            domain=DOMAIN,
            policy_id=CALIBRATION_POLICY_ID,
            version=CALIBRATION_VERSION,
            calibrated_at=CALIBRATED_AT,
        )


def test_no_hard_gate_before_calibration_and_an_enforced_one_after_activation():
    store = InMemoryBenchmarkStore()
    gate = DebateGate(store, domain=DOMAIN, benchmark_set_id=DEBATE_BENCHMARK_ID)
    low = Decimal("0.1")

    before = gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, low)
    assert not before.enforced and not before.blocks and before.policy_ref is None

    store.add_policy(_policy())
    stored_inactive = gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, low)
    assert not stored_inactive.enforced, "a stored but inactive policy arms nothing"

    store.activate(CALIBRATION_POLICY_ID, CALIBRATION_VERSION)
    after = gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, low)
    assert after.enforced and after.blocks
    assert after.policy_ref == f"{CALIBRATION_POLICY_ID}@{CALIBRATION_VERSION}"
    assert gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, _policy().threshold).passed
    # An armed gate fails closed on an unmeasured value (the ablation has no divergence).
    assert gate.evaluate(CRITIC_BUNDLE_DIVERGENCE, None).blocks


def test_a_policy_for_another_metric_cannot_arm_this_gate():
    policy = _policy().model_copy(update={"active": True})
    with pytest.raises(ValueError, match="not position_diversity"):
        evaluate_gate("position_diversity", Decimal("0.5"), policy)


def test_the_committed_report_is_current():
    """`scripts/run_debate_benchmark.py --check`, in-process: the published numbers are these."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_debate_benchmark", ROOT / "scripts" / "run_debate_benchmark.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (ROOT / "benchmarks" / "debate_benchmark_report.md").read_text(encoding="utf-8")
    assert committed.replace("\r\n", "\n") == module.build_report()
