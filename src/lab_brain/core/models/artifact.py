"""Artifact — the immutable, content-addressed root of every provenance chain (§17.1).

Everything entering the system becomes an Artifact first: paper PDFs, simulation projects,
scripts, output arrays, images, meeting transcripts, external repo snapshots. ART-001 requires
every one to carry an immutable id, a hash, a source and a timestamp, because a metric that
cannot be traced back to bytes is not evidence.

The identity is derived from content, never assigned. See ``identifiers.py``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import (
    LicenseClass,
    SecretScanStatus,
    SensitivityLabel,
    SourceOrigin,
)
from lab_brain.core.models.identifiers import (
    artifact_id_for,
    compute_content_hash,
    parse_content_hash,
)


class RightsMetadata(CoreModel):
    """License and reuse terms. SEC-004 blocks UNKNOWN/COPYLEFT from codegen context."""

    license_class: LicenseClass = LicenseClass.UNKNOWN
    license_identifier: str | None = None
    attribution_required: bool = True
    source_url: str | None = None
    retrieved_at: dt.datetime | None = None


class Artifact(CoreModel):
    """An immutable research asset, addressed by the hash of its bytes.

    ``artifact_id`` is not an input. It is recomputed from ``content_hash`` on construction, and
    a mismatch is rejected -- so an Artifact whose id does not match its content cannot be
    built, deserialised or loaded from the database.
    """

    artifact_id: str
    content_hash: str
    media_type: str
    uri: str

    # Human-meaningful versioning. Orthogonal to content addressing: a new revision is a new
    # artifact_id, and the lineage fields are what connect them (§6.1).
    #
    # Both default rather than being nullable: every artifact is revision 1 of its own lineage
    # unless it says otherwise. The alternative -- nullable lineage, populated when a second
    # revision appears -- requires mutating the first artifact after the fact, and until that
    # happened a lineage query would not return the original.
    lineage_id: str | None = None
    lineage_revision: int = Field(default=1, ge=1)
    previous_artifact_id: str | None = None

    source_origin: SourceOrigin

    # `project_id` and `sensitivity_label` are deliberately ABSENT (§17.1, ADR-0010, amendment
    # v3.3-a8). They describe a project's copy of the bytes, not the bytes, and the same bytes may
    # be present in several projects under different labels. They live on `ArtifactOccurrence`,
    # keyed on (artifact_id, project_id). `CoreModel` forbids extra fields, so passing either here
    # is a ValidationError rather than a silently ignored kwarg.

    created_at: dt.datetime = Field(default_factory=utc_now)
    #: When the content itself came into being, if known -- a 2019 paper ingested today has a
    #: 2019 `captured_at` and a today `created_at`. Condition-aware retrieval needs the former.
    captured_at: dt.datetime | None = None
    author_or_device: str | None = None
    actor_id: str | None = None

    parser_version: str | None = None
    derived_from_artifact_ids: tuple[str, ...] = ()

    rights_metadata: RightsMetadata | None = None
    #: SEC-003: parsing stages may only run once this is CLEAN or REDACTED.
    secret_scan_status: SecretScanStatus = SecretScanStatus.PENDING
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _identity_must_match_content(self) -> Self:
        parse_content_hash(self.content_hash)
        expected = artifact_id_for(self.content_hash)
        if self.artifact_id != expected:
            raise ValueError(
                f"artifact_id {self.artifact_id!r} is not the content-addressed identity of "
                f"content_hash {self.content_hash!r} (expected {expected!r}). "
                "Artifact identity is derived from content, never assigned."
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _default_lineage_to_self(cls, data: Any) -> Any:
        """An artifact with no declared lineage is revision 1 of its own.

        Applied before validation rather than after, so the frozen instance is never mutated.
        """
        if not isinstance(data, dict) or data.get("lineage_id"):
            return data
        artifact_id = data.get("artifact_id")
        if not isinstance(artifact_id, str):
            return data
        return {**data, "lineage_id": artifact_id}

    @model_validator(mode="after")
    def _lineage_chain_is_traceable(self) -> Self:
        """Revision 2+ must say what it supersedes, and nothing may supersede itself.

        A revision above 1 with no ``previous_artifact_id`` leaves a gap in the chain that
        T-ART-001 walks, so the lineage cannot be reconstructed from the records alone.
        """
        if self.lineage_revision > 1 and self.previous_artifact_id is None:
            raise ValueError(
                f"lineage_revision {self.lineage_revision} requires previous_artifact_id; "
                "a revision chain with a gap cannot be traced"
            )
        if self.lineage_revision == 1 and self.previous_artifact_id is not None:
            raise ValueError(
                "lineage_revision 1 must not declare previous_artifact_id; "
                "revision 1 is the start of the chain"
            )
        if self.previous_artifact_id == self.artifact_id:
            raise ValueError("previous_artifact_id must not be the artifact itself")
        return self

    @model_validator(mode="after")
    def _derivation_is_acyclic_at_depth_one(self) -> Self:
        if self.artifact_id in self.derived_from_artifact_ids:
            raise ValueError("artifact must not be derived from itself")
        return self

    @property
    def is_parseable(self) -> bool:
        """SEC-003: no parsing stage may run until the secret scan has cleared."""
        return self.secret_scan_status in {
            SecretScanStatus.CLEAN,
            SecretScanStatus.REDACTED,
        }

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: str,
        uri: str,
        source_origin: SourceOrigin,
        **extra: Any,
    ) -> Artifact:
        """Build an Artifact by hashing ``data``.

        The only ergonomic constructor, so the ordinary path cannot produce a mismatched id.

        Takes no project or sensitivity argument: classifying bytes is a separate act from
        recording them. Use :meth:`occurrence_in` to place the result in a project.
        """
        content_hash = compute_content_hash(data)
        return cls(
            artifact_id=artifact_id_for(content_hash),
            content_hash=content_hash,
            media_type=media_type,
            uri=uri,
            source_origin=source_origin,
            **extra,
        )

    def occurrence_in(
        self,
        project_id: str,
        sensitivity_label: SensitivityLabel,
        *,
        ingested_by_actor_id: str | None = None,
    ) -> ArtifactOccurrence:
        """Record this artifact's presence in one project, under that project's label.

        Both arguments are required and positional. An ``occurrence_in(project)`` that defaulted
        the label would be the P28 violation the old required field existed to prevent, one layer
        further out.
        """
        return ArtifactOccurrence(
            artifact_id=self.artifact_id,
            project_id=project_id,
            sensitivity_label=sensitivity_label,
            ingested_by_actor_id=ingested_by_actor_id or self.actor_id,
        )

    def next_revision(self, data: bytes, *, uri: str, **overrides: Any) -> Artifact:
        """Build the next lineage revision of this artifact from new bytes.

        Returns a *different* artifact -- new content, new id -- that records this one as its
        predecessor and inherits its lineage. Identical bytes are rejected rather than given
        revision n+1: the same content is the same artifact, not a new version of itself.
        """
        content_hash = compute_content_hash(data)
        if content_hash == self.content_hash:
            raise ValueError(
                "next_revision called with identical bytes; the same content is the same "
                f"artifact ({self.artifact_id}), not a new revision"
            )
        # Inherits properties of the bytes only. A revision does NOT inherit occurrences:
        # revision n+1 is different bytes, so which projects hold it and how each classifies it
        # are new facts. Silently copying the predecessor's label into every project would
        # classify content nobody has looked at.
        fields: dict[str, Any] = {
            "media_type": self.media_type,
            "source_origin": self.source_origin,
            "actor_id": self.actor_id,
        }
        fields.update(overrides)
        return Artifact(
            artifact_id=artifact_id_for(content_hash),
            content_hash=content_hash,
            uri=uri,
            lineage_id=self.lineage_id,
            lineage_revision=self.lineage_revision + 1,
            previous_artifact_id=self.artifact_id,
            **fields,
        )


__all__ = ["Artifact", "RightsMetadata"]
