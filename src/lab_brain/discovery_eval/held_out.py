"""Held-out mechanism classes: the true family is removed from the engine's catalog and prior.

THE SET-UP. For each declared class C of a scenario's catalog, worlds are generated whose truth is C
at an amplitude inside the inner 80% of its declared range. The engine is handed the catalog
WITHOUT C's whole family (every regime, every tier: initial, variant and extended), so neither the
initial working set, nor the prior, nor widening, nor rival or class closure can ever name it. The
laboratory still answers from the full catalog -- the truth is real, the engine just has no word for
it. The reduced catalog keeps the original id and a version suffix that is the same for every
family, so its name does not say what was removed.

WHAT IS CORRECT. No mechanism in the engine's vocabulary is true, so the correct outcome is NO
CLAIM: STOPPED_UNEXPLAINED (reported as unexplained), or STOPPED_INSUFFICIENT_VALIDATION. A claimed
mechanism class is a FORCE-FIT (a false discovery); NO_EFFECT_BEYOND_NOISE is a FALSE NULL (the
effect is real). Among the correct outcomes, `with_record` marks the ones that leave a trace a
person can act on: an anomaly still open at the stop, or a reframing record.

ALIASING. If the true class cannot be separated -- by the full available protocol, worst case over
both amplitude ranges, the same definition the engine uses -- from some hypothesis the REDUCED
catalog can express, then claiming that hypothesis is something no experiment here could prevent.
Such worlds are ALIASED: classified before any run, from the forward models alone, and scored
separately (a claim of an alias is a `surrogate`, reported, and excluded from the primary rates).

SAME AUTHOR. The held-out families were declared, by the same author lineage that wrote the engine,
in the catalog the engine was developed against. This tests the engine's behaviour when its
vocabulary is incomplete; it is not an independent test of unseen mechanisms.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from lab_brain.discovery.benchmark import Arm
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import hypothesis_universe
from lab_brain.discovery.metrics import Scorer, mean, paired_difference, rate
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    AnomalyState,
    Budget,
    DiscoveryResult,
    ExperimentSpec,
    MechanismClass,
    Outcome,
    make_hypothesis,
    to_jsonable,
)
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery.worlds import SyntheticWorld, WorldSpec
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory, find_truth_leaks

#: Every reduced catalog carries this version suffix, whichever family was removed.
REDUCED_VERSION_SUFFIX = "+held-out-family-removed"
KIND = "held_out"


class TruthLeak(RuntimeError):
    """Something the engine was handed, or returned, names the held-out truth."""


def without_family(catalog: DiscoveryCatalog, family: str) -> DiscoveryCatalog:
    """The catalog with every class of `family` removed; refused if nothing would be removed."""
    kept = tuple(m for m in catalog.mechanisms if m.family != family)
    if len(kept) == len(catalog.mechanisms):
        raise ValueError(f"catalog {catalog.ref} declares no family {family!r}")
    return replace(catalog, version=catalog.version + REDUCED_VERSION_SUFFIX, mechanisms=kept)


@dataclass(frozen=True)
class HeldOutWorld:
    spec: WorldSpec
    #: The truth's class (declared in the full catalog only).
    truth_class: str
    #: Removed from the engine's catalog entirely.
    family: str
    #: Hypotheses of the reduced catalog no available experiment separates from the truth class.
    aliases: tuple[str, ...]

    @property
    def aliased(self) -> bool:
        return bool(self.aliases)


def truth_needles(catalog: DiscoveryCatalog, world: HeldOutWorld) -> tuple[str, ...]:
    """The identifiers that would name the truth: every removed class id, and each removed
    class's forward-model fingerprint (as a class and as a one-class hypothesis)."""
    removed = [m for m in catalog.mechanisms if m.family == world.family]
    return tuple(
        sorted(
            {
                *(m.class_id for m in removed),
                *(make_hypothesis(m).fingerprint for m in removed),
                *(m.fingerprint for m in removed),
            }
        )
    )


def assert_family_absent(
    engine_catalog: DiscoveryCatalog, removed: Sequence[MechanismClass]
) -> None:
    """Structural absence: no class of the family, no removed class id, no removed forward model
    (by fingerprint, whatever it is called) is left in what the engine is handed."""
    families = {m.family for m in removed}
    ids = {m.class_id for m in removed}
    prints = {m.fingerprint for m in removed}
    left = [
        m.class_id
        for m in engine_catalog.mechanisms
        if m.family in families or m.class_id in ids or m.fingerprint in prints
    ]
    if left:
        raise TruthLeak(f"the engine's catalog still holds the held-out family: {left}")


def descriptive_mentions(engine_catalog: DiscoveryCatalog, family: str) -> list[str]:
    """Where the held-out family's id occurs as a word in the descriptive text the engine is
    handed (statements, regimes, descriptions). Reported, not refused: a remaining class may
    legitimately mention the held-out physics; the engine reads tables, never this text."""
    return find_truth_leaks(to_jsonable(engine_catalog), (family,))


def _amplitude(rng: random.Random, mechanism: MechanismClass) -> float:
    span = mechanism.upper - mechanism.lower
    return round(mechanism.lower + span * (0.1 + 0.8 * rng.random()), 4)


def held_out_worlds(
    catalog: DiscoveryCatalog,
    *,
    seeds_per_class: int,
    base_seed: int,
    protocol: DiscoveryProtocol,
) -> tuple[HeldOutWorld, ...]:
    """`seeds_per_class` worlds per declared class, deterministic in `base_seed`; aliasing is
    classified here, from the forward models alone, before anything runs."""
    available = tuple(e.experiment_id for e in catalog.experiments)
    full = SeparationOracle(catalog, available, protocol)
    out: list[HeldOutWorld] = []
    for index, mechanism in enumerate(sorted(catalog.mechanisms, key=lambda m: m.class_id)):
        reduced = without_family(catalog, mechanism.family)
        truth = make_hypothesis(mechanism)
        aliases = tuple(
            sorted(
                u.hypothesis_id
                for u in hypothesis_universe(reduced)
                if not full.distinguishable(truth, u)
            )
        )
        for i in range(seeds_per_class):
            seed = base_seed + 1000 * index + i
            rng = random.Random(f"{seed}:{KIND}:{mechanism.class_id}")
            spec = WorldSpec(
                f"{KIND}-{mechanism.class_id}-{i:02d}",
                KIND,
                seed,
                ((mechanism.class_id, _amplitude(rng, mechanism)),),
            )
            out.append(HeldOutWorld(spec, mechanism.class_id, mechanism.family, aliases))
    return tuple(out)


@dataclass(frozen=True)
class HeldOutRow:
    world_id: str
    truth_class: str
    family: str
    aliased: bool
    arm: str
    budget: int
    outcome: str
    claim: tuple[str, ...]
    spent: int
    correct: bool
    force_fit: bool
    false_null: bool
    surrogate: bool
    with_record: bool
    open_anomalies: int
    reframings: tuple[str, ...]
    digest: str


def score_held_out(world: HeldOutWorld, result: DiscoveryResult, spent: int) -> HeldOutRow:
    claim_made = result.outcome in CLAIM_OUTCOMES
    false_null = result.outcome is Outcome.NO_EFFECT_BEYOND_NOISE
    mechanism_claim = claim_made and not false_null
    surrogate = mechanism_claim and world.aliased and bool(set(result.claim) & set(world.aliases))
    open_anomalies = sum(
        1
        for a in result.anomalies
        if a.state in (AnomalyState.UNEXPLAINED, AnomalyState.ACCOMMODATED)
    )
    return HeldOutRow(
        world_id=world.spec.world_id,
        truth_class=world.truth_class,
        family=world.family,
        aliased=world.aliased,
        arm=result.arm,
        budget=result.budget,
        outcome=result.outcome.value,
        claim=result.claim,
        spent=spent,
        correct=not claim_made,
        force_fit=mechanism_claim and not surrogate,
        false_null=false_null,
        surrogate=surrogate,
        with_record=not claim_made and (open_anomalies > 0 or bool(result.reframings)),
        open_anomalies=open_anomalies,
        reframings=tuple(r.kind.value for r in result.reframings),
        digest=result.digest,
    )


def run_held_out(
    catalog: DiscoveryCatalog,
    worlds: Sequence[HeldOutWorld],
    *,
    arms: Sequence[Arm],
    budget: int,
    motivating_experiment: str,
    protocol: DiscoveryProtocol,
) -> list[HeldOutRow]:
    """Each arm on each world with the family removed. Refuses (TruthLeak) if the engine's catalog
    or any result names the truth."""
    experiments: dict[str, ExperimentSpec] = {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }
    costs = {k: e.cost for k, e in experiments.items()}
    reduced: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}
    rows: list[HeldOutRow] = []
    for world in worlds:
        key = (world.family, world.spec.removed)
        if key not in reduced:
            engine_catalog = without_family(catalog, world.family)
            available = world.spec.available(engine_catalog)
            reduced[key] = (
                engine_catalog,
                SeparationOracle(engine_catalog, available, protocol, dict(world.spec.removed)),
            )
        engine_catalog, oracle = reduced[key]
        assert_family_absent(
            engine_catalog, [m for m in catalog.mechanisms if m.family == world.family]
        )
        needles = truth_needles(catalog, world)
        leaks = find_truth_leaks(to_jsonable(engine_catalog), needles)
        if leaks:
            raise TruthLeak(f"the engine's catalog names the truth: {leaks[:3]}")
        available_ids = tuple(e.experiment_id for e in oracle.available)
        for arm in arms:
            meter = CostMeter(costs, budget)
            lab = blind_laboratory(
                SyntheticWorld(world.spec, catalog, motivating_experiment),
                experiments=experiments,
                available=available_ids,
                meter=meter,
            )
            result = arm.runner(
                arm=arm.arm_id,
                catalog=engine_catalog,
                oracle=oracle,
                protocol=arm.protocol,
                budget=Budget(budget),
                lab=lab,
            )
            leaks = find_truth_leaks(result.as_json(), needles)
            if leaks:
                raise TruthLeak(f"a result names the truth: {leaks[:3]}")
            if meter.spent != result.spent:
                raise RuntimeError(f"{world.spec.world_id}:{arm.arm_id}: meter and engine disagree")
            rows.append(score_held_out(world, result, meter.spent))
    return rows


def run_full_catalog_control(
    catalog: DiscoveryCatalog,
    worlds: Sequence[HeldOutWorld],
    *,
    arms: Sequence[Arm],
    budget: int,
    motivating_experiment: str,
    protocol: DiscoveryProtocol,
) -> dict[str, Any]:
    """The same worlds with the family LEFT IN the engine's catalog, scored by the benchmark's
    class rule: what each arm does when the truth is in its vocabulary (a contrast, not a test)."""
    oracle = SeparationOracle(
        catalog, tuple(e.experiment_id for e in catalog.experiments), protocol
    )
    scorer = Scorer(catalog)
    out: dict[str, Any] = {}
    for arm in arms:
        flags: list[bool] = []
        false: list[bool] = []
        for world in worlds:
            if world.spec.removed:
                raise ValueError("the control runs held-out worlds, which remove no experiment")
            result = arm.runner(
                arm=arm.arm_id,
                catalog=catalog,
                oracle=oracle,
                protocol=arm.protocol,
                budget=Budget(budget),
                lab=SyntheticWorld(world.spec, catalog, motivating_experiment),
            )
            score = scorer.score(world.spec, result, oracle)
            flags.append(score.correct)
            false.append(score.false_discovery)
        out[arm.arm_id] = {"correct": rate(flags), "false_discovery": rate(false)}
    return {"budget": budget, "worlds": len(worlds), "arms": out}


def summarize_held_out(
    rows: Sequence[HeldOutRow],
    *,
    arms: Sequence[str],
    seed: int,
    resamples: int,
    comparisons: Sequence[tuple[str, str]] = (("B2", "B1"), ("B2", "B0")),
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    budgets = sorted({r.budget for r in rows})
    for budget in budgets:
        at = [r for r in rows if r.budget == budget]
        primary = [r for r in at if not r.aliased]
        aliased = [r for r in at if r.aliased]
        arms_out: dict[str, Any] = {}
        for arm in arms:
            p = sorted((r for r in primary if r.arm == arm), key=lambda r: r.world_id)
            a = sorted((r for r in aliased if r.arm == arm), key=lambda r: r.world_id)
            outcomes: dict[str, int] = {}
            for r in p:
                outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
            families = sorted({r.family for r in p})
            arms_out[arm] = {
                "correct_no_claim": rate([r.correct for r in p]),
                "force_fit": rate([r.force_fit for r in p]),
                "false_null": rate([r.false_null for r in p]),
                "correct_with_record": rate([r.with_record for r in p]),
                "realized_cost": mean(
                    [float(r.spent) for r in p],
                    seed=seed,
                    resamples=resamples,
                    label=f"held_out:{arm}:{budget}:realized",
                ),
                "outcomes": dict(sorted(outcomes.items())),
                "per_family": {
                    f: {
                        "n": sum(1 for r in p if r.family == f),
                        "correct": sum(1 for r in p if r.family == f and r.correct),
                        "force_fit": sum(1 for r in p if r.family == f and r.force_fit),
                        "false_null": sum(1 for r in p if r.family == f and r.false_null),
                        "with_record": sum(1 for r in p if r.family == f and r.with_record),
                    }
                    for f in families
                },
                "aliased": {
                    "n": len(a),
                    "no_claim": sum(1 for r in a if r.correct),
                    "surrogate_claim": sum(1 for r in a if r.surrogate),
                    "other_claim": sum(1 for r in a if r.force_fit or r.false_null),
                },
            }
        paired: dict[str, Any] = {}
        for x, y in comparisons:
            if x not in arms or y not in arms:
                continue
            px = sorted((r for r in primary if r.arm == x), key=lambda r: r.world_id)
            py = sorted((r for r in primary if r.arm == y), key=lambda r: r.world_id)
            paired[f"{x}_minus_{y}_force_fit"] = paired_difference(
                [r.force_fit for r in px],
                [r.force_fit for r in py],
                seed=seed,
                resamples=resamples,
                label=f"held_out:{budget}:{x}-{y}:force_fit",
            )
            paired[f"{x}_minus_{y}_correct"] = paired_difference(
                [r.correct for r in px],
                [r.correct for r in py],
                seed=seed,
                resamples=resamples,
                label=f"held_out:{budget}:{x}-{y}:correct",
            )
        out[str(budget)] = {
            "worlds_primary": len({r.world_id for r in primary}),
            "worlds_aliased": len({r.world_id for r in aliased}),
            "arms": arms_out,
            "paired": paired,
        }
    return out


def rows_as_json(rows: Sequence[HeldOutRow]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = out.setdefault(
            r.world_id,
            {
                "world_id": r.world_id,
                "truth_class": r.truth_class,
                "family_removed": r.family,
                "aliased": r.aliased,
                "arms": {},
            },
        )
        entry["arms"].setdefault(r.arm, {})[str(r.budget)] = {
            "outcome": r.outcome,
            "claim": list(r.claim),
            "spent": r.spent,
            "correct": r.correct,
            "force_fit": r.force_fit,
            "false_null": r.false_null,
            "surrogate": r.surrogate,
            "with_record": r.with_record,
            "open_anomalies": r.open_anomalies,
            "reframings": list(r.reframings),
            "digest": r.digest,
        }
    return list(out.values())


def aliasing_table(worlds: Sequence[HeldOutWorld]) -> dict[str, Mapping[str, Any]]:
    """Per truth class: its family and the reduced-catalog hypotheses it cannot be told from."""
    table: dict[str, Mapping[str, Any]] = {}
    for w in worlds:
        table.setdefault(
            w.truth_class, {"family": w.family, "aliased": w.aliased, "aliases": list(w.aliases)}
        )
    return dict(sorted(table.items()))


__all__ = [
    "KIND",
    "REDUCED_VERSION_SUFFIX",
    "HeldOutRow",
    "HeldOutWorld",
    "TruthLeak",
    "aliasing_table",
    "assert_family_absent",
    "descriptive_mentions",
    "held_out_worlds",
    "rows_as_json",
    "run_full_catalog_control",
    "run_held_out",
    "score_held_out",
    "summarize_held_out",
    "truth_needles",
    "without_family",
]
