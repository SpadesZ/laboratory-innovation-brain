"""T-GH-002: an unauthorized private-repository request fails closed, leaves an audit event, and
leaks neither the query nor private context.

    GH-002    private repo access 需 explicit auth/allowlist/security policy；未授權時必須 fail closed。
    T-GH-002  未授權 private repo request 被 fail-closed 並產生 audit event；不洩漏 query/private
              context。
    §22       未配置明確 authentication + allowlist/project scope 時，系統不得讀 private repo；
              restricted context 不得被用於 uncontrolled public search。
"""

from __future__ import annotations

import pytest

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel
from lab_brain.core.models.external_source import ExternalSourceEventKind, Visibility
from lab_brain.sources.adapter import SourceQuery
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.sources.external import ConnectorRefusal
from lab_brain.tool_providers.github import GitHubConnector, StaticCredentials
from lab_brain.tool_providers.github import declaration as github_declaration
from tests.external_fixtures import (
    ACTOR,
    PRIVATE_REPO,
    PROJECT,
    TOKEN,
    access_policy,
    build,
    file_locator,
)

LOCATOR = file_locator(PRIVATE_REPO, "main", "probe/fourpoint.py")


def _refusals(world):  # type: ignore[no-untyped-def]
    return [
        e for e in world.store.events(PROJECT) if e.kind is ExternalSourceEventKind.ACCESS_REFUSED
    ]


def _leaks(world, *needles: str) -> list[str]:  # type: ignore[no-untyped-def]
    found = []
    for event in world.store.events(PROJECT):
        text = repr(event.model_dump())
        found += [n for n in needles if n in text]
    return found


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_no_allowlist_no_credential_fails_closed_and_is_audited_by_digest():
    world = build()
    with pytest.raises(ConnectorError) as refused:
        world.service.snapshot("github", LOCATOR, project_id=PROJECT, actor_id=ACTOR)
    assert refused.value.kind is ConnectorErrorKind.NOT_FOUND
    assert refused.value.audited
    (event,) = _refusals(world)
    assert event.locator is None
    assert event.locator_digest == ConnectorRefusal.digest(LOCATOR)
    assert event.detail == {"reason_code": "NOT_VISIBLE_WITHOUT_AUTHORIZATION"}
    assert _leaks(world, PRIVATE_REPO, "calibration") == []
    assert all(
        s.canonical_locator != LOCATOR for s in world.store.for_request(PROJECT, "github", LOCATOR)
    )
    # Nothing was read: the fixture host served no file.
    assert not any(op == "read_file" for op, _, _ in world.transport.calls)


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_a_credential_is_never_presented_for_a_repository_nobody_allowlisted():
    """The deployment holds a working token; the project did not allowlist the repository."""
    world = build(credential_ref="lab-token", secrets={"lab-token": TOKEN})
    assert world.github.search(SourceQuery(text="series resistance")), "discovery is anonymous"
    with pytest.raises(ConnectorError):
        world.github.retrieve(LOCATOR, project_id=PROJECT)
    assert world.transport.calls, "the anonymous request was made"
    assert any(op == "search" for op, _, _ in world.transport.calls)
    assert all(not token for _, _, token in world.transport.calls), "the token was sent"
    assert len(_refusals(world)) == 1


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_allowlisted_without_a_credential_is_refused_before_any_request():
    world = build(allowlist=frozenset({PRIVATE_REPO}), credential_ref=None)
    with pytest.raises(ConnectorError) as refused:
        world.github.retrieve(LOCATOR, project_id=PROJECT)
    assert refused.value.kind is ConnectorErrorKind.NOT_AUTHORIZED
    assert refused.value.error_class == "POLICY_BLOCK" and not refused.value.retryable
    assert world.transport.calls == [], "fail closed means nothing was sent"
    (event,) = _refusals(world)
    assert event.detail["reason_code"] == "PRIVATE_ACCESS_WITHOUT_CREDENTIAL"


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_a_refused_credential_is_audited_and_the_token_appears_nowhere():
    world = build(
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": "not-a-real-token"},
    )
    with pytest.raises(ConnectorError) as refused:
        world.github.retrieve(LOCATOR, project_id=PROJECT)
    assert refused.value.kind is ConnectorErrorKind.AUTHENTICATION_FAILED
    assert "not-a-real-token" not in str(refused.value)
    assert _refusals(world)[0].detail["reason_code"] == "CREDENTIAL_REFUSED"
    assert _leaks(world, "not-a-real-token", PRIVATE_REPO) == []


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_explicit_auth_and_allowlist_read_the_private_repo_under_its_private_label():
    world = build(
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": TOKEN},
    )
    snapshot = world.service.snapshot("github", LOCATOR, project_id=PROJECT, actor_id=ACTOR)
    assert snapshot.visibility is Visibility.PRIVATE
    assert snapshot.sensitivity is SensitivityLabel.CONFIDENTIAL_LAB
    assert snapshot.license_class is LicenseClass.PROPRIETARY
    assert snapshot.access_policy_ref == "ghp:m5@1.0.0"
    assert _refusals(world) == []
    assert TOKEN not in repr(snapshot.model_dump())


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_restricted_context_never_reaches_the_public_code_search():
    """A query derived from INTERNAL material is refused by SEC-001's gate before GitHub's
    transport is entered, and the egress audit records the refusal without the query."""
    world = build(context_labels={"art:sha256:" + "a" * 64: SensitivityLabel.INTERNAL})
    found = world.service.discover(
        SourceQuery(text="our unpublished contact redesign series resistance"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=("art:sha256:" + "a" * 64,),
    )
    assert found == ()
    assert not any(op == "search" for op, _, _ in world.transport.calls)
    blocked = world.runner.audit.blocked()
    assert blocked and all("unpublished" not in repr(d) for d in blocked)


@pytest.mark.requirement("GH-002")
@pytest.mark.spec_test("T-GH-002")
def test_a_withdrawn_allowlist_is_a_refusal_not_a_removal_and_names_nothing():
    """The project read the private file under authorization, then the allowlist was withdrawn.
    The next request is refused and audited by digest -- and the earlier snapshot is NOT marked
    SOURCE_UNAVAILABLE: this project may no longer see the repository, which says nothing about
    whether it still exists (§6.16 is about removal, not about access)."""
    world = build(
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": TOKEN},
    )
    kept = world.service.snapshot("github", LOCATOR, project_id=PROJECT, actor_id=ACTOR)
    world.registry.remove("github")
    world.registry.register(
        GitHubConnector(
            transport=world.transport,
            # The withdrawal is a new version of the project's policy, not an edit of the old one.
            policy=access_policy(credential_ref="lab-token", version="1.1.0"),
            credentials=StaticCredentials(world.secrets),
            audit=world.service,
            now=world.clock,
        ),
        github_declaration(),
        project_id=PROJECT,
    )
    with pytest.raises(ConnectorError) as refused:
        world.service.snapshot("github", LOCATOR, project_id=PROJECT, actor_id=ACTOR)
    assert refused.value.kind is ConnectorErrorKind.NOT_FOUND and refused.value.audited
    assert not world.service.unavailable(PROJECT, kept.snapshot_id)
    kinds = [e.kind for e in world.store.events(PROJECT)]
    assert ExternalSourceEventKind.SOURCE_UNAVAILABLE not in kinds
    assert ExternalSourceEventKind.CONNECTOR_ERROR not in kinds
    assert len(_refusals(world)) == 1
