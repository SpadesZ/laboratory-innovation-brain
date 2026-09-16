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
from lab_brain.core.repositories import SqlTransitionPolicyStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import ReviewStoreError, SqlReviewItemStore
from tests.conftest_fixtures import make_artifact
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
    # The event a review resolution will cite. A genesis event, so it needs no §17.14.1
    # authorization -- this module is about the authority loop, and dragging `v3.3-a12`'s
    # machinery in would make every failure here ambiguous between two slices.
    db.execute(
        "SELECT belief_revision_event_append('bre:resolution', %s, 'HYPOTHESIS', %s, NULL,"
        " 'ACTIVE', %s, ARRAY[]::text[], 'pol:genesis', '1.0.0', NULL, NULL, NULL, %s, %s, NULL)",
        (PROJECT, HYP, ["att:1"], T0, TRACE),
    )
    policies = SqlTransitionPolicyStore(db)
    policies.register(PROMOTE)
    policies.register(REJECT)
    return db


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


def test_resolving_the_review_closes_the_conflict_against_a_real_event(world):
    """Steps seven and eight: the resolution is an event, and the conflict closes against it."""
    _escalate(world, _evaluate())
    conflicts = SqlConflictStore(world)

    closed = conflicts.resolve(
        project_id=PROJECT,
        conflict_id="cfl:authority",
        resolution_event_id="bre:resolution",
        resolved_at=T0 + dt.timedelta(hours=1),
    )
    assert closed.resolution_status is ConflictResolutionStatus.RESOLVED
    assert closed.resolution_event_id == "bre:resolution"
    assert not closed.blocks_transitions
    assert conflicts.unresolved_for_subject(PROJECT, HYP) == ()


def test_only_after_the_closure_may_the_transition_be_reconsidered(world):
    """Step nine, and the whole point of the loop.

    Reconsidered, **not** allowed. The conflict no longer blocks, and the authority comparison is
    still INCOMPARABLE -- so the decision escalates again rather than passing. That is correct:
    closing the conflict records that a human looked, not that the evidence became rankable. A
    loop that returned ALLOW here would mean resolving a review promotes a belief whose authority
    question is unchanged.
    """
    _escalate(world, _evaluate())
    conflicts = SqlConflictStore(world)
    conflicts.resolve(
        project_id=PROJECT,
        conflict_id="cfl:authority",
        resolution_event_id="bre:resolution",
        resolved_at=T0 + dt.timedelta(hours=1),
    )

    reconsidered = _evaluate(conflicts=conflicts.unresolved_for_subject(PROJECT, HYP))
    assert reconsidered.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE, (
        "the block lifted; the authority question did not change"
    )
    assert reconsidered.blocking_conflict_ids == ()

    # And with a comparator that *can* rank the evidence, the same transition now passes -- so the
    # block really was the only thing in the way.
    from lab_brain.core.models import IndependenceSummary
    from tests.toy_authority import ToyAuthorityPolicyV2

    allowed = PROMOTE.evaluate(
        _view(),
        (_supporting(),),
        ToyAuthorityPolicyV2(),
        (),
        IndependenceSummary(independent_count=2),
        BeliefState.SUPPORTED,
    )
    assert allowed.outcome is TransitionOutcome.ALLOW


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
    SqlConflictStore(world).resolve(
        project_id=PROJECT,
        conflict_id="cfl:authority",
        resolution_event_id="bre:resolution",
        resolved_at=T0,
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
