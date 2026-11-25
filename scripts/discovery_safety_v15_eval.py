"""Evaluate safety v1.5 (B8) beside v1.4 (B7) and the v1.1 baseline (B4), world by world.

    python scripts/discovery_safety_v15_eval.py --dev BASE PER [--budgets 8,12] [--settings ...]
    python scripts/discovery_safety_v15_eval.py --design-freeze SHA      # held-out, ONCE
    python scripts/discovery_safety_v15_eval.py --check [--record-interpreter]
    python scripts/discovery_safety_v15_eval.py --arm-worker             # (internal)

Offline and zero-cost: no model, simulator, network or database; Discovery is not connected to real
research execution. The engine, the evaluation tooling, the v1.0-v1.4 safety packages and the v1.4
script's case builders are used exactly as frozen (source hashes checked against their manifests,
and the v1.4 script's hash is part of this freeze).

    boundary     every arm runs in a separate process (`--arm-worker`) that receives only its
                 catalog, the available experiments (and removal reasons), the cap and laboratory
                 replies; the world, its truth, the meter and the ledger stay in the evaluator
    freeze       `--design-freeze SHA` refuses unless the v1.5 package and this script are
                 byte-identical to that commit; the held-out base seeds are then DERIVED from the
                 commit's full id (`v15.model.holdout_base_seed`, domain `HOLDOUT_DOMAIN`)
    development  `--dev BASE PER` runs declared development seeds only (every range seen before,
                 including v1.4's spent held-out ranges) and writes only to --dev-out

SCORING. SAI 3.5 candidate.5 (spec commit 61af6ef) with the evaluator's v1.4 verdict (unchanged)
for every arm. Comparisons world by world at equal realized cost (v1.4's method, v1.5 metrics).
The abstention diagnosis and the refutation counts are evaluator-side (`v15.diagnose`).

WHAT THE NUMBERS ARE. ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds. Not
scientific validity, not an independent evaluation, nothing about a real device. Scientific
acceptance and G-D: NOT PASSED.

The composition root that names the silicon-photonics scenario and its grammar; `pyproject.toml`
exempts this file (as the v1.4 one) from the §24.2 import ban.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.model import (  # noqa: E402
    ExperimentSpec,
    make_hypothesis,
    stable_digest,
    to_jsonable,
)
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery.worlds import SyntheticWorld  # noqa: E402
from lab_brain.discovery_eval import held_out  # noqa: E402
from lab_brain.discovery_safety.v11.model import SAFETY_V11  # noqa: E402
from lab_brain.discovery_safety.v13 import evaluation as ev13  # noqa: E402
from lab_brain.discovery_safety.v13.boundary import serve_run, worker_loop  # noqa: E402
from lab_brain.discovery_safety.v13.ledger import EvaluatorLaboratory  # noqa: E402
from lab_brain.discovery_safety.v13.model import ArmAnswer  # noqa: E402
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14, SAFETY_V14  # noqa: E402
from lab_brain.discovery_safety.v15 import costmatch  # noqa: E402
from lab_brain.discovery_safety.v15 import diagnose as dg  # noqa: E402
from lab_brain.discovery_safety.v15 import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.v15.model import (  # noqa: E402
    HELD_OUT_V15,
    HOLDOUT_DOMAIN,
    PLAN,
    SAFETY_V15,
)
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    ring_catalog,
    ring_scenario,
)

V14_SCRIPT = ROOT / "scripts" / "discovery_safety_v14_eval.py"
_spec = importlib.util.spec_from_file_location("discovery_safety_v14_eval", V14_SCRIPT)
assert _spec is not None and _spec.loader is not None
v14s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v14s)

EVIDENCE_DIR = ROOT / "docs" / "audit" / "discovery-safety-v1.5-2026-11-25"
DEFAULT_OUT = EVIDENCE_DIR / "evidence"
V15_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_safety" / "v15"
INTERPRETERS_FILE = "interpreter_verification.json"
GRAMMAR = v14s.GRAMMAR
SETTINGS = ("held_out", "control", "benchmark")

_git = v14s._git
_sha256 = v14s._sha256
_rel = v14s._rel
_load = v14s._load
_dump = v14s._dump
_dump_rows = v14s._dump_rows
environment = v14s.environment
interpreter_key = v14s.interpreter_key


def _commit() -> str:
    try:
        head = _git("rev-parse", "HEAD").strip()
        dirty = _git("status", "--porcelain", "--", "src", "scripts").strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{'+dirty' if dirty else ''}"


def frozen_paths() -> list[Path]:
    return [*sorted(V15_PACKAGE.glob("*.py")), Path(__file__).resolve(), V14_SCRIPT.resolve()]


def v15_sources() -> dict[str, str]:
    return {_rel(p): _sha256(p) for p in frozen_paths()}


def design_freeze(commit: str, first_attempt: int = 0) -> dict[str, Any]:
    """The freeze record, refused unless the v1.5 package and the scripts are the commit's."""
    try:
        resolved = _git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot read the design-freeze commit {commit}: {exc}") from exc
    listed = _git("ls-tree", "--name-only", resolved, _rel(V15_PACKAGE) + "/").split()
    at_freeze = {}
    for relative in [
        *sorted(p for p in listed if p.endswith(".py")),
        _rel(Path(__file__)),
        _rel(V14_SCRIPT),
    ]:
        blob = subprocess.run(
            ["git", "show", f"{resolved}:{relative}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        at_freeze[relative] = hashlib.sha256(blob).hexdigest()
    if at_freeze != v15_sources():
        raise SystemExit(
            "the v1.5 sources differ from the design-freeze commit; the evaluation would not be of "
            "the frozen design"
        )
    return {
        "commit": resolved,
        "v15_sources_identical_to_freeze": True,
        "protocol_digest": SAFETY_V15.digest,
        "evaluator_rule_digest": EVALUATOR_RULE_V14.digest,
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "held_out_seed_rule": {
            "domain": HOLDOUT_DOMAIN,
            "rule": "base = 3_000_000_000 + 1000 * (int(SHA-256(domain || 0x00 || role || 0x00 || "
            "full commit id || 0x00 || attempt)) mod 1_000_000); the first attempt (from "
            f"{first_attempt}) at least 20_000 from every earlier range and from the other role's "
            "range",
            "first_attempt": first_attempt,
            "seeds": PLAN.held_out_seeds(resolved, first_attempt),
        },
    }


# -- the arm process --------------------------------------------------------------------------


def _handle(request: Mapping[str, Any], lab: Any) -> ArmAnswer:
    catalog, oracle = v14s._arm_catalog(request)
    return ev.run_arm(
        str(request["arm"]),
        catalog=catalog,
        oracle=oracle,
        budget=int(request["budget"]),
        lab=lab,
        grammar=GRAMMAR,
    )


class ArmProcess:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--arm-worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def run(self, request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
        assert self.process.stdin is not None and self.process.stdout is not None
        return serve_run(request, lab, self.process.stdin, self.process.stdout)


_PROCESS: list[ArmProcess] = []


def _execute_in_process(request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
    return _handle(request, lab)


def _execute_boundary(request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
    if not _PROCESS:
        _PROCESS.append(ArmProcess())
    return _PROCESS[0].run(request, lab)


# -- the evaluator's cases (v1.4's builders, plus the truth for the diagnosis) ------------------


def _extend(case: Any, truth: Any) -> ev.WorldCase:
    lab = case.lab_factory()

    def true_mean(experiment: ExperimentSpec) -> Mapping[str, float]:
        assert isinstance(lab, SyntheticWorld)
        return lab._truth(experiment, 1)

    base = {f.name: getattr(case, f.name) for f in dataclasses.fields(case)}
    return ev.WorldCase(**base, truth=truth, true_mean=true_mean)


def held_out_case(world: held_out.HeldOutWorld, removed: bool) -> ev.WorldCase:
    catalog = ring_catalog()
    truth = make_hypothesis(catalog.mechanism(world.truth_class))
    return _extend(v14s.held_out_case(world, removed), truth)


def benchmark_case(scenario: benchmark.Scenario, world: Any, oracles: Any) -> ev.WorldCase:
    return _extend(
        v14s.benchmark_case(scenario, world, oracles), world.truth_hypothesis(scenario.catalog)
    )


# -- running ------------------------------------------------------------------------------------

_MODE: list[str] = ["boundary"]
_ARMS: list[tuple[str, ...]] = [ev.ARM_IDS]


def _evaluator() -> ev.Evaluator:
    execute = _execute_boundary if _MODE[0] == "boundary" else _execute_in_process
    return ev.Evaluator(execute, GRAMMAR, EVALUATOR_RULE_V14, _ARMS[0])


def _init(mode: str, arms: tuple[str, ...]) -> None:
    _MODE[0] = mode
    _ARMS[0] = arms


def _held_out_task(args: tuple[int, int, int, bool, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, removed, budgets = args
    worlds = held_out.held_out_worlds(
        ring_catalog(), seeds_per_class=per, base_seed=base, protocol=DISCOVERY
    )
    return _evaluator().run(held_out_case(worlds[index], removed), budgets)


def _benchmark_task(args: tuple[int, int, int, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, budgets = args
    scenario = ring_scenario(per, base_seed=base)
    oracles = benchmark.Oracles(scenario.catalog, DISCOVERY)
    return _evaluator().run(benchmark_case(scenario, scenario.worlds[index], oracles), budgets)


def _map(fn: Any, tasks: list[Any], jobs: int, mode: str, arms: tuple[str, ...]) -> list[Any]:
    if jobs <= 1:
        _init(mode, arms)
        return [r for t in tasks for r in fn(t)]
    with Pool(jobs, initializer=_init, initargs=(mode, arms)) as pool:
        return [r for rs in pool.map(fn, tasks, chunksize=1) for r in rs]


def comparisons(
    rows: Sequence[Mapping[str, Any]], budgets: Sequence[int], label: str, arms: Sequence[str]
) -> dict[str, Any]:
    out: dict[str, Any] = {"method": "per-world matched at equal realized cost (v1.4 method)"}
    for y, x in PLAN.comparisons:
        if y not in arms or x not in arms:
            continue
        out[f"{y}-{x}"] = [
            costmatch.per_world_matched(
                rows,
                y,
                x,
                cap,
                tolerance=PLAN.per_world_tolerance,
                resamples=PLAN.bootstrap_resamples,
                label=label,
            )
            for cap in budgets
        ]
    return out


def held_out_set(
    log: list[str],
    base: int,
    per: int,
    budgets: tuple[int, ...],
    jobs: int,
    role: str,
    settings: tuple[str, ...] = SETTINGS,
    mode: str = "boundary",
    arms: tuple[str, ...] = ev.ARM_IDS,
    worlds_filter: tuple[str, ...] = (),
) -> tuple[dict[str, Any], dict[str, str], list[ev.RunRecord]]:
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
    every: list[ev.RunRecord] = []
    for removed, name in ((True, "held_out"), (False, "control")):
        if name not in settings:
            continue
        tasks = [
            (base, per, i, removed, budgets)
            for i, w in enumerate(worlds)
            if not worlds_filter or w.spec.world_id in worlds_filter
        ]
        records = _map(_held_out_task, tasks, jobs, mode, arms)
        every.extend(records)
        rows = ev.records_as_json(records)
        part: dict[str, Any] = {
            "setting": "true family REMOVED from the engine's catalog"
            if removed
            else "the same worlds with the family LEFT IN the catalog",
            "by_budget": ev.summarize(records, budgets, arms),
            "budget_never_exceeded": all(r.spent <= r.budget for r in records),
        }
        if removed:
            part["matched_primary"] = comparisons(
                [r for r in rows if not r["aliased"]], budgets, f"{name}-{base}-primary", arms
            )
            part["matched_aliased"] = comparisons(
                [r for r in rows if r["aliased"]], budgets, f"{name}-{base}-aliased", arms
            )
        else:
            part["matched"] = comparisons(rows, budgets, f"{name}-{base}", arms)
        out[name] = part
        files[f"{name}_{base}_rows.json"] = _dump_rows(rows)
        _log(log, f"{role} {name} {base}", records, budgets, arms)
    return out, files, every


def benchmark_set(
    log: list[str],
    base: int,
    per: int,
    budgets: tuple[int, ...],
    jobs: int,
    role: str,
    mode: str = "boundary",
    arms: tuple[str, ...] = ev.ARM_IDS,
    kinds: tuple[str, ...] = (),
) -> tuple[dict[str, Any], dict[str, str], list[ev.RunRecord]]:
    scenario = ring_scenario(per, base_seed=base)
    tasks = [
        (base, per, i, budgets)
        for i, w in enumerate(scenario.worlds)
        if not kinds or w.kind in kinds
    ]
    records = _map(_benchmark_task, tasks, jobs, mode, arms)
    _log(log, f"{role} benchmark {base}", records, budgets, arms)
    rows = ev.records_as_json(records)
    out = {
        "role": role,
        "base_seed": base,
        "seeds_per_kind": per,
        "worlds": len(tasks),
        "specs_digest": stable_digest(scenario.worlds),
        "by_budget": ev.summarize(records, budgets, arms),
        "matched": comparisons(rows, budgets, f"benchmark-{base}", arms),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
    }
    return out, {f"benchmark_{base}_rows.json": _dump_rows(rows)}, records


SHORT = v14s.SHORT


def _log(
    log: list[str], label: str, records: list[ev.RunRecord], budgets: Any, arms: Sequence[str]
) -> None:
    for budget in budgets:
        for arm in arms:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            for part, sub in ev.parts(mine).items():
                if not sub:
                    continue
                t = ev.table(sub)
                cats = " ".join(f"{SHORT[c]} {t['outcomes'][c]}" for c in ev.CATEGORIES)
                cost = t["realized_cost"]
                causes = " ".join(
                    f"{c.lower()} {n}" for c, n in t["abstention_causes"].items() if n
                )
                log.append(
                    f"{label} {part} b{budget} {arm} n={t['n']}: {cats} | supported "
                    f"{t['supported']} errors {t['errors']} supported-errors "
                    f"{t['supported_errors']} | own correct {t['own_correct']} own error "
                    f"{t['own_error']} | refuted {t['refuted_correct']} (incorrect "
                    f"{t['refuted_incorrect']}) runs {t['runs']} per-run {t['refuted_per_run']} "
                    f"per-unit {t['refuted_per_cost_unit']} | supportable {t['supportable']} "
                    f"supported {t['supportable_supported']} abstention correct "
                    f"{t['correct_abstention']} avoidable {t['avoidable_abstention']} [{causes}] "
                    f"| cost mean {cost.get('mean')} median {cost.get('median')} at-cap "
                    f"{cost.get('at_cap')}"
                )
    for r in records:
        if r.category in (ev13.FORCE_FIT, ev13.WRONG_CLAIM):
            log.append(
                f"  {r.arm} {r.category} {r.setting} {r.world_id}"
                f"{' (aliased)' if r.aliased else ''}"
                f" b{r.budget}: {r.answer} {list(r.claim)} ({r.outcome})"
            )


def _matched_log(log: list[str], label: str, matched: Mapping[str, Any]) -> None:
    for key, block in matched.items():
        if not isinstance(block, list):
            continue
        for p in block:
            d = p["differences"]
            log.append(
                f"{label} {key} @cap{p['anchor_cap']}: matched {p['matched']}/{p['worlds']} "
                f"({p['y']} dearer {p['unmatched_y_dearer']}, {p['x']} dearer "
                f"{p['unmatched_x_dearer']}); "
                + " ".join(
                    f"{k} {d[k]['mean']:+.3f} {d[k]['ci95']}"
                    for k in (
                        "own_correct",
                        "credited",
                        "supported_errors",
                        "own_error",
                        "refuted",
                        "avoidable_abstention",
                    )
                )
            )


# -- building the held-out evidence ---------------------------------------------------------------


def build(log: list[str], freeze: dict[str, Any], jobs: int) -> dict[str, str]:
    started = time.monotonic()
    scenario = ring_scenario(1, base_seed=1)
    tooling = v14s.frozen_inputs(scenario)
    v14_manifest = _load(v14s.DEFAULT_OUT / "manifest.json")
    tooling["v14_sources_match_frozen_manifest"] = {
        r: _sha256(ROOT / r) for r in v14_manifest["v14_sources_sha256"]
    } == v14_manifest["v14_sources_sha256"]
    tooling["v14_protocol_digest_matches"] = (
        v14_manifest["inputs"]["safety_protocol_digest"] == SAFETY_V14.digest
    )
    tooling["v14_evaluator_rule_digest_matches"] = (
        v14_manifest["inputs"]["evaluator_rule_digest"] == EVALUATOR_RULE_V14.digest
    )
    if not all(v for k, v in tooling.items() if k.endswith(("_manifest", "_matches"))):
        raise SystemExit(f"a frozen input drifted; refusing to continue: {tooling}")
    seeds = freeze["held_out_seed_rule"]["seeds"]
    files: dict[str, str] = {}
    results: dict[str, Any] = {}
    base = int(seeds["held-out-worlds"]["base_seed"])
    results["held_out_worlds"], extra, _ = held_out_set(
        log, base, PLAN.held_out_per_class, PLAN.budgets, jobs, HELD_OUT_V15
    )
    files.update(extra)
    _matched_log(log, "held_out primary", results["held_out_worlds"]["held_out"]["matched_primary"])
    _matched_log(log, "control", results["held_out_worlds"]["control"]["matched"])
    bench = int(seeds["benchmark-worlds"]["base_seed"])
    results["benchmark"], extra, _ = benchmark_set(
        log, bench, PLAN.benchmark_per_kind, PLAN.budgets, jobs, HELD_OUT_V15
    )
    _matched_log(log, "benchmark", results["benchmark"]["matched"])
    files.update(extra)
    inputs = {
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "engine_protocol_digest": DISCOVERY.digest,
        "v11_safety_protocol_digest": SAFETY_V11.digest,
        "v14_safety_protocol_digest": SAFETY_V14.digest,
        "safety_protocol": to_jsonable(SAFETY_V15),
        "safety_protocol_digest": SAFETY_V15.digest,
        "evaluator_rule": to_jsonable(EVALUATOR_RULE_V14),
        "evaluator_rule_digest": EVALUATOR_RULE_V14.digest,
        "plan": to_jsonable(PLAN),
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "diagnosis_causes": list(dg.CAUSES),
        "boundary": "every arm in a separate process (scripts/discovery_safety_v15_eval.py "
        "--arm-worker); JSON messages only",
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-safety-v1.5-evaluation-manifest@1",
        "frozen_inputs": tooling,
        "design_freeze": freeze,
        "v15_sources_sha256": v15_sources(),
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "evidence_files": sorted([*files, "results.json"]),
        "evidence_class": "ENGINEERING EVIDENCE ONLY -- developer-authored synthetic worlds",
        "not_claimed": [
            "scientific validity of any mechanism, forward model, grammar term or new mechanism",
            "an independent or blind evaluation: worlds, held-out families, the grammar, the "
            "engine, every safety gate and the evaluator's rule share an author lineage",
            "that v1.4 or v1.5 replaces v1.1: v1.1 remains the offline safety baseline",
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
            for key in ("code_commit", "environment"):
                old.pop(key, None)
                new.pop(key, None)
            if old != new:
                stale.append(f"{name}: hashed body differs")
        elif on_disk != content:
            stale.append(f"{name}: differs")
    if stale:
        print("STALE: " + "; ".join(stale))
        return 1
    recorded = _load(out / "manifest.json")["environment"]["interpreter_key"]
    verified_path = out / INTERPRETERS_FILE
    verified = _load(verified_path)["reproduced_under"] if verified_path.exists() else []
    known = {recorded, *(v["interpreter_key"] for v in verified)}
    current = interpreter_key()
    if record and current not in known:
        verified.append({**environment(), "result": "every evidence file reproduced exactly"})
        verified_path.write_text(_dump({"reproduced_under": verified}), encoding="utf-8")
        print(f"recorded: {current} reproduces the evidence exactly")
        return 0
    if current not in known:
        print(f"INTERPRETER MISMATCH: written under {recorded}; this is {current}")
        return 2
    print("evidence is current")
    return 0


def cause_table(paths: Sequence[Path], arms: Sequence[str]) -> list[str]:
    """Markdown tables of the abstention causes (answer NONE on supportable worlds) and of the
    open-rival kinds, per row file, arm and cap (reads row files only)."""
    out: list[str] = []
    for path in paths:
        rows = _load(path)
        caps = sorted({int(c) for r in rows for a in r["arms"].values() for c in a})
        for part, keep in (("primary", False), ("aliased", True)):
            sub = [r for r in rows if bool(r.get("aliased")) is keep]
            if not sub:
                continue
            out.append(f"\n#### {path.name} ({part}, {len(sub)} worlds)\n")
            out.append(
                "| arm | cap | supportable | SUPPORTED | abstained | "
                + " | ".join(c.lower() for c in dg.CAUSES)
                + " | correct / noise / budget / avoidable | open rivals by kind (abstained) |"
            )
            out.append("|" + "---|" * (6 + len(dg.CAUSES)))
            for arm in arms:
                for cap in caps:
                    cells = [
                        r["arms"][arm][str(cap)]
                        for r in sub
                        if arm in r["arms"] and str(cap) in r["arms"][arm]
                    ]
                    supp = [c for c in cells if c.get("supportable")]
                    if not supp:
                        continue
                    none = [c for c in supp if c["answer"] == "NONE" and c.get("cause")]
                    counts = {k: sum(c["cause"] == k for c in none) for k in dg.CAUSES}
                    buckets = {
                        b: sum(n for k, n in counts.items() if dg.BUCKETS[k] == b)
                        for b in ("correct", "noise_limited", "budget_limited", "avoidable")
                    }
                    kinds: dict[str, int] = {}
                    for c in none:
                        for k, n in (c.get("diagnosis") or {}).get("open_rival_kinds", {}).items():
                            kinds[k] = kinds.get(k, 0) + n
                    out.append(
                        f"| {arm} | {cap} | {len(supp)} | "
                        f"{sum(c['level'] == 'SUPPORTED' for c in supp)} | {len(none)} | "
                        + " | ".join(str(counts[k]) for k in dg.CAUSES)
                        + " | "
                        + " / ".join(str(v) for v in buckets.values())
                        + f" | {kinds} |"
                    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--record-interpreter", action="store_true")
    parser.add_argument("--design-freeze")
    parser.add_argument("--first-attempt", type=int, default=0)
    parser.add_argument("--dev", nargs=2, type=int, metavar=("BASE", "PER"))
    parser.add_argument("--budgets", default="")
    parser.add_argument("--settings", default=",".join(SETTINGS))
    parser.add_argument("--arms", default=",".join(ev.ARM_IDS))
    parser.add_argument("--kinds", default="")
    parser.add_argument("--worlds", default="", help="development only: world ids to run")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--dev-out", type=Path, help="development only: also write JSON here")
    parser.add_argument("--arm-worker", action="store_true")
    parser.add_argument("--cause-table", nargs="+", type=Path, help="row files to tabulate")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if args.arm_worker:
        return worker_loop(_handle)
    if args.cause_table:
        arms = tuple(a for a in args.arms.split(",") if a)
        print("\n".join(cause_table(args.cause_table, arms)))
        return 0
    log: list[str] = []
    budgets = tuple(int(b) for b in args.budgets.split(",")) if args.budgets else PLAN.budgets
    arms = tuple(a for a in args.arms.split(",") if a)
    mode = "in-process" if args.in_process else "boundary"
    if args.dev:
        base, per = args.dev
        if base not in {r.base_seed for r in PLAN.development}:
            parser.error("--dev runs declared development seeds only")
        settings = tuple(s for s in args.settings.split(",") if s)
        result: dict[str, Any] = {}
        rows: dict[str, str] = {}
        bench_bases = (1, 3_729_592_000, 3_168_619_000)
        if "benchmark" in settings and base in bench_bases:
            kinds = tuple(k for k in args.kinds.split(",") if k)
            result, rows, _ = benchmark_set(
                log, base, per, budgets, args.jobs, "DEVELOPMENT", mode, arms, kinds
            )
            _matched_log(log, "benchmark", result["matched"])
        elif base not in bench_bases:
            wf = tuple(w for w in args.worlds.split(",") if w)
            result, rows, _ = held_out_set(
                log, base, per, budgets, args.jobs, "DEVELOPMENT", settings, mode, arms, wf
            )
            if "held_out" in result:
                _matched_log(log, "held_out primary", result["held_out"]["matched_primary"])
            if "control" in result:
                _matched_log(log, "control", result["control"]["matched"])
        if args.dev_out:
            args.dev_out.mkdir(parents=True, exist_ok=True)
            tag = f"{base}_{per}_{'-'.join(settings)}_{'-'.join(arms)}"
            (args.dev_out / f"dev_{tag}.json").write_text(_dump(result), encoding="utf-8")
            for name, text in rows.items():
                (args.dev_out / f"dev_{tag}_{name}").write_text(text, encoding="utf-8")
            (args.dev_out / f"dev_{tag}.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        print("\n".join(log))
        return 0
    if args.check:
        manifest_path = args.out / "manifest.json"
        if not manifest_path.exists():
            print("STALE: manifest.json: missing")
            return 1
        freeze_record = _load(manifest_path)["design_freeze"]
        commit = freeze_record["commit"]
        first = int(freeze_record["held_out_seed_rule"].get("first_attempt", 0))
    else:
        if not args.design_freeze:
            parser.error("writing the evidence needs --design-freeze SHA")
        commit, first = args.design_freeze, args.first_attempt
        if (args.out / "manifest.json").exists():
            raise SystemExit(
                "held-out evidence already exists: the held-out evaluation runs exactly once "
                "(use --check to reproduce it)"
            )
    files = build(log, design_freeze(commit, first), args.jobs)
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
