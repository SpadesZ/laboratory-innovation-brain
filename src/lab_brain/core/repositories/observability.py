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
``lab_brain.core.repositories.memory``: opened once, closed once, never reopened, never deleted,
and **a parent span is in the same trace as its child**. The in-memory one is not a stub, because
the conformance tests run against both and a fake that allows what the database rejects makes a
green suite meaningless.

That last sentence was false when this module was first written, and the audit of P6 caught it: the
SQL store's foreign key rejected a dangling parent while ``InMemorySpanRepository.open`` did not
check parents at all, and *neither* required the parent to be in the same trace. Both now do.
Cost-ref integrity is the one asymmetry that remains and it is a deliberate parameter rather than a
silence -- the in-memory store can only resolve refs if it is given the ledger to resolve them
against, so it takes one.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lab_brain.core.models.execution_span import ExecutionSpan, SpanStatus
from lab_brain.core.repositories.budget import (
    CostLedger,
    SqlConnection,
    require_durable_connection,
)
from lab_brain.core.repositories.protocols import RepositoryError


class SpanLifecycleError(RepositoryError):
    """A span was opened twice, closed twice, closed without being open, or badly parented."""


class TraceCorruptionError(RepositoryError):
    """A trace cannot be reassembled into a tree, so no ordering of it would be honest.

    Raised rather than worked around. The first version of :meth:`TraceView.ordered` treated a span
    whose parent was absent as a root, on the reasoning that dropping it would shrink the evidence.
    That was the wrong repair: it turned a corrupt cross-trace edge into a plausible-looking tree,
    and a reconstruction that silently fixes its own input produces output that reads as evidence
    and is not. Both stores now make the corruption unrepresentable; if one is seen anyway, the
    honest answer is to say so.
    """


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

        Raises :class:`TraceCorruptionError` rather than repairing anything -- a span whose parent
        is not in this trace, a span in the wrong trace, or a parent cycle. See that class for why
        the earlier "treat it as a root" behaviour was the wrong answer.
        """
        known = {span.span_id for span in self.spans}
        wrong_trace = sorted(s.span_id for s in self.spans if s.trace_id != self.trace_id)
        if wrong_trace:
            raise TraceCorruptionError(
                f"trace {self.trace_id} was handed spans belonging to another trace: "
                f"{', '.join(wrong_trace)}"
            )
        orphans = sorted(
            f"{s.span_id}->{s.parent_span_id}"
            for s in self.spans
            if s.parent_span_id is not None and s.parent_span_id not in known
        )
        if orphans:
            raise TraceCorruptionError(
                f"trace {self.trace_id} contains spans whose parent is not in it: "
                f"{', '.join(orphans)}. Both stores forbid this, so seeing it means the trace was "
                "assembled from a partial or cross-trace read -- which cannot be ordered honestly"
            )

        by_parent: dict[str | None, list[ExecutionSpan]] = {}
        for span in self.spans:
            by_parent.setdefault(span.parent_span_id, []).append(span)
        for siblings in by_parent.values():
            siblings.sort(key=lambda s: (s.start_time, s.span_id))

        out: list[ExecutionSpan] = []

        def walk(parent: str | None) -> None:
            for span in by_parent.get(parent, ()):
                out.append(span)
                walk(span.span_id)

        walk(None)
        if len(out) != len(self.spans):
            # Unreachable through either store -- a parent must exist when its child is inserted,
            # and the close trigger forbids repointing one -- but a cycle would otherwise make this
            # function silently return a subset, which is the failure mode of a "can't happen".
            unreached = sorted({s.span_id for s in self.spans} - {s.span_id for s in out})
            raise TraceCorruptionError(
                f"trace {self.trace_id} is not a tree; unreachable from any root: "
                f"{', '.join(unreached)}"
            )
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
    """Spans in a dict, with the same rules the table enforces.

    ``ledger`` is optional and its absence is the one place this store is weaker than the SQL one:
    a cost ref can only be verified against something that can resolve it. Pass the ledger the
    dispatch seam is already using and refs are checked here too; leave it out and they are not.
    Made a parameter rather than a silence because the P6 audit found the previous docstring
    claiming parity it did not have.
    """

    def __init__(self, ledger: CostLedger | None = None) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, ExecutionSpan] = {}
        self._ledger = ledger

    def open(self, span: ExecutionSpan) -> ExecutionSpan:
        if span.status is not SpanStatus.RUNNING:
            raise SpanLifecycleError(
                f"span {span.span_id} was opened as {span.status.value}; a span is opened RUNNING "
                "and closed once, so recording it already-finished loses the interval"
            )
        with self._lock:
            if span.span_id in self._by_id:
                raise SpanLifecycleError(f"span {span.span_id} is already recorded")
            # Parent existence AND same trace, matching the composite foreign key migration 010b
            # puts on the table. Checking neither -- which this store did until the P6 audit --
            # let a fake accept the cross-trace edge the database rejects, which is precisely how
            # a conformance suite passes against a fake and fails in production.
            if span.parent_span_id is not None:
                parent = self._by_id.get(span.parent_span_id)
                if parent is None:
                    raise SpanLifecycleError(
                        f"span {span.span_id} names parent {span.parent_span_id}, which is not "
                        "recorded; a dangling parent makes the trace unreassemblable"
                    )
                if parent.trace_id != span.trace_id:
                    raise SpanLifecycleError(
                        f"span {span.span_id} is in trace {span.trace_id} but its parent "
                        f"{span.parent_span_id} is in {parent.trace_id}; a parent is in the same "
                        "trace as its child, or the edge crosses two episodes and belongs to "
                        "neither"
                    )
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
        """Close atomically with respect to its cost refs: all of them, or the span stays open."""
        refs = tuple(cost_entry_ids)
        if self._ledger is not None:
            # Before the mutation, so the failure leaves nothing half-done -- the same ordering
            # `execution_span_close` uses, for the same reason.
            missing = [ref for ref in refs if self._ledger.entry(ref) is None]
            if missing:
                raise SpanLifecycleError(
                    f"cost entries {', '.join(sorted(missing))} do not exist, so span {span_id} "
                    "stays RUNNING with no links. A span whose status is recorded and whose cost "
                    "refs are not is the one failure OPS-003 must not have"
                )
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
                cost_entry_ids=refs,
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
        # ONE STATEMENT, and that is the whole point. This used to be an UPDATE followed by one
        # INSERT per cost ref; under the autocommit connection these stores require, each of those
        # committed separately, so an invalid ref left the span permanently terminal with partial
        # links and the close-once trigger refused every retry. The two facts OPS-003 exists to
        # make reliable were exactly the pair that could diverge.
        #
        # `execution_span_close` (migration 010b) does the close and every link together, so the
        # statement's own atomicity is the guarantee: any invalid ref aborts it and the span stays
        # RUNNING. Wrapping this in a Python transaction was not an option -- these stores refuse a
        # connection they do not own precisely so they never commit somebody else's work.
        #
        # It also keeps the concurrency property: the conditional UPDATE inside the function takes
        # the row lock, so of two concurrent closes exactly one gets TRUE and the loser gets FALSE.
        row = self._connection.execute(
            "SELECT execution_span_close(%s, %s, %s, %s, %s)",
            (
                span_id,
                closed.status.value,
                closed.end_time,
                json.dumps(closed.metadata),
                list(closed.cost_entry_ids),
            ),
        ).fetchone()
        if row is None or row[0] is not True:
            raise SpanLifecycleError(
                f"span {span_id} was not open; a closed span is not re-decided (OPS-003)"
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
    "TraceCorruptionError",
    "TraceView",
]
