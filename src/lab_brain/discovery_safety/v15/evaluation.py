"""Arms B4, B7 and B8 on the same worlds, scored under SAI 3.5 candidate.5 by the v1.4 rule.

    B4   the v1.1 gate (the offline safety BASELINE)
    B7   the v1.4 gate (`safe_investigate_v14`), unchanged
    B8   the v1.5 gate (`safe_investigate_v15`): B7 with rival-targeted experiment choice

The evaluator rule is v1.4's, unchanged (`EVALUATOR_RULE_V14`): v1.5 changes the ARM only. Beside
each run's candidate.5 category the evaluator records (`diagnose.py`), from its own ledger and the
world's truth:

    refuted / refuted_incorrect   rivals closed by a FAILED prediction in the run (never by
                                  separation alone), and those of them that express the truth
    runs                          experiment runs recorded (MEASURE events)
    cause                         for a non-SUPPORTED answer on a world a held hypothesis
                                  expresses: why the truth's identity was not SUPPORTED on this
                                  record (correct vs avoidable abstention); "" otherwise

As in v1.3/v1.4 the arm runs in its own process and returns only an `ArmAnswer`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    Budget,
    ExperimentSpec,
    Hypothesis,
    Outcome,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v12.evaluation import Judge
from lab_brain.discovery_safety.v12.gate import grammar_shapes
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.model import SafeRunV12
from lab_brain.discovery_safety.v13 import evaluation as ev13
from lab_brain.discovery_safety.v13.ledger import (
    REGISTER,
    EvaluatorLaboratory,
    EvaluatorLedger,
)
from lab_brain.discovery_safety.v13.model import EVALUATOR_RULE, ArmAnswer
from lab_brain.discovery_safety.v13.rule import Rescorer, rescore
from lab_brain.discovery_safety.v14 import evaluation as ev14
from lab_brain.discovery_safety.v14.gate import safe_investigate_v14
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14, SAFETY_V14, EvaluatorRuleV14
from lab_brain.discovery_safety.v14.rule import RescorerV14
from lab_brain.discovery_safety.v15 import diagnose as dg
from lab_brain.discovery_safety.v15.gate import safe_investigate_v15
from lab_brain.discovery_safety.v15.model import SAFETY_V15

ARM_IDS = ("B4", "B7", "B8")
CATEGORIES = ev13.CATEGORIES
CREDITED = ev13.CREDITED
ERRORS = ev13.ERRORS
SUPPORTED, PROPOSAL, NONE = ev13.SUPPORTED, ev13.PROPOSAL, ev13.NONE


def run_arm(
    arm: str,
    *,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    budget: int,
    lab: Laboratory,
    grammar: TermGrammar | None,
) -> ArmAnswer:
    """Build and run one arm (inside the arm's own process in the evaluation)."""
    kwargs: dict[str, Any] = {
        "arm": arm,
        "catalog": catalog,
        "oracle": oracle,
        "protocol": DISCOVERY,
        "budget": Budget(budget),
        "lab": lab,
    }
    run: Any
    if arm == "B4":
        run = safe_investigate_v11(**kwargs)
    elif arm == "B7":
        run = safe_investigate_v14(**kwargs, safety=SAFETY_V14, grammar=grammar)
    elif arm == "B8":
        run = safe_investigate_v15(**kwargs, safety=SAFETY_V15, grammar=grammar)
    else:
        raise ValueError(f"unknown arm {arm}")
    result = run.result
    answered = proposal = ""
    if isinstance(run, SafeRunV12) and run.discovery is not None:
        if run.discovery.answered is not None:
            answered = run.discovery.answered.fingerprint
        if run.discovery.proposal is not None:
            proposal = run.discovery.proposal.fingerprint
    claimed = result.outcome in CLAIM_OUTCOMES
    claim = tuple(result.claim) if claimed else ()
    if result.outcome is Outcome.NO_EFFECT_BEYOND_NOISE:
        claim = (NULL_HYPOTHESIS.hypothesis_id,)
    kind = "NEW_MECHANISM" if answered else ("CATALOG_CLAIM" if claimed else "NONE")
    return ArmAnswer(
        arm=arm,
        outcome=result.outcome.value,
        answer_kind=kind,
        claim=claim,
        new_mechanism=answered,
        grammar_proposal=proposal,
        labelled_proposal=False,
        acted_on=kind != "NONE",
        spent=result.spent,
        reason=ev13._reason(result, run),
        digest=result.digest,
    )


@dataclass
class WorldCase(ev14.WorldCase):
    """v1.4's case plus what the evaluator needs for the diagnosis (never sent to an arm): the
    truth as a hypothesis (None: no catalog hypothesis is the truth) and the world's noise-free
    response to one run of an experiment."""

    truth: Hypothesis | None = None
    true_mean: Callable[[ExperimentSpec], Mapping[str, float]] | None = None


@dataclass(frozen=True)
class RunRecord(ev14.RunRecord):
    refuted: int = 0
    refuted_incorrect: int = 0
    refuted_by_kind: Mapping[str, int] = dataclasses.field(default_factory=dict)
    runs: int = 0
    #: A non-SUPPORTED answer on a supportable world: why (diagnose.CAUSES); "" otherwise.
    cause: str = ""
    supportable: bool = False
    diagnosis: Mapping[str, Any] | None = None


Execute = Callable[[Mapping[str, Any], EvaluatorLaboratory], ArmAnswer]


class Evaluator:
    """Runs every arm at every cap on one world; scores each run from its own ledger."""

    def __init__(
        self,
        execute: Execute,
        grammar: TermGrammar | None,
        rule: EvaluatorRuleV14 = EVALUATOR_RULE_V14,
        arms: Sequence[str] = ARM_IDS,
        diagnose: bool = True,
    ) -> None:
        self.execute = execute
        self.grammar = grammar
        self.rule = rule
        self.arms = tuple(arms)
        self.diagnose = diagnose

    def run(self, case: WorldCase, budgets: Sequence[int]) -> list[RunRecord]:
        experiments = ev13.all_experiments(case.full_catalog)
        costs = {k: e.cost for k, e in experiments.items()}
        universe = hypothesis_universe(case.engine_catalog)
        held = distinct_forward_models(universe)
        by_id = {h.hypothesis_id: h for h in universe}
        by_id[NULL_HYPOTHESIS.hypothesis_id] = NULL_HYPOTHESIS
        judge: Judge = case.judge(held)
        shapes = grammar_shapes(self.grammar) if self.grammar is not None else ()
        available = tuple(e.experiment_id for e in case.engine_oracle.available)
        rescorer = RescorerV14(
            held, shapes, experiments, self.rule, case.engine_oracle.distinguishable, available
        )
        rescorer13 = Rescorer(
            held, shapes, experiments, EVALUATOR_RULE, case.engine_oracle.distinguishable
        )
        supportable = judge.any_held_matches()
        truth_id = dg.truth_identity(rescorer, case.truth, judge.matches) if supportable else ""
        is_truth = dg.truth_predicate(rescorer, judge.matches, truth_id)
        out = []
        for budget in budgets:
            for arm in self.arms:
                meter = CostMeter(costs, budget)
                ledger = EvaluatorLedger()
                lab = EvaluatorLaboratory(
                    blind_laboratory(
                        case.lab_factory(),
                        experiments=experiments,
                        available=available,
                        meter=meter,
                    ),
                    ledger,
                )
                answer = self.execute({**case.request, "arm": arm, "budget": budget}, lab)
                if meter.spent != answer.spent:
                    raise RuntimeError(
                        f"{case.world_id}:{arm}:{budget}: the meter ({meter.spent}) and the arm "
                        f"({answer.spent}) disagree"
                    )
                events = ledger.events()
                j = ev14.judge_answer(judge, rescorer, rescorer13, events, answer, by_id)
                tests = rescore(rescorer, events)
                ref = dg.refutations(rescorer, events, tests, is_truth)
                cause, diagnosis = "", None
                if (
                    self.diagnose
                    and supportable
                    and truth_id
                    and j["level"] != SUPPORTED
                    and case.true_mean is not None
                ):
                    d = dg.diagnose(
                        rescorer, events, tests, truth_id, case.true_mean, budget, meter.spent
                    )
                    cause, diagnosis = d.cause, d.as_json()
                claimed = frozenset(by_id[i].fingerprint for i in answer.claim if i in by_id)
                out.append(
                    RunRecord(
                        setting=case.setting,
                        world_id=case.world_id,
                        kind=case.kind,
                        arm=arm,
                        budget=budget,
                        spent=meter.spent,
                        outcome=answer.outcome,
                        answer=answer.answer_kind,
                        claim=answer.claim,
                        category=j["category"],
                        level=j["level"],
                        v13_level=j["v13_level"],
                        asserted=j["asserted"],
                        proposal_hit=j["proposal_hit"],
                        own_correct=j["own_correct"],
                        own_error=j["own_error"],
                        own_category=case.own(answer.outcome, answer.claim, claimed),
                        open_rivals=j["open_rivals"],
                        reason=answer.reason,
                        registrations=sum(1 for e in events if e.kind == REGISTER),
                        aliased=case.aliased,
                        chain_head=ledger.head,
                        digest=answer.digest,
                        refuted=ref.refuted,
                        refuted_incorrect=ref.incorrect,
                        refuted_by_kind=ref.by_kind,
                        runs=ref.runs,
                        cause=cause,
                        supportable=supportable,
                        diagnosis=diagnosis,
                    )
                )
        return out


# -- summarising ------------------------------------------------------------------------------


def table(records: Sequence[RunRecord]) -> dict[str, Any]:
    """v1.4's table plus the efficiency columns and the abstention breakdown."""
    out = ev14.table(records)
    refuted = sum(r.refuted - r.refuted_incorrect for r in records)
    runs = sum(r.runs for r in records)
    spent = sum(r.spent for r in records)
    out["refuted_correct"] = refuted
    out["refuted_incorrect"] = sum(r.refuted_incorrect for r in records)
    out["runs"] = runs
    out["refuted_per_run"] = round(refuted / runs, 4) if runs else 0.0
    out["refuted_per_cost_unit"] = round(refuted / spent, 4) if spent else 0.0
    supportable = [r for r in records if r.supportable]
    out["supportable"] = len(supportable)
    out["supportable_supported"] = sum(r.level == SUPPORTED for r in supportable)
    out["refuted_by_kind"] = {
        k: sum(r.refuted_by_kind.get(k, 0) for r in records) for k in ("null", "catalog", "grammar")
    }
    abstained = [r for r in records if r.answer == "NONE" and r.cause]
    causes = {c: sum(r.cause == c for r in abstained) for c in dg.CAUSES}
    out["abstention_causes"] = causes
    buckets: dict[str, int] = {}
    for c, n in causes.items():
        buckets[dg.BUCKETS[c]] = buckets.get(dg.BUCKETS[c], 0) + n
    out["abstention_buckets"] = dict(sorted(buckets.items()))
    out["correct_abstention"] = buckets.get("correct", 0)
    out["avoidable_abstention"] = buckets.get("avoidable", 0)
    out["unsupported_claim_causes"] = {
        c: n
        for c in dg.CAUSES
        if (n := sum(r.cause == c for r in records if r.answer != "NONE" and r.cause))
    }
    return out


def parts(records: Sequence[RunRecord]) -> dict[str, list[RunRecord]]:
    if records and records[0].setting == "held_out":
        return {
            "primary": [r for r in records if not r.aliased],
            "aliased": [r for r in records if r.aliased],
        }
    return {"all": list(records)}


def summarize(
    records: Sequence[RunRecord], budgets: Sequence[int], arms: Sequence[str] = ARM_IDS
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "comparison_basis": "EQUAL_CAP: every arm had the same cap; realized costs differ by "
        "world and arm (see realized_cost and the per-world matched comparisons)"
    }
    for budget in budgets:
        at: dict[str, Any] = {}
        for arm in arms:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            if mine:
                at[arm] = {k: table(v) for k, v in parts(mine).items() if v}
        out[str(budget)] = at
    return out


def records_as_json(records: Sequence[RunRecord]) -> list[dict[str, Any]]:
    rows = ev14.records_as_json(records)
    index = {(r["setting"], r["world_id"]): r for r in rows}
    for r in records:
        entry = index[(r.setting, r.world_id)]["arms"][r.arm][str(r.budget)]
        entry.update(
            refuted=r.refuted,
            refuted_incorrect=r.refuted_incorrect,
            refuted_by_kind=dict(r.refuted_by_kind),
            runs=r.runs,
            cause=r.cause,
            supportable=r.supportable,
        )
        if r.diagnosis is not None:
            entry["diagnosis"] = dict(r.diagnosis)
    return rows


__all__ = [
    "ARM_IDS",
    "CATEGORIES",
    "CREDITED",
    "ERRORS",
    "Evaluator",
    "RunRecord",
    "WorldCase",
    "parts",
    "records_as_json",
    "run_arm",
    "summarize",
    "table",
]
