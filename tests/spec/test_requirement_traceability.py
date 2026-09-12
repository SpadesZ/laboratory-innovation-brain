"""T-SPEC-001 — Requirement / Test traceability (TST-002).

Pass condition (§26): all requirement IDs unique; every normative ID has at least one
test; no test references an unknown ID.

The spec document is the source of truth. These tests parse it rather than compare it
against a hand-maintained copy, so a table edit cannot drift away from CI silently.
"""

from __future__ import annotations

import pytest

from lab_brain.spec import (
    collect_marked_tests,
    load_milestones,
    load_spec,
)
from lab_brain.spec.parser import REQUIREMENT_ID_RE, TEST_ID_RE


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_requirement_ids_are_unique(spec):
    """A duplicated Requirement ID would make the traceability matrix ambiguous."""
    # parse_requirements raises on duplicates, so reaching here already proves
    # uniqueness within §25.3; assert the resulting set size to keep the guarantee
    # explicit and to catch EXT-001 colliding with a table row.
    ids = [requirement.requirement_id for requirement in spec.requirements.values()]
    assert len(ids) == len(set(ids)), "duplicate Requirement ID in spec"
    for requirement_id in ids:
        assert REQUIREMENT_ID_RE.match(requirement_id), (
            f"{requirement_id} is not a well-formed Requirement ID (§23.2 namespaces)"
        )


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_declared_count_invariant_matches_the_tables(spec):
    """§26 asserts "52 requirements <-> 52 tests"; the tables must actually say that."""
    assert spec.declared_invariants, "spec declares no requirement/test count invariant"
    for invariant in spec.declared_invariants:
        assert invariant.requirement_count == len(spec.requirements), (
            f"spec ({invariant.source_section}) declares "
            f"{invariant.requirement_count} requirements but "
            f"{len(spec.requirements)} are defined"
        )
        assert invariant.test_count == len(spec.test_ids), (
            f"spec ({invariant.source_section}) declares {invariant.test_count} tests "
            f"but the §26 matrix names {len(spec.test_ids)} distinct Test IDs"
        )


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_every_requirement_has_at_least_one_test(spec):
    """A Requirement with no Test will never be implemented (§0.3)."""
    untested = sorted(
        requirement_id
        for requirement_id in spec.requirements
        if not spec.tests_for(requirement_id)
    )
    assert not untested, f"requirements with no Test ID in §26: {untested}"


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_traceability_matrix_references_no_unknown_requirement(spec):
    """A Test pointing at an unknown Requirement points at an unknown norm (§0.3)."""
    unknown = sorted(
        {
            row.requirement_id
            for row in spec.traceability
            if row.requirement_id not in spec.requirements
        }
    )
    assert not unknown, f"§26 rows reference undeclared requirements: {unknown}"


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_traceability_test_ids_are_well_formed(spec):
    malformed = sorted(
        row.test_id for row in spec.traceability if not TEST_ID_RE.match(row.test_id)
    )
    assert not malformed, f"malformed Test IDs in §26: {malformed}"


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_test_markers_reference_only_known_requirement_ids(spec):
    """"test 不引用未知 ID" applied to real code, not just to the matrix."""
    offenders = [
        (test.location, requirement_id)
        for test in collect_marked_tests()
        for requirement_id in test.requirement_ids
        if requirement_id not in spec.requirements
    ]
    assert not offenders, (
        "tests marked with Requirement IDs the spec does not declare: " f"{offenders}"
    )


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_test_markers_reference_only_known_test_ids(spec):
    offenders = [
        (test.location, test_id)
        for test in collect_marked_tests()
        for test_id in test.test_ids
        if test_id not in spec.test_ids
    ]
    assert not offenders, (
        f"tests marked with Test IDs absent from the §26 matrix: {offenders}"
    )


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_marker_pairs_match_the_traceability_matrix(spec):
    """A test claiming (requirement, test) must claim a pair the spec actually maps."""
    declared_pairs = {(row.requirement_id, row.test_id) for row in spec.traceability}
    offenders: list[tuple[str, str, str]] = []
    for test in collect_marked_tests():
        for requirement_id in test.requirement_ids:
            for test_id in test.test_ids:
                if (requirement_id, test_id) not in declared_pairs:
                    offenders.append((test.location, requirement_id, test_id))
    assert not offenders, (
        "marker pairs not present in the §26 matrix "
        f"(requirement, test): {offenders}"
    )


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_every_marked_test_declares_both_markers():
    """Half a marker cannot be traced. Require requirement+test together."""
    incomplete = [
        test.location
        for test in collect_marked_tests()
        if not test.requirement_ids or not test.test_ids
    ]
    assert not incomplete, (
        "tests carrying only one of the two traceability markers: " f"{incomplete}"
    )


@pytest.mark.requirement("TST-002")
@pytest.mark.spec_test("T-SPEC-001")
def test_milestone_catalog_partitions_every_requirement(spec):
    """Every requirement belongs to exactly one milestone, so nothing is orphaned."""
    catalog = load_milestones()
    allocated = list(catalog.allocated_requirements)

    duplicated = sorted({r for r in allocated if allocated.count(r) > 1})
    assert not duplicated, f"requirements allocated to more than one milestone: {duplicated}"

    unknown = sorted(set(allocated) - set(spec.requirements))
    assert not unknown, f"milestones.yaml allocates undeclared requirements: {unknown}"

    unallocated = sorted(set(spec.requirements) - set(allocated))
    assert not unallocated, (
        f"requirements not allocated to any milestone: {unallocated}"
    )
