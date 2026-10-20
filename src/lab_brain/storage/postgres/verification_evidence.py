"""The loop's `EvidenceSink` over PostgreSQL: the existing evidence stores, composed (M4).

Nothing here is a new store. Observations, attestations, relations and condition matches go to
the tables M0a created, through the stores that already own them (`SqlObservationStore`,
`SqlAttestationStore`, `SqlRelationStore`, `SqlConditionMatchStore`), so every constraint and
trigger those tables carry -- EVI-005's payload validation, the relation interval rules, the
attestation subject/source checks -- applies to verification evidence exactly as to any other.
Artifact bytes are read back through the `RunOutputSink` that stored them.
"""

from __future__ import annotations

from typing import Any

from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.enums import SecretScanStatus, SourceOrigin
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.repositories.conditions import SqlConditionMatchStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.observations import SqlObservationStore
from lab_brain.tools.outputs import RunOutputSink


class SqlEvidenceSink:
    def __init__(self, *, connection: Any, outputs: RunOutputSink) -> None:
        self._connection = connection
        self._observations = SqlObservationStore(connection)
        self._attestations = SqlAttestationStore(connection)
        self._relations = SqlRelationStore(connection)
        self._matches = SqlConditionMatchStore(connection)
        self._outputs = outputs

    def add_observation(self, observation: Observation) -> Observation:
        return self._observations.add(observation)

    def add_attestation(self, attestation: Attestation) -> Attestation:
        return self._attestations.add(attestation)

    def add_relation(self, relation: RelationJudgment) -> RelationJudgment:
        return self._relations.add(relation)

    def add_condition_match(self, match: ConditionMatch) -> ConditionMatch:
        return self._matches.add(match)

    def attestation(self, project_id: str, attestation_id: str) -> Attestation | None:
        return self._attestations.get(project_id, attestation_id)

    def observation(self, project_id: str, observation_id: str) -> Observation | None:
        return self._observations.get(project_id, observation_id)

    def relation(self, project_id: str, relation_id: str) -> RelationJudgment | None:
        return self._relations.get(project_id, relation_id)

    def admitted_for_subject(
        self, project_id: str, subject_id: str
    ) -> tuple[RelationJudgment, ...]:
        return self._relations.admitted_for_subject(project_id, subject_id)

    def condition_match(self, condition_match_id: str) -> ConditionMatch | None:
        return self._matches.get(condition_match_id)

    def artifact_exists(self, artifact_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = %s", (artifact_id,)
        ).fetchone()
        return row is not None

    def load_artifact(self, artifact_id: str) -> Artifact | None:
        """The artifact's record, for the admission gate's EVI-009 walk (Run -> Artifact)."""
        row = self._connection.execute(
            "SELECT artifact_id, content_hash, media_type, uri, lineage_id, lineage_revision,"
            " source_origin, secret_scan_status, created_at FROM artifacts WHERE artifact_id = %s",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return Artifact(
            artifact_id=row[0],
            content_hash=row[1],
            media_type=row[2],
            uri=row[3],
            lineage_id=row[4],
            lineage_revision=row[5],
            source_origin=SourceOrigin(row[6]),
            secret_scan_status=SecretScanStatus(row[7]),
            created_at=row[8],
        )

    def artifact_in_project(self, artifact_id: str, project_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
            (artifact_id, project_id),
        ).fetchone()
        return row is not None

    def read_artifact(self, artifact_id: str) -> bytes:
        return self._outputs.read(artifact_id)


__all__ = ["SqlEvidenceSink"]
