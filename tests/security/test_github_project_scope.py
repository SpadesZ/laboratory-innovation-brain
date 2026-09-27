"""GH-002 across projects: project B never consumes project A's access policy, allowlist or
credential -- through the snapshot service, the connector, the registry, the router, the M1 fetch
path or a credential reference -- and each project still reads privately under its own scope.

    GH-002    private repo access 需 explicit auth/allowlist/security policy；未授權時必須 fail closed。
    T-GH-002  未授權 private repo request 被 fail-closed 並產生 audit event；不洩漏 query/private
              context。
    §22       未配置明確 authentication + allowlist/project scope 時，系統不得讀 private repo。

Every world here approves GitHub egress for EVERY project (see `tests/external_fixtures.py`), so
nothing below is refused by egress policy: what refuses is the access scope, which is the point.
"""

from __future__ import annotations

import dataclasses

import pytest

from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.external_source import ExternalSourceEventKind, Visibility
from lab_brain.sources.adapter import SourceQuery
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.sources.external import (
    ConnectorRefusal,
    ConnectorRegistrationError,
    ConnectorRegistry,
    ProjectScopeMismatch,
)
from lab_brain.sources.snapshots import SnapshotRefused
from lab_brain.tool_providers.github import declaration as github_declaration
from tests.classification_fixtures import labelled
from tests.external_fixtures import (
    ACTOR,
    PRIVATE_REPO,
    PROJECT,
    PUBLIC_REPO,
    TOKEN,
    build,
    file_locator,
)

PROJECT_B = "prj:B"
TOKEN_B = "fixture-token-b"
LOCATOR = file_locator(PRIVATE_REPO, "main", "probe/fourpoint.py")
PUBLIC = file_locator(PUBLIC_REPO, "main", "README.md")

pytestmark = [pytest.mark.requirement("GH-002"), pytest.mark.spec_test("T-GH-002")]


def _world_a():  # type: ignore[no-untyped-def]
    """Project A: the private repository allowlisted, and a working credential."""
    return build(
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": TOKEN},
    )


def _events(world, project_id: str):  # type: ignore[no-untyped-def]
    return list(world.store.events(project_id))


def _refusal_reasons(world, project_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        e.detail["reason_code"]
        for e in _events(world, project_id)
        if e.kind is ExternalSourceEventKind.ACCESS_REFUSED
    ]


def test_project_b_is_never_served_by_project_a_connector():
    """The reported P0: B asks for A's private file and, before this repair, received it under
    A's token. Now nothing leaves, nothing is stored, and B's own log says why -- by digest."""
    world = _world_a()
    for locator in (LOCATOR, PUBLIC):
        with pytest.raises(SnapshotRefused, match="GH-002"):
            world.service.snapshot("github", locator, project_id=PROJECT_B, actor_id=ACTOR)
    assert world.transport.calls == [], "no request reached the host"
    assert world.transport.presented == []
    assert not world.sink.stored
    assert _refusal_reasons(world, PROJECT_B) == ["NO_ACCESS_SCOPE_FOR_PROJECT"] * 2
    refused = _events(world, PROJECT_B)
    assert all(e.locator is None for e in refused)
    assert refused[0].locator_digest == ConnectorRefusal.digest(LOCATOR)
    assert _events(world, PROJECT) == [], "B's attempt is B's record, not A's"


def test_the_connector_refuses_another_project_before_parsing_resolving_or_requesting():
    """The last line: even called directly, A's connector serves only A."""
    world = _world_a()
    with pytest.raises(ConnectorError) as refused:
        world.github.retrieve(LOCATOR, project_id=PROJECT_B)
    assert refused.value.kind is ConnectorErrorKind.NOT_AUTHORIZED and refused.value.audited
    assert world.transport.calls == [] and world.transport.presented == []
    assert _refusal_reasons(world, PROJECT_B) == ["PROJECT_SCOPE_MISMATCH"]
    assert _events(world, PROJECT) == []
    # Not a parse error in disguise: an unparsable locator is refused the same way, first.
    with pytest.raises(ConnectorError) as garbage:
        world.github.retrieve("not a locator", project_id=PROJECT_B)
    assert garbage.value.kind is ConnectorErrorKind.NOT_AUTHORIZED


def test_a_scoped_connector_is_registered_for_its_own_project_only():
    world = _world_a()
    registry = ConnectorRegistry()
    for project_id in (PROJECT_B, None):
        with pytest.raises(ConnectorRegistrationError, match="GH-002"):
            registry.register(world.github, github_declaration(), project_id=project_id)
    registry.register(world.github, github_declaration(), project_id=PROJECT)
    assert registry.adapter("github", project_id=PROJECT) is world.github
    assert registry.adapter("github", project_id=PROJECT_B) is None
    assert registry.registered_elsewhere("github", project_id=PROJECT_B)


def test_routers_are_bound_to_one_project_and_hold_no_other_projects_authorization():
    world = _world_a()
    classifier = labelled({}, project_id=PROJECT)
    router_b = world.registry.router(
        project_id=PROJECT_B, runner=world.runner, classifier=classifier
    )
    assert router_b.providers == ("literature",), "B's router never holds A's connector"
    with pytest.raises(ProjectScopeMismatch):
        router_b.register(world.github)
    router_a = world.registry.router(project_id=PROJECT, runner=world.runner, classifier=classifier)
    query = SourceQuery(text="calibration probe")
    with pytest.raises(ProjectScopeMismatch):
        router_a.search(query, project_id=PROJECT_B, actor_id=ACTOR)
    with pytest.raises(ProjectScopeMismatch):
        router_a.fetch("github", LOCATOR, project_id=PROJECT_B, actor_id=ACTOR)
    with pytest.raises(ProjectScopeMismatch):
        router_a.authorized_providers(project_id=PROJECT_B, actor_id=ACTOR)
    assert world.transport.calls == []


def test_the_project_unaware_fetch_path_never_presents_a_credential():
    """M1's `fetch` carries no project, so it is anonymous -- even for A, even allowlisted."""
    world = _world_a()
    router_a = world.registry.router(
        project_id=PROJECT, runner=world.runner, classifier=labelled({}, project_id=PROJECT)
    )
    with pytest.raises(ConnectorError) as invisible:
        router_a.fetch(
            "github",
            LOCATOR,
            project_id=PROJECT,
            actor_id=ACTOR,
            escalate=frozenset({SensitivityLabel.PUBLIC}),
        )
    assert invisible.value.kind is ConnectorErrorKind.NOT_FOUND
    with pytest.raises(ConnectorError):
        world.github.fetch(file_locator(PRIVATE_REPO, "main", "probe/fourpoint.py"))
    assert world.github.fetch(PUBLIC) is not None
    assert world.transport.presented == []


def test_project_b_policy_cannot_resolve_project_a_credential_by_naming_it():
    """B allowlists the repository and names A's credential reference; references resolve in the
    asking project's namespace only, so B has no credential and is refused before any request."""
    world = _world_a()
    world.github_for(PROJECT_B, allowlist=frozenset({PRIVATE_REPO}), credential_ref="lab-token")
    with pytest.raises(ConnectorError) as refused:
        world.service.snapshot("github", LOCATOR, project_id=PROJECT_B, actor_id=ACTOR)
    assert refused.value.kind is ConnectorErrorKind.NOT_AUTHORIZED and refused.value.audited
    assert _refusal_reasons(world, PROJECT_B) == ["PRIVATE_ACCESS_WITHOUT_CREDENTIAL"]
    assert world.transport.calls == [] and world.transport.presented == []
    assert _events(world, PROJECT) == []


def test_a_record_read_under_another_scope_is_never_kept():
    """Belt and braces after retrieval: an adapter that ignores the asked-for project (here, A's
    connector hidden behind a wrapper that declares no scope, registered deployment-wide) returns
    A's private material to B's request; the service refuses it before anything is stored."""
    world = _world_a()

    class _Unscoped:
        def __init__(self, inner):  # type: ignore[no-untyped-def]
            self._inner = inner

        def provider_id(self):  # type: ignore[no-untyped-def]
            return self._inner.provider_id()

        def capabilities(self):  # type: ignore[no-untyped-def]
            return self._inner.capabilities()

        def healthcheck(self):  # type: ignore[no-untyped-def]
            return self._inner.healthcheck()

        def search(self, query):  # type: ignore[no-untyped-def]
            return self._inner.search(query)

        def fetch(self, locator):  # type: ignore[no-untyped-def]
            return self._inner.fetch(locator)

        def retrieve(self, locator, *, project_id):  # type: ignore[no-untyped-def]
            del project_id
            return self._inner.retrieve(locator, project_id=PROJECT)

    world.registry.register(_Unscoped(world.github), github_declaration())
    for locator in (LOCATOR, PUBLIC):
        with pytest.raises(SnapshotRefused, match="another access scope"):
            world.service.snapshot("github", locator, project_id=PROJECT_B, actor_id=ACTOR)
    assert not world.sink.stored
    assert world.store.for_request(PROJECT_B, "github", LOCATOR) == ()
    assert _refusal_reasons(world, PROJECT_B) == ["ACCESS_SCOPE_MISMATCH"] * 2


def test_each_project_reads_privately_under_its_own_scope_and_credential():
    """The valid half: A and B each allowlist the repository and each hold their own credential.
    Each reads with its own token only, each snapshot names its own project's scope, and neither
    project's snapshot is visible from, or a cache hit for, the other."""
    world = _world_a()
    world.transport.tokens[TOKEN_B] = (PRIVATE_REPO,)
    world.github_for(
        PROJECT_B,
        allowlist=frozenset({PRIVATE_REPO}),
        credential_ref="lab-token",
        secrets={"lab-token": TOKEN_B},
    )
    in_a = world.service.snapshot("github", LOCATOR, project_id=PROJECT, actor_id=ACTOR)
    presented_by_a = list(world.transport.presented)
    in_b = world.service.snapshot("github", LOCATOR, project_id=PROJECT_B, actor_id=ACTOR)
    presented_by_b = world.transport.presented[len(presented_by_a) :]
    assert set(presented_by_a) == {TOKEN} and set(presented_by_b) == {TOKEN_B}
    assert (in_a.project_id, in_a.access_policy_ref) == (PROJECT, "ghp:m5@1.0.0")
    assert (in_b.project_id, in_b.access_policy_ref) == (PROJECT_B, "ghp:B@1.0.0")
    for snapshot in (in_a, in_b):
        assert snapshot.visibility is Visibility.PRIVATE
        assert snapshot.sensitivity is SensitivityLabel.CONFIDENTIAL_LAB
    assert in_a.snapshot_id != in_b.snapshot_id and in_a.content_hash == in_b.content_hash
    assert world.store.snapshot(PROJECT_B, in_a.snapshot_id) is None
    assert ExternalSourceEventKind.CACHE_HIT not in [e.kind for e in _events(world, PROJECT_B)]
    assert _refusal_reasons(world, PROJECT) == _refusal_reasons(world, PROJECT_B) == []
    # Public material needs no scope of B's own to be read correctly -- but B reads it through
    # B's connector, never A's.
    before = len(world.transport.presented)
    public_b = world.service.snapshot("github", PUBLIC, project_id=PROJECT_B, actor_id=ACTOR)
    assert public_b.access_policy_ref == "ghp:B@1.0.0"
    assert len(world.transport.presented) == before, "public reads are anonymous"


def test_the_service_refuses_a_foreign_scope_even_if_the_registry_misroutes():
    """Defence in depth: a registry that hands project B project A's connector (a bug, or a
    subclass) still gets no request made -- the service checks the scope before egress."""
    world = _world_a()
    registry = world.registry

    class _Misrouting(ConnectorRegistry):
        def adapter(self, provider_id, *, project_id):  # type: ignore[no-untyped-def]
            del project_id
            return registry.adapter(provider_id, project_id=PROJECT)

    misrouting = _Misrouting()
    misrouting._adapters = registry._adapters  # the same registrations, looked up wrongly
    misrouting._declarations = registry._declarations
    world.service._registry = misrouting
    with pytest.raises(SnapshotRefused, match="GH-002"):
        world.service.snapshot("github", LOCATOR, project_id=PROJECT_B, actor_id=ACTOR)
    assert world.transport.calls == []
    assert _refusal_reasons(world, PROJECT_B) == ["NO_ACCESS_SCOPE_FOR_PROJECT"]


def test_private_material_from_an_adapter_with_no_scope_is_never_kept():
    """A project-neutral adapter has no authorization to have read private material with; if one
    returns some (and says nothing about whose access it used), it is refused before storage."""
    world = _world_a()
    inner = world.github

    class _Laundering:
        def provider_id(self):  # type: ignore[no-untyped-def]
            return inner.provider_id()

        def capabilities(self):  # type: ignore[no-untyped-def]
            return inner.capabilities()

        def healthcheck(self):  # type: ignore[no-untyped-def]
            return inner.healthcheck()

        def search(self, query):  # type: ignore[no-untyped-def]
            return inner.search(query)

        def fetch(self, locator):  # type: ignore[no-untyped-def]
            return inner.fetch(locator)

        def retrieve(self, locator, *, project_id):  # type: ignore[no-untyped-def]
            del project_id
            pinned = inner.retrieve(locator, project_id=PROJECT)
            metadata = {
                k: v
                for k, v in pinned.record.metadata.items()
                if k not in ("access_project", "access_policy")
            }
            return dataclasses.replace(
                pinned, record=dataclasses.replace(pinned.record, metadata=metadata)
            )

    world.registry.register(_Laundering(), github_declaration())
    with pytest.raises(SnapshotRefused, match="another access scope"):
        world.service.snapshot("github", LOCATOR, project_id=PROJECT_B, actor_id=ACTOR)
    assert not world.sink.stored
    assert _refusal_reasons(world, PROJECT_B) == ["ACCESS_SCOPE_MISMATCH"]
