"""The frozen independent-evaluation kit for the sealed hidden-world cases (composition root).

    python scripts/discovery_independent_kit.py verify [--archive ENC] [--quick]
    python scripts/discovery_independent_kit.py run --package P --sealed S --out DIR [--jobs N]
    python scripts/discovery_independent_kit.py score --package P --sealed S --out DIR [--jobs N]
    python scripts/discovery_independent_kit.py keygen --key K / sign --key K --out DIR /
                                                 verify-signature --out DIR
    python scripts/discovery_independent_kit.py dry-run [--check]      # the PUBLIC example only
    python scripts/discovery_independent_kit.py power [--check]
    python scripts/discovery_independent_kit.py pin-arm --arm-id B8 --commit SHA --entry M:F ...
    python scripts/discovery_independent_kit.py freeze                 # writes kit-manifest.json

WHO RUNS WHAT. The implementation side prepares and freezes this kit and runs it on the PUBLIC
example only (`dry-run`). The independent evaluator alone decrypts the sealed archive, on their own
machine, and runs `verify`, `run`, `score` and `sign` there (the runbook is in
`docs/evaluation/discovery-independent-evaluation-protocol.md` §12). Nothing here needs, reads or
prints hidden truth on the implementation side.

ONE RUN PER CASE AND ARM. Every pinned arm runs every case ONCE, at the plan's cap, in its own
fresh interpreter (`benchmarks/discovery_independent/kit/arm_worker.py`) loaded from a tree
materialized from the arm's pinned commit; the evaluator's process holds the world, the meter and
the hash-chained trace (`lab_brain.discovery_eval.independent`). The answer at every checkpoint of
the frozen ladder is derived from that one trace (`lab_brain.discovery_safety.independent`): no arm
gets a fresh run per checkpoint. (`dry-run` additionally runs fresh capped runs on the PUBLIC
example, to measure where a trace-derived answer differs from a fresh capped run.)

The one file that names the silicon-photonics scenario for the kit; `pyproject.toml` exempts it
from the §24.2 import ban, as for the other discovery composition roots.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import platform
import select
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from multiprocessing import Pool
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.core.canonical_json import canonical_hash  # noqa: E402
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery_eval import hidden_worlds as hw  # noqa: E402
from lab_brain.discovery_eval.blind import find_truth_leaks  # noqa: E402
from lab_brain.discovery_eval.independent import analysis  # noqa: E402
from lab_brain.discovery_eval.independent import trace as tr  # noqa: E402
from lab_brain.discovery_eval.independent.plan import PLAN  # noqa: E402
from lab_brain.discovery_eval.independent.service import CaseService, Lost  # noqa: E402
from lab_brain.discovery_safety.independent import checkpoint as cp  # noqa: E402
from lab_brain.discovery_safety.v12.grammar import grammar_from_declaration  # noqa: E402
from lab_brain.discovery_safety.v13.evaluation import all_experiments  # noqa: E402
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14  # noqa: E402
from lab_brain.domains.silicon_photonics import discovery_grammar  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)

KIT_DIR = ROOT / "benchmarks" / "discovery_independent" / "kit"
WORKER = KIT_DIR / "arm_worker.py"
REGISTRY = KIT_DIR / "arm-registry.json"
MANIFEST = KIT_DIR / "kit-manifest.json"
COMMITMENTS = KIT_DIR / "round5-commitments.json"
POWER = KIT_DIR / "power-analysis.json"
DRY = KIT_DIR / "dry-run"
EXAMPLE = ROOT / "benchmarks" / "discovery_independent" / "example.hidden-worlds.json"
GRAMMAR = grammar_from_declaration(discovery_grammar.declaration())

MANIFEST_KIND = "lab-brain/independent-eval-kit-manifest@1"
REGISTRY_KIND = "lab-brain/independent-eval-arm-registry@1"
RUN_SUMMARY_KIND = "lab-brain/independent-eval-run-summary@1"
RESULTS_KIND = "lab-brain/independent-eval-results@1"
SIGNATURE_NAMESPACE = b"lab-brain/independent-eval-results@1\x00"
EXAMPLE_SALT_DOMAIN = "lab-brain/independent-eval-kit/example-salt@1"

#: The sealed set this kit was frozen for (public facts only: hashes and the interface).
SEALED_SET = {
    "source_branch": "claude/lib-implementation-agent-47evs0-hidden-cases",
    "source_commit": "3d54297b26d5748d52e7aceb06d8021a4ffc18c8",
    "archive_path": "benchmarks/discovery_independent/sealed/round5-hidden-worlds.tar.gz.enc",
    "archive_sha256": "b23db527e50cf58f5e0a7d5a550b612fd8b0f4a274eaf6dbb5fa89693ca2fe83",
    "commitments_root": "sha256:839ac0110308102f990c1d2e9e5e246600c310f7adb71b59eeaf9c28db2dcf8b",
    "cases": 58,
}
KIT_SOURCES = (
    "scripts/discovery_independent_kit.py",
    "benchmarks/discovery_independent/kit/arm_worker.py",
    "benchmarks/discovery_independent/kit/arm-registry.json",
    "benchmarks/discovery_independent/kit/round5-commitments.json",
)
KIT_PACKAGES = (
    "src/lab_brain/discovery_eval/independent",
    "src/lab_brain/discovery_safety/independent",
)
DEPENDENCIES = ("pydantic", "pydantic-core", "PyYAML", "cryptography")


class KitRefused(SystemExit):
    """The kit refuses to continue (a hash mismatch, a wrong input)."""


# -- small helpers --------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _git(*args: str, binary: bool = False) -> Any:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8")


def interpreter_key() -> str:
    return f"{platform.python_implementation()} {sys.version_info.major}.{sys.version_info.minor}"


def environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for name in DEPENDENCIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "absent"
    return {"interpreter_key": interpreter_key(), "dependencies": versions}


def kit_sources() -> dict[str, str]:
    files = [ROOT / p for p in KIT_SOURCES]
    for package in KIT_PACKAGES:
        files.extend(sorted((ROOT / package).glob("*.py")))
    return {_rel(p): _sha256(p) for p in files}


def engine_sources() -> dict[str, str]:
    files = sorted((ROOT / "src" / "lab_brain" / "discovery").glob("*.py"))
    files.append(
        ROOT / "src" / "lab_brain" / "domains" / "silicon_photonics" / "discovery_catalog.py"
    )
    return {_rel(p): _sha256(p) for p in files}


def evaluator_closure() -> dict[str, str]:
    """Every `lab_brain` source file the evaluator's process imports (this script's closure),
    measured in a fresh interpreter."""
    code = (
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('kit', {str(Path(__file__).resolve())!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "print(json.dumps(sorted({v.__file__ for k, v in sys.modules.items()"
        " if k.startswith('lab_brain') and getattr(v, '__file__', None)})))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    files = [Path(p) for p in json.loads(out.stdout.strip().splitlines()[-1])]
    return {_rel(p): _sha256(p) for p in sorted(files)}


# -- the arm registry and arm trees ---------------------------------------------------------------


def registry() -> dict[str, Any]:
    data: dict[str, Any] = _load(REGISTRY)
    if data.get("kind") != REGISTRY_KIND:
        raise KitRefused(f"{_rel(REGISTRY)} is not a {REGISTRY_KIND}")
    return data


def filled_slots(reg: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(s) for s in reg["slots"] if s["status"] == "PINNED"]


def materialize(commit: str, src_tree: str, workdir: Path) -> Path:
    """The arm's tree: `git archive` of the pinned commit's `src`, refused if its tree id is not
    the pinned one or if it holds a link or anything but regular files and directories."""
    actual = _git("rev-parse", f"{commit}:src").strip()
    if actual != src_tree:
        raise KitRefused(f"{commit}:src is tree {actual}, not the pinned {src_tree}")
    target = workdir / "arms" / src_tree
    marker = target / ".materialized"
    if marker.exists():
        return target
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    blob = _git("archive", "--format=tar", commit, "src", binary=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
        for member in archive.getmembers():
            if not (member.isfile() or member.isdir()):
                raise KitRefused(f"the arm tree holds a non-regular entry {member.name}")
        archive.extractall(target, filter="data")
    marker.write_text(src_tree + "\n", encoding="utf-8")
    return target


def arm_closure(tree: Path, slot: Mapping[str, Any]) -> dict[str, str]:
    """The `lab_brain` files the arm process imports, relative to its tree, with their hashes."""
    context = slot["context"]
    refs = [slot["entry"], context["catalog"], context["oracle"], context["protocol"]]
    if context.get("grammar"):
        refs += [context["grammar"], context["grammar_builder"]]
    code = (
        "import importlib, json, os, sys\n"
        f"src = {str(tree / 'src')!r}\n"
        "sys.path.insert(0, src)\n"
        f"for ref in {refs!r}:\n"
        "    importlib.import_module(ref.partition(':')[0])\n"
        "print(json.dumps(sorted({os.path.relpath(v.__file__, os.path.dirname(src))"
        " for k, v in sys.modules.items() if k.startswith('lab_brain')"
        " and getattr(v, '__file__', None)})))\n"
    )
    out = subprocess.run(
        [sys.executable, "-s", "-B", "-P", "-c", code],
        cwd=tree,
        capture_output=True,
        text=True,
        check=True,
        env=_arm_env(),
    )
    files = json.loads(out.stdout.strip().splitlines()[-1])
    return {f: _sha256(tree / f) for f in files}


def _arm_env() -> dict[str, str]:
    return {"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"}


# -- the manifest and verify ----------------------------------------------------------------------


def commitments_check(path: Path) -> list[str]:
    problems = []
    data = _load(path)
    commitments = data.get("commitments", {})
    if canonical_hash(dict(commitments)) != data.get("root"):
        problems.append("the commitments file's commitments do not hash to its root")
    if data.get("root") != SEALED_SET["commitments_root"]:
        problems.append("the commitments root is not the pinned root")
    if len(commitments) != SEALED_SET["cases"] or data.get("cases") != SEALED_SET["cases"]:
        problems.append("the commitments file does not hold the pinned number of cases")
    return problems


def dry_run_files() -> dict[str, str]:
    return {_rel(p): _sha256(p) for p in sorted(DRY.rglob("*")) if p.is_file()}


def build_manifest(workdir: Path) -> dict[str, Any]:
    reg = registry()
    slots = []
    for slot in reg["slots"]:
        if slot["status"] == "PINNED":
            tree = materialize(slot["commit"], slot["src_tree"], workdir)
            if arm_closure(tree, slot) != slot["closure_sha256"]:
                raise KitRefused(f"slot {slot['arm_id']}: the registry's closure is stale")
        slots.append(slot)
    kit = kit_sources()
    engine = engine_sources()
    closure = evaluator_closure()
    return {
        "kind": MANIFEST_KIND,
        "kit_sources_sha256": kit,
        "kit_code_hash": canonical_hash(kit),
        "engine_sources_sha256": engine,
        "engine_hash": canonical_hash(engine),
        "evaluator_closure_sha256": closure,
        "evaluator_closure_hash": canonical_hash(closure),
        "hidden_world_format_sha256": {
            _rel(ROOT / p): _sha256(ROOT / p)
            for p in (
                "src/lab_brain/discovery_eval/hidden_worlds.py",
                "benchmarks/discovery_independent/hidden-worlds.schema.json",
            )
        },
        "arms": slots,
        "arm_registry_sha256": _sha256(REGISTRY),
        "plan": PLAN.as_json(),
        "plan_digest": PLAN.digest,
        "scoring": {
            "rule": PLAN.scoring,
            "evaluator_rule_v14_digest": EVALUATOR_RULE_V14.digest,
            "grammar_digest": GRAMMAR.digest,
            "catalog_ref": ring_catalog().ref,
            "catalog_digest": ring_catalog().digest,
            "protocol_digest": DISCOVERY.digest,
        },
        "sealed_set": {**SEALED_SET, "commitments_file_sha256": _sha256(COMMITMENTS)},
        "dry_run_sha256": dry_run_files(),
        "power_analysis_sha256": _sha256(POWER) if POWER.exists() else None,
        "environment": environment(),
    }


def freeze_id(manifest: Mapping[str, Any]) -> str:
    return canonical_hash(dict(manifest))


def archive_sha256(archive: Path | None) -> str:
    """The ciphertext's SHA-256: from a file, or streamed from the pinned git object (never
    written to disk, never decrypted)."""
    digest = hashlib.sha256()
    if archive is not None:
        with archive.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    spec = f"{SEALED_SET['source_commit']}:{SEALED_SET['archive_path']}"
    with subprocess.Popen(["git", "cat-file", "blob", spec], cwd=ROOT, stdout=subprocess.PIPE) as p:
        assert p.stdout is not None
        for chunk in iter(lambda: p.stdout.read(1 << 20), b""):  # type: ignore[union-attr]
            digest.update(chunk)
        if p.wait() != 0:
            raise KitRefused(f"cannot read {spec} from git; pass --archive")
    return digest.hexdigest()


def verify(workdir: Path, archive: Path | None = None, quick: bool = False) -> list[str]:
    """Every pinned hash recomputed; the list of mismatches (empty: the kit is the frozen one)."""
    problems: list[str] = []
    if not MANIFEST.exists():
        return ["no kit-manifest.json: the kit is not frozen"]
    frozen = _load(MANIFEST)
    if frozen.get("kind") != MANIFEST_KIND:
        return ["kit-manifest.json is not a kit manifest"]
    checks = {
        "kit sources": (kit_sources(), frozen["kit_sources_sha256"]),
        "engine sources": (engine_sources(), frozen["engine_sources_sha256"]),
        "hidden-world format": (
            {p: _sha256(ROOT / p) for p in frozen["hidden_world_format_sha256"]},
            frozen["hidden_world_format_sha256"],
        ),
        "dry-run outputs": (dry_run_files(), frozen["dry_run_sha256"]),
    }
    if not quick:
        checks["evaluator closure"] = (evaluator_closure(), frozen["evaluator_closure_sha256"])
    for name, (actual, expected) in checks.items():
        if actual != expected:
            changed = sorted(
                k for k in set(actual) | set(expected) if actual.get(k) != expected.get(k)
            )
            problems.append(f"{name} differ from the freeze: {changed[:8]}")
    if canonical_hash(frozen["kit_sources_sha256"]) != frozen["kit_code_hash"]:
        problems.append("the manifest's kit code hash does not match its own file list")
    if PLAN.digest != frozen["plan_digest"] or PLAN.as_json() != frozen["plan"]:
        problems.append("the analysis plan differs from the frozen plan")
    if EVALUATOR_RULE_V14.digest != frozen["scoring"]["evaluator_rule_v14_digest"]:
        problems.append("the evaluator rule differs from the frozen rule")
    if GRAMMAR.digest != frozen["scoring"]["grammar_digest"]:
        problems.append("the grammar differs from the frozen grammar")
    catalog = ring_catalog()
    if catalog.digest != frozen["scoring"]["catalog_digest"]:
        problems.append("the catalog differs from the frozen catalog")
    if _sha256(REGISTRY) != frozen["arm_registry_sha256"]:
        problems.append("the arm registry differs from the frozen registry")
    if frozen["sealed_set"] != {**SEALED_SET, "commitments_file_sha256": _sha256(COMMITMENTS)}:
        problems.append("the sealed-set pins differ from the freeze")
    problems.extend(commitments_check(COMMITMENTS))
    if frozen["environment"]["interpreter_key"] != interpreter_key():
        problems.append(
            f"interpreter {interpreter_key()} is not the frozen "
            f"{frozen['environment']['interpreter_key']}"
        )
    if (POWER.exists() and _sha256(POWER)) != frozen["power_analysis_sha256"]:
        problems.append("the power analysis differs from the freeze")
    if not quick:
        for slot in frozen["arms"]:
            if slot["status"] != "PINNED":
                continue
            try:
                tree = materialize(slot["commit"], slot["src_tree"], workdir)
                if arm_closure(tree, slot) != slot["closure_sha256"]:
                    problems.append(f"arm {slot['arm_id']}: its closure differs from the pin")
            except (KitRefused, subprocess.CalledProcessError) as exc:
                problems.append(f"arm {slot['arm_id']}: {exc}")
        try:
            if archive_sha256(archive) != SEALED_SET["archive_sha256"]:
                problems.append("the encrypted archive's SHA-256 is not the pinned one")
        except (KitRefused, OSError) as exc:
            problems.append(f"the encrypted archive could not be hashed: {exc}")
    return problems


# -- the arm process and one run ------------------------------------------------------------------


class _Lines:
    """Lines from the arm's stdout, with a deadline (the package reads no clock; this does)."""

    def __init__(self, process: subprocess.Popen[bytes], deadline: float) -> None:
        self.process = process
        self.deadline = deadline
        self.buffer = b""

    def __call__(self) -> dict[str, Any] | Lost:
        assert self.process.stdout is not None
        fd = self.process.stdout.fileno()
        while b"\n" not in self.buffer:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                return Lost("the run exceeded its wall-clock limit")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return Lost(f"the arm process ended (exit {self.process.poll()})")
            self.buffer += chunk
            if len(self.buffer) > 1 << 24:
                return Lost("the arm sent an over-long message")
        line, _, self.buffer = self.buffer.partition(b"\n")
        try:
            message = json.loads(line)
        except (UnicodeDecodeError, ValueError):
            return Lost("the arm sent something that is not JSON")
        if not isinstance(message, dict):
            return Lost("the arm sent something that is not one JSON object")
        return message


def _sender(process: subprocess.Popen[bytes]) -> Any:
    def send(message: Mapping[str, Any]) -> None:
        assert process.stdin is not None
        try:
            process.stdin.write(
                (json.dumps(dict(message), sort_keys=True, separators=(",", ":")) + "\n").encode()
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass  # the next receive reports the arm as gone

    return send


def run_one(
    *,
    world: hw.HiddenWorld,
    case_id: str,
    package_root: str,
    slot: Mapping[str, Any],
    tree: Path,
    budget: int,
    seconds: float,
    log_dir: Path | None,
    arm_uid: int | None = None,
    worker: Path = WORKER,
) -> tuple[tr.TraceEvent, ...]:
    """One arm on one case, once: a fresh arm process, the evaluator's service, the trace."""
    catalog = ring_catalog()
    experiments = all_experiments(catalog)
    available = world.available(catalog)
    service = CaseService(
        lab=hw.HiddenWorldLab(world, catalog, MOTIVATING_EXPERIMENT),
        experiments=experiments,
        available=available,
        cap=budget,
        arm_id=str(slot["arm_name"]),
        start={
            "case_id": case_id,
            "package_root": package_root,
            "slot": str(slot["arm_id"]),
            "commit": str(slot["commit"]),
            "src_tree": str(slot["src_tree"]),
            "entry": str(slot["entry"]),
        },
    )
    request = {
        "catalog_digest": catalog.digest,
        "available": list(available),
        "removed": [list(r) for r in world.removed],
        "budget": budget,
    }
    pin = {"entry": slot["entry"], "arm_name": slot["arm_name"], "context": slot["context"]}
    with tempfile.TemporaryDirectory(prefix="kit-arm-") as cwd:
        stderr_path = (log_dir / f"{case_id}.{slot['arm_id']}.{budget}.stderr") if log_dir else None
        stderr = stderr_path.open("wb") if stderr_path else subprocess.DEVNULL
        preexec = None
        if arm_uid is not None:

            def preexec() -> None:  # pragma: no cover - needs root
                os.setgid(arm_uid)
                os.setuid(arm_uid)

        process = subprocess.Popen(
            [
                sys.executable,
                "-s",
                "-B",
                "-P",
                str(worker),
                "--tree",
                str(tree),
                "--pin",
                json.dumps(pin, sort_keys=True),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            cwd=cwd,
            env=_arm_env(),
            preexec_fn=preexec,
        )
        try:
            events = service.serve(
                request, _sender(process), _Lines(process, time.monotonic() + seconds)
            )
        finally:
            if process.stdin is not None:
                with contextlib.suppress(OSError):
                    process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if stderr_path is not None and not isinstance(stderr, int):
                stderr.close()
    tr.verify_trace(events)
    return events


# -- the evaluator's phases -----------------------------------------------------------------------


def _example_salt(world_id: str) -> str:
    """Reproducible salts for the PUBLIC example only (a real set is sealed by its author)."""
    return hashlib.sha256(f"{EXAMPLE_SALT_DOMAIN}/{world_id}".encode()).hexdigest()


def load_inputs(
    package_path: Path, sealed_path: Path, *, example: bool
) -> tuple[hw.EnginePackage, hw.HiddenWorldSet]:
    """The engine package (checked against the pinned commitments unless this is the example) and
    the sealed worlds, verified against the package case by case BEFORE any arm runs: the
    laboratory serves only committed worlds."""
    catalog = ring_catalog()
    package_data = hw.load_document(package_path, repo=ROOT, allow_example=example)
    package = hw.parse_engine_package(package_data, catalog)
    if example != package.example_only:
        raise KitRefused("the example flag and the package's example_only disagree")
    if not example:
        pinned = _load(COMMITMENTS)
        if package.root != SEALED_SET["commitments_root"] or dict(package.commitments) != dict(
            pinned["commitments"]
        ):
            raise KitRefused("the engine package is not the committed sealed set")
    sealed_data = hw.load_document(sealed_path, repo=ROOT, allow_example=example)
    worlds = hw.reveal(sealed_data, package, catalog, DISCOVERY)
    return package, worlds


def run_phase(
    package: hw.EnginePackage,
    worlds: hw.HiddenWorldSet,
    out: Path,
    workdir: Path,
    jobs: int,
    *,
    freeze: str,
    slots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """T5: every filled arm on every case, once, at the cap. Writes traces and the run summary;
    prints and stores no truth."""
    by_case = {str(w.case_id): w for w in worlds.worlds}
    trees = {s["arm_id"]: materialize(s["commit"], s["src_tree"], workdir) for s in slots}
    logs = workdir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    tasks = [(c.case_id, s) for c in package.cases for s in slots]

    def task(item: tuple[str, Mapping[str, Any]]) -> tuple[str, str, tuple[tr.TraceEvent, ...]]:
        case_id, slot = item
        events = run_one(
            world=by_case[case_id],
            case_id=case_id,
            package_root=package.root,
            slot=slot,
            tree=trees[slot["arm_id"]],
            budget=PLAN.cap,
            seconds=PLAN.run_seconds,
            log_dir=logs,
        )
        return case_id, str(slot["arm_id"]), events

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(task, tasks))
    runs: dict[str, dict[str, Any]] = {}
    for case_id, arm, events in results:
        path = out / "traces" / case_id / f"{arm}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = tr.dumps(events)
        path.write_text(text, encoding="utf-8")
        runs.setdefault(case_id, {})[arm] = {
            "status": tr.status(events),
            "charge": int(events[-1].body["charge"]),
            "events": len(events),
            "head": events[-1].chain,
            "trace_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    summary = {
        "kind": RUN_SUMMARY_KIND,
        "kit_freeze_id": freeze,
        "package_root": package.root,
        "example_only": package.example_only,
        "cap": PLAN.cap,
        "arms": [s["arm_id"] for s in slots],
        "runs": dict(sorted(runs.items())),
    }
    (out / "run-summary.json").write_text(_dump(summary), encoding="utf-8")
    return summary


_SCORE: dict[str, Any] = {}


def _score_case(case_id: str) -> tuple[str, str, list[dict[str, Any]]]:
    worlds: hw.HiddenWorldSet = _SCORE["worlds"]
    out: Path = _SCORE["out"]
    summary = _SCORE["summary"]
    world = next(w for w in worlds.worlds if w.case_id == case_id)
    catalog = ring_catalog()
    scorer = cp.world_scorer(world, catalog, DISCOVERY, GRAMMAR)
    needles = {world.world_id, str(world.salt)} | {
        str(e.effect_id) for e in world.effects if e.effect_id is not None
    }
    rows = []
    for arm in summary["arms"]:
        recorded = summary["runs"].get(case_id, {}).get(arm)
        path = out / "traces" / case_id / f"{arm}.jsonl"
        if recorded is None or not path.exists():
            arm_rows = [cp._deficient(c, "MISSING", "no trace", None) for c in PLAN.ladder]
        else:
            try:
                events = tr.loads(path.read_text(encoding="utf-8"))
            except (ValueError, KeyError) as exc:
                events = ()
                arm_rows = [cp._deficient(c, cp.TAMPERED, str(exc), None) for c in PLAN.ladder]
            if events:
                arm_rows = cp.score_trace(scorer, events, PLAN.ladder, recorded["head"])
                said = [
                    {"answer": e.body.get("answer"), "identity": e.body.get("identity")}
                    for e in events
                    if e.kind in (tr.DECLARE, tr.REGISTER)
                ]
                leaks = find_truth_leaks(said, needles)
                if leaks:
                    arm_rows = [
                        cp._deficient(
                            c,
                            "LEAK",
                            f"truth strings in the arm's output: {leaks[:3]}",
                            recorded["charge"],
                        )
                        for c in PLAN.ladder
                    ]
        for row in arm_rows:
            rows.append({"case_id": case_id, "arm": arm, "world_category": world.category, **row})
    return case_id, world.category, rows


def score_phase(
    package: hw.EnginePackage,
    worlds: hw.HiddenWorldSet,
    out: Path,
    jobs: int,
    *,
    freeze: str,
) -> dict[str, Any]:
    """T6-T7: after the run summary exists, the reveal (already verified) and the scoring of every
    trace at every checkpoint, then the pre-registered analysis."""
    summary = _load(out / "run-summary.json")
    if summary.get("kind") != RUN_SUMMARY_KIND or summary["package_root"] != package.root:
        raise KitRefused("the run summary was not produced against this package")
    if summary["kit_freeze_id"] != freeze:
        raise KitRefused("the run was made with another kit freeze")
    _SCORE.update(worlds=worlds, out=out, summary=summary)
    cases = [c.case_id for c in package.cases]
    if jobs > 1:
        with Pool(jobs) as pool:
            scored = pool.map(_score_case, cases)
    else:
        scored = [_score_case(c) for c in cases]
    rows = [r for _, _, case_rows in scored for r in case_rows]
    categories = {case_id: category for case_id, category, _ in scored}
    result = analysis.analyse(rows, PLAN, summary["arms"], categories)
    rows_text = "[\n" + ",\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n]\n"
    results = {
        "kind": RESULTS_KIND,
        "kit_freeze_id": freeze,
        "package_root": package.root,
        "example_only": package.example_only,
        "reveal_verified": True,
        "run_summary_sha256": _sha256(out / "run-summary.json"),
        "per_category_cases": {
            c: sum(1 for v in categories.values() if v == c) for c in hw.CATEGORIES
        },
        "analysis": result,
    }
    (out / "rows.json").write_text(rows_text, encoding="utf-8")
    (out / "results.json").write_text(_dump(results), encoding="utf-8")
    digest = {
        "kind": "lab-brain/independent-eval-results-digest@1",
        "kit_freeze_id": freeze,
        "package_root": package.root,
        "files_sha256": {
            p.relative_to(out).as_posix(): _sha256(p)
            for p in sorted(out.rglob("*"))
            if p.is_file() and p.name not in ("results-digest.json", "results-digest.sig")
        },
    }
    (out / "results-digest.json").write_text(_dump(digest), encoding="utf-8")
    return results


# -- signing --------------------------------------------------------------------------------------


def keygen(key: Path) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(key, 0o600)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(public).decode()


def sign(key: Path, out: Path) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = serialization.load_pem_private_key(key.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise KitRefused("the signing key is not an Ed25519 key")
    message = SIGNATURE_NAMESPACE + (out / "results-digest.json").read_bytes()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    record = {
        "algorithm": "Ed25519",
        "namespace": SIGNATURE_NAMESPACE.decode().rstrip("\x00"),
        "public_key": base64.b64encode(public).decode(),
        "signature": base64.b64encode(private.sign(message)).decode(),
    }
    (out / "results-digest.sig").write_text(_dump(record), encoding="utf-8")
    return record["public_key"]


def verify_signature(out: Path, public_key: str | None) -> list[str]:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    problems = []
    record = _load(out / "results-digest.sig")
    if public_key is not None and record["public_key"] != public_key:
        problems.append("the signature's key is not the evaluator's published key")
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(record["public_key"]))
    message = SIGNATURE_NAMESPACE + (out / "results-digest.json").read_bytes()
    try:
        key.verify(base64.b64decode(record["signature"]), message)
    except InvalidSignature:
        problems.append("the signature does not verify")
    digest = _load(out / "results-digest.json")
    for name, expected in digest["files_sha256"].items():
        path = out / name
        if not path.exists() or _sha256(path) != expected:
            problems.append(f"{name} differs from the signed digest")
    return problems


# -- the dry run on the PUBLIC example ------------------------------------------------------------


def _equivalence(
    worlds: hw.HiddenWorldSet,
    package: hw.EnginePackage,
    slots: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    workdir: Path,
    jobs: int,
) -> dict[str, Any]:
    """For every case, arm and checkpoint c of the ladder: the answer derived from the single
    trace at c against the answer of a FRESH run capped at c (public example only)."""
    catalog = ring_catalog()
    by_case = {str(w.case_id): w for w in worlds.worlds}
    trees = {s["arm_id"]: materialize(s["commit"], s["src_tree"], workdir) for s in slots}
    tasks = [(c.case_id, s, k) for c in package.cases for s in slots for k in PLAN.ladder]

    def task(item: tuple[str, Mapping[str, Any], int]) -> tuple[str, str, int, Any]:
        case_id, slot, budget = item
        events = run_one(
            world=by_case[case_id],
            case_id=case_id,
            package_root=package.root,
            slot=slot,
            tree=trees[slot["arm_id"]],
            budget=budget,
            seconds=PLAN.run_seconds,
            log_dir=None,
        )
        return case_id, str(slot["arm_id"]), budget, events

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        fresh = list(pool.map(task, tasks))
    derived = {(r["case_id"], r["arm"], r["checkpoint"]): r for r in rows}
    cells = []
    for case_id, arm, budget, events in fresh:
        scorer = cp.world_scorer(by_case[case_id], catalog, DISCOVERY, GRAMMAR)
        fresh_row = cp.score_trace(scorer, events, (budget,), events[-1].chain)[0]
        mine = derived[(case_id, arm, budget)]
        same_answer = all(
            mine[k] == fresh_row[k] for k in ("answer_kind", "outcome", "claim", "new_mechanism")
        )
        if same_answer and mine["category"] == fresh_row["category"]:
            kind = "EQUAL"
        elif mine["held"] == "NONE" and fresh_row["answer_kind"] != "NONE":
            kind = "TRACE_HOLDS_NO_ANSWER_YET"
        elif same_answer:
            kind = "SAME_ANSWER_OTHER_EVIDENCE"
        else:
            kind = "DIFFERENT_ANSWER"
        cells.append(
            {
                "case_id": case_id,
                "arm": arm,
                "checkpoint": budget,
                "kind": kind,
                "trace": {k: mine[k] for k in ("held", "charge_at_answer", "category", "claim")},
                "fresh": {
                    "spent": fresh_row["spent_total"],
                    "category": fresh_row["category"],
                    "claim": fresh_row["claim"],
                },
                "fresh_category_credited": fresh_row["credited"],
                "trace_category_credited": mine["credited"],
            }
        )
    cells.sort(key=lambda c: (c["arm"], c["case_id"], c["checkpoint"]))
    counts: dict[str, dict[str, int]] = {}
    for c in cells:
        mine_counts = counts.setdefault(c["arm"], {})
        mine_counts[c["kind"]] = mine_counts.get(c["kind"], 0) + 1
    credited = {
        arm: {
            "trace_derived": sum(
                1 for c in cells if c["arm"] == arm and c["trace_category_credited"]
            ),
            "fresh_capped": sum(
                1 for c in cells if c["arm"] == arm and c["fresh_category_credited"]
            ),
        }
        for arm in sorted(counts)
    }
    return {
        "what": "trace-derived answer at checkpoint c vs a fresh run capped at c, PUBLIC example "
        "only; the sealed run never makes fresh capped runs",
        "counts": dict(sorted((k, dict(sorted(v.items()))) for k, v in counts.items())),
        "credited_cells": credited,
        "cells": cells,
    }


def dry_run(workdir: Path, jobs: int, check: bool) -> int:
    """seal -> blind run of every pinned arm -> reveal -> score at every checkpoint, on the PUBLIC
    example; plus the trace-vs-fresh study. `--check` regenerates into a temporary directory and
    compares every file byte for byte with the committed ones."""
    catalog = ring_catalog()
    data = hw.load_document(EXAMPLE, repo=ROOT, allow_example=True)
    sealed, package_data = hw.seal(
        hw.parse_hidden_worlds(data, catalog, DISCOVERY), salts=_example_salt
    )
    slots = filled_slots(registry())
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="kit-dry-") as tmp:
        out = Path(tmp) / "dry-run"
        out.mkdir()
        (out / "example.sealed.json").write_text(_dump(sealed), encoding="utf-8")
        (out / "example.engine-package.json").write_text(_dump(package_data), encoding="utf-8")
        package, worlds = load_inputs(
            out / "example.engine-package.json", out / "example.sealed.json", example=True
        )
        freeze = "dry-run:not-a-freeze"
        run_phase(package, worlds, out, workdir, jobs, freeze=freeze, slots=slots)
        score_phase(package, worlds, out, jobs, freeze=freeze)
        rows = json.loads((out / "rows.json").read_text(encoding="utf-8"))
        study = _equivalence(worlds, package, slots, rows, workdir, jobs)
        (out / "equivalence.json").write_text(_dump(study), encoding="utf-8")
        # the results digest names every file; regenerate it with the study included
        digest = _load(out / "results-digest.json")
        digest["files_sha256"]["equivalence.json"] = _sha256(out / "equivalence.json")
        (out / "results-digest.json").write_text(_dump(digest), encoding="utf-8")
        produced = {
            p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()
        }
        elapsed = time.monotonic() - started
        if check:
            committed = {
                p.relative_to(DRY).as_posix(): p.read_bytes() for p in DRY.rglob("*") if p.is_file()
            }
            stale = sorted(
                k for k in set(produced) | set(committed) if produced.get(k) != committed.get(k)
            )
            print(
                f"dry run reproduced in {elapsed:.0f} s: "
                + ("STALE: " + ", ".join(stale[:10]) if stale else "every file byte-identical")
            )
            return 1 if stale else 0
        if DRY.exists():
            shutil.rmtree(DRY)
        shutil.copytree(out, DRY)
    print(f"dry run written to {_rel(DRY)} in {elapsed:.0f} s ({len(produced)} files)")
    return 0


# -- power ----------------------------------------------------------------------------------------


def power_table() -> dict[str, Any]:
    ns = (20, 29, 40, 58)
    discordances = (0.1, 0.2, 0.3, 0.4, 0.5)
    analytic = {
        str(n): {
            format(d, ".1f"): round(analysis.minimum_detectable_difference(n, d), 4)
            for d in discordances
        }
        for n in ns
    }
    checks = []
    for n, d in ((58, 0.2), (58, 0.4), (29, 0.3)):
        mdd = analysis.minimum_detectable_difference(n, d)
        checks.append(
            {
                "n": n,
                "discordance": d,
                "difference": round(mdd, 4),
                "simulated_power": analysis.simulated_power(
                    n, d, mdd, simulations=300, resamples=1000, seed=PLAN.bootstrap_seed
                ),
            }
        )
    non_inferiority = []
    for n in (40, 58):
        for extra in (0, 1, 2, 3):
            diffs = [1.0] * extra + [0.0] * (n - extra)
            interval = analysis.percentile_interval(
                diffs,
                resamples=PLAN.bootstrap_resamples,
                seed=PLAN.bootstrap_seed,
                label="non-inferiority",
                confidence=PLAN.confidence,
            )
            non_inferiority.append(
                {
                    "n": n,
                    "candidate_only_errors": extra,
                    "baseline_only_errors": 0,
                    "upper_bound": interval["hi"],
                    "meets_margin": interval["hi"] <= PLAN.non_inferiority_margin,
                }
            )
    zero = {str(n): analysis.wilson(0, n) for n in (20, 29, 40, 58)}
    return {
        "non_inferiority_at_margin": non_inferiority,
        "wilson95_for_zero_events": zero,
        "what": "minimum detectable paired difference (80 % power, two-sided 5 %) for a binary "
        "per-case indicator, by the normal approximation d = k sqrt(D / (n + k^2)), k = z_0.975 + "
        "z_0.80, D = the share of discordant cases; checked by simulation of the plan's paired "
        "percentile bootstrap (300 studies, 1000 resamples each)",
        "n_note": "58 = every case; 20-40 = plausible numbers of expressible (primary) cases, "
        "which are not published before the reveal",
        "analytic_mdd": analytic,
        "simulation_checks": checks,
    }


def power(check: bool) -> int:
    text = _dump(power_table())
    if check:
        same = POWER.exists() and POWER.read_text(encoding="utf-8") == text
        print("power analysis is current" if same else "STALE: power-analysis.json")
        return 0 if same else 1
    POWER.write_text(text, encoding="utf-8")
    print(f"wrote {_rel(POWER)}")
    return 0


# -- pinning an arm (fills a registry slot; no code change) ---------------------------------------


def pin_arm(args: argparse.Namespace, workdir: Path) -> int:
    reg = registry()
    slot = next((s for s in reg["slots"] if s["arm_id"] == args.arm_id), None)
    if slot is None:
        raise KitRefused(f"no slot {args.arm_id} in the registry")
    commit = _git("rev-parse", "--verify", f"{args.commit}^{{commit}}").strip()
    src_tree = _git("rev-parse", f"{commit}:src").strip()
    context = dict(slot.get("context") or reg["default_context"])
    filled = {
        **slot,
        "status": "PINNED",
        "commit": commit,
        "src_tree": src_tree,
        "entry": args.entry,
        "arm_name": args.arm_name or args.arm_id,
        "context": context,
    }
    tree = materialize(commit, src_tree, workdir)
    filled["closure_sha256"] = arm_closure(tree, filled)
    reg["slots"] = [filled if s["arm_id"] == args.arm_id else s for s in reg["slots"]]
    REGISTRY.write_text(_dump(reg), encoding="utf-8")
    print(f"pinned {args.arm_id} at {commit} (src tree {src_tree}); re-freeze before any run")
    return 0


# -- main -----------------------------------------------------------------------------------------


def _frozen_or_refuse(workdir: Path, archive: Path | None) -> str:
    problems = verify(workdir, archive)
    if problems:
        for p in problems:
            print(f"MISMATCH: {p}", file=sys.stderr)
        raise KitRefused("verify failed: the kit is not the frozen kit; refusing to run")
    return freeze_id(_load(MANIFEST))


def main(argv: list[str] | None = None) -> int:
    if argv is None and os.environ.get("PYTHONHASHSEED") != "0":
        # every evaluator-side number must not depend on string hashing: re-run with a fixed seed
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        os.execve(
            sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env
        )
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--archive", type=Path)
    v.add_argument("--quick", action="store_true", help="skip arm trees, closure and archive")
    for name in ("run", "score"):
        p = sub.add_parser(name)
        p.add_argument("--package", type=Path, required=True)
        p.add_argument("--sealed", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--archive", type=Path)
        p.add_argument("--jobs", type=int, default=4)
    k = sub.add_parser("keygen")
    k.add_argument("--key", type=Path, required=True)
    s = sub.add_parser("sign")
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    vs = sub.add_parser("verify-signature")
    vs.add_argument("--out", type=Path, required=True)
    vs.add_argument("--public-key")
    d = sub.add_parser("dry-run")
    d.add_argument("--check", action="store_true")
    d.add_argument("--jobs", type=int, default=4)
    pw = sub.add_parser("power")
    pw.add_argument("--check", action="store_true")
    pa = sub.add_parser("pin-arm")
    pa.add_argument("--arm-id", required=True)
    pa.add_argument("--commit", required=True)
    pa.add_argument("--entry", required=True)
    pa.add_argument("--arm-name")
    sub.add_parser("freeze")
    parser.add_argument(
        "--workdir", type=Path, default=Path(tempfile.gettempdir()) / "lab-brain-kit"
    )
    args = parser.parse_args(argv)
    workdir: Path = args.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    if args.command == "verify":
        problems = verify(workdir, args.archive, args.quick)
        for problem in problems:
            print(f"MISMATCH: {problem}")
        if not problems:
            print(f"verify: OK; kit freeze id {freeze_id(_load(MANIFEST))}")
        return 1 if problems else 0
    if args.command in ("run", "score"):
        freeze = _frozen_or_refuse(workdir, args.archive)
        package, worlds = load_inputs(args.package, args.sealed, example=False)
        args.out.mkdir(parents=True, exist_ok=True)
        slots = [s for s in _load(MANIFEST)["arms"] if s["status"] == "PINNED"]
        if args.command == "run":
            if (args.out / "run-summary.json").exists():
                raise KitRefused("this output directory already holds a run; a run is made once")
            summary = run_phase(
                package, worlds, args.out, workdir, args.jobs, freeze=freeze, slots=slots
            )
            print(
                f"run complete: {sum(len(v) for v in summary['runs'].values())} runs; publish "
                f"run-summary.json sha256 {_sha256(args.out / 'run-summary.json')} before scoring"
            )
        else:
            results = score_phase(package, worlds, args.out, args.jobs, freeze=freeze)
            print(f"scored; decision {results['analysis']['decision']}; sign results-digest.json")
        return 0
    if args.command == "keygen":
        print(f"public key (publish it): {keygen(args.key)}")
        return 0
    if args.command == "sign":
        print(f"signed with public key {sign(args.key, args.out)}")
        return 0
    if args.command == "verify-signature":
        problems = verify_signature(args.out, args.public_key)
        for problem in problems:
            print(f"MISMATCH: {problem}")
        print("signature and files verify" if not problems else "signature check FAILED")
        return 1 if problems else 0
    if args.command == "dry-run":
        return dry_run(workdir, args.jobs, args.check)
    if args.command == "power":
        return power(args.check)
    if args.command == "pin-arm":
        return pin_arm(args, workdir)
    if args.command == "freeze":
        manifest = build_manifest(workdir)
        MANIFEST.write_text(_dump(manifest), encoding="utf-8")
        print(f"wrote {_rel(MANIFEST)}; freeze id {freeze_id(manifest)}")
        return 0
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
