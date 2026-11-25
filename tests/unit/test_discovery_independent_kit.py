"""The independent-evaluation kit: one trace per run, evaluator-held evidence, checkpoint answers,
the deficient-record rule, and adversarial arms.

Everything here runs on the PUBLIC example worlds (`benchmarks/discovery_independent/
example.hidden-worlds.json`) or on hand-made traces. No sealed material is used.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable, Generator, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import hidden_worlds as hw
from lab_brain.discovery_eval.independent import analysis
from lab_brain.discovery_eval.independent import trace as tr
from lab_brain.discovery_eval.independent.plan import PLAN, AnalysisPlan
from lab_brain.discovery_eval.independent.service import CaseService, Lost
from lab_brain.discovery_safety.independent import checkpoint as cp
from lab_brain.discovery_safety.v13.evaluation import all_experiments
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)
from lab_brain.spec import repo_root

ROOT = repo_root()
EXAMPLE = ROOT / "benchmarks" / "discovery_independent" / "example.hidden-worlds.json"


@cache
def kit() -> Any:
    spec = importlib.util.spec_from_file_location(
        "discovery_independent_kit", ROOT / "scripts" / "discovery_independent_kit.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def example() -> hw.HiddenWorldSet:
    catalog = ring_catalog()
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    worlds = hw.parse_hidden_worlds(data, catalog, DISCOVERY)
    sealed, package = hw.seal(worlds, salts=kit()._example_salt)
    return hw.reveal(sealed, hw.parse_engine_package(package, catalog), catalog, DISCOVERY)


def world(world_id: str) -> hw.HiddenWorld:
    return next(w for w in example().worlds if w.world_id == world_id)


@cache
def scorer(world_id: str) -> cp.WorldScorer:
    return cp.world_scorer(world(world_id), ring_catalog(), DISCOVERY, kit().GRAMMAR)


# -- an in-process transport for scripted arms -----------------------------------------------------

Script = Callable[[Mapping[str, Any]], Generator[dict[str, Any], dict[str, Any], None]]


def serve(
    script: Script, world_id: str = "example-01", cap: int = 48, arm: str = "X", **service: Any
) -> tuple[tr.TraceEvent, ...]:
    """Run a scripted arm (a generator that yields its messages and receives the replies)."""
    w = world(world_id)
    catalog = ring_catalog()
    svc = CaseService(
        lab=hw.HiddenWorldLab(w, catalog, MOTIVATING_EXPERIMENT),
        experiments=all_experiments(catalog),
        available=w.available(catalog),
        cap=cap,
        arm_id=arm,
        start={"case_id": str(w.case_id)},
        **service,
    )
    state: dict[str, Any] = {}

    def send(message: Mapping[str, Any]) -> None:
        if message.get("op") == "run":
            state["gen"] = script(message)
        else:
            state["reply"] = dict(message)

    def receive() -> dict[str, Any] | Lost:
        gen = state["gen"]
        try:
            if "reply" not in state:
                return next(gen)
            return gen.send(state.pop("reply"))
        except StopIteration:
            return Lost("the arm process ended")
        except RuntimeError as exc:
            return Lost(f"the arm process died: {exc}")

    events = svc.serve({"budget": cap}, send, receive)
    tr.verify_trace(events)
    return events


def answer(claim: list[str], *, arm: str = "X", spent: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "arm": arm,
        "outcome": "SURVIVING_PENDING_WARRANT_GATE" if claim else "STOPPED_UNEXPLAINED",
        "answer_kind": "CATALOG_CLAIM" if claim else "NONE",
        "claim": claim,
        "acted_on": bool(claim),
        "spent": spent,
        **extra,
    }


def truth_id(world_id: str = "example-01") -> str:
    truth = world(world_id).truth_hypothesis(ring_catalog())
    assert truth is not None
    return truth.hypothesis_id


def cheapest(world_id: str = "example-01") -> tuple[str, int]:
    catalog = ring_catalog()
    available = world(world_id).available(catalog)
    best = min(available, key=lambda e: (catalog.experiment(e).cost, e))
    return best, catalog.experiment(best).cost


def score(events: tuple[tr.TraceEvent, ...], world_id: str = "example-01") -> list[dict[str, Any]]:
    return cp.score_trace(scorer(world_id), events, PLAN.ladder, events[-1].chain)


# -- the trace -------------------------------------------------------------------------------------


def _trace() -> tuple[tr.TraceEvent, ...]:
    w = tr.TraceWriter()
    w.append(tr.START, {"case_id": "c"})
    w.append(tr.MOTIVATING, {"experiment_id": "baseline", "values": tr.encode_values([("a", 1.5)])})
    w.append(tr.DECLARE, {"answer": {"n": 1}, "charge": 0, "evidence_count": 1, "source": "x"})
    w.append(tr.MEASURE, {"experiment_id": "e", "values": [["a", "0.1"]], "charge_after": 10})
    w.append(tr.DECLARE, {"answer": {"n": 2}, "charge": 10, "evidence_count": 2, "source": "x"})
    w.append(tr.MEASURE, {"experiment_id": "e", "values": [["a", "0.2"]], "charge_after": 40})
    w.append(tr.DECLARE, {"answer": {"n": 3}, "charge": 40, "evidence_count": 3, "source": "x"})
    w.append(tr.END, {"status": tr.COMPLETED, "reason": "", "charge": 40})
    return w.events()


def test_a_trace_verifies_and_round_trips_byte_for_byte():
    events = _trace()
    tr.verify_trace(events, head=events[-1].chain)
    text = tr.dumps(events)
    assert tr.dumps(tr.loads(text)) == text
    tr.verify_trace(tr.loads(text), head=events[-1].chain)


@pytest.mark.parametrize(
    "edit",
    [
        "alter a value",
        "drop an event",
        "reorder",
        "back-date a declaration",
        "append after END",
        "rewrite and re-chain",
    ],
)
def test_any_edit_of_a_trace_after_the_fact_is_detected(edit):
    events = list(_trace())
    head = events[-1].chain
    if edit == "alter a value":
        e = events[3]
        events[3] = tr.TraceEvent(
            e.index, e.kind, {**e.body, "values": [["a", "9.9"]]}, e.previous, e.chain
        )
    elif edit == "drop an event":
        del events[3]
    elif edit == "reorder":
        events[3], events[5] = events[5], events[3]
    elif edit == "back-date a declaration":
        e = events[6]
        events[6] = tr.TraceEvent(e.index, e.kind, {**e.body, "charge": 5}, e.previous, e.chain)
    elif edit == "append after END":
        last = events[-1]
        events.append(tr.TraceEvent(last.index + 1, tr.DECLARE, {"charge": 0}, last.chain, "x"))
    else:
        # a forger who recomputes every chain value still cannot match the recorded head
        w = tr.TraceWriter()
        for e in events:
            body = dict(e.body)
            if e.kind == tr.DECLARE and body["answer"] == {"n": 3}:
                body["charge"] = 5
            w.append(e.kind, body)
        events = list(w.events())
    with pytest.raises(tr.TraceTampered):
        tr.verify_trace(events, head=head)


def test_the_answer_at_a_checkpoint_is_the_last_declaration_within_it():
    events = _trace()
    assert tr.answer_at(events, 0).body["answer"] == {"n": 1}
    assert tr.answer_at(events, 9).body["answer"] == {"n": 1}
    assert tr.answer_at(events, 10).body["answer"] == {"n": 2}
    assert tr.answer_at(events, 39).body["answer"] == {"n": 2}
    assert tr.answer_at(events, 40).body["answer"] == {"n": 3}
    assert len(tr.evidence_before(events, tr.answer_at(events, 10))) == 2


# -- evaluator-controlled evidence and adversarial arms -------------------------------------------


def test_an_honest_scripted_arm_completes_and_is_judged_on_the_evaluator_s_evidence():
    experiment, cost = cheapest()

    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        yield {"op": "motivating"}
        reply = yield {"op": "measure", "experiment_id": experiment, "replicate": 0, "session": 1}
        assert "values" in reply
        yield {"op": "done", "answer": answer([], spent=cost)}

    events = serve(arm)
    assert tr.status(events) == tr.COMPLETED
    assert [e.kind for e in events].count(tr.MEASURE) == 1
    rows = score(events)
    assert all(not r["deficient"] for r in rows)
    assert all(r["held"] == ("NONE" if r["checkpoint"] < cost else "final") for r in rows)


def test_an_arm_that_asserts_supported_without_evidence_is_never_credited():
    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        yield {"op": "done", "answer": answer([truth_id()], stated_level="SUPPORTED")}

    events = serve(arm)
    assert tr.status(events) == tr.COMPLETED
    final = tr.declarations(events)[-1]
    assert final.body["stated_level"] == "SUPPORTED"  # recorded, ignored
    for row in score(events):
        assert row["level"] == "PROPOSAL"
        assert row["category"] == "UNSUPPORTED_CLAIM"
        assert row["error"] and not row["credited"]


@pytest.mark.parametrize(
    "forgery",
    [
        "evidence in the answer",
        "an observation message",
        "a dated declaration",
        "a forged reading in a declaration",
        "an outcome outside the vocabulary",
    ],
)
def test_an_arm_that_forges_evidence_is_invalid(forgery):
    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        if forgery == "evidence in the answer":
            yield {
                "op": "done",
                "answer": answer([truth_id()], evidence=[["thermal_sweep", [["shift", 9.0]]]]),
            }
        elif forgery == "an observation message":
            yield {"op": "observation", "experiment_id": "thermal_sweep", "values": [["x", 1.0]]}
        elif forgery == "a dated declaration":
            yield {"op": "declare", "answer": {**answer([truth_id()]), "charge": 0}}
        elif forgery == "a forged reading in a declaration":
            yield {"op": "declare", "answer": answer([truth_id()], values=[["x", "1.0"]])}
        else:
            yield {"op": "done", "answer": {**answer([truth_id()]), "outcome": "SUPPORTED"}}

    events = serve(arm)
    assert tr.status(events) == tr.INVALID
    assert events[-2].kind == tr.INCIDENT and events[-2].body["kind"] == "protocol"
    rows = score(events)
    assert all(r["deficient"] and not r["credited"] and r["error"] for r in rows)


def test_a_forged_data_digest_in_a_registration_is_kept_beside_and_never_used():
    experiment, cost = cheapest()

    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        yield {"op": "motivating"}
        yield {
            "op": "register",
            "identity": "forged-identity",
            "experiment_id": experiment,
            "runs": 1,
            "data_digest": "sha256:" + "f" * 64,
        }
        yield {"op": "measure", "experiment_id": experiment, "replicate": 0, "session": 1}
        yield {"op": "done", "answer": answer([truth_id()], spent=cost)}

    events = serve(arm)
    assert tr.status(events) == tr.COMPLETED
    ledger = cp.ledger_from(tr.evidence_before(events, None))
    registration = next(e for e in ledger if e.kind == "REGISTER")
    assert registration.declared_data_digest == "sha256:" + "f" * 64
    assert registration.data_digest != registration.declared_data_digest  # the evaluator's own
    assert not any(r["credited"] for r in score(events))


def test_an_arm_that_misreports_its_spending_is_invalid():
    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        yield {"op": "done", "answer": answer([truth_id()], spent=7)}

    events = serve(arm)
    assert tr.status(events) == tr.INVALID
    assert events[-2].body["kind"] == "metering"


def test_an_arm_that_exceeds_its_budget_is_invalid_and_the_experiment_never_runs():
    experiment, cost = cheapest()
    calls: list[str] = []

    class CountingLab(hw.HiddenWorldLab):
        def measure(self, experiment_id: str, *, replicate: int, session: int) -> Any:
            calls.append(experiment_id)
            return super().measure(experiment_id, replicate=replicate, session=session)

    w = world("example-01")
    catalog = ring_catalog()
    svc = CaseService(
        lab=CountingLab(w, catalog, MOTIVATING_EXPERIMENT),
        experiments=all_experiments(catalog),
        available=w.available(catalog),
        cap=cost,
        arm_id="X",
        start={},
    )
    script = iter(
        [
            {"op": "measure", "experiment_id": experiment, "replicate": 0, "session": 1},
            {"op": "measure", "experiment_id": experiment, "replicate": 1, "session": 2},
            {"op": "done", "answer": answer([truth_id()], spent=2 * cost)},
        ]
    )
    events = svc.serve({}, lambda m: None, lambda: next(script))
    assert tr.status(events) == tr.INVALID
    assert events[-2].body["kind"] == "budget"
    assert calls == [experiment]  # the reservation refused the second run before it started
    assert int(events[-1].body["charge"]) == cost <= svc.cap


@pytest.mark.parametrize("how", ["raises", "process dies", "reports failure"])
def test_an_arm_that_crashes_mid_case_is_deficient_even_after_a_correct_anytime_answer(how):
    experiment, cost = cheapest()

    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        yield {"op": "measure", "experiment_id": experiment, "replicate": 0, "session": 1}
        yield {"op": "declare", "answer": answer([truth_id()], spent=cost)}
        if how == "raises":
            raise RuntimeError("boom")
        if how == "reports failure":
            yield {"op": "failed", "error": "ValueError: boom"}
        # "process dies": the generator just ends

    events = serve(arm)
    assert tr.status(events) == tr.CRASHED
    rows = score(events)
    assert all(r["deficient"] and not r["credited"] for r in rows)


def test_a_session_that_goes_back_is_invalid_and_a_flood_is_truncated():
    experiment, _ = cheapest()

    def back(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        yield {"op": "measure", "experiment_id": experiment, "replicate": 0, "session": 3}
        yield {"op": "measure", "experiment_id": experiment, "replicate": 1, "session": 1}

    assert tr.status(serve(back)) == tr.INVALID

    def flood(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        while True:
            yield {"op": "motivating"}

    assert tr.status(serve(flood, max_messages=50)) == tr.TRUNCATED


def test_an_unavailable_experiment_is_refused_and_recorded_without_charge():
    w = world("example-04")
    removed = w.removed[0][0] if w.removed else None
    if removed is None:
        pytest.skip("example-04 removes nothing")

    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        reply = yield {"op": "measure", "experiment_id": removed, "replicate": 0, "session": 1}
        assert reply["error"] == "ExposureRefused"
        yield {"op": "done", "answer": answer([])}

    events = serve(arm, world_id="example-04")
    assert tr.status(events) == tr.COMPLETED
    assert [e.kind for e in events].count(tr.REFUSED) == 1
    assert int(events[-1].body["charge"]) == 0


# -- checkpoints from one trace vs fresh capped runs ----------------------------------------------


def anytime_arm(order: list[str], claim: str) -> Script:
    """A deterministic arm whose choices never depend on its cap: it runs `order` while the next
    experiment fits, declaring after each run (no claim until two runs, then `claim`), and stops
    with its last declaration when the next one does not fit."""
    costs = {e.experiment_id: e.cost for e in all_experiments(ring_catalog()).values()}

    def arm(run: Mapping[str, Any]) -> Generator[dict[str, Any], dict[str, Any], None]:
        budget = int(run["budget"])
        spent = 0
        current = answer([])
        yield {"op": "motivating"}
        for k, experiment in enumerate(order):
            if spent + costs[experiment] > budget:
                break
            yield {"op": "measure", "experiment_id": experiment, "replicate": k, "session": k + 1}
            spent += costs[experiment]
            current = answer([claim] if k >= 1 else [], spent=spent)
            yield {"op": "declare", "answer": current}
        yield {"op": "done", "answer": {**current, "spent": spent}}

    return arm


@pytest.mark.parametrize("world_id", ["example-01", "example-03", "example-05"])
def test_for_a_cap_independent_deterministic_arm_the_trace_answer_equals_a_fresh_capped_run(
    world_id,
):
    catalog = ring_catalog()
    available = list(world(world_id).available(catalog))
    order = [available[i % len(available)] for i in range(12)]
    arm = anytime_arm(order, truth_id("example-01"))
    one = serve(arm, world_id=world_id, cap=PLAN.cap)
    derived = {r["checkpoint"]: r for r in score(one, world_id)}
    for c in PLAN.ladder:
        fresh = serve(arm, world_id=world_id, cap=c)
        row = cp.score_trace(scorer(world_id), fresh, (c,), fresh[-1].chain)[0]
        mine = derived[c]
        assert (mine["answer_kind"], mine["claim"]) == (row["answer_kind"], row["claim"])
        assert mine["category"] == row["category"]
        # the evidence of the trace answer at c is exactly the fresh run's evidence
        held = tr.answer_at(one, c)
        fresh_evidence = [e.body for e in tr.evidence_before(fresh, None)]
        assert [e.body for e in tr.evidence_before(one, held)] == fresh_evidence[
            : len(tr.evidence_before(one, held))
        ]


def test_early_stopping_moves_no_checkpoint_and_another_arm_s_trace_changes_nothing():
    """S2-CE-1: X right at 10 and stops; Y right at 30: at c* both are what they are, and X's
    rows do not depend on Y's trace."""
    experiment, _ = cheapest()
    x = serve(anytime_arm([experiment] * 3, truth_id()), cap=PLAN.cap)
    y = serve(anytime_arm([experiment] * 9, truth_id()), cap=PLAN.cap)
    rx, ry = score(x), score(y)
    assert rx == score(x)  # a function of X's trace only
    assert rx[-1]["held"] != "NONE" and ry[-1]["held"] != "NONE"
    assert rx[-1]["claim"] == ry[-1]["claim"] == [truth_id()]
    stop = int(x[-1].body["charge"])
    assert stop < int(y[-1].body["charge"])
    assert all(r["held"] == "final" for r in rx if r["checkpoint"] >= stop)


# -- the analysis ----------------------------------------------------------------------------------


def _rows(
    arm: str, values: list[tuple[bool, bool, bool]], checkpoint: int = 48
) -> list[dict[str, Any]]:
    """(exact, error, deficient) per case."""
    return [
        {
            "case_id": f"c{i:02d}",
            "arm": arm,
            "checkpoint": checkpoint,
            "exact": exact,
            "credited": exact,
            "error": error,
            "own_correct": exact,
            "deficient": deficient,
            "status": "INVALID" if deficient else "COMPLETED",
        }
        for i, (exact, error, deficient) in enumerate(values)
    ]


def test_a_deficient_run_is_scored_against_its_own_arm():
    cand = _rows("B7", [(True, False, True), (False, False, False)])
    ref = _rows("B4", [(False, True, False), (True, False, True)])
    pairs = analysis.paired(cand + ref, "B7", "B4", "exact", 48, ["c00", "c01"])
    assert pairs == [(0.0, 0.0), (0.0, 1.0)]
    errors = analysis.paired(cand + ref, "B7", "B4", "error", 48, ["c00", "c01"])
    assert errors == [(1.0, 1.0), (0.0, 0.0)]


def test_a_checkpoint_outside_the_frozen_ladder_is_refused():
    with pytest.raises(ValueError, match="ladder"):
        analysis.compare(
            _rows("B7", [(True, False, False)], 30) + _rows("B4", [(True, False, False)], 30),
            PLAN,
            "B7",
            "B4",
            "exact",
            30,
            ["c00"],
        )
    with pytest.raises(ValueError):
        AnalysisPlan(ladder=(6, 12), cap=48)


def test_the_decision_rules():
    def c(lo: float, hi: float) -> dict[str, Any]:
        return {"difference": {"lo": lo, "hi": hi}}

    assert analysis.decide(c(0.1, 0.4), c(-0.1, 0.0), 0.02, True) == "BETTER"
    assert analysis.decide(c(0.1, 0.4), c(-0.1, 0.05), 0.02, True) == "SAFETY_FAIL"
    assert analysis.decide(c(-0.4, -0.1), c(0.0, 0.0), 0.02, True) == "WORSE"
    assert analysis.decide(c(-0.1, 0.3), c(0.01, 0.1), 0.02, True) == "WORSE"
    assert analysis.decide(c(-0.1, 0.3), c(0.0, 0.0), 0.02, True) == "INCONCLUSIVE"
    assert analysis.decide(c(0.1, 0.4), c(0.0, 0.0), 0.02, False) == "INVALID"


def test_the_bootstrap_is_deterministic_and_the_exact_tests_are_right():
    values = [1.0] * 10 + [0.0] * 40 + [-1.0] * 8
    a = analysis.percentile_interval(values, resamples=2000, seed=1, label="t", confidence=0.95)
    b = analysis.percentile_interval(values, resamples=2000, seed=1, label="t", confidence=0.95)
    assert a == b and a["lo"] < a["mean"] < a["hi"]
    assert analysis.mcnemar_exact(0, 0) == 1.0
    assert analysis.mcnemar_exact(0, 6) == pytest.approx(2 / 64)
    adjusted = analysis.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted["a"]["reject"] and not adjusted["b"]["reject"] and not adjusted["c"]["reject"]
    assert analysis.wilson(0, 58) == [0.0, 0.062118]


def test_the_plan_is_frozen_in_the_manifest_and_names_one_primary_comparison():
    assert PLAN.primary_comparison(("B4", "B6", "B7")) == ("B7", "B4")
    assert PLAN.primary_comparison(("B4", "B6", "B7", "B8")) == ("B8", "B4")
    assert PLAN.primary_checkpoint == PLAN.cap == PLAN.ladder[-1]
    manifest = ROOT / "benchmarks" / "discovery_independent" / "kit" / "kit-manifest.json"
    if manifest.exists():
        frozen = json.loads(manifest.read_text(encoding="utf-8"))
        assert frozen["plan_digest"] == PLAN.digest


# -- the arm process boundary (real subprocesses) ----------------------------------------------------

ADVERSARIAL = """
import json, os

def answer(arm, spent=0):
    return {"arm": arm, "outcome": "STOPPED_UNEXPLAINED", "answer_kind": "NONE", "spent": spent}

def reads_the_sealed_file(arm, *, catalog, oracle, budget, lab, grammar):
    with open(os.environ.get("SEALED", "/etc/hostname")) as handle:
        handle.read()
    return answer(arm)

def lists_a_directory(arm, *, catalog, oracle, budget, lab, grammar):
    os.listdir("/")
    return answer(arm)

def starts_a_process(arm, *, catalog, oracle, budget, lab, grammar):
    import subprocess
    subprocess.run(["true"])
    return answer(arm)

def writes_a_file(arm, *, catalog, oracle, budget, lab, grammar):
    with open("out.txt", "w") as handle:
        handle.write("x")
    return answer(arm)

def crashes(arm, *, catalog, oracle, budget, lab, grammar):
    lab.motivating()
    raise RuntimeError("boom")

def dies(arm, *, catalog, oracle, budget, lab, grammar):
    lab.motivating()
    os._exit(3)

def honest(arm, *, catalog, oracle, budget, lab, grammar):
    lab.motivating()
    return answer(arm)
"""


@pytest.fixture(scope="module")
def adversarial_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    import shutil

    tree = tmp_path_factory.mktemp("arm-tree")
    shutil.copytree(
        ROOT / "src" / "lab_brain",
        tree / "src" / "lab_brain",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (tree / "src" / "adversarial_arms.py").write_text(ADVERSARIAL, encoding="utf-8")
    return tree


def _subprocess_run(
    tree: Path, entry: str, world_id: str = "example-07"
) -> tuple[tr.TraceEvent, ...]:
    k = kit()
    w = world(world_id)
    slot = {
        "arm_id": "X",
        "arm_name": "X",
        "commit": "test",
        "src_tree": "test",
        "entry": f"adversarial_arms:{entry}",
        "context": {
            "catalog": "lab_brain.domains.silicon_photonics.discovery_catalog:ring_catalog",
            "oracle": "lab_brain.discovery.distinguish:SeparationOracle",
            "protocol": "lab_brain.discovery.protocol:DISCOVERY",
        },
    }
    return k.run_one(
        world=w,
        case_id=str(w.case_id),
        package_root="test",
        slot=slot,
        tree=tree,
        budget=12,
        seconds=120,
        log_dir=None,
    )


@pytest.mark.parametrize(
    "entry,status",
    [
        ("honest", tr.COMPLETED),
        ("reads_the_sealed_file", tr.INVALID),
        ("lists_a_directory", tr.INVALID),
        ("starts_a_process", tr.INVALID),
        ("writes_a_file", tr.INVALID),
        ("crashes", tr.CRASHED),
        ("dies", tr.CRASHED),
    ],
)
def test_the_arm_process_guard(adversarial_tree, entry, status):
    events = _subprocess_run(adversarial_tree, entry)
    assert tr.status(events) == status, events[-1].body
    if status == tr.INVALID:
        assert events[-2].body["kind"] == "isolation"


def test_a_pinned_legacy_arm_in_its_own_process_answers_as_the_v14_harness_does(tmp_path):
    """B7 through the kit's worker (a tree materialized from its pinned commit) gives the same
    answer, meter and run digest as the frozen v1.4 harness in process on the same world and cap,
    and the evaluator credits it from the trace."""
    k = kit()
    slot = next(s for s in k.filled_slots(k.registry()) if s["arm_id"] == "B7")
    tree = k.materialize(slot["commit"], slot["src_tree"], tmp_path)
    w = world("example-02")
    events = k.run_one(
        world=w,
        case_id=str(w.case_id),
        package_root="test",
        slot=slot,
        tree=tree,
        budget=48,
        seconds=600,
        log_dir=None,
    )
    assert tr.status(events) == tr.COMPLETED
    final = tr.declarations(events)[-1].body["answer"]
    from lab_brain.discovery.distinguish import SeparationOracle
    from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
    from lab_brain.discovery_safety.v13.ledger import EvaluatorLaboratory, EvaluatorLedger
    from lab_brain.discovery_safety.v14 import evaluation as ev14

    catalog = ring_catalog()
    experiments = all_experiments(catalog)
    meter = CostMeter({x: e.cost for x, e in experiments.items()}, 48)
    lab = EvaluatorLaboratory(
        blind_laboratory(
            hw.HiddenWorldLab(w, catalog, MOTIVATING_EXPERIMENT),
            experiments=experiments,
            available=w.available(catalog),
            meter=meter,
        ),
        EvaluatorLedger(),
    )
    reference = ev14.run_arm(
        "B7",
        catalog=catalog,
        oracle=SeparationOracle(catalog, w.available(catalog), DISCOVERY, dict(w.removed)),
        budget=48,
        lab=lab,
        grammar=k.GRAMMAR,
    )
    assert final["digest"] == reference.digest
    assert final["claim"] == list(reference.claim) and final["spent"] == meter.spent
    assert int(events[-1].body["charge"]) == meter.spent
    # the positive control for the adversarial tests: credit is reachable, from the trace alone
    rows = cp.score_trace(scorer("example-02"), events, PLAN.ladder, events[-1].chain)
    assert rows[-1]["held"] == "final" and rows[-1]["credited"] and rows[-1]["level"] == "SUPPORTED"
    assert all(r["held"] == "NONE" for r in rows if r["checkpoint"] < meter.spent)


def test_the_arm_tree_is_refused_unless_it_is_the_pinned_tree(tmp_path):
    k = kit()
    slot = next(s for s in k.filled_slots(k.registry()) if s["arm_id"] == "B4")
    with pytest.raises(SystemExit, match="not the pinned"):
        k.materialize(slot["commit"], "0" * 40, tmp_path)


def test_a_truth_string_in_an_arm_s_output_is_found():
    from lab_brain.discovery_eval.blind import find_truth_leaks

    w = world("example-05")
    needles = {w.world_id} | {str(e.effect_id) for e in w.effects if e.effect_id}
    said = [{"answer": {"reason": f"looks like {sorted(needles)[0]}"}}]
    assert find_truth_leaks(said, needles)


# -- verify and the committed dry run --------------------------------------------------------------


def test_verify_refuses_any_changed_kit_file(monkeypatch, tmp_path):
    k = kit()
    if not k.MANIFEST.exists():
        pytest.skip("the kit is not frozen yet")
    assert k.verify(tmp_path, quick=True) == []
    original = k.kit_sources

    def changed() -> dict[str, str]:
        out = dict(original())
        out["scripts/discovery_independent_kit.py"] = "0" * 64
        return out

    monkeypatch.setattr(k, "kit_sources", changed)
    problems = k.verify(tmp_path, quick=True)
    assert problems and "kit sources" in problems[0]
    with pytest.raises(SystemExit, match="refusing to run"):
        k._frozen_or_refuse(tmp_path, None)


def test_the_committed_dry_run_is_internally_consistent():
    dry = ROOT / "benchmarks" / "discovery_independent" / "kit" / "dry-run"
    if not dry.exists():
        pytest.skip("no dry run committed yet")
    digest = json.loads((dry / "results-digest.json").read_text(encoding="utf-8"))
    for name, expected in digest["files_sha256"].items():
        assert hashlib.sha256((dry / name).read_bytes()).hexdigest() == expected, name
    summary = json.loads((dry / "run-summary.json").read_text(encoding="utf-8"))
    results = json.loads((dry / "results.json").read_text(encoding="utf-8"))
    assert summary["example_only"] is True and results["example_only"] is True
    for case_id, arms in summary["runs"].items():
        for arm, run in arms.items():
            text = (dry / "traces" / case_id / f"{arm}.jsonl").read_text(encoding="utf-8")
            assert hashlib.sha256(text.encode()).hexdigest() == run["trace_sha256"]
            tr.verify_trace(tr.loads(text), head=run["head"])
