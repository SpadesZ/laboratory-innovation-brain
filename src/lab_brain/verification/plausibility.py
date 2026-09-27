"""§9.1's `plausible(y)`, all four clauses (VER-004).

    plausible(y, action, domain_policy) is true iff ALL hold:
      1. y is a member of a declared, versioned OutcomeSpace for this action/hypothesis
      2. y is not excluded by an existing EXPLICIT-status condition or validity bound
      3. y passes the DomainPack validator (ValidationReport.status != FAIL)
      4. the producing Capability can actually yield y under current conditions
    Planner MUST NOT invent outcomes. An outcome that is merely imaginable is not plausible.

M0b's `core.sufficiency` evaluates clauses 1-2 and names 3-4 as unevaluated; this module is where
they are evaluated, and it leaves M0b's function untouched.

CLAUSES 1-2 ARE CORE'S, CLAUSES 3-4 ARE THE DOMAIN'S. Membership and explicit exclusion are read
off the declared OutcomeSpace; a validity bound is a declared `{"min": .., "max": ..}` or
`{"in": [..]}` on a condition the action runs under, and a condition that is present and outside a
declared bound excludes every outcome of that space (the space is not defined there). Whether an
outcome is physically admissible (3) and whether this capability can produce it under these
conditions (4) are domain judgments: a DomainPack registers ONE validator per domain under
`outcome_validator_id(domain)` through §24.3's `register_validators`, and it returns a
`ValidationReport` -- never a boolean (§17.19.2). Its FAIL findings about the outcome refuse clause
3; its FAIL findings with `subject_field == "capability"` refuse clause 4. Core adds the part of
clause 4 it can check itself: a capability that is UNAVAILABLE, or that does not produce the
observable, yields nothing.

NO VALIDATOR IS NOT A PASS. A domain that registered no outcome validator leaves clause 3
unanswered, and an unanswered clause is refused, not assumed -- the verdict names the missing
validator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lab_brain.core.models.capability import Capability
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.core.models.validation import ValidationReport, ValidationStatus

#: Findings a validator addresses to the capability, not the outcome, carry this subject field.
CAPABILITY_FIELD = "capability"


def outcome_validator_id(domain: str) -> str:
    """The id under which a domain registers its §9.1 outcome validator."""
    return f"{domain}.outcome_plausibility"


class PlausibilityClause(StrEnum):
    DECLARED_OUTCOME = "DECLARED_OUTCOME"
    NOT_EXCLUDED = "NOT_EXCLUDED"
    DOMAIN_VALIDATOR = "DOMAIN_VALIDATOR"
    CAPABILITY_CAN_YIELD = "CAPABILITY_CAN_YIELD"


@dataclass(frozen=True)
class OutcomeSubject:
    """What a domain outcome validator is asked about. Frozen: it cannot edit the question."""

    outcome: str
    outcome_space_ref: str
    observable_ref: str
    capability_id: str
    conditions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlausibilityVerdict:
    outcome: str
    plausible: bool
    failed_clause: PlausibilityClause | None = None
    detail: str = ""
    report_id: str | None = None


def _bound_violation(bounds: Mapping[str, Any], conditions: Mapping[str, Any]) -> str | None:
    for name in sorted(bounds):
        bound = bounds[name]
        if name not in conditions or not isinstance(bound, Mapping):
            continue
        value = conditions[name]
        if "in" in bound and value not in bound["in"]:
            return f"{name}={value!r} is outside the declared set {list(bound['in'])}"
        try:
            if "min" in bound and float(value) < float(bound["min"]):
                return f"{name}={value} is below the declared minimum {bound['min']}"
            if "max" in bound and float(value) > float(bound["max"]):
                return f"{name}={value} is above the declared maximum {bound['max']}"
        except (TypeError, ValueError):
            return f"{name}={value!r} cannot be compared with the declared numeric bound"
    return None


def assess_outcome(
    outcome: str,
    *,
    space: OutcomeSpace,
    observable_ref: str,
    capability: Capability,
    conditions: Mapping[str, Any],
    validator: Any | None,
) -> PlausibilityVerdict:
    """All four clauses, in order; the first that refuses is named. Pure but for the validator."""
    if outcome not in space.outcomes:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.DECLARED_OUTCOME,
            f"{outcome!r} is not a member of {space.ref}; a planner MUST NOT invent outcomes",
        )
    if outcome in space.explicit_exclusions:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.NOT_EXCLUDED,
            f"{space.ref} explicitly excludes {outcome!r}",
        )
    violation = _bound_violation(space.validity_bounds, conditions)
    if violation is not None:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.NOT_EXCLUDED,
            f"{space.ref} is not defined here: {violation}",
        )
    if validator is None:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.DOMAIN_VALIDATOR,
            f"no outcome validator is registered for domain {space.domain!r} "
            f"({outcome_validator_id(space.domain)}); clause 3 unanswered is clause 3 refused",
        )
    report: ValidationReport = validator.validate(
        OutcomeSubject(
            outcome=outcome,
            outcome_space_ref=space.ref,
            observable_ref=observable_ref,
            capability_id=capability.capability_id,
            conditions=dict(conditions),
        )
    )
    outcome_failures = [
        f for f in report.findings if f.is_failure and f.subject_field != CAPABILITY_FIELD
    ]
    if outcome_failures:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.DOMAIN_VALIDATOR,
            "; ".join(f"{f.rule_id}@{f.rule_version}: {f.message}" for f in outcome_failures),
            report.report_id,
        )
    if not capability.is_plannable or observable_ref not in capability.produces:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.CAPABILITY_CAN_YIELD,
            f"{capability.capability_id} is {capability.availability.value} and produces "
            f"{list(capability.produces)}; it cannot yield {observable_ref}={outcome!r} now",
            report.report_id,
        )
    capability_failures = [
        f for f in report.findings if f.is_failure and f.subject_field == CAPABILITY_FIELD
    ]
    if capability_failures:
        return PlausibilityVerdict(
            outcome,
            False,
            PlausibilityClause.CAPABILITY_CAN_YIELD,
            "; ".join(f"{f.rule_id}@{f.rule_version}: {f.message}" for f in capability_failures),
            report.report_id,
        )
    if report.status is ValidationStatus.FAIL:  # pragma: no cover - every FAIL is classified above
        raise AssertionError("a FAIL report with no FAIL finding")
    return PlausibilityVerdict(outcome, True, None, "", report.report_id)


__all__ = [
    "CAPABILITY_FIELD",
    "OutcomeSubject",
    "PlausibilityClause",
    "PlausibilityVerdict",
    "assess_outcome",
    "outcome_validator_id",
]
