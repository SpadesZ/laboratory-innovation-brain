"""The anytime ladder: the frozen engine at increasing caps, through a gate-owned replay laboratory.

The frozen engine (`investigate`) commits one answer when it stops and has no per-step hook. It is
deterministic given its inputs and the readings it receives, and its cap only decides which
experiments are affordable. So the gate can ask "what would the engine conclude with c units?"
for c = ladder_start, ladder_start + 1, ... without editing it -- provided a re-run is not charged
again for what was already measured.

`ReplayLaboratory` does that honestly. It is the gate's own record of every measurement made in
this investigation, keyed by (experiment, k) for the k-th run of that experiment. When an engine
run asks for the k-th run of E and it was already measured, it receives that recorded reading (the
same physical measurement); only a never-measured (E, k) goes to the real laboratory and is
charged by its meter. A new measurement that would take the distinct-measurement total past the
budget is refused with `ReplayCapReached` before it reaches the laboratory, and the ladder keeps the
last completed run. Every measurement any run made is data: measurements an earlier run made and the
chosen run did not ask for are handed to the gate as observations too (`orphans`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, investigate
from lab_brain.discovery.model import CLAIM_OUTCOMES, Budget, DiscoveryResult
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.v12.model import LadderStep

Values = tuple[tuple[str, float], ...]


class ReplayCapReached(RuntimeError):
    """A new measurement would exceed the investigation's budget; the ladder stops."""


@dataclass
class ReplayLaboratory:
    lab: Laboratory
    costs: Mapping[str, int]
    budget: int
    readings: dict[tuple[str, int], Values] = field(default_factory=dict)
    #: (experiment, k) in the order they were first measured.
    order: list[tuple[str, int]] = field(default_factory=list)
    charged: int = 0
    _motivating: tuple[str, Values] | None = None
    #: The (experiment, k) the current engine run asked for.
    requested: list[tuple[str, int]] = field(default_factory=list)

    def motivating(self) -> tuple[str, Values]:
        if self._motivating is None:
            self._motivating = self.lab.motivating()
        return self._motivating

    def measure(self, experiment_id: str, *, replicate: int, session: int) -> Values:
        key = (experiment_id, replicate)
        self.requested.append(key)
        if key in self.readings:
            return self.readings[key]
        cost = self.costs[experiment_id]
        if self.charged + cost > self.budget:
            raise ReplayCapReached(f"{experiment_id} would take the charge past {self.budget}")
        values = self.lab.measure(experiment_id, replicate=replicate, session=session)
        self.charged += cost
        self.readings[key] = values
        self.order.append(key)
        return values

    def next_replicate(self, experiment_id: str) -> int:
        return sum(1 for e, _ in self.readings if e == experiment_id)

    def register(self, text: str) -> int | None:
        """Forward a registration to the evaluator's ledger, if the laboratory carries one."""
        register = getattr(self.lab, "register", None)
        if register is None:
            return None
        index: Any = register(text)
        return int(index)


def run_ladder(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    replay: ReplayLaboratory,
    start: int,
    stop: int | None = None,
) -> tuple[DiscoveryResult, tuple[LadderStep, ...], int, tuple[tuple[str, int], ...]]:
    """Engine runs at caps start, start+1, ..., budget: stop at the first claim, or when the stop
    was not budget-bound (a larger cap cannot change a run whose every choice was affordable), or
    when a new measurement would pass the budget. Returns the chosen run, the ladder, its cap and
    the (experiment, k) readings the chosen run asked for. The first cap is at most the budget, so
    its run's new charges cannot pass the budget: there is always a chosen run."""
    max_cost = max(e.cost for e in oracle.available) if oracle.available else 1
    steps: list[LadderStep] = []
    chosen: DiscoveryResult | None = None
    chosen_cap = 0
    chosen_requested: tuple[tuple[str, int], ...] = ()
    last = budget.total if stop is None else min(stop, budget.total)
    for cap in range(min(start, last), last + 1):
        replay.requested = []
        try:
            result = investigate(
                arm=arm,
                catalog=catalog,
                oracle=oracle,
                protocol=protocol,
                budget=Budget(cap),
                lab=replay,
            )
        except ReplayCapReached:
            break
        chosen, chosen_cap, chosen_requested = result, cap, tuple(replay.requested)
        steps.append(
            LadderStep(cap, result.outcome.value, tuple(result.claim), result.spent, replay.charged)
        )
        if result.outcome in CLAIM_OUTCOMES:
            break
        if cap - result.spent >= max_cost:
            break
    if chosen is None:
        raise RuntimeError("the ladder's first cap could not run")
    return chosen, tuple(steps), chosen_cap, chosen_requested


__all__ = ["ReplayCapReached", "ReplayLaboratory", "run_ladder"]
