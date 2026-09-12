"""The M0a coverage audit's arithmetic must hold (§23.5 (2)).

Revision 2 of the audit contained the row "§15.4: hard MUST = 2, registry-covered = 1, delta = 0".
It is false, and it survived review because the table was prose -- nothing recomputed it. The
accompanying note then justified the gap by pointing at §7.2's `debate.metrics.recorded`, which is
a different obligation: §7.2 requires the metrics to be *recorded*, §15.4 requires the
groupthink-reduction *claim* to be refutable.

So the numbers are now data and the deltas are recomputed here. A row that does not balance fails
CI, and the "covered elsewhere" move is no longer available -- coverage is counted only at the
section where the statement is registered.

Deliberately unmarked. §23.5 (2) is a human review gate, not one of the 57 Requirement IDs, and
claiming one here would inflate the traceability matrix with something the spec never asked for.
What this file mechanises is the audit's *arithmetic*; the judgement in the `hard_must` counts and
the sign-off both remain human.
"""

from __future__ import annotations

import pytest

from lab_brain.spec import load_registry
from lab_brain.spec.coverage_audit import (
    load_hard_must_counts,
    reconcile,
    unaudited_sections,
    unbalanced,
)


@pytest.fixture(scope="module")
def rows():
    return reconcile(load_registry(), load_hard_must_counts())


def test_every_section_balances(rows):
    """§23.5's pass condition: delta is 0 for every section, under one formula."""
    assert unbalanced(rows) == []


def test_the_audit_is_not_empty(rows):
    """Guard against the reconciliation passing because nothing was counted."""
    assert len(rows) > 40, f"only {len(rows)} sections reconciled; the count file looks truncated"
    assert sum(row.hard_must for row in rows) > 50


def test_no_registry_section_in_range_is_left_uncounted():
    """A section omitted from the count file would balance by never being counted.

    That is the quieter version of the §15.4 failure: not a wrong number, but an absent row.
    """
    assert unaudited_sections(load_registry(), load_hard_must_counts()) == []


def test_should_entries_are_excluded_from_hard_must_coverage(rows):
    """§0.2 makes SHOULD normative, but a SHOULD is not a hard MUST and must not pad coverage.

    §6.21 is the live example: three registry entries, one of them SHOULD-level, against two hard
    MUSTs. Counting all three would have shown coverage exceeding the requirement and hidden a
    genuine gap elsewhere.
    """
    by_section = {row.section: row for row in rows}
    section = by_section["6.21"]
    assert section.should == 1
    assert section.hard_must == 2
    assert section.live_must == 2
    assert section.delta == 0


def test_deferred_entries_are_counted_once_not_twice(rows):
    """A DEFERRED entry counts as deferred, never also as covered.

    §6.17 and §14.3 each hold one deferred MUST. Counting it in both columns would make the delta
    negative and mask a missing registration.
    """
    by_section = {row.section: row for row in rows}

    independence = by_section["6.17"]
    assert (independence.hard_must, independence.live_must, independence.deferred_must) == (2, 1, 1)
    assert independence.delta == 0

    governance = by_section["14.3"]
    assert (governance.hard_must, governance.live_must, governance.deferred_must) == (2, 1, 1)
    assert governance.delta == 0


def test_section_15_4_is_covered_at_its_own_section(rows):
    """The specific row that was wrong, now asserted rather than narrated."""
    section = next(row for row in rows if row.section == "15.4")
    assert section.hard_must == 2
    assert section.live_must == 2
    assert section.delta == 0


def test_the_groupthink_statement_is_registered_distinctly_from_the_metrics_one():
    """§15.4 falsifiability and §7.2 metric recording are separate obligations.

    Both map to LLM-002, which is legitimate -- one requirement may cover several statements. What
    is not legitimate is treating the §7.2 entry as discharging §15.4, which is what the previous
    audit did.
    """
    registry = load_registry()
    keys = {statement.key: statement for statement in registry.statements}

    falsifiable = keys["debate.groupthink_reduction.falsifiable"]
    recorded = keys["debate.metrics.recorded"]

    assert falsifiable.section == "15.4"
    assert recorded.section == "7.2"
    assert falsifiable.key != recorded.key
    assert falsifiable.requirement_id == recorded.requirement_id == "LLM-002"


def test_every_hard_must_count_records_its_basis():
    """An unexplained number cannot be reviewed, which is the whole point of a human audit."""
    for section, (_, basis) in load_hard_must_counts().items():
        assert basis, f"§{section} has no basis recorded"
