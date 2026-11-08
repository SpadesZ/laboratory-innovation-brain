"""`safe_investigate_v12`: anytime allocation, registered adequacy probes, grammar discovery.

v1.0 and v1.1 are frozen by their evidence manifests and are not edited; this module subclasses the
v1.1 gate. What it changes (each switch in `SafetyProtocolV12`, each measured on its own):

    allocation   the frozen engine runs on the anytime cap ladder (`replay.run_ladder`); the gate's
                 starting data are every distinct measurement any ladder run made, and its budget
                 is what the laboratory has not yet charged
    registration before every adequacy probe the gate registers, per claimed member, the predicted
                 values for that run (fitted to the data admitted so far, with their standard
                 deviation) and the strongest alternatives' predictions (zero, and the best-fitting
                 other hypotheses the catalog expresses), in the evaluator's ledger. Endorsement
                 needs the ledger rule (`ledger.supported`) for every member: STRICTER than v1.1
    support test when every signal experiment was already run by the engine, the gate spends a run
                 on the most separating risky test it can afford, registered first
    probe order  never-run signal experiments by separation from the alternatives per unit cost
    discovery    on CATALOG_INCOMPLETE: grammar candidates, fitted, adequate ones tested on an unrun
                 discriminating experiment whose predictions were registered first

The adequacy criterion and `signal_coverage = 1.0` are v1.1's, unchanged.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.forward import fit, predict
from lab_brain.discovery.loop import Laboratory, hypothesis_universe, investigate
from lab_brain.discovery.model import (
    Budget,
    DiscoveryResult,
    DiscoveryState,
    ExperimentSpec,
    Hypothesis,
    HypothesisRecord,
    Observation,
    Origin,
    Outcome,
    Purpose,
    StateEvent,
    StepRecord,
    Tier,
    transition,
)
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.model import (
    AbstentionReason,
    ConfidenceLevel,
    ProbePurpose,
    SafetyDecision,
)
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.gate import _GateV11, adequacy_test_v11
from lab_brain.discovery_safety.v12.grammar import (
    CandidateShape,
    FittedShape,
    TermGrammar,
    candidate_classes,
    candidate_hypothesis,
    enumerate_shapes,
    fit_shape,
    prediction,
    separation,
)
from lab_brain.discovery_safety.v12.ledger import (
    PredictionLedger,
    PredictionRule,
    prediction_payload,
    rescore,
    score_prediction,
    supported,
)
from lab_brain.discovery_safety.v12.model import (
    SAFETY_V12,
    SEPARATION_ORDER,
    Allocation,
    DiscoveryAttempt,
    DiscoveryTest,
    GrammarCandidate,
    LadderStep,
    Registration,
    SafeRunV12,
    SafetyProtocolV12,
)
from lab_brain.discovery_safety.v12.replay import ReplayLaboratory, run_ladder

Prediction = tuple[dict[str, float], dict[str, float]]

_SHAPES: dict[str, tuple[CandidateShape, ...]] = {}


def grammar_shapes(grammar: TermGrammar) -> tuple[CandidateShape, ...]:
    """Every candidate shape of a grammar (computed once per grammar digest)."""
    key = grammar.digest
    if key not in _SHAPES:
        _SHAPES[key] = enumerate_shapes(grammar)
    return _SHAPES[key]


def _invert(matrix: list[list[float]]) -> list[list[float]] | None:
    n = len(matrix)
    a = [[*row, *(1.0 if i == j else 0.0 for j in range(n))] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        p = a[col][col]
        a[col] = [v / p for v in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col], strict=True)]
    return [row[n:] for row in a]


def hypothesis_prediction(
    h: Hypothesis,
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
    experiment: ExperimentSpec,
) -> Prediction:
    """A catalog hypothesis's predicted values for one run of `experiment`, at its fit to
    `observations`, with the standard deviation propagated from the amplitudes' covariance
    (components the data do not constrain contribute their half-range as a standard deviation)."""
    theta = fit(h, observations, experiments).theta
    mean = predict(h, theta, experiment)
    k = len(h.components)
    columns = [[0.0] * 0 for _ in range(k)]
    for o in observations:
        x = experiments[o.experiment_id]
        for entry in x.entries:
            for i, c in enumerate(h.components):
                columns[i].append(c.coefficient(x.experiment_id, entry.entry_id) / entry.sigma)
    used = [i for i in range(k) if any(v != 0.0 for v in columns[i])]
    cov: dict[tuple[int, int], float] = {}
    if used:
        xtx = [
            [math.fsum(a * b for a, b in zip(columns[i], columns[j], strict=True)) for j in used]
            for i in used
        ]
        inverse = _invert(xtx)
        if inverse is not None:
            for p, i in enumerate(used):
                for q, j in enumerate(used):
                    cov[(i, j)] = inverse[p][q]
    for i, c in enumerate(h.components):
        if (i, i) not in cov:
            cov[(i, i)] = ((c.upper - c.lower) / 2.0) ** 2
    sd = {}
    for entry in experiment.entries:
        s = [c.coefficient(experiment.experiment_id, entry.entry_id) for c in h.components]
        var = math.fsum(s[i] * cov.get((i, j), 0.0) * s[j] for i in range(k) for j in range(k))
        sd[entry.entry_id] = math.sqrt(max(0.0, var))
    return mean, sd


def _combined_separation(a: Prediction, b: Prediction, experiment: ExperimentSpec) -> float:
    d2 = 0.0
    for entry in experiment.entries:
        scale2 = (
            entry.sigma**2 + a[1].get(entry.entry_id, 0.0) ** 2 + b[1].get(entry.entry_id, 0.0) ** 2
        )
        d = a[0].get(entry.entry_id, 0.0) - b[0].get(entry.entry_id, 0.0)
        d2 += d * d / scale2
    return math.sqrt(d2)


def _zero(experiment: ExperimentSpec) -> Prediction:
    return (
        {e.entry_id: 0.0 for e in experiment.entries},
        {e.entry_id: 0.0 for e in experiment.entries},
    )


@dataclass
class _GateV12(_GateV11):
    replay: ReplayLaboratory = field(default=None)  # type: ignore[assignment]
    requested: tuple[tuple[str, int], ...] = ()
    grammar: TermGrammar | None = None
    ladder: tuple[LadderStep, ...] = ()
    engine_cap: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.safety, SafetyProtocolV12):
            raise TypeError("the v1.2 gate runs under a SafetyProtocolV12")
        self.v12: SafetyProtocolV12 = self.safety
        self.rule = PredictionRule(
            alpha=self.v12.alpha_prospective,
            z_max=self.v12.z_prospective,
            tau_risky=self.v12.tau_risky,
        )
        self.mirror = PredictionLedger()
        self.registrations: list[Registration] = []
        self.extra_notes: list[str] = []
        # Every measurement any ladder run made is data: the ones the chosen run did not ask for
        # (orphans) are admitted as observations too.
        chosen = set(self.requested)
        orphans: list[str] = []
        for experiment_id, k in self.replay.order:
            if (experiment_id, k) in chosen:
                continue
            self.step += 1
            observation = Observation(
                observation_id=f"obs:{self.step}",
                experiment_id=experiment_id,
                replicate=k,
                taken_at=self.step,
                values=self.replay.readings[(experiment_id, k)],
            )
            self.observations.append(observation)
            cost = self.experiments[experiment_id].cost
            self.steps.append(
                StepRecord(
                    step=self.step,
                    experiment_id=experiment_id,
                    purpose=Purpose.DISCRIMINATE,
                    utility=0.0,
                    cost=cost,
                    budget_after=self.budget.total - self.replay.charged,
                    observation_id=observation.observation_id,
                )
            )
            orphans.append(observation.observation_id)
        self.orphans = tuple(orphans)
        self.spent = self.replay.charged
        self.replicates = {}
        for o in self.observations:
            if not o.motivating:
                self.replicates[o.experiment_id] = max(
                    self.replicates.get(o.experiment_id, 0), o.replicate + 1
                )
        for experiment_id, k in self.replay.order:
            self.mirror.record_measurement(
                experiment_id, k, self.replay.readings[(experiment_id, k)]
            )
        self.charged_by_engine_runs = self.replay.charged
        self._alternatives: list[Hypothesis] | None = None
        self.forced_alternative: Hypothesis | None = None
        self.original_engine = self.engine
        self.gate_led_claim: str | None = None

    # -- registration ---------------------------------------------------------------------------

    def alternatives(self) -> list[Hypothesis]:
        """The best-fitting other hypotheses the catalog expresses (ranked once, before probing)."""
        if self._alternatives is None:
            prints = {h.fingerprint for h in self.members}
            admitted = self.admitted()
            ranked = sorted(
                (
                    (fit(h, admitted, self.experiments).chi2, h.hypothesis_id, h)
                    for h in distinct_forward_models(hypothesis_universe(self.catalog))
                    if h.fingerprint not in prints and not h.is_null
                ),
                key=lambda t: (t[0], t[1]),
            )
            self._alternatives = [h for _, _, h in ranked[: self.v12.max_alternatives]]
        return self._alternatives

    def predictions(
        self, experiment: ExperimentSpec
    ) -> tuple[list[Prediction], list[tuple[str, Prediction]]]:
        admitted = self.admitted()
        mine = [
            hypothesis_prediction(h, admitted, self.experiments, experiment) for h in self.members
        ]
        rivals = list(self.alternatives())
        if self.forced_alternative is not None and self.forced_alternative not in rivals:
            rivals.append(self.forced_alternative)
        others = [("none", _zero(experiment))] + [
            (h.hypothesis_id, hypothesis_prediction(h, admitted, self.experiments, experiment))
            for h in rivals
        ]
        return mine, others

    def register(
        self,
        subject: str,
        fingerprint: str,
        experiment: ExperimentSpec,
        mine: Prediction,
        others: Sequence[tuple[str, Prediction]],
        purpose: str,
    ) -> Registration:
        replicate = self.replicates.get(experiment.experiment_id, 0)
        text = prediction_payload(
            subject=subject,
            fingerprint=fingerprint,
            experiment_id=experiment.experiment_id,
            replicate=replicate,
            predicted=mine[0],
            sd=mine[1],
            alternatives=[(label, p[0], p[1]) for label, p in others],
            rule=self.rule,
            purpose=purpose,
        )
        index = self.replay.register(text)
        self.mirror.register(text)
        registration = Registration(
            ledger_index=-1 if index is None else index,
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
        if self.v12.registered_probes and self.members:
            experiment = self.experiments[experiment_id]
            mine, others = self.predictions(experiment)
            for h, p in zip(self.members, mine, strict=True):
                self.register(h.hypothesis_id, h.fingerprint, experiment, p, others, purpose.value)
        observation = super().run(experiment_id, purpose, signal, of)
        self.mirror.record_measurement(
            observation.experiment_id, observation.replicate, observation.values
        )
        return observation

    def self_supported(self, fingerprint: str) -> bool:
        """The ledger rule, applied by the gate to its own mirror (the evaluator re-derives it)."""
        return supported(
            rescore(self.mirror, self.experiments), fingerprint, self.v12.alpha_prospective
        )

    # -- probe order and the support test ---------------------------------------------------------

    def risk(self, experiment: ExperimentSpec) -> float:
        """How far the claim's prediction for one run is from its strongest alternative."""
        mine, others = self.predictions(experiment)
        return min(
            (max(_combined_separation(p, o, experiment) for _, o in others) for p in mine),
            default=0.0,
        )

    def order(self, candidates: Sequence[ExperimentSpec]) -> list[ExperimentSpec]:
        def cheapest(e: ExperimentSpec) -> tuple[float, ...]:
            return (e.cost, self.declared_order[e.experiment_id])

        if self.v12.probe_order != SEPARATION_ORDER or not self.members:
            return sorted(candidates, key=cheapest)
        scored = {e.experiment_id: self.risk(e) / e.cost for e in candidates}
        return sorted(candidates, key=lambda e: (-scored[e.experiment_id], *cheapest(e)))

    def members_supported(self) -> bool:
        return all(self.self_supported(h.fingerprint) for h in self.members)

    def support_test(self) -> str:
        """One registered run of the most separating affordable risky test (new experiments first,
        then replicates). "none": nothing risky is affordable; "clean": it ran and nothing fails;
        "reproduced" / "unreplicated": it ran and a failure was resolved that way (as `settle`)."""
        options = [e for e in self.available if e.cost <= self.remaining()]
        if not options:
            return "none"
        observed = {o.experiment_id for o in self.admitted()}
        scored = []
        for e in options:
            r = self.risk(e)
            if r >= self.v12.tau_risky:
                scored.append(
                    (
                        e.experiment_id in observed,
                        -r / e.cost,
                        e.cost,
                        self.declared_order[e.experiment_id],
                        e,
                    )
                )
        if not scored:
            return "none"
        chosen = min(scored, key=lambda t: t[:4])[4]
        self.run(chosen.experiment_id, ProbePurpose.ADEQUACY_PROBE, False, None)
        if self.v11.refit_fixpoint:
            self.recompute_signals()
        reproduced = self.settle()
        if reproduced is None:
            return "clean"
        return "reproduced" if reproduced else "unreplicated"

    def probe_fixpoint(self) -> bool | None:
        """v1.1's probe fixpoint in explicit phases, each resolving failures as v1.1 does:

        1. every never-run SIGNAL experiment of the union (v1.2 order), registered first;
        2. the deferred localized-failure resolution (v1.1);
        3. the support test, when no registered risky prediction of the claim has passed yet;
        4. rival exclusion: while a hypothesis the catalog expresses, of no greater complexity and
           distinguishable from the claim, is still adequate, run the registered test that
           separates the claim from the strongest such rival most per unit cost;
        5. v1.1's null probes while the budget lasts."""
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
                and (excluded := self.rival_test()) != "none"
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

    def open_rivals(self) -> list[tuple[float, str, Hypothesis]]:
        """Hypotheses the catalog expresses, of no greater complexity than the claim (a claim of
        "no effect" is held against every single class), distinguishable from every member, that
        are still adequate (strongest first). Parsimony as in the engine's rival closure: a more
        complex rival is not required to be excluded (development showed that requiring it
        abstains on nearly every in-catalog claim, because "the claim plus a small extra class"
        stays adequate)."""
        if not self.members:
            return []
        prints = {h.fingerprint for h in self.members}
        size = max(1, *(len(h.components) for h in self.members))
        out = []
        for h in distinct_forward_models(hypothesis_universe(self.catalog)):
            if h.fingerprint in prints or len(h.components) > size:
                continue
            if not all(self.oracle.distinguishable(h, m) for m in self.members):
                continue
            t = self.test(h)
            if t.adequate:
                out.append((t.chi2, h.hypothesis_id, h))
        return sorted(out, key=lambda x: (x[0], x[1]))

    def rival_test(self) -> str:
        """One registered run separating the claim from its strongest open rival ("none" when there
        is no open rival or no affordable experiment separates them by `tau_risky`)."""
        rivals = self.open_rivals()
        if not rivals:
            return "none"
        rival = rivals[0][2]
        admitted = self.admitted()
        best: tuple[float, int, int, ExperimentSpec] | None = None
        for e in self.available:
            if e.cost > self.remaining():
                continue
            theirs = hypothesis_prediction(rival, admitted, self.experiments, e)
            d = min(
                _combined_separation(
                    hypothesis_prediction(m, admitted, self.experiments, e), theirs, e
                )
                for m in self.members
            )
            if d < self.v12.tau_risky:
                continue
            key = (-d / e.cost, e.cost, self.declared_order[e.experiment_id], e)
            if best is None or key[:3] < best[:3]:
                best = key
        if best is None:
            return "none"
        self.forced_alternative = rival
        try:
            self.run(best[3].experiment_id, ProbePurpose.ADEQUACY_PROBE, False, None)
        finally:
            self.forced_alternative = None
        if self.v11.refit_fixpoint:
            self.recompute_signals()
        reproduced = self.settle()
        if reproduced is None:
            return "clean"
        return "reproduced" if reproduced else "unreplicated"

    # -- discovery ------------------------------------------------------------------------------

    def _measure(self, experiment: ExperimentSpec) -> Observation:
        if experiment.cost > self.remaining():
            raise RuntimeError(f"{experiment.experiment_id} is not affordable")
        self.step += 1
        replicate = self.replicates.get(experiment.experiment_id, 0)
        self.replicates[experiment.experiment_id] = replicate + 1
        values = self.lab.measure(experiment.experiment_id, replicate=replicate, session=self.step)
        observation = Observation(
            observation_id=f"obs:{self.step}",
            experiment_id=experiment.experiment_id,
            replicate=replicate,
            taken_at=self.step,
            values=values,
        )
        self.observations.append(observation)
        self.spent += experiment.cost
        self.steps.append(
            StepRecord(
                step=self.step,
                experiment_id=experiment.experiment_id,
                purpose=Purpose.PROSPECTIVE_TEST,
                utility=0.0,
                cost=experiment.cost,
                budget_after=self.remaining(),
                observation_id=observation.observation_id,
            )
        )
        self.mirror.record_measurement(experiment.experiment_id, replicate, values)
        return observation

    def _candidate(
        self, fitted: FittedShape, label: str
    ) -> tuple[GrammarCandidate, Hypothesis] | None:
        classes = candidate_classes(fitted, self.v12.candidate_band, label)
        if classes is None:
            return None
        h = candidate_hypothesis(classes)
        test = adequacy_test_v11(h, self.admitted(), self.experiments, self.v11)
        se = tuple(math.sqrt(max(0.0, fitted.covariance[i][i])) for i in range(len(fitted.theta)))
        return (
            GrammarCandidate(
                candidate_id=label,
                terms=tuple(t.term_id for t in fitted.shape.terms),
                theta=fitted.theta,
                se=se,
                tables=fitted.shape.tables,
                domain=tuple((c.lower, c.upper) for c in classes),
                fingerprint=fitted.shape.fingerprint,
                chi2=test.chi2,
                p_value=test.p_value,
                adequate=test.adequate,
            ),
            h,
        )

    def discover(self) -> DiscoveryAttempt | None:
        grammar = self.grammar
        if grammar is None or not self.v12.discovery:
            return None
        shapes = grammar_shapes(grammar)
        catalog_prints = {h.fingerprint for h in hypothesis_universe(self.catalog)}

        def adequate_now() -> list[tuple[GrammarCandidate, Hypothesis, FittedShape]]:
            admitted = self.admitted()
            out = []
            for shape in shapes:
                f = fit_shape(shape, admitted, self.experiments)
                if (
                    f is None
                    or f.p_value < self.safety.alpha_adequacy
                    or f.max_abs_z > self.safety.z_adequacy
                ):
                    continue
                label = "grammar:" + shape.fingerprint.split(":")[1][:12]
                built = self._candidate(f, label)
                if built is None or not built[0].adequate or built[1].fingerprint in catalog_prints:
                    continue
                out.append((built[0], built[1], f))
            out.sort(key=lambda t: (len(t[0].terms), t[0].chi2, t[0].candidate_id))
            return out

        live = adequate_now()[:12]
        first = tuple(c.candidate_id for c, _, _ in live)
        tests: list[DiscoveryTest] = []
        failed_ids: set[str] = set()
        reason = ""
        if not live:
            return DiscoveryAttempt(
                grammar.grammar_id,
                grammar.digest,
                len(shapes),
                (),
                (),
                (),
                None,
                None,
                "no grammar candidate is adequate to the admitted data",
            )
        best_before = live[0][0]
        while len(tests) < self.v12.max_discovery_tests:
            live = [t for t in adequate_now() if t[0].candidate_id not in failed_ids][:12]
            if not live:
                reason = "every candidate failed a registered prediction or became inadequate"
                break
            observed = {o.experiment_id for o in self.admitted()}
            options = [
                e
                for e in self.available
                if e.experiment_id not in observed and e.cost <= self.remaining()
            ]
            best: tuple[float, int, int, ExperimentSpec] | None = None
            for e in options:
                preds = [prediction(f, e) for _, _, f in live]
                zero = _zero(e)
                score = sum(
                    1 for p in preds if _combined_separation(p, zero, e) >= self.v12.tau_risky
                ) + sum(
                    1
                    for i in range(len(preds))
                    for j in range(i + 1, len(preds))
                    if _combined_separation(preds[i], preds[j], e) >= self.v12.tau_risky
                )
                key = (-score / e.cost, e.cost, self.declared_order[e.experiment_id], e)
                if score > 0 and (best is None or key[:3] < best[:3]):
                    best = key
            if best is None:
                reason = "no affordable never-run experiment discriminates the candidates"
                break
            experiment = best[3]
            preds = [prediction(f, experiment) for _, _, f in live]
            registrations = []
            for i, (c, _, _) in enumerate(live):
                others = [("none", _zero(experiment))] + [
                    (live[j][0].candidate_id, preds[j]) for j in range(len(live)) if j != i
                ]
                registrations.append(
                    self.register(
                        c.candidate_id,
                        c.fingerprint,
                        experiment,
                        preds[i],
                        others,
                        "DISCOVERY_TEST",
                    )
                )
            observation = self._measure(experiment)
            passed: list[str] = []
            failed: list[str] = []
            payloads = {e.digest: json.loads(e.text) for e in self.mirror.events if e.text}
            for (c, _, _), r in zip(live, registrations, strict=True):
                s = score_prediction(payloads[r.digest], observation.values, experiment)
                (passed if s.passed else failed).append(c.candidate_id)
            failed_ids.update(failed)
            tests.append(
                DiscoveryTest(
                    experiment.experiment_id,
                    observation.replicate,
                    tuple(registrations),
                    observation.observation_id,
                    tuple(passed),
                    tuple(failed),
                )
            )
            survivors_now = [t for t in adequate_now() if t[0].candidate_id not in failed_ids]
            if len(survivors_now) <= 1 or self._mutually_indistinguishable(survivors_now):
                break
        remaining = [t for t in adequate_now() if t[0].candidate_id not in failed_ids]
        survivors = [t for t in remaining if self.self_supported(t[0].fingerprint)]
        answered: GrammarCandidate | None = None
        proposal: GrammarCandidate | None = None
        if survivors:
            winner = survivors[0]
            if not self._mutually_indistinguishable([winner, *remaining]):
                reason = "candidates the experiments can still tell apart remain"
                proposal = winner[0]
            else:
                uncovered = self._uncovered_signals(winner[2])
                for experiment in sorted(
                    uncovered, key=lambda e: (e.cost, self.declared_order[e.experiment_id])
                ):
                    if experiment.cost > self.remaining():
                        continue
                    p = prediction(winner[2], experiment)
                    self.register(
                        winner[0].candidate_id,
                        winner[0].fingerprint,
                        experiment,
                        p,
                        [("none", _zero(experiment))],
                        "DISCOVERY_COVERAGE",
                    )
                    self._measure(experiment)
                refreshed = [
                    t for t in adequate_now() if t[0].candidate_id == winner[0].candidate_id
                ]
                if not refreshed:
                    reason = "the candidate became inadequate on its coverage runs"
                    proposal = winner[0]
                elif self._uncovered_signals(refreshed[0][2]):
                    reason = "the candidate's signal experiments could not all be afforded"
                    proposal = refreshed[0][0]
                elif not self.self_supported(winner[0].fingerprint):
                    reason = "the candidate's registered predictions do not meet the ledger rule"
                    proposal = refreshed[0][0]
                else:
                    answered = refreshed[0][0]
                    reason = (
                        "a registered prediction for an unrun experiment held; adequate and covered"
                    )
        else:
            proposal = best_before
            reason = reason or "no candidate passed a registered prediction"
        return DiscoveryAttempt(
            grammar_id=grammar.grammar_id,
            grammar_digest=grammar.digest,
            candidates_considered=len(shapes),
            adequate_before_test=first,
            tests=tuple(tests),
            survivors=tuple(t[0].candidate_id for t in survivors),
            answered=answered,
            proposal=None if answered is not None else proposal,
            reason=reason,
        )

    def _mutually_indistinguishable(
        self, items: Sequence[tuple[GrammarCandidate, Hypothesis, FittedShape]]
    ) -> bool:
        """Whether every item is INDISTINGUISHABLE from the first (pairwise with the first only:
        indistinguishability is not transitive, and the question is whether anything the
        experiments could tell apart from the leading candidate is still adequate)."""
        replicates = self.protocol.distinguish_replicates
        first = items[0][1]
        return all(
            separation(first, other[1], self.available, replicates) < self.protocol.distinguish_tau
            for other in items[1:]
        )

    def _uncovered_signals(self, fitted: FittedShape) -> list[ExperimentSpec]:
        observed = {o.experiment_id for o in self.admitted()}
        out = []
        for e in self.available:
            if e.experiment_id in observed:
                continue
            mean, _ = prediction(fitted, e)
            if any(abs(mean[x.entry_id]) / x.sigma >= self.safety.z_signal for x in e.entries):
                out.append(e)
        return out

    # -- the decision ---------------------------------------------------------------------------

    def lead(self) -> None:
        """Gate-led claim: when the engine stopped without a claim at its (reduced) cap, take the
        simplest adequate hypothesis the catalog expresses (fewest components, then the lowest
        chi-square; never one the engine refuted) as the claim to probe. It is endorsed only through
        the same probes, registered predictions, rival exclusion and adequacy test as any claim."""
        if self.members or not self.v12.gate_led or not self.admitted():
            return
        refuted = {r.hypothesis_id for r in self.engine.hypotheses if r.ever_refuted}
        ranked = []
        for h in distinct_forward_models(hypothesis_universe(self.catalog)):
            if h.hypothesis_id in refuted:
                continue
            t = self.test(h)
            if t.adequate:
                ranked.append((len(h.components), t.chi2, h.hypothesis_id, h))
        if not ranked:
            return
        h = min(ranked, key=lambda x: x[:3])[3]
        records = list(self.engine.hypotheses)
        if not any(r.hypothesis_id == h.hypothesis_id for r in records):
            tiers = {c.tier for c in h.components}
            records.append(
                HypothesisRecord(
                    hypothesis=h,
                    registered_at=self.step,
                    origin=Origin.INITIAL_CATALOG
                    if tiers <= {Tier.INITIAL}
                    else Origin.EXTENDED_LIBRARY,
                    history=(
                        StateEvent(
                            self.step,
                            DiscoveryState.UNDER_TEST.value,
                            "safety v1.2 gate-led claim: the simplest adequate hypothesis after "
                            "the engine stopped without a claim at its reduced cap",
                        ),
                    ),
                )
            )
        self.engine = replace(
            self.engine,
            outcome=Outcome.NO_EFFECT_BEYOND_NOISE
            if h.is_null
            else Outcome.SURVIVING_PENDING_WARRANT_GATE,
            claim=(h.hypothesis_id,),
            hypotheses=tuple(records),
            handover=None,
        )
        self.members = [h]
        self.gate_led_claim = h.hypothesis_id
        self.extra_notes.append(f"safety v1.2: gate-led claim {h.hypothesis_id}")

    def assess_v12(self) -> SafeRunV12:
        self.lead()
        run = self.assess_v11()
        result, assessment = run.result, run.assessment
        support = tuple((h.fingerprint, self.self_supported(h.fingerprint)) for h in self.members)
        endorsed = assessment.decision is SafetyDecision.ENDORSE_PENDING_WARRANT_GATE
        open_rivals = (
            [r[1] for r in self.open_rivals()] if endorsed and self.v12.rival_exclusion else []
        )
        if open_rivals:
            self.extra_notes.append(
                "safety v1.2: not endorsed while distinguishable rivals stay adequate: "
                + ", ".join(open_rivals[:4])
            )
        if endorsed and (
            (self.v12.require_registered_support and not all(ok for _, ok in support))
            or open_rivals
        ):
            why = (
                "safety v1.2: not endorsed (a distinguishable rival is still adequate)"
                if open_rivals
                else "safety v1.2: not endorsed (no registered risky prediction of the claim "
                "passed the ledger rule)"
            )
            records = [
                transition(r, self.step, DiscoveryState.STOPPED, why, ())
                if r.hypothesis_id in result.claim and r.state is not DiscoveryState.REFUTED
                else r
                for r in result.hypotheses
            ]
            result = replace(
                result,
                outcome=Outcome.STOPPED_INSUFFICIENT_VALIDATION,
                claim=(),
                handover=None,
                hypotheses=tuple(records),
                notes=(*result.notes, why),
            )
            assessment = replace(
                assessment,
                decision=SafetyDecision.ABSTAIN,
                reason=AbstentionReason.ADEQUACY_UNVERIFIED,
                confidence=ConfidenceLevel.PROVISIONAL,
                notes=(*assessment.notes, why),
            )
        attempt = None
        if assessment.catalog_incomplete:
            attempt = self.discover()
        if attempt is not None:
            line = f"safety v1.2 discovery: {attempt.reason}; " + (
                f"ANSWERED new mechanism {attempt.answered.candidate_id} "
                f"({' + '.join(attempt.answered.terms)})"
                if attempt.answered
                else (
                    f"PROPOSAL only {attempt.proposal.candidate_id}"
                    if attempt.proposal
                    else "no proposal"
                )
            )
            result = replace(
                result,
                observations=tuple(self.observations),
                steps=tuple(self.steps),
                spent=self.spent,
                notes=(*result.notes, line),
            )
        allocation = Allocation(
            budget=self.budget.total,
            ladder=self.ladder,
            engine_cap=self.engine_cap,
            charged_by_engine_runs=self.charged_by_engine_runs,
            orphan_measurements=self.orphans,
            reserve=self.budget.total - self.charged_by_engine_runs,
        )
        return SafeRunV12(
            result=result,
            engine=self.original_engine,
            assessment=assessment,
            refit=run.refit,
            member_tests=run.member_tests,
            allocation=allocation,
            registrations=tuple(self.registrations),
            support=support,
            discovery=attempt,
            notes=tuple(self.extra_notes),
        )


def safe_investigate_v12(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
    safety: SafetyProtocolV12 = SAFETY_V12,
    grammar: TermGrammar | None = None,
) -> SafeRunV12:
    """The frozen engine on the anytime ladder (or once, at the cap), then the v1.2 gate."""
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
    gate = _GateV12(
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
    )
    return gate.assess_v12()


def safe_runner_v12(
    safety: SafetyProtocolV12 = SAFETY_V12, grammar: TermGrammar | None = None
) -> Callable[..., DiscoveryResult]:
    def runner(**kwargs: object) -> DiscoveryResult:
        return safe_investigate_v12(safety=safety, grammar=grammar, **kwargs).result  # type: ignore[arg-type]

    return runner


__all__ = [
    "grammar_shapes",
    "hypothesis_prediction",
    "safe_investigate_v12",
    "safe_runner_v12",
]
