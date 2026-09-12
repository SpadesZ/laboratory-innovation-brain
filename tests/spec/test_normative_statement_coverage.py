"""T-SPEC-002 — Normative Statement Registry coverage (TST-003).

Pass condition (§26): registry entries have unique Requirement IDs; every entry maps to
at least one existing Test ID or carries an explicit DEFERRED rationale with review
date; no entry references an unknown requirement or test.

  Registry completeness against prose is a human audit gate (§23.5), NOT asserted here.

READING NOTE on "unique Requirement IDs". Taken literally as "each Requirement ID appears
in at most one entry", the §23.6 excerpt fails its own rule: VER-006 is registered twice
(prediction.typed.contract, sufficiency.hypothetical.sideeffect_free) and so is UX-001
(ingestion.state.derived, ingestion.duplicate.work_vs_bytes). One requirement legitimately
covers several distinct MUSTs in different sections. The enforceable reading -- and the
one implemented here -- is that each entry names exactly one unambiguously resolving
Requirement ID, and that statement *keys* are unique. Recorded as a spec observation in
docs/spec_coverage_audit/M0a.md.
"""

from __future__ import annotations

import pytest

from lab_brain.spec import (
    collect_marked_tests,
    load_milestones,
    load_registry,
    load_spec,
)
from lab_brain.spec.parser import REQUIREMENT_ID_RE


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_statement_keys_are_unique(registry):
    keys = list(registry.keys)
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    assert not duplicated, f"duplicate statement keys in registry: {duplicated}"


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_every_entry_names_one_resolvable_requirement(registry, spec):
    unresolvable = sorted(
        {
            f"{statement.key} -> {statement.requirement_id}"
            for statement in registry.statements
            if statement.requirement_id not in spec.requirements
        }
    )
    assert not unresolvable, (
        f"registry entries referencing unknown requirements: {unresolvable}"
    )
    malformed = sorted(
        {
            statement.requirement_id
            for statement in registry.statements
            if not REQUIREMENT_ID_RE.match(statement.requirement_id)
        }
    )
    assert not malformed, f"malformed Requirement IDs in registry: {malformed}"


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_no_entry_references_an_unknown_test(registry, spec):
    offenders = sorted(
        {
            f"{statement.key} -> {test_id}"
            for statement in registry.statements
            for test_id in statement.tests
            if test_id not in spec.test_ids
        }
    )
    assert not offenders, f"registry entries referencing unknown Test IDs: {offenders}"


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_entry_has_a_test_or_an_explicit_deferral(registry):
    offenders = [
        statement.key
        for statement in registry.statements
        if not statement.tests and not statement.is_deferred
    ]
    assert not offenders, (
        "registry entries with neither a Test ID nor a DEFERRED rationale: "
        f"{offenders}"
    )


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_deferred_entries_carry_a_review_date(registry):
    """A deferral without a review date is an indefinite exemption (§23.6)."""
    offenders = [
        statement.key
        for statement in registry.statements
        if statement.is_deferred and not statement.review_at
    ]
    assert not offenders, (
        f"DEFERRED registry entries with no review_at: {offenders}"
    )


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_registered_test_ids_agree_with_the_traceability_matrix(registry, spec):
    """A statement may only cite a Test the §26 matrix actually binds to its Requirement."""
    offenders: list[str] = []
    for statement in registry.statements:
        allowed = set(spec.tests_for(statement.requirement_id))
        for test_id in statement.tests:
            if test_id not in allowed:
                offenders.append(
                    f"{statement.key}: {test_id} is not mapped to "
                    f"{statement.requirement_id} in §26"
                )
    assert not offenders, offenders


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_registry_levels_are_normative_vocabulary(registry):
    """§0.2 defines exactly MUST / SHOULD / MAY as normative levels."""
    offenders = sorted(
        {
            f"{statement.key}={statement.level}"
            for statement in registry.statements
            if statement.level not in {"MUST", "SHOULD", "MAY"}
        }
    )
    assert not offenders, f"non-normative levels in registry: {offenders}"


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_every_spec_requirement_has_at_least_one_registry_entry(registry, spec):
    """Not prose completeness -- only that no declared Requirement is unregistered."""
    registered = {statement.requirement_id for statement in registry.statements}
    missing = sorted(set(spec.requirements) - registered)
    assert not missing, (
        f"declared requirements absent from the registry: {missing}"
    )


@pytest.mark.requirement("TST-003")
@pytest.mark.spec_test("T-SPEC-002")
def test_completed_milestones_have_real_tests(spec):
    """The ratchet: once a milestone is DONE, its requirements need executable tests.

    This is what stops a milestone being declared complete on the strength of prose.
    """
    catalog = load_milestones()
    covered = {
        requirement_id
        for test in collect_marked_tests()
        for requirement_id in test.requirement_ids
    }
    gaps: list[str] = []
    for milestone in catalog.milestones:
        if not milestone.is_complete:
            continue
        for requirement_id in milestone.requirements:
            if requirement_id not in covered:
                gaps.append(f"{milestone.milestone_id}:{requirement_id}")
    assert not gaps, (
        "milestones marked DONE whose requirements have no marked test: " f"{gaps}"
    )
