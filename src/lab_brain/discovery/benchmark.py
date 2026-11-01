"""The offline discovery benchmark: the same worlds, seeds and budget for every arm, then a freeze.

    B0  "single hypothesis"   `baselines.single_hypothesis_baseline` -- a deterministic stand-in for
                              one confident answer tested once; NOT a language model
    B1  "existing LIB style"  `investigate` under `EXISTING_LIB_STYLE`: a fixed initial set,
                              discrimination-per-cost selection and the shared refutation rule;
                              no anomaly records, noise test, expansion, reframing or closure. It is
                              a re-implementation of the existing loop's policy SHAPE in this
                              engine, not the PostgreSQL-backed `VerificationLoop`
    B2  "LIB + Discovery"     `investigate` under `DISCOVERY`

Ablations of B2 switch one discovery feature group off at a time, so a difference between B1 and
B2 can be traced to what produced it.

MATCHED BY CONSTRUCTION. Every arm runs every world with the same `Budget`, the same
`SeparationOracle` (one per set of available experiments), and a fresh `SyntheticWorld` built from
the same spec -- so the same noise for the same experiment run (common random numbers). `run`
records, per world, which arms ran and with what budget; a test checks that they are identical.

FROZEN. `manifest` records the catalog digest, the world specs' digest, each arm's protocol and
digest, the budget, the bootstrap seed and resamples, the interpreter, and the SHA-256 of every
source file of this package and of the scenario. `scripts/discovery_benchmark.py` writes the
manifest and the results of one complete run, and `--check` refuses a tree whose sources or results
no longer match.

WHAT THE NUMBERS ARE. Engineering evidence that the algorithm behaves as designed on toy forward
models written by the same implementer as the engine. Not scientific validity, not an independent
blind evaluation, and not a statement about any real device.
"""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from lab_brain.discovery.baselines import single_hypothesis_baseline
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, investigate
from lab_brain.discovery.metrics import (
    Scorer,
    WorldScore,
    distinguishable_diversity,
    mean,
    naive_hypothesis_count,
    paired_difference,
    rate,
)
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    Budget,
    DiscoveryResult,
    Hypothesis,
    MechanismClass,
    Origin,
    make_hypothesis,
    stable_digest,
    to_jsonable,
)
from lab_brain.discovery.protocol import DISCOVERY, EXISTING_LIB_STYLE, DiscoveryProtocol
from lab_brain.discovery.worlds import SyntheticWorld, UndeclaredEffect, WorldSpec

BENCHMARK_ID = "lab-brain/discovery-benchmark-offline"
BENCHMARK_VERSION = "0.1.0"
PACKAGE_DIR = Path(__file__).resolve().parent

Runner = Callable[..., DiscoveryResult]


@dataclass(frozen=True)
class Arm:
    arm_id: str
    label: str
    protocol: DiscoveryProtocol
    runner: Runner = field(compare=False, repr=False)


ARMS: tuple[Arm, ...] = (
    Arm(
        "B0",
        "single hypothesis (deterministic stand-in, not an LLM)",
        DISCOVERY,
        single_hypothesis_baseline,
    ),
    Arm("B1", "existing LIB style (fixed set + verification)", EXISTING_LIB_STYLE, investigate),
    Arm("B2", "LIB + Discovery", DISCOVERY, investigate),
)

ABLATIONS: tuple[Arm, ...] = (
    Arm(
        "B2-no-noise-test",
        "B2 without anomaly noise tests or decisive replication",
        replace(DISCOVERY, noise_test=False, decisive_replication=False),
        investigate,
    ),
    Arm(
        "B2-no-expansion",
        "B2 without widening or the measurement-chain review",
        replace(DISCOVERY, expansion=False, measurement_chain_review=False),
        investigate,
    ),
    Arm(
        "B2-no-closure",
        "B2 without rival closure, class closure or class reporting",
        replace(DISCOVERY, closure=False, rival_closure=False, report_classes=False),
        investigate,
    ),
    Arm(
        "B2-no-severity",
        "B2 with one prospective test and no decisive replication",
        replace(DISCOVERY, min_prospective_tests=1, decisive_replication=False),
        investigate,
    ),
)


@dataclass(frozen=True)
class Scenario:
    name: str
    catalog: DiscoveryCatalog
    worlds: tuple[WorldSpec, ...]
    undeclared: Mapping[str, UndeclaredEffect]
    motivating_experiment: str
    base_seed: int
    seeds_per_kind: int
    #: The scenario's own source files, hashed into the manifest.
    source_files: tuple[Path, ...] = ()


@dataclass(frozen=True)
class WorldRun:
    world: WorldSpec
    results: tuple[DiscoveryResult, ...]
    scores: tuple[WorldScore, ...]


@dataclass(frozen=True)
class BenchmarkRun:
    scenario: Scenario
    budget: int
    arms: tuple[Arm, ...]
    worlds: tuple[WorldRun, ...]


class Oracles:
    """One `SeparationOracle` per set of available experiments, shared by every arm."""

    def __init__(self, catalog: DiscoveryCatalog, protocol: DiscoveryProtocol) -> None:
        self.catalog = catalog
        self.protocol = protocol
        self._by_available: dict[tuple[str, ...], SeparationOracle] = {}

    def for_world(self, world: WorldSpec) -> SeparationOracle:
        available = world.available(self.catalog)
        if available not in self._by_available:
            self._by_available[available] = SeparationOracle(
                self.catalog, available, self.protocol, dict(world.removed)
            )
        return self._by_available[available]


def _distinguishability_protocol(arms: Sequence[Arm]) -> DiscoveryProtocol:
    keys = {(a.protocol.distinguish_tau, a.protocol.distinguish_replicates) for a in arms}
    if len(keys) != 1:
        raise ValueError("every arm must share one distinguishability definition")
    return arms[0].protocol


def lab_for(scenario: Scenario, world: WorldSpec) -> Laboratory:
    return SyntheticWorld(
        world, scenario.catalog, scenario.motivating_experiment, scenario.undeclared
    )


def run(scenario: Scenario, budget: int, arms: Sequence[Arm] = ARMS) -> BenchmarkRun:
    protocol = _distinguishability_protocol(arms)
    oracles = Oracles(scenario.catalog, protocol)
    scorer = Scorer(scenario.catalog)
    runs = []
    for world in scenario.worlds:
        oracle = oracles.for_world(world)
        results = tuple(
            arm.runner(
                arm=arm.arm_id,
                catalog=scenario.catalog,
                oracle=oracle,
                protocol=arm.protocol,
                budget=Budget(budget),
                lab=lab_for(scenario, world),
            )
            for arm in arms
        )
        scores = tuple(scorer.score(world, r, oracle) for r in results)
        runs.append(WorldRun(world, results, scores))
    return BenchmarkRun(scenario, budget, tuple(arms), tuple(runs))


def summarize(bench: BenchmarkRun, *, seed: int, resamples: int, blocks: int = 5) -> dict[str, Any]:
    """Per arm: rates with Wilson intervals, means with bootstrap intervals, per kind, per block."""
    out: dict[str, Any] = {}
    kinds = sorted({w.world.kind for w in bench.worlds})
    for index, arm in enumerate(bench.arms):
        scores = [w.scores[index] for w in bench.worlds]
        declared = [
            s for w, s in zip(bench.worlds, scores, strict=True) if w.world.undeclared is None
        ]
        correct_spent = [float(s.spent) for s in scores if s.correct]
        total_spent = sum(s.spent for s in scores)
        n_correct = sum(1 for s in scores if s.correct)
        per_block: list[float] = []
        block_size = max(1, bench.scenario.seeds_per_kind // blocks)
        for b in range(blocks):
            chosen = [
                s
                for w, s in zip(bench.worlds, scores, strict=True)
                if b * block_size <= int(w.world.world_id.rsplit("-", 1)[1]) < (b + 1) * block_size
            ]
            if chosen:
                per_block.append(round(sum(s.correct for s in chosen) / len(chosen), 4))
        out[arm.arm_id] = {
            "label": arm.label,
            "protocol_digest": arm.protocol.digest,
            "correct_outcome": rate([s.correct for s in scores]),
            "discovery_rate_declared_truths": rate([s.correct for s in declared]),
            "false_discovery": rate([s.false_discovery for s in scores]),
            "overclaim": rate([s.overclaim for s in scores]),
            "imprecise": rate([s.imprecise for s in scores]),
            "partial_false_discovery": rate([s.partial for s in scores]),
            "claims_made": rate([s.claim_made for s in scores]),
            "distinguishable_diversity": mean(
                [float(s.diversity) for s in scores],
                seed=seed,
                resamples=resamples,
                label=f"{arm.arm_id}:diversity",
            ),
            "naive_hypothesis_count": mean(
                [float(s.naive_count) for s in scores],
                seed=seed,
                resamples=resamples,
                label=f"{arm.arm_id}:naive",
            ),
            "budget_spent_all": mean(
                [float(s.spent) for s in scores],
                seed=seed,
                resamples=resamples,
                label=f"{arm.arm_id}:spent",
            ),
            "budget_spent_when_correct": mean(
                correct_spent, seed=seed, resamples=resamples, label=f"{arm.arm_id}:spent_correct"
            ),
            "budget_per_correct_outcome": (
                round(total_spent / n_correct, 4) if n_correct else None
            ),
            "open_anomalies_at_stop": mean(
                [float(s.open_anomalies) for s in scores],
                seed=seed,
                resamples=resamples,
                label=f"{arm.arm_id}:open",
            ),
            "per_kind": {
                kind: {
                    "correct": rate([s.correct for s in scores if s.kind == kind]),
                    "false_discovery": rate([s.false_discovery for s in scores if s.kind == kind]),
                    "overclaim": rate([s.overclaim for s in scores if s.kind == kind]),
                    "mean_spent": round(
                        sum(s.spent for s in scores if s.kind == kind)
                        / max(1, sum(1 for s in scores if s.kind == kind)),
                        4,
                    ),
                }
                for kind in kinds
            },
            "correct_rate_by_seed_block": per_block,
        }
    ids = [a.arm_id for a in bench.arms]
    paired: dict[str, Any] = {}
    if "B2" in ids:
        b2 = ids.index("B2")
        for other in ("B1", "B0"):
            if other in ids:
                o = ids.index(other)
                paired[f"B2_minus_{other}_correct"] = paired_difference(
                    [w.scores[b2].correct for w in bench.worlds],
                    [w.scores[o].correct for w in bench.worlds],
                    seed=seed,
                    resamples=resamples,
                    label=f"paired:B2-{other}",
                )
                paired[f"B2_minus_{other}_false_discovery"] = paired_difference(
                    [w.scores[b2].false_discovery for w in bench.worlds],
                    [w.scores[o].false_discovery for w in bench.worlds],
                    seed=seed,
                    resamples=resamples,
                    label=f"paired:B2-{other}:fd",
                )
    return {"arms": out, "paired": paired}


def world_rows(bench: BenchmarkRun) -> list[dict[str, Any]]:
    rows = []
    for w in bench.worlds:
        truth = w.world.truth_hypothesis(bench.scenario.catalog)
        rows.append(
            {
                "world_id": w.world.world_id,
                "kind": w.world.kind,
                "truth": "UNDECLARED:" + str(w.world.undeclared)
                if truth is None
                else truth.hypothesis_id,
                "arms": {
                    s.arm: {
                        "outcome": s.outcome,
                        "claim": list(r.claim),
                        "correct": s.correct,
                        "false_discovery": s.false_discovery,
                        "overclaim": s.overclaim,
                        "diversity": s.diversity,
                        "naive_count": s.naive_count,
                        "spent": s.spent,
                        "experiments": s.experiments,
                        "open_anomalies": s.open_anomalies,
                        "reframings": list(s.reframings),
                        "budget": r.budget,
                        "digest": s.digest,
                    }
                    for s, r in zip(w.scores, w.results, strict=True)
                },
            }
        )
    return rows


def run_digest(bench: BenchmarkRun) -> str:
    return stable_digest([[r.digest for r in w.results] for w in bench.worlds])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(scenario: Scenario, root: Path) -> dict[str, str]:
    files = sorted(PACKAGE_DIR.glob("*.py")) + sorted(scenario.source_files)
    return {p.resolve().relative_to(root.resolve()).as_posix(): sha256_file(p) for p in files}


def manifest(
    scenario: Scenario,
    *,
    budget: int,
    arms: Sequence[Arm],
    ablations: Sequence[Arm],
    sensitivity_budgets: Sequence[int],
    seed: int,
    resamples: int,
    root: Path,
    code_commit: str,
) -> dict[str, Any]:
    body = {
        "kind": "lab-brain/discovery-benchmark-manifest@1",
        "benchmark": {"id": BENCHMARK_ID, "version": BENCHMARK_VERSION},
        "scenario": scenario.name,
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "worlds": {
            "count": len(scenario.worlds),
            "base_seed": scenario.base_seed,
            "seeds_per_kind": scenario.seeds_per_kind,
            "kinds": sorted({w.kind for w in scenario.worlds}),
            "specs_digest": stable_digest(scenario.worlds),
        },
        "budget": budget,
        "sensitivity_budgets": list(sensitivity_budgets),
        "arms": [
            {
                "arm": a.arm_id,
                "label": a.label,
                "protocol": to_jsonable(a.protocol),
                "protocol_digest": a.protocol.digest,
            }
            for a in (*arms, *ablations)
        ],
        "statistics": {"bootstrap_seed": seed, "resamples": resamples, "interval": "95%"},
        "interpreter": f"{platform.python_implementation()} {platform.python_version()}",
        "sources_sha256": source_hashes(scenario, root),
        "code_commit": code_commit,
        "not_claimed": [
            "scientific validity of any mechanism or forward model",
            "an independent or blind evaluation (the worlds and the engine share an author)",
            "anything about a real device, a real measurement or a language model",
        ],
    }
    body["manifest_sha256"] = stable_digest({k: v for k, v in body.items() if k != "code_commit"})
    return body


def renamed_variants(mechanism: MechanismClass, count: int) -> tuple[MechanismClass, ...]:
    """Renamed copies with identical forward models -- the gaming input for diversity checks."""
    return tuple(
        replace(mechanism, class_id=f"{mechanism.class_id}.renamed_{i:02d}", prior=0.0)
        for i in range(count)
    )


def _risky(
    oracle: SeparationOracle,
    result: DiscoveryResult,
    hypothesis: Hypothesis,
    experiment_id: str,
    protocol: DiscoveryProtocol,
) -> bool:
    """The loop's "could have failed" test, against the noise model and every registered rival."""
    rivals = [NULL_HYPOTHESIS] + [
        r.hypothesis
        for r in result.hypotheses
        if r.alias_of is None and r.hypothesis_id != hypothesis.hypothesis_id
    ]
    return any(
        oracle.experiment_separation(hypothesis, rival, experiment_id) >= protocol.risky_separation
        for rival in rivals
        if rival.hypothesis_id != hypothesis.hypothesis_id
    )


def defect_demonstrations(bench: BenchmarkRun) -> dict[str, Any]:
    """Defects a naive version would have, measured on this run's own records."""
    catalog = bench.scenario.catalog
    oracles = Oracles(catalog, _distinguishability_protocol(bench.arms))
    ids = [a.arm_id for a in bench.arms]
    out: dict[str, Any] = {}
    # 1. Hypothesis-count gaming: add 50 renamed copies of one examined class.
    if "B2" in ids:
        first = bench.worlds[0]
        b2 = first.results[ids.index("B2")]
        oracle = oracles.for_world(first.world)
        examined = list(b2.examined)
        target = next(h for h in examined if not h.is_null)
        copies = (
            [make_hypothesis(m) for m in renamed_variants(target.components[0], 50)]
            if len(target.components) == 1
            else []
        )
        out["hypothesis_count_gaming"] = {
            "world": first.world.world_id,
            "copied": target.hypothesis_id,
            "copies_added": len(copies),
            "naive_count_before": naive_hypothesis_count(examined, oracle),
            "naive_count_after": naive_hypothesis_count([*examined, *copies], oracle),
            "distinguishable_diversity_before": distinguishable_diversity(examined, oracle),
            "distinguishable_diversity_after": distinguishable_diversity(
                [*examined, *copies], oracle
            ),
        }
    # 2. Retrospective self-support: hypotheses a rule that ignored registration time would have
    #    counted as through their prospective tests, but which were not.
    if "B2" in ids:
        index = ids.index("B2")
        protocol = bench.arms[index].protocol
        counted = 0
        examples: list[str] = []
        for w in bench.worlds:
            result = w.results[index]
            oracle = oracles.for_world(w.world)
            admitted = [o for o in result.observations if not o.motivating]
            for record in result.hypotheses:
                if record.alias_of is not None or record.origin in (
                    Origin.INITIAL_CATALOG,
                    Origin.INDISTINGUISHABILITY_CLOSURE,
                ):
                    continue

                risky = {
                    o.experiment_id
                    for o in admitted
                    if _risky(oracle, result, record.hypothesis, o.experiment_id, protocol)
                }
                naive = {o.experiment_id for o in admitted if o.experiment_id in risky}
                proper = {
                    o.experiment_id
                    for o in admitted
                    if o.taken_at > record.registered_at and o.experiment_id in risky
                }
                if (
                    len(naive) >= protocol.min_prospective_tests
                    and len(proper) < protocol.min_prospective_tests
                ):
                    counted += 1
                    if len(examples) < 5:
                        examples.append(f"{w.world.world_id}:{record.hypothesis_id}")
        out["retrospective_support"] = {
            "rule": "a naive rule counting every admitted risky observation, whatever its time",
            "hypotheses_it_would_have_counted_as_tested_but_were_not": counted,
            "examples": examples,
        }
    return out


__all__ = [
    "ABLATIONS",
    "ARMS",
    "BENCHMARK_ID",
    "BENCHMARK_VERSION",
    "Arm",
    "BenchmarkRun",
    "Oracles",
    "Scenario",
    "WorldRun",
    "defect_demonstrations",
    "lab_for",
    "manifest",
    "renamed_variants",
    "run",
    "run_digest",
    "source_hashes",
    "summarize",
    "world_rows",
]
