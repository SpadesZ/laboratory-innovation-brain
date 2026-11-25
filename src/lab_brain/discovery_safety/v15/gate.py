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
from lab_brain.discovery_safety.model import ProbePurpose
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.model import LadderStep, SafeRunV12
from lab_brain.discovery_safety.v12.replay import ReplayLaboratory, run_ladder
from lab_brain.discovery_safety.v13.rule import Prediction
from lab_brain.discovery_safety.v14.gate import _GateV14
from lab_brain.discovery_safety.v14.model import EVALUATOR_RULE_V14, EvaluatorRuleV14
from lab_brain.discovery_safety.v14.rule import Rival
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
    # far in the tail of the mixture: certain failure / central behaviour (|error| < 1e-9)
    if math.sqrt(noncentrality) - math.sqrt(x) > 9.0:
        return 1.0
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

    # -- the rival-targeted choice --------------------------------------------------------------

    def targeted_option(self) -> tuple[ExperimentSpec, int, list[Rival], float] | None:
        """(experiment, runs, rivals most-likely-to-fail first, expected refutations) of the
        affordable option with the most expected refutations per unit cost, or None when no
        option reaches `min_expected_refutations` (or nothing is open)."""
        rivals = [r for _, _, r in self.open_rivals()]
        if not rivals or not self.members:
            return None
        data = self.data()
        alpha = self.rescorer.rule.alpha
        top = self.v15.max_runs if self.v15.multi_run_tests else 1
        best: tuple[tuple[float, int, int], ExperimentSpec, int, list[float], float] | None = None
        for e in self.available:
            if e.cost > self.remaining():
                continue
            mine = [self.rescorer.predict(m.fingerprint, data, e) for m in self.members]
            if any(p is None for p in mine):
                continue
            claims = [p for p in mine if p is not None]
            theirs = [self._rival_prediction(r, e) for r in rivals]
            for n in range(1, top + 1):
                cost = n * e.cost
                if cost > self.remaining():
                    break
                cache: dict[tuple[object, ...], float] = {}
                probs = []
                for p in theirs:
                    if p is None:
                        probs.append(0.0)
                        continue
                    key = _key(p)
                    if key not in cache:
                        # a rival is refuted only if it fails whichever member is true: the least
                        # favourable member decides
                        cache[key] = min(failure_probability(q, p, e, n, alpha) for q in claims)
                    probs.append(cache[key])
                expected = math.fsum(probs)
                if expected < self.v15.min_expected_refutations:
                    continue
                rank = (-expected / cost, cost, self.declared_order[e.experiment_id])
                if best is None or rank < best[0]:
                    best = (rank, e, n, probs, expected)
        if best is None:
            return None
        _, e, n, probs, expected = best
        order = sorted(range(len(rivals)), key=lambda i: (-probs[i], i))
        return e, n, [rivals[i] for i in order], expected

    def rival_test(self) -> str:
        if not self.v15.targeted_selection:
            return super().rival_test()
        option = self.targeted_option()
        if option is None:
            return super().rival_test()
        e, n, rivals, _ = option
        return self._close(e, n, rivals)

    def probe_fixpoint(self) -> bool | None:
        """v1.2's probe fixpoint (`_GateV12.probe_fixpoint`) with one phase added in FRONT of the
        signal probes (`rival_first`): while a rival-targeted option is expected to refute at
        least `min_expected_refutations` open rivals and fewer than `max_rival_tests` rival tests
        have run, run it. Development showed B7 spending its whole budget at small caps on the
        fixed-order signal probes, leaving refutable rivals untested. The signal probes, the
        support test, the rival tests and the null probes follow as in v1.2 (sharing one rival
        test count)."""
        if not self.v15.rival_first:
            return super().probe_fixpoint()
        self.initial_signals = self.recompute_signals()
        self.deferring = (
            self.safety.probes and self.v11.localized_check and self.v11.defer_localized_replication
        )
        failure = self.failing()
        if failure is not None:
            outcome = self.resolve(failure, self.signal_set())
            if self.v11.refit_fixpoint:
                self.recompute_signals()
            if outcome != "noise":
                return outcome == "reproduced"
        if not self.safety.probes:
            return None
        support_runs = 0
        rival_runs = 0
        while True:
            observed = {o.experiment_id for o in self.admitted()}
            signals = self.signal_set()
            unobserved = [e for e in self.available if e.experiment_id not in observed]
            affordable = [e for e in unobserved if e.cost <= self.remaining()]
            queue = self.order([e for e in affordable if e.experiment_id in signals])
            option = (
                self.targeted_option()
                if self.v12.rival_exclusion
                and self.v12.registered_probes
                and rival_runs < self.v12.max_rival_tests
                and self.failing() is None
                else None
            )
            if option is not None:
                rival_runs += 1
                excluded = self._close(option[0], option[1], option[2])
                if excluded != "clean":
                    return excluded == "reproduced"
                continue
            if queue:
                chosen = queue[0]
                self.run(chosen.experiment_id, ProbePurpose.ADEQUACY_PROBE, True, None)
            elif self.deferring:
                self.deferring = False
                reproduced = self.settle()
                if reproduced is not None:
                    return reproduced
                continue
            elif (
                self.v12.support_test
                and self.v12.registered_probes
                and support_runs < 2
                and self.failing() is None
                and not self.members_supported()
                and (tested := self.support_test()) != "none"
            ):
                support_runs += 1
                if tested != "clean":
                    return tested == "reproduced"
                continue
            elif (
                self.v12.rival_exclusion
                and rival_runs < self.v12.max_rival_tests
                and self.failing() is None
                and (excluded := _GateV14.rival_test(self)) != "none"
            ):
                rival_runs += 1
                if excluded != "clean":
                    return excluded == "reproduced"
                continue
            else:
                nulls = self.order([e for e in affordable if e.experiment_id not in signals])
                if not (self.safety.probe_null_experiments and nulls):
                    return None
                self.run(nulls[0].experiment_id, ProbePurpose.ADEQUACY_PROBE, False, None)
            if self.v11.refit_fixpoint:
                self.recompute_signals()
            reproduced = self.settle()
            if reproduced is not None:
                return reproduced


def _key(p: Prediction) -> tuple[object, ...]:
    return (
        tuple(sorted((k, round(v, 9)) for k, v in p[0].items())),
        tuple(sorted((k, round(v, 9)) for k, v in p[1].items())),
    )


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
