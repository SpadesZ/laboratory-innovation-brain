"""Reproduce, on the UNCHANGED v1.2 code, that the arm decides what the v1.2 ledger calls SUPPORTED.

    python scripts/discovery_safety_v13_reproduce_before.py            # print the log
    python scripts/discovery_safety_v13_reproduce_before.py --write    # also write the evidence log

The v1.2 ledger (`lab_brain.discovery_safety.v12.ledger`) re-scores a registration with quantities
the ARM wrote into the payload: its predicted values, their standard deviation, the alternatives a
risky prediction is measured against, the rule's thresholds and the mechanism fingerprint the
prediction is filed under; and, for a new mechanism, the evaluator reads the answered candidate's
forward model from the arm's own run record. Each reproduction below uses only the v1.2 public API
(`LedgerLaboratory.register`, `rescore`, `supported`, `judge_run`) on a development world (base
7_000_000, declared in `PLAN.development`) and shows the evaluator's re-derived level becoming
SUPPORTED for an answer that is an error.

    R1  inflated SD          an honest prediction of an engine force-fit FAILS; the same prediction
                             with an inflated SD (and alternatives the arm placed far away) passes,
                             is "risky", and the force-fit is scored SUPPORTED / FORCE_FIT
    R2  weak alternatives    a prediction that does not discriminate the claim from an adequate
                             catalog rival (identical predicted values) is "risky" because the arm
                             registered only the zero prediction as its alternative; and in v1.2's
                             OWN registrations on development worlds, how many passed risky
                             predictions were risky only against "none" while "no effect" was
                             already refuted by the data admitted before the registration
    R3  arm-chosen rule      the payload carries alpha, z_max and tau_risky; an arm that writes
                             tau_risky = 0 makes a riskless prediction (identical to its only
                             alternative) "risky" (alpha is partly protected: Holm in `supported`
                             uses the evaluator's alpha; z_max and tau_risky are not)
    R4  arm-chosen label     the prediction is filed under a fingerprint the arm chooses; predicted
                             values of hypothesis A filed under the claim B support B
    R5  arm-supplied answer  for a new mechanism the evaluator takes the candidate (its forward
                             model and fingerprint) from the arm's run record; a candidate whose
                             tables are swapped for another shape's keeps the SUPPORTED level

ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds. Offline; no model, network,
database or real experiment.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery.distinguish import SeparationOracle  # noqa: E402
from lab_brain.discovery.forward import fit  # noqa: E402
from lab_brain.discovery.loop import hypothesis_universe, investigate  # noqa: E402
from lab_brain.discovery.model import (  # noqa: E402
    NULL_HYPOTHESIS,
    Budget,
    Observation,
    make_hypothesis,
)
from lab_brain.discovery.numerics import chi2_sf  # noqa: E402
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery.worlds import SyntheticWorld  # noqa: E402
from lab_brain.discovery_eval import held_out  # noqa: E402
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory  # noqa: E402
from lab_brain.discovery_safety.pairwise import distinct_forward_models  # noqa: E402
from lab_brain.discovery_safety.v12 import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.v12.gate import hypothesis_prediction  # noqa: E402
from lab_brain.discovery_safety.v12.grammar import grammar_from_declaration  # noqa: E402
from lab_brain.discovery_safety.v12.ledger import (  # noqa: E402
    PredictionLedger,
    PredictionRule,
    prediction_payload,
    rescore,
    score_prediction,
    supported,
)
from lab_brain.domains.silicon_photonics import discovery_grammar  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)

OUT = (
    ROOT
    / "docs"
    / "audit"
    / "discovery-safety-v1.3-2026-11-11"
    / "evidence"
    / "reproduction_before.log"
)
DEV = 7_000_000
FORCE_FIT_WORLD = "held_out-chain.polarization_drift-00"
AMBIENT = "held_out-thermo.ambient-00"
ALPHA = 0.01
GRAMMAR = grammar_from_declaration(discovery_grammar.declaration())


def _setup(world_id: str, budget: int, removed: bool = True):  # type: ignore[no-untyped-def]
    catalog = ring_catalog()
    worlds = {
        w.spec.world_id: w
        for w in held_out.held_out_worlds(
            catalog, seeds_per_class=15, base_seed=DEV, protocol=DISCOVERY
        )
    }
    world = worlds[world_id]
    engine_catalog = held_out.without_family(catalog, world.family) if removed else catalog
    experiments = ev._all_experiments(catalog)
    meter = CostMeter({k: e.cost for k, e in experiments.items()}, budget)
    ledger = PredictionLedger()
    lab = ev.LedgerLaboratory(
        blind_laboratory(
            SyntheticWorld(world.spec, catalog, MOTIVATING_EXPERIMENT),
            experiments=experiments,
            available=tuple(e.experiment_id for e in catalog.experiments),
            meter=meter,
        ),
        ledger,
    )
    all_ids = tuple(e.experiment_id for e in catalog.experiments)
    oracle = SeparationOracle(engine_catalog, all_ids, DISCOVERY)
    full = SeparationOracle(catalog, all_ids, DISCOVERY)
    truth = make_hypothesis(catalog.mechanism(world.truth_class))
    held = distinct_forward_models(hypothesis_universe(engine_catalog))
    judge = ev.Judge(truth, dict(world.spec.truth), held, full)
    return catalog, world, engine_catalog, oracle, experiments, meter, ledger, lab, judge


def _observations(ledger: PredictionLedger) -> list[Observation]:
    return [
        Observation(
            observation_id=f"o{e.index}",
            experiment_id=e.experiment_id,
            replicate=e.replicate,
            taken_at=e.index + 1,
            values=e.values,
        )
        for e in ledger.events
        if e.kind == "MEASURE"
    ]


def _next_replicate(ledger: PredictionLedger, experiment_id: str) -> int:
    return sum(1 for e in ledger.events if e.kind == "MEASURE" and e.experiment_id == experiment_id)


def _peek(world, catalog, experiment_id: str, replicate: int):  # type: ignore[no-untyped-def]
    """What the laboratory WILL return (the worlds are deterministic): used only to pick a
    reproduction case in which the honest prediction fails, never by the forged registration."""
    return SyntheticWorld(world.spec, catalog, MOTIVATING_EXPERIMENT).measure(
        experiment_id, replicate=replicate, session=0
    )


def r1_inflated_sd(log: list[str]) -> dict[str, object]:
    budget = 24
    catalog, world, engine_catalog, oracle, experiments, meter, ledger, lab, judge = _setup(
        FORCE_FIT_WORLD, budget
    )
    result = investigate(
        arm="ADV",
        catalog=engine_catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(budget - 4),
        lab=lab,
    )
    claim = [result.record(i).hypothesis for i in result.claim]
    log.append(
        f"R1 world {FORCE_FIT_WORLD} (dev base {DEV}, family removed): the frozen engine at cap "
        f"{budget - 4} claims {[h.hypothesis_id for h in claim]} (truth {world.truth_class}); "
        f"spent {meter.spent}"
    )
    level0 = ev.judge_run(judge, result, None, ledger, experiments, ALPHA)
    log.append(f"R1 before any registration: category {level0[1]}, level {level0[2]}")
    admitted = _observations(ledger)
    # an affordable experiment on which the honest prediction FAILS
    chosen = None
    for x in sorted(oracle.available, key=lambda e: (e.cost, e.experiment_id)):
        if x.cost > budget - meter.spent:
            continue
        k = _next_replicate(ledger, x.experiment_id)
        observed = dict(_peek(world, catalog, x.experiment_id, k))
        ok = True
        for h in claim:
            mean, sd = hypothesis_prediction(h, admitted, experiments, x)
            payload = json.loads(
                prediction_payload(
                    subject=h.hypothesis_id,
                    fingerprint=h.fingerprint,
                    experiment_id=x.experiment_id,
                    replicate=k,
                    predicted=mean,
                    sd=sd,
                    alternatives=[("none", dict.fromkeys(mean, 0.0), dict.fromkeys(mean, 0.0))],
                    rule=PredictionRule(),
                    purpose="R1",
                )
            )
            if score_prediction(payload, tuple(observed.items()), x).passed:
                ok = False
        if ok:
            chosen = (x, k)
            break
    if chosen is None:
        raise SystemExit("R1: no affordable experiment fails the honest prediction")
    x, k = chosen
    honest_scores = []
    for h in claim:
        mean, sd = hypothesis_prediction(h, admitted, experiments, x)
        inflated = {e: 1000.0 * max(v, max(s.sigma for s in x.entries)) for e, v in sd.items()}
        far = dict.fromkeys(mean, 10000000.0)
        honest_scores.append((h, mean, sd))
        lab.register(
            prediction_payload(
                subject=h.hypothesis_id,
                fingerprint=h.fingerprint,
                experiment_id=x.experiment_id,
                replicate=k,
                predicted=mean,
                sd=inflated,
                alternatives=[("none", far, dict.fromkeys(mean, 0.0))],
                rule=PredictionRule(),
                purpose="R1-inflated-sd",
            )
        )
    lab.measure(x.experiment_id, replicate=k, session=99)
    measured = ledger.measurement(x.experiment_id, k)
    assert measured is not None
    for h, mean, sd in honest_scores:
        honest = json.loads(
            prediction_payload(
                subject=h.hypothesis_id,
                fingerprint=h.fingerprint,
                experiment_id=x.experiment_id,
                replicate=k,
                predicted=mean,
                sd=sd,
                alternatives=[("none", dict.fromkeys(mean, 0.0), dict.fromkeys(mean, 0.0))],
                rule=PredictionRule(),
                purpose="R1-honest",
            )
        )
        s = score_prediction(honest, measured.values, x)
        log.append(
            f"R1 {h.hypothesis_id} on {x.experiment_id}#{k}: HONEST sd -> passed {s.passed} "
            f"(p {s.p_value:.3g}, max|z| {s.max_abs_z:.2f})"
        )
    tests = rescore(ledger, experiments)
    for t in tests:
        log.append(
            f"R1 ledger re-score of the INFLATED registration: passed {t.passed}, risky {t.risky}, "
            f"prospective {t.prospective}, p {t.p_value:.3g}"
        )
    _answer, category, level, *_ = ev.judge_run(judge, result, None, ledger, experiments, ALPHA)
    log.append(
        f"R1 evaluator's re-derived outcome after the inflated registration: {category} / {level}"
    )
    return {"category": category, "level": level, "before": level0[1:3]}


def r2_weak_alternatives(log: list[str]) -> dict[str, object]:
    catalog = ring_catalog()
    experiments = ev._all_experiments(catalog)
    universe = distinct_forward_models(hypothesis_universe(catalog))
    claim = next(h for h in universe if h.class_ids == ("thermo.self_heating",))
    rival = next(h for h in universe if h.class_ids == ("thermo.ambient",))

    # the claim's registered values are the RIVAL's own prediction (at its declared upper
    # amplitude) on the experiment where that prediction is farthest from zero: by construction the
    # observation cannot discriminate the claim from the rival
    def rival_mean(x):  # type: ignore[no-untyped-def]
        return {
            e.entry_id: sum(
                c.coefficient(x.experiment_id, e.entry_id) * c.upper for c in rival.components
            )
            for e in x.entries
        }

    x = max(
        catalog.experiments,
        key=lambda x: (
            sum((v / e.sigma) ** 2 for e, v in zip(x.entries, rival_mean(x).values(), strict=True)),
            x.experiment_id,
        ),
    )
    chosen = (x, rival_mean(x))
    x, mc = chosen
    zero = {e.entry_id: 0.0 for e in x.entries}
    ledger = PredictionLedger()
    ledger.register(
        prediction_payload(
            subject=claim.hypothesis_id,
            fingerprint=claim.fingerprint,
            experiment_id=x.experiment_id,
            replicate=0,
            predicted=mc,
            sd=zero,
            alternatives=[("none", zero, zero)],
            rule=PredictionRule(),
            purpose="R2-weak-alternatives",
        )
    )
    ledger.record_measurement(x.experiment_id, 0, tuple(mc.items()))
    t = rescore(ledger, experiments)[0]
    honest = PredictionLedger()
    honest.register(
        prediction_payload(
            subject=claim.hypothesis_id,
            fingerprint=claim.fingerprint,
            experiment_id=x.experiment_id,
            replicate=0,
            predicted=mc,
            sd=zero,
            alternatives=[("rival " + rival.hypothesis_id, mc, zero)],
            rule=PredictionRule(),
            purpose="R2-rival-alternative",
        )
    )
    honest.record_measurement(x.experiment_id, 0, tuple(mc.items()))
    th = rescore(honest, experiments)[0]
    log.append(
        f"R2 synthetic: claim {claim.hypothesis_id}, rival {rival.hypothesis_id}, experiment "
        f"{x.experiment_id}; with the arm's alternative 'none' only -> passed {t.passed} risky "
        f"{t.risky}, supported {supported([t], claim.fingerprint, ALPHA)}; with the rival as the "
        f"alternative -> risky {th.risky}"
    )
    return {"risky_with_none": t.risky, "risky_with_rival": th.risky}


def r2_real_runs(log: list[str], per: int) -> dict[str, int]:
    """v1.2's own registrations on development worlds: passed and risky, yet risky only against
    the zero prediction while 'no effect' was already refuted by the earlier data."""
    catalog = ring_catalog()
    worlds = held_out.held_out_worlds(
        catalog, seeds_per_class=per, base_seed=DEV, protocol=DISCOVERY
    )
    experiments = ev._all_experiments(catalog)
    counts = {"registrations": 0, "passed_risky": 0, "risky_only_vs_none_while_null_refuted": 0}
    examples: list[str] = []
    for world in worlds:
        for removed in (True, False):
            for budget in (12, 24):
                _, _, engine_catalog, oracle, _, _, ledger, lab, _ = _setup(
                    world.spec.world_id, budget, removed
                )
                from lab_brain.discovery_safety.v12.gate import safe_investigate_v12

                safe_investigate_v12(
                    arm="B5",
                    catalog=engine_catalog,
                    oracle=oracle,
                    protocol=DISCOVERY,
                    budget=Budget(budget),
                    lab=lab,
                    grammar=GRAMMAR,
                )
                for event, payload in ledger.registrations():
                    counts["registrations"] += 1
                    m = ledger.measurement(payload["experiment_id"], payload["replicate"])
                    if m is None or m.index < event.index:
                        continue
                    x = experiments[payload["experiment_id"]]
                    s = score_prediction(payload, m.values, x)
                    if not (s.passed and s.risky):
                        continue
                    counts["passed_risky"] += 1
                    before = [
                        Observation(
                            observation_id=f"o{e.index}",
                            experiment_id=e.experiment_id,
                            replicate=e.replicate,
                            taken_at=e.index + 1,
                            values=e.values,
                        )
                        for e in ledger.events[: event.index]
                        if e.kind == "MEASURE"
                    ]
                    null_fit = fit(NULL_HYPOTHESIS, before, experiments)
                    null_refuted = null_fit.n > 0 and chi2_sf(null_fit.chi2, null_fit.n) < ALPHA
                    tau = float(payload["rule"]["tau_risky"])
                    seps = {}
                    pred = {k: float(v) for k, v in payload["predicted"].items()}
                    sd = {k: float(v) for k, v in payload["sd"].items()}
                    for alt in payload["alternatives"]:
                        o = {k: float(v) for k, v in alt["predicted"].items()}
                        osd = {k: float(v) for k, v in alt["sd"].items()}
                        seps[alt["label"]] = math.sqrt(
                            sum(
                                (pred.get(e.entry_id, 0.0) - o.get(e.entry_id, 0.0)) ** 2
                                / (
                                    e.sigma**2
                                    + sd.get(e.entry_id, 0.0) ** 2
                                    + osd.get(e.entry_id, 0.0) ** 2
                                )
                                for e in x.entries
                            )
                        )
                    only_none = seps.get("none", 0.0) >= tau and all(
                        v < tau for k, v in seps.items() if k != "none"
                    )
                    if only_none and null_refuted:
                        counts["risky_only_vs_none_while_null_refuted"] += 1
                        if len(examples) < 5:
                            examples.append(
                                f"  e.g. {world.spec.world_id} {'removed' if removed else 'in'} "
                                f"b{budget}: {payload['subject']} on {x.experiment_id} "
                                f"({payload['purpose']}); separations "
                                + ", ".join(f"{k} {v:.2f}" for k, v in sorted(seps.items()))
                            )
    log.append(
        f"R2 v1.2's own registrations on development worlds (base {DEV}, {per} per class, family "
        f"removed and left in, budgets 12 and 24): {json.dumps(counts, sort_keys=True)}"
    )
    log.extend(examples)
    return counts


def r3_arm_rule(log: list[str]) -> dict[str, object]:
    catalog = ring_catalog()
    experiments = ev._all_experiments(catalog)
    x = experiments["cutback"]
    zero = {e.entry_id: 0.0 for e in x.entries}
    ledger = PredictionLedger()
    ledger.register(
        prediction_payload(
            subject="any",
            fingerprint="fp:any",
            experiment_id="cutback",
            replicate=0,
            predicted=zero,
            sd=zero,
            alternatives=[("none", zero, zero)],
            rule=PredictionRule(alpha=0.0, z_max=1e9, tau_risky=0.0),
            purpose="R3-arm-rule",
        )
    )
    ledger.record_measurement("cutback", 0, tuple(zero.items()))
    t = rescore(ledger, experiments)[0]
    log.append(
        f"R3 a riskless prediction (identical to its only alternative) under the arm's rule "
        f"alpha=0, z_max=1e9, tau_risky=0: passed {t.passed}, risky {t.risky}, supported "
        f"{supported([t], 'fp:any', ALPHA)}"
    )
    return {"passed": t.passed, "risky": t.risky}


def r4_arm_label(log: list[str]) -> dict[str, object]:
    catalog = ring_catalog()
    experiments = ev._all_experiments(catalog)
    universe = distinct_forward_models(hypothesis_universe(catalog))
    a = next(h for h in universe if h.class_ids == ("thermo.ambient",))
    b = next(h for h in universe if h.class_ids == ("scatter.sidewall",))
    x = experiments["baseline"]
    pa = {
        e.entry_id: sum(c.coefficient(x.experiment_id, e.entry_id) * c.upper for c in a.components)
        for e in x.entries
    }
    zero = {e.entry_id: 0.0 for e in x.entries}
    ledger = PredictionLedger()
    ledger.register(
        prediction_payload(
            subject=b.hypothesis_id,
            fingerprint=b.fingerprint,
            experiment_id="baseline",
            replicate=0,
            predicted=pa,
            sd=zero,
            alternatives=[("none", zero, zero)],
            rule=PredictionRule(),
            purpose="R4-arm-label",
        )
    )
    ledger.record_measurement("baseline", 0, tuple(pa.items()))
    t = rescore(ledger, experiments)[0]
    pb = {
        e.entry_id: sum(c.coefficient(x.experiment_id, e.entry_id) * c.upper for c in b.components)
        for e in x.entries
    }
    log.append(
        f"R4 {a.hypothesis_id}'s predicted values filed under {b.hypothesis_id}'s fingerprint: "
        f"passed {t.passed}, risky {t.risky}, {b.hypothesis_id} supported "
        f"{supported([t], b.fingerprint, ALPHA)} (what {b.hypothesis_id} itself predicts on "
        f"baseline: max |value| {max(abs(v) for v in pb.values()):.4g})"
    )
    return {"supported": supported([t], b.fingerprint, ALPHA)}


def r5_arm_answer(log: list[str]) -> dict[str, object]:
    budget = 24
    _catalog, _world, engine_catalog, oracle, experiments, _meter, ledger, lab, judge = _setup(
        AMBIENT, budget
    )
    from lab_brain.discovery_safety.v12.gate import grammar_shapes, safe_investigate_v12

    run = safe_investigate_v12(
        arm="B5",
        catalog=engine_catalog,
        oracle=oracle,
        protocol=DISCOVERY,
        budget=Budget(budget),
        lab=lab,
        grammar=GRAMMAR,
    )
    assert run.discovery is not None and run.discovery.answered is not None
    honest = ev.judge_run(judge, run.result, run, ledger, experiments, ALPHA)
    answered = run.discovery.answered
    other = next(
        s
        for s in grammar_shapes(GRAMMAR)
        if len(s.tables) == len(answered.tables)
        and s.fingerprint != answered.fingerprint
        and s.terms[0].channel != "index"
    )
    forged = replace(
        run,
        discovery=replace(
            run.discovery,
            answered=replace(
                answered, tables=other.tables, terms=tuple(t.term_id for t in other.terms)
            ),
        ),
    )
    out = ev.judge_run(judge, run.result, forged, ledger, experiments, ALPHA)
    log.append(
        f"R5 world {AMBIENT} b{budget}: B5 answered {answered.candidate_id} -> {honest[1]} / "
        f"{honest[2]}; the same run record with the answer's forward model swapped for "
        f"{other.shape_id[:60]}... (fingerprint left) -> {out[1]} / {out[2]}"
    )
    return {"honest": honest[1:3], "forged": out[1:3]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--per", type=int, default=3)
    args = parser.parse_args(argv)
    log = [
        "Reproduction BEFORE the v1.3 fix, on the unchanged v1.2 code "
        "(src/lab_brain/discovery_safety/v12/, design freeze 50549e2). Development seeds only.",
    ]
    out = {
        "R1": r1_inflated_sd(log),
        "R2": r2_weak_alternatives(log),
        "R3": r3_arm_rule(log),
        "R4": r4_arm_label(log),
        "R5": r5_arm_answer(log),
        "R2_real": r2_real_runs(log, args.per),
    }
    log.append("SUMMARY " + json.dumps(out, sort_keys=True, default=list))
    text = "\n".join(log) + "\n"
    print(text, end="")
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
