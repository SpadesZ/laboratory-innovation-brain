"""`safe_investigate_v11`: the v1.0 gate with a refit fixpoint and localized predictive checks.

v1.0 (`lab_brain.discovery_safety.gate`) is frozen by its evidence manifest and is not edited; this
module subclasses its gate and replaces exactly three things:

    adequacy   `test` adds the per-experiment checks (`localized_checks`) to v1.0's global test.
               Every caller of `test` -- the claim's members, the replicate that decides whether a
               failure was noise, the catalog-completeness check over every hypothesis the catalog
               expresses -- uses the same criterion
    probes     `probe_fixpoint` recomputes the claim's signal set after every admitted observation
               and always runs the cheapest affordable never-run SIGNAL experiment of the union
               before any null one; it stops when nothing affordable is left (or a failure is
               reproduced / cannot be replicated, as in v1.0)
    coverage   `assess` judges coverage against the UNION of every signal set computed (the final
               fit's included). A signal experiment that appeared only after a refit and could not
               be afforded leaves the claim ADEQUACY_UNVERIFIED, never endorsed

Everything else -- replication, completeness, the stage-1 proposal, pairwise requests, anomaly
records, the scored result -- is v1.0's code, called unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.forward import fit, predict
from lab_brain.discovery.loop import Laboratory, hypothesis_universe, investigate
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    AnomalyRecord,
    AnomalyState,
    Budget,
    DiscoveryResult,
    DiscoveryState,
    ExperimentSpec,
    Hypothesis,
    Observation,
    ReframingKind,
    ReframingRecord,
    transition,
)
from lab_brain.discovery.numerics import chi2_sf
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_safety.gate import (
    ABSTENTION_OUTCOME,
    _Gate,
    adequacy_test,
    discriminating_tests_passed,
    signal_experiments,
)
from lab_brain.discovery_safety.model import (
    AbstentionReason,
    AdequacyTest,
    ConfidenceLevel,
    ExperimentRequest,
    NewFamilyProposal,
    ProbePurpose,
    SafetyAssessment,
    SafetyDecision,
)
from lab_brain.discovery_safety.pairwise import distinct_forward_models
from lab_brain.discovery_safety.v11.model import (
    SAFETY_V11,
    AdequacyTestV11,
    LocalizedCheck,
    RefitCoverage,
    SafeRunV11,
    SafetyProtocolV11,
)


def localized_checks(
    hypothesis: Hypothesis,
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
    alpha: float,
) -> tuple[LocalizedCheck, ...]:
    """Per distinct experiment: chi-square of its standardised residuals under the GLOBAL fit, with
    Holm's step-down procedure over the family at level `alpha`. Order: first observation."""
    theta = fit(hypothesis, observations, experiments).theta
    groups: dict[str, list[Observation]] = {}
    for o in observations:
        groups.setdefault(o.experiment_id, []).append(o)
    raw: list[tuple[str, tuple[str, ...], float, int, float, str, float]] = []
    for experiment_id, members in groups.items():
        experiment = experiments[experiment_id]
        predicted = predict(hypothesis, theta, experiment)
        chi2 = 0.0
        k = 0
        worst_id, worst_z = members[0].observation_id, -1.0
        for o in members:
            for entry in experiment.entries:
                z = (o.value(entry.entry_id) - predicted[entry.entry_id]) / entry.sigma
                chi2 += z * z
                k += 1
                if abs(z) > worst_z:
                    worst_id, worst_z = o.observation_id, abs(z)
        raw.append(
            (
                experiment_id,
                tuple(o.observation_id for o in members),
                chi2,
                k,
                chi2_sf(chi2, k),
                worst_id,
                worst_z,
            )
        )
    m = len(raw)
    order = sorted(range(m), key=lambda i: (raw[i][4], raw[i][0]))
    level = {i: alpha / (m - rank) for rank, i in enumerate(order)}
    rejected: set[int] = set()
    for i in order:
        if raw[i][4] < level[i]:
            rejected.add(i)
        else:
            break
    return tuple(
        LocalizedCheck(
            experiment_id=experiment_id,
            observations=ids,
            chi2=chi2,
            k=k,
            p_value=p,
            level=level[i],
            rejected=i in rejected,
            worst_observation=worst_id,
            worst_z=worst_z,
        )
        for i, (experiment_id, ids, chi2, k, p, worst_id, worst_z) in enumerate(raw)
    )


def adequacy_test_v11(
    hypothesis: Hypothesis,
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
    safety: SafetyProtocolV11,
) -> AdequacyTestV11:
    """v1.0's global criterion AND (when enabled) no Holm rejection among the localized checks.
    On a localized failure alone, the worst observation is the most deviant one of the most
    significant rejected experiment (that is what a replicate must re-measure)."""
    base = adequacy_test(hypothesis, observations, experiments, safety)
    checks = (
        localized_checks(hypothesis, observations, experiments, safety.alpha_localized)
        if safety.localized_check and observations
        else ()
    )
    failed = [c for c in checks if c.rejected]
    adequate = base.adequate and not failed
    worst_observation, worst_z = base.worst_observation, base.worst_z
    if base.adequate and failed:
        first = min(failed, key=lambda c: (c.p_value, c.experiment_id))
        worst_observation, worst_z = first.worst_observation, first.worst_z
    return AdequacyTestV11(
        hypothesis_id=base.hypothesis_id,
        fingerprint=base.fingerprint,
        chi2=base.chi2,
        n=base.n,
        dof=base.dof,
        p_value=base.p_value,
        worst_observation=worst_observation,
        worst_z=worst_z,
        adequate=adequate,
        global_adequate=base.adequate,
        localized=checks,
        localized_failed=tuple(c.experiment_id for c in failed),
    )


@dataclass
class _GateV11(_Gate):
    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.safety, SafetyProtocolV11):
            raise TypeError("the v1.1 gate runs under a SafetyProtocolV11")
        self.v11: SafetyProtocolV11 = self.safety
        self.initial_signals: tuple[str, ...] = ()
        self.history: list[str] = []
        self.recomputations = 0
        #: While probing, a failure of the LOCALIZED checks alone is not resolved yet (see
        #: `defer_localized_replication`); the global test still stops probing as in v1.0.
        self.deferring = False

    # -- adequacy -------------------------------------------------------------------------------

    def test(self, h: Hypothesis, exclude: frozenset[str] = frozenset()) -> AdequacyTest:
        return adequacy_test_v11(h, self.admitted(exclude), self.experiments, self.v11)

    def failing(self, exclude: frozenset[str] = frozenset()) -> AdequacyTest | None:
        """v1.0's rule over the v1.1 tests; while `deferring`, a localized-only failure waits."""
        tests = [
            adequacy_test_v11(h, self.admitted(exclude), self.experiments, self.v11)
            for h in self.members
        ]
        failed = [t for t in tests if not (t.global_adequate if self.deferring else t.adequate)]
        return (
            min(failed, key=lambda t: (t.p_value, -t.worst_z, t.hypothesis_id)) if failed else None
        )

    def resolve(self, failure: AdequacyTest, signals: set[str]) -> str:
        """v1.0's replication, except that an experiment already holding
        `max_noise_exclusions_per_experiment` observations excluded as noise gets no further
        exclusion: a failure there again is a reproduction of its deviation."""
        original_id = failure.worst_observation
        if original_id is not None:
            experiment_id = next(
                o.experiment_id for o in self.observations if o.observation_id == original_id
            )
            excluded_here = sum(
                1
                for o in self.observations
                if o.experiment_id == experiment_id and o.observation_id in self.excluded
            )
            if excluded_here >= self.v11.max_noise_exclusions_per_experiment:
                self.notes.append(
                    f"safety v1.1: {original_id} fails again in {experiment_id}, which already had "
                    f"{excluded_here} observation(s) excluded as noise: reproduced"
                )
                return "reproduced"
        return super().resolve(failure, signals)

    # -- the refit fixpoint ---------------------------------------------------------------------

    def recompute_signals(self) -> tuple[str, ...]:
        """The claim's signal set at the fit to every admitted observation; added to the union."""
        current = signal_experiments(
            self.members, self.admitted(), self.experiments, self.available, self.safety
        )
        self.recomputations += 1
        for experiment_id in current:
            if experiment_id not in self.history:
                self.history.append(experiment_id)
        return current

    def signal_set(self) -> set[str]:
        return set(self.history) if self.v11.refit_fixpoint else set(self.initial_signals)

    def settle(self) -> bool | None:
        """Resolve failures until none is left. None: every one was noise (probing goes on);
        otherwise whether the failure was reproduced (probing stops, as in v1.0)."""
        while (failure := self.failing()) is not None:
            outcome = self.resolve(failure, self.signal_set())
            if self.v11.refit_fixpoint:
                self.recompute_signals()
            if outcome != "noise":
                return outcome == "reproduced"
        return None

    def probe_fixpoint(self) -> bool | None:
        """Probe until nothing affordable is left. Returns whether a failure was reproduced (None:
        nothing failed, or every failure was noise). With `refit_fixpoint` off, the order is
        v1.0's: the pre-probe signal experiments, cheapest first, then the null ones."""
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

        def key(e: ExperimentSpec) -> tuple[int, int]:
            return (e.cost, self.declared_order[e.experiment_id])

        while True:
            observed = {o.experiment_id for o in self.admitted()}
            signals = self.signal_set()
            unobserved = [e for e in self.available if e.experiment_id not in observed]
            queue = sorted((e for e in unobserved if e.experiment_id in signals), key=key)
            if self.safety.probe_null_experiments:
                queue += sorted((e for e in unobserved if e.experiment_id not in signals), key=key)
            chosen = next((e for e in queue if e.cost <= self.remaining()), None)
            if chosen is None:
                if not self.deferring:
                    return None
                # Nothing affordable is left to probe: now resolve a localized-only failure
                # (replicate it if the budget allows; otherwise it stays unreplicated).
                self.deferring = False
                reproduced = self.settle()
                if reproduced is not None:
                    return reproduced
                continue
            self.run(
                chosen.experiment_id,
                ProbePurpose.ADEQUACY_PROBE,
                chosen.experiment_id in signals,
                None,
            )
            if self.v11.refit_fixpoint:
                self.recompute_signals()
            reproduced = self.settle()
            if reproduced is not None:
                return reproduced

    def refit_record(self) -> RefitCoverage:
        final = self.recompute_signals()
        observed = {o.experiment_id for o in self.admitted()}
        # Reported against the whole union, whatever the decision is judged against (with
        # `refit_fixpoint` off the decision uses the initial set; the record still tells the truth).
        ordered = tuple(e.experiment_id for e in self.available if e.experiment_id in self.history)
        uncovered = tuple(e for e in ordered if e not in observed)
        return RefitCoverage(
            initial_signals=self.initial_signals,
            final_signals=final,
            signal_history=tuple(
                e.experiment_id for e in self.available if e.experiment_id in set(self.history)
            ),
            emerged_after_refit=tuple(
                e.experiment_id
                for e in self.available
                if e.experiment_id in set(self.history)
                and e.experiment_id not in set(self.initial_signals)
            ),
            recomputations=self.recomputations,
            uncovered=uncovered,
            stable=not uncovered,
        )

    # -- the decision (v1.0's, with coverage over the union) ------------------------------------

    def assess_v11(self) -> SafeRunV11:
        engine = self.engine
        claim_ids = tuple(engine.claim) if self.members else ()
        signals: tuple[str, ...] = ()
        reproduced: bool | None = None
        refit: RefitCoverage | None = None
        if self.members:
            reproduced = self.probe_fixpoint()
            refit = self.refit_record()
            judged = self.signal_set()
            signals = tuple(e.experiment_id for e in self.available if e.experiment_id in judged)
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
        if refit is not None and refit.emerged_after_refit:
            self.notes.append(
                "safety v1.1: signal predictions that emerged only after a refit: "
                + ", ".join(refit.emerged_after_refit)
                + ("" if refit.stable else f"; never run: {', '.join(refit.uncovered)}")
            )
        for t in member_tests:
            if isinstance(t, AdequacyTestV11) and t.global_adequate and t.localized_failed:
                self.notes.append(
                    f"safety v1.1: {t.hypothesis_id} passes the global test but fails the "
                    f"localized check on {', '.join(t.localized_failed)}"
                )
        proposal: NewFamilyProposal | None = None
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
        return SafeRunV11(
            result=result,
            engine=engine,
            assessment=assessment,
            refit=refit,
            member_tests=tuple(t for t in member_tests if isinstance(t, AdequacyTestV11)),
        )


def safe_investigate_v11(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
    safety: SafetyProtocolV11 = SAFETY_V11,
) -> SafeRunV11:
    """The frozen engine's investigation, then the v1.1 gate. Deterministic given the lab."""
    engine = investigate(
        arm=arm, catalog=catalog, oracle=oracle, protocol=protocol, budget=budget, lab=lab
    )
    return _GateV11(engine, catalog, oracle, protocol, safety, budget, lab).assess_v11()


def safe_runner_v11(safety: SafetyProtocolV11 = SAFETY_V11) -> Callable[..., DiscoveryResult]:
    """An `Arm` runner: the same keyword interface as `investigate`, returning the scored result."""

    def runner(**kwargs: object) -> DiscoveryResult:
        return safe_investigate_v11(safety=safety, **kwargs).result  # type: ignore[arg-type]

    return runner


__all__ = [
    "adequacy_test_v11",
    "localized_checks",
    "safe_investigate_v11",
    "safe_runner_v11",
]
