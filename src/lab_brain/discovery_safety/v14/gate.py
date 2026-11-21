"""`safe_investigate_v14`: the v1.3 gate deciding by the evaluator's v1.4 verdict (arm B7).

v1.0-v1.3 are frozen and not edited; this module subclasses the v1.3 gate. What changes:

    support   "is my claim supported?" is the evaluator's public v1.4 verdict (`verdict_v14`)
              applied to the gate's own copy of the record: a rival counts as closed only when its
              evaluator prediction failed on a test the claim passed (or its own registration
              failed), and adequate grammar shapes that the available experiments could still tell
              apart from the claim are rivals
    rivals    the open rivals are the evaluator's v1.4 open rivals (catalog, grammar, "no effect");
              a rival test registers the claim (and the rival) for n runs of ONE experiment, chosen
              to reach `tau_close` from as many open rivals as possible per unit cost (falling back
              to `tau_risky` from the strongest rival when nothing reaches `tau_close`)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe, investigate
from lab_brain.discovery.model import Budget, DiscoveryResult, ExperimentSpec
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.model import ProbePurpose
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.model import LadderStep, SafeRunV12
from lab_brain.discovery_safety.v12.replay import ReplayLaboratory, run_ladder
from lab_brain.discovery_safety.v13.gate import _ZERO, _GateV13
from lab_brain.discovery_safety.v13.rule import CATALOG, Prediction, rescore, separation
from lab_brain.discovery_safety.v14.model import (
    EVALUATOR_RULE_V14,
    SAFETY_V14,
    EvaluatorRuleV14,
    SafetyProtocolV14,
)
from lab_brain.discovery_safety.v14.rule import (
    RescorerV14,
    Rival,
    open_rivals_v14,
    verdict_v14,
)


@dataclass
class _GateV14(_GateV13):
    evaluator_rule: EvaluatorRuleV14 = field(default=EVALUATOR_RULE_V14)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.safety, SafetyProtocolV14):
            raise TypeError("the v1.4 gate runs under a SafetyProtocolV14")
        self.v14: SafetyProtocolV14 = self.safety
        rule = self.evaluator_rule
        if not isinstance(rule, EvaluatorRuleV14):
            raise TypeError("the v1.4 gate decides by the evaluator's v1.4 rule")
        self.rescorer = RescorerV14(
            distinct_forward_models(hypothesis_universe(self.catalog)),
            tuple(self.rescorer.shapes.values()),
            self.experiments,
            rule,
            self.oracle.distinguishable,
            tuple(e.experiment_id for e in self.available),
        )

    @property
    def rescorer_v14(self) -> RescorerV14:
        assert isinstance(self.rescorer, RescorerV14)
        return self.rescorer

    def self_supported(self, fingerprint: str) -> bool:
        events = self.record.events()
        tests = rescore(self.rescorer, events)
        return verdict_v14(self.rescorer_v14, events, tests, fingerprint).supported

    def open_rivals(self) -> list[tuple[float, str, Rival]]:  # type: ignore[override]
        """The evaluator's v1.4 open rivals of every member, strongest first."""
        if not self.members:
            return []
        events = self.record.events()
        tests = rescore(self.rescorer, events)
        seen: dict[str, Rival] = {}
        for m in self.members:
            for r in open_rivals_v14(self.rescorer_v14, events, tests, m.fingerprint):
                seen.setdefault(r.identity, r)
        return sorted(((r.chi2, r.label, r) for r in seen.values()), key=lambda x: (x[0], x[1]))

    def _rival_prediction(self, rival: Rival, experiment: ExperimentSpec) -> Prediction | None:
        identity = self.members[0].fingerprint if len(self.members) == 1 else ""
        data = self.data()
        if identity:
            return self.rescorer_v14.predict_rival(identity, rival.identity, data, experiment)
        return self.rescorer.predict(rival.identity, data, experiment)

    def rival_test(self) -> str:
        rivals = [r for _, _, r in self.open_rivals()]
        if not rivals:
            return "none"
        data = self.data()
        top = self.v14.max_runs if self.v14.multi_run_tests else 1
        # (closed per unit cost, -cost, ...) -- the best option reaching tau_close from the most
        # rivals; else the strongest rival at tau_risky (v1.3's choice)
        best: tuple[float, int, int, int, ExperimentSpec, tuple[Rival, ...]] | None = None
        for e in self.available:
            mine = [self.rescorer.predict(m.fingerprint, data, e) for m in self.members]
            if any(p is None for p in mine):
                continue
            theirs = [(r, self._rival_prediction(r, e)) for r in rivals]
            for n in range(1, top + 1):
                if n * e.cost > self.remaining():
                    break

                def gap(
                    p: Prediction | None,
                    n: int = n,
                    e: ExperimentSpec = e,
                    mine: list[Prediction | None] = mine,
                ) -> float:
                    if p is None:
                        return 0.0
                    return min(separation(q, p, e, n) for q in mine if q is not None)

                reach = tuple(r for r, p in theirs if gap(p) >= self.v14.tau_close)
                if not reach or not self.v14.batch_rivals:
                    continue
                key = (-len(reach) / (n * e.cost), n * e.cost, self.declared_order[e.experiment_id])
                if best is None or key < best[:3]:
                    best = (*key, n, e, reach)
        if best is None:
            return self._strongest_rival_test(rivals[0], data)
        return self._close(best[4], best[3], best[5])

    def _strongest_rival_test(self, rival: Rival, data: object) -> str:
        """v1.3's choice for one rival: the cheapest test (per unit of separation) reaching
        tau_risky."""
        chosen: tuple[float, int, int, int, ExperimentSpec] | None = None
        for e in self.available:
            theirs = self._rival_prediction(rival, e)
            if theirs is None:
                continue
            mine = [self.rescorer.predict(m.fingerprint, self.data(), e) for m in self.members]
            if any(p is None for p in mine):
                continue

            def gap(
                n: int,
                e: ExperimentSpec = e,
                theirs: Prediction = theirs,
                mine: list[Prediction | None] = mine,
            ) -> float:
                return min(separation(p, theirs, e, n) for p in mine if p is not None)

            n = self._runs_for(gap, e)
            if n is None:
                continue
            key = (n * e.cost / gap(n), n * e.cost, self.declared_order[e.experiment_id], n, e)
            if chosen is None or key[:3] < chosen[:3]:
                chosen = key
        if chosen is None:
            return "none"
        return self._close(chosen[4], chosen[3], (rival,))

    def _close(self, experiment: ExperimentSpec, runs: int, rivals: Sequence[Rival]) -> str:
        """Register the claim and the rivals for `runs` runs of `experiment`, run them."""
        catalog = {h.fingerprint: h for h in hypothesis_universe(self.catalog)}
        lead = rivals[0]
        self.forced_alternative = catalog.get(lead.identity) if lead.kind == CATALOG else None
        self.registration_runs = runs
        try:
            for h in self.members:
                self.register(h.hypothesis_id, h.fingerprint, experiment, _ZERO, (), "RIVAL_TEST")
            for r in rivals[:1]:
                self.register(r.label, r.identity, experiment, _ZERO, (), "RIVAL_TEST")
        finally:
            self.registration_runs = 1
        self.suppress_registration = True
        try:
            for _ in range(runs):
                self.run(experiment.experiment_id, ProbePurpose.ADEQUACY_PROBE, False, None)
        finally:
            self.suppress_registration = False
            self.forced_alternative = None
        if self.v11.refit_fixpoint:
            self.recompute_signals()
        reproduced = self.settle()
        if reproduced is None:
            return "clean"
        return "reproduced" if reproduced else "unreplicated"


def safe_investigate_v14(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
    safety: SafetyProtocolV14 = SAFETY_V14,
    grammar: TermGrammar | None = None,
    rule: EvaluatorRuleV14 = EVALUATOR_RULE_V14,
) -> SafeRunV12:
    """The frozen engine on the anytime ladder, then the v1.4 gate (records as v1.2's)."""
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
    gate = _GateV14(
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


def safe_runner_v14(
    safety: SafetyProtocolV14 = SAFETY_V14, grammar: TermGrammar | None = None
) -> Callable[..., DiscoveryResult]:
    def runner(**kwargs: object) -> DiscoveryResult:
        return safe_investigate_v14(safety=safety, grammar=grammar, **kwargs).result  # type: ignore[arg-type]

    return runner


__all__ = ["safe_investigate_v14", "safe_runner_v14"]
