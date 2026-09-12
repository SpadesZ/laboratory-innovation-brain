"""pytest plugin recording the real outcome of every traceability-marked test.

WHY THIS EXISTS

Coverage was previously counted from *collection*: a test pytest would collect counted as
evidence that a Requirement was discharged. Collection is not execution. All of these are
collected, none of them run an assertion, and all of them left CI green:

    @pytest.mark.skip(reason="not ready")      # SKIPPED at setup
    @pytest.mark.xfail(run=False)              # body never invoked
    class-level or module-level skip           # same, one level up
    @pytest.mark.postgres                      # our own conftest skips it by default

The last one is the sharpest: ``tests/conftest.py`` deliberately skips backend-gated tests so
a bare ``pytest`` stays green without PostgreSQL (AGT-007). That same mechanism silently
turned "deselected" into "covered".

So coverage is counted from outcomes reported by pytest itself. Markers are read through
pytest's own marker API rather than the AST model in ``markers.py``, which makes this check
independent of that model being right.

USAGE

    pytest --requirement-outcomes=var/requirement_outcomes.json
    python scripts/check_requirement_coverage.py

The report is a build artifact (gitignored). ``check_requirement_coverage.py`` fails closed if
it is missing, so deleting it is not a way past the gate.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pytest

REPORT_SCHEMA_VERSION = 1

#: Environment variables that enable a backend-dependent test profile. Mirrors
#: tests/conftest.py; a milestone declaring one of these in its gate_profile cannot be
#: validated by a run that did not enable it.
GATE_ENV_VARS: dict[str, str] = {
    "postgres": "LAB_BRAIN_TEST_POSTGRES",
    "lumerical": "LAB_BRAIN_TEST_LUMERICAL",
    "network": "LAB_BRAIN_TEST_NETWORK",
}

_OPTION = "--requirement-outcomes"
_ENV_OVERRIDE = "LAB_BRAIN_REQUIREMENT_OUTCOMES"


def enabled_gates() -> list[str]:
    return sorted(name for name, var in GATE_ENV_VARS.items() if os.environ.get(var))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        _OPTION,
        action="store",
        default=None,
        metavar="PATH",
        help=(
            "write a requirement-outcome report to PATH; consumed by "
            "scripts/check_requirement_coverage.py"
        ),
    )


class RequirementOutcomeRecorder:
    """Records, per marked test, whether it actually executed and passed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._markers: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        self._outcomes: dict[str, str] = {}

    # -- collection -------------------------------------------------------

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            requirement_ids = tuple(
                value
                for mark in item.iter_markers(name="requirement")
                for value in mark.args
                if isinstance(value, str)
            )
            test_ids = tuple(
                value
                for mark in item.iter_markers(name="spec_test")
                for value in mark.args
                if isinstance(value, str)
            )
            if requirement_ids or test_ids:
                self._markers[item.nodeid] = (requirement_ids, test_ids)

    # -- execution --------------------------------------------------------

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.nodeid not in self._markers:
            return
        current = self._outcomes.get(report.nodeid)

        if report.when == "setup":
            if report.outcome == "skipped":
                # xfail(run=False) surfaces here, not at call: pytest never invokes the body,
                # so the report arrives as a setup-phase skip carrying wasxfail.
                self._outcomes[report.nodeid] = (
                    "xfailed" if hasattr(report, "wasxfail") else "skipped"
                )
            elif report.failed:
                self._outcomes[report.nodeid] = "error"
            return

        if report.when == "call":
            if hasattr(report, "wasxfail"):
                # xfail(run=False) never invokes the body; xpass did run but is declared
                # not-working. Neither is evidence a requirement is discharged.
                self._outcomes[report.nodeid] = "xpassed" if report.passed else "xfailed"
            else:
                self._outcomes[report.nodeid] = report.outcome
            return

        # A teardown failure invalidates an otherwise-passing call.
        if report.when == "teardown" and report.failed and current == "passed":
            self._outcomes[report.nodeid] = "error"

    # -- reporting --------------------------------------------------------

    def build_report(self) -> dict[str, Any]:
        tests: list[dict[str, Any]] = []
        for node_id, (requirement_ids, test_ids) in sorted(self._markers.items()):
            # A marked test that produced no report at all was deselected before setup;
            # that is not coverage either.
            outcome = self._outcomes.get(node_id, "not_run")
            tests.append(
                {
                    "node_id": node_id,
                    "requirement_ids": list(requirement_ids),
                    "test_ids": list(test_ids),
                    "outcome": outcome,
                    "counts_as_coverage": outcome == "passed",
                }
            )
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
            "enabled_gates": enabled_gates(),
            "tests": tests,
        }

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.build_report(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def pytest_configure(config: pytest.Config) -> None:
    target = config.getoption(_OPTION) or os.environ.get(_ENV_OVERRIDE)
    if not target:
        return
    config.pluginmanager.register(
        RequirementOutcomeRecorder(Path(target)), name="lab-brain-requirement-outcomes"
    )
