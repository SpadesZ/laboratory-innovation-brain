"""External evidence admission: a snapshot becomes a SourceWork, a Claim and a REPORTED Attestation.

    GH-003    GitHub technical/prior-art evidence 不得自動升級為 peer-reviewed scientific
              evidence；repo/ref/commit 必須保存。
    T-GH-003  GitHub record 能被標為 technical/prior-art source；admission gate 不允許其自動冒充
              measured/peer-reviewed evidence。
    EVI-008   external reported evidence 的 version/retraction 檢查狀態 MUST 被記錄。
    §6.4      Stage A metadata → B 結構抽取 → C 深度補強 → D 人工確認；Stage 之間必須可停留，
              未完成的 stage 以 UNKNOWN 呈現，不得由模型補值。
    M5 gate   external evidence enters with source/condition/rights/provenance metadata.

THE LAST STEP OF PROGRESSIVE ENRICHMENT, AND A SEPARATE ONE. Discovery records metadata; a snapshot
pins and keeps; admission is a person's (or a workflow's) statement of what the material says, and
only then does it become evidence. Each step is its own authorized, recorded act.

THE STAGE AN ADMISSION MAY CLAIM IS BOUNDED BY WHAT WAS KEPT (§6.4). The attestation records the
enrichment stage it was drawn at, and a stage is only claimable if the kept material can be re-read
at that depth: a METADATA_ONLY snapshot supports Stage A and nothing more, an EXCERPT supports at
most Stage B, and only FULL_CONTENT supports Stage C. Stage D is never claimed on admission -- it is
a later human verification of an admitted attestation, not something an admission can assert about
itself. The default is Stage A, so an admission that says nothing about depth claims the least.

WHAT EXTERNAL MATERIAL CAN BE. Another party's report: `REPORTED`, and nothing else. The lab did
not measure, simulate or observe it, so MEASURED / SIMULATED / OBSERVED are refused for every
external snapshot, and a technical source (a code host) can in addition never carry a trust class
above TECHNICAL_ARTIFACT -- the snapshot, the work and the attestation all say so, and `002c`
refuses the attestation for any writer of SQL that tries otherwise.

EVERY ADMITTED ITEM CARRIES THE FOUR KINDS OF METADATA THE GATE NAMES.

    source       the SourceWork (work type, identifiers, trust class) and the pinned locator
    condition    the Attestation's `conditions` + `conditions_schema_version` -- required; EVI-005's
                 payload validation runs in the database for every writer
    rights       the snapshot's licence class, identifier, rights status and retention rule
    provenance   snapshot id, artifact id, content hash, resolved version, retrieval time, access
                 policy -- on the Attestation's `method`, and the snapshot row they name

SAME WORK, ONE WORK (EVI-004). A repository is one work however many commits and files are cited
from it; a paper is one work however many passages. The work is found by identifier first and
reused, so corroboration counting cannot see two sources where there is one.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from lab_brain.core.models.attestation import Attestation, ExtractionProvenance
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.enums import (
    EpistemicType,
    ExtractionStatus,
    SourceWorkStatus,
    SourceWorkType,
    TrustClass,
)
from lab_brain.core.models.external_source import (
    TECHNICAL_SOURCE_TYPES,
    ExternalSnapshot,
    ExternalSourceEvent,
    ExternalSourceEventKind,
    Retention,
)
from lab_brain.core.models.source_work import RetractionCheck, SourceWork, WorkIdentifier
from lab_brain.core.repositories.external_sources import ExternalSourceStore
from lab_brain.ingestion.admission_gate import AdmissionRequest
from lab_brain.sources.external import ConnectorRefusal

ADMISSION_VERSION = "external-admission@1.0.0"

#: The deepest §6.4 stage each retention can support. Stage D is a later human act, never here.
STAGE_CEILING: Mapping[Retention, ExtractionStatus] = {
    Retention.METADATA_ONLY: ExtractionStatus.STAGE_A_METADATA,
    Retention.EXCERPT: ExtractionStatus.STAGE_B_STRUCTURED,
    Retention.FULL_CONTENT: ExtractionStatus.STAGE_C_DEEP,
}
_STAGE_ORDER = tuple(ExtractionStatus)


class ExternalAdmissionRefused(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class WorkStore(Protocol):
    def add(self, work: SourceWork) -> SourceWork: ...

    def find_by_identifier(self, scheme: str, value: str) -> SourceWork | None: ...

    def record_status(self, source_work_id: str, check: RetractionCheck) -> None: ...


class ClaimSink(Protocol):
    def add(self, claim: Claim) -> Claim: ...


class AttestationSink(Protocol):
    def add(self, attestation: Attestation) -> Attestation: ...


class Gate(Protocol):
    def admit(self, request: AdmissionRequest) -> Attestation: ...


@dataclass(frozen=True)
class AdmittedExternalEvidence:
    snapshot: ExternalSnapshot
    source_work: SourceWork
    claim: Claim
    attestation: Attestation


#: The work type of external material whose source type names no repository: the kind of thing
#: the provider says it is. Every externally carriable class is here; NON_EXTERNAL_TRUST is not,
#: and cannot reach this (the snapshot model refuses it).
_WORK_TYPE_BY_TRUST: Mapping[TrustClass, SourceWorkType] = {
    TrustClass.PEER_REVIEWED: SourceWorkType.JOURNAL_ARTICLE,
    TrustClass.PREPRINT: SourceWorkType.PREPRINT,
    TrustClass.PATENT: SourceWorkType.PATENT,
    TrustClass.TECHNICAL_ARTIFACT: SourceWorkType.TECHNICAL_REPORT,
    TrustClass.WEB: SourceWorkType.WEB_PAGE,
}


def _work_identity(snapshot: ExternalSnapshot) -> tuple[WorkIdentifier, SourceWorkType, str]:
    identity = snapshot.repository_identity or ""
    if snapshot.source_type in TECHNICAL_SOURCE_TYPES:
        repository = identity.split(" ", 1)
        return (
            WorkIdentifier(scheme=f"{snapshot.provider}-repository", value=repository[0]),
            SourceWorkType.SOFTWARE_REPOSITORY,
            repository[1] if len(repository) > 1 else identity,
        )
    kind = _WORK_TYPE_BY_TRUST[snapshot.trust_class]
    if identity.startswith("doi:"):
        doi = identity.removeprefix("doi:")
        return WorkIdentifier(scheme="doi", value=doi), kind, doi
    return (
        WorkIdentifier(scheme=f"{snapshot.provider}-locator", value=snapshot.canonical_locator),
        kind,
        snapshot.canonical_locator,
    )


class ExternalEvidenceAdmission:
    def __init__(
        self,
        *,
        snapshots: ExternalSourceStore,
        works: WorkStore,
        claims: ClaimSink,
        attestations: AttestationSink,
        gate: Gate,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._snapshots = snapshots
        self._works = works
        self._claims = claims
        self._attestations = attestations
        self._gate = gate
        self._mint = mint
        self._now = now

    def admit(
        self,
        snapshot: ExternalSnapshot,
        *,
        proposition: str,
        fragment: str,
        conditions: Mapping[str, Any],
        conditions_schema_version: str,
        actor_id: str,
        epistemic_type: EpistemicType = EpistemicType.REPORTED,
        domain: str | None = None,
        retraction_status: SourceWorkStatus | None = None,
        stage: ExtractionStatus = ExtractionStatus.STAGE_A_METADATA,
    ) -> AdmittedExternalEvidence:
        durable = self._snapshots.snapshot(snapshot.project_id, snapshot.snapshot_id)
        if durable is None or durable != snapshot:
            raise ExternalAdmissionRefused(
                "SNAPSHOT_NOT_ON_RECORD",
                f"{snapshot.snapshot_id} is not the durable snapshot of that id; external evidence "
                "is admitted from the provenance record, never from an object a caller assembled",
            )
        if epistemic_type is not EpistemicType.REPORTED:
            technical = durable.source_type in TECHNICAL_SOURCE_TYPES
            raise ExternalAdmissionRefused(
                "TECHNICAL_EVIDENCE_PROMOTION" if technical else "EXTERNAL_EVIDENCE_PROMOTION",
                f"{durable.canonical_locator} is another party's material; it is admitted as "
                f"REPORTED, never {epistemic_type.value}"
                + (
                    ". GH-003: technical/prior-art evidence is not measured or peer-reviewed"
                    if technical
                    else ""
                ),
            )
        if not proposition.strip() or not fragment.strip():
            raise ExternalAdmissionRefused(
                "NO_PROPOSITION", "an admission states what the material says, and where in it"
            )
        ceiling = STAGE_CEILING[durable.retention]
        if _STAGE_ORDER.index(stage) > _STAGE_ORDER.index(ceiling):
            raise ExternalAdmissionRefused(
                "STAGE_BEYOND_RETENTION",
                f"{durable.snapshot_id} kept {durable.retention.value}, which supports at most "
                f"{ceiling.value}; {stage.value} would claim a depth nobody can re-read (§6.4)"
                + (
                    ". Stage D is a later human verification, never an admission's own claim"
                    if stage is ExtractionStatus.STAGE_D_HUMAN_VERIFIED
                    else ""
                ),
            )
        identifier, work_type, title = _work_identity(durable)
        unavailable = any(
            e.kind is ExternalSourceEventKind.SOURCE_UNAVAILABLE
            and e.snapshot_id == durable.snapshot_id
            for e in self._snapshots.events(durable.project_id)
        )
        status = (
            SourceWorkStatus.SOURCE_UNAVAILABLE
            if unavailable
            else retraction_status or SourceWorkStatus.UNKNOWN
        )
        check = RetractionCheck(
            status=status,
            checked_at=self._now(),
            checked_against=durable.provider,
        )
        work = self._works.find_by_identifier(identifier.scheme, identifier.value)
        if work is None:
            work = self._works.add(
                SourceWork(
                    source_work_id=self._mint("source_work"),
                    work_type=work_type,
                    title=title,
                    identifiers=(identifier,),
                    canonical_locator=durable.canonical_locator,
                    manifestation_artifact_ids=(durable.artifact_id,),
                    trust_class=durable.trust_class,
                    retraction_check=check,
                    created_at=self._now(),
                )
            )
        else:
            if work.trust_class is not durable.trust_class:
                raise ExternalAdmissionRefused(
                    "TRUST_CLASS_CONFLICT",
                    f"work {work.source_work_id} is {work.trust_class.value} and this snapshot is "
                    f"{durable.trust_class.value}; one work has one kind",
                )
            self._works.record_status(work.source_work_id, check)
        claim = self._claims.add(
            Claim(claim_id=self._mint("claim"), normalized_proposition=proposition, domain=domain)
        )
        attestation = Attestation(
            attestation_id=self._mint("attestation"),
            claim_id=claim.claim_id,
            epistemic_type=EpistemicType.REPORTED,
            source_work_id=work.source_work_id,
            locator=f"{durable.canonical_locator}#{fragment}",
            conditions=dict(conditions),
            conditions_schema_version=conditions_schema_version,
            method={
                "snapshot_id": durable.snapshot_id,
                "artifact_id": durable.artifact_id,
                "content_hash": durable.content_hash,
                "resolved_ref": durable.resolved_ref,
                "retrieved_at": durable.retrieved_at.isoformat(),
                "retention": durable.retention.value,
                "license_class": durable.license_class.value,
                "rights_status": durable.rights_status or "",
                "access_policy": durable.access_policy_ref or "",
            },
            extraction_status=stage,
            project_id=durable.project_id,
            extractor_version=ADMISSION_VERSION.split("@", 1)[1],
            extraction_provenance=ExtractionProvenance(
                extractor_id=ADMISSION_VERSION.split("@", 1)[0],
                extractor_version=ADMISSION_VERSION.split("@", 1)[1],
                extracted_at=self._now(),
                stage=stage,
                notes=f"stated by {actor_id} from {durable.snapshot_id}",
            ),
            created_at=self._now(),
        )
        admitted = self._gate.admit(AdmissionRequest(attestation=attestation))
        stored = self._attestations.add(admitted)
        self._snapshots.add_event(
            ExternalSourceEvent(
                event_id=self._mint("external_source_event"),
                project_id=durable.project_id,
                provider=durable.provider,
                kind=ExternalSourceEventKind.ADMITTED,
                locator_digest=ConnectorRefusal.digest(durable.canonical_locator),
                locator=durable.canonical_locator,
                snapshot_id=durable.snapshot_id,
                actor_id=actor_id,
                detail={
                    "attestation_id": stored.attestation_id,
                    "source_work_id": work.source_work_id,
                    "work_status": status.value,
                },
                occurred_at=self._now(),
            )
        )
        return AdmittedExternalEvidence(
            snapshot=durable, source_work=work, claim=claim, attestation=stored
        )


__all__ = [
    "ADMISSION_VERSION",
    "STAGE_CEILING",
    "AdmittedExternalEvidence",
    "ExternalAdmissionRefused",
    "ExternalEvidenceAdmission",
]
