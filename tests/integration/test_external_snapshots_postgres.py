"""T-GH-001 on PostgreSQL, and `002c` for every writer of SQL.

T-GH-001  public fixture repo 可 search/fetch；requested ref 解析到固定 commit SHA，file content
          hash 與 locator 被保存。
"""

from __future__ import annotations

import json

import pytest

from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.sources.adapter import SourceQuery
from lab_brain.sources.errors import ConnectorError
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.external_artifacts import SqlExternalArtifactSink
from tests.external_fixtures import (
    ACTOR,
    MAIN_COMMIT,
    PRIVATE_REPO,
    PROJECT,
    PUBLIC_REPO,
    REMOVABLE_REPO,
    T0,
    build,
    file_locator,
)

pytestmark = pytest.mark.postgres


def _world(db):  # type: ignore[no-untyped-def]
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'M5')", (PROJECT,))
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'r')",
        (ACTOR,),
    )
    store = SqlExternalSourceStore(db)
    sink = SqlExternalArtifactSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0)
    return build(store=store, sink=sink)


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_a_public_repo_is_searched_fetched_pinned_and_its_hash_and_locator_are_stored(db):
    world = _world(db)
    found = world.service.discover(
        SourceQuery(text="phase shifter charge simulation"), project_id=PROJECT, actor_id=ACTOR
    )
    assert f"github:{PUBLIC_REPO}" in {r.canonical_locator for r in found}
    snapshot = world.service.snapshot(
        "github",
        file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py"),
        project_id=PROJECT,
        actor_id=ACTOR,
    )
    row = db.execute(
        "SELECT s.requested_locator, s.canonical_locator, s.requested_ref, s.resolved_ref,"
        " s.repository_identity, s.content_hash, a.content_hash, a.source_origin,"
        " a.rights_metadata, o.sensitivity_label, s.retrieved_at"
        " FROM external_snapshots s JOIN artifacts a ON a.artifact_id = s.artifact_id"
        " JOIN artifact_occurrences o ON o.artifact_id = a.artifact_id AND o.project_id ="
        " s.project_id WHERE s.snapshot_id = %s",
        (snapshot.snapshot_id,),
    ).fetchone()
    (
        requested,
        canonical,
        ref,
        resolved,
        identity,
        content,
        artifact_hash,
        origin,
        rights,
        label,
        retrieved,
    ) = row
    assert requested == file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py")
    assert canonical == file_locator(PUBLIC_REPO, MAIN_COMMIT, "extract/rs_extraction.py")
    assert (ref, resolved) == ("main", MAIN_COMMIT)
    assert identity == f"github:repository/7001 {PUBLIC_REPO}"
    assert content == artifact_hash, "FULL_CONTENT: the kept bytes are the bytes returned"
    assert origin == "EXTERNAL_CONNECTOR" and label == "PUBLIC"
    rights = rights if isinstance(rights, dict) else json.loads(rights)
    assert rights["license_class"] == "PERMISSIVE" and rights["license_identifier"] == "MIT"
    assert retrieved is not None
    assert world.store.snapshot(PROJECT, snapshot.snapshot_id) == snapshot
    assert world.sink.read(snapshot.artifact_id).startswith(b'"""Series resistance')
    kinds = [e.kind.value for e in world.store.events(PROJECT)]
    assert "DISCOVERED" in kinds and kinds[-1] == "SNAPSHOTTED"


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_a_refused_private_request_is_a_durable_audit_row_that_names_nothing_private(db):
    world = _world(db)
    with pytest.raises(ConnectorError):
        world.service.snapshot(
            "github",
            file_locator(PRIVATE_REPO, "main", "probe/fourpoint.py"),
            project_id=PROJECT,
            actor_id=ACTOR,
        )
    rows = db.execute(
        "SELECT kind, locator, locator_digest, detail::text FROM external_source_events"
    ).fetchall()
    assert [r[0] for r in rows] == ["ACCESS_REFUSED"]
    assert rows[0][1] is None and rows[0][2].startswith("sha256:")
    assert "calibration" not in repr(rows)
    assert db.execute("SELECT count(*) FROM external_snapshots").fetchone() == (0,)


def test_removal_is_recorded_against_the_kept_snapshot_whose_bytes_remain(db):
    world = _world(db)
    locator = file_locator(REMOVABLE_REPO, "main", "mesh.py")
    kept = world.service.snapshot("github", locator, project_id=PROJECT, actor_id=ACTOR)
    world.transport.remove(REMOVABLE_REPO)
    with pytest.raises(ConnectorError):
        world.service.snapshot("github", locator, project_id=PROJECT, actor_id=ACTOR)
    assert db.execute(
        "SELECT kind FROM external_source_events WHERE snapshot_id = %s ORDER BY occurred_at",
        (kept.snapshot_id,),
    ).fetchall() == [("SNAPSHOTTED",), ("SOURCE_UNAVAILABLE",)]
    assert world.sink.read(kept.artifact_id) == b"EDGE_NM = 5\n"


def _insert_snapshot(db, artifact_id: str, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    row: dict[str, object] = {
        "snapshot_id": "xsn:raw",
        "project_id": PROJECT,
        "provider": "github",
        "source_type": "code_file",
        "requested_locator": "github:o/r@main:a.py",
        "canonical_locator": f"github:o/r@{MAIN_COMMIT}:a.py",
        "requested_ref": "main",
        "resolved_ref": MAIN_COMMIT,
        "repository_identity": "github:repository/1 o/r",
        "content_hash": "sha256:" + "1" * 64,
        "artifact_id": artifact_id,
        "retention": "METADATA_ONLY",
        "retention_rule": "raw",
        "visibility": "PUBLIC",
        "trust_class": "TECHNICAL_ARTIFACT",
        "sensitivity": "PUBLIC",
        "license_class": "PERMISSIVE",
        "retrieved_at": T0,
        "created_at": T0,
    }
    row.update(overrides)
    db.execute(
        f"INSERT INTO external_snapshots ({', '.join(row)}) VALUES"
        f" ({', '.join(['%s'] * len(row))})",
        tuple(row.values()),
    )


@pytest.mark.requirement("GH-003")
@pytest.mark.spec_test("T-GH-003")
def test_sql_refuses_unpinned_promoted_or_misattributed_snapshots(db):
    world = _world(db)
    kept = world.service.snapshot(
        "github",
        file_locator(PUBLIC_REPO, "main", "README.md"),
        project_id=PROJECT,
        actor_id=ACTOR,
    )
    artifact = kept.artifact_id
    with pytest.raises(Exception, match="external_snapshots_commit_pinned"):
        _insert_snapshot(db, artifact, resolved_ref="main")
    with pytest.raises(Exception, match="external_snapshots_technical_is_technical"):
        _insert_snapshot(db, artifact, trust_class="PEER_REVIEWED")
    for internal in ("INTERNAL_RUN", "INTERNAL_MEASUREMENT", "EXPERT_HEURISTIC"):
        with pytest.raises(Exception, match="external_snapshots_trust_class_check"):
            _insert_snapshot(db, artifact, source_type="paper_passage", trust_class=internal)
    with pytest.raises(Exception, match="external_snapshots_private_is_not_public"):
        _insert_snapshot(db, artifact, visibility="PRIVATE")
    with pytest.raises(Exception, match="FULL_CONTENT"):
        _insert_snapshot(db, artifact, retention="FULL_CONTENT")
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, lineage_id,"
        " source_origin) VALUES (%s, %s, 'x', 'cas://x', 'lin:x', 'RUN_OUTPUT')",
        ("art:sha256:" + "2" * 64, "sha256:" + "2" * 64),
    )
    with pytest.raises(Exception, match="origin is RUN_OUTPUT"):
        _insert_snapshot(db, "art:sha256:" + "2" * 64)
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:other', 'o')")
    with pytest.raises(Exception, match="not present in project prj:other"):
        _insert_snapshot(db, artifact, project_id="prj:other")
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM external_snapshots WHERE snapshot_id = %s", (kept.snapshot_id,))
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE external_source_events SET actor_id = NULL")


def test_sql_refuses_a_refusal_that_names_its_locator_and_an_event_that_carries_payload(db):
    _world(db)
    base = (
        "INSERT INTO external_source_events (event_id, project_id, provider, kind,"
        " locator_digest, locator, detail, occurred_at) VALUES (%s, %s, 'github', %s, %s, %s,"
        " %s::jsonb, %s)"
    )
    digest = "sha256:" + "3" * 64
    with pytest.raises(Exception, match="refusal_has_no_locator"):
        db.execute(base, ("xev:a", PROJECT, "ACCESS_REFUSED", digest, "github:p/r", "{}", T0))
    with pytest.raises(Exception, match="carries_no_payload"):
        db.execute(
            base, ("xev:b", PROJECT, "DISCOVERED", digest, "github:p/r", '{"token": "x"}', T0)
        )


def test_the_production_sink_scans_external_bytes_and_keeps_only_provenance_on_a_hit(db):
    """SEC-003 through the real scanner: a code host is where credentials leak."""
    world = _world(db)
    snapshot = world.service.snapshot(
        "github",
        file_locator(PUBLIC_REPO, "main", "config/deploy.env"),
        project_id=PROJECT,
        actor_id=ACTOR,
    )
    assert snapshot.retention.value == "METADATA_ONLY"
    assert snapshot.retention_rule.endswith("secret-scan-refused")
    kept = world.sink.read(snapshot.artifact_id)
    assert b"AKIA" not in kept and json.loads(kept)["content_hash"] == snapshot.content_hash
    origin, scan = db.execute(
        "SELECT source_origin, secret_scan_status FROM artifacts WHERE artifact_id = %s",
        (snapshot.artifact_id,),
    ).fetchone()
    assert (origin, scan) == ("EXTERNAL_CONNECTOR", "CLEAN")
