"""Safety v1.3: the evaluator-controlled boundary, the noise-only fix, candidate.5 scoring, comparisons.

Development seeds only (bases 1, 7_000_000 and 8_000_000, declared in `PLAN.development`); the
held-out evaluation is in the frozen evidence and its own test. Every world is synthetic and written
by the engine's author lineage. ENGINEERING EVIDENCE ONLY.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from functools import cache
from types import ModuleType
from typing import Any

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.loop import hypothesis_universe
from lab_brain.discovery.model import NULL_HYPOTHESIS, Budget, Observation
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.evaluation import classify
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v12.gate import grammar_shapes, hypothesis_prediction
from lab_brain.discovery_safety.v12.ledger import (
    PredictionLedger,
    PredictionRule,
    prediction_payload,
)
from lab_brain.discovery_safety.v12.model import PLAN as PLAN_V12
from lab_brain.discovery_safety.v12.model import SeedRange
from lab_brain.discovery_safety.v13 import evaluation as ev
from lab_brain.discovery_safety.v13.ledger import (
    MEASURE,
    REGISTER,
    EvaluatorLaboratory,
    EvaluatorLedger,
    observations_before,
    verify_chain,
)
from lab_brain.discovery_safety.v13.model import (
    EVALUATOR_RULE,
    PLAN,
    ArmAnswer,
    EvaluationPlanV13,
)
from lab_brain.discovery_safety.v13.rule import Rescorer, rescore, verdict
from lab_brain.spec import repo_root

SCRIPT = repo_root() / "scripts" / "discovery_safety_v13_eval.py"
REPRO = repo_root() / "scripts" / "discovery_safety_v13_reproduce_before.py"


def _load(path: Any, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def script() -> ModuleType:
    return _load(SCRIPT, "discovery_safety_v13_eval")


@cache
def repro() -> ModuleType:
    return _load(REPRO, "discovery_safety_v13_reproduce_before")


@cache
def held_out_worlds(base: int, per: int) -> dict[str, Any]:
    s = script()
    return {
        w.spec.world_id: w
        for w in held_out.held_out_worlds(
            s.ring_catalog(), seeds_per_class=per, base_seed=base, protocol=DISCOVERY
        )
    }


@cache
def scenario(per: int) -> Any:
    return script().ring_scenario(per, base_seed=1)


def _rescorer(catalog: Any, oracle: Any) -> Rescorer:
    return Rescorer(
        distinct_forward_models(hypothesis_universe(catalog)),
        grammar_shapes(script().GRAMMAR),
        ev.all_experiments(catalog),
        EVALUATOR_RULE,
        oracle.distinguishable,
    )


def _held_out_records(world_id: str, removed: bool, budgets: tuple[int, ...], arms=ev.ARM_IDS):  # type: ignore[no-untyped-def]
    s = script()
    case = s.held_out_case(held_out_worlds(7_000_000, 15)[world_id], removed)
    evaluator = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE, arms)
    return {(r.arm, r.budget): r for r in evaluator.run(case, budgets)}


@cache
def _benchmark_records(world_id: str, budgets: tuple[int, ...], arms: tuple[str, ...]):  # type: ignore[no-untyped-def]
    s = script()
    sc = scenario(15)
    world = next(w for w in sc.worlds if w.world_id == world_id)
    case = s.benchmark_case(sc, world, benchmark.Oracles(sc.catalog, DISCOVERY))
    evaluator = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE, arms)
    return {(r.arm, r.budget): r for r in evaluator.run(case, budgets)}


# -- A. the reproduced attacks no longer decide SUPPORTED -------------------------------------


def test_r1_the_force_fit_registered_through_v13_fails_on_the_evaluators_own_prediction():
    """The R1 world: the engine's force-fit, then the v1.2 payload with an inflated SD and a far
    alternative. The v1.3 laboratory keeps only its identity and experiment; the evaluator refits
    the claim to the earlier data with its own noise model: the test fails, nothing is SUPPORTED."""
    r = repro()
    catalog, world, engine_catalog, oracle, experiments, meter, _, _, judge = r._setup(
        r.FORCE_FIT_WORLD, 24
    )
    ledger = EvaluatorLedger()
    v12 = PredictionLedger()
    lab = EvaluatorLaboratory(
        blind_laboratory(
            r.SyntheticWorld(world.spec, catalog, r.MOTIVATING_EXPERIMENT),
            experiments=experiments,
            available=tuple(e.experiment_id for e in catalog.experiments),
            meter=meter,
        ),
        ledger,
        v12,
    )
    result = r.investigate(
        arm="ADV",
        catalog=engine_catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(20),
        lab=lab,
    )
    claim = result.record(result.claim[0]).hypothesis
    x = experiments["polarization_controlled"]
    data = observations_before(ledger.events(), len(ledger.events()))
    mean, sd = hypothesis_prediction(claim, data, experiments, x)
    lab.register(
        prediction_payload(
            subject=claim.hypothesis_id,
            fingerprint=claim.fingerprint,
            experiment_id=x.experiment_id,
            replicate=0,
            predicted=mean,
            sd=dict.fromkeys(sd, 1000000.0),
            alternatives=[("none", dict.fromkeys(mean, 1e7), dict.fromkeys(mean, 0.0))],
            rule=PredictionRule(alpha=0.0, z_max=1e9, tau_risky=0.0),
            purpose="R1",
        )
    )
    lab.measure(x.experiment_id, replicate=0, session=99)
    events = ledger.events()
    verify_chain(events)
    rescorer = _rescorer(engine_catalog, oracle)
    tests = rescore(rescorer, events)
    assert len(tests) == 1 and tests[0].complete and not tests[0].passed
    assert not verdict(rescorer, events, tests, claim.fingerprint).supported
    answer = ArmAnswer("ADV", result.outcome.value, "CATALOG_CLAIM", (claim.hypothesis_id,))
    case = replace(script().held_out_case(held_out_worlds(7_000_000, 15)[r.FORCE_FIT_WORLD], True))
    by_id = {h.hypothesis_id: h for h in hypothesis_universe(engine_catalog)}
    out = ev.judge_answer(case, judge, rescorer, events, answer, by_id, v12, EVALUATOR_RULE)
    assert (out["category"], out["level"]) == (ev.UNSUPPORTED_CLAIM, ev.PROPOSAL)


def test_r2_no_effect_is_an_alternative_only_while_the_earlier_data_allow_it():
    cat = script().ring_catalog()
    oracle = script().SeparationOracle(
        cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY
    )
    rescorer = _rescorer(cat, oracle)
    experiments = ev.all_experiments(cat)
    claim = next(h for h in rescorer.catalog.values() if h.class_ids == ("thermo.self_heating",))
    x = experiments["gas_cell_reference"]
    quiet = [
        Observation(f"q{i}", e, 0, i + 1, tuple((n.entry_id, 0.0) for n in experiments[e].entries))
        for i, e in enumerate(("baseline", "power_sweep"))
    ]
    loud = [
        Observation(
            f"l{i}", e, 0, i + 1, tuple((n.entry_id, 50 * n.sigma) for n in experiments[e].entries)
        )
        for i, e in enumerate(("baseline", "power_sweep"))
    ]
    names_quiet = {n for n, _ in rescorer.alternatives(claim.fingerprint, quiet, x)}
    names_loud = {n for n, _ in rescorer.alternatives(claim.fingerprint, loud, x)}
    assert NULL_HYPOTHESIS.fingerprint in names_quiet
    assert NULL_HYPOTHESIS.fingerprint not in names_loud


def test_r3_the_rule_is_the_evaluators_and_a_payload_rule_is_discarded():
    cat = script().ring_catalog()
    experiments = ev.all_experiments(cat)
    ledger = EvaluatorLedger()
    lab = EvaluatorLaboratory(_FixedLab(experiments), ledger)
    zero = {e.entry_id: 0.0 for e in experiments["cutback"].entries}
    lab.register(
        prediction_payload(
            subject="null",
            fingerprint=NULL_HYPOTHESIS.fingerprint,
            experiment_id="cutback",
            replicate=0,
            predicted=zero,
            sd=zero,
            alternatives=[("none", zero, zero)],
            rule=PredictionRule(alpha=0.0, z_max=1e9, tau_risky=0.0),
            purpose="R3",
        )
    )
    lab.measure("cutback", replicate=0, session=1)
    register = next(e for e in ledger.events() if e.kind == REGISTER)
    assert set(register.body()) >= {"identity", "experiment_id", "runs"}
    assert "rule" not in register.body() and "sd" not in register.body()
    oracle = script().SeparationOracle(
        cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY
    )
    rescorer = _rescorer(cat, oracle)
    t = rescore(rescorer, ledger.events())[0]
    # the evaluator's own riskiness (tau_risky 3 against the catalog's smallest declared effects),
    # not the payload's tau_risky = 0
    assert t.passed
    assert t.risk == rescorer.risk(NULL_HYPOTHESIS.fingerprint, [], experiments["cutback"], 1)[0]
    assert t.risky == (t.risk >= EVALUATOR_RULE.tau_risky)


class _FixedLab:
    """A laboratory returning zeros (tests only)."""

    def __init__(self, experiments: dict[str, Any]) -> None:
        self.experiments = experiments

    def motivating(self) -> tuple[str, tuple[tuple[str, float], ...]]:
        return "baseline", tuple((e.entry_id, 0.0) for e in self.experiments["baseline"].entries)

    def measure(self, experiment_id: str, *, replicate: int, session: int):  # type: ignore[no-untyped-def]
        return tuple((e.entry_id, 0.0) for e in self.experiments[experiment_id].entries)


def test_r4_the_evaluator_predicts_the_identity_itself_whatever_label_the_arm_used():
    """There are no predicted values to mislabel: the evaluator's prediction for an identity is its
    own refit of THAT identity's forward model."""
    cat = script().ring_catalog()
    experiments = ev.all_experiments(cat)
    oracle = script().SeparationOracle(
        cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY
    )
    rescorer = _rescorer(cat, oracle)
    b = next(h for h in rescorer.catalog.values() if h.class_ids == ("scatter.sidewall",))
    x = experiments["baseline"]
    assert rescorer.predict(b.fingerprint, [], x) == hypothesis_prediction(b, [], experiments, x)
    assert rescorer.predict("sha256:" + "f" * 64, [], x) is None
    ledger = EvaluatorLedger()
    ledger.register("sha256:" + "f" * 64, "baseline", 1)
    ledger.record_measurement("baseline", 0, ((x.entries[0].entry_id, 0.0),))
    assert rescore(rescorer, ledger.events())[0].void == "UNKNOWN_IDENTITY"


def test_r5_a_new_mechanism_is_rebuilt_by_the_evaluator_from_its_identity():
    """The arm hands over only the grammar shape's fingerprint; the evaluator refits that shape to
    all the recorded data and applies the declared band. An identity outside the grammar is not
    an answer the evaluator can support."""
    cat = script().ring_catalog()
    oracle = script().SeparationOracle(
        cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY
    )
    rescorer = _rescorer(cat, oracle)
    ledger = EvaluatorLedger()
    lab = EvaluatorLaboratory(_FixedLab(ev.all_experiments(cat)), ledger)
    for e in ("baseline", "power_sweep", "tec_stabilized"):
        lab.measure(e, replicate=0, session=1)
    shape = next(iter(rescorer.shapes.values()))
    rebuilt = rescorer.answer_hypothesis(shape.fingerprint, ledger.events(), "a")
    assert rebuilt is None or all(
        c.sensitivity == t for c, t in zip(rebuilt.components, shape.tables, strict=True)
    )
    assert rescorer.answer_hypothesis("sha256:" + "0" * 64, ledger.events(), "a") is None


# -- B. the ledger and the boundary -----------------------------------------------------------


def test_the_ledger_is_hash_chained_and_refuses_any_alteration():
    ledger = EvaluatorLedger()
    ledger.record_measurement("cutback", 0, (("loss_straight", 1.0),))
    ledger.register(NULL_HYPOTHESIS.fingerprint, "cutback", 2, "")
    ledger.record_measurement("cutback", 1, (("loss_straight", 1.5),))
    events = list(ledger.events())
    verify_chain(events)
    altered = [*events]
    altered[0] = replace(events[0], values=(("loss_straight", 1.1),))
    with pytest.raises(ValueError):
        verify_chain(altered)
    with pytest.raises(ValueError):
        verify_chain([events[0], events[2]])
    forged = [*events]
    forged[1] = replace(events[1], data_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError):
        verify_chain(forged)
    assert isinstance(ledger.events(), tuple)
    assert not hasattr(EvaluatorLaboratory, "events")


def test_a_multi_run_test_is_scored_on_the_mean_of_the_next_runs_and_incomplete_before():
    cat = script().ring_catalog()
    oracle = script().SeparationOracle(
        cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY
    )
    rescorer = _rescorer(cat, oracle)
    entries = ev.all_experiments(cat)["cutback"].entries
    ledger = EvaluatorLedger()
    ledger.register(NULL_HYPOTHESIS.fingerprint, "cutback", 2)
    ledger.record_measurement("cutback", 0, tuple((e.entry_id, 3.0 * e.sigma) for e in entries))
    assert rescore(rescorer, ledger.events())[0].void == "INCOMPLETE"
    ledger.record_measurement("cutback", 1, tuple((e.entry_id, -3.0 * e.sigma) for e in entries))
    t = rescore(rescorer, ledger.events())[0]
    assert t.complete and t.passed and t.max_abs_z == pytest.approx(0.0, abs=1e-9)
    assert t.measure_indices == (1, 2)


def test_every_arm_gives_the_same_answer_across_the_process_boundary():
    s = script()
    world = held_out_worlds(7_000_000, 15)["held_out-thermo.ambient-00"]
    case = s.held_out_case(world, True)
    inside = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE).run(case, (8,))
    outside = ev.Evaluator(s._execute_boundary, s.GRAMMAR, EVALUATOR_RULE).run(case, (8,))
    assert [(r.arm, r.category, r.level, r.spent, r.chain_head) for r in inside] == [
        (r.arm, r.category, r.level, r.spent, r.chain_head) for r in outside
    ]


# -- C. the noise-only root cause and its fix (development benchmark worlds, base 1) ---------


def test_v12_loses_a_noise_only_world_to_unexcludable_rivals_and_v13_supports_no_effect():
    rows = _benchmark_records("noise_only_null-01", (48,), ("B5", "B6"))
    b5, b6 = rows[("B5", 48)], rows[("B6", 48)]
    assert b5.answer == "NONE" and b5.reason == "ADEQUACY_UNVERIFIED"
    assert b5.spent < 48 - 10  # budget was left that v1.2 could not use
    assert b6.claim == ("hyp:null",) and (b6.category, b6.level) == (ev.EXACT, ev.SUPPORTED)


# -- D. candidate.5 scoring --------------------------------------------------------------------


def test_endorsed_but_unregistered_answers_are_unsupported_claims_and_their_matches_beside():
    rows = _held_out_records("held_out-geometry.thickness-01", False, (24,), ("B2", "B4", "B6"))
    for arm in ("B2", "B4"):
        r = rows[(arm, 24)]
        assert r.answer == "CATALOG_CLAIM" and r.asserted
        assert (r.category, r.level) == (ev.UNSUPPORTED_CLAIM, ev.PROPOSAL)
        assert r.proposal_hit and r.own_correct
    table = ev.table([rows[("B4", 24)]])
    assert table["asserted"] == 1 and table["supported"] == 0
    assert table["unsupported_claim"] == 1 and table["errors"] == 1 and table["proposal_only"] == 0
    assert rows[("B6", 24)].level == ev.SUPPORTED


def test_proposal_only_needs_the_arms_own_proposal_label_and_no_action():
    base = ev.RunRecord(
        "x", "w", "k", "B6", 8, 1, "o", "CATALOG_CLAIM", ("hyp:a",), ev.PROPOSAL_ONLY, ev.PROPOSAL,
        True, False, False, False, "NO_CLAIM", "", False, False, (), "", 0, 0, 0, 0, False, "", "",
    )  # fmt: skip
    with pytest.raises(AssertionError):
        ev.table([base])
    ok = replace(base, asserted=False)
    assert ev.table([ok])["proposal_only"] == 1 and ev.table([ok])["errors"] == 0


def test_v11s_legacy_category_is_reproduced_on_the_evaluators_side():
    s = script()
    world = held_out_worlds(7_000_000, 15)["held_out-geometry.thickness-01"]
    cat = s.ring_catalog()
    oracle = s.SeparationOracle(cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY)
    experiments = ev.all_experiments(cat)
    lab = blind_laboratory(
        s.SyntheticWorld(world.spec, cat, s.MOTIVATING_EXPERIMENT),
        experiments=experiments,
        meter=CostMeter({k: e.cost for k, e in experiments.items()}, 24),
    )
    run = safe_investigate_v11(
        arm="B4", catalog=cat, oracle=oracle, protocol=DISCOVERY, budget=Budget(24), lab=lab
    )
    scorer = s.Scorer(cat)
    claimed = frozenset(run.result.record(i).hypothesis.fingerprint for i in run.result.claim)
    assert ev.own_category_v11(
        scorer, world.spec, run.result.outcome.value, claimed, oracle
    ) == classify(scorer, world.spec, run.result, oracle)


def test_matched_comparison_reports_cost_unmatched_cells_and_is_deterministic():
    rows = list(_held_out_records("held_out-thermo.ambient-00", True, (8, 24)).values())
    a = ev.matched_comparisons(rows, PLAN, "t")
    b = ev.matched_comparisons(rows, PLAN, "t")
    assert a == b
    assert all(p["basis"] in ("COST_MATCHED", "COST_UNMATCHED") for p in a["pairs"])
    assert json.loads(json.dumps(a)) == a


# -- E. plan ---------------------------------------------------------------------------------


def test_the_plan_draws_fresh_ranges_away_from_every_earlier_one():
    used = {*PLAN_V12.seeds_used_before, *(r.base_seed for r in PLAN_V12.held_out)}
    used.add(PLAN_V12.benchmark_worlds.base_seed)
    assert used <= set(PLAN.seeds_used_before)
    for r in (*PLAN.held_out, PLAN.benchmark_worlds):
        assert all(abs(r.base_seed - u) >= 20_000 for u in used)
    with pytest.raises(ValueError):
        EvaluationPlanV13(
            held_out=(SeedRange("x", PLAN_V12.held_out[0].base_seed + 7, 15, "HELD_OUT_FOR_V1_3"),)
        )


def test_the_measurements_in_a_ledger_are_the_laboratorys_own():
    cat = script().ring_catalog()
    ledger = EvaluatorLedger()
    lab = EvaluatorLaboratory(_FixedLab(ev.all_experiments(cat)), ledger)
    lab.motivating()
    lab.measure("cutback", replicate=5, session=1)
    kinds = [e.kind for e in ledger.events()]
    assert kinds == ["MOTIVATING", MEASURE]
    assert ledger.events()[1].replicate == 5 and ledger.events()[1].count == 0
