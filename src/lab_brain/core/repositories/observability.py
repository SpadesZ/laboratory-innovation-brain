"""Span persistence and trace reconstruction (OPS-003, §12.5, §17.19.1).

T-OPS-003's pass condition is a *reconstruction*: one episode trace reassembles the chain and the
cost entries that went with it. So the interesting method here is not ``add`` -- it is
:meth:`TraceView.ordered`, because a store that can write spans and not reassemble them satisfies
nothing.

WHY RECONSTRUCTION IS NOT JUST ``SELECT ... WHERE trace_id = ?``. A trace is a tree, and the
question being asked of it is "what happened, in order, and what did each step cost". A flat list
in insertion order answers that only if nothing ever ran concurrently, which is exactly what spans
exist to describe. So the view is built as a tree, ordered by start time among siblings, and
flattened depth-first -- the order a human reads an episode in.

BOTH IMPLEMENTATIONS ENFORCE THE SAME CONTRACT, per the rule stated in
``lab_brain.core.repositories.memory``: opened once, closed once, never reopened, never deleted.
The in-memory one is not a stub, because the conformance tests run against both and a fake that
allows what the database rejects makes a green suite meaningless.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lab_brain.core.models.execution_span import ExecutionSpan, SpanStatus
from lab_brain.core.repositories.budget import SqlConnection, require_durable_connection
from lab_brain.core.repositories.protocols import RepositoryError


class SpanLifecycleError(RepositoryError):
    """A span was opened twice, closed twice, or closed without being open."""


@dataclass(frozen=True)
class TraceView:
    """Every span of one trace, plus the ordering T-OPS-003 asks for."""

    trace_id: str
    spans: tuple[ExecutionSpan, ...]

    def ordered(self) -> tuple[ExecutionSpan, ...]:
        """Depth-first from each root, siblings by start time then span_id.

        Ties broken on ``span_id`` so the order is total: two spans that started in the same
        microsecond must still reconstruct identically on every run, or a recorded trace is not
        reproducible evidence.

        Orphans -- spans whose declared parent is absent from this trace -- are appended rather
        than dropped. Losing a span because its parent is missing would silently shrink the
        evidence, and the parent being absent is itself worth seeing.
        """
        by_parent: dict[str | None, list[ExecutionSpan]] = {}
        known = {span.span_id for span in self.spans}
        for span in self.spans:
            parent = span.parent_span_id if span.parent_span_id in known else None
            by_parent.setdefault(parent, []).append(span)
        for siblings in by_parent.values():
            siblings.sort(key=lambda s: (s.start_time, s.span_id))

        out: list[ExecutionSpan] = []

        def walk(parent: str | None) -> None:
            for span in by_parent.get(parent, ()):
                out.append(span)
                walk(span.span_id)

        walk(None)
        return tuple(out)

    def cost_entry_ids(self) -> tuple[str, ...]:
        """Every ledger entry the trace is accountable for, in reconstruction order."""
        seen: dict[str, None] = {}
        for span in self.ordered():
            for entry_id in span.cost_entry_ids:
                seen.setdefault(entry_id, None)
        return tuple(seen)

    def open_spans(self) -> tuple[ExecutionSpan, ...]:
        """Spans still RUNNING. A trace that never closes is how a stuck episode looks."""
        return tuple(span for span in self.spans if span.is_open)


@runtime_checkable
class SpanRepository(Protocol):
    """§17.19.1 / OPS-003."""

    def open(self, span: ExecutionSpan) -> ExecutionSpan:
        """Record a RUNNING span. Rejects a non-RUNNING span and a duplicate id."""
        ...

    def close(
        self,
        span_id: str,
        status: SpanStatus,
        end_time: dt.datetime,
        cost_entry_ids: Sequence[str] = (),
        metadata: dict[str, object] | None = None,
    ) -> ExecutionSpan:
        """Finish an open span. Rejects closing one that is already closed."""
        ...

    def get(self, span_id: str) -> ExecutionSpan | None: ...

    def trace(self, trace_id: str) -> TraceView:
        """Every span of one trace. The reconstruction T-OPS-003 requires."""
        ...


class InMemorySpanRepository:
    """Spans in a dict, with the same lifecycle rules the table enforces."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, ExecutionSpan] = {}

    def open(self, span: ExecutionSpan) -> ExecutionSpan:
        if span.status is not SpanStatus.RUNNING:
            raise SpanLifecycleError(
                f"span {span.span_id} was opened as {span.status.value}; a span is opened RUNNING "
                "and closed once, so recording it already-finished loses the interval"
            )
        with self._lock:
            if span.span_id in self._by_id:
                raise SpanLifecycleError(f"span {span.span_id} is already recorded")
            self._by_id[span.span_id] = span
        return span

    def close(
        self,
        span_id: str,
        status: SpanStatus,
        end_time: dt.datetime,
        cost_entry_ids: Sequence[str] = (),
        metadata: dict[str, object] | None = None,
    ) -> ExecutionSpan:
        with self._lock:
            existing = self._by_id.get(span_id)
            if existing is None:
                raise SpanLifecycleError(f"no span {span_id} to close")
            if not existing.is_open:
                raise SpanLifecycleError(
                    f"span {span_id} is already {existing.status.value}; a closed span is not "
                    "re-decided"
                )
            closed = existing.closed(
                status=status,
                end_time=end_time,
                cost_entry_ids=tuple(cost_entry_ids),
                metadata=dict(metadata) if metadata is not None else None,
            )
            self._by_id[span_id] = closed
        return closed

    def get(self, span_id: str) -> ExecutionSpan | None:
        return self._by_id.get(span_id)

    def trace(self, trace_id: str) -> TraceView:
        return TraceView(
            trace_id=trace_id,
            spans=tuple(span for span in self._by_id.values() if span.trace_id == trace_id),
        )


_COLUMNS = (
    "span_id, trace_id, parent_span_id, span_type, episode_id, actor_id, "
    "model_call_id, job_id, retrieval_id, start_time, end_time, status, metadata"
)


class SqlSpanRepository:
    """The same contract against PostgreSQL.

    Requires an autocommit connection for the same reason
    :class:`~lab_brain.core.repositories.budget.SqlBudgetApprovalClaims` does: a span written
    inside a transaction the caller later rolls back is an execution that happened and left no
    trace, which is the failure mode observability exists to remove. Reusing that class's check
    rather than restating it, so there is one definition of "durable" in the package.
    """

    def __init__(self, connection: SqlConnection) -> None:
        require_durable_connection(connection)
        self._connection = connection

    def open(self, span: ExecutionSpan) -> ExecutionSpan:
        if span.status is not SpanStatus.RUNNING:
            raise SpanLifecycleError(
                f"span {span.span_id} was opened as {span.status.value}; a span is opened RUNNING "
                "and closed once, so recording it already-finished loses the interval"
            )
        self._connection.execute(
            f"INSERT INTO execution_spans ({_COLUMNS})"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                span.span_id,
                span.trace_id,
                span.parent_span_id,
                span.span_type.value,
                span.episode_id,
                span.actor_id,
                span.model_call_id,
                span.job_id,
                span.retrieval_id,
                span.start_time,
                span.end_time,
                span.status.value,
                json.dumps(span.metadata),
            ),
        )
        return span

    def close(
        self,
        span_id: str,
        status: SpanStatus,
        end_time: dt.datetime,
        cost_entry_ids: Sequence[str] = (),
        metadata: dict[str, object] | None = None,
    ) -> ExecutionSpan:
        existing = self.get(span_id)
        if existing is None:
            raise SpanLifecycleError(f"no span {span_id} to close")
        closed = existing.closed(
            status=status,
            end_time=end_time,
            cost_entry_ids=tuple(cost_entry_ids),
            metadata=dict(metadata) if metadata is not None else None,
        )
        # `AND status = 'RUNNING'` makes the close conditional in the write rather than after a
        # read, the same reason the approval claim puts `consumed_at IS NULL` in its WHERE: two
        # concurrent closes must not both succeed. The table's trigger refuses a re-close as well,
        # so a caller reaching past this class cannot re-decide a finished span either.
        row = self._connection.execute(
            "UPDATE execution_spans"
            "   SET status = %s, end_time = %s, metadata = %s"
            " WHERE span_id = %s AND status = 'RUNNING'"
            " RETURNING span_id",
            (closed.status.value, closed.end_time, json.dumps(closed.metadata), span_id),
        ).fetchone()
        if row is None:
            raise SpanLifecycleError(
                f"span {span_id} was not open; a closed span is not re-decided (OPS-003)"
            )
        for entry_id in closed.cost_entry_ids:
            self._connection.execute(
                "INSERT INTO execution_span_cost_entries (span_id, cost_entry_id)"
                " VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (span_id, entry_id),
            )
        return closed

    def get(self, span_id: str) -> ExecutionSpan | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM execution_spans WHERE span_id = %s", (span_id,)
        ).fetchone()
        return None if row is None else self._hydrate(row)

    def trace(self, trace_id: str) -> TraceView:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM execution_spans WHERE trace_id = %s", (trace_id,)
        ).fetchall()
        return TraceView(trace_id=trace_id, spans=tuple(self._hydrate(row) for row in rows))

    def _hydrate(self, row: Sequence[object]) -> ExecutionSpan:
        span_id = str(row[0])
        entries = self._connection.execute(
            "SELECT cost_entry_id FROM execution_span_cost_entries"
            " WHERE span_id = %s ORDER BY cost_entry_id",
            (span_id,),
        ).fetchall()
        metadata = row[12]
        return ExecutionSpan.model_validate(
            {
                "span_id": span_id,
                "trace_id": row[1],
                "parent_span_id": row[2],
                "span_type": row[3],
                "episode_id": row[4],
                "actor_id": row[5],
                "model_call_id": row[6],
                "job_id": row[7],
                "retrieval_id": row[8],
                "start_time": row[9],
                "end_time": row[10],
                "status": row[11],
                "cost_entry_ids": tuple(str(entry[0]) for entry in entries),
                "metadata": metadata if isinstance(metadata, dict) else json.loads(str(metadata)),
            }
        )


__all__ = [
    "InMemorySpanRepository",
    "SpanLifecycleError",
    "SpanRepository",
    "SqlSpanRepository",
    "TraceView",
]
