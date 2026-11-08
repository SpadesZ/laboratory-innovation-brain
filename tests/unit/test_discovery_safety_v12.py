"""Safety v1.2: root cause, allocation, registration ordering, alpha spending, grammar, scoring.

Development seeds only (bases 1, 5_000_000, 7_000_000 and 8_000_000, declared in
`PLAN.development`); the held-out evaluation is in the frozen evidence and its own test. Every
world is synthetic and written by the engine's author lineage. ENGINEERING EVIDENCE ONLY.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from functools import cache

import pytest

from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import investigate
from lab_brain.discovery.model import Budget, Purpose, make_hypothesis
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v12 import evaluation as ev
from lab_brain.discovery_safety.v12.gate import safe_investigate_v12
from lab_brain.discovery_safety.v12.grammar import (
    enumerate_shapes,
    grammar_from_declaration,
    term_table,
)
from lab_brain.discovery_safety.v12.ledger import (
    MEASURE,
    REGISTER,
    PredictionLedger,
    PredictionRule,
    holm_rejections,
    prediction_payload,
    rescore,
    supported,
)
from lab_brain.discovery_safety.v12.model import (
    DECLARED_ORDER,
    DEVELOPMENT,
    PLAN,
    SAFETY_V12,
    EvaluationPlanV12,
    SeedRange,
)
from lab_brain.discovery_safety.v12.replay import ReplayLaboratory, run_ladder
from lab_brain.domains.silicon_photonics import discovery_grammar
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DECLARED,
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)
from lab_brain.spec import repo_root

DEV = 7_000_000
GRAMMAR = grammar_from_declaration(discovery_grammar.declaration())


@cache
def catalog():  # type: ignore[no-untyped-def]
    return ring_catalog()


@cache
def worlds():  # type: ignore[no-untyped-def]
    return {
        w.spec.world_id: w
        for w in held_out.held_out_worlds(
            catalog(), seeds_per_class=15, base_seed=DEV, protocol=DISCOVERY
        )
    }


def _oracle(cat):  # type: ignore[no-untyped-def]
    return SeparationOracle(cat, tuple(e.experiment_id for e in cat.experiments), DISCOVERY)


@cache
def records(world_id: str, removed: bool, budget: int) -> tuple[ev.RunRecord, ...]:
    return tuple(
        ev.held_out_records(
            catalog(),
            worlds()[world_id],
            budgets=(budget,),
            motivating_experiment=MOTIVATING_EXPERIMENT,
            grammar=GRAMMAR,
            family_removed=removed,
        )
    )


def _by_arm(world_id: str, removed: bool, budget: int) -> dict[str, ev.RunRecord]:
    return {r.arm: r for r in records(world_id, removed, budget)}


def _ledger_run(world_id: str, removed: bool, budget: int, safety=SAFETY_V12):  # type: ignore[no-untyped-def]
    cat = catalog()
    w = worlds()[world_id]
    engine_cat = held_out.without_family(cat, w.family) if removed else cat
    experiments = {e.experiment_id: e for e in cat.experiments} | {
        u.experiment.experiment_id: u.experiment for u in cat.unavailable
    }
    meter = CostMeter({k: e.cost for k, e in experiments.items()}, budget)
    ledger = PredictionLedger()
    lab = ev.LedgerLaboratory(
        blind_laboratory(
            SyntheticWorld(w.spec, cat, MOTIVATING_EXPERIMENT),
            experiments=experiments,
            available=tuple(e.experiment_id for e in cat.experiments),
            meter=meter,
        ),
        ledger,
    )
    run = safe_investigate_v12(
        arm="B5",
        catalog=engine_cat,
        oracle=_oracle(engine_cat),
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=lab,
        safety=safety,
        grammar=GRAMMAR,
    )
    return run, ledger, meter, experiments


# -- root cause (pinned on the case the development log names) --------------------------------

THICKNESS = "held_out-geometry.thickness-01"


def test_root_cause_v11_loses_the_truth_to_the_engines_replicates():
    """B2 identifies the truth at budget 12, v1.1 abstains ADEQUACY_UNVERIFIED: the engine spent 11
    of 12 units, 6 of them on replicates of experiments it had already run, and the claim's
    never-run signal experiments cost more than what was left."""
    cat = catalog()
    w = worlds()[THICKNESS]
    engine = investigate(
        arm="B2",
        catalog=cat,
        oracle=_oracle(cat),
        protocol=DISCOVERY,
        budget=Budget(12),
        lab=SyntheticWorld(w.spec, cat, MOTIVATING_EXPERIMENT),
    )
    assert engine.claim == ("hyp:geometry.thickness",)
    seen: set[str] = set()
    replicate_cost = 0
    for step in engine.steps:
        if step.experiment_id in seen:
            replicate_cost += step.cost
        seen.add(step.experiment_id)
    assert engine.spent == 11 and replicate_cost >= 6
    v11 = safe_investigate_v11(
        arm="B4",
        catalog=cat,
        oracle=_oracle(cat),
        protocol=DISCOVERY,
        budget=Budget(12),
        lab=SyntheticWorld(w.spec, cat, MOTIVATING_EXPERIMENT),
    )
    assert v11.assessment.reason is not None
    assert v11.assessment.reason.value == "ADEQUACY_UNVERIFIED"
    assert v11.refit is not None and v11.refit.uncovered


def test_v12_recovers_that_identification_with_evidential_support():
    rows = _by_arm(THICKNESS, False, 12)
    assert rows["B2"].own_category == "CORRECT_IDENTIFICATION"
    assert rows["B2"].category == ev.PROPOSAL_ONLY  # no prediction was ever registered
    assert rows["B4"].category == ev.FALSE_NULL
    assert rows["B5"].category == ev.EXACT and rows["B5"].level == ev.SUPPORTED
    assert rows["B5"].spent <= 12


# -- allocation --------------------------------------------------------------------------------


def test_the_replay_laboratory_charges_each_measurement_once():
    w = worlds()[THICKNESS]
    cat = catalog()
    costs = {e.experiment_id: e.cost for e in cat.experiments}
    replay = ReplayLaboratory(SyntheticWorld(w.spec, cat, MOTIVATING_EXPERIMENT), costs, 12)
    first = replay.measure("tec_stabilized", replicate=0, session=1)
    again = replay.measure("tec_stabilized", replicate=0, session=7)
    assert first == again and replay.charged == 2
    replay.measure("tec_stabilized", replicate=1, session=8)
    assert replay.charged == 4 and replay.next_replicate("tec_stabilized") == 2


def test_the_ladder_stops_at_the_first_claim_within_the_engine_share():
    w = worlds()[THICKNESS]
    cat = catalog()
    costs = {e.experiment_id: e.cost for e in cat.experiments}
    replay = ReplayLaboratory(SyntheticWorld(w.spec, cat, MOTIVATING_EXPERIMENT), costs, 24)
    _engine, ladder, cap, requested = run_ladder(
        arm="B5",
        catalog=cat,
        oracle=_oracle(cat),
        protocol=DISCOVERY,
        budget=Budget(24),
        replay=replay,
        start=2,
        stop=12,
    )
    assert cap <= 12 and [s.cap for s in ladder] == list(range(2, cap + 1))
    assert all(not s.claim for s in ladder[:-1])
    assert replay.charged <= 24 and set(requested) <= set(replay.readings)


def test_every_ladder_measurement_is_data_and_the_meter_agrees():
    run, ledger, meter, _ = _ledger_run(THICKNESS, False, 12)
    assert meter.spent == run.result.spent <= 12
    measured = [e for e in ledger.events if e.kind == MEASURE]
    admitted = [o for o in run.result.observations if not o.motivating]
    assert len(measured) == len(admitted)
    assert run.allocation.engine_cap <= int(SAFETY_V12.engine_fraction * 12)


def test_probe_order_is_separation_per_cost_and_the_ablation_is_v11s():
    run, _, _, _ = _ledger_run(THICKNESS, False, 12)
    declared, _, _, _ = _ledger_run(
        THICKNESS, False, 12, safety=replace(SAFETY_V12, probe_order=DECLARED_ORDER)
    )
    assert run.assessment.probes and declared.assessment.probes
    assert SAFETY_V12.probe_order != DECLARED_ORDER


# -- registration ordering and alpha spending ----------------------------------------------------


def test_every_registration_precedes_the_measurement_it_names():
    run, ledger, _, experiments = _ledger_run(THICKNESS, False, 12)
    tests = rescore(ledger, experiments)
    assert tests and all(t.prospective for t in tests)
    for t in tests:
        assert t.measure_index is not None and t.register_index < t.measure_index
    assert {r.digest for r in run.registrations} == {
        e.digest for e in ledger.events if e.kind == REGISTER
    }


def _payload(experiment_id: str, replicate: int, value: float) -> str:
    return prediction_payload(
        subject="h",
        fingerprint="fp",
        experiment_id=experiment_id,
        replicate=replicate,
        predicted={"loss_straight": value},
        sd={"loss_straight": 0.0},
        alternatives=[("none", {"loss_straight": 0.0}, {"loss_straight": 0.0})],
        rule=PredictionRule(),
        purpose="TEST",
    )


def _experiments():  # type: ignore[no-untyped-def]
    return {e.experiment_id: e for e in catalog().experiments}


def test_a_prediction_registered_after_its_data_supports_nothing():
    ledger = PredictionLedger()
    ledger.record_measurement("cutback", 0, (("loss_straight", 1.0),))
    ledger.register(_payload("cutback", 0, 1.0))
    tests = rescore(ledger, _experiments())
    assert tests[0].passed and not tests[0].prospective
    assert not supported(tests, "fp", 0.01)
    before = PredictionLedger()
    before.register(_payload("cutback", 0, 1.0))
    before.record_measurement("cutback", 0, (("loss_straight", 1.0),))
    assert supported(rescore(before, _experiments()), "fp", 0.01)


def test_a_tampered_registration_is_refused():
    ledger = PredictionLedger()
    ledger.register(_payload("cutback", 0, 1.0))
    event = ledger.events[0]
    ledger.events[0] = replace(event, text=event.text.replace("1.000000000", "2.000000000"))
    with pytest.raises(ValueError):
        rescore(ledger, _experiments())


def test_holm_spends_alpha_over_every_registration_of_a_mechanism():
    assert holm_rejections([0.004, 0.5, 0.6], 0.01) == [False, False, False]
    assert holm_rejections([0.002, 0.5, 0.6], 0.01) == [True, False, False]
    ledger = PredictionLedger()
    for k, value in enumerate((1.0, 1.0, 1.0)):
        ledger.register(_payload("cutback", k, value))
        ledger.record_measurement("cutback", k, (("loss_straight", 1.0 + 0.1 * k),))
    assert supported(rescore(ledger, _experiments()), "fp", 0.01)
    ledger.register(_payload("cutback", 3, 1.0))
    ledger.record_measurement("cutback", 3, (("loss_straight", 1.5),))  # 5 sigma off
    assert not supported(rescore(ledger, _experiments()), "fp", 0.01)


def test_a_passed_but_riskless_prediction_supports_nothing():
    ledger = PredictionLedger()
    ledger.register(_payload("cutback", 0, 0.0))
    ledger.record_measurement("cutback", 0, (("loss_straight", 0.0),))
    tests = rescore(ledger, _experiments())
    assert tests[0].passed and not tests[0].risky
    assert not supported(tests, "fp", 0.01)


# -- grammar -----------------------------------------------------------------------------------


GRAMMAR_FILE = (
    repo_root() / "src" / "lab_brain" / "domains" / "silicon_photonics" / "discovery_grammar.py"
)


def test_the_grammar_declaration_references_no_catalog_definition():
    text = GRAMMAR_FILE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imports.append(n.module or "")
        elif isinstance(n, ast.Import):
            imports.extend(a.name for a in n.names)
    assert all(not m.startswith("lab_brain") for m in imports), imports
    assert "discovery_catalog" not in text
    forbidden = set()
    for d in DECLARED:
        forbidden |= {d.class_id, d.family, d.forward.__name__, d.parameter}
    forbidden -= {"amplitude"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert not forbidden & names, forbidden & names
    assert not {s for s in strings if s in forbidden}, forbidden & strings


def test_the_grammar_machinery_imports_no_domain():
    path = repo_root() / "src" / "lab_brain" / "discovery_safety" / "v12" / "grammar.py"
    assert "lab_brain.domains" not in path.read_text(encoding="utf-8")


def test_the_grammar_is_built_from_readouts_alone():
    shapes = enumerate_shapes(GRAMMAR)
    assert len(shapes) == 2892
    assert len({s.fingerprint for s in shapes}) == len(shapes)
    laser = next(s for s in shapes if s.shape_id.startswith("laser["))
    assert {(e, n): c for e, n, c in laser.tables[0]} == {
        ("baseline", "shift"): 1.0,
        ("tec_stabilized", "shift"): 1.0,
        ("gas_cell_reference", "refline"): 1.0,
    }
    for shape in shapes[:50]:
        assert term_table(GRAMMAR, shape.terms[0]) == shape.tables[0]


def test_the_grammar_digest_is_pinned_in_the_freeze():
    assert GRAMMAR.digest == (
        "sha256:767111e512f4d2424f2576a5949244879fad811c6854310a7501aa9111df8942"
    )


# -- discovery: validated versus proposal ----------------------------------------------------


AMBIENT = "held_out-thermo.ambient-00"


def test_a_new_mechanism_is_validated_only_through_a_registered_prediction():
    run, ledger, meter, experiments = _ledger_run(AMBIENT, True, 24)
    attempt = run.discovery
    assert attempt is not None and attempt.answered is not None
    assert attempt.tests
    tests = rescore(ledger, experiments)
    mine = [t for t in tests if t.fingerprint == attempt.answered.fingerprint]
    decisive = [t for t in mine if t.prospective and t.passed and t.risky]
    assert decisive and all(t.prospective for t in mine)
    first = decisive[0]
    assert first.measure_index is not None and first.register_index < first.measure_index
    # the experiment of the registered test had never been run before its registration
    measured_before = [
        e
        for e in ledger.events[: first.register_index]
        if e.kind == MEASURE and e.experiment_id == first.experiment_id
    ]
    assert not measured_before
    assert meter.spent == run.result.spent <= 24
    rows = _by_arm(AMBIENT, True, 24)
    assert rows["B5"].category == ev.VALIDATED_NEW and rows["B5"].level == ev.SUPPORTED
    assert all(rows[a].category == ev.CORRECT_ABSTENTION for a in ("B2", "B3", "B4"))


def test_the_same_answer_without_its_ledger_is_only_a_proposal():
    run, _, _, experiments = _ledger_run(AMBIENT, True, 24)
    cat = catalog()
    w = worlds()[AMBIENT]
    judge = ev.Judge(
        make_hypothesis(cat.mechanism(w.truth_class)),
        dict(w.spec.truth),
        (),
        _oracle(cat),
    )
    answer, category, level, hit, *_ = ev.judge_run(
        judge, run.result, run, PredictionLedger(), experiments, 0.01
    )
    assert (answer, category, level) == ("NEW_MECHANISM", ev.PROPOSAL_ONLY, "PROPOSAL")
    assert hit  # it does match the truth -- and is still not credited


def test_a_table_refuses_to_credit_an_unsupported_answer():
    rows = list(records(AMBIENT, True, 24))
    forged = replace(rows[-1], category=ev.VALIDATED_NEW, level="PROPOSAL")
    with pytest.raises(AssertionError):
        ev.table([forged])


def test_engine_claims_are_proposals_and_their_hits_are_counted_beside():
    rows = _by_arm("held_out-chain.polarization_drift-00", True, 24)
    assert rows["B2"].own_category == "FORCE_FIT"
    assert rows["B2"].category == ev.PROPOSAL_ONLY and not rows["B2"].proposal_hit
    control = _by_arm(THICKNESS, False, 12)
    assert control["B2"].category == ev.PROPOSAL_ONLY and control["B2"].proposal_hit
    table = ev.table([control["B2"]])
    assert table["proposal_only_hits"] == 1 and table["sai"][ev.EXACT]["k"] == 0


# -- plan ----------------------------------------------------------------------------------------


def test_the_plan_declares_development_seeds_and_fresh_held_out_ranges():
    assert {r.base_seed for r in PLAN.development} == {1, 5_000_000, 7_000_000, 8_000_000}
    assert all(r.role == DEVELOPMENT for r in PLAN.development)
    assert PLAN.held_out[0].base_seed >= 3_000_000_000
    with pytest.raises(ValueError):
        EvaluationPlanV12(held_out=(SeedRange("x", 3_931_910_000 + 5, 15, "HELD_OUT_FOR_V1_2"),))
    assert json.loads(json.dumps(ev.SAI_CATEGORIES)) == list(ev.SAI_CATEGORIES)


def test_registered_probes_are_steps_of_the_result():
    run, _, _, _ = _ledger_run(THICKNESS, False, 12)
    assert any(s.purpose is Purpose.PROSPECTIVE_TEST for s in run.result.steps)
