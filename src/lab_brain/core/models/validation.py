"""ValidationReport — what a domain validator returns instead of a boolean (§17.19.2).

    §17.19.2  DomainPack validators MUST return ValidationReport, never an unstructured
              boolean/string.

WHY THE RULE IS STATED AS A PROHIBITION. A validator that returns `False` has destroyed the only
thing anyone downstream needs: *which* rule failed, under *which* version of that rule, against
*which* subject. A conflict opened on "the validator said no" cannot be re-checked after the rule
changes, and a `VALIDITY_CONFLICT` (§17.19.3) that cannot name its failed rule is a conflict nobody
can close.

VALIDATION IS NOT EVIDENCE, AND THIS OBJECT IS NOT AN ATTESTATION. §10.2.1: `validate_*` "returns
ValidationReport; MUST NOT mutate raw evidence". A report *about* a measurement is a separate
record from the measurement, and it carries `provenance_refs` pointing back rather than a copy of
the values -- so a validator cannot quietly become a second writer of scientific fact. The
scientific path stays Artifact -> Claim/Observation -> Attestation; a report sits beside it.

NOT PERSISTED IN M2, deliberately, and recorded in `schema_drift.UNBOUND` rather than left
implicit. §26's rows for VER-002 and DOM-SP-001 are `unit` and `domain`: what they require is that
a validator *returns* this shape and that the rule lives in the DomainPack. The table arrives with
VER-004's planner-side plausibility check, which is the first thing that needs to read a report it
did not just compute.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.identifiers import new_id


class ValidationStatus(StrEnum):
    """§17.19.2's four outcomes.

    ``UNKNOWN`` is distinct from ``FAIL`` for the reason `ConditionMatchState.UNKNOWN` is distinct
    from `INCOMPATIBLE`: "the validator could not tell" and "the validator says no" lead to
    different gate outcomes, and a validator that reported a missing input as FAIL would make an
    un-runnable check indistinguishable from a violated rule.
    """

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ValidationFinding(CoreModel):
    """One thing a validator noticed, bound to the rule that noticed it.

    ``rule_id`` and ``rule_version`` together are what make a finding re-checkable: a domain rule
    that is corrected must not silently reinterpret the findings it produced before the correction.
    """

    rule_id: str
    rule_version: str
    status: ValidationStatus
    message: str
    #: The observable or condition field the finding is about, when it is about one.
    subject_field: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_failure(self) -> bool:
        return self.status is ValidationStatus.FAIL


class ValidationReport(CoreModel):
    """§17.19.2's structured validator return.

    ``status`` is DERIVED from the findings rather than supplied, and that is the half a boolean
    return loses in a different way: a report whose status disagreed with its own findings would
    be read by the gate and audited by a human, and they would reach opposite conclusions.
    """

    report_id: str = Field(default_factory=lambda: new_id("validation"))
    subject_type: str
    subject_id: str
    validator_id: str
    validator_version: str
    status: ValidationStatus
    findings: tuple[ValidationFinding, ...] = ()
    failed_rules: tuple[str, ...] = ()
    #: What the validator read. Never the values themselves -- see the module docstring.
    provenance_refs: tuple[str, ...] = ()
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _status_agrees_with_findings(self) -> Self:
        expected = derive_status(self.findings)
        if self.status is not expected:
            raise ValueError(
                f"validation report {self.report_id} declares status {self.status.value} but its "
                f"findings derive {expected.value}. A report whose summary contradicts its own "
                "detail is read one way by a gate and another way by a human"
            )
        failed = tuple(sorted({finding.rule_id for finding in self.findings if finding.is_failure}))
        if tuple(sorted(set(self.failed_rules))) != failed:
            raise ValueError(
                f"validation report {self.report_id} lists failed_rules "
                f"{sorted(set(self.failed_rules))} but its FAIL findings name {list(failed)}; "
                "§17.19.3's VALIDITY_CONFLICT is opened against failed_rules, so a list that "
                "disagrees with the findings opens a conflict nobody can close"
            )
        return self

    @property
    def passed(self) -> bool:
        """``PASS`` only.

        WARN is not a pass. §17.19.2 declares it as its own status precisely because a validator
        needs to be able to say "this is admissible and you should look at it", and collapsing it
        into PASS at the one place callers read would discard the distinction the enum exists for.
        """
        return self.status is ValidationStatus.PASS


def derive_status(findings: tuple[ValidationFinding, ...]) -> ValidationStatus:
    """The report's status, computed from its findings. Worst-first, and UNKNOWN outranks WARN.

    THE ORDER IS THE CLAIM. FAIL is decisive. Then UNKNOWN, because a check that could not run is
    a weaker basis than a check that ran and grumbled -- reporting WARN over UNKNOWN would let an
    un-runnable rule be summarised as "ran, minor issue". Then WARN. An empty finding list is PASS:
    a validator that examined a subject and found nothing wrong has passed it.
    """
    statuses = {finding.status for finding in findings}
    for candidate in (ValidationStatus.FAIL, ValidationStatus.UNKNOWN, ValidationStatus.WARN):
        if candidate in statuses:
            return candidate
    return ValidationStatus.PASS


def report(
    *,
    subject_type: str,
    subject_id: str,
    validator_id: str,
    validator_version: str,
    findings: tuple[ValidationFinding, ...] = (),
    provenance_refs: tuple[str, ...] = (),
    report_id: str | None = None,
) -> ValidationReport:
    """Build a consistent report. The only constructor a validator should use.

    Exists so `status` and `failed_rules` are computed in one place rather than by every validator
    that ever ships: the model refuses an inconsistent pair, and a helper that derives both means
    a DomainPack author cannot produce one by hand and be refused for it.
    """
    built = ValidationReport(
        subject_type=subject_type,
        subject_id=subject_id,
        validator_id=validator_id,
        validator_version=validator_version,
        status=derive_status(findings),
        findings=findings,
        failed_rules=tuple(sorted({finding.rule_id for finding in findings if finding.is_failure})),
        provenance_refs=provenance_refs,
    )
    # Built then re-validated rather than splatted into the constructor: a `**{...}` conditional
    # erases the field types, and mypy then checks nothing about any argument.
    return (
        built
        if report_id is None
        else ValidationReport.model_validate({**built.model_dump(), "report_id": report_id})
    )


__all__ = [
    "ValidationFinding",
    "ValidationReport",
    "ValidationStatus",
    "derive_status",
    "report",
]
