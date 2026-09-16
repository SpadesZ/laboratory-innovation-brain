"""EPI-004: INCOMPARABLE authority blocks a belief until a human review resolves it.

    §8.2.1  If any required AuthorityPolicy.compare() result is INCOMPARABLE:
              -> outcome = NEED_HUMAN_REVIEW
              -> auto-create ReviewItem(subject_type=AUTHORITY_CONFLICT, ...)
              -> no BeliefRevisionEvent may promote/reject until the review resolves

    §26     T-EPI-004: required INCOMPARABLE returns NEED_HUMAN_REVIEW, auto-creates
            ReviewItem(AUTHORITY_CONFLICT), and blocks belief promotion/rejection.

THE WHOLE LOOP, IN ORDER, THROUGH THE REAL STORES:

    INCOMPARABLE comparison
      -> TransitionDecision(NEED_HUMAN_REVIEW, AUTHORITY_INCOMPARABLE)
      -> typed Conflict(AUTHORITY_CONFLICT, blocking=True)
      -> persisted ReviewItem(subject_type=AUTHORITY_CONFLICT, subject_id=conflict_id)
      -> conflict.review_id linked, atomically
      -> the unresolved conflict reaches the next HypothesisView
      -> promotion AND rejection stay blocked
      -> the review resolution produces a belief revision event
      -> the conflict closes against that event
      -> only then may the transition be reconsidered

The last two steps are the ones a plausible implementation gets wrong. Raising the review feels
like progress, so it is tempting to treat escalation as having handled the problem -- §8.2.1 says
the *resolution* lifts the block, and a conflict UNDER_REVIEW still blocks.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterator

import psycopg
import pytest

from lab_brain.core.escalation import (
    EscalationRefused,
    authority_conflict_for,
    review_item_for,
)
from lab_brain.core.models import (
    BeliefState,
    HypothesisView,
    RelationJudgment,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)
from lab_brain.core.models.conflict import ConflictResolutionStatus, ConflictType
from lab_brain.core.models.review import ReviewStatus, ReviewSubjectType
from lab_brain.core.models.review_resolution import ReviewOutcome, ReviewResolution
from lab_brain.core.repositories import SqlTransitionPolicyStore
from lab_brain.core.repositories.conflicts import ConflictStoreError, SqlConflictStore
from lab_brain.core.repositories.reviews import ReviewStoreError, SqlReviewItemStore
from tests.conftest_fixtures import make_artifact
from tests.postgres_fixtures import DEFAULT_URL
from tests.toy_authority import ToyAuthorityPolicy

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-004"),
    pytest.mark.spec_test("T-EPI-004"),
]

T0 = dt.datetime(2026, 9, 16, 11, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:authority-1"

#: Requires `TIER_A`. The hypothesis below carries `SIDEBAND`, which the toy comparator cannot
#: rank against it -- the INCOMPARABLE case, not a shortfall.
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    required_authority_rule="TIER_A",
    blocking_conflict_policy=("AUTHORITY_CONFLICT",),
)
REJECT = PROMOTE.model_copy(
    update={"policy_id": "pol:reject", "candidate_to_state": BeliefState.CONTRADICTED}
)


def _queue_policy(db, project_id: str, policy_id: str = "rqp:test") -> None:  # type: ignore[no-untyped-def]
    """Register the §14.4 SLA/expiry policy every escalation is priced from since `011e`.

    Not optional and not a convenience: `authority_conflict_escalate` refuses a project with no
    active queue policy, because an item with no deadline is the state §14.4 exists to forbid.
    """
    from lab_brain.core.repositories.reviews import SqlReviewQueuePolicyStore
    from lab_brain.core.review_queue import ReviewQueuePolicy

    SqlReviewQueuePolicyStore(db).register(
        ReviewQueuePolicy(
            policy_id=policy_id,
            version="1.0.0",
            project_id=project_id,
            capacity=16,
            default_sla_minutes=24 * 60,
            default_expiry_minutes=72 * 60,
            reviewer_minutes_per_day=240,
            effective_from=T0,
        )
    )


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """One attestation, one genesis event a closure may cite, and the two policies registered."""
    artifact = make_artifact(b"an authority review fixture")
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, uri, media_type, source_origin,"
        " lineage_id, lineage_revision) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            artifact.artifact_id,
            artifact.content_hash,
            artifact.uri,
            artifact.media_type,
            artifact.source_origin.value,
            artifact.lineage_id,
            artifact.lineage_revision,
        ),
    )
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'rs')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0', %s::jsonb, '1.0.0')",
        ('{"type": "object", "properties": {}}',),
    )
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance) VALUES ('att:1', 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb,"
        " 'core/sch_test@1.0.0', %s, '1.0.0', %s::jsonb)",
        (
            artifact.artifact_id,
            PROJECT,
            '{"extractor_id": "ext:t", "extractor_version": "1.0.0"}',
        ),
    )
    db.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state,"
        " is_admission) VALUES ('pol:genesis', '1.0.0', 'DRAFT', 'ACTIVE', TRUE)"
    )
    # NO PRE-CREATED RESOLUTION EVENT. P11's fixture built `bre:resolution` here, before any
    # escalation, and its tests passed that unrelated event to `conflict_close` as proof that a
    # review had resolved -- while the review sat at QUEUED. Every event a closure cites is now
    # created by `_event_from_review`, after the escalation, and recorded as that review's
    # product.
    _queue_policy(db, PROJECT)
    policies = SqlTransitionPolicyStore(db)
    policies.register(PROMOTE)
    policies.register(REJECT)
    return db


@pytest.fixture
def uncommitted(world) -> Iterator[psycopg.Connection]:  # type: ignore[no-untyped-def]
    """A transactional session, for the two tests that need a review to be terminal *mid-flight*.

    `conflict_close`'s traceability branch can only be reached by a caller whose review has already
    resolved -- and once `011d` enforces the pair at COMMIT, that state exists only inside an
    unfinished transaction. Which is correct, and is how the supported path reaches it too: the
    review is terminalized before the conflict is closed. See the section header below for what
    these tests used to do instead.
    """
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), connect_timeout=5
    )
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _resolve_mid_transaction(cursor, review_id: str, resolution_id: str, event_id: str) -> None:
    """Terminalize a review against a genuine resolution, without closing its conflict yet."""
    cursor.execute(
        "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
        " resolved_by_actor_id, resolved_at, rationale, belief_revision_event_id)"
        " VALUES (%s, %s, %s, 'APPROVED', 'act:test', %s, 'the reviewer decided', %s)",
        (resolution_id, review_id, PROJECT, T0, event_id),
    )
    cursor.execute(
        "UPDATE review_items SET status = 'APPROVED', decision_ref = %s WHERE review_id = %s",
        (resolution_id, review_id),
    )


def _supporting() -> RelationJudgment:
    return RelationJudgment(
        relation_id="rel:1",
        from_entity_id="att:1",
        to_entity_id=HYP,
        relation_type=RelationType.SUPPORTS,
        project_id=PROJECT,
        supporting_attestation_ids=("att:1",),
    )


def _view(conflicts=()):  # type: ignore[no-untyped-def]
    """A hypothesis whose admitted evidence carries an unrankable authority class."""
    return HypothesisView(
        hypothesis_id=HYP,
        project_id=PROJECT,
        current_state=BeliefState.ACTIVE,
        stakes="HIGH",
        admitted_authority_classes=("SIDEBAND",),
        conflicts=tuple(conflicts),
    )


def _evaluate(policy=PROMOTE, conflicts=()):  # type: ignore[no-untyped-def]
    from lab_brain.core.models import IndependenceSummary

    return policy.evaluate(
        _view(conflicts),
        (_supporting(),),
        ToyAuthorityPolicy(),
        (),
        IndependenceSummary(independent_count=2),
        policy.candidate_to_state,
    )


def _escalate(world, decision):  # type: ignore[no-untyped-def]
    """Create the conflict and its review, and link them. Returns both, as stored."""
    conflict = authority_conflict_for(
        conflict_id="cfl:authority",
        decision=decision,
        hypothesis=_view(),
        detected_at=T0,
        detected_by_actor_or_slot="act:test",
        trace_id=TRACE,
        supporting_refs=("att:1",),
    )
    SqlConflictStore(world).record(conflict)
    review = SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=conflict,
        review=review_item_for(
            review_id="rvw:authority-1",
            conflict=conflict,
            decision=decision,
            created_at=T0,
            estimated_human_minutes=30,
        ),
    )
    stored_conflict = SqlConflictStore(world).get(PROJECT, "cfl:authority")
    assert stored_conflict is not None
    return stored_conflict, review


# --------------------------------------------------------------------------------------------
# §26's T-EPI-004 says the ReviewItem is **auto**-created, and until M0b closure nothing in this
# module proved the "auto": every test above calls `_escalate` by hand. `core.escalation` built the
# objects and a human test invoked it, which is the seam existing and not the automation.
#
# The test below calls no escalation function. It runs the episode, and the Conflict and the
# ReviewItem appear because an INCOMPARABLE comparison happened.
# --------------------------------------------------------------------------------------------


def test_the_review_item_is_created_automatically_by_the_episode(world):
    """T-EPI-004's "auto-creates ReviewItem(AUTHORITY_CONFLICT)", with nobody creating one.

    `BeliefEpisode.attempt_transition` is handed a hypothesis, a policy and a comparator. It is not
    handed a conflict, a review, or any instruction to escalate. What makes them exist is the
    comparator returning INCOMPARABLE at a required gate -- which is the sentence §8.2.1 writes.
    """
    from lab_brain.core.authority import AuthorityPolicyRegistry
    from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
    from lab_brain.core.episode import BeliefEpisode
    from lab_brain.core.repositories import (
        SqlAttestationStore,
        SqlBeliefEventStore,
        SqlRelationStore,
    )
    from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore

    world.execute(
        "UPDATE attestations SET authority_class = 'SIDEBAND' WHERE attestation_id = 'att:1'"
    )
    SqlRelationStore(world).add(
        RelationJudgment(
            relation_id="rel:1",
            from_entity_id="att:1",
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            project_id=PROJECT,
            supporting_attestation_ids=("att:1",),
            valid_from=T0,
            created_at=T0,
        )
    )
    SqlBeliefEventStore(world).append(
        admit_hypothesis(
            event_id="bre:genesis",
            policy=TransitionPolicy(
                policy_id="pol:genesis",
                version="1.0.0",
                from_state=BeliefState.DRAFT,
                candidate_to_state=BeliefState.ACTIVE,
                is_admission=True,
            ),
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=EpistemicStateProjection(
                project_id=PROJECT, target_id=HYP, current_state=None, last_event_id=None
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(SqlAttestationStore(world).get(PROJECT, "att:1"),),  # type: ignore[arg-type]
        )
    )

    registry = AuthorityPolicyRegistry()
    registry.register(ToyAuthorityPolicy())

    class _Ids:
        def decision_id(self) -> str:
            return "dec:auto"

        def event_id(self) -> str:
            return "bre:auto"

        def conflict_id(self) -> str:
            return "cfl:auto"

        def review_id(self) -> str:
            return "rvw:auto"

    assert world.execute("SELECT count(*) FROM review_items").fetchone()[0] == 0

    result = BeliefEpisode(
        policies=SqlTransitionPolicyStore(world),
        decisions=SqlBeliefTransitionDecisionStore(world),
        events=SqlBeliefEventStore(world),
        relations=SqlRelationStore(world),
        authority_classes=SqlAttestationStore(world),
        conflicts=SqlConflictStore(world),
        reviews=SqlReviewItemStore(world),
        ids=_Ids(),
        authority_policies=registry.as_mapping(),
    ).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
        authority_policy_ref=(ToyAuthorityPolicy().policy_id, ToyAuthorityPolicy().policy_version),
    )

    assert result.decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert result.decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE

    queued = SqlReviewItemStore(world).for_subject(PROJECT, "cfl:auto")
    assert [item.review_id for item in queued] == ["rvw:auto"], (
        "the ReviewItem must exist without anyone having asked for one"
    )
    assert queued[0].subject_type is ReviewSubjectType.AUTHORITY_CONFLICT
    assert queued[0].status is ReviewStatus.QUEUED
    assert queued[0].required_authority == "TIER_A"

    conflict = SqlConflictStore(world).get(PROJECT, "cfl:auto")
    assert conflict is not None
    assert conflict.review_id == "rvw:auto", "and it must be linked"
    assert conflict.blocks_transitions

    # And no belief moved: §8.2.1 blocks promotion and rejection until the review resolves.
    assert not result.transitioned
    assert [e.event_id for e in SqlBeliefEventStore(world).history(PROJECT, HYP)] == ["bre:genesis"]


# --------------------------------------------------------------------------------------------
# The loop.
# --------------------------------------------------------------------------------------------


def test_incomparable_authority_escalates_and_creates_a_linked_review(world):
    """Steps one to four: decision, conflict, persisted review, atomic link."""
    decision = _evaluate()
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE

    conflict, review = _escalate(world, decision)

    assert conflict.conflict_type is ConflictType.AUTHORITY_CONFLICT
    assert conflict.blocking is True
    assert conflict.subject_refs == (HYP,), "the hypothesis is one hop from the review"
    assert conflict.review_id == "rvw:authority-1"
    assert conflict.resolution_status is ConflictResolutionStatus.UNDER_REVIEW

    assert review.subject_type is ReviewSubjectType.AUTHORITY_CONFLICT
    assert review.subject_id == "cfl:authority", "§17.19.3: the subject is a conflict_id"
    assert review.status is ReviewStatus.QUEUED
    assert review.is_outstanding
    assert review.stakes == "HIGH", "carried from the decision, not re-derived by the caller"
    assert review.required_authority == "TIER_A", "the reviewer is told which threshold failed"


def test_the_escalated_conflict_reaches_the_next_hypothesis_view_and_still_blocks(world):
    """Step five and six, and the step a plausible implementation skips.

    Raising the review reads as progress. §8.2.1 says the *resolution* lifts the block, so a
    conflict UNDER_REVIEW must still stop the transition -- and it must do so having come back out
    of the database, not from the object the escalation happened to return.
    """
    conflict, _ = _escalate(world, _evaluate())

    unresolved = SqlConflictStore(world).unresolved_for_subject(PROJECT, HYP)
    assert [c.conflict_id for c in unresolved] == ["cfl:authority"]
    assert conflict.blocks_transitions

    blocked = _evaluate(conflicts=unresolved)
    assert blocked.outcome is not TransitionOutcome.ALLOW
    assert blocked.blocking_conflict_ids == ("cfl:authority",)


@pytest.mark.parametrize("policy", [PROMOTE, REJECT], ids=["promotion", "rejection"])
def test_both_promotion_and_rejection_stay_blocked(world, policy):
    """ "no BeliefRevisionEvent may promote/reject" is two obligations, and one is easy to miss.

    A gate that blocked promotions and let rejections through would satisfy the sentence as it is
    usually read while violating what it says -- and rejecting a hypothesis on authority nobody
    could rank is the same error as promoting one.
    """
    _escalate(world, _evaluate())
    unresolved = SqlConflictStore(world).unresolved_for_subject(PROJECT, HYP)

    decision = _evaluate(policy=policy, conflicts=unresolved)
    assert decision.outcome is not TransitionOutcome.ALLOW
    assert not decision.permits_transition


# --------------------------------------------------------------------------------------------
# The escalation refuses what it should.
# --------------------------------------------------------------------------------------------


def test_a_conflict_cannot_be_manufactured_from_a_decision_that_did_not_escalate(world):
    """A conflict built from a DENY would block a hypothesis whose question was answered."""
    from lab_brain.core.models import IndependenceSummary

    denied = PROMOTE.evaluate(
        HypothesisView(
            hypothesis_id=HYP,
            project_id=PROJECT,
            current_state=BeliefState.ACTIVE,
            admitted_authority_classes=("TIER_B",),
        ),
        (_supporting(),),
        ToyAuthorityPolicy(),
        (),
        IndependenceSummary(independent_count=2),
        BeliefState.SUPPORTED,
    )
    assert denied.outcome is TransitionOutcome.DENY

    with pytest.raises(EscalationRefused, match="not NEED_HUMAN_REVIEW"):
        authority_conflict_for(
            conflict_id="cfl:x",
            decision=denied,
            hypothesis=_view(),
            detected_at=T0,
            detected_by_actor_or_slot="act:test",
            trace_id=TRACE,
        )


def test_a_conflict_cannot_be_manufactured_from_a_different_escalation_reason(world):
    """§17.19.3's vocabulary is closed, and a mistyped conflict gates on the wrong condition."""
    from lab_brain.core.models import IndependenceSummary
    from tests.contract.test_transition_policy import conflict as typed_conflict

    # No authority rule, and SIM_TO_REAL_CONFLICT declared blocking -- so the escalation reason
    # is BLOCKING_CONFLICT rather than AUTHORITY_INCOMPARABLE, which is the case under test. The
    # first version of this left `blocking_conflict_policy` as PROMOTE's AUTHORITY_CONFLICT while
    # supplying a SIM_TO_REAL conflict, so nothing matched and the policy correctly said ALLOW.
    blocked = PROMOTE.model_copy(
        update={
            "required_authority_rule": None,
            "blocking_conflict_policy": ("SIM_TO_REAL_CONFLICT",),
        }
    ).evaluate(
        HypothesisView(
            hypothesis_id=HYP,
            project_id=PROJECT,
            current_state=BeliefState.ACTIVE,
            conflicts=(typed_conflict(project_id=PROJECT),),
        ),
        (_supporting(),),
        None,
        (),
        IndependenceSummary(independent_count=2),
        BeliefState.SUPPORTED,
    )
    assert blocked.reason_code is TransitionReason.BLOCKING_CONFLICT

    with pytest.raises(EscalationRefused, match="not AUTHORITY_INCOMPARABLE"):
        authority_conflict_for(
            conflict_id="cfl:x",
            decision=blocked,
            hypothesis=_view(),
            detected_at=T0,
            detected_by_actor_or_slot="act:test",
            trace_id=TRACE,
        )


def test_a_review_whose_subject_is_not_its_conflict_is_refused(world):
    """A mismatch would queue a review that cannot clear the block it was raised for."""
    decision = _evaluate()
    conflict = authority_conflict_for(
        conflict_id="cfl:authority",
        decision=decision,
        hypothesis=_view(),
        detected_at=T0,
        detected_by_actor_or_slot="act:test",
        trace_id=TRACE,
    )
    SqlConflictStore(world).record(conflict)

    wrong = review_item_for(
        review_id="rvw:1", conflict=conflict, decision=decision, created_at=T0
    ).model_copy(update={"subject_id": "cfl:something-else"})

    with pytest.raises(ReviewStoreError, match="names subject"):
        SqlReviewItemStore(world).escalate_authority_conflict(conflict=conflict, review=wrong)


def test_a_review_cannot_name_a_conflict_that_does_not_exist(world):
    """Enforced by the database, since the store is not the only writer.

    A review pointing at nothing would sit in the queue describing a block nobody can find.
    """
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="not a conflict in"):
        world.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
            " reason, trace_id, created_at) VALUES ('rvw:ghost', %s, 'AUTHORITY_CONFLICT',"
            " 'cfl:nonexistent', 'HIGH', 'AUTHORITY_INCOMPARABLE', %s, %s)",
            (PROJECT, TRACE, T0),
        )


def test_escalating_an_already_closed_conflict_is_refused(world):
    """Queueing human work to lift a block that is already gone.

    The reviewer would have no way to tell, which is why this fails rather than succeeding
    harmlessly.
    """
    decision = _evaluate()
    conflict, _ = _escalate(world, decision)
    # Closed the supported way, through the review's own resolution. The previous version reached
    # this state by passing a pre-created unrelated event, which is the bug this slice removed.
    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=_resolution(event_id=_event_from_review(world)),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    with pytest.raises(ReviewStoreError):
        SqlReviewItemStore(world).escalate_authority_conflict(
            conflict=conflict,
            review=review_item_for(
                review_id="rvw:second",
                conflict=conflict,
                decision=decision,
                created_at=T0,
            ),
        )


def test_a_cross_project_escalation_is_unrepresentable(world):
    """Composite foreign key on `(review_id, project_id)`, both directions."""
    world.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other')"
        " ON CONFLICT DO NOTHING"
    )
    conflict, _ = _escalate(world, _evaluate())

    import psycopg

    with pytest.raises((psycopg.errors.RaiseException, psycopg.errors.ForeignKeyViolation)):
        world.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
            " reason, trace_id, created_at) VALUES ('rvw:foreign', 'prj:other',"
            " 'AUTHORITY_CONFLICT', %s, 'HIGH', 'AUTHORITY_INCOMPARABLE', %s, %s)",
            (conflict.conflict_id, TRACE, T0),
        )


# --------------------------------------------------------------------------------------------
# `v3.3-a14`: the review has to actually resolve. This is the section the P11 audit's P0 was
# about, and the section P11 did not have.
#
# WHAT P11 DID. Its fixture pre-created `bre:resolution` before any escalation, left the
# ReviewItem at `QUEUED`, and passed that unrelated event to `conflict_close` as the closure
# proof. `conflict_close` never consulted the review, so it worked -- and the test was named
# `test_resolving_the_review_closes_the_conflict_against_a_real_event` while never touching the
# review. Those tests are gone. Every closure below goes through a real resolution.
# --------------------------------------------------------------------------------------------


def _resolution(
    *,
    resolution_id: str = "res:1",
    review_id: str = "rvw:authority-1",
    outcome: ReviewOutcome = ReviewOutcome.APPROVED,
    event_id: str = "bre:from-review",
    rationale: str = "the calibrated range was confirmed to cover the operating point",
) -> ReviewResolution:
    return ReviewResolution(
        resolution_id=resolution_id,
        review_id=review_id,
        project_id=PROJECT,
        outcome=outcome,
        resolved_by_actor_id="act:test",
        resolved_at=T0 + dt.timedelta(hours=1),
        rationale=rationale,
        belief_revision_event_id=event_id,
    )


def _event_from_review(world, event_id: str = "bre:from-review") -> str:  # type: ignore[no-untyped-def]
    """The belief revision event a review's resolution produces.

    Written *after* the escalation, which is the whole point: in P11 this existed before the
    review did, which is how an unrelated event could stand in for a resolution.
    """
    world.execute(
        "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, NULL, 'ACTIVE',"
        " %s, ARRAY[]::text[], 'pol:genesis', '1.0.0', NULL, NULL, NULL, %s, %s, NULL)",
        (event_id, PROJECT, f"hyp:{event_id}", ["att:1"], T0, TRACE),
    )
    return event_id


def test_a_queued_review_will_not_let_its_conflict_close(world):
    """The P0, stated at its simplest. Nobody has answered, so the block stays."""
    _escalate(world, _evaluate())
    _event_from_review(world)

    with pytest.raises(ConflictStoreError, match="still QUEUED"):
        SqlConflictStore(world).resolve(
            project_id=PROJECT,
            conflict_id="cfl:authority",
            resolution_event_id="bre:from-review",
            resolved_at=T0,
        )
    assert SqlConflictStore(world).get(PROJECT, "cfl:authority").blocks_transitions  # type: ignore[union-attr]


def test_an_assigned_review_will_not_let_its_conflict_close_either(world):
    """`ASSIGNED` is somebody having picked the task up, not somebody having decided.

    Worth its own case because "someone is on it" is the state most likely to be read as handled.
    """
    _escalate(world, _evaluate())
    _event_from_review(world)
    world.execute(
        "UPDATE review_items SET status = 'ASSIGNED', assigned_actor_id = 'act:test'"
        " WHERE review_id = 'rvw:authority-1'"
    )

    with pytest.raises(ConflictStoreError, match="still ASSIGNED"):
        SqlConflictStore(world).resolve(
            project_id=PROJECT,
            conflict_id="cfl:authority",
            resolution_event_id="bre:from-review",
            resolved_at=T0,
        )


# THESE TWO TESTS USED TO COMMIT A STATE THE SPEC FORBIDS, AS SETUP. Both needed a review that
# had genuinely resolved so `conflict_close` would reach its traceability branch, and both got
# there by committing `status='APPROVED', decision_ref=...` while the conflict sat at
# UNDER_REVIEW -- which is P0-A, the exact half-state `v3.3-a14` forbids. They passed because
# nothing enforced the pair; `011d` enforces it at COMMIT, and a test may not depend on a
# spec-invalid committed state to reach its assertion.
#
# The rewrite keeps the review's resolution completely genuine and simply never commits it: the
# terminal review lives inside an unfinished transaction, which is where the supported path puts
# it too. `conflict_close` raises on the substituted event before COMMIT is ever attempted, so the
# assertion is stronger than before -- the old version proved the substitution was refused from a
# state the database should not have allowed to exist.


def test_an_unrelated_same_project_event_is_not_closure_proof(world, uncommitted):
    """Exactly the substitution P11 made, now refused.

    The review really is resolved and the event really does exist in this project -- it is simply
    not the event this review's resolution produced.
    """
    _escalate(world, _evaluate())
    produced = _event_from_review(world)
    unrelated = _event_from_review(world, "bre:unrelated")

    with uncommitted.cursor() as cursor:
        _resolve_mid_transaction(cursor, "rvw:authority-1", "res:1", produced)
        with pytest.raises(
            psycopg.errors.RaiseException, match="is not proof that this review resolved"
        ):
            cursor.execute(
                "SELECT conflict_close('cfl:authority', %s, 'RESOLVED', %s, %s)",
                (PROJECT, unrelated, T0),
            )
    uncommitted.rollback()

    assert SqlConflictStore(world).get(PROJECT, "cfl:authority").blocks_transitions  # type: ignore[union-attr]
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:authority-1").is_outstanding  # type: ignore[union-attr]


def test_another_reviews_resolution_event_is_not_closure_proof(world, uncommitted):
    """Two conflicts, two reviews, and the second closed against the first's event.

    The first conflict resolves through the supported path and stays resolved, so the event being
    substituted is not merely unrelated -- it is a real resolution event, belonging to a real
    review, which simply did not resolve *this* one.
    """
    first, _ = _escalate(world, _evaluate())
    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=_resolution(event_id=_event_from_review(world)),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )
    assert first.conflict_id == "cfl:authority"

    other = authority_conflict_for(
        conflict_id="cfl:other",
        decision=_evaluate(),
        hypothesis=_view(),
        detected_at=T0,
        detected_by_actor_or_slot="act:test",
        trace_id=TRACE,
    )
    SqlConflictStore(world).record(other)
    SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=other,
        review=review_item_for(
            review_id="rvw:other", conflict=other, decision=_evaluate(), created_at=T0
        ),
    )
    own_event = _event_from_review(world, "bre:other")

    with uncommitted.cursor() as cursor:
        _resolve_mid_transaction(cursor, "rvw:other", "res:other", own_event)
        with pytest.raises(
            psycopg.errors.RaiseException, match="is not proof that this review resolved"
        ):
            cursor.execute(
                "SELECT conflict_close('cfl:other', %s, 'RESOLVED', %s, %s)",
                (PROJECT, "bre:from-review", T0),
            )
    uncommitted.rollback()

    assert SqlConflictStore(world).get(PROJECT, "cfl:other").blocks_transitions  # type: ignore[union-attr]


def test_a_terminal_review_with_no_decision_ref_is_refused(world):
    """§17.19.1 as amended: a terminal review must record how it was resolved.

    Refused by the database, because the store is not the only writer -- and this is the state a
    support script marking a queue "done" would create.
    """
    _escalate(world, _evaluate())

    with pytest.raises(psycopg.errors.RaiseException, match="with no decision_ref"):
        world.execute(
            "UPDATE review_items SET status = 'APPROVED' WHERE review_id = 'rvw:authority-1'"
        )


def test_an_outstanding_review_may_not_carry_a_decision_ref(world):
    """The other direction: an outstanding review must not look answered."""
    _escalate(world, _evaluate())
    world.execute(
        "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
        " resolved_by_actor_id, resolved_at, rationale, belief_revision_event_id)"
        " VALUES ('res:premature', 'rvw:authority-1', %s, 'APPROVED', 'act:test', %s, 'r', %s)",
        (PROJECT, T0, _event_from_review(world)),
    )

    with pytest.raises(psycopg.errors.RaiseException, match="must not look"):
        world.execute(
            "UPDATE review_items SET decision_ref = 'res:premature'"
            " WHERE review_id = 'rvw:authority-1'"
        )


def test_a_cross_project_resolution_is_unrepresentable(world):
    """Composite foreign keys on both the review and the event it produced."""
    world.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other')"
        " ON CONFLICT DO NOTHING"
    )
    _escalate(world, _evaluate())

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        world.execute(
            "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
            " resolved_by_actor_id, resolved_at, rationale, belief_revision_event_id)"
            " VALUES ('res:foreign', 'rvw:authority-1', 'prj:other', 'APPROVED', 'act:test',"
            " %s, 'r', %s)",
            (T0, _event_from_review(world)),
        )


def test_a_resolution_must_name_the_event_it_produced(world):
    """Required for every outcome, with no per-status exemption.

    The first draft of this slice made the event optional, reasoning that a REJECTED review might
    settle nothing. This test was written against that draft, tried to close a conflict as
    ACCEPTED_AS_OPEN_QUESTION with no event, and the database refused -- correctly, because the
    P10 ruling is that every status which stops a conflict blocking carries its closure event.
    A per-status exemption is exactly how the terminal-state hole appeared, so the rule is uniform
    and the model is what changed.
    """
    with pytest.raises(ValueError, match="belief_revision_event_id"):
        ReviewResolution(
            resolution_id="res:eventless",
            review_id="rvw:authority-1",
            project_id=PROJECT,
            outcome=ReviewOutcome.REJECTED,
            resolved_by_actor_id="act:test",
            resolved_at=T0,
            rationale="no",
        )  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("outcome", "conflict_status"),
    [
        (ReviewOutcome.APPROVED, ConflictResolutionStatus.RESOLVED),
        (ReviewOutcome.CORRECTED, ConflictResolutionStatus.RESOLVED),
        (ReviewOutcome.REJECTED, ConflictResolutionStatus.ACCEPTED_AS_OPEN_QUESTION),
        (ReviewOutcome.EXPIRED, ConflictResolutionStatus.EXPIRED),
    ],
)
def test_every_review_outcome_closes_its_conflict_against_its_own_event(
    world, outcome, conflict_status
):
    """All four outcomes, each with the conflict status it honestly implies.

    `REJECTED` closing as ACCEPTED_AS_OPEN_QUESTION is §17.19.3's honest third option: the
    disagreement is real, nobody is resolving it now, and the record says so -- and it still needs
    the event, because proceeding with the conflict on the record is itself a decision.
    """
    _escalate(world, _evaluate())
    produced = _event_from_review(world)

    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=_resolution(outcome=outcome, event_id=produced),
        conflict_status=conflict_status,
    )

    closed = SqlConflictStore(world).get(PROJECT, "cfl:authority")
    assert closed is not None
    assert closed.resolution_status is conflict_status
    assert closed.resolution_event_id == produced
    assert not closed.blocks_transitions

    review = SqlReviewItemStore(world).get(PROJECT, "rvw:authority-1")
    assert review is not None and not review.is_outstanding


def test_the_real_loop_resolves_the_review_and_closes_the_conflict_exactly_once(world):
    """The loop P11 claimed and did not have.

    The event is created *after* the escalation, recorded as this review's product, and is the
    only event the closure will accept. Then the second attempt loses.
    """
    _escalate(world, _evaluate())
    produced = _event_from_review(world)

    store = SqlReviewItemStore(world)
    store.resolve_and_close_conflict(
        resolution=_resolution(event_id=produced),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    review = store.get(PROJECT, "rvw:authority-1")
    assert review is not None
    assert review.status is ReviewStatus.APPROVED
    assert not review.is_outstanding
    assert review.decision_ref == "res:1", "the terminal review records its resolution"

    resolution = store.resolution_for(PROJECT, "rvw:authority-1")
    assert resolution is not None
    assert resolution.belief_revision_event_id == produced
    assert resolution.settled_the_question

    closed = SqlConflictStore(world).get(PROJECT, "cfl:authority")
    assert closed is not None
    assert closed.resolution_status is ConflictResolutionStatus.RESOLVED
    assert closed.resolution_event_id == produced
    assert not closed.blocks_transitions

    # Exactly once. A second resolution must lose rather than overwrite the first decision.
    with pytest.raises(ReviewStoreError):
        store.resolve_and_close_conflict(
            resolution=_resolution(resolution_id="res:2", event_id=produced),
            conflict_status=ConflictResolutionStatus.RESOLVED,
        )
    assert store.resolution_for(PROJECT, "rvw:authority-1").resolution_id == "res:1"  # type: ignore[union-attr]


def test_a_failed_resolution_leaves_no_trace_of_itself(world):
    """`v3.3-a14`'s atomicity clause, demonstrated with a failure that is actually reachable.

    WHAT WRITING THIS FOUND. The first version tried to construct "review terminal, conflict still
    open" -- and it could not, because inside `review_resolve_and_close_conflict` the same
    `p_event_id` is passed to both the resolution insert and the close, so the traceability check
    can never disagree with itself, and the only other post-update failure is "conflict already
    closed", which requires a conflict closed while its review was outstanding -- forbidden. The
    half-state is unreachable by construction, which is a stronger guarantee than a test for it.

    So this tests the property that *is* reachable: a second resolution attempt is refused and
    leaves no trace. It is refused by `review_resolutions_one_per_review` rather than by the
    review-status check -- earlier and stronger than expected when this was written, and the right
    guard for it: two resolution rows for one review would be two accounts of what a human
    decided, and whichever was read first would decide a belief.
    """
    _escalate(world, _evaluate())
    produced = _event_from_review(world)
    store = SqlReviewItemStore(world)
    store.resolve_and_close_conflict(
        resolution=_resolution(event_id=produced),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    with pytest.raises(ReviewStoreError, match=r"one_per_review|not outstanding"):
        store.resolve_and_close_conflict(
            resolution=_resolution(resolution_id="res:second", event_id=produced),
            conflict_status=ConflictResolutionStatus.RESOLVED,
        )

    assert (
        world.execute(
            "SELECT count(*) FROM review_resolutions WHERE resolution_id = 'res:second'"
        ).fetchone()[0]
        == 0
    ), "the failed attempt must not leave a resolution row behind"
    assert store.resolution_for(PROJECT, "rvw:authority-1").resolution_id == "res:1"  # type: ignore[union-attr]

    # And the first decision is intact on both sides.
    review = store.get(PROJECT, "rvw:authority-1")
    conflict = SqlConflictStore(world).get(PROJECT, "cfl:authority")
    assert review is not None and conflict is not None
    assert review.decision_ref == "res:1"
    assert conflict.resolution_event_id == produced


def test_an_outstanding_review_never_coexists_with_a_closed_conflict(world):
    """The half-state `v3.3-a14` names, asserted as unreachable rather than as a failure mode.

    Every path that closes a conflict goes through `conflict_close`, which refuses while the
    linked review is outstanding -- so this scans for the pair directly and requires it to be
    empty after the one legitimate closure and one refused attempt.
    """
    _escalate(world, _evaluate())
    produced = _event_from_review(world)

    with pytest.raises(ConflictStoreError):
        SqlConflictStore(world).resolve(
            project_id=PROJECT,
            conflict_id="cfl:authority",
            resolution_event_id=produced,
            resolved_at=T0,
        )
    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=_resolution(event_id=produced),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    offending = world.execute(
        "SELECT c.conflict_id, r.status FROM conflicts c JOIN review_items r"
        "   ON r.review_id = c.review_id AND r.project_id = c.project_id"
        " WHERE r.status IN ('QUEUED', 'ASSIGNED')"
        "   AND c.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW')"
    ).fetchall()
    assert offending == [], f"outstanding review with a closed conflict: {offending}"


# --------------------------------------------------------------------------------------------
# Duplicate escalation. `011b` accepted an already-UNDER_REVIEW conflict and overwrote review_id.
# --------------------------------------------------------------------------------------------


def test_a_repeated_escalation_returns_the_existing_review(world):
    """A retried episode must not queue a second reviewer for the same block.

    Idempotent rather than loud, because the retry is legitimate: the caller wants the review id
    and there is one. What must not happen is a second row -- the first review would sit in the
    queue gating nothing while the block pointed elsewhere.
    """
    conflict, first = _escalate(world, _evaluate())
    assert conflict.resolution_status is ConflictResolutionStatus.UNDER_REVIEW

    again = SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=conflict,
        review=review_item_for(
            review_id="rvw:duplicate",
            conflict=conflict,
            decision=_evaluate(),
            created_at=T0 + dt.timedelta(minutes=5),
        ),
    )
    assert again.review_id == first.review_id == "rvw:authority-1"

    rows = world.execute(
        "SELECT count(*) FROM review_items WHERE subject_id = 'cfl:authority'"
    ).fetchone()
    assert rows[0] == 1, "exactly one review row, and it is the first"
    assert (
        world.execute(
            "SELECT count(*) FROM review_items WHERE review_id = 'rvw:duplicate'"
        ).fetchone()[0]
        == 0
    )


def test_a_conflicts_review_link_cannot_be_replaced(world):
    """Written once, from NULL. Raw SQL too, since the function is not the only writer.

    The usurper is fully priced -- policy, due_at and expires_at -- so `011e`'s deadline trigger is
    satisfied and the refusal under test is `011a`'s one-time link rather than a missing SLA.
    """
    _escalate(world, _evaluate())
    world.execute(
        "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
        " reason, trace_id, created_at, queue_policy_id, queue_policy_version, due_at, expires_at)"
        " VALUES ('rvw:usurper', %s, 'AUTHORITY_CONFLICT', 'cfl:authority', 'HIGH',"
        " 'AUTHORITY_INCOMPARABLE', %s, %s, 'rqp:test', '1.0.0', %s, %s)",
        (PROJECT, TRACE, T0, T0 + dt.timedelta(hours=24), T0 + dt.timedelta(hours=72)),
    )

    with pytest.raises(psycopg.errors.RaiseException, match="already gated by review"):
        world.execute(
            "UPDATE conflicts SET review_id = 'rvw:usurper' WHERE conflict_id = 'cfl:authority'"
        )
    assert SqlConflictStore(world).get(PROJECT, "cfl:authority").review_id == "rvw:authority-1"  # type: ignore[union-attr]


# --------------------------------------------------------------------------------------------
# Immutability, completed. `011a` left these two editable.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("supporting_refs", "ARRAY['att:something-else']"),
        ("episode_id", "'epi:rewritten'"),
        ("blocking", "FALSE"),
        ("subject_refs", "ARRAY['hyp:something-else']"),
        ("conflict_type", "'PROVENANCE_CONFLICT'"),
    ],
)
def test_scientific_provenance_cannot_be_rewritten_by_raw_sql(world, column, value):
    """`supporting_refs` and `episode_id` are the two `011a` left open.

    Both are scientific provenance -- the evidence the conflict rests on, and the episode that
    found it -- so rewriting either changes what the disagreement was rather than resolving it.
    """
    _escalate(world, _evaluate())

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        world.execute(
            f"UPDATE conflicts SET {column} = {value} WHERE conflict_id = 'cfl:authority'"
        )


def test_a_closed_conflict_cannot_be_reopened_or_rewritten(world):
    """Terminal rows are final. Reopening would give two accounts of why a belief unblocked."""
    _escalate(world, _evaluate())
    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=_resolution(event_id=_event_from_review(world)),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    for statement in (
        "UPDATE conflicts SET resolution_status = 'OPEN', resolved_at = NULL,"
        " resolution_event_id = NULL WHERE conflict_id = 'cfl:authority'",
        "UPDATE conflicts SET resolution_status = 'EXPIRED' WHERE conflict_id = 'cfl:authority'",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="already RESOLVED"):
            world.execute(statement)


def test_a_resolution_must_carry_a_substantive_rationale():
    """A required field satisfied by an empty string is an optional field with extra steps.

    Added because the mutation run caught it: removing this validator left the whole suite green,
    so the check existed and nothing held it. The rationale is the only account of why a human
    lifted a block, and a blank one makes the review unauditable while looking complete.
    """
    for blank in ("", "   ", "\n\t"):
        with pytest.raises(ValueError, match="no rationale"):
            ReviewResolution(
                resolution_id="res:blank",
                review_id="rvw:authority-1",
                project_id=PROJECT,
                outcome=ReviewOutcome.APPROVED,
                resolved_by_actor_id="act:test",
                resolved_at=T0,
                rationale=blank,
                belief_revision_event_id="bre:whatever",
            )
