"""Candidate and design comparison without a single scalar figure of merit (VER-007, P10, §10.4).

    VER-007  Candidate/design comparison MUST preserve and present multi-objective trade-offs. A
             single scalar figure of merit MUST NOT be the sole keep/discard criterion (P10).
    T-VER-007 ... a scalar-only OutcomeSpace over design quality requires explicit declared
             justification.

KEEP/DISCARD IS DOMINANCE, NOTHING ELSE. A candidate is discarded only when another candidate is at
least as good on EVERY declared objective and strictly better on one -- and the comparison records
which candidates dominate it, so the discard can be checked. Everything on the front is kept, with
its full objective vector: the trade-off is the output, not a step on the way to a number.

ONE OBJECTIVE IS REFUSED, NOT QUIETLY ACCEPTED. A comparison over a single objective is a scalar
figure of merit by definition; it is built only when the caller supplies a `ScalarJustification`
naming who declared it and why (a design space where one quantity genuinely is the whole question
exists -- it just has to be said out loud, on the record). The same rule covers OutcomeSpaces: one
declared over design quality (`hypothesis_type == "DESIGN_QUALITY"`) whose outcomes are ordered by a
single metric (`order_or_metric_ref`) is refused by `require_design_space_justification` unless a
justification for that exact space version is declared.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from lab_brain.core.models.prediction import OutcomeSpace

DESIGN_QUALITY = "DESIGN_QUALITY"


class ScalarFigureOfMeritRefused(ValueError):
    """A single scalar was offered as the sole keep/discard criterion without declared reason."""


class Direction(StrEnum):
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"


@dataclass(frozen=True)
class Objective:
    name: str
    direction: Direction
    unit: str = ""


@dataclass(frozen=True)
class ScalarJustification:
    """An explicit, attributed declaration that one objective is the whole question."""

    subject_ref: str
    rationale: str
    declared_by_actor_id: str
    declared_at: dt.datetime

    def __post_init__(self) -> None:
        if not self.rationale.strip() or not self.declared_by_actor_id.strip():
            raise ScalarFigureOfMeritRefused(
                f"a scalar justification for {self.subject_ref} must state its rationale and its "
                "author; an unattributed 'one number is enough' is the P10 failure it exempts"
            )


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    values: Mapping[str, Decimal]


@dataclass(frozen=True)
class Verdict:
    keep: bool
    #: Candidates that dominate this one on every objective (empty when kept).
    dominated_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradeoffComparison:
    objectives: tuple[Objective, ...]
    candidates: tuple[Candidate, ...]
    verdicts: Mapping[str, Verdict] = field(default_factory=dict)
    justification: ScalarJustification | None = None

    @property
    def front(self) -> tuple[str, ...]:
        return tuple(sorted(c for c, v in self.verdicts.items() if v.keep))

    def table(self) -> str:
        """The trade-off, presented: every candidate, every objective, the verdict and why."""
        header = "| candidate | " + " | ".join(
            f"{o.name} ({'min' if o.direction is Direction.MINIMIZE else 'max'})"
            for o in self.objectives
        )
        lines = [
            header + " | kept | dominated by |",
            "|" + "---|" * (len(self.objectives) + 3),
        ]
        for c in sorted(self.candidates, key=lambda c: c.candidate_id):
            v = self.verdicts[c.candidate_id]
            cells = " | ".join(str(c.values[o.name]) for o in self.objectives)
            lines.append(
                f"| {c.candidate_id} | {cells} | {'yes' if v.keep else 'no'} | "
                f"{', '.join(v.dominated_by) or '—'} |"
            )
        return "\n".join(lines)


def _better_or_equal(a: Decimal, b: Decimal, direction: Direction) -> bool:
    return a <= b if direction is Direction.MINIMIZE else a >= b


def _strictly_better(a: Decimal, b: Decimal, direction: Direction) -> bool:
    return a < b if direction is Direction.MINIMIZE else a > b


def compare(
    candidates: Sequence[Candidate],
    objectives: Sequence[Objective],
    *,
    justification: ScalarJustification | None = None,
) -> TradeoffComparison:
    """Keep every non-dominated candidate; record, for every other, who dominates it."""
    if not objectives:
        raise ScalarFigureOfMeritRefused("a comparison with no objective compares nothing")
    if len(objectives) == 1 and justification is None:
        raise ScalarFigureOfMeritRefused(
            f"a comparison over the single objective {objectives[0].name!r} is a scalar figure of "
            "merit, and VER-007 / P10 forbid it as the sole keep/discard criterion. Declare a "
            "ScalarJustification if one quantity genuinely is the whole question"
        )
    names = [o.name for o in objectives]
    if len(set(names)) != len(names):
        raise ValueError("an objective is declared twice")
    for c in candidates:
        missing = sorted(set(names) - set(c.values))
        if missing:
            raise ValueError(
                f"candidate {c.candidate_id} has no value for {missing}; a trade-off with a hole "
                "in it would be decided by whatever filled the hole"
            )
    verdicts: dict[str, Verdict] = {}
    for c in candidates:
        dominators = sorted(
            o.candidate_id
            for o in candidates
            if o.candidate_id != c.candidate_id
            and all(
                _better_or_equal(o.values[x.name], c.values[x.name], x.direction)
                for x in objectives
            )
            and any(
                _strictly_better(o.values[x.name], c.values[x.name], x.direction)
                for x in objectives
            )
        )
        verdicts[c.candidate_id] = Verdict(keep=not dominators, dominated_by=tuple(dominators))
    return TradeoffComparison(
        objectives=tuple(objectives),
        candidates=tuple(candidates),
        verdicts=verdicts,
        justification=justification,
    )


def is_scalar_design_space(space: OutcomeSpace) -> bool:
    return space.hypothesis_type == DESIGN_QUALITY and space.order_or_metric_ref is not None


def require_design_space_justification(
    space: OutcomeSpace, justifications: Mapping[str, ScalarJustification]
) -> None:
    """Refuse a scalar-only design-quality OutcomeSpace that nobody justified (T-VER-007)."""
    if is_scalar_design_space(space) and space.ref not in justifications:
        raise ScalarFigureOfMeritRefused(
            f"outcome space {space.ref} orders design quality by the single metric "
            f"{space.order_or_metric_ref!r}. VER-007: a scalar-only OutcomeSpace over design "
            "quality requires an explicit declared justification, and none is declared for it"
        )


__all__ = [
    "DESIGN_QUALITY",
    "Candidate",
    "Direction",
    "Objective",
    "ScalarFigureOfMeritRefused",
    "ScalarJustification",
    "TradeoffComparison",
    "Verdict",
    "compare",
    "is_scalar_design_space",
    "require_design_space_justification",
]
