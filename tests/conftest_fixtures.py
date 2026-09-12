"""Shared builders for core scientific entities.

Kept out of ``conftest.py`` so they can be imported explicitly. A fixture that silently supplies
a valid ``sensitivity_label`` or a registered condition schema would let a test pass while the
thing under test never saw a real classification decision.
"""

from __future__ import annotations

from typing import Any

from lab_brain.core.models import (
    Artifact,
    Attestation,
    Claim,
    ConditionSchemaRegistration,
    EpistemicType,
    ExtractionProvenance,
    Observation,
    RelationJudgment,
    RelationType,
    SensitivityLabel,
    SourceOrigin,
    SourceWork,
    SourceWorkType,
    TrustClass,
    WorkIdentifier,
)
from lab_brain.evidence import ConditionSchemaRegistry

PROJECT_ID = "prj:test"
EXTRACTOR_ID = "toy_extractor"
EXTRACTOR_VERSION = "1.0.0"

#: A minimal condition schema owned by a fictional ``toy`` domain. Core tests must not depend on
#: the Silicon Photonics DomainPack: it does not exist until M2, and depending on it would be
#: exactly the core-to-domain coupling §24.2 forbids.
TOY_SCHEMA_REF = "toy/basic@1.0.0"
TOY_COMPARATOR_VERSION = "toy-comparator-1.0.0"

TOY_SCHEMA = ConditionSchemaRegistration(
    domain="toy",
    schema_id="basic",
    version="1.0.0",
    comparator_version=TOY_COMPARATOR_VERSION,
    json_schema={
        "type": "object",
        "required": ["setting"],
        "properties": {
            "setting": {"type": "string"},
            "level": {"type": "number"},
        },
    },
)

TOY_SCHEMA_V2 = ConditionSchemaRegistration(
    domain="toy",
    schema_id="basic",
    version="2.0.0",
    comparator_version="toy-comparator-2.0.0",
    json_schema={
        "type": "object",
        "required": ["setting", "level"],
        "properties": {
            "setting": {"type": "string"},
            "level": {"type": "number"},
            "mode": {"type": "string"},
        },
    },
)


def registry_with_toy_schema() -> ConditionSchemaRegistry:
    registry = ConditionSchemaRegistry()
    registry.register_schema(TOY_SCHEMA)
    return registry


def make_artifact(data: bytes = b"payload", **overrides: Any) -> Artifact:
    fields: dict[str, Any] = {
        "media_type": "application/octet-stream",
        "uri": "file:///tmp/payload.bin",
        "source_origin": SourceOrigin.UPLOAD,
        "sensitivity_label": SensitivityLabel.INTERNAL,
        "project_id": PROJECT_ID,
    }
    fields.update(overrides)
    return Artifact.from_bytes(data, **fields)


def make_source_work(**overrides: Any) -> SourceWork:
    fields: dict[str, Any] = {
        "work_type": SourceWorkType.JOURNAL_ARTICLE,
        "title": "A measurement of something",
        "trust_class": TrustClass.PEER_REVIEWED,
        "identifiers": (WorkIdentifier(scheme="doi", value="10.1000/Example.1"),),
    }
    fields.update(overrides)
    return SourceWork(**fields)


def make_claim(**overrides: Any) -> Claim:
    fields: dict[str, Any] = {
        "normalized_proposition": "quantity X increases with parameter Y",
        "domain": "toy",
    }
    fields.update(overrides)
    return Claim(**fields)


def make_observation(**overrides: Any) -> Observation:
    fields: dict[str, Any] = {
        "artifact_id": make_artifact().artifact_id,
        "metric_or_event": "toy_metric",
        "conditions": {"setting": "nominal"},
        "conditions_schema_version": TOY_SCHEMA_REF,
        "method_ref": f"{EXTRACTOR_ID}@{EXTRACTOR_VERSION}",
        "project_id": PROJECT_ID,
    }
    fields.update(overrides)
    return Observation(**fields)


def make_extraction_provenance(**overrides: Any) -> ExtractionProvenance:
    fields: dict[str, Any] = {
        "extractor_id": EXTRACTOR_ID,
        "extractor_version": EXTRACTOR_VERSION,
    }
    fields.update(overrides)
    return ExtractionProvenance(**fields)


def make_attestation(**overrides: Any) -> Attestation:
    provenance = overrides.pop("extraction_provenance", make_extraction_provenance())
    fields: dict[str, Any] = {
        "claim_id": "clm:test",
        "epistemic_type": EpistemicType.REPORTED,
        "source_work_id": "swk:test",
        "locator": "p.3, table 2",
        "conditions": {"setting": "nominal"},
        "conditions_schema_version": TOY_SCHEMA_REF,
        "project_id": PROJECT_ID,
        "extractor_version": provenance.extractor_version,
        "extraction_provenance": provenance,
    }
    fields.update(overrides)
    return Attestation(**fields)


def make_relation(**overrides: Any) -> RelationJudgment:
    fields: dict[str, Any] = {
        "from_entity_id": "att:a",
        "to_entity_id": "hyp:b",
        "relation_type": RelationType.SUPPORTS,
        "project_id": PROJECT_ID,
        "supporting_attestation_ids": ("att:a",),
    }
    fields.update(overrides)
    return RelationJudgment(**fields)


__all__ = [
    "EXTRACTOR_ID",
    "EXTRACTOR_VERSION",
    "PROJECT_ID",
    "TOY_COMPARATOR_VERSION",
    "TOY_SCHEMA",
    "TOY_SCHEMA_REF",
    "TOY_SCHEMA_V2",
    "make_artifact",
    "make_attestation",
    "make_claim",
    "make_extraction_provenance",
    "make_observation",
    "make_relation",
    "make_source_work",
    "registry_with_toy_schema",
]
