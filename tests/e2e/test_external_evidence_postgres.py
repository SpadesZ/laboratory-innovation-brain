"""M5 end to end on PostgreSQL: external evidence enters with source/condition/rights/provenance
metadata, GitHub material traces to repository + resolved commit, and technical material is never
promoted (M5 exit gate, GH-001, GH-003 / T-GH-003, EVI-008)."""

from __future__ import annotations

import json

import pytest

from lab_brain.core.models.enums import (
    EpistemicType,
    ExtractionStatus,
    SourceWorkStatus,
    SourceWorkType,
    TrustClass,
)
from lab_brain.core.repositories.conditions import SqlConditionSchemaStore
from lab_brain.core.repositories.evidence import SqlAttestationStore
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.repositories.source_works import SqlClaimStore, SqlSourceWorkStore
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF, registration
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.sources.admission import ExternalAdmissionRefused, ExternalEvidenceAdmission
from lab_brain.sources.errors import ConnectorError
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.external_artifacts import SqlExternalArtifactSink
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from tests.external_fixtures import (
    ACTOR,
    MAIN_COMMIT,
    PROJECT,
    PUBLIC_REPO,
    REMOVABLE_REPO,
    T0,
    UNLICENSED_REPO,
    build,
    file_locator,
)

pytestmark = pytest.mark.postgres

CONDITIONS = {"bias_v": "-2", "frequency_hz": "1000000000", "device_length_um": "500"}


def _world(db):  # type: ignore[no-untyped-def]
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'M5')", (PROJECT,))
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'r')",
        (ACTOR,),
    )
    SqlConditionSchemaStore(db).ensure(registration())
    world = build(
        store=SqlExternalSourceStore(db),
        sink=SqlExternalArtifactSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0),
        works=SqlSourceWorkStore(db),
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
    return world, admission


def _admit(world, admission, provider: str, locator: str, **kw):  # type: ignore[no-untyped-def]
    snapshot = world.service.snapshot(provider, locator, project_id=PROJECT, actor_id=ACTOR)
    return admission.admit(
        snapshot,
        proposition=kw.pop("proposition", "Rs per length is normalised by the drawn length"),
        fragment=kw.pop("fragment", "L3-L5"),
        conditions=CONDITIONS,
        conditions_schema_version=SCHEMA_REF,
        actor_id=ACTOR,
        **kw,
    )


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_external_evidence_enters_with_source_condition_rights_and_provenance(db):
    world, admission = _world(db)
    admitted = _admit(
        world, admission, "github", file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py")
    )
    row = db.execute(
        "SELECT a.epistemic_type, a.locator, a.conditions, a.conditions_schema_version,"
        " a.method, w.work_type, w.trust_class, w.canonical_locator"
        " FROM attestations a JOIN source_works w ON w.source_work_id = a.source_work_id"
        " WHERE a.attestation_id = %s",
        (admitted.attestation.attestation_id,),
    ).fetchone()
    epistemic, locator, conditions, schema, method, work_type, trust, canonical = row
    method = method if isinstance(method, dict) else json.loads(method)
    # source
    assert (work_type, trust) == ("SOFTWARE_REPOSITORY", "TECHNICAL_ARTIFACT")
    assert canonical == file_locator(PUBLIC_REPO, MAIN_COMMIT, "extract/rs_extraction.py")
    assert locator.startswith(canonical) and locator.endswith("#L3-L5")
    identifiers = db.execute(
        "SELECT scheme, value FROM source_work_identifiers WHERE source_work_id = %s",
        (admitted.source_work.source_work_id,),
    ).fetchall()
    assert identifiers == [("github-repository", "github:repository/7001")]
    # condition
    assert conditions == CONDITIONS and schema == SCHEMA_REF
    # rights
    assert method["license_class"] == "PERMISSIVE" and method["rights_status"] == "licence:MIT"
    assert method["retention"] == "FULL_CONTENT"
    # provenance: repository + resolved commit + retrieval time + content/snapshot hash (§22)
    assert method["resolved_ref"] == MAIN_COMMIT
    assert method["snapshot_id"] == admitted.snapshot.snapshot_id
    assert method["content_hash"] == admitted.snapshot.content_hash
    assert method["retrieved_at"] and method["artifact_id"] == admitted.snapshot.artifact_id
    assert epistemic == "REPORTED"
    kinds = [e.kind.value for e in world.store.events(PROJECT)]
    assert kinds[-2:] == ["SNAPSHOTTED", "ADMITTED"]


@pytest.mark.requirement("GH-003")
@pytest.mark.spec_test("T-GH-003")
def test_a_github_record_is_technical_and_cannot_pose_as_measured_or_peer_reviewed(db):
    world, admission = _world(db)
    locator = file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py")
    with pytest.raises(ExternalAdmissionRefused) as refused:
        _admit(world, admission, "github", locator, epistemic_type=EpistemicType.MEASURED)
    assert refused.value.reason_code == "TECHNICAL_EVIDENCE_PROMOTION"
    admitted = _admit(world, admission, "github", locator)
    assert admitted.source_work.trust_class is TrustClass.TECHNICAL_ARTIFACT
    assert admitted.source_work.work_type is SourceWorkType.SOFTWARE_REPOSITORY
    # Any writer of SQL meets the same rule.
    with pytest.raises(Exception, match="GH-003"):
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_work_id,"
            " locator, conditions, conditions_schema_version, project_id, extractor_version,"
            " extraction_provenance) VALUES ('att:forged', %s, 'MEASURED', %s, 'l', %s::jsonb,"
            " %s, %s, '1', '{}'::jsonb)",
            (
                admitted.claim.claim_id,
                admitted.source_work.source_work_id,
                json.dumps(CONDITIONS),
                SCHEMA_REF,
                PROJECT,
            ),
        )
    with pytest.raises(Exception, match="GH-003"):
        db.execute(
            "INSERT INTO source_works (source_work_id, work_type, title, trust_class)"
            " VALUES ('swk:forged', 'SOFTWARE_REPOSITORY', 'x', 'PEER_REVIEWED')"
        )
    # A caller-assembled snapshot is not admitted: provenance comes from the record.
    forged = admitted.snapshot.model_copy(
        update={"trust_class": TrustClass.TECHNICAL_ARTIFACT, "retention_rule": "edited"}
    )
    with pytest.raises(ExternalAdmissionRefused, match="SNAPSHOT_NOT_ON_RECORD"):
        admission.admit(
            forged,
            proposition="p",
            fragment="f",
            conditions=CONDITIONS,
            conditions_schema_version=SCHEMA_REF,
            actor_id=ACTOR,
        )


def test_literature_evidence_is_peer_reviewed_only_when_it_is_and_its_status_is_recorded(db):
    world, admission = _world(db)
    paper = _admit(
        world,
        admission,
        "literature",
        "doi:10.5555/sp.2019.041#p3",
        proposition="normalising by the taper-inclusive length overstates Rs per length",
        fragment="Results,p4",
        retraction_status=SourceWorkStatus.ACTIVE,
    )
    assert paper.source_work.trust_class is TrustClass.PEER_REVIEWED
    assert paper.source_work.work_type is SourceWorkType.JOURNAL_ARTICLE
    second = _admit(world, admission, "literature", "doi:10.5555/sp.2019.041#p5")
    assert second.source_work.source_work_id == paper.source_work.source_work_id, "one work"
    retracted = _admit(
        world,
        admission,
        "literature",
        "doi:10.5555/sp.2018.007#p1",
        retraction_status=SourceWorkStatus.RETRACTED,
    )
    stored = SqlSourceWorkStore(db).get(retracted.source_work.source_work_id)
    assert stored is not None and stored.retraction_check.status is SourceWorkStatus.RETRACTED
    preprint = _admit(world, admission, "literature", "doi:10.5555/sp.2021.113#p2")
    assert preprint.source_work.work_type is SourceWorkType.PREPRINT


def test_a_removed_repository_is_recorded_source_unavailable_and_its_snapshot_still_admits(db):
    world, admission = _world(db)
    locator = file_locator(REMOVABLE_REPO, "main", "mesh.py")
    kept = world.service.snapshot("github", locator, project_id=PROJECT, actor_id=ACTOR)
    world.transport.remove(REMOVABLE_REPO)
    with pytest.raises(ConnectorError):
        world.service.snapshot("github", locator, project_id=PROJECT, actor_id=ACTOR)
    admitted = admission.admit(
        kept,
        proposition="the legacy mesh edge was 5 nm",
        fragment="L1",
        conditions=CONDITIONS,
        conditions_schema_version=SCHEMA_REF,
        actor_id=ACTOR,
    )
    work = SqlSourceWorkStore(db).get(admitted.source_work.source_work_id)
    assert work is not None
    assert work.retraction_check.status is SourceWorkStatus.SOURCE_UNAVAILABLE
    assert world.sink.read(kept.artifact_id) == b"EDGE_NM = 5\n"


def test_the_enrichment_stage_is_bounded_by_what_the_snapshot_kept_for_every_writer(db):
    """§6.4 in SQL: a row naming its snapshot cannot claim a depth the kept material lacks."""
    world, admission = _world(db)
    kept_metadata = _admit(
        world, admission, "github", file_locator(UNLICENSED_REPO, "main", "rs.py")
    )
    assert kept_metadata.snapshot.retention.value == "METADATA_ONLY"
    assert kept_metadata.attestation.extraction_status is ExtractionStatus.STAGE_A_METADATA
    method = dict(kept_metadata.attestation.method)

    def forge(attestation_id: str, stage: str, project: str = PROJECT) -> None:
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_work_id,"
            " locator, conditions, conditions_schema_version, project_id, extractor_version,"
            " extraction_provenance, method, extraction_status) VALUES (%s, %s, 'REPORTED', %s,"
            " 'l', %s::jsonb, %s, %s, '1', '{}'::jsonb, %s::jsonb, %s)",
            (
                attestation_id,
                kept_metadata.claim.claim_id,
                kept_metadata.source_work.source_work_id,
                json.dumps(CONDITIONS),
                SCHEMA_REF,
                project,
                json.dumps(method),
                stage,
            ),
        )

    for stage in ("STAGE_B_STRUCTURED", "STAGE_C_DEEP", "STAGE_D_HUMAN_VERIFIED"):
        with pytest.raises(Exception, match="a stage is claimable"):
            forge(f"att:forged-{stage}", stage)
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:other', 'other')")
    with pytest.raises(Exception, match="cites external snapshot"):
        forge("att:elsewhere", "STAGE_A_METADATA", project="prj:other")
    forge("att:honest", "STAGE_A_METADATA")


def test_a_repository_removed_after_admission_leaves_its_work_source_unavailable(db):
    """The status lands on the stored work when the removal is observed (§6.16, EVI-008)."""
    world, admission = _world(db)
    locator = file_locator(REMOVABLE_REPO, "main", "mesh.py")
    admitted = _admit(world, admission, "github", locator, proposition="mesh edge is 5 nm")
    before = SqlSourceWorkStore(db).get(admitted.source_work.source_work_id)
    assert before is not None and before.retraction_check.status is SourceWorkStatus.UNKNOWN
    world.transport.remove(REMOVABLE_REPO)
    with pytest.raises(ConnectorError):
        world.service.snapshot("github", locator, project_id=PROJECT, actor_id=ACTOR)
    after = SqlSourceWorkStore(db).get(admitted.source_work.source_work_id)
    assert after is not None
    assert after.retraction_check.status is SourceWorkStatus.SOURCE_UNAVAILABLE
    assert after.retraction_check.notice_locator == admitted.snapshot.canonical_locator
