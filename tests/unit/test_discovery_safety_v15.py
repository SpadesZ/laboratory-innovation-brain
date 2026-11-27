"""Safety v1.5: arm B8 (rival-targeted experiment choice) under the unchanged v1.4 evaluator rule.

Adversarial tests try to make B8 (or an arm built like it) obtain a false SUPPORTED: a rival closed
without a failed prediction, separation without prediction, evidence from outside the evaluator's
boundary, a lying arm, a grammar rival omitted. Development seeds only (base 8_000_000 and the
v1.3 ranges; every range seen before is development data). ENGINEERING EVIDENCE ONLY.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import math
import random
from functools import cache
from types import ModuleType
from typing import Any

import pytest

from lab_brain.discovery.loop import hypothesis_universe
from lab_brain.discovery.model import NULL_HYPOTHESIS
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v12.gate import grammar_shapes
from lab_brain.discovery_safety.v13 import evaluation as ev13
from lab_brain.discovery_safety.v13.ledger import (
    MEASURE,
    REGISTER,
    EvaluatorLaboratory,
    EvaluatorLedger,
    observations_before,
)
from lab_brain.discovery_safety.v13.model import ArmAnswer
from lab_brain.discovery_safety.v13.rule import rescore, separation
from lab_brain.discovery_safety.v14 import gate as gate14
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14, EvaluatorRuleV14
from lab_brain.discovery_safety.v14.rule import RescorerV14, closed_by, verdict_v14
from lab_brain.discovery_safety.v15 import diagnose as dg
from lab_brain.discovery_safety.v15 import evaluation as ev
from lab_brain.discovery_safety.v15 import gate as gate15
from lab_brain.discovery_safety.v15.model import (
    HOLDOUT_DOMAIN,
    PLAN,
    SAFETY_V15,
    holdout_base_seed,
)
from lab_brain.spec import repo_root

SCRIPT = repo_root() / "scripts" / "discovery_safety_v15_eval.py"
DEV = 8_000_000


@cache
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("discovery_safety_v15_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def _case(world_id: str, removed: bool = False) -> Any:
    s = script()
    worlds = held_out.held_out_worlds(
        s.ring_catalog(), seeds_per_class=1, base_seed=DEV, protocol=DISCOVERY
    )
    return s.held_out_case(next(w for w in worlds if w.spec.world_id == world_id), removed)


def _rescorer(case: Any, rule: EvaluatorRuleV14 = EVALUATOR_RULE_V14) -> RescorerV14:
    return RescorerV14(
        distinct_forward_models(hypothesis_universe(case.engine_catalog)),
        grammar_shapes(script().GRAMMAR),
        ev13.all_experiments(case.full_catalog),
        rule,
        case.engine_oracle.distinguishable,
        tuple(e.experiment_id for e in case.engine_oracle.available),
    )


def _run(case: Any, arm: str, cap: int, handle: Any = None) -> tuple[ArmAnswer, list[Any]]:
    s = script()
    experiments = ev13.all_experiments(case.full_catalog)
    ledger = EvaluatorLedger()
    lab = EvaluatorLaboratory(
        blind_laboratory(
            case.lab_factory(),
            experiments=experiments,
            available=tuple(e.experiment_id for e in case.engine_oracle.available),
            meter=CostMeter({k: e.cost for k, e in experiments.items()}, cap),
        ),
        ledger,
    )
    answer = (handle or s._handle)({**case.request, "arm": arm, "budget": cap}, lab)
    return answer, ledger.events()


def test_the_script_refuses_a_lab_brain_imported_from_another_checkout(monkeypatch):
    s = script()
    s.assert_own_checkout()  # this checkout: fine
    monkeypatch.setattr(s.lab_brain, "__file__", "/elsewhere/src/lab_brain/__init__.py")
    with pytest.raises(SystemExit):
        s.assert_own_checkout()


# -- A. B8 changes the arm's experiment choice only -------------------------------------------


def test_b8_decides_support_and_rivals_exactly_as_b7_and_only_chooses_tests_differently():
    g15, g14 = gate15._GateV15, gate14._GateV14
    for name in ("self_supported", "open_rivals", "_rival_prediction", "_close", "register"):
        assert getattr(g15, name) is getattr(g14, name), name
    own = {n for n in vars(g15) if not n.startswith("__")}
    assert own == {"_targeting", "targeted_option", "rival_test", "probe_fixpoint"}
    # the evaluation scores B8 with the v1.4 rule, unchanged
    assert ev.Evaluator(lambda r, lab: None, None).rule is EVALUATOR_RULE_V14  # type: ignore[arg-type,return-value]


def test_b8_registers_identities_only_and_gives_the_same_answer_across_the_process_boundary():
    s = script()
    case = _case("held_out-fcd.static-00")
    _, events = _run(case, "B8", 12)
    for e in events:
        if e.kind == REGISTER:
            assert {"predicted", "sd", "alternatives", "rule"}.isdisjoint(e.body())
    inside = ev.Evaluator(s._execute_in_process, s.GRAMMAR, arms=("B8",)).run(case, (12,))
    outside = ev.Evaluator(s._execute_boundary, s.GRAMMAR, arms=("B8",)).run(case, (12,))
    assert [(r.category, r.level, r.spent, r.chain_head, r.digest) for r in inside] == [
        (r.category, r.level, r.spent, r.chain_head, r.digest) for r in outside
    ]


def test_every_rival_b8_closes_is_closed_by_its_own_failed_prediction():
    """Re-derive every closure in B8 ledgers independently: the rival's evaluator prediction,
    refitted to the data before the passed registration, fails the pass test on its runs (or the
    rival's own registration failed). Separation alone never appears as a closure."""
    for world, removed, cap in (
        ("held_out-geometry.width_narrow-00", False, 8),
        ("held_out-thermo.ambient-00", True, 8),
    ):
        case = _case(world, removed)
        _, events = _run(case, "B8", cap)
        rescorer = _rescorer(case)
        tests = rescore(rescorer, events)
        claims = {t.identity for t in tests if t.complete and t.passed}
        data = observations_before(events, len(events))
        checked = 0
        for identity in claims:
            for rival in rescorer.rivals_v14(identity, data):
                index = closed_by(rescorer, events, tests, identity, rival.identity)
                if index is None:
                    continue
                t = next(t for t in tests if t.register_index == index)
                if t.identity == rival.identity:
                    assert t.complete and not t.passed
                    continue
                x = rescorer.experiments[t.experiment_id]
                theirs = rescorer.predict_rival(
                    identity, rival.identity, observations_before(events, index), x
                )
                assert theirs is not None
                observed = [dict(events[i].values) for i in t.measure_indices]
                passed, _, _ = rescorer.score_values(theirs, observed, x)
                assert t.passed and not passed
                checked += 1
        assert checked > 0, world


# -- B. adversarial ledgers: the evaluator's boundary holds for any arm ------------------------


def _ambient_ledger() -> tuple[Any, RescorerV14, EvaluatorLedger, Any]:
    case = _case("held_out-thermo.ambient-00")
    rescorer = _rescorer(case)
    lab = case.lab_factory()
    ledger = EvaluatorLedger()
    for i, x in enumerate(("baseline", "power_sweep", "tec_stabilized", "baseline")):
        ledger.record_measurement(x, i, lab.measure(x, replicate=i, session=1))
    claim = next(h for h in rescorer.catalog.values() if h.hypothesis_id == "hyp:thermo.ambient")
    return case, rescorer, ledger, claim


def _midpoint_attack(rescorer: RescorerV14, ledger: EvaluatorLedger, claim: Any) -> Any:
    """Register the claim (and a rival) on an experiment that SEPARATES them by 3.5-5 combined SD,
    then record a reading exactly halfway: both predictions pass; nothing was discriminated."""
    data = observations_before(ledger.events(), len(ledger.events()))
    for rival in rescorer.rivals_v14(claim.fingerprint, data):
        for x in rescorer.available:
            e = rescorer.experiments[x]
            a = rescorer.predict(claim.fingerprint, data, e)
            b = rescorer.predict_rival(claim.fingerprint, rival.identity, data, e)
            if a is None or b is None or not 3.5 < separation(a, b, e, 1) < 5.0:
                continue
            ledger.register(claim.fingerprint, x, 1)
            ledger.register(rival.identity, x, 1)
            mid = tuple((n.entry_id, (a[0][n.entry_id] + b[0][n.entry_id]) / 2) for n in e.entries)
            ledger.record_measurement(x, 99, mid)
            return rival
    raise AssertionError("no separating option found")  # pragma: no cover


def test_separation_without_a_failed_prediction_closes_nothing():
    _, rescorer, ledger, claim = _ambient_ledger()
    rival = _midpoint_attack(rescorer, ledger, claim)
    events = ledger.events()
    tests = rescore(rescorer, events)
    assert all(t.complete and t.passed and t.risky for t in tests)
    assert closed_by(rescorer, events, tests, claim.fingerprint, rival.identity) is None
    v = verdict_v14(rescorer, events, tests, claim.fingerprint)
    assert rival.label in v.open_rivals and not v.supported


def test_a_rival_whose_own_registration_passed_is_not_closed_by_registering_it():
    """Registering a rival is no closure: only its FAILED registration closes it."""
    _, rescorer, ledger, claim = _ambient_ledger()
    rival = _midpoint_attack(rescorer, ledger, claim)
    events = ledger.events()
    tests = rescore(rescorer, events)
    own = [t for t in tests if t.identity == rival.identity]
    assert own and all(t.passed for t in own)
    assert closed_by(rescorer, events, tests, claim.fingerprint, rival.identity) is None


def test_arm_declared_digests_and_incomplete_or_oversized_registrations_support_nothing():
    _, rescorer, ledger, claim = _ambient_ledger()
    x = "gas_cell_reference"
    ledger.register(claim.fingerprint, x, 1, "sha256:" + "f" * 64)  # a false declared digest
    ledger.register(claim.fingerprint, "cutback", 5)  # more runs than the rule allows
    ledger.register(claim.fingerprint, "width_array", 2)  # never measured: incomplete
    lab = _case("held_out-thermo.ambient-00").lab_factory()
    ledger.record_measurement(x, 0, lab.measure(x, replicate=0, session=1))
    for k in range(5):
        ledger.record_measurement("cutback", k, lab.measure("cutback", replicate=k, session=1))
    events = ledger.events()
    tests = rescore(rescorer, events)
    by_x = {t.experiment_id: t for t in tests}
    assert by_x[x].declared_digest_matches is False  # recorded, never relied on
    assert by_x["cutback"].void == "RUNS_OUT_OF_RANGE" and not by_x["cutback"].complete
    assert by_x["width_array"].void == "INCOMPLETE" and not by_x["width_array"].complete


def test_the_arm_cannot_write_a_measurement_or_read_the_ledger():
    lab = EvaluatorLaboratory(_case("held_out-thermo.ambient-00").lab_factory(), EvaluatorLedger())
    public = {n for n in dir(lab) if not n.startswith("_")}
    assert public <= {"motivating", "measure", "register", "register_identity"}


def _lying_handle(request: Any, lab: Any) -> ArmAnswer:
    """An arm that runs B8 but believes every claim is supported and every rival closed (a lying
    or broken gate): it asserts whatever it holds."""

    class Liar(gate15._GateV15):
        def self_supported(self, fingerprint: str) -> bool:
            return True

        def open_rivals(self) -> list[Any]:  # type: ignore[override]
            return []

    original = gate15._GateV15
    gate15._GateV15 = Liar  # type: ignore[misc]
    try:
        return script()._handle(request, lab)
    finally:
        gate15._GateV15 = original  # type: ignore[misc]


def test_a_lying_arm_gains_no_supported_answer_from_its_own_beliefs():
    """Family removed (the truth is not expressible): honest B8 abstains; the liar asserts a
    claim and the evaluator, re-deriving the verdict from its ledger, scores it UNSUPPORTED_CLAIM."""
    s = script()
    case = _case("held_out-geometry.gap_small-00", removed=True)
    honest = ev.Evaluator(s._execute_in_process, s.GRAMMAR, arms=("B8",)).run(case, (8,))[0]
    liar = ev.Evaluator(_lying_handle, s.GRAMMAR, arms=("B8",)).run(case, (8,))[0]
    assert honest.answer == "NONE"
    assert liar.answer != "NONE"
    assert liar.level == ev.PROPOSAL and liar.category == ev13.UNSUPPORTED_CLAIM


def test_omitting_grammar_rivals_would_support_what_the_full_rule_withholds():
    """A B8 run whose claim is held back only by grammar rivals: under a rule without grammar
    rivals it would be SUPPORTED; the evaluator's rule keeps every grammar rival."""
    case = _case("held_out-geometry.gap_small-00", removed=True)
    answer, events = _run(case, "B8", 8)
    full = _rescorer(case)
    tests = rescore(full, events)
    claims = sorted({t.identity for t in tests if t.complete and t.passed and t.risky})
    assert claims
    no_grammar = _rescorer(case, dataclasses.replace(EVALUATOR_RULE_V14, grammar_rivals=False))
    found = False
    for identity in claims:
        v = verdict_v14(full, events, tests, identity)
        w = verdict_v14(no_grammar, events, rescore(no_grammar, events), identity)
        if w.supported and not v.supported:
            assert all(label.startswith("grammar:") for label in v.open_rivals)
            found = True
    assert found
    assert answer.answer_kind == "NONE"


def _null_rival_first_handle(request: Any, lab: Any) -> ArmAnswer:
    """B8 before its development fix: rival-first targeting also for a claim of "no effect"."""

    class NullFirst(gate15._GateV15):
        def _targeting(self) -> bool:
            return True

    original = gate15._GateV15
    gate15._GateV15 = NullFirst  # type: ignore[misc]
    try:
        return script()._handle(request, lab)
    finally:
        gate15._GateV15 = original  # type: ignore[misc]


@cache
def _gap_small_01() -> Any:
    s = script()
    worlds = held_out.held_out_worlds(
        s.ring_catalog(), seeds_per_class=2, base_seed=DEV, protocol=DISCOVERY
    )
    return s.held_out_case(
        next(w for w in worlds if w.spec.world_id == "held_out-geometry.gap_small-01"), True
    )


def test_known_residual_rival_first_testing_of_no_effect_reaches_a_false_supported():
    """RESIDUAL WEAKNESS OF THE v1.4 RULE (found in development, reported, not fixed in the rule):
    an arm that tests "no effect" only where its catalog rivals (at their smallest declared
    effects) are cheap to refute reaches SUPPORTED "no effect" on a world whose true effect is
    outside the arm's catalog and below the rule's grammar threshold on what was measured. B8 as
    first drafted did this; any adversarial arm can."""
    s = script()
    out = ev.Evaluator(_null_rival_first_handle, s.GRAMMAR, arms=("B8",)).run(_gap_small_01(), (6,))
    assert out[0].claim == ("hyp:null",) and out[0].level == ev.SUPPORTED
    assert out[0].category == ev13.FORCE_FIT


def test_b8_runs_a_claim_of_no_effect_as_b7_and_does_not_endorse_it_there():
    s = script()
    rows = ev.Evaluator(s._execute_in_process, s.GRAMMAR, arms=("B7", "B8")).run(
        _gap_small_01(), (6, 8, 10)
    )
    for r in rows:
        assert r.category not in (ev13.FORCE_FIT, ev13.WRONG_CLAIM, ev13.UNSUPPORTED_CLAIM)
    by = {(r.arm, r.budget): r for r in rows}
    for cap in (6, 8, 10):
        assert by[("B8", cap)].chain_head == by[("B7", cap)].chain_head


# -- C. the expected-refutation computation ----------------------------------------------------


def test_noncentral_chi_square_matches_a_monte_carlo_estimate():
    rng = random.Random(7)
    for dof, lam in ((1, 9.0), (3, 12.0), (2, 0.5)):
        x = gate15.chi2_critical(dof, 0.01)
        mu = [math.sqrt(lam / dof)] * dof
        hits = sum(sum((m + rng.gauss(0, 1)) ** 2 for m in mu) >= x for _ in range(20000))
        assert abs(gate15.noncentral_chi2_sf(x, dof, lam) - hits / 20000) < 0.02
    assert abs(gate15.chi2_critical(1, 0.01) - 6.6349) < 1e-3


def test_a_far_rival_is_likely_refuted_and_a_close_one_is_not():
    case = _case("held_out-thermo.ambient-00")
    x = ev13.all_experiments(case.full_catalog)["baseline"]
    zero = ({e.entry_id: 0.0 for e in x.entries}, {e.entry_id: 0.0 for e in x.entries})
    far = ({e.entry_id: 6.0 * e.sigma for e in x.entries}, zero[1])
    near = ({e.entry_id: 0.5 * e.sigma for e in x.entries}, zero[1])
    assert gate15.failure_probability(zero, far, x, 1, 0.01) > 0.9
    assert gate15.failure_probability(zero, near, x, 1, 0.01) < 0.1
    # more runs refute more
    assert gate15.failure_probability(zero, near, x, 4, 0.01) > gate15.failure_probability(
        zero, near, x, 1, 0.01
    )


# -- D. the evaluator's diagnosis --------------------------------------------------------------


def test_the_diagnosis_names_causes_and_counts_only_failed_prediction_refutations():
    s = script()
    case = _case("held_out-fcd.static-00")
    rows = {
        r.arm: r
        for r in ev.Evaluator(s._execute_in_process, s.GRAMMAR, arms=("B4", "B7")).run(case, (12,))
    }
    b4, b7 = rows["B4"], rows["B7"]
    assert b4.supportable and b4.refuted == 0  # v1.1 registers nothing: no refutation
    assert b7.level != ev.SUPPORTED and b7.cause in dg.CAUSES
    assert b7.diagnosis is not None and b7.diagnosis["open_rivals"] > 0
    assert b7.runs == sum(1 for _ in range(b7.runs))
    assert set(dg.BUCKETS) == set(dg.CAUSES)


def test_a_separation_only_test_counts_as_no_refutation():
    _, rescorer, ledger, claim = _ambient_ledger()
    _midpoint_attack(rescorer, ledger, claim)
    events = ledger.events()
    tests = rescore(rescorer, events)
    ref = dg.refutations(rescorer, events, tests, lambda i: False)
    assert ref.refuted == sum(1 for t in tests if t.complete and not t.passed)
    assert ref.runs == sum(1 for e in events if e.kind == MEASURE)


# -- E. the held-out seed rule -----------------------------------------------------------------


def test_v15_seeds_use_the_v15_domain_the_full_commit_and_avoid_every_earlier_range():
    commit = "0123456789abcdef0123456789abcdef01234567"
    seeds = PLAN.held_out_seeds(commit)
    text = f"{HOLDOUT_DOMAIN}\x00held-out-worlds\x00{commit}\x000"
    expected = 3_000_000_000 + 1000 * (
        int(hashlib.sha256(text.encode()).hexdigest(), 16) % 1_000_000
    )
    assert HOLDOUT_DOMAIN == "lab-brain/discovery-safety-v1.5/held-out-seeds@1"
    assert (
        seeds["held-out-worlds"]["attempt"] > 0 or seeds["held-out-worlds"]["base_seed"] == expected
    )
    for v in seeds.values():
        assert all(abs(v["base_seed"] - u) >= 20_000 for u in PLAN.used)
    # v1.4's spent held-out ranges are development data now
    assert {3_905_077_000, 3_168_619_000} <= {r.base_seed for r in PLAN.development}
    assert PLAN.held_out_seeds(commit, 2)["held-out-worlds"]["attempt"] >= 2
    with pytest.raises(ValueError):
        holdout_base_seed("abc", "held-out-worlds", ())
    first = holdout_base_seed(commit, "x", ())[0]
    assert holdout_base_seed(commit, "x", (first,))[1] >= 1
    assert SAFETY_V15.rival_first and SAFETY_V15.targeted_selection
    assert NULL_HYPOTHESIS.is_null


def _square(t: int) -> list[int]:
    _CALLS.append(t)
    return [t * t]


_CALLS: list[int] = []


def test_an_interrupted_run_resumes_from_its_finished_worlds_without_changing_them(tmp_path):
    s = script()
    s._CHECKPOINT[0] = tmp_path / "progress"
    try:
        assert s._map(_square, [1, 2, 3], 1, "in-process", ("B8",)) == [1, 4, 9]
        _CALLS.clear()
        (tmp_path / "progress" / f"{s._task_key(_square, (('B8',), 2))}.pickle").unlink()
        assert s._map(_square, [1, 2, 3], 1, "in-process", ("B8",)) == [1, 4, 9]
        assert _CALLS == [2]  # only the missing world was recomputed
    finally:
        s._CHECKPOINT[0] = None
