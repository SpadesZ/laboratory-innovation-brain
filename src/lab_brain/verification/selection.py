"""§9.2's ordering, made deterministic by §9.6's SelectionPolicy (VER-003, VER-005).

    §9.2  排序依據為：1 能否改變決策（sufficiency，二元） 2 預測分歧程度 3 CostVector 上的 Pareto
          支配關係 4 版本化 SelectionPolicy 的 lexicographic fallback
    VER-005 identical input + identical policy version MUST return an identical ranked plan.

THE ORDER, AND ONE INTERPRETATION IT NEEDS.

    1. sufficient before insufficient            (§9.1, binary)
    2. discriminating before not                 (a KNOWN, positive disagreement between rivals
                                                  over the action's observable)
    3. Pareto layer on the policy's dimensions   (computed within the group from 1-2, so an
                                                  irrelevant insufficient candidate cannot demote
                                                  a sufficient one by dominating it)
    4. the policy's lexicographic fallback
    5. the policy's tie-break rule

Criterion 2 is binary here, not a magnitude, and that is a reading of §9.1 rather than a shortcut:
"the disagreement metric MAY differ by domain" and is declared per OutcomeSpace, so two actions
producing different observables are measured by different metrics. Ranking 0.5 under a rank
distance above 1.0 under a categorical mismatch would be imposing one universal distance on
metrics §9.1 says core must not unify. What every metric does answer is whether the rivals are
predicted to disagree at all -- so that is what is compared.

NOTHING IS SUMMED. Every comparison below is per dimension. `dimension_value` maps each §9.4 field
to an ordered value (lower is cheaper) and nothing ever adds two of them together.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from lab_brain.core.models.cost import CostVector, DependencyRisk
from lab_brain.core.models.verification import CostDimension, SelectionPolicy

_RISK_ORDER = {
    DependencyRisk.NONE: 0,
    DependencyRisk.LOW: 1,
    DependencyRisk.MEDIUM: 2,
    DependencyRisk.HIGH: 3,
}

_NOW: tuple[int] = (0,)


def dimension_value(cost: CostVector, dimension: CostDimension) -> tuple[int, ...] | Decimal:
    """One dimension of a CostVector as an ordered value; lower is cheaper. Never a sum."""
    if dimension is CostDimension.IRREVERSIBLE:
        return (1,) if cost.irreversible else (0,)
    if dimension is CostDimension.DEPENDENCY_RISK:
        return (_RISK_ORDER[cost.dependency_risk],)
    if dimension is CostDimension.EARLIEST_AVAILABLE_AT:
        at = cost.earliest_available_at
        # Available now (None) sorts before any future date; dates compare by epoch microseconds.
        return _NOW if at is None else (1, int(at.astimezone(dt.UTC).timestamp() * 1_000_000))
    return Decimal(getattr(cost, dimension.value))


@dataclass(frozen=True)
class SelectionCandidate:
    """What selection needs to know about one candidate action -- and nothing scalar."""

    action_id: str
    cost: CostVector
    sufficient: bool
    discriminating: bool


def dominates(a: CostVector, b: CostVector, dimensions: Sequence[CostDimension]) -> bool:
    """a is no worse than b on every dimension and strictly better on at least one."""
    no_worse = all(_le(dimension_value(a, d), dimension_value(b, d)) for d in dimensions)
    better = any(_lt(dimension_value(a, d), dimension_value(b, d)) for d in dimensions)
    return no_worse and better


def _le(x: tuple[int, ...] | Decimal, y: tuple[int, ...] | Decimal) -> bool:
    return x <= y  # type: ignore[operator]


def _lt(x: tuple[int, ...] | Decimal, y: tuple[int, ...] | Decimal) -> bool:
    return x < y  # type: ignore[operator]


def pareto_layers(
    candidates: Sequence[SelectionCandidate], dimensions: Sequence[CostDimension]
) -> dict[str, int]:
    """Non-dominated sorting: layer 0 is the front, layer 1 the front once it is removed, ..."""
    remaining = {c.action_id: c for c in candidates}
    layers: dict[str, int] = {}
    layer = 0
    while remaining:
        front = sorted(
            a
            for a, c in remaining.items()
            if not any(
                dominates(o.cost, c.cost, dimensions) for b, o in remaining.items() if b != a
            )
        )
        for action_id in front:
            layers[action_id] = layer
            del remaining[action_id]
        layer += 1
    return layers


def dominated_by(
    candidate: SelectionCandidate,
    group: Sequence[SelectionCandidate],
    dimensions: Sequence[CostDimension],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            other.action_id
            for other in group
            if other.action_id != candidate.action_id
            and dominates(other.cost, candidate.cost, dimensions)
        )
    )


def _lexicographic(cost: CostVector, policy: SelectionPolicy) -> tuple[object, ...]:
    return tuple(dimension_value(cost, d) for d in policy.lexicographic_fallback)


@dataclass(frozen=True)
class Ranking:
    ranked_ids: tuple[str, ...]
    #: Pareto layer of each candidate within its (sufficient, discriminating) group.
    layers: dict[str, int]
    #: Layer 0 of the leading group -- the front the choice was made from.
    front_ids: tuple[str, ...]


def rank(candidates: Sequence[SelectionCandidate], policy: SelectionPolicy) -> Ranking:
    """§9.2's order under `policy`. A pure function of its arguments (VER-005)."""
    groups: dict[tuple[bool, bool], list[SelectionCandidate]] = {}
    for candidate in candidates:
        groups.setdefault((candidate.sufficient, candidate.discriminating), []).append(candidate)
    layers: dict[str, int] = {}
    for group in groups.values():
        layers.update(pareto_layers(group, policy.pareto_dimensions))

    def key(c: SelectionCandidate) -> tuple[object, ...]:
        return (
            not c.sufficient,
            not c.discriminating,
            layers[c.action_id],
            *_lexicographic(c.cost, policy),
            c.action_id,  # TieBreakRule.CAPABILITY_ID -- the only rule §9.6's policy may name here
        )

    ranked = tuple(c.action_id for c in sorted(candidates, key=key))
    leading = sorted(candidates, key=key)[0] if candidates else None
    front = (
        tuple(
            sorted(
                c.action_id
                for c in groups[(leading.sufficient, leading.discriminating)]
                if layers[c.action_id] == 0
            )
        )
        if leading is not None
        else ()
    )
    return Ranking(ranked_ids=ranked, layers=layers, front_ids=front)


def cost_order(
    candidates: Sequence[SelectionCandidate], policy: SelectionPolicy
) -> tuple[str, ...]:
    """The candidates by cost alone -- Pareto layer, then fallback, then tie-break.

    Used for the escalation record: which candidates would have been cheaper than the chosen one,
    had sufficiency not mattered. Every such candidate must carry a reason in the plan (VER-001).
    """
    layers = pareto_layers(candidates, policy.pareto_dimensions)
    return tuple(
        c.action_id
        for c in sorted(
            candidates,
            key=lambda c: (layers[c.action_id], *_lexicographic(c.cost, policy), c.action_id),
        )
    )


__all__ = [
    "Ranking",
    "SelectionCandidate",
    "cost_order",
    "dimension_value",
    "dominated_by",
    "dominates",
    "pareto_layers",
    "rank",
]
