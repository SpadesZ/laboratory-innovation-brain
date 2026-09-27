"""The storage half of §17.21's snapshot: rights-governed, content-addressed, pinned, cached.

    §6.16   若某 prior-art conclusion 依賴的 GitHub material 已消失，狀態改為
            SOURCE_UNAVAILABLE 並保留既有 snapshot（若合法且先前已保存）。
    §26.1   M5: ref-pinned snapshot/cache; progressive enrichment.
    §20     (Copyright/rights) rights metadata + source-specific retention；no blanket fair-use
            assumption.

THE FLOW, EVERY STEP AUTHORIZED OR RECORDED:

    discover    `SourceRouter.search` (M1: egress gate per provider, refusals skipped) and one
                DISCOVERED event per record -- metadata only; nothing is pinned or kept yet
    snapshot    the adapter's `retrieve` runs inside `AuthorizedExternalRunner.execute` (SEC-001:
                the locator is what leaves, and it is what the gate judges); the record is clamped
                to the provider's declared trust ceiling (GH-003); the pinned locator is the cache
                key -- a second snapshot of the same pinned version is a CACHE_HIT, never a copy;
                the retention policy decides what may be kept; the kept bytes become an
                EXTERNAL_CONNECTOR artifact in the project under the record's label and rights;
                the provenance row is written; SNAPSHOTTED (and REF_DRIFT when the same request now
                pins a different version) is recorded
    admit       `sources.admission` -- a separate, later step (progressive enrichment)

A CONNECTOR FAILURE IS RECORDED AND RE-RAISED, NEVER PAPERED OVER. When the material an earlier
snapshot of the same request pinned has gone, that snapshot is marked SOURCE_UNAVAILABLE -- by
event; the snapshot rows and their artifacts are untouched, so what was read can still be re-read
(§6.16) -- and every SourceWork admitted from it has its status recorded as SOURCE_UNAVAILABLE,
which is what a conclusion resting on it answers to (EVI-008; `evidence.source_status` maps that
status to NEEDS_HUMAN_REVIEW for a major revision). Nothing substitutes content. "Gone" is decided
narrowly, because an unavailable source pushes every conclusion on it to review:

    SOURCE_REMOVED                          the provider says the container is gone
    NOT_FOUND at a resolved version         only the snapshots pinned AT that version: a path
                                            missing at a branch's new head says nothing about the
                                            commit an earlier snapshot pinned
    NOT_FOUND the connector audited         a change at the source for material this project read
      as a refusal                          publicly (a public repository that vanished is, to an
                                            anonymous caller, "not visible"); NOT for material it
                                            read under authorization -- a withdrawn allowlist is
                                            the project's own decision, not the source's removal
    any other NOT_FOUND                     the container or version is gone

ONE PROJECT'S AUTHORIZATION SERVES ONE PROJECT (GH-002). The adapter is looked up for the
requesting project -- its own scoped adapter, else a project-neutral one, never another project's --
and a provider registered only under other projects' authorization is refused and audited by digest
in the requesting project's log BEFORE any egress. The adapter is then asked to retrieve FOR that
project and refuses any other. After retrieval, and before anything is kept, the record must say it
was read under this project's scope; private material read under any other is refused and nothing
is stored. The scope is recorded before the snapshot that names it, and `002d` refuses a snapshot
whose scope belongs to another project, or private material off its scope's allowlist.

SECRET SCAN FIRST (SEC-003). Material that fails the scan is not stored; the snapshot is downgraded
to METADATA_ONLY with a rule that says why. External code is exactly where credentials leak.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from lab_brain.core.canonical_json import canonical_bytes
from lab_brain.core.models.artifact import RightsMetadata
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, SourceWorkStatus
from lab_brain.core.models.external_source import (
    ExternalAccessScope,
    ExternalSnapshot,
    ExternalSourceEvent,
    ExternalSourceEventKind,
    Retention,
    Visibility,
)
from lab_brain.core.models.identifiers import artifact_id_for, compute_content_hash
from lab_brain.core.models.source_work import RetractionCheck
from lab_brain.core.repositories.external_sources import ExternalSourceStore
from lab_brain.security.classification import ContextClassifier
from lab_brain.security.egress import CodeArtifact
from lab_brain.security.external import AuthorizedExternalRunner, ExternalEffect
from lab_brain.sources.adapter import ExternalSourceRecord, SourceQuery
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.sources.external import (
    ConnectorRefusal,
    ConnectorRegistry,
    PinnedContent,
    RetrievingAdapter,
    access_scope_of,
)

TEXT_SOURCE_TYPES = frozenset({"paper_passage", "web_page"})


class SnapshotRefused(RuntimeError):
    """A snapshot could not be taken as asked (no such provider, provider cannot retrieve)."""


class SecretsFound(RuntimeError):
    """A sink refused bytes that failed the secret scan (SEC-003)."""


class WorkStatusSink(Protocol):
    def record_status(self, source_work_id: str, check: RetractionCheck) -> None: ...


class ExternalArtifactSink(Protocol):
    def store(
        self,
        *,
        project_id: str,
        media_type: str,
        data: bytes,
        label: SensitivityLabel,
        rights: RightsMetadata,
    ) -> str:
        """Store as an EXTERNAL_CONNECTOR artifact present in the project; return its id.

        Raises `SecretsFound` for bytes that fail the secret scan.
        """
        ...


@dataclass
class InMemoryExternalArtifactSink:
    stored: dict[str, bytes] = field(default_factory=dict)
    placed: set[tuple[str, str]] = field(default_factory=set)
    refuse_secrets: tuple[bytes, ...] = (b"AKIA", b"-----BEGIN")

    def store(
        self,
        *,
        project_id: str,
        media_type: str,
        data: bytes,
        label: SensitivityLabel,
        rights: RightsMetadata,
    ) -> str:
        del media_type, label, rights
        if any(marker in data for marker in self.refuse_secrets):
            raise SecretsFound("suspected credential")
        artifact_id = artifact_id_for(compute_content_hash(data))
        self.stored[artifact_id] = data
        self.placed.add((artifact_id, project_id))
        return artifact_id


@dataclass(frozen=True)
class RetentionPolicy:
    """What of an external record may be kept, decided from its rights -- data, versioned."""

    policy_id: str = "rtn:external"
    version: str = "1.0.0"
    #: The longest quotation kept of a text source whose licence permits no reuse.
    excerpt_chars: int = 280

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"

    def decide(self, record: ExternalSourceRecord) -> tuple[Retention, str]:
        if record.visibility.value == Visibility.PRIVATE.value:
            return Retention.FULL_CONTENT, f"{self.ref}:authorized-private"
        if record.license_class is LicenseClass.PERMISSIVE:
            return Retention.FULL_CONTENT, f"{self.ref}:permissive"
        if record.license_class is LicenseClass.COPYLEFT:
            # Kept for provenance; SEC-004 separately keeps it out of code-generation context.
            return Retention.FULL_CONTENT, f"{self.ref}:copyleft-provenance"
        if record.source_type in TEXT_SOURCE_TYPES:
            return Retention.EXCERPT, f"{self.ref}:excerpt-{self.excerpt_chars}"
        return Retention.METADATA_ONLY, f"{self.ref}:no-reuse-licence"


def _rights(record: ExternalSourceRecord) -> RightsMetadata:
    return RightsMetadata(
        license_class=record.license_class,
        license_identifier=record.license_identifier,
        source_url=record.canonical_locator,
        retrieved_at=record.retrieved_at,
    )


class ExternalSnapshotService:
    """See the module docstring."""

    def __init__(
        self,
        *,
        registry: ConnectorRegistry,
        runner: AuthorizedExternalRunner,
        classifier: ContextClassifier,
        store: ExternalSourceStore,
        sink: ExternalArtifactSink,
        retention: RetentionPolicy,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
        works: WorkStatusSink | None = None,
    ) -> None:
        self._registry = registry
        self._works = works
        self._runner = runner
        self._classifier = classifier
        self._store = store
        self._sink = sink
        self._retention = retention
        self._mint = mint
        self._now = now

    # -- events --------------------------------------------------------------------------

    def _event(
        self,
        kind: ExternalSourceEventKind,
        *,
        project_id: str,
        provider: str,
        locator: str,
        actor_id: str | None,
        snapshot_id: str | None = None,
        **detail: str,
    ) -> ExternalSourceEvent:
        return self._store.add_event(
            ExternalSourceEvent(
                event_id=self._mint("external_source_event"),
                project_id=project_id,
                provider=provider,
                kind=kind,
                locator_digest=ConnectorRefusal.digest(locator),
                locator=None if kind is ExternalSourceEventKind.ACCESS_REFUSED else locator,
                snapshot_id=snapshot_id,
                actor_id=actor_id,
                detail=detail,
                occurred_at=self._now(),
            )
        )

    def record_refusal(self, refusal: ConnectorRefusal) -> None:
        """`ConnectorAudit` for a project's connectors: refusals become durable events."""
        self._store.add_event(
            ExternalSourceEvent(
                event_id=self._mint("external_source_event"),
                project_id=refusal.project_id,
                provider=refusal.provider_id,
                kind=ExternalSourceEventKind.ACCESS_REFUSED,
                locator_digest=refusal.locator_digest,
                detail={"reason_code": refusal.reason_code},
                occurred_at=refusal.at,
            )
        )

    # -- discover ------------------------------------------------------------------------

    def discover(
        self,
        query: SourceQuery,
        *,
        project_id: str,
        actor_id: str,
        context_artifact_ids: Sequence[str] = (),
        escalate: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.PUBLIC}),
    ) -> tuple[ExternalSourceRecord, ...]:
        router = self._registry.router(
            project_id=project_id, runner=self._runner, classifier=self._classifier
        )
        found = router.search(
            query,
            project_id=project_id,
            actor_id=actor_id,
            context_artifact_ids=context_artifact_ids,
            escalate=escalate,
        )
        records = tuple(self._registry.clamp(r) for r in found)
        for record in records:
            self._event(
                ExternalSourceEventKind.DISCOVERED,
                project_id=project_id,
                provider=record.provider,
                locator=record.canonical_locator,
                actor_id=actor_id,
                source_type=record.source_type,
                trust_class=record.trust_class.value,
            )
        return records

    # -- snapshot ------------------------------------------------------------------------

    def snapshot(
        self,
        provider_id: str,
        locator: str,
        *,
        project_id: str,
        actor_id: str,
        context_artifact_ids: Sequence[str] = (),
        escalate: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.PUBLIC}),
    ) -> ExternalSnapshot:
        adapter = self._registry.adapter(provider_id, project_id=project_id)
        scope = access_scope_of(adapter)
        if adapter is None or (scope is not None and scope.project_id != project_id):
            if adapter is not None or self._registry.registered_elsewhere(
                provider_id, project_id=project_id
            ):
                # Another project's authorization exists for this provider; this project has
                # none. Refused before egress, and audited here, by digest (GH-002).
                self._refuse_scope(provider_id, locator, project_id, "NO_ACCESS_SCOPE_FOR_PROJECT")
            raise SnapshotRefused(
                f"no provider {provider_id} is registered for project {project_id}; another "
                "project's access is never used in its place (GH-002)"
            )
        if not isinstance(adapter, RetrievingAdapter) or not adapter.capabilities().can_snapshot:
            raise SnapshotRefused(f"{provider_id} cannot retrieve pinned content")
        effect = ExternalEffect(
            project_id=project_id,
            actor_id=actor_id,
            provider_id=provider_id,
            classification=self._classifier.require_artifacts(
                context_artifact_ids, project_id=project_id, declared=escalate
            ),
            material=locator,
            reach=adapter.capabilities().reach,
        )

        def _retrieve() -> PinnedContent:
            return adapter.retrieve(locator, project_id=project_id)

        try:
            pinned = self._runner.execute(effect, _retrieve)
        except ConnectorError as failed:
            self._record_failure(failed, project_id, provider_id, locator, actor_id)
            raise
        record = self._registry.clamp(pinned.record)
        self._within_scope(record, scope, project_id, locator)
        cached = self._store.pinned(project_id, provider_id, record.canonical_locator)
        if cached is not None:
            if cached.content_hash != record.content_hash:
                raise SnapshotRefused(
                    f"{record.canonical_locator} names an immutable version and now hashes to "
                    f"{record.content_hash}, not {cached.content_hash}; the provider's pin is not "
                    "one -- refusing rather than replacing the cached snapshot"
                )
            self._event(
                ExternalSourceEventKind.CACHE_HIT,
                project_id=project_id,
                provider=provider_id,
                locator=record.canonical_locator,
                actor_id=actor_id,
                snapshot_id=cached.snapshot_id,
            )
            return cached
        earlier = self._store.for_request(project_id, provider_id, locator)
        if scope is not None:
            self._store.record_access_scope(scope)
        retention, rule = self._retention.decide(record)
        artifact_id, retention, rule = self._keep(pinned, record, retention, rule, project_id)
        snapshot = self._store.add_snapshot(
            ExternalSnapshot(
                snapshot_id=self._mint("external_snapshot"),
                project_id=project_id,
                provider=provider_id,
                source_type=record.source_type,
                requested_locator=locator,
                canonical_locator=record.canonical_locator,
                requested_ref=pinned.requested_ref,
                resolved_ref=str(record.version_ref),
                repository_identity=_identity(record),
                content_hash=str(record.content_hash),
                artifact_id=artifact_id,
                retention=retention,
                retention_rule=rule,
                visibility=Visibility(record.visibility.value),
                trust_class=record.trust_class,
                sensitivity=record.sensitivity,
                license_class=record.license_class,
                license_identifier=record.license_identifier,
                rights_status=record.rights_status,
                access_policy_ref=record.metadata.get("access_policy"),
                retrieved_at=record.retrieved_at,
                created_at=self._now(),
            )
        )
        self._event(
            ExternalSourceEventKind.SNAPSHOTTED,
            project_id=project_id,
            provider=provider_id,
            locator=snapshot.canonical_locator,
            actor_id=actor_id,
            snapshot_id=snapshot.snapshot_id,
            retention=retention.value,
            resolved_ref=snapshot.resolved_ref,
        )
        drifted = [s for s in earlier if s.resolved_ref != snapshot.resolved_ref]
        if drifted:
            self._event(
                ExternalSourceEventKind.REF_DRIFT,
                project_id=project_id,
                provider=provider_id,
                locator=locator,
                actor_id=actor_id,
                snapshot_id=snapshot.snapshot_id,
                previous_resolved_ref=drifted[-1].resolved_ref,
                resolved_ref=snapshot.resolved_ref,
            )
        return snapshot

    def _refuse_scope(self, provider_id: str, locator: str, project_id: str, reason: str) -> None:
        self.record_refusal(
            ConnectorRefusal(
                provider_id=provider_id,
                project_id=project_id,
                reason_code=reason,
                locator_digest=ConnectorRefusal.digest(locator),
                at=self._now(),
            )
        )

    def _within_scope(
        self,
        record: ExternalSourceRecord,
        scope: ExternalAccessScope | None,
        project_id: str,
        locator: str,
    ) -> None:
        """Before anything is kept: the record was read under THIS project's scope (GH-002)."""
        read_for = record.metadata.get("access_project")
        policy = record.metadata.get("access_policy")
        foreign = read_for is not None and read_for != project_id
        if scope is not None:
            foreign = foreign or policy != scope.policy_ref or scope.project_id != project_id
        unscoped_private = record.visibility.value != Visibility.PUBLIC.value and scope is None
        if foreign or unscoped_private:
            self._refuse_scope(record.provider, locator, project_id, "ACCESS_SCOPE_MISMATCH")
            raise SnapshotRefused(
                f"{record.provider} returned material read under another access scope than "
                f"project {project_id}'s; nothing is kept (GH-002)"
            )

    def _keep(
        self,
        pinned: PinnedContent,
        record: ExternalSourceRecord,
        retention: Retention,
        rule: str,
        project_id: str,
    ) -> tuple[str, Retention, str]:
        if retention is Retention.FULL_CONTENT:
            data, media_type = pinned.content, pinned.media_type
        elif retention is Retention.EXCERPT:
            text = pinned.content.decode("utf-8", errors="replace")
            data = text[: self._retention.excerpt_chars].encode("utf-8")
            media_type = "text/plain"
        else:
            data, media_type = self._metadata_bytes(record), "application/json"
        try:
            artifact_id = self._sink.store(
                project_id=project_id,
                media_type=media_type,
                data=data,
                label=record.sensitivity,
                rights=_rights(record),
            )
        except SecretsFound:
            # SEC-003: the bytes do not reach normal storage. Provenance still does.
            artifact_id = self._sink.store(
                project_id=project_id,
                media_type="application/json",
                data=self._metadata_bytes(record),
                label=record.sensitivity,
                rights=_rights(record),
            )
            return (
                artifact_id,
                Retention.METADATA_ONLY,
                f"{self._retention.ref}:secret-scan-refused",
            )
        return artifact_id, retention, rule

    @staticmethod
    def _metadata_bytes(record: ExternalSourceRecord) -> bytes:
        return canonical_bytes(
            {
                "provider": record.provider,
                "source_type": record.source_type,
                "canonical_locator": record.canonical_locator,
                "version_ref": record.version_ref,
                "content_hash": record.content_hash,
                "retrieved_at": record.retrieved_at.isoformat(),
                "license_class": record.license_class.value,
                "license_identifier": record.license_identifier,
                "rights_status": record.rights_status,
                "metadata": dict(sorted(record.metadata.items())),
            }
        )

    def _record_failure(
        self,
        failed: ConnectorError,
        project_id: str,
        provider_id: str,
        locator: str,
        actor_id: str,
    ) -> None:
        earlier = self._store.for_request(project_id, provider_id, locator)
        for snapshot in _gone(failed, earlier):
            self._event(
                ExternalSourceEventKind.SOURCE_UNAVAILABLE,
                project_id=project_id,
                provider=provider_id,
                locator=snapshot.canonical_locator,
                actor_id=actor_id,
                snapshot_id=snapshot.snapshot_id,
                connector_error=failed.kind.value,
            )
            self._mark_works(snapshot, provider_id)
        if failed.audited:
            # The connector recorded the refusal by digest; recording it again here would name
            # the locator it withheld (GH-002).
            return
        self._event(
            ExternalSourceEventKind.CONNECTOR_ERROR,
            project_id=project_id,
            provider=provider_id,
            locator=locator,
            actor_id=actor_id,
            connector_error=failed.kind.value,
            error_class=failed.error_class,
            **({"pinned_ref": failed.pinned_ref} if failed.pinned_ref else {}),
        )

    def _mark_works(self, snapshot: ExternalSnapshot, provider_id: str) -> None:
        """EVI-008: every work admitted from a now-unavailable snapshot records that status."""
        if self._works is None:
            return
        admitted = {
            e.detail["source_work_id"]
            for e in self._store.events(snapshot.project_id)
            if e.kind is ExternalSourceEventKind.ADMITTED
            and e.snapshot_id == snapshot.snapshot_id
            and "source_work_id" in e.detail
        }
        for source_work_id in sorted(admitted):
            self._works.record_status(
                source_work_id,
                RetractionCheck(
                    status=SourceWorkStatus.SOURCE_UNAVAILABLE,
                    checked_at=self._now(),
                    checked_against=provider_id,
                    notice_locator=snapshot.canonical_locator,
                ),
            )

    def unavailable(self, project_id: str, snapshot_id: str) -> bool:
        """Whether a SOURCE_UNAVAILABLE event names this snapshot (§6.16's status)."""
        return any(
            e.kind is ExternalSourceEventKind.SOURCE_UNAVAILABLE and e.snapshot_id == snapshot_id
            for e in self._store.events(project_id)
        )


def code_artifact(snapshot: ExternalSnapshot) -> CodeArtifact:
    """A kept snapshot as SEC-004's gate sees it before any code-generation context.

    The licence class travels with the snapshot, and the pinned locator is its provenance -- the
    re-checkable record SEC-004 asks for when a project's code policy changes.
    """
    return CodeArtifact(
        artifact_id=snapshot.artifact_id,
        license_class=snapshot.license_class,
        license_identifier=snapshot.license_identifier,
        provenance=snapshot.canonical_locator,
    )


def _gone(failed: ConnectorError, earlier: Sequence[ExternalSnapshot]) -> list[ExternalSnapshot]:
    """The earlier snapshots whose pinned material this failure shows to be gone (docstring)."""
    if failed.kind is ConnectorErrorKind.SOURCE_REMOVED:
        return list(earlier)
    if failed.kind is not ConnectorErrorKind.NOT_FOUND:
        return []
    if failed.pinned_ref is not None:
        return [s for s in earlier if s.resolved_ref == failed.pinned_ref]
    if failed.audited:
        return [s for s in earlier if s.visibility is Visibility.PUBLIC]
    return list(earlier)


def _identity(record: ExternalSourceRecord) -> str | None:
    repository = record.metadata.get("repository")
    repository_id = record.metadata.get("repository_id")
    if repository and repository_id:
        return f"{record.provider}:repository/{repository_id} {repository}"
    doi = record.metadata.get("doi")
    return f"doi:{doi}" if doi else None


__all__ = [
    "ExternalArtifactSink",
    "ExternalSnapshotService",
    "InMemoryExternalArtifactSink",
    "RetentionPolicy",
    "SecretsFound",
    "SnapshotRefused",
    "WorkStatusSink",
    "code_artifact",
]
