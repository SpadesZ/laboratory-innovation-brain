"""Typed tool contracts — the four verb classes and what each one promises (§10.2.1, SIM-003).

    §10.2.1  All DomainPack tools MUST use one of four verb prefixes.
             The prefix declares the contract, not merely the name.

               run_*       backend-bound; executes a solver/instrument; produces numerical
                           artifacts + Observation; carries BackendValidity.
               extract_*   backend-agnostic; consumes typed arrays + conditions; produces metrics
                           with normalization basis and method provenance. MUST accept both
                           simulated and measured fixtures (DOM-SP-002).
               inspect_*   reads geometry/config/state without solving; produces Observation.
               validate_*  returns ValidationReport; MUST NOT mutate raw evidence.

THE SENTENCE THAT DRIVES THIS MODULE is "the prefix declares the contract, not merely the name". A
naming convention checked by review is a naming convention; the promises above are checked here, at
registration, and each one is refused in the shape it would actually be broken:

    run_*       must name a Capability and a condition schema version. A backend execution whose
                conditions are unversioned produces a Run nobody can compare to another Run.
    extract_*   must NOT name a Capability or a backend. "Backend-agnostic" is not a property of
                the implementation's good intentions -- a descriptor that can name a backend is one
                that will, and DOM-SP-002 then has two extractors that agree by coincidence.
    inspect_*   must not declare a resource demand. Reading configuration does not take a license
                seat, and one that claimed to would park work behind a resource nobody releases.
    validate_*  must produce exactly a ValidationReport. §17.19.2 forbids the unstructured boolean,
                and a validator that also produced an observable would be writing evidence.

WHY THERE IS NO `ToolRequest(payload: dict)`. SIM-003 forbids an `eval_script`-class interface, and
the weakest form of that is not `exec()` -- it is a tool boundary that accepts an untyped blob and
lets the implementation decide what it means. Every request and result here is a Pydantic model
declared by the tool and checked by the registry before the implementation is reached.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.condition import ConditionSchemaRef


class ToolClass(StrEnum):
    """§10.2.1's four verb prefixes. The value IS the prefix, minus the underscore."""

    RUN = "run"
    EXTRACT = "extract"
    INSPECT = "inspect"
    VALIDATE = "validate"

    @property
    def prefix(self) -> str:
        return f"{self.value}_"


#: §10.2.1: "Tool identity uses a single scheme: DOM-SP-TOOL-xxx. The legacy SP-CH-xx / SP-MO-xx /
#: SP-IC-xx scheme is retired." Generalised over the domain code so a second DomainPack does not
#: need core edited -- which is EXT-001's whole question.
TOOL_ID = re.compile(r"^DOM-[A-Z]{2,6}-TOOL-\d{3}$")

#: The retired scheme, refused by name. A pattern that merely fails to match would reject these
#: anyway; naming them means the refusal explains itself instead of reading as a typo.
RETIRED_TOOL_ID = re.compile(r"^SP-(CH|MO|IC)-\d+$")

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolContractError(ValueError):
    """A tool descriptor does not keep the promise its verb prefix makes."""


class ToolRequest(CoreModel):
    """Base for everything a tool is invoked with.

    Frozen and `extra="forbid"` like every `CoreModel`, which is the point: a field the tool does
    not declare is refused rather than carried along to be interpreted by whatever reads it last.
    """

    project_id: str
    trace_id: str


class ToolResult(CoreModel):
    """Base for everything a tool returns.

    ``tool_id`` and ``tool_version`` are on the RESULT, not only on the descriptor, because a
    result outlives the call: an Observation derived from it has to be able to say which tool at
    which version produced the number, and a result that only knows its own values cannot.
    """

    tool_id: str
    tool_version: str
    warnings: tuple[str, ...] = ()


class ToolDescriptor(CoreModel):
    """What a tool declares about itself before it may be registered.

    A descriptor is not documentation. `ToolRegistry.register` refuses one that contradicts its
    own verb prefix, and refuses an implementation whose request/result models do not match it --
    so the four promises in the module docstring are enforced at the only moment they are cheap to
    enforce.
    """

    tool_id: str
    #: The canonical name from §10.2.2, e.g. `extract_cj_rs`. Its prefix must be `tool_class`.
    name: str
    tool_class: ToolClass
    domain: str
    version: str

    #: `run_*` only. §10.2.1 makes `run_*` backend-bound, and §9.5 makes a backend plannable only
    #: through a Capability -- so a `run_*` tool with no capability is one the planner cannot
    #: select and VER-002 cannot govern.
    capability_id: str | None = None
    #: `run_*` only. §17.4's Run records `conditions_schema_version`; a tool that executes without
    #: declaring one produces manifests that cannot be compared (EVI-005).
    conditions_schema_version: str | None = None

    #: Opaque observable kind names. Core never interprets them (§24.1).
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    #: `run_*` only; the license/seat resource this tool contends for (§10.7). `None` means the
    #: tool takes no external seat.
    resource_id: str | None = None

    notes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _the_prefix_declares_the_contract(self) -> Self:
        if RETIRED_TOOL_ID.match(self.tool_id):
            raise ToolContractError(
                f"tool id {self.tool_id!r} uses the retired SP-CH-xx / SP-MO-xx / SP-IC-xx scheme. "
                "§10.2.1 declares a single scheme, DOM-SP-TOOL-xxx, so a tool cannot be referred "
                "to by two identities in two records"
            )
        if not TOOL_ID.match(self.tool_id):
            raise ToolContractError(
                f"tool id {self.tool_id!r} is not a §10.2.1 tool identity; expected "
                "DOM-<DOMAIN>-TOOL-nnn"
            )
        if not _TOOL_NAME.match(self.name):
            raise ToolContractError(f"tool name {self.name!r} is not a canonical snake_case name")
        if not self.name.startswith(self.tool_class.prefix):
            raise ToolContractError(
                f"tool {self.tool_id} is declared {self.tool_class.value} but is named "
                f"{self.name!r}. §10.2.1: the prefix declares the contract, not merely the name -- "
                f"a {self.tool_class.value} tool is named {self.tool_class.prefix}*"
            )
        if not self.produces:
            raise ToolContractError(
                f"tool {self.tool_id} declares no `produces`; a tool whose output is undeclared "
                "cannot be matched by the planner or bound to a Prediction"
            )

        if self.tool_class is ToolClass.RUN:
            if self.capability_id is None:
                raise ToolContractError(
                    f"run tool {self.tool_id} names no capability_id. §10.2.1 makes `run_*` "
                    "backend-bound and §9.5 makes a backend plannable only through a Capability "
                    "descriptor, so an unbound run tool is unplannable and ungoverned (VER-002)"
                )
            if self.conditions_schema_version is None:
                raise ToolContractError(
                    f"run tool {self.tool_id} declares no conditions_schema_version. §17.4 records "
                    "one on every Run; without it two executions of this tool produce manifests "
                    "that cannot be compared (EVI-005, SIM-001)"
                )
            ConditionSchemaRef.parse(self.conditions_schema_version)
        else:
            if self.capability_id is not None:
                raise ToolContractError(
                    f"{self.tool_class.value} tool {self.tool_id} names capability "
                    f"{self.capability_id!r}. Only `run_*` is backend-bound (§10.2.1); binding a "
                    "backend to an extract/inspect/validate tool is how a 'backend-agnostic' "
                    "contract acquires a backend (DOM-SP-002)"
                )
            if self.resource_id is not None:
                raise ToolContractError(
                    f"{self.tool_class.value} tool {self.tool_id} declares resource "
                    f"{self.resource_id!r}. Only a backend execution contends for a license seat "
                    "(§10.7); a non-run tool that claimed one would park work behind a resource "
                    "nothing ever releases"
                )

        if self.tool_class is ToolClass.EXTRACT and not self.requires:
            raise ToolContractError(
                f"extract tool {self.tool_id} declares no `requires`. §10.2.1: an extractor "
                "consumes typed arrays -- one that declares no input cannot be checked against a "
                "simulated *and* a measured fixture, which is exactly DOM-SP-002's question"
            )
        return self

    @property
    def is_backend_bound(self) -> bool:
        return self.tool_class is ToolClass.RUN


@runtime_checkable
class ToolImplementation(Protocol):
    """The callable half of a tool, with its request and result types declared.

    Declared as types rather than inferred, so `ToolRegistry.invoke` can refuse a foreign payload
    *before* the implementation sees it. An implementation that accepted `Any` would be the untyped
    boundary SIM-003 forbids, wearing a typed descriptor.
    """

    @property
    def request_model(self) -> type[ToolRequest]: ...

    @property
    def result_model(self) -> type[ToolResult]: ...

    def __call__(self, request: ToolRequest) -> ToolResult: ...


__all__ = [
    "RETIRED_TOOL_ID",
    "TOOL_ID",
    "ToolClass",
    "ToolContractError",
    "ToolDescriptor",
    "ToolImplementation",
    "ToolRequest",
    "ToolResult",
]
