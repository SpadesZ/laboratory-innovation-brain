"""The evaluator's side of one run: the laboratory service, the meter and the trace.

    evaluator process                                  arm process (separate interpreter)
    -----------------                                  ----------------------------------
    the world (truth), the meter, the trace     <--    {"op": "motivating"}
                                                <--    {"op": "measure", experiment_id, replicate, session}
                                                <--    {"op": "register", identity, experiment_id, runs, data_digest}
                                                <--    {"op": "declare", "answer": {...}}       (anytime, optional)
                                                <--    {"op": "done", "answer": {...}}          (final)
                                                <--    {"op": "failed", "error": "..."}         (the arm raised)
                                                <--    {"op": "violation", ...}                 (the worker's guard)

The transport is the caller's (`send`, `receive`): the composition root owns the arm process, its
pipes and its wall-clock limit (this package starts no process and reads no clock). `receive`
returns a message, or a `Lost` describing why none came (the arm exited, closed its channel, sent
something that is not one JSON object, or ran out of time).

EVALUATOR-CONTROLLED EVIDENCE. The arm reaches the world only through `measure`: the evaluator
checks the experiment is available in this world, RESERVES its frozen cost against the cap before
running it (an experiment whose cost does not fit is never run), runs it, and writes the MEASURE
event itself. A REGISTER event keeps only the identity, experiment and run count the arm names (the
digest the arm declares for its data is kept beside, never relied on). A declared answer is checked
against a closed schema and stamped by the evaluator with the charge and the number of evidence
events at that moment; the arm cannot date it. Nothing else an arm sends is accepted: an unknown
operation, an unknown key, a malformed value, a session that goes backwards, an answer whose
`spent` differs from the meter, an attempt beyond the cap or a guard violation ends the run INVALID
on the spot. The arm never receives the trace, the meter, the world or any verdict.

STATUS. COMPLETED (the arm answered), CRASHED (the arm raised or its process died or went silent),
INVALID (an incident above), TRUNCATED (the message limit was reached). Only a COMPLETED trace is
scored; every other status is DEFICIENT and is scored against the arm at every checkpoint.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.loop import Laboratory
from lab_brain.discovery.model import ExperimentSpec
from lab_brain.discovery_eval.blind import _checked
from lab_brain.discovery_eval.independent import trace as tr

#: The keys an answer may carry (the v1.3 `ArmAnswer` schema plus the arm's stated level).
ANSWER_KEYS = frozenset(
    {
        "arm",
        "outcome",
        "answer_kind",
        "claim",
        "new_mechanism",
        "grammar_proposal",
        "labelled_proposal",
        "acted_on",
        "spent",
        "reason",
        "digest",
        "notes",
        "stated_level",
    }
)
ANSWER_KINDS = frozenset({"NONE", "CATALOG_CLAIM", "NEW_MECHANISM"})
OPS = frozenset({"motivating", "measure", "register", "declare", "done", "failed", "violation"})
MAX_TEXT = 4000
MAX_LIST = 64
#: A run that exchanges more messages than this is TRUNCATED (a runaway arm).
DEFAULT_MAX_MESSAGES = 20_000


@dataclass(frozen=True)
class Lost:
    """No message came: why."""

    reason: str


Send = Callable[[Mapping[str, Any]], None]
Receive = Callable[[], "dict[str, Any] | Lost"]


class _Invalid(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def _text(value: Any, where: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _Invalid("protocol", f"{where}: a string of at most {limit} characters")
    return value


def _int(value: Any, where: str, low: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise _Invalid("protocol", f"{where}: an integer >= {low}")
    return value


def validate_answer(raw: Any, arm_id: str) -> dict[str, Any]:
    """The answer as plain data under a closed schema, or `_Invalid`. Nothing in it is trusted:
    the evaluator judges it from the trace."""
    if not isinstance(raw, Mapping):
        raise _Invalid("protocol", "an answer is an object")
    extra = sorted(set(raw) - ANSWER_KEYS)
    if extra:
        raise _Invalid("protocol", f"an answer carries keys outside its schema: {extra}")
    for key in ("arm", "outcome", "answer_kind"):
        if key not in raw:
            raise _Invalid("protocol", f"an answer names its {key}")
    out: dict[str, Any] = {
        "arm": _text(raw["arm"], "answer.arm", 64),
        "outcome": _text(raw["outcome"], "answer.outcome", 64),
        "answer_kind": _text(raw["answer_kind"], "answer.answer_kind", 32),
        "new_mechanism": _text(raw.get("new_mechanism", ""), "answer.new_mechanism", 200),
        "grammar_proposal": _text(raw.get("grammar_proposal", ""), "answer.grammar_proposal", 200),
        "reason": _text(raw.get("reason", ""), "answer.reason"),
        "digest": _text(raw.get("digest", ""), "answer.digest", 200),
        "stated_level": _text(raw.get("stated_level", ""), "answer.stated_level", 32),
        "spent": _int(raw.get("spent", 0), "answer.spent"),
    }
    if out["arm"] != arm_id:
        raise _Invalid("protocol", f"the answer names arm {out['arm']!r}, not {arm_id!r}")
    if out["answer_kind"] not in ANSWER_KINDS:
        raise _Invalid("protocol", f"answer_kind {out['answer_kind']!r} is not one of the kinds")
    for key in ("labelled_proposal", "acted_on"):
        value = raw.get(key, False)
        if not isinstance(value, bool):
            raise _Invalid("protocol", f"answer.{key}: true or false")
        out[key] = value
    for key in ("claim", "notes"):
        value = raw.get(key, [])
        if not isinstance(value, list | tuple) or len(value) > MAX_LIST:
            raise _Invalid("protocol", f"answer.{key}: a list of at most {MAX_LIST} strings")
        out[key] = [_text(v, f"answer.{key}[]", 400) for v in value]
    return out


class CaseService:
    """One run's laboratory service: the world's laboratory (truth stays here), the frozen cost
    table, the cap and the trace."""

    def __init__(
        self,
        *,
        lab: Laboratory,
        experiments: Mapping[str, ExperimentSpec],
        available: tuple[str, ...],
        cap: int,
        arm_id: str,
        start: Mapping[str, Any],
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:
        self._lab = lab
        self._specs = dict(experiments)
        self._available = frozenset(available)
        self.cap = cap
        self.arm_id = arm_id
        self.charge = 0
        self.max_messages = max_messages
        self.messages = 0
        self._session = 0
        self.writer = tr.TraceWriter()
        self.writer.append(tr.START, {**dict(start), "arm": arm_id, "cap": cap})

    # -- the operations ------------------------------------------------------------------------

    def _motivating(self) -> dict[str, Any]:
        experiment_id, values = self._lab.motivating()
        checked = _checked(self._specs[experiment_id], values)
        self.writer.append(
            tr.MOTIVATING,
            {"experiment_id": experiment_id, "values": tr.encode_values(checked)},
        )
        return {"experiment_id": experiment_id, "values": [[k, v] for k, v in checked]}

    def _measure(self, message: Mapping[str, Any]) -> dict[str, Any]:
        experiment_id = _text(message.get("experiment_id"), "measure.experiment_id", 200)
        replicate = _int(message.get("replicate"), "measure.replicate")
        session = _int(message.get("session"), "measure.session")
        if session < self._session:
            raise _Invalid("protocol", f"session {session} goes back from {self._session}")
        if experiment_id not in self._specs or experiment_id not in self._available:
            self.writer.append(
                tr.REFUSED,
                {"op": "measure", "experiment_id": experiment_id, "reason": "unavailable"},
            )
            return {
                "error": "ExposureRefused",
                "message": f"{experiment_id} cannot be run in this world's laboratory",
            }
        cost = int(self._specs[experiment_id].cost)
        if self.charge + cost > self.cap:
            # reservation before execution: it does not fit, so it never runs
            raise _Invalid(
                "budget",
                f"{experiment_id} reserves {cost} with {self.cap - self.charge} of {self.cap} left",
            )
        self._session = session
        before = self.charge
        values = _checked(
            self._specs[experiment_id],
            self._lab.measure(experiment_id, replicate=replicate, session=session),
        )
        self.charge += cost  # settlement: the frozen cost table, so settlement == reservation
        self.writer.append(
            tr.MEASURE,
            {
                "experiment_id": experiment_id,
                "replicate": replicate,
                "session": session,
                "cost": cost,
                "charge_before": before,
                "charge_after": self.charge,
                "values": tr.encode_values(values),
            },
        )
        return {"values": [[k, v] for k, v in values]}

    def _register(self, message: Mapping[str, Any]) -> dict[str, Any]:
        identity = _text(message.get("identity"), "register.identity", 400)
        experiment_id = _text(message.get("experiment_id"), "register.experiment_id", 200)
        runs = _int(message.get("runs", 1), "register.runs", 1)
        declared = _text(message.get("data_digest") or "", "register.data_digest", 200)
        if not identity:
            raise _Invalid("protocol", "a registration names an identity")
        if experiment_id not in self._specs:
            raise _Invalid("protocol", f"a registration names an unknown experiment {experiment_id!r}")
        # the v1.3 ledger index the arm would have received: evidence events before this one
        index = self.writer.evidence_count()
        event = self.writer.append(
            tr.REGISTER,
            {
                "identity": identity,
                "experiment_id": experiment_id,
                "runs": runs,
                "declared_data_digest": declared,
            },
        )
        return {"receipt": {"index": index, "chain": event.chain}}

    def _declare(self, raw: Any, source: str) -> None:
        answer = validate_answer(raw, self.arm_id)
        stated = answer.pop("stated_level")
        self.writer.append(
            tr.DECLARE,
            {
                "source": source,
                "answer": answer,
                "stated_level": stated,
                "charge": self.charge,
                "evidence_count": self.writer.evidence_count(),
            },
        )

    # -- the run ---------------------------------------------------------------------------------

    def end(self, status: str, reason: str) -> tuple[tr.TraceEvent, ...]:
        self.writer.append(
            tr.END,
            {
                "status": status,
                "reason": reason[:MAX_TEXT],
                "charge": self.charge,
                "messages": self.messages,
            },
        )
        return self.writer.events()

    def incident(self, kind: str, detail: str) -> tuple[tr.TraceEvent, ...]:
        self.writer.append(tr.INCIDENT, {"kind": kind, "detail": detail[:MAX_TEXT]})
        return self.end(tr.INVALID, f"{kind}: {detail}")

    def serve(
        self, request: Mapping[str, Any], send: Send, receive: Receive
    ) -> tuple[tr.TraceEvent, ...]:
        """Send the run request, then serve the arm until it answers, fails or breaks a rule."""
        send({"op": "run", **dict(request)})
        while True:
            message = receive()
            if isinstance(message, Lost):
                return self.end(tr.CRASHED, f"no answer: {message.reason}")
            self.messages += 1
            if self.messages > self.max_messages:
                return self.end(tr.TRUNCATED, f"more than {self.max_messages} messages")
            op = message.get("op") if isinstance(message, dict) else None
            try:
                if op not in OPS:
                    raise _Invalid("protocol", f"unknown operation {op!r}")
                if op == "violation":
                    raise _Invalid("isolation", _text(message.get("detail", ""), "violation"))
                if op == "failed":
                    return self.end(
                        tr.CRASHED, "the arm raised: " + str(message.get("error", ""))[:MAX_TEXT]
                    )
                if op == "done":
                    self._declare(message.get("answer"), "final")
                    final = self.writer.events()[-1].body["answer"]
                    if int(final["spent"]) != self.charge:
                        raise _Invalid(
                            "metering",
                            f"the arm reports {final['spent']} spent; the meter charged "
                            f"{self.charge}",
                        )
                    return self.end(tr.COMPLETED, "answered")
                if op == "declare":
                    self._declare(message.get("answer"), "anytime")
                    reply: dict[str, Any] = {"ok": True}
                elif op == "motivating":
                    reply = self._motivating()
                elif op == "measure":
                    reply = self._measure(message)
                else:
                    reply = self._register(message)
            except _Invalid as exc:
                return self.incident(exc.kind, exc.detail)
            send(reply)


def run_case(
    service: CaseService, request: Mapping[str, Any], send: Send, receive: Receive
) -> tuple[tr.TraceEvent, ...]:
    events = service.serve(request, send, receive)
    tr.verify_trace(events)
    return events


def finite(values: Any) -> bool:
    return all(math.isfinite(float(v)) for _, v in values)


__all__ = [
    "ANSWER_KEYS",
    "ANSWER_KINDS",
    "DEFAULT_MAX_MESSAGES",
    "OPS",
    "CaseService",
    "Lost",
    "Receive",
    "Send",
    "run_case",
    "validate_answer",
]
