"""Reproductions BEFORE the v1.4 fix: v1.3's residual SUPPORTED errors and their two root causes.

Committed before any v1.4 code, on the unchanged v1.3 package. The worlds are the ones where v1.3's
frozen run (round 4) endorsed a wrong answer at SUPPORTED; their seed ranges (held-out/control base
3_218_044_000, benchmark base 3_729_592_000) were seen in round 4 and are DEVELOPMENT data now.
Each test asserts the v1.3 behaviour (it keeps passing: v1.3 is frozen); the v1.4 counterparts are
in `test_discovery_safety_v14.py`.

    root cause 1  v1.3 closes a rival when a passed registration of the answer SEPARATED their
                  predictions (>= tau_risky). Separation is not discrimination: the rival's own
                  evaluator prediction passes the same runs (it often fits them better)
    root cause 2  v1.3's open-rival check ignores the grammar: a grammar shape adequate on all the
                  data and predicting >= 3 combined SD away from the answer on an available,
                  never-run experiment is no obstacle to SUPPORTED

ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds.
"""

from __future__ import annotations

import importlib.util
from functools import cache
from types import ModuleType
from typing import Any

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.loop import hypothesis_universe
from lab_brain.discovery.model import NULL_HYPOTHESIS
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v12.gate import grammar_shapes
from lab_brain.discovery_safety.v12.grammar import prediction
from lab_brain.discovery_safety.v12.ledger import PredictionLedger
from lab_brain.discovery_safety.v13 import evaluation as ev
from lab_brain.discovery_safety.v13.ledger import (
    EvaluatorLaboratory,
    EvaluatorLedger,
    observations_before,
)
from lab_brain.discovery_safety.v13.model import EVALUATOR_RULE
from lab_brain.discovery_safety.v13.rule import Rescorer, rescore, separation, verdict
from lab_brain.spec import repo_root

SCRIPT = repo_root() / "scripts" / "discovery_safety_v13_eval.py"
HELD_OUT_V13 = 3_218_044_000
BENCHMARK_V13 = 3_729_592_000

#: (setting, world, cap, claimed, v1.3's category in its frozen run)
CASES = (
    ("held_out", "held_out-leakage.substrate-06", 24, "hyp:scatter.sidewall", ev.FORCE_FIT),
    ("held_out", "held_out-geometry.width_wide-03", 8, "hyp:geometry.thickness", ev.WRONG_CLAIM),
    (
        "benchmark",
        "noise_glitch-06",
        8,
        "hyp:chain.laser_drift+geometry.gap_small",
        ev.WRONG_CLAIM,
    ),
    ("benchmark", "noise_only_null-04", 8, "hyp:geometry.gap_large", ev.WRONG_CLAIM),
)


@cache
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("discovery_safety_v13_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(setting: str, world_id: str) -> Any:
    s = script()
    if setting == "benchmark":
        sc = s.ring_scenario(15, base_seed=BENCHMARK_V13)
        world = next(w for w in sc.worlds if w.world_id == world_id)
        return s.benchmark_case(sc, world, benchmark.Oracles(sc.catalog, DISCOVERY))
    worlds = held_out.held_out_worlds(
        s.ring_catalog(), seeds_per_class=10, base_seed=HELD_OUT_V13, protocol=DISCOVERY
    )
    return s.held_out_case(next(w for w in worlds if w.spec.world_id == world_id), True)


@cache
def _b6(setting: str, world_id: str, cap: int) -> tuple[Any, Any, Any, Any]:
    """B6 (v1.3, unchanged) in process on one world: (case, answer, ledger events, rescorer)."""
    s = script()
    case = _case(setting, world_id)
    experiments = ev.all_experiments(case.full_catalog)
    ledger = EvaluatorLedger()
    lab = EvaluatorLaboratory(
        blind_laboratory(
            case.lab_factory(),
            experiments=experiments,
            available=tuple(e.experiment_id for e in case.engine_oracle.available),
            meter=CostMeter({k: e.cost for k, e in experiments.items()}, cap),
        ),
        ledger,
        PredictionLedger(),
    )
    answer = s._handle({**case.request, "arm": "B6", "budget": cap}, lab)
    rescorer = Rescorer(
        distinct_forward_models(hypothesis_universe(case.engine_catalog)),
        grammar_shapes(s.GRAMMAR),
        experiments,
        EVALUATOR_RULE,
        case.engine_oracle.distinguishable,
    )
    return case, answer, ledger.events(), rescorer


def _claim(rescorer: Rescorer, claimed: str) -> Any:
    return next(h for h in rescorer.catalog.values() if h.hypothesis_id == claimed)


@pytest.mark.parametrize(("setting", "world_id", "cap", "claimed", "category"), CASES)
def test_v13_endorses_a_wrong_answer_at_supported(setting, world_id, cap, claimed, category):
    case, answer, events, rescorer = _b6(setting, world_id, cap)
    assert answer.claim == (claimed,)
    h = _claim(rescorer, claimed)
    assert verdict(rescorer, events, rescore(rescorer, events), h.fingerprint).supported
    assert case.truth is not None and case.truth.hypothesis_id != claimed
    s = script()
    record = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE, ("B6",)).run(
        case, (cap,)
    )[0]
    assert (record.level, record.category) == (ev.SUPPORTED, category)


@pytest.mark.parametrize(
    ("setting", "world_id", "cap", "claimed", "rival"),
    [
        ("held_out", "held_out-leakage.substrate-06", 24, "hyp:scatter.sidewall",
         "hyp:chain.polarization_drift"),
        ("benchmark", "noise_glitch-06", 8, "hyp:chain.laser_drift+geometry.gap_small",
         "hyp:chain.laser_drift"),
        ("benchmark", "noise_only_null-04", 8, "hyp:geometry.gap_large", "hyp:null"),
    ],
)  # fmt: skip
def test_root_cause_1_a_rival_counted_as_separated_passes_the_same_runs(
    setting, world_id, cap, claimed, rival
):
    """v1.3 closed `rival` because a passed registration of the claim separated their predictions;
    the evaluator's own prediction of the rival passes those runs too (the truth is the rival's
    side, or neither), so the data never discriminated them."""
    _, _, events, rescorer = _b6(setting, world_id, cap)
    h = _claim(rescorer, claimed)
    tests = rescore(rescorer, events)
    data = observations_before(events, len(events))
    viable = {r.hypothesis_id for r in rescorer.rivals(h.fingerprint, data)}
    assert rival in viable  # still adequate on ALL the data, and a rival under v1.3's own rule
    r = NULL_HYPOTHESIS if rival == "hyp:null" else _claim(rescorer, rival)
    closing = [
        t
        for t in tests
        if t.identity == h.fingerprint and t.passed and r.fingerprint in t.separated
    ]
    assert closing  # v1.3 counts the rival as closed by separation
    for t in closing:
        experiment = rescorer.experiments[t.experiment_id]
        before = observations_before(events, t.register_index)
        theirs = rescorer.rival_prediction(h.fingerprint, r, before, experiment)
        assert theirs is not None
        passed, _, _ = rescorer.score_values(
            theirs, [dict(events[i].values) for i in t.measure_indices], experiment
        )
        assert passed  # ... yet the rival predicted the same runs within the rule
    assert r.hypothesis_id not in verdict(rescorer, events, tests, h.fingerprint).open_rivals


@pytest.mark.parametrize(
    ("world_id", "cap", "claimed"),
    [
        ("held_out-geometry.width_wide-03", 8, "hyp:geometry.thickness"),
        ("held_out-leakage.substrate-06", 24, "hyp:scatter.sidewall"),
    ],
)
def test_root_cause_2_an_adequate_grammar_alternative_is_ignored(world_id, cap, claimed):
    """A grammar shape adequate on all the data predicts >= 3 combined SD (4 runs) away from the
    claim on an available experiment; v1.3's open-rival check does not look at the grammar."""
    case, _, events, rescorer = _b6("held_out", world_id, cap)
    h = _claim(rescorer, claimed)
    data = observations_before(events, len(events))
    available = [e.experiment_id for e in case.engine_oracle.available]
    separated = []
    for fitted in rescorer.viable(data).grammar:
        for x in available:
            experiment = rescorer.experiments[x]
            mine = rescorer.predict(h.fingerprint, data, experiment)
            assert mine is not None
            if separation(mine, prediction(fitted, experiment), experiment, 4) >= 3.0:
                separated.append(fitted.shape.shape_id)
                break
    assert separated
    v = verdict(rescorer, events, rescore(rescorer, events), h.fingerprint)
    assert v.supported and not any(r.startswith("grammar") for r in v.open_rivals)


def test_root_cause_2b_no_effect_is_supported_beside_a_clear_grammar_expressible_effect():
    """Found on development seeds while building v1.4 (base 8_000_000, family removed): on
    `geometry.gap_small-01` at cap 12 B6 endorses "no effect" at SUPPORTED although kappa reads
    1.3, 1.1, 2.7 (sigma 1) and adequate grammar shapes fit that shift >= 3 combined SD from zero;
    v1.3 holds "no effect" only against catalog classes at their smallest declared effects, and
    the arm's catalog lacks the coupling family."""
    s = script()
    worlds = held_out.held_out_worlds(
        s.ring_catalog(), seeds_per_class=3, base_seed=8_000_000, protocol=DISCOVERY
    )
    case = s.held_out_case(
        next(w for w in worlds if w.spec.world_id == "held_out-geometry.gap_small-01"), True
    )
    record = ev.Evaluator(s._execute_in_process, s.GRAMMAR, EVALUATOR_RULE, ("B6",)).run(
        case, (12,)
    )[0]
    assert record.claim == ("hyp:null",)
    assert (record.level, record.category) == (ev.SUPPORTED, ev.FORCE_FIT)
