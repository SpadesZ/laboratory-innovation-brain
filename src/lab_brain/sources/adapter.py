"""The external source boundary (SRC-001, §17.21, §7.5, §24.2).

§17.21: 所有外部 source provider 必須正規化成同一個 contract；SourceRouter 只依賴 capabilities /
policy / normalized records，不知道 provider 實作細節.

WHAT THE RULE IS PROTECTING. Not tidiness -- §24.2 keeps provider specifics out of the cognition
path because a `github.Repository` or an `arxiv.Result` leaking into reasoning code makes the
reasoning depend on a vendor's schema. When that vendor changes a field name, the change arrives
in the middle of a scientific decision.

So `SourceRouter` sees `ExternalSourceRecord` and nothing else, and a test imports the router's
module and asserts it names no provider.

ADAPTER REMOVAL MUST NOT BREAK STARTUP. §26's T-SRC-001 row makes swapping fakes for real
providers the pass condition, and a router that raised when an adapter was missing would make
every deployment carry every provider. `SourceRouter` reports an absent provider as an
unavailable capability -- which UX-007 already renders as degraded rather than as an error.

THIS IS NOT GH-001/002/003. Those are M5 and concern GitHub specifically: auth modes, private
repository access, rate limits. What is built here is the *contract* they will have to satisfy,
exercised with deterministic local adapters.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.security.external import (
    AuthorizedExternalRunner,
    ExternalEffect,
    ExternalEffectRefused,
    ExternalReach,
)


class SourceVisibility(StrEnum):
    """§17.21's `visibility`. What kind of access the record required."""

    PUBLIC = "PUBLIC"
    AUTHENTICATED = "AUTHENTICATED"
    PRIVATE = "PRIVATE"


@dataclass(frozen=True)
class SourceCapabilities:
    """§17.21's `capabilities()`. What the router may ask this provider to do."""

    provider_id: str
    can_search: bool = True
    can_fetch: bool = True
    can_snapshot: bool = False
    #: The highest sensitivity this provider may be shown. A provider that only handles public
    #: material declares PUBLIC, and SEC-001's gate reads it -- so the boundary is a property of
    #: the adapter rather than a rule each caller remembers.
    max_sensitivity: SensitivityLabel = SensitivityLabel.PUBLIC
    #: Whether reaching this provider leaves the approved boundary (§14.2).
    #:
    #: DECLARED, never inferred. A local corpus on this machine is a legitimate Private Mode
    #: provider and must keep working with no egress at all -- but "no policy configured, so it
    #: must be local" is exactly what an unwired production deployment looks like. Defaults to
    #: EXTERNAL so an adapter that says nothing is treated as the dangerous case.
    reach: ExternalReach = ExternalReach.EXTERNAL


@dataclass(frozen=True)
class SourceHealthReport:
    """§17.21's `healthcheck()` return, feeding UX-007."""

    provider_id: str
    reachable: bool
    detail: str = ""


@dataclass(frozen=True)
class SourceQuery:
    """A normalized query. No provider syntax: a router that passed through a provider's query
    language would be leaking the provider into every caller that built one."""

    text: str
    limit: int = 10
    since: dt.datetime | None = None


@dataclass(frozen=True)
class ExternalSourceRecord:
    """§17.21's normalized record.

    `rights_status` and `license_metadata` are here rather than discovered later because SEC-004
    decides on them: code arriving with no licence recorded must be distinguishable from code
    recorded as permissive, and a field populated after the fact cannot make that distinction.
    """

    provider: str
    source_type: str
    canonical_locator: str
    retrieved_at: dt.datetime
    visibility: SourceVisibility
    trust_class: TrustClass
    sensitivity: SensitivityLabel
    title: str | None = None
    owner: str | None = None
    version_ref: str | None = None
    content_hash: str | None = None
    snapshot_artifact_id: str | None = None
    rights_status: str | None = None
    license_class: LicenseClass = LicenseClass.UNKNOWN
    license_identifier: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    raw_payload_ref: str | None = None


@runtime_checkable
class ExternalSourceAdapter(Protocol):
    """§17.21's interface. Structural, so an adapter needs no import from this package."""

    def provider_id(self) -> str: ...

    def capabilities(self) -> SourceCapabilities: ...

    def healthcheck(self) -> SourceHealthReport: ...

    def search(self, query: SourceQuery) -> Sequence[ExternalSourceRecord]: ...

    def fetch(self, locator: str) -> ExternalSourceRecord | None: ...


class ProviderUnavailable(RuntimeError):
    """A named provider is not registered, or reports itself unreachable.

    Raised only when a caller asked for that provider BY NAME. A router-wide search over the
    registered set does not raise for a missing one -- see `SourceRouter.search`.
    """


class SourceRouter:
    """§7.5's evidence source router. Knows capabilities, policy and normalized records.

    IT KNOWS NO PROVIDER. There is no `if provider == "github"` anywhere, and
    `test_the_router_names_no_provider` parses this module to say so. The moment such a branch
    exists, the router has a second contract -- the real one, and the one it documents.
    """

    def __init__(
        self,
        adapters: Sequence[ExternalSourceAdapter] = (),
        *,
        runner: AuthorizedExternalRunner,
    ) -> None:
        """``runner`` is REQUIRED and has no default.

        SEC-001 says external connector egress requires policy and Actor clearance. A default of
        `None` would mean a deployment that never wired authorization still builds a working
        router -- and the requirement would be satisfied by convention rather than by
        construction. There is no way to obtain a `SourceRouter` that can reach an adapter
        without one.
        """
        self._adapters = {adapter.provider_id(): adapter for adapter in adapters}
        self._runner = runner

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def register(self, adapter: ExternalSourceAdapter) -> None:
        self._adapters[adapter.provider_id()] = adapter

    def remove(self, provider_id: str) -> None:
        """Removing an adapter is a supported operation, not an error.

        §26 requires swapping fakes for real providers without touching the router or cognition.
        A registry that could not lose a member would make every deployment carry every provider
        -- and an outage in one would then be an outage in all of them.
        """
        self._adapters.pop(provider_id, None)

    def health(self) -> tuple[SourceHealthReport, ...]:
        """For UX-007. An absent adapter contributes nothing rather than an error row."""
        return tuple(adapter.healthcheck() for adapter in self._adapters.values())

    def search(
        self,
        query: SourceQuery,
        *,
        project_id: str,
        actor_id: str,
        sensitivity: SensitivityLabel,
    ) -> tuple[ExternalSourceRecord, ...]:
        """Every adapter this actor is authorized to reach, in one normalized result set.

        AUTHORIZATION IS PER ADAPTER AND HAPPENS BEFORE THE CALL. `runner.execute` performs the
        adapter's `search` only on ALLOW; a refused provider never has its transport entered.
        The query text is what would leave, so it is what the gate digests.

        A refused provider is SKIPPED, like an unreachable one, and for the same reason: turning
        one provider's policy refusal into a failed research query tells the researcher nothing
        and breaks every other provider. The refusal is in the audit log, and UX surfaces read
        `authorized_providers` to explain it.

        `project_id`, `actor_id` and `sensitivity` are required. A search with no actor is an
        unidentified request (§14.4), and a default would be the optional-gate shape again.
        """
        results: list[ExternalSourceRecord] = []
        for adapter in self._adapters.values():
            capabilities = adapter.capabilities()
            if not capabilities.can_search:
                continue
            if not adapter.healthcheck().reachable:
                continue
            effect = ExternalEffect(
                project_id=project_id,
                actor_id=actor_id,
                provider_id=adapter.provider_id(),
                sensitivity=sensitivity,
                material=query.text,
                reach=capabilities.reach,
            )

            def _search(a: ExternalSourceAdapter = adapter) -> Sequence[ExternalSourceRecord]:
                return a.search(query)

            try:
                found = self._runner.execute(effect, _search)
            except ExternalEffectRefused:
                continue
            results.extend(found)
        # Deterministic order, so a retrieval is reproducible across registry iteration order.
        return tuple(sorted(results, key=lambda r: (r.provider, r.canonical_locator)))

    def authorized_providers(
        self, *, project_id: str, actor_id: str, sensitivity: SensitivityLabel
    ) -> tuple[str, ...]:
        """Which registered providers this actor may reach for this material.

        A read, not a permission: it performs nothing. UX surfaces use it to explain why a
        provider produced no results without the researcher having to run a query that is
        refused.
        """
        allowed = []
        for adapter in self._adapters.values():
            decision = self._runner.authorize(
                ExternalEffect(
                    project_id=project_id,
                    actor_id=actor_id,
                    provider_id=adapter.provider_id(),
                    sensitivity=sensitivity,
                    material="",
                    reach=adapter.capabilities().reach,
                )
            )
            if decision.permitted:
                allowed.append(adapter.provider_id())
        return tuple(sorted(allowed))

    def fetch(
        self,
        provider_id: str,
        locator: str,
        *,
        project_id: str,
        actor_id: str,
        sensitivity: SensitivityLabel,
    ) -> ExternalSourceRecord:
        """One record, by name. Raises, because the caller asked for THIS provider.

        A refusal raises `ExternalEffectRefused` rather than being swallowed: the caller named
        one provider, and silently returning nothing would look like "no such record" when the
        truth is "you may not ask".
        """
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            raise ProviderUnavailable(
                f"no adapter registered for {provider_id}; the record cannot be fetched and "
                "guessing another provider would silently change where the evidence came from"
            )
        health = adapter.healthcheck()
        if not health.reachable:
            raise ProviderUnavailable(f"{provider_id} is unreachable: {health.detail}")

        effect = ExternalEffect(
            project_id=project_id,
            actor_id=actor_id,
            provider_id=provider_id,
            sensitivity=sensitivity,
            material=locator,
            reach=adapter.capabilities().reach,
        )

        def _fetch() -> ExternalSourceRecord | None:
            return adapter.fetch(locator)

        record = self._runner.execute(effect, _fetch)
        if record is None:
            raise ProviderUnavailable(f"{provider_id} has no record at {locator}")
        return record

    def capabilities_for(self, provider_id: str) -> SourceCapabilities | None:
        adapter = self._adapters.get(provider_id)
        return None if adapter is None else adapter.capabilities()


__all__ = [
    "ExternalSourceAdapter",
    "ExternalSourceRecord",
    "ProviderUnavailable",
    "SourceCapabilities",
    "SourceHealthReport",
    "SourceQuery",
    "SourceRouter",
    "SourceVisibility",
]
