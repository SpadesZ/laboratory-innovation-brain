"""Cross-check the static collector against real pytest collection.

``markers.py`` reproduces pytest's collection rules with ``ast`` so that coverage cannot be
claimed by a decorator on a function pytest never runs. But a reimplementation of pytest's
rules is a *model* of pytest, and a model can drift -- from a config change
(``python_functions``, ``python_classes``), a pytest upgrade, or a construct the AST walker
does not understand.

So the model is compared against ``--collect-only`` output. If they disagree, the harness is
wrong and says so, instead of quietly under- or over-counting coverage.

Deliberately unmarked: this validates the harness, not a Requirement.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from lab_brain.spec import collect_marked_tests, repo_root


def _pytest_collected_node_ids() -> frozenset[str]:
    """Node IDs pytest actually collects, normalised and de-parametrised."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "pytest --collect-only failed, so the static collector cannot be "
            f"cross-checked:\n{result.stdout}\n{result.stderr}"
        )
    node_ids: set[str] = set()
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if "::" not in candidate:
            continue
        path, _, rest = candidate.partition("::")
        if not path.endswith(".py"):
            continue
        # Drop parametrisation: test_foo[case-1] -> test_foo
        rest = rest.split("[", 1)[0]
        node_ids.add(f"{path.replace(chr(92), '/')}::{rest}")
    return frozenset(node_ids)


@pytest.fixture(scope="module")
def collected() -> frozenset[str]:
    return _pytest_collected_node_ids()


def test_pytest_collection_is_not_empty(collected):
    """Guard against the cross-check passing because collection returned nothing."""
    assert len(collected) > 20, (
        f"only {len(collected)} node IDs parsed from --collect-only; the output format "
        "likely changed and this cross-check is no longer comparing anything"
    )


def test_every_statically_marked_test_is_collected_by_pytest(collected):
    """A marked test the runner never collects is counted coverage that never executes."""
    missing = sorted(
        f"tests/{test.node_id}"
        for test in collect_marked_tests()
        if f"tests/{test.node_id}" not in collected
    )
    assert not missing, (
        "statically marked tests that pytest does not collect — either the marker sits on "
        f"something that never runs, or markers.py has drifted from pytest: {missing}"
    )


def _pytest_marked_requirements() -> dict[str, frozenset[str]]:
    """What pytest's *own* marker API sees, per node ID.

    Read from the outcome plugin, which uses ``item.iter_markers()``. Run under ``--collect-only``
    into a throwaway report, so the real report is untouched and this is a collection-time fact
    independent of any earlier session.
    """
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "collect.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                f"--requirement-outcomes={report}",
            ],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        if not report.is_file():
            pytest.fail(
                "the outcome plugin wrote no report under --collect-only, so pytest's real marker "
                f"view cannot be read:\n{result.stdout}\n{result.stderr}"
            )
        payload = json.loads(report.read_text(encoding="utf-8"))

    seen: dict[str, set[str]] = {}
    for entry in payload["tests"]:
        node_id = entry["node_id"].replace("\\", "/").split("[", 1)[0]
        seen.setdefault(node_id, set()).update(entry["requirement_ids"])
    return {node_id: frozenset(ids) for node_id, ids in seen.items()}


def test_every_test_pytest_considers_marked_is_in_the_static_model():
    """The direction this cross-check was missing -- and it was hiding a real bug.

    The other direction asks "does every marker I found sit on something pytest runs?". It cannot
    see a marker pytest *applies* that the AST walker never noticed, and that is exactly what
    happened: module-level ``pytestmark = [...]`` is honoured by pytest and was invisible to
    ``markers.py``, so ``tests/contract/test_critique_gate.py`` discharged SRC-002 while the
    traceability matrix reported that Requirement as having no test at all.

    Under-reporting is the less alarming direction, but it is still a false statement about
    coverage, and the same blind spot would equally hide over-reporting for any construct the
    walker mis-parses.
    """
    static = {
        f"tests/{test.node_id}": frozenset(test.requirement_ids) for test in collect_marked_tests()
    }
    real = _pytest_marked_requirements()
    assert real, "pytest reported no marked tests; the cross-check is comparing nothing"

    missing = sorted(node_id for node_id in real if node_id not in static)
    assert not missing, (
        "pytest applies traceability markers to these tests but markers.py does not see them, "
        f"so the matrix under-reports coverage: {missing}"
    )

    disagreed = sorted(
        f"{node_id}: pytest={sorted(real[node_id])} static={sorted(static[node_id])}"
        for node_id in real
        if node_id in static and real[node_id] != static[node_id]
    )
    assert not disagreed, f"requirement IDs differ between pytest and markers.py: {disagreed}"


def test_module_level_pytestmark_is_understood():
    """Anchor the construct that exposed the gap, so a refactor cannot quietly drop support."""
    by_module: dict[str, set[str]] = {}
    for test in collect_marked_tests():
        by_module.setdefault(test.module, set()).update(test.requirement_ids)
    assert "contract/test_critique_gate.py" in by_module, (
        "the pytestmark-marked module is not in the static model"
    )
    assert by_module["contract/test_critique_gate.py"] == {"SRC-002"}


def test_static_collector_finds_the_known_marked_tests():
    """Anchor the model against this repository's own traceability tests."""
    node_ids = {test.node_id for test in collect_marked_tests()}
    for expected in (
        "spec/test_requirement_traceability.py::test_requirement_ids_are_unique",
        "spec/test_normative_statement_coverage.py::test_statement_keys_are_unique",
    ):
        assert expected in node_ids, f"static collector missed {expected}"
