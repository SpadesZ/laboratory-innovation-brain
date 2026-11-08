"""Arms B2-B5 on the same worlds, scored on two axes (SAI 3.5 candidate.4), per arm and budget.

    B2   the frozen engine (`investigate` under `DISCOVERY`)
    B3   the v1.0 gate, unchanged          B4   the v1.1 gate, unchanged
    B5   the v1.2 gate (`safe_investigate_v12`) with the domain's term grammar

THE LABORATORY each arm receives is the evaluator's: a blind laboratory (`blind_laboratory`) with
a cost meter, whose every run is also written to an evaluator-owned `PredictionLedger`, plus one
extra method, `register(text)`, that appends a prediction to that ledger. B2-B4 never call it.

TWO AXES, NEVER MERGED (`classify_outcome` / `verified_evidence` of SAI candidate.4, re-derived
here from the ledger and the sealed truth; the arm's own label is never trusted):

    level      SUPPORTED iff every mechanism of the final answer has, in the LEDGER, a prediction
               registered before the data it names was measured, re-scored as passed and risky by
               the evaluator, with Holm's procedure over all of that mechanism's registrations
               rejecting none (`ledger.supported`); otherwise PROPOSAL. No answer: NONE.
    category   no answer: FALSE_NULL if some hypothesis the arm's catalog expresses matches the
               truth (identity, or INDISTINGUISHABLE under the world's full experiment set), else
               CORRECT_ABSTENTION. An answer below SUPPORTED: PROPOSAL_ONLY (never credited, never
               an error). A SUPPORTED answer: outside the catalog -> VALIDATED_NEW_MECHANISM if it
               matches the truth, else WRONG_CLAIM; inside -> EXACT_IDENTIFICATION (truth identity),
               INDISTINGUISHABLE_ALTERNATIVE, or FORCE_FIT (distinguishable, truth not held and
               matched by nothing held) / WRONG_CLAIM (otherwise). No undeclared truth can be
               matched (truth None: any supported answer is WRONG_CLAIM). Distinguishability here
               is binary (worst case over both parameter domains vs `distinguish_tau` with
               `distinguish_replicates`), so UNRESOLVED_ALTERNATIVE never occurs.

Beside the categories: the arm's OWN answer (the gate's endorsement or the engine's claim, taken at
face value, with v1.1's legacy categories), and `proposal_hit` -- whether a PROPOSAL_ONLY answer, or
a grammar proposal beside an abstention, matches the truth. Counted, never credited.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.benchmark import Arm, Oracles, Scenario, lab_for
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe
from lab_brain.discovery.metrics import Scorer, rate
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    Budget,
    DiscoveryResult,
    ExperimentSpec,
    Hypothesis,
    MechanismClass,
    MechanismKind,
    Outcome,
    Tier,
    make_hypothesis,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld, WorldSpec
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory
from lab_brain.discovery_safety.evaluation import B2, SafeArmRecorder
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.evaluation import SafeArmRecorderV11, classify
from lab_brain.discovery_safety.v12.gate import safe_investigate_v12
from lab_brain.discovery_safety.v12.grammar import TermGrammar, separation
from lab_brain.discovery_safety.v12.ledger import PredictionLedger, rescore, supported
from lab_brain.discovery_safety.v12.model import (
    SAFETY_V12,
    GrammarCandidate,
    SafeRunV12,
    SafetyProtocolV12,
)

ARM_IDS = ("B2", "B3", "B4", "B5")

EXACT = "EXACT_IDENTIFICATION"
INDISTINGUISHABLE = "INDISTINGUISHABLE_ALTERNATIVE"
VALIDATED_NEW = "VALIDATED_NEW_MECHANISM"
PROPOSAL_ONLY = "PROPOSAL_ONLY"
CORRECT_ABSTENTION = "CORRECT_ABSTENTION"
FALSE_NULL = "FALSE_NULL"
FORCE_FIT = "FORCE_FIT"
WRONG_CLAIM = "WRONG_CLAIM"
SAI_CATEGORIES = (
    EXACT,
    INDISTINGUISHABLE,
    VALIDATED_NEW,
    PROPOSAL_ONLY,
    CORRECT_ABSTENTION,
    FALSE_NULL,
    FORCE_FIT,
    WRONG_CLAIM,
)
SUPPORTED = "SUPPORTED"
PROPOSAL = "PROPOSAL"
NONE = "NONE"
#: v1.1's categories of the arm's own answer, taken at face value (no evidence check).
OWN_CATEGORIES = (
    "CORRECT_IDENTIFICATION",
    "INDISTINGUISHABLE_ALTERNATIVE",
    "FORCE_FIT",
    "FALSE_NULL",
    "NO_CLAIM",
)
NO_ANSWER_COMMITTED = "NO_ANSWER_COMMITTED"
EQUAL_CAP = (
    "EQUAL_CAP -- COST_UNMATCHED: every arm had the same cap; realized costs differ by arm "
    "(see realized_cost)"
)
CHECKPOINT_BASIS = (
    "REALIZED_COST_CHECKPOINT -- commit-at-termination: every arm (B5 included: its ladder runs "
    "inside the gate and nothing is answered before the gate decides) commits one answer when it "
    "stops; at checkpoint c it counts only if the run's whole realized cost is <= c "
    "(experiments charged in full when started), else NO_ANSWER_COMMITTED. How an arm WOULD "
    "have answered if stopped at c is not available: COST_UNMATCHED"
)


class LedgerLaboratory:
    """The evaluator's laboratory: blind, metered, every run written to the ledger, plus
    `register`. Holds the wrapped laboratory and ledger in a closure-free pair of private slots."""

    __slots__ = ("_lab", "_ledger")

    def __init__(self, lab: Laboratory, ledger: PredictionLedger) -> None:
        self._lab = lab
        self._ledger = ledger

    def motivating(self) -> tuple[str, tuple[tuple[str, float], ...]]:
        return self._lab.motivating()

    def measure(
        self, experiment_id: str, *, replicate: int, session: int
    ) -> tuple[tuple[str, float], ...]:
        values = self._lab.measure(experiment_id, replicate=replicate, session=session)
        self._ledger.record_measurement(experiment_id, replicate, values)
        return values

    def register(self, text: str) -> int:
        return self._ledger.register(text)

    def __repr__(self) -> str:
        return "LedgerLaboratory()"


@dataclass
class SafeArmRecorderV12:
    safety: SafetyProtocolV12 = SAFETY_V12
    grammar: TermGrammar | None = None
    runs: dict[str, SafeRunV12] = field(default_factory=dict)

    def __call__(self, **kwargs: Any) -> DiscoveryResult:
        run = safe_investigate_v12(safety=self.safety, grammar=self.grammar, **kwargs)
        self.runs[run.result.digest] = run
        return run.result

    def arm(self, arm_id: str = "B5") -> Arm:
        return Arm(arm_id, "LIB + Discovery + safety gate v1.2", DISCOVERY, self)


class Arms:
    def __init__(self, grammar: TermGrammar | None, safety: SafetyProtocolV12 = SAFETY_V12):
        self.b3 = SafeArmRecorder()
        self.b4 = SafeArmRecorderV11()
        self.b5 = SafeArmRecorderV12(safety, grammar)
        self.arms: tuple[Arm, ...] = (B2, self.b3.arm("B3"), self.b4.arm("B4"), self.b5.arm("B5"))

    def reason(self, arm: str, result: DiscoveryResult) -> str:
        if result.outcome in CLAIM_OUTCOMES:
            return ""
        stores: dict[str, Mapping[str, Any]] = {
            "B3": self.b3.runs,
            "B4": self.b4.runs,
            "B5": self.b5.runs,
        }
        store: Mapping[str, Any] = stores.get(arm, {})
        run = store.get(result.digest)
        if run is None or run.assessment.reason is None:
            return result.outcome.value
        if run.assessment.reason.value == "NO_ENGINE_CLAIM":
            return f"NO_ENGINE_CLAIM:{run.assessment.engine_outcome.value}"
        return str(run.assessment.reason.value)


def grammar_hypothesis(candidate: GrammarCandidate) -> Hypothesis:
    """A grammar candidate's forward model and declared domain, as a hypothesis (evaluator-side)."""
    classes = [
        MechanismClass(
            class_id=f"answer.t{i}",
            family=f"answer.f{i}",
            mechanism=term,
            regime="fitted",
            statement=term,
            kind=MechanismKind.PHYSICAL,
            tier=Tier.EXTENDED,
            parameter="amplitude",
            lower=lo,
            upper=hi,
            sensitivity=table,
        )
        for i, (term, table, (lo, hi)) in enumerate(
            zip(candidate.terms, candidate.tables, candidate.domain, strict=True)
        )
    ]
    return make_hypothesis(*classes)


@dataclass(frozen=True)
class RunRecord:
    setting: str
    world_id: str
    kind: str
    arm: str
    budget: int
    spent: int
    outcome: str
    #: NONE, CATALOG_CLAIM or NEW_MECHANISM (the arm's own final answer).
    answer: str
    claim: tuple[str, ...]
    own_category: str
    category: str
    level: str
    #: A PROPOSAL_ONLY answer, or a grammar proposal beside an abstention, matches the truth.
    proposal_hit: bool
    grammar_proposal: bool
    grammar_proposal_hit: bool
    #: The answered new mechanism also matches the truth at the world's TRUE amplitude (stricter).
    new_mechanism_point_match: bool
    reason: str
    registrations: int
    aliased: bool
    digest: str


class Judge:
    """The evaluator's verdicts for one world (truth sealed here, never handed to an arm)."""

    def __init__(
        self,
        truth: Hypothesis | None,
        truth_point: Mapping[str, float],
        held: Sequence[Hypothesis],
        full: SeparationOracle,
    ) -> None:
        self.truth = truth
        self.truth_point = dict(truth_point)
        self.full = full
        self.experiments = full.available
        self.held_prints = {h.fingerprint for h in held}
        self.held = held
        self._any_match: bool | None = None

    def matches(self, h: Hypothesis) -> bool:
        if self.truth is None:
            return False
        if h.fingerprint == self.truth.fingerprint:
            return True
        return (
            separation(h, self.truth, self.experiments, self.full.protocol.distinguish_replicates)
            < self.full.protocol.distinguish_tau
        )

    def any_held_matches(self) -> bool:
        if self._any_match is None:
            self._any_match = any(self.matches(h) for h in self.held)
        return self._any_match

    def catalog_category(self, members: Sequence[Hypothesis]) -> str:
        if self.truth is None:
            return WRONG_CLAIM
        if all(self.matches(m) for m in members):
            return (
                EXACT
                if self.truth.fingerprint in {m.fingerprint for m in members}
                else (INDISTINGUISHABLE)
            )
        if self.truth.fingerprint in self.held_prints or self.any_held_matches():
            return WRONG_CLAIM
        return FORCE_FIT

    def point_match(self, candidate: GrammarCandidate) -> bool:
        """Stricter: the candidate AT ITS FITTED amplitudes vs the truth AT ITS TRUE amplitudes,
        over the full experiment set with the replication allowance."""
        if self.truth is None:
            return False
        d2 = 0.0
        for x in self.experiments:
            for e in x.entries:
                mine = sum(
                    t * {(a, b): c for a, b, c in table}.get((x.experiment_id, e.entry_id), 0.0)
                    for t, table in zip(candidate.theta, candidate.tables, strict=True)
                )
                truth = sum(
                    self.truth_point.get(c.class_id, 0.0)
                    * c.coefficient(x.experiment_id, e.entry_id)
                    for c in self.truth.components
                )
                d2 += ((mine - truth) / e.sigma) ** 2
        return math.sqrt(self.full.protocol.distinguish_replicates * d2) < (
            self.full.protocol.distinguish_tau
        )


def judge_run(
    judge: Judge,
    result: DiscoveryResult,
    run: SafeRunV12 | None,
    ledger: PredictionLedger,
    experiments: Mapping[str, ExperimentSpec],
    alpha: float,
) -> tuple[str, str, str, bool, bool, bool, bool]:
    """(answer, category, level, proposal_hit, grammar_proposal, grammar_proposal_hit,
    new_mechanism_point_match) for one run."""
    tests = rescore(ledger, experiments)
    grammar_proposal = (
        run is not None and run.discovery is not None and (run.discovery.proposal is not None)
    )
    grammar_hit = False
    if grammar_proposal and run is not None and run.discovery is not None:
        proposal = run.discovery.proposal
        grammar_hit = proposal is not None and judge.matches(grammar_hypothesis(proposal))
    if run is not None and run.discovery is not None and run.discovery.answered is not None:
        answer = run.discovery.answered
        h = grammar_hypothesis(answer)
        ok = supported(tests, answer.fingerprint, alpha)
        point = judge.point_match(answer)
        if not ok:
            return (
                "NEW_MECHANISM",
                PROPOSAL_ONLY,
                PROPOSAL,
                judge.matches(h),
                grammar_proposal,
                grammar_hit,
                point,
            )
        if h.fingerprint in judge.held_prints:
            category = judge.catalog_category([h])
        else:
            category = VALIDATED_NEW if judge.matches(h) else WRONG_CLAIM
        return ("NEW_MECHANISM", category, SUPPORTED, False, grammar_proposal, grammar_hit, point)
    if result.outcome not in CLAIM_OUTCOMES:
        category = FALSE_NULL if judge.any_held_matches() else CORRECT_ABSTENTION
        return ("NONE", category, NONE, False, grammar_proposal, grammar_hit, False)
    members = [result.record(i).hypothesis for i in result.claim] or [NULL_HYPOTHESIS]
    if result.outcome is Outcome.NO_EFFECT_BEYOND_NOISE:
        members = [NULL_HYPOTHESIS]
    ok = all(supported(tests, m.fingerprint, alpha) for m in members)
    if not ok:
        hit = judge.truth is not None and all(judge.matches(m) for m in members)
        return ("CATALOG_CLAIM", PROPOSAL_ONLY, PROPOSAL, hit, grammar_proposal, grammar_hit, False)
    return (
        "CATALOG_CLAIM",
        judge.catalog_category(members),
        SUPPORTED,
        False,
        grammar_proposal,
        grammar_hit,
        False,
    )


def _all_experiments(catalog: DiscoveryCatalog) -> dict[str, ExperimentSpec]:
    return {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }


def run_world(
    *,
    setting: str,
    world: WorldSpec,
    kind: str,
    aliased: bool,
    lab_factory: Callable[[], Laboratory],
    engine_catalog: DiscoveryCatalog,
    engine_oracle: SeparationOracle,
    full_catalog: DiscoveryCatalog,
    full_oracle: SeparationOracle,
    truth: Hypothesis | None,
    budgets: Sequence[int],
    grammar: TermGrammar | None,
    own: Callable[[DiscoveryResult], str],
    safety: SafetyProtocolV12 = SAFETY_V12,
) -> list[RunRecord]:
    """Every arm at every budget on one world (fresh laboratory, ledger and meter per run)."""
    experiments = _all_experiments(full_catalog)
    costs = {k: e.cost for k, e in experiments.items()}
    held = distinct_forward_models(hypothesis_universe(engine_catalog))
    judge = Judge(truth, dict(world.truth), held, full_oracle)
    available = tuple(e.experiment_id for e in engine_oracle.available)
    out = []
    for budget in budgets:
        arms = Arms(grammar, safety)
        for arm in arms.arms:
            meter = CostMeter(costs, budget)
            ledger = PredictionLedger()
            lab = LedgerLaboratory(
                blind_laboratory(
                    lab_factory(), experiments=experiments, available=available, meter=meter
                ),
                ledger,
            )
            result = arm.runner(
                arm=arm.arm_id,
                catalog=engine_catalog,
                oracle=engine_oracle,
                protocol=arm.protocol,
                budget=Budget(budget),
                lab=lab,
            )
            if meter.spent != result.spent:
                raise RuntimeError(f"{world.world_id}:{arm.arm_id}: meter and arm disagree")
            run = arms.b5.runs.get(result.digest) if arm.arm_id == "B5" else None
            answer, category, level, hit, gp, ghit, point = judge_run(
                judge, result, run, ledger, experiments, safety.alpha_prospective
            )
            out.append(
                RunRecord(
                    setting=setting,
                    world_id=world.world_id,
                    kind=kind,
                    arm=arm.arm_id,
                    budget=budget,
                    spent=meter.spent,
                    outcome=result.outcome.value,
                    answer=answer,
                    claim=tuple(result.claim),
                    own_category=own(result),
                    category=category,
                    level=level,
                    proposal_hit=hit,
                    grammar_proposal=gp,
                    grammar_proposal_hit=ghit,
                    new_mechanism_point_match=point,
                    reason=arms.reason(arm.arm_id, result),
                    registrations=sum(1 for e in ledger.events if e.kind == "REGISTER"),
                    aliased=aliased,
                    digest=result.digest,
                )
            )
    return out


def held_out_records(
    catalog: DiscoveryCatalog,
    world: held_out.HeldOutWorld,
    *,
    budgets: Sequence[int],
    motivating_experiment: str,
    grammar: TermGrammar | None,
    family_removed: bool,
    safety: SafetyProtocolV12 = SAFETY_V12,
) -> list[RunRecord]:
    """One held-out world: family REMOVED from the engine's catalog, or LEFT IN (control)."""
    all_ids = tuple(e.experiment_id for e in catalog.experiments)
    full = SeparationOracle(catalog, all_ids, DISCOVERY)
    truth = make_hypothesis(catalog.mechanism(world.truth_class))
    if family_removed:
        engine_catalog = held_out.without_family(catalog, world.family)
        held_out.assert_family_absent(
            engine_catalog, [m for m in catalog.mechanisms if m.family == world.family]
        )
        engine_oracle = SeparationOracle(engine_catalog, all_ids, DISCOVERY)

        def own(result: DiscoveryResult) -> str:
            claimed = result.outcome in CLAIM_OUTCOMES
            if not claimed:
                return "NO_CLAIM"
            if result.outcome is Outcome.NO_EFFECT_BEYOND_NOISE:
                return "FALSE_NULL"
            if world.aliased and set(result.claim) & set(world.aliases):
                return "INDISTINGUISHABLE_ALTERNATIVE"
            return "FORCE_FIT"

    else:
        engine_catalog, engine_oracle = catalog, full
        scorer = Scorer(catalog)

        def own(result: DiscoveryResult) -> str:
            return classify(scorer, world.spec, result, full)

    return run_world(
        setting="held_out" if family_removed else "control",
        world=world.spec,
        kind=f"held_out:{world.family}",
        aliased=world.aliased and family_removed,
        lab_factory=lambda: SyntheticWorld(world.spec, catalog, motivating_experiment),
        engine_catalog=engine_catalog,
        engine_oracle=engine_oracle,
        full_catalog=catalog,
        full_oracle=full,
        truth=truth,
        budgets=budgets,
        grammar=grammar,
        own=own,
        safety=safety,
    )


def benchmark_records(
    scenario: Scenario,
    world: WorldSpec,
    *,
    budgets: Sequence[int],
    grammar: TermGrammar | None,
    oracles: Oracles,
    safety: SafetyProtocolV12 = SAFETY_V12,
) -> list[RunRecord]:
    oracle = oracles.for_world(world)
    scorer = Scorer(scenario.catalog)

    def own(result: DiscoveryResult) -> str:
        return classify(scorer, world, result, oracle)

    return run_world(
        setting="benchmark",
        world=world,
        kind=world.kind,
        aliased=False,
        lab_factory=lambda: lab_for(scenario, world),
        engine_catalog=scenario.catalog,
        engine_oracle=oracle,
        full_catalog=scenario.catalog,
        full_oracle=oracle,
        truth=world.truth_hypothesis(scenario.catalog),
        budgets=budgets,
        grammar=grammar,
        own=own,
        safety=safety,
    )


# -- summarising -----------------------------------------------------------------------------


def _rate(k: int, n: int) -> dict[str, Any]:
    return rate([True] * k + [False] * (n - k))


def realized_cost(records: Sequence[RunRecord]) -> dict[str, Any]:
    spent = sorted(r.spent for r in records)
    if not spent:
        return {"n": 0}
    n = len(spent)
    median = float(spent[n // 2]) if n % 2 else (spent[n // 2 - 1] + spent[n // 2]) / 2.0
    return {
        "n": n,
        "mean": round(sum(spent) / n, 4),
        "median": median,
        "min": spent[0],
        "max": spent[-1],
    }


def table(records: Sequence[RunRecord]) -> dict[str, Any]:
    n = len(records)
    out: dict[str, Any] = {"n": n}
    out["sai"] = {c: _rate(sum(r.category == c for r in records), n) for c in SAI_CATEGORIES}
    out["own_answer"] = {c: sum(r.own_category == c for r in records) for c in OWN_CATEGORIES}
    answered = [r for r in records if r.answer != "NONE"]
    out["answers"] = len(answered)
    out["answers_supported"] = sum(r.level == SUPPORTED for r in answered)
    out["new_mechanism_answers"] = sum(r.answer == "NEW_MECHANISM" for r in records)
    out["new_mechanism_point_match"] = sum(r.new_mechanism_point_match for r in records)
    out["proposal_only_hits"] = sum(r.category == PROPOSAL_ONLY and r.proposal_hit for r in records)
    out["grammar_proposals"] = sum(r.grammar_proposal for r in records)
    out["grammar_proposal_hits"] = sum(r.grammar_proposal_hit for r in records)
    reasons: dict[str, int] = {}
    for r in records:
        if r.answer == "NONE":
            reasons[r.reason] = reasons.get(r.reason, 0) + 1
    out["abstention_reasons"] = dict(sorted(reasons.items()))
    out["realized_cost"] = realized_cost(records)
    credited = sum(
        r.category in (EXACT, INDISTINGUISHABLE, VALIDATED_NEW) and r.level != SUPPORTED
        for r in records
    )
    if credited:
        raise AssertionError("an answer below SUPPORTED was credited")
    return out


def summarize(records: Sequence[RunRecord], budgets: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {"comparison_basis": EQUAL_CAP}
    for budget in budgets:
        at: dict[str, Any] = {}
        for arm in ARM_IDS:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            if mine and mine[0].setting == "held_out":
                at[arm] = {
                    "primary": table([r for r in mine if not r.aliased]),
                    "aliased": table([r for r in mine if r.aliased]),
                }
            else:
                at[arm] = {"all": table(mine)}
        out[str(budget)] = at
    return out


def checkpoints(
    records: Sequence[RunRecord], budgets: Sequence[int], fractions: Sequence[float]
) -> dict[str, Any]:
    out: dict[str, Any] = {"comparison_basis": CHECKPOINT_BASIS}
    for budget in budgets:
        at: dict[str, Any] = {}
        for fraction in fractions:
            c = int(fraction * budget)
            per: dict[str, Any] = {}
            for arm in ARM_IDS:
                mine = [r for r in records if r.budget == budget and r.arm == arm and not r.aliased]
                committed = [r for r in mine if r.spent <= c]
                row = {k: sum(r.category == k for r in committed) for k in SAI_CATEGORIES}
                row[NO_ANSWER_COMMITTED] = len(mine) - len(committed)
                row["n"] = len(mine)
                per[arm] = row
            at[f"{fraction:g}"] = {"checkpoint_units": c, "arms": per}
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
            "own": r.own_category,
            "claim": list(r.claim),
            "outcome": r.outcome,
            "reason": r.reason,
            "spent": r.spent,
            "registrations": r.registrations,
            "proposal_hit": r.proposal_hit,
            "grammar_proposal": r.grammar_proposal,
            "grammar_proposal_hit": r.grammar_proposal_hit,
            "digest": r.digest,
        }
    return list(out.values())


__all__ = [
    "ARM_IDS",
    "CORRECT_ABSTENTION",
    "EXACT",
    "FALSE_NULL",
    "FORCE_FIT",
    "INDISTINGUISHABLE",
    "PROPOSAL_ONLY",
    "SAI_CATEGORIES",
    "VALIDATED_NEW",
    "WRONG_CLAIM",
    "Arms",
    "Judge",
    "LedgerLaboratory",
    "RunRecord",
    "SafeArmRecorderV12",
    "benchmark_records",
    "checkpoints",
    "grammar_hypothesis",
    "held_out_records",
    "judge_run",
    "realized_cost",
    "records_as_json",
    "run_world",
    "summarize",
    "table",
]
