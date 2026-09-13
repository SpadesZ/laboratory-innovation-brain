"""Repository contracts for the M0a scientific identity entities.

Protocols rather than base classes: the in-memory fake and the PostgreSQL implementation are
independent, and conformance tests run the *same* suite against both. A shared base class would
let the fake inherit behaviour the real store does not have, which is how a suite ends up
passing against a fake and failing in production.

Two rules every implementation must honour, because they are what the M0a requirements mean at
the storage boundary:

**Artifact writes are idempotent on content** (ART-001). Storing the same bytes twice yields one
artifact. Storing *different* content under an existing artifact_id is impossible by
construction, since the id is derived from the content.

**Condition-aware writes are validated** (EVI-005). Observation and Attestation carry a
``conditions_schema_version``; a record whose version is unregistered, or whose condition keys do
not conform, is rejected at write time rather than discovered later.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.source_work import SourceWork


class RepositoryError(RuntimeError):
    """A write violated a storage-level invariant."""


class DuplicateIdentityError(RepositoryError):
    """An identifier already exists with different content."""


@runtime_checkable
class ArtifactRepository(Protocol):
    def add(self, artifact: Artifact) -> Artifact:
        """Store ``artifact``, or return the existing one if these bytes are already stored.

        Idempotent on content. Rejects a payload whose id disagrees with an existing record of
        the same id -- which content addressing makes impossible unless a caller hand-built one.
        """
        ...

    def get(self, artifact_id: str) -> Artifact | None: ...

    def get_by_content_hash(self, content_hash: str) -> Artifact | None:
        """Identical-bytes duplicate detection (UX-001)."""
        ...

    def lineage(self, lineage_id: str) -> tuple[Artifact, ...]:
        """All revisions of one lineage, ordered by ``lineage_revision``."""
        ...

    def list_for_project(self, project_id: str) -> tuple[Artifact, ...]: ...

    def record_occurrence(self, occurrence: ArtifactOccurrence) -> ArtifactOccurrence: ...

    def occurrence(self, artifact_id: str, project_id: str) -> ArtifactOccurrence | None: ...


@runtime_checkable
class SourceWorkRepository(Protocol):
    def add(self, source_work: SourceWork) -> SourceWork: ...

    def get(self, source_work_id: str) -> SourceWork | None: ...

    def find_by_identifier(self, scheme: str, value: str) -> SourceWork | None:
        """Same-work resolution by external identifier (EVI-004).

        A DOI hit is the cheapest reliable way to collapse a preprint and a journal version into
        one work before corroboration is counted.
        """
        ...

    def find_by_artifact(self, artifact_id: str) -> tuple[SourceWork, ...]: ...


@runtime_checkable
class ClaimRepository(Protocol):
    def add(self, claim: Claim) -> Claim: ...

    def get(self, claim_id: str) -> Claim | None: ...

    def find_by_normalized_proposition(
        self, normalized_proposition: str, domain: str | None = None
    ) -> Claim | None: ...

    def resolve(self, claim_id: str) -> Claim | None:
        """Follow ``merged_into_claim_id`` to the surviving claim.

        Attestations written against a claim that later merged must still be counted against the
        survivor, or the merge silently discards evidence.
        """
        ...


@runtime_checkable
class ObservationRepository(Protocol):
    def add(self, observation: Observation) -> Observation:
        """Store an observation. MUST validate ``conditions_schema_version`` (EVI-005)."""
        ...

    def get(self, observation_id: str) -> Observation | None: ...

    def list_for_origin(self, origin_id: str) -> tuple[Observation, ...]:
        """Observations produced by one Run or Artifact."""
        ...


@runtime_checkable
class AttestationRepository(Protocol):
    def add(self, attestation: Attestation) -> Attestation:
        """Store an attestation. MUST validate ``conditions_schema_version`` (EVI-005)."""
        ...

    def get(self, attestation_id: str) -> Attestation | None: ...

    def list_for_subject(self, subject_id: str) -> tuple[Attestation, ...]:
        """Attestations witnessing one Claim or Observation."""
        ...

    def list_for_source(self, source_id: str) -> tuple[Attestation, ...]: ...

    def list_by_extractor_version(
        self, extractor_id: str, extractor_version: str
    ) -> tuple[Attestation, ...]:
        """Selection set for contamination quarantine (§6.18).

        When an extractor version turns out to be systematically wrong, this is what identifies
        everything it produced so belief events can be replayed without it.
        """
        ...


@runtime_checkable
class EvidenceBundleRepository(Protocol):
    """§17.14.1 / EVI-006.

    §22's Bundle Reproducibility criterion requires any LLM scientific output to trace to a
    canonical bundle hash and **reconstruct the same ordered evidence set**. A hash nobody can look
    up proves only that two hashes differ, never what either contained -- so bundles are stored, and
    every read recomputes the hash and rejects a mismatch.
    """

    def add(self, bundle: EvidenceBundle) -> EvidenceBundle: ...

    def get(self, bundle_id: str) -> EvidenceBundle | None:
        """Load a bundle. MUST verify the stored hash against a freshly computed one."""
        ...

    def find_by_hash(self, canonical_hash: str) -> tuple[EvidenceBundle, ...]:
        """Bundles representing the same retrieval.

        Returns a sequence, not a single bundle: the same retrieval legitimately recurs, and each
        occurrence is its own record with its own id and timestamp.
        """
        ...

    def list_for_project(self, project_id: str) -> tuple[EvidenceBundle, ...]: ...


@runtime_checkable
class RelationRepository(Protocol):
    """§17.12 requires every traversal to be bounded and to support ``as_of``."""

    def add(self, relation: RelationJudgment) -> RelationJudgment: ...

    def get(self, relation_id: str) -> RelationJudgment | None: ...

    def neighbors(
        self,
        entity_id: str,
        relation_types: Sequence[RelationType] | None = None,
        as_of: dt.datetime | None = None,
        limit: int = 100,
    ) -> tuple[RelationJudgment, ...]:
        """Relations touching ``entity_id`` in either direction.

        ``limit`` is required, not optional: an unbounded traversal on a dense provenance graph
        is how a retrieval call becomes a full table scan (§17.12).
        """
        ...

    def invalidate(self, relation_id: str, reason: str, actor_id: str) -> RelationJudgment:
        """Close a relation. Never deletes -- the judgment stays in the record (P2)."""
        ...


__all__ = [
    "ArtifactRepository",
    "AttestationRepository",
    "ClaimRepository",
    "DuplicateIdentityError",
    "ObservationRepository",
    "RelationRepository",
    "RepositoryError",
    "SourceWorkRepository",
]
