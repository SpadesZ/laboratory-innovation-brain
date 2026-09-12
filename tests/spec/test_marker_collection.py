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

import subprocess
import sys

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


def test_static_collector_finds_the_known_marked_tests():
    """Anchor the model against this repository's own traceability tests."""
    node_ids = {test.node_id for test in collect_marked_tests()}
    for expected in (
        "spec/test_requirement_traceability.py::test_requirement_ids_are_unique",
        "spec/test_normative_statement_coverage.py::test_statement_keys_are_unique",
    ):
        assert expected in node_ids, f"static collector missed {expected}"
