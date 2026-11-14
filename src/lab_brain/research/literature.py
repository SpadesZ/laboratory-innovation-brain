"""The external-evidence stage: literature discovered, pinned and admitted through M5, unchanged.

    §7.5   DIAGNOSIS: internal first; the Critic's inverted retrieval leaves lab history
           (PEER_REVIEWED, PREPRINT, TECHNICAL_ARTIFACT) -- "避免只相信 lab history"
    §26.1  M5: external evidence enters with source/condition/rights/provenance metadata

ONLY WHEN CONFIGURED, AND ONLY WITH A QUERY THE USER DECLARED PUBLIC. A research goal is project
context (INTERNAL by default); sending it to a literature provider would be exactly the uncontrolled
public search §22 forbids. So this stage runs only when the invoking actor supplies both a provider
and a query they declare PUBLIC -- the sanitized form of the question -- and an egress policy for
this run that approves that one provider for PUBLIC material, declared by that actor and recorded on
the report. Everything after that is M5's: `ConnectorRegistry` (the provider registered project-
neutral), `ExternalSnapshotService` (SEC-001 authorization, pinned retrieval, rights-governed
retention, provenance rows, lifecycle events) and `ExternalEvidenceAdmission` (REPORTED only, the
durable snapshot only, source/condition/rights/provenance metadata).

WHAT IS ADMITTED, AND AS WHAT. The top passages are snapshotted. A passage whose retention kept its
text is admitted as a verbatim REPORTED statement -- the proposition is the kept text itself, the
fragment its section and page -- so the Critic's inverted retrieval can cite it. A passage the
rights policy kept as metadata only is listed and not admitted: there is no text on record to
state. The provider's reported publication status (e.g. RETRACTED) is recorded on the work
(EVI-008) rather than used to filter.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from lab_brain.core.models.enums import SensitivityLabel, SourceWorkStatus, TrustClass
from lab_brain.core.models.external_source import ExternalSnapshot, Retention
from lab_brain.research.evidence import DOCUMENT_STATEMENT_SCHEMA_REF, AdmittedStatement
from lab_brain.security.egress import EgressAuditLog, EgressGate, EgressPolicy, PrivacyMode
from lab_brain.security.external import AuthorizedExternalRunner
from lab_brain.sources.adapter import ExternalSourceAdapter, SourceQuery
from lab_brain.sources.admission import ExternalAdmissionRefused, ExternalEvidenceAdmission
from lab_brain.sources.errors import ConnectorError
from lab_brain.sources.external import ConnectorDeclaration, ConnectorRegistry
from lab_brain.sources.snapshots import ExternalSnapshotService, RetentionPolicy, SnapshotRefused

EGRESS_POLICY_ID = "egp:research-run"
EGRESS_POLICY_VERSION = "1.0.0"


@dataclass(frozen=True)
class LiteratureRequest:
    """A configured provider and the PUBLIC query the actor declared for it."""

    adapter: ExternalSourceAdapter
    declaration: ConnectorDeclaration
    query: str
    #: Where the corpus or service is, for the report ("local corpus file ...").
    description: str
    max_passages: int = 3


@dataclass(frozen=True)
class ConsultedSource:
    snapshot: ExternalSnapshot
    title: str
    status: str | None
    admitted: AdmittedStatement | None
    note: str


@dataclass(frozen=True)
class LiteratureResult:
    provider: str
    description: str
    query: str
    egress_policy: str
    discovered: int
    consulted: tuple[ConsultedSource, ...]
    refusals: tuple[str, ...] = ()
    egress_decisions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def admitted(self) -> tuple[AdmittedStatement, ...]:
        return tuple(c.admitted for c in self.consulted if c.admitted is not None)


def run_literature_stage(
    request: LiteratureRequest,
    *,
    project_id: str,
    actor_id: str,
    clearance: frozenset[SensitivityLabel],
    classifier: Any,
    store: Any,
    sink: Any,
    works: Any,
    claims: Any,
    attestations: Any,
    gate: Any,
    mint: Callable[[str], str],
    now: Callable[[], dt.datetime],
) -> LiteratureResult:
    provider = request.declaration.provider_id
    policy = EgressPolicy(
        policy_id=EGRESS_POLICY_ID,
        version=EGRESS_POLICY_VERSION,
        project_id=project_id,
        mode=PrivacyMode.RESEARCH,
        declared_by_actor_id=actor_id,
        permitted_labels=frozenset({SensitivityLabel.PUBLIC}),
        approved_providers=frozenset({provider}),
    )
    audit = EgressAuditLog()
    runner = AuthorizedExternalRunner(
        gate=EgressGate(
            policy_for=lambda p: policy if p == project_id else None,
            clearance_of=lambda a, p: (
                clearance if (a, p) == (actor_id, project_id) else frozenset()
            ),
        ),
        audit=audit,
    )
    registry = ConnectorRegistry()
    registry.register(request.adapter, request.declaration)
    service = ExternalSnapshotService(
        registry=registry,
        runner=runner,
        classifier=classifier,
        store=store,
        sink=sink,
        retention=RetentionPolicy(),
        mint=mint,
        now=now,
        works=works,
    )
    admission = ExternalEvidenceAdmission(
        snapshots=store,
        works=works,
        claims=claims,
        attestations=attestations,
        gate=gate,
        mint=mint,
        now=now,
    )
    discovered = service.discover(
        SourceQuery(text=request.query, limit=max(10, request.max_passages)),
        project_id=project_id,
        actor_id=actor_id,
        escalate=frozenset({SensitivityLabel.PUBLIC}),
    )
    consulted: list[ConsultedSource] = []
    refusals: list[str] = []
    for record in discovered[: request.max_passages]:
        try:
            snapshot = service.snapshot(
                provider,
                record.canonical_locator,
                project_id=project_id,
                actor_id=actor_id,
                escalate=frozenset({SensitivityLabel.PUBLIC}),
            )
        except (ConnectorError, SnapshotRefused) as refused:
            refusals.append(f"{record.canonical_locator}: {refused}")
            continue
        status = record.metadata.get("status")
        title = record.title or record.canonical_locator
        if snapshot.retention is Retention.METADATA_ONLY:
            consulted.append(
                ConsultedSource(
                    snapshot, title, status, None, "kept as metadata only; no text to admit"
                )
            )
            continue
        text = sink.read(snapshot.artifact_id).decode("utf-8", errors="replace").strip()
        fragment = _fragment(record.metadata)
        try:
            evidence = admission.admit(
                snapshot,
                proposition=text,
                fragment=fragment,
                conditions={},
                conditions_schema_version=DOCUMENT_STATEMENT_SCHEMA_REF,
                actor_id=actor_id,
                retraction_status=_status(status),
            )
        except ExternalAdmissionRefused as refused:
            consulted.append(ConsultedSource(snapshot, title, status, None, str(refused)))
            continue
        consulted.append(
            ConsultedSource(
                snapshot,
                title,
                status,
                AdmittedStatement(
                    attestation_id=evidence.attestation.attestation_id,
                    claim_id=evidence.claim.claim_id,
                    project_id=project_id,
                    artifact_id=snapshot.artifact_id,
                    evidence_unit_id="",
                    locator=evidence.attestation.locator,
                    text=text,
                    trust_class=TrustClass(snapshot.trust_class),
                    source_name=title,
                    source_work_id=evidence.source_work.source_work_id,
                ),
                f"admitted as REPORTED ({snapshot.retention.value.lower()} kept); "
                f"work status {evidence.source_work.retraction_check.status.value}",
            )
        )
    return LiteratureResult(
        provider=provider,
        description=request.description,
        query=request.query,
        egress_policy=f"{EGRESS_POLICY_ID}@{EGRESS_POLICY_VERSION} (declared by {actor_id})",
        discovered=len(discovered),
        consulted=tuple(consulted),
        refusals=tuple(refusals),
        egress_decisions=tuple(
            f"{d.outcome.value} {d.reason_code}: {d.detail}" for d in audit.entries
        ),
    )


def _fragment(metadata: Mapping[str, str]) -> str:
    section = metadata.get("section") or "passage"
    page = metadata.get("page")
    return f"{section}, p.{page}" if page else section


def _status(value: str | None) -> SourceWorkStatus | None:
    if value is None:
        return None
    try:
        return SourceWorkStatus(value)
    except ValueError:
        return None


__all__ = [
    "EGRESS_POLICY_ID",
    "ConsultedSource",
    "LiteratureRequest",
    "LiteratureResult",
    "run_literature_stage",
]
