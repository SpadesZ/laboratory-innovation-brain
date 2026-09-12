"""Versioned condition schemas and condition comparison (§6.19, §17.19).

Conditions are what make two numbers comparable or not: wavelength, bias, temperature,
geometry, doping, platform. Core knows that conditions are versioned and that comparison
returns a five-valued result; it does not know what a wavelength is. Those semantics arrive
from a DomainPack (§24.1), which is why nothing in this module names a physical quantity.

``conditions_schema_version`` is a single field in the spec, but a bare version string cannot
identify a schema -- ``ConditionSchemaRegistration`` is keyed by ``(domain, schema_id, version)``.
So the field carries a qualified reference, ``domain/schema_id@version``, parsed by
:class:`ConditionSchemaRef` rather than by ad-hoc string splitting at each call site.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import ConditionMatchState
from lab_brain.core.models.identifiers import new_id

_REF_PATTERN = re.compile(
    r"^(?P<domain>[a-z0-9_]+)/(?P<schema_id>[a-z0-9_]+)@(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$"
)


class ConditionSchemaError(ValueError):
    """A condition schema reference is malformed, unregistered, or version-mismatched."""


class ConditionSchemaRef(CoreModel):
    """A resolvable pointer to one registered condition schema version."""

    domain: str
    schema_id: str
    version: str

    def __str__(self) -> str:
        return f"{self.domain}/{self.schema_id}@{self.version}"

    @classmethod
    def parse(cls, reference: str) -> ConditionSchemaRef:
        match = _REF_PATTERN.match(reference)
        if not match:
            raise ConditionSchemaError(
                f"condition schema reference must be 'domain/schema_id@major.minor.patch', "
                f"got {reference!r}"
            )
        return cls(**match.groupdict())

    @property
    def schema_key(self) -> tuple[str, str]:
        """Identity without the version, for grouping revisions of one schema."""
        return (self.domain, self.schema_id)


class ConditionSchemaRegistration(CoreModel):
    """§6.19. One registered, versioned condition schema.

    ``comparator_version`` is separate from ``version`` on purpose: the comparison *rules* can
    be corrected without the field set changing, and a ConditionMatch produced under the old
    comparator must remain identifiable as such.
    """

    domain: str
    schema_id: str
    version: str
    json_schema: dict[str, Any]
    comparator_version: str
    registered_at: dt.datetime = Field(default_factory=utc_now)

    @property
    def ref(self) -> ConditionSchemaRef:
        return ConditionSchemaRef(
            domain=self.domain, schema_id=self.schema_id, version=self.version
        )

    @property
    def required_fields(self) -> frozenset[str]:
        required = self.json_schema.get("required", [])
        return frozenset(required) if isinstance(required, list) else frozenset()

    @property
    def known_fields(self) -> frozenset[str]:
        properties = self.json_schema.get("properties", {})
        return frozenset(properties) if isinstance(properties, dict) else frozenset()


class ConditionMismatch(CoreModel):
    """One field on which two condition sets disagree."""

    field: str
    left: Any = None
    right: Any = None
    reason: str


class ConditionMatch(CoreModel):
    """§17.19. The result of comparing two condition sets.

    ``UNKNOWN`` and ``INCOMPATIBLE`` are deliberately distinct. "We cannot tell whether these
    are comparable" must be able to trigger escalation, which collapsing it into "not
    comparable" would hide.
    """

    condition_match_id: str = Field(default_factory=lambda: new_id("condition_match"))
    state: ConditionMatchState
    matched_fields: tuple[str, ...] = ()
    mismatches: tuple[ConditionMismatch, ...] = ()
    unknowns: tuple[str, ...] = ()
    #: Which comparison rules produced this result. A match is not reproducible without it.
    tolerance_policy_version: str
    schema_ref: ConditionSchemaRef
    rationale_ref: str | None = None
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _state_agrees_with_findings(self) -> Self:
        """The state must be consistent with the evidence recorded alongside it.

        Without this, a comparator could report EXACT while listing mismatches, and every
        downstream gate reading only the state would be misled.
        """
        if self.state is ConditionMatchState.EXACT and (self.mismatches or self.unknowns):
            raise ValueError("ConditionMatch state EXACT contradicts recorded mismatches/unknowns")
        if self.state is ConditionMatchState.INCOMPATIBLE and not self.mismatches:
            raise ValueError(
                "ConditionMatch state INCOMPATIBLE requires at least one recorded mismatch"
            )
        if self.state is ConditionMatchState.UNKNOWN and not self.unknowns:
            raise ValueError(
                "ConditionMatch state UNKNOWN requires at least one recorded unknown field"
            )
        return self

    @property
    def is_comparable(self) -> bool:
        """Whether these condition sets may be combined at all (P4)."""
        return self.state in {ConditionMatchState.EXACT, ConditionMatchState.COMPATIBLE}


__all__ = [
    "ConditionMatch",
    "ConditionMatchState",
    "ConditionMismatch",
    "ConditionSchemaError",
    "ConditionSchemaRef",
    "ConditionSchemaRegistration",
]
