"""The evaluator's ledger: append-only, hash-chained, written only by the evaluator's laboratory.

Three kinds of event, each with the SHA-256 chain value of everything before it:

    MOTIVATING  the motivating observation the investigation starts from (not admitted data)
    MEASURE     the laboratory ran an experiment and returned these values; written by the
                evaluator's laboratory itself, so no arm can write one without paying for a run.
                `replicate` is what the arm asked for; `count` is the evaluator's own count of
                earlier runs of that experiment in this investigation
    REGISTER    the arm named an IDENTITY (a forward-model fingerprint), an experiment and a number
                of runs; the evaluator stores them with ITS OWN digest of the measurements recorded
                so far (and the digest the arm declared, if any, for comparison only)

Nothing in a REGISTER event is a prediction: the predicted values, their uncertainty, the
alternatives and the thresholds are computed later by the evaluator (`rule.py`) from the events
before the registration. The target of a registration is the next `runs` MEASURE events of its
experiment after it.

`EvaluatorLaboratory` is what the arm receives in process: `motivating`, `measure`,
`register_identity` (and `register`, which accepts a v1.2 payload and keeps only its identity and
experiment). It exposes no read of the ledger, and the ledger keeps its events in a private list
that only `events()` copies out. In process this is an object-capability boundary against
accidental misuse, not against an adversary that walks the interpreter's memory; the evaluation
therefore runs each arm in a separate process (`boundary.py`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.loop import Laboratory
from lab_brain.discovery.model import Observation
from lab_brain.discovery_safety.v12.ledger import PredictionLedger

MOTIVATING = "MOTIVATING"
MEASURE = "MEASURE"
REGISTER = "REGISTER"
GENESIS = "sha256:" + "0" * 64

Values = tuple[tuple[str, float], ...]


def _canonical(body: Mapping[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEvent:
    index: int
    kind: str
    experiment_id: str
    #: MEASURE: the replicate the arm asked for; REGISTER: -1.
    replicate: int = -1
    #: MEASURE: the evaluator's own count of earlier runs of this experiment.
    count: int = -1
    values: Values = ()
    identity: str = ""
    runs: int = 0
    #: REGISTER: the evaluator's digest of every MEASURE event before this one.
    data_digest: str = ""
    #: REGISTER: what the arm declared it used (compared, never relied on).
    declared_data_digest: str = ""
    previous: str = GENESIS
    chain: str = ""

    def body(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "experiment_id": self.experiment_id,
            "replicate": self.replicate,
            "count": self.count,
            "values": [[k, repr(float(v))] for k, v in self.values],
            "identity": self.identity,
            "runs": self.runs,
            "data_digest": self.data_digest,
            "declared_data_digest": self.declared_data_digest,
            "previous": self.previous,
        }


def measurement_digest(measurements: Sequence[tuple[str, Values]]) -> str:
    """The digest of an ordered list of (experiment, values): what a registration was based on."""
    return _sha(
        _canonical(
            {"measurements": [[e, [[k, repr(float(v))] for k, v in vs]] for e, vs in measurements]}
        )
    )


class EvaluatorLedger:
    """Append-only and hash-chained. Owned by the evaluator; never handed to an arm."""

    __slots__ = ("_events",)

    def __init__(self) -> None:
        self._events: list[LedgerEvent] = []

    def _append(self, **fields: Any) -> LedgerEvent:
        previous = self._events[-1].chain if self._events else GENESIS
        draft = LedgerEvent(index=len(self._events), previous=previous, **fields)
        event = LedgerEvent(**{**draft.__dict__, "chain": _sha(_canonical(draft.body()))})
        self._events.append(event)
        return event

    def record_motivating(self, experiment_id: str, values: Values) -> LedgerEvent:
        return self._append(kind=MOTIVATING, experiment_id=experiment_id, values=tuple(values))

    def record_measurement(self, experiment_id: str, replicate: int, values: Values) -> LedgerEvent:
        count = sum(
            1 for e in self._events if e.kind == MEASURE and e.experiment_id == experiment_id
        )
        return self._append(
            kind=MEASURE,
            experiment_id=experiment_id,
            replicate=replicate,
            count=count,
            values=tuple(values),
        )

    def register(
        self, identity: str, experiment_id: str, runs: int, declared_data_digest: str = ""
    ) -> LedgerEvent:
        if not identity or not isinstance(identity, str):
            raise ValueError("a registration names an identity")
        if not isinstance(runs, int) or runs < 1:
            raise ValueError("a registered test has at least one run")
        return self._append(
            kind=REGISTER,
            experiment_id=experiment_id,
            identity=identity,
            runs=runs,
            data_digest=measurement_digest(self.measurements_before(len(self._events))),
            declared_data_digest=declared_data_digest or "",
        )

    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    @property
    def head(self) -> str:
        return self._events[-1].chain if self._events else GENESIS

    def measurements_before(self, index: int) -> list[tuple[str, Values]]:
        return [(e.experiment_id, e.values) for e in self._events[:index] if e.kind == MEASURE]


def verify_chain(events: Sequence[LedgerEvent]) -> None:
    """Raise if any event was altered, removed or reordered (recomputes every chain value)."""
    previous = GENESIS
    for i, event in enumerate(events):
        if event.index != i or event.previous != previous:
            raise ValueError(f"ledger event {i} is out of order or its predecessor changed")
        if _sha(_canonical(event.body())) != event.chain:
            raise ValueError(f"ledger event {i} does not match its chain value")
        if event.kind == REGISTER and event.data_digest != measurement_digest(
            [(e.experiment_id, e.values) for e in events[:i] if e.kind == MEASURE]
        ):
            raise ValueError(f"registration {i} does not match the data recorded before it")
        previous = event.chain


def observations_before(events: Sequence[LedgerEvent], index: int) -> list[Observation]:
    """The admitted data before event `index`, as observations (motivating excluded)."""
    return [
        Observation(
            observation_id=f"ledger:{e.index}",
            experiment_id=e.experiment_id,
            replicate=e.count,
            taken_at=e.index + 1,
            values=e.values,
        )
        for e in events[:index]
        if e.kind == MEASURE
    ]


class EvaluatorLaboratory:
    """The laboratory an arm receives in process: blind and metered (the wrapped laboratory),
    every run written to the evaluator's ledger, plus `register_identity`. Reads nothing back."""

    __slots__ = ("_lab", "_ledger", "_v12")

    def __init__(
        self, lab: Laboratory, ledger: EvaluatorLedger, v12: PredictionLedger | None = None
    ) -> None:
        self._lab = lab
        self._ledger = ledger
        self._v12 = v12

    def motivating(self) -> tuple[str, Values]:
        experiment_id, values = self._lab.motivating()
        self._ledger.record_motivating(experiment_id, values)
        return experiment_id, values

    def measure(self, experiment_id: str, *, replicate: int, session: int) -> Values:
        values = self._lab.measure(experiment_id, replicate=replicate, session=session)
        self._ledger.record_measurement(experiment_id, replicate, values)
        if self._v12 is not None:
            self._v12.record_measurement(experiment_id, replicate, values)
        return values

    def register_identity(
        self, identity: str, experiment_id: str, runs: int = 1, data_digest: str = ""
    ) -> dict[str, Any]:
        event = self._ledger.register(identity, experiment_id, runs, data_digest)
        return {"index": event.index, "chain": event.chain}

    def register(self, text: str) -> int:
        """A v1.2 payload: kept whole in the evaluator's v1.2 ledger (to report v1.2's own rule),
        and registered in the v1.3 ledger as its identity and experiment only -- its predicted
        values, SD, alternatives and rule are discarded."""
        payload = json.loads(text)
        if self._v12 is not None:
            self._v12.register(text)
        event = self._ledger.register(str(payload["fingerprint"]), str(payload["experiment_id"]), 1)
        return event.index

    def __repr__(self) -> str:
        return "EvaluatorLaboratory()"


__all__ = [
    "GENESIS",
    "MEASURE",
    "MOTIVATING",
    "REGISTER",
    "EvaluatorLaboratory",
    "EvaluatorLedger",
    "LedgerEvent",
    "measurement_digest",
    "observations_before",
    "verify_chain",
]
