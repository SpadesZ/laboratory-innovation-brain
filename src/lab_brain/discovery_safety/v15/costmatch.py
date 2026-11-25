"""Per-world matched comparisons (v1.4's method, `v14.costmatch`) with the v1.5 metrics added:

    refuted              rivals closed by a FAILED prediction in the run, excluding refutations of
                         an identity expressing the truth
    avoidable_abstention an abstention (answer NONE) on a supportable world whose diagnosed cause
                         is in the AVOIDABLE bucket (`diagnose.AVOIDABLE_CAUSES`)
    correct_abstention   ... whose cause is in the CORRECT bucket

The matching itself (anytime answers at the lower realized cost, +-tolerance) is v1.4's.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from lab_brain.discovery_safety.v13.evaluation import _bootstrap
from lab_brain.discovery_safety.v14.costmatch import METRICS as METRICS_V14
from lab_brain.discovery_safety.v14.costmatch import anytime, cost_distribution
from lab_brain.discovery_safety.v15.diagnose import AVOIDABLE_CAUSES, CORRECT_CAUSES

Cell = Mapping[str, Any]
Row = Mapping[str, Any]

METRICS: dict[str, Callable[[Cell], float]] = {
    **METRICS_V14,
    "refuted": lambda c: float(int(c.get("refuted", 0)) - int(c.get("refuted_incorrect", 0))),
    "avoidable_abstention": lambda c: float(
        c["answer"] == "NONE" and c.get("cause") in AVOIDABLE_CAUSES
    ),
    "correct_abstention": lambda c: float(
        c["answer"] == "NONE" and c.get("cause") in CORRECT_CAUSES
    ),
}


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
    """v1.4's per-world matched comparison of Y and X at anchor cap `anchor`, v1.5 metrics."""
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
    ci = _bootstrap(diffs, resamples, f"lab-brain/v1.5/per-world/{label}/{y}-{x}/{anchor}")

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


__all__ = ["METRICS", "per_world_matched"]
