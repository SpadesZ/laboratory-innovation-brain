"""Where a budget approval is actually spent (COST-001, §17.17.1).

§17.17.1 says an approval releases one action ONCE. That word is the whole of this module.

The pure gate cannot deliver it. `evaluate_budget` is told which approvals the caller believes are
already spent, and two dispatches that both believe none are will both be told yes -- each decision
correct on its own inputs, one approval spent twice. Single use is a property of the record, so it
is enforced where the record lives.

BOTH IMPLEMENTATIONS ENFORCE THE SAME CONTRACT. The in-memory one is not a convenience stub: it
takes a lock and performs the same test-and-set, because the conformance suite runs against both and
a fake that is atomic only by accident makes a green suite meaningless. That is the same rule
`lab_brain.core.repositories.memory` states, for the same reason.

WHAT `claim` PROMISES:

    exactly one caller gets True   for any number of concurrent claims of one approval
    False, never an exception      for the ordinary loss -- already consumed, consumed by another
                                   action, or no such approval
    no partial state               consumed_at and consumed_by_action move together or not at all
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Sequence
from typing import Protocol

from lab_brain.core.repositories.protocols import RepositoryError


class NonDurableClaimStoreError(RepositoryError):
    """A claim store was given a connection whose writes a rollback could undo.

    Raised rather than returned as ``False``. A false claim is indistinguishable from ordinary
    contention -- "somebody else got it" -- and would downgrade a misconfiguration into a retry
    loop that silently never succeeds. This is a wiring error and says so.
    """


class SqlCursor(Protocol):
    """The one cursor method this module needs."""

    def fetchone(self) -> tuple[object, ...] | None: ...


class SqlConnection(Protocol):
    """A DBAPI-ish connection, structurally.

    Typed as a Protocol rather than imported from psycopg so `lab_brain.core` keeps no hard
    dependency on a database driver: AGT-007 requires the suite to run with no PostgreSQL at all,
    and an import at module scope would break that for everything that imports this package.

    ``autocommit`` is part of the contract, not an implementation detail of the driver. See
    :class:`SqlBudgetApprovalClaims` -- a claim that is only true until someone rolls back is not
    a claim.
    """

    autocommit: bool

    def execute(self, query: str, params: Sequence[object] = ..., /) -> SqlCursor: ...


class InMemoryBudgetApprovalClaims:
    """Thread-safe single use, for the backend-free profile.

    The lock is not decoration. Without it this class would pass every sequential test and fail the
    only property it exists to provide, and the failure would appear first in production.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: approval_id -> (action_ref it was granted for, when it was consumed or None)
        self._approvals: dict[str, tuple[str, dt.datetime | None]] = {}

    def register(self, approval_id: str, action_ref: str) -> None:
        """Record an unconsumed approval. Mirrors the row `budget_approvals` would hold."""
        with self._lock:
            self._approvals[approval_id] = (action_ref, None)

    def claim(self, approval_id: str, action_ref: str, now: dt.datetime) -> bool:
        with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                return False
            granted_for, consumed_at = record
            # Both conditions are inside the lock, which is what makes this a test-and-set rather
            # than a check followed by a hopeful write.
            if consumed_at is not None or granted_for != action_ref:
                return False
            self._approvals[approval_id] = (granted_for, now)
            return True

    def consumed_at(self, approval_id: str) -> dt.datetime | None:
        with self._lock:
            record = self._approvals.get(approval_id)
            return None if record is None else record[1]


class SqlBudgetApprovalClaims:
    """Single use enforced by the database, in one statement, durably.

    ATOMICITY. The mechanism is the ``WHERE consumed_at IS NULL``:

        UPDATE budget_approvals
           SET consumed_at = %s, consumed_by_action = %s
         WHERE approval_id = %s AND consumed_at IS NULL AND action_ref = %s
        RETURNING approval_id

    PostgreSQL takes a row lock for the duration, so a concurrent identical statement blocks, then
    re-evaluates its ``WHERE`` against the committed row and matches nothing. The loser gets zero
    rows back -- not an error, not a second release.

    A SELECT-then-UPDATE would not do this. Two transactions can both read `consumed_at IS NULL`
    and both proceed, and under READ COMMITTED nothing stops them; the condition has to be part of
    the write. `action_ref` is in the ``WHERE`` as well as in the table's CHECK constraint, so an
    approval cannot be spent on an action it was not granted for even by a caller that reaches past
    this class.

    DURABILITY, WHICH ATOMICITY ALONE DOES NOT GIVE. Atomic is not the same as spent. Handed a
    psycopg connection in its default ``autocommit=False`` mode, the statement above runs inside
    the caller's open transaction, and the sequence is:

        claim() -> True                     the row is updated, in an uncommitted transaction
        caller performs the side effect     the LLM call is made, the money is spent
        the transaction rolls back          for any reason at all, including an unrelated error
        the approval is unconsumed again    and claimable a second time

    The external effect is not transactional and does not roll back with it. So the approval has
    released two actions, which is exactly what §17.17.1's ONCE forbids, and nothing in the atomic
    UPDATE prevents it.

    WHY THIS CLASS DOES NOT SIMPLY COMMIT. It is handed someone else's connection. Calling
    ``commit()`` on it would durably commit whatever else that caller had in flight -- half a unit
    of work they intended to roll back -- and a component that silently commits its owner's
    transaction is a worse bug than the one it fixes. OPS-004 exists because cross-store writes
    need *deliberate* transaction boundaries.

    SO IT REFUSES INSTEAD. The connection must be in autocommit mode, checked when the store is
    built and again on every claim, because ``autocommit`` is settable and a connection that was
    durable at construction may not be at use. Fail-closed: an object that cannot be *proven* to
    have autocommit semantics is rejected rather than assumed, since the failure it would otherwise
    produce is silent, and visible only as an approval that worked twice.
    """

    def __init__(self, connection: SqlConnection) -> None:
        self._require_durable(connection)
        self._connection = connection

    @staticmethod
    def _require_durable(connection: SqlConnection) -> None:
        """Refuse a connection whose writes are not committed by the statement that makes them."""
        autocommit = getattr(connection, "autocommit", None)
        if autocommit is not True:
            raise NonDurableClaimStoreError(
                f"{type(connection).__name__} has autocommit={autocommit!r}; "
                "SqlBudgetApprovalClaims requires autocommit=True. Inside an open transaction a "
                "claim is undone by a rollback while the side effect it authorised is not, so the "
                "same approval releases a second action (§17.17.1 ONCE). This class will not "
                "commit a connection it does not own -- pass a dedicated autocommit connection"
            )

    def claim(self, approval_id: str, action_ref: str, now: dt.datetime) -> bool:
        # Re-checked here, not only at construction: `autocommit` is settable, and the property
        # that matters is the state of the connection at the moment the claim is made.
        self._require_durable(self._connection)
        row = self._connection.execute(
            "UPDATE budget_approvals"
            "   SET consumed_at = %s, consumed_by_action = %s"
            " WHERE approval_id = %s AND consumed_at IS NULL AND action_ref = %s"
            " RETURNING approval_id",
            (now, action_ref, approval_id, action_ref),
        ).fetchone()
        return row is not None


__all__ = [
    "InMemoryBudgetApprovalClaims",
    "NonDurableClaimStoreError",
    "SqlBudgetApprovalClaims",
    "SqlConnection",
    "SqlCursor",
]
