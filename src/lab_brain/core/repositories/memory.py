"""In-memory repository implementations.

Exists so the core suite runs with no PostgreSQL (AGT-007). Deliberately *not* a convenience
stub: it enforces the same write-time invariants as the SQL implementation, because a fake that
accepts what the real store rejects makes a green suite meaningless.

The conformance suite in ``tests/contract/`` runs against both this and the PostgreSQL
implementation. Any behaviour that differs is a bug in one of them, not an acceptable variation.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.source_work import SourceWork
from lab_brain.core.repositories.protocols import (
    DuplicateIdentityError,
    RepositoryError,
)
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Artifact] = {}
        #: Keyed on (artifact_id, project_id), mirroring the primary key of the
        #: `artifact_occurrences` table. Separate from `_by_id` because the same bytes may be
        #: present in several projects under different labels (ADR-0010).
        self._occurrences: dict[tuple[str, str], ArtifactOccurrence] = {}

    def add(self, artifact: Artifact) -> Artifact:
        existing = self._by_id.get(artifact.artifact_id)
        if existing is not None:
            # Content addressing means equal ids imply equal bytes. A disagreement here means a
            # hand-built record, so it is rejected rather than overwritten.
            if existing.content_hash != artifact.content_hash:
                raise DuplicateIdentityError(
                    f"artifact_id {artifact.artifact_id} already stored with a different "
                    f"content_hash ({existing.content_hash} vs {artifact.content_hash})"
                )
            return existing
        self._by_id[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        return self._by_id.get(artifact_id)

    def get_by_content_hash(self, content_hash: str) -> Artifact | None:
        for artifact in self._by_id.values():
            if artifact.content_hash == content_hash:
                return artifact
        return None

    def lineage(self, lineage_id: str) -> tuple[Artifact, ...]:
        return tuple(
            sorted(
                (a for a in self._by_id.values() if a.lineage_id == lineage_id),
                key=lambda a: a.lineage_revision,
            )
        )

    def list_for_project(self, project_id: str) -> tuple[Artifact, ...]:
        """Artifacts with an occurrence in ``project_id``.

        An artifact alone no longer knows which projects hold it (ADR-0010), so this answers from
        the recorded occurrences. An artifact with no occurrence here is not in this project, even
        though it exists globally -- which is the whole point of the split.
        """
        ids = {key[0] for key in self._occurrences if key[1] == project_id}
        return tuple(
            sorted(
                (a for a in self._by_id.values() if a.artifact_id in ids),
                key=lambda a: (a.created_at, a.artifact_id),
            )
        )

    def record_occurrence(self, occurrence: ArtifactOccurrence) -> ArtifactOccurrence:
        """Place an artifact in a project under that project's label.

        Refuses an occurrence for an artifact this repository has never seen: an occurrence is a
        statement about specific bytes, and one pointing at nothing classifies nothing.
        """
        if occurrence.artifact_id not in self._by_id:
            raise KeyError(
                f"no artifact {occurrence.artifact_id!r}; an occurrence must refer to stored bytes"
            )
        self._occurrences[occurrence.occurrence_key] = occurrence
        return occurrence

    def occurrence(self, artifact_id: str, project_id: str) -> ArtifactOccurrence | None:
        """The occurrence, or None. None means *not present here*, never *unclassified*."""
        return self._occurrences.get((artifact_id, project_id))


class InMemorySourceWorkRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, SourceWork] = {}

    def add(self, source_work: SourceWork) -> SourceWork:
        self._by_id[source_work.source_work_id] = source_work
        return source_work

    def get(self, source_work_id: str) -> SourceWork | None:
        return self._by_id.get(source_work_id)

    def find_by_identifier(self, scheme: str, value: str) -> SourceWork | None:
        needle = f"{scheme.lower()}:{value.lower() if scheme.lower() == 'doi' else value}"
        for work in self._by_id.values():
            if needle in work.identifier_keys:
                return work
        return None

    def find_by_artifact(self, artifact_id: str) -> tuple[SourceWork, ...]:
        return tuple(
            work for work in self._by_id.values() if artifact_id in work.manifestation_artifact_ids
        )


class InMemoryClaimRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Claim] = {}

    def add(self, claim: Claim) -> Claim:
        self._by_id[claim.claim_id] = claim
        return claim

    def get(self, claim_id: str) -> Claim | None:
        return self._by_id.get(claim_id)

    def find_by_normalized_proposition(
        self, normalized_proposition: str, domain: str | None = None
    ) -> Claim | None:
        for claim in self._by_id.values():
            if claim.normalized_proposition == normalized_proposition and claim.domain == domain:
                return claim
        return None

    def resolve(self, claim_id: str) -> Claim | None:
        seen: set[str] = set()
        current = self._by_id.get(claim_id)
        while current is not None and current.merged_into_claim_id is not None:
            if current.claim_id in seen:
                raise RepositoryError(f"claim merge cycle detected starting at {claim_id}")
            seen.add(current.claim_id)
            current = self._by_id.get(current.merged_into_claim_id)
        return current


class InMemoryObservationRepository:
    def __init__(self, conditions: ConditionSchemaRegistry) -> None:
        self._conditions = conditions
        self._by_id: dict[str, Observation] = {}

    def add(self, observation: Observation) -> Observation:
        # EVI-005 is a write-time gate. Validating on read would let unauditable records
        # accumulate and only fail once somebody tried to use them.
        self._conditions.validate(observation.conditions, observation.conditions_schema_version)
        self._by_id[observation.observation_id] = observation
        return observation

    def get(self, observation_id: str) -> Observation | None:
        return self._by_id.get(observation_id)

    def list_for_origin(self, origin_id: str) -> tuple[Observation, ...]:
        return tuple(
            sorted(
                (o for o in self._by_id.values() if o.origin_id == origin_id),
                key=lambda o: (o.created_at, o.observation_id),
            )
        )


class InMemoryAttestationRepository:
    def __init__(self, conditions: ConditionSchemaRegistry) -> None:
        self._conditions = conditions
        self._by_id: dict[str, Attestation] = {}

    def add(self, attestation: Attestation) -> Attestation:
        self._conditions.validate(attestation.conditions, attestation.conditions_schema_version)
        self._by_id[attestation.attestation_id] = attestation
        return attestation

    def get(self, attestation_id: str) -> Attestation | None:
        return self._by_id.get(attestation_id)

    def list_for_subject(self, subject_id: str) -> tuple[Attestation, ...]:
        return tuple(
            sorted(
                (a for a in self._by_id.values() if a.subject_id == subject_id),
                key=lambda a: (a.created_at, a.attestation_id),
            )
        )

    def list_for_source(self, source_id: str) -> tuple[Attestation, ...]:
        return tuple(
            sorted(
                (a for a in self._by_id.values() if a.source_id == source_id),
                key=lambda a: (a.created_at, a.attestation_id),
            )
        )

    def list_by_extractor_version(
        self, extractor_id: str, extractor_version: str
    ) -> tuple[Attestation, ...]:
        return tuple(
            sorted(
                (
                    a
                    for a in self._by_id.values()
                    if a.extraction_provenance.extractor_id == extractor_id
                    and a.extractor_version == extractor_version
                ),
                key=lambda a: (a.created_at, a.attestation_id),
            )
        )


class InMemoryEvidenceBundleRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, EvidenceBundle] = {}

    def add(self, bundle: EvidenceBundle) -> EvidenceBundle:
        existing = self._by_id.get(bundle.bundle_id)
        if existing is not None and existing.canonical_hash != bundle.canonical_hash:
            raise DuplicateIdentityError(
                f"bundle_id {bundle.bundle_id} already stored with a different canonical_hash "
                f"({existing.canonical_hash} vs {bundle.canonical_hash})"
            )
        self._by_id[bundle.bundle_id] = bundle
        return bundle

    def get(self, bundle_id: str) -> EvidenceBundle | None:
        bundle = self._by_id.get(bundle_id)
        if bundle is None:
            return None
        # An in-memory object cannot disagree with itself, but the check is kept so this
        # implementation and the SQL one enforce the same contract. The conformance suite runs
        # against both, and a fake that skips a check makes the suite weaker than it looks.
        if bundle.canonical_hash != bundle.compute_hash():
            raise RepositoryError(
                f"bundle {bundle_id} hash does not match its content; provenance is unverifiable"
            )
        return bundle

    def find_by_hash(self, canonical_hash: str) -> tuple[EvidenceBundle, ...]:
        return tuple(
            sorted(
                (b for b in self._by_id.values() if b.canonical_hash == canonical_hash),
                key=lambda b: (b.created_at, b.bundle_id),
            )
        )

    def list_for_project(self, project_id: str) -> tuple[EvidenceBundle, ...]:
        return tuple(
            sorted(
                (b for b in self._by_id.values() if b.project_id == project_id),
                key=lambda b: (b.created_at, b.bundle_id),
            )
        )


class InMemoryRelationRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, RelationJudgment] = {}

    def add(self, relation: RelationJudgment) -> RelationJudgment:
        self._by_id[relation.relation_id] = relation
        return relation

    def get(self, relation_id: str) -> RelationJudgment | None:
        return self._by_id.get(relation_id)

    def neighbors(
        self,
        entity_id: str,
        relation_types: Sequence[RelationType] | None = None,
        as_of: dt.datetime | None = None,
        limit: int = 100,
    ) -> tuple[RelationJudgment, ...]:
        if limit <= 0:
            raise RepositoryError("limit must be positive; traversal MUST be bounded (§17.12)")
        wanted = set(relation_types) if relation_types else None
        matches = [
            relation
            for relation in self._by_id.values()
            if entity_id in (relation.from_entity_id, relation.to_entity_id)
            and (wanted is None or relation.relation_type in wanted)
            and (relation.is_valid_at(as_of) if as_of else relation.is_current)
        ]
        matches.sort(key=lambda relation: (relation.created_at, relation.relation_id))
        return tuple(matches[:limit])

    def invalidate(self, relation_id: str, reason: str, actor_id: str) -> RelationJudgment:
        relation = self._by_id.get(relation_id)
        if relation is None:
            raise RepositoryError(f"relation {relation_id} not found")
        if not relation.is_current:
            raise RepositoryError(
                f"relation {relation_id} was already invalidated at {relation.valid_to}"
            )
        closed = relation.invalidate(reason=reason, actor_id=actor_id)
        self._by_id[relation_id] = closed
        return closed


__all__ = [
    "InMemoryArtifactRepository",
    "InMemoryAttestationRepository",
    "InMemoryClaimRepository",
    "InMemoryObservationRepository",
    "InMemoryRelationRepository",
    "InMemorySourceWorkRepository",
]
