"""Run the offline evaluation refinements of the Discovery Loop once, completely, and freeze them.

    python scripts/discovery_independent_eval.py            # write the evidence directory
    python scripts/discovery_independent_eval.py --check    # refuse if sources or results drifted

Three zero-cost, offline results, all on the engine exactly as frozen by the 2026-11-01 evidence
(its source hashes are checked against that manifest, and its frozen run is reproduced digest for
digest before anything else is computed):

    cost curves     B0, B1 and B2 over the cap grid 4..24 on FRESH seeds of the existing world
                    generator: realized (metered, not nominal) cost, correct and false-discovery
                    rates with Wilson intervals, area under the correct-rate curve, budget-to-first-
                    correct, paired McNemar tests with Holm's correction, and the cap invariants
    held-out class  worlds whose true mechanism family is removed from the engine's catalog and
                    prior (same author lineage as the engine -- not independent): correct is no
                    claim; a claimed mechanism is a force-fit
    scaffold        the documented hidden-world format run end to end on its EXAMPLE file (not a
                    hidden set): validate, seal, blind run, reveal, score, and three refusals

Nothing here calls a model, a simulator or the network, and nothing touches a database. B0 is a
deterministic single-hypothesis stand-in, NOT a language model; B1 re-implements the existing
loop's policy shape inside this engine and is NOT the PostgreSQL-backed `VerificationLoop`.

This script is the composition root (the one place naming the silicon-photonics scenario), which is
why `pyproject.toml` exempts this single file from the §24.2 import ban.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.model import stable_digest, to_jsonable  # noqa: E402
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery_eval import curves, held_out  # noqa: E402
from lab_brain.discovery_eval import hidden_worlds as hw  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    EVALUATION_BASE_SEED,
    MOTIVATING_EXPERIMENT,
    ring_scenario,
)

DEFAULT_OUT = ROOT / "docs" / "audit" / "discovery-independent-evaluation-2026-11-02" / "evidence"
FROZEN = ROOT / "docs" / "audit" / "discovery-loop-offline-2026-11-01" / "evidence"
EXAMPLE = ROOT / "benchmarks" / "discovery_independent" / "example.hidden-worlds.json"
SCHEMA = ROOT / "benchmarks" / "discovery_independent" / "hidden-worlds.schema.json"
EVAL_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_eval"

#: Fresh seeds of the existing generator, never run before this evaluation (the 2026-11-01 run used
#: 2026110100; development and the unit tests use 1). Seeds do not overlap: base + 1000*kind + i.
CURVE_BASE_SEED = 2026_11_02_00
SEEDS_PER_KIND = 25
CAPS = (4, 6, 8, 10, 12, 16, 20, 24)
#: Held-out worlds: base + 1000*class + i, disjoint from every other seed range used.
HELD_OUT_BASE_SEED = 2026_11_02_00 + 500_000
HELD_OUT_SEEDS_PER_CLASS = 15
HELD_OUT_BUDGETS = (12, 24)
CROSS_CHECK_BUDGET = 12
SCAFFOLD_BUDGET = 12
BOOTSTRAP_SEED = 20261102
RESAMPLES = 2000
ARM_IDS = [a.arm_id for a in benchmark.ARMS]


def _commit() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "scripts", "benchmarks"],
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
    """A JSON array with one world per line: still one JSON document, but a diff names worlds."""
    lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    return "[\n" + ",\n".join(lines) + "\n]\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _demo_salt(world_id: str) -> str:
    """DEMONSTRATION ONLY: reproducible, public, therefore NOT secret. A real seal draws 32 random
    bytes per world (`hw.seal` without `salts`)."""
    return hashlib.sha256(f"DEMO-SALT-NOT-SECRET:{world_id}".encode()).hexdigest()


def cross_check(log: list[str]) -> dict[str, Any]:
    """The engine is the frozen one: same sources, and the frozen main run reproduces exactly."""
    frozen_manifest = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))
    frozen_results = json.loads((FROZEN / "results.json").read_text(encoding="utf-8"))
    scenario = ring_scenario(SEEDS_PER_KIND, base_seed=EVALUATION_BASE_SEED)
    sources = benchmark.source_hashes(scenario, ROOT)
    rows = curves.run_grid(scenario, (CROSS_CHECK_BUDGET,), benchmark.ARMS)
    by_world: dict[str, list[str]] = {}
    for row in rows:
        by_world.setdefault(row.world_id, []).append(row.digest)
    digest = stable_digest([by_world[w.world_id] for w in scenario.worlds])
    frozen_digest = frozen_results["reproducibility"]["run_digest"]
    correct = {a: sum(1 for r in rows if r.arm == a and r.correct) for a in ARM_IDS}
    frozen_correct = {a: frozen_results["main"]["arms"][a]["correct_outcome"]["k"] for a in ARM_IDS}
    log.append(
        f"cross-check on the 2026-11-01 evaluation seeds at cap {CROSS_CHECK_BUDGET}: run digest "
        f"{'matches' if digest == frozen_digest else 'DIFFERS'}; correct {correct}"
    )
    return {
        "frozen_evidence": _rel(FROZEN),
        "frozen_code_commit": frozen_manifest["code_commit"],
        "frozen_manifest_sha256": frozen_manifest["manifest_sha256"],
        "engine_sources_match_frozen_manifest": sources == frozen_manifest["sources_sha256"],
        "budget": CROSS_CHECK_BUDGET,
        "base_seed": EVALUATION_BASE_SEED,
        "run_digest": digest,
        "frozen_run_digest": frozen_digest,
        "run_digest_matches": digest == frozen_digest,
        "correct": correct,
        "frozen_correct": frozen_correct,
        "correct_matches": correct == frozen_correct,
        "harness": "curves.run_grid (blind, metered laboratory) reproduces benchmark.run exactly",
    }


def cost_curves(log: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    scenario = ring_scenario(SEEDS_PER_KIND, base_seed=CURVE_BASE_SEED)
    started = time.monotonic()
    rows = curves.run_grid(scenario, CAPS, benchmark.ARMS)
    log.append(
        f"cost curves: {len(scenario.worlds)} worlds x {len(CAPS)} caps x {len(ARM_IDS)} arms = "
        f"{len(rows)} runs, base seed {CURVE_BASE_SEED} ({time.monotonic() - started:.1f}s)"
    )
    firsts: dict[str, Any] = {}
    for world in scenario.worlds:
        firsts.setdefault(world.kind, world)
    subset = type(scenario)(**{**scenario.__dict__, "worlds": tuple(firsts.values())})
    again = curves.run_grid(subset, CAPS, benchmark.ARMS)
    first_ids = {w.world_id for w in firsts.values()}
    recorded = {(r.world_id, r.arm, r.cap): r.digest for r in rows if r.world_id in first_ids}
    identical = sum(1 for r in again if recorded[(r.world_id, r.arm, r.cap)] == r.digest)
    summary = curves.summarize_grid(
        rows, caps=CAPS, arms=ARM_IDS, seed=BOOTSTRAP_SEED, resamples=RESAMPLES
    )
    out = {
        "kind": "lab-brain/discovery-cost-curves@1",
        "scenario": scenario.name,
        "base_seed": CURVE_BASE_SEED,
        "seeds_per_kind": SEEDS_PER_KIND,
        "world_kinds": sorted({w.kind for w in scenario.worlds}),
        "summary": summary,
        "invariants": curves.grid_invariants(rows, CAPS),
        "determinism": {
            "rerun": "first world of each kind, every cap and arm",
            "compared": len(again),
            "identical": identical,
        },
        "never_confirmed": not any("CONFIRMED" in r.outcome for r in rows),
        "labels": {a.arm_id: a.label for a in benchmark.ARMS},
    }
    log.append("cap  arm  correct [95% CI]           false-disc  realized mean  utilisation")
    for cap in CAPS:
        for arm in ARM_IDS:
            s = summary["per_cap"][str(cap)][arm]
            log.append(
                f"{cap:>3}  {arm}   {s['correct']['rate']:.3f} {s['correct']['wilson95']}  "
                f"{s['false_discovery']['rate']:.3f}       {s['realized_cost']['mean']:.2f}"
                f"          {s['utilisation']:.3f}"
            )
    log.append(f"AUC (correct vs cap): {summary['auc_correct_vs_cap']}")
    log.append(f"AUC paired: {summary['auc_paired']}")
    return out, curves.rows_as_json(rows), scenario


def held_out_experiment(log: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    catalog = ring_scenario(1, base_seed=CURVE_BASE_SEED).catalog
    worlds = held_out.held_out_worlds(
        catalog,
        seeds_per_class=HELD_OUT_SEEDS_PER_CLASS,
        base_seed=HELD_OUT_BASE_SEED,
        protocol=DISCOVERY,
    )
    rows: list[held_out.HeldOutRow] = []
    for budget in HELD_OUT_BUDGETS:
        started = time.monotonic()
        rows.extend(
            held_out.run_held_out(
                catalog,
                worlds,
                arms=benchmark.ARMS,
                budget=budget,
                motivating_experiment=MOTIVATING_EXPERIMENT,
                protocol=DISCOVERY,
            )
        )
        log.append(
            f"held-out: {len(worlds)} worlds x {len(ARM_IDS)} arms at budget {budget} "
            f"({time.monotonic() - started:.1f}s)"
        )
    summary = held_out.summarize_held_out(
        rows, arms=ARM_IDS, seed=BOOTSTRAP_SEED, resamples=RESAMPLES
    )
    control = held_out.run_full_catalog_control(
        catalog,
        worlds,
        arms=benchmark.ARMS,
        budget=HELD_OUT_BUDGETS[0],
        motivating_experiment=MOTIVATING_EXPERIMENT,
        protocol=DISCOVERY,
    )
    families = sorted({w.family for w in worlds})
    out = {
        "kind": "lab-brain/discovery-held-out-class@1",
        "author_note": (
            "SAME AUTHOR LINEAGE: the held-out families were declared in the catalog the engine "
            "was developed against, by the same author lineage. This tests behaviour with an "
            "incomplete vocabulary; it is not an independent test of unseen mechanisms."
        ),
        "base_seed": HELD_OUT_BASE_SEED,
        "seeds_per_class": HELD_OUT_SEEDS_PER_CLASS,
        "budgets": list(HELD_OUT_BUDGETS),
        "classes": len({w.truth_class for w in worlds}),
        "worlds": len(worlds),
        "correct_outcome": "no claim (STOPPED_UNEXPLAINED or STOPPED_INSUFFICIENT_VALIDATION)",
        "force_fit": "a claimed mechanism class (false discovery)",
        "false_null": "NO_EFFECT_BEYOND_NOISE (the effect is real)",
        "aliasing": held_out.aliasing_table(worlds),
        "descriptive_mentions_of_removed_family": {
            f: held_out.descriptive_mentions(held_out.without_family(catalog, f), f)
            for f in families
        },
        "summary": summary,
        "control_family_left_in_catalog": control,
        "never_confirmed": not any("CONFIRMED" in r.outcome for r in rows),
        "budget_never_exceeded": all(r.spent <= r.budget for r in rows),
    }
    for budget in HELD_OUT_BUDGETS:
        s = summary[str(budget)]
        log.append(
            f"held-out budget {budget}: primary worlds {s['worlds_primary']}, aliased "
            f"{s['worlds_aliased']}"
        )
        for arm in ARM_IDS:
            a = s["arms"][arm]
            log.append(
                f"  {arm} correct(no claim) {a['correct_no_claim']['rate']:.3f} "
                f"force-fit {a['force_fit']['rate']:.3f} false-null {a['false_null']['rate']:.3f} "
                f"with-record {a['correct_with_record']['rate']:.3f} "
                f"realized {a['realized_cost']['mean']:.2f}"
            )
    return out, held_out.rows_as_json(rows), worlds


def scaffold_demo(log: list[str]) -> dict[str, Any]:
    catalog = ring_scenario(1, base_seed=CURVE_BASE_SEED).catalog
    refusals: dict[str, str] = {}
    try:
        hw.load_document(EXAMPLE, repo=ROOT, allow_example=False)
    except hw.HiddenWorldRefused as error:
        refusals["example_used_as_hidden_set"] = str(error)
    data = hw.load_document(EXAMPLE, repo=ROOT, allow_example=True)
    worlds = hw.parse_hidden_worlds(data, catalog, DISCOVERY)
    leaking = json.loads(json.dumps(data))
    leaking["worlds"][0]["public"]["removed"] = [
        ["tec_stabilized", "stage disabled: the chip runs warm (ambient temperature offset)"]
    ]
    try:
        hw.parse_hidden_worlds(leaking, catalog, DISCOVERY)
    except hw.HiddenWorldRefused as error:
        refusals["removal_reason_names_the_truth"] = str(error)
    sealed, package = hw.seal(worlds, salts=_demo_salt)
    engine_package = hw.parse_engine_package(package, catalog)
    lab_side = hw.parse_hidden_worlds(sealed, catalog, DISCOVERY, sealed=True)
    outputs = hw.run_blind(
        engine_package,
        catalog,
        arms=benchmark.ARMS,
        budget=SCAFFOLD_BUDGET,
        laboratories=hw.sealed_laboratories(lab_side, catalog),
    )
    tampered = json.loads(json.dumps(package))
    tampered["cases"][0]["public"]["removed"] = [["cutback", "the saw is broken"]]
    try:
        hw.reveal(sealed, hw.parse_engine_package(tampered, catalog), catalog, DISCOVERY)
    except hw.CommitmentMismatch as error:
        refusals["public_part_altered_after_commitment"] = str(error)
    revealed = hw.reveal(sealed, engine_package, catalog, DISCOVERY)
    score = hw.score_outputs(
        outputs,
        revealed,
        engine_package,
        catalog,
        DISCOVERY,
        seed=BOOTSTRAP_SEED,
        resamples=RESAMPLES,
    )
    log.append(
        f"scaffold example: {len(worlds.worlds)} EXAMPLE worlds sealed (demo salts), root "
        f"{engine_package.root[:24]}..., refusals demonstrated: {sorted(refusals)}"
    )
    return {
        "kind": "lab-brain/discovery-hidden-world-scaffold-demo@1",
        "notice": (
            "EXAMPLE ONLY. The example file is public and written by the engine author's "
            "lineage; the salts are reproducible demonstration values and therefore NOT secret. "
            "Nothing here is a hidden set, an independent evaluation or a result about the engine."
        ),
        "example_file": _rel(EXAMPLE),
        "example_sha256": _sha256(EXAMPLE),
        "schema_file": _rel(SCHEMA),
        "engine_package": package,
        "outputs_digest": stable_digest(outputs),
        "score": {k: v for k, v in score.items() if k != "rows"},
        "rows": score["rows"],
        "refusals_demonstrated": refusals,
        "categories": {w.world_id: w.category for w in worlds.worlds},
        "aliases": {w.world_id: list(w.aliases) for w in worlds.worlds if w.aliases},
    }


def build(log: list[str]) -> dict[str, str]:
    started = time.monotonic()
    check = cross_check(log)
    curve_out, curve_rows, curve_scenario = cost_curves(log)
    held_out_out, held_out_rows, held_out_worlds = held_out_experiment(log)
    scaffold = scaffold_demo(log)
    evaluation_sources = {
        _rel(p): _sha256(p)
        for p in (*sorted(EVAL_PACKAGE.glob("*.py")), Path(__file__).resolve(), EXAMPLE, SCHEMA)
    }
    inputs = {
        "catalog": {"ref": curve_scenario.catalog.ref, "digest": curve_scenario.catalog.digest},
        "curve_worlds": {
            "base_seed": CURVE_BASE_SEED,
            "seeds_per_kind": SEEDS_PER_KIND,
            "count": len(curve_scenario.worlds),
            "specs_digest": stable_digest(curve_scenario.worlds),
        },
        "held_out_worlds": {
            "base_seed": HELD_OUT_BASE_SEED,
            "seeds_per_class": HELD_OUT_SEEDS_PER_CLASS,
            "count": len(held_out_worlds),
            "specs_digest": stable_digest(held_out_worlds),
        },
        "example_sha256": _sha256(EXAMPLE),
        "caps": list(CAPS),
        "held_out_budgets": list(HELD_OUT_BUDGETS),
        "scaffold_budget": SCAFFOLD_BUDGET,
        "arms": [
            {"arm": a.arm_id, "label": a.label, "protocol_digest": a.protocol.digest}
            for a in benchmark.ARMS
        ],
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-independent-evaluation-manifest@1",
        "engine": {
            "frozen_by": check["frozen_evidence"],
            "frozen_code_commit": check["frozen_code_commit"],
            "frozen_manifest_sha256": check["frozen_manifest_sha256"],
            "sources_sha256": benchmark.source_hashes(curve_scenario, ROOT),
            "sources_match_frozen_manifest": check["engine_sources_match_frozen_manifest"],
        },
        "evaluation_sources_sha256": evaluation_sources,
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "statistics": {
            "bootstrap_seed": BOOTSTRAP_SEED,
            "resamples": RESAMPLES,
            "interval": "95% (Wilson for proportions, seeded percentile bootstrap otherwise)",
            "multiplicity": "exact McNemar per cap and comparison, Holm-adjusted; "
            "Bonferroni-widened paired bootstrap intervals",
        },
        "interpreter": f"{platform.python_implementation()} {platform.python_version()}",
        "not_claimed": [
            "scientific validity of any mechanism or forward model",
            "an independent or blind evaluation: worlds, held-out families and the engine share "
            "an author lineage",
            "anything about a real device, real literature, a language model (B0 is not one) or "
            "the real PostgreSQL LIB workflow (B1 is not it)",
        ],
    }
    body["manifest_sha256"] = stable_digest(body)
    body["code_commit"] = _commit()
    log.append(f"elapsed {time.monotonic() - started:.1f}s")
    return {
        "manifest.json": _dump(body),
        "cross_check.json": _dump(check),
        "cost_curves.json": _dump(curve_out),
        "cost_curve_rows.json": _dump_rows(curve_rows),
        "held_out.json": _dump(held_out_out),
        "held_out_rows.json": _dump_rows(held_out_rows),
        "held_out_worlds.json": _dump(to_jsonable(held_out_worlds)),
        "scaffold_example.json": _dump(scaffold),
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
