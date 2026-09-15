"""Creating a belief revision, and replaying them back (EPI-003, EPI-005, §6.18, §8.2.1).

TWO FUNCTIONS, AND THE FIRST ONE IS A GATE.

:func:`record_transition` is the only way to obtain a legitimate :class:`BeliefRevisionEvent`. The
model can be constructed directly -- it is a Pydantic model and nothing can stop that -- so the
gate is not a barrier around the constructor. It is the thing that checks the event against *the
decision that authorised it*, and it is what the event store's callers are required to go through.
AGT-016 and EPI-005 both say the same thing from different angles:

    LLM output alone cannot cause a scientific status transition.
    No LLM may directly assign a scientific transition.

An LLM may produce a RelationJudgment and may write the rationale. What it may not do is decide.
So every refusal below is a way an event could claim an authorisation it does not have:

    non-ALLOW decision      the commonest bypass: run `evaluate`, ignore the answer, write the
                            event anyway. NEED_HUMAN_REVIEW is the dangerous one, because it looks
                            like progress
    decision/policy mismatch  an ALLOW borrowed from a different policy, or from a different
                            version of the same one
    decision/transition mismatch  an ALLOW for ACTIVE -> SUPPORTED reused to justify
                            ACTIVE -> CONTRADICTED
    invalid predecessor     the hypothesis moved since the decision was computed, so the
                            `from_state` the policy evaluated is no longer the state it would
                            transition from
    cross-project reference  evidence from another project justifying this project's belief. The
                            reason `v3.3-a11` added `project_id`: before it, this was not a
                            question the record could even express

:func:`replay` is the other half of EPI-003 -- and §6.18's contamination rollback is the reason it
exists, not a feature on top of it:

    發現某 extractor_version 有系統性錯誤
      -> quarantine 該版本產生的所有 Attestation
      -> replay BeliefRevisionEvent, 略過被隔離的 triggering attestation
      -> 得到可驗證的新 EpistemicStateProjection
      -> 不得靠手改 current status

WHAT THIS REDUCER IS NOT. It produces :class:`BeliefProjection`, deliberately **not** §17.13's
``EpistemicStateProjection``: there is no ``belief_level`` and no ``unresolved_conflicts``, because
those need `EPI-004` and `EPI-006`. Naming it differently is the point -- a type called
``EpistemicStateProjection`` with two of its fields missing would be read as finished.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import (
    BeliefRevisionEvent,
    BeliefState,
    BeliefTargetType,
)
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    TransitionDecision,
    TransitionOutcome,
    TransitionPolicy,
)


class BeliefTransitionRefused(RuntimeError):
    """An event was asked for that no policy decision authorises.

    Raised rather than returned. A refusal here is not a governance outcome a planner should route
    around -- ``evaluate`` already produced the governance outcome, and this means the caller is
    trying to write an event that disagrees with it.
    """


class SkipReason(StrEnum):
    """Why a recorded event did not contribute to a replayed projection."""

    #: §6.18: the event's triggering evidence was quarantined.
    QUARANTINED_TRIGGER = "QUARANTINED_TRIGGER"
    #: A predecessor was skipped, so this event's `from_state` no longer holds.
    PREDECESSOR_MISSING = "PREDECESSOR_MISSING"


@dataclass(frozen=True)
class BeliefProjection:
    """The minimal replay result: what the events say the state is now.

    ``skipped`` is carried rather than discarded, and it is the interesting half. After a
    contamination rollback, "the state is ACTIVE" is much less useful than "the state is ACTIVE
    because these four events were dropped" -- the second is reviewable, the first is an assertion.
    """

    target_id: str
    current_state: BeliefState | None
    last_event_id: str | None
    applied: tuple[str, ...] = ()
    skipped: tuple[tuple[str, SkipReason], ...] = ()

    @property
    def is_empty(self) -> bool:
        """No event applied. Distinct from a state of DRAFT, which an event had to produce."""
        return self.current_state is None


def replay(
    target_id: str,
    events: Sequence[BeliefRevisionEvent],
    quarantined_attestation_ids: Iterable[str] = (),
) -> BeliefProjection:
    """Fold a target's events into its current state, skipping quarantined evidence (§6.18).

    Deterministic by construction: events are ordered by ``(occurred_at, event_id)`` -- a total
    order, so two events recorded in the same microsecond still replay identically on every run --
    and the quarantine set is only ever tested for membership, never iterated.

    SKIPPING IS FAIL-CLOSED, AND THE CHOICE IS ARGUABLE ENOUGH TO STATE. An event whose triggers
    are *partly* quarantined is skipped, not kept. The policy decision that authorised it was
    computed over the whole trigger set, and this reducer cannot know it would still have been ALLOW
    over a subset -- re-deciding would need the policy inputs, which the event does not carry.
    Keeping the event would preserve a belief whose authorisation may no longer hold, which is
    exactly the contamination §6.18 is rolling back. True re-evaluation is a later refinement.

    A SKIP CASCADES. Once an event is dropped, a later event whose ``from_state`` no longer matches
    the running state is dropped too: its precondition was the state the dropped event produced. Not
    cascading would apply a transition from a state the replay never reached.
    """
    quarantined = frozenset(quarantined_attestation_ids)
    ordered = sorted(
        (event for event in events if event.target_id == target_id),
        key=lambda event: (event.occurred_at, event.event_id),
    )

    state: BeliefState | None = None
    last: str | None = None
    applied: list[str] = []
    skipped: list[tuple[str, SkipReason]] = []

    for event in ordered:
        if quarantined and any(ref in quarantined for ref in event.triggering_attestation_ids):
            skipped.append((event.event_id, SkipReason.QUARANTINED_TRIGGER))
            continue
        if event.from_state is not state:
            skipped.append((event.event_id, SkipReason.PREDECESSOR_MISSING))
            continue
        state = event.to_state
        last = event.event_id
        applied.append(event.event_id)

    return BeliefProjection(
        target_id=target_id,
        current_state=state,
        last_event_id=last,
        applied=tuple(applied),
        skipped=tuple(skipped),
    )


def record_transition(
    *,
    event_id: str,
    decision: TransitionDecision,
    policy: TransitionPolicy,
    hypothesis: HypothesisView,
    candidate_to_state: BeliefState,
    prior: BeliefProjection,
    occurred_at: dt.datetime,
    trace_id: str,
    triggering_attestations: Sequence[Attestation] = (),
    triggering_relations: Sequence[RelationJudgment] = (),
    actor_id: str | None = None,
    inference_provenance_id: str | None = None,
    rationale_artifact_or_record_ref: str | None = None,
) -> BeliefRevisionEvent:
    """Build the event a policy ALLOW authorises, or refuse to build one at all.

    Keyword-only throughout. Eleven positional arguments of which several are strings is how a
    ``trace_id`` ends up in the ``actor_id`` slot, and this is the function whose whole job is to
    make an event trustworthy.

    ``prior`` is the replayed projection, passed in rather than loaded: the check it enables --
    that the hypothesis has not moved since the decision was computed -- is meaningless against a
    projection this function derived itself from the same stale view.
    """
    if decision.outcome is not TransitionOutcome.ALLOW:
        raise BeliefTransitionRefused(
            f"decision for {hypothesis.hypothesis_id} is "
            f"{decision.outcome.value} ({decision.reason_code.value}), so no belief revision "
            "event may be created. Running `evaluate` and then writing the event regardless is "
            "the bypass EPI-005 and AGT-016 exist to forbid"
        )

    if (decision.policy_id, decision.policy_version) != (policy.policy_id, policy.version):
        raise BeliefTransitionRefused(
            f"the decision was made by {decision.policy_id}@{decision.policy_version} but the "
            f"event would cite {policy.policy_id}@{policy.version}; an ALLOW does not carry over "
            "to another policy or another version of the same one"
        )

    if (
        policy.from_state is not hypothesis.current_state
        or policy.candidate_to_state is not candidate_to_state
    ):
        raise BeliefTransitionRefused(
            f"the decision authorises {policy.from_state.value} -> "
            f"{policy.candidate_to_state.value}, but the event would record "
            f"{hypothesis.current_state.value} -> {candidate_to_state.value}"
        )

    if prior.current_state is not hypothesis.current_state:
        raise BeliefTransitionRefused(
            f"{hypothesis.hypothesis_id} is at "
            f"{'no recorded state' if prior.current_state is None else prior.current_state.value}"
            f" according to its event history, but the decision was computed against "
            f"{'no state' if hypothesis.current_state is None else hypothesis.current_state.value}"
            ". The hypothesis moved after the decision, so the state the policy evaluated is not "
            "the state this event would transition from"
        )

    cross_project = sorted(
        {
            f"{kind}:{record.project_id}"
            for kind, records in (
                ("attestation", triggering_attestations),
                ("relation", triggering_relations),
            )
            for record in records
            if record.project_id != hypothesis.project_id
        }
    )
    if cross_project:
        raise BeliefTransitionRefused(
            f"the event would cite evidence from outside {hypothesis.project_id}: "
            f"{', '.join(cross_project)}. Evidence from another project cannot justify this "
            "project's belief, and before `v3.3-a11` this was not a question the record could "
            "even express"
        )

    return BeliefRevisionEvent(
        event_id=event_id,
        project_id=hypothesis.project_id,
        target_type=BeliefTargetType.HYPOTHESIS,
        target_id=hypothesis.hypothesis_id,
        from_state=hypothesis.current_state,
        to_state=candidate_to_state,
        triggering_attestation_ids=tuple(
            sorted({record.attestation_id for record in triggering_attestations})
        ),
        triggering_relation_ids=tuple(
            sorted({record.relation_id for record in triggering_relations})
        ),
        policy_id=policy.policy_id,
        policy_version=policy.version,
        actor_id=actor_id,
        inference_provenance_id=inference_provenance_id,
        rationale_artifact_or_record_ref=rationale_artifact_or_record_ref,
        occurred_at=occurred_at,
        trace_id=trace_id,
    )


def quarantined_by_extractor_version(
    attestations: Iterable[Attestation], extractor_versions: Mapping[str, str] | None = None
) -> frozenset[str]:
    """Attestation ids produced by a quarantined extractor version (§6.18).

    ``extractor_versions`` maps ``extractor_id -> version``; an attestation is quarantined when its
    extractor and version both match an entry. Matching on the pair rather than the version alone
    matters: "1.0.0" is not a global identifier, and quarantining every extractor that happens to
    share a version string would discard evidence that was never contaminated.
    """
    if not extractor_versions:
        return frozenset()
    return frozenset(
        attestation.attestation_id
        for attestation in attestations
        if extractor_versions.get(attestation.extraction_provenance.extractor_id)
        == attestation.extractor_version
    )


__all__ = [
    "BeliefProjection",
    "BeliefTransitionRefused",
    "SkipReason",
    "quarantined_by_extractor_version",
    "record_transition",
    "replay",
]
