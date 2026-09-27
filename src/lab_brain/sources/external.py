"""M5's extension of the external source boundary: pinned retrieval, refusal audit, registry.

    §17.21  ExternalSourceAdapter { ..., snapshot(locator_or_record, ref?, policy) -> ArtifactRef }
    §26.1   M5: ExternalSourceAdapter registry、... ref-pinned snapshot/cache
    AGT-008 disabling/replacing one provider does not require cognition source changes.

M1 built `ExternalSourceAdapter` (search / fetch / capabilities / healthcheck) and `SourceRouter`,
and they are hard-locked. §17.21's `snapshot` is realised in two halves, and the split is the point:

    the provider half   `RetrievingAdapter.retrieve(locator)` -- resolve the requested version to
                        an immutable one (a branch to a commit SHA, a DOI to a version), read the
                        bytes AT that version, and return them with a record whose
                        `canonical_locator` names the pinned version and whose `content_hash` is
                        the hash of exactly those bytes. A provider knows how to pin.
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
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from lab_brain.core.models.enums import TrustClass
from lab_brain.core.models.external_source import NON_EXTERNAL_TRUST, TECHNICAL_SOURCE_TYPES
from lab_brain.security.classification import ContextClassifier
from lab_brain.security.external import AuthorizedExternalRunner
from lab_brain.sources.adapter import ExternalSourceAdapter, ExternalSourceRecord, SourceRouter

SCIENTIFIC_TRUST = frozenset(
    {TrustClass.PEER_REVIEWED, TrustClass.INTERNAL_MEASUREMENT, TrustClass.INTERNAL_RUN}
)


class ConnectorRegistrationError(ValueError):
    """An adapter's declaration contradicts its shape."""


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

    def retrieve(self, locator: str) -> PinnedContent: ...


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
    """Capability-based registry of external adapters (§26.1 M5, AGT-008)."""

    def __init__(self) -> None:
        self._adapters: dict[str, ExternalSourceAdapter] = {}
        self._declarations: dict[str, ConnectorDeclaration] = {}

    def register(
        self, adapter: ExternalSourceAdapter, declaration: ConnectorDeclaration
    ) -> ExternalSourceAdapter:
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
        if provider in self._adapters:
            raise ConnectorRegistrationError(f"{provider} is already registered")
        self._adapters[provider] = adapter
        self._declarations[provider] = declaration
        return adapter

    def remove(self, provider_id: str) -> None:
        """Supported, and changes nothing else (AGT-008, M5's exit gate)."""
        self._adapters.pop(provider_id, None)
        self._declarations.pop(provider_id, None)

    def declaration(self, provider_id: str) -> ConnectorDeclaration | None:
        return self._declarations.get(provider_id)

    def adapter(self, provider_id: str) -> ExternalSourceAdapter | None:
        return self._adapters.get(provider_id)

    def router(
        self, *, runner: AuthorizedExternalRunner, classifier: ContextClassifier
    ) -> SourceRouter:
        """M1's router over what is registered now. The router knows no provider."""
        return SourceRouter(
            [self._adapters[p] for p in sorted(self._adapters)],
            runner=runner,
            classifier=classifier,
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
        return iter(self._adapters[p] for p in sorted(self._adapters))

    def __len__(self) -> int:
        return len(self._adapters)


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
    "RetrievingAdapter",
]
