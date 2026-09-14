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


class SqlCursor(Protocol):
    """The one cursor method this module needs."""

    def fetchone(self) -> tuple[object, ...] | None: ...


class SqlConnection(Protocol):
    """A DBAPI-ish connection, structurally.

    Typed as a Protocol rather than imported from psycopg so `lab_brain.core` keeps no hard
    dependency on a database driver: AGT-007 requires the suite to run with no PostgreSQL at all,
    and an import at module scope would break that for everything that imports this package.
    """

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
    """Single use enforced by the database, in one statement.

    The whole mechanism is the ``WHERE consumed_at IS NULL``:

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
    """

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def claim(self, approval_id: str, action_ref: str, now: dt.datetime) -> bool:
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
    "SqlBudgetApprovalClaims",
    "SqlConnection",
    "SqlCursor",
]
