"""B0, the single-hypothesis baseline: take the most likely answer, test it once, accept if it fits.

A deterministic stand-in for the "one confident answer" pattern -- it is NOT a language model and
makes no claim about how any model behaves. It reads the motivating observation the way an answer
conditioned on the report would: among the initial catalog's mechanisms consistent with that
observation, in order of declared prior (ties by class id), it takes the first, runs the cheapest
affordable experiment in which that mechanism predicts a clear effect (worst-case separation from
the noise model at least `risky_separation` -- the confirmation-seeking test), and accepts the
mechanism if its fit to everything it has measured passes the same pre-registered test the other
arms use. Otherwise it moves to the next mechanism. It considers no rival, records no anomaly and
never reframes. Its budget is the same as every other arm's; it usually stops early.
"""

from __future__ import annotations

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.forward import fit
from lab_brain.discovery.loop import Laboratory
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    Budget,
    DiscoveryResult,
    DiscoveryState,
    HypothesisRecord,
    Observation,
    Origin,
    Outcome,
    Purpose,
    StateEvent,
    StepRecord,
    make_hypothesis,
    transition,
)
from lab_brain.discovery.protocol import DiscoveryProtocol


def single_hypothesis_baseline(
    *,
    arm: str,
    catalog: DiscoveryCatalog,
    oracle: SeparationOracle,
    protocol: DiscoveryProtocol,
    budget: Budget,
    lab: Laboratory,
) -> DiscoveryResult:
    experiments = {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }
    experiment_id, values = lab.motivating()
    motivating = Observation("obs:0", experiment_id, -1, 0, values, motivating=True)
    observations: list[Observation] = [motivating]
    measured: list[Observation] = []
    records: list[HypothesisRecord] = []
    steps: list[StepRecord] = []
    step = spent = session = 0
    replicates: dict[str, int] = {}
    outcome = Outcome.STOPPED_INSUFFICIENT_VALIDATION
    claim: tuple[str, ...] = ()
    ordered = sorted(catalog.initial, key=lambda m: (-m.prior, m.class_id))
    candidates = [
        m
        for m in ordered
        if fit(make_hypothesis(m), [motivating], experiments).p_value >= protocol.alpha_refute
    ]
    for mechanism in candidates:
        hypothesis = make_hypothesis(mechanism)
        record = HypothesisRecord(
            hypothesis=hypothesis,
            registered_at=step,
            origin=Origin.INITIAL_CATALOG,
            history=(
                StateEvent(
                    step,
                    DiscoveryState.PROPOSED.value,
                    "most likely remaining mechanism consistent with the report",
                ),
            ),
        )
        if measured:
            prior_fit = fit(hypothesis, measured, experiments)
            if prior_fit.p_value < protocol.alpha_refute:
                records.append(
                    transition(
                        record,
                        step,
                        DiscoveryState.REFUTED,
                        f"already inconsistent with what was measured (p={prior_fit.p_value:.2e})",
                        tuple(o.observation_id for o in measured),
                    )
                )
                continue
        remaining = budget.total - spent
        tests = [
            (e.cost, i, e.experiment_id)
            for i, e in enumerate(oracle.available)
            if e.cost <= remaining
            and oracle.experiment_separation(hypothesis, NULL_HYPOTHESIS, e.experiment_id)
            >= protocol.risky_separation
        ]
        if not tests:
            records.append(
                transition(
                    record,
                    step,
                    DiscoveryState.STOPPED,
                    "no affordable experiment in which it predicts a clear effect",
                    (),
                )
            )
            break
        chosen = min(tests)[2]
        cost = experiments[chosen].cost
        step += 1
        session += 1
        replicate = replicates.get(chosen, 0)
        replicates[chosen] = replicate + 1
        observation = Observation(
            f"obs:{step}",
            chosen,
            replicate,
            step,
            lab.measure(chosen, replicate=replicate, session=session),
        )
        observations.append(observation)
        measured.append(observation)
        spent += cost
        steps.append(
            StepRecord(
                step,
                chosen,
                Purpose.SINGLE_HYPOTHESIS_TEST,
                0.0,
                cost,
                budget.total - spent,
                observation.observation_id,
            )
        )
        result = fit(hypothesis, measured, experiments)
        if result.p_value >= protocol.alpha_refute:
            records.append(
                transition(
                    record,
                    step,
                    DiscoveryState.SURVIVING,
                    f"its confirmation test fits (p={result.p_value:.2e}); accepted",
                    (observation.observation_id,),
                )
            )
            outcome = Outcome.SURVIVING_PENDING_WARRANT_GATE
            claim = (hypothesis.hypothesis_id,)
            break
        records.append(
            transition(
                record,
                step,
                DiscoveryState.REFUTED,
                f"its confirmation test does not fit (p={result.p_value:.2e})",
                (observation.observation_id,),
            )
        )
    return DiscoveryResult(
        arm=arm,
        protocol_digest=protocol.digest,
        catalog_ref=catalog.ref,
        budget=budget.total,
        spent=spent,
        outcome=outcome,
        claim=claim,
        hypotheses=tuple(records),
        observations=tuple(observations),
        anomalies=(),
        reframings=(),
        steps=tuple(steps),
        handover=None,
        notes=("single-hypothesis baseline: a deterministic stand-in, not a language model",),
    )


__all__ = ["single_hypothesis_baseline"]
