"""Condition schema registry — EVI-005's admission point.

> 每筆 condition-aware record 必須帶 `conditions_schema_version`。資料庫寫入時驗證 schema；
> 不符者拒絕或隔離（EVI-005）。

Two things follow that the registry has to make true rather than merely possible.

**A version must be registered before it can be written against.** An unregistered version means
nobody can later say what those condition keys meant, so a record carrying one is unauditable
from the moment it is stored.

**Comparison is domain-supplied.** Core validates *structure* -- required keys present, no
undeclared keys, version resolvable. It never decides whether 1549 nm and 1550 nm are the same
condition; a DomainPack comparator does (§24.1). This module therefore contains no physical
quantity and no tolerance.

Validation here is deliberately structural rather than a full JSON Schema evaluation: the
required/properties subset is what EVI-005's pass condition needs, and pulling in a JSON Schema
engine for it would add a dependency this milestone does not justify (P20). Where a domain needs
richer validation it registers a comparator that performs it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol

from lab_brain.core.models.condition import (
    ConditionMatch,
    ConditionSchemaError,
    ConditionSchemaRef,
    ConditionSchemaRegistration,
)


class ConditionComparator(Protocol):
    """A DomainPack-registered comparison rule (§6.19).

    ``version`` is separate from the schema version because comparison rules can be corrected
    without the field set changing, and a ConditionMatch must remain attributable to the rules
    that produced it.
    """

    version: str

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        schema: ConditionSchemaRegistration,
    ) -> ConditionMatch: ...


class ConditionSchemaRegistry:
    """Holds registered condition schema versions and their comparators.

    Not a singleton and not module-global: tests, and eventually multiple projects, need
    independent registries. Global mutable registration state is how a domain leaks into core
    by accident.
    """

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str, str], ConditionSchemaRegistration] = {}
        self._comparators: dict[tuple[str, str], ConditionComparator] = {}

    # -- registration -----------------------------------------------------

    def register_schema(self, registration: ConditionSchemaRegistration) -> None:
        """Register one schema version.

        Re-registering the same ``(domain, schema_id, version)`` with different content is
        rejected: a version is an immutable contract, and silently redefining one would
        reinterpret every record already written against it.
        """
        key = (registration.domain, registration.schema_id, registration.version)
        existing = self._schemas.get(key)
        if existing is not None and existing != registration:
            raise ConditionSchemaError(
                f"{registration.ref} is already registered with different content; a schema "
                "version is immutable -- publish a new version instead"
            )
        self._schemas[key] = registration

    def register_comparator(
        self, domain: str, schema_id: str, comparator: ConditionComparator
    ) -> None:
        self._comparators[(domain, schema_id)] = comparator

    # -- lookup -----------------------------------------------------------

    def get_schema(self, reference: str | ConditionSchemaRef) -> ConditionSchemaRegistration:
        ref = (
            reference
            if isinstance(reference, ConditionSchemaRef)
            else ConditionSchemaRef.parse(reference)
        )
        try:
            return self._schemas[(ref.domain, ref.schema_id, ref.version)]
        except KeyError:
            known = sorted(str(schema.ref) for schema in self._schemas.values())
            raise ConditionSchemaError(
                f"condition schema {ref} is not registered. A record cannot be written against "
                f"an unregistered version (EVI-005). Registered: {known or '(none)'}"
            ) from None

    def get_comparator(self, reference: str | ConditionSchemaRef) -> ConditionComparator:
        ref = (
            reference
            if isinstance(reference, ConditionSchemaRef)
            else ConditionSchemaRef.parse(reference)
        )
        try:
            return self._comparators[ref.schema_key]
        except KeyError:
            raise ConditionSchemaError(
                f"no comparator registered for {ref.domain}/{ref.schema_id}; core does not "
                "define condition comparison semantics (§24.1)"
            ) from None

    def is_registered(self, reference: str | ConditionSchemaRef) -> bool:
        try:
            self.get_schema(reference)
        except ConditionSchemaError:
            return False
        return True

    def __iter__(self) -> Iterator[ConditionSchemaRegistration]:
        return iter(self._schemas.values())

    def __len__(self) -> int:
        return len(self._schemas)

    def versions_of(self, domain: str, schema_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                version
                for (registered_domain, registered_id, version) in self._schemas
                if (registered_domain, registered_id) == (domain, schema_id)
            )
        )

    # -- validation -------------------------------------------------------

    def validate(
        self, conditions: Mapping[str, Any], conditions_schema_version: str
    ) -> ConditionSchemaRegistration:
        """Validate a condition set against its declared schema version.

        Raises :class:`ConditionSchemaError` on any of: malformed reference, unregistered
        version, missing required key, or undeclared key. Returns the registration so callers
        can reuse it without a second lookup.
        """
        schema = self.get_schema(conditions_schema_version)

        missing = sorted(schema.required_fields - set(conditions))
        if missing:
            raise ConditionSchemaError(
                f"conditions are missing required fields {missing} declared by {schema.ref}"
            )

        # Undeclared keys are rejected rather than ignored. A misspelled condition key that is
        # silently dropped produces a record that looks fully specified and is not -- and
        # condition-aware retrieval would then treat it as comparable when it is not.
        undeclared = sorted(set(conditions) - schema.known_fields)
        if undeclared:
            raise ConditionSchemaError(
                f"conditions carry fields {undeclared} not declared by {schema.ref}; "
                f"declared fields are {sorted(schema.known_fields)}"
            )
        return schema

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        conditions_schema_version: str,
    ) -> ConditionMatch:
        """Compare two condition sets under their registered comparator.

        Both sides are validated first: comparing an invalid condition set would produce a
        ConditionMatch that looks authoritative and rests on unvalidated input.
        """
        schema = self.validate(left, conditions_schema_version)
        self.validate(right, conditions_schema_version)
        comparator = self.get_comparator(conditions_schema_version)
        match = comparator.compare(left, right, schema)
        if match.tolerance_policy_version != comparator.version:
            raise ConditionSchemaError(
                f"comparator returned tolerance_policy_version "
                f"{match.tolerance_policy_version!r} but declares version "
                f"{comparator.version!r}; a ConditionMatch must be attributable to the rules "
                "that produced it"
            )
        return match


__all__ = ["ConditionComparator", "ConditionSchemaRegistry"]
