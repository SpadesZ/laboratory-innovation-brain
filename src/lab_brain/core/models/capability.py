"""Capability descriptors — what the planner is allowed to know about a backend (§17.18, §9.5).

    §9.5  Planner 只讀 Capability descriptor，不知道 backend 名稱：
              estimate_cost(params) -> CostVector
          沒有 Capability descriptor 的 backend **不可被規劃**（VER-002）。

THE POINT OF THE INDIRECTION. A planner that knew backend names would have to know what they can
do, and "what CHARGE can do" is silicon-photonics knowledge (§24.1's forbidden column). So the
descriptor is the whole interface: ``requires`` / ``produces`` say what an action consumes and
yields, ``authority_class`` says how strong the evidence would be, and the planner matches those
without ever learning that a solver exists.

``backend_id`` IS ON THE DESCRIPTOR, AND THAT IS NOT A CONTRADICTION. §17.18 declares it, and it
has to be there: a Run manifest records which backend executed (§17.4), and without the descriptor
naming one there would be nothing tying a plan to the thing that carries it out. What §9.5 forbids
is the planner *reasoning* about the value -- `VerificationPlanner` never reads it, which
`test_the_planner_never_reads_a_backend_id` asserts by parsing the module.

WHY ``estimate_cost_contract`` IS A REFERENCE AND NOT A CALLABLE. §17.18 declares it as "reference
to the implementation of estimate_cost(params) -> CostVector". A descriptor is a stored record --
it round-trips through a table -- so it holds the *name* of the estimator, and
`CapabilityRegistry` resolves that name to the implementation. Storing a function object would
make the descriptor unserialisable and would also make "which estimator priced this action" an
unanswerable question after the fact.

AVAILABILITY IS A STATE, NOT A BOOLEAN, because UX-007 needs three answers. §17.24: *a Lumerical
seat shortage surfaces as degraded availability, not as an error*. With a boolean, contention has
to be reported as either available (which hides it) or unavailable (which overstates it and sends
an engineer to investigate a healthy queue).
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.condition import ConditionSchemaRef


#: §9.3's verification action types, as identifiers. The table there is prose with spaces and a
#: slash; these are the machine forms, one per row, and nothing else may be declared.
#:
#: DOMAIN-FREE BY CONSTRUCTION. Every member names a *kind of epistemic act* -- look it up, derive
#: it, compare it to history, compute it, simulate it, measure it, build it, ask a person. None of
#: them names a solver, an instrument or a physical quantity, which is what lets the planner rank
#: candidates without importing a DomainPack (§24.1, §24.2).
class ActionType(StrEnum):
    """§9.3. The vocabulary a Capability may declare."""

    EXISTING_EVIDENCE_LOOKUP = "EXISTING_EVIDENCE_LOOKUP"
    ANALYTICAL_RULE_CHECK = "ANALYTICAL_RULE_CHECK"
    HISTORICAL_CASE_COMPARISON = "HISTORICAL_CASE_COMPARISON"
    NUMERICAL_SURROGATE = "NUMERICAL_SURROGATE"
    SIMULATION = "SIMULATION"
    MEASUREMENT = "MEASUREMENT"
    FABRICATION = "FABRICATION"
    HUMAN_EXPERT_REVIEW = "HUMAN_EXPERT_REVIEW"


class Availability(StrEnum):
    """§17.18's ``availability``, with the three answers §17.24's health view needs.

    ``DEGRADED`` is the load-bearing member -- see the module docstring. A capability whose
    license seats are all leased is DEGRADED and its work waits; it is not broken.
    """

    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


#: Action types that reach outside the system and therefore may declare a license/seat constraint.
#: Not a rule about what is expensive -- a human review is expensive -- but about what contends for
#: a finite external resource §10.7's WAITING_RESOURCE exists for.
_EXTERNALLY_CONTENDED = frozenset(
    {ActionType.SIMULATION, ActionType.MEASUREMENT, ActionType.FABRICATION}
)

_CAPABILITY_ID = re.compile(r"^cap:[a-z0-9][a-z0-9_.\-]*$")


class Capability(CoreModel):
    """§17.18, field-for-field. The only thing the Verification Planner reads about an action.

    Field-for-field is not incidental: `schema_drift.BINDINGS` compares this model, the §17.18
    block and `capabilities` in `007c_capabilities.sql` against each other in both directions, so
    a column or an attribute that the spec does not declare is a CI failure rather than a habit.
    That is why there is no ``created_at`` here and none in the table -- see the migration header.
    """

    capability_id: str
    #: ``None`` for a core capability (a repository lookup, a human review). A DomainPack's
    #: capabilities name their domain, which is how `remove the plugin` becomes a filter rather
    #: than a code change (DOM-SP-001).
    domain: str | None = None
    action_type: ActionType
    backend_id: str

    #: §9.5's matching surface. Opaque observable/artifact kind names -- core never interprets
    #: them, it only checks set membership, which is what keeps `Cj_per_length` out of core.
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    #: Domain-supplied, compared by `AuthorityPolicy` (ADR-0007). Core never orders these.
    authority_class: str
    availability: Availability = Availability.AVAILABLE

    conditions_schema_version: str | None = None
    privacy_constraints: tuple[str, ...] = ()
    license_constraints: tuple[str, ...] = ()

    #: §9.4's qualifier, hoisted onto the descriptor because §7.6 gates dispatch on it *before*
    #: any cost is estimated: an irreversible action may not be dispatched without an independent
    #: critique, whatever it costs.
    irreversible: bool = False
    earliest_available_at: dt.datetime | None = None

    #: The NAME of the estimator, resolved by `CapabilityRegistry`. See the module docstring for
    #: why this is not the callable itself.
    estimate_cost_contract: str
    version: str

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if not _CAPABILITY_ID.match(self.capability_id):
            raise ValueError(
                f"capability_id {self.capability_id!r} is not a capability identity; expected "
                "'cap:<name>'. A descriptor keyed on a free-form string cannot be told apart "
                "from a backend id, and VER-002 turns on exactly that distinction"
            )
        if not self.produces:
            raise ValueError(
                f"capability {self.capability_id} declares no `produces`. §9.5's planner matches "
                "candidates by what they yield, so a capability that produces nothing can never "
                "be selected -- and a descriptor that can never be selected is a registration "
                "nobody will notice is wrong"
            )
        if overlap := sorted(set(self.requires) & set(self.produces)):
            raise ValueError(
                f"capability {self.capability_id} both requires and produces {overlap}; an action "
                "that consumes what it yields would satisfy its own precondition and the planner "
                "would schedule it against itself"
            )
        if self.conditions_schema_version is not None:
            ConditionSchemaRef.parse(self.conditions_schema_version)
        if self.license_constraints and self.action_type not in _EXTERNALLY_CONTENDED:
            raise ValueError(
                f"capability {self.capability_id} is {self.action_type.value} and declares "
                f"license constraints {list(self.license_constraints)}. Only simulation, "
                "measurement and fabrication contend for an external seat; a license on a "
                "repository lookup would park work in WAITING_RESOURCE for a resource that does "
                "not exist (§10.7)"
            )
        return self

    @property
    def is_plannable(self) -> bool:
        """Whether §9.5 permits this to be selected at all right now.

        DEGRADED is plannable and UNAVAILABLE is not, which is the distinction §17.24 draws: a
        contended capability is one the plan waits on, an unavailable one is not a candidate.
        """
        return self.availability is not Availability.UNAVAILABLE

    def satisfied_by(self, available: frozenset[str]) -> bool:
        """Whether everything this action ``requires`` is already on hand."""
        return set(self.requires) <= available


__all__ = ["ActionType", "Availability", "Capability"]
