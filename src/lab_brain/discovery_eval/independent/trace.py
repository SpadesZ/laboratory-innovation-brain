"""The run trace: one append-only, hash-chained record per (case, arm), written by the evaluator.

Every event is written by the evaluator's process; nothing an arm sends is copied into the trace
except its declared answers (as data to be judged) and the identities it registers. Each event
carries the chain value of everything before it:

    chain_i = "sha256:" + SHA-256(canonical_json({index, kind, body, previous}))

    START       case id, arm id and pin, the cap, the package root and the kit manifest id
    MOTIVATING  the motivating observation (not admitted data, costs nothing)
    MEASURE     the laboratory ran an experiment: experiment, the replicate and session the arm
                asked for, its frozen cost, the charge before and after, the values returned
    REGISTER    the arm named an identity, an experiment and a number of runs (no prediction: the
                evaluator computes every prediction itself from the events before)
    DECLARE     the arm committed an answer (an anytime answer, or its final one), stamped by the
                evaluator with the charge at that moment and the number of evidence events before
                it; the arm's own statement of its level is kept as `stated_level` and ignored
    REFUSED     a request the laboratory refused (an experiment this world cannot run)
    INCIDENT    a budget, protocol, isolation or metering incident (the run is then INVALID)
    END         the run's status (COMPLETED, CRASHED, INVALID, TRUNCATED), the meter's charge

Values are written as `repr(float)` strings: canonical JSON refuses floats, and `float(repr(x))`
is exactly `x`.

THE ANSWER AT A CHECKPOINT. Let D be the DECLARE events of a COMPLETED trace in order. The answer
at checkpoint c is the answer of the last d in D whose `charge` is <= c; if there is none, the arm
holds no claim at c. The charge of a DECLARE is the frozen cost of every experiment STARTED before
it (experiment costs are fixed in this interface, so the reservation of an experiment is its
settlement and no operation straddles a declaration). The evidence for that answer is exactly the
MOTIVATING, MEASURE and REGISTER events before it (`evidence_count`): a result obtained after the
declaration cannot reach the answer at an earlier checkpoint.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.core.canonical_json import canonical_bytes

TRACE_KIND = "lab-brain/independent-eval-trace@1"
GENESIS = "sha256:" + "0" * 64

START = "START"
MOTIVATING = "MOTIVATING"
MEASURE = "MEASURE"
REGISTER = "REGISTER"
DECLARE = "DECLARE"
REFUSED = "REFUSED"
INCIDENT = "INCIDENT"
END = "END"
KINDS = (START, MOTIVATING, MEASURE, REGISTER, DECLARE, REFUSED, INCIDENT, END)
#: The events that are evidence (what the evaluator's rule reads).
EVIDENCE_KINDS = frozenset({MOTIVATING, MEASURE, REGISTER})

COMPLETED = "COMPLETED"
CRASHED = "CRASHED"
INVALID = "INVALID"
TRUNCATED = "TRUNCATED"
STATUSES = (COMPLETED, CRASHED, INVALID, TRUNCATED)

Values = tuple[tuple[str, float], ...]


class TraceTampered(ValueError):
    """The trace was altered, reordered, truncated or extended after the evaluator wrote it."""


def encode_values(values: Iterable[tuple[str, float]]) -> list[list[str]]:
    return [[str(k), repr(float(v))] for k, v in values]


def decode_values(raw: Iterable[Sequence[str]]) -> Values:
    return tuple((str(k), float(v)) for k, v in raw)


def _chain(index: int, kind: str, body: Mapping[str, Any], previous: str) -> str:
    payload = {"index": index, "kind": kind, "body": dict(body), "previous": previous}
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class TraceEvent:
    index: int
    kind: str
    body: Mapping[str, Any]
    previous: str
    chain: str

    def as_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "body": dict(self.body),
            "previous": self.previous,
            "chain": self.chain,
        }


class TraceWriter:
    """Append-only. Owned by the evaluator; never handed to an arm."""

    __slots__ = ("_events",)

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    def append(self, kind: str, body: Mapping[str, Any]) -> TraceEvent:
        if kind not in KINDS:
            raise ValueError(f"unknown trace event kind {kind!r}")
        if self._events and self._events[-1].kind == END:
            raise ValueError("the trace has ended")
        index = len(self._events)
        previous = self._events[-1].chain if self._events else GENESIS
        clean = json.loads(json.dumps(dict(body)))  # plain JSON data only, copied
        event = TraceEvent(index, kind, clean, previous, _chain(index, kind, clean, previous))
        self._events.append(event)
        return event

    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    @property
    def head(self) -> str:
        return self._events[-1].chain if self._events else GENESIS

    def evidence_count(self) -> int:
        return sum(1 for e in self._events if e.kind in EVIDENCE_KINDS)

    @property
    def ended(self) -> bool:
        return bool(self._events) and self._events[-1].kind == END


def verify_trace(events: Sequence[TraceEvent], *, head: str | None = None) -> None:
    """Raise `TraceTampered` unless every event is in place and unaltered, the trace starts with
    START and ends with END exactly once, and (when given) its last chain value is `head`, the
    value the evaluator recorded in the run summary when the run ended."""
    previous = GENESIS
    for i, event in enumerate(events):
        if event.index != i or event.previous != previous:
            raise TraceTampered(f"trace event {i} is out of order or its predecessor changed")
        if event.kind not in KINDS:
            raise TraceTampered(f"trace event {i} has an unknown kind")
        if _chain(event.index, event.kind, event.body, event.previous) != event.chain:
            raise TraceTampered(f"trace event {i} does not match its chain value")
        previous = event.chain
    if not events or events[0].kind != START:
        raise TraceTampered("a trace starts with START")
    ends = [e.index for e in events if e.kind == END]
    if ends != [len(events) - 1]:
        raise TraceTampered("a trace ends with exactly one END")
    if head is not None and events[-1].chain != head:
        raise TraceTampered("the trace's head differs from the one recorded when the run ended")


def dumps(events: Sequence[TraceEvent]) -> str:
    """JSON lines, one event per line, keys sorted: byte-stable."""
    return "".join(
        json.dumps(e.as_json(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for e in events
    )


def loads(text: str) -> tuple[TraceEvent, ...]:
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict) or set(raw) != {"index", "kind", "body", "previous", "chain"}:
            raise TraceTampered("a trace line is one event object with exactly its five keys")
        out.append(
            TraceEvent(
                index=int(raw["index"]),
                kind=str(raw["kind"]),
                body=dict(raw["body"]),
                previous=str(raw["previous"]),
                chain=str(raw["chain"]),
            )
        )
    return tuple(out)


def status(events: Sequence[TraceEvent]) -> str:
    return str(events[-1].body["status"])


def declarations(events: Sequence[TraceEvent]) -> list[TraceEvent]:
    return [e for e in events if e.kind == DECLARE]


def answer_at(events: Sequence[TraceEvent], checkpoint: int) -> TraceEvent | None:
    """The DECLARE event that holds at `checkpoint`: the last one whose charge is <= checkpoint,
    or None (no claim). Meaningful for COMPLETED traces only; the scorer treats every other status
    as deficient at every checkpoint."""
    held: TraceEvent | None = None
    for event in declarations(events):
        if int(event.body["charge"]) <= checkpoint:
            held = event
        else:
            break
    return held


def evidence_before(events: Sequence[TraceEvent], declaration: TraceEvent | None) -> list[TraceEvent]:
    """The evidence events written before `declaration` (all of them when it is None and the
    caller wants the whole trace's evidence)."""
    limit = declaration.index if declaration is not None else len(events)
    return [e for e in events[:limit] if e.kind in EVIDENCE_KINDS]


__all__ = [
    "COMPLETED",
    "CRASHED",
    "DECLARE",
    "END",
    "EVIDENCE_KINDS",
    "GENESIS",
    "INCIDENT",
    "INVALID",
    "KINDS",
    "MEASURE",
    "MOTIVATING",
    "REFUSED",
    "REGISTER",
    "START",
    "STATUSES",
    "TRACE_KIND",
    "TRUNCATED",
    "TraceEvent",
    "TraceTampered",
    "TraceWriter",
    "answer_at",
    "declarations",
    "decode_values",
    "dumps",
    "encode_values",
    "evidence_before",
    "loads",
    "status",
    "verify_trace",
]
