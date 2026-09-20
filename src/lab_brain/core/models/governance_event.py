"""§17.19.1's `GovernanceEvent` — a state change that is governance, not science (`v3.3-a15`).

    §17.19.1  BeliefRevisionEvent (17.13) = a scientific epistemic-state transition.
              GovernanceEvent            = a governance/operational state change that does NOT
                                           itself alter scientific belief.

              A GovernanceEvent MUST NOT be accepted as BeliefRevisionEvent evidence, MUST NOT
              appear in a belief replay, and MUST NOT mutate EpistemicStateProjection.
              A scheduler or maintenance process MUST NOT author a BeliefRevisionEvent.

WHY THIS TYPE EXISTS, AND IT IS WORTH THE PARAGRAPH BECAUSE THE ALTERNATIVE LOOKED EASIER.
SPEC-ISSUE-012 asked what event an automatically expired `ReviewItem` may cite. `v3.3-a14` routes
every conflict closure through the resolution's event, and `011c` made that a
`belief_revision_events` reference -- but §17.13 gives a `BeliefRevisionEvent` one meaning, and an
unanswered timeout is not a belief transition. Every way of forcing one was illegal or dishonest: a
no-op transition policy is unrepresentable (`005b`), a real `ACTIVE -> INCONCLUSIVE` is circular
while the conflict blocks and is a scheduler declaring a scientific conclusion when it does not,
and the M0b fixture had been inventing a hypothesis to hang a genesis event on.

So the record of "a deadline passed" is its own kind of fact.

THE VOCABULARY IS ONE VALUE, DELIBERATELY. `REVIEW_EXPIRY` and nothing else. A general-purpose
audit event would become a second way to close any Conflict without moving a belief -- the hole
this amendment exists to avoid rather than open. Adding a kind is a spec amendment, which is the
cost that keeps it honest.

TWO ACTORS, ANSWERING DIFFERENT QUESTIONS. `declared_by_actor_id` is who decided that items of this
stakes lapse after this long; `actor_id` is who or what executed this particular sweep. §14.4 gives
the minimal actor model human / service account / agent role, so an automated executor is
expressible -- and recording it in the same slot as the author would let a service account look
like the source of a governance decision it only carried out.

THE EVENT ALONE PROVES NOTHING (`v3.3-a16`). Nothing on this object says which review it may close;
the fields say which review it *describes*. A genuine `REVIEW_EXPIRY` for one review is therefore
presentable as closure proof for another in the same project, and the model cannot see it because
the model only ever holds one row. That binding -- subject, conflict, exact policy version, policy
declarer and executor all agreeing with the chain being closed -- is enforced at the commit
boundary by `011g`, which is the only writer-independent place it can live. What the model does
hold is the one fact that is local to this row: a `REVIEW_EXPIRY` names the authority it executed.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from lab_brain.core.models.base import CoreModel


class GovernanceEventType(StrEnum):
    """§17.19.1's closed vocabulary. One member -- see the module docstring."""

    REVIEW_EXPIRY = "REVIEW_EXPIRY"


class GovernanceSubjectType(StrEnum):
    """What a governance event is *about*. One member, matching the one event type."""

    REVIEW_ITEM = "REVIEW_ITEM"


class ResolutionEventKind(StrEnum):
    """`v3.3-a15`: which kind of event a closure references.

    The pair `(resolution_event_kind, resolution_event_id)` replaces the bare event id that
    `011c` stored. `GOVERNANCE` is permitted for exactly one combination -- an `EXPIRED`
    `ReviewResolution` against a `REVIEW_EXPIRY` `GovernanceEvent` -- and every other closure is
    `BELIEF_REVISION`.
    """

    BELIEF_REVISION = "BELIEF_REVISION"
    GOVERNANCE = "GOVERNANCE"


class GovernanceEvent(CoreModel):
    """One governance or operational state change, append-only and project-scoped."""

    event_id: str
    project_id: str
    event_type: GovernanceEventType
    subject_type: GovernanceSubjectType
    #: The `review_id`, for a `REVIEW_ITEM` subject.
    subject_id: str
    #: The Conflict this expiry closed, when there was one. Nullable because a review that gates
    #: nothing can still expire, and naming a conflict it did not close would be a lie.
    related_conflict_id: str | None = None

    #: The standing policy that authorised this, **and which version of it**. Not the currently
    #: active one: an expiry re-interpreted under a policy the reviewer never saw is not the
    #: deadline they were given (`v3.3-a15`).
    policy_id: str
    policy_version: str
    #: Who declared that policy. Carried from the policy, never from the executor.
    #:
    #: `v3.3-a16` made it **optional-in-shape and required-in-substance for REVIEW_EXPIRY**, the
    #: same arrangement `ReviewResolution.belief_revision_event_id` carries. `v3.3-a15` made
    #: `ReviewQueuePolicy.declared_by_actor_id` NOT NULL, so for the only event type in the
    #: vocabulary there is always a correct value and "absent" can only mean the writer declined to
    #: record it. Kept nullable in shape because the field is keyed on `event_type`: a second kind
    #: would have to state its own provenance rule rather than inherit this one by accident.
    declared_by_actor_id: str | None = None
    #: Who or what executed this sweep. Required: §14.4 puts `actor_id` on every governance action.
    actor_id: str

    reason_code: str
    rationale: str | None = None

    occurred_at: dt.datetime
    trace_id: str
    episode_id: str | None = None

    @model_validator(mode="after")
    def _the_executor_is_not_the_author(self) -> Self:
        """`declared_by_actor_id` and `actor_id` answer different questions.

        Not an equality ban -- a supervisor who declared the policy may legitimately run the sweep
        by hand, and that is one actor in both slots. What is refused is a *blank* reason code,
        because the reason is the only prose on a record that exists to explain why a block lifted
        with nobody deciding.
        """
        if not self.reason_code.strip():
            raise ValueError(
                f"governance event {self.event_id} records no reason_code. It is the only account "
                "of why a block lifted with nobody having decided, and a blank one makes the "
                "closure unauditable while looking complete"
            )
        return self

    @model_validator(mode="after")
    def _an_expiry_names_the_authority_it_executed(self) -> Self:
        """`v3.3-a16`: a REVIEW_EXPIRY records who declared the policy it executed.

        The model half of `011g`'s CHECK, and it says the same thing. Both exist for the reason
        this project has written down repeatedly: a model guard holds for callers who go through
        the model, and a migration or a support script writes SQL. This one catches it earlier and
        explains it; the CHECK is the one that actually holds.

        Blank is refused alongside absent. A required field satisfied by an empty string is an
        optional field with extra steps, and this is the record that says an expiry executed a
        standing decision rather than a service account's own.
        """
        if (
            self.event_type is GovernanceEventType.REVIEW_EXPIRY
            and not (self.declared_by_actor_id or "").strip()
        ):
            raise ValueError(
                f"governance event {self.event_id} expires review {self.subject_id} without "
                "naming who declared the queue policy that authorised it. §17.19.1 makes the "
                "policy author the standing authority for automatic expiry and forbids inferring "
                f"it from the executor -- recording {self.actor_id} alone would make a service "
                "account look like the source of a governance decision it only carried out"
            )
        return self

    @property
    def closes_a_conflict(self) -> bool:
        return self.related_conflict_id is not None


__all__ = [
    "GovernanceEvent",
    "GovernanceEventType",
    "GovernanceSubjectType",
    "ResolutionEventKind",
]
