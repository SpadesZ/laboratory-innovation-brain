"""§17's canonical schemas, the Pydantic models and the migration DDL must agree.

P4 moved `project_id` and `sensitivity_label` off the global `artifacts` table -- correctly, for
R-7 -- and left §17.1 and the Pydantic `Artifact` still declaring both. Three artefacts then
disagreed about what an Artifact *is*, the whole suite stayed green, and the drift survived a review
round before a human read the two files side by side.

Nothing could have caught it. The spec's schemas are fenced code blocks, the models are Python, the
tables are SQL, and no check read more than one of the three.

Deliberately unmarked: this validates the spec-to-implementation harness, not a Requirement.
"""

from __future__ import annotations

import pytest

from lab_brain.spec.schema_drift import (
    BINDINGS,
    UNBOUND,
    SchemaDriftError,
    all_drift,
    canonical_fields,
    drift,
    effective_table_columns,
    model_fields,
    stale_exemptions,
    unbound_canonical_schemas,
)


def test_no_canonical_schema_has_drifted():
    """The guard itself. Every bound §17 schema matches its model and its table, both ways."""
    assert all_drift() == []


def test_the_artifact_contract_is_the_one_adr_0010_describes():
    """Pinned, because this is the specific drift that occurred.

    Asserting the *absence* of the two fields from all three places, so a well-meaning
    reintroduction fails here with the reason attached rather than passing quietly.
    """
    binding = next(b for b in BINDINGS if b.schema_name == "Artifact")
    canonical = canonical_fields("Artifact", "17.1")
    model = model_fields(binding.model_path)
    table = effective_table_columns(binding)

    for field in ("project_id", "sensitivity_label"):
        assert field not in canonical, f"§17.1 declares {field}; ADR-0010 moved it to §17.1.1"
        assert field not in model, f"Artifact model carries {field}"
        assert field not in table, f"artifacts table carries {field}"

    assert "content_hash" in canonical and "content_hash" in model and "content_hash" in table


def test_the_occurrence_contract_carries_exactly_the_project_scoped_facts():
    """And the other half: the fields have to land somewhere, not merely leave."""
    binding = next(b for b in BINDINGS if b.schema_name == "ArtifactOccurrence")
    canonical = canonical_fields("ArtifactOccurrence", "17.1.1")
    assert {"artifact_id", "project_id", "sensitivity_label"} <= canonical
    assert canonical == model_fields(binding.model_path)
    assert canonical <= effective_table_columns(binding)


def test_a_field_added_to_the_model_alone_is_detected():
    """Prove the guard fires in the direction that actually happened.

    A field present in the implementation and absent from the spec is exactly how `project_id`
    ended up on `artifacts`.
    """
    binding = next(b for b in BINDINGS if b.schema_name == "Artifact")
    doctored = (
        __import__("lab_brain.spec.parser", fromlist=["spec_path"])
        .spec_path()
        .read_text(encoding="utf-8")
        .replace("  source_origin,\n", "", 1)
    )
    findings = drift(binding, doctored)
    assert any(
        ("source_origin" in finding and "not\ndeclared" in finding.replace(" ", "\n"))
        or ("source_origin" in finding and "not declared" in finding)
        for finding in findings
    ), findings


def test_a_field_removed_from_the_implementation_is_detected():
    """The mirror direction: the spec declares something nobody built."""
    binding = next(b for b in BINDINGS if b.schema_name == "Artifact")
    doctored = (
        __import__("lab_brain.spec.parser", fromlist=["spec_path"])
        .spec_path()
        .read_text(encoding="utf-8")
        .replace("  source_origin,\n", "  source_origin, invented_field,\n", 1)
    )
    findings = drift(binding, doctored)
    assert any(
        "invented_field" in finding and "absent from the" in finding for finding in findings
    ), findings


def test_the_parse_is_not_vacuous():
    """Guard the guard: a §17 format change must fail loudly, not silently compare nothing."""
    for binding in BINDINGS:
        fields = canonical_fields(binding.schema_name, binding.section)
        assert len(fields) >= 4, f"§{binding.section} parsed to {len(fields)} fields"

    with pytest.raises(SchemaDriftError, match=r"contains no `Artifact \{ \.\.\. \}` block"):
        canonical_fields("Artifact", "17.1", "## 17.1 Artifact Schema\n\nno code block here\n")

    with pytest.raises(SchemaDriftError, match="not found"):
        canonical_fields("Artifact", "99.9", "## 1 Nothing\n")


def test_every_binding_names_a_real_model_and_table():
    """A binding whose target does not exist would pass by never comparing anything."""
    for binding in BINDINGS:
        assert model_fields(binding.model_path), binding.model_path
        assert effective_table_columns(binding), binding.table


def test_every_canonical_schema_is_bound_or_exempt():
    """Completeness. The claim `BINDINGS` makes about itself has to be true.

    An earlier comment said adding a model without binding it "is itself caught by
    test_every_core_model_with_a_canonical_schema_is_bound" -- a test that did not exist. Only 2 of
    the 12 §17 schemas naming a core model were bound, and nothing said so.

    This is that test. Every §17 block naming an exported core model must be bound, or listed in
    `UNBOUND` with a reason. Silence is no longer an option; an unreviewed gap becomes a visible one.
    """
    assert unbound_canonical_schemas() == []


def test_no_exemption_has_gone_stale():
    """The exemption list must not rot into a permanent excuse.

    A schema deleted by an amendment, or one later bound properly, would otherwise keep an entry
    claiming it cannot be checked.
    """
    assert stale_exemptions() == []


def test_the_exemptions_are_explained_and_finite():
    """Each exemption states why, and the list is small enough to read.

    Most §17 blocks are abbreviated sketches rather than complete schemas, which is a real reason
    not to bind them by exact field equality -- and also exactly the reasoning that would excuse
    anything if it were left implicit.
    """
    for name, reason in UNBOUND.items():
        assert len(reason.split()) >= 8, f"{name}'s exemption is too terse to review: {reason!r}"
        assert "§" in reason or "block" in reason, (
            f"{name}'s exemption should say what about the canonical block prevents binding"
        )
    assert len(UNBOUND) < len(BINDINGS) + 20, "the exemption list has grown past reviewability"


def test_the_completeness_scan_sees_the_schemas_it_should():
    """Guard the guard: a §17 format change must not empty the scan and pass everything."""
    from lab_brain.spec.schema_drift import canonical_schema_names

    names = canonical_schema_names()
    assert len(names) > 20, f"only {len(names)} §17 schema blocks found; format likely changed"
    for expected in ("Artifact", "ArtifactOccurrence", "Claim", "Attestation"):
        assert expected in names, f"§17 scan missed {expected}"


def test_an_unbound_unexempted_schema_is_detected():
    """Prove the completeness guard fires, by removing an exemption it depends on."""
    import lab_brain.spec.schema_drift as module

    saved = dict(module.UNBOUND)
    try:
        module.UNBOUND.pop("Claim")
        assert any("Claim" in finding for finding in unbound_canonical_schemas())
    finally:
        module.UNBOUND.clear()
        module.UNBOUND.update(saved)
