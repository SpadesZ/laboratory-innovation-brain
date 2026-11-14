"""GH-002 across projects, on PostgreSQL: `002d` for every writer of SQL, and the service path.

A snapshot names the access scope it was read under; the scope belongs to one project and one
allowlist forever; a snapshot in project B naming project A's scope is refused, private material
with no scope or off its scope's allowlist is refused, and a scope cannot be re-pointed. The valid
half: each project's own private read lands in its own project under its own scope.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models.external_source import ExternalAccessScope
from lab_brain.core.repositories.external_sources import (
    ExternalSourceStoreError,
    SqlExternalSourceStore,
)
from lab_brain.sources.snapshots import SnapshotRefused
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.external_artifacts import SqlExternalArtifactSink
from tests.external_fixtures import (
    ACTOR,
    MAIN_COMMIT,
    PRIVATE_REPO,
    PROJECT,
    PUBLIC_REPO,
    T0,
    TOKEN,
    build,
    file_locator,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("GH-002"),
    pytest.mark.spec_test("T-GH-002"),
]

PROJECT_B = "prj:B"
TOKEN_B = "fixture-token-b"
PRIVATE = file_locator(PRIVATE_REPO, "main", "probe/fourpoint.py")


def _world(db):  # type: ignore[no-untyped-def]
    for project in (PROJECT, PROJECT_B):
        db.execute("INSERT INTO projects (project_id, name) VALUES (%s, %s)", (project, project))
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'r')",
        (ACTOR,),
    )
    world = build(
        store=SqlExternalSourceStore(db),
        sink=SqlExternalArtifactSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0),
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": TOKEN},
    )
    world.transport.tokens[TOKEN_B] = (PRIVATE_REPO,)
    return world


def _insert(db, artifact_id: str, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    row: dict[str, object] = {
        "snapshot_id": "xsn:forged",
        "project_id": PROJECT_B,
        "provider": "github",
        "source_type": "code_file",
        "requested_locator": f"github:{PRIVATE_REPO}@main:forged.py",
        "canonical_locator": f"github:{PRIVATE_REPO}@{MAIN_COMMIT}:forged.py",
        "requested_ref": "main",
        "resolved_ref": MAIN_COMMIT,
        "repository_identity": f"github:repository/7002 {PRIVATE_REPO}",
        "content_hash": "sha256:" + "3" * 64,
        "artifact_id": artifact_id,
        "retention": "METADATA_ONLY",
        "retention_rule": "raw",
        "visibility": "PRIVATE",
        "trust_class": "TECHNICAL_ARTIFACT",
        "sensitivity": "CONFIDENTIAL_LAB",
        "license_class": "PROPRIETARY",
        "access_policy_ref": "ghp:m5@1.0.0",
        "retrieved_at": T0,
        "created_at": T0,
    }
    row.update(overrides)
    db.execute(
        f"INSERT INTO external_snapshots ({', '.join(row)}) VALUES"
        f" ({', '.join(['%s'] * len(row))})",
        tuple(row.values()),
    )


def test_each_project_reads_privately_into_its_own_project_under_its_own_scope(db):
    world = _world(db)
    world.github_for(
        PROJECT_B,
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": TOKEN_B},
    )
    in_a = world.service.snapshot("github", PRIVATE, project_id=PROJECT, actor_id=ACTOR)
    in_b = world.service.snapshot("github", PRIVATE, project_id=PROJECT_B, actor_id=ACTOR)
    rows = db.execute(
        "SELECT s.project_id, s.access_policy_ref, a.project_id, a.private_allowlist"
        " FROM external_snapshots s JOIN external_access_scopes a"
        " ON a.policy_ref = s.access_policy_ref ORDER BY s.project_id"
    ).fetchall()
    assert rows == [
        (PROJECT_B, "ghp:B@1.0.0", PROJECT_B, [PRIVATE_REPO]),
        (PROJECT, "ghp:m5@1.0.0", PROJECT, [PRIVATE_REPO]),
    ]
    assert in_a.snapshot_id != in_b.snapshot_id


def test_the_service_refuses_project_b_before_any_row_or_request(db):
    world = _world(db)
    with pytest.raises(SnapshotRefused, match="GH-002"):
        world.service.snapshot("github", PRIVATE, project_id=PROJECT_B, actor_id=ACTOR)
    assert world.transport.calls == []
    assert db.execute("SELECT count(*) FROM external_snapshots").fetchone() == (0,)
    assert db.execute(
        "SELECT kind, locator, detail->>'reason_code' FROM external_source_events"
        " WHERE project_id = %s",
        (PROJECT_B,),
    ).fetchall() == [("ACCESS_REFUSED", None, "NO_ACCESS_SCOPE_FOR_PROJECT")]


def test_sql_refuses_a_snapshot_read_under_another_projects_scope(db):
    world = _world(db)
    world.github_for(PROJECT_B)  # B: public-only, its own scope
    world.service.snapshot("github", PRIVATE, project_id=PROJECT, actor_id=ACTOR)  # A's scope
    public_b = world.service.snapshot(
        "github",
        file_locator(PUBLIC_REPO, "main", "README.md"),
        project_id=PROJECT_B,
        actor_id=ACTOR,
    )
    artifact_in_b = public_b.artifact_id
    with pytest.raises(Exception, match="serves no other"):
        _insert(db, artifact_in_b)  # B's row, A's scope
    with pytest.raises(Exception, match="serves no other"):
        _insert(db, artifact_in_b, visibility="PUBLIC", sensitivity="PUBLIC")
    with pytest.raises(Exception, match="no access scope"):
        _insert(db, artifact_in_b, access_policy_ref=None)
    with pytest.raises(Exception, match="not recorded"):
        _insert(db, artifact_in_b, access_policy_ref="ghp:invented@1.0.0")
    with pytest.raises(Exception, match="allowlist"):
        _insert(db, artifact_in_b, access_policy_ref="ghp:B@1.0.0")  # B's scope, not allowlisted
    assert db.execute(
        "SELECT count(*) FROM external_snapshots WHERE project_id = %s AND visibility <> 'PUBLIC'",
        (PROJECT_B,),
    ).fetchone() == (0,)


def test_a_scope_cannot_be_re_pointed_or_edited(db):
    world = _world(db)
    world.service.snapshot("github", PRIVATE, project_id=PROJECT, actor_id=ACTOR)
    store = SqlExternalSourceStore(db)
    hijack = ExternalAccessScope(
        policy_ref="ghp:m5@1.0.0",
        project_id=PROJECT_B,
        provider="github",
        declared_by_actor_id="act:pi",
        private_allowlist=frozenset({PRIVATE_REPO}),
    )
    with pytest.raises(ExternalSourceStoreError, match="cannot be re-pointed"):
        store.record_access_scope(hijack)
    with pytest.raises(Exception, match="append-only"):
        db.execute(
            "UPDATE external_access_scopes SET project_id = %s WHERE policy_ref = 'ghp:m5@1.0.0'",
            (PROJECT_B,),
        )
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM external_access_scopes")
