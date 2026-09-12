"""The authoritative DONE gate: a milestone is complete only if its tests actually passed.

``markers.py`` answers "is there a test?" from source. That question is necessary but not
sufficient, because a collected test can be skipped, xfailed or deselected and still look like
coverage. This module answers the question that matters: "did a test for this Requirement
execute and pass, under the gate profile this milestone declares?"

Two conditions, both required:

  1. every Requirement allocated to a DONE milestone has >= 1 test with outcome ``passed``;
  2. the run that produced the report had every gate in the milestone's ``gate_profile``
     enabled -- so a milestone needing PostgreSQL cannot be signed off by a run that skipped
     every PostgreSQL test.

Fails closed: a missing or unreadable report is a violation, not a pass.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from lab_brain.spec.outcome_plugin import REPORT_SCHEMA_VERSION
from lab_brain.spec.parser import repo_root
from lab_brain.spec.registry import MilestoneCatalog

#: Outcomes that count as evidence a Requirement was discharged. Deliberately only one.
COVERING_OUTCOMES = frozenset({"passed"})


class OutcomeReportError(RuntimeError):
    """The outcome report is missing or structurally invalid."""


@dataclass(frozen=True)
class RecordedOutcome:
    """One marked test's real outcome.

    Not named ``TestOutcome``: pytest collects ``Test*`` classes, so that name makes this
    dataclass look like a test class wherever it is imported into a test module.
    """

    node_id: str
    requirement_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    outcome: str

    @property
    def counts_as_coverage(self) -> bool:
        return self.outcome in COVERING_OUTCOMES


@dataclass(frozen=True)
class OutcomeReport:
    path: Path
    generated_at: str
    enabled_gates: frozenset[str]
    tests: tuple[RecordedOutcome, ...]

    def passing_requirement_ids(self) -> frozenset[str]:
        return frozenset(
            requirement_id
            for test in self.tests
            if test.counts_as_coverage
            for requirement_id in test.requirement_ids
        )

    def tests_for(self, requirement_id: str) -> tuple[RecordedOutcome, ...]:
        return tuple(test for test in self.tests if requirement_id in test.requirement_ids)


def default_report_path() -> Path:
    return repo_root() / "var" / "requirement_outcomes.json"


def load_outcome_report(path: Path | None = None) -> OutcomeReport:
    resolved = path or default_report_path()
    if not resolved.is_file():
        raise OutcomeReportError(
            f"outcome report not found at {resolved}. Run pytest with "
            f"--requirement-outcomes={resolved} before checking coverage."
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OutcomeReportError(f"{resolved} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OutcomeReportError(f"{resolved} must contain a JSON object")
    version = payload.get("schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise OutcomeReportError(
            f"{resolved} has schema_version {version!r}, expected {REPORT_SCHEMA_VERSION}"
        )
    raw_tests = payload.get("tests")
    if not isinstance(raw_tests, list):
        raise OutcomeReportError(f"{resolved}: 'tests' must be a list")

    tests: list[RecordedOutcome] = []
    for entry in raw_tests:
        if not isinstance(entry, dict):
            raise OutcomeReportError(f"{resolved}: each test entry must be an object")
        tests.append(
            RecordedOutcome(
                node_id=str(entry.get("node_id", "")),
                requirement_ids=tuple(entry.get("requirement_ids") or ()),
                test_ids=tuple(entry.get("test_ids") or ()),
                outcome=str(entry.get("outcome", "not_run")),
            )
        )
    return OutcomeReport(
        path=resolved,
        generated_at=str(payload.get("generated_at", "")),
        enabled_gates=frozenset(payload.get("enabled_gates") or ()),
        tests=tuple(tests),
    )


def check_completed_milestones_have_passing_tests(
    catalog: MilestoneCatalog, report: OutcomeReport
) -> list[str]:
    """Every Requirement of a DONE milestone must have a test that executed and passed."""
    violations: list[str] = []
    for milestone in catalog.milestones:
        if not milestone.is_complete:
            continue
        for requirement_id in milestone.requirements:
            candidates = report.tests_for(requirement_id)
            if any(test.counts_as_coverage for test in candidates):
                continue
            if not candidates:
                violations.append(
                    f"{milestone.milestone_id} is DONE but {requirement_id} has no "
                    "marked test in the outcome report"
                )
            else:
                observed = ", ".join(f"{test.node_id} -> {test.outcome}" for test in candidates)
                violations.append(
                    f"{milestone.milestone_id} is DONE but no test for {requirement_id} "
                    f"passed; observed: {observed}"
                )
    return violations


def check_gate_profiles_were_enabled(catalog: MilestoneCatalog, report: OutcomeReport) -> list[str]:
    """A DONE milestone must have been validated under the gates it declares it needs."""
    return [
        f"{milestone.milestone_id} is DONE and declares gate_profile "
        f"{sorted(milestone.gate_profile)} but the report was produced with "
        f"{sorted(report.enabled_gates)} enabled"
        for milestone in catalog.milestones
        if milestone.is_complete and not set(milestone.gate_profile) <= set(report.enabled_gates)
    ]


# ---------------------------------------------------------------------------
# GATE-severity spec issues must not be open when the milestone they gate is DONE
# ---------------------------------------------------------------------------

_FIELD_RE = re.compile(r"^(Severity|Status|Blocks gate):\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class SpecIssue:
    issue_id: str
    severity: str
    status: str
    blocks_gate: str | None
    path: Path

    @property
    def is_open(self) -> bool:
        return self.status.upper() == "OPEN"

    @property
    def is_gate(self) -> bool:
        return self.severity.upper() == "GATE"


def load_spec_issues(issues_dir: Path) -> tuple[SpecIssue, ...]:
    """Parse the machine-readable header fields of each spec issue document."""
    issues: list[SpecIssue] = []
    for path in sorted(issues_dir.glob("SPEC-ISSUE-*.md")):
        fields = dict(_FIELD_RE.findall(path.read_text(encoding="utf-8")))
        issue_id = path.name.split("-")[0:3]
        issues.append(
            SpecIssue(
                issue_id="-".join(issue_id),
                severity=fields.get("Severity", ""),
                status=fields.get("Status", ""),
                blocks_gate=fields.get("Blocks gate") or None,
                path=path,
            )
        )
    return tuple(issues)


def check_no_open_gate_issues_for_completed_milestones(
    catalog: MilestoneCatalog, issues: tuple[SpecIssue, ...]
) -> list[str]:
    """docs/spec_issues/README.md says GATE issues MUST be resolved before their gate.

    Without this, "GATE severity" is documentation: a milestone could be marked DONE with two
    open GATE issues against it and CI would stay green.
    """
    violations: list[str] = []
    for issue in issues:
        if not (issue.is_open and issue.is_gate and issue.blocks_gate):
            continue
        for milestone_id in (part.strip() for part in issue.blocks_gate.split(",")):
            try:
                milestone = catalog.get(milestone_id)
            except KeyError:
                violations.append(
                    f"{issue.issue_id} declares 'Blocks gate: {milestone_id}' "
                    "but no such milestone exists"
                )
                continue
            if milestone.is_complete:
                violations.append(
                    f"{milestone_id} is DONE but {issue.issue_id} is an OPEN GATE issue "
                    f"against it ({issue.path.name})"
                )
    return violations


def check_spec_issue_headers_are_parseable(
    issues: tuple[SpecIssue, ...],
) -> list[str]:
    """An unparseable header would silently disable the GATE check above."""
    violations: list[str] = []
    for issue in issues:
        if not issue.severity:
            violations.append(f"{issue.path.name} has no machine-readable 'Severity:' field")
        elif issue.severity.upper() not in {"BLOCKING", "GATE", "EDITORIAL"}:
            violations.append(
                f"{issue.path.name} has unknown Severity {issue.severity!r}; "
                "expected BLOCKING, GATE or EDITORIAL"
            )
        if not issue.status:
            violations.append(f"{issue.path.name} has no machine-readable 'Status:' field")
        elif issue.status.upper() not in {"OPEN", "RESOLVED", "WITHDRAWN"}:
            violations.append(
                f"{issue.path.name} has unknown Status {issue.status!r}; "
                "expected OPEN, RESOLVED or WITHDRAWN"
            )
        if issue.is_gate and not issue.blocks_gate:
            violations.append(
                f"{issue.path.name} is GATE severity but declares no 'Blocks gate:' "
                "milestone, so nothing enforces it"
            )
    return violations
