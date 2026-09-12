"""Spec conformance checks as pure functions over parsed inputs.

Every check takes already-parsed data and returns a list of violation strings; empty means
pass. The indirection buys one specific thing: the same function can be run against the
real repository (T-SPEC-001 / T-SPEC-002) *and* against a deliberately broken fixture
(tests/spec/test_conformance_guards.py).

That matters because "the assertion passed" and "the assertion can fail" are different
claims. Asserting only against correct data proves nothing about whether a guard has teeth.
Earlier this harness was validated by editing the repository, running pytest, and reverting
-- which leaves no durable evidence and cannot run in CI. These functions make the negative
case a permanent test instead.
"""

from __future__ import annotations

from pathlib import Path

from lab_brain.spec.markers import MarkedTest, RejectedMarker
from lab_brain.spec.parser import (
    REQUIREMENT_ID_RE,
    TEST_ID_RE,
    SpecDocument,
)
from lab_brain.spec.registry import (
    MilestoneCatalog,
    NormativeStatementRegistry,
)

_NORMATIVE_LEVELS = frozenset({"MUST", "SHOULD", "MAY"})


# ---------------------------------------------------------------------------
# T-SPEC-001 — Requirement / Test traceability (TST-002)
# ---------------------------------------------------------------------------


def check_requirement_ids_unique(spec: SpecDocument) -> list[str]:
    ids = [requirement.requirement_id for requirement in spec.requirements.values()]
    return [
        f"duplicate Requirement ID: {requirement_id}"
        for requirement_id in sorted({r for r in ids if ids.count(r) > 1})
    ]


def check_requirement_ids_wellformed(spec: SpecDocument) -> list[str]:
    return [
        f"malformed Requirement ID (§23.2 namespaces): {requirement_id}"
        for requirement_id in sorted(spec.requirements)
        if not REQUIREMENT_ID_RE.match(requirement_id)
    ]


def check_declared_invariant(spec: SpecDocument) -> list[str]:
    if not spec.declared_invariants:
        return ["spec declares no requirement/test count invariant"]
    violations: list[str] = []
    for invariant in spec.declared_invariants:
        if invariant.requirement_count != len(spec.requirements):
            violations.append(
                f"spec ({invariant.source_section}) declares "
                f"{invariant.requirement_count} requirements but "
                f"{len(spec.requirements)} are defined"
            )
        if invariant.test_count != len(spec.test_ids):
            violations.append(
                f"spec ({invariant.source_section}) declares {invariant.test_count} "
                f"tests but the §26 matrix names {len(spec.test_ids)} distinct Test IDs"
            )
    return violations


def check_every_requirement_has_test(spec: SpecDocument) -> list[str]:
    return [
        f"{requirement_id} has no Test ID in §26"
        for requirement_id in sorted(spec.requirements)
        if not spec.tests_for(requirement_id)
    ]


def check_matrix_requirements_known(spec: SpecDocument) -> list[str]:
    return [
        f"§26 row references undeclared requirement: {requirement_id}"
        for requirement_id in sorted(
            {
                row.requirement_id
                for row in spec.traceability
                if row.requirement_id not in spec.requirements
            }
        )
    ]


def check_matrix_test_ids_wellformed(spec: SpecDocument) -> list[str]:
    return [
        f"malformed Test ID in §26: {row.test_id}"
        for row in spec.traceability
        if not TEST_ID_RE.match(row.test_id)
    ]


def check_markers_reference_known_requirements(
    spec: SpecDocument, tests: tuple[MarkedTest, ...]
) -> list[str]:
    return [
        f"{test.location} marks unknown Requirement ID {requirement_id}"
        for test in tests
        for requirement_id in test.requirement_ids
        if requirement_id not in spec.requirements
    ]


def check_markers_reference_known_tests(
    spec: SpecDocument, tests: tuple[MarkedTest, ...]
) -> list[str]:
    return [
        f"{test.location} marks Test ID {test_id} absent from the §26 matrix"
        for test in tests
        for test_id in test.test_ids
        if test_id not in spec.test_ids
    ]


def check_marker_pairs_in_matrix(
    spec: SpecDocument, tests: tuple[MarkedTest, ...]
) -> list[str]:
    declared = {(row.requirement_id, row.test_id) for row in spec.traceability}
    return [
        f"{test.location} claims ({requirement_id}, {test_id}), "
        "a pair the §26 matrix does not map"
        for test in tests
        for requirement_id in test.requirement_ids
        for test_id in test.test_ids
        if (requirement_id, test_id) not in declared
    ]


def check_markers_complete(tests: tuple[MarkedTest, ...]) -> list[str]:
    return [
        f"{test.location} carries only one of the two traceability markers"
        for test in tests
        if not test.requirement_ids or not test.test_ids
    ]


def check_no_markers_on_uncollected_functions(
    rejected: tuple[RejectedMarker, ...],
) -> list[str]:
    """Markers on things pytest never runs would satisfy the DONE ratchet without executing.

    This is the hole that makes every other coverage claim in this harness conditional:
    a decorated ``helper_that_never_runs()`` is indistinguishable from real coverage unless
    collectability is checked explicitly.
    """
    return [
        f"{marker.location} carries a traceability marker but {marker.reason}"
        for marker in rejected
    ]


def check_milestones_partition_requirements(
    spec: SpecDocument, catalog: MilestoneCatalog
) -> list[str]:
    allocated = list(catalog.allocated_requirements)
    violations: list[str] = []
    violations.extend(
        f"{requirement_id} allocated to more than one milestone"
        for requirement_id in sorted({r for r in allocated if allocated.count(r) > 1})
    )
    violations.extend(
        f"milestones.yaml allocates undeclared requirement: {requirement_id}"
        for requirement_id in sorted(set(allocated) - set(spec.requirements))
    )
    violations.extend(
        f"{requirement_id} is not allocated to any milestone"
        for requirement_id in sorted(set(spec.requirements) - set(allocated))
    )
    return violations


# ---------------------------------------------------------------------------
# T-SPEC-002 — Normative Statement Registry coverage (TST-003)
# ---------------------------------------------------------------------------


def check_registry_keys_unique(registry: NormativeStatementRegistry) -> list[str]:
    keys = list(registry.keys)
    return [
        f"duplicate statement key: {key}"
        for key in sorted({k for k in keys if keys.count(k) > 1})
    ]


def check_registry_requirements_resolvable(
    registry: NormativeStatementRegistry, spec: SpecDocument
) -> list[str]:
    violations: list[str] = []
    for statement in registry.statements:
        if statement.requirement_id not in spec.requirements:
            violations.append(
                f"{statement.key} references unknown requirement {statement.requirement_id}"
            )
        elif not REQUIREMENT_ID_RE.match(statement.requirement_id):
            violations.append(
                f"{statement.key} has malformed Requirement ID {statement.requirement_id}"
            )
    return violations


def check_registry_tests_known(
    registry: NormativeStatementRegistry, spec: SpecDocument
) -> list[str]:
    return [
        f"{statement.key} references unknown Test ID {test_id}"
        for statement in registry.statements
        for test_id in statement.tests
        if test_id not in spec.test_ids
    ]


def check_registry_test_or_deferral(
    registry: NormativeStatementRegistry,
) -> list[str]:
    return [
        f"{statement.key} has neither a Test ID nor a DEFERRED rationale"
        for statement in registry.statements
        if not statement.tests and not statement.is_deferred
    ]


def check_registry_deferral_review_date(
    registry: NormativeStatementRegistry,
) -> list[str]:
    return [
        f"{statement.key} is DEFERRED with no review_at (an indefinite exemption)"
        for statement in registry.statements
        if statement.is_deferred and not statement.review_at
    ]


def check_registry_matches_matrix(
    registry: NormativeStatementRegistry, spec: SpecDocument
) -> list[str]:
    violations: list[str] = []
    for statement in registry.statements:
        allowed = set(spec.tests_for(statement.requirement_id))
        violations.extend(
            f"{statement.key}: {test_id} is not mapped to {statement.requirement_id} in §26"
            for test_id in statement.tests
            if test_id not in allowed
        )
    return violations


def check_registry_levels(registry: NormativeStatementRegistry) -> list[str]:
    return [
        f"{statement.key} has non-normative level {statement.level!r}"
        for statement in registry.statements
        if statement.level not in _NORMATIVE_LEVELS
    ]


def check_every_requirement_registered(
    registry: NormativeStatementRegistry, spec: SpecDocument
) -> list[str]:
    registered = {statement.requirement_id for statement in registry.statements}
    return [
        f"declared requirement absent from the registry: {requirement_id}"
        for requirement_id in sorted(set(spec.requirements) - registered)
    ]


def check_registry_spec_issues_exist(
    registry: NormativeStatementRegistry, issues_dir: Path
) -> list[str]:
    """A cited spec issue must be a real document.

    AGT-015 forbids an agent resolving a spec ambiguity by choosing a reading. Where a
    registry entry rests on a contested reading, it names the issue file that tracks it, and
    the file has to exist -- otherwise "there is an open spec issue" decays into a comment
    nobody ever has to act on.
    """
    # Issue files carry a descriptive suffix (SPEC-ISSUE-003-typed-tools-....md), so match
    # on the ID prefix rather than an exact filename.
    return [
        f"{statement.key} cites spec issue {statement.spec_issue} but no "
        f"{issues_dir.name}/{statement.spec_issue}*.md exists"
        for statement in registry.statements
        if statement.spec_issue and not any(issues_dir.glob(f"{statement.spec_issue}*.md"))
    ]


def check_completed_milestones_have_collected_tests(
    catalog: MilestoneCatalog, tests: tuple[MarkedTest, ...]
) -> list[str]:
    """NECESSARY BUT NOT SUFFICIENT -- this is not the DONE gate.

    A collected test can be skipped, xfailed or deselected and still appear here, so passing
    this check does not establish that anything executed. The authoritative gate is
    ``lab_brain.spec.outcomes.check_completed_milestones_have_passing_tests``, which reads real
    pytest outcomes after the session finishes.

    Kept because it gives a fast source-level signal, and a Requirement with no marked test at
    all is worth catching without waiting for a full run.
    """
    covered = {requirement_id for test in tests for requirement_id in test.requirement_ids}
    return [
        f"{milestone.milestone_id} is DONE but {requirement_id} has no collected test"
        for milestone in catalog.milestones
        if milestone.is_complete
        for requirement_id in milestone.requirements
        if requirement_id not in covered
    ]
