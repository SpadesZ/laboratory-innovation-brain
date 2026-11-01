"""How a discovery result hands over to the Causal Warrant Gate -- and why it can do no more.

The gate (`docs/implementation/causal-warrant-gate-v1.md`, `-v1.1.md`; SQL `012o`/`012p`) is the
only path to CONFIRMED. It needs a hypothesis set of rivals, admitted certificates with typed
predictions bound to declared OutcomeSpaces, Runs and Attestations, relations, a DOMAIN or signed
REVIEW warrant per relation that moves a belief, and `ConfirmationRule.standing` over all of it. An
offline loop over toy forward models has none of those records and must not invent them, so the
handover is a typed packet, not a call:

    candidate_class        the surviving class (one member, or several no available experiment
                           separates) -- the gate's candidate set
    rivals                 every other registered hypothesis with its standing here, its refutation
                           basis, and the available experiment that best separates it from the
                           candidate -- the rivals I6 says must be excluded on WARRANTED evidence;
                           a refutation here is a chi-square test, not a warranted CONTRADICTS
    prospective_support    per member, the observations taken after its registration that it
                           passed -- the only ones that may ever count for it
    never_considered       declared classes this run never registered: the closed world (T9)
    open_anomalies         anything still unexplained
    would_separate         declared but unavailable experiments that would split the class
    requirements           what the gate must still establish; nothing here satisfies any of them

`draft_certificates` maps the packet onto the gate's hypothesis input: core §8.1 `Hypothesis`
certificates (statement, mechanism, falsifier, minimal test) for the candidate class and its rivals,
unadmitted. Typed `Prediction`s are not produced: they must bind to a DomainPack-declared
OutcomeSpace (VER-006), and the discovery observables have none -- inventing one here would be the
self-certification the gate exists to stop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from lab_brain.core.models.hypothesis import Hypothesis as CoreHypothesis
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.model import (
    AnomalyRecord,
    AnomalyState,
    DiscoveryState,
    GateHandover,
    GateRequirement,
    HypothesisRecord,
    Outcome,
    ReframingKind,
    ReframingRecord,
    RivalStanding,
    make_hypothesis,
)

PENDING = "PENDING_CAUSAL_WARRANT_GATE"

REQUIREMENTS: tuple[GateRequirement, ...] = (
    GateRequirement(
        "admit each candidate and rival certificate through the §8 admission gate; the loop "
        "registered hypotheses and admitted none",
        "lab_brain.core.belief.admit_hypothesis",
    ),
    GateRequirement(
        "bind typed Predictions to a DomainPack-declared OutcomeSpace version (VER-006); these "
        "forward models declare none",
        "lab_brain.core.models.prediction.bind",
    ),
    GateRequirement(
        "obtain new, prospective evidence as Runs and Attestations through the admission gate; "
        "offline synthetic observations are not evidence",
        "lab_brain.ingestion.admission_gate; lab_brain.verification.prospective (011s)",
    ),
    GateRequirement(
        "warrant every belief-moving SUPPORTS/CONTRADICTS by a code-reviewed DOMAIN declaration or "
        "a signed REVIEW grant; the loop's survival and refutations warrant nothing",
        "lab_brain.core.warrant.WarrantResolver; lab_brain.security.reviewer_identity",
    ),
    GateRequirement(
        "pass the confirmation rule: one warranted SUPPORTED class, every rival affirming its "
        "observation excluded on a warranted refutation, no foreign signature observed",
        "lab_brain.verification.loop.ConfirmationRule.standing; migration 012p",
    ),
)


def build_handover(
    *,
    outcome: Outcome,
    claim: tuple[str, ...],
    records: Sequence[HypothesisRecord],
    anomalies: Sequence[AnomalyRecord],
    support: Mapping[str, tuple[str, ...]],
    oracle: SeparationOracle,
    catalog: DiscoveryCatalog,
    reframings: Sequence[ReframingRecord],
    cannot_exclude: tuple[str, ...] = (),
) -> GateHandover:
    by_id = {r.hypothesis_id: r for r in records}
    members = [by_id[i] for i in claim]
    rivals = []
    for record in records:
        if record.hypothesis_id in claim or record.alias_of is not None:
            continue
        closest: tuple[str | None, float] | None = None
        for member in members:
            found = oracle.best_separating(record.hypothesis, member.hypothesis)
            if closest is None or found[1] < closest[1]:
                # The rival is only as separated as its closest candidate member.
                closest = found
        best = closest if closest is not None else (None, 0.0)
        refutation = next(
            (e.basis for e in reversed(record.history) if e.state == DiscoveryState.REFUTED), ()
        )
        rivals.append(
            RivalStanding(
                hypothesis_id=record.hypothesis_id,
                mechanism=record.hypothesis.mechanism,
                state=record.state.value,
                refutation_basis=refutation if record.ever_refuted else (),
                best_separating_experiment=best[0],
                separation=best[1],
            )
        )
    held = {r.hypothesis.fingerprint for r in records}
    never = tuple(
        sorted(m.class_id for m in catalog.mechanisms if make_hypothesis(m).fingerprint not in held)
    )
    open_anomalies = tuple(
        a.anomaly_id
        for a in anomalies
        if a.state in (AnomalyState.UNEXPLAINED, AnomalyState.ACCOMMODATED)
    )
    would: list[tuple[str, str]] = []
    for i, first in enumerate(members):
        for second in members[i + 1 :]:
            would.extend(oracle.would_separate(first.hypothesis, second.hypothesis))
    notes = [
        "survival here is a pre-registered chi-square test over toy forward models; it is not "
        "warranted support and confirms nothing",
    ]
    if any(r.kind is ReframingKind.CHANGE_OBSERVABLE for r in reframings):
        notes.append(
            "the candidate class needs a different observable to be split (see reframings)"
        )
    return GateHandover(
        status=PENDING,
        outcome=outcome,
        candidate_class=claim,
        candidate_mechanisms=tuple(m.hypothesis.mechanism for m in members),
        prospective_support=tuple((i, support.get(i, ())) for i in claim),
        rivals=tuple(rivals),
        never_considered=never,
        open_anomalies=open_anomalies,
        would_separate=tuple(sorted(set(would))),
        requirements=REQUIREMENTS,
        cannot_exclude=cannot_exclude,
        notes=tuple(notes),
    )


def draft_certificates(
    handover: GateHandover,
    records: Sequence[HypothesisRecord],
    *,
    project_id: str,
    episode_id: str,
) -> tuple[CoreHypothesis, ...]:
    """The candidate class and its rivals as unadmitted core §8.1 certificates.

    Each falsifier names the available experiment that best separates the hypothesis from its
    closest competitor; nothing here is admitted, predicted or warranted.
    """
    by_id = {r.hypothesis_id: r for r in records}
    rival_test = {r.hypothesis_id: r.best_separating_experiment for r in handover.rivals}
    certificates = []
    for hypothesis_id in (*handover.candidate_class, *(r.hypothesis_id for r in handover.rivals)):
        record = by_id[hypothesis_id]
        test = rival_test.get(hypothesis_id)
        if test is None:
            test = next(
                (
                    r.best_separating_experiment
                    for r in handover.rivals
                    if r.best_separating_experiment
                ),
                None,
            )
        falsifier = (
            f"an admitted run of {test} reports an entry outside this hypothesis's predicted band"
            if test
            else "no available experiment is declared that could refute it"
        )
        certificates.append(
            CoreHypothesis(
                hypothesis_id=f"{episode_id}/{hypothesis_id}",
                project_id=project_id,
                statement=record.hypothesis.statement,
                mechanism=record.hypothesis.mechanism,
                falsifier=falsifier,
                minimal_test_ref=test,
                created_in_episode=episode_id,
            )
        )
    return tuple(certificates)


__all__ = ["PENDING", "REQUIREMENTS", "build_handover", "draft_certificates"]
