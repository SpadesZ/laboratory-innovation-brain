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
import hashlib
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
    """Records, per marked test, whether it actually executed and passed.

    It also records the session's whole collection, which is what lets
    ``scripts/update_status.py`` derive IMPLEMENTATION_STATUS.md's test inventory rather than trust
    a hand-written table. That table claimed "288 passed with postgres; 237 + 51 skipped without"
    while the suite had grown to 307, and nothing read it -- so AGT-003's "docs agree with
    implementation state" was passing CI on a number nobody recomputed.

    The per-file figures recorded here are **collected** counts, deliberately. Collection is
    profile-independent: the postgres and backend-free profiles collect the same tests and differ
    only in how many they skip. That makes the derived table checkable in every CI job, and the
    "how many execute without a backend" figure comes from counting gate markers rather than from
    comparing two separate runs.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._markers: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        self._outcomes: dict[str, str] = {}
        self._collected: dict[str, tuple[str, ...]] = {}

    # -- collection -------------------------------------------------------

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            # Which backend gates this test needs, so "runs without a backend" is derived from the
            # markers instead of asserted by whoever last edited the table.
            self._collected[item.nodeid] = tuple(
                sorted(gate for gate in GATE_ENV_VARS if item.get_closest_marker(gate) is not None)
            )
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
            "collection": self.build_collection(),
            "tests": tests,
        }

    def build_collection(self) -> dict[str, Any]:
        """The session's collection, grouped by test file.

        ``node_digest`` covers the sorted node ids. ``update_status.py --check`` re-collects and
        compares it, so a report left over from an earlier run cannot validate the current table --
        without that, "the doc matches the report" would be true while both were stale.
        """
        by_file: dict[str, dict[str, int]] = {}
        for node_id, gates in sorted(self._collected.items()):
            path = node_id.split("::", 1)[0].replace("\\", "/")
            entry = by_file.setdefault(path, {"collected": 0, "gated": 0})
            entry["collected"] += 1
            if gates:
                entry["gated"] += 1
        digest = hashlib.sha256("\n".join(sorted(self._collected)).encode("utf-8")).hexdigest()
        return {
            "collected": len(self._collected),
            "gated": sum(1 for gates in self._collected.values() if gates),
            "node_digest": digest[:16],
            "by_file": by_file,
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
