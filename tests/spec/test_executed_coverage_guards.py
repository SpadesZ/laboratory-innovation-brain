"""Negative tests: a collected-but-not-executed test must never count as coverage.

The P1 review found that the DONE ratchet counted *collected* tests. Collection is not
execution. Every construct below is collected by pytest, runs no assertion, and leaves the
session green -- so under the old ratchet each one could carry a Requirement to DONE:

    @pytest.mark.skip                  SKIPPED at setup
    @pytest.mark.xfail(run=False)      body never invoked
    pytestmark / class-level skip      same, one level up
    @pytest.mark.postgres              tests/conftest.py skips it unless opted in

The last is self-inflicted: the mechanism that keeps a bare `pytest` green without PostgreSQL
(AGT-007) was also converting "deselected" into "covered".

These tests run **real pytest subprocesses** over generated fixture files and read the outcome
report that run produced. Asserting against a hand-built report would only prove the checker
parses JSON; it would not prove pytest reports what the checker assumes.

Deliberately unmarked: this validates the harness, not a Requirement.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from lab_brain.spec.outcomes import (
    OutcomeReport,
    OutcomeReportError,
    RecordedOutcome,
    check_completed_milestones_have_passing_tests,
    check_gate_profiles_were_enabled,
    check_no_open_gate_issues_for_completed_milestones,
    check_spec_issue_headers_are_parseable,
    load_outcome_report,
    load_spec_issues,
)
from lab_brain.spec.registry import load_milestones

_CONFTEST = """\
pytest_plugins = ("lab_brain.spec.outcome_plugin",)
"""


def _run_pytest(
    tmp_path: Path, source: str, *, env_extra: dict[str, str] | None = None
) -> OutcomeReport:
    """Run pytest over a generated test file and return the outcome report it produced.

    The subprocess environment is scrubbed of every ``LAB_BRAIN_TEST_*`` gate before
    ``env_extra`` is applied. Inheriting them made these tests depend on how the *outer* suite
    was invoked: with ``LAB_BRAIN_TEST_POSTGRES=1`` set, the gated-skip fixture stopped being
    skipped and the guard silently stopped guarding. A test of the harness must control its own
    environment, or it is testing the ambient shell.
    """
    project = tmp_path / "sandbox"
    project.mkdir()
    (project / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (project / "test_probe.py").write_text(textwrap.dedent(source), encoding="utf-8")
    (project / "pytest.ini").write_text(
        "[pytest]\n"
        "markers =\n"
        "    requirement(id): Requirement ID\n"
        "    spec_test(id): Test ID\n"
        "    postgres: requires PostgreSQL\n",
        encoding="utf-8",
    )
    report_path = project / "outcomes.json"

    import os

    from lab_brain.spec.outcome_plugin import GATE_ENV_VARS

    env = {
        key: value for key, value in os.environ.items() if key not in set(GATE_ENV_VARS.values())
    }
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--requirement-outcomes={report_path}",
            str(project / "test_probe.py"),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert report_path.is_file(), "plugin did not write an outcome report"
    return load_outcome_report(report_path)


def _single(report: OutcomeReport) -> RecordedOutcome:
    assert len(report.tests) == 1, f"expected one marked test, got {report.tests}"
    return report.tests[0]


# ---------------------------------------------------------------------------
# The four bypasses the review named
# ---------------------------------------------------------------------------


def test_skipped_test_does_not_count_as_coverage(tmp_path):
    """The review's exact fixture: skipped, body asserts False, session still green."""
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.skip(reason="not ready")
        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert False
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "skipped"
    assert not outcome.counts_as_coverage
    assert "ART-001" not in report.passing_requirement_ids()


def test_xfail_without_run_does_not_count_as_coverage(tmp_path):
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.xfail(run=False, reason="known broken")
        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert False
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "xfailed"
    assert not outcome.counts_as_coverage


def test_module_level_skip_does_not_count_as_coverage(tmp_path):
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        pytestmark = pytest.mark.skip(reason="module not ready")

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert False
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "skipped"
    assert not outcome.counts_as_coverage


def test_class_level_skip_does_not_count_as_coverage(tmp_path):
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.skip(reason="class not ready")
        @pytest.mark.requirement("ART-001")
        class TestArtifact:
            @pytest.mark.spec_test("T-ART-001")
            def test_artifact(self):
                assert False
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "skipped"
    assert not outcome.counts_as_coverage


def test_environment_gated_test_skipped_by_conftest_does_not_count(tmp_path):
    """Our own AGT-007 skip mechanism must not manufacture coverage."""
    report = _run_pytest(
        tmp_path,
        """
        import os
        import pytest

        # Mirrors tests/conftest.py: skip unless the backend is opted in.
        pytestmark = pytest.mark.skipif(
            not os.environ.get("LAB_BRAIN_TEST_POSTGRES"),
            reason="requires postgres",
        )

        @pytest.mark.postgres
        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert True
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "skipped"
    assert not outcome.counts_as_coverage
    assert report.enabled_gates == frozenset()


# ---------------------------------------------------------------------------
# Failure modes adjacent to the four, and the positive control
# ---------------------------------------------------------------------------


def test_failing_test_does_not_count_as_coverage(tmp_path):
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert False
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "failed"
    assert not outcome.counts_as_coverage


def test_xpassed_test_does_not_count_as_coverage(tmp_path):
    """An xpass executed and passed, but is declared not-working. Not evidence."""
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.xfail(reason="expected broken")
        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert True
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "xpassed"
    assert not outcome.counts_as_coverage


def test_error_in_fixture_setup_does_not_count_as_coverage(tmp_path):
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("setup blew up")

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact(broken):
            assert True
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "error"
    assert not outcome.counts_as_coverage


def test_a_genuinely_passing_test_does_count_as_coverage(tmp_path):
    """Positive control: without this the suite would pass by rejecting everything."""
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert True
        """,
    )
    outcome = _single(report)
    assert outcome.outcome == "passed"
    assert outcome.counts_as_coverage
    assert "ART-001" in report.passing_requirement_ids()


def test_enabled_gates_are_recorded_when_opted_in(tmp_path):
    report = _run_pytest(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_artifact():
            assert True
        """,
        env_extra={"LAB_BRAIN_TEST_POSTGRES": "1"},
    )
    assert "postgres" in report.enabled_gates


# ---------------------------------------------------------------------------
# The ratchet itself
# ---------------------------------------------------------------------------


def _milestones(tmp_path: Path, *, status: str, gate_profile: str = "[]") -> Path:
    path = tmp_path / "milestones.yaml"
    path.write_text(
        "schema_version: 1\n"
        "milestones:\n"
        "  - id: M0a\n"
        "    name: Probe\n"
        f"    status: {status}\n"
        "    exit_gate: probe\n"
        f"    gate_profile: {gate_profile}\n"
        "    requirements: [ART-001]\n",
        encoding="utf-8",
    )
    return path


def _report(tmp_path: Path, outcome: str, gates: list[str]) -> OutcomeReport:
    path = tmp_path / "outcomes.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-12T00:00:00+00:00",
                "enabled_gates": gates,
                "tests": [
                    {
                        "node_id": "tests/test_probe.py::test_artifact",
                        "requirement_ids": ["ART-001"],
                        "test_ids": ["T-ART-001"],
                        "outcome": outcome,
                        "counts_as_coverage": outcome == "passed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return load_outcome_report(path)


@pytest.mark.parametrize("outcome", ["skipped", "xfailed", "xpassed", "failed", "error", "not_run"])
def test_done_milestone_rejects_every_non_passing_outcome(tmp_path, outcome):
    catalog = load_milestones(_milestones(tmp_path, status="DONE"))
    report = _report(tmp_path, outcome, [])
    assert check_completed_milestones_have_passing_tests(catalog, report) != []


def test_done_milestone_accepts_a_passing_outcome(tmp_path):
    catalog = load_milestones(_milestones(tmp_path, status="DONE"))
    report = _report(tmp_path, "passed", [])
    assert check_completed_milestones_have_passing_tests(catalog, report) == []


def test_in_progress_milestone_is_not_ratcheted(tmp_path):
    """The gate binds at DONE, not before -- otherwise no work could ever start."""
    catalog = load_milestones(_milestones(tmp_path, status="IN_PROGRESS"))
    report = _report(tmp_path, "skipped", [])
    assert check_completed_milestones_have_passing_tests(catalog, report) == []


def test_done_milestone_requires_its_declared_gate_profile(tmp_path):
    """A postgres-gated milestone cannot be signed off by a run that skipped postgres."""
    catalog = load_milestones(_milestones(tmp_path, status="DONE", gate_profile="[postgres]"))
    assert check_gate_profiles_were_enabled(catalog, _report(tmp_path, "passed", [])) != []
    assert (
        check_gate_profiles_were_enabled(catalog, _report(tmp_path, "passed", ["postgres"])) == []
    )


def test_missing_outcome_report_fails_closed(tmp_path):
    """Deleting the report must not be a way past the gate."""
    with pytest.raises(OutcomeReportError, match="not found"):
        load_outcome_report(tmp_path / "absent.json")


def test_outcome_report_with_wrong_schema_version_is_rejected(tmp_path):
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps({"schema_version": 99, "tests": []}), encoding="utf-8")
    with pytest.raises(OutcomeReportError, match="schema_version"):
        load_outcome_report(path)


# ---------------------------------------------------------------------------
# GATE spec issues must block the milestone they name
# ---------------------------------------------------------------------------


def _issue(tmp_path: Path, name: str, body: str) -> Path:
    issues = tmp_path / "spec_issues"
    issues.mkdir(exist_ok=True)
    (issues / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return issues


def test_open_gate_issue_blocks_a_done_milestone(tmp_path):
    catalog = load_milestones(_milestones(tmp_path, status="DONE"))
    issues = load_spec_issues(
        _issue(
            tmp_path,
            "SPEC-ISSUE-001-probe.md",
            """
            # SPEC-ISSUE-001: probe

            Severity: GATE
            Status: OPEN
            Blocks gate: M0a
            """,
        )
    )
    assert check_no_open_gate_issues_for_completed_milestones(catalog, issues) != []


def test_resolved_gate_issue_does_not_block(tmp_path):
    catalog = load_milestones(_milestones(tmp_path, status="DONE"))
    issues = load_spec_issues(
        _issue(
            tmp_path,
            "SPEC-ISSUE-001-probe.md",
            """
            # SPEC-ISSUE-001: probe

            Severity: GATE
            Status: RESOLVED
            Blocks gate: M0a
            """,
        )
    )
    assert check_no_open_gate_issues_for_completed_milestones(catalog, issues) == []


def test_editorial_issue_does_not_block(tmp_path):
    catalog = load_milestones(_milestones(tmp_path, status="DONE"))
    issues = load_spec_issues(
        _issue(
            tmp_path,
            "SPEC-ISSUE-002-probe.md",
            """
            # SPEC-ISSUE-002: probe

            Severity: EDITORIAL
            Status: OPEN
            """,
        )
    )
    assert check_no_open_gate_issues_for_completed_milestones(catalog, issues) == []


def test_gate_issue_without_blocks_gate_is_reported(tmp_path):
    """A GATE issue naming no milestone enforces nothing, so the header check catches it."""
    issues = load_spec_issues(
        _issue(
            tmp_path,
            "SPEC-ISSUE-004-probe.md",
            """
            # SPEC-ISSUE-004: probe

            Severity: GATE
            Status: OPEN
            """,
        )
    )
    assert check_spec_issue_headers_are_parseable(issues) != []


def test_unparseable_issue_header_is_reported(tmp_path):
    """An unreadable header would silently disable the GATE check."""
    issues = load_spec_issues(
        _issue(
            tmp_path,
            "SPEC-ISSUE-005-probe.md",
            """
            # SPEC-ISSUE-005: probe

            Severity: **GATE** — prose after the value
            Status: probably open
            """,
        )
    )
    assert check_spec_issue_headers_are_parseable(issues) != []


def test_gate_issue_naming_an_unknown_milestone_is_reported(tmp_path):
    catalog = load_milestones(_milestones(tmp_path, status="DONE"))
    issues = load_spec_issues(
        _issue(
            tmp_path,
            "SPEC-ISSUE-006-probe.md",
            """
            # SPEC-ISSUE-006: probe

            Severity: GATE
            Status: OPEN
            Blocks gate: M99
            """,
        )
    )
    assert any(
        "no such milestone" in violation
        for violation in check_no_open_gate_issues_for_completed_milestones(catalog, issues)
    )


# ---------------------------------------------------------------------------
# This repository's own state
# ---------------------------------------------------------------------------


def test_this_repository_has_parseable_spec_issue_headers():
    from lab_brain.spec import spec_issues_dir

    issues = load_spec_issues(spec_issues_dir())
    assert len(issues) == 3, f"expected 3 spec issues, found {[i.issue_id for i in issues]}"
    assert check_spec_issue_headers_are_parseable(issues) == []
