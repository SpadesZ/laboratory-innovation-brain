"""VER-008: disagreement metrics are declared, versioned, bound to an OutcomeSpace, deterministic.

    VER-008  Any DisagreementMetric used for verification ranking MUST be bound to a declared
             OutcomeSpace, MUST carry a version, and MUST be deterministic: identical input plus
             identical metric version MUST yield an identical result. Core MUST NOT hard-code one
             universal distance.
    §9.2     排序依據為：1 能否改變決策 2 預測分歧程度（DomainPack 宣告的 disagreement metric）...

DETERMINISM BY CONSTRUCTION, NOT BY PROMISE. A declared OutcomeSpace is a FINITE tuple of outcomes,
so a metric over it is a finite table. The registry evaluates the domain's implementation over every
pair of admitted outcomes at registration -- twice -- and refuses it if the two passes disagree, if
a value is not a finite non-negative Decimal, if d(x, x) is not zero, or if d(x, y) != d(y, x). What
it keeps is the TABLE. Every later ranking reads the table and never calls the implementation again,
so "identical input plus identical metric version yields an identical result" cannot fail at use
time: there is nothing left that could vary.

CORE SHIPS NO METRIC. The registry starts empty and core defines no implementation; a DomainPack
registers one through §24.3's `register_disagreement_metrics`. `tests/unit/test_disagreement_
metrics.py` parses `lab_brain.core` and `lab_brain.verification` and fails if either defines a
metric implementation -- "Core does not hard-code one universal distance" (§9.1).

THE PREDICTION VOCABULARY. A Prediction names an observable (`observable_ref`) and the declared
OutcomeSpace its outcome is read in; the planner matches the observable EXACTLY against what a
Capability produces. So which observable is read in which space is a DomainPack declaration too
(`declare_observable`), made beside the spaces: one space per observable, the space declared first.
It is what the Hypothesis Engine is shown and what its parser admits -- nothing derives an
observable from a space id, and nothing restricts it to the backends installed here: a prediction
over a simulation nobody can run yet is still a prediction.

WHAT THE RANKING DOES AND DOES NOT DECIDE. `rank_by_disagreement` orders candidate actions by how
far apart the surviving hypotheses' AFFIRMATIVE forecasts over the action's observable are, under
the metric the domain declared for that OutcomeSpace. It does not decide sufficiency (§9.1,
VER-006's `evaluate_sufficiency` does, over EVERY typed prediction, falsifiers included), Pareto
dominance or the SelectionPolicy (VER-005, M4). It is §9.2's second criterion, and an action whose
observable has no declared metric is ranked AFTER every action that has one, with its disagreement
reported as unknown rather than zero.

AFFIRMATIVE FORECASTS ONLY. A hypothesis forecasts an outcome with a SUPPORTS or PREDICTS
prediction. A CONTRADICTS prediction is its predeclared FALSIFYING outcome -- what would refute it,
not what it expects -- and every admitted certificate carries one; TESTS alone says only that an
outcome bears on it. So a prediction is a forecast only when it declares SUPPORTS or PREDICTS and no
CONTRADICTS (`is_affirmative_forecast`); one CONTRADICTS among several effects makes it a
falsifier. Nothing is inferred from what a hypothesis does not declare. Per observable and
OutcomeSpace version, each rival's forecasts are the SET of outcomes it affirms (duplicates
collapse), and:

    fewer than two rivals forecast        unknown (None)
    every rival's set is the same         0 -- identical forecasts do not disagree, however many
    every rival forecasts one outcome     the declared metric, pairwise, the maximum over rivals
    otherwise (several outcomes, unequal) unknown: the domain declares a distance between outcomes,
                                          not between sets of them, and core invents none -- no
                                          Cartesian maximum, average or set metric
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from lab_brain.core.models.benchmark import DisagreementMetric
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.prediction import OutcomeSpace, Prediction


class DisagreementMetricError(ValueError):
    """A metric is undeclared, unbound, unversioned or not deterministic -- or was misapplied."""


@runtime_checkable
class DisagreementMetricImplementation(Protocol):
    """What a DomainPack supplies: the declaration, and the distance it declares."""

    @property
    def declaration(self) -> DisagreementMetric: ...

    def distance(self, a: str, b: str) -> Decimal: ...


@dataclass(frozen=True)
class TabulatedMetric:
    """A registered metric, frozen as the table of its values over the declared outcomes."""

    declaration: DisagreementMetric
    outcome_space: OutcomeSpace
    table: tuple[tuple[str, str, Decimal], ...]

    @property
    def ref(self) -> str:
        return self.declaration.ref

    def distance(self, a: str, b: str) -> Decimal:
        for x, y, value in self.table:
            if (x, y) == (a, b):
                return value
        raise DisagreementMetricError(
            f"metric {self.ref} is defined over {self.outcome_space.ref}'s admitted outcomes "
            f"{sorted(_admitted(self.outcome_space))}; ({a!r}, {b!r}) is outside it. VER-004: an "
            "outcome that is merely imaginable is not in the space"
        )


def _admitted(space: OutcomeSpace) -> tuple[str, ...]:
    return tuple(o for o in space.outcomes if space.admits(o))


class DisagreementMetricRegistry:
    """Declared OutcomeSpaces and the metrics bound to them. Empty until a DomainPack writes."""

    def __init__(self) -> None:
        self._spaces: dict[tuple[str, str], OutcomeSpace] = {}
        self._metrics: dict[tuple[str, str], TabulatedMetric] = {}
        self._observables: dict[str, tuple[str, str]] = {}

    # -- outcome spaces -------------------------------------------------------------------------

    def declare_space(self, space: OutcomeSpace) -> OutcomeSpace:
        key = (space.outcome_space_id, space.version)
        existing = self._spaces.get(key)
        if existing is not None and existing != space:
            raise DisagreementMetricError(
                f"outcome space {space.ref} is already declared with different membership; a "
                "changed space is a new version"
            )
        self._spaces[key] = space
        return space

    def outcome_space(self, outcome_space_id: str, version: str) -> OutcomeSpace | None:
        return self._spaces.get((outcome_space_id, version))

    def declared_spaces(self) -> tuple[OutcomeSpace, ...]:
        return tuple(self._spaces[k] for k in sorted(self._spaces))

    # -- the prediction vocabulary --------------------------------------------------------------

    def declare_observable(
        self, observable_ref: str, outcome_space_id: str, version: str
    ) -> OutcomeSpace:
        """Declare that predictions over `observable_ref` are read in this declared space."""
        if not observable_ref.strip() or observable_ref != observable_ref.strip():
            raise DisagreementMetricError(
                f"observable {observable_ref!r} is not a canonical identifier"
            )
        space = self._spaces.get((outcome_space_id, version))
        if space is None:
            raise DisagreementMetricError(
                f"observable {observable_ref} is bound to outcome space {outcome_space_id}@"
                f"{version}, which has not been declared; declare the space first"
            )
        existing = self._observables.get(observable_ref)
        if existing is not None and existing != (outcome_space_id, version):
            raise DisagreementMetricError(
                f"observable {observable_ref} is already read in {existing[0]}@{existing[1]}; one "
                "observable is read in one space, or a prediction's binding would be two facts"
            )
        self._observables[observable_ref] = (outcome_space_id, version)
        return space

    def observable_bindings(self, domain: str | None = None) -> dict[str, OutcomeSpace]:
        """observable_ref -> the declared space it is read in; a domain's alone if one is named."""
        bound = {o: self._spaces[key] for o, key in sorted(self._observables.items())}
        return {o: s for o, s in bound.items() if domain is None or s.domain == domain}

    # -- metrics --------------------------------------------------------------------------------

    def register(self, implementation: DisagreementMetricImplementation) -> TabulatedMetric:
        if not isinstance(implementation, DisagreementMetricImplementation):
            raise DisagreementMetricError(
                f"{implementation!r} does not expose a DisagreementMetric declaration and a "
                "distance; VER-008 ranks only by a declared metric"
            )
        declaration = implementation.declaration
        space = self._spaces.get((declaration.outcome_space_id, declaration.outcome_space_version))
        if space is None:
            raise DisagreementMetricError(
                f"metric {declaration.ref} is bound to outcome space "
                f"{declaration.outcome_space_ref}, which has not been declared. VER-008: a metric "
                "MUST be bound to a DECLARED OutcomeSpace"
            )
        key = (declaration.metric_id, declaration.version)
        existing = self._metrics.get(key)
        table = self._tabulate(implementation, space)
        if existing is not None:
            if existing.table != table or existing.declaration != declaration:
                raise DisagreementMetricError(
                    f"metric {declaration.ref} is already registered with different values; a "
                    "changed metric is a new version, or identical input under one version would "
                    "stop yielding an identical result"
                )
            return existing
        tabulated = TabulatedMetric(declaration=declaration, outcome_space=space, table=table)
        self._metrics[key] = tabulated
        return tabulated

    def metric(self, metric_id: str, version: str) -> TabulatedMetric:
        found = self._metrics.get((metric_id, version))
        if found is None:
            raise DisagreementMetricError(f"no disagreement metric {metric_id}@{version}")
        return found

    def for_space(self, outcome_space_id: str, version: str) -> TabulatedMetric | None:
        """The metric declared for one OutcomeSpace version, or `None` if the domain declared none.

        More than one metric for one space is refused at lookup: a ranking that silently picked one
        of two would make the answer depend on registration order.
        """
        bound = [
            m
            for m in self._metrics.values()
            if (m.declaration.outcome_space_id, m.declaration.outcome_space_version)
            == (outcome_space_id, version)
        ]
        if len(bound) > 1:
            raise DisagreementMetricError(
                f"outcome space {outcome_space_id}@{version} has {len(bound)} metrics "
                f"({sorted(m.ref for m in bound)}); ranking needs the one the domain declared"
            )
        return bound[0] if bound else None

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(m.ref for m in self._metrics.values()))

    def __len__(self) -> int:
        return len(self._metrics)

    @staticmethod
    def _tabulate(
        implementation: DisagreementMetricImplementation, space: OutcomeSpace
    ) -> tuple[tuple[str, str, Decimal], ...]:
        """Evaluate every pair twice; refuse anything that is not a deterministic distance."""
        ref = implementation.declaration.ref
        outcomes = _admitted(space)
        rows: list[tuple[str, str, Decimal]] = []
        for a, b in itertools.product(outcomes, repeat=2):
            first = implementation.distance(a, b)
            second = implementation.distance(a, b)
            if not isinstance(first, Decimal) or not isinstance(second, Decimal):
                raise DisagreementMetricError(
                    f"metric {ref} returned {type(first).__name__} for ({a!r}, {b!r}); a Decimal "
                    "is "
                    "required so the value is exact and reproducible across platforms"
                )
            if first != second:
                raise DisagreementMetricError(
                    f"metric {ref} returned {first} and then {second} for ({a!r}, {b!r}). VER-008: "
                    "identical input under one version MUST yield an identical result"
                )
            if not first.is_finite() or first < 0:
                raise DisagreementMetricError(
                    f"metric {ref} returned {first} for ({a!r}, {b!r}); a disagreement is a "
                    "finite, "
                    "non-negative quantity"
                )
            if a == b and first != 0:
                raise DisagreementMetricError(
                    f"metric {ref} reports {first} disagreement between {a!r} and itself"
                )
            rows.append((a, b, first))
        values = {(a, b): v for a, b, v in rows}
        asymmetric = sorted((a, b) for (a, b), v in values.items() if values[(b, a)] != v)
        if asymmetric:
            raise DisagreementMetricError(
                f"metric {ref} is not symmetric on {asymmetric[:3]}; the disagreement between two "
                "predictions cannot depend on which one is listed first"
            )
        return tuple(sorted(rows))


#: The effects that state an affirmative forecast: the outcome the hypothesis says will be observed.
AFFIRMATIVE_EFFECTS = frozenset({RelationType.SUPPORTS, RelationType.PREDICTS})


def is_affirmative_forecast(prediction: Prediction) -> bool:
    """SUPPORTS or PREDICTS, and no CONTRADICTS: a falsifier is never a forecast, whatever else it
    declares, and TESTS alone forecasts nothing."""
    effects = {effect.relation_type for effect in prediction.relation_effect_if_observed}
    return RelationType.CONTRADICTS not in effects and bool(effects & AFFIRMATIVE_EFFECTS)


@dataclass(frozen=True)
class RankedAction:
    """One candidate action, and how far apart the rivals' affirmative forecasts over it are."""

    capability_id: str
    observable_ref: str
    #: `None` -- unknown, not zero -- when no metric is declared for the OutcomeSpace, fewer than
    #: two hypotheses forecast an outcome over this observable, or rivals forecast unequal SETS of
    #: outcomes (no set distance is declared).
    disagreement: Decimal | None
    metric_ref: str | None
    outcome_space_ref: str | None
    #: (hypothesis_id, forecast outcome) pairs the disagreement was computed from -- affirmative
    #: forecasts only.
    predictions: tuple[tuple[str, str], ...]


def forecast_disagreement(
    forecasts: Mapping[str, frozenset[str]], metric: TabulatedMetric
) -> Decimal | None:
    """The disagreement between rivals' affirmative forecast sets (hypothesis -> outcomes), under
    `metric`. See the module docstring for the four cases; `None` is unknown, never zero."""
    if len(forecasts) < 2:
        return None
    sets = [forecasts[h] for h in sorted(forecasts)]
    if all(s == sets[0] for s in sets):
        return Decimal(0)
    if any(len(s) != 1 for s in sets):
        return None
    single = [next(iter(s)) for s in sets]
    return max(metric.distance(a, b) for a, b in itertools.combinations(single, 2))


def rank_by_disagreement(
    candidates: Sequence[tuple[str, Sequence[str]]],
    predictions: Sequence[Prediction],
    metrics: DisagreementMetricRegistry,
) -> tuple[RankedAction, ...]:
    """§9.2's second criterion over ``candidates`` -- (capability_id, produces) pairs.

    Deterministic: the disagreement is `forecast_disagreement` over each rival's affirmative
    forecasts (an action discriminates if it separates any two rivals' forecasts), and the order is
    (disagreement descending, unknowns last, capability id, observable). An observable with
    predictions but no forecast -- falsifiers only -- is still listed, with its disagreement
    unknown. No clock, no randomness, no call into the domain implementation.
    """
    ranked: list[RankedAction] = []
    for capability_id, produces in candidates:
        for observable in sorted(produces):
            over = [p for p in predictions if p.observable_ref == observable]
            if not over:
                continue
            by_space: dict[tuple[str, str], list[Prediction]] = {}
            for p in over:
                by_space.setdefault((p.outcome_space_id, p.outcome_space_version), []).append(p)
            for (space_id, space_version), group in sorted(by_space.items()):
                forecasts: dict[str, set[str]] = {}
                for p in group:
                    if is_affirmative_forecast(p):
                        forecasts.setdefault(p.hypothesis_id, set()).add(p.expected_outcome)
                metric = metrics.for_space(space_id, space_version)
                ranked.append(
                    RankedAction(
                        capability_id=capability_id,
                        observable_ref=observable,
                        disagreement=None
                        if metric is None
                        else forecast_disagreement(
                            {h: frozenset(o) for h, o in forecasts.items()}, metric
                        ),
                        metric_ref=None if metric is None else metric.ref,
                        outcome_space_ref=f"{space_id}@{space_version}",
                        predictions=tuple(
                            sorted((h, o) for h, outcomes in forecasts.items() for o in outcomes)
                        ),
                    )
                )
    return tuple(
        sorted(
            ranked,
            key=lambda r: (
                r.disagreement is None,
                -(r.disagreement or Decimal(0)),
                r.capability_id,
                r.observable_ref,
                r.outcome_space_ref or "",
            ),
        )
    )


__all__ = [
    "AFFIRMATIVE_EFFECTS",
    "DisagreementMetricError",
    "DisagreementMetricImplementation",
    "DisagreementMetricRegistry",
    "RankedAction",
    "TabulatedMetric",
    "forecast_disagreement",
    "is_affirmative_forecast",
    "rank_by_disagreement",
]
