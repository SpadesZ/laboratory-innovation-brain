"""M5's extension of the external source boundary: pinned retrieval, refusal audit, registry.

    §17.21  ExternalSourceAdapter { ..., snapshot(locator_or_record, ref?, policy) -> ArtifactRef }
    §26.1   M5: ExternalSourceAdapter registry、... ref-pinned snapshot/cache
    AGT-008 disabling/replacing one provider does not require cognition source changes.

M1 built `ExternalSourceAdapter` (search / fetch / capabilities / healthcheck) and `SourceRouter`,
and they are hard-locked. §17.21's `snapshot` is realised in two halves, and the split is the point:

    the provider half   `RetrievingAdapter.retrieve(locator, project_id=)` -- resolve the
                        requested version to an immutable one (a branch to a commit SHA, a DOI to
                        a version), read the bytes AT that version, and return them with a record
                        whose `canonical_locator` names the pinned version and whose
                        `content_hash` is the hash of exactly those bytes. A provider knows how to
                        pin.
    the storage half    `sources.snapshots.ExternalSnapshotService.snapshot` -- decide under the
                        rights policy what may be kept, store it content-addressed as an
                        EXTERNAL_CONNECTOR artifact in the project, and write the provenance row.
                        A provider does not decide retention, and does not hold a store.

So no provider can write an artifact, and no rights decision depends on a vendor adapter
remembering to make it.

THE REGISTRY CHECKS WHAT IT IS GIVEN. `ConnectorRegistry.register` refuses an adapter whose
declared capabilities contradict its shape (a snapshot-capable declaration with no `retrieve`, an
empty provider id, a trust ceiling that claims PEER_REVIEWED for a code host) -- the conformance
test AGT-008 names, applied at registration rather than hoped for in review. Removing a provider is
a supported operation and changes nothing else.

AN ADAPTER THAT CARRIES AUTHORIZATION BELONGS TO ONE PROJECT (GH-002). An adapter holding an
allowlist or able to resolve a credential declares an `ExternalAccessScope`. The registry registers
it for that project only -- never deployment-wide, never for another project -- and looks adapters
up BY PROJECT: a project gets its own scoped adapter, else a project-neutral one, and never another
project's. The router it hands out is bound to that project too, so a caller cannot build a router
for project A and then search or fetch for project B through it. The M1 router and the M1 adapter
protocol are unchanged; the binding is added around them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.external_source import (
    NON_EXTERNAL_TRUST,
    TECHNICAL_SOURCE_TYPES,
    ExternalAccessScope,
)
from lab_brain.security.classification import ContextClassifier
from lab_brain.security.external import AuthorizedExternalRunner
from lab_brain.sources.adapter import (
    ExternalSourceAdapter,
    ExternalSourceRecord,
    SourceQuery,
    SourceRouter,
)

SCIENTIFIC_TRUST = frozenset(
    {TrustClass.PEER_REVIEWED, TrustClass.INTERNAL_MEASUREMENT, TrustClass.INTERNAL_RUN}
)


class ConnectorRegistrationError(ValueError):
    """An adapter's declaration contradicts its shape."""


class ProjectScopeMismatch(PermissionError):
    """A request for one project reached authorization that belongs to another (GH-002)."""


@dataclass(frozen=True)
class PinnedContent:
    """The provider half of §17.21's snapshot: bytes at an immutable version, and their record."""

    record: ExternalSourceRecord
    content: bytes
    media_type: str
    #: The version the caller asked for, as asked ("main", "v1.0", a DOI without version).
    requested_ref: str | None = None

    def __post_init__(self) -> None:
        digest = "sha256:" + hashlib.sha256(self.content).hexdigest()
        if self.record.content_hash != digest:
            raise ValueError(
                f"{self.record.provider} returned {self.record.canonical_locator} with "
                f"content_hash {self.record.content_hash!r} for bytes hashing to {digest}; a "
                "pinned record must hash exactly the bytes it came with"
            )
        if self.record.version_ref is None:
            raise ValueError(
                f"{self.record.canonical_locator} is not pinned to a version; a snapshot of a "
                "moving target cannot be reproduced (§6.16, risk P1 'remote source drift')"
            )


@runtime_checkable
class RetrievingAdapter(ExternalSourceAdapter, Protocol):
    """An adapter that can pin and read what it indexes (§17.21's snapshot, provider half)."""

    def retrieve(self, locator: str, *, project_id: str) -> PinnedContent:
        """Pin and read for ``project_id``. An adapter with an access scope refuses any other
        project before it resolves a credential or makes a request."""
        ...


@runtime_checkable
class ScopedAdapter(Protocol):
    """An adapter that carries one project's authorization (see the module docstring)."""

    def access_scope(self) -> ExternalAccessScope: ...


def access_scope_of(adapter: object) -> ExternalAccessScope | None:
    """The project authorization an adapter carries, or `None` for a project-neutral adapter."""
    return adapter.access_scope() if isinstance(adapter, ScopedAdapter) else None


@dataclass(frozen=True)
class ConnectorRefusal:
    """An access refusal, as audit evidence (GH-002). Structurally without payload.

    The locator is recorded as a digest: the audit record proves WHICH request was refused, to
    anyone who holds the request, without writing a private repository's name or a query into a
    log read more widely than the material itself.
    """

    provider_id: str
    project_id: str
    reason_code: str
    locator_digest: str
    at: dt.datetime

    @staticmethod
    def digest(locator: str) -> str:
        return "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()


class ConnectorAudit(Protocol):
    def record_refusal(self, refusal: ConnectorRefusal) -> None: ...


@dataclass
class InMemoryConnectorAudit:
    refusals: list[ConnectorRefusal] = field(default_factory=list)

    def record_refusal(self, refusal: ConnectorRefusal) -> None:
        self.refusals.append(refusal)


@dataclass(frozen=True)
class ConnectorDeclaration:
    """What a deployment declares about a registered provider, beyond its capabilities.

    ``trust_ceiling`` is the most a record from this provider may be labelled (§6.5). A code host's
    ceiling is TECHNICAL_ARTIFACT, and the registry refuses a higher one -- GH-003's "不得自動升級為
    peer-reviewed scientific evidence" enforced where the provider is admitted, before any record.
    """

    provider_id: str
    trust_ceiling: tuple[TrustClass, ...]
    technical_only: bool = False


class ConnectorRegistry:
    """Capability-based registry of external adapters (§26.1 M5, AGT-008), scoped by project."""

    def __init__(self) -> None:
        #: provider -> registration scope (a project id, or `None` for deployment-wide) -> adapter
        self._adapters: dict[str, dict[str | None, ExternalSourceAdapter]] = {}
        self._declarations: dict[str, ConnectorDeclaration] = {}

    def register(
        self,
        adapter: ExternalSourceAdapter,
        declaration: ConnectorDeclaration,
        *,
        project_id: str | None = None,
    ) -> ExternalSourceAdapter:
        """Register for one project, or deployment-wide when ``project_id`` is `None`.

        An adapter carrying an access scope is registered for its scope's project and nowhere
        else: deployment-wide it would serve every project, and for another project it would
        hand that project this one's allowlist and credential.
        """
        if not isinstance(adapter, ExternalSourceAdapter):
            raise ConnectorRegistrationError(f"{adapter!r} is not an ExternalSourceAdapter")
        provider = adapter.provider_id()
        if not provider or provider != declaration.provider_id:
            raise ConnectorRegistrationError(
                f"adapter provider id {provider!r} does not match its declaration "
                f"{declaration.provider_id!r}"
            )
        capabilities = adapter.capabilities()
        if capabilities.provider_id != provider:
            raise ConnectorRegistrationError(
                f"{provider} declares capabilities for {capabilities.provider_id!r}"
            )
        if capabilities.can_snapshot and not isinstance(adapter, RetrievingAdapter):
            raise ConnectorRegistrationError(
                f"{provider} declares can_snapshot but cannot retrieve pinned content; a snapshot "
                "capability with nothing behind it would be discovered by the first citation"
            )
        if not declaration.trust_ceiling:
            raise ConnectorRegistrationError(f"{provider} declares no trust ceiling")
        internal = set(declaration.trust_ceiling) & NON_EXTERNAL_TRUST
        if internal:
            raise ConnectorRegistrationError(
                f"{provider} declares {sorted(t.value for t in internal)} in its trust ceiling; "
                "no external source is the lab's own run or measurement, and an expert heuristic "
                "enters by human approval (P16), not through a connector (§6.5)"
            )
        if declaration.technical_only and set(declaration.trust_ceiling) & SCIENTIFIC_TRUST:
            raise ConnectorRegistrationError(
                f"{provider} is a technical source and declares a scientific trust ceiling "
                f"{sorted(t.value for t in declaration.trust_ceiling)}. GH-003: technical and "
                "prior-art material is never promoted to peer-reviewed evidence"
            )
        scope = access_scope_of(adapter)
        if scope is not None and (scope.provider != provider or scope.project_id != project_id):
            where = "deployment-wide" if project_id is None else f"for project {project_id}"
            raise ConnectorRegistrationError(
                f"{provider} carries project {scope.project_id}'s access scope {scope.policy_ref} "
                f"for provider {scope.provider}; it cannot be registered {where}. Authorization "
                "belongs to one project and serves no other (GH-002)"
            )
        known = self._declarations.get(provider)
        if known is not None and known != declaration:
            raise ConnectorRegistrationError(
                f"{provider} is already registered under a different declaration; one provider "
                "has one trust ceiling in a deployment"
            )
        scopes = self._adapters.setdefault(provider, {})
        if project_id in scopes:
            where = "deployment-wide" if project_id is None else f"for project {project_id}"
            raise ConnectorRegistrationError(f"{provider} is already registered {where}")
        scopes[project_id] = adapter
        self._declarations[provider] = declaration
        return adapter

    def remove(self, provider_id: str, *, project_id: str | None = None) -> None:
        """Supported, and changes nothing else (AGT-008, M5's exit gate).

        Without ``project_id`` the provider is removed from every scope -- "removing the GitHub
        provider" in the exit gate's sense.
        """
        if project_id is None:
            self._adapters.pop(provider_id, None)
            self._declarations.pop(provider_id, None)
            return
        scopes = self._adapters.get(provider_id, {})
        scopes.pop(project_id, None)
        if not scopes:
            self._adapters.pop(provider_id, None)
            self._declarations.pop(provider_id, None)

    def declaration(self, provider_id: str) -> ConnectorDeclaration | None:
        return self._declarations.get(provider_id)

    def adapter(self, provider_id: str, *, project_id: str) -> ExternalSourceAdapter | None:
        """The project's own adapter, else the deployment-wide one -- never another project's."""
        scopes = self._adapters.get(provider_id, {})
        return scopes.get(project_id, scopes.get(None))

    def registered_elsewhere(self, provider_id: str, *, project_id: str) -> bool:
        """Whether the provider exists here only under other projects' authorization."""
        scopes = self._adapters.get(provider_id, {})
        return bool(scopes) and self.adapter(provider_id, project_id=project_id) is None

    def router(
        self,
        *,
        project_id: str,
        runner: AuthorizedExternalRunner,
        classifier: ContextClassifier,
    ) -> ProjectBoundRouter:
        """M1's router over what this project may use now, bound to this project."""
        adapters = [
            adapter
            for provider in sorted(self._adapters)
            if (adapter := self.adapter(provider, project_id=project_id)) is not None
        ]
        return ProjectBoundRouter(
            adapters, project_id=project_id, runner=runner, classifier=classifier
        )

    def clamp(self, record: ExternalSourceRecord) -> ExternalSourceRecord:
        """A record as the deployment admits it: never above its provider's trust ceiling."""
        declaration = self._declarations.get(record.provider)
        if declaration is None:
            raise ConnectorRegistrationError(f"no provider {record.provider} is registered")
        if record.trust_class in declaration.trust_ceiling and not (
            record.source_type in TECHNICAL_SOURCE_TYPES and record.trust_class in SCIENTIFIC_TRUST
        ):
            return record
        raise ConnectorRegistrationError(
            f"{record.provider} returned {record.canonical_locator} labelled "
            f"{record.trust_class.value} ({record.source_type}); its declared ceiling is "
            f"{sorted(t.value for t in declaration.trust_ceiling)}. A provider does not get to "
            "promote its own records (§6.5, GH-003)"
        )

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def __iter__(self) -> Iterator[ExternalSourceAdapter]:
        return iter(
            scopes[key]
            for provider in sorted(self._adapters)
            for scopes in (self._adapters[provider],)
            for key in sorted(scopes, key=lambda k: k or "")
        )

    def __len__(self) -> int:
        return len(self._adapters)


def _refuse_foreign(adapter: ExternalSourceAdapter, project_id: str) -> None:
    scope = access_scope_of(adapter)
    if scope is not None and scope.project_id != project_id:
        raise ProjectScopeMismatch(
            f"{adapter.provider_id()} carries project {scope.project_id}'s access scope "
            f"{scope.policy_ref}; a router bound to project {project_id} cannot hold it (GH-002)"
        )


class ProjectBoundRouter(SourceRouter):
    """M1's `SourceRouter`, bound to one project (GH-002).

    It holds only adapters that are project-neutral or scoped to its project, refuses to be
    given another project's, and refuses a search, fetch or authorization read for any other
    project -- so the per-call `project_id` M1's router accepts can no longer steer a request
    for one project through adapters chosen for another. M1's router itself is unchanged.
    """

    def __init__(
        self,
        adapters: Sequence[ExternalSourceAdapter] = (),
        *,
        project_id: str,
        runner: AuthorizedExternalRunner,
        classifier: ContextClassifier,
    ) -> None:
        for adapter in adapters:
            _refuse_foreign(adapter, project_id)
        super().__init__(adapters, runner=runner, classifier=classifier)
        self._project_id = project_id

    @property
    def project_id(self) -> str:
        return self._project_id

    def _bound(self, project_id: str) -> None:
        if project_id != self._project_id:
            raise ProjectScopeMismatch(
                f"this router is bound to project {self._project_id}; a request for project "
                f"{project_id} is routed through that project's own router (GH-002)"
            )

    def register(self, adapter: ExternalSourceAdapter) -> None:
        _refuse_foreign(adapter, self._project_id)
        super().register(adapter)

    def search(
        self,
        query: SourceQuery,
        *,
        project_id: str,
        actor_id: str,
        context_artifact_ids: Sequence[str] = (),
        escalate: frozenset[SensitivityLabel] = frozenset(),
    ) -> tuple[ExternalSourceRecord, ...]:
        self._bound(project_id)
        return super().search(
            query,
            project_id=project_id,
            actor_id=actor_id,
            context_artifact_ids=context_artifact_ids,
            escalate=escalate,
        )

    def authorized_providers(
        self,
        *,
        project_id: str,
        actor_id: str,
        context_artifact_ids: Sequence[str] = (),
        escalate: frozenset[SensitivityLabel] = frozenset(),
    ) -> tuple[str, ...]:
        self._bound(project_id)
        return super().authorized_providers(
            project_id=project_id,
            actor_id=actor_id,
            context_artifact_ids=context_artifact_ids,
            escalate=escalate,
        )

    def fetch(
        self,
        provider_id: str,
        locator: str,
        *,
        project_id: str,
        actor_id: str,
        context_artifact_ids: Sequence[str] = (),
        escalate: frozenset[SensitivityLabel] = frozenset(),
    ) -> ExternalSourceRecord:
        self._bound(project_id)
        return super().fetch(
            provider_id,
            locator,
            project_id=project_id,
            actor_id=actor_id,
            context_artifact_ids=context_artifact_ids,
            escalate=escalate,
        )


__all__ = [
    "SCIENTIFIC_TRUST",
    "TECHNICAL_SOURCE_TYPES",
    "ConnectorAudit",
    "ConnectorDeclaration",
    "ConnectorRefusal",
    "ConnectorRegistrationError",
    "ConnectorRegistry",
    "InMemoryConnectorAudit",
    "PinnedContent",
    "ProjectBoundRouter",
    "ProjectScopeMismatch",
    "RetrievingAdapter",
    "ScopedAdapter",
    "access_scope_of",
]
