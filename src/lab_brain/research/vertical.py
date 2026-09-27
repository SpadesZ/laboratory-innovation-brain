"""What a DomainPack supplies to a product research episode, and how a deployment names one.

THE ORCHESTRATOR IS DOMAIN-AGNOSTIC; THE PACK SUPPLIES EVERYTHING DOMAIN-SPECIFIC. §24.2 forbids
core and orchestration from importing a pack, and the lint rule TID251 holds the shipped package to
it. So `lab_brain.research` never names Silicon Photonics: a pack exposes a factory returning a
`ProductVertical` -- its installed registries, its verification policies, its mechanism catalog, and
how to read its verification input -- and a deployment selects the factory BY NAME through the
`lab_brain.domain_verticals` entry-point group. That is the one place a concrete pack is chosen.

WHAT "AVAILABLE" MEANS HERE IS THE DEPLOYMENT'S TRUTH. The pack installs its declared capabilities,
wires a backend for every one this deployment can actually execute, and marks the rest UNAVAILABLE
with a stated reason (`BlockedCapability`). The planner never selects an UNAVAILABLE capability
(§17.24), so nothing unexecutable is attempted and nothing is mocked in its place. What the best
next action WOULD be if it were available is answered separately, from `planning_capabilities` --
the pack's declared descriptors -- and reported as a pending requirement, never executed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Protocol

from lab_brain.cognition.catalog_reasoner import MechanismCatalog
from lab_brain.core.models.condition import ConditionSchemaRegistration
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.models.verification import SelectionPolicy
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.sufficiency import TransitionTarget

if TYPE_CHECKING:  # pragma: no cover
    from lab_brain.core.authority import AuthorityPolicy

ENTRY_POINT_GROUP = "lab_brain.domain_verticals"


class VerticalNotFound(LookupError):
    """No installed pack offers a product vertical under that name."""


class InputRefused(ValueError):
    """The verification input could not be read as the pack's declared input."""


@dataclass(frozen=True)
class VerificationInput:
    """The pack's reading of the user's verification input (e.g. a device project)."""

    #: The input kind capabilities declare in `requires` (VER-002's available-inputs half).
    kind: str
    conditions: Mapping[str, Any]
    conditions_schema_version: str
    #: One line a person recognises: "device PS-501, drawn length 500 um".
    summary: str


@dataclass(frozen=True)
class BlockedCapability:
    """A declared capability this deployment cannot execute, and why -- never silently absent."""

    capability_id: str
    action_type: str
    reason: str
    #: What a person or deployment must provide for it to run.
    requires: str


@dataclass(frozen=True)
class ProductVertical:
    domain: str
    #: The pack as installed for EXECUTION: backends wired for what can run here.
    registry: DomainPackRegistry
    #: The pack's declared descriptors, availability untouched by this deployment -- read only to
    #: answer "what would the best next action be", never to execute anything.
    planning_capabilities: CapabilityRegistry
    blocked: tuple[BlockedCapability, ...]
    catalog: MechanismCatalog
    intent: str
    stakes: str
    selection_policy: SelectionPolicy
    targets: tuple[TransitionTarget, ...]
    #: Every policy the episode's belief path may cite, registered before the episode runs.
    transition_policies: tuple[TransitionPolicy, ...]
    #: The verification loop's authority comparator, and every version a decision may cite.
    authority_policy: AuthorityPolicy
    authority_policies: Mapping[tuple[str, str], AuthorityPolicy]
    condition_schemas: tuple[ConditionSchemaRegistration, ...]
    debate_benchmark_id: str
    #: The media type the verification input is stored under, and how the pack reads it.
    input_media_type: str
    read_input: Callable[[bytes], VerificationInput]
    #: Human-readable identity of the executing backends, for the report.
    backends: Mapping[str, str]


class VerticalFactory(Protocol):
    """What an entry point in `lab_brain.domain_verticals` resolves to."""

    def __call__(
        self,
        *,
        outputs: Any,
        jobs: Any,
        broker: Any,
        now: Callable[[], dt.datetime],
    ) -> ProductVertical: ...


def load_vertical_factory(name: str) -> VerticalFactory:
    """The factory a deployment names. Unknown names are refused with the installed ones listed."""
    found = {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}
    if name not in found:
        raise VerticalNotFound(
            f"no product vertical named {name!r} is installed; installed: {sorted(found) or 'none'}"
        )
    factory: VerticalFactory = found[name].load()
    return factory


__all__ = [
    "ENTRY_POINT_GROUP",
    "BlockedCapability",
    "InputRefused",
    "ProductVertical",
    "VerificationInput",
    "VerticalFactory",
    "VerticalNotFound",
    "load_vertical_factory",
]
