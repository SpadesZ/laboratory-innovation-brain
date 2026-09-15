"""Execution observability — the trace/span contract (OPS-003, §12.5, §17.19.1).

WHAT THIS IS FOR.

§12.5: ``trace_id`` 貫穿 episode → retrieval → LLM call → job → run → artifact.
OPS-003: execution observability MUST persist a trace/span contract linking those, **with status
and cost refs**.

The last four words are the load-bearing ones and the reason this lives next to the cost ledger
rather than in a logging module. A span is not a log line. A log line says something happened; a
span says *this* interval of execution, under *this* trace, cost *these* ledger entries and ended
in *this* status. That is what makes "why did this episode spend six hours and forty dollars"
answerable, and an episode whose spans cannot be reassembled is an episode nobody can review.

WHERE THE VOCABULARIES COME FROM. §17.19.1 declares ``span_type`` and ``status`` without
enumerating either, so both enums below are derived from what the specification names elsewhere
rather than invented:

    SpanType    §12.5's chain -- episode, retrieval, LLM call, job, run -- plus TOOL_CALL, because
                §17.17's gate fires before each "LLM/tool call" and a tool dispatch that cannot be
                typed cannot be observed.
    SpanStatus  SUCCEEDED / FAILED from §17.16's Job and §17.22's StageResult; BLOCKED separately,
                because UX-002 states that budget exhaustion classifies as POLICY_BLOCK and **not**
                FAILED. Collapsing the two would make "we refused to spend this" look like "this
                broke", which sends the wrong person to investigate. (UX-002 itself is M1; this is
                consistency with it, not a claim to discharge it.)

AT MOST ONE SUBJECT. §17.19.1 writes the subject reference as
``model_call_id?/job_id?/retrieval_id?`` -- one slash-separated alternation, not three independent
fields. Read literally that is "at most one of these", and it is enforced below: a span describes
one thing. A span carrying both a ``job_id`` and a ``retrieval_id`` is two spans that were never
separated, and every cost attributed to it is attributed to both.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel


class SpanType(StrEnum):
    """What kind of execution this interval covers. See the module docstring for the derivation."""

    EPISODE = "EPISODE"
    RETRIEVAL = "RETRIEVAL"
    LLM_CALL = "LLM_CALL"
    TOOL_CALL = "TOOL_CALL"
    JOB = "JOB"
    RUN = "RUN"


class SpanStatus(StrEnum):
    """How the interval ended, or that it has not.

    ``BLOCKED`` is deliberately not ``FAILED``: a governance refusal and a breakage need different
    people. See the module docstring.
    """

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


#: Statuses that mean the interval is over. A span in one of these MUST carry an ``end_time``.
TERMINAL_SPAN_STATUSES: frozenset[SpanStatus] = frozenset(
    {SpanStatus.SUCCEEDED, SpanStatus.FAILED, SpanStatus.BLOCKED}
)

#: Which subject reference each span type may carry. A type absent from this map carries none:
#: an EPISODE span's subject is the episode, which it already names in ``episode_id``.
SUBJECT_FIELD_FOR_TYPE: dict[SpanType, str] = {
    SpanType.RETRIEVAL: "retrieval_id",
    SpanType.LLM_CALL: "model_call_id",
    SpanType.JOB: "job_id",
}

_SUBJECT_FIELDS = ("model_call_id", "job_id", "retrieval_id")


class ExecutionSpan(CoreModel):
    """One interval of execution within one trace (§17.19.1).

    Fields are exactly §17.19.1's, with ``cost_entry_ids`` stored by the table as a join rather
    than an array column -- see ``STRUCTURAL_ONLY`` in ``lab_brain.spec.schema_drift``. Nothing has
    been added: notably there is no ``project_id``, because §17.19.1 declares none, and inventing
    one here would be the drift ADR-0010 was written about. That does leave trace reads unscoped by
    project; recorded as a gap rather than papered over, because the scope would have to come from
    the Episode, which does not exist until M1.
    """

    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    span_type: SpanType
    episode_id: str | None = None
    actor_id: str | None = None

    #: At most one of the three is set, and it has to match ``span_type``. See the module docstring.
    model_call_id: str | None = None
    job_id: str | None = None
    retrieval_id: str | None = None

    start_time: dt.datetime
    end_time: dt.datetime | None = None
    status: SpanStatus

    #: Ledger entries this interval is accountable for (OPS-003's "cost refs"). A tuple, so the
    #: frozen model is frozen in fact and not only in configuration.
    cost_entry_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.parent_span_id == self.span_id:
            raise ValueError(
                f"span {self.span_id} is its own parent; a trace has to be a tree, and a cycle "
                "makes reconstruction non-terminating rather than merely wrong"
            )

        present = [name for name in _SUBJECT_FIELDS if getattr(self, name) is not None]
        if len(present) > 1:
            raise ValueError(
                f"span {self.span_id} carries {', '.join(present)}; §17.19.1 declares the subject "
                "as one alternation, so a span describes at most one thing. Two subjects means "
                "two spans were never separated, and every cost on it is attributed to both"
            )
        expected = SUBJECT_FIELD_FOR_TYPE.get(self.span_type)
        if expected is None:
            if present:
                raise ValueError(
                    f"a {self.span_type.value} span takes no subject reference, but "
                    f"{present[0]} is set"
                )
        elif present and present[0] != expected:
            raise ValueError(
                f"a {self.span_type.value} span's subject is {expected}, but {present[0]} is set; "
                "a span typed as one thing and pointing at another cannot be reassembled"
            )

        if self.status in TERMINAL_SPAN_STATUSES and self.end_time is None:
            raise ValueError(
                f"span {self.span_id} is {self.status.value} with no end_time; a finished interval "
                "with no end is indistinguishable from one still running, and duration is what "
                "observability is for"
            )
        if self.status is SpanStatus.RUNNING and self.end_time is not None:
            raise ValueError(
                f"span {self.span_id} is RUNNING but has an end_time; close it with a terminal "
                "status instead of leaving a contradiction in the record"
            )
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError(
                f"span {self.span_id} ends before it starts ({self.end_time} < {self.start_time})"
            )
        if len(set(self.cost_entry_ids)) != len(self.cost_entry_ids):
            raise ValueError(
                f"span {self.span_id} lists a cost entry twice; a double-counted cost is worse "
                "than an unrecorded one because it looks like evidence"
            )
        return self

    @property
    def is_open(self) -> bool:
        return self.status is SpanStatus.RUNNING

    @property
    def duration_s(self) -> float | None:
        """Elapsed seconds, or ``None`` while the span is open."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    def closed(
        self,
        status: SpanStatus,
        end_time: dt.datetime,
        cost_entry_ids: tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionSpan:
        """A copy of this span, finished. The model is frozen; closing writes a new value.

        Re-validated rather than ``model_copy``d: ``model_copy`` skips validation, so an end_time
        before the start, or a status/end_time contradiction, would be constructible through the
        one method whose whole job is to produce a valid closed span.
        """
        if status is SpanStatus.RUNNING:
            raise ValueError("closing a span requires a terminal status")
        return ExecutionSpan.model_validate(
            {
                **self.model_dump(),
                "status": status,
                "end_time": end_time,
                "cost_entry_ids": (
                    self.cost_entry_ids if cost_entry_ids is None else cost_entry_ids
                ),
                "metadata": self.metadata if metadata is None else metadata,
            }
        )


__all__ = [
    "SUBJECT_FIELD_FOR_TYPE",
    "TERMINAL_SPAN_STATUSES",
    "ExecutionSpan",
    "SpanStatus",
    "SpanType",
]
