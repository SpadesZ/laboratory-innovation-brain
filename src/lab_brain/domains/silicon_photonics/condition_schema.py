"""Silicon photonics condition schema and comparator (EVI-005, §6.19, §24.1).

    §24.1  Silicon Photonics DomainPack owns: 波長/偏壓/溫度/幾何/doping/driver-load semantics

EVERY FIELD HERE IS AUTHORISED BY THE SPECIFICATION, and the list is deliberately short. §25.1's
vertical is a bias sweep on a PN junction and §25.3's EVI-001 names "bias/frequency conditions";
§24.1 names wavelength, bias, temperature and geometry as this pack's column. What is NOT here is
anything the spec does not authorise -- there is no ring radius, no doping profile, no mesh field.
A DomainPack may eventually need them; inventing them now because they are scientifically plausible
is exactly the move §23.4 reserves for a human steering point.

`device_length_um` IS A GEOMETRY CONDITION AND IT IS LOAD-BEARING, not decoration. EVI-001 requires
a normalization basis, and `extract_cj_rs` normalizes per unit length -- so a record that does not
carry the length has no basis to normalize against, and the extractor returns UNKNOWN rather than a
number. It is a *condition* rather than an extractor parameter because two measurements of
differently-sized devices are not comparable, and that is what a condition is for.

THE COMPARATOR IS VERSIONED SEPARATELY FROM THE SCHEMA (§6.19). Tolerances are rules, not fields:
deciding that 1549.9 nm and 1550.0 nm are the same condition can be corrected without the field set
changing, and a `ConditionMatch` produced under the old tolerance must stay identifiable as such.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from lab_brain.core.models.condition import (
    ConditionMatch,
    ConditionMismatch,
    ConditionSchemaRegistration,
)
from lab_brain.core.models.enums import ConditionMatchState

DOMAIN: Final = "silicon_photonics"
SCHEMA_ID: Final = "pn_junction_ac"
SCHEMA_VERSION: Final = "1.0.0"
COMPARATOR_VERSION: Final = "1.0.0"

#: The reference every SiPh AC record, Run and Capability carries.
SCHEMA_REF: Final = f"{DOMAIN}/{SCHEMA_ID}@{SCHEMA_VERSION}"

#: Tolerances, declared as data and versioned with the comparator. Values are relative unless the
#: name says otherwise. Stated here rather than inline so a correction is one reviewable edit and
#: shows up as a comparator version bump.
TOLERANCES: Final[Mapping[str, Decimal]] = {
    "bias_v": Decimal("0.01"),  # absolute, volts
    "frequency_hz": Decimal("0.05"),  # relative
    "temperature_k": Decimal("1.0"),  # absolute, kelvin
    "wavelength_nm": Decimal("0.5"),  # absolute, nanometres
    "device_length_um": Decimal("0"),  # exact: a different length is a different device
}

#: Fields compared with an ABSOLUTE tolerance. The rest are relative. Split explicitly because
#: "0.05 V" and "5% of the bias" are different rules and a bias sweep through zero makes the
#: second one meaningless.
_ABSOLUTE: Final = frozenset({"bias_v", "temperature_k", "wavelength_nm", "device_length_um"})


def registration() -> ConditionSchemaRegistration:
    """§6.19's registration for the one schema this pack declares in M2."""
    return ConditionSchemaRegistration(
        domain=DOMAIN,
        schema_id=SCHEMA_ID,
        version=SCHEMA_VERSION,
        comparator_version=COMPARATOR_VERSION,
        json_schema={
            "type": "object",
            # REQUIRED is the EVI-001 half. A Cj/Rs record without bias and frequency cannot be
            # placed on a sweep, and without a device length it cannot be normalized -- which is
            # three of EVI-001's four clauses expressed as a schema rather than as a convention.
            "required": ["bias_v", "frequency_hz", "device_length_um"],
            "properties": {
                "bias_v": {"type": "string", "description": "Applied bias, volts, decimal string"},
                "frequency_hz": {
                    "type": "string",
                    "description": "Small-signal frequency, hertz, decimal string",
                },
                "device_length_um": {
                    "type": "string",
                    "description": "Active device length, micrometres. The normalization basis.",
                },
                "temperature_k": {"type": "string", "description": "Device temperature, kelvin"},
                "wavelength_nm": {
                    "type": "string",
                    "description": "Optical wavelength, nanometres. Absent for a purely "
                    "electrical measurement -- NOT defaulted to 1550 (§24.1 forbids core or this "
                    "schema assuming it).",
                },
            },
            # Decimal strings rather than JSON numbers throughout: `canonical_json` refuses floats
            # because a value that rounds differently on two machines cannot be hashed
            # reproducibly, and a condition that hashes differently is a condition two processes
            # disagree about.
            "additionalProperties": False,
        },
    )


def _decimal(value: Any) -> Decimal | None:
    """Parse a condition value, or `None` if it is not a number. Never raises."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class PnJunctionConditionComparator:
    """§6.19's comparator for `pn_junction_ac`, versioned independently of the schema.

    FIVE-VALUED, and `UNKNOWN` is not a failure mode. §17.19 keeps UNKNOWN distinct from
    INCOMPATIBLE because "we cannot tell whether these are comparable" and "they are not
    comparable" lead to different gate outcomes -- `TransitionPolicy.evaluate` escalates the first
    to NEED_HUMAN_REVIEW and denies on the second. A comparator that collapsed them would lose the
    escalation signal.

    Deterministic: no clock, no randomness, and every collection it builds is sorted.
    """

    #: Declared as an instance attribute with a default rather than a `ClassVar`: §6.19's
    #: `ConditionComparator` protocol declares `version` as an instance variable, and a ClassVar
    #: does not satisfy it -- a comparator that did not type-check against the protocol would be
    #: registered through `Any` and the structural check would have been skipped.
    version: str = COMPARATOR_VERSION

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        schema: ConditionSchemaRegistration,
    ) -> ConditionMatch:
        matched: list[str] = []
        mismatches: list[ConditionMismatch] = []
        unknowns: list[str] = []

        for field in sorted(schema.known_fields):
            a, b = left.get(field), right.get(field)
            if a is None and b is None:
                continue
            if a is None or b is None:
                # One side says nothing. NOT a mismatch: an electrical sweep that records no
                # wavelength has not contradicted one that does, it has declined to state it.
                unknowns.append(field)
                continue
            left_value, right_value = _decimal(a), _decimal(b)
            if left_value is None or right_value is None:
                unknowns.append(field)
                continue

            tolerance = TOLERANCES.get(field, Decimal("0"))
            delta = abs(left_value - right_value)
            if field in _ABSOLUTE:
                within = delta <= tolerance
            else:
                scale = max(abs(left_value), abs(right_value))
                within = delta <= tolerance * scale if scale else delta == 0
            if within:
                matched.append(field)
            else:
                mismatches.append(
                    ConditionMismatch(
                        field=field,
                        left=str(left_value),
                        right=str(right_value),
                        reason=(
                            f"|{left_value} - {right_value}| = {delta} exceeds the declared "
                            f"{'absolute' if field in _ABSOLUTE else 'relative'} tolerance "
                            f"{tolerance} at comparator {self.version}"
                        ),
                    )
                )

        if mismatches:
            state = ConditionMatchState.INCOMPATIBLE
        elif unknowns:
            state = ConditionMatchState.UNKNOWN
        elif not matched:
            # Nothing compared at all. Reported as UNKNOWN rather than EXACT, which is the
            # difference between "these agree" and "there was nothing to disagree about" -- and
            # `ConditionMatch` refuses UNKNOWN with no recorded unknown, so the reason is stored.
            unknowns.append("(no comparable field present)")
            state = ConditionMatchState.UNKNOWN
        else:
            exact = all(
                _decimal(left.get(field)) == _decimal(right.get(field)) for field in matched
            )
            state = ConditionMatchState.EXACT if exact else ConditionMatchState.COMPATIBLE

        return ConditionMatch(
            state=state,
            matched_fields=tuple(sorted(matched)),
            mismatches=tuple(mismatches),
            unknowns=tuple(sorted(unknowns)),
            tolerance_policy_version=self.version,
            schema_ref=schema.ref,
        )


__all__ = [
    "COMPARATOR_VERSION",
    "DOMAIN",
    "SCHEMA_ID",
    "SCHEMA_REF",
    "SCHEMA_VERSION",
    "TOLERANCES",
    "PnJunctionConditionComparator",
    "registration",
]
