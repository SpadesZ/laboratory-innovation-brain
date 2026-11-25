"""The pre-registered analysis (`plan.AnalysisPlan`) over the scorer's per-checkpoint rows.

A row is one (case, arm, checkpoint): `case_id`, `arm`, `world_category` (after the reveal),
`checkpoint`, `deficient`, `status`, and the indicators `exact`, `credited`, `error`,
`own_correct`, plus `spent_total` (the meter's charge for the whole run).

Statistics (all deterministic):

    paired bootstrap   resample cases with replacement; the k-th index of resample b is taken from
                       SHA-256(label || seed || b) in counter mode (4 bytes per index, reduced
                       modulo n), so the indices are the same on every platform; the same indices
                       are used for every metric and comparison over the same case list (paired,
                       common resamples). Percentile interval: the floor(B * a/2)-th and the
                       ceil(B * (1 - a/2)) - 1-th of the sorted resample means (0-based)
    McNemar            exact two-sided binomial test on the discordant pairs
    Holm               step-down over the filled comparisons within one (metric, checkpoint)
    Wilson             95 % score interval for a single arm's proportion
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from lab_brain.discovery_eval.independent.plan import AnalysisPlan

Row = Mapping[str, Any]
Z975 = 1.959963984540054
Z80 = 0.8416212335729143
INCIDENT_STATUSES = frozenset({"INVALID", "TAMPERED", "TRUNCATED"})


def _r(x: float) -> float:
    return round(x, 6)


@lru_cache(maxsize=16)
def bootstrap_indices(n: int, resamples: int, seed: int, label: str) -> tuple[tuple[int, ...], ...]:
    out: list[tuple[int, ...]] = []
    for b in range(resamples):
        stream = b""
        counter = 0
        while len(stream) < 4 * n:
            stream += hashlib.sha256(f"{label}\x00{seed}\x00{b}\x00{counter}".encode()).digest()
            counter += 1
        out.append(tuple(int.from_bytes(stream[4 * k : 4 * k + 4], "big") % n for k in range(n)))
    return tuple(out)


def percentile_interval(
    values: Sequence[float], *, resamples: int, seed: int, label: str, confidence: float
) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None}
    indices = bootstrap_indices(n, resamples, seed, label)
    means = sorted(math.fsum(values[i] for i in idx) / n for idx in indices)
    alpha = 1.0 - confidence
    lo = means[math.floor(resamples * alpha / 2)]
    hi = means[math.ceil(resamples * (1 - alpha / 2)) - 1]
    return {"n": n, "mean": _r(math.fsum(values) / n), "lo": _r(lo), "hi": _r(hi)}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p-value for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail: float = math.fsum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2.0 * tail)


def holm(pvalues: Mapping[str, float], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    order = sorted(pvalues, key=lambda k: (pvalues[k], k))
    m = len(order)
    out: dict[str, dict[str, Any]] = {}
    running = 0.0
    rejecting = True
    for i, key in enumerate(order):
        adjusted = min(1.0, (m - i) * pvalues[key])
        running = max(running, adjusted)
        rejecting = rejecting and pvalues[key] <= alpha / (m - i)
        out[key] = {"p": _r(pvalues[key]), "holm_p": _r(running), "reject": rejecting}
    return out


def wilson(k: int, n: int, z: float = Z975) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [_r(max(0.0, centre - half)), _r(min(1.0, centre + half))]


# -- paired values with the deficient-record rule -------------------------------------------------

_GOOD = {"exact": True, "credited": True, "own_correct": True, "error": False}


def _value(row: Row, metric: str, role: str) -> float:
    """The indicator; a deficient row is scored against its own arm (Appendix J §3.4)."""
    if row["deficient"]:
        good = _GOOD[metric]
        # the candidate's deficient run counts as the bad value, the reference's as the good one
        bad_for_candidate = (not good) if role == "candidate" else good
        return 1.0 if bad_for_candidate else 0.0
    return 1.0 if row[metric] else 0.0


def _index(rows: Sequence[Row]) -> dict[tuple[str, str, int], Row]:
    return {(str(r["case_id"]), str(r["arm"]), int(r["checkpoint"])): r for r in rows}


def paired(
    rows: Sequence[Row],
    candidate: str,
    reference: str,
    metric: str,
    checkpoint: int,
    cases: Sequence[str],
) -> list[tuple[float, float]]:
    at = _index(rows)
    out = []
    for case in cases:
        x = at.get((case, candidate, checkpoint))
        y = at.get((case, reference, checkpoint))
        if x is None or y is None:
            raise ValueError(f"{case}: a compared arm has no row at checkpoint {checkpoint}")
        out.append((_value(x, metric, "candidate"), _value(y, metric, "reference")))
    return out


def compare(
    rows: Sequence[Row],
    plan: AnalysisPlan,
    candidate: str,
    reference: str,
    metric: str,
    checkpoint: int,
    cases: Sequence[str],
) -> dict[str, Any]:
    """The paired difference candidate - reference over `cases`; the bootstrap indices depend on
    the case list only, so every metric and comparison over the same cases shares them."""
    plan.checkpoint(checkpoint)
    label = "cases:" + hashlib.sha256("\x00".join(cases).encode()).hexdigest()[:16]
    pairs = paired(rows, candidate, reference, metric, checkpoint, cases)
    diffs = [x - y for x, y in pairs]
    b = sum(1 for x, y in pairs if x > y)
    c = sum(1 for x, y in pairs if x < y)
    interval = percentile_interval(
        diffs,
        resamples=plan.bootstrap_resamples,
        seed=plan.bootstrap_seed,
        label=label,
        confidence=plan.confidence,
    )
    return {
        "candidate": candidate,
        "reference": reference,
        "metric": metric,
        "checkpoint": checkpoint,
        "n": len(pairs),
        "candidate_rate": _r(math.fsum(x for x, _ in pairs) / len(pairs)) if pairs else None,
        "reference_rate": _r(math.fsum(y for _, y in pairs) / len(pairs)) if pairs else None,
        "difference": interval,
        "discordant": {"candidate_only": b, "reference_only": c},
        "mcnemar_p": _r(mcnemar_exact(b, c)),
    }


# -- the study ------------------------------------------------------------------------------------


def study_validity(
    rows: Sequence[Row], plan: AnalysisPlan, arms: Sequence[str], cases: Sequence[str]
) -> dict[str, Any]:
    runs = {(str(r["case_id"]), str(r["arm"])): r for r in rows if r["checkpoint"] == plan.cap}
    total = len(runs)
    incidents = sorted(f"{c}:{a}" for (c, a), r in runs.items() if r["status"] in INCIDENT_STATUSES)
    crashed = sorted(f"{c}:{a}" for (c, a), r in runs.items() if r["status"] == "CRASHED")
    deficient_cases = sorted(
        {c for (c, a), r in runs.items() if r["deficient"] and a in arms and c in cases}
    )
    incident_share = len(incidents) / total if total else 0.0
    case_share = len(deficient_cases) / len(cases) if cases else 0.0
    valid = (
        incident_share <= plan.max_incident_share and case_share <= plan.max_deficient_case_share
    )
    return {
        "runs": total,
        "incident_runs": incidents,
        "crashed_runs": crashed,
        "incident_share": _r(incident_share),
        "deficient_cases": deficient_cases,
        "deficient_case_share": _r(case_share),
        "valid": valid,
    }


def decide(
    primary: Mapping[str, Any],
    safety: Mapping[str, Any],
    margin: float,
    valid: bool,
    alpha: float = 0.05,
) -> str:
    """The plan's decision. An interval bound alone never decides a direction: the exact McNemar
    test on the same pairs must also reject at `alpha` (a percentile bootstrap degenerates to a
    point when every discordant pair goes one way, e.g. [1, 1] from five cases)."""
    if not valid:
        return "INVALID"
    p, s = primary["difference"], safety["difference"]
    if p["lo"] is None or s["lo"] is None:
        return "INCONCLUSIVE"
    primary_rejects = primary["mcnemar_p"] < alpha
    safety_rejects = safety["mcnemar_p"] < alpha
    if (p["hi"] < 0 and primary_rejects) or (s["lo"] > 0 and safety_rejects):
        return "WORSE"
    if p["lo"] > 0 and primary_rejects:
        return "BETTER" if s["hi"] <= margin else "SAFETY_FAIL"
    return "INCONCLUSIVE"


def arm_summary(
    rows: Sequence[Row], arm: str, checkpoint: int, cases: Sequence[str]
) -> dict[str, Any]:
    at = _index(rows)
    mine = [at[(c, arm, checkpoint)] for c in cases if (c, arm, checkpoint) in at]
    n = len(mine)
    out: dict[str, Any] = {"n": n}
    for metric in ("exact", "credited", "error", "own_correct"):
        k = sum(1 for r in mine if (r[metric] if not r["deficient"] else metric == "error"))
        out[metric] = {"k": k, "rate": _r(k / n) if n else None, "wilson95": wilson(k, n)}
    out["deficient"] = sum(1 for r in mine if r["deficient"])
    categories: dict[str, int] = {}
    for r in mine:
        categories[str(r["category"])] = categories.get(str(r["category"]), 0) + 1
    out["categories"] = dict(sorted(categories.items()))
    out["no_answer_yet"] = sum(1 for r in mine if not r["deficient"] and r["held"] == "NONE")
    return out


def cost_distribution(values: Sequence[int], cap: int) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def q(p: float) -> int:
        return ordered[max(0, math.ceil(p * len(ordered)) - 1)]

    return {
        "n": len(ordered),
        "mean": _r(math.fsum(ordered) / len(ordered)),
        "median": q(0.5),
        "p90": q(0.9),
        "max": ordered[-1],
        "at_cap": _r(sum(1 for v in ordered if v >= cap) / len(ordered)),
    }


def analyse(
    rows: Sequence[Row],
    plan: AnalysisPlan,
    filled: Sequence[str],
    case_categories: Mapping[str, str],
) -> dict[str, Any]:
    """Everything the plan pre-registers, from the rows alone."""
    filled = tuple(filled)
    all_cases = sorted(case_categories)
    primary_cases = [c for c in all_cases if case_categories[c] in plan.primary_categories]
    safety_cases = [
        c for c in all_cases if case_categories[c] not in plan.safety_excluded_categories
    ]
    candidate, reference = plan.primary_comparison(filled)
    validity = study_validity(rows, plan, (candidate, reference), all_cases)
    primary = compare(
        rows,
        plan,
        candidate,
        reference,
        plan.primary_metric,
        plan.primary_checkpoint,
        primary_cases,
    )
    safety = compare(
        rows,
        plan,
        candidate,
        reference,
        plan.safety_metric,
        plan.primary_checkpoint,
        safety_cases,
    )
    decision = decide(
        primary, safety, plan.non_inferiority_margin, validity["valid"], plan.decision_alpha
    )
    secondary: dict[str, Any] = {}
    for metric in plan.secondary_metrics:
        cases = primary_cases if metric == "exact" else safety_cases
        for checkpoint in plan.ladder:
            key = f"{metric}@{checkpoint}"
            results = {
                f"{a}-{b}": compare(rows, plan, a, b, metric, checkpoint, cases)
                for a, b in plan.filled_comparisons(filled)
            }
            adjusted = holm({k: v["mcnemar_p"] for k, v in results.items()})
            for k, v in results.items():
                v["holm"] = adjusted[k]
            secondary[key] = results
    curves = {
        arm: {
            str(c): {
                "all": arm_summary(rows, arm, c, all_cases),
                "primary_cases": arm_summary(rows, arm, c, primary_cases),
            }
            for c in plan.ladder
        }
        for arm in filled
    }
    auc = {}
    for arm in filled:
        points = [curves[arm][str(c)]["all"]["credited"]["rate"] or 0.0 for c in plan.ladder]
        width = plan.ladder[-1] - plan.ladder[0]
        area = math.fsum(
            (points[i] + points[i + 1]) / 2 * (plan.ladder[i + 1] - plan.ladder[i])
            for i in range(len(points) - 1)
        )
        auc[arm] = _r(area / width) if width else None
    at = _index(rows)
    costs = {
        arm: cost_distribution(
            [
                int(at[(c, arm, plan.cap)]["spent_total"])
                for c in all_cases
                if (c, arm, plan.cap) in at and at[(c, arm, plan.cap)]["spent_total"] is not None
            ],
            plan.cap,
        )
        for arm in filled
    }
    per_category = {
        category: {
            arm: arm_summary(
                rows,
                arm,
                plan.primary_checkpoint,
                [c for c in all_cases if case_categories[c] == category],
            )
            for arm in filled
        }
        for category in sorted(set(case_categories.values()))
    }
    return {
        "plan_digest": plan.digest,
        "arms": list(filled),
        "cases": len(all_cases),
        "primary_cases": len(primary_cases),
        "safety_cases": len(safety_cases),
        "validity": validity,
        "primary": primary,
        "safety": safety,
        "decision": decision,
        "decision_rule": "BETTER iff primary lo > 0, primary exact McNemar p < 0.05 and safety hi "
        "<= margin; WORSE iff (primary hi < 0 and its McNemar p < 0.05) or (safety lo > 0 and its "
        "McNemar p < 0.05); SAFETY_FAIL iff primary lo > 0 with p < 0.05 but safety hi > margin; "
        "else INCONCLUSIVE; INVALID when the study-level deficiency limits are exceeded",
        "secondary": secondary,
        "anytime_curves": curves,
        "anytime_auc_credited_secondary": auc,
        "realized_cost": costs,
        "per_category_at_primary_checkpoint": per_category,
    }


# -- power ----------------------------------------------------------------------------------------


def minimum_detectable_difference(n: int, discordance: float, z_alpha: float = Z975) -> float:
    """The smallest true paired difference d with 80 % power for a two-sided 5 % test of d = 0,
    by the normal approximation to the paired-bootstrap interval: per-case variance
    discordance - d^2, so d = k * sqrt(discordance / (n + k^2)), k = z_alpha + z_power."""
    k = z_alpha + Z80
    return k * math.sqrt(discordance / (n + k * k))


def simulated_power(
    n: int,
    discordance: float,
    difference: float,
    *,
    simulations: int,
    resamples: int,
    seed: int,
) -> float:
    """Share of simulated studies whose paired-bootstrap 95 % lower bound is above zero, when the
    candidate-only and reference-only discordance probabilities are (disc + diff)/2 and
    (disc - diff)/2. Deterministic: SHA-256 counter-mode draws."""
    p_plus = (discordance + difference) / 2
    p_minus = (discordance - difference) / 2
    if p_minus < 0:
        raise ValueError("the difference exceeds the discordance")
    hits = 0
    for s in range(simulations):
        diffs = []
        for i in range(n):
            u = (
                int.from_bytes(
                    hashlib.sha256(f"power\x00{seed}\x00{s}\x00{i}".encode()).digest()[:8], "big"
                )
                / 2**64
            )
            diffs.append(1.0 if u < p_plus else (-1.0 if u < p_plus + p_minus else 0.0))
        interval = percentile_interval(
            diffs, resamples=resamples, seed=seed, label="power", confidence=0.95
        )
        if interval["lo"] is not None and interval["lo"] > 0:
            hits += 1
    return hits / simulations


__all__ = [
    "analyse",
    "arm_summary",
    "bootstrap_indices",
    "compare",
    "cost_distribution",
    "decide",
    "holm",
    "mcnemar_exact",
    "minimum_detectable_difference",
    "paired",
    "percentile_interval",
    "simulated_power",
    "study_validity",
    "wilson",
]
