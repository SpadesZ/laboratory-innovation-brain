"""The belief event log (EPI-003, §6.18, §17.13).

APPEND AND READ, AND NOTHING ELSE. There is no ``update``, no ``delete`` and no
``set_current_state``, and their absence is the contract rather than an omission: §6.18 forbids
repairing a belief by editing the current status, so a store that offered the operation would make
the rule advisory. A correction is a new event.

AN EVENT AND ITS TRIGGER REFERENCES ARE ONE FACT. The SQL implementation writes both through
``belief_revision_event_append`` in a single statement. That is the lesson migration 010b cost: a
span's status and its cost refs were written separately and could end up permanently divided. Here
it would be worse, because these tables are append-only in both directions -- a half-written event
could never be completed *or* removed.

BOTH IMPLEMENTATIONS ENFORCE THE SAME CONTRACT: one event per id, references that resolve, and no
mutation. The in-memory one resolves references against the attestation and relation ids it is
given, for the reason stated in ``lab_brain.core.repositories.observability`` -- a fake that accepts
what the database rejects is how a conformance suite passes against the fake and fails in
production.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from lab_brain.core.models.belief_event import BeliefRevisionEvent
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError


class BeliefEventError(RepositoryError):
    """An event could not be appended, or an append would not have been replayable."""


@runtime_checkable
class BeliefEventStore(Protocol):
    """§17.13. Deliberately append-and-read: see the module docstring."""

    def append(self, event: BeliefRevisionEvent) -> BeliefRevisionEvent:
        """Record one event with its trigger references, atomically. Never overwrites."""
        ...

    def get(self, event_id: str) -> BeliefRevisionEvent | None: ...

    def history(self, target_id: str) -> tuple[BeliefRevisionEvent, ...]:
        """Every event for one target, in replay order.

        Ordered by ``occurred_at`` then ``event_id`` so the order is total: two events recorded in
        the same microsecond must still replay identically on every run, or the projection they
        produce is not reproducible evidence.
        """
        ...


class InMemoryBeliefEventStore:
    """The event log in a list, with the same rules the tables enforce.

    ``known_attestation_ids`` / ``known_relation_ids`` are what the references are resolved
    against. Empty means "resolve nothing", so a caller that wants the parity the SQL store gives
    has to say what exists -- which is the honest shape: an in-memory store cannot know otherwise.
    """

    def __init__(
        self,
        known_attestation_ids: Iterable[str] = (),
        known_relation_ids: Iterable[str] = (),
    ) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BeliefRevisionEvent] = {}
        self._attestations = set(known_attestation_ids)
        self._relations = set(known_relation_ids)

    def append(self, event: BeliefRevisionEvent) -> BeliefRevisionEvent:
        unresolved = [
            ref for ref in event.triggering_attestation_ids if ref not in self._attestations
        ] + [ref for ref in event.triggering_relation_ids if ref not in self._relations]
        if unresolved:
            raise BeliefEventError(
                f"event {event.event_id} cites triggers that do not resolve: "
                f"{', '.join(sorted(unresolved))}. A trigger reference that resolves to nothing "
                "makes §6.18's contamination rollback silently incomplete"
            )
        with self._lock:
            if event.event_id in self._by_id:
                raise BeliefEventError(
                    f"event {event.event_id} is already recorded; the log is append-only "
                    "(EPI-003) -- a correction is a new event, never a replacement"
                )
            self._by_id[event.event_id] = event
        return event

    def get(self, event_id: str) -> BeliefRevisionEvent | None:
        return self._by_id.get(event_id)

    def history(self, target_id: str) -> tuple[BeliefRevisionEvent, ...]:
        return tuple(
            sorted(
                (e for e in self._by_id.values() if e.target_id == target_id),
                key=lambda e: (e.occurred_at, e.event_id),
            )
        )

    def project_history(self, project_id: str) -> tuple[BeliefRevisionEvent, ...]:
        """Every event of one project, in replay order. `v3.3-a11` made this expressible."""
        return tuple(
            sorted(
                (e for e in self._by_id.values() if e.project_id == project_id),
                key=lambda e: (e.occurred_at, e.event_id),
            )
        )


_COLUMNS = (
    "event_id, project_id, target_type, target_id, from_state, to_state, "
    "policy_id, policy_version, actor_id, inference_provenance_id, "
    "rationale_artifact_or_record_ref, occurred_at, trace_id"
)


class SqlBeliefEventStore:
    """The same contract against PostgreSQL.

    Requires an autocommit connection for the reason ``require_durable_connection`` states: an
    event written inside a transaction the caller later rolls back is a belief revision that
    happened and left no record, which is the failure EPI-003 exists to remove.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def append(self, event: BeliefRevisionEvent) -> BeliefRevisionEvent:
        require_durable_connection(self._connection)
        # One statement for the event and both reference sets. See the module docstring.
        self._connection.execute(
            "SELECT belief_revision_event_append("
            " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                event.event_id,
                event.project_id,
                event.target_type.value,
                event.target_id,
                None if event.from_state is None else event.from_state.value,
                event.to_state.value,
                list(event.triggering_attestation_ids),
                list(event.triggering_relation_ids),
                event.policy_id,
                event.policy_version,
                event.actor_id,
                event.inference_provenance_id,
                event.rationale_artifact_or_record_ref,
                event.occurred_at,
                event.trace_id,
            ),
        )
        return event

    def get(self, event_id: str) -> BeliefRevisionEvent | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM belief_revision_events WHERE event_id = %s", (event_id,)
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def history(self, target_id: str) -> tuple[BeliefRevisionEvent, ...]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM belief_revision_events WHERE target_id = %s"
            " ORDER BY occurred_at, event_id",
            (target_id,),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def project_history(self, project_id: str) -> tuple[BeliefRevisionEvent, ...]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM belief_revision_events WHERE project_id = %s"
            " ORDER BY occurred_at, event_id",
            (project_id,),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def _hydrate(self, row: Sequence[object]) -> BeliefRevisionEvent:
        event_id = str(row[0])
        attestations = self._connection.execute(
            "SELECT attestation_id FROM belief_revision_event_attestations"
            " WHERE event_id = %s ORDER BY attestation_id",
            (event_id,),
        ).fetchall()
        relations = self._connection.execute(
            "SELECT relation_id FROM belief_revision_event_relations"
            " WHERE event_id = %s ORDER BY relation_id",
            (event_id,),
        ).fetchall()
        return BeliefRevisionEvent.model_validate(
            {
                "event_id": event_id,
                "project_id": row[1],
                "target_type": row[2],
                "target_id": row[3],
                "from_state": row[4],
                "to_state": row[5],
                "triggering_attestation_ids": tuple(str(r[0]) for r in attestations),
                "triggering_relation_ids": tuple(str(r[0]) for r in relations),
                "policy_id": row[6],
                "policy_version": row[7],
                "actor_id": row[8],
                "inference_provenance_id": row[9],
                "rationale_artifact_or_record_ref": row[10],
                "occurred_at": row[11],
                "trace_id": row[12],
            }
        )


class SqlTransitionPolicyStore:
    """Registered policy versions (§8.2.1, migration 005b).

    Register and read only. A policy version is immutable once registered -- the table enforces it
    by trigger -- because re-running version 1.0.0 to re-derive a past decision requires 1.0.0 to
    still be exactly what it was. A changed rule is a new version.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def register(self, policy: TransitionPolicy) -> TransitionPolicy:
        self._connection.execute(
            "INSERT INTO transition_policies ("
            " policy_id, version, domain, from_state, candidate_to_state,"
            " required_relation_types, required_authority_rule, required_condition_match,"
            " min_independent_attestations, independence_basis, blocking_conflict_policy,"
            " human_gate, effective_from, supersedes"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                policy.policy_id,
                policy.version,
                policy.domain,
                policy.from_state.value,
                policy.candidate_to_state.value,
                [member.value for member in policy.required_relation_types],
                policy.required_authority_rule,
                [member.value for member in policy.required_condition_match],
                policy.min_independent_attestations,
                None if policy.independence_basis is None else policy.independence_basis.value,
                list(policy.blocking_conflict_policy),
                policy.human_gate,
                policy.effective_from,
                policy.supersedes,
            ),
        )
        return policy

    def get(self, policy_id: str, version: str) -> TransitionPolicy | None:
        row = self._connection.execute(
            "SELECT policy_id, version, domain, from_state, candidate_to_state,"
            " required_relation_types, required_authority_rule, required_condition_match,"
            " min_independent_attestations, independence_basis, blocking_conflict_policy,"
            " human_gate, effective_from, supersedes"
            " FROM transition_policies WHERE policy_id = %s AND version = %s",
            (policy_id, version),
        ).fetchone()
        if row is None:
            return None

        def array(value: object) -> tuple[object, ...]:
            """A TEXT[] column arrives as a list; an empty one may arrive as NULL."""
            return tuple(value) if isinstance(value, list) else ()

        return TransitionPolicy.model_validate(
            {
                "policy_id": row[0],
                "version": row[1],
                "domain": row[2],
                "from_state": row[3],
                "candidate_to_state": row[4],
                "required_relation_types": array(row[5]),
                "required_authority_rule": row[6],
                "required_condition_match": array(row[7]),
                "min_independent_attestations": row[8],
                "independence_basis": row[9],
                "blocking_conflict_policy": array(row[10]),
                "human_gate": row[11],
                "effective_from": row[12],
                "supersedes": row[13],
            }
        )


__all__ = [
    "BeliefEventError",
    "BeliefEventStore",
    "InMemoryBeliefEventStore",
    "SqlBeliefEventStore",
    "SqlTransitionPolicyStore",
]
