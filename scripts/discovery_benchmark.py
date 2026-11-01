"""Run the offline discovery benchmark once, completely, and freeze its evidence.

    python scripts/discovery_benchmark.py                 # write the evidence directory
    python scripts/discovery_benchmark.py --check         # refuse if sources or results drifted

Arms B0 (single hypothesis, a deterministic stand-in -- not an LLM), B1 (existing LIB style) and
B2 (LIB + Discovery) run the SAME worlds with the SAME seeds and the SAME experiment budget; four
ablations of B2 and two further budgets are run for context. The main arms run twice and the two
runs must agree digest for digest (reproducibility). Nothing here calls a model, a simulator or the
network, and nothing touches a database.

This script is the composition root: it is the one place that names the silicon-photonics scenario
(the discovery engine itself imports no DomainPack), which is why `pyproject.toml` exempts this
single file from the §24.2 import ban.

Writes, into --out:
    manifest.json         catalog and world-spec digests, every arm's protocol, budget, statistics,
                          interpreter, source SHA-256s, code commit
    results.json          per-arm metrics with Wilson / bootstrap intervals, per world kind, paired
                          B2-vs-baseline differences, ablations, budget sensitivity, reproducibility
    worlds.json           the world specs (the hidden truths, revealed for audit)
    world_rows.json       every world's outcome per main arm
    defects.json          defects a naive version would have, measured on this run
    exemplar_traces.json  full records of the first world of each kind, for the main arms
    run.log               what ran, in order
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.model import to_jsonable  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    EVALUATION_BASE_SEED,
    ring_scenario,
)

DEFAULT_OUT = ROOT / "docs" / "audit" / "discovery-loop-offline-2026-11-01" / "evidence"
SEEDS_PER_KIND = 25
BUDGET = 12
SENSITIVITY = (8, 16)
BOOTSTRAP_SEED = 20261101
RESAMPLES = 2000


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


def build(log: list[str]) -> dict[str, str]:
    """Run everything and return {file name: content} for the deterministic files."""
    started = time.monotonic()
    scenario = ring_scenario(SEEDS_PER_KIND, base_seed=EVALUATION_BASE_SEED)
    log.append(
        f"scenario {scenario.name}: {len(scenario.worlds)} worlds, {SEEDS_PER_KIND} per kind, "
        f"base seed {EVALUATION_BASE_SEED}; budget {BUDGET}"
    )
    main = benchmark.run(scenario, BUDGET, benchmark.ARMS)
    log.append(f"main arms run 1: digest {benchmark.run_digest(main)}")
    again = benchmark.run(scenario, BUDGET, benchmark.ARMS)
    log.append(f"main arms run 2: digest {benchmark.run_digest(again)}")
    identical = benchmark.run_digest(main) == benchmark.run_digest(again)
    per_world_identical = sum(
        1
        for a, b in zip(main.worlds, again.worlds, strict=True)
        for x, y in zip(a.results, b.results, strict=True)
        if x.digest == y.digest
    )
    ablations = benchmark.run(scenario, BUDGET, benchmark.ABLATIONS)
    log.append(f"ablations: digest {benchmark.run_digest(ablations)}")
    sensitivity = {}
    for budget in SENSITIVITY:
        other = benchmark.run(scenario, budget, benchmark.ARMS)
        log.append(f"budget {budget}: digest {benchmark.run_digest(other)}")
        sensitivity[str(budget)] = {
            arm: {
                key: value
                for key, value in summary.items()
                if key
                in (
                    "correct_outcome",
                    "discovery_rate_declared_truths",
                    "false_discovery",
                    "overclaim",
                    "budget_spent_all",
                )
            }
            for arm, summary in benchmark.summarize(
                other, seed=BOOTSTRAP_SEED, resamples=RESAMPLES
            )["arms"].items()
        }
    summary = benchmark.summarize(main, seed=BOOTSTRAP_SEED, resamples=RESAMPLES)
    matched = all(
        len({r.budget for r in w.results}) == 1
        and [r.arm for r in w.results] == [a.arm_id for a in benchmark.ARMS]
        for w in main.worlds
    )
    results = {
        "kind": "lab-brain/discovery-benchmark-results@1",
        "budget": BUDGET,
        "main": summary,
        "ablations": benchmark.summarize(ablations, seed=BOOTSTRAP_SEED, resamples=RESAMPLES)[
            "arms"
        ],
        "budget_sensitivity": sensitivity,
        "matched": {
            "same_worlds_seeds_and_budget_for_every_arm": matched,
            "worlds": len(main.worlds),
            "arms": [a.arm_id for a in benchmark.ARMS],
        },
        "reproducibility": {
            "two_runs_identical": identical,
            "results_compared": len(main.worlds) * len(benchmark.ARMS),
            "results_identical": per_world_identical,
            "run_digest": benchmark.run_digest(main),
        },
        "never_confirmed": not any(
            "CONFIRMED" in r.outcome.value
            or any(e.state == "CONFIRMED" for h in r.hypotheses for e in h.history)
            for w in (*main.worlds, *ablations.worlds)
            for r in w.results
        ),
        "budget_never_exceeded": all(
            r.spent <= r.budget for w in (*main.worlds, *ablations.worlds) for r in w.results
        ),
    }
    exemplars = {}
    for w in main.worlds:
        if w.world.kind not in exemplars:
            exemplars[w.world.kind] = {
                "world": to_jsonable(w.world),
                "results": [r.as_json() for r in w.results],
            }
    manifest = benchmark.manifest(
        scenario,
        budget=BUDGET,
        arms=benchmark.ARMS,
        ablations=benchmark.ABLATIONS,
        sensitivity_budgets=SENSITIVITY,
        seed=BOOTSTRAP_SEED,
        resamples=RESAMPLES,
        root=ROOT,
        code_commit=_commit(),
    )
    log.append(f"elapsed {time.monotonic() - started:.1f}s")
    _table(summary, log)
    return {
        "manifest.json": _dump(manifest),
        "results.json": _dump(results),
        "worlds.json": _dump(to_jsonable(scenario.worlds)),
        "world_rows.json": _dump(benchmark.world_rows(main)),
        "defects.json": _dump(benchmark.defect_demonstrations(main)),
        "exemplar_traces.json": _dump(exemplars),
    }


def _table(summary: dict[str, Any], log: list[str]) -> None:
    log.append("arm  correct  [95% CI]        false-disc  overclaim  diversity  spent")
    for arm, s in summary["arms"].items():
        c = s["correct_outcome"]
        log.append(
            f"{arm:4} {c['rate']:.3f}  {c['wilson95']}  {s['false_discovery']['rate']:.3f}"
            f"       {s['overclaim']['rate']:.3f}      {s['distinguishable_diversity']['mean']:.2f}"
            f"       {s['budget_spent_all']['mean']:.2f}"
        )


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
                on_disk_json = json.loads(on_disk)
                new_json = json.loads(content)
                on_disk_json.pop("code_commit", None)
                new_json.pop("code_commit", None)
                if on_disk_json != new_json:
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
