"""Post-test gate: a DONE milestone must have tests that executed and passed.

Runs *after* pytest, because the question it answers cannot be answered during the session --
a test asserting "every DONE requirement passed" would have to know the outcome of tests that
have not run yet.

    pytest --requirement-outcomes=var/requirement_outcomes.json
    python scripts/check_requirement_coverage.py

Checks:
  1. every Requirement of a DONE milestone has >= 1 test with outcome `passed`
  2. the run enabled every gate in each DONE milestone's `gate_profile`
  3. no OPEN GATE spec issue names a milestone that is already DONE
  4. every spec issue header is machine-readable (an unparseable one disables check 3)

Fails closed: a missing report is a violation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_brain.spec import load_milestones, spec_issues_dir
from lab_brain.spec.outcomes import (
    OutcomeReportError,
    check_completed_milestones_have_passing_tests,
    check_gate_profiles_were_enabled,
    check_no_open_gate_issues_for_completed_milestones,
    check_spec_issue_headers_are_parseable,
    default_report_path,
    load_outcome_report,
    load_spec_issues,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"outcome report path (default: {default_report_path()})",
    )
    args = parser.parse_args()

    catalog = load_milestones()
    issues = load_spec_issues(spec_issues_dir())

    try:
        report = load_outcome_report(args.report)
    except OutcomeReportError as exc:
        print(f"FAIL  {exc}")
        return 1

    # A partial report cannot answer this question, and answering it anyway produces a message that
    # actively misleads: "M0a is DONE but ART-001 has no marked test in the outcome report" reads as
    # "that test does not exist" when the truth is "this run did not execute it". CI hit exactly
    # that on the commit which first marked a milestone DONE -- the spec-conformance job runs only
    # `pytest tests/spec`, and this check had been vacuously passing until then because no milestone
    # was DONE. Same failure mode as `update_status.py` reading a spec-only report, and it gets the
    # same answer: refuse, rather than state a confident wrong one.
    scope = report.collection_directories()
    expected = {
        entry.name
        for entry in (Path(__file__).resolve().parents[1] / "tests").iterdir()
        if entry.is_dir() and entry.name != "__pycache__" and any(entry.glob("test_*.py"))
    }
    if scope and not expected <= scope:
        print(
            f"FAIL  the outcome report covers only {', '.join(sorted(scope))}, so it cannot show "
            "whether a DONE milestone's tests passed."
        )
        print(f"      Missing: {', '.join(sorted(expected - scope))}")
        print("      Run the whole suite first, under the gate profile the milestone declares:")
        print("        LAB_BRAIN_TEST_POSTGRES=1 pytest")
        return 1

    checks = {
        "DONE milestones have passing tests": check_completed_milestones_have_passing_tests(
            catalog, report
        ),
        "DONE milestones ran their declared gate profile": check_gate_profiles_were_enabled(
            catalog, report
        ),
        "no OPEN GATE spec issue blocks a DONE milestone": (
            check_no_open_gate_issues_for_completed_milestones(catalog, issues)
        ),
        "spec issue headers are machine-readable": check_spec_issue_headers_are_parseable(issues),
    }

    print(f"outcome report : {report.path}")
    print(f"generated at   : {report.generated_at}")
    print(f"enabled gates  : {sorted(report.enabled_gates) or '(none)'}")
    print(f"marked tests   : {len(report.tests)}")

    counted = sorted(report.passing_requirement_ids())
    print(f"requirements with a passing test: {len(counted)}")

    not_counted = sorted(
        f"{test.node_id} -> {test.outcome}" for test in report.tests if not test.counts_as_coverage
    )
    if not_counted:
        print(f"\nmarked tests NOT counted as coverage ({len(not_counted)}):")
        for line in not_counted:
            print(f"  {line}")

    failed = False
    print()
    for label, violations in checks.items():
        if violations:
            failed = True
            print(f"FAIL  {label}")
            for violation in violations:
                print(f"        {violation}")
        else:
            print(f"ok    {label}")

    active = [m.milestone_id for m in catalog.milestones if m.status == "IN_PROGRESS"]
    done = [m.milestone_id for m in catalog.milestones if m.is_complete]
    print(f"\nmilestones DONE: {done or '(none)'}  IN_PROGRESS: {active or '(none)'}")
    if not done:
        print(
            "No milestone is DONE yet, so the coverage ratchet has nothing to enforce. "
            "It becomes binding the moment one is."
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
