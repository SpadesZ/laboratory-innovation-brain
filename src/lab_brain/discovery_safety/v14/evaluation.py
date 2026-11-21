"""Arms B4, B6 and B7 on the same worlds, scored under SAI 3.5 candidate.5 by the v1.4 rule.

    B4   the v1.1 gate (the offline safety BASELINE)      B6   the v1.3 gate, unchanged
    B7   the v1.4 gate (`safe_investigate_v14`)

As in v1.3: the arm runs in its own process and hands back only an `ArmAnswer`; the evaluator owns
the world, the meter and the hash-chained ledger and re-derives everything from them. The level is
the evaluator's v1.4 verdict for EVERY arm (one evaluator, one rule); the v1.3 rule's level is
recorded beside (`v13_level`) so that the effect of the rule change on each arm is visible.

A `WorldCase` carries a `Judge` built by the composition root (a v1.3-style synthetic world, or a
sealed hidden world after its reveal); the arm process never sees it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe
from lab_brain.discovery.model import CLAIM_OUTCOMES, NULL_HYPOTHESIS, Budget, Hypothesis, Outcome
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v12.evaluation import Judge
from lab_brain.discovery_safety.v12.gate import grammar_shapes
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.model import SafeRunV12
from lab_brain.discovery_safety.v13 import evaluation as ev13
from lab_brain.discovery_safety.v13.gate import safe_investigate_v13
from lab_brain.discovery_safety.v13.ledger import (
    REGISTER,
    EvaluatorLaboratory,
    EvaluatorLedger,
    LedgerEvent,
    verify_chain,
)
from lab_brain.discovery_safety.v13.model import EVALUATOR_RULE, SAFETY_V13, ArmAnswer
from lab_brain.discovery_safety.v13.rule import Rescorer, rescore, verdict
from lab_brain.discovery_safety.v14.gate import safe_investigate_v14
from lab_brain.discovery_safety.v14.model import (
    EVALUATOR_RULE_V14,
    SAFETY_V14,
    EvaluatorRuleV14,
)
from lab_brain.discovery_safety.v14.rule import RescorerV14, verdict_v14

ARM_IDS = ("B4", "B6", "B7")
CATEGORIES = ev13.CATEGORIES
CREDITED = ev13.CREDITED
ERRORS = ev13.ERRORS
UNANSWERED = ev13.UNANSWERED
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
    elif arm == "B6":
        run = safe_investigate_v13(**kwargs, safety=SAFETY_V13, grammar=grammar)
    elif arm == "B7":
        run = safe_investigate_v14(**kwargs, safety=SAFETY_V14, grammar=grammar)
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
class WorldCase:
    """One world as the evaluator sees it (the truth stays here, inside `judge` and `own`)."""

    setting: str
    world_id: str
    kind: str
    aliased: bool
    lab_factory: Callable[[], Laboratory]
    engine_catalog: DiscoveryCatalog
    engine_oracle: SeparationOracle
    full_catalog: DiscoveryCatalog
    #: The evaluator's judge for this world, given the hypotheses the arm holds.
    judge: Callable[[Sequence[Hypothesis]], Judge]
    #: What the arm process needs to rebuild its catalog and oracle (never the truth).
    request: Mapping[str, Any]
    #: v1.1's face-value category of an answer: (outcome, claimed ids, claimed fingerprints).
    own: Callable[[str, tuple[str, ...], frozenset[str]], str]


@dataclass(frozen=True)
class RunRecord:
    setting: str
    world_id: str
    kind: str
    arm: str
    budget: int
    spent: int
    outcome: str
    answer: str
    claim: tuple[str, ...]
    category: str
    level: str
    #: The level under v1.3's evaluator rule (reported beside; not the scoring rule).
    v13_level: str
    asserted: bool
    proposal_hit: bool
    own_correct: bool
    own_error: bool
    own_category: str
    open_rivals: int
    reason: str
    registrations: int
    aliased: bool
    chain_head: str
    digest: str


def judge_answer(
    judge: Judge,
    rescorer: RescorerV14,
    rescorer13: Rescorer,
    events: Sequence[LedgerEvent],
    answer: ArmAnswer,
    by_id: Mapping[str, Hypothesis],
) -> dict[str, Any]:
    """Candidate.5 category under the v1.4 verdict; v1.3's level beside."""
    verify_chain(events)
    tests = rescore(rescorer, events)
    if answer.answer_kind == "NONE":
        category = ev13.FALSE_NULL if judge.any_held_matches() else ev13.CORRECT_ABSTENTION
        return {
            "category": category,
            "level": NONE,
            "v13_level": NONE,
            "asserted": False,
            "proposal_hit": False,
            "own_correct": category == ev13.CORRECT_ABSTENTION,
            "own_error": False,
            "open_rivals": 0,
        }
    new = answer.answer_kind == "NEW_MECHANISM"
    members: list[Hypothesis | None]
    if new:
        members = [rescorer.answer_hypothesis(answer.new_mechanism, events, "answer")]
        identities = [answer.new_mechanism]
    else:
        members = [by_id.get(i) for i in answer.claim]
        identities = [
            m.fingerprint if m is not None else f"unknown:{i}"
            for m, i in zip(members, answer.claim, strict=True)
        ]
    verdicts = [verdict_v14(rescorer, events, tests, i) for i in identities]
    complete = all(m is not None for m in members)
    level = SUPPORTED if complete and all(v.supported for v in verdicts) else PROPOSAL
    tests13 = rescore(rescorer13, events)
    v13 = complete and all(verdict(rescorer13, events, tests13, i).supported for i in identities)
    known = [m for m in members if m is not None]
    matches = len(known) == len(members) and all(judge.matches(m) for m in known)
    asserted = not (answer.labelled_proposal and not answer.acted_on)
    out: dict[str, Any] = {
        "v13_level": SUPPORTED if v13 else PROPOSAL,
        "own_correct": matches,
        "own_error": not matches,
        "open_rivals": sum(len(v.open_rivals) for v in verdicts),
        "asserted": asserted,
    }
    if level == PROPOSAL:
        out.update(
            category=ev13.UNSUPPORTED_CLAIM if asserted else ev13.PROPOSAL_ONLY,
            level=PROPOSAL,
            proposal_hit=matches,
        )
        return out
    if new:
        h0 = known[0]
        category = (
            judge.catalog_category([h0])
            if h0.fingerprint in judge.held_prints
            else (ev13.VALIDATED_NEW if judge.matches(h0) else ev13.WRONG_CLAIM)
        )
    else:
        category = judge.catalog_category(known)
    out.update(category=category, level=SUPPORTED, proposal_hit=False)
    return out


Execute = Callable[[Mapping[str, Any], EvaluatorLaboratory], ArmAnswer]


class Evaluator:
    """Runs every arm at every cap on one world and scores each run from its own ledger."""

    def __init__(
        self,
        execute: Execute,
        grammar: TermGrammar | None,
        rule: EvaluatorRuleV14 = EVALUATOR_RULE_V14,
        arms: Sequence[str] = ARM_IDS,
    ) -> None:
        self.execute = execute
        self.grammar = grammar
        self.rule = rule
        self.arms = tuple(arms)

    def run(self, case: WorldCase, budgets: Sequence[int]) -> list[RunRecord]:
        experiments = ev13.all_experiments(case.full_catalog)
        costs = {k: e.cost for k, e in experiments.items()}
        universe = hypothesis_universe(case.engine_catalog)
        held = distinct_forward_models(universe)
        by_id = {h.hypothesis_id: h for h in universe}
        by_id[NULL_HYPOTHESIS.hypothesis_id] = NULL_HYPOTHESIS
        judge = case.judge(held)
        shapes = grammar_shapes(self.grammar) if self.grammar is not None else ()
        available = tuple(e.experiment_id for e in case.engine_oracle.available)
        rescorer = RescorerV14(
            held, shapes, experiments, self.rule, case.engine_oracle.distinguishable, available
        )
        rescorer13 = Rescorer(
            held, shapes, experiments, EVALUATOR_RULE, case.engine_oracle.distinguishable
        )
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
                j = judge_answer(judge, rescorer, rescorer13, events, answer, by_id)
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
                    )
                )
        return out


# -- summarising ------------------------------------------------------------------------------


def table(records: Sequence[RunRecord]) -> dict[str, Any]:
    """Candidate.5 counts, the face-value columns, and the realized-cost distribution."""
    from lab_brain.discovery_safety.v14.costmatch import cost_distribution

    n = len(records)
    out: dict[str, Any] = {"n": n}
    out["outcomes"] = {c: sum(r.category == c for r in records) for c in CATEGORIES}
    out["credited"] = sum(r.category in CREDITED for r in records)
    out["errors"] = sum(r.category in ERRORS for r in records)
    out["supported"] = sum(r.level == SUPPORTED for r in records)
    out["supported_errors"] = sum(r.category in (ev13.FORCE_FIT, ev13.WRONG_CLAIM) for r in records)
    out["unsupported_claim"] = sum(r.category == ev13.UNSUPPORTED_CLAIM for r in records)
    out["unsupported_claim_hits"] = sum(
        r.category == ev13.UNSUPPORTED_CLAIM and r.proposal_hit for r in records
    )
    out["v13_rule_supported"] = sum(r.v13_level == SUPPORTED for r in records)
    out["own_correct"] = sum(r.own_correct for r in records)
    out["own_error"] = sum(r.own_error for r in records)
    out["own_category"] = {
        c: sum(r.own_category == c for r in records) for c in ev13.OWN_CATEGORIES
    }
    reasons: dict[str, int] = {}
    for r in records:
        if r.answer == "NONE":
            reasons[r.reason] = reasons.get(r.reason, 0) + 1
    out["abstention_reasons"] = dict(sorted(reasons.items()))
    out["realized_cost"] = cost_distribution(
        [r.spent for r in records], records[0].budget if records else 0
    )
    if any(r.category in CREDITED and r.level != SUPPORTED for r in records):
        raise AssertionError("an answer below SUPPORTED was credited")
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
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        entry = out.setdefault(
            f"{r.setting}:{r.world_id}",
            {
                "setting": r.setting,
                "world_id": r.world_id,
                "kind": r.kind,
                "aliased": r.aliased,
                "arms": {},
            },
        )
        entry["arms"].setdefault(r.arm, {})[str(r.budget)] = {
            "answer": r.answer,
            "category": r.category,
            "level": r.level,
            "v13_level": r.v13_level,
            "asserted": r.asserted,
            "proposal_hit": r.proposal_hit,
            "own_correct": r.own_correct,
            "own_error": r.own_error,
            "own_category": r.own_category,
            "claim": list(r.claim),
            "outcome": r.outcome,
            "reason": r.reason,
            "spent": r.spent,
            "registrations": r.registrations,
            "open_rivals": r.open_rivals,
            "chain_head": r.chain_head,
            "digest": r.digest,
        }
    return list(out.values())


__all__ = [
    "ARM_IDS",
    "CATEGORIES",
    "CREDITED",
    "ERRORS",
    "Evaluator",
    "RunRecord",
    "WorldCase",
    "judge_answer",
    "parts",
    "records_as_json",
    "run_arm",
    "summarize",
    "table",
]
