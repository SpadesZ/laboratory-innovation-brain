"""The storage half of §17.21's snapshot, in memory: rights-governed retention, the pinned cache,
drift and removal (§6.16), secret scanning (SEC-003), and the provenance models' own refusals."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.core.models.external_source import (
    ExternalAccessScope,
    ExternalSnapshot,
    ExternalSourceEvent,
    ExternalSourceEventKind,
    Retention,
    Visibility,
)
from lab_brain.core.repositories.external_sources import (
    ExternalSourceStoreError,
    InMemoryExternalSourceStore,
)
from lab_brain.security.egress import CodePolicy, may_enter_generation_context
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.sources.external import ConnectorRefusal
from lab_brain.sources.snapshots import SnapshotRefused, code_artifact
from tests.external_fixtures import (
    ACTOR,
    COPYLEFT_REPO,
    MAIN_COMMIT,
    PROJECT,
    PUBLIC_REPO,
    REMOVABLE_REPO,
    UNLICENSED_REPO,
    V10_COMMIT,
    build,
    file_locator,
)


def _snap(world, provider: str, locator: str):  # type: ignore[no-untyped-def]
    return world.service.snapshot(provider, locator, project_id=PROJECT, actor_id=ACTOR)


def _kinds(world) -> list[ExternalSourceEventKind]:  # type: ignore[no-untyped-def]
    return [e.kind for e in world.store.events(PROJECT)]


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_what_is_kept_follows_the_rights_and_the_row_says_which_rule_decided():
    world = build()
    permissive = _snap(
        world, "github", file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py")
    )
    assert permissive.retention is Retention.FULL_CONTENT
    assert world.sink.stored[permissive.artifact_id].startswith(b'"""Series resistance')
    copyleft = _snap(world, "github", file_locator(COPYLEFT_REPO, "main", "fit.py"))
    assert (copyleft.retention, copyleft.license_class) == (
        Retention.FULL_CONTENT,
        LicenseClass.COPYLEFT,
    )
    unlicensed = _snap(world, "github", file_locator(UNLICENSED_REPO, "main", "rs.py"))
    assert unlicensed.retention is Retention.METADATA_ONLY
    assert unlicensed.retention_rule.endswith("no-reuse-licence")
    kept = world.sink.stored[unlicensed.artifact_id]
    assert b"def fit" not in kept, "no blanket fair use: the code itself is not kept"
    assert unlicensed.content_hash.encode() in kept, "the hash of what was read is"
    passage = _snap(world, "literature", "doi:10.5555/sp.2021.113#p2")
    assert passage.retention is Retention.EXCERPT
    assert len(world.sink.stored[passage.artifact_id].decode()) <= 280
    open_access = _snap(world, "literature", "doi:10.5555/sp.2019.041#p3")
    assert open_access.retention is Retention.FULL_CONTENT
    assert open_access.trust_class is TrustClass.PEER_REVIEWED


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_the_pinned_version_is_the_cache_key_and_a_moved_branch_is_a_new_snapshot():
    world = build()
    locator = file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py")
    first = _snap(world, "github", locator)
    assert _snap(world, "github", locator) == first
    assert _kinds(world).count(ExternalSourceEventKind.CACHE_HIT) == 1
    assert len(world.sink.stored) == 1
    world.transport.move_ref(PUBLIC_REPO, "main", V10_COMMIT)
    moved = _snap(world, "github", locator)
    assert moved.snapshot_id != first.snapshot_id
    assert (first.resolved_ref, moved.resolved_ref) == (MAIN_COMMIT, V10_COMMIT)
    drift = [e for e in world.store.events(PROJECT) if e.kind is ExternalSourceEventKind.REF_DRIFT]
    assert drift and drift[0].detail["previous_resolved_ref"] == MAIN_COMMIT
    # The old snapshot and its bytes are still there to re-read.
    assert world.store.snapshot(PROJECT, first.snapshot_id) == first
    assert first.artifact_id in world.sink.stored


def test_removed_material_marks_earlier_snapshots_unavailable_and_keeps_them():
    world = build()
    locator = file_locator(REMOVABLE_REPO, "main", "mesh.py")
    kept = _snap(world, "github", locator)
    world.transport.remove(REMOVABLE_REPO)
    with pytest.raises(ConnectorError) as removed:
        _snap(world, "github", locator)
    assert removed.value.kind is ConnectorErrorKind.SOURCE_REMOVED
    assert world.service.unavailable(PROJECT, kept.snapshot_id)
    assert world.sink.stored[kept.artifact_id] == b"EDGE_NM = 5\n"
    errors = [
        e for e in world.store.events(PROJECT) if e.kind is ExternalSourceEventKind.CONNECTOR_ERROR
    ]
    assert errors[-1].detail == {
        "connector_error": "SOURCE_REMOVED",
        "error_class": "EXTERNAL_SERVICE_ERROR",
    }


def test_a_file_carrying_a_credential_keeps_provenance_and_not_the_bytes():
    world = build()
    snapshot = _snap(world, "github", file_locator(PUBLIC_REPO, "main", "config/deploy.env"))
    assert snapshot.retention is Retention.METADATA_ONLY
    assert snapshot.retention_rule.endswith("secret-scan-refused")
    assert all(b"AKIA" not in data for data in world.sink.stored.values())


def test_a_literature_version_that_is_not_held_is_drift_and_nothing_is_substituted():
    world = build()
    with pytest.raises(ConnectorError) as drift:
        _snap(world, "literature", "doi:10.5555/sp.2021.113@v1#p2")
    assert drift.value.kind is ConnectorErrorKind.REF_DRIFT
    assert not world.sink.stored


def _snapshot_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "snapshot_id": "xsn:1",
        "project_id": PROJECT,
        "provider": "github",
        "source_type": "code_file",
        "requested_locator": file_locator(PUBLIC_REPO, "main", "a.py"),
        "canonical_locator": file_locator(PUBLIC_REPO, MAIN_COMMIT, "a.py"),
        "requested_ref": "main",
        "resolved_ref": MAIN_COMMIT,
        "repository_identity": "github:repository/7001 photonics-lab/pn-modulator-sim",
        "content_hash": "sha256:" + "0" * 64,
        "artifact_id": "art:sha256:" + "0" * 64,
        "retention": Retention.FULL_CONTENT,
        "retention_rule": "r",
        "visibility": Visibility.PUBLIC,
        "trust_class": TrustClass.TECHNICAL_ARTIFACT,
        "sensitivity": SensitivityLabel.PUBLIC,
        "license_class": LicenseClass.PERMISSIVE,
        "retrieved_at": dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
    }
    fields.update(overrides)
    return fields


@pytest.mark.requirement("GH-003")
@pytest.mark.spec_test("T-GH-003")
def test_the_snapshot_model_refuses_unpinned_promoted_or_mislabelled_provenance():
    ExternalSnapshot(**_snapshot_fields())
    with pytest.raises(ValidationError, match="not a commit SHA"):
        ExternalSnapshot(**_snapshot_fields(resolved_ref="main"))
    with pytest.raises(ValidationError, match="does not name its commit"):
        ExternalSnapshot(
            **_snapshot_fields(canonical_locator=file_locator(PUBLIC_REPO, "main", "a.py"))
        )
    with pytest.raises(ValidationError, match="GH-003"):
        ExternalSnapshot(**_snapshot_fields(trust_class=TrustClass.PEER_REVIEWED))
    with pytest.raises(ValidationError, match="labelled PUBLIC"):
        ExternalSnapshot(**_snapshot_fields(visibility=Visibility.PRIVATE))
    with pytest.raises(ValidationError, match="repository identity"):
        ExternalSnapshot(**_snapshot_fields(repository_identity=None))
    for internal in (
        TrustClass.INTERNAL_RUN,
        TrustClass.INTERNAL_MEASUREMENT,
        TrustClass.EXPERT_HEURISTIC,
    ):
        with pytest.raises(ValidationError, match="no external source can be"):
            ExternalSnapshot(
                **_snapshot_fields(
                    source_type="paper_passage",
                    canonical_locator="doi:10.5555/x@vor#p1",
                    resolved_ref="vor",
                    trust_class=internal,
                )
            )


def test_an_access_refusal_event_can_carry_only_a_digest_and_no_event_carries_payload():
    digest = ConnectorRefusal.digest("github:x/y@main:z")
    base = {
        "event_id": "xev:1",
        "project_id": PROJECT,
        "provider": "github",
        "locator_digest": digest,
    }
    ExternalSourceEvent(**base, kind=ExternalSourceEventKind.ACCESS_REFUSED)
    with pytest.raises(ValidationError, match="never the locator"):
        ExternalSourceEvent(
            **base, kind=ExternalSourceEventKind.ACCESS_REFUSED, locator="github:x/y@main:z"
        )
    with pytest.raises(ValidationError, match="may not carry"):
        ExternalSourceEvent(
            **base,
            kind=ExternalSourceEventKind.DISCOVERED,
            locator="github:x/y",
            detail={"query": "secret plan"},
        )


def test_a_path_missing_at_a_moved_branch_is_not_the_removal_of_the_pinned_version():
    """§6.16 narrowly: the file is gone from main's new head; the commit an earlier snapshot pinned
    still holds it. Recorded as a connector error at that version, and nothing is marked
    SOURCE_UNAVAILABLE."""
    world = build()
    locator = file_locator(PUBLIC_REPO, "main", "config/deploy.env")
    kept = _snap(world, "github", locator)
    world.transport.move_ref(PUBLIC_REPO, "main", V10_COMMIT)  # v1.0 has no config/deploy.env
    with pytest.raises(ConnectorError) as missing:
        _snap(world, "github", locator)
    assert missing.value.kind is ConnectorErrorKind.NOT_FOUND
    assert missing.value.pinned_ref == V10_COMMIT
    assert not world.service.unavailable(PROJECT, kept.snapshot_id)
    error = [
        e for e in world.store.events(PROJECT) if e.kind is ExternalSourceEventKind.CONNECTOR_ERROR
    ]
    assert error[-1].detail["pinned_ref"] == V10_COMMIT


def test_a_public_repository_that_vanished_is_unavailable_even_though_the_host_says_not_visible():
    """A deleted public repository answers an anonymous caller exactly as a private one does. The
    connector refuses and audits by digest (GH-002 is unchanged), and the snapshot this project read
    publicly is marked SOURCE_UNAVAILABLE -- the change happened at the source."""
    world = build()
    locator = file_locator(REMOVABLE_REPO, "main", "mesh.py")
    kept = _snap(world, "github", locator)
    world.transport.repositories[REMOVABLE_REPO]["private"] = True
    with pytest.raises(ConnectorError) as vanished:
        _snap(world, "github", locator)
    assert vanished.value.kind is ConnectorErrorKind.NOT_FOUND and vanished.value.audited
    assert world.service.unavailable(PROJECT, kept.snapshot_id)
    kinds = _kinds(world)
    assert ExternalSourceEventKind.ACCESS_REFUSED in kinds
    assert ExternalSourceEventKind.CONNECTOR_ERROR not in kinds


def test_external_code_meets_sec_004_before_any_generation_context():
    """SEC-004: the snapshot's licence class is what the code-generation gate reads."""
    world = build()
    mit = _snap(world, "github", file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py"))
    gpl = _snap(world, "github", file_locator(COPYLEFT_REPO, "main", "fit.py"))
    unknown = _snap(world, "github", file_locator(UNLICENSED_REPO, "main", "rs.py"))
    assert code_artifact(mit).provenance == mit.canonical_locator
    assert may_enter_generation_context(code_artifact(mit), None).permitted
    assert not may_enter_generation_context(code_artifact(gpl), None).permitted
    assert (
        may_enter_generation_context(code_artifact(unknown), None).reason_code == "LICENSE_UNKNOWN"
    )
    permits_copyleft = CodePolicy(
        policy_id="cp:m5",
        version="1.0.0",
        project_id=PROJECT,
        declared_by_actor_id="act:pi",
        permitted=frozenset({LicenseClass.PERMISSIVE, LicenseClass.COPYLEFT}),
    )
    assert may_enter_generation_context(code_artifact(gpl), permits_copyleft).permitted


def test_a_pinned_version_that_re_hashes_differently_is_refused_not_replaced():
    """A commit is immutable; if the provider now serves different bytes for it, the provider's pin
    is not one. The cached snapshot stands and nothing is overwritten or served as a cache hit."""
    world = build()
    locator = file_locator(PUBLIC_REPO, "main", "README.md")
    first = _snap(world, "github", locator)
    world.transport.repositories[PUBLIC_REPO]["commits"][MAIN_COMMIT]["README.md"] = "tampered.\n"
    with pytest.raises(SnapshotRefused, match="immutable version"):
        _snap(world, "github", locator)
    assert world.store.snapshot(PROJECT, first.snapshot_id) == first
    assert ExternalSourceEventKind.CACHE_HIT not in _kinds(world)
    with pytest.raises(SnapshotRefused, match="no provider"):
        _snap(world, "patents", "pat:US1")


def test_the_store_keeps_a_snapshot_only_under_a_recorded_scope_of_its_own_project():
    """The in-memory store holds what `002d` holds in SQL (GH-002)."""
    store = InMemoryExternalSourceStore()
    scope = ExternalAccessScope(
        policy_ref="ghp:a@1.0.0",
        project_id="prj:a",
        provider="github",
        declared_by_actor_id="act:pi",
    )
    snapshot = ExternalSnapshot(
        **_snapshot_fields(project_id="prj:b", access_policy_ref="ghp:a@1.0.0")
    )
    with pytest.raises(ExternalSourceStoreError, match="not recorded for that project"):
        store.add_snapshot(snapshot)
    store.record_access_scope(scope)
    with pytest.raises(ExternalSourceStoreError, match="not recorded for that project"):
        store.add_snapshot(snapshot)
    with pytest.raises(ExternalSourceStoreError, match="cannot be re-pointed"):
        store.record_access_scope(scope.model_copy(update={"project_id": "prj:b"}))
    store.add_snapshot(snapshot.model_copy(update={"project_id": "prj:a"}))
