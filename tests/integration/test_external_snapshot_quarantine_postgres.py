"""GH-002 upgrade safety (`002e`): snapshots written before scopes were bound fail closed.

`002d` checks new writes only. A database that ran the vulnerable M5 code before `002d` can hold
snapshots read for one project under another project's policy, with no scope recorded anywhere. The
upgrade test here builds exactly that database -- migrated to `002c`, seeded with legacy rows by
the only means the old code had (plain INSERTs, no scope check) -- then applies `002d` and `002e`
and checks that every row whose project and access scope cannot be proven coherent is quarantined,
that the provable ones are not, and that quarantined material cannot be used: not admitted, not a
cache hit, not cited by a new relation, bundle or belief event, and selectable for §6.18 replay.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lab_brain.core.models.artifact import RightsMetadata
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel
from lab_brain.core.models.external_source import ExternalAccessScope
from lab_brain.core.repositories.conditions import SqlConditionSchemaStore
from lab_brain.core.repositories.evidence import SqlAttestationStore
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.repositories.source_works import SqlClaimStore, SqlSourceWorkStore
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF, registration
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.sources.admission import ExternalAdmissionRefused, ExternalEvidenceAdmission
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.external_artifacts import SqlExternalArtifactSink
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from tests.external_fixtures import ACTOR, MAIN_COMMIT, PRIVATE_REPO, PUBLIC_REPO, T0, build
from tests.integration.test_belief_events_postgres import PROJECT as BELIEF_PROJECT
from tests.integration.test_belief_events_postgres import _stored, seeded  # noqa: F401
from tests.integration.test_evidence_bundles_postgres import _store as store_bundle
from tests.integration.test_evidence_bundles_postgres import make_bundle
from tests.postgres_fixtures import database_url

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("GH-002"),
    pytest.mark.spec_test("T-GH-002"),
]

ROOT = Path(__file__).resolve().parents[2]
PROJECT_A, PROJECT_B = "prj:A", "prj:B"
CONDITIONS = {"bias_v": "-2", "frequency_hz": "1000000000", "device_length_um": "500"}


def _migrations() -> tuple[Any, ...]:
    spec = importlib.util.spec_from_file_location("lab_brain_migrate", ROOT / "scripts/migrate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return tuple(module.load_migrations())


@pytest.fixture
def scratch() -> Iterator[Any]:
    """A database of its own, migrated to the state before `002d` existed."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import make_conninfo

    name = f"lab_brain_upgrade_{os.getpid()}"
    try:
        admin = psycopg.connect(
            make_conninfo(database_url(), dbname="postgres"), autocommit=True, connect_timeout=5
        )
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable: {type(exc).__name__}")
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            with psycopg.connect(
                make_conninfo(database_url(), dbname=name), autocommit=True
            ) as connection:
                migrations = _migrations()
                names = [m.filename for m in migrations]
                cut = names.index("002d_external_access_scopes.sql")
                for migration in migrations[:cut]:
                    connection.execute(migration.sql)
                connection.migrations_after = migrations[cut:]  # type: ignore[attr-defined]
                yield connection
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _apply(connection: Any, filename: str) -> None:
    (migration,) = [m for m in connection.migrations_after if m.filename == filename]
    connection.execute(migration.sql)


def _artifact(connection: Any, project_id: str, data: bytes, label: SensitivityLabel) -> str:
    sink = SqlExternalArtifactSink(
        connection=connection, store=InMemoryArtifactStore(), now=lambda: T0
    )
    return sink.store(
        project_id=project_id,
        media_type="application/json",
        data=data,
        label=label,
        rights=RightsMetadata(license_class=LicenseClass.UNKNOWN, retrieved_at=T0),
    )


def _legacy(connection: Any, snapshot_id: str, project_id: str, **row: object) -> None:
    """A snapshot as the pre-`002d` code wrote it: a plain INSERT, no scope checked."""
    private = row.get("visibility", "PRIVATE") != "PUBLIC"
    label = SensitivityLabel.CONFIDENTIAL_LAB if private else SensitivityLabel.PUBLIC
    path = row.pop("path", f"{snapshot_id.split(':')[1]}.py")
    repo = row.pop("repo", PRIVATE_REPO)
    values: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "provider": "github",
        "source_type": "code_file",
        "requested_locator": f"github:{repo}@main:{path}",
        "canonical_locator": f"github:{repo}@{MAIN_COMMIT}:{path}",
        "requested_ref": "main",
        "resolved_ref": MAIN_COMMIT,
        "repository_identity": f"github:repository/7002 {repo}",
        "content_hash": "sha256:" + "4" * 64,
        "artifact_id": _artifact(connection, project_id, snapshot_id.encode(), label),
        "retention": "METADATA_ONLY",
        "retention_rule": "legacy",
        "visibility": "PRIVATE",
        "trust_class": "TECHNICAL_ARTIFACT",
        "sensitivity": label.value,
        "license_class": "PROPRIETARY" if private else "UNKNOWN",
        "access_policy_ref": None,
        "retrieved_at": T0,
        "created_at": T0,
    }
    values.update(row)
    connection.execute(
        f"INSERT INTO external_snapshots ({', '.join(values)})"
        f" VALUES ({', '.join(['%s'] * len(values))})",
        tuple(values.values()),
    )


def _scope(connection: Any, policy_ref: str, project_id: str, allowlist: frozenset[str]) -> None:
    SqlExternalSourceStore(connection).record_access_scope(
        ExternalAccessScope(
            policy_ref=policy_ref,
            project_id=project_id,
            provider="github",
            declared_by_actor_id="act:pi",
            private_allowlist=allowlist,
        )
    )


def test_the_upgrade_quarantines_every_legacy_snapshot_it_cannot_prove_and_keeps_the_rest(scratch):
    db = scratch
    for project in (PROJECT_A, PROJECT_B):
        db.execute("INSERT INTO projects (project_id, name) VALUES (%s, %s)", (project, project))
    # --- written by the vulnerable code, before `002d` -----------------------------------
    _legacy(db, "xsn:a-own", PROJECT_A, access_policy_ref="ghp:A@1.0.0")
    _legacy(db, "xsn:b-via-a", PROJECT_B, access_policy_ref="ghp:A@1.0.0")  # the P0 pattern
    _legacy(
        db,
        "xsn:b-unrecorded",
        PROJECT_B,
        repo=PUBLIC_REPO,
        visibility="PUBLIC",
        access_policy_ref="ghp:legacy@1.0.0",
    )
    _legacy(db, "xsn:b-no-scope", PROJECT_B)
    _legacy(
        db,
        "xsn:a-off-list",
        PROJECT_A,
        repo="photonics-lab/other-private",
        access_policy_ref="ghp:A@1.0.0",
    )
    _legacy(
        db,
        "xsn:b-paper",
        PROJECT_B,
        provider="literature",
        source_type="paper_passage",
        requested_locator="doi:10.5555/sp.2019.041#p3",
        canonical_locator="doi:10.5555/sp.2019.041@vor#p3",
        requested_ref=None,
        resolved_ref="vor",
        repository_identity="doi:10.5555/sp.2019.041",
        visibility="PUBLIC",
        trust_class="PEER_REVIEWED",
        license_class="PERMISSIVE",
    )
    # An attestation the old admission wrote from the P0 snapshot.
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:l', 'p')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_legacy', '1.0.0',"
        ' \'{"type": "object", "properties": {}}\'::jsonb, \'1.0.0\')'
    )
    legacy_artifact = db.execute(
        "SELECT artifact_id FROM external_snapshots WHERE snapshot_id = 'xsn:b-via-a'"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance, method) VALUES ('att:legacy', 'clm:l', 'REPORTED', %s, 'L1',"
        " '{}'::jsonb, 'core/sch_legacy@1.0.0', %s, '1.0.0',"
        ' \'{"extractor_id": "external-admission", "extractor_version": "1.0.0"}\'::jsonb,'
        " %s::jsonb)",
        (legacy_artifact, PROJECT_B, json.dumps({"snapshot_id": "xsn:b-via-a"})),
    )
    # --- the upgrade: `002d`, then project A's first authorized read, then `002e` ---------
    _apply(db, "002d_external_access_scopes.sql")
    _scope(db, "ghp:A@1.0.0", PROJECT_A, frozenset({PRIVATE_REPO}))
    _scope(db, "ghp:B@1.0.0", PROJECT_B, frozenset())
    _legacy(  # written after `002d`, so checked at write time
        db,
        "xsn:b-after-002d",
        PROJECT_B,
        repo=PUBLIC_REPO,
        path="after.py",
        visibility="PUBLIC",
        access_policy_ref="ghp:B@1.0.0",
    )
    _apply(db, "002e_external_snapshot_quarantine.sql")

    quarantined = dict(
        db.execute("SELECT snapshot_id, reason_code FROM external_snapshot_quarantine").fetchall()
    )
    assert quarantined == {
        "xsn:b-via-a": "SCOPE_OF_ANOTHER_PROJECT",
        "xsn:b-unrecorded": "SCOPE_NOT_RECORDED",
        "xsn:b-no-scope": "PRIVATE_WITHOUT_SCOPE",
        "xsn:a-off-list": "NOT_ON_ALLOWLIST",
    }, "every unprovable row, and only those"
    store = SqlExternalSourceStore(db)
    # §6.18: the evidence admitted from quarantined material is the replay's quarantine set.
    assert store.quarantined_attestation_ids(PROJECT_B) == ("att:legacy",)
    assert store.quarantined_attestation_ids(PROJECT_A) == ()
    # Admission from it is refused for every writer of SQL.
    with pytest.raises(Exception, match="quarantined"):
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type,"
            " source_artifact_id, locator, conditions, conditions_schema_version, project_id,"
            " extractor_version, extraction_provenance, method) VALUES ('att:new', 'clm:l',"
            " 'REPORTED', %s, 'L2', '{}'::jsonb, 'core/sch_legacy@1.0.0', %s, '1.0.0',"
            ' \'{"extractor_id": "x", "extractor_version": "1.0.0"}\'::jsonb, %s::jsonb)',
            (legacy_artifact, PROJECT_B, json.dumps({"snapshot_id": "xsn:b-via-a"})),
        )
    # A new relation citing the legacy attestation is refused.
    with pytest.raises(Exception, match="quarantined external snapshot"):
        db.execute(
            "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
            " relation_type, project_id, supporting_attestation_ids)"
            " VALUES ('rel:l', 'hyp:x', 'clm:l', 'SUPPORTS', %s, ARRAY['att:legacy'])",
            (PROJECT_B,),
        )
    # Not a cache hit; a fresh, coherent read supersedes it; a trusted row still holds its key.
    unrecorded = db.execute(
        "SELECT canonical_locator FROM external_snapshots WHERE snapshot_id = 'xsn:b-unrecorded'"
    ).fetchone()[0]
    assert store.pinned(PROJECT_B, "github", unrecorded) is None
    _legacy(
        db,
        "xsn:b-fresh",
        PROJECT_B,
        repo=PUBLIC_REPO,
        path="b-unrecorded.py",
        visibility="PUBLIC",
        access_policy_ref="ghp:B@1.0.0",
    )
    fresh = store.pinned(PROJECT_B, "github", unrecorded)
    assert fresh is not None and fresh.snapshot_id == "xsn:b-fresh"
    paper = store.pinned(PROJECT_B, "literature", "doi:10.5555/sp.2019.041@vor#p3")
    assert paper is not None and paper.snapshot_id == "xsn:b-paper", "provable legacy rows stay"
    with pytest.raises(Exception, match="already snapshotted"):
        _legacy(
            db,
            "xsn:b-paper-again",
            PROJECT_B,
            provider="literature",
            source_type="paper_passage",
            requested_locator="doi:10.5555/sp.2019.041#p3",
            canonical_locator="doi:10.5555/sp.2019.041@vor#p3",
            requested_ref=None,
            resolved_ref="vor",
            repository_identity="doi:10.5555/sp.2019.041",
            visibility="PUBLIC",
            trust_class="PEER_REVIEWED",
            license_class="PERMISSIVE",
        )
    # Quarantine is append-only.
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM external_snapshot_quarantine")


# --- use guards on a current database: a snapshot quarantined after admission ----------------


def _quarantined_admission(db) -> tuple[Any, Any]:  # type: ignore[no-untyped-def]
    """An attestation admitted in the belief fixture's project, whose snapshot is then quarantined."""
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'r')"
        " ON CONFLICT DO NOTHING",
        (ACTOR,),
    )
    SqlConditionSchemaStore(db).ensure(registration())
    world = build(
        store=SqlExternalSourceStore(db),
        sink=SqlExternalArtifactSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0),
        project_id=BELIEF_PROJECT,
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
        "literature", "doi:10.5555/sp.2019.041#p3", project_id=BELIEF_PROJECT, actor_id=ACTOR
    )

    def admit():  # type: ignore[no-untyped-def]
        return admission.admit(
            snapshot,
            proposition="Rs per length is normalised by the drawn length",
            fragment="Results",
            conditions=CONDITIONS,
            conditions_schema_version=SCHEMA_REF,
            actor_id=ACTOR,
        )

    admitted = admit()
    world.store.quarantine(BELIEF_PROJECT, snapshot.snapshot_id, "QUARANTINED_BY_OPERATOR")
    return admitted, admit


def test_quarantined_evidence_is_not_admitted_bundled_or_cited_by_a_belief_event(seeded):  # noqa: F811
    db = seeded
    admitted, admit_again = _quarantined_admission(db)
    attestation_id = admitted.attestation.attestation_id
    with pytest.raises(ExternalAdmissionRefused, match="SNAPSHOT_QUARANTINED"):
        admit_again()
    assert SqlExternalSourceStore(db).quarantined_attestation_ids(BELIEF_PROJECT) == (
        attestation_id,
    )
    with pytest.raises(Exception, match="quarantined external snapshot"):
        store_bundle(db, make_bundle(ordered_attestation_ids=(attestation_id,)))
    with pytest.raises(Exception, match="quarantined external snapshot"):
        _stored(db, event_id="bre:q", triggering_attestation_ids=(attestation_id,))
    assert db.execute(
        "SELECT count(*) FROM belief_revision_event_attestations WHERE attestation_id = %s",
        (attestation_id,),
    ).fetchone() == (0,)


def test_a_quarantine_names_its_snapshot_project_and_known_reasons_only(db):
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:q', 'q')")
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'r')",
        (ACTOR,),
    )
    world = build(
        store=SqlExternalSourceStore(db),
        sink=SqlExternalArtifactSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0),
        project_id="prj:q",
    )
    snapshot = world.service.snapshot(
        "literature", "doi:10.5555/sp.2019.041#p3", project_id="prj:q", actor_id=ACTOR
    )
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:other', 'o')")
    with pytest.raises(Exception, match="not the snapshot's project"):
        world.store.quarantine("prj:other", snapshot.snapshot_id, "QUARANTINED_BY_OPERATOR")
    with pytest.raises(Exception, match="reason_code"):
        world.store.quarantine("prj:q", snapshot.snapshot_id, "BECAUSE")
    world.store.quarantine("prj:q", snapshot.snapshot_id, "QUARANTINED_BY_OPERATOR")
    assert world.store.quarantine_reason("prj:q", snapshot.snapshot_id) == "QUARANTINED_BY_OPERATOR"
