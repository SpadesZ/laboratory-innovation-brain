"""Predictions and fits: a hypothesis's tabulated forward model against observations.

A hypothesis predicts each experiment entry as the sum over its components of
``amplitude * sensitivity``; the noise model is Gaussian with the entry's declared sigma. A fit is
the box-constrained least-squares amplitude vector over the given observations, its chi-square,
and the chi-square upper-tail p-value with ``n - k`` degrees of freedom (``k`` = components the data
actually constrain; at least one degree of freedom). A component no observation constrains is set
to the middle of its range -- the fit does not care, and a prediction made from it must not lean on
one end of an unexplored range.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lab_brain.discovery.model import ExperimentSpec, Hypothesis, Observation
from lab_brain.discovery.numerics import box_lsq, chi2_sf


@dataclass(frozen=True)
class Fit:
    hypothesis_id: str
    theta: tuple[float, ...]
    chi2: float
    n: int
    dof: int
    p_value: float
    #: For each observation: the largest |standardised residual| over its entries.
    max_abs_z: tuple[tuple[str, float], ...]

    def z_of(self, observation_id: str) -> float:
        return next((z for o, z in self.max_abs_z if o == observation_id), 0.0)


def predict(
    hypothesis: Hypothesis, theta: Sequence[float], experiment: ExperimentSpec
) -> dict[str, float]:
    out = {e.entry_id: 0.0 for e in experiment.entries}
    for component, amplitude in zip(hypothesis.components, theta, strict=True):
        for entry in experiment.entries:
            out[entry.entry_id] += amplitude * component.coefficient(
                experiment.experiment_id, entry.entry_id
            )
    return out


def midpoint_theta(hypothesis: Hypothesis) -> tuple[float, ...]:
    return tuple((c.lower + c.upper) / 2.0 for c in hypothesis.components)


def fit(
    hypothesis: Hypothesis,
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
) -> Fit:
    columns: list[list[float]] = [[] for _ in hypothesis.components]
    y: list[float] = []
    for observation in observations:
        experiment = experiments[observation.experiment_id]
        for entry in experiment.entries:
            y.append(observation.value(entry.entry_id) / entry.sigma)
            for i, component in enumerate(hypothesis.components):
                columns[i].append(
                    component.coefficient(experiment.experiment_id, entry.entry_id) / entry.sigma
                )
    lower = [c.lower for c in hypothesis.components]
    upper = [c.upper for c in hypothesis.components]
    theta_raw, chi2 = box_lsq(columns, y, lower, upper)
    constrained = [any(v != 0.0 for v in column) for column in columns]
    theta = tuple(
        t if used else (c.lower + c.upper) / 2.0
        for t, used, c in zip(theta_raw, constrained, hypothesis.components, strict=True)
    )
    n = len(y)
    k = sum(constrained)
    if n == 0:
        return Fit(hypothesis.hypothesis_id, theta, 0.0, 0, 0, 1.0, ())
    dof = max(1, n - k)
    per_observation: list[tuple[str, float]] = []
    for observation in observations:
        experiment = experiments[observation.experiment_id]
        predicted = predict(hypothesis, theta, experiment)
        worst = max(
            abs(observation.value(e.entry_id) - predicted[e.entry_id]) / e.sigma
            for e in experiment.entries
        )
        per_observation.append((observation.observation_id, worst))
    return Fit(
        hypothesis_id=hypothesis.hypothesis_id,
        theta=theta,
        chi2=chi2,
        n=n,
        dof=dof,
        p_value=chi2_sf(chi2, dof),
        max_abs_z=tuple(per_observation),
    )


def standardized_distance(
    a: Mapping[str, float], b: Mapping[str, float], experiment: ExperimentSpec
) -> float:
    return math.sqrt(
        math.fsum(((a[e.entry_id] - b[e.entry_id]) / e.sigma) ** 2 for e in experiment.entries)
    )


__all__ = ["Fit", "fit", "midpoint_theta", "predict", "standardized_distance"]
