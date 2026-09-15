"""Creating a belief revision, and replaying them back (EPI-003, EPI-005, §6.18, §8.2.1).

THREE FUNCTIONS. TWO ARE GATES AND THE THIRD IS THE REPLAY.

:func:`record_transition` (a §8.2.1 transition) and :func:`admit_hypothesis` (§8's admission) are
the only ways to obtain an :class:`AuthorizedRevision`, and the event store accepts nothing else.
A bare :class:`BeliefRevisionEvent` can still be constructed -- it is a Pydantic model -- but it
cannot be persisted, which is the difference the P7 audit asked for: the persistence path can now
tell an authorised revision from an unevaluated one.

Admission is a *separate* path rather than a relaxation of the transition gate. A hypothesis with
no events has no state and every `TransitionPolicy` declares a `from_state`, so a transition can
never be a target's first record; before `admit_hypothesis` the only way to write that first event
was to bypass the gate entirely, which turned the one legitimate un-gated write into a general
bypass.

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Annotation-only. `lab_brain.core.authority` imports `models.enums`, which executes
    # `models/__init__`, which imports `models.transition`, which imports `authority` -- so a
    # runtime import here would enter that cycle from a third side and break collection. The
    # cycle predates this module; importing the Protocol lazily avoids widening it.
    from lab_brain.core.authority import AuthorityPolicy

from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import (
    BeliefRevisionEvent,
    BeliefState,
    BeliefTargetType,
)
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.decision import (
    BeliefTransitionDecision,
    DecisionInputSnapshot,
    DecisionType,
)
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionDecision,
    TransitionPolicy,
)


class BeliefTransitionRefused(RuntimeError):
    """An event was asked for that no policy decision authorises.

    Raised rather than returned. A refusal here is not a governance outcome a planner should route
    around -- ``evaluate`` already produced the governance outcome, and this means the caller is
    trying to write an event that disagrees with it.
    """


#: The capability only this module can present. See :class:`AuthorizedRevision`.
_MINTED_HERE = object()


@dataclass(frozen=True)
class AuthorizedRevision:
    """An event plus the in-process fact that this module produced it from an authorisation.

    WHY THIS TYPE EXISTS. Before it, ``store.append(event)`` took a bare
    :class:`BeliefRevisionEvent`, and a hand-constructed one was indistinguishable from the output
    of :func:`record_transition` -- so the persistence path could not tell an authorised revision
    from an unevaluated one. Making the store accept only this type means the bypass has to be
    written deliberately and is visible in review: a caller with an event and no capability cannot
    append it.

    WHAT IT IS NOT: durable. The capability lives in one process. A support script, a migration or
    a future service writing SQL is not bound by it, and the stored row records nothing about it.
    Migration ``005c`` closes every forgery that is *inconsistent* with the cited policy; the
    consistent one needs a persisted authorisation, which §17.13 and §8.2.1 cannot express --
    escalated as SPEC-ISSUE-011 rather than invented here (AGT-015), and carried as risk R-13.

    ``_proof`` is a module-private sentinel, not a secret. Someone who imports ``_MINTED_HERE`` can
    forge one; the point is that they cannot do it *accidentally*, and that the line doing it shows
    up in a diff.
    """

    event: BeliefRevisionEvent
    #: Which path minted this -- a §8.2.1 transition or a §8 admission. Recorded so a reader of a
    #: call site can see which of the two gates was used without following the value.
    origin: str
    _proof: object = None

    def __post_init__(self) -> None:
        if self._proof is not _MINTED_HERE:
            raise BeliefTransitionRefused(
                "AuthorizedRevision cannot be constructed directly. A belief revision is written "
                "by record_transition() from a policy ALLOW, or by admit_hypothesis() through §8's "
                "admission gate -- constructing the capability beside them is the bypass it exists "
                "to make visible"
            )


class SkipReason(StrEnum):
    """Why a recorded event did not contribute to a replayed projection."""

    #: §6.18: the event's triggering evidence was quarantined.
    QUARANTINED_TRIGGER = "QUARANTINED_TRIGGER"
    #: A predecessor was skipped, so this event's `from_state` no longer holds.
    PREDECESSOR_MISSING = "PREDECESSOR_MISSING"


class BeliefScopeError(RuntimeError):
    """A replay or a history read mixed projects.

    Separate from :class:`BeliefTransitionRefused`: that one means a caller tried to write an
    unauthorised belief, this one means a caller lost track of which project it was asking about.
    Different mistakes, different people to tell.
    """


@dataclass(frozen=True)
class BeliefProjection:
    """The minimal replay result: what one project's events say the state is now.

    ``skipped`` is carried rather than discarded, and it is the interesting half. After a
    contamination rollback, "the state is ACTIVE" is much less useful than "the state is ACTIVE
    because these four events were dropped" -- the second is reviewable, the first is an assertion.
    """

    project_id: str
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
    project_id: str,
    target_id: str,
    events: Sequence[BeliefRevisionEvent],
    quarantined_attestation_ids: Iterable[str] = (),
) -> BeliefProjection:
    """Fold one project's events for one target into its current state (§6.18).

    SCOPED ON ``(project_id, target_id)``, not on the target alone. `v3.3-a11` added `project_id`
    so that "this project's belief history" is expressible, and a replay keyed only on `target_id`
    throws that away: two projects may legitimately use the same hypothesis id, and folding both
    histories together produces a state neither of them is in.

    Mixed-project input **fails loudly** rather than being filtered. A caller that hands this
    function events from two projects has already lost track of scope somewhere earlier, and
    silently dropping the foreign ones would return a plausible projection built from a query
    nobody meant to run.

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
    foreign = sorted({event.project_id for event in events if event.project_id != project_id})
    if foreign:
        raise BeliefScopeError(
            f"replay of {target_id} in {project_id} was handed events from "
            f"{', '.join(foreign)}. Two projects may legitimately use the same target id, so "
            "folding their histories together would produce a state neither is in -- and "
            "filtering them out silently would hide that the query was wrong"
        )

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
        project_id=project_id,
        target_id=target_id,
        current_state=state,
        last_event_id=last,
        applied=tuple(applied),
        skipped=tuple(skipped),
    )


class AuthorizationNotRederivable(BeliefTransitionRefused):
    """A stored authorization did not reproduce when re-evaluated (§17.14.1, `v3.3-a12`).

    Its own class because it is the one refusal that is never a caller mistake. Every other
    refusal in this module means someone assembled an event wrongly; this one means the record
    and the policy disagree about what was authorised, which is either a forged Decision or a
    policy that was mutated after the fact. Both need a human, and neither should be caught and
    retried.
    """


def authorize_transition(
    *,
    decision_id: str,
    policy: TransitionPolicy,
    hypothesis: HypothesisView,
    admitted_relations: Sequence[RelationJudgment] = (),
    authority_policy: AuthorityPolicy | None = None,
    condition_matches: Sequence[ConditionMatch] = (),
    independence_summary: IndependenceSummary,
    candidate_to_state: BeliefState,
    created_at: dt.datetime,
    episode_id: str | None = None,
    actor_id: str | None = None,
    triggering_event_ids: Sequence[str] = (),
) -> BeliefTransitionDecision:
    """Evaluate a transition and record the authorization durably (§17.14.1, `v3.3-a12`).

    This is the only supported way to obtain a :class:`BeliefTransitionDecision`, and it does not
    take a `TransitionDecision` as an argument -- it *computes* one. That asymmetry is the whole
    mechanism: a caller cannot hand in the verdict it wants, because the verdict is derived here
    from the six inputs, and those same six inputs are what gets stored.

    Non-ALLOW outcomes are returned rather than raised. A DENY is a real and useful record -- it
    says this transition was considered and refused -- and §17.14.1 keeps it for exactly that
    reason. What it cannot do is authorise anything; :func:`record_transition` refuses it.
    """
    snapshot = DecisionInputSnapshot(
        hypothesis=hypothesis,
        admitted_relations=tuple(admitted_relations),
        condition_matches=tuple(condition_matches),
        independence_summary=independence_summary,
        candidate_to_state=candidate_to_state,
        authority_policy_id=None if authority_policy is None else authority_policy.policy_id,
        authority_policy_version=(
            None if authority_policy is None else authority_policy.policy_version
        ),
    )

    evaluated = policy.evaluate(
        hypothesis,
        tuple(admitted_relations),
        authority_policy,
        tuple(condition_matches),
        independence_summary,
        candidate_to_state,
    )

    return BeliefTransitionDecision(
        decision_id=decision_id,
        project_id=hypothesis.project_id,
        subject_id=hypothesis.hypothesis_id,
        decision_type=DecisionType.BELIEF_TRANSITION,
        result=evaluated.outcome,
        evaluated=evaluated,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        from_state=hypothesis.current_state,
        to_state=candidate_to_state,
        decision_input_snapshot=snapshot,
        input_hash=snapshot.input_hash(),
        episode_id=episode_id,
        actor_id=actor_id,
        policy_refs=(f"{policy.policy_id}@{policy.version}",),
        triggering_event_ids=tuple(triggering_event_ids),
        created_at=created_at,
    )


def rederive_decision(
    *,
    authorization: BeliefTransitionDecision,
    policy: TransitionPolicy,
    authority_policy: AuthorityPolicy | None = None,
) -> TransitionDecision:
    """Re-run `evaluate` on the stored snapshot and insist it reproduces (`v3.3-a12` (d)).

    Fail-closed, and the comparison is over the **whole** `TransitionDecision` under canonical
    serialization, not just `outcome`. A re-evaluation that agreed on ALLOW but disagreed on
    `reason_code` or `blocking_conflict_ids` would mean the policy has changed underneath the
    record, and accepting it would let a mutated policy launder an old authorization.

    Raises :class:`AuthorizationNotRederivable` on any disagreement, including a comparator whose
    identity does not match the one the snapshot recorded -- re-deriving under a *different*
    DomainPack comparator answers a different question, and answering it would be worse than
    refusing because the result looks like a confirmation.
    """
    snapshot = authorization.decision_input_snapshot

    if authorization.input_hash != snapshot.input_hash():
        raise AuthorizationNotRederivable(
            f"{authorization.decision_id} records input_hash {authorization.input_hash} but its "
            f"snapshot canonicalizes to {snapshot.input_hash()}; the inputs have been altered "
            "since the authorization was computed, so there is nothing left to re-derive"
        )

    if (policy.policy_id, policy.version) != (
        authorization.policy_id,
        authorization.policy_version,
    ):
        raise AuthorizationNotRederivable(
            f"{authorization.decision_id} was computed under {authorization.policy_id}@"
            f"{authorization.policy_version}, but re-derivation was attempted with "
            f"{policy.policy_id}@{policy.version}. §8.2.1's determinism guarantee holds within one "
            "policy version and says nothing across two"
        )

    supplied = (
        (None, None)
        if authority_policy is None
        else (authority_policy.policy_id, authority_policy.policy_version)
    )
    recorded = (snapshot.authority_policy_id, snapshot.authority_policy_version)
    if supplied != recorded:
        raise AuthorizationNotRederivable(
            f"{authorization.decision_id} was computed with authority comparator "
            f"{recorded[0]}@{recorded[1]} but re-derivation supplied {supplied[0]}@{supplied[1]}. "
            "Core cannot reconstruct a DomainPack comparator from a record (§24.2), so it must be "
            "the same one -- and §17.14.1 forbids storing its results instead, because that would "
            "put the authority rules beyond falsification (§10.5.1)"
        )

    replayed = policy.evaluate(
        snapshot.hypothesis,
        snapshot.admitted_relations,
        authority_policy,
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )

    if canonicalize(replayed.model_dump(mode="json")) != canonicalize(
        authorization.evaluated.model_dump(mode="json")
    ):
        raise AuthorizationNotRederivable(
            f"{authorization.decision_id} records a {authorization.result.value} "
            f"({authorization.evaluated.reason_code.value}) but re-evaluating its own snapshot "
            f"under {policy.policy_id}@{policy.version} yields {replayed.outcome.value} "
            f"({replayed.reason_code.value}). Either the authorization was never computed from "
            "these inputs, or the policy changed after it was -- in both cases the transition is "
            "unauthorised and this fails closed"
        )

    return replayed


def record_transition(
    *,
    event_id: str,
    authorization: BeliefTransitionDecision,
    policy: TransitionPolicy,
    authority_policy: AuthorityPolicy | None = None,
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
) -> AuthorizedRevision:
    """Build the event a policy ALLOW authorises, or refuse to build one at all.

    Keyword-only throughout. Eleven positional arguments of which several are strings is how a
    ``trace_id`` ends up in the ``actor_id`` slot, and this is the function whose whole job is to
    make an event trustworthy.

    ``prior`` is the replayed projection, passed in rather than loaded: the check it enables --
    that the hypothesis has not moved since the decision was computed -- is meaningless against a
    projection this function derived itself from the same stale view.

    Since `v3.3-a12` the authorization is a stored :class:`BeliefTransitionDecision` and is
    **re-derived here before anything is minted**. That ordering matters: re-deriving first means
    a Decision that cannot reproduce never reaches the other checks, so no event can be built on
    an authorization whose inputs no longer evaluate to what it claims.
    """
    rederive_decision(
        authorization=authorization,
        policy=policy,
        authority_policy=authority_policy,
    )
    decision = authorization.evaluated

    if authorization.decision_type is not DecisionType.BELIEF_TRANSITION:
        raise BeliefTransitionRefused(
            f"{authorization.decision_id} is a {authorization.decision_type.value} decision; only "
            "a BELIEF_TRANSITION decision authorises a belief transition (§17.14.1)"
        )

    if not authorization.authorizes_transition:
        raise BeliefTransitionRefused(
            f"authorization {authorization.decision_id} for {hypothesis.hypothesis_id} records "
            f"{authorization.result.value} ({decision.reason_code.value}), so no belief revision "
            "event may be created. Running `evaluate` and then writing the event regardless is "
            "the bypass EPI-005 and AGT-016 exist to forbid"
        )

    if (authorization.project_id, authorization.subject_id) != (
        hypothesis.project_id,
        hypothesis.hypothesis_id,
    ):
        raise BeliefTransitionRefused(
            f"authorization {authorization.decision_id} authorises "
            f"{authorization.subject_id} in {authorization.project_id}, but the event would "
            f"record {hypothesis.hypothesis_id} in {hypothesis.project_id}. An ALLOW is for one "
            "subject in one project and does not transfer to another"
        )

    if (decision.policy_id, decision.policy_version) != (policy.policy_id, policy.version):
        raise BeliefTransitionRefused(
            f"the decision was made by {decision.policy_id}@{decision.policy_version} but the "
            f"event would cite {policy.policy_id}@{policy.version}; an ALLOW does not carry over "
            "to another policy or another version of the same one"
        )

    if (authorization.from_state, authorization.to_state) != (
        hypothesis.current_state,
        candidate_to_state,
    ):
        raise BeliefTransitionRefused(
            f"authorization {authorization.decision_id} covers "
            f"{authorization.from_state.value} -> {authorization.to_state.value}, but the event "
            f"would record {hypothesis.current_state.value} -> {candidate_to_state.value}"
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

    if policy.is_admission:
        raise BeliefTransitionRefused(
            f"{policy.policy_id}@{policy.version} is an admission policy, and §8's admission gate "
            "is a separate path -- use admit_hypothesis(). Allowing a transition here would make "
            "every dropped predecessor look like an admission"
        )

    return AuthorizedRevision(
        event=BeliefRevisionEvent(
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
            authorization_decision_id=authorization.decision_id,
            actor_id=actor_id,
            inference_provenance_id=inference_provenance_id,
            rationale_artifact_or_record_ref=rationale_artifact_or_record_ref,
            occurred_at=occurred_at,
            trace_id=trace_id,
        ),
        origin="TRANSITION",
        _proof=_MINTED_HERE,
    )


def admit_hypothesis(
    *,
    event_id: str,
    policy: TransitionPolicy,
    project_id: str,
    hypothesis_id: str,
    prior: BeliefProjection,
    occurred_at: dt.datetime,
    trace_id: str,
    triggering_attestations: Sequence[Attestation] = (),
    triggering_relations: Sequence[RelationJudgment] = (),
    actor_id: str | None = None,
    inference_provenance_id: str | None = None,
    rationale_artifact_or_record_ref: str | None = None,
) -> AuthorizedRevision:
    """Record a hypothesis's **first** state: §8's Hypothesis Admission Gate.

    A SEPARATE PATH, DELIBERATELY. A hypothesis with no events has no state, and every
    `TransitionPolicy` declares a `from_state` -- so a policy-authorised *transition* always has a
    predecessor and can never be a target's first record. Before this function, the only way to
    write that first event was to bypass the gate entirely, which made the one legitimate
    un-gated write into a general bypass (the P7 audit's first finding).

    So admission is its own function, backed by its own kind of policy (``is_admission``), and it
    refuses the two things that would turn it back into a hole:

        a transition policy      would let any dropped predecessor be recorded as an admission
        a target with history    admission happens once; a second one would rewrite the beginning

    §8's full admission gate -- mechanism, prediction, falsifier, assumptions, confounders,
    minimum test -- is `EPI-001` in M3. This records the resulting state change and checks nothing
    about the certificate, which is why `EPI-003` stays IN_PROGRESS.
    """
    if not policy.is_admission:
        raise BeliefTransitionRefused(
            f"{policy.policy_id}@{policy.version} is a transition policy, not an admission "
            "policy. §8's admission gate is a separate path, and backing an admission with a "
            "transition policy is how a dropped predecessor gets recorded as a beginning"
        )
    if not prior.is_empty:
        raise BeliefTransitionRefused(
            f"{hypothesis_id} already has recorded history (state "
            f"{prior.current_state.value if prior.current_state else 'unknown'}, last event "
            f"{prior.last_event_id}); admission happens once, and a second one would rewrite the "
            "beginning of a history that is supposed to be append-only"
        )
    if prior.project_id != project_id or prior.target_id != hypothesis_id:
        raise BeliefScopeError(
            f"the supplied projection is for {prior.target_id} in {prior.project_id}, not "
            f"{hypothesis_id} in {project_id}; an emptiness check against the wrong history "
            "proves nothing"
        )

    cross_project = sorted(
        {
            f"{kind}:{record.project_id}"
            for kind, records in (
                ("attestation", triggering_attestations),
                ("relation", triggering_relations),
            )
            for record in records
            if record.project_id != project_id
        }
    )
    if cross_project:
        raise BeliefTransitionRefused(
            f"the admission would cite evidence from outside {project_id}: "
            f"{', '.join(cross_project)}"
        )

    return AuthorizedRevision(
        event=BeliefRevisionEvent(
            event_id=event_id,
            project_id=project_id,
            target_type=BeliefTargetType.HYPOTHESIS,
            target_id=hypothesis_id,
            from_state=None,
            to_state=policy.candidate_to_state,
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
        ),
        origin="ADMISSION",
        _proof=_MINTED_HERE,
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
    "AuthorizedRevision",
    "BeliefProjection",
    "BeliefScopeError",
    "BeliefTransitionRefused",
    "SkipReason",
    "admit_hypothesis",
    "quarantined_by_extractor_version",
    "record_transition",
    "replay",
]
