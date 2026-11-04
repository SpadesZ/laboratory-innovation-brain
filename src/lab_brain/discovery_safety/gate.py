"""`safe_investigate`: the frozen engine, then an adequacy gate before anything is endorsed.

THE ROOT CAUSE THIS ADDRESSES. The frozen engine (`lab_brain.discovery.loop`) claims a class as
soon as one distinguishable class is left and every member passed `min_prospective_tests` risky
tests (`next_action` -> `conclude`). Every experiment it selects is chosen to separate DECLARED
hypotheses from each other (`select`, `prospective_test`), and "passed" means "not refuted at
alpha = 1e-3". Nothing ever asks whether the survivor is adequate on the experiments it was never
run on. When the true family is absent, a surrogate that matches the truth on the two to four
experiments the engine happened to run survives and is claimed -- while the experiment that would
expose it (often one unit of cost away, with budget left over) is never run because no declared
rival is separated by it.

THE GATE, step by step (thresholds: `SafetyProtocol`, fixed before any evaluation world ran):

    1. probes      before endorsing, run the available experiments the claim has not been tested
                   on: first every experiment it PREDICTS A SIGNAL IN (cheapest first, declared
                   order on ties), then the ones it predicts nothing in, while the budget lasts.
                   A probe is a test the claim can fail whatever the rivals are -- it is not
                   chosen to separate declared hypotheses, which is exactly what the engine's
                   selection cannot do for an unnamed truth
    2. adequacy    each claimed member is refitted to every admitted observation (the engine's
                   and the probes'): adequate iff p >= alpha_adequacy AND no observation has an
                   entry beyond z_adequacy sigma. Relative to the declared noise model, not to the
                   rivals
    3. replicate   a failure is replicated once (the worst observation; within the allowance and
                   the budget). Inadequacy that survives without the original is REPRODUCED; a
                   replicate that fits attributes the original to noise and probing continues; no
                   affordable replicate leaves it UNREPLICATED (still not endorsed)
    4. completeness  on inadequacy, every hypothesis the catalog can express (the noise model,
                   each class, each family pair -- distinct forward models only) is held to the
                   same test. Some adequate: CLAIM_INADEQUATE. None: CATALOG_INCOMPLETE
    5. decide      endorse only an adequate claim whose signal experiments were all run
                   (`signal_coverage`); otherwise ABSTAIN with the reason, open anomaly records, a
                   reframed question, a stage-1 proposal (catalog incomplete only), and pairwise
                   discriminating-experiment requests

More budget can only add probes, so it can only add chances to expose a surrogate; it never adds a
way to endorse one. The engine's own result is kept untouched in `SafeRun.engine`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.forward import fit, predict, standardized_distance
from lab_brain.discovery.loop import Laboratory, hypothesis_universe, investigate
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    AnomalyKind,
    AnomalyRecord,
    AnomalyState,
    Budget,
    DiscoveryResult,
    DiscoveryState,
    ExperimentSpec,
    Hypothesis,
    Observation,
    Outcome,
    Purpose,
    ReframingKind,
    ReframingRecord,
    ReproductionResult,
    StateEvent,
    StepRecord,
    stable_digest,
    transition,
)
from lab_brain.discovery.numerics import chi2_sf
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.model import (
    PROPOSAL_STAGE,
    PROPOSAL_STATUS,
    SAFETY,
    AbstentionReason,
    AdequacyTest,
    ConfidenceLevel,
    ExperimentRequest,
    NewFamilyProposal,
    ProbePurpose,
    ProbeRecord,
    RequestPurpose,
    SafeRun,
    SafetyAssessment,
    SafetyDecision,
    SafetyProtocol,
    SignatureEntry,
)
from lab_brain.discovery_safety.pairwise import distinct_forward_models

#: How an abstention is reported in the engine's outcome vocabulary (none of them is a claim).
ABSTENTION_OUTCOME: Mapping[AbstentionReason, Outcome] = {
    AbstentionReason.ADEQUACY_UNVERIFIED: Outcome.STOPPED_INSUFFICIENT_VALIDATION,
    AbstentionReason.CLAIM_INADEQUATE: Outcome.STOPPED_UNEXPLAINED,
    AbstentionReason.CATALOG_INCOMPLETE: Outcome.STOPPED_UNEXPLAINED,
    AbstentionReason.CATALOG_INCOMPLETE_UNREPLICATED: Outcome.STOPPED_UNEXPLAINED,
}


def adequacy_test(
    hypothesis: Hypothesis,
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
    safety: SafetyProtocol,
) -> AdequacyTest:
    """The pre-declared adequacy criterion: a good fit relative to the noise model, everywhere."""
    f = fit(hypothesis, observations, experiments)
    worst_id, worst_z = None, 0.0
    for observation_id, z in f.max_abs_z:
        if z > worst_z:
            worst_id, worst_z = observation_id, z
    adequate = f.p_value >= safety.alpha_adequacy and worst_z <= safety.z_adequacy
    return AdequacyTest(
        hypothesis_id=hypothesis.hypothesis_id,
        fingerprint=hypothesis.fingerprint,
        chi2=f.chi2,
        n=f.n,
        dof=f.dof,
        p_value=f.p_value,
        worst_observation=worst_id,
        worst_z=worst_z,
        adequate=adequate,
    )


def signal_experiments(
    members: Sequence[Hypothesis],
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
    available: Sequence[ExperimentSpec],
    safety: SafetyProtocol,
) -> tuple[str, ...]:
    """Available experiments in which some member, at its fitted amplitudes, predicts an entry at
    least `z_signal` sigma from zero -- the predictions an endorsement must have checked."""
    out = []
    thetas = [fit(h, observations, experiments).theta for h in members]
    for experiment in available:
        for h, theta in zip(members, thetas, strict=True):
            predicted = predict(h, theta, experiment)
            if any(
                abs(predicted[e.entry_id]) / e.sigma >= safety.z_signal for e in experiment.entries
            ):
                out.append(experiment.experiment_id)
                break
    return tuple(out)


def discriminating_tests_passed(
    members: Sequence[Hypothesis],
    rivals: Sequence[Hypothesis],
    observations: Sequence[Observation],
    oracle: SeparationOracle,
    threshold: float,
) -> int:
    """DISTINCT experiments among `observations` on which every member could have been separated
    from the noise model or from a DISTINCT rival forward model by one run (`threshold`, worst
    case). A replicate of an experiment already counted, or a renamed duplicate rival, adds
    nothing."""
    models = [
        r
        for r in distinct_forward_models(rivals)
        if r.fingerprint not in {m.fingerprint for m in members}
    ]
    counted = set()
    for experiment_id in sorted({o.experiment_id for o in observations if not o.motivating}):
        if all(
            (
                not m.is_null
                and oracle.experiment_separation(m, NULL_HYPOTHESIS, experiment_id) >= threshold
            )
            or any(oracle.experiment_separation(m, r, experiment_id) >= threshold for r in models)
            for m in members
        ):
            counted.add(experiment_id)
    return len(counted)


@dataclass
class _Gate:
    engine: DiscoveryResult
    catalog: DiscoveryCatalog
    oracle: SeparationOracle
    protocol: DiscoveryProtocol
    safety: SafetyProtocol
    budget: Budget
    lab: Laboratory

    def __post_init__(self) -> None:
        self.experiments: dict[str, ExperimentSpec] = {
            e.experiment_id: e
            for e in (*self.catalog.experiments, *(u.experiment for u in self.catalog.unavailable))
        }
        self.available = self.oracle.available
        self.declared_order = {e.experiment_id: i for i, e in enumerate(self.available)}
        self.observations: list[Observation] = list(self.engine.observations)
        self.steps: list[StepRecord] = list(self.engine.steps)
        self.spent = self.engine.spent
        self.step = max((s.step for s in self.steps), default=0)
        self.excluded: set[str] = {
            a.observation_id
            for a in self.engine.anomalies
            if a.state is AnomalyState.ATTRIBUTED_TO_NOISE
        } | {
            t.original_observation_id
            for t in self.engine.replications
            if t.result is ReproductionResult.NOT_REPRODUCED_NOISE
        }
        self.replicates: dict[str, int] = {}
        for o in self.observations:
            if not o.motivating:
                self.replicates[o.experiment_id] = max(
                    self.replicates.get(o.experiment_id, 0), o.replicate + 1
                )
        self.probes: list[ProbeRecord] = []
        self.replications_used = 0
        self.notes: list[str] = []
        self.members: list[Hypothesis] = (
            [self.engine.record(i).hypothesis for i in self.engine.claim]
            if self.engine.outcome in CLAIM_OUTCOMES
            else []
        )

    # -- data ---------------------------------------------------------------------------------

    def admitted(self, exclude: frozenset[str] = frozenset()) -> list[Observation]:
        return [
            o
            for o in self.observations
            if not o.motivating and o.observation_id not in self.excluded | exclude
        ]

    def remaining(self) -> int:
        return self.budget.total - self.spent

    def test(self, h: Hypothesis, exclude: frozenset[str] = frozenset()) -> AdequacyTest:
        return adequacy_test(h, self.admitted(exclude), self.experiments, self.safety)

    def run(
        self, experiment_id: str, purpose: ProbePurpose, signal: bool, of: str | None
    ) -> Observation:
        experiment = self.experiments[experiment_id]
        if experiment.cost > self.remaining():
            raise RuntimeError(f"{experiment_id} is not affordable; the gate never overspends")
        self.step += 1
        replicate = self.replicates.get(experiment_id, 0)
        self.replicates[experiment_id] = replicate + 1
        values = self.lab.measure(experiment_id, replicate=replicate, session=self.step)
        observation = Observation(
            observation_id=f"obs:{self.step}",
            experiment_id=experiment_id,
            replicate=replicate,
            taken_at=self.step,
            values=values,
        )
        self.observations.append(observation)
        self.spent += experiment.cost
        self.steps.append(
            StepRecord(
                step=self.step,
                experiment_id=experiment_id,
                purpose=Purpose.PROSPECTIVE_TEST
                if purpose is ProbePurpose.ADEQUACY_PROBE
                else Purpose.NOISE_TEST,
                utility=0.0,
                cost=experiment.cost,
                budget_after=self.remaining(),
                observation_id=observation.observation_id,
            )
        )
        self.probes.append(
            ProbeRecord(
                observation_id=observation.observation_id,
                experiment_id=experiment_id,
                purpose=purpose,
                claim_signal=signal,
                max_abs_z_under_claim=self.worst_z(observation.observation_id),
                replicates=of,
            )
        )
        return observation

    def worst_z(self, observation_id: str) -> float:
        admitted = self.admitted()
        zs = [fit(h, admitted, self.experiments).z_of(observation_id) for h in self.members]
        return max(zs, default=0.0)

    def failing(self, exclude: frozenset[str] = frozenset()) -> AdequacyTest | None:
        """The worst-failing member's test, or None when every member is adequate."""
        failed = [t for t in (self.test(h, exclude) for h in self.members) if not t.adequate]
        return (
            min(failed, key=lambda t: (t.p_value, -t.worst_z, t.hypothesis_id)) if failed else None
        )

    # -- steps 1-3: probes and replication ------------------------------------------------------

    def resolve(self, failure: AdequacyTest, signals: set[str]) -> str:
        """Replicate the failure's worst observation: 'noise', 'reproduced' or 'unreplicated'."""
        original_id = failure.worst_observation
        if original_id is None:
            return "unreplicated"
        original = next(o for o in self.observations if o.observation_id == original_id)
        cost = self.experiments[original.experiment_id].cost
        if self.replications_used >= self.safety.max_probe_replications or cost > self.remaining():
            return "unreplicated"
        self.replications_used += 1
        self.run(
            original.experiment_id,
            ProbePurpose.PROBE_REPLICATION,
            original.experiment_id in signals,
            original_id,
        )
        if self.failing(frozenset({original_id})) is None:
            self.excluded.add(original_id)
            self.notes.append(
                f"safety: {original_id} attributed to noise -- its replicate fits the claim"
            )
            return "noise"
        return "reproduced"

    def probe(self, signals: tuple[str, ...]) -> bool | None:
        """Run the probes. Returns whether a failure was reproduced (None: nothing failed)."""
        signal_set = set(signals)
        failure = self.failing()
        if failure is not None:
            outcome = self.resolve(failure, signal_set)
            if outcome != "noise":
                return outcome == "reproduced"
        if not self.safety.probes:
            return None
        observed = {o.experiment_id for o in self.admitted()}
        unobserved = [e for e in self.available if e.experiment_id not in observed]

        def key(e: ExperimentSpec) -> tuple[int, int]:
            return (e.cost, self.declared_order[e.experiment_id])

        queue = sorted((e for e in unobserved if e.experiment_id in signal_set), key=key)
        if self.safety.probe_null_experiments:
            queue += sorted((e for e in unobserved if e.experiment_id not in signal_set), key=key)
        for experiment in queue:
            if experiment.cost > self.remaining():
                continue
            self.run(
                experiment.experiment_id,
                ProbePurpose.ADEQUACY_PROBE,
                experiment.experiment_id in signal_set,
                None,
            )
            while (failure := self.failing()) is not None:
                outcome = self.resolve(failure, signal_set)
                if outcome != "noise":
                    return outcome == "reproduced"
        return None

    # -- step 4-5: completeness, proposal, requests, decision -----------------------------------

    def universe_tests(self) -> list[AdequacyTest]:
        return [self.test(h) for h in distinct_forward_models(hypothesis_universe(self.catalog))]

    def proposal(self, universe: Sequence[AdequacyTest]) -> NewFamilyProposal:
        admitted = self.admitted()
        by_key: dict[tuple[str, str], list[float]] = {}
        for o in admitted:
            for entry in self.experiments[o.experiment_id].entries:
                by_key.setdefault((o.experiment_id, entry.entry_id), []).append(
                    o.value(entry.entry_id)
                )
        signature: list[SignatureEntry] = []
        null: list[tuple[str, str]] = []
        table: dict[tuple[str, str], float] = {}
        for (experiment_id, entry_id), values in sorted(by_key.items()):
            sigma = self.experiments[experiment_id].entry(entry_id).sigma
            m = math.fsum(values) / len(values)
            z = m / (sigma / math.sqrt(len(values)))
            if abs(z) >= self.safety.z_signal:
                signature.append(SignatureEntry(experiment_id, entry_id, m, len(values), z))
                table[(experiment_id, entry_id)] = m
            else:
                null.append((experiment_id, entry_id))
        chi2 = 0.0
        n = 0
        worst = 0.0
        for o in admitted:
            for entry in self.experiments[o.experiment_id].entries:
                r = (
                    o.value(entry.entry_id) - table.get((o.experiment_id, entry.entry_id), 0.0)
                ) / entry.sigma
                chi2 += r * r
                worst = max(worst, abs(r))
                n += 1
        p = chi2_sf(chi2, max(1, n - len(signature))) if n else 1.0
        observed = sorted({o.experiment_id for o in admitted})
        synthetic = [
            Observation(
                observation_id=f"proposal:{experiment_id}",
                experiment_id=experiment_id,
                replicate=0,
                taken_at=0,
                values=tuple(
                    (e.entry_id, table.get((experiment_id, e.entry_id), 0.0))
                    for e in self.experiments[experiment_id].entries
                ),
            )
            for experiment_id in observed
        ]
        closest: tuple[float, str] | None = None
        for h in distinct_forward_models(hypothesis_universe(self.catalog)):
            separation = math.sqrt(fit(h, synthetic, self.experiments).chi2)
            if closest is None or (separation, h.hypothesis_id) < closest:
                closest = (separation, h.hypothesis_id)
        unobserved = tuple(
            e.experiment_id for e in self.available if e.experiment_id not in set(observed)
        )
        proposal_id = (
            "proposal:"
            + stable_digest([[s.experiment_id, s.entry_id, s.mean] for s in signature]).split(":")[
                1
            ][:12]
        )
        described = "; ".join(
            f"{s.experiment_id}.{s.entry_id} {s.mean:+.3g} ({s.z:+.1f} SE, {s.runs} run(s))"
            for s in signature
        )
        statement = (
            "PROPOSAL (stage-1 exploratory idea, not a claim): an effect outside the declared "
            f"catalog, none of whose {len(universe)} distinct forward models is adequate to the "
            f"admitted data, with the tabulated signature [{described or 'none significant'}]; "
            f"no significant effect on {len(null)} other observed entries; nothing is predicted "
            f"for the {len(unobserved)} experiment(s) never run"
        )
        return NewFamilyProposal(
            proposal_id=proposal_id,
            stage=PROPOSAL_STAGE,
            status=PROPOSAL_STATUS,
            statement=statement,
            signature=tuple(signature),
            observed_null=tuple(null),
            unobserved_experiments=unobserved,
            fits_observed=p >= self.safety.alpha_adequacy and worst <= self.safety.z_adequacy,
            fit_p_value=p,
            closest_declared=None if closest is None else closest[1],
            closest_separation=0.0 if closest is None else closest[0],
            required_next=(
                "a prospective test on an experiment NOT used to derive the signature (one of the "
                "experiments never run, or a declared one first extended with a forward model for "
                "this family), and a forward model a person writes for it -- the table read off "
                "the residuals supports nothing by itself"
            ),
        )

    def _group(
        self,
        found: Sequence[tuple[str, tuple[str, str, float], int]],
        purpose: RequestPurpose,
        why: str,
    ) -> tuple[ExperimentRequest, ...]:
        by: dict[str, list[tuple[tuple[str, str, float], int]]] = {}
        for experiment_id, pair, needed in found:
            by.setdefault(experiment_id, []).append((pair, needed))
        available_ids = {e.experiment_id for e in self.available}
        return tuple(
            ExperimentRequest(
                experiment_id=experiment_id,
                available=experiment_id in available_ids,
                purpose=purpose,
                pairs=tuple(sorted(p for p, _ in items)),
                replicates_needed=max(n for _, n in items),
                rationale=why,
            )
            for experiment_id, items in sorted(by.items())
        )

    def _needed(self, separation: float) -> int:
        if separation <= 0:
            return 0
        return max(1, math.ceil((self.safety.discriminating_tau / separation) ** 2))

    def pairwise_requests(self, candidates: Sequence[Hypothesis]) -> tuple[ExperimentRequest, ...]:
        """Per PAIR of candidates, the cheapest declared experiment whose one run separates them by
        at least `discriminating_tau` (else the most separating one, with the replicates needed).
        Pairs are never chained: each request names exactly the pairs it separates."""
        all_ids = [e.experiment_id for e in self.available] + [
            u.experiment.experiment_id for u in self.catalog.unavailable
        ]
        found = []
        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                scored = [(self.oracle.experiment_separation(a, b, x), x) for x in all_ids]
                enough = [
                    (self.experiments[x].cost, -s, x)
                    for s, x in scored
                    if s >= self.safety.discriminating_tau
                ]
                if enough:
                    _cost, neg, x = min(enough)
                    found.append((x, (a.hypothesis_id, b.hypothesis_id, -neg), 1))
                else:
                    s, x = max(scored)
                    if s > 0:
                        found.append((x, (a.hypothesis_id, b.hypothesis_id, s), self._needed(s)))
        return self._group(
            found,
            RequestPurpose.DISCRIMINATE_CANDIDATES,
            "predicted outcomes of the pair differ by at least the threshold (worst case over "
            "amplitudes) after the stated number of runs",
        )

    def proposal_requests(
        self, proposal: NewFamilyProposal, declared: Sequence[Hypothesis]
    ) -> tuple[ExperimentRequest, ...]:
        """Per declared candidate, the observed experiment where the proposal's signature and the
        candidate's best fit differ most in one run: replicating it discriminates them."""
        table = {(s.experiment_id, s.entry_id): s.mean for s in proposal.signature}
        admitted = self.admitted()
        observed = sorted({o.experiment_id for o in admitted})
        found = []
        for h in declared:
            theta = fit(h, admitted, self.experiments).theta
            best: tuple[float, str] | None = None
            for experiment_id in observed:
                experiment = self.experiments[experiment_id]
                mine = {
                    e.entry_id: table.get((experiment_id, e.entry_id), 0.0)
                    for e in experiment.entries
                }
                d = standardized_distance(mine, predict(h, theta, experiment), experiment)
                if best is None or (d, experiment_id) > best:
                    best = (d, experiment_id)
            if best is not None and best[0] > 0:
                found.append(
                    (
                        best[1],
                        (proposal.proposal_id, h.hypothesis_id, best[0]),
                        self._needed(best[0]),
                    )
                )
        return self._group(
            found,
            RequestPurpose.DISCRIMINATE_PROPOSAL,
            "the stage-1 proposal and the declared candidate predict outcomes that differ by the "
            "stated separation in one run; a replicate tests the proposal on data not used to "
            "derive it",
        )

    def coverage_requests(
        self,
        members: Sequence[Hypothesis],
        uncovered: Sequence[str],
        why: str = "the claim predicts a signal here and was never tested here; until it is, it "
        "is not endorsed",
    ) -> tuple[ExperimentRequest, ...]:
        found = []
        for experiment_id in uncovered:
            for m in members:
                s = self.oracle.experiment_separation(m, NULL_HYPOTHESIS, experiment_id)
                if s <= 0:
                    continue
                found.append(
                    (
                        experiment_id,
                        (m.hypothesis_id, NULL_HYPOTHESIS.hypothesis_id, s),
                        self._needed(s),
                    )
                )
        return self._group(found, RequestPurpose.ADEQUACY_PROBE, why)

    def anomaly(
        self, observation_id: str, z: float, reason: str, at_detection: tuple[str, ...], k: int
    ) -> AnomalyRecord:
        return AnomalyRecord(
            anomaly_id=f"anm:{k}",
            kind=AnomalyKind.UNEXPLAINED_OBSERVATION,
            observation_id=observation_id,
            detected_at=self.step,
            hypotheses_at_detection=at_detection,
            max_abs_z=z,
            history=(StateEvent(self.step, AnomalyState.UNEXPLAINED.value, reason),),
        )

    def assess(self) -> SafeRun:
        engine = self.engine
        claim_ids = tuple(engine.claim) if self.members else ()
        signals: tuple[str, ...] = ()
        reproduced: bool | None = None
        if self.members:
            signals = signal_experiments(
                self.members, self.admitted(), self.experiments, self.available, self.safety
            )
            reproduced = self.probe(signals)
        member_tests = tuple(self.test(h) for h in self.members)
        admitted = self.admitted()
        observed = {o.experiment_id for o in admitted}
        covered = tuple(e for e in signals if e in observed)
        uncovered = tuple(e for e in signals if e not in observed)
        inadequate = any(not t.adequate for t in member_tests)
        universe: list[AdequacyTest] = []
        alternatives: list[AdequacyTest] = []
        if inadequate or not self.members:
            universe = self.universe_tests() if admitted else []
            member_prints = {h.fingerprint for h in self.members}
            alternatives = sorted(
                (t for t in universe if t.adequate and t.fingerprint not in member_prints),
                key=lambda t: (-t.p_value, t.hypothesis_id),
            )
        catalog_incomplete = bool(universe) and not any(t.adequate for t in universe)
        rivals = [r.hypothesis for r in engine.hypotheses if r.alias_of is None]
        passed = (
            discriminating_tests_passed(
                self.members, rivals, admitted, self.oracle, self.protocol.risky_separation
            )
            if self.members and not inadequate
            else 0
        )
        coverage_ok = (
            not signals or len(covered) / len(signals) >= self.safety.signal_coverage - 1e-12
        )
        # -- decision -------------------------------------------------------------------------
        reason: AbstentionReason | None
        if not self.members:
            reason = AbstentionReason.NO_ENGINE_CLAIM
        elif inadequate and self.safety.abstain_on_inadequacy:
            if alternatives:
                reason = AbstentionReason.CLAIM_INADEQUATE
            elif reproduced:
                reason = AbstentionReason.CATALOG_INCOMPLETE
            else:
                reason = AbstentionReason.CATALOG_INCOMPLETE_UNREPLICATED
        elif not inadequate and not coverage_ok and self.safety.require_coverage:
            reason = AbstentionReason.ADEQUACY_UNVERIFIED
        else:
            reason = None
        decision = (
            SafetyDecision.ABSTAIN
            if reason is not None
            else SafetyDecision.ENDORSE_PENDING_WARRANT_GATE
        )
        if reason is None:
            confidence = ConfidenceLevel.ADEQUATE
        elif reason is AbstentionReason.ADEQUACY_UNVERIFIED:
            confidence = ConfidenceLevel.PROVISIONAL
        else:
            confidence = ConfidenceLevel.NONE
        # -- what a person can act on ---------------------------------------------------------
        proposal = None
        requests: tuple[ExperimentRequest, ...] = ()
        question: str | None = None
        new_anomalies: list[AnomalyRecord] = []
        k = len(engine.anomalies)
        open_engine = [
            a
            for a in engine.anomalies
            if a.state in (AnomalyState.UNEXPLAINED, AnomalyState.ACCOMMODATED)
        ]
        if inadequate and decision is SafetyDecision.ABSTAIN:
            worst = min(
                (t for t in member_tests if not t.adequate),
                key=lambda t: (t.p_value, t.hypothesis_id),
            )
            flagged = {
                oid: z
                for oid, z in fit(
                    next(h for h in self.members if h.hypothesis_id == worst.hypothesis_id),
                    admitted,
                    self.experiments,
                ).max_abs_z
                if z > self.safety.z_adequacy
            }
            if not flagged and worst.worst_observation is not None:
                flagged = {worst.worst_observation: worst.worst_z}
            for oid in sorted(flagged, key=lambda o: int(o.split(":")[1])):
                k += 1
                new_anomalies.append(
                    self.anomaly(
                        oid,
                        flagged[oid],
                        f"safety gate: outside the noise model under the claim's refit "
                        f"({worst.hypothesis_id}: p={worst.p_value:.2e}, "
                        f"max |z|={flagged[oid]:.2f}); "
                        + (
                            "no hypothesis the catalog expresses is adequate"
                            if catalog_incomplete
                            else "unresolved"
                        ),
                        claim_ids,
                        k,
                    )
                )
        if catalog_incomplete:
            proposal = self.proposal(universe)
            ranked = sorted(universe, key=lambda t: (t.chi2, t.hypothesis_id))
            by_id = {
                h.hypothesis_id: h
                for h in distinct_forward_models(hypothesis_universe(self.catalog))
            }
            declared = [
                by_id[t.hypothesis_id] for t in ranked[: self.safety.max_request_candidates - 1]
            ]
            requests = self.proposal_requests(proposal, declared)
            question = (
                "Reframed: which mechanism OUTSIDE the declared catalog "
                f"('{self.catalog.question}') "
                f"produces the signature of {proposal.proposal_id}? None of the "
                f"{len(universe)} distinct forward models the catalog expresses (noise model, "
                "single classes, family pairs) is adequate to the admitted data."
            )
            if not self.members and not open_engine and not new_anomalies:
                best = ranked[0]
                if best.worst_observation is not None:
                    k += 1
                    new_anomalies.append(
                        self.anomaly(
                            best.worst_observation,
                            best.worst_z,
                            "safety gate: no hypothesis the catalog expresses is adequate",
                            (best.hypothesis_id,),
                            k,
                        )
                    )
        elif reason is AbstentionReason.CLAIM_INADEQUATE:
            by_id = {
                h.hypothesis_id: h
                for h in distinct_forward_models(hypothesis_universe(self.catalog))
            }
            candidates = [
                by_id[t.hypothesis_id] for t in alternatives[: self.safety.max_request_candidates]
            ]
            if len(candidates) >= 2:
                requests = self.pairwise_requests(candidates)
            else:
                alt_signals = signal_experiments(
                    candidates, admitted, self.experiments, self.available, self.safety
                )
                untested = [e for e in alt_signals if e not in observed]
                if not untested:
                    # Every experiment it predicts a signal in was run: its prospective tests are
                    # the never-run experiments where it predicts the most (worst case vs null).
                    by_signal: list[tuple[float, str]] = sorted(
                        (
                            -self.oracle.experiment_separation(h, NULL_HYPOTHESIS, x.experiment_id),
                            x.experiment_id,
                        )
                        for h in candidates
                        for x in self.available
                        if x.experiment_id not in observed
                    )
                    untested = []
                    for score, experiment_id in by_signal:
                        if score < 0 and experiment_id not in untested and len(untested) < 2:
                            untested.append(experiment_id)
                requests = self.coverage_requests(
                    candidates,
                    untested,
                    "a prospective test of the one still-adequate declared hypothesis, which was "
                    "fitted after the claim failed (accommodation, not support)",
                )
                if not requests:
                    self.notes.append(
                        "safety: no declared experiment can test the remaining candidate "
                        "prospectively against 'none of the above'"
                    )
            question = (
                f"Reframed: {', '.join(claim_ids)} fails the adequacy test; which of the "
                "still-adequate "
                f"declared hypotheses ({', '.join(t.hypothesis_id for t in alternatives[:4])}"
                f"{', ...' if len(alternatives) > 4 else ''}) explains the data?"
            )
        elif reason is AbstentionReason.ADEQUACY_UNVERIFIED:
            requests = self.coverage_requests(self.members, uncovered)
            question = (
                f"Reframed: does {', '.join(claim_ids)} also hold on {', '.join(uncovered)}, "
                "where it "
                "predicts a signal and was never tested?"
            )
        elif reason is AbstentionReason.NO_ENGINE_CLAIM and alternatives:
            self.notes.append(
                f"safety: the engine made no claim; {len(alternatives)} declared hypotheses remain "
                "adequate"
            )
        # -- the scored result ----------------------------------------------------------------
        records = list(engine.hypotheses)
        if decision is SafetyDecision.ABSTAIN and self.members:
            why = f"safety gate: not endorsed ({reason.value if reason else ''})"
            records = [
                transition(r, self.step, DiscoveryState.STOPPED, why, ())
                if r.hypothesis_id in claim_ids and r.state is not DiscoveryState.REFUTED
                else r
                for r in records
            ]
        reframings = list(engine.reframings)
        if question is not None:
            reframings.append(
                ReframingRecord(
                    reframing_id=f"rfr:{len(reframings) + 1}",
                    kind=ReframingKind.WIDEN_MECHANISM_SPACE
                    if catalog_incomplete
                    else ReframingKind.STOP_INSUFFICIENT,
                    step=self.step,
                    failed_hypotheses=tuple(
                        sorted(t.hypothesis_id for t in member_tests if not t.adequate)
                    ),
                    anomalies=tuple(a.anomaly_id for a in (*open_engine, *new_anomalies)),
                    added_hypotheses=(),
                    considered=len(universe),
                    rationale=question,
                    subjects=(proposal.proposal_id,) if proposal else tuple(sorted(claim_ids)),
                )
            )
        outcome = (
            engine.outcome
            if reason is None or reason is AbstentionReason.NO_ENGINE_CLAIM
            else ABSTENTION_OUTCOME[reason]
        )
        endorsed = decision is SafetyDecision.ENDORSE_PENDING_WARRANT_GATE
        summary = (
            f"safety {self.safety.version} ({self.safety.digest}): {decision.value}"
            + (f" / {reason.value}" if reason else "")
            + f"; probes {sum(1 for p in self.probes if p.purpose is ProbePurpose.ADEQUACY_PROBE)}"
            f", replications {self.replications_used}, spent on probes {self.spent - engine.spent}"
        )
        result = replace(
            engine,
            outcome=outcome,
            claim=engine.claim if endorsed else (),
            hypotheses=tuple(records),
            observations=tuple(self.observations),
            anomalies=(*engine.anomalies, *new_anomalies),
            reframings=tuple(reframings),
            steps=tuple(self.steps),
            spent=self.spent,
            handover=engine.handover if endorsed else None,
            notes=(*engine.notes, summary, *self.notes),
        )
        assessment = SafetyAssessment(
            protocol_digest=self.safety.digest,
            engine_outcome=engine.outcome,
            engine_claim=tuple(engine.claim),
            decision=decision,
            reason=reason,
            confidence=confidence,
            adequacy=member_tests,
            probes=tuple(self.probes),
            signal_experiments=signals,
            signal_covered=covered,
            catalog_incomplete=catalog_incomplete,
            inadequacy_reproduced=reproduced if inadequate else None,
            adequate_alternatives=tuple(t.hypothesis_id for t in alternatives),
            distinct_hypotheses_checked=len(universe)
            if universe
            else len(distinct_forward_models(self.members)),
            discriminating_tests_passed=passed,
            anomalies=tuple(a.anomaly_id for a in (*open_engine, *new_anomalies)),
            proposal=proposal,
            requests=requests,
            reframed_question=question,
            spent_by_engine=engine.spent,
            spent_on_probes=self.spent - engine.spent,
            excluded_as_noise=tuple(sorted(self.excluded, key=lambda o: int(o.split(":")[1]))),
            notes=tuple(self.notes),
        )
        return SafeRun(result=result, engine=engine, assessment=assessment)


def safe_investigate(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
    safety: SafetyProtocol = SAFETY,
) -> SafeRun:
    """The frozen engine's investigation, then the adequacy gate. Deterministic given the lab."""
    engine = investigate(
        arm=arm, catalog=catalog, oracle=oracle, protocol=protocol, budget=budget, lab=lab
    )
    return _Gate(engine, catalog, oracle, protocol, safety, budget, lab).assess()


def safe_runner(safety: SafetyProtocol = SAFETY) -> Callable[..., DiscoveryResult]:
    """An `Arm` runner: the same keyword interface as `investigate`, returning the scored result."""

    def runner(**kwargs: object) -> DiscoveryResult:
        return safe_investigate(safety=safety, **kwargs).result  # type: ignore[arg-type]

    return runner


__all__ = [
    "ABSTENTION_OUTCOME",
    "adequacy_test",
    "discriminating_tests_passed",
    "safe_investigate",
    "safe_runner",
    "signal_experiments",
]
