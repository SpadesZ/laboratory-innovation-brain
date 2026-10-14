"""DIAGNOSTIC_WARRANT reviews and their grants (Causal Warrant Gate, `012o`).

THIN, BECAUSE THE INVARIANTS ARE THE DATABASE'S. `diagnostic_warrant_review_enqueue` prices a
review from the project's active queue policy and returns the existing review for a relation that
was already asked about, whatever its status; `diagnostic_warrant_resolve` writes the grant, the
WARRANT_GRANT resolution and the terminal review in one statement, for an active human member of
the project, exactly once. This class passes arguments and reads rows back.

The in-memory twin enforces the same rules for the core suite (AGT-007), so a test that passes
against it is not passing against something more permissive than PostgreSQL.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence

from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.review import OUTSTANDING_REVIEW_STATUSES, ReviewItem, ReviewStatus
from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.models.warrant import DiagnosticWarrantGrant, GrantVerdict
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError
from lab_brain.core.repositories.reviews import SqlReviewItemStore


class WarrantStoreError(RepositoryError):
    """A warrant review could not be queued or answered."""


_GRANT_COLUMNS = (
    "grant_id, project_id, review_id, relation_id, relation_type, hypothesis_id, prediction_id, "
    "verdict, granted_by_actor_id, granted_at, rationale, considered_rival_ids"
)


def _grant(row: Sequence[object]) -> DiagnosticWarrantGrant:
    names = [n.strip() for n in _GRANT_COLUMNS.split(",")]
    values = dict(zip(names, row, strict=True))
    values["considered_rival_ids"] = tuple(values["considered_rival_ids"] or ())  # type: ignore[arg-type]
    return DiagnosticWarrantGrant.model_validate(values)


class SqlDiagnosticWarrantStore:
    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection
        self._reviews = SqlReviewItemStore(connection)

    def enqueue_warrant_review(
        self,
        *,
        review_id: str,
        project_id: str,
        relation_id: str,
        stakes: str,
        reason: str,
        trace_id: str,
        episode_id: str | None,
        created_at: dt.datetime,
        estimated_minutes: int,
    ) -> str:
        try:
            row = self._connection.execute(
                "SELECT diagnostic_warrant_review_enqueue(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    review_id,
                    project_id,
                    relation_id,
                    stakes,
                    reason,
                    trace_id,
                    episode_id,
                    created_at,
                    estimated_minutes,
                ),
            ).fetchone()
        except Exception as exc:
            raise WarrantStoreError(
                f"the diagnostic warrant for {relation_id} in {project_id} could not be queued: "
                f"{exc}"
            ) from exc
        if row is None:  # pragma: no cover - the function returns an id or raises
            raise WarrantStoreError(
                f"diagnostic_warrant_review_enqueue returned nothing for {review_id}"
            )
        return str(row[0])

    def resolve(
        self,
        *,
        resolution_id: str,
        grant_id: str,
        review_id: str,
        project_id: str,
        outcome: ReviewOutcome,
        actor_id: str,
        rationale: str,
        considered_rival_ids: Sequence[str],
        resolved_at: dt.datetime,
    ) -> DiagnosticWarrantGrant:
        try:
            self._connection.execute(
                "SELECT diagnostic_warrant_resolve(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    resolution_id,
                    grant_id,
                    review_id,
                    project_id,
                    outcome.value,
                    actor_id,
                    rationale,
                    list(considered_rival_ids),
                    resolved_at,
                ),
            )
        except Exception as exc:
            raise WarrantStoreError(
                f"review {review_id} in {project_id} could not be answered: {exc}"
            ) from exc
        written = self.grant(project_id, grant_id)
        if written is None:  # pragma: no cover - the function raises before this is reachable
            raise WarrantStoreError(f"{grant_id} vanished between writing and reading it back")
        return written

    def grant(self, project_id: str, grant_id: str) -> DiagnosticWarrantGrant | None:
        row = self._connection.execute(
            f"SELECT {_GRANT_COLUMNS} FROM diagnostic_warrant_grants"
            " WHERE project_id = %s AND grant_id = %s",
            (project_id, grant_id),
        ).fetchone()
        return None if row is None else _grant(row)

    def grants_for_relations(
        self, project_id: str, relation_ids: Sequence[str]
    ) -> tuple[DiagnosticWarrantGrant, ...]:
        if not relation_ids:
            return ()
        rows = self._connection.execute(
            f"SELECT {_GRANT_COLUMNS} FROM diagnostic_warrant_grants"
            " WHERE project_id = %s AND relation_id = ANY (%s) ORDER BY relation_id",
            (project_id, list(relation_ids)),
        ).fetchall()
        return tuple(_grant(row) for row in rows)

    def review_for_relation(self, project_id: str, relation_id: str) -> ReviewItem | None:
        found = [
            r
            for r in self._reviews.for_subject(project_id, relation_id)
            if r.subject_type.value == "DIAGNOSTIC_WARRANT"
        ]
        return found[0] if found else None

    def outstanding_relations(self, project_id: str, relation_ids: Sequence[str]) -> frozenset[str]:
        """Which of these relations have a warrant review a person still owes an answer on."""
        if not relation_ids:
            return frozenset()
        rows = self._connection.execute(
            "SELECT subject_id FROM review_items WHERE project_id = %s"
            " AND subject_type = 'DIAGNOSTIC_WARRANT' AND subject_id = ANY (%s)"
            " AND status = ANY (%s)",
            (
                project_id,
                list(relation_ids),
                sorted(s.value for s in OUTSTANDING_REVIEW_STATUSES),
            ),
        ).fetchall()
        return frozenset(str(row[0]) for row in rows)

    def outstanding(self, project_id: str) -> tuple[ReviewItem, ...]:
        """Every DIAGNOSTIC_WARRANT review still owed in the project, oldest first."""
        rows = self._connection.execute(
            "SELECT review_id FROM review_items WHERE project_id = %s"
            " AND subject_type = 'DIAGNOSTIC_WARRANT' AND status = ANY (%s)"
            " ORDER BY created_at, review_id",
            (project_id, sorted(s.value for s in OUTSTANDING_REVIEW_STATUSES)),
        ).fetchall()
        found = [self._reviews.get(project_id, str(row[0])) for row in rows]
        return tuple(r for r in found if r is not None)


class InMemoryDiagnosticWarrantStore:
    """The same rules without PostgreSQL: one review per relation, one answer per review."""

    def __init__(
        self,
        *,
        relation: Callable[[str, str], RelationJudgment | None],
        members: Callable[[str, str], bool] = lambda _actor, _project: True,
        priced: bool = True,
    ) -> None:
        self._relation = relation
        self._members = members
        self._priced = priced
        self.reviews: dict[str, ReviewItem] = {}
        self.grants: dict[str, DiagnosticWarrantGrant] = {}

    def enqueue_warrant_review(
        self,
        *,
        review_id: str,
        project_id: str,
        relation_id: str,
        stakes: str,
        reason: str,
        trace_id: str,
        episode_id: str | None,
        created_at: dt.datetime,
        estimated_minutes: int,
    ) -> str:
        for existing in self.reviews.values():
            if (existing.project_id, existing.subject_id) == (project_id, relation_id):
                return existing.review_id
        if not self._priced:
            raise WarrantStoreError(f"project {project_id} has no active review queue policy")
        relation = self._relation(project_id, relation_id)
        if relation is None or relation.relation_type not in (
            RelationType.SUPPORTS,
            RelationType.CONTRADICTS,
        ):
            raise WarrantStoreError(f"{relation_id} is not a SUPPORTS or CONTRADICTS relation")
        self.reviews[review_id] = ReviewItem.model_validate(
            {
                "review_id": review_id,
                "project_id": project_id,
                "subject_type": "DIAGNOSTIC_WARRANT",
                "subject_id": relation_id,
                "stakes": stakes,
                "reason": reason,
                "trace_id": trace_id,
                "episode_id": episode_id,
                "created_at": created_at,
                "estimated_human_minutes": estimated_minutes,
            }
        )
        return review_id

    def resolve(
        self,
        *,
        resolution_id: str,
        grant_id: str,
        review_id: str,
        project_id: str,
        outcome: ReviewOutcome,
        actor_id: str,
        rationale: str,
        considered_rival_ids: Sequence[str],
        resolved_at: dt.datetime,
    ) -> DiagnosticWarrantGrant:
        review = self.reviews.get(review_id)
        if review is None or review.project_id != project_id:
            raise WarrantStoreError(
                f"{review_id} is not a DIAGNOSTIC_WARRANT review of {project_id}"
            )
        if not review.is_outstanding:
            raise WarrantStoreError(f"{review_id} is already {review.status.value}")
        if outcome not in (ReviewOutcome.APPROVED, ReviewOutcome.REJECTED):
            raise WarrantStoreError(f"a warrant is APPROVED or REJECTED, not {outcome.value}")
        if not self._members(actor_id, project_id):
            raise WarrantStoreError(f"{actor_id} is not an active human member of {project_id}")
        if review.expires_at is not None and review.expires_at <= resolved_at:
            raise WarrantStoreError(f"{review_id} expired at {review.expires_at.isoformat()}")
        relation = self._relation(project_id, review.subject_id)
        assert relation is not None
        if relation.actor_id is not None and relation.actor_id == actor_id:
            raise WarrantStoreError(
                f"{actor_id} ran the episode that recorded {relation.relation_id} and cannot also "
                "warrant what it means"
            )
        grant = DiagnosticWarrantGrant(
            grant_id=grant_id,
            project_id=project_id,
            review_id=review_id,
            relation_id=relation.relation_id,
            relation_type=relation.relation_type,
            hypothesis_id=relation.to_entity_id,
            prediction_id=str(relation.attributes.get("prediction_id")),
            verdict=(
                GrantVerdict.WARRANTED
                if outcome is ReviewOutcome.APPROVED
                else GrantVerdict.NOT_WARRANTED
            ),
            granted_by_actor_id=actor_id,
            granted_at=resolved_at,
            rationale=rationale,
            considered_rival_ids=tuple(considered_rival_ids),
        )
        self.grants[grant_id] = grant
        self.reviews[review_id] = review.model_copy(
            update={"status": ReviewStatus(outcome.value), "decision_ref": resolution_id}
        )
        return grant

    def grant(self, project_id: str, grant_id: str) -> DiagnosticWarrantGrant | None:
        found = self.grants.get(grant_id)
        return found if found is not None and found.project_id == project_id else None

    def grants_for_relations(
        self, project_id: str, relation_ids: Sequence[str]
    ) -> tuple[DiagnosticWarrantGrant, ...]:
        wanted = set(relation_ids)
        return tuple(
            sorted(
                (
                    g
                    for g in self.grants.values()
                    if g.project_id == project_id and g.relation_id in wanted
                ),
                key=lambda g: g.relation_id,
            )
        )

    def review_for_relation(self, project_id: str, relation_id: str) -> ReviewItem | None:
        return next(
            (
                r
                for r in self.reviews.values()
                if (r.project_id, r.subject_id) == (project_id, relation_id)
            ),
            None,
        )

    def outstanding_relations(self, project_id: str, relation_ids: Sequence[str]) -> frozenset[str]:
        wanted = set(relation_ids)
        return frozenset(
            r.subject_id
            for r in self.reviews.values()
            if r.project_id == project_id and r.subject_id in wanted and r.is_outstanding
        )

    def outstanding(self, project_id: str) -> tuple[ReviewItem, ...]:
        return tuple(
            sorted(
                (
                    r
                    for r in self.reviews.values()
                    if r.project_id == project_id and r.is_outstanding
                ),
                key=lambda r: (r.created_at, r.review_id),
            )
        )


__all__ = [
    "InMemoryDiagnosticWarrantStore",
    "SqlDiagnosticWarrantStore",
    "WarrantStoreError",
]
