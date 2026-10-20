"""The GitHubConnector: public discovery, ref-pinned retrieval, and policy-gated private access.

    GH-001  GitHubConnector 至少支援 public repo discovery + ref/commit-pinned file fetch +
            normalized provenance record。
    GH-002  private repo access 需 explicit auth/allowlist/security policy；
            未授權時必須 fail closed。
    GH-003  GitHub technical/prior-art evidence 不得自動升級為 peer-reviewed scientific evidence；
            repo/ref/commit 必須保存。

AN `ExternalSourceAdapter`, AND NOTHING THE COGNITION LAYER COULD NAME. It lives under
`tool_providers`, is registered by a deployment, and is reached only through `SourceRouter` and
`ExternalSnapshotService`. Removing it removes GitHub from the searched set and changes nothing else
(M5's exit gate); `tests/unit/test_extension_boundary.py` and
`tests/contract/test_external_source_registry.py` hold that no core, cognition, evidence,
verification, ingestion or sources module imports it.

LOCATORS, AND WHAT PINNING MEANS.

    github:<owner>/<repo>                   a repository (discovery)
    github:<owner>/<repo>@<ref>:<path>      a file at a branch, tag or commit

Git forbids ':' in ref names, so the grammar is unambiguous. `retrieve` resolves `<ref>` to a
40-hex commit SHA, reads the file AT that commit, and returns a record whose canonical locator names
the commit -- `github:owner/repo@<sha>:<path>` -- with the requested ref, the resolved commit, the
repository's immutable numeric id, the path, the retrieval time and the sha256 of the bytes. A
requested commit SHA that no longer resolves is REF_DRIFT: the connector does not silently fall back
to a branch head, which would be a different version presented as the one asked for.

PRIVATE ACCESS FAILS CLOSED (GH-002). A repository is read with a credential only when BOTH hold:
it is on the project's allowlist, and the policy names a credential that resolves. Otherwise the
request is made anonymously -- a credential is never presented for a repository nobody allowlisted,
so a token cannot widen what a project reaches -- and a private repository then answers "not
found", which is refused and audited. An allowlisted repository with no resolvable credential is
refused BEFORE any request. Every refusal is recorded through `ConnectorAudit` as a digest of the
locator and a reason code: no repository name, no query, no token.

ONE CONNECTOR, ONE PROJECT (GH-002). A connector is built for one project's access policy and
declares that as its `ExternalAccessScope`. `retrieve` takes the requesting project and refuses any
other one FIRST -- before the locator is parsed, a credential resolved or a request made -- so a
request for project B can never be served by project A's allowlist or token, whatever registry or
router it came through. Credentials are resolved per project: a policy naming a credential
reference resolves it in its own project's namespace, so project B's policy cannot name project A's
secret. `fetch`, the M1 path that carries no project, is anonymous only: it never presents a
credential, so it cannot be the way around the binding.

GITHUB IS TECHNICAL MATERIAL (GH-003). Every record is TECHNICAL_ARTIFACT, whatever the
repository's stars or README claim; the registry refuses a declaration that would let this provider
label anything higher, and `002c` refuses a snapshot or an attestation that tries.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.core.models.external_source import ExternalAccessScope
from lab_brain.security.external import ExternalReach
from lab_brain.sources.adapter import (
    ExternalSourceRecord,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
    SourceVisibility,
)
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.sources.external import (
    ConnectorAudit,
    ConnectorDeclaration,
    ConnectorRefusal,
    PinnedContent,
)
from lab_brain.tool_providers.github import transport as wire
from lab_brain.tool_providers.github.transport import GitHubTransport, RepoInfo, TransportError

PROVIDER_ID = "github"

_LOCATOR = re.compile(
    r"^github:(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<name>[A-Za-z0-9._-]{1,100})"
    r"(?:@(?P<ref>[^:\s]+):(?P<path>[^\s]+))?$"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

#: SPDX identifiers by SEC-004 class. Anything unlisted is UNKNOWN -- never guessed permissive.
_PERMISSIVE = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense", "Zlib"}
)
_COPYLEFT_PREFIXES = ("GPL-", "LGPL-", "AGPL-", "MPL-", "EPL-", "EUPL-", "CC-BY-SA-")


def license_class_for(spdx: str | None, *, private: bool) -> LicenseClass:
    if spdx in _PERMISSIVE:
        return LicenseClass.PERMISSIVE
    if spdx is not None and spdx.startswith(_COPYLEFT_PREFIXES):
        return LicenseClass.COPYLEFT
    if private and spdx in (None, "NOASSERTION"):
        # Somebody's private code with no licence is theirs: not UNKNOWN, PROPRIETARY.
        return LicenseClass.PROPRIETARY
    return LicenseClass.UNKNOWN


@dataclass(frozen=True)
class Locator:
    owner: str
    name: str
    ref: str | None = None
    path: str | None = None

    @classmethod
    def parse(cls, text: str) -> Locator:
        match = _LOCATOR.match(text)
        if match is None:
            raise ConnectorError(
                ConnectorErrorKind.NOT_FOUND,
                provider_id=PROVIDER_ID,
                detail="not a github locator (github:<owner>/<repo>[@<ref>:<path>])",
            )
        return cls(match["owner"], match["name"], match["ref"], match["path"])

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class CredentialResolver(Protocol):
    """Resolves a credential REFERENCE to a secret, within one project's namespace (GH-002).

    The reference is config; the secret is not. The same reference in two projects names two
    different secrets, and a reference with no secret in the asking project resolves to nothing --
    never to another project's secret of that name.
    """

    def resolve(self, project_id: str, credential_ref: str) -> str | None: ...


@dataclass(frozen=True)
class StaticCredentials:
    #: project id -> credential reference -> secret
    secrets: Mapping[str, Mapping[str, str]]

    def resolve(self, project_id: str, credential_ref: str) -> str | None:
        return self.secrets.get(project_id, {}).get(credential_ref)


@dataclass(frozen=True)
class GitHubAccessPolicy:
    """A project's declared GitHub access (GH-002). Authored, versioned, project-scoped."""

    policy_id: str
    version: str
    project_id: str
    declared_by_actor_id: str
    #: `owner/repo` names this project may read privately. Empty means public-only.
    private_allowlist: frozenset[str] = frozenset()
    #: A reference the CredentialResolver turns into a token. `None` means anonymous only.
    credential_ref: str | None = None
    #: The label private material is stored under in this project (§14.1).
    private_label: SensitivityLabel = SensitivityLabel.CONFIDENTIAL_LAB

    def __post_init__(self) -> None:
        if not self.declared_by_actor_id.strip():
            raise ValueError("an access policy nobody declared is a permission nobody granted")
        if self.private_label is SensitivityLabel.PUBLIC:
            raise ValueError("private repository content cannot be labelled PUBLIC")

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"


def declaration() -> ConnectorDeclaration:
    """How a deployment registers this provider: technical material, nothing higher (GH-003)."""
    return ConnectorDeclaration(
        provider_id=PROVIDER_ID,
        trust_ceiling=(TrustClass.TECHNICAL_ARTIFACT,),
        technical_only=True,
    )


class GitHubConnector:
    """See the module docstring. One instance serves one project's access policy."""

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        policy: GitHubAccessPolicy,
        credentials: CredentialResolver,
        audit: ConnectorAudit,
        now: Callable[[], dt.datetime],
    ) -> None:
        self._transport = transport
        self._policy = policy
        self._credentials = credentials
        self._audit = audit
        self._now = now

    # -- §17.21 ----------------------------------------------------------------------------

    def provider_id(self) -> str:
        return PROVIDER_ID

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            provider_id=PROVIDER_ID,
            can_search=True,
            can_fetch=True,
            can_snapshot=True,
            # What may be SENT to GitHub: public material only. A search query is disclosed to
            # the provider, and SEC-001's gate reads this before the transport is entered.
            max_sensitivity=SensitivityLabel.PUBLIC,
            reach=ExternalReach.EXTERNAL,
        )

    @property
    def policy(self) -> GitHubAccessPolicy:
        return self._policy

    def access_scope(self) -> ExternalAccessScope:
        """The one project this connector's allowlist and credential belong to (GH-002)."""
        return ExternalAccessScope(
            policy_ref=self._policy.ref,
            project_id=self._policy.project_id,
            provider=PROVIDER_ID,
            declared_by_actor_id=self._policy.declared_by_actor_id,
            private_allowlist=self._policy.private_allowlist,
        )

    def healthcheck(self) -> SourceHealthReport:
        try:
            status = self._transport.rate_limit()
        except TransportError as failed:
            return SourceHealthReport(PROVIDER_ID, False, f"{failed.kind}: {failed.detail}")
        if status.remaining <= 0:
            return SourceHealthReport(
                PROVIDER_ID, False, f"rate limited; resets in {status.reset_after_s}s"
            )
        return SourceHealthReport(PROVIDER_ID, True, self._transport.name)

    def search(self, query: SourceQuery) -> Sequence[ExternalSourceRecord]:
        """Public discovery. ALWAYS anonymous: a credential never widens a search (GH-002)."""
        try:
            found = self._transport.search_repositories(query.text, query.limit, token=None)
        except TransportError as failed:
            raise self._structured(failed) from failed
        return tuple(self._repository_record(info, pinned=None) for info in found)

    def fetch(self, locator: str) -> ExternalSourceRecord | None:
        """M1's project-unaware lookup. ANONYMOUS ONLY: it never presents a credential (GH-002)."""
        parsed = Locator.parse(locator)
        if parsed.path is None:
            info = self._repository(parsed, None, locator)
            commit = self._pin(parsed, info.default_branch, None)
            return self._repository_record(info, pinned=commit)
        return self._read(parsed, locator, token=None).record

    def retrieve(self, locator: str, *, project_id: str) -> PinnedContent:
        """The provider half of §17.21's snapshot: resolve, pin, read, hash. GH-001.

        For ``project_id`` only, and only if it is this connector's project: checked before
        anything else (GH-002).
        """
        if project_id != self._policy.project_id:
            self._refuse(
                "PROJECT_SCOPE_MISMATCH",
                locator,
                ConnectorErrorKind.NOT_AUTHORIZED,
                "this connector carries another project's access policy and serves no other "
                "project; nothing was resolved or requested (GH-002)",
                project_id=project_id,
            )
        parsed = Locator.parse(locator)
        return self._read(parsed, locator, token=self._access(parsed, locator))

    def _read(self, parsed: Locator, locator: str, *, token: str | None) -> PinnedContent:
        if parsed.path is None or parsed.ref is None:
            raise ConnectorError(
                ConnectorErrorKind.NOT_FOUND,
                provider_id=PROVIDER_ID,
                detail="retrieval needs a file locator with a ref: "
                "github:<owner>/<repo>@<ref>:<path>",
            )
        info = self._repository(parsed, token, locator)
        commit = self._pin(parsed, parsed.ref, token)
        try:
            content = self._transport.read_file(
                parsed.owner, parsed.name, commit, parsed.path, token=token
            )
        except TransportError as failed:
            raise self._structured(failed, commit) from failed
        record = ExternalSourceRecord(
            provider=PROVIDER_ID,
            source_type="code_file",
            canonical_locator=f"github:{info.full_name}@{commit}:{parsed.path}",
            retrieved_at=self._now(),
            visibility=SourceVisibility.PRIVATE if info.private else SourceVisibility.PUBLIC,
            trust_class=TrustClass.TECHNICAL_ARTIFACT,
            sensitivity=self._policy.private_label if info.private else SensitivityLabel.PUBLIC,
            title=parsed.path,
            owner=info.owner,
            version_ref=commit,
            content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
            rights_status=f"licence:{info.license_spdx}" if info.license_spdx else "no-licence",
            license_class=license_class_for(info.license_spdx, private=info.private),
            license_identifier=info.license_spdx,
            metadata={
                "repository": info.full_name,
                "repository_id": str(info.repo_id),
                "requested_ref": parsed.ref,
                "resolved_commit": commit,
                "path": parsed.path,
                "access_policy": self._policy.ref,
                "access_project": self._policy.project_id,
                "authenticated": "yes" if token is not None else "no",
            },
        )
        return PinnedContent(
            record=record, content=content, media_type="text/plain", requested_ref=parsed.ref
        )

    # -- internals ------------------------------------------------------------------------

    def _refuse(
        self,
        reason: str,
        locator: str,
        kind: ConnectorErrorKind,
        detail: str,
        *,
        project_id: str | None = None,
    ) -> None:
        """Audit by digest and raise. The refusal is recorded in the REQUESTING project's log."""
        self._audit.record_refusal(
            ConnectorRefusal(
                provider_id=PROVIDER_ID,
                project_id=project_id or self._policy.project_id,
                reason_code=reason,
                locator_digest=ConnectorRefusal.digest(locator),
                at=self._now(),
            )
        )
        raise ConnectorError(kind, provider_id=PROVIDER_ID, detail=detail, audited=True)

    def _access(self, parsed: Locator, locator: str) -> str | None:
        """The credential for this repository, or `None` for anonymous access. GH-002."""
        if parsed.full_name not in self._policy.private_allowlist:
            return None
        token = (
            self._credentials.resolve(self._policy.project_id, self._policy.credential_ref)
            if self._policy.credential_ref is not None
            else None
        )
        if token is None:
            self._refuse(
                "PRIVATE_ACCESS_WITHOUT_CREDENTIAL",
                locator,
                ConnectorErrorKind.NOT_AUTHORIZED,
                f"the repository is allowlisted for private access under {self._policy.ref} but "
                "no credential is configured; private access fails closed (GH-002)",
            )
        return token

    def _repository(self, parsed: Locator, token: str | None, locator: str) -> RepoInfo:
        try:
            return self._transport.repository(parsed.owner, parsed.name, token=token)
        except TransportError as failed:
            if failed.kind == wire.NOT_FOUND and token is None:
                self._refuse(
                    "NOT_VISIBLE_WITHOUT_AUTHORIZATION",
                    locator,
                    ConnectorErrorKind.NOT_FOUND,
                    "no repository is visible at this locator without authorization; a private "
                    "repository is read only when allowlisted for this project with a credential "
                    "(GH-002)",
                )
            if failed.kind == wire.UNAUTHORIZED:
                self._refuse(
                    "CREDENTIAL_REFUSED",
                    locator,
                    ConnectorErrorKind.AUTHENTICATION_FAILED,
                    "the provider refused the configured credential",
                )
            raise self._structured(failed) from failed

    def _pin(self, parsed: Locator, ref: str, token: str | None) -> str:
        try:
            commit = self._transport.resolve_ref(parsed.owner, parsed.name, ref, token=token)
        except TransportError as failed:
            if failed.kind == wire.NOT_FOUND and _COMMIT.match(ref):
                raise ConnectorError(
                    ConnectorErrorKind.REF_DRIFT,
                    provider_id=PROVIDER_ID,
                    detail="the pinned commit no longer resolves; no other version is substituted",
                ) from failed
            raise self._structured(failed) from failed
        if not _COMMIT.match(commit):
            raise ConnectorError(
                ConnectorErrorKind.REF_DRIFT,
                provider_id=PROVIDER_ID,
                detail="the provider resolved the ref to something that is not a commit SHA",
            )
        if _COMMIT.match(ref) and commit != ref:
            raise ConnectorError(
                ConnectorErrorKind.REF_DRIFT,
                provider_id=PROVIDER_ID,
                detail="a pinned commit resolved to a different commit",
            )
        return commit

    def _structured(self, failed: TransportError, pinned: str | None = None) -> ConnectorError:
        kind = {
            wire.NOT_FOUND: ConnectorErrorKind.NOT_FOUND,
            wire.UNAUTHORIZED: ConnectorErrorKind.AUTHENTICATION_FAILED,
            wire.RATE_LIMITED: ConnectorErrorKind.RATE_LIMITED,
            wire.GONE: ConnectorErrorKind.SOURCE_REMOVED,
            wire.NETWORK: ConnectorErrorKind.NETWORK_UNAVAILABLE,
        }.get(failed.kind, ConnectorErrorKind.NETWORK_UNAVAILABLE)
        return ConnectorError(
            kind,
            provider_id=PROVIDER_ID,
            detail=failed.detail,
            retry_after_s=failed.retry_after_s,
            pinned_ref=pinned,
        )

    def _repository_record(self, info: RepoInfo, *, pinned: str | None) -> ExternalSourceRecord:
        return ExternalSourceRecord(
            provider=PROVIDER_ID,
            source_type="repository",
            canonical_locator=f"github:{info.full_name}",
            retrieved_at=self._now(),
            visibility=SourceVisibility.PRIVATE if info.private else SourceVisibility.PUBLIC,
            trust_class=TrustClass.TECHNICAL_ARTIFACT,
            sensitivity=self._policy.private_label if info.private else SensitivityLabel.PUBLIC,
            title=info.full_name,
            owner=info.owner,
            version_ref=pinned,
            rights_status=f"licence:{info.license_spdx}" if info.license_spdx else "no-licence",
            license_class=license_class_for(info.license_spdx, private=info.private),
            license_identifier=info.license_spdx,
            metadata={
                "repository": info.full_name,
                "repository_id": str(info.repo_id),
                "default_branch": info.default_branch,
                "description": info.description,
            },
        )


__all__ = [
    "PROVIDER_ID",
    "CredentialResolver",
    "GitHubAccessPolicy",
    "GitHubConnector",
    "Locator",
    "StaticCredentials",
    "declaration",
    "license_class_for",
]
