"""Scoring a discovery result against a world's hidden truth: distinguishable classes, not counts.

THE TRUTH'S CLASS. For a world whose truth is a declared hypothesis T (the noise model, a class, or
a composition), and the hypothesis universe U the catalog can express:

    N(T)   = T and every member of U that no available experiment separates from T
    N1(T)  = the members of N(T) no more complex than T (equally parsimonious alternatives)

A claimed class R (fingerprints, so a renamed duplicate is the same member) is scored:

    correct          T in R, R within N(T), and N1(T) within R -- the truth, nothing an available
                     experiment could have separated from it, and every equally simple alternative
                     it cannot be separated from (reporting one member of an inseparable pair is
                     NOT correct: that is resolving by fiat)
    false_discovery  a claim none of whose members is T or indistinguishable from it; for an
                     undeclared truth, any claim at all
    overclaim        R within N(T) but missing an equally simple indistinguishable alternative
    imprecise        T in R, but R also holds something an available experiment separates from T
    partial          a false discovery that shares a mechanism class with the truth

For an undeclared truth (no catalog hypothesis describes it) the correct outcome is no claim.

DIVERSITY IS DISTINGUISHABLE CLASSES. `distinguishable_diversity` counts the connected components of
the indistinguishability graph over the hypotheses a run examined. Fifty renamed copies or fifty
variants no available experiment separates from one hypothesis add nothing. `naive_hypothesis_count`
is kept, named as the defect it is, so a test can show it fails that property.

UNCERTAINTY. Proportions get the Wilson interval from `lab_brain.evaluation.stats`; means get a
seeded percentile bootstrap written the same way (`bootstrap_mean`), and paired arm differences a
seeded paired bootstrap over worlds. Each interval describes the sampling noise of these synthetic
worlds and nothing beyond them.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import hypothesis_universe
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    AnomalyState,
    DiscoveryResult,
    Hypothesis,
)
from lab_brain.discovery.worlds import WorldSpec
from lab_brain.evaluation.stats import wilson


def distinguishable_diversity(examined: Sequence[Hypothesis], oracle: SeparationOracle) -> int:
    """The number of distinguishable classes among the hypotheses examined."""
    return len(oracle.classes(examined))


def naive_hypothesis_count(examined: Sequence[Hypothesis], oracle: SeparationOracle) -> int:
    """THE REJECTED METRIC: how many hypotheses were examined. Gamed by adding variants."""
    del oracle
    return len(examined)


def resists_variant_gaming(
    metric: Callable[[Sequence[Hypothesis], SeparationOracle], int],
    examined: Sequence[Hypothesis],
    variants: Sequence[Hypothesis],
    oracle: SeparationOracle,
) -> bool:
    """Whether adding `variants` (each indistinguishable from an examined hypothesis) leaves the
    metric unchanged -- the property a diversity metric must have."""
    for variant in variants:
        if all(oracle.distinguishable(variant, h) for h in examined):
            raise ValueError(f"{variant.hypothesis_id} is not a variant of anything examined")
    return metric(examined, oracle) == metric((*examined, *variants), oracle)


@dataclass(frozen=True)
class WorldScore:
    world_id: str
    kind: str
    arm: str
    outcome: str
    claim_made: bool
    correct: bool
    false_discovery: bool
    overclaim: bool
    imprecise: bool
    partial: bool
    diversity: int
    naive_count: int
    spent: int
    experiments: int
    open_anomalies: int
    reframings: tuple[str, ...]
    digest: str


class Scorer:
    """Scores results for one catalog; caches each truth's class per available-experiment set."""

    def __init__(self, catalog: DiscoveryCatalog) -> None:
        self.catalog = catalog
        self.universe = hypothesis_universe(catalog)
        self._classes: dict[tuple[str, tuple[str, ...]], tuple[frozenset[str], frozenset[str]]] = {}

    def truth_class(
        self, truth: Hypothesis, oracle: SeparationOracle
    ) -> tuple[frozenset[str], frozenset[str]]:
        """(N, N1) as fingerprint sets."""
        key = (truth.fingerprint, tuple(e.experiment_id for e in oracle.available))
        if key not in self._classes:
            near = {truth.fingerprint}
            simple = {truth.fingerprint}
            for u in self.universe:
                if not oracle.distinguishable(u, truth):
                    near.add(u.fingerprint)
                    if len(u.components) <= len(truth.components):
                        simple.add(u.fingerprint)
            self._classes[key] = (frozenset(near), frozenset(simple))
        return self._classes[key]

    def score(
        self, world: WorldSpec, result: DiscoveryResult, oracle: SeparationOracle
    ) -> WorldScore:
        truth = world.truth_hypothesis(self.catalog)
        claim_made = result.outcome in CLAIM_OUTCOMES
        claimed = (
            frozenset(result.record(i).hypothesis.fingerprint for i in result.claim)
            if claim_made
            else frozenset()
        )
        if truth is None:
            correct = not claim_made
            false_discovery = claim_made
            overclaim = imprecise = partial = False
        else:
            near, simple = self.truth_class(truth, oracle)
            inside = claimed <= near
            correct = claim_made and truth.fingerprint in claimed and inside and simple <= claimed
            false_discovery = claim_made and not (claimed & near)
            overclaim = (
                claim_made and not correct and inside and bool(claimed) and not (simple <= claimed)
            )
            imprecise = claim_made and truth.fingerprint in claimed and not inside
            truth_classes = set(truth.class_ids)
            claimed_classes = {
                c for i in result.claim for c in result.record(i).hypothesis.class_ids
            }
            partial = false_discovery and bool(truth_classes & claimed_classes)
        examined = result.examined
        return WorldScore(
            world_id=world.world_id,
            kind=world.kind,
            arm=result.arm,
            outcome=result.outcome.value,
            claim_made=claim_made,
            correct=correct,
            false_discovery=false_discovery,
            overclaim=overclaim,
            imprecise=imprecise,
            partial=partial,
            diversity=distinguishable_diversity(examined, oracle),
            naive_count=naive_hypothesis_count(examined, oracle),
            spent=result.spent,
            experiments=len(result.steps),
            open_anomalies=sum(
                1
                for a in result.anomalies
                if a.state in (AnomalyState.UNEXPLAINED, AnomalyState.ACCOMMODATED)
            ),
            reframings=tuple(r.kind.value for r in result.reframings),
            digest=result.digest,
        )


def bootstrap_mean(
    values: Sequence[float], *, seed: int, resamples: int, label: str, confidence: float = 0.95
) -> tuple[float, float] | None:
    """A seeded percentile bootstrap of a mean (the same draw rule as `evaluation.stats`)."""
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not values:
        return None
    rng = random.Random(f"{seed}:{label}")
    n = len(values)
    means = sorted(
        math.fsum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)
    )
    tail = (1 - confidence) / 2
    low = means[max(0, math.ceil(tail * resamples) - 1)]
    high = means[min(resamples - 1, math.ceil((1 - tail) * resamples) - 1)]
    return round(low, 4), round(high, 4)


def paired_difference(
    a: Sequence[bool], b: Sequence[bool], *, seed: int, resamples: int, label: str
) -> dict[str, object]:
    """Mean of a - b over paired worlds, with a seeded paired percentile bootstrap interval."""
    if len(a) != len(b):
        raise ValueError("a paired difference needs the same worlds on both sides")
    diffs = [(1.0 if x else 0.0) - (1.0 if y else 0.0) for x, y in zip(a, b, strict=True)]
    return {
        "mean": round(math.fsum(diffs) / len(diffs), 4) if diffs else None,
        "ci95": bootstrap_mean(diffs, seed=seed, resamples=resamples, label=label),
        "worlds": len(diffs),
        "a_only": sum(1 for x, y in zip(a, b, strict=True) if x and not y),
        "b_only": sum(1 for x, y in zip(a, b, strict=True) if y and not x),
    }


def rate(flags: Sequence[bool]) -> dict[str, object]:
    k, n = sum(1 for f in flags if f), len(flags)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": wilson(k, n)}


def mean(values: Sequence[float], *, seed: int, resamples: int, label: str) -> dict[str, object]:
    return {
        "n": len(values),
        "mean": round(math.fsum(values) / len(values), 4) if values else None,
        "bootstrap95": bootstrap_mean(values, seed=seed, resamples=resamples, label=label),
    }


__all__ = [
    "Scorer",
    "WorldScore",
    "bootstrap_mean",
    "distinguishable_diversity",
    "mean",
    "naive_hypothesis_count",
    "paired_difference",
    "rate",
    "resists_variant_gaming",
]
