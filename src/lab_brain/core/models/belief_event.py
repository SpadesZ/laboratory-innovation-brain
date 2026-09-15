"""Belief revision as an append-only event (EPI-003, §6.18, §17.13).

WHY THE EVENT IS THE TRUTH AND THE STATE IS NOT.

§6.18 describes the flow this whole design exists for. An extractor version turns out to be
systematically wrong; every Attestation it produced is quarantined; the belief events are replayed
**skipping the quarantined triggers**; and the result is a new, checkable EpistemicState. The last
line of that passage is the one that shapes the schema:

    不得靠手改 current status

If the current status were the stored truth, that rollback would be a hand edit and nobody could
tell afterwards which beliefs had been derived and which had been asserted. So the events are the
record, the state is a projection of them, and a manual correction is itself an event (AGT-009).

WHAT THAT DEMANDS OF AN EVENT, and what each validator below is protecting:

    it changed something          an ACTIVE -> ACTIVE "revision" replays as a no-op, so a history
                                  can be padded with events that mean nothing, and a projection's
                                  `last_event_id` stops identifying what produced the state
    it cites its triggers         quarantine replay works by dropping events whose triggering
                                  attestations were quarantined. An event citing no trigger is
                                  unreachable by that mechanism -- it survives every rollback,
                                  which makes the rollback quietly incomplete
    it names its policy           `(policy_id, policy_version)`, per `v3.3-a11`. Versions are
                                  per-policy, so a version alone cannot select what to re-run
    it names its project          also `v3.3-a11`. Without it a replay is installation-wide and
                                  "this event cites another project's evidence" is not sayable

NOT AN ENTITY YET: the target. §8.2's lifecycle belongs to `Hypothesis`, which is `EPI-001` in M3,
so `target_id` has no foreign key to resolve against. Recorded as a risk rather than faked with a
column that looks checked.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from lab_brain.core.models.base import CoreModel


class BeliefState(StrEnum):
    """§8.2's hypothesis lifecycle, exactly.

    There is deliberately no ``REJECTED``. §8.2.1's prose mentions "SUPPORTED/REJECTED" but §8.2's
    diagram -- the normative one -- has ``CONTRADICTED`` as the negative terminal. Read as
    shorthand; see SPEC-ISSUE-010 for the ruling, so the next reader need not re-derive it.
    """

    DRAFT = "DRAFT"
    ADMITTED = "ADMITTED"
    ACTIVE = "ACTIVE"
    SUPPORTED = "SUPPORTED"
    CHALLENGED = "CHALLENGED"
    CONTRADICTED = "CONTRADICTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    EVOLVED = "EVOLVED"
    SUPERSEDED = "SUPERSEDED"


#: States §8.2 draws as exits from the lifecycle rather than positions inside it. A transition
#: *out* of one would mean a superseded hypothesis came back, and the replay would produce a state
#: the lifecycle does not contain.
BELIEF_TERMINAL_STATES: frozenset[BeliefState] = frozenset(
    {BeliefState.EVOLVED, BeliefState.SUPERSEDED}
)


class BeliefTargetType(StrEnum):
    """What kind of thing a revision is about.

    One member, because §8.2 defines one lifecycle. A Claim's identity status is
    ``ClaimIdentityStatus`` and is governed by the merge path (P22), not by ``TransitionPolicy``;
    giving it a transition vocabulary here would be building part of EPI-001 from an M0b slice.
    The field exists because §17.13 declares it and the enum is the honest current extent.
    """

    HYPOTHESIS = "HYPOTHESIS"


class BeliefRevisionEvent(CoreModel):
    """One recorded belief revision (§17.13, as amended by `v3.3-a11`).

    Append-only is enforced in three places and needs all three: this model is frozen, the table
    rejects UPDATE and DELETE by trigger, and the creation path (Phase C) refuses an event that no
    policy decision authorised. Any one of them alone leaves a way to write history.
    """

    event_id: str
    project_id: str
    target_type: BeliefTargetType
    target_id: str

    #: Optional per §17.13: a target's first event has no predecessor to name.
    from_state: BeliefState | None = None
    to_state: BeliefState

    triggering_attestation_ids: tuple[str, ...] = ()
    triggering_relation_ids: tuple[str, ...] = ()

    #: `(policy_id, policy_version)` identifies the exact §8.2.1 policy row that authorised this.
    policy_id: str
    policy_version: str

    #: Set when a human is the author of the revision -- §6.18's manual correction, which is an
    #: event like any other rather than an edit to the projection.
    actor_id: str | None = None
    inference_provenance_id: str | None = None
    rationale_artifact_or_record_ref: str | None = None

    occurred_at: dt.datetime
    trace_id: str

    @model_validator(mode="after")
    def _check_transition(self) -> Self:
        if self.from_state is not None:
            if self.from_state == self.to_state:
                raise ValueError(
                    f"event {self.event_id} does not change the state ({self.to_state.value} -> "
                    f"{self.to_state.value}); a revision that revises nothing replays as a no-op "
                    "and lets a history be padded with events that mean nothing"
                )
            if self.from_state in BELIEF_TERMINAL_STATES:
                raise ValueError(
                    f"event {self.event_id} transitions out of {self.from_state.value}, which "
                    "§8.2 draws as terminal; a superseded hypothesis does not come back, and the "
                    "replay would produce a state the lifecycle does not contain"
                )

        if not self.triggering_attestation_ids and not self.triggering_relation_ids:
            raise ValueError(
                f"event {self.event_id} cites no triggering attestation or relation. §6.18's "
                "contamination rollback replays by skipping events whose triggers were "
                "quarantined, so an event with no triggers survives every rollback and makes it "
                "quietly incomplete"
            )
        for label, refs in (
            ("attestation", self.triggering_attestation_ids),
            ("relation", self.triggering_relation_ids),
        ):
            if len(set(refs)) != len(refs):
                raise ValueError(
                    f"event {self.event_id} lists a triggering {label} twice, which double-counts "
                    "the evidence that authorised the revision"
                )
        return self

    @property
    def triggering_refs(self) -> tuple[str, ...]:
        """Every trigger, attestations first. Convenience for quarantine matching (§6.18)."""
        return self.triggering_attestation_ids + self.triggering_relation_ids

    @property
    def is_initial(self) -> bool:
        """True when this is a target's first recorded revision."""
        return self.from_state is None


__all__ = [
    "BELIEF_TERMINAL_STATES",
    "BeliefRevisionEvent",
    "BeliefState",
    "BeliefTargetType",
]
