"""Arms B2, B4, B5 and B6 on the same worlds, scored under SAI 3.5 candidate.5 by the evaluator.

    B2   the frozen engine                   B4   the v1.1 gate (the offline safety BASELINE)
    B5   the v1.2 gate, unchanged            B6   the v1.3 gate (`safe_investigate_v13`)

THE ARM'S SIDE (`run_arm`) builds and runs one arm against whatever laboratory it is handed -- in
the evaluation, a `ProxyLaboratory` in a separate process (`boundary.py`) -- and returns an
`ArmAnswer`: what it answers, its own stance, its own spend. Nothing else crosses back.

THE EVALUATOR'S SIDE (`Evaluator.run`) owns the world, the meter and the ledger, serves the arm,
then re-derives everything from its own ledger (`rule.rescore`, `rule.verdict`) and the truth:

    level      SUPPORTED iff every identity of the answer has the evaluator's verdict: a complete
               registration that passed and is risky under the evaluator's own prediction and
               alternatives, Holm over all its registrations rejecting none, and no open rival
               (`rule.verdict`); otherwise PROPOSAL. No answer: NONE. (SAI candidate.5
               `verified_evidence`: no quantity deciding pass or riskiness is arm-supplied, so
               `arm_supplied_inputs` is False for this rule; v1.2's own payload rule -- reported
               beside for B5 as `v12_level` -- has arm-supplied inputs and is PROPOSAL by
               candidate.5 whatever it re-scores to.)
    category   candidate.5 `classify_outcome` with `AnswerStance`: no answer -> FALSE_NULL /
               CORRECT_ABSTENTION; an answer below SUPPORTED -> PROPOSAL_ONLY only if the arm
               labelled it a proposal and nothing acted on it, else UNSUPPORTED_CLAIM (an error,
               whether or not it matches the truth: the match is reported beside); a SUPPORTED
               answer -> EXACT_IDENTIFICATION, INDISTINGUISHABLE_ALTERNATIVE,
               VALIDATED_NEW_MECHANISM, FORCE_FIT or WRONG_CLAIM (as v1.2's `Judge`)
    face value the arm's answer taken at its word, judged against the truth (`own_correct`,
               `own_error`), and v1.1's legacy categories (`own_category`), so that the v1.1
               baseline is reported in its own terms too

COMPARISONS (`matched_comparisons`): for a pair (Y, X) and each cap of X, the cap of Y whose mean
realized cost is nearest; differences Y - X paired on identical worlds with paired-bootstrap 95 %
intervals; the pair is COST_MATCHED only if the interval of the mean realized-cost difference lies
within +-`cost_tolerance` units, else COST_UNMATCHED. Every answer is committed when the arm stops
(commit-at-termination); the realized cost is the evaluator's meter.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe, investigate
from lab_brain.discovery.metrics import Scorer, rate
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    Budget,
    DiscoveryResult,
    ExperimentSpec,
    Hypothesis,
    Outcome,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import WorldSpec
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.evaluation import (
    CORRECT_IDENTIFICATION,
    NO_CLAIM,
)
from lab_brain.discovery_safety.v11.evaluation import (
    FALSE_NULL as OWN_FALSE_NULL,
)
from lab_brain.discovery_safety.v11.evaluation import (
    FORCE_FIT as OWN_FORCE_FIT,
)
from lab_brain.discovery_safety.v11.evaluation import (
    INDISTINGUISHABLE_ALTERNATIVE as OWN_INDISTINGUISHABLE,
)
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v12.evaluation import Judge
from lab_brain.discovery_safety.v12.gate import grammar_shapes, safe_investigate_v12
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.ledger import PredictionLedger
from lab_brain.discovery_safety.v12.ledger import rescore as rescore_v12
from lab_brain.discovery_safety.v12.ledger import supported as supported_v12
from lab_brain.discovery_safety.v12.model import SAFETY_V12, SafeRunV12
from lab_brain.discovery_safety.v13.gate import safe_investigate_v13
from lab_brain.discovery_safety.v13.ledger import (
    REGISTER,
    EvaluatorLaboratory,
    EvaluatorLedger,
    LedgerEvent,
    verify_chain,
)
from lab_brain.discovery_safety.v13.model import (
    EVALUATOR_RULE,
    PLAN,
    SAFETY_V13,
    ArmAnswer,
    EvaluationPlanV13,
    EvaluatorRule,
)
from lab_brain.discovery_safety.v13.rule import Rescorer, rescore, verdict

ARM_IDS = ("B2", "B4", "B5", "B6")

EXACT = "EXACT_IDENTIFICATION"
INDISTINGUISHABLE = "INDISTINGUISHABLE_ALTERNATIVE"
VALIDATED_NEW = "VALIDATED_NEW_MECHANISM"
PROPOSAL_ONLY = "PROPOSAL_ONLY"
UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
CORRECT_ABSTENTION = "CORRECT_ABSTENTION"
FALSE_NULL = "FALSE_NULL"
FORCE_FIT = "FORCE_FIT"
WRONG_CLAIM = "WRONG_CLAIM"
#: SAI candidate.5 outcomes (UNRESOLVED_ALTERNATIVE cannot occur: distinguishability is binary).
CATEGORIES = (
    EXACT,
    INDISTINGUISHABLE,
    VALIDATED_NEW,
    PROPOSAL_ONLY,
    UNSUPPORTED_CLAIM,
    CORRECT_ABSTENTION,
    FALSE_NULL,
    FORCE_FIT,
    WRONG_CLAIM,
)
CREDITED = (EXACT, INDISTINGUISHABLE, VALIDATED_NEW)
ERRORS = (FORCE_FIT, WRONG_CLAIM, UNSUPPORTED_CLAIM)
UNANSWERED = (PROPOSAL_ONLY, CORRECT_ABSTENTION, FALSE_NULL)
SUPPORTED = "SUPPORTED"
PROPOSAL = "PROPOSAL"
NONE = "NONE"
OWN_CATEGORIES = (
    CORRECT_IDENTIFICATION,
    OWN_INDISTINGUISHABLE,
    OWN_FORCE_FIT,
    OWN_FALSE_NULL,
    NO_CLAIM,
)
EQUAL_CAP = (
    "EQUAL_CAP -- COST_UNMATCHED unless stated: every arm had the same cap; realized costs differ "
    "by arm (see realized_cost)"
)
MATCHED_BASIS = (
    "MATCHED_REALIZED_COST -- commit-at-termination; for each cap of X, the cap of Y with the "
    "nearest mean realized cost; differences Y - X paired on identical worlds, paired-bootstrap "
    "95 % intervals; COST_MATCHED iff the interval of the mean realized-cost difference lies "
    "within +-cost_tolerance units, else COST_UNMATCHED"
)


# -- the arm's side ---------------------------------------------------------------------------


def _reason(result: DiscoveryResult, run: Any) -> str:
    if result.outcome in CLAIM_OUTCOMES:
        return ""
    if run is None or run.assessment.reason is None:
        return result.outcome.value
    if run.assessment.reason.value == "NO_ENGINE_CLAIM":
        return f"NO_ENGINE_CLAIM:{run.assessment.engine_outcome.value}"
    return str(run.assessment.reason.value)


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
    run: Any = None
    kwargs: dict[str, Any] = {
        "arm": arm,
        "catalog": catalog,
        "oracle": oracle,
        "protocol": DISCOVERY,
        "budget": Budget(budget),
        "lab": lab,
    }
    if arm == "B2":
        result = investigate(**kwargs)
    elif arm == "B4":
        run = safe_investigate_v11(**kwargs)
        result = run.result
    elif arm == "B5":
        run = safe_investigate_v12(**kwargs, safety=SAFETY_V12, grammar=grammar)
        result = run.result
    elif arm == "B6":
        run = safe_investigate_v13(**kwargs, safety=SAFETY_V13, grammar=grammar)
        result = run.result
    else:
        raise ValueError(f"unknown arm {arm}")
    answered = ""
    proposal = ""
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
        # every arm here states its final answer as its conclusion (an endorsement, the engine's
        # claim, or an answered new mechanism); a grammar candidate left beside an abstention is
        # not the answer
        labelled_proposal=False,
        acted_on=kind != "NONE",
        spent=result.spent,
        reason=_reason(result, run),
        digest=result.digest,
    )


# -- the evaluator's side ---------------------------------------------------------------------


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
    #: Candidate.5 outcome and the evaluator's level.
    category: str
    level: str
    asserted: bool
    #: Below SUPPORTED: whether the answer matches the truth anyway (never credited).
    proposal_hit: bool
    #: The answer at face value, judged against the truth.
    own_correct: bool
    own_error: bool
    #: v1.1's legacy category of the answer at face value.
    own_category: str
    #: B5 only: the level v1.2's own payload rule re-scores to (arm-supplied inputs).
    v12_level: str
    grammar_proposal: bool
    grammar_proposal_hit: bool
    open_rivals: tuple[str, ...]
    reason: str
    registrations: int
    void_registrations: int
    declared_digest_mismatches: int
    replicate_mismatches: int
    aliased: bool
    chain_head: str
    digest: str


def own_category_v11(
    scorer: Scorer,
    world: WorldSpec,
    outcome: str,
    claimed: frozenset[str],
    oracle: SeparationOracle,
) -> str:
    """v1.1's `classify`, re-implemented on the evaluator's side from the answer's outcome and the
    claimed forward models (the arm's result object never crosses the boundary)."""
    if Outcome(outcome) not in CLAIM_OUTCOMES:
        return NO_CLAIM
    truth = world.truth_hypothesis(scorer.catalog)
    if truth is not None:
        near, simple = scorer.truth_class(truth, oracle)
        if truth.fingerprint in claimed and claimed <= near and simple <= claimed:
            return CORRECT_IDENTIFICATION
    if Outcome(outcome) is Outcome.NO_EFFECT_BEYOND_NOISE and (truth is None or not truth.is_null):
        return OWN_FALSE_NULL
    if truth is not None:
        near, _ = scorer.truth_class(truth, oracle)
        if claimed and claimed <= near:
            return OWN_INDISTINGUISHABLE
    return OWN_FORCE_FIT


def all_experiments(catalog: DiscoveryCatalog) -> dict[str, ExperimentSpec]:
    return {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }


Execute = Callable[[Mapping[str, Any], EvaluatorLaboratory], ArmAnswer]


@dataclass
class WorldCase:
    """One world as the evaluator sees it (the truth stays here)."""

    setting: str
    world: WorldSpec
    kind: str
    aliased: bool
    lab_factory: Callable[[], Laboratory]
    engine_catalog: DiscoveryCatalog
    engine_oracle: SeparationOracle
    full_catalog: DiscoveryCatalog
    full_oracle: SeparationOracle
    truth: Hypothesis | None
    #: What the arm process needs to rebuild its catalog and oracle (never the truth).
    request: Mapping[str, Any]
    #: v1.1's face-value category of an answer: (outcome, claimed ids, claimed fingerprints).
    own: Callable[[str, tuple[str, ...], frozenset[str]], str]


def judge_answer(
    case: WorldCase,
    judge: Judge,
    rescorer: Rescorer,
    events: Sequence[LedgerEvent],
    answer: ArmAnswer,
    by_id: Mapping[str, Hypothesis],
    v12_ledger: PredictionLedger,
    rule: EvaluatorRule,
) -> dict[str, Any]:
    verify_chain(events)
    tests = rescore(rescorer, events)
    out: dict[str, Any] = {
        "open_rivals": (),
        "v12_level": "",
        "grammar_proposal_hit": False,
    }
    if answer.grammar_proposal:
        h = rescorer.answer_hypothesis(answer.grammar_proposal, events, "proposal")
        out["grammar_proposal_hit"] = h is not None and judge.matches(h)
    if answer.answer_kind == "NONE":
        category = FALSE_NULL if judge.any_held_matches() else CORRECT_ABSTENTION
        out.update(
            category=category,
            level=NONE,
            asserted=False,
            proposal_hit=False,
            own_correct=category == CORRECT_ABSTENTION,
            own_error=False,
        )
        return out
    members: list[Hypothesis | None]
    identities: list[str]
    new = answer.answer_kind == "NEW_MECHANISM"
    if new:
        h = rescorer.answer_hypothesis(answer.new_mechanism, events, "answer")
        members, identities = [h], [answer.new_mechanism]
    else:
        members = [by_id.get(i) for i in answer.claim]
        identities = [
            m.fingerprint if m is not None else f"unknown:{i}"
            for m, i in zip(members, answer.claim, strict=True)
        ]
    verdicts = [verdict(rescorer, events, tests, i) for i in identities]
    supported = all(m is not None for m in members) and all(v.supported for v in verdicts)
    level = SUPPORTED if supported else PROPOSAL
    out["open_rivals"] = tuple(sorted({r for v in verdicts for r in v.open_rivals}))
    if answer.arm == "B5":
        v12_tests = rescore_v12(v12_ledger, rescorer.experiments)
        ok = all(supported_v12(v12_tests, i, rule.alpha) for i in identities)
        out["v12_level"] = SUPPORTED if ok else PROPOSAL
    known = [m for m in members if m is not None]
    matches = len(known) == len(members) and all(judge.matches(m) for m in known)
    asserted = not (answer.labelled_proposal and not answer.acted_on)
    out["own_correct"] = matches
    out["own_error"] = not matches
    if level == PROPOSAL:
        out.update(
            category=UNSUPPORTED_CLAIM if asserted else PROPOSAL_ONLY,
            level=PROPOSAL,
            asserted=asserted,
            proposal_hit=matches,
        )
        return out
    held = list(known)
    if new:
        h0 = held[0]
        category = (
            judge.catalog_category([h0])
            if h0.fingerprint in judge.held_prints
            else (VALIDATED_NEW if judge.matches(h0) else WRONG_CLAIM)
        )
    else:
        category = judge.catalog_category(held)
    out.update(category=category, level=SUPPORTED, asserted=asserted, proposal_hit=False)
    return out


class Evaluator:
    """Runs every arm at every cap on one world and scores each run from its own ledger."""

    def __init__(
        self,
        execute: Execute,
        grammar: TermGrammar | None,
        rule: EvaluatorRule = EVALUATOR_RULE,
        arms: Sequence[str] = ARM_IDS,
    ) -> None:
        self.execute = execute
        self.grammar = grammar
        self.rule = rule
        self.arms = tuple(arms)

    def run(self, case: WorldCase, budgets: Sequence[int]) -> list[RunRecord]:
        experiments = all_experiments(case.full_catalog)
        costs = {k: e.cost for k, e in experiments.items()}
        universe = hypothesis_universe(case.engine_catalog)
        held = distinct_forward_models(universe)
        by_id = {h.hypothesis_id: h for h in universe}
        by_id[NULL_HYPOTHESIS.hypothesis_id] = NULL_HYPOTHESIS
        judge = Judge(case.truth, dict(case.world.truth), held, case.full_oracle)
        shapes = grammar_shapes(self.grammar) if self.grammar is not None else ()
        rescorer = Rescorer(
            held, shapes, experiments, self.rule, case.engine_oracle.distinguishable
        )
        available = tuple(e.experiment_id for e in case.engine_oracle.available)
        out = []
        for budget in budgets:
            for arm in self.arms:
                meter = CostMeter(costs, budget)
                ledger = EvaluatorLedger()
                v12 = PredictionLedger()
                lab = EvaluatorLaboratory(
                    blind_laboratory(
                        case.lab_factory(),
                        experiments=experiments,
                        available=available,
                        meter=meter,
                    ),
                    ledger,
                    v12,
                )
                answer = self.execute({**case.request, "arm": arm, "budget": budget}, lab)
                if meter.spent != answer.spent:
                    raise RuntimeError(
                        f"{case.world.world_id}:{arm}:{budget}: the meter ({meter.spent}) and the "
                        f"arm ({answer.spent}) disagree"
                    )
                events = ledger.events()
                verdicts = judge_answer(
                    case, judge, rescorer, events, answer, by_id, v12, self.rule
                )
                claimed = frozenset(by_id[i].fingerprint for i in answer.claim if i in by_id)
                tests = rescore(rescorer, events)
                out.append(
                    RunRecord(
                        setting=case.setting,
                        world_id=case.world.world_id,
                        kind=case.kind,
                        arm=arm,
                        budget=budget,
                        spent=meter.spent,
                        outcome=answer.outcome,
                        answer=answer.answer_kind,
                        claim=answer.claim,
                        category=verdicts["category"],
                        level=verdicts["level"],
                        asserted=verdicts["asserted"],
                        proposal_hit=verdicts["proposal_hit"],
                        own_correct=verdicts["own_correct"],
                        own_error=verdicts["own_error"],
                        own_category=case.own(answer.outcome, answer.claim, claimed),
                        v12_level=verdicts["v12_level"],
                        grammar_proposal=bool(answer.grammar_proposal),
                        grammar_proposal_hit=verdicts["grammar_proposal_hit"],
                        open_rivals=verdicts["open_rivals"],
                        reason=answer.reason,
                        registrations=sum(1 for e in events if e.kind == REGISTER),
                        void_registrations=sum(1 for t in tests if t.void),
                        declared_digest_mismatches=sum(
                            1 for t in tests if t.declared_digest_matches is False
                        ),
                        replicate_mismatches=sum(
                            1 for e in events if e.kind == "MEASURE" and e.replicate != e.count
                        ),
                        aliased=case.aliased,
                        chain_head=ledger.head,
                        digest=answer.digest,
                    )
                )
        return out


# -- summarising ------------------------------------------------------------------------------


def _rate(k: int, n: int) -> dict[str, Any]:
    return rate([True] * k + [False] * (n - k))


def realized_cost(records: Sequence[RunRecord]) -> dict[str, Any]:
    spent = sorted(r.spent for r in records)
    if not spent:
        return {"n": 0}
    n = len(spent)
    median = float(spent[n // 2]) if n % 2 else (spent[n // 2 - 1] + spent[n // 2]) / 2.0
    return {"n": n, "mean": round(sum(spent) / n, 4), "median": median}


def table(records: Sequence[RunRecord]) -> dict[str, Any]:
    """Candidate.5 `outcome_report` counts plus the face-value and cost columns."""
    n = len(records)
    out: dict[str, Any] = {"n": n}
    out["outcomes"] = {c: _rate(sum(r.category == c for r in records), n) for c in CATEGORIES}
    out["asserted"] = sum(r.category not in UNANSWERED for r in records)
    out["supported"] = sum(r.level == SUPPORTED for r in records)
    out["unsupported_claim"] = sum(r.category == UNSUPPORTED_CLAIM for r in records)
    out["proposal_only"] = sum(r.category == PROPOSAL_ONLY for r in records)
    out["errors"] = sum(r.category in ERRORS for r in records)
    out["credited"] = sum(r.category in CREDITED for r in records)
    out["unsupported_claim_hits"] = sum(
        r.category == UNSUPPORTED_CLAIM and r.proposal_hit for r in records
    )
    out["own_correct"] = sum(r.own_correct for r in records)
    out["own_error"] = sum(r.own_error for r in records)
    out["own_category"] = {c: sum(r.own_category == c for r in records) for c in OWN_CATEGORIES}
    out["v12_level_supported"] = sum(r.v12_level == SUPPORTED for r in records)
    out["grammar_proposals"] = sum(r.grammar_proposal for r in records)
    out["grammar_proposal_hits"] = sum(r.grammar_proposal_hit for r in records)
    reasons: dict[str, int] = {}
    for r in records:
        if r.answer == "NONE":
            reasons[r.reason] = reasons.get(r.reason, 0) + 1
    out["abstention_reasons"] = dict(sorted(reasons.items()))
    out["realized_cost"] = realized_cost(records)
    out["integrity"] = {
        "void_registrations": sum(r.void_registrations for r in records),
        "declared_digest_mismatches": sum(r.declared_digest_mismatches for r in records),
        "replicate_mismatches": sum(r.replicate_mismatches for r in records),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
    }
    if any(r.category in CREDITED and r.level != SUPPORTED for r in records):
        raise AssertionError("an answer below SUPPORTED was credited")
    if any(r.category == PROPOSAL_ONLY and r.asserted for r in records):
        raise AssertionError("an asserted answer was scored as a proposal")
    return out


def parts(records: Sequence[RunRecord]) -> dict[str, list[RunRecord]]:
    if records and records[0].setting == "held_out":
        return {
            "primary": [r for r in records if not r.aliased],
            "aliased": [r for r in records if r.aliased],
        }
    return {"all": list(records)}


def summarize(records: Sequence[RunRecord], budgets: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {"comparison_basis": EQUAL_CAP}
    for budget in budgets:
        at: dict[str, Any] = {}
        for arm in ARM_IDS:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            if mine:
                at[arm] = {k: table(v) for k, v in parts(mine).items()}
        out[str(budget)] = at
    return out


# -- matched realized cost --------------------------------------------------------------------

METRICS: dict[str, Callable[[RunRecord], float]] = {
    "credited": lambda r: float(r.category in CREDITED),
    "errors_c5": lambda r: float(r.category in ERRORS),
    "supported_errors": lambda r: float(r.category in (FORCE_FIT, WRONG_CLAIM)),
    "own_correct": lambda r: float(r.own_correct),
    "own_error": lambda r: float(r.own_error),
}


def _indices(seed: str, resample: int, n: int) -> list[int]:
    """n indices in [0, n) for one bootstrap resample: SHA-256 in counter mode over a fixed seed
    string (deterministic; this package uses no random-number module)."""
    out: list[int] = []
    block = 0
    while len(out) < n:
        digest = hashlib.sha256(f"{seed}/{resample}/{block}".encode()).digest()
        for i in range(0, len(digest), 4):
            if len(out) < n:
                out.append(int.from_bytes(digest[i : i + 4], "big") % n)
        block += 1
    return out


def _bootstrap(
    diffs: Mapping[str, Sequence[float]], resamples: int, seed: str
) -> dict[str, tuple[float, float, float]]:
    """Paired bootstrap (resampling worlds) of the mean of each difference vector."""
    names = sorted(diffs)
    n = len(diffs[names[0]]) if names else 0
    if n == 0:
        return dict.fromkeys(names, (0.0, 0.0, 0.0))
    draws: dict[str, list[float]] = {k: [] for k in names}
    for b in range(resamples):
        idx = _indices(seed, b, n)
        for k in names:
            v = diffs[k]
            draws[k].append(math.fsum(v[i] for i in idx) / n)
    out = {}
    for k in names:
        d = sorted(draws[k])
        lo = d[int(0.025 * (resamples - 1))]
        hi = d[math.ceil(0.975 * (resamples - 1))]
        out[k] = (round(math.fsum(diffs[k]) / n, 6), round(lo, 6), round(hi, 6))
    return out


def matched_comparisons(
    records: Sequence[RunRecord], plan: EvaluationPlanV13 = PLAN, label: str = ""
) -> dict[str, Any]:
    out: dict[str, Any] = {"comparison_basis": MATCHED_BASIS, "pairs": []}
    by: dict[tuple[str, int], dict[str, RunRecord]] = {}
    for r in records:
        by.setdefault((r.arm, r.budget), {})[r.world_id] = r
    budgets = sorted({r.budget for r in records})

    def mean_cost(arm: str, b: int) -> float:
        cell = by.get((arm, b), {})
        return sum(r.spent for r in cell.values()) / max(1, len(cell))

    for y, x in plan.comparisons:
        for bx in budgets:
            if (x, bx) not in by or not any((y, b) in by for b in budgets):
                continue
            target = mean_cost(x, bx)
            by_cap = [b for b in budgets if (y, b) in by]
            by_ = min(by_cap, key=lambda b: (abs(mean_cost(y, b) - target), b))
            cx, cy = by[(x, bx)], by[(y, by_)]
            worlds = sorted(set(cx) & set(cy))
            diffs = {"cost": [float(cy[w].spent - cx[w].spent) for w in worlds]}
            for name, f in METRICS.items():
                diffs[name] = [f(cy[w]) - f(cx[w]) for w in worlds]
            ci = _bootstrap(
                diffs, plan.bootstrap_resamples, f"lab-brain/v1.3/bootstrap/{label}/{y}-{x}/{bx}"
            )
            lo, hi = ci["cost"][1], ci["cost"][2]
            matched = -plan.cost_tolerance <= lo and hi <= plan.cost_tolerance
            out["pairs"].append(
                {
                    "y": y,
                    "x": x,
                    "cap_x": bx,
                    "cap_y": by_,
                    "n": len(worlds),
                    "mean_cost_x": round(sum(cx[w].spent for w in worlds) / max(1, len(worlds)), 4),
                    "mean_cost_y": round(sum(cy[w].spent for w in worlds) / max(1, len(worlds)), 4),
                    "basis": "COST_MATCHED" if matched else "COST_UNMATCHED",
                    "differences": {
                        k: {"mean": v[0], "ci95": [v[1], v[2]]} for k, v in sorted(ci.items())
                    },
                }
            )
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
            "asserted": r.asserted,
            "proposal_hit": r.proposal_hit,
            "own_correct": r.own_correct,
            "own_error": r.own_error,
            "own_category": r.own_category,
            "v12_level": r.v12_level,
            "claim": list(r.claim),
            "outcome": r.outcome,
            "reason": r.reason,
            "spent": r.spent,
            "registrations": r.registrations,
            "void_registrations": r.void_registrations,
            "open_rivals": list(r.open_rivals),
            "grammar_proposal": r.grammar_proposal,
            "grammar_proposal_hit": r.grammar_proposal_hit,
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
    "all_experiments",
    "judge_answer",
    "matched_comparisons",
    "own_category_v11",
    "records_as_json",
    "run_arm",
    "summarize",
    "table",
]
