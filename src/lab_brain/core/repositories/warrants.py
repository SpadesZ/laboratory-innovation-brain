"""DIAGNOSTIC_WARRANT reviews and their grants (Causal Warrant Gate, `012o`).

THIN, BECAUSE THE INVARIANTS ARE THE DATABASE'S. `diagnostic_warrant_review_enqueue` prices a
review from the project's active queue policy and returns the existing review for a relation that
was already asked about, whatever its status; `diagnostic_warrant_resolve` writes the grant, the
WARRANT_GRANT resolution and the terminal review in one statement, for an active human member of
the project, exactly once. This class passes arguments and reads rows back.

AN ANSWER IS SIGNED HERE, NOT ASSERTED (V1.1, `012p`). `resolve` takes a `GrantSigner` -- the
reviewer's enrolment and private key -- instead of an actor id: it builds the answer from the
review and the relation as stored, signs exactly those bytes, and writes the signature with it.
The database checks the frame (an unrevoked enrolment of that person, made before the answer);
the signature is verified whenever the answer is counted. Enrolments and revocations are an
authority's signed statements, stored here and verified against keys pinned outside the database.

The in-memory twin enforces the same rules for the core suite (AGT-007), so a test that passes
against it is not passing against something more permissive than PostgreSQL.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Sequence
from typing import Protocol

from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.review import OUTSTANDING_REVIEW_STATUSES, ReviewItem, ReviewStatus
from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.models.reviewer import ReviewerEnrolment, ReviewerKeyRevocation
from lab_brain.core.models.warrant import (
    DiagnosticDeclarationSet,
    DiagnosticWarrantGrant,
    GrantVerdict,
)
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.evidence import SqlRelationStore
from lab_brain.core.repositories.protocols import RepositoryError
from lab_brain.core.repositories.reviews import SqlReviewItemStore


class WarrantStoreError(RepositoryError):
    """A warrant review could not be queued or answered."""


class GrantSigner(Protocol):
    """A reviewer's enrolled key, as `resolve` uses it: whose, under which enrolment, and sign."""

    @property
    def actor_id(self) -> str: ...

    @property
    def enrolment_id(self) -> str: ...

    def sign(self, message: bytes) -> str: ...


def _signed(
    signer: GrantSigner,
    *,
    grant_id: str,
    project_id: str,
    review: ReviewItem,
    relation: RelationJudgment,
    outcome: ReviewOutcome,
    rationale: str,
    considered_rival_ids: Sequence[str],
    resolved_at: dt.datetime,
    identifies_class_ref: str | None,
) -> DiagnosticWarrantGrant:
    """The answer as it will be stored, signed over exactly those fields."""
    if outcome not in (ReviewOutcome.APPROVED, ReviewOutcome.REJECTED):
        raise WarrantStoreError(f"a warrant is APPROVED or REJECTED, not {outcome.value}")
    unsigned = DiagnosticWarrantGrant(
        grant_id=grant_id,
        project_id=project_id,
        review_id=review.review_id,
        relation_id=relation.relation_id,
        relation_type=relation.relation_type,
        hypothesis_id=relation.to_entity_id,
        prediction_id=str(relation.attributes.get("prediction_id")),
        verdict=(
            GrantVerdict.WARRANTED
            if outcome is ReviewOutcome.APPROVED
            else GrantVerdict.NOT_WARRANTED
        ),
        granted_by_actor_id=signer.actor_id,
        granted_at=resolved_at,
        rationale=rationale,
        considered_rival_ids=tuple(considered_rival_ids),
        identifies_class_ref=identifies_class_ref,
        enrolment_id=signer.enrolment_id,
    )
    return unsigned.model_copy(update={"signature": signer.sign(unsigned.statement())})


_GRANT_COLUMNS = (
    "grant_id, project_id, review_id, relation_id, relation_type, hypothesis_id, prediction_id, "
    "verdict, granted_by_actor_id, granted_at, rationale, considered_rival_ids, "
    "identifies_class_ref, enrolment_id, signature"
)

_ENROLMENT_COLUMNS = (
    "enrolment_id, project_id, actor_id, public_key, scope, enrolled_at, authority_actor_id, "
    "authority_key_id, authority_signature"
)

_REVOCATION_COLUMNS = (
    "revocation_id, enrolment_id, project_id, effective_at, reason, authority_actor_id, "
    "authority_key_id, authority_signature"
)


def _enrolment(row: Sequence[object]) -> ReviewerEnrolment:
    names = [n.strip() for n in _ENROLMENT_COLUMNS.split(",")]
    return ReviewerEnrolment.model_validate(dict(zip(names, row, strict=True)))


def _revocation(row: Sequence[object]) -> ReviewerKeyRevocation:
    names = [n.strip() for n in _REVOCATION_COLUMNS.split(",")]
    return ReviewerKeyRevocation.model_validate(dict(zip(names, row, strict=True)))


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
        self._relations = SqlRelationStore(connection)

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
        signer: GrantSigner,
        rationale: str,
        considered_rival_ids: Sequence[str],
        resolved_at: dt.datetime,
        identifies_class_ref: str | None = None,
    ) -> DiagnosticWarrantGrant:
        review = self._reviews.get(project_id, review_id)
        relation = None if review is None else self._relations.get(project_id, review.subject_id)
        if review is None or relation is None or review.subject_type.value != "DIAGNOSTIC_WARRANT":
            raise WarrantStoreError(
                f"review {review_id} is not a DIAGNOSTIC_WARRANT review of {project_id}"
            )
        try:
            answer = _signed(
                signer,
                grant_id=grant_id,
                project_id=project_id,
                review=review,
                relation=relation,
                outcome=outcome,
                rationale=rationale,
                considered_rival_ids=considered_rival_ids,
                resolved_at=resolved_at,
                identifies_class_ref=identifies_class_ref,
            )
        except ValueError as exc:
            raise WarrantStoreError(f"review {review_id} could not be answered: {exc}") from exc
        try:
            self._connection.execute(
                "SELECT diagnostic_warrant_resolve(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    resolution_id,
                    grant_id,
                    review_id,
                    project_id,
                    outcome.value,
                    answer.granted_by_actor_id,
                    answer.rationale,
                    list(answer.considered_rival_ids),
                    resolved_at,
                    answer.enrolment_id,
                    answer.signature,
                    identifies_class_ref,
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

    # -- reviewer keys -------------------------------------------------------------------------

    def enrol(self, enrolment: ReviewerEnrolment) -> ReviewerEnrolment:
        try:
            self._connection.execute(
                f"INSERT INTO warrant_reviewer_enrolments ({_ENROLMENT_COLUMNS}, key_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    enrolment.enrolment_id,
                    enrolment.project_id,
                    enrolment.actor_id,
                    enrolment.public_key,
                    enrolment.scope,
                    enrolment.enrolled_at,
                    enrolment.authority_actor_id,
                    enrolment.authority_key_id,
                    enrolment.authority_signature,
                    enrolment.key_id,
                ),
            )
        except Exception as exc:
            raise WarrantStoreError(
                f"enrolment {enrolment.enrolment_id} was refused: {exc}"
            ) from exc
        return enrolment

    def revoke(self, revocation: ReviewerKeyRevocation) -> ReviewerKeyRevocation:
        try:
            self._connection.execute(
                f"INSERT INTO warrant_reviewer_revocations ({_REVOCATION_COLUMNS})"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    revocation.revocation_id,
                    revocation.enrolment_id,
                    revocation.project_id,
                    revocation.effective_at,
                    revocation.reason,
                    revocation.authority_actor_id,
                    revocation.authority_key_id,
                    revocation.authority_signature,
                ),
            )
        except Exception as exc:
            raise WarrantStoreError(
                f"revocation {revocation.revocation_id} was refused: {exc}"
            ) from exc
        return revocation

    def enrolment(self, project_id: str, enrolment_id: str) -> ReviewerEnrolment | None:
        row = self._connection.execute(
            f"SELECT {_ENROLMENT_COLUMNS} FROM warrant_reviewer_enrolments"
            " WHERE project_id = %s AND enrolment_id = %s",
            (project_id, enrolment_id),
        ).fetchone()
        return None if row is None else _enrolment(row)

    def enrolments(
        self, project_id: str, actor_id: str | None = None
    ) -> tuple[ReviewerEnrolment, ...]:
        rows = self._connection.execute(
            f"SELECT {_ENROLMENT_COLUMNS} FROM warrant_reviewer_enrolments"
            " WHERE project_id = %s AND (%s::text IS NULL OR actor_id = %s)"
            " ORDER BY enrolled_at, enrolment_id",
            (project_id, actor_id, actor_id),
        ).fetchall()
        return tuple(_enrolment(row) for row in rows)

    def revocations(self, project_id: str, enrolment_id: str) -> tuple[ReviewerKeyRevocation, ...]:
        rows = self._connection.execute(
            f"SELECT {_REVOCATION_COLUMNS} FROM warrant_reviewer_revocations"
            " WHERE project_id = %s AND enrolment_id = %s ORDER BY revocation_id",
            (project_id, enrolment_id),
        ).fetchall()
        return tuple(_revocation(row) for row in rows)

    # -- answers -------------------------------------------------------------------------------

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
        self.enrolled: dict[str, ReviewerEnrolment] = {}
        self.revoked: dict[str, ReviewerKeyRevocation] = {}

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
            if (
                existing.project_id,
                existing.subject_id,
            ) == (project_id, relation_id) and existing.status is not ReviewStatus.EXPIRED:
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
        signer: GrantSigner,
        rationale: str,
        considered_rival_ids: Sequence[str],
        resolved_at: dt.datetime,
        identifies_class_ref: str | None = None,
    ) -> DiagnosticWarrantGrant:
        actor_id = signer.actor_id
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
        enrolment = self.enrolled.get(signer.enrolment_id)
        if enrolment is None or (enrolment.project_id, enrolment.actor_id) != (
            project_id,
            actor_id,
        ):
            raise WarrantStoreError(
                f"{signer.enrolment_id} is not {actor_id}'s reviewer key in {project_id}"
            )
        if signer.enrolment_id in self.revoked:
            raise WarrantStoreError(f"enrolment {signer.enrolment_id} is revoked")
        if resolved_at < enrolment.enrolled_at or resolved_at < review.created_at:
            raise WarrantStoreError(f"an answer to {review_id} cannot predate its key or question")
        try:
            grant = _signed(
                signer,
                grant_id=grant_id,
                project_id=project_id,
                review=review,
                relation=relation,
                outcome=outcome,
                rationale=rationale,
                considered_rival_ids=considered_rival_ids,
                resolved_at=resolved_at,
                identifies_class_ref=identifies_class_ref,
            )
        except ValueError as exc:
            raise WarrantStoreError(f"{review_id} could not be answered: {exc}") from exc
        self.grants[grant_id] = grant
        self.reviews[review_id] = review.model_copy(
            update={"status": ReviewStatus(outcome.value), "decision_ref": resolution_id}
        )
        return grant

    def enrol(self, enrolment: ReviewerEnrolment) -> ReviewerEnrolment:
        if not self._members(enrolment.actor_id, enrolment.project_id):
            raise WarrantStoreError(
                f"{enrolment.actor_id} is not an active human member of {enrolment.project_id}"
            )
        if any(
            e.key_id == enrolment.key_id and e.actor_id != enrolment.actor_id
            for e in self.enrolled.values()
        ):
            raise WarrantStoreError(
                f"key {enrolment.key_id} is already enrolled for another person"
            )
        if enrolment.enrolment_id in self.enrolled:
            raise WarrantStoreError(f"enrolment {enrolment.enrolment_id} exists")
        self.enrolled[enrolment.enrolment_id] = enrolment
        return enrolment

    def revoke(self, revocation: ReviewerKeyRevocation) -> ReviewerKeyRevocation:
        if revocation.enrolment_id not in self.enrolled or revocation.enrolment_id in self.revoked:
            raise WarrantStoreError(f"{revocation.enrolment_id} cannot be revoked")
        self.revoked[revocation.enrolment_id] = revocation
        return revocation

    def enrolment(self, project_id: str, enrolment_id: str) -> ReviewerEnrolment | None:
        found = self.enrolled.get(enrolment_id)
        return found if found is not None and found.project_id == project_id else None

    def enrolments(
        self, project_id: str, actor_id: str | None = None
    ) -> tuple[ReviewerEnrolment, ...]:
        return tuple(
            sorted(
                (
                    e
                    for e in self.enrolled.values()
                    if e.project_id == project_id and actor_id in (None, e.actor_id)
                ),
                key=lambda e: (e.enrolled_at, e.enrolment_id),
            )
        )

    def revocations(self, project_id: str, enrolment_id: str) -> tuple[ReviewerKeyRevocation, ...]:
        found = self.revoked.get(enrolment_id)
        return () if found is None or found.project_id != project_id else (found,)

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


class SqlDeclarationSetStore:
    """The declaration set versions a composition root may cite, registered for SQL (`012p`).

    The confirmation rule is evaluated in the database for every writer, and it needs the
    domain's declarations; the DomainPack's code is their source of truth. So registration is
    exact: an existing row for a version must have the code's digest, and a version of one of
    these sets that the code does not declare is refused -- a declaration nobody reviewed as code
    must not decide what the database accepts as a confirmation. Either refusal stops the caller
    before anything is concluded.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def ensure(
        self, declaration_sets: Sequence[DiagnosticDeclarationSet], active: str | None
    ) -> None:
        """Register every version, in order, the active one last and superseding the one before.

        Each later version of a set supersedes the version listed before it, so only `active`
        is read by new conclusions; earlier versions stay registered so what they decided still
        re-checks.
        """
        known = {s.ref: s for s in declaration_sets}
        ordered = sorted(declaration_sets, key=lambda s: s.ref == active)
        previous: dict[str, str] = {}
        for declarations in ordered:
            row = self._connection.execute(
                "SELECT digest FROM diagnostic_declaration_sets WHERE set_id = %s AND version = %s",
                (declarations.set_id, declarations.version),
            ).fetchone()
            if row is not None and row[0] != declarations.digest:
                raise WarrantStoreError(
                    f"the database registers declaration set {declarations.ref} with digest "
                    f"{row[0]}; this code declares {declarations.digest}. A declaration changed "
                    "in place is not the one conclusions were reasoned under"
                )
            if row is None:
                self._connection.execute(
                    "INSERT INTO diagnostic_declaration_sets"
                    " (set_id, version, domain, digest, declarations, supersedes)"
                    " VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                    (
                        declarations.set_id,
                        declarations.version,
                        declarations.domain,
                        declarations.digest,
                        json.dumps(
                            declarations.model_dump(mode="json")["declarations"], sort_keys=True
                        ),
                        previous.get(declarations.set_id),
                    ),
                )
            previous[declarations.set_id] = declarations.ref
        set_ids = sorted({s.set_id for s in declaration_sets})
        if not set_ids:
            return
        stranger = self._connection.execute(
            "SELECT set_id || '@' || version FROM diagnostic_declaration_sets"
            " WHERE set_id = ANY (%s) ORDER BY 1",
            (set_ids,),
        ).fetchall()
        unknown = sorted(str(r[0]) for r in stranger if str(r[0]) not in known)
        if unknown:
            raise WarrantStoreError(
                f"the database registers declaration set version(s) {', '.join(unknown)}, which "
                "this code does not declare; the confirmation rule would read declarations "
                "nobody reviewed as code"
            )


__all__ = [
    "GrantSigner",
    "InMemoryDiagnosticWarrantStore",
    "SqlDeclarationSetStore",
    "SqlDiagnosticWarrantStore",
    "WarrantStoreError",
]
