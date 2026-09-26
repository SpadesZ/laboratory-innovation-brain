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

BOTH IMPLEMENTATIONS ENFORCE THE SAME CONTRACT: one event per id, references that resolve, a
target that is an admitted hypothesis of the event's project (M3 / R-12, `011j`), and no
mutation. The in-memory one resolves references against the attestation and relation ids it is
given, for the reason stated in ``lab_brain.core.repositories.observability`` -- a fake that accepts
what the database rejects is how a conformance suite passes against the fake and fails in
production.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, runtime_checkable

from lab_brain.core.belief import AuthorizedRevision
from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.models.belief_event import BeliefRevisionEvent
from lab_brain.core.models.decision import BeliefTransitionDecision
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError


class BeliefEventError(RepositoryError):
    """An event could not be appended, or an append would not have been replayable."""


@runtime_checkable
class BeliefEventStore(Protocol):
    """§17.13. Deliberately append-and-read: see the module docstring."""

    def append(self, authorized: AuthorizedRevision) -> BeliefRevisionEvent:
        """Record one authorised event with its trigger references, atomically.

        Takes an :class:`AuthorizedRevision`, never a bare event. A hand-constructed
        `BeliefRevisionEvent` is indistinguishable from the output of `record_transition`, so a
        store that accepted one could not tell an authorised revision from an unevaluated one --
        the P7 audit's first finding. The capability is in-process only; the durable half is
        SPEC-ISSUE-011 and risk R-13.
        """
        ...

    def get(self, event_id: str) -> BeliefRevisionEvent | None: ...

    def history(self, project_id: str, target_id: str) -> tuple[BeliefRevisionEvent, ...]:
        """Every event for one target **in one project**, in replay order.

        Scoped on the pair, not on the target alone: two projects may legitimately use the same
        hypothesis id, and a history keyed only on `target_id` would fold both together. That is
        what `v3.3-a11`'s `project_id` is for.

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

    ``known_hypotheses`` is the same for the target (M3 / R-12): the ``(project_id, hypothesis_id)``
    pairs admitted through §8's gate, or a callable answering for them -- the admission service's
    store, when certificates are admitted as the log grows. Empty resolves nothing, exactly as
    `011j`'s foreign key does for a database that has admitted nothing.
    """

    def __init__(
        self,
        known_attestation_ids: Iterable[str] = (),
        known_relation_ids: Iterable[str] = (),
        known_hypotheses: Iterable[tuple[str, str]] | Callable[[str, str], bool] = (),
    ) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BeliefRevisionEvent] = {}
        self._attestations = set(known_attestation_ids)
        self._relations = set(known_relation_ids)
        if callable(known_hypotheses):
            self._hypothesis_exists = known_hypotheses
        else:
            admitted = frozenset(known_hypotheses)
            self._hypothesis_exists = lambda project_id, hypothesis_id: (
                (project_id, hypothesis_id) in admitted
            )

    def append(self, authorized: AuthorizedRevision) -> BeliefRevisionEvent:
        event = authorized.event
        if not self._hypothesis_exists(event.project_id, event.target_id):
            raise BeliefEventError(
                f"event {event.event_id} targets hypothesis {event.target_id} in "
                f"{event.project_id}, which was never admitted there. R-12 / EPI-001: a belief "
                "event names a hypothesis admitted through §8's gate, in its own project"
            )
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

    def history(self, project_id: str, target_id: str) -> tuple[BeliefRevisionEvent, ...]:
        return tuple(
            sorted(
                (
                    e
                    for e in self._by_id.values()
                    if e.project_id == project_id and e.target_id == target_id
                ),
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
    "rationale_artifact_or_record_ref, occurred_at, trace_id, "
    "authorization_decision_id"
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

    def append(self, authorized: AuthorizedRevision) -> BeliefRevisionEvent:
        require_durable_connection(self._connection)
        event = authorized.event
        # One statement for the event and both reference sets. See the module docstring.
        self._connection.execute(
            "SELECT belief_revision_event_append("
            " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                event.authorization_decision_id,
            ),
        )
        return event

    def get(self, event_id: str) -> BeliefRevisionEvent | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM belief_revision_events WHERE event_id = %s", (event_id,)
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def history(self, project_id: str, target_id: str) -> tuple[BeliefRevisionEvent, ...]:
        # Both columns in the WHERE, not one plus a Python filter: the index is on
        # (target_id, occurred_at, event_id) and the scope is the pair, so a query that fetched
        # every project's history and narrowed it afterwards would read rows the caller has no
        # business seeing (SEC-002) on the way to the right answer.
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM belief_revision_events"
            " WHERE project_id = %s AND target_id = %s ORDER BY occurred_at, event_id",
            (project_id, target_id),
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
                "authorization_decision_id": row[13],
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
            " human_gate, is_admission, effective_from, supersedes"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                policy.is_admission,
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
            " human_gate, is_admission, effective_from, supersedes"
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
                "is_admission": row[12],
                "effective_from": row[13],
                "supersedes": row[14],
            }
        )


__all__ = [
    "BeliefEventError",
    "BeliefEventStore",
    "InMemoryBeliefEventStore",
    "SqlBeliefEventStore",
    "SqlTransitionPolicyStore",
]


class InMemoryBeliefTransitionDecisionStore:
    """§17.14.1 authorizations, held in process. Append-only, like the table.

    Records the ``decision_id`` collision as a refusal rather than an overwrite. A second
    authorization under an id that already exists is either a bug or an attempt to replace the
    reason a belief changed, and neither should silently win.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BeliefTransitionDecision] = {}

    def record(self, decision: BeliefTransitionDecision) -> BeliefTransitionDecision:
        with self._lock:
            existing = self._by_id.get(decision.decision_id)
            if existing is not None:
                raise BeliefEventError(
                    f"authorization {decision.decision_id} already exists; "
                    "belief_transition_decisions is append-only, so an authorization is never "
                    "replaced -- a re-evaluation is a new Decision with a new id"
                )
            self._by_id[decision.decision_id] = decision
        return decision

    def get(self, decision_id: str) -> BeliefTransitionDecision | None:
        return self._by_id.get(decision_id)


_DECISION_COLUMNS = (
    "decision_id, project_id, subject_id, decision_type, result, policy_id, policy_version, "
    "from_state, to_state, authority_policy_id, authority_policy_version, "
    "decision_input_snapshot, input_hash, evaluated_decision, episode_id, actor_id, created_at"
)


class SqlBeliefTransitionDecisionStore:
    """The same contract against PostgreSQL (`v3.3-a12`).

    ``decision_input_snapshot`` and ``evaluated_decision`` are stored as the canonical JSON *text*
    the model produced, not as jsonb. That is deliberate and the migration says why: ``input_hash``
    is verified by the database against these exact bytes, and jsonb would normalise them, leaving
    the check with nothing to do but trust the writer.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def record(self, decision: BeliefTransitionDecision) -> BeliefTransitionDecision:
        require_durable_connection(self._connection)
        snapshot = decision.decision_input_snapshot
        self._connection.execute(
            f"INSERT INTO belief_transition_decisions ({_DECISION_COLUMNS})"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                decision.decision_id,
                decision.project_id,
                decision.subject_id,
                decision.decision_type.value,
                decision.result.value,
                decision.policy_id,
                decision.policy_version,
                decision.from_state.value,
                decision.to_state.value,
                snapshot.authority_policy_id,
                snapshot.authority_policy_version,
                snapshot.canonical_bytes_text(),
                decision.input_hash,
                canonicalize(decision.evaluated.model_dump(mode="json")),
                decision.episode_id,
                decision.actor_id,
                decision.created_at,
            ),
        )
        return decision

    def get(self, decision_id: str) -> BeliefTransitionDecision | None:
        row = self._connection.execute(
            f"SELECT {_DECISION_COLUMNS} FROM belief_transition_decisions WHERE decision_id = %s",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        return BeliefTransitionDecision.model_validate(
            {
                "decision_id": row[0],
                "project_id": row[1],
                "subject_id": row[2],
                "decision_type": row[3],
                "result": row[4],
                "policy_id": row[5],
                "policy_version": row[6],
                "from_state": row[7],
                "to_state": row[8],
                # The snapshot round-trips through its own model, so a stored snapshot that no
                # longer satisfies the model's invariants fails here rather than being handed to
                # a caller as if it were valid.
                "decision_input_snapshot": json.loads(str(row[11])),
                "input_hash": row[12],
                "evaluated": json.loads(str(row[13])),
                "episode_id": row[14],
                "actor_id": row[15],
                "created_at": row[16],
            }
        )
