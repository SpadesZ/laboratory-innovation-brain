"""The environment of a blind evaluation, pinned so an independent evaluator can reproduce it.

A frozen protocol manifest (`manifest.py`) pins WHAT is scored -- cases, truth commitments, scorer.
It does not pin the system that PRODUCED the outputs. Two runs of the same frozen holdout on
different code, migrations, libraries or models are two experiments, and a score is only
reproducible if the evaluator can name, and later check, the one that ran. This module records it:

    code         the commit SHA and whether the working tree was clean (a dirty tree is refused
                 unless the evaluator says otherwise: uncommitted code cannot be reproduced)
    schema       every migration in apply order with its SHA-256, and one digest over the list
    libraries    every installed distribution `name==version`, and one digest over the list
    scorer       the scorer id, version and the SHA-256 of each scoring source file
    model        the model the generator used: endpoint, id and the evaluator-recorded digest

ZERO COST BY CONSTRUCTION. The protocol this serves (docs/evaluation/G0-blind-evaluation-protocol)
is free to run: its model must be served on this machine. An endpoint that is not this machine is
refused unless the evaluator explicitly records an Owner-authorized paid run (`allow_remote`) --
a remote model costs money and leaves the zero-cost protocol, and the manifest says so.

`verify` compares a recorded manifest with the environment now, field by field, and returns every
difference; reproducing a score starts with an empty list.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_brain.evaluation import scoring
from lab_brain.evaluation.manifest import scorer_sources
from lab_brain.llm_runtime.provider import is_this_machine_url

ENVIRONMENT_KIND = "g0-eval/environment@1"


class EnvironmentRefused(ValueError):
    """The environment cannot serve a zero-cost, reproducible blind evaluation as recorded."""


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest(lines: Sequence[str]) -> str:
    return _sha256("\n".join(lines).encode("utf-8"))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def code_state(root: Path) -> dict[str, Any]:
    return {
        "commit": _git(root, "rev-parse", "HEAD"),
        "clean": _git(root, "status", "--porcelain") == "",
    }


def schema_state(root: Path, apply_order: Sequence[str]) -> dict[str, Any]:
    files = [f"{name} {_sha256((root / 'migrations' / name).read_bytes())}" for name in apply_order]
    return {"migrations": files, "digest": _digest(files)}


def library_state() -> dict[str, Any]:
    names = sorted(
        {
            f"{(d.metadata['Name'] or '').lower()}=={d.version}"
            for d in importlib.metadata.distributions()
            if d.metadata["Name"]
        }
    )
    return {
        "python": platform.python_version(),
        "distributions": names,
        "digest": _digest(names),
    }


def model_state(
    *, endpoint: str, model_id: str, model_digest: str, allow_remote: bool
) -> dict[str, Any]:
    if not model_id or not model_digest:
        raise EnvironmentRefused(
            "name the generator's model and its digest (e.g. the local model's content digest)"
        )
    local = is_this_machine_url(endpoint)
    if not local and not allow_remote:
        raise EnvironmentRefused(
            f"{endpoint} is not this machine: the zero-cost protocol runs a local model only; a "
            "remote model is a paid run that needs the Owner's authorization (allow_remote)"
        )
    return {
        "endpoint": endpoint,
        "model_id": model_id,
        "model_digest": model_digest,
        "served_by_this_machine": local,
        "zero_cost": local,
    }


def capture(
    root: Path,
    apply_order: Sequence[str],
    *,
    endpoint: str,
    model_id: str,
    model_digest: str,
    allow_remote: bool = False,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    """The environment now, as a manifest. Refuses a dirty tree unless `allow_dirty`."""
    code = code_state(root)
    if not code["clean"] and not allow_dirty:
        raise EnvironmentRefused(
            "the working tree has uncommitted changes: what ran could not be reproduced from the "
            "commit; commit or stash, or record allow_dirty for a dry run that proves nothing"
        )
    manifest: dict[str, Any] = {
        "kind": ENVIRONMENT_KIND,
        "code": code,
        "schema": schema_state(root, apply_order),
        "libraries": library_state(),
        "scorer": {
            "id": scoring.SCORER_ID,
            "version": scoring.SCORER_VERSION,
            "sources": scorer_sources(),
        },
        "model": model_state(
            endpoint=endpoint,
            model_id=model_id,
            model_digest=model_digest,
            allow_remote=allow_remote,
        ),
        "platform": {"system": platform.system(), "machine": platform.machine()},
    }
    manifest["environment_sha256"] = environment_hash(manifest)
    return manifest


def environment_hash(manifest: Mapping[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k != "environment_sha256"}
    return _sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def verify(recorded: Mapping[str, Any], now: Mapping[str, Any]) -> list[str]:
    """Every difference that would make `now` a different experiment from `recorded`."""
    if recorded.get("kind") != ENVIRONMENT_KIND:
        return [f"not an environment manifest ({ENVIRONMENT_KIND})"]
    if environment_hash(recorded) != recorded.get("environment_sha256"):
        return ["the recorded manifest does not hash to its own environment_sha256"]
    drift = []
    for field, path in (
        ("commit", ("code", "commit")),
        ("schema", ("schema", "digest")),
        ("libraries", ("libraries", "digest")),
        ("python", ("libraries", "python")),
        ("scorer version", ("scorer", "version")),
        ("scorer sources", ("scorer", "sources")),
        ("model id", ("model", "model_id")),
        ("model digest", ("model", "model_digest")),
        ("model endpoint locality", ("model", "served_by_this_machine")),
    ):
        a: Any = recorded
        b: Any = now
        for key in path:
            a = a.get(key) if isinstance(a, Mapping) else None
            b = b.get(key) if isinstance(b, Mapping) else None
        if a != b:
            drift.append(f"{field}: recorded {a!r}, now {b!r}")
    return drift


__all__ = [
    "ENVIRONMENT_KIND",
    "EnvironmentRefused",
    "capture",
    "environment_hash",
    "verify",
]
