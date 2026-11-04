"""Evaluate safety v1.1 (arm B4) beside v1.0 (B3) and the frozen engine (B2), and freeze it.

    python scripts/discovery_safety_v11_eval.py --design-freeze SHA   # write the evidence
    python scripts/discovery_safety_v11_eval.py --check               # refuse if anything drifted
    python scripts/discovery_safety_v11_eval.py --check --record-interpreter
                                                    # after a full content match, record that this
                                                    # interpreter reproduced the evidence

Offline and zero-cost: no model, simulator, network or database; Discovery is not connected to real
research execution. The engine, the 2026-11-02 evaluation tooling and the v1.0 safety package are
used exactly as frozen (their source hashes are checked against their manifests first), and v1.0's
recorded B2 and B3 digests are reproduced on the worlds v1.0 ran before anything new is reported.

    design freeze   `--design-freeze SHA` names the commit that froze the v1.1 design. The script
                    refuses unless the v1.1 package and this script are byte-identical to that
                    commit and the protocol and plan digests computed there equal today's (git
                    reads the commit; nothing is checked out)
    held-out        NEW worlds on the seed range `PLAN.held_out` derived from a fixed string,
                    generated only now, after the freeze: the family removed (B2/B3/B4), the family
                    left in (control), and the benchmark's world kinds on `PLAN.benchmark_worlds`
    previously      the P3 and v1.0-new held-out worlds (and their controls): reported, LABELLED as
    inspected       previously inspected, never as held-out for v1.1
    checkpoints     the pre-registered realized-cost ladder (`PLAN.checkpoints`)

REPRODUCIBILITY ACROSS INTERPRETERS. Every result and digest is computed in pure Python: the
engine's numerics are its own (no numpy/scipy), worlds draw from `random.Random(str)` (version-2
seeding: SHA-512 of the string, stable across CPython 3.x), digests hash floats as fixed six-decimal
strings, and every iteration that feeds a result is over a list or a sorted collection (never over a
set or dict of strings whose order depends on PYTHONHASHSEED). The manifest's hashed body therefore
holds no interpreter detail; the interpreter, platform and dependency versions are recorded in an
`environment` block outside the hash. `--check` is still strict: every evidence file must match
byte for byte (manifest: its hashed body), and an interpreter (implementation + major.minor) that is
not recorded as having reproduced the evidence is refused with INTERPRETER MISMATCH (exit 2) even
when every file matches. Nothing is ever accepted on a mismatch.

WHAT THE NUMBERS ARE. ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds; the held-out
families were declared in the catalog the engine was developed against. Not scientific validity, not
an independent evaluation, nothing about a real device. Scientific acceptance and G-D: NOT PASSED.

This script is the composition root that names the silicon-photonics scenario, which is why
`pyproject.toml` exempts this single file from the §24.2 import ban.
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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.model import stable_digest, to_jsonable  # noqa: E402
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery_eval import held_out  # noqa: E402
from lab_brain.discovery_safety.model import SAFETY  # noqa: E402
from lab_brain.discovery_safety.v11 import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.v11.model import (  # noqa: E402
    PLAN,
    SAFETY_V11,
    SeedRange,
)
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_scenario,
)

DEFAULT_OUT = ROOT / "docs" / "audit" / "discovery-safety-v1.1-2026-11-04" / "evidence"
FROZEN_ENGINE = ROOT / "docs" / "audit" / "discovery-loop-offline-2026-11-01" / "evidence"
FROZEN_EVAL = ROOT / "docs" / "audit" / "discovery-independent-evaluation-2026-11-02" / "evidence"
FROZEN_V10 = ROOT / "docs" / "audit" / "discovery-unknown-mechanism-safety-2026-11-04" / "evidence"
V10_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_safety"
V11_PACKAGE = V10_PACKAGE / "v11"
INTERPRETERS_FILE = "interpreter_verification.json"
#: v1.0's rows files, per previously inspected range (to reproduce its B2 and B3 digests).
V10_ROWS = {
    2_026_610_200: "held_out_p3_seeds_rows.json",
    2_026_810_400: "held_out_new_seeds_rows.json",
}
DEPENDENCIES = ("pydantic", "pydantic-core", "PyYAML", "cryptography")


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


def v11_sources() -> dict[str, str]:
    files = [*sorted(V11_PACKAGE.glob("*.py")), Path(__file__).resolve()]
    return {_rel(p): _sha256(p) for p in files}


# -- frozen inputs ---------------------------------------------------------------------------


def frozen_inputs(scenario: benchmark.Scenario) -> dict[str, Any]:
    engine = _load(FROZEN_ENGINE / "manifest.json")
    evaluation = _load(FROZEN_EVAL / "manifest.json")
    v10 = _load(FROZEN_V10 / "manifest.json")
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
        "v10_protocol_digest_matches": v10["inputs"]["safety_protocol_digest"] == SAFETY.digest,
        "frozen_engine_manifest_sha256": engine["manifest_sha256"],
        "frozen_evaluation_manifest_sha256": evaluation["manifest_sha256"],
        "frozen_v10_manifest_sha256": v10["manifest_sha256"],
    }
    if not all(v for k, v in out.items() if k.endswith(("_manifest", "_matches"))):
        raise SystemExit(f"a frozen input drifted; refusing to continue: {out}")
    return out


def design_freeze(commit: str) -> dict[str, Any]:
    """The v1.1 package and this script must be byte-identical to the design-freeze commit."""
    try:
        resolved = _git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        listed = _git("ls-tree", "--name-only", resolved, _rel(V11_PACKAGE) + "/").split()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot read the design-freeze commit {commit}: {exc}") from exc
    at_freeze = {}
    for relative in [*sorted(p for p in listed if p.endswith(".py")), _rel(Path(__file__))]:
        blob = subprocess.run(
            ["git", "show", f"{resolved}:{relative}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        at_freeze[relative] = hashlib.sha256(blob).hexdigest()
    if at_freeze != v11_sources():
        raise SystemExit(
            "the v1.1 sources differ from the design-freeze commit; the evaluation would not be of "
            "the frozen design"
        )
    return {
        "commit": resolved,
        "v11_sources_identical_to_freeze": True,
        "protocol_digest": SAFETY_V11.digest,
        "plan_digest": PLAN.digest,
        "held_out_seeds_generated_after_freeze": True,
    }


# -- running ---------------------------------------------------------------------------------


def held_out_set(
    log: list[str], scenario: benchmark.Scenario, seeds: SeedRange
) -> tuple[dict[str, Any], dict[str, str]]:
    worlds = held_out.held_out_worlds(
        scenario.catalog,
        seeds_per_class=seeds.per_group,
        base_seed=seeds.base_seed,
        protocol=DISCOVERY,
    )
    arms = ev.make_arms()
    records = ev.run_held_out_setting(
        scenario.catalog,
        worlds,
        budgets=PLAN.budgets,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        arms=arms,
    )
    control = ev.run_control_setting(
        scenario.catalog,
        worlds,
        budgets=PLAN.budgets,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        arms=arms,
    )
    head = ev.summarize(records, PLAN.budgets)
    chead = ev.summarize(control, PLAN.budgets)
    for budget in PLAN.budgets:
        parts = []
        for arm in ev.ARM_IDS:
            p = head[str(budget)][arm]["primary"]
            c = chead[str(budget)][arm]["all"]
            parts.append(
                f"{arm} force-fit {p['FORCE_FIT']['k']}/{p['FORCE_FIT']['n']} false-null "
                f"{p['FALSE_NULL']['k']} | control correct {c['CORRECT_IDENTIFICATION']['k']}/"
                f"{c['CORRECT_IDENTIFICATION']['n']}"
            )
        log.append(f"{seeds.role} {seeds.base_seed} budget {budget}: " + "; ".join(parts))
    reproduction: dict[str, Any] | None = None
    if seeds.base_seed in V10_ROWS:
        recorded = {r["world_id"]: r for r in _load(FROZEN_V10 / V10_ROWS[seeds.base_seed])}
        compared = identical = 0
        for r in records:
            if r.arm in ("B2", "B3"):
                compared += 1
                identical += (
                    recorded[r.world_id]["arms"][r.arm][str(r.budget)]["digest"] == r.digest
                )
        reproduction = {"compared": compared, "identical": identical}
        log.append(f"  v1.0 recorded B2/B3 digests reproduced: {identical}/{compared}")
        if identical != compared:
            raise SystemExit("v1.0's recorded digests do not reproduce; refusing to continue")
    out = {
        "label": seeds.label,
        "role": seeds.role,
        "base_seed": seeds.base_seed,
        "seeds_per_class": seeds.per_group,
        "worlds": len(worlds),
        "worlds_primary": sum(1 for w in worlds if not w.aliased),
        "worlds_aliased": sum(1 for w in worlds if w.aliased),
        "specs_digest": stable_digest(worlds),
        "held_out": {
            "setting": "true family REMOVED from the engine's catalog; correct = no claim",
            "by_budget": head,
            "checkpoints_primary": ev.checkpoint_table(
                records, PLAN.budgets, PLAN.checkpoints, primary_only=True
            ),
            "budget_monotonicity": {a: ev.budget_monotonicity(records, a) for a in ev.ARM_IDS},
        },
        "control": {
            "setting": "the same worlds with the family LEFT IN the catalog",
            "by_budget": chead,
            "checkpoints": ev.checkpoint_table(
                control, PLAN.budgets, PLAN.checkpoints, primary_only=False
            ),
        },
        "v11_additions": ev.refit_summary(arms),
        "v10_digests_reproduced": reproduction,
        "never_confirmed": not any("CONFIRMED" in r.outcome for r in (*records, *control)),
        "budget_never_exceeded": all(r.spent <= r.budget for r in (*records, *control)),
    }
    tag = f"{seeds.base_seed}"
    files = {
        f"held_out_{tag}_rows.json": _dump_rows(ev.records_as_json(records)),
        f"control_{tag}_rows.json": _dump_rows(ev.records_as_json(control)),
    }
    return out, files


def benchmark_set(log: list[str]) -> tuple[dict[str, Any], dict[str, str]]:
    seeds = PLAN.benchmark_worlds
    scenario = ring_scenario(seeds.per_group, base_seed=seeds.base_seed)
    arms = ev.make_arms()
    records = ev.run_benchmark_setting(scenario, budgets=PLAN.budgets, arms=arms)
    head = ev.summarize(records, PLAN.budgets)
    for budget in PLAN.budgets:
        parts = [
            f"{arm} correct {head[str(budget)][arm]['all']['CORRECT_IDENTIFICATION']['k']} "
            f"force-fit/false-discovery {head[str(budget)][arm]['all']['FORCE_FIT']['k']}"
            for arm in ev.ARM_IDS
        ]
        log.append(f"benchmark {seeds.base_seed} budget {budget}: " + "; ".join(parts))
    out = {
        "label": seeds.label,
        "role": seeds.role,
        "base_seed": seeds.base_seed,
        "seeds_per_kind": seeds.per_group,
        "worlds": len(scenario.worlds),
        "specs_digest": stable_digest(scenario.worlds),
        "setting": "the benchmark's world kinds (truth in the catalog, noise-only, or undeclared)",
        "by_budget": head,
        "checkpoints": ev.checkpoint_table(
            records, PLAN.budgets, PLAN.checkpoints, primary_only=False
        ),
        "v11_additions": ev.refit_summary(arms),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
    }
    return out, {f"benchmark_{seeds.base_seed}_rows.json": _dump_rows(ev.records_as_json(records))}


def build(log: list[str], freeze: dict[str, Any]) -> dict[str, str]:
    started = time.monotonic()
    scenario = ring_scenario(1, base_seed=1)
    tooling = frozen_inputs(scenario)
    files: dict[str, str] = {}
    results: dict[str, Any] = {}
    for seeds in PLAN.held_out:
        results[f"held_out_{seeds.base_seed}"], extra = held_out_set(log, scenario, seeds)
        files.update(extra)
    results["benchmark"], extra = benchmark_set(log)
    files.update(extra)
    for seeds in PLAN.previously_inspected:
        results[f"previously_inspected_{seeds.base_seed}"], extra = held_out_set(
            log, scenario, seeds
        )
        files.update(extra)
    inputs = {
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "engine_protocol_digest": DISCOVERY.digest,
        "v10_safety_protocol_digest": SAFETY.digest,
        "safety_protocol": to_jsonable(SAFETY_V11),
        "safety_protocol_digest": SAFETY_V11.digest,
        "plan": to_jsonable(PLAN),
        "plan_digest": PLAN.digest,
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-safety-v1.1-evaluation-manifest@1",
        "frozen_inputs": tooling,
        "design_freeze": freeze,
        "v11_sources_sha256": v11_sources(),
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "evidence_files": sorted([*files, "results.json"]),
        "evidence_class": "ENGINEERING EVIDENCE ONLY -- developer-authored synthetic worlds",
        "not_claimed": [
            "scientific validity of any mechanism, forward model or proposal",
            "an independent or blind evaluation: worlds, held-out families, the engine and both "
            "safety gates share an author lineage",
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
                f"(note: INTERPRETER MISMATCH as well -- evidence written under {recorded}, "
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
    parser.add_argument("--check", action="store_true", help="fail if the evidence is stale")
    parser.add_argument("--record-interpreter", action="store_true")
    parser.add_argument("--design-freeze", help="the design-freeze commit (writing only)")
    args = parser.parse_args(argv)
    log: list[str] = []
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
    files = build(log, design_freeze(commit))
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
