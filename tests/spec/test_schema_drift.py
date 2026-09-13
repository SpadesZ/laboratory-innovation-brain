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
    SchemaDriftError,
    all_drift,
    canonical_fields,
    drift,
    effective_table_columns,
    model_fields,
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
