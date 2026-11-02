"""Information exposure controls: what the engine may reach of a hidden world, and what it cost.

    blind_laboratory(lab, ...)   a `Laboratory` whose only behaviour is `motivating` and `measure`.
                                 The world object (its spec, truth, seed and full catalog) is held
                                 in a closure, never as an attribute; the wrapper has no instance
                                 dictionary and no slots. It refuses an experiment the world's lab
                                 cannot run, and it refuses a returned reading that is not exactly
                                 the experiment's declared entries as numbers -- nothing else can
                                 travel back to the engine.
    CostMeter                    the laboratory's own count of what it ran. REALIZED COST is the
                                 meter's figure, charged from the declared experiment costs before
                                 each run, independently of what the engine reports spending; a run
                                 the cap does not cover is refused by the meter itself
                                 (`RealizedCostExceeded`), not only by the engine's budget check.
    find_truth_leaks(tree, ...)  every place in a JSON-able tree (a catalog, an engine package, a
                                 result) where a truth string appears as a token in a key or a
                                 string value, case-insensitively -- the check that what the engine
                                 is handed and what it returns name nothing hidden. Lexical, not
                                 semantic: a paraphrase of the truth is not detected.

LIMIT. In one Python process nothing is truly hidden: `type(lab).measure.__closure__` reaches the
world. The wrapper guards against ACCIDENTAL exposure and makes deliberate access visible in review;
it is not a security boundary. The independent protocol runs the laboratory as a separate process
whose files the engine cannot read (`docs/evaluation/discovery-independent-evaluation-protocol.md`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.loop import Laboratory
from lab_brain.discovery.model import ExperimentSpec

Values = tuple[tuple[str, float], ...]


class ExposureRefused(RuntimeError):
    """The engine asked for, or was about to receive, something outside the blind interface."""


class RealizedCostExceeded(RuntimeError):
    """The laboratory was asked to run an experiment its cap does not cover."""


@dataclass
class CostMeter:
    """The laboratory's own ledger: declared cost charged per run, refused beyond the cap."""

    costs: Mapping[str, int]
    cap: int
    spent: int = 0
    runs: list[str] = field(default_factory=list)

    def charge(self, experiment_id: str) -> None:
        cost = self.costs[experiment_id]
        if self.spent + cost > self.cap:
            raise RealizedCostExceeded(
                f"{experiment_id} costs {cost}; the laboratory's cap of {self.cap} has "
                f"{self.cap - self.spent} left"
            )
        self.spent += cost
        self.runs.append(experiment_id)


def _checked(experiment: ExperimentSpec, values: Any) -> Values:
    """Exactly the experiment's declared entries, in order, as finite numbers -- or refused."""
    expected = [e.entry_id for e in experiment.entries]
    try:
        pairs = [(str(k), v) for k, v in values]
    except (TypeError, ValueError) as error:
        raise ExposureRefused(
            f"{experiment.experiment_id}: a reading is (entry, value) pairs"
        ) from (error)
    if [k for k, _ in pairs] != expected:
        raise ExposureRefused(
            f"{experiment.experiment_id}: a reading carries exactly the declared entries {expected}"
        )
    out = []
    for key, value in pairs:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ExposureRefused(f"{experiment.experiment_id}.{key}: a reading value is a number")
        number = float(value)
        if not math.isfinite(number):
            raise ExposureRefused(f"{experiment.experiment_id}.{key}: a reading value is finite")
        out.append((key, number))
    return tuple(out)


def blind_laboratory(
    lab: Laboratory,
    *,
    experiments: Mapping[str, ExperimentSpec],
    available: Collection[str] | None = None,
    meter: CostMeter | None = None,
) -> Laboratory:
    """Wrap `lab` so the engine can reach `motivating` and `measure` and nothing else."""
    motivating_fn = lab.motivating
    measure_fn = lab.measure
    allowed = frozenset(available) if available is not None else None
    specs = dict(experiments)

    def motivating() -> tuple[str, Values]:
        experiment_id, values = motivating_fn()
        return experiment_id, _checked(specs[experiment_id], values)

    def measure(experiment_id: str, *, replicate: int, session: int) -> Values:
        if experiment_id not in specs or (allowed is not None and experiment_id not in allowed):
            raise ExposureRefused(f"{experiment_id} cannot be run in this world's laboratory")
        if meter is not None:
            meter.charge(experiment_id)
        values = measure_fn(experiment_id, replicate=replicate, session=session)
        return _checked(specs[experiment_id], values)

    class BlindLaboratory:
        __slots__ = ()

        def motivating(self) -> tuple[str, Values]:
            return motivating()

        def measure(self, experiment_id: str, *, replicate: int, session: int) -> Values:
            return measure(experiment_id, replicate=replicate, session=session)

        def __repr__(self) -> str:
            return "BlindLaboratory()"

    return BlindLaboratory()


def needle_pattern(needle: str) -> re.Pattern[str]:
    """`needle` as a token: not preceded or followed by a letter or digit, case-insensitive. So
    `fcd` is found in "fcd.static" but not inside a hexadecimal digest."""
    return re.compile(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])")


def find_truth_leaks(tree: Any, needles: Iterable[str], path: str = "$") -> list[str]:
    """Paths where a needle occurs as a token (case-insensitively) in a key or a string value."""
    wanted = [(n, needle_pattern(n)) for n in sorted({n.lower() for n in needles if n})]
    found: list[str] = []

    def hit(text: str) -> str | None:
        lowered = text.lower()
        return next((n for n, pattern in wanted if pattern.search(lowered)), None)

    def walk(value: Any, where: str) -> None:
        if isinstance(value, str):
            needle = hit(value)
            if needle is not None:
                found.append(f"{where}: {needle!r}")
        elif isinstance(value, Mapping):
            for key, item in value.items():
                needle = hit(str(key))
                if needle is not None:
                    found.append(f"{where}.{key} (key): {needle!r}")
                walk(item, f"{where}.{key}")
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")

    walk(tree, path)
    return found


__all__ = [
    "CostMeter",
    "ExposureRefused",
    "RealizedCostExceeded",
    "blind_laboratory",
    "find_truth_leaks",
    "needle_pattern",
]
