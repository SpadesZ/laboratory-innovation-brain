"""The episode path that connects the pieces SYS-001 names, and nothing else (SYS-001).

    §25.3 SYS-001  Core scientific state path MUST be Artifact/SourceWork -> Claim/Observation
                   -> Attestation -> RelationJudgment -> TransitionPolicy -> BeliefRevisionEvent
                   -> EpistemicStateProjection.

WHAT WAS MISSING, AND IT WAS NOT A COMPONENT. Every stage above existed and was governed: the
evidence tables since M0a, `TransitionPolicy.evaluate` since P7, the durable Decision since P8, the
read-side re-derivation since P9, the typed Conflict since P11, the review-resolution invariant
since P12/P13. What did not exist was a caller that walked the path end to end. So EPI-004's §26
row -- "**auto**-creates ReviewItem(AUTHORITY_CONFLICT)" -- had no auto: `core.escalation` built
the objects and every test invoked it by hand. This module is the missing caller, and it is
deliberately thin. It decides nothing.

THE DIVISION OF LABOUR, WHICH IS THE WHOLE DESIGN:

    TransitionPolicy.evaluate    pure, deterministic, replayable. Decides.
    this module                  impure: reads repositories, writes rows, calls the escalation
                                 seam. Decides nothing, and re-derives everything it reads.

`evaluate` must stay pure because `v3.3-a12` requires a stored Decision to re-derive from its own
snapshot: a policy that performed a repository read could not be replayed, and a replay that cannot
reproduce is not an audit. Every impure thing the flow needs therefore happens *here* -- resolving
the authority classes off the supporting attestations, loading the conflicts, reading the history --
and the resolved values are what go into the snapshot.

WHAT THIS MODULE MAY NOT BECOME. A second transition operator. §26's T-EPI-005 requires that only
`evaluate` exists in the codebase, so there is no `should_transition` here, no "force" flag and no
path that writes an event without an ALLOW. :func:`attempt_transition` returns the decision it got;
when the decision is not ALLOW the returned `event` is `None` and nothing was written. A caller that
wants a different answer has to change the evidence or the policy, which is the point.

THE THREE BRANCHES, AND WHY THE MIDDLE ONE IS THE INTERESTING ONE:

    ALLOW                 durable Decision -> BeliefRevisionEvent -> reload -> re-derive -> project
    NEED_HUMAN_REVIEW     auto-create the typed Conflict, auto-persist and link the ReviewItem,
      (AUTHORITY_         and write **no** event. This is EPI-004's auto, and EPI-006's
       INCOMPARABLE)      "AUTHORITY_CONFLICT from an INCOMPARABLE comparison creates a Conflict
                          linked to the auto-created ReviewItem".
    anything else         no event, no conflict, no review. A DENY is an answer, not a failure.

RETRIES ARE IDEMPOTENT, AND NOT BY BEING CAREFUL. An episode that runs twice must not queue a
second reviewer for one block. That guarantee is `011c`'s `authority_conflict_escalate`, which is
conditioned on `review_id IS NULL` and returns the existing review -- proven under real concurrency
in P13. This module's part is smaller and is the half a retry would otherwise break: it looks for an
existing unresolved `AUTHORITY_CONFLICT` on the hypothesis *before* minting a conflict id, because a
second conflict row would be a second block with its own review, and the database would be right to
accept it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - annotation only; see `belief.py` for the cycle it avoids
    from lab_brain.core.authority import AuthorityPolicy

from lab_brain.core.belief import (
    AuthorizedRevision,
    BeliefTransitionRefused,
    EpistemicStateProjection,
    authorize_transition,
    record_transition,
    replay,
    verified_history,
)
from lab_brain.core.escalation import authority_conflict_for, review_item_for
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefRevisionEvent, BeliefState
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.conflict import Conflict, ConflictType
from lab_brain.core.models.decision import BeliefTransitionDecision
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.review import ReviewItem
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionDecision,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)


class EpisodeRefused(RuntimeError):
    """The episode could not be run at all -- distinct from a policy refusing a transition.

    A DENY is a result and is *returned*. This is raised only when the episode cannot honestly
    ask the question: the named policy is not registered, the evidence is in another project, the
    hypothesis has no admitted history. Conflating the two would let a caller treat "I could not
    evaluate" as "the answer was no".
    """


# ---------------------------------------------------------------------------------------------
# Ports. Structural, so the in-memory stores and the SQL ones both satisfy them without either
# importing this module -- and so a test can substitute one without a backend.
# ---------------------------------------------------------------------------------------------


@runtime_checkable
class RelationSource(Protocol):
    """The admitted `RelationJudgment`s pointing at a subject (§17.8)."""

    def admitted_for_subject(
        self, project_id: str, subject_id: str
    ) -> tuple[RelationJudgment, ...]: ...


@runtime_checkable
class AuthorityClassSource(Protocol):
    """Resolves `supporting_attestation_ids` to their `authority_class` values (§17.2)."""

    def authority_classes_for(
        self, project_id: str, attestation_ids: Sequence[str]
    ) -> tuple[str, ...]: ...


@runtime_checkable
class ConflictSource(Protocol):
    """§17.19.3 conflicts, read and recorded."""

    def record(self, conflict: Conflict) -> Conflict: ...

    def get(self, project_id: str, conflict_id: str) -> Conflict | None: ...

    def unresolved_for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]: ...


@runtime_checkable
class ReviewSink(Protocol):
    """§17.19.1 review items, created and linked atomically (migration `011c`)."""

    def escalate_authority_conflict(
        self, *, conflict: Conflict, review: ReviewItem
    ) -> ReviewItem: ...

    def for_subject(self, project_id: str, subject_id: str) -> tuple[ReviewItem, ...]: ...


@runtime_checkable
class EventSink(Protocol):
    def append(self, authorized: AuthorizedRevision) -> BeliefRevisionEvent: ...

    def history(self, project_id: str, target_id: str) -> tuple[BeliefRevisionEvent, ...]: ...


@runtime_checkable
class DecisionSink(Protocol):
    def record(self, decision: BeliefTransitionDecision) -> BeliefTransitionDecision: ...

    def get(self, decision_id: str) -> BeliefTransitionDecision | None: ...


@runtime_checkable
class PolicySource(Protocol):
    def get(self, policy_id: str, version: str) -> TransitionPolicy | None: ...


@runtime_checkable
class IdSource(Protocol):
    """Supplies the ids this episode would otherwise invent.

    A seam rather than `uuid4()` inline, for one reason worth stating: a test that cannot predict
    the ids cannot assert that a *retry* reused them. Idempotence is the property under test, and
    it is unobservable if every run names its rows differently.
    """

    def decision_id(self) -> str: ...

    def event_id(self) -> str: ...

    def conflict_id(self) -> str: ...

    def review_id(self) -> str: ...


# ---------------------------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeResult:
    """Everything one attempt produced, including the deliberate absences.

    `event is None` is not an error path -- it is what three of the four outcomes look like, and a
    caller must be able to tell "no transition was authorised" from "something went wrong". The
    exception is reserved for the cases where the question could not be asked.
    """

    decision: TransitionDecision
    projection: EpistemicStateProjection
    #: The durable authorization. Recorded for *every* outcome, ALLOW or not: §17.14.1 keeps a
    #: DENY precisely because "this was considered and refused" is a fact worth having.
    authorization: BeliefTransitionDecision
    event: BeliefRevisionEvent | None = None
    conflict: Conflict | None = None
    review: ReviewItem | None = None
    #: True when the escalation found an existing conflict/review rather than creating one.
    escalation_was_existing: bool = False

    @property
    def transitioned(self) -> bool:
        return self.event is not None

    @property
    def escalated(self) -> bool:
        return self.review is not None


# ---------------------------------------------------------------------------------------------
# The episode
# ---------------------------------------------------------------------------------------------


class BeliefEpisode:
    """One hypothesis, one candidate transition, the whole governed path.

    Constructed with its ports rather than reaching for globals, so the same object runs against
    the in-memory stores and against PostgreSQL, and neither knows about the other.
    """

    def __init__(
        self,
        *,
        policies: PolicySource,
        decisions: DecisionSink,
        events: EventSink,
        relations: RelationSource,
        authority_classes: AuthorityClassSource,
        conflicts: ConflictSource,
        reviews: ReviewSink,
        ids: IdSource,
        authority_policies: Mapping[tuple[str, str], AuthorityPolicy] = MappingProxyType({}),
    ) -> None:
        self._policies = policies
        self._decisions = decisions
        self._events = events
        self._relations = relations
        self._authority_classes = authority_classes
        self._conflicts = conflicts
        self._reviews = reviews
        self._ids = ids
        self._authority_policies = authority_policies

    # -- reads -------------------------------------------------------------------------------

    def project(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        quarantined_attestation_ids: Sequence[str] = (),
        projected_at: dt.datetime | None = None,
    ) -> EpistemicStateProjection:
        """The current verified projection: history -> re-derive each -> fold -> attach conflicts.

        THE PRODUCTION READ PATH, AND THE ORDER IS THE POINT (`v3.3-a13`). `verified_history`
        re-derives every stored event's authorization *before* `replay` sees it, so a semantically
        forged Decision -- correct hash, correct linkage, ALLOW recorded, snapshot that evaluates
        to DENY -- is refused here rather than folded into a belief. PostgreSQL cannot make that
        check, because making it would mean a second copy of `evaluate` living in SQL.
        """
        history = self._events.history(project_id, hypothesis_id)
        verified = verified_history(
            project_id=project_id,
            target_id=hypothesis_id,
            events=history,
            decisions=self._decisions,
            policies=self._policies,
            authority_policies=self._authority_policies,
        )
        return replay(
            project_id,
            hypothesis_id,
            verified,
            quarantined_attestation_ids=quarantined_attestation_ids,
            unresolved_conflicts=[
                conflict.conflict_id
                for conflict in self._conflicts.unresolved_for_subject(project_id, hypothesis_id)
            ],
            projected_at=projected_at,
        )

    def hypothesis_view(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        current_state: BeliefState,
        stakes: str,
        admitted_relations: Sequence[RelationJudgment],
    ) -> HypothesisView:
        """Assemble the view `evaluate` reads, resolving what the pure policy cannot.

        Two repository reads happen here and nowhere else:

        * **conflicts** -- every unresolved §17.19.3 record naming this hypothesis. Handed over
          whole, not pre-filtered: which of them *block* is `blocking_conflict_policy`'s decision,
          and a caller that filtered first would be deciding it (the arrangement §17.19.3 forbids).
        * **authority classes** -- `authority_class` lives on `Attestation`, a `RelationJudgment`
          carries only `supporting_attestation_ids`, and §8.2.1's normative signature passes
          relations. Somebody has to join the two, and it cannot be the pure policy.

        `stakes` is a parameter because `Hypothesis` (§8.1) does not exist until EPI-001 in M3.
        Passing it is honest; defaulting it would invent the one field §8.2.1 hands straight to the
        ReviewItem a human then has to prioritise.
        """
        supporting = sorted(
            {
                attestation_id
                for relation in admitted_relations
                for attestation_id in relation.supporting_attestation_ids
            }
        )
        return HypothesisView(
            hypothesis_id=hypothesis_id,
            project_id=project_id,
            current_state=current_state,
            stakes=stakes,
            conflicts=self._conflicts.unresolved_for_subject(project_id, hypothesis_id),
            admitted_authority_classes=self._authority_classes.authority_classes_for(
                project_id, supporting
            ),
        )

    # -- the attempt -------------------------------------------------------------------------

    def attempt_transition(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        policy_id: str,
        policy_version: str,
        candidate_to_state: BeliefState,
        stakes: str,
        occurred_at: dt.datetime,
        trace_id: str,
        episode_id: str | None = None,
        actor_id: str | None = None,
        authority_policy_ref: tuple[str, str] | None = None,
        condition_matches: Sequence[ConditionMatch] = (),
        independence_summary: IndependenceSummary | None = None,
        triggering_attestations: Sequence[Attestation] = (),
        inference_provenance_id: str | None = None,
        rationale_artifact_or_record_ref: str | None = None,
        detected_by_actor_or_slot: str = "core.episode",
        estimated_human_minutes: int = 0,
    ) -> EpisodeResult:
        """Run one candidate transition through the whole path and act on the answer.

        `occurred_at` is a parameter, not a clock read. The episode is impure by design, but the
        *timestamps on the record* are the caller's to supply -- a function that stamped `now()`
        would make two otherwise identical runs produce different rows, and the first thing anyone
        does when auditing a belief is re-run it.

        `independence_summary` defaults to a WORK-basis summary of zero, which is a real answer
        rather than a convenience: EVI-004 says an unclassified pair contributes 0, so a policy
        with `min_independent_attestations` set will report the shortfall instead of being
        satisfied by silence. A caller that has resolved independence passes it.
        """
        policy = self._policies.get(policy_id, policy_version)
        if policy is None:
            raise EpisodeRefused(
                f"{policy_id}@{policy_version} is not registered. §8.2.1 keys a policy on "
                "(policy_id, version) and an unregistered one cannot be re-derived later, so the "
                "transition it would authorise could never be audited"
            )
        if policy.is_admission:
            raise EpisodeRefused(
                f"{policy_id}@{policy_version} is an admission policy. §8's admission gate is a "
                "separate path -- admit_hypothesis() -- and running it here would make every "
                "dropped predecessor look like a beginning"
            )

        prior = self.project(
            project_id=project_id, hypothesis_id=hypothesis_id, projected_at=occurred_at
        )
        if prior.current_state is None:
            raise EpisodeRefused(
                f"{hypothesis_id} in {project_id} has no admitted history, so there is no state to "
                "transition from. §8's admission gate runs first and is not this path"
            )

        admitted = self._relations.admitted_for_subject(project_id, hypothesis_id)
        view = self.hypothesis_view(
            project_id=project_id,
            hypothesis_id=hypothesis_id,
            current_state=prior.current_state,
            stakes=stakes,
            admitted_relations=admitted,
        )
        comparator = self._authority_policy_for(policy, authority_policy_ref)

        # THE DURABLE AUTHORIZATION IS COMPUTED, NEVER SUPPLIED. `authorize_transition` takes the
        # six inputs and *derives* the verdict; there is no parameter through which this method
        # could hand in the answer it wanted. That asymmetry is what makes the stored snapshot
        # worth re-deriving.
        authorization = authorize_transition(
            decision_id=self._ids.decision_id(),
            policy=policy,
            hypothesis=view,
            admitted_relations=admitted,
            authority_policy=comparator,
            condition_matches=tuple(condition_matches),
            independence_summary=independence_summary or IndependenceSummary(),
            candidate_to_state=candidate_to_state,
            created_at=occurred_at,
            episode_id=episode_id,
            actor_id=actor_id,
        )
        self._decisions.record(authorization)
        decision = authorization.evaluated

        if decision.outcome is TransitionOutcome.ALLOW:
            event = self._commit(
                policy=policy,
                comparator=comparator,
                authorization=authorization,
                view=view,
                prior=prior,
                candidate_to_state=candidate_to_state,
                occurred_at=occurred_at,
                trace_id=trace_id,
                triggering_attestations=triggering_attestations,
                triggering_relations=admitted,
                actor_id=actor_id,
                inference_provenance_id=inference_provenance_id,
                rationale_artifact_or_record_ref=rationale_artifact_or_record_ref,
            )
            return EpisodeResult(
                decision=decision,
                authorization=authorization,
                event=event,
                projection=self.project(
                    project_id=project_id, hypothesis_id=hypothesis_id, projected_at=occurred_at
                ),
            )

        conflict: Conflict | None = None
        review: ReviewItem | None = None
        existing = False
        if decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW:
            if decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE:
                conflict, review, existing = self._escalate(
                    decision=decision,
                    view=view,
                    occurred_at=occurred_at,
                    trace_id=trace_id,
                    episode_id=episode_id,
                    detected_by_actor_or_slot=detected_by_actor_or_slot,
                    estimated_human_minutes=estimated_human_minutes,
                    supporting_refs=tuple(
                        sorted({record.attestation_id for record in triggering_attestations})
                    ),
                )
            elif decision.blocking_conflict_ids:
                # A RETRY LANDS HERE, NOT IN THE BRANCH ABOVE, AND THAT SURPRISED THIS CODE ONCE.
                # Once the first attempt has raised the AUTHORITY_CONFLICT, the conflict itself
                # blocks -- so `evaluate` reports BLOCKING_CONFLICT at check 2 and never reaches
                # the authority check at 6. Nothing should be created (there is already a block and
                # a reviewer), but a caller that got `review=None` would have no way to find out
                # who is handling it, and the obvious fix -- escalating again -- is the duplicate
                # this whole path exists to prevent. So the existing pair is *reported*.
                conflict, review, existing = self._existing_block(
                    view.project_id, decision.blocking_conflict_ids
                )

        # Re-projected after the escalation, so `unresolved_conflicts` includes the conflict this
        # attempt just raised. A projection that omitted it would tell the next reader the belief
        # is unblocked at the exact moment it became blocked.
        return EpisodeResult(
            decision=decision,
            authorization=authorization,
            event=None,
            conflict=conflict,
            review=review,
            escalation_was_existing=existing,
            projection=self.project(
                project_id=project_id, hypothesis_id=hypothesis_id, projected_at=occurred_at
            ),
        )

    # -- the two branches, kept separate so neither can quietly grow the other's powers -------

    def _commit(
        self,
        *,
        policy: TransitionPolicy,
        comparator: AuthorityPolicy | None,
        authorization: BeliefTransitionDecision,
        view: HypothesisView,
        prior: EpistemicStateProjection,
        candidate_to_state: BeliefState,
        occurred_at: dt.datetime,
        trace_id: str,
        triggering_attestations: Sequence[Attestation],
        triggering_relations: Sequence[RelationJudgment],
        actor_id: str | None,
        inference_provenance_id: str | None,
        rationale_artifact_or_record_ref: str | None,
    ) -> BeliefRevisionEvent:
        """Mint and persist the event an ALLOW authorises.

        No refusal is caught here. `record_transition` raises `BeliefTransitionRefused` on any
        disagreement between the authorization and the event it would write, and swallowing that
        to "return None instead" would turn the loudest guard in the system into a quiet branch.
        """
        authorized = record_transition(
            event_id=self._ids.event_id(),
            authorization=authorization,
            policy=policy,
            authority_policy=comparator,
            hypothesis=view,
            candidate_to_state=candidate_to_state,
            prior=prior,
            occurred_at=occurred_at,
            trace_id=trace_id,
            triggering_attestations=triggering_attestations,
            triggering_relations=triggering_relations,
            actor_id=actor_id,
            inference_provenance_id=inference_provenance_id,
            rationale_artifact_or_record_ref=rationale_artifact_or_record_ref,
        )
        return self._events.append(authorized)

    def _escalate(
        self,
        *,
        decision: TransitionDecision,
        view: HypothesisView,
        occurred_at: dt.datetime,
        trace_id: str,
        episode_id: str | None,
        detected_by_actor_or_slot: str,
        estimated_human_minutes: int,
        supporting_refs: tuple[str, ...],
    ) -> tuple[Conflict, ReviewItem, bool]:
        """EPI-004's *auto*: create the typed Conflict and its ReviewItem, or reuse them.

        THE REUSE CHECK IS THE IDEMPOTENCE, AND IT IS THIS MODULE'S HALF. `011c` made
        `authority_conflict_escalate` idempotent per conflict -- a retry gets the review that
        already gates it, proven under real concurrency in P13. But that guarantee is keyed on the
        *conflict*, and a retried episode that minted a fresh conflict id would sail straight past
        it: two conflicts, two reviews, one hypothesis blocked twice. So the existing unresolved
        AUTHORITY_CONFLICT is looked up first, by subject.

        No semantics are reimplemented here. The Conflict and the ReviewItem are built by
        `core.escalation`, which refuses a decision that did not escalate and refuses a mistyped
        conflict; the linking is `011c`'s function, through the review store.
        """
        for existing in self._conflicts.unresolved_for_subject(view.project_id, view.hypothesis_id):
            if existing.conflict_type is not ConflictType.AUTHORITY_CONFLICT:
                continue
            queued = self._reviews.for_subject(view.project_id, existing.conflict_id)
            if queued:
                return existing, queued[0], True
            # A conflict recorded with no review is a block nobody is working on. Finishing the
            # escalation is the repair, and `authority_conflict_escalate` is conditioned on
            # `review_id IS NULL`, so a concurrent finisher still yields one winner.
            return (
                existing,
                self._reviews.escalate_authority_conflict(
                    conflict=existing,
                    review=review_item_for(
                        review_id=self._ids.review_id(),
                        conflict=existing,
                        decision=decision,
                        created_at=occurred_at,
                        estimated_human_minutes=estimated_human_minutes,
                    ),
                ),
                True,
            )

        conflict = self._conflicts.record(
            authority_conflict_for(
                conflict_id=self._ids.conflict_id(),
                decision=decision,
                hypothesis=view,
                detected_at=occurred_at,
                detected_by_actor_or_slot=detected_by_actor_or_slot,
                trace_id=trace_id,
                episode_id=episode_id,
                supporting_refs=supporting_refs,
            )
        )
        review = self._reviews.escalate_authority_conflict(
            conflict=conflict,
            review=review_item_for(
                review_id=self._ids.review_id(),
                conflict=conflict,
                decision=decision,
                created_at=occurred_at,
                estimated_human_minutes=estimated_human_minutes,
            ),
        )
        return conflict, review, False

    def _existing_block(
        self, project_id: str, blocking_conflict_ids: Sequence[str]
    ) -> tuple[Conflict | None, ReviewItem | None, bool]:
        """Report the conflict already gating this belief, and the review already queued for it.

        READ-ONLY, DELIBERATELY. This path creates nothing. §8.2.1's auto-creation is specific to
        INCOMPARABLE authority; a blocking conflict of some other type is a disagreement the domain
        declared gating, and whether it should also raise a ReviewItem is that conflict's own
        escalation story rather than something to infer here. Reporting an *unreviewed* blocking
        conflict with `review=None` is the honest answer: the belief is blocked and nobody is on it.
        """
        for conflict_id in sorted(blocking_conflict_ids):
            queued = self._reviews.for_subject(project_id, conflict_id)
            if queued:
                return self._conflicts.get(project_id, conflict_id), queued[0], True
        return None, None, False

    def _authority_policy_for(
        self, policy: TransitionPolicy, ref: tuple[str, str] | None
    ) -> AuthorityPolicy | None:
        """Resolve the named comparator, or refuse -- never silently pass `None`.

        THE COMPARATOR IS NAMED BY THE CALLER, WHICH IS NOT AN OVERSIGHT. `TransitionPolicy` has no
        field pointing at one and `AuthorityPolicy` carries no domain; §8.2.1 passes the comparator
        as an *argument* to `evaluate`, so choosing it is the caller's act. Inferring it from
        `policy.domain` would mean core picking a DomainPack comparator on a hypothesis's behalf,
        and §10.5.1 is explicit that the ordering is the domain's to state.

        FAIL CLOSED RATHER THAN ESCALATE, and this is the subtle one. `evaluate` reads a `None`
        comparator beside a `required_authority_rule` as AUTHORITY_INCOMPARABLE and escalates --
        correct behaviour for *that* function, which cannot tell "these classes are unrankable"
        from "nobody supplied a ranker". Here the two are distinguishable, and letting an
        unregistered comparator become a queued ReviewItem would put a human in front of a
        configuration error and bill it to the one budget §14.4.1 says is scarce.

        A comparator supplied for a policy that declares no authority rule is dropped, not
        recorded. It would change nothing about the verdict and everything about the snapshot: the
        stored `authority_policy_id` makes re-derivation *require* that comparator to be resolvable
        forever after (§17.14.1), so recording an unused one manufactures a permanent dependency.
        """
        if policy.required_authority_rule is None:
            return None
        if ref is None:
            raise EpisodeRefused(
                f"{policy.policy_id}@{policy.version} requires authority "
                f"{policy.required_authority_rule!r} but no authority_policy_ref was supplied. "
                "Core ships no default ordering (§10.5), and evaluating without a comparator would "
                "escalate to a human for what is a missing registration"
            )
        comparator = self._authority_policies.get(ref)
        if comparator is None:
            registered = sorted(f"{name}@{version}" for name, version in self._authority_policies)
            raise EpisodeRefused(
                f"comparator {ref[0]}@{ref[1]} is not registered; available: "
                f"{registered or 'none'}. §8.2.1's determinism guarantee holds within one "
                "comparator version and says nothing across two, so there is no nearest match"
            )
        return comparator


__all__ = [
    "AuthorityClassSource",
    "BeliefEpisode",
    "BeliefTransitionRefused",
    "ConflictSource",
    "DecisionSink",
    "EpisodeRefused",
    "EpisodeResult",
    "EventSink",
    "IdSource",
    "PolicySource",
    "RelationSource",
    "ReviewSink",
]
