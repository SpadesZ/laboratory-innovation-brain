"""M5's world: a code host and a literature corpus behind the ExternalSourceAdapter boundary.

Everything external here is a deterministic fixture -- `FixtureGitHubTransport` over
`fixtures/external/github_fixture.json` and `LiteratureCorpusAdapter` over
`fixtures/external/literature_corpus.json`. No test in this repository performs a live GitHub or
literature request except the `network`-marked one, which is deselected by default.

The egress policy opens GitHub and the literature provider to PUBLIC material only, so a query
derived from INTERNAL or restricted context is refused before the transport is entered (SEC-001,
§22 "restricted context 不得被用於 uncontrolled public search"). It approves GitHub for every project
on purpose: egress approval is per project, and it is NOT what keeps project B out of project A's
authorization -- the access scope is (GH-002), and the cross-project tests rely on egress saying yes.

The GitHub connector is registered for the world's project, as its access scope requires; the
literature adapter holds no authorization and is registered deployment-wide. Credentials live in one
deployment-wide resolver, namespaced by project -- `world.secrets` -- so a test can give project A a
secret and check that project B's policy cannot reach it by naming the same reference.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.repositories.external_sources import (
    ExternalSourceStore,
    InMemoryExternalSourceStore,
)
from lab_brain.security.egress import EgressAuditLog, EgressGate, EgressPolicy, PrivacyMode
from lab_brain.security.external import AuthorizedExternalRunner
from lab_brain.sources.external import ConnectorRegistry
from lab_brain.sources.snapshots import (
    ExternalArtifactSink,
    ExternalSnapshotService,
    InMemoryExternalArtifactSink,
    RetentionPolicy,
    WorkStatusSink,
)
from lab_brain.tool_providers.github import (
    FixtureGitHubTransport,
    GitHubAccessPolicy,
    GitHubConnector,
    StaticCredentials,
)
from lab_brain.tool_providers.github import declaration as github_declaration
from lab_brain.tool_providers.literature import LiteratureCorpusAdapter
from lab_brain.tool_providers.literature import declaration as literature_declaration
from tests.classification_fixtures import labelled

ROOT = Path(__file__).resolve().parents[1]
GITHUB_FIXTURE = ROOT / "fixtures" / "external" / "github_fixture.json"
LITERATURE_FIXTURE = ROOT / "fixtures" / "external" / "literature_corpus.json"

PROJECT = "prj:m5"
ACTOR = "act:researcher"
T0 = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)

PUBLIC_REPO = "photonics-lab/pn-modulator-sim"
PRIVATE_REPO = "photonics-lab/calibration-private"
UNLICENSED_REPO = "someone/unlicensed-rs-tools"
COPYLEFT_REPO = "gpl-org/rs-fit"
REMOVABLE_REPO = "old-org/soon-removed"
MAIN_COMMIT = "0973bc59702b6e5d7b2470d896983afd84c6d958"
V10_COMMIT = "006f0988d53f7c488aa9a457948d4fb6d23a548a"
TOKEN = "fixture-token-lab"


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def __call__(self) -> dt.datetime:
        self.at = self.at + dt.timedelta(seconds=1)
        return self.at


class Ids:
    def __init__(self, scope: str = "m5") -> None:
        self.scope = scope
        self.counts: dict[str, int] = {}

    def __call__(self, kind: str) -> str:
        from lab_brain.core.models.identifiers import new_id

        prefix = new_id(kind).split(":", 1)[0]
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return f"{prefix}:{self.scope}-{self.counts[kind]:04d}"


def runner(project_id: str = PROJECT) -> AuthorizedExternalRunner:
    del project_id  # every project gets the same egress approval; see the module docstring
    public_only = frozenset({SensitivityLabel.PUBLIC})
    return AuthorizedExternalRunner(
        gate=EgressGate(
            policy_for=lambda p: EgressPolicy(
                policy_id=f"egp:{p}",
                version="1.0.0",
                project_id=p,
                mode=PrivacyMode.RESEARCH,
                declared_by_actor_id="act:pi",
                permitted_labels=public_only,
                approved_providers=frozenset({"github", "literature"}),
            ),
            clearance_of=lambda _a, _p: frozenset(
                {SensitivityLabel.PUBLIC, SensitivityLabel.INTERNAL}
            ),
        ),
        audit=EgressAuditLog(),
    )


def access_policy(
    *,
    allowlist: frozenset[str] = frozenset(),
    credential_ref: str | None = None,
    project_id: str = PROJECT,
    version: str = "1.0.0",
) -> GitHubAccessPolicy:
    return GitHubAccessPolicy(
        policy_id="ghp:" + project_id.removeprefix("prj:"),
        version=version,
        project_id=project_id,
        declared_by_actor_id="act:pi",
        private_allowlist=allowlist,
        credential_ref=credential_ref,
    )


@dataclass
class ExternalWorld:
    transport: FixtureGitHubTransport
    github: GitHubConnector
    literature: LiteratureCorpusAdapter
    registry: ConnectorRegistry
    service: ExternalSnapshotService
    store: ExternalSourceStore
    sink: Any
    runner: AuthorizedExternalRunner
    clock: Clock
    mint: Ids
    #: project id -> credential reference -> secret; the deployment's one resolver reads this.
    secrets: dict[str, dict[str, str]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def github_for(
        self,
        project_id: str,
        *,
        allowlist: frozenset[str] = frozenset(),
        credential_ref: str | None = None,
        secrets: dict[str, str] | None = None,
        register: bool = True,
    ) -> GitHubConnector:
        """A second project's own connector on the same host, resolver and audit."""
        if secrets:
            self.secrets.setdefault(project_id, {}).update(secrets)
        connector = GitHubConnector(
            transport=self.transport,
            policy=access_policy(
                allowlist=allowlist, credential_ref=credential_ref, project_id=project_id
            ),
            credentials=StaticCredentials(self.secrets),
            audit=self.service,
            now=self.clock,
        )
        if register:
            self.registry.register(connector, github_declaration(), project_id=project_id)
        return connector


def build(
    *,
    store: ExternalSourceStore | None = None,
    sink: ExternalArtifactSink | None = None,
    allowlist: frozenset[str] = frozenset(),
    credential_ref: str | None = None,
    secrets: dict[str, str] | None = None,
    project_id: str = PROJECT,
    with_github: bool = True,
    context_labels: dict[str, SensitivityLabel] | None = None,
    works: WorkStatusSink | None = None,
) -> ExternalWorld:
    clock = Clock()
    mint = Ids()
    store = store or InMemoryExternalSourceStore()
    sink = sink or InMemoryExternalArtifactSink()
    transport = FixtureGitHubTransport.from_file(GITHUB_FIXTURE)
    registry = ConnectorRegistry()
    authorized = runner(project_id)
    classifier = labelled(context_labels or {}, project_id=project_id)
    service_holder: dict[str, ExternalSnapshotService] = {}
    vault: dict[str, dict[str, str]] = {project_id: dict(secrets or {})}

    class _Audit:
        def record_refusal(self, refusal: Any) -> None:
            service_holder["service"].record_refusal(refusal)

    github = GitHubConnector(
        transport=transport,
        policy=access_policy(
            allowlist=allowlist, credential_ref=credential_ref, project_id=project_id
        ),
        credentials=StaticCredentials(vault),
        audit=_Audit(),
        now=clock,
    )
    literature = LiteratureCorpusAdapter.from_file(LITERATURE_FIXTURE, now=clock)
    if with_github:
        registry.register(github, github_declaration(), project_id=project_id)
    registry.register(literature, literature_declaration())
    service = ExternalSnapshotService(
        registry=registry,
        runner=authorized,
        classifier=classifier,
        store=store,
        sink=sink,
        retention=RetentionPolicy(),
        mint=mint,
        now=clock,
        works=works,
    )
    service_holder["service"] = service
    return ExternalWorld(
        transport=transport,
        github=github,
        literature=literature,
        registry=registry,
        service=service,
        store=store,
        sink=sink,
        runner=authorized,
        clock=clock,
        mint=mint,
        secrets=vault,
    )


def file_locator(repo: str, ref: str, path: str) -> str:
    return f"github:{repo}@{ref}:{path}"


__all__ = [
    "ACTOR",
    "COPYLEFT_REPO",
    "GITHUB_FIXTURE",
    "LITERATURE_FIXTURE",
    "MAIN_COMMIT",
    "PRIVATE_REPO",
    "PROJECT",
    "PUBLIC_REPO",
    "REMOVABLE_REPO",
    "T0",
    "TOKEN",
    "UNLICENSED_REPO",
    "V10_COMMIT",
    "ExternalWorld",
    "access_policy",
    "build",
    "file_locator",
    "runner",
]
