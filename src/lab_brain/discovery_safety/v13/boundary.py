"""The process boundary: an arm runs in its own OS process and reaches the laboratory by message.

    evaluator process                               arm process (a fresh interpreter)
    -----------------                               ---------------------------------
    the world (its truth), the cost meter,          the arm's code, its catalog (as the arm
    the ledger, the evaluator laboratory            holds it at case start), the grammar
            ^                                                 |
            |  {"op": "motivating"}                           |
            |  {"op": "measure", experiment, replicate, ...}  |
            |  {"op": "register", identity, experiment, runs, data_digest}
            |  {"op": "register_v12", text}   (v1.2 payload; only identity + experiment kept)
            |  {"op": "done", "answer": {...}}                |
            +-------------------------------------------------+

Messages are one JSON document per line on the arm process's stdin/stdout (the arm's own stdout is
redirected to stderr). JSON only, in both directions: the evaluator never unpickles anything an
arm sends, and an arm's answer is plain data (`ArmAnswer`). The arm process never receives the
world specification, the truth, the meter, the ledger or the evaluator's verdicts; what it learns
is exactly what a laboratory returns. The evaluator applies its meter and its blind wrapper to
every request, as it does in process.

This module is domain-free: the composition root supplies the arm process's command line and,
inside it, the function that builds and runs an arm (`worker_loop`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import IO, Any

from lab_brain.discovery_eval.blind import ExposureRefused, RealizedCostExceeded
from lab_brain.discovery_safety.v13.ledger import EvaluatorLaboratory
from lab_brain.discovery_safety.v13.model import ArmAnswer

Values = tuple[tuple[str, float], ...]

_ERRORS: dict[str, type[Exception]] = {
    "ExposureRefused": ExposureRefused,
    "RealizedCostExceeded": RealizedCostExceeded,
}


class BoundaryError(RuntimeError):
    """The arm process broke the protocol or died."""


def _send(stream: IO[str], message: Mapping[str, Any]) -> None:
    stream.write(json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


def _receive(stream: IO[str]) -> dict[str, Any]:
    line = stream.readline()
    if not line:
        raise BoundaryError("the other side closed the channel")
    message = json.loads(line)
    if not isinstance(message, dict):
        raise BoundaryError("a message is a JSON object")
    return message


def _values(raw: Any) -> Values:
    return tuple((str(k), float(v)) for k, v in raw)


class ArmProcess:
    """One arm process, reused for many runs (one at a time)."""

    def __init__(self, argv: Sequence[str]) -> None:
        self._process = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def run(self, request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
        """Send one run request and serve the arm's laboratory requests until it answers."""
        assert self._process.stdin is not None and self._process.stdout is not None
        _send(self._process.stdin, {"op": "run", **request})
        while True:
            message = _receive(self._process.stdout)
            op = message.get("op")
            reply: dict[str, Any]
            try:
                if op == "motivating":
                    experiment_id, values = lab.motivating()
                    reply = {"experiment_id": experiment_id, "values": [list(v) for v in values]}
                elif op == "measure":
                    values = lab.measure(
                        str(message["experiment_id"]),
                        replicate=int(message["replicate"]),
                        session=int(message["session"]),
                    )
                    reply = {"values": [list(v) for v in values]}
                elif op == "register":
                    reply = {
                        "receipt": lab.register_identity(
                            str(message["identity"]),
                            str(message["experiment_id"]),
                            int(message["runs"]),
                            str(message.get("data_digest") or ""),
                        )
                    }
                elif op == "register_v12":
                    reply = {"index": lab.register(str(message["text"]))}
                elif op == "done":
                    return ArmAnswer.from_json(message["answer"])
                elif op == "failed":
                    raise BoundaryError(f"the arm failed: {message.get('error')}")
                else:
                    raise BoundaryError(f"unknown request {op!r}")
            except (ExposureRefused, RealizedCostExceeded, ValueError) as exc:
                reply = {"error": type(exc).__name__, "message": str(exc)}
            _send(self._process.stdin, reply)

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        self._process.wait(timeout=30)


class ProxyLaboratory:
    """What an arm holds inside its own process: every call is a message to the evaluator."""

    __slots__ = ("_in", "_out")

    def __init__(self, inbound: IO[str], outbound: IO[str]) -> None:
        self._in = inbound
        self._out = outbound

    def _call(self, message: Mapping[str, Any]) -> dict[str, Any]:
        _send(self._out, message)
        reply = _receive(self._in)
        if "error" in reply:
            error = _ERRORS.get(str(reply["error"]), RuntimeError)
            raise error(str(reply.get("message", "")))
        return reply

    def motivating(self) -> tuple[str, Values]:
        reply = self._call({"op": "motivating"})
        return str(reply["experiment_id"]), _values(reply["values"])

    def measure(self, experiment_id: str, *, replicate: int, session: int) -> Values:
        reply = self._call(
            {
                "op": "measure",
                "experiment_id": experiment_id,
                "replicate": replicate,
                "session": session,
            }
        )
        return _values(reply["values"])

    def register_identity(
        self, identity: str, experiment_id: str, runs: int = 1, data_digest: str = ""
    ) -> dict[str, Any]:
        reply = self._call(
            {
                "op": "register",
                "identity": identity,
                "experiment_id": experiment_id,
                "runs": runs,
                "data_digest": data_digest,
            }
        )
        receipt: dict[str, Any] = reply["receipt"]
        return receipt

    def register(self, text: str) -> int:
        return int(self._call({"op": "register_v12", "text": text})["index"])


def worker_loop(
    handler: Callable[[Mapping[str, Any], ProxyLaboratory], ArmAnswer],
    inbound: IO[str] | None = None,
    outbound: IO[str] | None = None,
) -> int:
    """The arm process's main loop: one run request at a time until stdin closes. The arm's own
    prints go to stderr so that stdout carries protocol messages only."""
    inbound = inbound if inbound is not None else sys.stdin
    outbound = outbound if outbound is not None else sys.stdout
    sys.stdout = sys.stderr
    lab = ProxyLaboratory(inbound, outbound)
    while True:
        line = inbound.readline()
        if not line:
            return 0
        request = json.loads(line)
        try:
            answer = handler(request, lab)
        except Exception as exc:  # reported to the evaluator, which stops the evaluation
            _send(outbound, {"op": "failed", "error": f"{type(exc).__name__}: {exc}"})
            continue
        _send(outbound, {"op": "done", "answer": answer.as_json()})


__all__ = ["ArmProcess", "BoundaryError", "ProxyLaboratory", "worker_loop"]
