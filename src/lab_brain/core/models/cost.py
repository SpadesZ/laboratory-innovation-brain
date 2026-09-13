"""Cost as a vector, and the ledger that records it (§9.4, §17.17, COST-001).

WHY THERE IS NO TOTAL.

§9.4 is emphatic: 不得把全部成本壓縮成單一 ``normalized_cost`` 作為唯一決策依據. The example it
gives is the one that matters -- a six-week MPW shuttle is not "expensive", it is *slow* and
*irreversible* and *schedule-coupled*. Collapse those into one number and a planner will happily
rank it next to a long, cheap, perfectly repeatable simulation.

So :class:`CostVector` deliberately offers no ``total()``, no ``normalized_cost``, and no ordering.
The absence is the design: a scalar that exists gets used for comparison the moment someone needs to
sort a list, and the discarded dimensions are exactly the ones VER-003 is protecting.

``irreversible``, ``earliest_available_at`` and ``dependency_risk`` are not magnitudes at all. They
are qualifiers -- you cannot average irreversibility -- which is the second reason a single number
cannot represent this.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from lab_brain.core.models.base import CoreModel


class DependencyRisk(StrEnum):
    """How badly this action couples the plan to something outside it (§9.4).

    A shuttle booking is HIGH not because it costs money but because missing the window costs a
    quarter.
    """

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CostKind(StrEnum):
    """Whether a ledger entry is what was predicted or what happened.

    Kept as separate entries rather than one row updated in place. The estimate is the gate's
    *input*: overwriting it with the actual destroys the evidence for why the call was admitted,
    and makes systematic under-estimation invisible.
    """

    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


class CostVector(CoreModel):
    """§9.4's cost of an action, in every dimension the spec names.

    Defaults are zero/absent so a partial estimate is still a usable vector -- a call that consumes
    no license seat should not have to say so. What may *not* be defaulted is the estimate as a
    whole: :func:`lab_brain.core.budget.evaluate_budget` refuses a request with no estimate rather
    than treating "unknown" as "free".
    """

    #: Seconds of elapsed time. Integer: sub-second precision is noise at this granularity, and
    #: the canonical-JSON profile refuses floats anyway.
    wall_clock_s: int = Field(default=0, ge=0)
    #: Researcher attention. §14.4.1 makes this a real capacity, not a soft cost.
    human_minutes: int = Field(default=0, ge=0)
    #: Decimal, never float: money that rounds differently on two machines is not auditable.
    money_estimate: Decimal = Field(default=Decimal(0), ge=0)
    compute_units: int = Field(default=0, ge=0)
    license_seat_s: int = Field(default=0, ge=0)

    #: Waiting time, expressed as the earliest moment the action could complete rather than as a
    #: duration. An absolute instant composes across a plan; a duration has to be re-based against
    #: a start time nobody recorded.
    earliest_available_at: dt.datetime | None = None
    #: Not a magnitude. A tape-out cannot be un-done at any price.
    irreversible: bool = False
    dependency_risk: DependencyRisk = DependencyRisk.NONE

    def plus(self, other: CostVector) -> CostVector:
        """Accumulate consumption. Additive dimensions add; qualifiers take the stronger value.

        Not ``__add__``: an operator invites ``sum()``, and summing a list of cost vectors is one
        short step from treating the result as a score.
        """
        risks = list(DependencyRisk)
        return CostVector(
            wall_clock_s=self.wall_clock_s + other.wall_clock_s,
            human_minutes=self.human_minutes + other.human_minutes,
            money_estimate=self.money_estimate + other.money_estimate,
            compute_units=self.compute_units + other.compute_units,
            license_seat_s=self.license_seat_s + other.license_seat_s,
            earliest_available_at=max(
                (d for d in (self.earliest_available_at, other.earliest_available_at) if d),
                default=None,
            ),
            irreversible=self.irreversible or other.irreversible,
            dependency_risk=max(self.dependency_risk, other.dependency_risk, key=risks.index),
        )


#: The dimensions a budget can cap. Qualifiers are absent on purpose: "irreversible" is not
#: something you have a quota of, and gating on it is §7.6's job, not the budget's.
CAPPED_DIMENSIONS: tuple[str, ...] = (
    "wall_clock_s",
    "human_minutes",
    "money_estimate",
    "compute_units",
    "license_seat_s",
)


class CostEntry(CoreModel):
    """One recorded cost, estimated or actual (§17.17).

    ``project_id`` and ``cost_kind`` were added to the canonical schema by amendment `v3.3-a9`:
    COST-001 requires a cost to be traceable to its project and requires estimates and actuals to
    be distinguishable, and §17.17's original block stated neither.
    """

    cost_entry_id: str
    project_id: str
    episode_id: str
    #: The agent role or LLM slot that incurred it, or the human actor. §7.3 slots are not Actors,
    #: so this is deliberately wider than `actor_id`.
    actor_or_slot: str
    action_ref: str
    cost_kind: CostKind
    cost: CostVector
    #: Set when an overrun was released by a supervisor, so the ledger shows not just that the
    #: money was spent but that someone signed for it.
    approval_id: str | None = None
    recorded_at: dt.datetime


__all__ = [
    "CAPPED_DIMENSIONS",
    "CostEntry",
    "CostKind",
    "CostVector",
    "DependencyRisk",
]
