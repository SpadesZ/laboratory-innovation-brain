"""External evidence as provenance: the pinned snapshot and its lifecycle (M5, §6.16, §17.21).

    M5 exit gate  external evidence enters with source/condition/rights/provenance metadata;
                  GitHub source 可追到 repo + resolved commit/ref.
    §22           任何被引用的 GitHub file/code/release 能追到 repository identity + resolved
                  commit/ref + retrieved_at + content/snapshot hash.
    §6.16         ... 狀態改為 SOURCE_UNAVAILABLE 並保留既有 snapshot（若合法且先前已保存）。

AN `ExternalSnapshot` IS WHAT A CITATION OF EXTERNAL MATERIAL RESTS ON. It names the provider, the
locator as requested and as pinned, the resolved version, the content hash of what the provider
returned, the artifact the project actually kept, the rights under which it was kept, and the access
policy that let it be read. It is append-only: a later retrieval of a moved branch is a new
snapshot, and the old one stays -- so a conclusion drawn from the old bytes can still be re-read.

WHAT WAS KEPT IS A RIGHTS DECISION, AND THE ROW SAYS WHICH. `retention` is FULL_CONTENT (the
artifact is the bytes; its hash IS the content hash), EXCERPT (a bounded quotation of a text source
whose licence permits no more) or METADATA_ONLY (a canonical JSON record of the provenance, content
hash included, and not the bytes -- §20's "no blanket fair-use assumption"). `retention_rule` names
the rule that decided.

THE LIFECYCLE IS EVENTS. Discovery, pinning, snapshotting, cache hits, admission, drift, removal and
refused access are `ExternalSourceEvent`s. A refused access carries only a digest of the locator (a
private repository's name is itself private context, GH-002); every other event carries the locator.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Code-host material (§5 / GH-003). Never labelled above TECHNICAL_ARTIFACT.
TECHNICAL_SOURCE_TYPES = frozenset({"repository", "code_file", "release"})
#: Source types whose version is a git commit and must be pinned to one (§22 GitHub Provenance).
COMMIT_PINNED_SOURCE_TYPES = frozenset({"code_file", "release"})
#: Trust classes no external source can carry (§6.5): the lab's own runs and measurements are
#: internal by definition, and an expert heuristic enters by human approval (P16), not a connector.
NON_EXTERNAL_TRUST = frozenset(
    {TrustClass.INTERNAL_RUN, TrustClass.INTERNAL_MEASUREMENT, TrustClass.EXPERT_HEURISTIC}
)


class Retention(StrEnum):
    FULL_CONTENT = "FULL_CONTENT"
    EXCERPT = "EXCERPT"
    METADATA_ONLY = "METADATA_ONLY"


class Visibility(StrEnum):
    PUBLIC = "PUBLIC"
    AUTHENTICATED = "AUTHENTICATED"
    PRIVATE = "PRIVATE"


class ExternalAccessScope(CoreModel):
    """Whose authorization an adapter carries (GH-002): one project's, and only that project's.

    An adapter that holds an allowlist or can resolve a credential belongs to exactly one project,
    and serves no other. This is the provider-neutral statement of that binding -- what the
    registry checks at registration, what the snapshot service checks before any authenticated
    request and again before any snapshot is written, and what `002d` checks for every writer of
    SQL: material read under a scope is stored only in the scope's project, and private material
    only when its repository is on the scope's allowlist.

    The credential itself is not here and never is; `policy_ref` names the authored, versioned
    policy the credential reference belongs to.
    """

    policy_ref: str
    project_id: str
    provider: str
    declared_by_actor_id: str
    #: Container names (e.g. "owner/repo") this project may read privately. Empty: public only.
    private_allowlist: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def _a_scope_is_declared(self) -> Self:
        for name in ("policy_ref", "project_id", "provider", "declared_by_actor_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"an access scope names its {name}")
        return self


class ExternalSnapshot(CoreModel):
    snapshot_id: str
    project_id: str
    provider: str
    source_type: str
    #: As the caller asked ("github:o/r@main:x.py") and as pinned ("github:o/r@<sha>:x.py").
    requested_locator: str
    canonical_locator: str
    requested_ref: str | None = None
    resolved_ref: str
    #: The provider's immutable identity of the container, e.g. "github:repository/12345 o/r".
    repository_identity: str | None = None
    #: sha256 of the bytes the provider returned -- whatever was kept.
    content_hash: str
    artifact_id: str
    retention: Retention
    retention_rule: str
    visibility: Visibility
    trust_class: TrustClass
    sensitivity: SensitivityLabel
    license_class: LicenseClass
    license_identifier: str | None = None
    rights_status: str | None = None
    access_policy_ref: str | None = None
    retrieved_at: dt.datetime
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_snapshot_is_pinned_provenance(self) -> Self:
        if not _DIGEST.match(self.content_hash):
            raise ValueError(f"snapshot {self.snapshot_id} content_hash is not sha256:<hex>")
        if not self.resolved_ref.strip():
            raise ValueError(f"snapshot {self.snapshot_id} names no resolved version")
        if self.source_type in COMMIT_PINNED_SOURCE_TYPES:
            if not _COMMIT.match(self.resolved_ref):
                raise ValueError(
                    f"snapshot {self.snapshot_id} of {self.source_type} is pinned to "
                    f"{self.resolved_ref!r}, not a commit SHA (§22 GitHub Provenance)"
                )
            if self.resolved_ref not in self.canonical_locator:
                raise ValueError(
                    f"snapshot {self.snapshot_id}'s canonical locator does not name its commit"
                )
            if not self.repository_identity:
                raise ValueError(f"snapshot {self.snapshot_id} names no repository identity")
        if self.trust_class in NON_EXTERNAL_TRUST:
            raise ValueError(
                f"snapshot {self.snapshot_id} is external material labelled "
                f"{self.trust_class.value}, which no external source can be (§6.5)"
            )
        if self.source_type in TECHNICAL_SOURCE_TYPES and (
            self.trust_class is not TrustClass.TECHNICAL_ARTIFACT
        ):
            raise ValueError(
                f"snapshot {self.snapshot_id} of {self.source_type} is labelled "
                f"{self.trust_class.value}; GH-003: technical material is TECHNICAL_ARTIFACT"
            )
        if self.visibility is not Visibility.PUBLIC and self.sensitivity is SensitivityLabel.PUBLIC:
            raise ValueError(
                f"snapshot {self.snapshot_id} is {self.visibility.value} material labelled PUBLIC"
            )
        return self


class ExternalSourceEventKind(StrEnum):
    DISCOVERED = "DISCOVERED"
    SNAPSHOTTED = "SNAPSHOTTED"
    CACHE_HIT = "CACHE_HIT"
    ADMITTED = "ADMITTED"
    REF_DRIFT = "REF_DRIFT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    ACCESS_REFUSED = "ACCESS_REFUSED"
    CONNECTOR_ERROR = "CONNECTOR_ERROR"


class ExternalSourceEvent(CoreModel):
    event_id: str
    project_id: str
    provider: str
    kind: ExternalSourceEventKind
    locator_digest: str
    #: The locator itself -- absent exactly for ACCESS_REFUSED (see the module docstring).
    locator: str | None = None
    snapshot_id: str | None = None
    actor_id: str | None = None
    #: Machine-readable facts only: reason codes, error classes, resolved refs, counts.
    detail: dict[str, str] = Field(default_factory=dict)
    occurred_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_refusal_carries_no_locator(self) -> Self:
        if not _DIGEST.match(self.locator_digest):
            raise ValueError("locator_digest is not sha256:<hex>")
        refused = self.kind is ExternalSourceEventKind.ACCESS_REFUSED
        if refused and self.locator is not None:
            raise ValueError(
                "an ACCESS_REFUSED event records a digest of the locator, never the locator: a "
                "private repository's name is private context (GH-002)"
            )
        if not refused and self.locator is None:
            raise ValueError(f"a {self.kind.value} event names its locator")
        forbidden = {"query", "text", "content", "token", "credential"} & set(self.detail)
        if forbidden:
            raise ValueError(f"event detail may not carry {sorted(forbidden)}")
        return self


__all__ = [
    "COMMIT_PINNED_SOURCE_TYPES",
    "NON_EXTERNAL_TRUST",
    "TECHNICAL_SOURCE_TYPES",
    "ExternalAccessScope",
    "ExternalSnapshot",
    "ExternalSourceEvent",
    "ExternalSourceEventKind",
    "Retention",
    "Visibility",
]
