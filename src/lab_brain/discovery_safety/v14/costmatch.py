"""Comparing arms at equal realized cost WORLD BY WORLD, instead of at equal mean cost.

WHY. v1.3 called a comparison COST_MATCHED when the arms' MEAN realized cost over the worlds was
close (`v13.evaluation.matched_comparisons`). A close mean hides what happened per world: one arm
spends 2 units on a world where the other spends 20 and the reverse elsewhere; an arm that stops
early on easy worlds and runs to the cap on hard ones has a mean like an arm that spends evenly;
a cap censors the dearer arm; and the paired difference in outcomes is then confounded by the
difference in cost on each world. `cost_contrast` measures all of this on any row file.

THE METHOD (`per_world_matched`). Each arm's run at cap k is its ANYTIME answer for budget k: what
it commits to when allowed k units; its realized cost r(k) <= k is the evaluator's meter. For a
pair (Y, X) and an anchor cap K, on each world w:

    c_w        = min(r_Y(K), r_X(K))           the common per-world cost point: the lower of the two
                                               realized costs at the anchor cap
    answer_A   = the run of arm A, among its caps <= K, whose realized cost is nearest c_w within
                 `tolerance` units (ties: the cheaper run, then the larger cap) -- A's anytime
                 answer at cost c_w
    matched    iff both arms have such an answer

The arm that spent less at K contributes its cap-K answer; the arm that spent more contributes the
answer it gave under a smaller cap at (about) the same realized cost. A world where the dearer arm
has no answer within the tolerance is UNMATCHED: it is counted and described (which arm was dearer,
each arm's outcomes there), never averaged into the difference. Differences Y - X are paired over
the matched worlds with a paired-bootstrap 95 % interval (SHA-256 counter-mode resampling, as v1.3).
The cost distribution (quantiles, share of runs that ended at the cap) is reported beside every
comparison.

LIMIT. Matching conditions on realized cost, which depends on the world and the arm: the matched
worlds are a selected subset (often the cheaper or easier worlds), so a matched difference is a
statement about those worlds, not about all of them; the unmatched worlds are reported for that
reason. Anytime answers come only from the cap grid: a denser grid matches more worlds.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from lab_brain.discovery_safety.v13.evaluation import _bootstrap

Cell = Mapping[str, Any]
#: Per world: arm -> cap (as a string) -> the row file's cell ({"spent", "category", ...}).
Row = Mapping[str, Any]

CREDITED = ("EXACT_IDENTIFICATION", "INDISTINGUISHABLE_ALTERNATIVE", "VALIDATED_NEW_MECHANISM")
ERRORS = ("FORCE_FIT", "WRONG_CLAIM", "UNSUPPORTED_CLAIM")
METRICS: dict[str, Callable[[Cell], float]] = {
    "credited": lambda c: float(c["category"] in CREDITED),
    "errors_c5": lambda c: float(c["category"] in ERRORS),
    "supported_errors": lambda c: float(c["category"] in ("FORCE_FIT", "WRONG_CLAIM")),
    "own_correct": lambda c: float(bool(c["own_correct"])),
    "own_error": lambda c: float(bool(c["own_error"])),
}


def _quantile(values: Sequence[int], q: float) -> float:
    """Nearest-rank on the sorted values (no interpolation)."""
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))])


def cost_distribution(spent: Sequence[int], cap: int, cheapest: int = 1) -> dict[str, Any]:
    """Realized costs of a set of runs at one cap: mean, quantiles, and the share that ended
    unable to afford the cheapest experiment (`at_cap`: the cap censored them)."""
    if not spent:
        return {"n": 0}
    n = len(spent)
    return {
        "n": n,
        "mean": round(sum(spent) / n, 4),
        "min": min(spent),
        "p10": _quantile(spent, 0.10),
        "p25": _quantile(spent, 0.25),
        "median": _quantile(spent, 0.50),
        "p75": _quantile(spent, 0.75),
        "p90": _quantile(spent, 0.90),
        "max": max(spent),
        "at_cap": round(sum(1 for s in spent if cap - s < cheapest) / n, 4) if cap else None,
    }


def anytime(
    cells: Mapping[str, Cell], cost: int, max_cap: int, tolerance: int
) -> tuple[int, Cell] | None:
    """(cap, cell) of the run, among caps <= max_cap, whose realized cost is nearest `cost` within
    `tolerance` (ties: the cheaper run, then the larger cap); None when there is none."""
    best: tuple[tuple[int, int, int], int, Cell] | None = None
    for cap_text, cell in cells.items():
        cap = int(cap_text)
        gap = abs(int(cell["spent"]) - cost)
        if cap > max_cap or gap > tolerance:
            continue
        key = (gap, int(cell["spent"]), -cap)
        if best is None or key < best[0]:
            best = (key, cap, cell)
    return None if best is None else (best[1], best[2])


def per_world_matched(
    rows: Sequence[Row],
    y: str,
    x: str,
    anchor: int,
    *,
    tolerance: int,
    resamples: int,
    label: str,
) -> dict[str, Any]:
    """The per-world matched comparison of Y and X at anchor cap `anchor` (see the module text)."""
    matched: list[tuple[str, int, Cell, int, Cell, int]] = []
    unmatched: list[tuple[str, str, Cell, Cell]] = []
    for row in rows:
        arms = row["arms"]
        if y not in arms or x not in arms:
            continue
        ky, kx = arms[y].get(str(anchor)), arms[x].get(str(anchor))
        if ky is None or kx is None:
            continue
        point = min(int(ky["spent"]), int(kx["spent"]))
        ay = anytime(arms[y], point, anchor, tolerance)
        ax = anytime(arms[x], point, anchor, tolerance)
        if ay is None or ax is None:
            dearer = y if ky["spent"] > kx["spent"] else x
            unmatched.append((str(row["world_id"]), dearer, ky, kx))
            continue
        matched.append((str(row["world_id"]), ay[0], ay[1], ax[0], ax[1], point))
    diffs: dict[str, list[float]] = {
        "cost": [float(cy["spent"] - cx["spent"]) for _, _, cy, _, cx, _ in matched]
    }
    for name, f in METRICS.items():
        diffs[name] = [f(cy) - f(cx) for _, _, cy, _, cx, _ in matched]
    ci = _bootstrap(diffs, resamples, f"lab-brain/v1.4/per-world/{label}/{y}-{x}/{anchor}")

    def means(cells: Sequence[Cell]) -> dict[str, float | None]:
        return {
            k: (round(math.fsum(f(c) for c in cells) / len(cells), 4) if cells else None)
            for k, f in METRICS.items()
        }

    return {
        "y": y,
        "x": x,
        "anchor_cap": anchor,
        "tolerance": tolerance,
        "worlds": len(matched) + len(unmatched),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "unmatched_y_dearer": sum(1 for _, d, _, _ in unmatched if d == y),
        "unmatched_x_dearer": sum(1 for _, d, _, _ in unmatched if d == x),
        "matched_cost_point": cost_distribution([p for *_, p in matched], anchor),
        "matched_caps_used": {
            y: dict(sorted(_count(k for _, k, _, _, _, _ in matched).items())),
            x: dict(sorted(_count(k for _, _, _, k, _, _ in matched).items())),
        },
        "differences": {k: {"mean": v[0], "ci95": [v[1], v[2]]} for k, v in sorted(ci.items())},
        "matched_means": {
            y: means([c for _, _, c, _, _, _ in matched]),
            x: means([c for _, _, _, _, c, _ in matched]),
        },
        "unmatched_means_at_anchor": {
            y: means([c for _, _, c, _ in unmatched]),
            x: means([c for _, _, _, c in unmatched]),
        },
    }


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def cost_contrast(
    rows: Sequence[Row], y: str, x: str, cap: int, *, tolerance: int, resamples: int, label: str
) -> dict[str, Any]:
    """What a MEAN-cost match at equal cap hides, on one row file: the mean cost difference and its
    bootstrap interval (v1.3's basis), the per-world cost differences, the cap-censored shares,
    and the outcome difference split by which arm spent more on the world."""
    pairs = [
        (r["arms"][y][str(cap)], r["arms"][x][str(cap)])
        for r in rows
        if str(cap) in r["arms"].get(y, {}) and str(cap) in r["arms"].get(x, {})
    ]
    dcost = [int(cy["spent"]) - int(cx["spent"]) for cy, cx in pairs]
    ci = _bootstrap(
        {"cost": [float(d) for d in dcost]},
        resamples,
        f"lab-brain/v1.4/contrast/{label}/{y}-{x}/{cap}",
    )["cost"]
    strata: dict[str, Any] = {}
    bands: list[tuple[str, Callable[[int], bool]]] = [
        (f"{y} spent more", lambda d: d > tolerance),
        ("within tolerance", lambda d: abs(d) <= tolerance),
        (f"{x} spent more", lambda d: d < -tolerance),
    ]
    for name, keep in bands:
        chosen = [(cy, cx) for (cy, cx), d in zip(pairs, dcost, strict=True) if keep(d)]
        strata[name] = {
            "worlds": len(chosen),
            "own_correct_difference": round(
                math.fsum(METRICS["own_correct"](a) - METRICS["own_correct"](b) for a, b in chosen)
                / len(chosen),
                4,
            )
            if chosen
            else None,
            "credited_difference": round(
                math.fsum(METRICS["credited"](a) - METRICS["credited"](b) for a, b in chosen)
                / len(chosen),
                4,
            )
            if chosen
            else None,
        }
    return {
        "y": y,
        "x": x,
        "cap": cap,
        "worlds": len(pairs),
        "mean_cost": {
            y: round(math.fsum(int(a["spent"]) for a, _ in pairs) / len(pairs), 4),
            x: round(math.fsum(int(b["spent"]) for _, b in pairs) / len(pairs), 4),
        },
        "mean_cost_difference": {"mean": ci[0], "ci95": [ci[1], ci[2]]},
        "v13_basis_would_say": "COST_MATCHED"
        if ci[1] >= -1.0 and ci[2] <= 1.0
        else "COST_UNMATCHED",
        "per_world_cost_difference": cost_distribution(dcost, 0),
        "worlds_beyond_tolerance": sum(1 for d in dcost if abs(d) > tolerance),
        "cost": {
            y: cost_distribution([int(a["spent"]) for a, _ in pairs], cap),
            x: cost_distribution([int(b["spent"]) for _, b in pairs], cap),
        },
        "outcome_by_cost_stratum": strata,
    }


__all__ = [
    "METRICS",
    "anytime",
    "cost_contrast",
    "cost_distribution",
    "per_world_matched",
]
