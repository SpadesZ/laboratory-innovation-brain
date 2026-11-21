"""The evaluator's rule v1.4: rivals closed only by a failed prediction; grammar rivals.

`RescorerV14` is v1.3's `Rescorer` (identities, the evaluator's own predictions, alternatives and
pass test, unchanged) with the v1.4 rival set; `open_rivals_v14` and `verdict_v14` are the
evaluator's verdict. A rival is named by its IDENTITY (a catalog or grammar fingerprint, or "no
effect"), as a registration is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from lab_brain.discovery.forward import fit
from lab_brain.discovery.model import NULL_HYPOTHESIS, ExperimentSpec, Hypothesis, Observation
from lab_brain.discovery_safety.v12.grammar import CandidateShape
from lab_brain.discovery_safety.v12.ledger import holm_rejections
from lab_brain.discovery_safety.v13.ledger import LedgerEvent, observations_before
from lab_brain.discovery_safety.v13.rule import (
    CATALOG,
    GRAMMAR,
    NULL,
    Prediction,
    RescoredTest,
    Rescorer,
    separation,
    smallest_effect,
)
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14, EvaluatorRuleV14


@dataclass(frozen=True)
class Rival:
    identity: str
    label: str
    kind: str
    #: Fit quality on all the data (lower first: the strongest rival).
    chi2: float


class RescorerV14(Rescorer):
    """v1.3's evaluator with the v1.4 rival set. `available`: the experiments the arm can run in
    this case (grammar rivals must be distinguishable on one of them)."""

    def __init__(
        self,
        catalog_hypotheses: Sequence[Hypothesis],
        shapes: Sequence[CandidateShape],
        experiments: Mapping[str, ExperimentSpec],
        rule: EvaluatorRuleV14 = EVALUATOR_RULE_V14,
        distinguishable: Callable[[Hypothesis, Hypothesis], bool] | None = None,
        available: Sequence[str] = (),
    ) -> None:
        super().__init__(catalog_hypotheses, shapes, experiments, rule, distinguishable)
        self.rule_v14 = rule
        self.available = tuple(a for a in available if a in self.experiments) or tuple(
            self.experiments
        )
        self._rivals: dict[tuple[str, tuple[object, ...]], tuple[Rival, ...]] = {}

    def size(self, identity: str) -> int:
        """Components for the parsimony rule: a grammar shape is one cause."""
        if self.kind(identity) == CATALOG:
            return max(1, len(self.catalog[identity].components))
        return 1

    def _separable(
        self, mine: Mapping[str, Prediction], other: str, data: Sequence[Observation]
    ) -> bool:
        """Whether `other`, at its fit to `data`, is >= tau_risky from `mine` for `max_runs` runs
        of some available experiment."""
        runs = self.rule.max_runs
        for x in self.available:
            experiment = self.experiments[x]
            theirs = self.predict(other, data, experiment)
            if theirs is None:
                continue
            if separation(mine[x], theirs, experiment, runs) >= self.rule.tau_risky:
                return True
        return False

    def rivals_v14(self, identity: str, data: Sequence[Observation]) -> tuple[Rival, ...]:
        """The v1.4 rival set of `identity` on `data` (see `EvaluatorRuleV14`)."""
        key = (identity, self._key(data))
        cached = self._rivals.get(key)
        if cached is not None:
            return cached
        kind = self.kind(identity)
        v = self.viable(data)
        out: list[Rival] = []
        if kind is None:
            self._rivals[key] = ()
            return ()
        if kind != NULL and v.null:
            out.append(Rival(NULL_HYPOTHESIS.fingerprint, NULL_HYPOTHESIS.hypothesis_id, NULL, 0.0))
        size = self.size(identity)
        claim = self.hypothesis(identity)
        mine: dict[str, Prediction] = {}
        for x in self.available:
            p = self.predict(identity, data, self.experiments[x])
            if p is None:
                break
            mine[x] = p
        predictable = len(mine) == len(self.available)
        for h in v.catalog:
            if h.fingerprint == identity or len(h.components) > size:
                continue
            if kind == NULL:
                if smallest_effect(h, next(iter(self.experiments.values()))) is None:
                    continue
                if self.distinguishable is not None and not self.distinguishable(
                    NULL_HYPOTHESIS, h
                ):
                    continue
            elif kind == CATALOG:
                assert claim is not None
                if self.distinguishable is not None and not self.distinguishable(claim, h):
                    continue
            elif not predictable or not self._separable(mine, h.fingerprint, data):
                continue
            out.append(
                Rival(h.fingerprint, h.hypothesis_id, CATALOG, fit(h, data, self.experiments).chi2)
            )
        if self.rule_v14.grammar_rivals and predictable:
            for fitted in v.grammar:
                fp = fitted.shape.fingerprint
                if fp == identity:
                    continue
                if self._separable(mine, fp, data):
                    out.append(Rival(fp, "grammar:" + fitted.shape.shape_id, GRAMMAR, fitted.chi2))
        result = tuple(sorted(out, key=lambda r: (r.chi2, r.label)))
        self._rivals[key] = result
        return result

    def predict_rival(
        self, identity: str, rival: str, data: Sequence[Observation], experiment: ExperimentSpec
    ) -> Prediction | None:
        """How the evaluator predicts a rival in a test of `identity`: a catalog rival of "no
        effect" at its smallest declared effect, every other rival at its own fit to `data`."""
        if rival == NULL_HYPOTHESIS.fingerprint:
            return self.predict(rival, data, experiment)
        if self.kind(identity) == NULL and self.kind(rival) == CATALOG:
            return smallest_effect(self.catalog[rival], experiment)
        return self.predict(rival, data, experiment)


def closed_by(
    rescorer: RescorerV14,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
    rival: str,
) -> int | None:
    """The register index of the first registration that closes `rival` for `identity` (None: open).
    (a) a passed registration of the identity on whose runs the rival's evaluator prediction
    failed; (b) a failed registration of the rival itself."""
    for t in tests:
        if not t.complete:
            continue
        if t.identity == rival and not t.passed:
            return t.register_index
        if t.identity != identity or not t.passed:
            continue
        experiment = rescorer.experiments[t.experiment_id]
        data = observations_before(events, t.register_index)
        theirs = rescorer.predict_rival(identity, rival, data, experiment)
        if theirs is None:
            continue
        observed = [dict(events[i].values) for i in t.measure_indices]
        passed, _, _ = rescorer.score_values(theirs, observed, experiment)
        if not passed:
            return t.register_index
    return None


def open_rivals_v14(
    rescorer: RescorerV14,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
) -> list[Rival]:
    """Rivals on ALL the recorded data that no registration closed (strongest first)."""
    data = observations_before(events, len(events))
    if not rescorer.rule_v14.closure_by_failed_prediction:  # pragma: no cover - v1.3 behaviour
        raise ValueError("v1.4 closes rivals only by a failed prediction")
    return [
        r
        for r in rescorer.rivals_v14(identity, data)
        if closed_by(rescorer, events, tests, identity, r.identity) is None
    ]


@dataclass(frozen=True)
class VerdictV14:
    identity: str
    known: bool
    registered: bool
    risky_pass: bool
    holm_ok: bool
    open_rivals: tuple[str, ...]
    #: Whether the rival check ran (it is skipped when the rest of the verdict already fails).
    rivals_checked: bool = True

    @property
    def supported(self) -> bool:
        return (
            self.known
            and self.risky_pass
            and self.holm_ok
            and self.rivals_checked
            and not self.open_rivals
        )


def verdict_v14(
    rescorer: RescorerV14,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
) -> VerdictV14:
    mine = [t for t in tests if t.identity == identity and t.complete]
    known = rescorer.kind(identity) is not None
    risky_pass = any(t.passed and t.risky for t in mine)
    holm_ok = not any(holm_rejections([t.p_value for t in mine], rescorer.rule.alpha))
    checked = known and risky_pass and holm_ok
    # the rival check is the expensive part; it decides nothing when the rest already fails
    rivals = (
        tuple(sorted(r.label for r in open_rivals_v14(rescorer, events, tests, identity)))
        if checked
        else ()
    )
    return VerdictV14(identity, known, bool(mine), risky_pass, holm_ok, rivals, checked)


__all__ = [
    "GRAMMAR",
    "RescorerV14",
    "Rival",
    "VerdictV14",
    "closed_by",
    "open_rivals_v14",
    "verdict_v14",
]
