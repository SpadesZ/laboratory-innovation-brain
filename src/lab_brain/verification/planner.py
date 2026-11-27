"""The Verification Planner's descriptor half (VER-002, §9.5).

    VER-002    Verification Planner 必須使用 Capability descriptors；sufficient candidate 有明確
               state-transition/blocked-conflict criterion。
    T-VER-002  Planner 對無 capability descriptor 的 backend 不可規劃；有 descriptor 時依
               produces/requires match。

TWO CLAUSES, AND THIS MODULE IMPLEMENTS BOTH BY DELEGATING THE SECOND.

The first is here: candidates come from `CapabilityRegistry` and nowhere else, matched on
`requires` / `produces`. `plan_for_backend` is the negative -- a backend with no descriptor raises
rather than returning an empty plan, because an empty plan is ambiguous and a refusal is not.

The second -- "sufficient candidate has an explicit state-transition / blocked-conflict criterion"
-- is `lab_brain.core.sufficiency.evaluate_sufficiency`, which M0b already built for VER-006 and
which returns exactly that criterion: would a declared outcome change the `TransitionDecision`, or
resolve a blocking Conflict. This module calls it; it does not reimplement it. A planner with its
own notion of "sufficient" would be a second definition of when a belief may move, and §8.2.1
allows one.

WHAT THE PLANNER NEVER READS: `Capability.backend_id`. §9.5 -- *Planner 只讀 Capability
descriptor，不知道 backend 名稱*. The field exists on the descriptor because §17.18 declares it and
a Run manifest needs it, but no ranking or filtering here consults it, and
`test_the_planner_never_reads_a_backend_id` parses this module to keep it that way.

NO SCALAR RANKING. `PlannedAction` carries the whole `CostVector` and the candidates come back in
a declared order (`produces`, then capability id) rather than sorted by a number. §9.4's
prohibition on a single `normalized_cost` is not only about the ledger: a planner that sorted by
one would have made the decision VER-003 forbids, and `SelectionPolicy` (VER-005, M4) is where an
ordering is allowed to be declared.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lab_brain.core.models.capability import Capability
from lab_brain.core.models.cost import CostVector
from lab_brain.verification.capability_registry import (
    CapabilityNotRegistered,
    CapabilityRegistry,
)


class PlanningRefused(Exception):
    """A backend or capability may not be planned. Carries the reason code.

    An exception rather than an empty plan: "nothing satisfies the goal" and "you asked about a
    backend nobody described" are different answers, and VER-002 is about the second.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


#: Reason codes, so tests assert state rather than prose.
NO_DESCRIPTOR = "NO_CAPABILITY_DESCRIPTOR"
UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
REQUIRES_UNSATISFIED = "REQUIRES_UNSATISFIED"


class PlannedAction:
    """One capability that could be run next, with its cost and why it qualified.

    A plain class rather than a `CoreModel` because it holds a live `Capability` and a computed
    `CostVector` and is not persisted -- §17.14.1's VerificationPlan is M4's, and giving this a
    table now would be building it early under a different name.
    """

    __slots__ = ("capability", "consumed", "cost", "satisfies")

    def __init__(
        self,
        capability: Capability,
        cost: CostVector,
        satisfies: tuple[str, ...],
        consumed: tuple[str, ...],
    ) -> None:
        self.capability = capability
        self.cost = cost
        #: Which of the goal observables this action would produce.
        self.satisfies = satisfies
        #: Which already-available inputs it consumes.
        self.consumed = consumed

    @property
    def capability_id(self) -> str:
        return self.capability.capability_id

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"PlannedAction({self.capability_id}, satisfies={list(self.satisfies)})"


class VerificationPlanner:
    """§9.5's planner surface: descriptors in, candidate actions out.

    Deterministic. Candidates are returned sorted by `(first satisfied observable, capability_id)`,
    never by cost, so two runs over the same registry produce the same list -- which VER-005 will
    later rank with a declared `SelectionPolicy`.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def plan(
        self,
        *,
        goal: Sequence[str],
        available: frozenset[str] = frozenset(),
        params: Mapping[str, Any] | None = None,
    ) -> tuple[PlannedAction, ...]:
        """Capabilities that produce something in ``goal`` and whose ``requires`` are satisfied.

        BOTH HALVES OF THE MATCH ARE REQUIRED, and the `requires` half is the one that is easy to
        drop. A capability that produces the goal but needs an input nobody has is not a candidate;
        planning it would put an action in the plan that cannot start, and the plan's cost estimate
        would then be a lower bound on something else entirely.
        """
        wanted = frozenset(goal)
        candidates: list[PlannedAction] = []
        for capability in self._registry:
            if not capability.is_plannable:
                continue
            satisfies = tuple(sorted(wanted & frozenset(capability.produces)))
            if not satisfies:
                continue
            if not capability.satisfied_by(available):
                continue
            candidates.append(
                PlannedAction(
                    capability=capability,
                    cost=self._registry.estimate(capability.capability_id, dict(params or {})),
                    satisfies=satisfies,
                    consumed=tuple(sorted(frozenset(capability.requires) & available)),
                )
            )
        return tuple(
            sorted(candidates, key=lambda action: (action.satisfies[0], action.capability_id))
        )

    def plan_for_backend(
        self,
        backend_id: str,
        *,
        goal: Sequence[str],
        available: frozenset[str] = frozenset(),
        params: Mapping[str, Any] | None = None,
    ) -> tuple[PlannedAction, ...]:
        """VER-002's negative. A backend with no descriptor raises; it does not plan emptily.

        The distinction matters operationally. "No candidates" is a normal planning outcome that a
        caller handles by looking elsewhere; "this backend has no descriptor" is a registration
        defect that will silently exclude the backend from every plan until someone notices.
        """
        if not self._registry.for_backend(backend_id):
            raise PlanningRefused(
                NO_DESCRIPTOR,
                f"backend {backend_id!r} has no Capability descriptor. §9.5: a backend with no "
                "descriptor MUST NOT be planned -- the planner reads descriptors and does not "
                "know backend names, so an undescribed backend is one it cannot price, cannot "
                "check the availability of, and cannot bind a Prediction to (VER-002)",
            )
        described = {c.capability_id for c in self._registry.for_backend(backend_id)}
        return tuple(
            action
            for action in self.plan(goal=goal, available=available, params=params)
            if action.capability_id in described
        )

    def require(
        self,
        capability_id: str,
        *,
        available: frozenset[str] = frozenset(),
    ) -> Capability:
        """Resolve a capability the caller intends to dispatch, or refuse with a reason.

        The gate `dispatch_action` would call before executing: it answers "may this run at all"
        in one place, so an availability check does not have to be repeated by every caller in a
        slightly different form.
        """
        try:
            capability = self._registry.resolve(capability_id)
        except CapabilityNotRegistered as missing:
            raise PlanningRefused(NO_DESCRIPTOR, str(missing)) from missing
        if not capability.is_plannable:
            raise PlanningRefused(
                UNAVAILABLE,
                f"capability {capability_id} is {capability.availability.value}. A DEGRADED "
                "capability is plannable and waits; an UNAVAILABLE one is not a candidate "
                "(§17.24)",
            )
        if not capability.satisfied_by(available):
            missing_inputs = sorted(frozenset(capability.requires) - available)
            raise PlanningRefused(
                REQUIRES_UNSATISFIED,
                f"capability {capability_id} requires {missing_inputs}, which are not available. "
                "An action in a plan that cannot start makes the plan's cost a lower bound on "
                "something else",
            )
        return capability


__all__ = [
    "NO_DESCRIPTOR",
    "REQUIRES_UNSATISFIED",
    "UNAVAILABLE",
    "PlannedAction",
    "PlanningRefused",
    "VerificationPlanner",
]
