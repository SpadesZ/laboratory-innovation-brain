"""Which cheap checks the competing hypotheses leave unaddressed (the coverage review's input).

THE FAILURE IT ANSWERS. A real model proposed five well-formed rivals for a device whose via never
reached metal, and none of them said anything about contact connectivity -- a seconds-long design
inspection that would have settled it. Verification plans only over what hypotheses predict, so
the cheapest discriminating check was never run and the cause was never found.

WHAT IS COMPUTED, AND FROM WHAT. An observable is UNADDRESSED when

    * it is in the domain's prediction vocabulary (a hypothesis could predict over it);
    * a check that produces it can run HERE, now -- the execution registry plans it (available,
      its inputs on hand) -- and at low cost: its declared estimate needs no person, no money, no
      licence seat and nothing irreversible;
    * no admitted hypothesis declares a SUPPORTS or CONTRADICTS prediction over it, so whatever the
      check observed could move no belief.

Nothing here reads a verification input's CONTENT, a benchmark, a catalog or an expected answer:
only the hypotheses, the vocabulary, the capability descriptors and which input KINDS are on hand.
The same hypotheses therefore leave the same gaps whatever the device turns out to be -- the review
is told where nobody has looked, never what it would find.

Ordered cheapest first under the estimate (elapsed time, then compute, then capability id), which
is the cheapest-sufficient-verification order the planner itself will use.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from lab_brain.cognition.roles import DISCRIMINATING_EFFECTS
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.hypothesis_set import HypothesisCertificate
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.planner import VerificationPlanner


@dataclass(frozen=True)
class CoverageGap:
    observable_ref: str
    #: The cheapest check here that produces it.
    capability_id: str
    action_type: str
    cost: CostVector

    def as_context(self, space: OutcomeSpace) -> dict[str, object]:
        return {
            "observable_ref": self.observable_ref,
            "outcome_space_id": space.outcome_space_id,
            "outcome_space_version": space.version,
            "outcomes": list(space.outcomes),
            "check": self.capability_id,
            "action_type": self.action_type,
        }


def is_low_cost(cost: CostVector) -> bool:
    """No person, no money, no licence seat, nothing irreversible: a check the run can just do."""
    return not (
        cost.human_minutes or cost.money_estimate or cost.license_seat_s or cost.irreversible
    )


def discriminated(certificates: Sequence[HypothesisCertificate]) -> frozenset[str]:
    """Observables some hypothesis makes a SUPPORTS or CONTRADICTS prediction over."""
    return frozenset(
        p.observable_ref
        for c in certificates
        for p in c.predictions
        if any(t.relation_type in DISCRIMINATING_EFFECTS for t in p.relation_effect_if_observed)
    )


def unaddressed_checks(
    certificates: Sequence[HypothesisCertificate],
    bindings: Mapping[str, OutcomeSpace],
    capabilities: CapabilityRegistry,
    available: Collection[str],
) -> tuple[CoverageGap, ...]:
    covered = discriminated(certificates)
    planned = VerificationPlanner(capabilities).plan(
        goal=sorted(bindings), available=frozenset(available)
    )
    best: dict[str, CoverageGap] = {}
    for action in planned:
        if not is_low_cost(action.cost):
            continue
        for observable in action.satisfies:
            if observable in covered:
                continue
            gap = CoverageGap(
                observable_ref=observable,
                capability_id=action.capability_id,
                action_type=action.capability.action_type.value,
                cost=action.cost,
            )
            if observable not in best or _order(gap) < _order(best[observable]):
                best[observable] = gap
    return tuple(sorted(best.values(), key=_order))


def _order(gap: CoverageGap) -> tuple[int, int, str, str]:
    return (gap.cost.wall_clock_s, gap.cost.compute_units, gap.capability_id, gap.observable_ref)


__all__ = ["CoverageGap", "discriminated", "is_low_cost", "unaddressed_checks"]
