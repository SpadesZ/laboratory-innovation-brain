"""Shared fixtures for the G0 round-5 suites (not a test module)."""

from __future__ import annotations

from typing import Any

from lab_brain.core.repositories.conditions import SqlConditionSchemaStore
from lab_brain.core.repositories.evidence import SqlAttestationStore
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.repositories.source_works import SqlClaimStore, SqlSourceWorkStore
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF, registration
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.sources.admission import ExternalEvidenceAdmission
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.external_artifacts import SqlExternalArtifactSink
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from tests.external_fixtures import ACTOR, T0, build

CONDITIONS = {"bias_v": "-2", "frequency_hz": "1000000000", "device_length_um": "500"}


def external_attestation(db: Any, project_id: str) -> str:
    """An attestation admitted in `project_id` from a public literature snapshot, through the
    product's external admission (`002d`); its snapshot is not quarantined (yet)."""
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'r')"
        " ON CONFLICT DO NOTHING",
        (ACTOR,),
    )
    SqlConditionSchemaStore(db).ensure(registration())
    world = build(
        store=SqlExternalSourceStore(db),
        sink=SqlExternalArtifactSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0),
        project_id=project_id,
    )
    evidence = SqlEvidenceSink(connection=db, outputs=None)  # type: ignore[arg-type]
    admission = ExternalEvidenceAdmission(
        snapshots=world.store,
        works=SqlSourceWorkStore(db),
        claims=SqlClaimStore(db),
        attestations=SqlAttestationStore(db),
        gate=EvidenceAdmissionGate(
            load_artifact=evidence.load_artifact, load_evidence_unit=lambda _u: None
        ),
        mint=world.mint,
        now=world.clock,
    )
    snapshot = world.service.snapshot(
        "literature", "doi:10.5555/sp.2019.041#p3", project_id=project_id, actor_id=ACTOR
    )
    admitted = admission.admit(
        snapshot,
        proposition="Rs per length is normalised by the drawn length",
        fragment="Results",
        conditions=CONDITIONS,
        conditions_schema_version=SCHEMA_REF,
        actor_id=ACTOR,
    )
    return str(admitted.attestation.attestation_id)
