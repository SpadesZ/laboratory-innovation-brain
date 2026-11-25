"""The arm process of the independent-evaluation kit (one fresh interpreter per case and arm).

    python -s -B -P arm_worker.py --tree DIR --pin PIN_JSON

Started by the evaluator (`scripts/discovery_independent_kit.py`) with a minimal environment, an
empty working directory and pipes as stdin/stdout; it reads the arm's code ONLY from `DIR/src`, a
tree the evaluator materialized from the arm's pinned commit and checked against the pinned tree
id. It is deliberately standalone (it imports nothing from the kit's own checkout).

GUARD (defence in depth for Python arms; the boundary that matters is the operating system's: the
evaluator runs this process as a user that cannot read the sealed material, see the runbook).
Before any arm code is imported, an audit hook is installed that cannot be removed from Python:

    reads    only below the arm tree and the interpreter's own prefixes (stdlib, site-packages)
    writes   none, anywhere
    refused  process creation (subprocess, os.system, exec, spawn, fork), sockets, ctypes,
             changing directory

On the first refused event the worker writes {"op": "violation", ...} on the protocol channel and
exits at once (`os._exit`): an arm cannot catch it and continue. The evaluator ends the run
INVALID. `sys.path` is cut down to the arm tree and the interpreter's prefixes before the hook is
installed, and every `lab_brain` module must come from the arm tree.

PROTOCOL. One JSON object per line. The evaluator sends {"op": "run", ...}; the worker answers with
laboratory requests (motivating, measure, register), optional anytime declarations
({"op": "declare", "answer": ...}, for arms that call `lab.declare(answer)`), and finally
{"op": "done", "answer": ...} or {"op": "failed", "error": ...}. The arm's own prints go to stderr.
"""

from __future__ import annotations

import importlib
import json
import os
import site
import sys
from collections.abc import Callable
from typing import Any

PROTOCOL_OUT = sys.stdout
PROTOCOL_IN = sys.stdin
VIOLATION_EXIT = 70
_REFUSED_PREFIXES = (
    "subprocess.",
    "os.system",
    "os.exec",
    "os.spawn",
    "os.posix_spawn",
    "os.fork",
    "os.forkpty",
    "os.startfile",
    "os.chdir",
    "os.kill",
    "socket.",
    "ctypes.",
    "_posixsubprocess",
    "pty.",
    "webbrowser.",
    "urllib.",
    "ftplib.",
    "http.",
    "smtplib.",
    "os.remove",
    "os.rename",
    "os.rmdir",
    "os.mkdir",
    "os.link",
    "os.symlink",
    "os.truncate",
    "os.chmod",
    "os.chown",
    "os.utime",
    "shutil.",
)


def _send(message: dict[str, Any]) -> None:
    PROTOCOL_OUT.write(json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n")
    PROTOCOL_OUT.flush()


def _receive() -> dict[str, Any] | None:
    line = PROTOCOL_IN.readline()
    if not line:
        return None
    message = json.loads(line)
    if not isinstance(message, dict):
        raise SystemExit("the evaluator sent something that is not an object")
    return message


def _violation(event: str, detail: str) -> None:
    try:
        _send({"op": "violation", "event": event, "detail": f"{event}: {detail}"[:2000]})
    finally:
        os._exit(VIOLATION_EXIT)


def _roots(tree: str) -> tuple[str, ...]:
    candidates = {tree, sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    try:
        candidates.update(site.getsitepackages())
    except AttributeError:  # pragma: no cover - venv without getsitepackages
        pass
    out: set[str] = set()
    for c in candidates:
        if c:
            out.add(os.path.abspath(c))
            out.add(os.path.realpath(c))
    return tuple(sorted(out))


def install_guard(tree: str) -> None:
    roots = _roots(tree)

    def allowed(path: Any) -> bool:
        if isinstance(path, int):
            return True  # an already-open descriptor (the protocol pipes)
        try:
            text = os.fsdecode(path)
        except TypeError:
            return False
        full = os.path.abspath(text)
        return any(full == r or full.startswith(r.rstrip(os.sep) + os.sep) for r in roots)

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            writing = (isinstance(mode, str) and any(m in mode for m in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
            )
            if writing and not isinstance(path, int):
                _violation(event, f"write to {path!r}")
            if not allowed(path):
                _violation(event, f"read of {path!r}")
        elif event in ("os.listdir", "os.scandir"):
            path = args[0] if args else "."
            if not allowed(path if path is not None else "."):
                _violation(event, f"listing of {path!r}")
        elif event.startswith(_REFUSED_PREFIXES):
            _violation(event, "refused in the arm process")

    sys.addaudithook(hook)


def _load(reference: str) -> Any:
    module, _, name = reference.partition(":")
    value: Any = importlib.import_module(module)
    for part in name.split("."):
        value = getattr(value, part)
    return value


class Laboratory:
    """What the arm holds: every call is a message to the evaluator's laboratory service."""

    __slots__ = ()

    @staticmethod
    def _call(message: dict[str, Any]) -> dict[str, Any]:
        _send(message)
        reply = _receive()
        if reply is None:
            raise SystemExit("the evaluator closed the channel")
        if "error" in reply:
            raise RuntimeError(f"{reply['error']}: {reply.get('message', '')}")
        return reply

    def motivating(self) -> tuple[str, tuple[tuple[str, float], ...]]:
        reply = self._call({"op": "motivating"})
        return str(reply["experiment_id"]), tuple((str(k), float(v)) for k, v in reply["values"])

    def measure(
        self, experiment_id: str, *, replicate: int, session: int
    ) -> tuple[tuple[str, float], ...]:
        reply = self._call(
            {
                "op": "measure",
                "experiment_id": experiment_id,
                "replicate": replicate,
                "session": session,
            }
        )
        return tuple((str(k), float(v)) for k, v in reply["values"])

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

    def declare(self, answer: Any) -> None:
        """An anytime answer: the evaluator stamps it with the charge at this moment."""
        payload = answer.as_json() if hasattr(answer, "as_json") else dict(answer)
        self._call({"op": "declare", "answer": payload})

    def __repr__(self) -> str:
        return "Laboratory()"


def main(argv: list[str]) -> int:
    if "--tree" not in argv or "--pin" not in argv:
        print("usage: arm_worker.py --tree DIR --pin PIN_JSON", file=sys.stderr)
        return 2
    tree = os.path.abspath(argv[argv.index("--tree") + 1])
    pin = json.loads(argv[argv.index("--pin") + 1])
    src = os.path.join(tree, "src")
    prefixes = _roots(tree)
    sys.path[:] = [src] + [
        p
        for p in sys.path
        if p and any(os.path.abspath(p).startswith(r) for r in prefixes) and p != src
    ]
    sys.stdout = sys.stderr  # the arm's prints never reach the protocol channel
    install_guard(tree)
    context = pin["context"]
    entry: Callable[..., Any] = _load(pin["entry"])
    catalog_factory = _load(context["catalog"])
    oracle_class = _load(context["oracle"])
    protocol = _load(context["protocol"])
    grammar = None
    if context.get("grammar"):
        grammar = _load(context["grammar_builder"])(_load(context["grammar"])())
    outside = sorted(
        name
        for name, module in sys.modules.items()
        if name.startswith("lab_brain")
        and getattr(module, "__file__", None)
        and not os.path.abspath(str(module.__file__)).startswith(src + os.sep)
    )
    if outside:
        _violation("import", f"lab_brain modules from outside the arm tree: {outside[:5]}")
    lab = Laboratory()
    while True:
        request = _receive()
        if request is None:
            return 0
        try:
            catalog = catalog_factory()
            if catalog.digest != request["catalog_digest"]:
                raise ValueError("the arm's catalog is not the catalog the package names")
            available = tuple(request["available"])
            removed = {str(a): str(b) for a, b in request.get("removed", [])}
            oracle = oracle_class(catalog, available, protocol, removed)
            answer = entry(
                str(pin["arm_name"]),
                catalog=catalog,
                oracle=oracle,
                budget=int(request["budget"]),
                lab=lab,
                grammar=grammar,
            )
            payload = answer.as_json() if hasattr(answer, "as_json") else dict(answer)
        except SystemExit:
            raise
        except Exception as exc:  # reported; the evaluator ends the run CRASHED
            _send({"op": "failed", "error": f"{type(exc).__name__}: {exc}"[:2000]})
            continue
        _send({"op": "done", "answer": payload})


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
