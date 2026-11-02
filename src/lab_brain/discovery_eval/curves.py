"""Realized-cost and cost-discovery curves over a budget grid, with honest uncertainty.

THE QUESTION A CURVE ANSWERS. At a fixed cap (the budget an arm may NOT exceed), how often does each
arm end correct, how often does it make a false discovery, and how much does it ACTUALLY spend? An
arm that stops after one cheap experiment has not used its cap, so "matched budget" means equal caps
AND reported realized use -- never the cap quoted as the cost.

    run_grid            every world, every cap, every arm, through a blind, metered laboratory:
                        realized cost is the laboratory meter's count, checked equal to what the
                        engine reports; the meter refuses anything beyond the cap
    summarize_grid      per cap and arm: correct and false-discovery rates (Wilson), realized cost
                        (mean with a seeded bootstrap, median, p90, max), utilisation, the share of
                        runs that ran out of budget, realized cost per correct outcome (a ratio
                        bootstrap), the share of experiments that refuted something; per cap and
                        compared pair: the paired difference (bootstrap, and a Bonferroni-widened
                        interval), the exact McNemar test and Holm-adjusted p-values; over the grid:
                        the normalised area under the correct-rate curve per world (bootstrap,
                        paired differences), budget-to-first-correct (censored at the largest cap),
                        the cumulative share solved by each cap, and where a curve goes down
    grid_invariants     what holds by construction and is checked, not hoped: realized cost never
                        exceeds the cap; the meter agrees with the engine; and a run that ended with
                        at least the dearest available experiment's cost unspent never had a choice
                        restricted by its cap, so at every larger cap it is the same run (same
                        experiments, outcome, claim and cost). The share of such unconstrained runs
                        is therefore non-decreasing in the cap. The correct rate itself is NOT
                        monotone by construction (a larger cap can change which experiment is
                        affordable and so the path); where it goes down is reported.

Every interval describes the sampling noise of these synthetic worlds and nothing beyond them.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery import benchmark
from lab_brain.discovery.benchmark import Arm, Scenario
from lab_brain.discovery.metrics import Scorer, bootstrap_mean, mean, rate
from lab_brain.discovery.model import Budget, DiscoveryResult, DiscoveryState, ExperimentSpec
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory

#: The pre-registered comparisons: the discovery arm against each baseline.
COMPARISONS: tuple[tuple[str, str], ...] = (("B2", "B1"), ("B2", "B0"))


@dataclass(frozen=True)
class CapRow:
    """One arm on one world at one cap."""

    world_id: str
    kind: str
    arm: str
    cap: int
    #: Realized cost: what the laboratory's meter charged.
    spent: int
    #: What the engine reported spending; must equal `spent`.
    reported_spent: int
    correct: bool
    false_discovery: bool
    claim_made: bool
    outcome: str
    claim: tuple[str, ...]
    experiments: tuple[str, ...]
    #: Experiments after which at least one registered hypothesis was refuted.
    discriminating: int
    #: The cap left at least the dearest available experiment's cost unspent.
    unconstrained: bool
    #: The cap left less than the cheapest available experiment's cost.
    exhausted: bool
    digest: str


def shared_protocol(arms: Sequence[Arm]) -> DiscoveryProtocol:
    keys = {(a.protocol.distinguish_tau, a.protocol.distinguish_replicates) for a in arms}
    if len(keys) != 1:
        raise ValueError("every arm must share one distinguishability definition")
    return arms[0].protocol


def discriminating_experiments(result: DiscoveryResult) -> int:
    """How many of the run's experiments were followed by at least one refutation."""
    refuted_at = {
        event.step
        for record in result.hypotheses
        for event in record.history
        if event.state == DiscoveryState.REFUTED.value
    }
    return sum(1 for step in result.steps if step.step in refuted_at)


def all_experiments(scenario: Scenario) -> dict[str, ExperimentSpec]:
    catalog = scenario.catalog
    return {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }


def run_grid(scenario: Scenario, caps: Sequence[int], arms: Sequence[Arm]) -> list[CapRow]:
    """Every world x cap x arm through a blind, metered laboratory. Deterministic in the seeds."""
    if sorted(set(caps)) != list(caps):
        raise ValueError("caps are strictly increasing")
    oracles = benchmark.Oracles(scenario.catalog, shared_protocol(arms))
    scorer = Scorer(scenario.catalog)
    experiments = all_experiments(scenario)
    costs = {k: e.cost for k, e in experiments.items()}
    rows: list[CapRow] = []
    for world in scenario.worlds:
        oracle = oracles.for_world(world)
        available = tuple(e.experiment_id for e in oracle.available)
        dearest = max(e.cost for e in oracle.available)
        cheapest = min(e.cost for e in oracle.available)
        for cap in caps:
            for arm in arms:
                meter = CostMeter(costs, cap)
                lab = blind_laboratory(
                    benchmark.lab_for(scenario, world),
                    experiments=experiments,
                    available=available,
                    meter=meter,
                )
                result = arm.runner(
                    arm=arm.arm_id,
                    catalog=scenario.catalog,
                    oracle=oracle,
                    protocol=arm.protocol,
                    budget=Budget(cap),
                    lab=lab,
                )
                score = scorer.score(world, result, oracle)
                rows.append(
                    CapRow(
                        world_id=world.world_id,
                        kind=world.kind,
                        arm=arm.arm_id,
                        cap=cap,
                        spent=meter.spent,
                        reported_spent=result.spent,
                        correct=score.correct,
                        false_discovery=score.false_discovery,
                        claim_made=score.claim_made,
                        outcome=score.outcome,
                        claim=result.claim,
                        experiments=tuple(s.experiment_id for s in result.steps),
                        discriminating=discriminating_experiments(result),
                        unconstrained=cap - meter.spent >= dearest,
                        exhausted=cap - meter.spent < cheapest,
                        digest=result.digest,
                    )
                )
    return rows


# -- statistics ----------------------------------------------------------------------------------


def normalized_auc(caps: Sequence[int], values: Sequence[float]) -> float:
    """Trapezoidal area under `values` over `caps`, divided by the cap range (so in [0, 1])."""
    if len(caps) != len(values) or len(caps) < 2:
        raise ValueError("an area needs at least two caps and one value per cap")
    area = math.fsum(
        (caps[i + 1] - caps[i]) * (values[i] + values[i + 1]) / 2.0 for i in range(len(caps) - 1)
    )
    return area / (caps[-1] - caps[0])


def first_correct(caps: Sequence[int], flags: Sequence[bool]) -> int | None:
    """The smallest cap at which the run is correct; None when it never is (censored)."""
    return next((c for c, f in zip(caps, flags, strict=True) if f), None)


def lower_median(values: Sequence[int | None]) -> int | None:
    """The nearest-rank (lower) median with None as +infinity; None when it is not reached."""
    if not values:
        return None
    ordered = sorted(values, key=lambda v: (v is None, v or 0))
    return ordered[math.ceil(len(ordered) / 2) - 1]


def bootstrap_lower_median(
    values: Sequence[int | None], *, seed: int, resamples: int, label: str
) -> tuple[int | None, int | None] | None:
    """Percentile interval of the censored lower median; None bounds mean "beyond the grid"."""
    if not values:
        return None
    rng = random.Random(f"{seed}:{label}")
    n = len(values)
    medians = [lower_median([values[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples)]
    medians.sort(key=lambda v: (v is None, v or 0))
    low = medians[max(0, math.ceil(0.025 * resamples) - 1)]
    high = medians[min(resamples - 1, math.ceil(0.975 * resamples) - 1)]
    return low, high


def ratio_bootstrap(
    numerator: Sequence[float],
    denominator: Sequence[float],
    *,
    seed: int,
    resamples: int,
    label: str,
) -> dict[str, Any]:
    """sum(numerator) / sum(denominator) over worlds, with a seeded paired percentile bootstrap.
    Resamples whose denominator is zero have no ratio; how many there were is reported."""
    if len(numerator) != len(denominator):
        raise ValueError("a ratio needs one numerator and one denominator per world")
    total = math.fsum(denominator)
    point = round(math.fsum(numerator) / total, 4) if total else None
    rng = random.Random(f"{seed}:{label}")
    n = len(numerator)
    ratios: list[float] = []
    undefined = 0
    for _ in range(resamples if n else 0):
        picks = [rng.randrange(n) for _ in range(n)]
        den = math.fsum(denominator[i] for i in picks)
        if den == 0:
            undefined += 1
            continue
        ratios.append(math.fsum(numerator[i] for i in picks) / den)
    ratios.sort()
    interval = None
    if ratios:
        k = len(ratios)
        interval = (
            round(ratios[max(0, math.ceil(0.025 * k) - 1)], 4),
            round(ratios[min(k - 1, math.ceil(0.975 * k) - 1)], 4),
        )
    return {"point": point, "bootstrap95": interval, "undefined_resamples": undefined}


def exact_mcnemar(a_only: int, b_only: int) -> float:
    """Two-sided exact McNemar p-value: a binomial(n, 1/2) test on the discordant pairs."""
    n = a_only + b_only
    if n == 0:
        return 1.0
    tail = math.fsum(math.comb(n, k) for k in range(min(a_only, b_only) + 1)) / 2.0**n
    return min(1.0, 2.0 * tail)


def holm(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (step-down, monotone)."""
    ordered = sorted(pvalues.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - index) * p))
        adjusted[key] = running
    return adjusted


def _quantile(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _index(rows: Sequence[CapRow]) -> dict[tuple[str, str, int], CapRow]:
    return {(r.world_id, r.arm, r.cap): r for r in rows}


def summarize_grid(
    rows: Sequence[CapRow],
    *,
    caps: Sequence[int],
    arms: Sequence[str],
    seed: int,
    resamples: int,
    comparisons: Sequence[tuple[str, str]] = COMPARISONS,
) -> dict[str, Any]:
    by = _index(rows)
    worlds = sorted({r.world_id for r in rows}, key=lambda w: (w.rsplit("-", 1)[0], w))
    comparisons = [(a, b) for a, b in comparisons if a in arms and b in arms]
    per_cap: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    pvalues: dict[str, float] = {}
    family = max(1, len(caps) * len(comparisons))
    for cap in caps:
        cap_key = str(cap)
        per_cap[cap_key] = {}
        for arm in arms:
            chosen = [by[(w, arm, cap)] for w in worlds]
            spent = [r.spent for r in chosen]
            n_correct = sum(1 for r in chosen if r.correct)
            experiments = sum(len(r.experiments) for r in chosen)
            per_cap[cap_key][arm] = {
                "correct": rate([r.correct for r in chosen]),
                "false_discovery": rate([r.false_discovery for r in chosen]),
                "claims_made": rate([r.claim_made for r in chosen]),
                "realized_cost": mean(
                    [float(s) for s in spent],
                    seed=seed,
                    resamples=resamples,
                    label=f"{arm}:{cap}:realized",
                ),
                "realized_cost_median": _quantile(spent, 0.5),
                "realized_cost_p90": _quantile(spent, 0.9),
                "realized_cost_max": max(spent) if spent else None,
                "realized_total": sum(spent),
                "nominal_total": cap * len(chosen),
                "utilisation": round(sum(spent) / (cap * len(chosen)), 4) if chosen else None,
                "exhausted": rate([r.exhausted for r in chosen]),
                "unconstrained": rate([r.unconstrained for r in chosen]),
                "realized_cost_per_correct": ratio_bootstrap(
                    [float(s) for s in spent],
                    [1.0 if r.correct else 0.0 for r in chosen],
                    seed=seed,
                    resamples=resamples,
                    label=f"{arm}:{cap}:cost_per_correct",
                ),
                "mean_experiments": round(experiments / len(chosen), 4) if chosen else None,
                "discriminating_share": (
                    round(sum(r.discriminating for r in chosen) / experiments, 4)
                    if experiments
                    else None
                ),
                "correct_count": n_correct,
            }
        for a, b in comparisons:
            key = f"{a}_minus_{b}@{cap}"
            fa = [by[(w, a, cap)] for w in worlds]
            fb = [by[(w, b, cap)] for w in worlds]
            diffs = [float(x.correct) - float(y.correct) for x, y in zip(fa, fb, strict=True)]
            a_only = sum(1 for x, y in zip(fa, fb, strict=True) if x.correct and not y.correct)
            b_only = sum(1 for x, y in zip(fa, fb, strict=True) if y.correct and not x.correct)
            p = exact_mcnemar(a_only, b_only)
            pvalues[key] = p
            cost_diffs = [float(x.spent - y.spent) for x, y in zip(fa, fb, strict=True)]
            fd_diffs = [
                float(x.false_discovery) - float(y.false_discovery)
                for x, y in zip(fa, fb, strict=True)
            ]
            paired[key] = {
                "correct_difference": round(math.fsum(diffs) / len(diffs), 4),
                "correct_ci95": bootstrap_mean(
                    diffs, seed=seed, resamples=resamples, label=f"paired:{key}"
                ),
                "correct_ci_bonferroni": bootstrap_mean(
                    diffs,
                    seed=seed,
                    resamples=resamples,
                    label=f"paired:{key}",
                    confidence=1 - 0.05 / family,
                ),
                "a_only": a_only,
                "b_only": b_only,
                "mcnemar_p": round(p, 6),
                "false_discovery_difference": round(math.fsum(fd_diffs) / len(fd_diffs), 4),
                "false_discovery_ci95": bootstrap_mean(
                    fd_diffs, seed=seed, resamples=resamples, label=f"paired:{key}:fd"
                ),
                "realized_cost_difference": round(math.fsum(cost_diffs) / len(cost_diffs), 4),
                "realized_cost_ci95": bootstrap_mean(
                    cost_diffs, seed=seed, resamples=resamples, label=f"paired:{key}:cost"
                ),
            }
    adjusted = holm(pvalues)
    for key, value in adjusted.items():
        paired[key]["holm_p"] = round(value, 6)
    auc: dict[str, Any] = {}
    per_world_auc: dict[str, list[float]] = {}
    bfc: dict[str, Any] = {}
    cumulative: dict[str, Any] = {}
    curve: dict[str, Any] = {}
    decreases: dict[str, Any] = {}
    for arm in arms:
        values = [
            normalized_auc(caps, [float(by[(w, arm, c)].correct) for c in caps]) for w in worlds
        ]
        per_world_auc[arm] = values
        auc[arm] = {
            "mean": round(math.fsum(values) / len(values), 4),
            "bootstrap95": bootstrap_mean(
                values, seed=seed, resamples=resamples, label=f"{arm}:auc"
            ),
        }
        firsts = [first_correct(caps, [by[(w, arm, c)].correct for c in caps]) for w in worlds]
        solved = [f is not None for f in firsts]
        realized_first = [
            float(by[(w, arm, f)].spent) for w, f in zip(worlds, firsts, strict=True) if f
        ]
        stable = [
            all(by[(w, arm, c)].correct for c in caps if c >= f)
            for w, f in zip(worlds, firsts, strict=True)
            if f is not None
        ]
        bfc[arm] = {
            "solved_within_grid": rate(solved),
            "median_first_correct_cap": lower_median(firsts),
            "median_first_correct_cap_bootstrap95": bootstrap_lower_median(
                firsts, seed=seed, resamples=resamples, label=f"{arm}:bfc"
            ),
            "realized_cost_at_first_correct": mean(
                realized_first, seed=seed, resamples=resamples, label=f"{arm}:bfc_realized"
            ),
            "stays_correct_at_every_larger_cap": rate(stable),
        }
        cumulative[arm] = {
            str(c): round(sum(1 for f in firsts if f is not None and f <= c) / len(firsts), 4)
            for c in caps
        }
        points = [
            [
                c,
                per_cap[str(c)][arm]["realized_cost"]["mean"],
                per_cap[str(c)][arm]["correct"]["rate"],
            ]
            for c in caps
        ]
        curve[arm] = points
        decreases[arm] = [
            [points[i][0], points[i + 1][0], points[i][2], points[i + 1][2]]
            for i in range(len(points) - 1)
            if points[i + 1][2] < points[i][2]
        ]
    auc_paired: dict[str, Any] = {}
    for a, b in comparisons:
        diffs = [x - y for x, y in zip(per_world_auc[a], per_world_auc[b], strict=True)]
        auc_paired[f"{a}_minus_{b}"] = {
            "mean": round(math.fsum(diffs) / len(diffs), 4),
            "bootstrap95": bootstrap_mean(
                diffs, seed=seed, resamples=resamples, label=f"auc:{a}-{b}"
            ),
            "worlds": len(diffs),
        }
    return {
        "caps": list(caps),
        "arms": list(arms),
        "worlds": len(worlds),
        "per_cap": per_cap,
        "paired_per_cap": paired,
        "multiplicity": {
            "family": "per-cap paired correct-rate comparisons",
            "size": len(pvalues),
            "test": "exact McNemar (two-sided)",
            "adjustment": "Holm-Bonferroni",
            "bonferroni_interval_confidence": round(1 - 0.05 / family, 6),
        },
        "auc_correct_vs_cap": auc,
        "auc_paired": auc_paired,
        "budget_to_first_correct": bfc,
        "cumulative_solved_by_cap": cumulative,
        "curve_points_cap_realized_correct": curve,
        "correct_rate_decreases": decreases,
    }


def grid_invariants(rows: Sequence[CapRow], caps: Sequence[int]) -> dict[str, Any]:
    """The properties that hold by construction, checked on every row."""
    by = _index(rows)
    over_cap = [f"{r.world_id}:{r.arm}@{r.cap}" for r in rows if r.spent > r.cap]
    meter_mismatch = [f"{r.world_id}:{r.arm}@{r.cap}" for r in rows if r.spent != r.reported_spent]
    checked = 0
    violations: list[str] = []
    for world_id, arm in sorted({(r.world_id, r.arm) for r in rows}):
        for i, cap in enumerate(caps):
            row = by[(world_id, arm, cap)]
            if not row.unconstrained:
                continue
            for larger in caps[i + 1 :]:
                other = by[(world_id, arm, larger)]
                checked += 1
                same = (other.experiments, other.outcome, other.claim, other.spent) == (
                    row.experiments,
                    row.outcome,
                    row.claim,
                    row.spent,
                )
                if not same or not other.unconstrained:
                    violations.append(f"{world_id}:{arm} {cap}->{larger}")
            break
    shares: dict[str, list[float]] = {}
    for arm in sorted({r.arm for r in rows}):
        shares[arm] = []
        for cap in caps:
            chosen = [r for r in rows if r.arm == arm and r.cap == cap]
            shares[arm].append(round(sum(r.unconstrained for r in chosen) / len(chosen), 4))
    non_decreasing = all(all(s[i] <= s[i + 1] for i in range(len(s) - 1)) for s in shares.values())
    return {
        "runs": len(rows),
        "realized_within_cap": not over_cap,
        "over_cap": over_cap,
        "meter_equals_engine_report": not meter_mismatch,
        "meter_mismatch": meter_mismatch,
        "unconstrained_runs_identical_at_larger_caps": {
            "comparisons": checked,
            "violations": violations,
        },
        "unconstrained_share_by_cap": shares,
        "unconstrained_share_non_decreasing": non_decreasing,
    }


def rows_as_json(rows: Sequence[CapRow]) -> list[dict[str, Any]]:
    """Per world: kind and, per arm and cap, the row's essentials (compact, deterministic)."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = out.setdefault(r.world_id, {"world_id": r.world_id, "kind": r.kind, "arms": {}})
        entry["arms"].setdefault(r.arm, {})[str(r.cap)] = {
            "spent": r.spent,
            "correct": r.correct,
            "false_discovery": r.false_discovery,
            "outcome": r.outcome,
            "claim": list(r.claim),
            "experiments": len(r.experiments),
            "discriminating": r.discriminating,
            "exhausted": r.exhausted,
            "unconstrained": r.unconstrained,
            "digest": r.digest,
        }
    return list(out.values())


__all__ = [
    "COMPARISONS",
    "CapRow",
    "bootstrap_lower_median",
    "discriminating_experiments",
    "exact_mcnemar",
    "first_correct",
    "grid_invariants",
    "holm",
    "lower_median",
    "normalized_auc",
    "ratio_bootstrap",
    "rows_as_json",
    "run_grid",
    "shared_protocol",
    "summarize_grid",
]
