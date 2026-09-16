"""The persisted `Attestation` -> `RelationJudgment` leg of SYS-001's path.

    §25.3 SYS-001  Core scientific state path MUST be Artifact/SourceWork -> Claim/Observation
                   -> Attestation -> RelationJudgment -> TransitionPolicy -> BeliefRevisionEvent
                   -> EpistemicStateProjection.

Migrations `003` and `004` have had these tables since M0a, and until now only the in-memory
repositories could read them. That was survivable while the belief tests built `RelationJudgment`
objects by hand -- and it is exactly what made the middle of SYS-001's path unproven: a test that
constructs the relations it then evaluates has not shown that admitted evidence *reaches* the
policy, only that the policy handles the objects the test made.

WHAT IS HERE AND WHAT IS NOT. Enough to persist an attestation and a relation and to read them
back the way an episode needs them, which is the leg SYS-001 names. Traversal, bitemporal `as_of`
queries and the `neighbors` contract stay with `InMemoryRelationRepository` and §17.12's
GraphRepository, which is M3 -- adding a half-implemented traversal here would make the seam look
finished.

PROJECT SCOPE IS PART OF THE QUERY, NOT A FILTER AFTERWARDS. SEC-002 again: two projects may
legitimately reference the same hypothesis id, and a read keyed only on the subject would touch
rows the caller has no business seeing on its way to the right answer.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence

from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import EPISTEMIC_RELATION_TYPES, RelationJudgment
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError


class EvidenceStoreError(RepositoryError):
    """An attestation or relation could not be recorded, or was read out of scope."""


_ATTESTATION_COLUMNS = (
    "attestation_id, claim_id, observation_id, epistemic_type, source_artifact_id, "
    "source_work_id, run_id, locator, conditions, conditions_schema_version, field_states, "
    "units, uncertainty, method, extraction_status, verification_status, authority_class, "
    "project_id, extractor_version, extraction_provenance, created_at"
)

_RELATION_COLUMNS = (
    "relation_id, from_entity_id, to_entity_id, relation_type, attributes, "
    "supporting_attestation_ids, condition_match_ref, inference_provenance_id, actor_id, "
    "project_id, valid_from, valid_to, invalidation_reason, created_at"
)


def _jsonb(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class SqlAttestationStore:
    """§17.2 attestations against the `003` table, read back through the model's validator."""

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def add(self, attestation: Attestation) -> Attestation:
        require_durable_connection(self._connection)
        self._connection.execute(
            f"INSERT INTO attestations ({_ATTESTATION_COLUMNS})"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s::jsonb,"
            " %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s)",
            (
                attestation.attestation_id,
                attestation.claim_id,
                attestation.observation_id,
                attestation.epistemic_type.value,
                attestation.source_artifact_id,
                attestation.source_work_id,
                attestation.run_id,
                attestation.locator,
                _jsonb(attestation.conditions),
                attestation.conditions_schema_version,
                _jsonb(
                    {
                        name: field.model_dump(mode="json")
                        for name, field in attestation.field_states.items()
                    }
                ),
                attestation.units,
                None
                if attestation.uncertainty is None
                else _jsonb(attestation.uncertainty.model_dump(mode="json")),
                _jsonb(attestation.method),
                attestation.extraction_status.value,
                attestation.verification_status.value,
                attestation.authority_class,
                attestation.project_id,
                attestation.extractor_version,
                _jsonb(attestation.extraction_provenance.model_dump(mode="json")),
                attestation.created_at,
            ),
        )
        return attestation

    def get(self, project_id: str, attestation_id: str) -> Attestation | None:
        row = self._connection.execute(
            f"SELECT {_ATTESTATION_COLUMNS} FROM attestations"
            " WHERE project_id = %s AND attestation_id = %s",
            (project_id, attestation_id),
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def authority_classes_for(
        self, project_id: str, attestation_ids: Sequence[str]
    ) -> tuple[str, ...]:
        """The distinct, sorted `authority_class` values behind a set of attestations.

        THIS IS THE READ §8.2.1 CANNOT DO FOR ITSELF, and the reason `HypothesisView` carries
        `admitted_authority_classes`. `authority_class` lives on `Attestation`; a `RelationJudgment`
        carries only `supporting_attestation_ids`; and `TransitionPolicy.evaluate` must stay pure,
        so resolving one to the other is the caller's job (§17.14.1 requires the decision snapshot
        to be re-evaluable, which a repository read inside `evaluate` would destroy).

        Sorted and de-duplicated here rather than at the call site, because the result reaches a
        `TransitionDecision` that gets canonicalized and hashed -- an unstable order would make the
        same evidence produce two different `input_hash` values.

        Attestations with no `authority_class` contribute nothing rather than an empty string: the
        column is nullable because core must not invent a domain's vocabulary (ADR-0007), and a
        `""` class would be compared by the DomainPack comparator as if it were one.
        """
        if not attestation_ids:
            return ()
        rows = self._connection.execute(
            "SELECT DISTINCT authority_class FROM attestations"
            " WHERE project_id = %s AND attestation_id = ANY (%s)"
            "   AND authority_class IS NOT NULL",
            (project_id, list(attestation_ids)),
        ).fetchall()
        return tuple(sorted(str(row[0]) for row in rows))

    def _hydrate(self, row: Sequence[object]) -> Attestation:
        return Attestation.model_validate(
            {
                "attestation_id": row[0],
                "claim_id": row[1],
                "observation_id": row[2],
                "epistemic_type": row[3],
                "source_artifact_id": row[4],
                "source_work_id": row[5],
                "run_id": row[6],
                "locator": row[7],
                "conditions": row[8],
                "conditions_schema_version": row[9],
                "field_states": row[10],
                "units": row[11],
                "uncertainty": row[12],
                "method": row[13],
                "extraction_status": row[14],
                "verification_status": row[15],
                "authority_class": row[16],
                "project_id": row[17],
                "extractor_version": row[18],
                "extraction_provenance": row[19],
                "created_at": row[20],
            }
        )


class SqlRelationStore:
    """§17.8 relation judgments against the `004` table."""

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def add(self, relation: RelationJudgment) -> RelationJudgment:
        require_durable_connection(self._connection)
        self._connection.execute(
            f"INSERT INTO relation_judgments ({_RELATION_COLUMNS})"
            " VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                relation.relation_id,
                relation.from_entity_id,
                relation.to_entity_id,
                relation.relation_type.value,
                _jsonb(relation.attributes),
                list(relation.supporting_attestation_ids),
                relation.condition_match_ref,
                relation.inference_provenance_id,
                relation.actor_id,
                relation.project_id,
                relation.valid_from,
                relation.valid_to,
                relation.invalidation_reason,
                relation.created_at,
            ),
        )
        return relation

    def get(self, project_id: str, relation_id: str) -> RelationJudgment | None:
        row = self._connection.execute(
            f"SELECT {_RELATION_COLUMNS} FROM relation_judgments"
            " WHERE project_id = %s AND relation_id = %s",
            (project_id, relation_id),
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def admitted_for_subject(
        self, project_id: str, subject_id: str
    ) -> tuple[RelationJudgment, ...]:
        """The currently-held epistemic judgments pointing at one subject, in a stable order.

        "Admitted" means three things at once, and dropping any of them changes what a policy sees:

        * **epistemic** -- only SUPPORTS / CONTRADICTS / TESTS / PREDICTS move belief (§17.8).
          `CITES` and `SAME_WORK_AS` are bookkeeping, and feeding them to `required_relation_types`
          would let a citation satisfy a support requirement.
        * **current** -- `valid_to IS NULL`. An invalidated judgment is history; replaying today's
          decision against a relation somebody has since withdrawn produces a belief the lab does
          not hold.
        * **this project's** -- SEC-002.

        Ordered by `(valid_from, relation_id)`, a total order, because the result goes into a
        `DecisionInputSnapshot` that is canonicalized and hashed: two runs that read the same rows
        in different orders would authorize the same transition under two different `input_hash`
        values, and neither would re-derive against the other.
        """
        rows = self._connection.execute(
            f"SELECT {_RELATION_COLUMNS} FROM relation_judgments"
            " WHERE project_id = %s AND to_entity_id = %s AND valid_to IS NULL"
            "   AND relation_type = ANY (%s)"
            " ORDER BY valid_from, relation_id",
            (
                project_id,
                subject_id,
                sorted(kind.value for kind in EPISTEMIC_RELATION_TYPES),
            ),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def invalidate(
        self, *, project_id: str, relation_id: str, reason: str, actor_id: str, at: dt.datetime
    ) -> RelationJudgment:
        """Close a judgment, recording why and who. Never a DELETE (§17.12).

        Goes through the model's own `invalidate`, so the closed row is re-validated rather than
        patched in SQL -- the `model_copy` lesson from `v3.3-a12`.
        """
        require_durable_connection(self._connection)
        existing = self.get(project_id, relation_id)
        if existing is None:
            raise EvidenceStoreError(
                f"relation {relation_id} does not exist in {project_id}. Invalidating an absent "
                "judgment would report success for a relation still held somewhere else -- or in "
                "another project, which is why this is keyed on both"
            )
        if not existing.is_current:
            raise EvidenceStoreError(
                f"relation {relation_id} was already invalidated at "
                f"{existing.valid_to} ({existing.invalidation_reason}). Re-closing it would "
                "overwrite the reason the first withdrawal recorded"
            )
        closed = existing.invalidate(reason=reason, actor_id=actor_id, at=at)
        self._connection.execute(
            "UPDATE relation_judgments SET valid_to = %s, invalidation_reason = %s, actor_id = %s"
            " WHERE relation_id = %s AND project_id = %s AND valid_to IS NULL",
            (closed.valid_to, closed.invalidation_reason, closed.actor_id, relation_id, project_id),
        )
        return closed

    def _hydrate(self, row: Sequence[object]) -> RelationJudgment:
        return RelationJudgment.model_validate(
            {
                "relation_id": row[0],
                "from_entity_id": row[1],
                "to_entity_id": row[2],
                "relation_type": RelationType(str(row[3])),
                "attributes": row[4],
                "supporting_attestation_ids": tuple(row[5]),  # type: ignore[arg-type]
                "condition_match_ref": row[6],
                "inference_provenance_id": row[7],
                "actor_id": row[8],
                "project_id": row[9],
                "valid_from": row[10],
                "valid_to": row[11],
                "invalidation_reason": row[12],
                "created_at": row[13],
            }
        )


__all__ = [
    "EvidenceStoreError",
    "SqlAttestationStore",
    "SqlRelationStore",
]
