"""T-SPEC-002 — Normative Statement Registry coverage (TST-003).

Pass condition (§26, as amended by maintainer ruling `v3.3-a1`):

    `statement_key` MUST be unique across the registry; each registry entry MUST reference
    exactly one valid Requirement ID. One Requirement ID MAY be referenced by multiple entries
    when it covers distinct normative statements in different sections. Every entry maps to at
    least one existing Test ID or carries an explicit DEFERRED rationale with review date; no
    entry references an unknown requirement or test.

  Registry completeness against prose is a human audit gate (§23.5), NOT asserted here.

The original wording said only "registry entries have unique Requirement IDs", which read
literally made the §23.6 excerpt violate its own rule -- `VER-006` and `UX-001` each appear
twice there. That was escalated as SPEC-ISSUE-001 rather than decided in code (AGT-015), and
the maintainer ruled Reading B on 2026-09-12. The assertions below did not change; they now
rest on settled spec text.
"""

from __future__ import annotations

import pytest

from lab_brain.spec import (
    collect_marked_tests,
    conformance,
    load_milestones,
    load_registry,
    load_spec,
    spec_issues_dir,
)


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_statement_keys_are_unique(registry):
    assert conformance.check_registry_keys_unique(registry) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_every_entry_names_one_resolvable_requirement(registry, spec):
    assert conformance.check_registry_requirements_resolvable(registry, spec) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_no_entry_references_an_unknown_test(registry, spec):
    assert conformance.check_registry_tests_known(registry, spec) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_entry_has_a_test_or_an_explicit_deferral(registry):
    assert conformance.check_registry_test_or_deferral(registry) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_deferred_entries_carry_a_review_date(registry):
    """A deferral without a review date is an indefinite exemption (§23.6)."""
    assert conformance.check_registry_deferral_review_date(registry) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_registered_test_ids_agree_with_the_traceability_matrix(registry, spec):
    """A statement may only cite a Test the §26 matrix binds to its Requirement."""
    assert conformance.check_registry_matches_matrix(registry, spec) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_registry_levels_are_normative_vocabulary(registry):
    """§0.2 defines exactly MUST / SHOULD / MAY as normative levels."""
    assert conformance.check_registry_levels(registry) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_every_spec_requirement_has_at_least_one_registry_entry(registry, spec):
    """Not prose completeness -- only that no declared Requirement is unregistered."""
    assert conformance.check_every_requirement_registered(registry, spec) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_cited_spec_issues_exist(registry):
    """An entry resting on a contested reading must name a real, open spec issue.

    Without this, "there is a spec issue for that" degrades into a code comment that nobody
    is obliged to act on.
    """
    assert conformance.check_registry_spec_issues_exist(registry, spec_issues_dir()) == []


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_completed_milestones_have_collected_tests():
    """Fast source-level half of the ratchet: a DONE requirement must have a marked test.

    NOT the authoritative gate. A collected test can be skipped, xfailed or deselected and
    still satisfy this. The real gate runs after the session, in
    ``scripts/check_requirement_coverage.py``, which requires outcome ``passed`` under the
    milestone's declared ``gate_profile``. It cannot live here: a test asserting "every DONE
    requirement passed" would need the outcomes of tests that have not run yet.
    """
    assert (
        conformance.check_completed_milestones_have_collected_tests(
            load_milestones(), collect_marked_tests()
        )
        == []
    )
