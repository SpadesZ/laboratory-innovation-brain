"""The user's documents as citable evidence: verbatim statements, admitted through M1's gate.

    §6.2  Claim / Observation / Attestation 分離
    EVI-010  the canonical evidence body is the unit; a retrieval payload cannot alter it

WHY THIS STEP EXISTS. Ingestion stores a document and segments it into EvidenceUnits; the debate
cites ATTESTATIONS (§17.14.1's bundles name attestation ids, and a genesis belief event resolves
each one by foreign key). Between the two, something must say "this document states this". Here
that is the least interpretive statement possible: one REPORTED attestation per unit, whose claim
is the unit's own canonical text -- verbatim, no paraphrase, no model. The extractor is named and
versioned (`research.verbatim_statement@1.0.0`) so §6.18 can quarantine everything it produced.

EVERY STATEMENT GOES THROUGH `IngestionService.admission_gate`. The unit is loaded by identity, the
actor's read is authorized by the same ScientificReadGate every scientific read uses, the unit is
re-derived from the document's own stored bytes (EVI-010's segmentation re-verification), and the
claimed body must equal the canonical one. Nothing here decides admissibility.

WHAT IT DOES NOT CLAIM. Every statement is REPORTED -- the document reports it; the lab did not
measure anything by uploading a file. The trust class a file's statements carry in retrieval is the
one the USER declared for that file (a measurement record, a simulation record, notes), recorded on
the report; the system does not infer it. Conditions are not stated in a free-text unit, so the
statements use `core/document_statement@1.0.0`, which declares no condition fields: condition-aware
reasoning never treats them as matched to anything.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lab_brain.composition import IngestionService
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation, ExtractionProvenance
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.condition import ConditionSchemaRegistration
from lab_brain.core.models.enums import EpistemicType, TrustClass
from lab_brain.ingestion.admission_gate import AdmissionRequest
from lab_brain.ingestion.reverification import SegmentationReverifier

EXTRACTOR_ID = "research.verbatim_statement"
EXTRACTOR_VERSION = "1.0.0"

DOCUMENT_STATEMENT_SCHEMA = ConditionSchemaRegistration(
    domain="core",
    schema_id="document_statement",
    version="1.0.0",
    comparator_version="1.0.0",
    json_schema={
        "type": "object",
        "description": (
            "A verbatim statement read from a document. Its conditions are not stated in a "
            "machine-readable form, so none are recorded."
        ),
        "properties": {},
        "additionalProperties": False,
    },
)
DOCUMENT_STATEMENT_SCHEMA_REF = "core/document_statement@1.0.0"


@dataclass(frozen=True)
class AdmittedStatement:
    """One admitted verbatim statement, as the report and the evidence catalog read it."""

    attestation_id: str
    claim_id: str
    project_id: str
    artifact_id: str
    evidence_unit_id: str
    locator: str
    text: str
    trust_class: TrustClass
    source_name: str
    source_work_id: str | None = None


class StatementAdmitter:
    """Admit a document's units as REPORTED statements. See the module docstring."""

    def __init__(
        self,
        *,
        service: IngestionService,
        load_artifact: Callable[[str], Artifact | None],
        read_bytes: Callable[[str], bytes | None],
        claims: Any,
        attestations: Any,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._service = service
        self._load_artifact = load_artifact
        self._read_bytes = read_bytes
        self._claims = claims
        self._attestations = attestations
        self._mint = mint
        self._now = now

    def admit(
        self,
        *,
        project_id: str,
        actor_id: str,
        artifact_id: str,
        trust_class: TrustClass,
        source_name: str,
    ) -> tuple[AdmittedStatement, ...]:
        """Every unit of one document this actor may read, admitted, in document order."""
        gate = self._service.admission_gate(
            actor_id=actor_id,
            load_artifact=self._load_artifact,
            resegment=SegmentationReverifier(self._read_bytes),
        )
        units = sorted(
            (
                authorized
                for authorized in self._service.evidence_for(
                    actor_id=actor_id, project_id=project_id
                )
                if authorized.unit.artifact_id == artifact_id
            ),
            key=lambda a: (a.unit.structural_path, a.unit.evidence_unit_id),
        )
        admitted: list[AdmittedStatement] = []
        for authorized in units:
            unit = authorized.unit
            if not unit.body.strip():
                continue
            at = self._now()
            claim = self._claims.add(
                Claim(claim_id=self._mint("claim"), normalized_proposition=unit.body)
            )
            attestation = Attestation(
                attestation_id=self._mint("attestation"),
                claim_id=claim.claim_id,
                epistemic_type=EpistemicType.REPORTED,
                source_artifact_id=artifact_id,
                locator=unit.locator.label,
                evidence_unit_id=unit.evidence_unit_id,
                conditions={},
                conditions_schema_version=DOCUMENT_STATEMENT_SCHEMA_REF,
                project_id=project_id,
                extractor_version=EXTRACTOR_VERSION,
                extraction_provenance=ExtractionProvenance(
                    extractor_id=EXTRACTOR_ID,
                    extractor_version=EXTRACTOR_VERSION,
                    extracted_at=at,
                    notes=f"verbatim unit of {source_name}, admitted for {actor_id}",
                ),
                created_at=at,
            )
            stored = self._attestations.add(
                gate.admit(
                    AdmissionRequest(
                        attestation=attestation,
                        evidence_unit_id=unit.evidence_unit_id,
                        claimed_body=unit.body,
                    )
                )
            )
            admitted.append(
                AdmittedStatement(
                    attestation_id=stored.attestation_id,
                    claim_id=claim.claim_id,
                    project_id=project_id,
                    artifact_id=artifact_id,
                    evidence_unit_id=unit.evidence_unit_id,
                    locator=unit.locator.label,
                    text=unit.body,
                    trust_class=trust_class,
                    source_name=source_name,
                )
            )
        return tuple(admitted)


__all__ = [
    "DOCUMENT_STATEMENT_SCHEMA",
    "DOCUMENT_STATEMENT_SCHEMA_REF",
    "EXTRACTOR_ID",
    "EXTRACTOR_VERSION",
    "AdmittedStatement",
    "StatementAdmitter",
]
