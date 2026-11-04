"""Evaluate the out-of-catalog safety gate (arm B3) beside the frozen engine (B2), and freeze it.

    python scripts/discovery_safety_eval.py            # write the evidence directory
    python scripts/discovery_safety_eval.py --check    # refuse if sources or results drifted

Offline and zero-cost: no model, simulator, network or database. The engine and the 2026-11-02
evaluation tooling are used exactly as frozen (their source hashes are checked against the frozen
manifests first), and the frozen held-out run is reproduced digest for digest before anything new
is computed. Nothing in the frozen evidence directories is read for anything but that comparison,
and nothing there is written.

    reproduction    B2 on the frozen P3 held-out worlds at budgets 12 and 24 through the frozen
                    `run_held_out`: every digest and the recorded force-fit counts must match
    held-out        B2 and B3 at budgets 8, 12, 24 and 48 on (a) the frozen P3 held-out worlds
                    (same seeds) and (b) NEW held-out worlds on a seed range never run before
    control         the same worlds with the family LEFT IN the catalog: in-catalog accuracy and
                    false discoveries, B2 against B3 (the positive control)
    curves          the existing world generator on the P3 curve seeds over the cap grid plus 48:
                    in-catalog accuracy and false discoveries per world kind
    sensitivity     the Owner's coverage option (1.0 default, 0.5, 0.0) at budgets 12 and 24 --
                    reported, NOT used to choose the default

The safety thresholds (`SafetyProtocol`) were fixed on DEVELOPMENT seeds only (held-out base seed
5_000_000, six worlds per class; curve worlds base seed 1) before any evaluation seed below ran.

WHAT THE NUMBERS ARE. Engineering evidence on synthetic worlds written by the engine's author
lineage; the held-out families were declared in the catalog the engine was developed against. Not
scientific validity, not an independent evaluation, nothing about a real device.

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
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.distinguish import SeparationOracle  # noqa: E402
from lab_brain.discovery.model import Budget, stable_digest, to_jsonable  # noqa: E402
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery.worlds import SyntheticWorld  # noqa: E402
from lab_brain.discovery_eval import curves, held_out  # noqa: E402
from lab_brain.discovery_safety import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.gate import safe_investigate  # noqa: E402
from lab_brain.discovery_safety.model import SAFETY  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_scenario,
)

DEFAULT_OUT = ROOT / "docs" / "audit" / "discovery-unknown-mechanism-safety-2026-11-04" / "evidence"
FROZEN_ENGINE = ROOT / "docs" / "audit" / "discovery-loop-offline-2026-11-01" / "evidence"
FROZEN_EVAL = ROOT / "docs" / "audit" / "discovery-independent-evaluation-2026-11-02" / "evidence"
SAFETY_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_safety"

#: The frozen P3 seeds (scripts/discovery_independent_eval.py), reused unchanged.
P3_HELD_OUT_BASE_SEED = 2026_11_02_00 + 500_000
P3_HELD_OUT_SEEDS_PER_CLASS = 15
P3_CURVE_BASE_SEED = 2026_11_02_00
P3_SEEDS_PER_KIND = 25
P3_HELD_OUT_BUDGETS = (12, 24)
#: NEW held-out worlds: base + 1000*class + i, disjoint from every seed range run before
#: (2026110100.., 2026110200.., 2026610200.., development 1.. and 5000000..).
NEW_HELD_OUT_BASE_SEED = 2026_11_04_00 + 700_000
NEW_HELD_OUT_SEEDS_PER_CLASS = 15
#: Seeds the safety thresholds were fixed on (development only; never an evaluation seed).
DEVELOPMENT_HELD_OUT_BASE_SEED = 5_000_000
DEVELOPMENT_CURVE_BASE_SEED = 1
BUDGETS = (8, 12, 24, 48)
CAPS = (4, 6, 8, 10, 12, 16, 20, 24, 48)
SENSITIVITY_BUDGETS = (12, 24)
SENSITIVITY_COVERAGE = (1.0, 0.5, 0.0)


def _commit() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "scripts"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{'+dirty' if dirty else ''}"


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _dump_rows(rows: list[dict[str, Any]]) -> str:
    lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    return "[\n" + ",\n".join(lines) + "\n]\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reproduction(log: list[str], scenario: benchmark.Scenario) -> dict[str, Any]:
    """The engine and the evaluation tooling are the frozen ones, and P3's force-fit reproduces."""
    frozen_engine = _load(FROZEN_ENGINE / "manifest.json")
    frozen_eval = _load(FROZEN_EVAL / "manifest.json")
    engine_sources = benchmark.source_hashes(scenario, ROOT)
    eval_sources = {
        relative: _sha256(ROOT / relative) for relative in frozen_eval["evaluation_sources_sha256"]
    }
    worlds = held_out.held_out_worlds(
        scenario.catalog,
        seeds_per_class=P3_HELD_OUT_SEEDS_PER_CLASS,
        base_seed=P3_HELD_OUT_BASE_SEED,
        protocol=DISCOVERY,
    )
    recorded_rows = {r["world_id"]: r for r in _load(FROZEN_EVAL / "held_out_rows.json")}
    recorded = _load(FROZEN_EVAL / "held_out.json")["summary"]
    per_budget: dict[str, Any] = {}
    for budget in P3_HELD_OUT_BUDGETS:
        rows = held_out.run_held_out(
            scenario.catalog,
            worlds,
            arms=(ev.B2,),
            budget=budget,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            protocol=DISCOVERY,
        )
        identical = sum(
            recorded_rows[r.world_id]["arms"]["B2"][str(budget)]["digest"] == r.digest for r in rows
        )
        primary = [r for r in rows if not r.aliased]
        force_fit = sum(r.force_fit for r in primary)
        per_budget[str(budget)] = {
            "runs": len(rows),
            "digest_identical_to_recorded": identical,
            "primary_worlds": len(primary),
            "force_fit": force_fit,
            "recorded_force_fit": recorded[str(budget)]["arms"]["B2"]["force_fit"]["k"],
            "force_fit_rate": round(force_fit / len(primary), 4),
        }
        log.append(
            f"reproduction B2 budget {budget}: {identical}/{len(rows)} digests identical; "
            f"force-fit {force_fit}/{len(primary)} (recorded "
            f"{per_budget[str(budget)]['recorded_force_fit']})"
        )
    out = {
        "frozen_engine_evidence": _rel(FROZEN_ENGINE),
        "frozen_engine_manifest_sha256": frozen_engine["manifest_sha256"],
        "engine_sources_match_frozen_manifest": engine_sources == frozen_engine["sources_sha256"],
        "frozen_evaluation_evidence": _rel(FROZEN_EVAL),
        "frozen_evaluation_manifest_sha256": frozen_eval["manifest_sha256"],
        "evaluation_sources_match_frozen_manifest": eval_sources
        == frozen_eval["evaluation_sources_sha256"],
        "held_out_worlds_specs_digest": stable_digest(worlds),
        "recorded_held_out_worlds_specs_digest": frozen_eval["inputs"]["held_out_worlds"][
            "specs_digest"
        ],
        "B2": per_budget,
    }
    out["reproduced"] = (
        out["engine_sources_match_frozen_manifest"]
        and out["evaluation_sources_match_frozen_manifest"]
        and out["held_out_worlds_specs_digest"] == out["recorded_held_out_worlds_specs_digest"]
        and all(
            v["digest_identical_to_recorded"] == v["runs"]
            and v["force_fit"] == v["recorded_force_fit"]
            for v in per_budget.values()
        )
    )
    if not out["reproduced"]:
        raise SystemExit("the frozen P3 held-out result does not reproduce; refusing to continue")
    return out


def held_out_block(
    log: list[str], scenario: benchmark.Scenario, base_seed: int, seeds: int, label: str
) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    worlds = held_out.held_out_worlds(
        scenario.catalog, seeds_per_class=seeds, base_seed=base_seed, protocol=DISCOVERY
    )
    rows, decisions = ev.held_out_evaluation(
        scenario.catalog, worlds, budgets=BUDGETS, motivating_experiment=MOTIVATING_EXPERIMENT
    )
    head = ev.headline(rows, (ev.B2.arm_id, ev.SAFE_ARM_ID))
    for budget in BUDGETS:
        b2, b3 = head[str(budget)]["B2"], head[str(budget)][ev.SAFE_ARM_ID]
        log.append(
            f"{label} budget {budget}: force-fit B2 {b2['force_fit']['k']}/{b2['force_fit']['n']} "
            f"-> B3 {b3['force_fit']['k']}/{b3['force_fit']['n']}; false null "
            f"{b2['false_null']['k']} -> {b3['false_null']['k']}; abstained "
            f"{b2['abstained_correctly']['k']} -> {b3['abstained_correctly']['k']}"
        )
    out = {
        "label": label,
        "base_seed": base_seed,
        "seeds_per_class": seeds,
        "worlds": len(worlds),
        "worlds_primary": sum(1 for w in worlds if not w.aliased),
        "worlds_aliased": sum(1 for w in worlds if w.aliased),
        "specs_digest": stable_digest(worlds),
        "budgets": list(BUDGETS),
        "correct_outcome": "no claim (STOPPED_UNEXPLAINED / STOPPED_INSUFFICIENT_VALIDATION)",
        "headline_primary": head,
        "frozen_summary": held_out.summarize_held_out(
            rows,
            arms=[ev.B2.arm_id, ev.SAFE_ARM_ID],
            seed=20261104,
            resamples=2000,
            comparisons=((ev.SAFE_ARM_ID, ev.B2.arm_id),),
        ),
        "safe_arm_decisions": decisions,
        "budget_monotonicity": {
            arm: ev.budget_monotonicity(rows, arm) for arm in (ev.B2.arm_id, ev.SAFE_ARM_ID)
        },
        "never_confirmed": not any("CONFIRMED" in r.outcome for r in rows),
        "budget_never_exceeded": all(r.spent <= r.budget for r in rows),
    }
    return out, held_out.rows_as_json(rows), worlds


def control_block(
    log: list[str], scenario: benchmark.Scenario, worlds: Any, label: str
) -> dict[str, Any]:
    out = ev.control_evaluation(
        scenario.catalog, worlds, budgets=BUDGETS, motivating_experiment=MOTIVATING_EXPERIMENT
    )
    for budget in BUDGETS:
        arms = out[str(budget)]["arms"]
        log.append(
            f"control ({label}) budget {budget}: in-catalog correct B2 "
            f"{arms['B2']['correct']['k']}/{arms['B2']['correct']['n']} -> B3 "
            f"{arms[ev.SAFE_ARM_ID]['correct']['k']}; false discoveries "
            f"{arms['B2']['false_discovery']['k']} -> "
            f"{arms[ev.SAFE_ARM_ID]['false_discovery']['k']}"
        )
    return out


def curve_block(log: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    scenario = ring_scenario(P3_SEEDS_PER_KIND, base_seed=P3_CURVE_BASE_SEED)
    rows, summary = ev.curve_evaluation(scenario, CAPS)
    recorded = {r["world_id"]: r for r in _load(FROZEN_EVAL / "cost_curve_rows.json")}
    identical = compared = 0
    for r in rows:
        if r.arm == "B2" and str(r.cap) in recorded[r.world_id]["arms"]["B2"]:
            compared += 1
            identical += recorded[r.world_id]["arms"]["B2"][str(r.cap)]["digest"] == r.digest
    for cap in CAPS:
        at = summary[str(cap)]
        log.append(
            f"curves cap {cap}: correct B2 {at['B2']['correct']['k']} -> B3 "
            f"{at[ev.SAFE_ARM_ID]['correct']['k']} of {at['B2']['correct']['n']}; false "
            f"discoveries {at['B2']['false_discovery']['k']} -> "
            f"{at[ev.SAFE_ARM_ID]['false_discovery']['k']}"
        )
    log.append(f"curves: B2 digests identical to the P3 record {identical}/{compared}")
    out = {
        "base_seed": P3_CURVE_BASE_SEED,
        "seeds_per_kind": P3_SEEDS_PER_KIND,
        "worlds": len(scenario.worlds),
        "specs_digest": stable_digest(scenario.worlds),
        "caps": list(CAPS),
        "B2_digests_identical_to_p3_record": {"identical": identical, "compared": compared},
        "per_cap": summary,
        "invariants": curves.grid_invariants(rows, CAPS),
    }
    return out, curves.rows_as_json(rows), scenario


def sensitivity_block(log: list[str], scenario: benchmark.Scenario) -> dict[str, Any]:
    """The coverage option the Owner decides. Reported for transparency; NOT used to choose."""
    out: dict[str, Any] = {
        "notice": (
            "Owner option, reported for transparency. The default (signal_coverage = 1.0) was "
            "fixed before these numbers were computed and is not chosen from them."
        ),
        "worlds": "P3 held-out worlds (frozen seeds), primary only; control = family left in",
        "options": {},
    }
    worlds = held_out.held_out_worlds(
        scenario.catalog,
        seeds_per_class=P3_HELD_OUT_SEEDS_PER_CLASS,
        base_seed=P3_HELD_OUT_BASE_SEED,
        protocol=DISCOVERY,
    )
    for coverage in SENSITIVITY_COVERAGE:
        safety = replace(SAFETY, signal_coverage=coverage)
        rows, _ = ev.held_out_evaluation(
            scenario.catalog,
            worlds,
            budgets=SENSITIVITY_BUDGETS,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            safety=safety,
        )
        control = ev.control_evaluation(
            scenario.catalog,
            worlds,
            budgets=SENSITIVITY_BUDGETS,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            safety=safety,
        )
        head = ev.headline(rows, (ev.SAFE_ARM_ID,))
        option: dict[str, Any] = {"safety_digest": safety.digest}
        for budget in SENSITIVITY_BUDGETS:
            b3 = head[str(budget)][ev.SAFE_ARM_ID]
            ctl = control[str(budget)]["arms"][ev.SAFE_ARM_ID]
            option[str(budget)] = {
                "held_out_force_fit": b3["force_fit"],
                "held_out_false_null": b3["false_null"],
                "control_correct": ctl["correct"],
                "control_false_discovery": ctl["false_discovery"],
            }
            log.append(
                f"sensitivity coverage {coverage} budget {budget}: force-fit "
                f"{b3['force_fit']['k']}/{b3['force_fit']['n']}, control correct "
                f"{ctl['correct']['k']}/{ctl['correct']['n']}"
            )
        out["options"][str(coverage)] = option
    return out


def examples(scenario: benchmark.Scenario) -> dict[str, Any]:
    """One full assessment of each kind, for a reader: catalog incomplete, endorsed."""
    worlds = held_out.held_out_worlds(
        scenario.catalog,
        seeds_per_class=NEW_HELD_OUT_SEEDS_PER_CLASS,
        base_seed=NEW_HELD_OUT_BASE_SEED,
        protocol=DISCOVERY,
    )
    out: dict[str, Any] = {}
    full = SeparationOracle(
        scenario.catalog, tuple(e.experiment_id for e in scenario.catalog.experiments), DISCOVERY
    )
    for world in worlds:
        if world.aliased or "catalog_incomplete" in out:
            continue
        reduced = held_out.without_family(scenario.catalog, world.family)
        oracle = SeparationOracle(
            reduced, tuple(e.experiment_id for e in reduced.experiments), DISCOVERY
        )
        run = safe_investigate(
            arm=ev.SAFE_ARM_ID,
            catalog=reduced,
            oracle=oracle,
            protocol=DISCOVERY,
            budget=Budget(24),
            lab=SyntheticWorld(world.spec, scenario.catalog, MOTIVATING_EXPERIMENT),
        )
        if run.assessment.catalog_incomplete and run.engine.claim:
            out["catalog_incomplete"] = {
                "world_id_revealed_after_run": world.spec.world_id,
                "budget": 24,
                "engine_outcome": run.engine.outcome.value,
                "engine_claim": list(run.engine.claim),
                "assessment": to_jsonable(run.assessment),
            }
    world = worlds[0]
    run = safe_investigate(
        arm=ev.SAFE_ARM_ID,
        catalog=scenario.catalog,
        oracle=full,
        protocol=DISCOVERY,
        budget=Budget(24),
        lab=SyntheticWorld(world.spec, scenario.catalog, MOTIVATING_EXPERIMENT),
    )
    out["in_catalog_endorsed"] = {
        "world_id": world.spec.world_id,
        "budget": 24,
        "truth_in_catalog": True,
        "assessment": to_jsonable(run.assessment),
    }
    return out


def build(log: list[str]) -> dict[str, str]:
    started = time.monotonic()
    scenario = ring_scenario(P3_SEEDS_PER_KIND, base_seed=P3_CURVE_BASE_SEED)
    repro = reproduction(log, scenario)
    frozen_out, frozen_rows, frozen_worlds = held_out_block(
        log, scenario, P3_HELD_OUT_BASE_SEED, P3_HELD_OUT_SEEDS_PER_CLASS, "held-out P3 seeds"
    )
    new_out, new_rows, new_worlds = held_out_block(
        log, scenario, NEW_HELD_OUT_BASE_SEED, NEW_HELD_OUT_SEEDS_PER_CLASS, "held-out NEW seeds"
    )
    control = {
        "p3_held_out_worlds": control_block(log, scenario, frozen_worlds, "P3 seeds"),
        "new_held_out_worlds": control_block(log, scenario, new_worlds, "NEW seeds"),
    }
    curve_out, curve_rows, _ = curve_block(log)
    sensitivity = sensitivity_block(log, scenario)
    sources = {
        _rel(p): _sha256(p)
        for p in (*sorted(SAFETY_PACKAGE.glob("*.py")), Path(__file__).resolve())
    }
    inputs = {
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "p3_held_out_worlds": {
            "base_seed": P3_HELD_OUT_BASE_SEED,
            "seeds_per_class": P3_HELD_OUT_SEEDS_PER_CLASS,
            "specs_digest": stable_digest(frozen_worlds),
        },
        "new_held_out_worlds": {
            "base_seed": NEW_HELD_OUT_BASE_SEED,
            "seeds_per_class": NEW_HELD_OUT_SEEDS_PER_CLASS,
            "specs_digest": stable_digest(new_worlds),
        },
        "p3_curve_worlds": {"base_seed": P3_CURVE_BASE_SEED, "seeds_per_kind": P3_SEEDS_PER_KIND},
        "development_seeds_used_to_fix_thresholds": {
            "held_out_base_seed": DEVELOPMENT_HELD_OUT_BASE_SEED,
            "held_out_seeds_per_class": 6,
            "curve_base_seed": DEVELOPMENT_CURVE_BASE_SEED,
        },
        "budgets": list(BUDGETS),
        "caps": list(CAPS),
        "engine_protocol_digest": DISCOVERY.digest,
        "safety_protocol": to_jsonable(SAFETY),
        "safety_protocol_digest": SAFETY.digest,
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-safety-evaluation-manifest@1",
        "engine_and_evaluation_tooling": {
            "engine_sources_match_frozen_manifest": repro["engine_sources_match_frozen_manifest"],
            "evaluation_sources_match_frozen_manifest": repro[
                "evaluation_sources_match_frozen_manifest"
            ],
            "frozen_engine_manifest_sha256": repro["frozen_engine_manifest_sha256"],
            "frozen_evaluation_manifest_sha256": repro["frozen_evaluation_manifest_sha256"],
        },
        "safety_sources_sha256": sources,
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "interpreter": f"{platform.python_implementation()} {platform.python_version()}",
        "evidence_class": "ENGINEERING EVIDENCE ONLY -- developer-authored synthetic worlds",
        "not_claimed": [
            "scientific validity of any mechanism, forward model or proposal",
            "an independent or blind evaluation: worlds, held-out families, the engine and the "
            "safety gate share an author lineage",
            "anything about a real device, real literature, a language model or the real "
            "PostgreSQL LIB workflow",
            "scientific acceptance (NOT PASSED) or G-D (NOT PASSED)",
        ],
    }
    body["manifest_sha256"] = stable_digest(body)
    body["code_commit"] = _commit()
    example = examples(scenario)
    log.append(f"elapsed {time.monotonic() - started:.1f}s")
    return {
        "manifest.json": _dump(body),
        "reproduction.json": _dump(repro),
        "held_out_p3_seeds.json": _dump(frozen_out),
        "held_out_p3_seeds_rows.json": _dump_rows(frozen_rows),
        "held_out_new_seeds.json": _dump(new_out),
        "held_out_new_seeds_rows.json": _dump_rows(new_rows),
        "held_out_new_seeds_worlds.json": _dump(to_jsonable(new_worlds)),
        "control.json": _dump(control),
        "curves.json": _dump(curve_out),
        "curve_rows.json": _dump_rows(curve_rows),
        "sensitivity.json": _dump(sensitivity),
        "examples.json": _dump(example),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="fail if the evidence is stale")
    args = parser.parse_args(argv)
    log: list[str] = []
    files = build(log)
    if args.check:
        stale = []
        for name, content in files.items():
            path = args.out / name
            if not path.exists():
                stale.append(f"{name}: missing")
                continue
            on_disk = path.read_text(encoding="utf-8")
            if name == "manifest.json":
                old, new = json.loads(on_disk), json.loads(content)
                old.pop("code_commit", None)
                new.pop("code_commit", None)
                if old != new:
                    stale.append(f"{name}: differs")
            elif on_disk != content:
                stale.append(f"{name}: differs")
        for line in log:
            print(line)
        if stale:
            print("STALE: " + "; ".join(stale))
            return 1
        print("evidence is current")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
    (args.out / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
