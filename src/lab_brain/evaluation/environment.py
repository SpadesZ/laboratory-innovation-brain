"""The environment of a blind evaluation, pinned so an independent evaluator can reproduce it.

A frozen protocol manifest (`manifest.py`) pins WHAT is scored -- cases, truth commitments, scorer.
It does not pin the system that PRODUCED the outputs. Two runs of the same frozen holdout on
different code, migrations, libraries or models are two experiments, and a score is only
reproducible if the evaluator can name, and later check, the one that ran. This module records it:

    code         the commit SHA and whether the working tree was clean (a dirty tree is refused
                 unless the evaluator says otherwise: uncommitted code cannot be reproduced)
    schema       every migration in apply order with its SHA-256, and one digest over the list;
                 given a database connection, also the migrations actually applied to it (its
                 `schema_migrations` ledger) -- the files on disk are not the schema that ran
    libraries    every installed distribution `name==version`, and one digest over the list
    scorer       the scorer id, version and the SHA-256 of each scoring source file
    model        the model the generator used: endpoint, id, digest -- and where the digest came
                 from: `served` when the local model server reported it (Ollama's `/api/tags`)
                 and it matched the evaluator's, `declared` when the server could not say. A
                 served digest that contradicts the declared one is refused: the tag now names a
                 different model
    settings     every LAB_BRAIN_* setting of the process, with its value -- except a secret
                 (key, password, passphrase, token, URL or DSN), recorded only as set
    platform     the operating system and machine

ZERO COST BY CONSTRUCTION. The protocol this serves (docs/evaluation/G0-blind-evaluation-protocol)
is free to run: its model must be served on this machine. An endpoint that is not this machine is
refused unless the evaluator explicitly records an Owner-authorized paid run (`allow_remote`) --
a remote model costs money and leaves the zero-cost protocol, and the manifest says so.

`verify` compares a recorded manifest with the environment now, field by field, and returns every
difference; reproducing a score starts with an empty list. The blind runner calls it before the
first case and after the last (`lab_brain.evaluation.runner`).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_brain.evaluation import scoring
from lab_brain.evaluation.manifest import scorer_sources
from lab_brain.llm_runtime.provider import is_this_machine_url

ENVIRONMENT_KIND = "g0-eval/environment@1"
VERIFICATION_KIND = "g0-eval/environment-verification@1"


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


def schema_state(
    root: Path, apply_order: Sequence[str], connection: Any | None = None
) -> dict[str, Any]:
    files = [f"{name} {_sha256((root / 'migrations' / name).read_bytes())}" for name in apply_order]
    state: dict[str, Any] = {"migrations": files, "digest": _digest(files), "applied_digest": None}
    if connection is not None:
        applied = [
            f"{name} {checksum}"
            for name, checksum in connection.execute(
                "SELECT filename, checksum FROM schema_migrations ORDER BY apply_index, filename"
            ).fetchall()
        ]
        state["applied"] = applied
        state["applied_digest"] = _digest(applied)
    return state


#: A setting whose value is a secret (or carries one, as a URL with a password does): only its
#: presence is recorded.
_SECRET_WORDS = frozenset(
    {"KEY", "SECRET", "PASSWORD", "PASSPHRASE", "TOKEN", "CREDENTIAL", "CREDENTIALS", "URL", "DSN"}
)


def _secret_setting(name: str) -> bool:
    return any(word in _SECRET_WORDS for word in name.upper().split("_"))


def settings_state(env: Mapping[str, str]) -> dict[str, Any]:
    """Every LAB_BRAIN_* setting: `NAME=value`, or `NAME=<set>` for a secret."""
    values = sorted(
        f"{name}=<set>" if _secret_setting(name) else f"{name}={value}"
        for name, value in env.items()
        if name.startswith("LAB_BRAIN_")
    )
    return {"values": values, "digest": _digest(values)}


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=3) as answer:  # only ever this machine
        return json.loads(answer.read().decode("utf-8"))


def served_model_digest(
    endpoint: str, model_id: str, *, fetch: Callable[[str], Any] = _fetch_json
) -> str | None:
    """The digest the local model server reports for `model_id` (Ollama: `GET /api/tags`, a GET
    without a body -- no prompt, nothing generated, no cost), or None when it cannot say."""
    root = endpoint.rstrip("/")
    root = root[: -len("/v1")] if root.endswith("/v1") else root
    try:
        listed = fetch(root + "/api/tags")
    except Exception:  # a server that cannot say leaves the digest declared
        return None
    models = listed.get("models") if isinstance(listed, Mapping) else None
    for entry in models if isinstance(models, list) else ():
        if isinstance(entry, Mapping) and model_id in (entry.get("name"), entry.get("model")):
            digest = entry.get("digest")
            if isinstance(digest, str) and re.fullmatch(r"(sha256:)?[0-9a-f]{64}", digest):
                return digest if digest.startswith("sha256:") else "sha256:" + digest
    return None


def _same_digest(a: str, b: str) -> bool:
    def bare(d: str) -> str:
        return d.lower().removeprefix("sha256:")

    return bare(a) == bare(b)


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
    *,
    endpoint: str,
    model_id: str,
    model_digest: str,
    allow_remote: bool,
    fetch_tags: Callable[[str], Any] | None = None,
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
    served = (
        served_model_digest(endpoint, model_id, fetch=fetch_tags or _fetch_json) if local else None
    )
    if served is not None and not _same_digest(served, model_digest):
        raise EnvironmentRefused(
            f"the local server serves {model_id} as {served}, not the declared {model_digest}: "
            "the tag names a different model now"
        )
    return {
        "endpoint": endpoint,
        "model_id": model_id,
        "model_digest": model_digest,
        "digest_source": "served" if served is not None else "declared",
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
    connection: Any | None = None,
    env: Mapping[str, str] | None = None,
    fetch_tags: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """The environment now, as a manifest. Refuses a dirty tree unless `allow_dirty`.
    `connection`: the evaluation's database, whose applied migrations are recorded; `env`: the
    process environment (default `os.environ`); `fetch_tags`: how the local model server is asked
    for its digests (default: HTTP GET on this machine)."""
    code = code_state(root)
    if not code["clean"] and not allow_dirty:
        raise EnvironmentRefused(
            "the working tree has uncommitted changes: what ran could not be reproduced from the "
            "commit; commit or stash, or record allow_dirty for a dry run that proves nothing"
        )
    manifest: dict[str, Any] = {
        "kind": ENVIRONMENT_KIND,
        "code": code,
        "schema": schema_state(root, apply_order, connection),
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
            fetch_tags=fetch_tags,
        ),
        "settings": settings_state(os.environ if env is None else env),
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
        ("clean tree", ("code", "clean")),
        ("schema", ("schema", "digest")),
        ("applied schema", ("schema", "applied_digest")),
        ("libraries", ("libraries", "digest")),
        ("python", ("libraries", "python")),
        ("scorer version", ("scorer", "version")),
        ("scorer sources", ("scorer", "sources")),
        ("model id", ("model", "model_id")),
        ("model digest", ("model", "model_digest")),
        ("model digest source", ("model", "digest_source")),
        ("model endpoint", ("model", "endpoint")),
        ("model endpoint locality", ("model", "served_by_this_machine")),
        ("settings", ("settings", "digest")),
        ("platform", ("platform",)),
    ):
        a: Any = recorded
        b: Any = now
        for key in path:
            a = a.get(key) if isinstance(a, Mapping) else None
            b = b.get(key) if isinstance(b, Mapping) else None
        if a != b:
            drift.append(f"{field}: recorded {a!r}, now {b!r}")
    return drift


def verification_record(
    recorded: Mapping[str, Any],
    now: Mapping[str, Any],
    *,
    verifier_id: str,
    verified_at: str,
) -> dict[str, Any]:
    """The evaluator's record that they re-captured the environment and compared it with the
    recorded one (`verify`): what was compared, by whom, when, and every difference. An
    ACCEPTANCE score requires one with no difference (`manifest.score_run`)."""
    if not verifier_id.strip():
        raise EnvironmentRefused("a verification names who verified (the evaluator's id)")
    model: Mapping[str, Any] = now["model"] if isinstance(now.get("model"), Mapping) else {}
    code: Mapping[str, Any] = now["code"] if isinstance(now.get("code"), Mapping) else {}
    record: dict[str, Any] = {
        "kind": VERIFICATION_KIND,
        "recorded_sha256": recorded.get("environment_sha256"),
        "now_sha256": now.get("environment_sha256"),
        "drift": verify(recorded, now),
        "digest_source": model.get("digest_source"),
        "clean": code.get("clean"),
        "verifier_id": verifier_id.strip(),
        "verified_at": verified_at,
    }
    record["record_sha256"] = _sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return record


def verification_problems(
    record: Mapping[str, Any] | None, environment_sha256: str | None
) -> list[str]:
    """Why `record` does not make an environment verified for an ACCEPTANCE score; empty when
    it does. Strict by default: a model digest only declared -- never measured -- does not
    qualify (SPEC-ISSUE-019, Owner decision E5)."""
    if record is None:
        return ["no independent environment verification (g0_eval_environment.py verify --out)"]
    problems: list[str] = []
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    digest = _sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if record.get("kind") != VERIFICATION_KIND:
        problems.append(f"not an environment verification ({VERIFICATION_KIND})")
    if digest != record.get("record_sha256"):
        problems.append("the verification does not hash to its own record_sha256")
    if environment_sha256 is None or record.get("recorded_sha256") != environment_sha256:
        problems.append("the verification is of another environment than the run's")
    if record.get("drift") != []:
        problems.append(
            "the verification found differences: " + "; ".join(record.get("drift") or ["?"])
        )
    if record.get("digest_source") != "served":
        problems.append("the model digest was only declared, not served by the model server")
    if record.get("clean") is not True:
        problems.append("the verified working tree was not clean")
    if not str(record.get("verifier_id") or "").strip():
        problems.append("the verification names no verifier")
    return problems


__all__ = [
    "ENVIRONMENT_KIND",
    "VERIFICATION_KIND",
    "EnvironmentRefused",
    "capture",
    "environment_hash",
    "schema_state",
    "served_model_digest",
    "settings_state",
    "verification_problems",
    "verification_record",
    "verify",
]
