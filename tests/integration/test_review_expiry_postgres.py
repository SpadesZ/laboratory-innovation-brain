"""T-OPS-002 liveness: an overdue review leaves PENDING, and no belief moves (`v3.3-a15`).

    §26  T-OPS-002 ... an item past its expiry leaves PENDING via the declared policy rather than
         parking there indefinitely (§14.4).

EVERY TEST HERE DRIVES `ReviewExpiryProcessor`, THE PRODUCTION CALLER -- never `ReviewQueue.expire`
and never `review_expire` by hand. That is the whole point of the M0b sign-off finding: the seam
was correct and nothing invoked it, so the obligation held for callers who called it, which is to
say for tests. A liveness proof that reaches past the caller proves the same nothing again.

THE CHAIN §17.19.1 DECLARES, ASSERTED LINK BY LINK:

    expired QUEUED|ASSIGNED ReviewItem
      -> GovernanceEvent(REVIEW_EXPIRY)          a governance fact, not a scientific one
      -> ReviewResolution(EXPIRED)               settled_the_question is False
      -> ReviewItem EXPIRED                      it has left PENDING
      -> Conflict ACCEPTED_AS_OPEN_QUESTION      closed for THIS instance only
      -> EpistemicStateProjection unchanged      no belief moved, no event was written

NO FABRICATED HYPOTHESIS ANYWHERE. The previous fixture wrote a genesis `BeliefRevisionEvent` for
`f"hyp:{event_id}"` -- a hypothesis that did not exist -- to satisfy the foreign key `011a` placed
on `resolution_event_id`. `011f` gives the expiry its own kind of event, so nothing here invents a
subject. `test_the_expiry_writes_no_belief_revision_event` counts the belief log to prove it.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import os
import threading
from collections.abc import Iterator

import psycopg
import pytest

from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.models import BeliefState, TransitionPolicy
from lab_brain.core.models.attestation import (
    Attestation,
    EpistemicType,
    ExtractionProvenance,
)
from lab_brain.core.models.conflict import (
    Conflict,
    ConflictResolutionStatus,
    ConflictType,
)
from lab_brain.core.models.governance_event import (
    GovernanceEventType,
    GovernanceSubjectType,
    ResolutionEventKind,
)
from lab_brain.core.models.review import ReviewItem, ReviewStatus, ReviewSubjectType
from lab_brain.core.models.review_resolution import ReviewOutcome, ReviewResolution
from lab_brain.core.repositories import SqlAttestationStore, SqlBeliefEventStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import (
    ReviewStoreError,
    SqlReviewItemStore,
    SqlReviewQueuePolicyStore,
)
from lab_brain.core.review_expiry import (
    DefaultExpiryIdSource,
    ExpiryRefused,
    ReviewExpiryProcessor,
    sweep_projects,
)
from lab_brain.core.review_queue import ReviewQueuePolicy
from tests.conftest_fixtures import make_artifact
from tests.postgres_fixtures import DEFAULT_URL

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("OPS-002"),
    pytest.mark.spec_test("T-OPS-002"),
]

T0 = dt.datetime(2026, 9, 19, 9, 0, tzinfo=dt.UTC)
#: Well past the 48h HIGH expiry below, so every sweep in this module is genuinely overdue.
LATER = T0 + dt.timedelta(days=5)
PROJECT = "prj:test"
OTHER = "prj:other"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:expiry"

#: The professor who declared the SLA. The standing authority for every automatic expiry below.
DECLARER = "act:test"
#: The process that executes the sweep. A SERVICE actor, and it does not thereby become a
#: scientific decision-maker (§17.19.1).
EXECUTOR = "act:sweeper"

POLICY = ReviewQueuePolicy(
    policy_id="rqp:lab",
    version="1.0.0",
    project_id=PROJECT,
    capacity=8,
    default_sla_minutes=24 * 60,
    default_expiry_minutes=72 * 60,
    sla_minutes_by_stakes={"HIGH": 4 * 60},
    expiry_minutes_by_stakes={"HIGH": 48 * 60},
    reviewer_minutes_per_day=120,
    declared_by_actor_id=DECLARER,
    effective_from=T0,
)

GENESIS = TransitionPolicy(
    policy_id="pol:genesis",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """A real admitted hypothesis, a queue policy, and a SERVICE actor to run the sweep."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name)"
        " VALUES (%s, 'SERVICE', 'Expiry sweeper') ON CONFLICT DO NOTHING",
        (EXECUTOR,),
    )
    artifact = make_artifact(b"an expiry fixture")
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
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state,"
        " is_admission) VALUES ('pol:genesis', '1.0.0', 'DRAFT', 'ACTIVE', TRUE)"
    )
    attestation = SqlAttestationStore(db).add(
        Attestation(
            attestation_id="att:1",
            claim_id="clm:1",
            epistemic_type=EpistemicType.REPORTED,
            source_artifact_id=artifact.artifact_id,
            locator="p.1",
            conditions_schema_version="core/sch_test@1.0.0",
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="ext:t", extractor_version="1.0.0"
            ),
        )
    )
    # A REAL hypothesis, admitted through the real gate. Nothing in this module fabricates one.
    SqlBeliefEventStore(db).append(
        admit_hypothesis(
            event_id="bre:genesis",
            policy=GENESIS,
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=EpistemicStateProjection(
                project_id=PROJECT, target_id=HYP, current_state=None, last_event_id=None
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(attestation,),
        )
    )
    SqlReviewQueuePolicyStore(db).register(POLICY)
    return db


@pytest.fixture
def second(db) -> Iterator[psycopg.Connection]:  # type: ignore[no-untyped-def]
    """A genuinely separate autocommit session, so the expiry race is a race."""
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), autocommit=True, connect_timeout=5
    )
    try:
        yield connection
    finally:
        connection.close()


def _escalate(world, review_id: str, conflict_id: str, stakes: str = "HIGH") -> ReviewItem:  # type: ignore[no-untyped-def]
    SqlConflictStore(world).record(
        Conflict(
            conflict_id=conflict_id,
            project_id=PROJECT,
            conflict_type=ConflictType.AUTHORITY_CONFLICT,
            subject_refs=(HYP,),
            blocking=True,
            detected_at=T0,
            detected_by_actor_or_slot="act:test",
            trace_id=TRACE,
        )
    )
    return SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=SqlConflictStore(world).get(PROJECT, conflict_id),  # type: ignore[arg-type]
        review=ReviewItem(
            review_id=review_id,
            project_id=PROJECT,
            subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
            subject_id=conflict_id,
            stakes=stakes,
            reason="AUTHORITY_INCOMPARABLE",
            trace_id=TRACE,
            created_at=T0,
            estimated_human_minutes=30,
        ),
    )


def _processor(connection) -> ReviewExpiryProcessor:  # type: ignore[no-untyped-def]
    return ReviewExpiryProcessor(reviews=SqlReviewItemStore(connection))


def _sweep(connection, now: dt.datetime = LATER):  # type: ignore[no-untyped-def]
    """The production maintenance entry point. Nothing below reaches past it."""
    return _processor(connection).sweep(
        project_id=PROJECT, now=now, actor_id=EXECUTOR, trace_id="trc:sweep"
    )


def _forbidden_pairs(world) -> list[tuple[str, ...]]:  # type: ignore[no-untyped-def]
    """`011d`'s invariant, scanned directly. Must be empty after every sweep."""
    return world.execute(
        "SELECT r.review_id, r.status, c.conflict_id, c.resolution_status"
        "  FROM conflicts c JOIN review_items r"
        "    ON r.review_id = c.review_id AND r.project_id = c.project_id"
        " WHERE (r.status IN ('QUEUED', 'ASSIGNED')"
        "        AND c.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW'))"
        "    OR (r.status NOT IN ('QUEUED', 'ASSIGNED')"
        "        AND c.resolution_status IN ('OPEN', 'UNDER_REVIEW'))"
    ).fetchall()


# --------------------------------------------------------------------------------------------
# The liveness proof, link by link.
# --------------------------------------------------------------------------------------------


def test_the_production_sweep_expires_an_overdue_review_end_to_end(world):
    """§26's clause in full, through the production caller and nothing else."""
    _escalate(world, "rvw:1", "cfl:1")
    before_events = world.execute("SELECT count(*) FROM belief_revision_events").fetchone()[0]

    result = _sweep(world)

    assert result.count == 1 and not result.refused
    event = result.expired[0]

    # 1. A GovernanceEvent, and it is governance rather than science.
    assert event.event_type is GovernanceEventType.REVIEW_EXPIRY
    assert event.subject_type is GovernanceSubjectType.REVIEW_ITEM
    assert event.subject_id == "rvw:1"
    assert event.related_conflict_id == "cfl:1"
    assert event.reason_code == ReviewExpiryProcessor.REASON_CODE
    assert event.occurred_at == LATER

    # 2. Two actors, answering different questions (§17.19.1).
    assert event.declared_by_actor_id == DECLARER, "who declared the SLA"
    assert event.actor_id == EXECUTOR, "who executed this sweep"
    assert event.declared_by_actor_id != event.actor_id

    # 3. The exact policy version the item was priced by.
    assert (event.policy_id, event.policy_version) == ("rqp:lab", "1.0.0")

    # 4. The resolution: EXPIRED, GOVERNANCE, and it settled nothing.
    store = SqlReviewItemStore(world)
    resolution = store.resolution_for(PROJECT, "rvw:1")
    assert resolution is not None
    assert resolution.outcome is ReviewOutcome.EXPIRED
    assert resolution.resolution_event_kind is ResolutionEventKind.GOVERNANCE
    assert resolution.governance_event_id == event.event_id
    assert resolution.belief_revision_event_id is None
    assert not resolution.settled_the_question, "a timeout did not answer the question"

    # 5. The review has left PENDING.
    review = store.get(PROJECT, "rvw:1")
    assert review is not None
    assert review.status is ReviewStatus.EXPIRED
    assert not review.is_outstanding
    assert review.decision_ref == resolution.resolution_id

    # 6. The conflict closed as the honest status, against the SAME (kind, id) pair.
    conflict_row = world.execute(
        "SELECT resolution_status, resolution_event_kind, resolution_event_id,"
        " governance_event_id FROM conflicts WHERE conflict_id = 'cfl:1'"
    ).fetchone()
    assert conflict_row[0] == "ACCEPTED_AS_OPEN_QUESTION"
    assert conflict_row[1] == "GOVERNANCE"
    assert conflict_row[2] is None, "a governance closure names no belief revision"
    assert conflict_row[3] == event.event_id

    # 7. No belief moved, and no belief event was written.
    assert (
        world.execute("SELECT count(*) FROM belief_revision_events").fetchone()[0] == before_events
    )
    assert _forbidden_pairs(world) == []


def test_the_expiry_writes_no_belief_revision_event_and_leaves_the_projection_alone(world):
    """The clause SPEC-ISSUE-012 was really about: a scheduler must not author belief.

    Asserted twice over -- the belief log is byte-identical, and the replayed projection is the one
    admission left.
    """
    _escalate(world, "rvw:1", "cfl:1")
    before = world.execute(
        "SELECT event_id, target_id, from_state, to_state FROM belief_revision_events"
        " ORDER BY event_id"
    ).fetchall()
    assert before == [("bre:genesis", HYP, None, "ACTIVE")]

    _sweep(world)

    after = world.execute(
        "SELECT event_id, target_id, from_state, to_state FROM belief_revision_events"
        " ORDER BY event_id"
    ).fetchall()
    assert after == before, "the expiry authored a belief revision"

    # And no invented subject anywhere -- the fabricated-hypothesis construction is gone.
    targets = {
        row[0]
        for row in world.execute("SELECT DISTINCT target_id FROM belief_revision_events").fetchall()
    }
    assert targets == {HYP}


def test_an_assigned_review_expires_too(world):
    """`ASSIGNED` is somebody having picked the task up, not somebody having answered it.

    Worth its own case because "someone is on it" is the state most likely to be read as handled
    and quietly excluded from a sweep -- which would park it forever, the exact §14.4 failure.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute(
        "UPDATE review_items SET status = 'ASSIGNED', assigned_actor_id = %s"
        " WHERE review_id = 'rvw:1'",
        (DECLARER,),
    )

    result = _sweep(world)

    assert result.count == 1
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:1").status is ReviewStatus.EXPIRED  # type: ignore[union-attr]
    assert _forbidden_pairs(world) == []


def test_a_review_that_has_not_expired_is_left_alone(world):
    """Not an error -- it is simply not selected. Its deadline has not passed."""
    _escalate(world, "rvw:1", "cfl:1")

    result = _sweep(world, now=T0 + dt.timedelta(hours=5))

    assert result.count == 0 and not result.refused
    review = SqlReviewItemStore(world).get(PROJECT, "rvw:1")
    assert review is not None and review.is_outstanding
    assert SqlConflictStore(world).get(PROJECT, "cfl:1").blocks_transitions  # type: ignore[union-attr]


def test_the_sweep_is_project_scoped(world):
    """SEC-002 does not exempt the sweep. Another project's overdue items are not this one's."""
    _escalate(world, "rvw:1", "cfl:1")

    other = _processor(world).sweep(
        project_id=OTHER, now=LATER, actor_id=EXECUTOR, trace_id="trc:sweep"
    )
    assert other.count == 0

    review = SqlReviewItemStore(world).get(PROJECT, "rvw:1")
    assert review is not None and review.is_outstanding, "swept from the wrong project"


def test_sweeping_several_projects_keeps_them_separate(world):
    """One call per project rather than one global query -- see `sweep_projects`."""
    _escalate(world, "rvw:1", "cfl:1")

    results = sweep_projects(
        _processor(world),
        project_ids=[OTHER, PROJECT, PROJECT],
        now=LATER,
        actor_id=EXECUTOR,
        trace_id="trc:sweep",
    )
    assert [r.project_id for r in results] == [OTHER, PROJECT], "sorted and de-duplicated"
    assert {r.project_id: r.count for r in results} == {OTHER: 0, PROJECT: 1}


# --------------------------------------------------------------------------------------------
# Provenance and authority. Each must fail closed.
# --------------------------------------------------------------------------------------------


def test_a_sweep_with_no_executor_is_refused(world):
    """§14.4 puts `actor_id` on every governance action; an expiry with no executor is a block
    that lifted with nobody accountable."""
    _escalate(world, "rvw:1", "cfl:1")
    with pytest.raises(ExpiryRefused, match="executing actor_id"):
        _processor(world).sweep(project_id=PROJECT, now=LATER, actor_id="   ", trace_id="trc:sweep")
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:1").is_outstanding  # type: ignore[union-attr]


def test_an_unknown_executor_fails_closed(world):
    """The actor foreign key. A sweep run by an actor the database never heard of writes nothing.

    Recorded against the item rather than raised, because one unexpireable review must not abandon
    the rest of the queue -- but the item stays outstanding, which is the fail-closed direction.
    """
    _escalate(world, "rvw:1", "cfl:1")

    result = _processor(world).sweep(
        project_id=PROJECT, now=LATER, actor_id="act:nobody", trace_id="trc:sweep"
    )
    assert result.count == 0
    assert "rvw:1" in result.refused

    review = SqlReviewItemStore(world).get(PROJECT, "rvw:1")
    assert review is not None and review.is_outstanding
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 0
    assert _forbidden_pairs(world) == []


def test_an_active_service_executor_is_allowed(world):
    """The positive control for the guard below, and it is not redundant.

    `v3.3-a16` requires the executor to be ACTIVE. A guard that refused every executor would turn
    the two negative tests around it green, so the permitted case is asserted explicitly: a SERVICE
    actor that is active expires the review, and §17.19.1 is clear that executing one does not make
    it a scientific decision-maker.
    """
    _escalate(world, "rvw:1", "cfl:1")
    assert world.execute("SELECT active FROM actors WHERE actor_id = %s", (EXECUTOR,)).fetchone()[0]

    result = _sweep(world)

    assert result.count == 1 and not result.refused
    assert result.expired[0].actor_id == EXECUTOR
    assert result.expired[0].declared_by_actor_id == DECLARER, (
        "still not inferred from the executor"
    )
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:1").status is ReviewStatus.EXPIRED  # type: ignore[union-attr]


def test_an_inactive_executor_fails_closed(world):
    """`v3.3-a16`: an actor row that exists and is switched off may not expire a review.

    The gap the unknown-executor test above does not cover. A decommissioned scheduler, a departed
    reviewer's automation and a revoked integration are all represented as `active = FALSE`, and
    the actors foreign key is satisfied by every one of them -- so before this guard a
    decommissioned service account could keep lifting blocks with nobody accountable.

    Fail-closed means the item stays in the queue: a human still owes an answer, which is a state
    somebody can act on, rather than a block that lifted on a revoked authority.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute("UPDATE actors SET active = FALSE WHERE actor_id = %s", (EXECUTOR,))

    result = _sweep(world)

    assert result.count == 0
    assert "rvw:1" in result.refused
    assert "not active" in result.refused["rvw:1"]

    review = SqlReviewItemStore(world).get(PROJECT, "rvw:1")
    assert review is not None and review.is_outstanding, "the review must still be owed an answer"
    assert SqlConflictStore(world).get(PROJECT, "cfl:1").blocks_transitions, (  # type: ignore[union-attr]
        "and the conflict must still block"
    )
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 0
    assert world.execute("SELECT count(*) FROM review_resolutions").fetchone()[0] == 0, (
        "no resolution either -- the whole statement is atomic"
    )
    assert _forbidden_pairs(world) == []


def test_raw_sql_cannot_write_an_expiry_for_an_inactive_executor_either(world):
    """The same guard reached without the processor, because support scripts are writers too.

    A migration, a backfill or an operator at a psql prompt never calls `review_expire`. The guard
    is a trigger on `governance_events` rather than a check inside that function for exactly this
    reason -- it is the sentence "an inactive actor does not execute expiries", not "the supported
    path declines to let it".
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute("UPDATE actors SET active = FALSE WHERE actor_id = %s", (EXECUTOR,))

    with pytest.raises(psycopg.errors.RaiseException, match="is not active"):
        world.execute(
            "INSERT INTO governance_events (event_id, project_id, event_type, subject_type,"
            " subject_id, policy_id, policy_version, declared_by_actor_id, actor_id, reason_code,"
            " occurred_at, trace_id)"
            " VALUES ('gev:revoked', %s, 'REVIEW_EXPIRY', 'REVIEW_ITEM', 'rvw:1', 'rqp:lab',"
            " '1.0.0', %s, %s, 'REVIEW_SLA_EXPIRED', %s, %s)",
            (PROJECT, DECLARER, EXECUTOR, LATER, TRACE),
        )
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 0


def test_deactivating_an_executor_does_not_invalidate_the_expiries_it_already_ran(world):
    """Judged when the expiry is written, and deliberately never re-judged.

    The guard lives in a BEFORE INSERT trigger rather than in the deferred commit-boundary
    invariant, and this is the case that decides between them: if "is the executor active" were
    re-asked at every later commit, decommissioning a service account would retroactively invalidate
    every expiry it ever ran -- turning an ordinary operational act into history corruption, and
    wedging the next transaction that happened to touch one of those reviews.
    """
    _escalate(world, "rvw:1", "cfl:1")
    assert _sweep(world).count == 1

    world.execute("UPDATE actors SET active = FALSE WHERE actor_id = %s", (EXECUTOR,))

    # The chain is still readable, still consistent, and still re-assertable at a commit boundary:
    # a fresh escalation in the same project writes rows whose deferred triggers run over it.
    _escalate(world, "rvw:2", "cfl:2")

    review = SqlReviewItemStore(world).get(PROJECT, "rvw:1")
    assert review is not None and review.status is ReviewStatus.EXPIRED
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 1
    assert _forbidden_pairs(world) == []


def test_the_expiry_cites_the_policy_version_the_item_was_priced_by(world):
    """`v3.3-a15`: an expiry re-interpreted under a policy the reviewer never saw is not the
    deadline they were given.

    The lab supersedes its SLA after the item was queued. The sweep must still cite `1.0.0` -- the
    version that computed this item's `expires_at` -- and not the newly active `2.0.0`.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute("UPDATE review_queue_policies SET active = FALSE WHERE version = '1.0.0'")
    SqlReviewQueuePolicyStore(world).register(
        POLICY.model_copy(update={"version": "2.0.0", "expiry_minutes_by_stakes": {"HIGH": 10}})
    )

    result = _sweep(world)

    assert result.count == 1
    assert (result.expired[0].policy_id, result.expired[0].policy_version) == ("rqp:lab", "1.0.0")


def test_a_mismatched_policy_version_is_refused_by_the_database(world):
    """The guard behind the guard. Even if a caller passed a convenient version, SQL refuses it."""
    review = _escalate(world, "rvw:1", "cfl:1")
    SqlReviewQueuePolicyStore(world).register(
        POLICY.model_copy(update={"version": "2.0.0", "active": False})
    )

    with pytest.raises(ReviewStoreError, match="was priced by"):
        SqlReviewItemStore(world).expire(
            review=review.model_copy(update={"queue_policy_version": "2.0.0"}),
            governance_event_id="gev:wrong",
            resolution_id="res:wrong",
            actor_id=EXECUTOR,
            reason_code="REVIEW_SLA_EXPIRED",
            rationale="citing a version the reviewer never saw",
            now=LATER,
            trace_id="trc:sweep",
        )
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 0


# --------------------------------------------------------------------------------------------
# The typed closure pair. Every substitution must be refused.
# --------------------------------------------------------------------------------------------


def test_a_governance_event_belonging_to_another_review_cannot_close_this_one(world):
    """The `v3.3-a14` substitution, in its `v3.3-a15` form.

    Two reviews expire legitimately. Then the second review's resolution is re-pointed at the
    first's governance event -- a real REVIEW_EXPIRY event, in the right project, simply not this
    review's.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _escalate(world, "rvw:2", "cfl:2")
    result = _sweep(world)
    assert result.count == 2

    first = DefaultExpiryIdSource().governance_event_id("rvw:1")
    with pytest.raises(
        psycopg.errors.RaiseException, match=r"two accounts|is not proof|resolved review"
    ):
        world.execute(
            "UPDATE review_resolutions SET governance_event_id = %s WHERE review_id = 'rvw:2'",
            (first,),
        )


@pytest.mark.parametrize("outcome", ["APPROVED", "CORRECTED", "REJECTED"])
def test_a_human_outcome_cannot_close_against_a_governance_event(world, outcome):
    """`v3.3-a15` permits GOVERNANCE for EXPIRED and nothing else.

    APPROVED, CORRECTED and REJECTED are decisions somebody made; a GovernanceEvent is the record
    that nobody did. Closing one against the other would misattribute a human decision to a
    scheduler.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _sweep(world)
    event_id = DefaultExpiryIdSource().governance_event_id("rvw:1")

    with pytest.raises(psycopg.errors.CheckViolation, match="governance_only_expires"):
        world.execute(
            "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
            " resolved_by_actor_id, resolved_at, rationale, governance_event_id,"
            " resolution_event_kind) VALUES ('res:human', 'rvw:1', %s, %s, %s, %s, 'r', %s,"
            " 'GOVERNANCE')",
            (PROJECT, outcome, DECLARER, LATER, event_id),
        )


def test_the_model_refuses_a_human_outcome_against_a_governance_event():
    """The same rule in the model, which catches it earlier and explains it."""
    with pytest.raises(ValueError, match="permits GOVERNANCE only for EXPIRED"):
        ReviewResolution(
            resolution_id="res:1",
            review_id="rvw:1",
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            resolved_by_actor_id=DECLARER,
            resolved_at=LATER,
            rationale="a human decided",
            governance_event_id="gev:1",
            resolution_event_kind=ResolutionEventKind.GOVERNANCE,
        )


def test_a_resolution_cannot_carry_both_kinds_of_event():
    """Exactly one, matching the declared kind. Both would claim a belief moved and did not."""
    with pytest.raises(ValueError, match="must carry exactly"):
        ReviewResolution(
            resolution_id="res:1",
            review_id="rvw:1",
            project_id=PROJECT,
            outcome=ReviewOutcome.EXPIRED,
            resolved_by_actor_id=EXECUTOR,
            resolved_at=LATER,
            rationale="both at once",
            belief_revision_event_id="bre:1",
            governance_event_id="gev:1",
            resolution_event_kind=ResolutionEventKind.GOVERNANCE,
        )


def test_a_wrong_event_type_cannot_be_written_at_all(world):
    """The vocabulary is closed at one value, so a general-purpose governance event does not
    exist to close anything with."""
    _escalate(world, "rvw:1", "cfl:1")
    # Every other field is valid, `declared_by_actor_id` included, so the only thing this row can
    # be refused for is the vocabulary -- which is what the test is about.
    with pytest.raises(psycopg.errors.CheckViolation, match="event_type"):
        world.execute(
            "INSERT INTO governance_events (event_id, project_id, event_type, subject_type,"
            " subject_id, policy_id, policy_version, declared_by_actor_id, actor_id, reason_code,"
            " occurred_at, trace_id)"
            " VALUES ('gev:x', %s, 'CONFLICT_WITHDRAWN', 'REVIEW_ITEM', 'rvw:1', 'rqp:lab',"
            " '1.0.0', %s, %s, 'r', %s, %s)",
            (PROJECT, DECLARER, EXECUTOR, LATER, TRACE),
        )


def test_a_governance_event_cannot_close_a_conflict_with_no_review(world):
    """GOVERNANCE is only ever the product of a REVIEW_EXPIRY, and a conflict with no reviewer has
    no review to expire. Otherwise it would be a general-purpose way to unblock a belief."""
    _escalate(world, "rvw:1", "cfl:1")
    _sweep(world)
    event_id = DefaultExpiryIdSource().governance_event_id("rvw:1")

    SqlConflictStore(world).record(
        Conflict(
            conflict_id="cfl:unreviewed",
            project_id=PROJECT,
            conflict_type=ConflictType.SIM_TO_REAL_CONFLICT,
            subject_refs=(HYP,),
            blocking=True,
            detected_at=T0,
            detected_by_actor_or_slot="act:test",
            trace_id=TRACE,
        )
    )
    with pytest.raises(psycopg.errors.RaiseException, match="linked to no review"):
        world.execute(
            "SELECT conflict_close('cfl:unreviewed', %s, 'ACCEPTED_AS_OPEN_QUESTION', %s, %s,"
            " 'GOVERNANCE')",
            (PROJECT, event_id, LATER),
        )


def test_the_human_path_still_closes_against_a_belief_revision(world):
    """The other side of the rule, so the generalisation did not quietly widen anything.

    A human resolution is unchanged: BELIEF_REVISION, a real belief event, and
    `settled_the_question` true.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute(
        "SELECT belief_revision_event_append('bre:resolved', %s, 'HYPOTHESIS', %s, NULL,"
        " 'ACTIVE', ARRAY['att:1'], ARRAY[]::text[], 'pol:genesis', '1.0.0', NULL, NULL, NULL,"
        " %s, %s, NULL)",
        (PROJECT, "hyp:second", T0, TRACE),
    )
    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=ReviewResolution(
            resolution_id="res:human",
            review_id="rvw:1",
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            resolved_by_actor_id=DECLARER,
            resolved_at=T0 + dt.timedelta(hours=1),
            rationale="the calibrated range covers the operating point",
            belief_revision_event_id="bre:resolved",
        ),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    resolution = SqlReviewItemStore(world).resolution_for(PROJECT, "rvw:1")
    assert resolution is not None
    assert resolution.resolution_event_kind is ResolutionEventKind.BELIEF_REVISION
    assert resolution.belief_revision_event_id == "bre:resolved"
    assert resolution.governance_event_id is None
    assert resolution.settled_the_question

    row = world.execute(
        "SELECT resolution_event_kind, resolution_event_id, governance_event_id FROM conflicts"
        " WHERE conflict_id = 'cfl:1'"
    ).fetchone()
    assert row == ("BELIEF_REVISION", "bre:resolved", None)
    assert _forbidden_pairs(world) == []


def test_an_already_resolved_review_is_not_swept_again(world):
    """A human answered it before the sweep ran. It is done, not overdue."""
    _escalate(world, "rvw:1", "cfl:1")
    world.execute(
        "SELECT belief_revision_event_append('bre:resolved', %s, 'HYPOTHESIS', %s, NULL,"
        " 'ACTIVE', ARRAY['att:1'], ARRAY[]::text[], 'pol:genesis', '1.0.0', NULL, NULL, NULL,"
        " %s, %s, NULL)",
        (PROJECT, "hyp:second", T0, TRACE),
    )
    SqlReviewItemStore(world).resolve_and_close_conflict(
        resolution=ReviewResolution(
            resolution_id="res:human",
            review_id="rvw:1",
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            resolved_by_actor_id=DECLARER,
            resolved_at=T0 + dt.timedelta(hours=1),
            rationale="answered in time",
            belief_revision_event_id="bre:resolved",
        ),
        conflict_status=ConflictResolutionStatus.RESOLVED,
    )

    result = _sweep(world)
    assert result.count == 0 and not result.refused
    assert SqlReviewItemStore(world).resolution_for(PROJECT, "rvw:1").resolution_id == "res:human"  # type: ignore[union-attr]


# --------------------------------------------------------------------------------------------
# Retry and concurrency.
# --------------------------------------------------------------------------------------------


def test_a_repeated_sweep_writes_nothing_new(world):
    """Idempotence, and the ids are derived so a retry proposes the same primary keys.

    A sweep that renamed its rows would make a second expiry indistinguishable from a retry, which
    is why `DefaultExpiryIdSource` derives them from the review.
    """
    _escalate(world, "rvw:1", "cfl:1")
    first = _sweep(world)
    assert first.count == 1

    again = _sweep(world)
    assert again.count == 0, "a retry must not expire an already-expired review"
    assert not again.refused, "and it must not report the retry as a failure either"
    # `overdue()` filters on status in SQL, so the second sweep does not even select the item --
    # which is the strongest form of the guarantee: the retry has nothing to be idempotent about.
    # The narrower race, where an item is answered between the SELECT and the loop body, is held
    # by `test_an_item_answered_mid_sweep_is_reported_rather_than_forced`.
    assert SqlReviewItemStore(world).overdue(PROJECT, LATER) == ()

    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 1
    assert (
        world.execute(
            "SELECT count(*) FROM review_resolutions WHERE review_id = 'rvw:1'"
        ).fetchone()[0]
        == 1
    )
    assert _forbidden_pairs(world) == []


def test_two_sessions_sweeping_the_same_queue_produce_exactly_one_expiry(world, second):
    """A real race across two connections, with a barrier.

    Two schedulers on two hosts is the realistic deployment, and the one outcome that must not
    happen is two governance events claiming to have expired the same review.
    """
    _escalate(world, "rvw:1", "cfl:1")
    start = threading.Barrier(2)

    def attempt(connection):  # type: ignore[no-untyped-def]
        start.wait(timeout=10)
        try:
            return ("ok", _sweep(connection).count)
        except Exception as exc:
            return ("failed", f"{type(exc).__name__}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(attempt, c) for c in (world, second)]]

    expired_counts = [value for kind, value in results if kind == "ok"]
    assert sum(c for c in expired_counts if isinstance(c, int)) == 1, (
        f"exactly one session may expire the review, got {results}"
    )
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 1
    assert (
        world.execute(
            "SELECT count(*) FROM review_resolutions WHERE review_id = 'rvw:1'"
        ).fetchone()[0]
        == 1
    )
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:1").status is ReviewStatus.EXPIRED  # type: ignore[union-attr]
    assert _forbidden_pairs(world) == []


def test_one_unexpireable_item_does_not_abandon_the_rest_of_the_queue(world):
    """A sweep that stopped at the first awkward row would heal only as far as its worst item --
    which is the parking §14.4 forbids, arrived at by a different route."""
    _escalate(world, "rvw:1", "cfl:1")
    _escalate(world, "rvw:2", "cfl:2")
    # Pre-write the governance event id `rvw:1` will propose, so its expiry collides.
    world.execute(
        "INSERT INTO governance_events (event_id, project_id, event_type, subject_type,"
        " subject_id, policy_id, policy_version, declared_by_actor_id, actor_id, reason_code,"
        " occurred_at, trace_id)"
        " VALUES (%s, %s, 'REVIEW_EXPIRY', 'REVIEW_ITEM', 'rvw:1', 'rqp:lab', '1.0.0', %s, %s,"
        " 'squatter', %s, %s)",
        (
            DefaultExpiryIdSource().governance_event_id("rvw:1"),
            PROJECT,
            # `v3.3-a16` requires it on a REVIEW_EXPIRY. Supplied correctly so that the collision
            # under test is the primary key one -- an event refused for a second reason would
            # prove the sweep survives a different fault than the one this test names.
            DECLARER,
            EXECUTOR,
            LATER,
            TRACE,
        ),
    )

    result = _sweep(world)

    assert "rvw:1" in result.refused
    assert result.count == 1, "the second item still expired"
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:2").status is ReviewStatus.EXPIRED  # type: ignore[union-attr]
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:1").is_outstanding  # type: ignore[union-attr]
    assert _forbidden_pairs(world) == []


def test_the_sweep_is_ordered_and_bounded(world):
    """Oldest first, and `limit` batches a backlog rather than making it one transaction."""
    _escalate(world, "rvw:a", "cfl:a")
    _escalate(world, "rvw:b", "cfl:b")
    _escalate(world, "rvw:c", "cfl:c")

    batched = _processor(world).sweep(
        project_id=PROJECT, now=LATER, actor_id=EXECUTOR, trace_id="trc:sweep", limit=2
    )
    assert batched.count == 2
    assert [e.subject_id for e in batched.expired] == ["rvw:a", "rvw:b"]

    rest = _sweep(world)
    assert [e.subject_id for e in rest.expired] == ["rvw:c"]


def test_the_conflict_closure_does_not_make_the_authority_comparable(world):
    """ACCEPTED_AS_OPEN_QUESTION closes this instance, not the question (`v3.3-a15`).

    A later episode over the same INCOMPARABLE comparison must still be able to raise a new
    conflict and a new review -- so the closed one must not block that, and the belief must not
    have moved.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _sweep(world)

    assert SqlConflictStore(world).unresolved_for_subject(PROJECT, HYP) == (), (
        "the expired instance no longer blocks"
    )

    # A fresh conflict for the same hypothesis is accepted, which is what "the question is still
    # open" means operationally.
    _escalate(world, "rvw:2", "cfl:2")
    reopened = SqlConflictStore(world).unresolved_for_subject(PROJECT, HYP)
    assert [c.conflict_id for c in reopened] == ["cfl:2"]
    assert reopened[0].blocks_transitions


def test_an_item_answered_mid_sweep_is_reported_rather_than_forced():
    """The narrow race the `already_gone` branch exists for, made deterministic.

    `overdue()` filters on status in SQL, so a *retried* sweep never selects an already-expired
    item. The branch that matters is the one in between: a human answers a review after the sweep
    has read the candidate list and before the loop reaches it. Under concurrency that window is
    real, and forcing the expiry through would overwrite the answer they just gave.

    Driven with a stub sink rather than a database, because the whole point is to land exactly in
    that window -- a postgres test would have to win a race to prove anything, and a test that has
    to win a race proves nothing when it loses.
    """
    answered = ReviewItem(
        review_id="rvw:answered",
        project_id=PROJECT,
        subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
        subject_id="cfl:1",
        stakes="HIGH",
        reason="AUTHORITY_INCOMPARABLE",
        trace_id=TRACE,
        created_at=T0,
        status=ReviewStatus.APPROVED,
        decision_ref="res:human",
        queue_policy_id="rqp:lab",
        queue_policy_version="1.0.0",
        due_at=T0 + dt.timedelta(hours=4),
        expires_at=T0 + dt.timedelta(hours=48),
    )

    class StaleSink:
        """Returns a candidate that has since been answered, as a real read/act gap would."""

        def overdue(self, project_id: str, now: dt.datetime) -> tuple[ReviewItem, ...]:
            return (answered,)

        def expire(self, **kwargs: object) -> None:  # pragma: no cover - must not be reached
            raise AssertionError("the sweep forced an expiry over a human's answer")

    result = ReviewExpiryProcessor(reviews=StaleSink()).sweep(  # type: ignore[arg-type]
        project_id=PROJECT, now=LATER, actor_id=EXECUTOR, trace_id="trc:sweep"
    )

    assert result.count == 0
    assert result.already_gone == ("rvw:answered",)
    assert not result.refused, "somebody answering in time is not a failure"


# --------------------------------------------------------------------------------------------
# The database-level guards behind the processor. Found by mutation: each of these survived a
# first pass because every test reached them through the production caller, which never asks for
# the forbidden shape. A guard that only the happy path exercises is a guard nothing holds.
# --------------------------------------------------------------------------------------------


@pytest.fixture
def raw(db) -> Iterator[psycopg.Connection]:  # type: ignore[no-untyped-def]
    """A transactional session, for the commit-boundary case `011d` owns."""
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), connect_timeout=5
    )
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("kind", "column", "value"),
    [
        ("GOVERNANCE", "belief_revision_event_id", "bre:genesis"),
        ("BELIEF_REVISION", "governance_event_id", "gev:expiry:rvw:1"),
    ],
    ids=["governance_carrying_a_belief_event", "belief_revision_carrying_a_governance_event"],
)
def test_a_resolution_whose_kind_disagrees_with_its_event_is_refused(world, kind, column, value):
    """`011f`'s kind/column agreement CHECK, exercised by raw SQL.

    The model refuses this too, and the model is not the only writer. Both directions are covered:
    a GOVERNANCE closure carrying a belief revision claims a belief moved when none did, and a
    BELIEF_REVISION closure carrying a governance event claims a human decided when nobody did.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _sweep(world)  # produces a real governance event for the second case to misuse

    statement = (
        "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
        " resolved_by_actor_id, resolved_at, rationale, resolution_event_kind, "
        + column
        + ") VALUES ('res:mismatch', 'rvw:2', %s, 'EXPIRED', %s, %s, 'r', %s, %s)"
    )
    _escalate(world, "rvw:2", "cfl:2")
    with pytest.raises(psycopg.errors.CheckViolation, match="event_matches_kind"):
        world.execute(statement, (PROJECT, EXECUTOR, LATER, kind, value))


def test_a_conflict_cannot_close_as_a_different_kind_than_its_resolution_recorded(world):
    """`conflict_close`'s (kind, id) pair check.

    The resolution records BELIEF_REVISION; the close claims GOVERNANCE. Agreeing on the id is not
    enough once the reference is typed -- the two would describe one act as two different kinds.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute(
        "SELECT belief_revision_event_append('bre:human', %s, 'HYPOTHESIS', %s, NULL, 'ACTIVE',"
        " ARRAY['att:1'], ARRAY[]::text[], 'pol:genesis', '1.0.0', NULL, NULL, NULL, %s, %s, NULL)",
        (PROJECT, "hyp:other", T0, TRACE),
    )

    tx = psycopg.connect(os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), connect_timeout=5)
    try:
        with tx.cursor() as cursor:
            cursor.execute(
                "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
                " resolved_by_actor_id, resolved_at, rationale, belief_revision_event_id,"
                " resolution_event_kind) VALUES ('res:1', 'rvw:1', %s, 'APPROVED', %s, %s, 'r',"
                " 'bre:human', 'BELIEF_REVISION')",
                (PROJECT, DECLARER, LATER),
            )
            cursor.execute(
                "UPDATE review_items SET status = 'APPROVED', decision_ref = 'res:1'"
                " WHERE review_id = 'rvw:1'"
            )
            with pytest.raises(psycopg.errors.RaiseException, match="recorded a"):
                cursor.execute(
                    "SELECT conflict_close('cfl:1', %s, 'ACCEPTED_AS_OPEN_QUESTION', 'bre:human',"
                    " %s, 'GOVERNANCE')",
                    (PROJECT, LATER),
                )
    finally:
        tx.rollback()
        tx.close()


def test_a_conflict_kind_rewritten_by_raw_sql_does_not_survive_commit(world, raw):
    """`011d`'s commit-boundary invariant, generalised to the typed pair by `011f`.

    The resolution is re-pointed at a BELIEF_REVISION event while the conflict still records
    GOVERNANCE. Every per-statement guard is satisfied; the pair only disagrees at COMMIT, which is
    exactly the shape P13 closed and `v3.3-a15` had to widen rather than drop.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _sweep(world)
    world.execute(
        "SELECT belief_revision_event_append('bre:elsewhere', %s, 'HYPOTHESIS', %s, NULL,"
        " 'ACTIVE', ARRAY['att:1'], ARRAY[]::text[], 'pol:genesis', '1.0.0', NULL, NULL, NULL,"
        " %s, %s, NULL)",
        (PROJECT, "hyp:other", T0, TRACE),
    )

    with raw.cursor() as cursor:
        cursor.execute(
            "UPDATE review_resolutions SET resolution_event_kind = 'BELIEF_REVISION',"
            " governance_event_id = NULL, belief_revision_event_id = 'bre:elsewhere'"
            " WHERE review_id = 'rvw:1'"
        )

    with pytest.raises(psycopg.errors.RaiseException, match=r"recorded a|closed against a"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_the_database_refuses_an_early_expiry_even_if_a_caller_asks(world):
    """The deadline guard inside `review_expire`, reached directly.

    The processor never asks for this -- it only selects items already past `expires_at` -- so the
    SQL guard behind it is exercised here instead. A sweep that could expire anything on request is
    a way to clear an inconvenient review, and the declared deadline is what makes one legitimate.
    """
    review = _escalate(world, "rvw:1", "cfl:1")

    with pytest.raises(ReviewStoreError, match="which is not before"):
        SqlReviewItemStore(world).expire(
            review=review,
            governance_event_id="gev:early",
            resolution_id="res:early",
            actor_id=EXECUTOR,
            reason_code="REVIEW_SLA_EXPIRED",
            rationale="before the deadline",
            now=T0 + dt.timedelta(hours=1),
            trace_id="trc:sweep",
        )
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 0
    assert SqlReviewItemStore(world).get(PROJECT, "rvw:1").is_outstanding  # type: ignore[union-attr]


def test_a_queue_policy_must_name_who_declared_it(world):
    """`v3.3-a15`: the standing authority for automatic expiry is recorded, not inferred.

    Refused by the database, because the model is not the only writer -- and a policy with no
    author is an expiry nobody authorised, executed by a service account that would then look like
    the source of the decision.
    """
    with pytest.raises(psycopg.errors.NotNullViolation, match="declared_by_actor_id"):
        world.execute(
            "INSERT INTO review_queue_policies (policy_id, version, project_id, capacity,"
            " default_sla_minutes, default_expiry_minutes, effective_from, active)"
            " VALUES ('rqp:anon', '1.0.0', %s, 4, 60, 120, %s, FALSE)",
            (PROJECT, T0),
        )
