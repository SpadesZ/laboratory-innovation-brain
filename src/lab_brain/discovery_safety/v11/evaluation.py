"""Arms B2, B3 and B4 on the same worlds, scored per arm and per budget, plus cost checkpoints.

    B2   the frozen engine (`investigate` under `DISCOVERY`)
    B3   the v1.0 safety gate (`lab_brain.discovery_safety.gate.safe_investigate`), unchanged
    B4   the v1.1 safety gate (`safe_investigate_v11`)

SETTINGS. Every world is run through a blind, metered laboratory (`blind_laboratory`, `CostMeter`):
the meter's charge is the realized cost and must equal what the arm reports.

    held_out    the true family REMOVED from the engine's catalog (frozen `held_out.run_held_out`,
                truth-leak refusal included). Correct = no claim. Nothing can be identified
    control     the same worlds with the family LEFT IN: the truth is expressible
    benchmark   the benchmark's world kinds (single classes, compositions, an inseparable pair,
                noise-only, a measurement-chain confounder, an undeclared truth)

CATEGORIES (exactly one per run):

    CORRECT_IDENTIFICATION      the frozen scorer's `correct`: the exact truth (with every equally
                                simple alternative no experiment separates from it). Never a
                                held-out run, never a stage-1 proposal
    INDISTINGUISHABLE_ALTERNATIVE  a claim every member of which no available experiment separates
                                from the truth, that is not the correct identification (held-out:
                                a surrogate claim on an ALIASED world)
    FORCE_FIT                   a mechanism claim whose members are separable from the truth (held-
                                out: any non-surrogate mechanism claim; in-catalog: a false
                                discovery, or a claim holding the truth beside something separable)
    FALSE_NULL                  NO_EFFECT_BEYOND_NOISE when there is an effect
    NO_CLAIM                    an abstention (correct in held-out and undeclared-truth worlds);
                                its reason is recorded

A STAGE-1 PROPOSAL IS NOT A DISCOVERY. Proposals are counted beside the categories, and a run with
a proposal is never an identification (`proposals_counted_as_identification` must be 0).

EQUAL CAPS ARE NOT EQUAL COSTS. At one cap the arms spend different amounts. `checkpoints` reports a
pre-registered realized-cost ladder (fractions of the cap): an arm's answer at checkpoint c is the
last answer it committed while its cumulative charge was <= c, each experiment charged in full when
it starts. The frozen engine and both gates commit exactly ONE answer, when they stop -- none of
them exposes an interim committed answer (the engine's loop has no hook for one, and its
`StepRecord`s carry no interim claim; the gates decide once, after the engine). So the answer at c
is the final one if the run's whole realized cost is <= c, and NO_ANSWER_COMMITTED otherwise. That
is exact, not an estimate; what it cannot give is how an arm WOULD have answered had it been
stopped at c, which would need an anytime hook in the frozen engine. Comparisons that would need
that are labelled COST_UNMATCHED.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.benchmark import Arm, Oracles, Scenario, lab_for
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory
from lab_brain.discovery.metrics import Scorer, rate
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    Budget,
    DiscoveryResult,
    ExperimentSpec,
    Outcome,
    to_jsonable,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld, WorldSpec
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory, find_truth_leaks
from lab_brain.discovery_safety.evaluation import B2, SafeArmRecorder
from lab_brain.discovery_safety.model import SafetyAssessment
from lab_brain.discovery_safety.v11.gate import safe_investigate_v11
from lab_brain.discovery_safety.v11.model import (
    PLAN,
    SAFETY_V11,
    EvaluationPlanV11,
    SafeRunV11,
    SafetyProtocolV11,
)

B3_ID, B4_ID = "B3", "B4"
ARM_IDS = ("B2", B3_ID, B4_ID)

CORRECT_IDENTIFICATION = "CORRECT_IDENTIFICATION"
INDISTINGUISHABLE_ALTERNATIVE = "INDISTINGUISHABLE_ALTERNATIVE"
FORCE_FIT = "FORCE_FIT"
FALSE_NULL = "FALSE_NULL"
NO_CLAIM = "NO_CLAIM"
CATEGORIES = (
    CORRECT_IDENTIFICATION,
    INDISTINGUISHABLE_ALTERNATIVE,
    FORCE_FIT,
    FALSE_NULL,
    NO_CLAIM,
)
NO_ANSWER_COMMITTED = "NO_ANSWER_COMMITTED"

EQUAL_CAP = (
    "EQUAL_CAP -- COST_UNMATCHED: every arm had the same cap; realized costs differ by arm "
    "(see realized_cost)"
)
CHECKPOINT_BASIS = (
    "REALIZED_COST_CHECKPOINT -- commit-at-termination: each arm commits one answer, when it "
    "stops; at checkpoint c it counts only if the run's whole realized cost is <= c "
    "(experiments charged in full at start), else NO_ANSWER_COMMITTED"
)
ANYTIME_MISSING = (
    "No arm exposes interim committed answers: the frozen engine's `investigate` returns one "
    "result at its end (no per-step hook; StepRecord carries no interim claim) and both safety "
    "gates decide once, after the engine. Adding one would mean editing the frozen engine, which "
    "this work may not do. How an arm WOULD have answered if stopped at c is therefore not "
    "reported; any comparison needing it is COST_UNMATCHED."
)


@dataclass
class SafeArmRecorderV11:
    """An `Arm` runner for B4 that keeps every run (assessment, refit trace), keyed by digest."""

    safety: SafetyProtocolV11 = SAFETY_V11
    runs: dict[str, SafeRunV11] = field(default_factory=dict)

    def __call__(self, **kwargs: Any) -> DiscoveryResult:
        run = safe_investigate_v11(safety=self.safety, **kwargs)
        self.runs[run.result.digest] = run
        return run.result

    def assessment(self, digest: str) -> SafetyAssessment:
        return self.runs[digest].assessment

    def arm(self, arm_id: str = B4_ID) -> Arm:
        return Arm(arm_id, "LIB + Discovery + out-of-catalog safety gate (v1.1)", DISCOVERY, self)


@dataclass(frozen=True)
class RunRecord:
    setting: str
    world_id: str
    kind: str
    arm: str
    budget: int
    #: The laboratory meter's charge (realized cost); equals what the arm reported.
    spent: int
    outcome: str
    claim: tuple[str, ...]
    category: str
    #: Why there is no claim (safe arms: the gate's reason; B2: the engine's outcome); "" if claim.
    reason: str
    #: A stage-1 new-family proposal was written (exploratory; never a discovery).
    proposal: bool
    #: Held-out only: the truth cannot be separated from something the reduced catalog expresses.
    aliased: bool
    digest: str


class _Arms:
    """B2, B3 and B4 with recorders, so the safe arms' reasons and proposals can be read back."""

    def __init__(self, v10_recorder: SafeArmRecorder, v11_recorder: SafeArmRecorderV11) -> None:
        self.b3 = v10_recorder
        self.b4 = v11_recorder
        self.arms: tuple[Arm, ...] = (B2, v10_recorder.arm(B3_ID), v11_recorder.arm(B4_ID))

    def assessment(self, arm: str, digest: str) -> SafetyAssessment | None:
        if arm == B3_ID:
            return self.b3.assessment(digest)
        if arm == B4_ID:
            return self.b4.assessment(digest)
        return None

    def reason(self, arm: str, result_outcome: str, claimed: bool, digest: str) -> str:
        if claimed:
            return ""
        a = self.assessment(arm, digest)
        if a is None or a.reason is None:
            return result_outcome
        if a.reason.value == "NO_ENGINE_CLAIM":
            return f"NO_ENGINE_CLAIM:{a.engine_outcome.value}"
        return a.reason.value

    def proposal(self, arm: str, digest: str) -> bool:
        a = self.assessment(arm, digest)
        return a is not None and a.proposal is not None


def make_arms(safety: SafetyProtocolV11 = SAFETY_V11) -> _Arms:
    return _Arms(SafeArmRecorder(), SafeArmRecorderV11(safety))


def _all_experiments(catalog: DiscoveryCatalog) -> dict[str, ExperimentSpec]:
    return {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }


# -- running ---------------------------------------------------------------------------------


def run_held_out_setting(
    catalog: DiscoveryCatalog,
    worlds: Sequence[held_out.HeldOutWorld],
    *,
    budgets: Sequence[int],
    motivating_experiment: str,
    arms: _Arms,
) -> list[RunRecord]:
    """Every arm on every world with the family removed, through the frozen `run_held_out`."""
    by_world = {w.spec.world_id: w for w in worlds}
    out: list[RunRecord] = []
    for budget in budgets:
        rows = held_out.run_held_out(
            catalog,
            worlds,
            arms=arms.arms,
            budget=budget,
            motivating_experiment=motivating_experiment,
            protocol=DISCOVERY,
        )
        for r in rows:
            world = by_world[r.world_id]
            a = arms.assessment(r.arm, r.digest)
            if a is not None:
                leaks = find_truth_leaks(
                    [to_jsonable(a), to_jsonable(arms.b4.runs[r.digest].refit)]
                    if r.arm == B4_ID
                    else to_jsonable(a),
                    held_out.truth_needles(catalog, world),
                )
                if leaks:
                    raise held_out.TruthLeak(f"an assessment names the truth: {leaks[:3]}")
            claimed = r.outcome in {o.value for o in CLAIM_OUTCOMES}
            if r.false_null:
                category = FALSE_NULL
            elif r.surrogate:
                category = INDISTINGUISHABLE_ALTERNATIVE
            elif r.force_fit:
                category = FORCE_FIT
            else:
                category = NO_CLAIM
            out.append(
                RunRecord(
                    setting="held_out",
                    world_id=r.world_id,
                    kind=f"held_out:{r.family}",
                    arm=r.arm,
                    budget=budget,
                    spent=r.spent,
                    outcome=r.outcome,
                    claim=r.claim,
                    category=category,
                    reason=arms.reason(r.arm, r.outcome, claimed, r.digest),
                    proposal=arms.proposal(r.arm, r.digest),
                    aliased=r.aliased,
                    digest=r.digest,
                )
            )
    return out


def classify(
    scorer: Scorer, world: WorldSpec, result: DiscoveryResult, oracle: SeparationOracle
) -> str:
    """One category for an in-catalog run (the truth expressible, or undeclared)."""
    score = scorer.score(world, result, oracle)
    if not score.claim_made:
        return NO_CLAIM
    if score.correct:
        return CORRECT_IDENTIFICATION
    truth = world.truth_hypothesis(scorer.catalog)
    if result.outcome is Outcome.NO_EFFECT_BEYOND_NOISE and (truth is None or not truth.is_null):
        return FALSE_NULL
    if truth is not None:
        near, _simple = scorer.truth_class(truth, oracle)
        claimed = {result.record(i).hypothesis.fingerprint for i in result.claim}
        if claimed and claimed <= near:
            return INDISTINGUISHABLE_ALTERNATIVE
    return FORCE_FIT


def _run_in_catalog(
    setting: str,
    catalog: DiscoveryCatalog,
    worlds: Sequence[tuple[WorldSpec, Laboratory, SeparationOracle]],
    *,
    budgets: Sequence[int],
    arms: _Arms,
) -> list[RunRecord]:
    scorer = Scorer(catalog)
    experiments = _all_experiments(catalog)
    costs = {k: e.cost for k, e in experiments.items()}
    out: list[RunRecord] = []
    for world, lab, oracle in worlds:
        available = tuple(e.experiment_id for e in oracle.available)
        for budget in budgets:
            for arm in arms.arms:
                meter = CostMeter(costs, budget)
                result = arm.runner(
                    arm=arm.arm_id,
                    catalog=catalog,
                    oracle=oracle,
                    protocol=arm.protocol,
                    budget=Budget(budget),
                    lab=blind_laboratory(
                        lab, experiments=experiments, available=available, meter=meter
                    ),
                )
                if meter.spent != result.spent:
                    raise RuntimeError(f"{world.world_id}:{arm.arm_id}: meter and arm disagree")
                claimed = result.outcome in CLAIM_OUTCOMES
                out.append(
                    RunRecord(
                        setting=setting,
                        world_id=world.world_id,
                        kind=world.kind,
                        arm=arm.arm_id,
                        budget=budget,
                        spent=meter.spent,
                        outcome=result.outcome.value,
                        claim=result.claim,
                        category=classify(scorer, world, result, oracle),
                        reason=arms.reason(
                            arm.arm_id, result.outcome.value, claimed, result.digest
                        ),
                        proposal=arms.proposal(arm.arm_id, result.digest),
                        aliased=False,
                        digest=result.digest,
                    )
                )
    return out


def run_control_setting(
    catalog: DiscoveryCatalog,
    worlds: Sequence[held_out.HeldOutWorld],
    *,
    budgets: Sequence[int],
    motivating_experiment: str,
    arms: _Arms,
) -> list[RunRecord]:
    """The held-out worlds with the family LEFT IN the catalog (the truth is expressible)."""
    oracle = SeparationOracle(
        catalog, tuple(e.experiment_id for e in catalog.experiments), DISCOVERY
    )
    triples = []
    for w in worlds:
        if w.spec.removed:
            raise ValueError("the control runs held-out worlds, which remove no experiment")
        triples.append((w.spec, SyntheticWorld(w.spec, catalog, motivating_experiment), oracle))
    return _run_in_catalog("control", catalog, triples, budgets=budgets, arms=arms)


def run_benchmark_setting(
    scenario: Scenario, *, budgets: Sequence[int], arms: _Arms
) -> list[RunRecord]:
    """The benchmark's world kinds, each with its own available experiments."""
    oracles = Oracles(scenario.catalog, DISCOVERY)
    triples = [(w, lab_for(scenario, w), oracles.for_world(w)) for w in scenario.worlds]
    return _run_in_catalog("benchmark", scenario.catalog, triples, budgets=budgets, arms=arms)


# -- summarising -----------------------------------------------------------------------------


def _rate(k: int, n: int) -> dict[str, Any]:
    """k of n with its Wilson 95% interval (the frozen scorer's `rate`)."""
    return rate([True] * k + [False] * (n - k))


def _quantile(sorted_values: Sequence[int], q: float) -> float:
    """The nearest-rank quantile (no interpolation: realized costs are integers)."""
    if not sorted_values:
        raise ValueError("no values")
    n = len(sorted_values)
    index = min(n - 1, max(0, math.ceil(q * n) - 1))
    return float(sorted_values[index])


def realized_cost(records: Sequence[RunRecord]) -> dict[str, Any]:
    spent = sorted(r.spent for r in records)
    if not spent:
        return {"n": 0}
    n = len(spent)
    median = float(spent[n // 2]) if n % 2 else (spent[n // 2 - 1] + spent[n // 2]) / 2.0
    histogram: dict[str, int] = {}
    for s in spent:
        histogram[str(s)] = histogram.get(str(s), 0) + 1
    return {
        "n": n,
        "mean": round(sum(spent) / n, 4),
        "median": median,
        "min": spent[0],
        "p10": _quantile(spent, 0.1),
        "p90": _quantile(spent, 0.9),
        "max": spent[-1],
        "distribution": dict(sorted(histogram.items(), key=lambda kv: int(kv[0]))),
    }


def _counts(values: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def category_table(records: Sequence[RunRecord]) -> dict[str, Any]:
    n = len(records)
    out: dict[str, Any] = {c: _rate(sum(r.category == c for r in records), n) for c in CATEGORIES}
    out["abstention_reasons"] = _counts([r.reason for r in records if r.category == NO_CLAIM])
    out["stage_1_proposals"] = sum(r.proposal for r in records)
    counted = sum(r.proposal and r.category == CORRECT_IDENTIFICATION for r in records)
    if counted:
        raise AssertionError("a stage-1 proposal was counted as an identification")
    out["proposals_counted_as_identification"] = counted
    out["realized_cost"] = realized_cost(records)
    return out


def summarize(records: Sequence[RunRecord], budgets: Sequence[int]) -> dict[str, Any]:
    """Per budget, per arm: the category table. Held-out: primary (non-aliased) and aliased."""
    out: dict[str, Any] = {"comparison_basis": EQUAL_CAP}
    for budget in budgets:
        at: dict[str, Any] = {}
        for arm in ARM_IDS:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            if mine and mine[0].setting == "held_out":
                at[arm] = {
                    "primary": category_table([r for r in mine if not r.aliased]),
                    "aliased": category_table([r for r in mine if r.aliased]),
                }
            else:
                at[arm] = {"all": category_table(mine)}
                kinds = sorted({r.kind for r in mine})
                if len(kinds) > 1:
                    at[arm]["per_kind"] = {
                        k: {
                            c: sum(r.category == c for r in mine if r.kind == k) for c in CATEGORIES
                        }
                        | {"n": sum(r.kind == k for r in mine)}
                        for k in kinds
                    }
        out[str(budget)] = at
    return out


def checkpoint_table(
    records: Sequence[RunRecord],
    budgets: Sequence[int],
    fractions: Sequence[float],
    *,
    primary_only: bool,
) -> dict[str, Any]:
    """At checkpoint c = floor(fraction x cap): the committed answer if the whole run cost <= c."""
    out: dict[str, Any] = {"comparison_basis": CHECKPOINT_BASIS, "anytime_missing": ANYTIME_MISSING}
    for budget in budgets:
        at: dict[str, Any] = {}
        for fraction in fractions:
            c = int(fraction * budget)
            per_arm: dict[str, Any] = {}
            for arm in ARM_IDS:
                mine = [
                    r
                    for r in records
                    if r.budget == budget and r.arm == arm and not (primary_only and r.aliased)
                ]
                n = len(mine)
                committed = [r for r in mine if r.spent <= c]
                row: dict[str, Any] = {
                    c_: _rate(sum(r.category == c_ for r in committed), n) for c_ in CATEGORIES
                }
                row[NO_ANSWER_COMMITTED] = _rate(n - len(committed), n)
                per_arm[arm] = row
            at[f"{fraction:g}"] = {"checkpoint_units": c, "arms": per_arm}
        out[str(budget)] = at
    return out


def budget_monotonicity(records: Sequence[RunRecord], arm: str) -> dict[str, Any]:
    """Per world: does a larger budget ever turn this arm's non-force-fit into a force-fit?"""
    budgets = sorted({r.budget for r in records})
    index: Mapping[tuple[str, int], RunRecord] = {
        (r.world_id, r.budget): r for r in records if r.arm == arm
    }
    worlds = sorted({r.world_id for r in records if r.arm == arm and not r.aliased})
    escalations = [
        f"{w}: {a} -> {b}"
        for w in worlds
        for a, b in itertools.pairwise(budgets)
        if index[(w, a)].category != FORCE_FIT and index[(w, b)].category == FORCE_FIT
    ]
    return {"budgets": budgets, "worlds": len(worlds), "force_fit_escalations": escalations}


def records_as_json(records: Sequence[RunRecord]) -> list[dict[str, Any]]:
    """One row per world, every arm and budget nested (deterministic order)."""
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        entry = out.setdefault(
            r.world_id,
            {"world_id": r.world_id, "kind": r.kind, "aliased": r.aliased, "arms": {}},
        )
        entry["arms"].setdefault(r.arm, {})[str(r.budget)] = {
            "outcome": r.outcome,
            "claim": list(r.claim),
            "category": r.category,
            "reason": r.reason,
            "proposal": r.proposal,
            "spent": r.spent,
            "digest": r.digest,
        }
    return list(out.values())


def refit_summary(arms: _Arms) -> dict[str, Any]:
    """What the v1.1 additions did across every B4 run recorded."""
    runs = list(arms.b4.runs.values())
    with_claim = [r for r in runs if r.refit is not None]
    emerged = [r for r in with_claim if r.refit is not None and r.refit.emerged_after_refit]
    localized_only = [
        r for r in runs if any(t.global_adequate and t.localized_failed for t in r.member_tests)
    ]
    return {
        "b4_runs": len(runs),
        "b4_runs_with_engine_claim": len(with_claim),
        "signal_predictions_emerged_after_refit": len(emerged),
        "of_which_endorsed": sum(r.assessment.endorsed for r in emerged),
        "of_which_unverified": sum(
            r.assessment.reason is not None and r.assessment.reason.value == "ADEQUACY_UNVERIFIED"
            for r in emerged
        ),
        "endorsed_with_a_never_run_signal_experiment": sum(
            r.assessment.endorsed and r.refit is not None and not r.refit.stable for r in with_claim
        ),
        "claim_failed_localized_check_only": len(localized_only),
    }


def plan_record(plan: EvaluationPlanV11 = PLAN) -> dict[str, Any]:
    return {"plan": to_jsonable(plan), "digest": plan.digest}


__all__ = [
    "ANYTIME_MISSING",
    "ARM_IDS",
    "B3_ID",
    "B4_ID",
    "CATEGORIES",
    "CHECKPOINT_BASIS",
    "CORRECT_IDENTIFICATION",
    "EQUAL_CAP",
    "FALSE_NULL",
    "FORCE_FIT",
    "INDISTINGUISHABLE_ALTERNATIVE",
    "NO_ANSWER_COMMITTED",
    "NO_CLAIM",
    "RunRecord",
    "SafeArmRecorderV11",
    "budget_monotonicity",
    "category_table",
    "checkpoint_table",
    "classify",
    "make_arms",
    "plan_record",
    "realized_cost",
    "records_as_json",
    "refit_summary",
    "run_benchmark_setting",
    "run_control_setting",
    "run_held_out_setting",
    "summarize",
]
