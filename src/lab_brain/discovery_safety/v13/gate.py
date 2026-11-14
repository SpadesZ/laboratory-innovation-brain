"""`safe_investigate_v13`: the v1.2 gate registering identities, deciding by the evaluator's rule.

v1.0, v1.1 and v1.2 are frozen by their evidence manifests and are not edited; this module
subclasses the v1.2 gate. What it changes (each switch in `SafetyProtocolV13`):

    registration  every registration the v1.2 gate made now sends the evaluator only an identity
                  (forward-model fingerprint), the experiment, the number of runs and a digest of
                  the data the gate holds (`register_identity`). The gate keeps v1.2's full payload
                  in its OWN mirror for its internal discovery bookkeeping; the evaluator never sees
                  it
    support       the gate's "is my claim supported?" is the evaluator's public rule
                  (`rule.supported`) applied to the gate's own copy of the record, so the gate
                  endorses only what the evaluator will re-derive as SUPPORTED
    multi-run     the support test and the rival test may register n runs (1 <= n <= `max_runs`) of
                  one experiment: the smallest n at which the evaluator's separation reaches
                  `tau_risky`, if affordable
    rivals        a rival is excluded once its own registration for a separating test failed; for a
                  "no effect" claim the rival is tested at its smallest declared effect (the
                  evaluator's alternative for null claims)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe, investigate
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    Budget,
    DiscoveryResult,
    DiscoveryState,
    ExperimentSpec,
    Hypothesis,
    HypothesisRecord,
    Observation,
    Origin,
    Outcome,
    StateEvent,
)
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.model import ProbePurpose
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.gate import _GateV11
from lab_brain.discovery_safety.v12.gate import _GateV12, grammar_shapes
from lab_brain.discovery_safety.v12.grammar import TermGrammar
from lab_brain.discovery_safety.v12.ledger import prediction_payload
from lab_brain.discovery_safety.v12.model import LadderStep, Registration, SafeRunV12
from lab_brain.discovery_safety.v12.replay import ReplayLaboratory, run_ladder
from lab_brain.discovery_safety.v13.ledger import (
    EvaluatorLedger,
    measurement_digest,
    observations_before,
)
from lab_brain.discovery_safety.v13.model import (
    EVALUATOR_RULE,
    SAFETY_V13,
    EvaluatorRule,
    SafetyProtocolV13,
)
from lab_brain.discovery_safety.v13.rule import (
    Prediction,
    Rescorer,
    open_rivals,
    rescore,
    separation,
    verdict,
)

_ZERO: Prediction = ({}, {})


@dataclass
class _GateV13(_GateV12):
    #: The evaluator's public rule (the v1.2 gate's own `self.rule` stays its PredictionRule, used
    #: only for the payloads in the gate's private mirror).
    evaluator_rule: EvaluatorRule = field(default=EVALUATOR_RULE)

    def __post_init__(self) -> None:
        evaluator_rule = self.evaluator_rule
        super().__post_init__()
        if not isinstance(self.safety, SafetyProtocolV13):
            raise TypeError("the v1.3 gate runs under a SafetyProtocolV13")
        self.v13: SafetyProtocolV13 = self.safety
        self.record = EvaluatorLedger()
        for experiment_id, k in self.replay.order:
            self.record.record_measurement(
                experiment_id, k, self.replay.readings[(experiment_id, k)]
            )
        shapes = grammar_shapes(self.grammar) if self.grammar is not None else ()
        self.rescorer = Rescorer(
            distinct_forward_models(hypothesis_universe(self.catalog)),
            shapes,
            self.experiments,
            evaluator_rule,
            self.oracle.distinguishable,
        )
        self.registration_runs = 1
        self.suppress_registration = False

    # -- registration: identities only ---------------------------------------------------------

    def data(self) -> list[Observation]:
        events = self.record.events()
        return observations_before(events, len(events))

    def register(
        self,
        subject: str,
        fingerprint: str,
        experiment: ExperimentSpec,
        mine: Prediction,
        others: Sequence[tuple[str, Prediction]],
        purpose: str,
    ) -> Registration:
        runs = self.registration_runs
        declared = measurement_digest(self.record.measurements_before(len(self.record.events())))
        handle = getattr(self.replay.lab, "register_identity", None)
        receipt = (
            handle(fingerprint, experiment.experiment_id, runs, declared)
            if handle is not None
            else None
        )
        self.record.register(fingerprint, experiment.experiment_id, runs, declared)
        # the gate's own v1.2-style payload, kept in its own mirror only (discovery bookkeeping)
        replicate = self.replicates.get(experiment.experiment_id, 0)
        text = prediction_payload(
            subject=subject,
            fingerprint=fingerprint,
            experiment_id=experiment.experiment_id,
            replicate=replicate,
            predicted=mine[0],
            sd=mine[1],
            alternatives=[(label, p[0], p[1]) for label, p in others],
            rule=self.rule,  # v1.2's PredictionRule, set by the v1.2 gate
            purpose=purpose,
        )
        self.mirror.register(text)
        registration = Registration(
            ledger_index=-1 if receipt is None else int(receipt["index"]),
            digest=self.mirror.events[-1].digest,
            subject=subject,
            fingerprint=fingerprint,
            experiment_id=experiment.experiment_id,
            replicate=replicate,
            purpose=purpose,
        )
        self.registrations.append(registration)
        return registration

    def run(
        self, experiment_id: str, purpose: ProbePurpose, signal: bool, of: str | None
    ) -> Observation:
        if self.v12.registered_probes and self.members and not self.suppress_registration:
            experiment = self.experiments[experiment_id]
            for h in self.members:
                self.register(h.hypothesis_id, h.fingerprint, experiment, _ZERO, (), purpose.value)
        observation = _GateV11.run(self, experiment_id, purpose, signal, of)
        self.mirror.record_measurement(
            observation.experiment_id, observation.replicate, observation.values
        )
        self.record.record_measurement(
            observation.experiment_id, observation.replicate, observation.values
        )
        return observation

    def _measure(self, experiment: ExperimentSpec) -> Observation:
        observation = super()._measure(experiment)
        self.record.record_measurement(
            observation.experiment_id, observation.replicate, observation.values
        )
        return observation

    def self_supported(self, fingerprint: str) -> bool:
        if not self.v13.evaluator_rule_support:
            return super().self_supported(fingerprint)
        events = self.record.events()
        tests = rescore(self.rescorer, events)
        return verdict(self.rescorer, events, tests, fingerprint).supported

    # -- risk under the evaluator's rule --------------------------------------------------------

    def risk(self, experiment: ExperimentSpec, runs: int = 1) -> float:
        data = self.data()
        return min(
            (self.rescorer.risk(h.fingerprint, data, experiment, runs)[0] for h in self.members),
            default=0.0,
        )

    def _runs_for(self, gap: Callable[[int], float], experiment: ExperimentSpec) -> int | None:
        """The smallest number of runs whose separation reaches tau_risky and is affordable."""
        top = self.v13.max_runs if self.v13.multi_run_tests else 1
        for n in range(1, top + 1):
            if n * experiment.cost > self.remaining():
                return None
            if gap(n) >= self.v12.tau_risky:
                return n
        return None

    def run_test(
        self,
        experiment: ExperimentSpec,
        runs: int,
        purpose: ProbePurpose,
        extra: Sequence[Hypothesis] = (),
    ) -> str:
        """Register the claim (and `extra` identities) for `runs` runs of one experiment, run them,
        then resolve failures as v1.1 does ("clean", "reproduced" or "unreplicated")."""
        self.registration_runs = runs
        try:
            for h in [*self.members, *extra]:
                self.register(h.hypothesis_id, h.fingerprint, experiment, _ZERO, (), purpose.value)
        finally:
            self.registration_runs = 1
        self.suppress_registration = True
        try:
            for _ in range(runs):
                self.run(experiment.experiment_id, purpose, False, None)
        finally:
            self.suppress_registration = False
        if self.v11.refit_fixpoint:
            self.recompute_signals()
        reproduced = self.settle()
        if reproduced is None:
            return "clean"
        return "reproduced" if reproduced else "unreplicated"

    def support_test(self) -> str:
        observed = {o.experiment_id for o in self.admitted()}
        scored = []
        for e in self.available:
            n = self._runs_for(lambda k, e=e: self.risk(e, k), e)  # type: ignore[misc]
            if n is None:
                continue
            r = self.risk(e, n)
            scored.append(
                (
                    e.experiment_id in observed,
                    n * e.cost,
                    -r,
                    self.declared_order[e.experiment_id],
                    n,
                    e,
                )
            )
        if not scored:
            return "none"
        chosen = min(scored, key=lambda t: t[:4])
        return self.run_test(chosen[5], chosen[4], ProbePurpose.ADEQUACY_PROBE)

    # -- rivals ---------------------------------------------------------------------------------

    def open_rivals(self) -> list[tuple[float, str, Hypothesis]]:
        """The evaluator's open rivals of every member (viable, no more complex, distinguishable,
        not yet separated by a passed registration, never refuted by a failed one), strongest
        first. v1.2's list (`super().open_rivals()`) without the evaluator's closing rule when
        `rival_refuted_by_failed_registration` is off."""
        if not self.v13.rival_refuted_by_failed_registration:
            return super().open_rivals()
        if not self.members:
            return []
        events = self.record.events()
        tests = rescore(self.rescorer, events)
        seen: dict[str, Hypothesis] = {}
        for m in self.members:
            for h in open_rivals(self.rescorer, events, tests, m.fingerprint):
                seen.setdefault(h.fingerprint, h)
        return sorted(
            ((self.test(h).chi2, h.hypothesis_id, h) for h in seen.values()),
            key=lambda x: (x[0], x[1]),
        )

    # -- parsimony fallback ---------------------------------------------------------------------

    def assess_v12(self) -> SafeRunV12:
        """v1.2's assessment; then, if the claim was not endorsed (and no new mechanism was
        answered) while "no effect" is still viable on all the data (one-outlier tolerant, the
        evaluator's test) and the budget allows another run, "no effect" -- the simplest
        hypothesis -- is assessed as the claim with what is left, under the same probes,
        registrations, rival tests and adequacy test. v1.2 never reconsidered the null once the
        engine's small-cap ladder had claimed a mechanism from a few noisy readings (development
        log §C: 13 of 25 noise-only worlds at budget 24)."""
        run = super().assess_v12()
        if not self._fallback_due(run):
            return run
        first = ", ".join(h.hypothesis_id for h in self.members)
        records = list(run.result.hypotheses)
        if not any(r.hypothesis_id == NULL_HYPOTHESIS.hypothesis_id for r in records):
            records.append(
                HypothesisRecord(
                    hypothesis=NULL_HYPOTHESIS,
                    registered_at=self.step,
                    origin=Origin.INITIAL_CATALOG,
                    history=(
                        StateEvent(
                            self.step,
                            DiscoveryState.UNDER_TEST.value,
                            "safety v1.3 parsimony fallback: 'no effect' assessed after "
                            f"{first} was not endorsed",
                        ),
                    ),
                )
            )
        self.engine = replace(
            run.result,
            outcome=Outcome.NO_EFFECT_BEYOND_NOISE,
            claim=(NULL_HYPOTHESIS.hypothesis_id,),
            hypotheses=tuple(records),
            handover=None,
            observations=tuple(self.observations),
            steps=tuple(self.steps),
            spent=self.spent,
        )
        self.members = [NULL_HYPOTHESIS]
        self.history = []
        self.initial_signals = ()
        self.deferring = False
        self._alternatives = None
        self.forced_alternative = None
        self.fallback_used = True
        self.extra_notes.append(
            f"safety v1.3: {first} not endorsed while 'no effect' stays viable; 'no effect' "
            f"assessed with the {self.remaining()} unit(s) left"
        )
        second = super().assess_v12()
        return replace(second, engine=self.original_engine, notes=tuple(self.extra_notes))

    def _fallback_due(self, run: SafeRunV12) -> bool:
        if not self.v13.null_fallback or getattr(self, "fallback_used", False):
            return False
        if run.result.claim or (run.discovery is not None and run.discovery.answered is not None):
            return False
        if not self.members or any(h.is_null for h in self.members):
            return False
        cheapest = min((e.cost for e in self.available), default=0)
        if not self.available or cheapest > self.remaining():
            return False
        return self.rescorer.adequate(NULL_HYPOTHESIS, self.data())

    def rival_prediction(self, rival: Hypothesis, experiment: ExperimentSpec) -> Prediction | None:
        identity = self.members[0].fingerprint if len(self.members) == 1 else ""
        if identity:
            return self.rescorer.rival_prediction(identity, rival, self.data(), experiment)
        return self.rescorer.predict(rival.fingerprint, self.data(), experiment)

    def rival_test(self) -> str:
        rivals = self.open_rivals()
        if not rivals:
            return "none"
        rival = rivals[0][2]
        data = self.data()
        best: tuple[float, int, int, int, ExperimentSpec] | None = None
        for e in self.available:
            theirs = self.rival_prediction(rival, e)
            if theirs is None:
                continue
            mine = [self.rescorer.predict(m.fingerprint, data, e) for m in self.members]
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
            if best is None or key[:3] < best[:3]:
                best = key
        if best is None:
            return "none"
        self.forced_alternative = rival
        try:
            return self.run_test(best[4], best[3], ProbePurpose.ADEQUACY_PROBE, extra=(rival,))
        finally:
            self.forced_alternative = None


def safe_investigate_v13(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
    safety: SafetyProtocolV13 = SAFETY_V13,
    grammar: TermGrammar | None = None,
    rule: EvaluatorRule = EVALUATOR_RULE,
) -> SafeRunV12:
    """The frozen engine on the anytime ladder, then the v1.3 gate (records as v1.2's)."""
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
    gate = _GateV13(
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


def safe_runner_v13(
    safety: SafetyProtocolV13 = SAFETY_V13, grammar: TermGrammar | None = None
) -> Callable[..., DiscoveryResult]:
    def runner(**kwargs: object) -> DiscoveryResult:
        return safe_investigate_v13(safety=safety, grammar=grammar, **kwargs).result  # type: ignore[arg-type]

    return runner


__all__ = ["NULL_HYPOTHESIS", "safe_investigate_v13", "safe_runner_v13"]
