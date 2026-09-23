"""The typed ToolRegistry — the only way a tool is invoked (SIM-003, §10.2).

    SIM-003  Tool invocation MUST occur through a typed ToolRegistry. No tool, Capability or
             backend adapter may expose an arbitrary script-execution entry point
             (`eval_script`-class public interface). Untyped execution paths MUST be rejected by
             static conformance test.

TWO HALVES, AND THE STATIC ONE IS NOT ENOUGH ON ITS OWN. `tests/unit/test_no_arbitrary_script_
execution.py` has scanned the source tree for `eval_script`-shaped names since M0a, and it would
pass on a codebase with no registry at all -- absence of a forbidden name is not presence of a
typed path. This module is the other half: every invocation resolves a descriptor, checks the
request against the type that descriptor's implementation declared, and only then calls it.

WHY THE REGISTRY VALIDATES AND DOES NOT MERELY LOOK UP. A registry that returned the callable would
be a dictionary, and the caller would then be the thing deciding what a valid request is. That is
the same shape as `DiagnosticsService`'s rejected `include_technical` flag and UX-002's optional
budget gate: the check exists, and it is the caller's to skip. So `invoke` is the entry point and
there is no accessor that hands out an implementation.

WHAT IS DELIBERATELY NOT HERE. Cost, budget and the trace. A tool invocation that must be budgeted
goes through `lab_brain.core.dispatch.dispatch_action`, which owns the span and the ledger; this
registry owns *what may be called and with what*. Merging them would mean either every registry
lookup opened a span, or the seam that gates external effects had a second entrance.
"""

from __future__ import annotations

from collections.abc import Iterator

from lab_brain.tools.contracts import (
    ToolClass,
    ToolDescriptor,
    ToolImplementation,
    ToolRequest,
    ToolResult,
)


class ToolNotRegistered(LookupError):
    """No such tool. Raised, never `None`.

    A caller handed `None` has to remember to check it, and the place that forgets is the place a
    verification action is silently skipped -- which reads, downstream, as "the check passed".
    """


class ToolRegistrationError(ValueError):
    """A tool cannot be registered as declared."""


class ToolInvocationError(TypeError):
    """A request does not match the type the tool declared.

    A `TypeError` rather than a domain exception because that is what it is: the boundary was
    handed something of the wrong shape. Catching it and continuing would be catching a type error
    and continuing.
    """


class ToolRegistry:
    """Descriptors and implementations, keyed by tool id. Invocation is the only public verb.

    NOT A GLOBAL. An instance is constructed and DomainPacks register into it (§24.3's
    `register_tools(registry)`), so a test can build a registry with one domain installed and
    nothing else -- which is what makes DOM-SP-001's "remove the plugin and core still starts"
    checkable rather than aspirational.
    """

    def __init__(self) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._implementations: dict[str, ToolImplementation] = {}

    # -- registration -------------------------------------------------------

    def register(self, descriptor: ToolDescriptor, implementation: ToolImplementation) -> None:
        """Register a tool, refusing anything that would make invocation untyped.

        The descriptor has already refused a prefix that contradicts its class (see
        `contracts.ToolDescriptor`). What is checked HERE is the pair: an implementation whose
        declared models disagree with its descriptor's class, and a second registration under an
        id that is already taken.
        """
        if descriptor.tool_id in self._descriptors:
            existing = self._descriptors[descriptor.tool_id]
            raise ToolRegistrationError(
                f"tool {descriptor.tool_id} is already registered as {existing.name!r} "
                f"{existing.version}. Re-registering in place would mean a Run recorded against "
                "this id could have been produced by either implementation, and nothing in the "
                "record would say which"
            )
        taken = {name: tool_id for tool_id, name in self._names().items()}
        if descriptor.name in taken:
            raise ToolRegistrationError(
                f"tool name {descriptor.name!r} is already registered as {taken[descriptor.name]}. "
                "§10.2.2's canonical names are identities too: two tools answering to one name "
                "makes 'which tool produced this' unanswerable from a name alone"
            )

        for label, model, base in (
            ("request_model", implementation.request_model, ToolRequest),
            ("result_model", implementation.result_model, ToolResult),
        ):
            if not (isinstance(model, type) and issubclass(model, base)):
                raise ToolRegistrationError(
                    f"tool {descriptor.tool_id} declares {label}={model!r}, which is not a "
                    f"{base.__name__} subclass. An untyped boundary is the `eval_script` hazard "
                    "in its weakest form: the implementation, not the contract, decides what the "
                    "payload means (SIM-003)"
                )

        if descriptor.tool_class is ToolClass.VALIDATE:
            # §10.2.1 / §17.19.2: a validator returns a ValidationReport and MUST NOT mutate raw
            # evidence. Imported here rather than at module scope so `tools` does not depend on the
            # validation model merely to define a registry.
            from lab_brain.core.models.validation import ValidationReport

            produced = implementation.result_model
            carries_report = any(
                isinstance(field.annotation, type)
                and issubclass(field.annotation, ValidationReport)
                for field in produced.model_fields.values()
            )
            if not carries_report:
                raise ToolRegistrationError(
                    f"validate tool {descriptor.tool_id} returns {produced.__name__}, which "
                    "carries no ValidationReport. §17.19.2: DomainPack validators MUST return a "
                    "ValidationReport, never an unstructured boolean/string -- a refusal nobody "
                    "can trace to a versioned rule cannot be re-checked when the rule changes"
                )

        self._descriptors[descriptor.tool_id] = descriptor
        self._implementations[descriptor.tool_id] = implementation

    # -- reads --------------------------------------------------------------

    def descriptor(self, tool_id: str) -> ToolDescriptor:
        """The declared contract, or raise. Safe to expose: it carries no callable."""
        try:
            return self._descriptors[tool_id]
        except KeyError:
            raise ToolNotRegistered(
                f"no tool is registered as {tool_id}. Registered: "
                f"{sorted(self._descriptors) or 'nothing'}"
            ) from None

    def by_name(self, name: str) -> ToolDescriptor:
        """Resolve §10.2.2's canonical name to its descriptor."""
        for descriptor in self._descriptors.values():
            if descriptor.name == name:
                return descriptor
        raise ToolNotRegistered(f"no tool is registered under the canonical name {name!r}")

    def tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._descriptors))

    def of_class(self, tool_class: ToolClass) -> tuple[ToolDescriptor, ...]:
        return tuple(
            sorted(
                (d for d in self._descriptors.values() if d.tool_class is tool_class),
                key=lambda d: d.tool_id,
            )
        )

    def of_domain(self, domain: str) -> tuple[ToolDescriptor, ...]:
        return tuple(
            sorted(
                (d for d in self._descriptors.values() if d.domain == domain),
                key=lambda d: d.tool_id,
            )
        )

    def __iter__(self) -> Iterator[ToolDescriptor]:
        return iter(sorted(self._descriptors.values(), key=lambda d: d.tool_id))

    def __len__(self) -> int:
        return len(self._descriptors)

    # -- the only execution path --------------------------------------------

    def invoke(self, tool_id: str, request: ToolRequest) -> ToolResult:
        """Call a registered tool with a request of the type it declared.

        There is no `implementation_for(tool_id)`. Handing the callable back would move the type
        check to the caller, and SIM-003's requirement is that invocation *goes through* the typed
        registry -- not that a typed registry exists somewhere nearby.
        """
        descriptor = self.descriptor(tool_id)
        implementation = self._implementations[tool_id]

        expected = implementation.request_model
        if not isinstance(request, expected):
            raise ToolInvocationError(
                f"tool {tool_id} ({descriptor.name}) takes {expected.__name__} but was given "
                f"{type(request).__name__}. The registry checks the type before the "
                "implementation sees the payload, so a tool never has to decide what an unknown "
                "object means (SIM-003)"
            )

        result = implementation(request)
        if not isinstance(result, implementation.result_model):
            raise ToolInvocationError(
                f"tool {tool_id} ({descriptor.name}) declared it returns "
                f"{implementation.result_model.__name__} and returned {type(result).__name__}. "
                "A result of an undeclared type is a contract the caller cannot rely on"
            )
        if result.tool_id != descriptor.tool_id:
            raise ToolInvocationError(
                f"tool {tool_id} returned a result stamped {result.tool_id!r}. A result outlives "
                "the call and is what an Observation cites; a mis-stamped one attributes a number "
                "to the wrong tool"
            )
        if result.tool_version != descriptor.version:
            raise ToolInvocationError(
                f"tool {tool_id} is registered at version {descriptor.version!r} and returned a "
                f"result stamped {result.tool_version!r}. §6.18's contamination rollback selects "
                "by version, so a mis-stamped result survives a quarantine that should have "
                "caught it"
            )
        return result

    def _names(self) -> dict[str, str]:
        return {tool_id: d.name for tool_id, d in self._descriptors.items()}


__all__ = [
    "ToolInvocationError",
    "ToolNotRegistered",
    "ToolRegistrationError",
    "ToolRegistry",
]
