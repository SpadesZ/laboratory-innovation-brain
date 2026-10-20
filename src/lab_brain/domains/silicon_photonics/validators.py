"""`validate_expected_trends` — DOM-SP-TOOL-006, and the rule core must not contain (DOM-SP-001).

    DOM-SP-001    Silicon photonics rule/validator 版本必須記錄；core 不得內建 Rs 趨勢規則。
    T-DOM-SP-001  Rs trend validator 只存在 Silicon Photonics DomainPack，移除 plugin 後 core
                  仍可啟動。
    §10.2.1       validate_*  returns ValidationReport; MUST NOT mutate raw evidence.

THE SECOND HALF OF DOM-SP-001 IS THE ONE WITH TEETH. "The rule version must be recorded" is
satisfied by a field; "core must not contain the Rs trend rule" is satisfied only by the rule not
being there, and the way to keep it not-there is for core to have no place to put it. It does not:
`ValidationReport` (§17.19.2) carries findings keyed by an opaque `rule_id`, and every threshold
below lives in `RULES` in this file. Removing this plugin removes the rule and leaves core running,
which `test_core_starts_with_no_domain_pack_installed` exercises directly.

WHY THE THRESHOLDS ARE DATA AND NOT LITERALS IN THE CHECKS. A rule whose threshold is inline can be
changed without changing a version, and a report produced before the change then cannot be
distinguished from one produced after. `RULES` is a declared table with a version per rule; a
correction is one reviewable edit and shows up in every report that cites it.

WHAT THE RULES ARE. §25.1's vertical is the diagnosis case: *Cj trend plausible; Rs extremely high
and weakly bias-dependent*. So the validator checks the two trends that case turns on -- reverse
bias should reduce junction capacitance, and series resistance should not swing wildly across a
sweep -- and reports a FAIL finding when a sweep violates one. It does NOT diagnose: naming the
cause is EPI-001's competing hypotheses in M3, and a validator that announced a root cause would
be pre-empting the debate the system exists to run.

NO REAL DEVICE VALUES. The thresholds are generic plausibility bounds on a *trend*, not on a
magnitude: `MAX_RS_RELATIVE_SWING` is a fraction and `MIN_CJ_MONOTONIC_FRACTION` is a fraction.
Nothing here encodes a capacitance, a resistance, a geometry or a process from any real project,
and the fixtures that exercise it are synthetic.

IT MUTATES NOTHING. `validate` takes a value object and returns a report. It holds no store, no
connection and no attestation, so "MUST NOT mutate raw evidence" is a property of what it can
reach rather than of what it happens to do.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import ClassVar, Final

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.validation import (
    ValidationFinding,
    ValidationReport,
    ValidationStatus,
    report,
)

TOOL_ID: Final = "DOM-SP-TOOL-006"
TOOL_NAME: Final = "validate_expected_trends"
VALIDATOR_ID: Final = "validate_expected_trends"
VALIDATOR_VERSION: Final = "1.0.0"

RULE_RS_BIAS_STABILITY: Final = "SP-RULE-RS-001"
RULE_CJ_REVERSE_BIAS: Final = "SP-RULE-CJ-001"
RULE_SWEEP_SHAPE: Final = "SP-RULE-SWEEP-001"

#: Declared thresholds, versioned per rule. See the module docstring for why these are data.
#:
#: `max_rs_relative_swing`   Rs across a reverse-bias sweep is expected to be weakly
#:                           bias-dependent; a swing beyond this fraction of the mean is the
#:                           anomaly §25.1 describes, reported as a FAIL for a human to explain.
#: `min_cj_monotonic_share`  Cj is expected to fall as reverse bias increases. Stated as a share
#:                           of adjacent pairs rather than as strict monotonicity, because one
#:                           noisy point in a real sweep is not a physics violation.
RULES: Final[dict[str, dict[str, object]]] = {
    RULE_RS_BIAS_STABILITY: {
        "version": "1.0.0",
        "statement": "series resistance is weakly bias-dependent across a reverse-bias sweep",
        "max_rs_relative_swing": Decimal("0.25"),
    },
    RULE_CJ_REVERSE_BIAS: {
        "version": "1.0.0",
        "statement": "junction capacitance decreases as reverse bias increases",
        "min_cj_monotonic_share": Decimal("0.75"),
    },
    RULE_SWEEP_SHAPE: {
        "version": "1.0.0",
        "statement": "a trend check needs at least two bias points",
        "min_points": 2,
    },
}


class TrendSample(CoreModel):
    """One bias point of an extracted sweep.

    A value object, not an Attestation. The validator reads a sweep the extractor produced and
    reports on it; the scientific record is written by admission, elsewhere, from the extraction
    result (§10.2.1: a validator MUST NOT mutate raw evidence).
    """

    bias_v: Decimal
    cj_per_length: Decimal | None = None
    rs_per_length: Decimal | None = None


class TrendSubject(CoreModel):
    """What is being validated, and what it can be traced back to."""

    subject_id: str
    samples: tuple[TrendSample, ...]
    #: Run / Artifact / EvidenceUnit references the sweep came from. Copied into the report's
    #: `provenance_refs`, so a finding can be walked back without the report holding the values.
    provenance_refs: tuple[str, ...] = ()


class ExpectedTrendValidator:
    """DOM-SP-001's Rs trend rule, and the Cj trend beside it. Lives only in this pack."""

    validator_id: ClassVar[str] = VALIDATOR_ID
    validator_version: ClassVar[str] = VALIDATOR_VERSION

    def validate(self, subject: object) -> ValidationReport:
        """Check a sweep against the declared trends. Returns a report; never a bool.

        An unusable subject is reported UNKNOWN rather than raising: §17.19.2 keeps UNKNOWN
        distinct from FAIL because "the check could not run" and "the rule was violated" lead to
        different gate outcomes, and a validator that raised would force its caller to invent one.
        """
        if not isinstance(subject, TrendSubject):
            return report(
                subject_type="TREND_SWEEP",
                subject_id=getattr(subject, "subject_id", "(unknown)"),
                validator_id=self.validator_id,
                validator_version=self.validator_version,
                findings=(
                    ValidationFinding(
                        rule_id=RULE_SWEEP_SHAPE,
                        rule_version=str(RULES[RULE_SWEEP_SHAPE]["version"]),
                        status=ValidationStatus.UNKNOWN,
                        message=(
                            f"{type(subject).__name__} is not a TrendSubject, so no trend could "
                            "be read from it"
                        ),
                    ),
                ),
            )

        findings: list[ValidationFinding] = []
        ordered = tuple(sorted(subject.samples, key=lambda sample: sample.bias_v))
        minimum = int(RULES[RULE_SWEEP_SHAPE]["min_points"])  # type: ignore[call-overload]

        if len(ordered) < minimum:
            findings.append(
                ValidationFinding(
                    rule_id=RULE_SWEEP_SHAPE,
                    rule_version=str(RULES[RULE_SWEEP_SHAPE]["version"]),
                    status=ValidationStatus.UNKNOWN,
                    message=(
                        f"{len(ordered)} bias point(s) supplied; a trend needs at least {minimum}. "
                        "A single point is a value, not a trend, and reporting PASS on one would "
                        "make an un-run check look like a satisfied rule"
                    ),
                )
            )
        else:
            findings.extend(self._rs_stability(ordered))
            findings.extend(self._cj_reverse_bias(ordered))

        return report(
            subject_type="TREND_SWEEP",
            subject_id=subject.subject_id,
            validator_id=self.validator_id,
            validator_version=self.validator_version,
            findings=tuple(findings),
            provenance_refs=subject.provenance_refs,
        )

    # -- the rules ----------------------------------------------------------

    def _rs_stability(self, ordered: tuple[TrendSample, ...]) -> list[ValidationFinding]:
        """DOM-SP-001's named rule: Rs is weakly bias-dependent."""
        rule = RULES[RULE_RS_BIAS_STABILITY]
        values = [s.rs_per_length for s in ordered if s.rs_per_length is not None]
        if len(values) < 2:
            return [
                ValidationFinding(
                    rule_id=RULE_RS_BIAS_STABILITY,
                    rule_version=str(rule["version"]),
                    status=ValidationStatus.UNKNOWN,
                    subject_field="Rs_per_length",
                    message="fewer than two Rs values were extracted; the trend is not checkable",
                )
            ]
        mean = sum(values, Decimal(0)) / Decimal(len(values))
        if mean == 0:
            return [
                ValidationFinding(
                    rule_id=RULE_RS_BIAS_STABILITY,
                    rule_version=str(rule["version"]),
                    status=ValidationStatus.UNKNOWN,
                    subject_field="Rs_per_length",
                    message="mean Rs is zero; a relative swing is undefined against it",
                )
            ]
        swing = (max(values) - min(values)) / abs(mean)
        limit = rule["max_rs_relative_swing"]
        assert isinstance(limit, Decimal)
        if swing > limit:
            return [
                ValidationFinding(
                    rule_id=RULE_RS_BIAS_STABILITY,
                    rule_version=str(rule["version"]),
                    status=ValidationStatus.FAIL,
                    subject_field="Rs_per_length",
                    message=(
                        f"Rs varies by {swing} of its mean across the sweep, beyond the declared "
                        f"{limit}. §25.1's anomaly is the opposite reading of the same rule -- "
                        "this reports the violation and names no cause"
                    ),
                    detail={"relative_swing": str(swing), "limit": str(limit)},
                )
            ]
        return [
            ValidationFinding(
                rule_id=RULE_RS_BIAS_STABILITY,
                rule_version=str(rule["version"]),
                status=ValidationStatus.PASS,
                subject_field="Rs_per_length",
                message=f"Rs relative swing {swing} is within the declared {limit}",
                detail={"relative_swing": str(swing), "limit": str(limit)},
            )
        ]

    def _cj_reverse_bias(self, ordered: tuple[TrendSample, ...]) -> list[ValidationFinding]:
        rule = RULES[RULE_CJ_REVERSE_BIAS]
        pairs = [(s.bias_v, s.cj_per_length) for s in ordered if s.cj_per_length is not None]
        if len(pairs) < 2:
            return [
                ValidationFinding(
                    rule_id=RULE_CJ_REVERSE_BIAS,
                    rule_version=str(rule["version"]),
                    status=ValidationStatus.UNKNOWN,
                    subject_field="Cj_per_length",
                    message="fewer than two Cj values were extracted; the trend is not checkable",
                )
            ]
        # Sorted ascending by bias, and reverse bias is NEGATIVE. So moving up the sorted list is
        # moving towards zero bias -- less depletion, more capacitance -- and the rule "Cj falls as
        # reverse bias increases" is the same statement as "Cj does not fall as bias increases".
        # Written in the second form because that is the direction the list is actually walked.
        steps = list(pairwise(pairs))
        conforming = sum(1 for (_, earlier), (_, later) in steps if later >= earlier)
        share = Decimal(conforming) / Decimal(len(steps))
        floor = rule["min_cj_monotonic_share"]
        assert isinstance(floor, Decimal)
        status = ValidationStatus.PASS if share >= floor else ValidationStatus.FAIL
        return [
            ValidationFinding(
                rule_id=RULE_CJ_REVERSE_BIAS,
                rule_version=str(rule["version"]),
                status=status,
                subject_field="Cj_per_length",
                message=(
                    f"{conforming}/{len(steps)} adjacent bias steps have Cj rising as reverse bias "
                    f"is reduced (share {share}, declared floor {floor})"
                ),
                detail={"share": str(share), "floor": str(floor)},
            )
        ]


__all__ = [
    "RULES",
    "RULE_CJ_REVERSE_BIAS",
    "RULE_RS_BIAS_STABILITY",
    "RULE_SWEEP_SHAPE",
    "TOOL_ID",
    "TOOL_NAME",
    "VALIDATOR_ID",
    "VALIDATOR_VERSION",
    "ExpectedTrendValidator",
    "TrendSample",
    "TrendSubject",
]
