"""The offline Discovery Loop: discriminate, notice what nothing explains, test it, and reframe.

ONE ENGINE, CONFIGURED BY A PRE-REGISTERED PROTOCOL. `investigate` runs both the "existing LIB
style" arm (a fixed initial set, discrimination-per-cost selection, refutation -- every discovery
switch off) and the discovery arm (all on). Each step:

    1. evaluate     every live hypothesis is fitted to the ADMITTED observations (never the
                    motivating one, never one attributed to noise). A fit with p < alpha is a
                    refutation, recorded with its leave-one-out basis (the observations it hinges
                    on). Guard: a hypothesis is never refuted while one that no available experiment
                    separates from it survives -- it is kept, INDISTINGUISHABLE. A live hypothesis
                    is SURVIVING only through an observation taken AFTER its registration from a
                    test it could have failed (`risky`): no retrospective self-support.
    2. anomalies    an observation outside the noise model under every live hypothesis is an
                    UNEXPLAINED anomaly; when every hypothesis has failed, each observation that is
                    the sole basis of a refutation is one too. Nothing removes an anomaly record.
    3. noise test   the pre-registered test for an unexplained anomaly is one replication. If a
                    declared hypothesis explains the replicate and, on the entry where the original
                    deviates most, the replicate sides with it rather than with the original, the
                    original is ATTRIBUTED_TO_NOISE: it is excluded, and each refutation it was
                    pivotal for is re-examined without it (a hypothesis that now fits returns to
                    UNDER_TEST, never to support). Otherwise the deviation is REPRODUCED when
                    original and replicate agree, or UNSTABLE (stays UNEXPLAINED) when they do not.
    4. reframe      when nothing live remains, or a tested anomaly persists unexplained: question
                    the measurement chain, then widen the mechanism space (regime variants, extended
                    classes, compositions -- only those consistent with the admitted data AND
                    distinguishable from everything held), then narrow the scope and stop. Each
                    reframing is an append-only record citing the failed hypotheses and anomalies.
    5. claim/stop   exactly one distinguishable class left, every member prospectively tested, no
                    persistent anomaly: the class is SURVIVING, pending the Causal Warrant Gate.
                    Before reporting it, the closure adds every declared hypothesis that no
                    available experiment separates from it, so a class is never resolved by fiat.
                    Otherwise: the most discriminating affordable experiment per unit cost; none ->
                    STOPPED_INSUFFICIENT_VALIDATION.

The loop never confirms. It has no path to a belief event, a root-cause conclusion or a warrant;
`tests/unit/test_discovery_governance.py` holds that structurally.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import NO_AVAILABLE_EXPERIMENT, SeparationOracle
from lab_brain.discovery.forward import Fit, fit, predict, standardized_distance
from lab_brain.discovery.handover import build_handover
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    AnomalyKind,
    AnomalyRecord,
    AnomalyState,
    Budget,
    DiscoveryResult,
    DiscoveryState,
    Hypothesis,
    HypothesisRecord,
    MechanismClass,
    Observation,
    Origin,
    Outcome,
    Purpose,
    ReframingKind,
    ReframingRecord,
    ReproductionResult,
    ReproductionTest,
    StateEvent,
    StepRecord,
    Tier,
    anomaly_transition,
    make_hypothesis,
    reinstatement_reason,
    transition,
)
from lab_brain.discovery.protocol import DiscoveryProtocol


class Laboratory(Protocol):
    """Where measurements come from. Offline, a seeded synthetic world."""

    def motivating(self) -> tuple[str, tuple[tuple[str, float], ...]]:
        """The observation that started the investigation: (experiment id, values)."""
        ...

    def measure(
        self, experiment_id: str, *, replicate: int, session: int
    ) -> tuple[tuple[str, float], ...]:
        """One run of an experiment: the `replicate`-th of it, the `session`-th of the run."""
        ...


class BudgetExceeded(RuntimeError):
    """An experiment was about to be run that the budget does not cover. Never caught."""


@dataclass(frozen=True)
class _Action:
    experiment_id: str
    purpose: Purpose
    utility: float
    #: The anomaly a noise test is for, or the observation a decisive replication repeats.
    target: str | None = None


def prior_weight(hypothesis: Hypothesis, protocol: DiscoveryProtocol) -> float:
    """Selection weight from the catalog prior; data-motivated hypotheses get the declared floor."""
    if hypothesis.is_null:
        return protocol.null_prior

    def one(c: MechanismClass) -> float:
        if c.tier is Tier.INITIAL and c.prior > 0:
            return c.prior
        return max(c.prior, protocol.widened_prior_floor)

    return math.prod(one(c) for c in hypothesis.components)


def hypothesis_universe(catalog: DiscoveryCatalog) -> tuple[Hypothesis, ...]:
    """Every hypothesis the catalog expresses: the noise model, each class, each family pair."""
    singles = [make_hypothesis(m) for m in catalog.mechanisms]
    pairs = [
        make_hypothesis(a, b)
        for i, a in enumerate(catalog.mechanisms)
        for b in catalog.mechanisms[i + 1 :]
        if a.family != b.family
    ]
    return (NULL_HYPOTHESIS, *singles, *pairs)


class _Investigation:
    """The working state of one call to `investigate`. Local to the call; nothing global."""

    def __init__(
        self,
        *,
        arm: str,
        catalog: DiscoveryCatalog,
        oracle: SeparationOracle,
        protocol: DiscoveryProtocol,
        budget: Budget,
        lab: Laboratory,
    ) -> None:
        self.arm = arm
        self.catalog = catalog
        self.oracle = oracle
        self.p = protocol
        self.budget = budget
        self.lab = lab
        self.experiments = oracle.experiments
        self.all_experiments = {
            e.experiment_id: e
            for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
        }
        self.records: dict[str, HypothesisRecord] = {}
        self.order: list[str] = []
        self.observations: list[Observation] = []
        self.noise_excluded: set[str] = set()
        self.anomalies: dict[str, AnomalyRecord] = {}
        self.reframings: list[ReframingRecord] = []
        self.steps: list[StepRecord] = []
        self.notes: list[str] = []
        self.step = 0
        self.spent = 0
        self.session = 0
        self.replicates: dict[str, int] = {}
        self.noise_tests_used = 0
        self.widen_rounds = 0
        self.chain_reviewed = False
        self.chain_priority = False
        self.fits: dict[str, Fit] = {}
        self.replications: list[ReproductionTest] = []
        self.cannot_exclude: list[str] = []
        self.outcome: Outcome | None = None
        self.claim: tuple[str, ...] = ()

    # -- registry -----------------------------------------------------------------------------

    def register(self, hypothesis: Hypothesis, origin: Origin, reason: str) -> str | None:
        if hypothesis.hypothesis_id in self.records:
            return None
        twin = next(
            (
                r
                for r in (self.records[i] for i in self.order)
                if r.alias_of is None and r.hypothesis.fingerprint == hypothesis.fingerprint
            ),
            None,
        )
        if twin is not None:
            self.records[hypothesis.hypothesis_id] = HypothesisRecord(
                hypothesis=hypothesis,
                registered_at=self.step,
                origin=origin,
                history=(
                    StateEvent(
                        self.step,
                        DiscoveryState.INDISTINGUISHABLE.value,
                        f"identical forward model to {twin.hypothesis_id}: merged, not counted "
                        "or tested separately",
                        (twin.hypothesis_id,),
                    ),
                ),
                alias_of=twin.hypothesis_id,
            )
            self.order.append(hypothesis.hypothesis_id)
            return None
        self.records[hypothesis.hypothesis_id] = HypothesisRecord(
            hypothesis=hypothesis,
            registered_at=self.step,
            origin=origin,
            history=(StateEvent(self.step, DiscoveryState.PROPOSED.value, reason),),
        )
        self.order.append(hypothesis.hypothesis_id)
        return hypothesis.hypothesis_id

    def held(self) -> list[HypothesisRecord]:
        return [self.records[i] for i in self.order if self.records[i].alias_of is None]

    def live(self) -> list[HypothesisRecord]:
        return [r for r in self.held() if r.is_live]

    def held_fingerprints(self) -> set[str]:
        return {r.hypothesis.fingerprint for r in self.records.values()}

    def admitted(self, exclude: frozenset[str] = frozenset()) -> list[Observation]:
        return [
            o
            for o in self.observations
            if not o.motivating
            and o.observation_id not in self.noise_excluded
            and o.observation_id not in exclude
        ]

    def observation(self, observation_id: str) -> Observation:
        return next(o for o in self.observations if o.observation_id == observation_id)

    def fit(self, hypothesis: Hypothesis, observations: Sequence[Observation]) -> Fit:
        return fit(hypothesis, observations, self.all_experiments)

    # -- support ------------------------------------------------------------------------------

    def risky(self, hypothesis: Hypothesis, experiment_id: str) -> bool:
        """Whether one run of the experiment could have refuted the hypothesis (worst case)."""
        threshold = self.p.risky_separation
        if not hypothesis.is_null and (
            self.oracle.experiment_separation(hypothesis, NULL_HYPOTHESIS, experiment_id)
            >= threshold
        ):
            return True
        return any(
            self.oracle.experiment_separation(hypothesis, r.hypothesis, experiment_id) >= threshold
            for r in self.held()
            if r.hypothesis.hypothesis_id != hypothesis.hypothesis_id
        )

    def prospective_support(self, record: HypothesisRecord) -> tuple[str, ...]:
        """Admitted observations taken after registration from a test it could have failed."""
        return tuple(
            o.observation_id
            for o in self.admitted()
            if o.taken_at > record.registered_at and self.risky(record.hypothesis, o.experiment_id)
        )

    def passed_experiments(self, record: HypothesisRecord) -> set[str]:
        return {self.observation(i).experiment_id for i in self.prospective_support(record)}

    def supported(self, record: HypothesisRecord) -> bool:
        """Severity: prospective passes on `min_prospective_tests` distinct experiments."""
        return len(self.passed_experiments(record)) >= self.p.min_prospective_tests

    # -- step 1: evaluate ----------------------------------------------------------------------

    def evaluate(self) -> None:
        admitted = self.admitted()
        live = self.live()
        self.fits = {r.hypothesis_id: self.fit(r.hypothesis, admitted) for r in live}
        alpha = self.p.alpha_refute
        leader = (
            min(live, key=lambda r: (self.fits[r.hypothesis_id].chi2, r.hypothesis_id))
            if live
            else None
        )
        best = self.fits[leader.hypothesis_id].chi2 if leader is not None else 0.0
        failing = [r for r in live if self.fails(self.fits[r.hypothesis_id], best)]
        passing = [r for r in live if not self.fails(self.fits[r.hypothesis_id], best)]
        for record in failing:
            f = self.fits[record.hypothesis_id]
            twin = None
            if self.p.indistinguishable_guard:
                twin = next(
                    (
                        s
                        for s in passing
                        if not self.oracle.distinguishable(record.hypothesis, s.hypothesis)
                    ),
                    None,
                )
            if twin is not None:
                self.records[record.hypothesis_id] = transition(
                    record,
                    self.step,
                    DiscoveryState.INDISTINGUISHABLE,
                    f"fails its own fit (p={f.p_value:.2e}) but {NO_AVAILABLE_EXPERIMENT} and "
                    f"{twin.hypothesis_id}, which survives; not refuted by fiat",
                    (twin.hypothesis_id,),
                )
                continue
            assert leader is not None
            basis = self.refutation_basis(record.hypothesis, leader.hypothesis, admitted)
            if f.p_value < alpha:
                why = f"p={f.p_value:.2e} < alpha={alpha}"
            else:
                why = (
                    f"chi2 exceeds the best live fit ({leader.hypothesis_id}, {best:.2f}) by "
                    f"{f.chi2 - best:.2f} > {self.p.delta_chi2_refute}"
                )
            self.records[record.hypothesis_id] = transition(
                record,
                self.step,
                DiscoveryState.REFUTED,
                f"chi2={f.chi2:.2f} over {f.n} entries, dof={f.dof}: {why}",
                basis,
            )
        for record in passing:
            support = self.prospective_support(record)
            if self.supported(record):
                state, reason = (
                    DiscoveryState.SURVIVING,
                    f"passed tests on {len(self.passed_experiments(record))} distinct experiments "
                    "taken after its registration, each one it could have failed",
                )
            elif admitted:
                state, reason = (
                    DiscoveryState.UNDER_TEST,
                    "consistent with the admitted data; not yet through the required "
                    "prospective tests",
                )
            else:
                state, reason = DiscoveryState.PROPOSED, "registered; nothing admitted yet"
            if record.state is not state:
                self.records[record.hypothesis_id] = transition(
                    record, self.step, state, reason, support
                )

    def fails(self, f: Fit, best_chi2: float | None) -> bool:
        """The pre-registered refutation rule: absolute misfit, or far worse than the best rival."""
        if f.p_value < self.p.alpha_refute:
            return True
        return best_chi2 is not None and f.chi2 - best_chi2 > self.p.delta_chi2_refute

    def refutation_basis(
        self, hypothesis: Hypothesis, leader: Hypothesis, admitted: Sequence[Observation]
    ) -> tuple[str, ...]:
        """Leave-one-out: the observations without which the hypothesis would not be refuted."""
        out = []
        for o in admitted:
            rest = [x for x in admitted if x is not o]
            own = self.fit(hypothesis, rest)
            rival = self.fit(leader, rest)
            if not self.fails(own, min(own.chi2, rival.chi2)):
                out.append(o.observation_id)
        return tuple(out)

    # -- step 2: anomalies ---------------------------------------------------------------------

    def _new_anomaly(
        self,
        kind: AnomalyKind,
        observation_id: str,
        hypotheses: tuple[str, ...],
        max_abs_z: float,
        reason: str,
    ) -> None:
        anomaly_id = f"anm:{len(self.anomalies) + 1}"
        self.anomalies[anomaly_id] = AnomalyRecord(
            anomaly_id=anomaly_id,
            kind=kind,
            observation_id=observation_id,
            detected_at=self.step,
            hypotheses_at_detection=hypotheses,
            max_abs_z=max_abs_z,
            history=(StateEvent(self.step, AnomalyState.UNEXPLAINED.value, reason),),
        )

    def detect_unexplained(self, observation: Observation) -> None:
        live = self.live()
        if not live:
            return
        admitted = self.admitted()
        zs = [self.fit(r.hypothesis, admitted).z_of(observation.observation_id) for r in live]
        least = min(zs)
        if least > self.p.z_anomaly:
            self._new_anomaly(
                AnomalyKind.UNEXPLAINED_OBSERVATION,
                observation.observation_id,
                tuple(sorted(r.hypothesis_id for r in live)),
                least,
                f"outside the noise model under every live hypothesis (smallest max |z| = "
                f"{least:.2f} > {self.p.z_anomaly})",
            )

    def dependents(self, observation_id: str) -> tuple[str, ...]:
        """Refuted hypotheses whose standing refutation this observation is pivotal for."""
        return tuple(
            sorted(
                r.hypothesis_id
                for r in self.held()
                if r.state is DiscoveryState.REFUTED and observation_id in r.history[-1].basis
            )
        )

    def sole_dependents(self, observation_id: str) -> tuple[str, ...]:
        """Refuted hypotheses whose standing refutation rests on this observation alone."""
        return tuple(
            sorted(
                r.hypothesis_id
                for r in self.held()
                if r.state is DiscoveryState.REFUTED and r.history[-1].basis == (observation_id,)
            )
        )

    def detect_sole_bases(self) -> None:
        if self.live():
            return
        anomalous = {a.observation_id for a in self.anomalies.values()}
        bases = sorted(
            {
                r.history[-1].basis[0]
                for r in self.held()
                if r.state is DiscoveryState.REFUTED and len(r.history[-1].basis) == 1
            }
        )
        for observation_id in bases:
            if observation_id in anomalous:
                continue
            dependents = self.sole_dependents(observation_id)
            first = self.records[dependents[0]].hypothesis
            z = self.fit(first, self.admitted()).z_of(observation_id)
            self._new_anomaly(
                AnomalyKind.SOLE_REFUTATION_BASIS,
                observation_id,
                dependents,
                z,
                f"every hypothesis has failed; {', '.join(dependents)} rest on this observation "
                "alone",
            )

    def anomaly_observations(self, anomaly: AnomalyRecord) -> tuple[str, ...]:
        return (
            anomaly.observation_id,
            *(t.replicate_observation_id for t in anomaly.tests),
        )

    def update_anomalies(self) -> None:
        if not self.p.anomalies:
            return
        for anomaly_id in sorted(self.anomalies, key=lambda a: int(a.split(":")[1])):
            anomaly = self.anomalies[anomaly_id]
            if anomaly.state is AnomalyState.ATTRIBUTED_TO_NOISE:
                continue
            observed = [
                x for x in self.anomaly_observations(anomaly) if x not in self.noise_excluded
            ]
            fitting = [
                r
                for r in self.live()
                if all(self.fits[r.hypothesis_id].z_of(x) <= self.p.z_anomaly for x in observed)
            ]
            surviving = [r for r in fitting if r.state is DiscoveryState.SURVIVING]
            if surviving:
                state, reason, basis = (
                    AnomalyState.EXPLAINED,
                    "accounted for by a hypothesis that survived a prospective test",
                    tuple(r.hypothesis_id for r in surviving),
                )
            elif fitting:
                state, reason, basis = (
                    AnomalyState.ACCOMMODATED,
                    "fitted by a live hypothesis not yet through a prospective test -- "
                    "accommodation, not explanation",
                    tuple(r.hypothesis_id for r in fitting),
                )
            else:
                state, reason, basis = (
                    AnomalyState.UNEXPLAINED,
                    "no live hypothesis accounts for it",
                    (),
                )
            if anomaly.state is not state:
                self.anomalies[anomaly_id] = anomaly_transition(
                    anomaly, self.step, state, reason, basis
                )

    # -- step 3: noise test ---------------------------------------------------------------------

    def replication_test(self, original: Observation, replicate: Observation) -> ReproductionTest:
        """The pre-registered replication test (see the module doc, step 3)."""
        experiment = self.all_experiments[original.experiment_id]
        disagreement = max(
            abs(original.value(e.entry_id) - replicate.value(e.entry_id))
            / (math.sqrt(2.0) * e.sigma)
            for e in experiment.entries
        )
        candidates = sorted(
            {r.hypothesis_id for r in self.live()} | set(self.dependents(original.observation_id))
        )
        without = self.admitted(exclude=frozenset({original.observation_id}))
        fits = {h: self.fit(self.records[h].hypothesis, without) for h in candidates}
        explaining = [
            h
            for h in candidates
            if fits[h].p_value >= self.p.alpha_refute
            and fits[h].z_of(replicate.observation_id) <= self.p.z_anomaly
        ]
        reference: str | None = None
        if explaining:
            # A declared hypothesis explains the replicate. On the entry where the original
            # deviates most from that hypothesis, does the replicate side with the hypothesis or
            # with the original?
            reference = min(explaining, key=lambda h: (fits[h].chi2, h))
            predicted = predict(
                self.records[reference].hypothesis, fits[reference].theta, experiment
            )
            worst = max(
                experiment.entries,
                key=lambda e: abs(original.value(e.entry_id) - predicted[e.entry_id]) / e.sigma,
            )
            to_hypothesis = abs(replicate.value(worst.entry_id) - predicted[worst.entry_id])
            to_original = abs(replicate.value(worst.entry_id) - original.value(worst.entry_id))
            result = (
                ReproductionResult.NOT_REPRODUCED_NOISE
                if to_hypothesis < to_original
                else ReproductionResult.REPRODUCED
            )
        elif disagreement <= self.p.z_reproduce:
            result = ReproductionResult.REPRODUCED
        else:
            result = ReproductionResult.NOT_REPRODUCED_UNSTABLE
        if result is ReproductionResult.REPRODUCED:
            reference = None
        self.noise_tests_used += 1
        return ReproductionTest(
            step=self.step,
            original_observation_id=original.observation_id,
            replicate_observation_id=replicate.observation_id,
            result=result,
            max_disagreement_z=disagreement,
            reference_hypothesis_id=reference,
        )

    def decisive_replication(self, observation_id: str, replicate: Observation) -> None:
        original = self.observation(observation_id)
        test = self.replication_test(original, replicate)
        self.replications.append(test)
        if test.result is ReproductionResult.NOT_REPRODUCED_NOISE:
            self.noise_excluded.add(original.observation_id)
            self.reinstate(original.observation_id, replicate.observation_id)
        elif test.result is ReproductionResult.NOT_REPRODUCED_UNSTABLE:
            self._new_anomaly(
                AnomalyKind.SOLE_REFUTATION_BASIS,
                original.observation_id,
                self.dependents(original.observation_id),
                test.max_disagreement_z,
                "its decisive replication disagrees with it and is itself unexplained",
            )
            anomaly_id = f"anm:{len(self.anomalies)}"
            self.anomalies[anomaly_id] = replace(self.anomalies[anomaly_id], tests=(test,))

    def reproduction_test(self, anomaly_id: str, replicate: Observation) -> None:
        anomaly = self.anomalies[anomaly_id]
        original = self.observation(anomaly.observation_id)
        test = self.replication_test(original, replicate)
        result, disagreement, reference = (
            test.result,
            test.max_disagreement_z,
            test.reference_hypothesis_id,
        )
        anomaly = replace(anomaly, tests=(*anomaly.tests, test))
        if result is ReproductionResult.NOT_REPRODUCED_NOISE:
            self.anomalies[anomaly_id] = anomaly_transition(
                anomaly,
                self.step,
                AnomalyState.ATTRIBUTED_TO_NOISE,
                f"pre-registered replication {replicate.observation_id} disagrees with it "
                f"(max {disagreement:.2f} > {self.p.z_reproduce} sqrt(2) sigma) and fits "
                f"{reference}",
                (replicate.observation_id,),
            )
            self.noise_excluded.add(original.observation_id)
            self.reinstate(original.observation_id, anomaly_id)
        else:
            self.anomalies[anomaly_id] = anomaly_transition(
                anomaly,
                self.step,
                AnomalyState.UNEXPLAINED,
                "reproduced by its replication"
                if result is ReproductionResult.REPRODUCED
                else "not reproduced, and the replicate is unexplained too -- not noise",
                (replicate.observation_id,),
            )

    def reinstate(self, observation_id: str, cause: str) -> None:
        """Re-examine every refutation `observation_id` was pivotal for, now it is noise."""
        admitted = self.admitted()
        live_chi2 = [self.fit(r.hypothesis, admitted).chi2 for r in self.live()]
        for record in self.held():
            if record.state is not DiscoveryState.REFUTED:
                continue
            if observation_id not in record.history[-1].basis:
                continue
            own = self.fit(record.hypothesis, admitted)
            if self.fails(own, min([*live_chi2, own.chi2])):
                continue
            self.records[record.hypothesis_id] = transition(
                record,
                self.step,
                DiscoveryState.UNDER_TEST,
                reinstatement_reason(observation_id),
                (cause, observation_id),
            )

    # -- step 4: reframe ------------------------------------------------------------------------

    def _screen(
        self, candidates: Sequence[Hypothesis], limit: int
    ) -> tuple[list[Hypothesis], int, int, int]:
        """Candidates consistent with the admitted data and distinguishable from all held."""
        admitted = self.admitted()
        held_fps = self.held_fingerprints()
        live_chi2 = [self.fit(r.hypothesis, admitted).chi2 for r in self.live()]
        best = min(live_chi2) if live_chi2 else None
        scored: list[tuple[float, str, Hypothesis]] = []
        refuted_by_data = 0
        duplicates = 0
        for h in candidates:
            if h.fingerprint in held_fps or h.hypothesis_id in self.records:
                duplicates += 1
                continue
            f = self.fit(h, admitted)
            if self.fails(f, None if best is None else min(best, f.chi2)):
                refuted_by_data += 1
                continue
            scored.append((-(prior_weight(h, self.p) * f.p_value), h.hypothesis_id, h))
        scored.sort(key=lambda t: (t[0], t[1]))
        accepted: list[Hypothesis] = []
        indistinguishable = 0
        reference = [r.hypothesis for r in self.held()]
        for _, _, h in scored:
            if len(accepted) >= limit:
                break
            if any(not self.oracle.distinguishable(h, r) for r in (*reference, *accepted)):
                indistinguishable += 1
                continue
            accepted.append(h)
        return accepted, refuted_by_data, indistinguishable, duplicates

    def _record(
        self,
        kind: ReframingKind,
        added: Sequence[str],
        considered: int,
        rationale: str,
        subjects: Sequence[str] = (),
    ) -> None:
        if not self.p.reframing:
            return
        self.reframings.append(
            ReframingRecord(
                reframing_id=f"rfr:{len(self.reframings) + 1}",
                kind=kind,
                step=self.step,
                failed_hypotheses=tuple(
                    sorted(r.hypothesis_id for r in self.held() if r.ever_refuted)
                ),
                anomalies=tuple(
                    sorted(
                        a.anomaly_id
                        for a in self.anomalies.values()
                        if a.state is not AnomalyState.ATTRIBUTED_TO_NOISE
                    )
                ),
                added_hypotheses=tuple(added),
                considered=considered,
                rationale=rationale,
                subjects=tuple(subjects),
            )
        )

    def reframe(self, persistent: Sequence[AnomalyRecord]) -> bool:
        """Apply the pre-registered reframing table. True if hypotheses were added."""
        pending = ", ".join(a.anomaly_id for a in persistent)
        why = (
            "every live hypothesis has failed"
            if not self.live()
            else f"tested anomalies persist unexplained ({pending})"
        )
        if self.p.measurement_chain_review and not self.chain_reviewed:
            self.chain_reviewed = True
            held = self.held_fingerprints()
            chain = [make_hypothesis(m) for m in self.catalog.measurement_chain]
            unheld = [h for h in chain if h.fingerprint not in held]
            if unheld:
                accepted, by_data, indist, _ = self._screen(unheld, self.p.widen_batch)
                added = [
                    i
                    for h in accepted
                    if (
                        i := self.register(
                            h,
                            Origin.MEASUREMENT_CHAIN_REVIEW,
                            f"measurement chain questioned: {why}",
                        )
                    )
                ]
                self.chain_priority = bool(added)
                self._record(
                    ReframingKind.QUESTION_THE_MEASUREMENT_CHAIN,
                    added,
                    len(unheld),
                    f"{why}; declared measurement-chain classes not held: {len(unheld)}; "
                    f"refuted by existing data: {by_data}; indistinguishable from held: {indist}; "
                    f"added: {len(added)}",
                )
                if added:
                    return True
        if self.p.expansion and self.widen_rounds < self.p.max_widen_rounds:
            self.widen_rounds += 1
            families = {f for r in self.held() for f in r.hypothesis.families}
            variants = [make_hypothesis(m) for m in self.catalog.variants if m.family in families]
            extended = [make_hypothesis(m) for m in self.catalog.extended]
            mechanisms = self.catalog.mechanisms
            pairs = [
                make_hypothesis(a, b)
                for i, a in enumerate(mechanisms)
                for b in mechanisms[i + 1 :]
                if a.family != b.family
            ]
            candidates = [*variants, *extended, *pairs]
            accepted, by_data, indist, dupes = self._screen(candidates, self.p.widen_batch)
            origins = {
                Tier.VARIANT: Origin.REGIME_VARIANT,
                Tier.EXTENDED: Origin.EXTENDED_LIBRARY,
                Tier.INITIAL: Origin.EXTENDED_LIBRARY,
            }
            added = []
            for h in accepted:
                origin = (
                    Origin.COMPOSITION if len(h.components) > 1 else origins[h.components[0].tier]
                )
                registered = self.register(h, origin, f"widened (round {self.widen_rounds}): {why}")
                if registered:
                    added.append(registered)
            self._record(
                ReframingKind.WIDEN_MECHANISM_SPACE,
                added,
                len(candidates),
                f"{why}; candidates {len(candidates)} (variants {len(variants)}, extended "
                f"{len(extended)}, compositions {len(pairs)}); already held {dupes}; refuted by "
                f"existing data {by_data}; indistinguishable from held {indist}; added "
                f"{len(added)} (batch limit {self.p.widen_batch})",
            )
            if added:
                return True
        if persistent:
            bad = sorted({self.observation(a.observation_id).experiment_id for a in persistent})
            scope = [o for o in self.admitted() if o.experiment_id not in bad]
            if scope:
                fitting = [
                    r.hypothesis_id
                    for r in self.held()
                    if self.fit(r.hypothesis, scope).p_value >= self.p.alpha_refute
                ]
                if fitting:
                    self._record(
                        ReframingKind.NARROW_SCOPE,
                        (),
                        len(self.held()),
                        f"outside {', '.join(bad)}, {', '.join(fitting)} account for the admitted "
                        "data; the anomalies there stay UNEXPLAINED and no claim is made",
                        fitting,
                    )
        self._record(
            ReframingKind.STOP_INSUFFICIENT,
            (),
            0,
            f"{why}, and the reframing table is exhausted (chain reviewed: {self.chain_reviewed}, "
            f"widening rounds: {self.widen_rounds}/{self.p.max_widen_rounds})",
        )
        return False

    def close_rivals(self, members: Sequence[HypothesisRecord]) -> bool:
        """Register the declared rivals a claim would otherwise ignore. True if any were added."""
        complexity = max(len(r.hypothesis.components) for r in members)
        held = self.held_fingerprints()
        candidates = [
            u
            for u in hypothesis_universe(self.catalog)
            if len(u.components) <= complexity and u.fingerprint not in held
        ]
        accepted, by_data, indist, _ = self._screen(candidates, self.p.widen_batch)
        added = []
        for h in accepted:
            origin = (
                Origin.COMPOSITION
                if len(h.components) > 1
                else Origin.REGIME_VARIANT
                if h.components[0].tier is Tier.VARIANT
                else Origin.EXTENDED_LIBRARY
            )
            registered = self.register(
                h, origin, "rival closure: a declared alternative the admitted data do not refute"
            )
            if registered:
                added.append(registered)
        if added:
            self._record(
                ReframingKind.WIDEN_MECHANISM_SPACE,
                added,
                len(candidates),
                f"rival closure before claiming {', '.join(r.hypothesis_id for r in members)}: "
                f"declared alternatives of no greater complexity {len(candidates)}; refuted by "
                f"existing data {by_data}; indistinguishable from held {indist} (left to the "
                f"class closure); added {len(added)}",
            )
        return bool(added)

    # -- step 5: selection ---------------------------------------------------------------------

    def affordable(self, purpose_filter: Callable[[str], bool] | None = None) -> list[str]:
        remaining = self.budget.total - self.spent
        return [
            e.experiment_id
            for e in self.oracle.available
            if e.cost <= remaining and (purpose_filter is None or purpose_filter(e.experiment_id))
        ]

    def discrimination_utility(
        self, live: Sequence[HypothesisRecord], group: dict[str, int], experiment_id: str
    ) -> float:
        experiment = self.experiments[experiment_id]
        weights = {
            r.hypothesis_id: prior_weight(r.hypothesis, self.p)
            * max(self.fits[r.hypothesis_id].p_value, 1e-6)
            for r in live
        }
        total = math.fsum(weights.values()) or 1.0
        predictions = {
            r.hypothesis_id: predict(r.hypothesis, self.fits[r.hypothesis_id].theta, experiment)
            for r in live
        }
        value = 0.0
        ids = [r.hypothesis_id for r in live]
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if group[a] == group[b]:
                    continue
                d = standardized_distance(predictions[a], predictions[b], experiment)
                value += (
                    (weights[a] / total) * (weights[b] / total) * min(1.0, d / self.p.selection_tau)
                )
        return value / experiment.cost

    def select(
        self, live: Sequence[HypothesisRecord], classes: Sequence[tuple[str, ...]]
    ) -> tuple[str, float] | None:
        group = {h: i for i, members in enumerate(classes) for h in members}
        options = self.affordable()
        if self.chain_priority:
            chain = [i for i in options if self.experiments[i].chain_check]
            scored = [(self.discrimination_utility(live, group, i), i) for i in chain]
            useful = [s for s in scored if s[0] > 1e-9]
            if useful:
                best = max(useful, key=lambda s: (s[0], -self.experiments[s[1]].cost))
                return best[1], best[0]
            self.chain_priority = False
        best_id: str | None = None
        best_value = 1e-9
        for experiment_id in options:
            value = self.discrimination_utility(live, group, experiment_id)
            if value > best_value + 1e-12:
                best_id, best_value = experiment_id, value
        return None if best_id is None else (best_id, best_value)

    def prospective_test(self, members: Sequence[HypothesisRecord]) -> str | None:
        """The cheapest affordable experiment some unsupported member could fail and has not yet
        passed (severity counts distinct experiments); ties by declared order."""
        options = []
        order = {e.experiment_id: i for i, e in enumerate(self.oracle.available)}
        for experiment_id in self.affordable():
            if any(
                experiment_id not in self.passed_experiments(r)
                and self.risky(r.hypothesis, experiment_id)
                for r in members
            ):
                cost = self.experiments[experiment_id].cost
                options.append((cost, order[experiment_id], experiment_id))
        return min(options)[2] if options else None

    def decisive_observation(self) -> str | None:
        """An unreplicated observation on which some rival's refutation rests alone, if any."""
        if not (self.p.decisive_replication and self.p.noise_test):
            return None
        if self.noise_tests_used >= self.p.max_noise_tests:
            return None
        admitted = self.admitted()
        runs: dict[str, int] = {}
        for o in admitted:
            runs[o.experiment_id] = runs.get(o.experiment_id, 0) + 1
        replicated = {t.original_observation_id for t in self.replications}
        options = []
        for o in admitted:
            if runs[o.experiment_id] > 1 or o.observation_id in replicated:
                continue
            if o.experiment_id not in self.affordable():
                continue
            dependents = self.dependents(o.observation_id)
            if dependents:
                options.append((-len(dependents), o.taken_at, o.observation_id))
        return min(options)[2] if options else None

    # -- the loop -------------------------------------------------------------------------------

    def next_action(self) -> _Action | None:
        if self.p.noise_test and self.noise_tests_used < self.p.max_noise_tests:
            pending = [
                a
                for a in self.anomalies.values()
                if a.state is AnomalyState.UNEXPLAINED
                and not a.tests
                and a.observation_id not in self.noise_excluded
            ]
            options = []
            for a in pending:
                experiment_id = self.observation(a.observation_id).experiment_id
                if experiment_id in self.affordable():
                    weight = len(self.dependents(a.observation_id)) + 1
                    options.append((-weight, a.detected_at, a.anomaly_id, experiment_id))
            if options:
                _, _, anomaly_id, experiment_id = min(options)
                return _Action(experiment_id, Purpose.NOISE_TEST, 0.0, anomaly_id)
        live = self.live()
        persistent = [
            a for a in self.anomalies.values() if a.state is AnomalyState.UNEXPLAINED and a.tests
        ]
        if not live or persistent:
            if (self.p.expansion or self.p.measurement_chain_review) and self.reframe(persistent):
                self.evaluate()
                self.update_anomalies()
                return self.next_action()
            self.stop(Outcome.STOPPED_UNEXPLAINED)
            return None
        hypotheses = [r.hypothesis for r in live]
        classes = (
            self.oracle.classes(hypotheses)
            if self.p.report_classes
            else tuple((r.hypothesis_id,) for r in live)
        )
        if len(classes) == 1:
            members = [self.records[i] for i in classes[0]]
            untested = [r for r in members if not self.supported(r)]
            if not untested:
                decisive = self.decisive_observation()
                if decisive is not None:
                    experiment_id = self.observation(decisive).experiment_id
                    return _Action(experiment_id, Purpose.DECISIVE_REPLICATION, 0.0, decisive)
                if self.p.rival_closure and self.close_rivals(members):
                    self.evaluate()
                    self.update_anomalies()
                    return self.next_action()
                self.conclude(classes[0])
                return None
            test_id = self.prospective_test(untested)
            if test_id is None:
                self.notes.append(
                    f"{', '.join(r.hypothesis_id for r in untested)}: no affordable experiment "
                    "it could fail"
                )
                self.stop(Outcome.STOPPED_INSUFFICIENT_VALIDATION)
                return None
            return _Action(test_id, Purpose.PROSPECTIVE_TEST, 0.0)
        chosen = self.select(live, classes)
        if chosen is None:
            self.stop(Outcome.STOPPED_INSUFFICIENT_VALIDATION, classes)
            return None
        experiment_id, utility = chosen
        purpose = (
            Purpose.CHAIN_CHECK
            if self.chain_priority and self.experiments[experiment_id].chain_check
            else Purpose.DISCRIMINATE
        )
        return _Action(experiment_id, purpose, utility)

    def run(self, action: _Action) -> None:
        experiment = self.experiments[action.experiment_id]
        if self.spent + experiment.cost > self.budget.total:
            raise BudgetExceeded(
                f"{experiment.experiment_id} costs {experiment.cost}; "
                f"{self.budget.total - self.spent} remain"
            )
        self.step += 1
        self.session += 1
        replicate = self.replicates.get(experiment.experiment_id, 0)
        self.replicates[experiment.experiment_id] = replicate + 1
        values = self.lab.measure(
            experiment.experiment_id, replicate=replicate, session=self.session
        )
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
                purpose=action.purpose,
                utility=action.utility,
                cost=experiment.cost,
                budget_after=self.budget.total - self.spent,
                observation_id=observation.observation_id,
            )
        )
        if action.purpose is Purpose.NOISE_TEST and action.target is not None:
            self.reproduction_test(action.target, observation)
        elif action.purpose is Purpose.DECISIVE_REPLICATION and action.target is not None:
            self.decisive_replication(action.target, observation)
        elif self.p.anomalies:
            self.detect_unexplained(observation)

    def stop(self, outcome: Outcome, classes: Sequence[tuple[str, ...]] = ()) -> None:
        if outcome is Outcome.STOPPED_INSUFFICIENT_VALIDATION and self.p.reframing:
            by_id = {r.hypothesis_id: r.hypothesis for r in self.live()}
            needed: list[str] = []
            subjects: list[str] = []
            for i, first in enumerate(classes):
                for second in classes[i + 1 :]:
                    for experiment_id, reason in self.oracle.would_separate(
                        by_id[first[0]], by_id[second[0]]
                    ):
                        needed.append(f"{experiment_id} ({reason})")
                        subjects.extend((first[0], second[0]))
            if needed:
                self._record(
                    ReframingKind.CHANGE_OBSERVABLE,
                    (),
                    len(classes),
                    "the affordable available experiments cannot separate what is live; "
                    f"declared but unavailable: {'; '.join(sorted(set(needed)))}",
                    sorted(set(subjects)),
                )
            self._record(
                ReframingKind.STOP_INSUFFICIENT,
                (),
                0,
                f"{len(classes)} distinguishable classes live and no affordable experiment "
                f"discriminates them ({self.budget.total - self.spent} of {self.budget.total} "
                "units left)",
                tuple(m for c in classes for m in c),
            )
        for record in self.live():
            self.records[record.hypothesis_id] = transition(
                record,
                self.step,
                DiscoveryState.STOPPED,
                f"live when the loop stopped: {outcome.value}",
                (),
            )
        self.outcome = outcome

    def conclude(self, members: tuple[str, ...]) -> None:
        cls = list(members)
        if self.p.closure:
            admitted = self.admitted()
            held = self.held_fingerprints()
            #: Parsimony: the class takes alternatives no more complex than its members; a more
            #: complex indistinguishable hypothesis (a member plus a small extra contribution) is
            #: recorded as not excluded, not as a rival explanation.
            complexity = max(len(self.records[m].hypothesis.components) for m in cls)
            for candidate in hypothesis_universe(self.catalog):
                if candidate.fingerprint in held:
                    continue
                twin = next(
                    (
                        m
                        for m in cls
                        if not self.oracle.distinguishable(candidate, self.records[m].hypothesis)
                    ),
                    None,
                )
                if twin is None:
                    continue
                if self.fit(candidate, admitted).p_value < self.p.alpha_refute:
                    continue
                if len(candidate.components) > complexity:
                    self.cannot_exclude.append(candidate.hypothesis_id)
                    continue
                self.records[candidate.hypothesis_id] = HypothesisRecord(
                    hypothesis=candidate,
                    registered_at=self.step,
                    origin=Origin.INDISTINGUISHABILITY_CLOSURE,
                    history=(
                        StateEvent(
                            self.step,
                            DiscoveryState.INDISTINGUISHABLE.value,
                            f"{NO_AVAILABLE_EXPERIMENT} and {twin}; consistent with the "
                            "admitted data -- reported in its class, never resolved by fiat",
                            (twin,),
                        ),
                    ),
                )
                self.order.append(candidate.hypothesis_id)
                held.add(candidate.fingerprint)
                cls.append(candidate.hypothesis_id)
        cls.sort()
        if len(cls) > 1 and self.p.reframing:
            needed = set()
            for i, first in enumerate(cls):
                for second in cls[i + 1 :]:
                    for experiment_id, reason in self.oracle.would_separate(
                        self.records[first].hypothesis, self.records[second].hypothesis
                    ):
                        needed.add(f"{experiment_id} ({reason})")
            self._record(
                ReframingKind.CHANGE_OBSERVABLE,
                (),
                len(cls),
                f"{NO_AVAILABLE_EXPERIMENT}: {', '.join(cls)}; "
                + (
                    f"declared but unavailable experiments that would: {'; '.join(sorted(needed))}"
                    if needed
                    else "no declared experiment would"
                ),
                cls,
            )
        self.claim = tuple(cls)
        if cls == [NULL_HYPOTHESIS.hypothesis_id]:
            self.outcome = Outcome.NO_EFFECT_BEYOND_NOISE
        elif len(cls) == 1:
            self.outcome = Outcome.SURVIVING_PENDING_WARRANT_GATE
        else:
            self.outcome = Outcome.INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE

    def result(self) -> DiscoveryResult:
        assert self.outcome is not None
        hypotheses = tuple(self.records[i] for i in self.order)
        anomalies = tuple(
            self.anomalies[a] for a in sorted(self.anomalies, key=lambda a: int(a.split(":")[1]))
        )
        support = {
            r.hypothesis_id: self.prospective_support(r) for r in hypotheses if r.alias_of is None
        }
        handover = (
            build_handover(
                outcome=self.outcome,
                claim=self.claim,
                records=hypotheses,
                anomalies=anomalies,
                support=support,
                oracle=self.oracle,
                catalog=self.catalog,
                reframings=tuple(self.reframings),
                cannot_exclude=tuple(self.cannot_exclude),
            )
            if self.outcome in CLAIM_OUTCOMES and self.outcome is not Outcome.NO_EFFECT_BEYOND_NOISE
            else None
        )
        return DiscoveryResult(
            arm=self.arm,
            protocol_digest=self.p.digest,
            catalog_ref=self.catalog.ref,
            budget=self.budget.total,
            spent=self.spent,
            outcome=self.outcome,
            claim=self.claim,
            hypotheses=hypotheses,
            observations=tuple(self.observations),
            anomalies=anomalies,
            reframings=tuple(self.reframings),
            steps=tuple(self.steps),
            handover=handover,
            replications=tuple(self.replications),
            notes=tuple(self.notes),
        )


def investigate(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
) -> DiscoveryResult:
    """Run one investigation to its end. Deterministic given the laboratory's seed."""
    run = _Investigation(
        arm=arm, catalog=catalog, oracle=oracle, protocol=protocol, budget=budget, lab=lab
    )
    experiment_id, values = lab.motivating()
    run.observations.append(
        Observation(
            observation_id="obs:0",
            experiment_id=experiment_id,
            replicate=-1,
            taken_at=0,
            values=values,
            motivating=True,
        )
    )
    run.register(NULL_HYPOTHESIS, Origin.INITIAL_CATALOG, "the noise model is always a rival")
    for mechanism in catalog.initial:
        run.register(make_hypothesis(mechanism), Origin.INITIAL_CATALOG, "initial working set")
    while run.outcome is None:
        run.evaluate()
        if run.p.anomalies:
            run.detect_sole_bases()
        run.update_anomalies()
        action = run.next_action()
        if action is None:
            break
        run.run(action)
    return run.result()


__all__ = [
    "BudgetExceeded",
    "Laboratory",
    "hypothesis_universe",
    "investigate",
    "prior_weight",
]
