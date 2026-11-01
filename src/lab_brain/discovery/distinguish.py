"""Distinguishability: when an available experiment can separate two hypotheses, and when none can.

THE STATISTIC. For hypotheses A and B and a set of experiments X, the standardised separation is

    sep_X(A, B) = min over a in range(A), b in range(B) of
                  sqrt( sum over X's experiments and entries e of
                        ((mu_A(e; a) - mu_B(e; b)) / sigma_e)^2 )

-- the closest the two forward models can come, in noise units, when each is allowed any amplitude
it declares. It is a WORST case: if some amplitudes make the predictions coincide, no outcome of X
can tell A from B, whatever the truth's amplitude is.

    one experiment, one run       `experiment_separation(A, B, e)`, used for selection and for
                                  "could this test have failed"
    the whole available protocol  `joint_separation(A, B)` = sqrt(R) * sep_available(A, B), with
                                  R the protocol's replication allowance: every available
                                  experiment run R times. A and B are DISTINGUISHABLE iff
                                  this is at least `distinguish_tau`.

INDISTINGUISHABLE HYPOTHESES ARE ONE CLASS. `classes` returns the connected components of the
"indistinguishable" graph over the hypotheses given. A renamed duplicate (identical forward model)
has separation zero from its original and lands in its class; fifty variants that no available
experiment separates from one hypothesis add nothing to the number of classes. Components are the
transitive closure, so a chain A~B~C is one class even if A and C alone could be separated -- the
conservative reading: the loop never claims to have separated what some member of the chain cannot
be separated from. The reason is always the same sentence, and it is recorded: no available
experiment separates them.

Data-independent on purpose. Whether two hypotheses are distinguishable is a property of the
forward models and the experiments this lab can run, never of the data seen so far, so it cannot be
tuned after the fact.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.model import ExperimentSpec, Hypothesis
from lab_brain.discovery.numerics import box_lsq
from lab_brain.discovery.protocol import DiscoveryProtocol

NO_AVAILABLE_EXPERIMENT = "no available experiment separates them"


class SeparationOracle:
    """Separations for one catalog and one set of available experiments. Caches by forward model.

    The cache is instance state keyed by forward-model fingerprints, so the answer for a pair never
    depends on what the hypotheses are called or in which order they were asked about.
    """

    def __init__(
        self,
        catalog: DiscoveryCatalog,
        available: Iterable[str],
        protocol: DiscoveryProtocol,
        unavailable_reasons: Mapping[str, str] | None = None,
    ) -> None:
        available_ids = set(available)
        unknown = available_ids - {e.experiment_id for e in catalog.experiments}
        if unknown:
            raise ValueError(f"experiments {sorted(unknown)} are not declared available")
        self.catalog = catalog
        self.protocol = protocol
        self.available: tuple[ExperimentSpec, ...] = tuple(
            e for e in catalog.experiments if e.experiment_id in available_ids
        )
        reasons = dict(unavailable_reasons or {})
        for u in catalog.unavailable:
            reasons.setdefault(u.experiment.experiment_id, u.reason)
        for e in catalog.experiments:
            if e.experiment_id not in available_ids:
                reasons.setdefault(e.experiment_id, "not available in this setting")
        self.unavailable: tuple[tuple[ExperimentSpec, str], ...] = tuple(
            (catalog.experiment(i), reasons[i]) for i in sorted(reasons)
        )
        self._experiments = {e.experiment_id: e for e in self.available}
        self._single: dict[tuple[str, str, str], float] = {}
        self._joint: dict[tuple[str, str, tuple[str, ...]], float] = {}

    @property
    def experiments(self) -> Mapping[str, ExperimentSpec]:
        return self._experiments

    def _separation(
        self, a: Hypothesis, b: Hypothesis, experiments: Sequence[ExperimentSpec]
    ) -> float:
        columns: list[list[float]] = []
        lower: list[float] = []
        upper: list[float] = []
        for sign, hypothesis in ((1.0, a), (-1.0, b)):
            for component in hypothesis.components:
                column = [
                    sign * component.coefficient(x.experiment_id, e.entry_id) / e.sigma
                    for x in experiments
                    for e in x.entries
                ]
                columns.append(column)
                lower.append(component.lower)
                upper.append(component.upper)
        n = sum(len(x.entries) for x in experiments)
        _, value = box_lsq(columns, [0.0] * n, lower, upper)
        return math.sqrt(value)

    @staticmethod
    def _key(a: Hypothesis, b: Hypothesis) -> tuple[str, str]:
        fa, fb = a.fingerprint, b.fingerprint
        return (fa, fb) if fa <= fb else (fb, fa)

    def experiment_separation(self, a: Hypothesis, b: Hypothesis, experiment_id: str) -> float:
        """One run of one experiment (available or declared-unavailable), worst case."""
        fa, fb = self._key(a, b)
        key = (fa, fb, experiment_id)
        if key not in self._single:
            experiment = self.catalog.experiment(experiment_id)
            self._single[key] = self._separation(a, b, (experiment,))
        return self._single[key]

    def joint_separation(self, a: Hypothesis, b: Hypothesis, extra: Sequence[str] = ()) -> float:
        """The full available protocol (plus `extra` declared experiments), replicated R times."""
        fa, fb = self._key(a, b)
        key = (fa, fb, tuple(sorted(extra)))
        if key not in self._joint:
            experiments = (*self.available, *(self.catalog.experiment(i) for i in sorted(extra)))
            self._joint[key] = math.sqrt(self.protocol.distinguish_replicates) * self._separation(
                a, b, experiments
            )
        return self._joint[key]

    def distinguishable(self, a: Hypothesis, b: Hypothesis) -> bool:
        if a.fingerprint == b.fingerprint:
            return False
        return self.joint_separation(a, b) >= self.protocol.distinguish_tau

    def classes(self, hypotheses: Sequence[Hypothesis]) -> tuple[tuple[str, ...], ...]:
        """Connected components of the indistinguishability graph, deterministic and sorted."""
        ids = sorted({h.hypothesis_id for h in hypotheses})
        by_id = {h.hypothesis_id: h for h in hypotheses}
        parent = {i: i for i in ids}

        def find(i: str) -> str:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for x, first in enumerate(ids):
            for second in ids[x + 1 :]:
                if not self.distinguishable(by_id[first], by_id[second]):
                    ra, rb = find(first), find(second)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
        groups: dict[str, list[str]] = {}
        for i in ids:
            groups.setdefault(find(i), []).append(i)
        return tuple(sorted(tuple(sorted(g)) for g in groups.values()))

    def would_separate(self, a: Hypothesis, b: Hypothesis) -> tuple[tuple[str, str], ...]:
        """Declared unavailable experiments that, added to the available ones, separate a and b."""
        found = []
        for experiment, reason in self.unavailable:
            if (
                self.joint_separation(a, b, (experiment.experiment_id,))
                >= self.protocol.distinguish_tau
            ):
                found.append((experiment.experiment_id, reason))
        return tuple(found)

    def best_separating(self, a: Hypothesis, b: Hypothesis) -> tuple[str | None, float]:
        """The available experiment whose single run separates a and b most, and by how much."""
        best: tuple[str | None, float] = (None, 0.0)
        for experiment in self.available:
            value = self.experiment_separation(a, b, experiment.experiment_id)
            if value > best[1] + 1e-12:
                best = (experiment.experiment_id, value)
        return best


__all__ = ["NO_AVAILABLE_EXPERIMENT", "SeparationOracle"]
