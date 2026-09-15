"""§17.14.1's `Decision` as the durable authorization behind a belief transition (`v3.3-a12`).

WHY THIS EXISTS AT ALL. Before `v3.3-a12` a `BeliefRevisionEvent` recorded which policy *would
have* authorised it, and nothing more. `TransitionDecision` had no identity and was never stored,
so a hand-built event citing a real policy and recording exactly the transition that policy
governs was indistinguishable from one that had actually been evaluated. The missing piece was not
a check -- it was the **object to check against**. This module is that object.

AND WHY A SNAPSHOT RATHER THAN A VERDICT. Storing only `result=ALLOW` would move the forgery one
level up: anyone could write a Decision row saying ALLOW. What makes this durable is
``decision_input_snapshot`` -- the six inputs of §8.2.1's canonical operator, canonically
serialized and hashed. Forging an authorization now requires supplying inputs that genuinely
evaluate to ALLOW under the immutable policy, and at that point it is not a forgery; it is an
authorization. §8.2.1's determinism guarantee is what converts recomputation from a guess into a
check.

THE ONE THING IT CANNOT RECONSTRUCT BY ITSELF. `AuthorityPolicy` is a DomainPack-supplied
comparator (§10.5, ADR-0007) and core must not import a DomainPack, so the snapshot records its
identity and version rather than the object. Re-derivation therefore needs that comparator to be
present. The spec is explicit that the alternative -- storing the comparison *results* -- is
forbidden: it would make the authority rules unfalsifiable, which is exactly what §10.5.1 refuses
when it bans silently coercing INCOMPARABLE into an ordering.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from lab_brain.core.canonical_json import canonical_hash, canonicalize
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionDecision,
    TransitionOutcome,
)


class DecisionType(StrEnum):
    """§17.14.1. Fixed to ``BELIEF_TRANSITION`` for this use.

    Declared as an enum with one member rather than a bare string because §17.14.1 reserves
    `Decision` for other decision types too; a future `decision_type` must be added here
    deliberately rather than arriving as an unvalidated string.
    """

    BELIEF_TRANSITION = "BELIEF_TRANSITION"


class DecisionInputSnapshot(CoreModel):
    """The six inputs of `TransitionPolicy.evaluate` (§8.2.1), immutably recorded.

    Field names match the canonical operator's parameter names exactly. That is deliberate: this
    snapshot's whole purpose is to be fed back into `evaluate`, and a rename here would be a
    silent divergence between what was authorised and what gets re-checked.
    """

    hypothesis: HypothesisView
    admitted_relations: tuple[RelationJudgment, ...] = ()
    condition_matches: tuple[ConditionMatch, ...] = ()
    independence_summary: IndependenceSummary
    candidate_to_state: BeliefState

    #: §10.5's comparator by identity, never by result. ``None`` means no comparator took part,
    #: which is the only case where re-derivation needs nothing outside this record.
    authority_policy_id: str | None = None
    authority_policy_version: str | None = None

    @model_validator(mode="after")
    def _authority_identity_is_all_or_nothing(self) -> DecisionInputSnapshot:
        """Half an identity cannot locate a comparator, so it is not a valid record of one."""
        if (self.authority_policy_id is None) != (self.authority_policy_version is None):
            raise ValueError(
                "authority_policy_id and authority_policy_version must be given together: "
                "an id without a version does not uniquely locate a comparator, and a version "
                "without an id names nothing at all (§17.14.1, v3.3-a12)"
            )
        return self

    def canonical_form(self) -> dict[str, Any]:
        """The exact structure that gets serialized and hashed.

        Built by `model_dump(mode="json")` rather than by hand so a field added to the snapshot
        cannot be left out of the hash -- a hash that covers some of the inputs is worse than no
        hash, because it looks like a binding.
        """
        return self.model_dump(mode="json")

    def canonical_bytes_text(self) -> str:
        """Canonical JSON text. This exact string is what gets stored and hashed."""
        return canonicalize(self.canonical_form())

    def input_hash(self) -> str:
        """``sha256:`` over the canonical bytes, per §17.14.1."""
        return canonical_hash(self.canonical_form())


class BeliefTransitionDecision(CoreModel):
    """A stored, re-derivable authorization for one belief transition (§17.14.1, `v3.3-a12`).

    ``result`` is §17.14.1's top-level field and ``evaluated`` is §8.2.1's full
    `TransitionDecision`. Both are kept, and a validator holds them consistent: the DB trigger
    needs a single scalar column to refuse a non-ALLOW authorization, while re-derivation has to
    compare the *whole* decision -- a record that matched only on `outcome` would accept a
    re-evaluation that produced a different `reason_code` or a different conflict set.
    """

    decision_id: str
    project_id: str
    subject_id: str
    decision_type: DecisionType = DecisionType.BELIEF_TRANSITION

    result: TransitionOutcome
    evaluated: TransitionDecision

    policy_id: str
    policy_version: str
    from_state: BeliefState
    to_state: BeliefState

    decision_input_snapshot: DecisionInputSnapshot
    input_hash: str

    episode_id: str | None = None
    actor_id: str | None = None
    policy_refs: tuple[str, ...] = ()
    triggering_event_ids: tuple[str, ...] = ()
    created_at: dt.datetime = Field(...)

    @model_validator(mode="after")
    def _the_record_agrees_with_itself(self) -> BeliefTransitionDecision:
        """Every cross-field invariant §17.14.1 states, checked at construction.

        These are not redundant with the database trigger. The trigger stops a forged row from
        being persisted; this stops an inconsistent Decision from ever being built, so the error
        surfaces at the line that got it wrong rather than at commit time.
        """
        if self.result is not self.evaluated.outcome:
            raise ValueError(
                f"result is {self.result.value} but the recorded TransitionDecision says "
                f"{self.evaluated.outcome.value}; a Decision whose scalar verdict disagrees with "
                "the decision it stores can be read two ways, and the DB reads the scalar"
            )
        if (self.evaluated.policy_id, self.evaluated.policy_version) != (
            self.policy_id,
            self.policy_version,
        ):
            raise ValueError(
                f"the stored decision was made by {self.evaluated.policy_id}@"
                f"{self.evaluated.policy_version} but this record claims "
                f"{self.policy_id}@{self.policy_version}"
            )
        snapshot = self.decision_input_snapshot
        if snapshot.candidate_to_state is not self.to_state:
            raise ValueError(
                f"the snapshot was evaluated toward {snapshot.candidate_to_state.value} but this "
                f"record authorises a transition to {self.to_state.value}"
            )
        if snapshot.hypothesis.current_state is not self.from_state:
            raise ValueError(
                f"the snapshot's hypothesis is at {snapshot.hypothesis.current_state.value} but "
                f"this record authorises a transition from {self.from_state.value}"
            )
        if snapshot.hypothesis.hypothesis_id != self.subject_id:
            raise ValueError(
                f"the snapshot evaluated {snapshot.hypothesis.hypothesis_id} but this record "
                f"names {self.subject_id} as its subject"
            )
        if snapshot.hypothesis.project_id != self.project_id:
            raise ValueError(
                f"the snapshot's hypothesis belongs to {snapshot.hypothesis.project_id} but this "
                f"record claims {self.project_id}; SEC-002 scopes every read by project, so an "
                "authorization that spans two of them authorises nothing in either"
            )
        expected = snapshot.input_hash()
        if self.input_hash != expected:
            raise ValueError(
                f"input_hash is {self.input_hash} but the snapshot canonicalizes to {expected}; "
                "the hash is the binding between this authorization and the inputs it was "
                "computed from, and an unbound hash is decoration"
            )
        return self

    @property
    def authorizes_transition(self) -> bool:
        """Only ALLOW authorises. The other three outcomes are records of refusal."""
        return self.result is TransitionOutcome.ALLOW


__all__ = [
    "BeliefTransitionDecision",
    "DecisionInputSnapshot",
    "DecisionType",
]
