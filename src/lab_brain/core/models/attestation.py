"""Attestation — a named source's witness of a Claim or Observation (§17.2, §17.9).

The load-bearing rule is in the spec as a one-line negative:

    No support_targets[] / contradict_targets[] here. Those are RelationJudgments.

It is enforced structurally below. An Attestation says "this source, at this locator, under
these conditions, reports this". It does not say what that *implies* about any hypothesis --
that is a RelationJudgment, which carries its own provenance and can be retracted independently
(SYS-001).

Field-level status is the other half. A record does not get one confidence score; every
important field carries its own status, so an extractor can say UNKNOWN about bias while being
EXPLICIT about wavelength instead of guessing to fill the schema (P14 / EVI-002).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.condition import ConditionSchemaRef
from lab_brain.core.models.enums import (
    HIGH_WEIGHT_FIELD_STATUSES,
    EpistemicType,
    ExtractionStatus,
    FieldStatus,
    VerificationStatus,
)
from lab_brain.core.models.identifiers import new_id


class EvidenceField(CoreModel):
    """§17.9. One condition or parameter, with its own provenance status."""

    name: str
    value: Any = None
    unit: str | None = None
    status: FieldStatus
    #: Where in the source this came from -- page, table, figure, equation. Without it an
    #: EXPLICIT claim cannot be audited back to the document.
    locator: str | None = None
    #: How a DERIVED value was computed.
    derivation: str | None = None
    source_refs: tuple[str, ...] = ()
    #: ReviewItem reference (§17.9). A field-level review is a queued item with stakes and an
    #: SLA, not a free-floating status string.
    review_id: str | None = None

    @model_validator(mode="after")
    def _absent_statuses_carry_no_value(self) -> Self:
        """UNKNOWN and NOT_REPORTED must not carry a value.

        A value sitting behind an UNKNOWN status is exactly the hallucinated completion EVI-002
        forbids: the status says "we do not know" while the field offers something to read.
        """
        if (
            self.status in {FieldStatus.UNKNOWN, FieldStatus.NOT_REPORTED}
            and self.value is not None
        ):
            raise ValueError(
                f"field {self.name!r} has status {self.status} but carries a value "
                f"{self.value!r}; absent fields must be empty, not filled with a guess"
            )
        if self.status is FieldStatus.EXPLICIT and self.value is None:
            raise ValueError(
                f"field {self.name!r} is EXPLICIT but has no value; an explicit field with "
                "nothing in it should be NOT_REPORTED"
            )
        if self.status is FieldStatus.DERIVED and self.derivation is None:
            raise ValueError(
                f"field {self.name!r} is DERIVED but records no derivation; the value cannot "
                "be recomputed or audited"
            )
        return self

    @property
    def is_high_weight(self) -> bool:
        """§6.3: only EXPLICIT / VERIFIED_DERIVED may carry high weight in filtering."""
        return self.status in HIGH_WEIGHT_FIELD_STATUSES

    @property
    def is_original_evidence(self) -> bool:
        """INFERRED must be marked as non-original (§6.3)."""
        return self.status is not FieldStatus.INFERRED


class Uncertainty(CoreModel):
    """Reported uncertainty, kept structured so it is not lost into a display string."""

    kind: str
    value: float | None = None
    unit: str | None = None
    confidence_level: float | None = Field(default=None, gt=0, lt=1)
    note: str | None = None


class ExtractionProvenance(CoreModel):
    """How this attestation was produced, so a bad extractor version can be quarantined.

    §6.18's contamination rollback selects by ``extractor_version``: quarantine everything that
    version produced, replay the belief events without it, and compare. That is only possible
    if every attestation records which extractor made it.
    """

    extractor_id: str
    extractor_version: str
    #: Set only when an LLM produced this; links to InferenceProvenance (LLM-001, M1).
    inference_provenance_id: str | None = None
    extracted_at: dt.datetime = Field(default_factory=utc_now)
    stage: ExtractionStatus = ExtractionStatus.STAGE_A_METADATA
    notes: str | None = None


#: Field names that would create a second, unversioned source of truth for support and
#: contradiction. Rejected structurally here and checked statically by T-SYS-001 (M0b).
FORBIDDEN_RELATION_FIELDS = frozenset(
    {
        "support_targets",
        "contradict_targets",
        "supports",
        "contradicts",
        "evidence_for",
        "evidence_against",
        "triggering_evidence_ids",
    }
)


class Attestation(CoreModel):
    """A named source's witness of a Claim or an Observation."""

    attestation_id: str = Field(default_factory=lambda: new_id("attestation"))

    #: Exactly one subject. An attestation witnesses a proposition or a concrete observation,
    #: never both -- which of the two it is determines how corroboration counts it.
    claim_id: str | None = None
    observation_id: str | None = None

    #: P3 / EVI-003. INFERRED can never be promoted to a factual type. Stored on the record
    #: rather than inferred from the source kind, so the admission gate has something to check.
    epistemic_type: EpistemicType

    #: Exactly one source. "Which source said this" is the whole point of the object.
    source_artifact_id: str | None = None
    source_work_id: str | None = None
    run_id: str | None = None

    #: Where in the source. A claim without a locator cannot be re-checked by a human.
    locator: str

    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str
    #: Per-field status, keyed by field name (§6.3).
    field_states: dict[str, EvidenceField] = Field(default_factory=dict)

    units: str | None = None
    uncertainty: Uncertainty | None = None
    #: How the source obtained the value, as reported by the source.
    method: dict[str, Any] = Field(default_factory=dict)

    extraction_status: ExtractionStatus = ExtractionStatus.STAGE_A_METADATA
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    #: Domain-supplied authority class, compared by AuthorityPolicy (ADR-0007). Core never
    #: orders these values itself.
    authority_class: str | None = None

    project_id: str
    extractor_version: str
    extraction_provenance: ExtractionProvenance
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _exactly_one_subject(self) -> Self:
        subjects = [self.claim_id, self.observation_id]
        if len([subject for subject in subjects if subject is not None]) != 1:
            raise ValueError(
                "Attestation requires exactly one of claim_id or observation_id; got "
                f"claim_id={self.claim_id!r}, observation_id={self.observation_id!r}"
            )
        return self

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        sources = [self.source_artifact_id, self.source_work_id, self.run_id]
        if len([source for source in sources if source is not None]) != 1:
            raise ValueError(
                "Attestation requires exactly one of source_artifact_id, source_work_id or "
                f"run_id; got artifact={self.source_artifact_id!r}, "
                f"work={self.source_work_id!r}, run={self.run_id!r}"
            )
        return self

    @model_validator(mode="after")
    def _field_states_are_keyed_by_their_own_name(self) -> Self:
        mismatched = [
            f"{key} != {field.name}"
            for key, field in self.field_states.items()
            if key != field.name
        ]
        if mismatched:
            raise ValueError(f"field_states keys must match EvidenceField.name: {mismatched}")
        return self

    @model_validator(mode="after")
    def _condition_schema_ref_is_wellformed(self) -> Self:
        ConditionSchemaRef.parse(self.conditions_schema_version)
        return self

    @model_validator(mode="after")
    def _extractor_version_agrees_with_provenance(self) -> Self:
        """Two places record the extractor version; disagreement breaks quarantine selection."""
        if self.extractor_version != self.extraction_provenance.extractor_version:
            raise ValueError(
                f"extractor_version {self.extractor_version!r} disagrees with "
                f"extraction_provenance.extractor_version "
                f"{self.extraction_provenance.extractor_version!r}; quarantine by version "
                "would miss records where these differ"
            )
        return self

    @property
    def schema_ref(self) -> ConditionSchemaRef:
        return ConditionSchemaRef.parse(self.conditions_schema_version)

    @property
    def is_inference(self) -> bool:
        """EVI-003: an inference may never be admitted as factual evidence."""
        return self.epistemic_type is EpistemicType.INFERRED

    @property
    def subject_id(self) -> str:
        subject = self.claim_id or self.observation_id
        assert subject is not None  # guaranteed by _exactly_one_subject
        return subject

    @property
    def source_id(self) -> str:
        source = self.source_artifact_id or self.source_work_id or self.run_id
        assert source is not None  # guaranteed by _exactly_one_source
        return source

    def unknown_fields(self) -> tuple[str, ...]:
        """Fields the extractor declined to fill. Surfaced, not hidden (§6.4)."""
        return tuple(
            sorted(
                name
                for name, field in self.field_states.items()
                if field.status in {FieldStatus.UNKNOWN, FieldStatus.NOT_REPORTED}
            )
        )

    def high_weight_fields(self) -> tuple[str, ...]:
        return tuple(
            sorted(name for name, field in self.field_states.items() if field.is_high_weight)
        )


__all__ = [
    "FORBIDDEN_RELATION_FIELDS",
    "Attestation",
    "EvidenceField",
    "ExtractionProvenance",
    "Uncertainty",
]
