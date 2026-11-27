"""The Capability registry, and the cost estimators it resolves (§9.5, §17.18, VER-002).

    §9.5  沒有 Capability descriptor 的 backend **不可被規劃**（VER-002）。

THAT SENTENCE IS A NEGATIVE, AND A NEGATIVE NEEDS SOMETHING TO BE ABSENT FROM. A planner that took
a list of backends and planned over them could not refuse an undescribed one -- there would be
nowhere for the absence to show. So the registry is the only source of candidates, and
`VerificationPlanner` cannot reach a backend that was never registered because it never sees a
backend at all: it sees descriptors.

WHY `estimate_cost` IS RESOLVED HERE AND NOT STORED. §17.18 declares `estimate_cost_contract` as a
*reference* to an implementation. The descriptor round-trips through a table, so it holds a name;
this registry holds the name -> callable mapping. A descriptor whose estimator is not registered is
refused at registration rather than at planning time, because the failure mode otherwise is a
capability that looks plannable until the moment a plan needs its cost.

ESTIMATORS ARE REGISTERED SEPARATELY FROM CAPABILITIES so a DomainPack can share one estimator
across several capabilities -- three CHARGE tools priced by the same solver model -- without
copying it, which is how two copies of a cost model start disagreeing.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.capability import Availability, Capability
from lab_brain.core.models.cost import CostVector


class CapabilityRegistrationError(ValueError):
    """A capability or estimator cannot be registered as declared."""


class CapabilityNotRegistered(LookupError):
    """No descriptor for this capability. VER-002's refusal, as an exception.

    Raised rather than returning `None` for the reason `AuthorityResolutionError` gives: a caller
    handed `None` has to remember to check it, and the place that forgets is the place an
    undescribed backend gets planned anyway.
    """


@runtime_checkable
class CostEstimator(Protocol):
    """§9.5's `estimate_cost(params) -> CostVector`, exactly."""

    def __call__(self, params: Mapping[str, Any]) -> CostVector: ...


class CapabilityRegistry:
    """Descriptors keyed by id, plus the estimators they name.

    NOT A GLOBAL, for the reason `ToolRegistry` is not: DOM-SP-001 asks what happens when the
    plugin is removed, and that question is only answerable if a registry can be built without it.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._estimators: dict[str, CostEstimator] = {}

    # -- registration -------------------------------------------------------

    def register_estimator(self, contract: str, estimator: CostEstimator) -> None:
        existing = self._estimators.get(contract)
        if existing is not None and existing is not estimator:
            raise CapabilityRegistrationError(
                f"a different estimator is already registered as {contract!r}. A cost contract is "
                "named on the descriptor and recorded in the ledger; replacing one in place would "
                "reprice every past estimate under a model it was never computed with"
            )
        self._estimators[contract] = estimator

    def register(self, capability: Capability) -> Capability:
        """Register a descriptor whose estimator already exists.

        The ordering requirement is deliberate and is the opposite of convenient: a capability
        registered before its estimator would be plannable and unpriceable, and VER-003 makes the
        cost vector part of the decision rather than a report produced afterwards.
        """
        existing = self._capabilities.get(capability.capability_id)
        if existing is not None and existing != capability:
            raise CapabilityRegistrationError(
                f"a different descriptor is already registered as {capability.capability_id} "
                f"(version {existing.version}). §17.18 versions the descriptor so a change gets a "
                "new version; replacing one in place would make a past plan unreproducible"
            )
        if capability.estimate_cost_contract not in self._estimators:
            raise CapabilityRegistrationError(
                f"capability {capability.capability_id} names cost contract "
                f"{capability.estimate_cost_contract!r}, which is not registered. §9.5's planner "
                "reads `estimate_cost(params) -> CostVector` off the descriptor, so an "
                "unresolvable contract produces a capability that is plannable and unpriceable -- "
                "discovered at the moment a plan needs a number (VER-003)"
            )
        self._capabilities[capability.capability_id] = capability
        return capability

    # -- reads --------------------------------------------------------------

    def resolve(self, capability_id: str) -> Capability:
        found = self._capabilities.get(capability_id)
        if found is None:
            raise CapabilityNotRegistered(
                f"no Capability descriptor is registered as {capability_id!r}. §9.5: a backend "
                "with no descriptor MUST NOT be planned (VER-002). Registered: "
                f"{sorted(self._capabilities) or 'nothing'}"
            )
        return found

    def get(self, capability_id: str) -> Capability | None:
        """Mapping-shaped accessor, for callers that legitimately treat absence as a value."""
        return self._capabilities.get(capability_id)

    def for_backend(self, backend_id: str) -> tuple[Capability, ...]:
        """Every descriptor naming this backend. Empty means the backend is unplannable.

        Exists so VER-002's negative case can be *asked* rather than inferred from a planner
        returning nothing -- an empty plan has several causes and only one of them is this.
        """
        return tuple(
            sorted(
                (c for c in self._capabilities.values() if c.backend_id == backend_id),
                key=lambda c: c.capability_id,
            )
        )

    def of_domain(self, domain: str | None) -> tuple[Capability, ...]:
        return tuple(
            sorted(
                (c for c in self._capabilities.values() if c.domain == domain),
                key=lambda c: c.capability_id,
            )
        )

    def estimator(self, contract: str) -> CostEstimator | None:
        """The estimator registered under ``contract``, or `None`.

        Mapping-shaped rather than raising, because the one caller -- `BudgetedToolDispatcher`,
        pricing a tool that has no Capability -- has its own fail-closed branch with its own
        message about why an unpriceable tool cannot pass the budget gate. Raising through it would
        replace that with a different exception type for the same condition.
        """
        return self._estimators.get(contract)

    def estimate(self, capability_id: str, params: Mapping[str, Any]) -> CostVector:
        """§9.5's `estimate_cost(params) -> CostVector` for one capability.

        Resolving the descriptor first is not ceremony: it means an unregistered capability cannot
        be priced, so a caller cannot obtain a cost for something the planner would refuse.
        """
        capability = self.resolve(capability_id)
        estimator = self._estimators[capability.estimate_cost_contract]
        return estimator(params)

    def set_availability(self, capability_id: str, availability: Availability) -> Capability:
        """Update availability, which is the one field that legitimately changes without a version.

        §17.18 versions the descriptor's *contract*; availability is state, not contract -- a
        license server going busy is not a new capability. Everything else is immutable, which
        `register` enforces.
        """
        capability = self.resolve(capability_id)
        updated = capability.model_copy(update={"availability": availability})
        self._capabilities[capability_id] = updated
        return updated

    def __iter__(self) -> Iterator[Capability]:
        return iter(sorted(self._capabilities.values(), key=lambda c: c.capability_id))

    def __len__(self) -> int:
        return len(self._capabilities)

    def capability_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))


__all__ = [
    "CapabilityNotRegistered",
    "CapabilityRegistrationError",
    "CapabilityRegistry",
    "CostEstimator",
]
