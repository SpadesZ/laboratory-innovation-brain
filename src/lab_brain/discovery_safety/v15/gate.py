"""`safe_investigate_v15`: the v1.4 gate with rival-targeted experiment choice (arm B8).

v1.0-v1.4 are frozen and not edited; this module subclasses the v1.4 gate. Only the choice of the
rival test changes (`SafetyProtocolV15.targeted_selection`):

    expected refutations   for an option (experiment e, n runs) and an open rival R, the
                           probability that R's evaluator prediction FAILS the evaluator's pass
                           test (chi-square of the n-run mean at `alpha`) when the claim is true:
                           the mean of n runs is then distributed around the claim's prediction
                           with variance sigma^2/n + sd_claim^2 per entry, and R's statistic is a
                           scaled noncentral chi-square. The option's value is the sum over open
                           rivals (the expected number of rivals refuted), per unit cost
    registration           the claim (every member) and the rival most likely to fail, for the n
                           runs of e; nothing else is sent to the evaluator (identity, experiment,
                           runs), so the evaluator's boundary is unchanged
    fallback               when no affordable option is expected to refute at least
                           `min_expected_refutations` rivals, B7's choice

The arm decides nothing about SUPPORTED: the evaluator re-derives every verdict from its ledger.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, investigate
from lab_brain.discovery.model import Budget, DiscoveryResult, ExperimentSpec
from lab_brain.discovery.numerics import chi2_sf
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.model import LadderStep, SafeRunV12
from lab_brain.discovery_safety.v12.replay import ReplayLaboratory, run_ladder
from lab_brain.discovery_safety.v13.rule import Prediction
from lab_brain.discovery_safety.v14.gate import _GateV14
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14, EvaluatorRuleV14
from lab_brain.discovery_safety.v15.model import SAFETY_V15, SafetyProtocolV15


@lru_cache(maxsize=64)
def chi2_critical(dof: int, alpha: float) -> float:
    """x with P(chi-square(dof) >= x) = alpha (bisection on the repository's chi2_sf)."""
    lo, hi = 0.0, 10.0 * dof + 100.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if chi2_sf(mid, dof) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def noncentral_chi2_sf(x: float, dof: int, noncentrality: float) -> float:
    """P(X >= x), X ~ noncentral chi-square(dof, lambda): the Poisson mixture of central ones."""
    if noncentrality <= 0.0:
        return chi2_sf(x, dof)
    half = noncentrality / 2.0
    j0 = int(half)
    total = 0.0
    log_half = math.log(half)
    for direction in (range(j0, j0 + 2000), range(j0 - 1, -1, -1)):
        for j in direction:
            w = math.exp(-half + j * log_half - math.lgamma(j + 1))
            total += w * chi2_sf(x, dof + 2 * j)
            if w < 1e-12 and abs(j - half) > 5:
                break
    return min(1.0, max(0.0, total))


def failure_probability(
    claim: Prediction, rival: Prediction, experiment: ExperimentSpec, runs: int, alpha: float
) -> float:
    """P(the rival's prediction fails the chi-square pass test on `runs` runs | the claim is true).

    Per entry the observed mean is N(m_c, s_c^2) with s_c^2 = sigma^2/n + sd_c^2; the rival's z is
    (mean - m_r) / s_r with s_r^2 = sigma^2/n + sd_r^2, so z ~ N((m_c - m_r)/s_r, s_c^2/s_r^2). The
    sum of squares is approximated as v * noncentral chi-square(k, sum mu^2 / v) with v the mean
    variance ratio; the |z| <= z_max part of the pass test is ignored (it can only add failures,
    so the estimate is conservative)."""
    k = 0
    lam = 0.0
    ratios = []
    for e in experiment.entries:
        s_c2 = e.sigma**2 / runs + claim[1].get(e.entry_id, 0.0) ** 2
        s_r2 = e.sigma**2 / runs + rival[1].get(e.entry_id, 0.0) ** 2
        d = claim[0].get(e.entry_id, 0.0) - rival[0].get(e.entry_id, 0.0)
        ratios.append(s_c2 / s_r2)
        lam += d * d / s_r2
        k += 1
    if not k:
        return 0.0
    v = math.fsum(ratios) / k
    return noncentral_chi2_sf(chi2_critical(k, alpha) / v, k, lam / v)


@dataclass
class _GateV15(_GateV14):
    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.safety, SafetyProtocolV15):
            raise TypeError("the v1.5 gate runs under a SafetyProtocolV15")
        self.v15: SafetyProtocolV15 = self.safety

    def rival_test(self) -> str:
        if not self.v15.targeted_selection:
            return super().rival_test()
        rivals = [r for _, _, r in self.open_rivals()]
        if not rivals:
            return "none"
        data = self.data()
        alpha = self.rescorer.rule.alpha
        top = self.v15.max_runs if self.v15.multi_run_tests else 1
        best: tuple[float, int, int, int, ExperimentSpec, int] | None = None
        best_order: list[int] = []
        for e in self.available:
            mine = [self.rescorer.predict(m.fingerprint, data, e) for m in self.members]
            if any(p is None for p in mine) or not mine:
                continue
            theirs = [self._rival_prediction(r, e) for r in rivals]
            for n in range(1, top + 1):
                cost = n * e.cost
                if cost > self.remaining():
                    break
                probs = []
                for p in theirs:
                    if p is None:
                        probs.append(0.0)
                        continue
                    # the rival is refuted only if it fails whichever member is true: the least
                    # favourable member decides
                    probs.append(
                        min(failure_probability(q, p, e, n, alpha) for q in mine if q is not None)
                    )
                expected = math.fsum(probs)
                if expected < self.v15.min_expected_refutations:
                    continue
                key = (-expected / cost, cost, self.declared_order[e.experiment_id])
                if best is None or key < best[:3]:
                    best = (*key, n, e, 0)
                    best_order = sorted(range(len(rivals)), key=lambda i: (-probs[i], i))
        if best is None:
            return super().rival_test()
        lead = [rivals[best_order[0]], *(rivals[i] for i in best_order[1:])]
        return self._close(best[4], best[3], lead)


def safe_investigate_v15(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
    safety: SafetyProtocolV15 = SAFETY_V15,
    grammar: TermGrammar | None = None,
    rule: EvaluatorRuleV14 = EVALUATOR_RULE_V14,
) -> SafeRunV12:
    """The frozen engine on the anytime ladder, then the v1.5 gate (records as v1.2's). Same
    interface as `safe_investigate_v14`."""
    costs = {
        e.experiment_id: e.cost
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }
    replay = ReplayLaboratory(lab, costs, budget.total)
    if safety.anytime_allocation:
        engine, ladder, cap, requested = run_ladder(
            arm=arm,
            catalog=catalog,
            oracle=oracle,
            protocol=protocol,
            budget=budget,
            replay=replay,
            start=safety.ladder_start,
            stop=max(1, int(safety.engine_fraction * budget.total))
            if safety.gate_led
            else budget.total,
        )
    else:
        engine = investigate(
            arm=arm, catalog=catalog, oracle=oracle, protocol=protocol, budget=budget, lab=replay
        )
        cap, requested = budget.total, tuple(replay.requested)
        ladder = (
            LadderStep(
                cap, engine.outcome.value, tuple(engine.claim), engine.spent, replay.charged
            ),
        )
    gate = _GateV15(
        engine,
        catalog,
        oracle,
        protocol,
        safety,
        budget,
        replay,
        replay=replay,
        requested=requested,
        grammar=grammar,
        ladder=ladder,
        engine_cap=cap,
        evaluator_rule=rule,
    )
    return gate.assess_v12()


def safe_runner_v15(
    safety: SafetyProtocolV15 = SAFETY_V15, grammar: TermGrammar | None = None
) -> Callable[..., DiscoveryResult]:
    def runner(**kwargs: object) -> DiscoveryResult:
        return safe_investigate_v15(safety=safety, grammar=grammar, **kwargs).result  # type: ignore[arg-type]

    return runner


__all__ = [
    "chi2_critical",
    "failure_probability",
    "noncentral_chi2_sf",
    "safe_investigate_v15",
    "safe_runner_v15",
]
