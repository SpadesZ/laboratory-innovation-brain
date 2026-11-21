"""Safety v1.4: rival closure by failed prediction, grammar rivals, per-world cost matching, holdout.

Development seeds only: v1.2/v1.3 development bases and v1.3's held-out (3_218_044_000) and
benchmark (3_729_592_000) ranges, which were seen in round 4 and are development data now
(`PLAN.development`). Every world is synthetic and written by the engine's author lineage.
ENGINEERING EVIDENCE ONLY.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
from functools import cache
from types import ModuleType
from typing import Any

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.loop import hypothesis_universe, investigate
from lab_brain.discovery.model import NULL_HYPOTHESIS, Budget
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v12.gate import grammar_shapes, hypothesis_prediction
from lab_brain.discovery_safety.v12.ledger import PredictionRule, prediction_payload
from lab_brain.discovery_safety.v13 import evaluation as ev13
from lab_brain.discovery_safety.v13.ledger import (
    REGISTER,
    EvaluatorLaboratory,
    EvaluatorLedger,
    observations_before,
    verify_chain,
)
from lab_brain.discovery_safety.v13.model import ArmAnswer
from lab_brain.discovery_safety.v13.rule import rescore
from lab_brain.discovery_safety.v14 import costmatch
from lab_brain.discovery_safety.v14 import evaluation as ev
from lab_brain.discovery_safety.v14.model import (
    EVALUATOR_RULE_V14,
    HOLDOUT_DOMAIN,
    PLAN,
    holdout_base_seed,
)
from lab_brain.discovery_safety.v14.rule import (
    RescorerV14,
    closed_by,
    open_rivals_v14,
    verdict_v14,
)
from lab_brain.spec import repo_root

SCRIPT = repo_root() / "scripts" / "discovery_safety_v14_eval.py"
REPRO = repo_root() / "scripts" / "discovery_safety_v13_reproduce_before.py"
HELD_OUT_V13 = 3_218_044_000
BENCHMARK_V13 = 3_729_592_000


def _load(path: Any, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def script() -> ModuleType:
    return _load(SCRIPT, "discovery_safety_v14_eval")


@cache
def repro() -> ModuleType:
    return _load(REPRO, "discovery_safety_v13_reproduce_before")


def _case(setting: str, world_id: str) -> Any:
    s = script()
    if setting == "benchmark":
        sc = s.ring_scenario(15, base_seed=BENCHMARK_V13)
        world = next(w for w in sc.worlds if w.world_id == world_id)
        return s.benchmark_case(sc, world, benchmark.Oracles(sc.catalog, DISCOVERY))
    worlds = held_out.held_out_worlds(
        s.ring_catalog(), seeds_per_class=10, base_seed=HELD_OUT_V13, protocol=DISCOVERY
    )
    return s.held_out_case(
        next(w for w in worlds if w.spec.world_id == world_id), setting == "held_out"
    )


@cache
def _records(setting: str, world_id: str, caps: tuple[int, ...]) -> dict[tuple[str, int], Any]:
    s = script()
    evaluator = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE_V14)
    return {(r.arm, r.budget): r for r in evaluator.run(_case(setting, world_id), caps)}


def _rescorer(case: Any) -> RescorerV14:
    return RescorerV14(
        distinct_forward_models(hypothesis_universe(case.engine_catalog)),
        grammar_shapes(script().GRAMMAR),
        ev13.all_experiments(case.full_catalog),
        EVALUATOR_RULE_V14,
        case.engine_oracle.distinguishable,
        tuple(e.experiment_id for e in case.engine_oracle.available),
    )


# -- A. the residual false endorsements of v1.3 ------------------------------------------------

RESIDUAL = (
    ("held_out", "held_out-leakage.substrate-06", (24, 48)),
    ("held_out", "held_out-geometry.width_wide-03", (8,)),
    ("benchmark", "noise_glitch-06", (8,)),
    ("benchmark", "noise_only_null-04", (8,)),
)


@pytest.mark.parametrize(("setting", "world_id", "caps"), RESIDUAL)
def test_v14_rule_withholds_support_from_v13s_wrong_answers_and_b7_does_not_endorse_them(
    setting, world_id, caps
):
    rows = _records(setting, world_id, caps)
    for cap in caps:
        b6, b7 = rows[("B6", cap)], rows[("B7", cap)]
        # v1.3's answer: SUPPORTED by v1.3's rule, an UNSUPPORTED_CLAIM under v1.4's (still an
        # error under candidate.5), with open rivals named
        assert b6.v13_level == ev.SUPPORTED and b6.level == ev.PROPOSAL
        assert b6.category == ev13.UNSUPPORTED_CLAIM and b6.open_rivals > 0
        # v1.4 does not endorse a wrong answer here (it abstains)
        assert b7.category not in (ev13.FORCE_FIT, ev13.WRONG_CLAIM, ev13.UNSUPPORTED_CLAIM)
        assert b7.answer == "NONE"


def test_a_rival_whose_prediction_passes_the_closing_runs_stays_open():
    """`leakage.substrate-06`: v1.3 closed `chain.polarization_drift` by separation on the cutback
    test; under v1.4 it is closed only if its own prediction failed there, which it did not."""
    case = _case("held_out", "held_out-leakage.substrate-06")
    s = script()
    ledger = EvaluatorLedger()
    experiments = ev13.all_experiments(case.full_catalog)
    lab = EvaluatorLaboratory(
        blind_laboratory(
            case.lab_factory(),
            experiments=experiments,
            available=tuple(e.experiment_id for e in case.engine_oracle.available),
            meter=CostMeter({k: e.cost for k, e in experiments.items()}, 24),
        ),
        ledger,
    )
    answer = s._handle({**case.request, "arm": "B6", "budget": 24}, lab)
    rescorer = _rescorer(case)
    events = ledger.events()
    tests = rescore(rescorer, events)
    claim = next(h for h in rescorer.catalog.values() if h.hypothesis_id == answer.claim[0])
    rival = next(
        h for h in rescorer.catalog.values() if h.hypothesis_id == "hyp:chain.polarization_drift"
    )
    assert closed_by(rescorer, events, tests, claim.fingerprint, rival.fingerprint) is None
    labels = {r.label for r in open_rivals_v14(rescorer, events, tests, claim.fingerprint)}
    assert "hyp:chain.polarization_drift" in labels
    assert any(label.startswith("grammar:") for label in labels)
    assert not verdict_v14(rescorer, events, tests, claim.fingerprint).supported


def test_a_rival_is_closed_by_its_failed_prediction_on_a_test_the_claim_passed():
    """`geometry.width_wide-03` at cap 8: the claim's passed gap-array test refutes
    `cladding.index_drift` (its own evaluator prediction fails the same run)."""
    case = _case("held_out", "held_out-geometry.width_wide-03")
    s = script()
    ledger = EvaluatorLedger()
    experiments = ev13.all_experiments(case.full_catalog)
    lab = EvaluatorLaboratory(
        blind_laboratory(
            case.lab_factory(),
            experiments=experiments,
            available=tuple(e.experiment_id for e in case.engine_oracle.available),
            meter=CostMeter({k: e.cost for k, e in experiments.items()}, 8),
        ),
        ledger,
    )
    answer = s._handle({**case.request, "arm": "B6", "budget": 8}, lab)
    rescorer = _rescorer(case)
    events = ledger.events()
    tests = rescore(rescorer, events)
    claim = next(h for h in rescorer.catalog.values() if h.hypothesis_id == answer.claim[0])
    rival = next(
        h for h in rescorer.catalog.values() if h.hypothesis_id == "hyp:cladding.index_drift"
    )
    index = closed_by(rescorer, events, tests, claim.fingerprint, rival.fingerprint)
    assert index is not None
    t = next(t for t in tests if t.register_index == index)
    assert t.identity == claim.fingerprint and t.passed and t.experiment_id == "gap_array"
    # what keeps the claim unsupported is the grammar: adequate shapes that predict differently
    # on experiments the arm never ran
    rivals = open_rivals_v14(rescorer, events, tests, claim.fingerprint)
    assert rivals and all(r.kind == "grammar" for r in rivals)


def test_a_grammar_shape_is_one_cause_and_quiet_data_raise_no_grammar_rival_of_no_effect():
    case = _case("control", "held_out-thermo.ambient-00")
    rescorer = _rescorer(case)
    shape = next(s for s in rescorer.shapes.values() if len(s.tables) == 2)
    assert rescorer.size(shape.fingerprint) == 1
    assert rescorer.size(NULL_HYPOTHESIS.fingerprint) == 1
    ledger = EvaluatorLedger()
    experiments = ev13.all_experiments(case.full_catalog)
    for x in ("baseline", "power_sweep", "tec_stabilized"):
        ledger.record_measurement(x, 0, tuple((e.entry_id, 0.0) for e in experiments[x].entries))
    data = observations_before(ledger.events(), len(ledger.events()))
    assert all(r.kind != "grammar" for r in rescorer.rivals_v14(NULL_HYPOTHESIS.fingerprint, data))


def test_no_effect_is_held_against_a_grammar_shape_whose_fitted_effect_is_clear():
    """Development world `geometry.gap_small-01` (base 8_000_000, family removed): kappa reads
    1.3, 1.1, 2.7 (sigma 1); "no effect" stays adequate (one-outlier tolerant) and no catalog
    hypothesis the arm holds expresses a coupling shift. v1.3's rule endorsed "no effect"; under
    v1.4 a grammar shape fitted to that shift is an open rival, and B7 does not claim it."""
    s = script()
    worlds = held_out.held_out_worlds(
        s.ring_catalog(), seeds_per_class=3, base_seed=8_000_000, protocol=DISCOVERY
    )
    case = s.held_out_case(
        next(w for w in worlds if w.spec.world_id == "held_out-geometry.gap_small-01"), True
    )
    evaluator = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE_V14, ("B6", "B7"))
    rows = {r.arm: r for r in evaluator.run(case, (12,))}
    assert rows["B6"].claim == ("hyp:null",) and rows["B6"].v13_level == ev.SUPPORTED
    assert rows["B6"].level == ev.PROPOSAL and rows["B6"].open_rivals > 0
    assert rows["B7"].category not in (ev13.FORCE_FIT, ev13.WRONG_CLAIM, ev13.UNSUPPORTED_CLAIM)


# -- B. the five v1.3 ledger attacks stay refused under the v1.4 rule --------------------------


def _r1_ledger() -> tuple[Any, Any, Any, Any, Any]:
    r = repro()
    catalog, world, engine_catalog, oracle, experiments, meter, _, _, judge = r._setup(
        r.FORCE_FIT_WORLD, 24
    )
    ledger = EvaluatorLedger()
    lab = EvaluatorLaboratory(
        blind_laboratory(
            r.SyntheticWorld(world.spec, catalog, r.MOTIVATING_EXPERIMENT),
            experiments=experiments,
            available=tuple(e.experiment_id for e in catalog.experiments),
            meter=meter,
        ),
        ledger,
    )
    result = investigate(
        arm="ADV",
        catalog=engine_catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(20),
        lab=lab,
    )
    claim = result.record(result.claim[0]).hypothesis
    rescorer = RescorerV14(
        distinct_forward_models(hypothesis_universe(engine_catalog)),
        grammar_shapes(script().GRAMMAR),
        experiments,
        EVALUATOR_RULE_V14,
        oracle.distinguishable,
        tuple(e.experiment_id for e in catalog.experiments),
    )
    return lab, ledger, claim, rescorer, (judge, engine_catalog, experiments, result)


def _payload(subject: str, fingerprint: str, x: Any, mean: Any, sd: Any, alts: Any) -> str:
    return prediction_payload(
        subject=subject,
        fingerprint=fingerprint,
        experiment_id=x.experiment_id,
        replicate=0,
        predicted=mean,
        sd=sd,
        alternatives=alts,
        rule=PredictionRule(alpha=0.0, z_max=1e9, tau_risky=0.0),
        purpose="ATTACK",
    )


@pytest.mark.parametrize("attack", ["sd", "alternatives", "thresholds", "label"])
def test_arm_supplied_quantities_decide_nothing_under_v14(attack):
    """R1-R4: inflated SD, a far arm-chosen alternative, payload thresholds, and another
    hypothesis's values filed under the claim's fingerprint. The v1.3 ledger keeps only identity
    and experiment; the v1.4 evaluator refits the identity itself: the force-fit fails its own
    prediction and is never SUPPORTED."""
    lab, ledger, claim, rescorer, (judge, engine_catalog, experiments, result) = _r1_ledger()
    x = experiments["polarization_controlled"]
    data = observations_before(ledger.events(), len(ledger.events()))
    mean, sd = hypothesis_prediction(claim, data, experiments, x)
    other = next(h for h in rescorer.catalog.values() if h.class_ids == ("thermo.ambient",))
    far = [("none", dict.fromkeys(mean, 1e7), dict.fromkeys(mean, 0.0))]
    payload = {
        "sd": _payload(
            claim.hypothesis_id, claim.fingerprint, x, mean, dict.fromkeys(sd, 1e6), far
        ),
        "alternatives": _payload(claim.hypothesis_id, claim.fingerprint, x, mean, sd, far),
        "thresholds": _payload(claim.hypothesis_id, claim.fingerprint, x, mean, sd, []),
        "label": _payload(
            claim.hypothesis_id,
            claim.fingerprint,
            x,
            *hypothesis_prediction(other, data, experiments, x),
            far,
        ),
    }[attack]
    lab.register(payload)
    lab.measure(x.experiment_id, replicate=0, session=99)
    events = ledger.events()
    verify_chain(events)
    register = next(e for e in events if e.kind == REGISTER)
    assert {"sd", "alternatives", "rule", "predicted"}.isdisjoint(register.body())
    tests = rescore(rescorer, events)
    assert len(tests) == 1 and tests[0].complete and not tests[0].passed
    assert not verdict_v14(rescorer, events, tests, claim.fingerprint).supported
    by_id = {h.hypothesis_id: h for h in hypothesis_universe(engine_catalog)}
    out = ev.judge_answer(
        judge,
        rescorer,
        _v13(rescorer),
        events,
        ArmAnswer("ADV", result.outcome.value, "CATALOG_CLAIM", (claim.hypothesis_id,)),
        by_id,
    )
    assert (out["category"], out["level"]) == (ev13.UNSUPPORTED_CLAIM, ev.PROPOSAL)


def _v13(rescorer: RescorerV14) -> Any:
    from lab_brain.discovery_safety.v13.model import EVALUATOR_RULE
    from lab_brain.discovery_safety.v13.rule import Rescorer

    return Rescorer(
        list(rescorer.catalog.values()),
        list(rescorer.shapes.values()),
        rescorer.experiments,
        EVALUATOR_RULE,
        rescorer.distinguishable,
    )


def test_a_new_mechanism_answer_is_rebuilt_by_the_evaluator_and_a_forged_one_supports_nothing():
    """R5: the answer carries only a grammar fingerprint; the evaluator rebuilds it from its own
    ledger. A fingerprint outside the grammar (or one never registered) is not SUPPORTED."""
    _, ledger, _, rescorer, (judge, engine_catalog, _, result) = _r1_ledger()
    events = ledger.events()
    by_id = {h.hypothesis_id: h for h in hypothesis_universe(engine_catalog)}
    for identity in ("sha256:" + "0" * 64, next(iter(rescorer.shapes))):
        out = ev.judge_answer(
            judge,
            rescorer,
            _v13(rescorer),
            events,
            ArmAnswer("ADV", result.outcome.value, "NEW_MECHANISM", new_mechanism=identity),
            by_id,
        )
        assert out["level"] == ev.PROPOSAL and out["category"] == ev13.UNSUPPORTED_CLAIM


def test_b7_gives_the_same_answer_across_the_process_boundary():
    s = script()
    case = _case("held_out", "held_out-thermo.ambient-00")
    inside = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE_V14).run(case, (8,))
    outside = ev.Evaluator(s._execute_boundary, s.GRAMMAR, EVALUATOR_RULE_V14).run(case, (8,))
    assert [(r.arm, r.category, r.level, r.spent, r.chain_head, r.digest) for r in inside] == [
        (r.arm, r.category, r.level, r.spent, r.chain_head, r.digest) for r in outside
    ]


# -- C. per-world matching ---------------------------------------------------------------------


def _row(world: str, y: dict[int, tuple[int, bool]], x: dict[int, tuple[int, bool]]) -> Any:
    def cells(d: dict[int, tuple[int, bool]]) -> dict[str, Any]:
        return {
            str(cap): {
                "spent": spent,
                "own_correct": ok,
                "own_error": not ok,
                "category": "EXACT_IDENTIFICATION" if ok else "FALSE_NULL",
            }
            for cap, (spent, ok) in d.items()
        }

    return {"world_id": world, "arms": {"Y": cells(y), "X": cells(x)}}


def test_a_mean_cost_match_hides_opposite_per_world_costs_and_per_world_matching_does_not():
    """Two worlds: Y spends 2 where X spends 10 and the reverse. Mean costs are equal (a v1.3
    COST_MATCHED cell); world by world nothing at the anchor cap is at equal cost, so the dearer
    arm's cheaper anytime answer is used, or the world is unmatched."""
    rows = [
        _row("w1", {6: (2, False), 10: (2, False)}, {6: (6, True), 10: (10, True)}),
        _row("w2", {6: (6, True), 10: (10, True)}, {6: (2, False), 10: (2, False)}),
    ]
    contrast = costmatch.cost_contrast(rows, "Y", "X", 10, tolerance=1, resamples=50, label="t")
    assert contrast["mean_cost_difference"]["mean"] == 0.0
    assert contrast["worlds_beyond_tolerance"] == 2
    matched = costmatch.per_world_matched(rows, "Y", "X", 10, tolerance=1, resamples=50, label="t")
    assert matched["matched"] == 0 and matched["unmatched"] == 2
    assert matched["unmatched_y_dearer"] == 1 and matched["unmatched_x_dearer"] == 1


def test_per_world_matching_uses_the_dearer_arms_cheaper_anytime_answer():
    rows = [_row("w", {6: (6, True), 10: (9, True)}, {6: (5, False), 10: (6, False)})]
    p = costmatch.per_world_matched(rows, "Y", "X", 10, tolerance=1, resamples=50, label="t")
    # cost point min(9, 6) = 6: Y's anytime answer at 6 is its cap-6 run; X's is its cap-10 run
    assert p["matched"] == 1 and p["matched_caps_used"] == {"Y": {"6": 1}, "X": {"10": 1}}
    assert p["differences"]["cost"]["mean"] == 0.0
    assert p["differences"]["own_correct"]["mean"] == 1.0
    assert costmatch.anytime(rows[0]["arms"]["Y"], 7, 10, 0) is None
    assert costmatch.anytime(rows[0]["arms"]["Y"], 9, 6, 1) is None  # caps above the anchor


def test_cost_distribution_reports_quantiles_and_the_cap_censored_share():
    d = costmatch.cost_distribution([1, 2, 3, 4, 10, 10], 10)
    assert (d["min"], d["median"], d["max"], d["at_cap"]) == (1, 3.0, 10, round(2 / 6, 4))


def test_the_v13_reanalysis_is_reproducible_from_the_frozen_rows():
    path = (
        repo_root()
        / "docs"
        / "audit"
        / "discovery-safety-v1.4-2026-11-21"
        / "evidence"
        / "v13_reanalysis.json"
    )
    if not path.exists():
        pytest.skip("the reanalysis evidence is written in its own commit")
    log: list[str] = []
    assert json.loads(script()._dump(script().reanalyse_v13(log))) == json.loads(
        path.read_text(encoding="utf-8")
    )


# -- D. the held-out seed rule -----------------------------------------------------------------


def test_held_out_seeds_are_derived_from_the_full_freeze_commit_and_avoid_every_earlier_range():
    commit = "0123456789abcdef0123456789abcdef01234567"
    seeds = PLAN.held_out_seeds(commit)
    text = f"{HOLDOUT_DOMAIN}\x00held-out-worlds\x00{commit}\x000"
    expected = 3_000_000_000 + 1000 * (
        int(hashlib.sha256(text.encode()).hexdigest(), 16) % 1_000_000
    )
    first = seeds["held-out-worlds"]
    assert first["attempt"] > 0 or first["base_seed"] == expected
    used = PLAN.used
    for s in seeds.values():
        assert all(abs(s["base_seed"] - u) >= 20_000 for u in used)
    assert seeds == PLAN.held_out_seeds(commit)
    assert seeds != PLAN.held_out_seeds("f" * 40)
    with pytest.raises(ValueError):
        holdout_base_seed("abc123", "held-out-worlds", used)
    # v1.3's seen ranges are development data now
    assert {HELD_OUT_V13, BENCHMARK_V13} <= {r.base_seed for r in PLAN.development}
    assert holdout_base_seed(commit, "x", (holdout_base_seed(commit, "x", ())[0],))[1] >= 1


def test_a_test_the_answer_itself_failed_closes_no_rival():
    """Closure needs a PASSED registration of the answer: when the answer and the rival both fail
    the same runs, the data discriminated nothing between them."""
    case = _case("control", "held_out-thermo.ambient-00")
    rescorer = _rescorer(case)
    experiments = ev13.all_experiments(case.full_catalog)
    claim = next(h for h in rescorer.catalog.values() if h.class_ids == ("thermo.ambient",))
    ledger = EvaluatorLedger()
    x = experiments["baseline"]
    for k in range(2):
        ledger.record_measurement("baseline", k, tuple((e.entry_id, 0.0) for e in x.entries))
    ledger.register(claim.fingerprint, "gas_cell_reference", 1)
    y = experiments["gas_cell_reference"]
    ledger.record_measurement(
        "gas_cell_reference", 0, tuple((e.entry_id, 40 * e.sigma) for e in y.entries)
    )
    events = ledger.events()
    tests = rescore(rescorer, events)
    assert tests[0].complete and not tests[0].passed
    assert (
        closed_by(rescorer, events, tests, claim.fingerprint, NULL_HYPOTHESIS.fingerprint) is None
    )
    # the same runs close "no effect" as soon as they count as a passed test of the answer
    passed = [dataclasses.replace(tests[0], passed=True)]
    assert closed_by(rescorer, events, passed, claim.fingerprint, NULL_HYPOTHESIS.fingerprint) == (
        tests[0].register_index
    )
