"""Every hard obligation in §6-§16 must be accounted for occurrence by occurrence.

Revision 4 of the M0a audit counted hard obligations per *section*, and that still permitted the
write-off this file removes. §10.7 was closed as ``hard_must: 0`` with the basis "the Job-ification
rule is registered at §12.4, its precise location", and §11 as "the core-must-not-import-domain rule
is registered at §24.2". Both claims happened to be true. Nothing checked either one: no target key
was named, so nothing verified the statement existed, still lived at that section, or said what the
basis claimed it said.

Counting occurrences instead makes the claim machine-checkable. Each explicit ``MUST / MUST NOT /
必須 / 不得 / 不可`` in §6-§16 is classified exactly once, and RESTATEMENT_OF has to name a
statement_key that resolves against the registry.

Deliberately unmarked, like the section-level audit next door. §23.5 (2) is a human review gate, not
one of the 58 Requirement IDs; what these tests mechanise is the audit's bookkeeping, while the
adjudications and the sign-off stay human.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab_brain.spec import load_registry
from lab_brain.spec.coverage_audit import (
    CLASSIFICATIONS,
    count_disagreements,
    doubly_registered,
    drifted_quotes,
    hard_obligation_occurrences,
    headings_asserting_obligations,
    load_hard_must_counts,
    load_keyword_free,
    load_obligation_inventory,
    registered_per_section,
    stale_adjudications,
    unclassified_occurrences,
    undeclared_keyword_free,
    unresolved_targets,
)
from lab_brain.spec.registry import RegistryError


@pytest.fixture(scope="module")
def inventory():
    return load_obligation_inventory()


def test_no_hard_occurrence_is_left_unclassified(inventory):
    """The primary guard. A new obligation is a CI failure until someone adjudicates it."""
    assert unclassified_occurrences(inventory) == []


def test_no_adjudication_survives_the_occurrence_it_describes(inventory):
    """Inverse drift: a deleted sentence must not leave a row still accounting for it."""
    assert stale_adjudications(inventory) == []


def test_a_reworded_obligation_is_not_silently_inherited(inventory):
    """Rewording can change what a sentence obliges while keeping its position.

    The digest covers the containing line, so an amendment that edits the prose forces
    re-adjudication instead of carrying the old classification forward.
    """
    assert drifted_quotes(inventory) == []


def test_every_named_target_resolves_to_a_registry_statement(inventory):
    """The second guard the user asked for, and the one that closes §10.7 and §11.

    Naming a target is worth nothing if the name is never checked. A typo, a renamed key, or a
    statement deleted by an amendment all show up here.
    """
    assert unresolved_targets(inventory, load_registry()) == []


def test_no_statement_has_two_prose_homes(inventory):
    """One obligation, one REGISTERED occurrence.

    Two sites claiming the same key would let a single obligation be counted twice -- inflating a
    section's hard_must and then manufacturing the coverage to balance it. That is the §15.4 failure
    with the sign flipped, so it gets its own guard. Repetition belongs in RESTATEMENT_OF.
    """
    assert doubly_registered(inventory) == []


def test_hard_must_agrees_with_the_inventory():
    """`hard_must` is derived, not asserted.

    Two files maintained separately are forced to agree: the count file's number must equal the
    REGISTERED occurrences the inventory records at that section plus the keyword-free statements it
    declares. Rev 4's §7.2 is why this matters -- its basis text named three obligations while the
    number said 2, and nothing compared them.
    """
    assert (
        count_disagreements(
            load_hard_must_counts(), load_keyword_free(), load_obligation_inventory()
        )
        == []
    )


def test_every_keyword_free_statement_is_declared_with_a_rationale(inventory):
    """A registered MUST with no occurrence must be declared, or nobody is asked how it is stated.

    §10.5 is the case that justifies the category: the obligation rides entirely on 不是
    (「「measurement 永遠最高」**不是** core 假設」), so no keyword scan can see it. Legitimate -- and
    also exactly where an unfounded count could hide, hence the required rationale.
    """
    assert undeclared_keyword_free(load_keyword_free(), inventory, load_registry()) == []


def test_a_heading_that_asserts_an_obligation_has_one(inventory):
    """Guard the heading exclusion.

    Heading lines are skipped by the scan, on the rule that a title asserting an obligation must
    state it in the body. Left unchecked that exclusion is a hiding place: §14.4.1's heading is
    「ReviewQueue 必須接回 Verification Planner」, and had its body stated nothing, the section would
    have counted 0 with no scan objecting.
    """
    assert headings_asserting_obligations(load_hard_must_counts()) == []


def test_the_extraction_is_not_vacuous():
    """Guard the guard: a format change must not empty the scan and pass everything.

    Every check in this file is downstream of the occurrence list. If the scan returned nothing,
    all of them would pass while nothing was being checked -- so the floor is asserted here, along
    with the specific occurrences the audit's findings depend on.
    """
    occurrences = {o.occurrence_id for o in hard_obligation_occurrences()}
    assert len(occurrences) > 60, (
        f"only {len(occurrences)} occurrences found; format likely changed"
    )
    for occurrence_id in ("7.2#2", "7.6#1", "8.2.1#2", "10.2.1#2", "10.7#1", "11#1", "14.3#1"):
        assert occurrence_id in occurrences, f"{occurrence_id} no longer extracted"


def test_every_classification_is_one_of_the_three(inventory):
    """No fourth class, and no default -- an unlooked-at occurrence must fail, not be assumed benign."""
    assert {row.classification for row in inventory} <= set(CLASSIFICATIONS)
    assert len(inventory) > 60


def test_the_sections_the_reviewer_named_are_resolved_at_occurrence_level(inventory):
    """The seven sections the review called out, asserted rather than narrated.

    Each was either miscounted or written off. The expected classification and target are pinned
    here so a later edit that quietly re-writes one off fails.
    """
    rows = {row.occurrence_id: row for row in inventory}

    # Previously written off as hard_must: 0 with an unnamed "registered elsewhere" basis.
    assert rows["10.7#1"].classification == "RESTATEMENT_OF"
    assert rows["10.7#1"].target == "job.long_running.suspend_resume_idempotent"
    assert rows["11#1"].classification == "RESTATEMENT_OF"
    assert rows["11#1"].target == "domain.core_no_domain_import"

    # Previously unowned; now registered against an existing Requirement.
    assert rows["7.2#2"].target == "debate.rounds.not_fixed"
    assert rows["7.6#1"].target == "critique.independent_path.major_reject"
    assert rows["7.6#2"].target == "inference.no_provenance_not_usable"
    assert rows["8.2.1#2"].target == "transition.decision.deterministic"
    assert rows["14.4#1"].target == "review.queue.stakes_sla_expiry"
    for occurrence_id in ("7.2#2", "7.6#1", "7.6#2", "8.2.1#2", "14.4#1"):
        assert rows[occurrence_id].classification == "REGISTERED"

    # Previously attributed to the wrong section, which made §10.2 look covered.
    assert rows["10.2.1#2"].classification == "REGISTERED"
    assert rows["10.2.1#2"].target == "extractor.backend_agnostic"
    extractor = next(s for s in load_registry().statements if s.key == "extractor.backend_agnostic")
    assert extractor.section == "10.2.1"

    # §14.3's two keyword occurrences, one live and one deferred.
    assert rows["14.3#1"].target == "privacy.query_gate.no_private_identifiers"
    assert rows["14.3#2"].target == "governance.fabrication.human_signoff"

    # And the sections whose totals moved as a result.
    per_section = registered_per_section(inventory)
    assert per_section["7.2"] == 3
    assert per_section["7.6"] == 2
    assert per_section["8.2.1"] == 2
    assert per_section["10.2.1"] == 3
    assert "10.7" not in per_section
    assert "11" not in per_section


def _mutate(inventory, occurrence_id, **changes):
    """Return the inventory with one row altered, for proving a guard actually fires."""
    return tuple(
        replace(row, **changes) if row.occurrence_id == occurrence_id else row for row in inventory
    )


def test_dropping_an_adjudication_is_detected(inventory):
    """Prove the completeness guard fires. Removing a row must surface as unclassified."""
    thinned = tuple(row for row in inventory if row.occurrence_id != "10.5.1#1")
    findings = unclassified_occurrences(thinned)
    assert any(finding.startswith("10.5.1#1") for finding in findings), findings


def test_a_target_that_does_not_resolve_is_detected(inventory):
    """Prove target resolution fires -- the guard that gives §10.7 and §11 their meaning."""
    broken = _mutate(inventory, "10.7#1", target="job.long_running.suspend_resume_idempotant")
    assert unresolved_targets(broken, load_registry()) == [
        "10.7#1 -> job.long_running.suspend_resume_idempotant"
    ]


def test_claiming_a_second_prose_home_is_detected(inventory):
    """Prove the one-home rule fires: §10.7 upgrading itself to REGISTERED must be caught."""
    doubled = _mutate(inventory, "10.7#1", classification="REGISTERED")
    assert doubly_registered(doubled) == [
        "job.long_running.suspend_resume_idempotent claimed by 10.7#1, 12.4#1"
    ]


def test_a_count_that_disagrees_with_the_inventory_is_detected(inventory):
    """Prove the cross-check fires in both directions.

    Downgrading an occurrence must break the count, and so must inflating the count -- otherwise the
    file could be fixed by editing whichever side is more convenient.
    """
    downgraded = _mutate(
        inventory, "15.4#1", classification="RESTATEMENT_OF", target="benchmark.policy.calibration"
    )
    problems = count_disagreements(load_hard_must_counts(), load_keyword_free(), downgraded)
    assert problems == [
        "§15.4: hard_must=2 but inventory implies 1 (1 REGISTERED + 0 keyword-free)"
    ]

    counts = dict(load_hard_must_counts())
    counts["15.4"] = (9, counts["15.4"][1])
    inflated = count_disagreements(counts, load_keyword_free(), inventory)
    assert inflated == [
        "§15.4: hard_must=9 but inventory implies 2 (2 REGISTERED + 0 keyword-free)"
    ]


def test_a_reworded_quote_is_detected(inventory):
    """Prove drift detection fires rather than accepting whatever digest is on disk."""
    drifted = _mutate(inventory, "11#1", quote_digest="0" * 16)
    findings = drifted_quotes(drifted)
    assert len(findings) == 1 and findings[0].startswith("11#1: recorded 0000000000000000")


def test_an_undeclared_keyword_free_statement_is_detected(inventory):
    """Prove the keyword-free declaration requirement fires.

    §10.5's statement has no occurrence, so dropping its declaration must leave it accounted for
    nowhere -- which is how §10.5.1's two MUSTs stayed invisible in rev 3.
    """
    keyword_free = dict(load_keyword_free())
    keyword_free["10.5"] = ()
    assert undeclared_keyword_free(keyword_free, inventory, load_registry()) == [
        "§10.5 authority.partial_order_not_ladder"
    ]


def test_a_shape_error_is_refused_at_load_time(tmp_path):
    """A REGISTERED row with no target must not load at all.

    Failing here rather than in one test means every consumer -- the tests, the rebuild script, the
    audit generator -- sees the same rule, and the inventory cannot be made to load by editing the
    check that reads it.
    """
    broken = tmp_path / "inv.yaml"
    broken.write_text(
        "schema_version: 1\noccurrences:\n"
        "  - occurrence_id: '9.9#1'\n    quote: x\n    classification: REGISTERED\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="names no target statement_key"):
        load_obligation_inventory(broken)

    broken.write_text(
        "schema_version: 1\noccurrences:\n"
        "  - occurrence_id: '9.9#1'\n    quote: x\n"
        "    classification: NON_NORMATIVE_WITH_RATIONALE\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="has no rationale"):
        load_obligation_inventory(broken)

    broken.write_text(
        "schema_version: 1\noccurrences:\n"
        "  - occurrence_id: '9.9#1'\n    quote: x\n    classification: PROBABLY_FINE\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="must be one of"):
        load_obligation_inventory(broken)


def test_a_restatement_bottoms_out_at_a_statement_some_section_owns(inventory):
    """A restatement chain has to end somewhere real.

    Target resolution already proves the key exists. This adds the part that makes it mean
    something: the key must be owned somewhere. Two shapes are legitimate and the distinction
    matters --

    * **cross-section** (§10.7 -> §12.4): the target's home is a different section, which must
      itself register it or declare it keyword-free. Otherwise every site defers to another and the
      obligation is recorded nowhere -- the write-off, one level of indirection deeper.
    * **same-sentence** (§6.4's 「必須可停留」 then 「不得由模型補值」): the target's home is this same
      section, which must therefore also carry the REGISTERED occurrence. A same-section
      RESTATEMENT_OF with no REGISTERED sibling means the section never actually registered it.
    """
    homes = {row.target: row.section for row in inventory if row.classification == "REGISTERED"}
    keyword_free = load_keyword_free()
    declared = {key: section for section, keys in keyword_free.items() for key in keys}
    sections = {statement.key: statement.section for statement in load_registry().statements}

    for row in inventory:
        if row.classification != "RESTATEMENT_OF":
            continue
        home = homes.get(row.target) or declared.get(row.target) or sections[row.target]
        if sections[row.target] == row.section:
            assert homes.get(row.target) == row.section, (
                f"{row.occurrence_id} restates {row.target}, registered at this same section, but "
                "no occurrence here is REGISTERED for it"
            )
        else:
            assert home == sections[row.target], (
                f"{row.occurrence_id} restates {row.target}, whose home section "
                f"§{sections[row.target]} neither registers nor declares it"
            )
