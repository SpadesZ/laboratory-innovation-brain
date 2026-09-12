"""T-SPEC-001 — Requirement / Test traceability (TST-002).

Pass condition (§26): all requirement IDs unique; every normative ID has at least one
test; no test references an unknown ID.

The spec document is the source of truth, so these tests parse it rather than compare it
against a hand-maintained copy. Each assertion delegates to a pure function in
``lab_brain.spec.conformance``; the same function is run against deliberately broken
fixtures in ``test_conformance_guards.py``, which is what proves the guard can fail.
"""

from __future__ import annotations

import pytest

from lab_brain.spec import (
    collect_marked_tests,
    conformance,
    load_milestones,
    load_spec,
    rejected_markers,
)


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def marked_tests():
    return collect_marked_tests()


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_requirement_ids_are_unique(spec):
    """A duplicated Requirement ID would make the traceability matrix ambiguous."""
    assert conformance.check_requirement_ids_unique(spec) == []
    assert conformance.check_requirement_ids_wellformed(spec) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_declared_count_invariant_matches_the_tables(spec):
    """§26 asserts "52 requirements <-> 52 tests"; the tables must actually say that."""
    assert conformance.check_declared_invariant(spec) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_every_requirement_has_at_least_one_test(spec):
    """A Requirement with no Test will never be implemented (§0.3)."""
    assert conformance.check_every_requirement_has_test(spec) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_traceability_matrix_references_no_unknown_requirement(spec):
    """A Test pointing at an unknown Requirement points at an unknown norm (§0.3)."""
    assert conformance.check_matrix_requirements_known(spec) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_traceability_test_ids_are_well_formed(spec):
    assert conformance.check_matrix_test_ids_wellformed(spec) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_test_markers_reference_only_known_requirement_ids(spec, marked_tests):
    """Spec rule 「test 不引用未知 ID」 applied to real code, not just to the matrix."""
    assert conformance.check_markers_reference_known_requirements(spec, marked_tests) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_test_markers_reference_only_known_test_ids(spec, marked_tests):
    assert conformance.check_markers_reference_known_tests(spec, marked_tests) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_marker_pairs_match_the_traceability_matrix(spec, marked_tests):
    """A test claiming (requirement, test) must claim a pair the spec actually maps."""
    assert conformance.check_marker_pairs_in_matrix(spec, marked_tests) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_every_marked_test_declares_both_markers(marked_tests):
    """Half a marker cannot be traced. Require requirement+test together."""
    assert conformance.check_markers_complete(marked_tests) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_no_traceability_marker_sits_on_an_uncollected_function():
    """Coverage means a test that runs, not a decorator that exists.

    A marked ``helper_that_never_runs()`` or a marked method on a non-``Test*`` class would
    otherwise count toward the milestone-DONE ratchet without ever executing.
    """
    assert conformance.check_no_markers_on_uncollected_functions(rejected_markers()) == []


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_milestone_catalog_partitions_every_requirement(spec):
    """Every requirement belongs to exactly one milestone, so nothing is orphaned."""
    assert conformance.check_milestones_partition_requirements(spec, load_milestones()) == []
