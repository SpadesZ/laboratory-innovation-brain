"""Negative tests: every spec-conformance guard must be able to fail.

Asserting a guard against correct data proves the data is correct. It proves nothing about
whether the guard has teeth. A check that returns ``[]`` unconditionally passes every
positive test in this suite while constraining nothing.

The P1 review caught two such guards -- a duplicate `EXT-001` was silently collapsed before
uniqueness was counted, and a marker on a function pytest never collects counted as coverage.
Both had passing positive tests.

So each guard gets a fixture that violates exactly one rule, and the guard is required to
report it. These run in CI on every commit, unlike the earlier approach of editing the
repository by hand and reverting, which left no durable evidence and could not be re-run.

Deliberately unmarked with requirement/spec_test markers: these test the *harness*, not a
Requirement, and claiming a Requirement ID here would inflate the traceability matrix.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from lab_brain.spec import conformance, load_spec
from lab_brain.spec.markers import (
    collect_marked_tests,
    rejected_markers,
)
from lab_brain.spec.parser import SpecParseError, parse_requirements, spec_path
from lab_brain.spec.registry import RegistryError, load_milestones, load_registry

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def spec_text() -> str:
    return spec_path().read_text(encoding="utf-8")


def _write_registry(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(
        'schema_version: 1\nspec_version: "3.3"\nnormative_statements:\n' + body,
        encoding="utf-8",
    )
    return path


def _write_milestones(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "milestones.yaml"
    path.write_text("schema_version: 1\nmilestones:\n" + body, encoding="utf-8")
    return path


def _write_test_module(tmp_path: Path, name: str, source: str) -> Path:
    root = tmp_path / "tests"
    root.mkdir(exist_ok=True)
    (root / name).write_text(textwrap.dedent(source), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Parser-level guards
# ---------------------------------------------------------------------------


def test_ext_001_declared_in_both_sections_is_rejected(spec_text):
    """§25.3 states EXT-001 is deliberately not repeated there (51 rows + EXT-001 = 52).

    Regression test for the P1 review finding: this used to be a plain dict assignment, so a
    duplicate was overwritten and `len(ids) == len(set(ids))` still passed. The duplicate was
    collapsed before it could be counted.
    """
    injected = spec_text.replace(
        "| SYS-001 | Core scientific state path MUST be",
        "| EXT-001 | Duplicate injected by test. |\n"
        "| SYS-001 | Core scientific state path MUST be",
        1,
    )
    assert injected != spec_text, "injection point not found; fixture needs updating"

    with pytest.raises(SpecParseError, match=re.escape("declared both in §25.3 and in §24.5")):
        parse_requirements(injected)


def test_missing_ext_001_declaration_is_rejected(spec_text):
    injected = spec_text.replace("**EXT-001**", "**EXT-999**", 1)
    with pytest.raises(SpecParseError, match="EXT-001 declaration not found"):
        parse_requirements(injected)


def test_requirement_count_drift_is_reported(spec_text, tmp_path):
    """The spec's self-asserted "52 requirements" must agree with its own tables."""
    path = tmp_path / "SAI_3.3.md"
    path.write_text(
        spec_text.replace("**52 requirements", "**51 requirements"), encoding="utf-8"
    )
    drifted = load_spec(path)
    assert conformance.check_declared_invariant(drifted) != []


# ---------------------------------------------------------------------------
# Marker collectability guards
# ---------------------------------------------------------------------------


def test_marker_on_non_test_function_is_not_counted_as_coverage(tmp_path):
    """The P1 review's second blocker: a marked helper pytest never runs.

    Two things must hold. The helper must not appear as coverage, and it must be reported --
    silently dropping it would let someone believe they had marked a test.
    """
    root = _write_test_module(
        tmp_path,
        "test_probe.py",
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def helper_that_never_runs():
            pass
        """,
    )
    assert collect_marked_tests(root) == ()
    rejected = rejected_markers(root)
    assert len(rejected) == 1
    assert rejected[0].name == "helper_that_never_runs"
    assert conformance.check_no_markers_on_uncollected_functions(rejected) != []


def test_marker_on_non_test_class_method_is_not_counted_as_coverage(tmp_path):
    """pytest only collects methods of ``Test*`` classes."""
    root = _write_test_module(
        tmp_path,
        "test_probe.py",
        """
        import pytest

        class Helper:
            @pytest.mark.requirement("ART-001")
            @pytest.mark.spec_test("T-ART-001")
            def test_looks_real(self):
                pass
        """,
    )
    assert collect_marked_tests(root) == ()
    assert conformance.check_no_markers_on_uncollected_functions(rejected_markers(root)) != []


def test_marker_on_class_with_init_is_not_counted_as_coverage(tmp_path):
    """pytest skips ``Test*`` classes that define ``__init__``."""
    root = _write_test_module(
        tmp_path,
        "test_probe.py",
        """
        import pytest

        class TestWithInit:
            def __init__(self):
                pass

            @pytest.mark.requirement("ART-001")
            @pytest.mark.spec_test("T-ART-001")
            def test_looks_real(self):
                pass
        """,
    )
    assert collect_marked_tests(root) == ()
    assert conformance.check_no_markers_on_uncollected_functions(rejected_markers(root)) != []


def test_marker_on_real_test_in_test_class_is_counted(tmp_path):
    """The positive side: a genuinely collectable test must still be recognised."""
    root = _write_test_module(
        tmp_path,
        "test_probe.py",
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        class TestArtifact:
            @pytest.mark.spec_test("T-ART-001")
            def test_real(self):
                pass
        """,
    )
    collected = collect_marked_tests(root)
    assert len(collected) == 1
    assert collected[0].requirement_ids == ("ART-001",)
    assert collected[0].test_ids == ("T-ART-001",)
    assert collected[0].node_id == "test_probe.py::TestArtifact::test_real"
    assert rejected_markers(root) == ()


def test_module_not_matching_test_glob_is_ignored(tmp_path):
    root = _write_test_module(
        tmp_path,
        "helpers.py",
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_in_non_test_module():
            pass
        """,
    )
    assert collect_marked_tests(root) == ()
    assert rejected_markers(root) == ()


# ---------------------------------------------------------------------------
# Traceability guards
# ---------------------------------------------------------------------------


def _marked(tmp_path: Path, source: str):
    return collect_marked_tests(_write_test_module(tmp_path, "test_probe.py", source))


def test_unknown_requirement_id_in_marker_is_reported(tmp_path):
    tests = _marked(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ZZZ-999")
        @pytest.mark.spec_test("T-ART-001")
        def test_probe():
            pass
        """,
    )
    assert conformance.check_markers_reference_known_requirements(load_spec(), tests) != []


def test_unknown_test_id_in_marker_is_reported(tmp_path):
    tests = _marked(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-NOT-A-REAL-TEST")
        def test_probe():
            pass
        """,
    )
    assert conformance.check_markers_reference_known_tests(load_spec(), tests) != []


def test_marker_pair_absent_from_matrix_is_reported(tmp_path):
    tests = _marked(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-SYS-001")
        def test_probe():
            pass
        """,
    )
    assert conformance.check_marker_pairs_in_matrix(load_spec(), tests) != []


def test_half_a_marker_pair_is_reported(tmp_path):
    tests = _marked(
        tmp_path,
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        def test_probe():
            pass
        """,
    )
    assert conformance.check_markers_complete(tests) != []


# ---------------------------------------------------------------------------
# Registry guards
# ---------------------------------------------------------------------------

_VALID_ENTRY = """\
  - key: probe.valid
    section: "6.1"
    level: MUST
    requirement_id: ART-001
    tests: [T-ART-001]
"""


def test_duplicate_statement_key_is_reported(tmp_path):
    registry = load_registry(_write_registry(tmp_path, _VALID_ENTRY + _VALID_ENTRY))
    assert conformance.check_registry_keys_unique(registry) != []


def test_unknown_requirement_in_registry_is_reported(tmp_path):
    registry = load_registry(
        _write_registry(
            tmp_path,
            """\
  - key: probe.unknown_requirement
    section: "6.1"
    level: MUST
    requirement_id: ZZZ-999
    tests: [T-ART-001]
""",
        )
    )
    assert conformance.check_registry_requirements_resolvable(registry, load_spec()) != []


def test_unknown_test_in_registry_is_reported(tmp_path):
    registry = load_registry(
        _write_registry(
            tmp_path,
            """\
  - key: probe.unknown_test
    section: "6.1"
    level: MUST
    requirement_id: ART-001
    tests: [T-DOES-NOT-EXIST]
""",
        )
    )
    assert conformance.check_registry_tests_known(registry, load_spec()) != []


def test_entry_with_no_test_and_no_deferral_is_reported(tmp_path):
    registry = load_registry(
        _write_registry(
            tmp_path,
            """\
  - key: probe.no_test
    section: "6.1"
    level: MUST
    requirement_id: ART-001
    tests: []
""",
        )
    )
    assert conformance.check_registry_test_or_deferral(registry) != []


def test_deferral_without_review_date_is_reported(tmp_path):
    registry = load_registry(
        _write_registry(
            tmp_path,
            """\
  - key: probe.no_review_date
    section: "6.1"
    level: MUST
    requirement_id: ART-001
    tests: []
    deferred_rationale: deferred for the purposes of this test
""",
        )
    )
    assert conformance.check_registry_deferral_review_date(registry) != []


def test_test_not_mapped_to_that_requirement_is_reported(tmp_path):
    registry = load_registry(
        _write_registry(
            tmp_path,
            """\
  - key: probe.wrong_mapping
    section: "6.1"
    level: MUST
    requirement_id: ART-001
    tests: [T-SYS-001]
""",
        )
    )
    assert conformance.check_registry_matches_matrix(registry, load_spec()) != []


def test_non_normative_level_is_rejected_at_load(tmp_path):
    """Vocabulary is validated eagerly, so an invalid level cannot reach a check."""
    with pytest.raises(RegistryError, match="level"):
        load_registry(
            _write_registry(
                tmp_path,
                """\
  - key: probe.bad_level
    section: "6.1"
    level: SHALL
    requirement_id: ART-001
    tests: [T-ART-001]
""",
            )
        )


def test_unregistered_requirement_is_reported(tmp_path):
    registry = load_registry(_write_registry(tmp_path, _VALID_ENTRY))
    missing = conformance.check_every_requirement_registered(registry, load_spec())
    assert len(missing) == len(load_spec().requirements) - 1


def test_cited_spec_issue_that_does_not_exist_is_reported(tmp_path):
    registry = load_registry(
        _write_registry(
            tmp_path,
            """\
  - key: probe.dangling_issue
    section: "6.1"
    level: MUST
    requirement_id: ART-001
    tests: [T-ART-001]
    spec_issue: SPEC-ISSUE-999
""",
        )
    )
    assert conformance.check_registry_spec_issues_exist(registry, tmp_path) != []


# ---------------------------------------------------------------------------
# Milestone guards
# ---------------------------------------------------------------------------

_M0A = """\
  - id: M0a
    name: Probe
    status: {status}
    exit_gate: probe
    requirements: [{requirements}]
"""


def test_unallocated_requirement_is_reported(tmp_path):
    catalog = load_milestones(
        _write_milestones(tmp_path, _M0A.format(status="IN_PROGRESS", requirements="ART-001"))
    )
    assert conformance.check_milestones_partition_requirements(load_spec(), catalog) != []


def test_requirement_allocated_twice_is_reported(tmp_path):
    catalog = load_milestones(
        _write_milestones(
            tmp_path,
            _M0A.format(status="IN_PROGRESS", requirements="ART-001, ART-001"),
        )
    )
    assert any(
        "more than one milestone" in violation
        for violation in conformance.check_milestones_partition_requirements(
            load_spec(), catalog
        )
    )


def test_unknown_requirement_in_milestones_is_reported(tmp_path):
    catalog = load_milestones(
        _write_milestones(tmp_path, _M0A.format(status="IN_PROGRESS", requirements="ZZZ-999"))
    )
    assert any(
        "undeclared requirement" in violation
        for violation in conformance.check_milestones_partition_requirements(
            load_spec(), catalog
        )
    )


def test_milestone_marked_done_without_a_collected_test_is_reported(tmp_path):
    """The DONE ratchet must fail on a requirement whose only "test" is uncollectable."""
    catalog = load_milestones(
        _write_milestones(tmp_path, _M0A.format(status="DONE", requirements="ART-001"))
    )
    root = _write_test_module(
        tmp_path,
        "test_probe.py",
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def helper_not_collected():
            pass
        """,
    )
    assert (
        conformance.check_completed_milestones_have_tests(catalog, collect_marked_tests(root))
        != []
    )


def test_milestone_marked_done_with_a_real_test_passes(tmp_path):
    catalog = load_milestones(
        _write_milestones(tmp_path, _M0A.format(status="DONE", requirements="ART-001"))
    )
    root = _write_test_module(
        tmp_path,
        "test_probe.py",
        """
        import pytest

        @pytest.mark.requirement("ART-001")
        @pytest.mark.spec_test("T-ART-001")
        def test_real():
            pass
        """,
    )
    assert (
        conformance.check_completed_milestones_have_tests(catalog, collect_marked_tests(root))
        == []
    )
