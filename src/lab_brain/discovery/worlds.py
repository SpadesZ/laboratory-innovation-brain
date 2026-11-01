"""Seeded synthetic worlds: a hidden truth, a noise model, and the experiments a lab can run.

A world is the offline benchmark's laboratory. It hides a truth -- a declared mechanism class with
an amplitude, a composition of two, the noise model alone, or an UNDECLARED effect no catalog class
describes -- and answers `measure` with the truth's prediction plus Gaussian noise of each entry's
declared sigma.

COMMON RANDOM NUMBERS. The noise of the k-th run of experiment E is drawn from
`random.Random(f"{world seed}:{E}:{k}")`, whatever arm is asking and in whatever order: two arms
that run the same experiment the same number of times see the same numbers. String seeding is
SHA-512 based and stable across processes, so a world reproduces exactly. The optional glitch (a
single `glitch_sigma` outlier) lands on the first measurement of the investigation, whichever
experiment that is, so every arm meets exactly one.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    ExperimentSpec,
    Hypothesis,
    make_hypothesis,
)

#: An effect no catalog class declares: (experiment, session index) -> entry values (no noise).
UndeclaredEffect = Callable[[ExperimentSpec, int], Mapping[str, float]]


@dataclass(frozen=True)
class WorldSpec:
    world_id: str
    kind: str
    seed: int
    #: Declared classes and the amplitude each takes in this world. Empty with no `undeclared`
    #: effect means the truth is the noise model alone.
    truth: tuple[tuple[str, float], ...] = ()
    #: The id of an undeclared truth effect (the scenario supplies it); excludes `truth`.
    undeclared: str | None = None
    #: Experiments this world's lab cannot run, with the reason.
    removed: tuple[tuple[str, str], ...] = ()
    glitch_motivating: bool = False
    glitch_first: bool = False
    glitch_sigma: float = 7.0

    def __post_init__(self) -> None:
        if self.truth and self.undeclared:
            raise ValueError("a world's truth is declared classes or an undeclared effect")

    def truth_hypothesis(self, catalog: DiscoveryCatalog) -> Hypothesis | None:
        """The truth as a catalog hypothesis, or None when it is undeclared."""
        if self.undeclared is not None:
            return None
        if not self.truth:
            return NULL_HYPOTHESIS
        return make_hypothesis(*(catalog.mechanism(c) for c, _ in self.truth))

    def available(self, catalog: DiscoveryCatalog) -> tuple[str, ...]:
        removed = {e for e, _ in self.removed}
        return tuple(e.experiment_id for e in catalog.experiments if e.experiment_id not in removed)


@dataclass
class SyntheticWorld:
    """`Laboratory` for one world. Holds no state between calls beyond its fixed spec."""

    spec: WorldSpec
    catalog: DiscoveryCatalog
    motivating_experiment: str
    undeclared: Mapping[str, UndeclaredEffect] = field(default_factory=dict)

    def _truth(self, experiment: ExperimentSpec, session: int) -> dict[str, float]:
        values = {e.entry_id: 0.0 for e in experiment.entries}
        if self.spec.undeclared is not None:
            effect = self.undeclared[self.spec.undeclared](experiment, session)
            for key, value in effect.items():
                values[key] += value
            return values
        for class_id, amplitude in self.spec.truth:
            mechanism = self.catalog.mechanism(class_id)
            for entry in experiment.entries:
                values[entry.entry_id] += amplitude * mechanism.coefficient(
                    experiment.experiment_id, entry.entry_id
                )
        return values

    def _sample(
        self, experiment: ExperimentSpec, key: str, session: int, glitch: bool
    ) -> tuple[tuple[str, float], ...]:
        rng = random.Random(f"{self.spec.seed}:{self.spec.world_id}:{key}")
        truth = self._truth(experiment, session)
        values = {
            e.entry_id: truth[e.entry_id] + e.sigma * rng.gauss(0.0, 1.0)
            for e in experiment.entries
        }
        if glitch:
            g = random.Random(f"{self.spec.seed}:{self.spec.world_id}:glitch:{key}")
            entry = experiment.entries[g.randrange(len(experiment.entries))]
            sign = 1.0 if g.random() < 0.5 else -1.0
            values[entry.entry_id] += sign * self.spec.glitch_sigma * entry.sigma
        return tuple((e.entry_id, values[e.entry_id]) for e in experiment.entries)

    def motivating(self) -> tuple[str, tuple[tuple[str, float], ...]]:
        experiment = self.catalog.experiment(self.motivating_experiment)
        return experiment.experiment_id, self._sample(
            experiment, "motivating", 0, self.spec.glitch_motivating
        )

    def measure(
        self, experiment_id: str, *, replicate: int, session: int
    ) -> tuple[tuple[str, float], ...]:
        experiment = self.catalog.experiment(experiment_id)
        return self._sample(
            experiment,
            f"{experiment_id}:{replicate}",
            session,
            self.spec.glitch_first and session == 1,
        )


__all__ = ["SyntheticWorld", "UndeclaredEffect", "WorldSpec"]
