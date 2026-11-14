"""The evaluator's rule: every quantity that decides pass and riskiness, computed by the evaluator.

`Rescorer` holds what the evaluator owns -- the identities it can resolve (the arm's catalog at
case start, the declared grammar, "no effect"), the experiment specifications with their
instrument sigmas, and an `EvaluatorRule` -- and scores every REGISTER event of a ledger from the
ledger alone (`rescore`). The rule is public: an arm may apply it to its own copy of what it
measured to anticipate the verdict (the v1.3 gate does), but the evaluator never reads an arm's
computation.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from lab_brain.discovery.forward import fit
from lab_brain.discovery.model import NULL_HYPOTHESIS, ExperimentSpec, Hypothesis, Observation
from lab_brain.discovery.numerics import chi2_sf
from lab_brain.discovery_safety.v12.gate import hypothesis_prediction
from lab_brain.discovery_safety.v12.grammar import (
    CandidateShape,
    FittedShape,
    _invert,
    candidate_classes,
    candidate_hypothesis,
    fit_shape,
    prediction,
)
from lab_brain.discovery_safety.v12.ledger import holm_rejections
from lab_brain.discovery_safety.v13.ledger import (
    MEASURE,
    REGISTER,
    LedgerEvent,
    observations_before,
)
from lab_brain.discovery_safety.v13.model import EVALUATOR_RULE, EvaluatorRule

Prediction = tuple[dict[str, float], dict[str, float]]

CATALOG = "catalog"
GRAMMAR = "grammar"
NULL = "null"


def _zero(experiment: ExperimentSpec) -> Prediction:
    z = {e.entry_id: 0.0 for e in experiment.entries}
    return z, dict(z)


def smallest_effect(h: Hypothesis, experiment: ExperimentSpec) -> Prediction | None:
    """The hypothesis at its smallest declared effect: every amplitude at the bound of its domain
    nearest zero (None if a domain contains zero: no smallest effect is declared)."""
    amplitudes = []
    for c in h.components:
        if c.lower > 0:
            amplitudes.append(c.lower)
        elif c.upper < 0:
            amplitudes.append(c.upper)
        else:
            return None
    mean = {
        e.entry_id: math.fsum(
            a * c.coefficient(experiment.experiment_id, e.entry_id)
            for a, c in zip(amplitudes, h.components, strict=True)
        )
        for e in experiment.entries
    }
    return mean, {e.entry_id: 0.0 for e in experiment.entries}


def separation(a: Prediction, b: Prediction, experiment: ExperimentSpec, runs: int) -> float:
    d2 = 0.0
    for e in experiment.entries:
        scale2 = e.sigma**2 / runs + a[1].get(e.entry_id, 0.0) ** 2 + b[1].get(e.entry_id, 0.0) ** 2
        d = a[0].get(e.entry_id, 0.0) - b[0].get(e.entry_id, 0.0)
        d2 += d * d / scale2
    return math.sqrt(d2)


@dataclass(frozen=True)
class Viable:
    """The alternatives adequate on one data prefix (evaluator's choice)."""

    catalog: tuple[Hypothesis, ...]
    grammar: tuple[FittedShape, ...]
    null: bool


class Rescorer:
    """The evaluator's side: identities, experiments, rule; caches per data prefix."""

    def __init__(
        self,
        catalog_hypotheses: Sequence[Hypothesis],
        shapes: Sequence[CandidateShape],
        experiments: Mapping[str, ExperimentSpec],
        rule: EvaluatorRule = EVALUATOR_RULE,
        distinguishable: Callable[[Hypothesis, Hypothesis], bool] | None = None,
    ) -> None:
        self.rule = rule
        self.distinguishable = distinguishable
        self.experiments = dict(experiments)
        self.catalog = {h.fingerprint: h for h in catalog_hypotheses if not h.is_null}
        self.shapes = {s.fingerprint: s for s in shapes}
        self._viable: dict[tuple[object, ...], Viable] = {}
        self._fits: dict[tuple[str, tuple[object, ...]], FittedShape | None] = {}
        self._designs: dict[str, dict[str, list[tuple[str, tuple[float, ...]]]]] = {}

    # -- identities -----------------------------------------------------------------------------

    def kind(self, identity: str) -> str | None:
        if identity == NULL_HYPOTHESIS.fingerprint:
            return NULL
        if identity in self.catalog:
            return CATALOG
        if identity in self.shapes:
            return GRAMMAR
        return None

    @staticmethod
    def _key(observations: Sequence[Observation]) -> tuple[object, ...]:
        """Content, not ids: the caches are safe to share between ledgers."""
        return tuple((o.experiment_id, o.values) for o in observations)

    def _design(self, shape: CandidateShape) -> dict[str, list[tuple[str, tuple[float, ...]]]]:
        """Per experiment, the entries the shape reads: (entry, x / sigma per term)."""
        design = self._designs.get(shape.fingerprint)
        if design is None:
            coefficient = [{(e, n): c for e, n, c in table} for table in shape.tables]
            design = {}
            for x in self.experiments.values():
                rows = []
                for entry in x.entries:
                    v = tuple(
                        c.get((x.experiment_id, entry.entry_id), 0.0) / entry.sigma
                        for c in coefficient
                    )
                    if any(v):
                        rows.append((entry.entry_id, v))
                design[x.experiment_id] = rows
            self._designs[shape.fingerprint] = design
        return design

    def _plausible(
        self,
        shape: CandidateShape,
        data: Sequence[Observation],
        scaled: Sequence[dict[str, float]],
        yy: float,
        rows: int,
    ) -> bool:
        """A cheap pre-screen of the global adequacy test from the normal equations: False only
        when the shape is certainly unfit (unconstrained, or its chi-square p-value is below half
        of alpha_adequacy); survivors are refitted exactly by `fit_shape`."""
        design = self._design(shape)
        k = len(shape.tables)
        xtx = [[0.0] * k for _ in range(k)]
        xty = [0.0] * k
        for o, y in zip(data, scaled, strict=True):
            for entry_id, v in design[o.experiment_id]:
                yv = y[entry_id]
                for i in range(k):
                    xty[i] += v[i] * yv
                    for j in range(k):
                        xtx[i][j] += v[i] * v[j]
        if any(xtx[i][i] <= 1e-12 for i in range(k)):
            return False
        inverse = _invert(xtx)
        if inverse is None:
            return True
        theta = [sum(inverse[i][j] * xty[j] for j in range(k)) for i in range(k)]
        chi2 = max(0.0, yy - sum(t * b for t, b in zip(theta, xty, strict=True)))
        return chi2_sf(chi2, max(1, rows - k)) >= 0.5 * self.rule.alpha_adequacy

    def _fit_shape(self, shape: CandidateShape, data: Sequence[Observation]) -> FittedShape | None:
        key = (shape.fingerprint, self._key(data))
        if key not in self._fits:
            self._fits[key] = fit_shape(shape, data, self.experiments)
        return self._fits[key]

    def predict(
        self, identity: str, data: Sequence[Observation], experiment: ExperimentSpec
    ) -> Prediction | None:
        """The identity's predictive distribution for ONE run of `experiment`, refitted by the
        evaluator to `data` (None: the identity predicts nothing there)."""
        kind = self.kind(identity)
        if kind == NULL:
            return _zero(experiment)
        if kind == CATALOG:
            return hypothesis_prediction(self.catalog[identity], data, self.experiments, experiment)
        if kind == GRAMMAR:
            fitted = self._fit_shape(self.shapes[identity], data)
            return None if fitted is None else prediction(fitted, experiment)
        return None

    def adequate(self, h: Hypothesis, data: Sequence[Observation]) -> bool:
        """The global adequacy test, tolerant of ONE aberrant reading: adequate on the data, or on
        the data without its single worst-fitting observation (one unreplicated reading cannot by
        itself rule an explanation out)."""
        r = self.rule
        f = fit(h, data, self.experiments)
        worst_id, worst = "", 0.0
        for observation_id, z in f.max_abs_z:
            if z > worst:
                worst_id, worst = observation_id, z
        if f.p_value >= r.alpha_adequacy and worst <= r.z_adequacy:
            return True
        rest = [o for o in data if o.observation_id != worst_id]
        if not rest or len(rest) == len(data):
            return False
        g = fit(h, rest, self.experiments)
        return g.p_value >= r.alpha_adequacy and all(z <= r.z_adequacy for _, z in g.max_abs_z)

    def viable(self, data: Sequence[Observation]) -> Viable:
        key = self._key(data)
        if key in self._viable:
            return self._viable[key]
        r = self.rule
        catalog = [h for h in self.catalog.values() if self.adequate(h, data)]
        scaled = [
            {
                e.entry_id: o.value(e.entry_id) / e.sigma
                for e in self.experiments[o.experiment_id].entries
            }
            for o in data
        ]
        yy = math.fsum(v * v for y in scaled for v in y.values())
        rows = sum(len(y) for y in scaled)
        grammar = []
        for shape in self.shapes.values():
            if not self._plausible(shape, data, scaled, yy, rows):
                continue
            fitted = self._fit_shape(shape, data)
            if (
                fitted is not None
                and fitted.p_value >= r.alpha_adequacy
                and fitted.max_abs_z <= r.z_adequacy
            ):
                grammar.append(fitted)
        out = Viable(tuple(catalog), tuple(grammar), self.adequate(NULL_HYPOTHESIS, data))
        self._viable[key] = out
        return out

    def alternatives(
        self, identity: str, data: Sequence[Observation], experiment: ExperimentSpec
    ) -> list[tuple[str, Prediction]]:
        v = self.viable(data)
        out: list[tuple[str, Prediction]] = []
        if self.kind(identity) == NULL:
            for h in v.catalog:
                p = smallest_effect(h, experiment)
                if p is not None:
                    out.append((h.fingerprint, p))
            return out
        for h in v.catalog:
            if h.fingerprint != identity:
                out.append(
                    (h.fingerprint, hypothesis_prediction(h, data, self.experiments, experiment))
                )
        for fitted in v.grammar:
            if fitted.shape.fingerprint != identity:
                out.append((fitted.shape.fingerprint, prediction(fitted, experiment)))
        if v.null:
            out.append((NULL_HYPOTHESIS.fingerprint, _zero(experiment)))
        return out

    def risk(
        self, identity: str, data: Sequence[Observation], experiment: ExperimentSpec, runs: int
    ) -> tuple[float, str]:
        """The largest separation of the identity's prediction from an evaluator alternative, and
        which alternative it is (0, "") when the identity predicts nothing or none is viable."""
        mine = self.predict(identity, data, experiment)
        if mine is None:
            return 0.0, ""
        best, label = 0.0, ""
        for name, other in self.alternatives(identity, data, experiment):
            s = separation(mine, other, experiment, runs)
            if s > best or (s == best and name < label):
                best, label = s, name
        return best, label

    def hypothesis(self, identity: str) -> Hypothesis | None:
        if self.kind(identity) == NULL:
            return NULL_HYPOTHESIS
        return self.catalog.get(identity)

    def rivals(self, identity: str, data: Sequence[Observation]) -> list[Hypothesis]:
        """The alternatives a SUPPORTED answer must have been put at risk against: "no effect" if it
        is viable (one-outlier tolerant), and every catalog hypothesis that is viable, has no more
        components than the answer (a "no effect" answer: single hypotheses) and is
        distinguishable from it under the full experiment set. A grammar answer is held against
        "no effect" only (a grammar shape has no declared domain to judge distinguishability)."""
        v = self.viable(data)
        kind = self.kind(identity)
        out: list[Hypothesis] = []
        if kind != NULL and v.null:
            out.append(NULL_HYPOTHESIS)
        claim = self.hypothesis(identity)
        if kind == GRAMMAR or claim is None:
            return out
        size = max(1, len(claim.components))
        for h in v.catalog:
            if h.fingerprint == identity or len(h.components) > size:
                continue
            if kind == NULL and smallest_effect(h, next(iter(self.experiments.values()))) is None:
                continue
            if self.distinguishable is not None and not self.distinguishable(claim, h):
                continue
            out.append(h)
        return sorted(out, key=lambda h: h.hypothesis_id)

    def rival_prediction(
        self,
        identity: str,
        rival: Hypothesis,
        data: Sequence[Observation],
        experiment: ExperimentSpec,
    ) -> Prediction | None:
        """How the evaluator predicts a rival in a test of `identity`: at its smallest declared
        effect when the identity is "no effect", else at its own fit to the earlier data."""
        if rival.is_null:
            return _zero(experiment)
        if self.kind(identity) == NULL:
            return smallest_effect(rival, experiment)
        return self.predict(rival.fingerprint, data, experiment)

    def score_values(
        self,
        mine: Prediction,
        observed: Sequence[Mapping[str, float]],
        experiment: ExperimentSpec,
    ) -> tuple[bool, float, float]:
        """(passed, p, max |z|) of a prediction against the mean of `observed` runs."""
        n = len(observed)
        chi2 = 0.0
        worst = 0.0
        for e in experiment.entries:
            mean = math.fsum(o[e.entry_id] for o in observed) / n
            scale = math.sqrt(e.sigma**2 / n + mine[1].get(e.entry_id, 0.0) ** 2)
            z = (mean - mine[0].get(e.entry_id, 0.0)) / scale
            chi2 += z * z
            worst = max(worst, abs(z))
        p = chi2_sf(chi2, len(experiment.entries))
        return p >= self.rule.alpha and worst <= self.rule.z_max, p, worst

    def answer_hypothesis(
        self, identity: str, events: Sequence[LedgerEvent], label: str
    ) -> Hypothesis | None:
        """A new-mechanism answer as the evaluator reconstructs it: the grammar shape the identity
        names, refitted to ALL the recorded data, with the rule's declared band."""
        if self.kind(identity) != GRAMMAR:
            return None
        data = observations_before(events, len(events))
        fitted = fit_shape(self.shapes[identity], data, self.experiments)
        if fitted is None:
            return None
        classes = candidate_classes(fitted, self.rule.candidate_band, label)
        return None if classes is None else candidate_hypothesis(classes)


@dataclass(frozen=True)
class RescoredTest:
    register_index: int
    identity: str
    kind: str
    experiment_id: str
    runs: int
    #: The MEASURE events scored (the next `runs` runs of the experiment after the registration).
    measure_indices: tuple[int, ...]
    complete: bool
    passed: bool
    risky: bool
    p_value: float
    max_abs_z: float
    risk: float
    against: str
    #: Why it supports nothing, if so: "", UNKNOWN_IDENTITY, NO_PREDICTION, INCOMPLETE,
    #: RUNS_OUT_OF_RANGE
    void: str
    declared_digest_matches: bool | None
    #: Rivals (`Rescorer.rivals` at registration time) this test separated from the identity by at
    #: least tau_risky.
    separated: tuple[str, ...] = ()


def rescore(rescorer: Rescorer, events: Sequence[LedgerEvent]) -> list[RescoredTest]:
    """Every REGISTER event, scored by the evaluator from the ledger alone."""
    out = []
    for event in events:
        if event.kind != REGISTER:
            continue
        declared = (
            None
            if not event.declared_data_digest
            else event.declared_data_digest == event.data_digest
        )
        experiment = rescorer.experiments.get(event.experiment_id)
        kind = rescorer.kind(event.identity)
        targets = [
            e
            for e in events[event.index + 1 :]
            if e.kind == MEASURE and e.experiment_id == event.experiment_id
        ][: event.runs]

        def void(
            reason: str,
            event: LedgerEvent = event,
            kind: str | None = kind,
            targets: Sequence[LedgerEvent] = targets,
            declared: bool | None = declared,
        ) -> RescoredTest:
            return RescoredTest(
                event.index,
                event.identity,
                kind or "",
                event.experiment_id,
                event.runs,
                tuple(t.index for t in targets),
                False,
                False,
                False,
                0.0,
                0.0,
                0.0,
                "",
                reason,
                declared,
            )

        if kind is None or experiment is None:
            out.append(void("UNKNOWN_IDENTITY"))
            continue
        if not 1 <= event.runs <= rescorer.rule.max_runs:
            out.append(void("RUNS_OUT_OF_RANGE"))
            continue
        if len(targets) < event.runs:
            out.append(void("INCOMPLETE"))
            continue
        data = observations_before(events, event.index)
        mine = rescorer.predict(event.identity, data, experiment)
        if mine is None:
            out.append(void("NO_PREDICTION"))
            continue
        passed, p, worst = rescorer.score_values(
            mine, [dict(t.values) for t in targets], experiment
        )
        risk, against = rescorer.risk(event.identity, data, experiment, event.runs)
        separated = []
        for rival in rescorer.rivals(event.identity, data):
            theirs = rescorer.rival_prediction(event.identity, rival, data, experiment)
            if theirs is not None and (
                separation(mine, theirs, experiment, event.runs) >= rescorer.rule.tau_risky
            ):
                separated.append(rival.fingerprint)
        out.append(
            RescoredTest(
                event.index,
                event.identity,
                kind,
                event.experiment_id,
                event.runs,
                tuple(t.index for t in targets),
                True,
                passed,
                risk >= rescorer.rule.tau_risky,
                p,
                worst,
                risk,
                against,
                "",
                declared,
                tuple(separated),
            )
        )
    return out


def open_rivals(
    rescorer: Rescorer,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
) -> list[Hypothesis]:
    """Rivals still viable on ALL the recorded data that no passed registration of the identity
    separated from it, and whose own registration never failed."""
    data = observations_before(events, len(events))
    closed: set[str] = set()
    for t in tests:
        if t.identity == identity and t.complete and t.passed:
            closed.update(t.separated)
    return [
        h
        for h in rescorer.rivals(identity, data)
        if h.fingerprint not in closed and not refuted(tests, h.fingerprint)
    ]


@dataclass(frozen=True)
class Verdict:
    """The evaluator's evidential verdict on one answered identity."""

    identity: str
    known: bool
    registered: bool
    risky_pass: bool
    holm_ok: bool
    open_rivals: tuple[str, ...]

    @property
    def supported(self) -> bool:
        return self.known and self.risky_pass and self.holm_ok and not self.open_rivals


def verdict(
    rescorer: Rescorer,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
) -> Verdict:
    mine = [t for t in tests if t.identity == identity and t.complete]
    known = rescorer.kind(identity) is not None
    return Verdict(
        identity=identity,
        known=known,
        registered=bool(mine),
        risky_pass=any(t.passed and t.risky for t in mine),
        holm_ok=not any(holm_rejections([t.p_value for t in mine], rescorer.rule.alpha)),
        open_rivals=tuple(
            sorted(h.hypothesis_id for h in open_rivals(rescorer, events, tests, identity))
        )
        if known
        else (),
    )


def supported(tests: Sequence[RescoredTest], identity: str, alpha: float) -> bool:
    """The registration part of the rule: a complete registration of the identity passed and is
    risky, and Holm over all its complete registrations at family-wise `alpha` rejects none. The
    full evidential verdict (`verdict`) also needs no open rival."""
    mine = [t for t in tests if t.identity == identity and t.complete]
    if not any(t.passed and t.risky for t in mine):
        return False
    return not any(holm_rejections([t.p_value for t in mine], alpha))


def refuted(tests: Sequence[RescoredTest], identity: str) -> bool:
    """A complete registration of the identity failed the rule (its own prediction was wrong)."""
    return any(t.identity == identity and t.complete and not t.passed for t in tests)


__all__ = [
    "CATALOG",
    "GRAMMAR",
    "NULL",
    "RescoredTest",
    "Rescorer",
    "Verdict",
    "Viable",
    "open_rivals",
    "refuted",
    "rescore",
    "separation",
    "smallest_effect",
    "supported",
    "verdict",
]
