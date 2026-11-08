"""Evaluate safety v1.2 (arm B5) beside v1.1 (B4), v1.0 (B3) and the frozen engine (B2).

    python scripts/discovery_safety_v12_eval.py --dev BASE PER [--budgets 8,12]   # development
    python scripts/discovery_safety_v12_eval.py --design-freeze SHA               # write evidence
    python scripts/discovery_safety_v12_eval.py --check [--record-interpreter]    # refuse drift

Offline and zero-cost: no model, simulator, network or database; Discovery is not connected to real
research execution. The engine, the 2026-11-02 evaluation tooling, and the v1.0 and v1.1 safety
packages are used exactly as frozen (their source hashes are checked against their manifests
first).

    design freeze   `--design-freeze SHA` refuses unless the v1.2 package, the ring scenario's term
                    grammar and this script are byte-identical to that commit, and the protocol and
                    plan digests computed there are today's
    held-out        NEW worlds on `PLAN.held_out` (derived from a fixed string, generated only after
                    the freeze): the family REMOVED (all arms) and LEFT IN (control); the benchmark
                    world kinds on `PLAN.benchmark_worlds`
    development     `--dev BASE PER` runs development held-out worlds only (base seeds declared in
                    `PLAN.development`) and writes nothing to the evidence

SCORING. SAI 3.5 candidate.4: category and evidential level, re-derived by the evaluator from the
ledger of each run (`lab_brain.discovery_safety.v12.evaluation`). The arms' own answers are also
reported at face value. The interpreter policy is v1.1's: the hashed body holds no interpreter
detail, `--check` needs every file byte-identical and the interpreter recorded as verified.

WHAT THE NUMBERS ARE. ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds. Not
scientific validity, not an independent evaluation, nothing about a real device. Scientific
acceptance and G-D: NOT PASSED.

The composition root that names the silicon-photonics scenario and its grammar; `pyproject.toml`
exempts this single file from the §24.2 import ban.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from importlib import metadata
from multiprocessing import Pool
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.model import stable_digest, to_jsonable  # noqa: E402
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery_eval import held_out  # noqa: E402
from lab_brain.discovery_safety.model import SAFETY  # noqa: E402
from lab_brain.discovery_safety.v11.model import SAFETY_V11  # noqa: E402
from lab_brain.discovery_safety.v12 import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.v12.grammar import grammar_from_declaration  # noqa: E402
from lab_brain.discovery_safety.v12.model import PLAN, SAFETY_V12  # noqa: E402
from lab_brain.domains.silicon_photonics import discovery_grammar  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_catalog,
    ring_scenario,
)

DEFAULT_OUT = ROOT / "docs" / "audit" / "discovery-safety-v1.2-2026-11-08" / "evidence"
AUDIT = ROOT / "docs" / "audit"
FROZEN_ENGINE = AUDIT / "discovery-loop-offline-2026-11-01" / "evidence"
FROZEN_EVAL = AUDIT / "discovery-independent-evaluation-2026-11-02" / "evidence"
FROZEN_V10 = AUDIT / "discovery-unknown-mechanism-safety-2026-11-04" / "evidence"
FROZEN_V11 = AUDIT / "discovery-safety-v1.1-2026-11-04" / "evidence"
V12_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_safety" / "v12"
GRAMMAR_FILE = ROOT / "src" / "lab_brain" / "domains" / "silicon_photonics" / "discovery_grammar.py"
INTERPRETERS_FILE = "interpreter_verification.json"
DEPENDENCIES = ("pydantic", "pydantic-core", "PyYAML", "cryptography")
GRAMMAR = grammar_from_declaration(discovery_grammar.declaration())


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _commit() -> str:
    try:
        head = _git("rev-parse", "HEAD").strip()
        dirty = _git("status", "--porcelain", "--", "src", "scripts").strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{'+dirty' if dirty else ''}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _dump_rows(rows: list[dict[str, Any]]) -> str:
    return (
        "[\n"
        + ",\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
        + "\n]\n"
    )


def interpreter_key() -> str:
    return f"{platform.python_implementation()} {sys.version_info.major}.{sys.version_info.minor}"


def environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for name in DEPENDENCIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "absent"
    return {
        "interpreter": f"{platform.python_implementation()} {platform.python_version()}",
        "interpreter_key": interpreter_key(),
        "platform": platform.platform(),
        "dependencies": versions,
        "numerical_libraries": "none (no numpy, scipy or other compiled numerics are imported)",
    }


def v12_sources() -> dict[str, str]:
    files = [*sorted(V12_PACKAGE.glob("*.py")), GRAMMAR_FILE, Path(__file__).resolve()]
    return {_rel(p): _sha256(p) for p in files}


def frozen_inputs(scenario: benchmark.Scenario) -> dict[str, Any]:
    engine = _load(FROZEN_ENGINE / "manifest.json")
    evaluation = _load(FROZEN_EVAL / "manifest.json")
    v10 = _load(FROZEN_V10 / "manifest.json")
    v11 = _load(FROZEN_V11 / "manifest.json")
    out = {
        "engine_sources_match_frozen_manifest": benchmark.source_hashes(scenario, ROOT)
        == engine["sources_sha256"],
        "evaluation_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in evaluation["evaluation_sources_sha256"]
        }
        == evaluation["evaluation_sources_sha256"],
        "v10_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in v10["safety_sources_sha256"]
        }
        == v10["safety_sources_sha256"],
        "v11_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in v11["v11_sources_sha256"] if not r.startswith("scripts/")
        }
        == {k: v for k, v in v11["v11_sources_sha256"].items() if not k.startswith("scripts/")},
        "v10_protocol_digest_matches": v10["inputs"]["safety_protocol_digest"] == SAFETY.digest,
        "v11_protocol_digest_matches": v11["inputs"]["safety_protocol_digest"] == SAFETY_V11.digest,
        "frozen_engine_manifest_sha256": engine["manifest_sha256"],
        "frozen_evaluation_manifest_sha256": evaluation["manifest_sha256"],
        "frozen_v10_manifest_sha256": v10["manifest_sha256"],
        "frozen_v11_manifest_sha256": v11["manifest_sha256"],
    }
    if not all(v for k, v in out.items() if k.endswith(("_manifest", "_matches"))):
        raise SystemExit(f"a frozen input drifted; refusing to continue: {out}")
    return out


def design_freeze(commit: str) -> dict[str, Any]:
    try:
        resolved = _git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        listed = _git("ls-tree", "--name-only", resolved, _rel(V12_PACKAGE) + "/").split()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot read the design-freeze commit {commit}: {exc}") from exc
    at_freeze = {}
    for relative in [
        *sorted(p for p in listed if p.endswith(".py")),
        _rel(GRAMMAR_FILE),
        _rel(Path(__file__)),
    ]:
        blob = subprocess.run(
            ["git", "show", f"{resolved}:{relative}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        at_freeze[relative] = hashlib.sha256(blob).hexdigest()
    if at_freeze != v12_sources():
        raise SystemExit(
            "the v1.2 sources differ from the design-freeze commit; the evaluation would not be of "
            "the frozen design"
        )
    return {
        "commit": resolved,
        "v12_sources_identical_to_freeze": True,
        "protocol_digest": SAFETY_V12.digest,
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "held_out_seeds_generated_after_freeze": True,
    }


# -- running (one world per task, so worlds run in parallel and merge in a fixed order) ------


def _held_out_task(args: tuple[int, int, int, bool, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, removed, budgets = args
    catalog = ring_catalog()
    worlds = held_out.held_out_worlds(
        catalog, seeds_per_class=per, base_seed=base, protocol=DISCOVERY
    )
    return ev.held_out_records(
        catalog,
        worlds[index],
        budgets=budgets,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        grammar=GRAMMAR,
        family_removed=removed,
    )


def _benchmark_task(args: tuple[int, int, int, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, budgets = args
    scenario = ring_scenario(per, base_seed=base)
    oracles = benchmark.Oracles(scenario.catalog, DISCOVERY)
    return ev.benchmark_records(
        scenario, scenario.worlds[index], budgets=budgets, grammar=GRAMMAR, oracles=oracles
    )


def _map(fn: Any, tasks: list[Any], jobs: int) -> list[ev.RunRecord]:
    if jobs <= 1:
        return [r for t in tasks for r in fn(t)]
    with Pool(jobs) as pool:
        return [r for rs in pool.map(fn, tasks, chunksize=1) for r in rs]


def held_out_set(
    log: list[str], base: int, per: int, budgets: tuple[int, ...], jobs: int, role: str
) -> tuple[dict[str, Any], dict[str, str]]:
    worlds = held_out.held_out_worlds(
        ring_catalog(), seeds_per_class=per, base_seed=base, protocol=DISCOVERY
    )
    out: dict[str, Any] = {
        "role": role,
        "base_seed": base,
        "seeds_per_class": per,
        "worlds": len(worlds),
        "worlds_primary": sum(1 for w in worlds if not w.aliased),
        "worlds_aliased": sum(1 for w in worlds if w.aliased),
        "specs_digest": stable_digest(worlds),
    }
    files: dict[str, str] = {}
    for removed, name in ((True, "held_out"), (False, "control")):
        tasks = [(base, per, i, removed, budgets) for i in range(len(worlds))]
        records = _map(_held_out_task, tasks, jobs)
        summary = ev.summarize(records, budgets)
        out[name] = {
            "setting": "true family REMOVED from the engine's catalog"
            if removed
            else "the same worlds with the family LEFT IN the catalog",
            "by_budget": summary,
            "checkpoints": ev.checkpoints(records, budgets, PLAN.checkpoints),
            "budget_never_exceeded": all(r.spent <= r.budget for r in records),
        }
        files[f"{name}_{base}_rows.json"] = _dump_rows(ev.records_as_json(records))
        _log(log, f"{role} {name} {base}", summary, budgets, "primary" if removed else "all")
        _errors(log, records)
    return out, files


def benchmark_set(
    log: list[str], base: int, per: int, budgets: tuple[int, ...], jobs: int, role: str
) -> tuple[dict[str, Any], dict[str, str]]:
    scenario = ring_scenario(per, base_seed=base)
    tasks = [(base, per, i, budgets) for i in range(len(scenario.worlds))]
    records = _map(_benchmark_task, tasks, jobs)
    summary = ev.summarize(records, budgets)
    _log(log, f"{role} benchmark {base}", summary, budgets, "all")
    _errors(log, records)
    out = {
        "role": role,
        "base_seed": base,
        "seeds_per_kind": per,
        "worlds": len(scenario.worlds),
        "specs_digest": stable_digest(scenario.worlds),
        "by_budget": summary,
        "per_kind": {
            kind: ev.summarize([r for r in records if r.kind == kind], budgets)
            for kind in sorted({r.kind for r in records})
        },
        "checkpoints": ev.checkpoints(records, budgets, PLAN.checkpoints),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
    }
    return out, {f"benchmark_{base}_rows.json": _dump_rows(ev.records_as_json(records))}


def _errors(log: list[str], records: list[ev.RunRecord]) -> None:
    """Every SUPPORTED error of B5 (for development inspection and the run log)."""
    for r in records:
        if r.arm == "B5" and r.category in (ev.FORCE_FIT, ev.WRONG_CLAIM):
            log.append(
                f"  B5 {r.category} {r.setting} {r.world_id} b{r.budget}: {r.answer} "
                f"{list(r.claim)} ({r.outcome})"
            )


def _log(log: list[str], label: str, summary: dict[str, Any], budgets: Any, part: str) -> None:
    short = {
        "EXACT_IDENTIFICATION": "exact",
        "INDISTINGUISHABLE_ALTERNATIVE": "indist",
        "VALIDATED_NEW_MECHANISM": "validated-new",
        "PROPOSAL_ONLY": "proposal-only",
        "CORRECT_ABSTENTION": "abstain-ok",
        "FALSE_NULL": "false-null",
        "FORCE_FIT": "force-fit",
        "WRONG_CLAIM": "wrong",
    }
    for budget in budgets:
        for arm in ev.ARM_IDS:
            t = summary[str(budget)][arm][part]
            cats = " ".join(f"{short[c]} {t['sai'][c]['k']}" for c in ev.SAI_CATEGORIES)
            own = t["own_answer"]
            log.append(
                f"{label} b{budget} {arm} n={t['n']}: {cats} | own: correct "
                f"{own['CORRECT_IDENTIFICATION']} force-fit {own['FORCE_FIT']} | answers "
                f"{t['answers']} supported {t['answers_supported']} | grammar proposals "
                f"{t['grammar_proposals']} (hits {t['grammar_proposal_hits']}) | cost "
                f"{t['realized_cost'].get('mean')}"
            )


def build(log: list[str], freeze: dict[str, Any], jobs: int) -> dict[str, str]:
    started = time.monotonic()
    scenario = ring_scenario(1, base_seed=1)
    tooling = frozen_inputs(scenario)
    files: dict[str, str] = {}
    results: dict[str, Any] = {}
    for seeds in PLAN.held_out:
        results[f"held_out_{seeds.base_seed}"], extra = held_out_set(
            log, seeds.base_seed, seeds.per_group, PLAN.budgets, jobs, seeds.role
        )
        files.update(extra)
    b = PLAN.benchmark_worlds
    results["benchmark"], extra = benchmark_set(
        log, b.base_seed, b.per_group, PLAN.budgets, jobs, b.role
    )
    files.update(extra)
    inputs = {
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "engine_protocol_digest": DISCOVERY.digest,
        "v10_safety_protocol_digest": SAFETY.digest,
        "v11_safety_protocol_digest": SAFETY_V11.digest,
        "safety_protocol": to_jsonable(SAFETY_V12),
        "safety_protocol_digest": SAFETY_V12.digest,
        "plan": to_jsonable(PLAN),
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-safety-v1.2-evaluation-manifest@1",
        "frozen_inputs": tooling,
        "design_freeze": freeze,
        "v12_sources_sha256": v12_sources(),
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "evidence_files": sorted([*files, "results.json"]),
        "evidence_class": "ENGINEERING EVIDENCE ONLY -- developer-authored synthetic worlds",
        "not_claimed": [
            "scientific validity of any mechanism, forward model, grammar term or new mechanism",
            "an independent or blind evaluation: worlds, held-out families, the grammar, the "
            "engine and every safety gate share an author lineage",
            "anything about a real device, real literature, a language model or the real "
            "PostgreSQL LIB workflow; Discovery is not connected to real research execution",
            "scientific acceptance (NOT PASSED) or G-D (NOT PASSED)",
        ],
    }
    results_text = _dump(results)
    body["results_sha256"] = hashlib.sha256(results_text.encode("utf-8")).hexdigest()
    body["rows_sha256"] = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in sorted(files.items())
    }
    body["manifest_sha256"] = stable_digest(body)
    manifest = {**body, "code_commit": _commit(), "environment": environment()}
    log.append(f"elapsed {time.monotonic() - started:.1f}s")
    return {"manifest.json": _dump(manifest), "results.json": results_text, **files}


UNHASHED = ("code_commit", "environment")


def check(out: Path, files: dict[str, str], record: bool) -> int:
    stale = []
    for name, content in files.items():
        path = out / name
        if not path.exists():
            stale.append(f"{name}: missing")
            continue
        on_disk = path.read_text(encoding="utf-8")
        if name == "manifest.json":
            old, new = json.loads(on_disk), json.loads(content)
            for key in UNHASHED:
                old.pop(key, None)
                new.pop(key, None)
            if old != new:
                stale.append(f"{name}: hashed body differs")
        elif on_disk != content:
            stale.append(f"{name}: differs")
    recorded = (
        _load(out / "manifest.json")["environment"]["interpreter_key"]
        if (out / "manifest.json").exists()
        else None
    )
    verified_path = out / INTERPRETERS_FILE
    verified = _load(verified_path)["reproduced_under"] if verified_path.exists() else []
    known = {recorded, *(v["interpreter_key"] for v in verified)}
    current = interpreter_key()
    if stale:
        print("STALE: " + "; ".join(stale))
        if current not in known:
            print(
                f"(note: INTERPRETER MISMATCH as well -- written under {recorded}, "
                f"running {current})"
            )
        return 1
    if record:
        if current not in known:
            verified.append({**environment(), "result": "every evidence file reproduced exactly"})
            verified_path.write_text(_dump({"reproduced_under": verified}), encoding="utf-8")
            print(f"recorded: {current} reproduces the evidence exactly")
        return 0
    if current not in known:
        print(
            f"INTERPRETER MISMATCH: the evidence was written under {recorded} and reproduced under "
            f"{sorted(k for k in known if k)}; this is {current}. Every file matched, but this "
            "interpreter is not recorded as verified -- refusing to call the evidence current "
            "(re-run with --record-interpreter after review)."
        )
        return 2
    print("evidence is current")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--record-interpreter", action="store_true")
    parser.add_argument("--design-freeze")
    parser.add_argument("--dev", nargs=2, type=int, metavar=("BASE", "PER"))
    parser.add_argument("--budgets", default="")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    log: list[str] = []
    if args.dev:
        base, per = args.dev
        if base not in {r.base_seed for r in PLAN.development}:
            parser.error("--dev runs declared development seeds only")
        budgets = tuple(int(b) for b in args.budgets.split(",")) if args.budgets else PLAN.budgets
        held_out_set(log, base, per, budgets, args.jobs, "DEVELOPMENT")
        if base == 1:
            benchmark_set(log, base, per, budgets, args.jobs, "DEVELOPMENT")
        print("\n".join(log))
        return 0
    if args.check:
        manifest_path = args.out / "manifest.json"
        if not manifest_path.exists():
            print("STALE: manifest.json: missing")
            return 1
        commit = _load(manifest_path)["design_freeze"]["commit"]
    else:
        if not args.design_freeze:
            parser.error("writing the evidence needs --design-freeze SHA")
        commit = args.design_freeze
    files = build(log, design_freeze(commit), args.jobs)
    for line in log:
        print(line)
    if args.check:
        return check(args.out, files, args.record_interpreter)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
    (args.out / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
