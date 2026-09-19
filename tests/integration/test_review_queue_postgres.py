"""T-OPS-002: the ReviewQueue has capacity, an SLA and an expiry, and feeds a Capability.

    §14.4    Human ReviewQueue 必須有 stakes、created_at、SLA/expiry policy 與 queue capacity，
             避免所有 uncertain item 永久卡在 PENDING。
    §14.4.1  Human review 是一個 **Capability**，不是無限免費資源。
    §26      T-OPS-002 | unit/integration | queue depth/capacity changes human-review capability
             availability and planner earliest_available_at; **a ReviewItem without `stakes` or
             without an SLA/expiry policy is refused at creation, and an item past its expiry
             leaves PENDING via the declared policy rather than parking there indefinitely.**

THE THREE CLAUSES, AND WHY THE LAST ONE IS EXPENSIVE. "Leaves PENDING via the declared policy" is
not a status flip. `v3.3-a14` makes EXPIRED a terminal review status, and `011c`/`011d` require a
terminal review to carry a durable `ReviewResolution` whose linked Conflict is terminal against
that resolution's own event. So an expiry closes a conflict and unblocks a belief nobody
adjudicated -- a real governance act, with a real record. Anything cheaper would be the half-state
P12/P13 spent two slices closing.

LIVENESS LIVES NEXT DOOR. SPEC-ISSUE-012 gated it until `v3.3-a15` gave an expiry an event it
could honestly author; the proof now runs through the production caller in
`test_review_expiry_postgres.py`. This module keeps the other two clauses -- what a queue
refuses at creation, and how depth and capacity become Capability availability.

The fabricated-hypothesis fixture that used to stand in for a closure event is deleted, not
adapted. `011f` means nothing here has to invent a subject to satisfy a foreign key.

NOT UX-005. T-UX-005 additionally requires the NEEDS_REVIEW user experience, which does not exist.
This file discharges the governance/backend contract and nothing else.
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from lab_brain.core.models.conflict import (
    Conflict,
    ConflictResolutionStatus,
    ConflictType,
)
from lab_brain.core.models.review import ReviewItem, ReviewSubjectType
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import (
    ReviewStoreError,
    SqlReviewItemStore,
    SqlReviewQueuePolicyStore,
)
from lab_brain.core.review_queue import (
    ReviewQueue,
    ReviewQueueError,
    ReviewQueuePolicy,
    price_review,
)
from tests.conftest_fixtures import make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("OPS-002"),
    pytest.mark.spec_test("T-OPS-002"),
]

T0 = dt.datetime(2026, 9, 16, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:queue"

POLICY = ReviewQueuePolicy(
    policy_id="rqp:lab",
    version="1.0.0",
    project_id=PROJECT,
    capacity=2,
    default_sla_minutes=24 * 60,
    default_expiry_minutes=72 * 60,
    # HIGH stakes get a reviewer sooner and lapse sooner: a high-stakes question nobody answered
    # in two days is a different fact from a routine one still waiting.
    sla_minutes_by_stakes={"HIGH": 4 * 60},
    expiry_minutes_by_stakes={"HIGH": 48 * 60},
    # `v3.3-a15`: who declared this SLA. The standing authority an automatic expiry
    # executes, recorded separately from whoever runs the sweep.
    declared_by_actor_id="act:test",
    reviewer_minutes_per_day=120,
    effective_from=T0,
)


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """A project with an active queue policy, and the evidence a closure event will need."""
    artifact = make_artifact(b"a review queue fixture")
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
    SqlReviewQueuePolicyStore(db).register(POLICY)
    return db


def _conflict(world, conflict_id: str) -> Conflict:  # type: ignore[no-untyped-def]
    return SqlConflictStore(world).record(
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


def _escalate(world, review_id: str, conflict_id: str, stakes: str = "HIGH") -> ReviewItem:  # type: ignore[no-untyped-def]
    return SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=_conflict(world, conflict_id),
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


def _queue(world) -> ReviewQueue:  # type: ignore[no-untyped-def]
    policy = SqlReviewQueuePolicyStore(world).active_for(PROJECT)
    assert policy is not None
    return ReviewQueue(policy=policy, reviews=SqlReviewItemStore(world))


# --------------------------------------------------------------------------------------------
# Clause 2: refused at creation, without stakes or without a policy.
# --------------------------------------------------------------------------------------------


def test_escalation_prices_the_item_from_the_declared_policy(world):
    """The positive: a queued item leaves with both deadlines and the policy that set them."""
    review = _escalate(world, "rvw:1", "cfl:1", stakes="HIGH")

    assert review.stakes == "HIGH"
    assert review.due_at == T0 + dt.timedelta(hours=4), "the HIGH override, not the default"
    assert review.expires_at == T0 + dt.timedelta(hours=48)

    recorded = world.execute(
        "SELECT queue_policy_id, queue_policy_version FROM review_items WHERE review_id = 'rvw:1'"
    ).fetchone()
    assert recorded == ("rqp:lab", "1.0.0"), (
        "the item records which policy priced it, so an expiry stays explicable after the lab "
        "changes the rule"
    )


def test_a_stakes_value_the_policy_does_not_mention_falls_back_to_the_declared_default(world):
    """There is no third fallback. A queue that guessed would have a deadline nobody declared."""
    review = _escalate(world, "rvw:1", "cfl:1", stakes="ROUTINE")
    assert review.due_at == T0 + dt.timedelta(hours=24)
    assert review.expires_at == T0 + dt.timedelta(hours=72)


def test_a_review_with_no_stakes_is_refused_at_creation(world):
    """§14.4: stakes is what a reviewer prioritises by and what the SLA is priced from.

    Refused by the database, because the store is not the only writer -- and a blank string is the
    shape this takes in practice, since `011b` already made the column NOT NULL.
    """
    _conflict(world, "cfl:1")
    with pytest.raises(psycopg.errors.RaiseException, match="has no stakes"):
        world.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
            " reason, trace_id, created_at, queue_policy_id, queue_policy_version, due_at,"
            " expires_at) VALUES ('rvw:blank', %s, 'AUTHORITY_CONFLICT', 'cfl:1', '   ',"
            " 'AUTHORITY_INCOMPARABLE', %s, %s, 'rqp:lab', '1.0.0', %s, %s)",
            (PROJECT, TRACE, T0, T0, T0),
        )


def test_a_review_with_no_sla_or_expiry_policy_is_refused_at_creation(world):
    """The state §14.4 exists to forbid: an item with no deadline, which can park forever."""
    _conflict(world, "cfl:1")
    with pytest.raises(psycopg.errors.RaiseException, match="names no queue policy"):
        world.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
            " reason, trace_id, created_at) VALUES ('rvw:undated', %s, 'AUTHORITY_CONFLICT',"
            " 'cfl:1', 'HIGH', 'AUTHORITY_INCOMPARABLE', %s, %s)",
            (PROJECT, TRACE, T0),
        )


def test_naming_a_policy_without_being_priced_by_it_is_also_refused(world):
    """The near-miss. Citing an SLA policy is not the same as having a deadline."""
    _conflict(world, "cfl:1")
    with pytest.raises(psycopg.errors.RaiseException, match="missing due_at or expires_at"):
        world.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
            " reason, trace_id, created_at, queue_policy_id, queue_policy_version)"
            " VALUES ('rvw:named', %s, 'AUTHORITY_CONFLICT', 'cfl:1', 'HIGH',"
            " 'AUTHORITY_INCOMPARABLE', %s, %s, 'rqp:lab', '1.0.0')",
            (PROJECT, TRACE, T0),
        )


def test_an_item_that_expires_before_it_is_due_is_refused(world):
    """It would close unanswered while the queue reported no SLA breach at all."""
    _conflict(world, "cfl:1")
    with pytest.raises(psycopg.errors.RaiseException, match="before it is due"):
        world.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes,"
            " reason, trace_id, created_at, queue_policy_id, queue_policy_version, due_at,"
            " expires_at) VALUES ('rvw:inverted', %s, 'AUTHORITY_CONFLICT', 'cfl:1', 'HIGH',"
            " 'AUTHORITY_INCOMPARABLE', %s, %s, 'rqp:lab', '1.0.0', %s, %s)",
            (PROJECT, TRACE, T0, T0 + dt.timedelta(hours=4), T0 + dt.timedelta(hours=1)),
        )


def test_escalation_is_refused_when_the_project_declares_no_active_policy(world):
    """A project with no SLA cannot queue human work at all -- the fail-closed direction.

    The conflict stays OPEN and `blocking`, so the belief stays blocked. That is the right way
    round: the alternative is a queued item with no deadline, which is the thing §14.4 forbids.
    """
    world.execute("UPDATE review_queue_policies SET active = FALSE WHERE policy_id = 'rqp:lab'")
    with pytest.raises(ReviewStoreError, match="no active review queue policy"):
        _escalate(world, "rvw:1", "cfl:1")

    conflict = SqlConflictStore(world).get(PROJECT, "cfl:1")
    assert conflict is not None
    assert conflict.resolution_status is ConflictResolutionStatus.OPEN
    assert conflict.blocks_transitions, "the block must stay in place"


def test_two_active_policies_for_one_project_are_unrepresentable(world):
    """ "Which deadline applies" must not depend on read order."""
    with pytest.raises((ReviewStoreError, psycopg.errors.UniqueViolation)):
        SqlReviewQueuePolicyStore(world).register(
            POLICY.model_copy(update={"policy_id": "rqp:rival", "version": "1.0.0"})
        )


def test_the_python_pricing_gate_refuses_what_the_trigger_refuses(world):
    """Both halves exist for the reason this project has written down five times.

    A model guard holds for callers who go through the model; a migration, a support script or a
    future service writes SQL. This one catches it earlier and says more; the trigger is the one
    that actually holds.
    """
    blank = ReviewItem(
        review_id="rvw:blank",
        project_id=PROJECT,
        subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
        subject_id="cfl:1",
        stakes="  ",
        reason="AUTHORITY_INCOMPARABLE",
        trace_id=TRACE,
        created_at=T0,
    )
    with pytest.raises(ReviewQueueError, match="has no stakes"):
        price_review(review=blank, policy=POLICY)

    foreign = blank.model_copy(update={"stakes": "HIGH", "project_id": "prj:other"})
    with pytest.raises(ReviewQueueError, match="does not price another"):
        price_review(review=foreign, policy=POLICY)

    retired = POLICY.model_copy(update={"active": False})
    with pytest.raises(ReviewQueueError, match="not active"):
        price_review(review=blank.model_copy(update={"stakes": "HIGH"}), policy=retired)


def test_a_policy_whose_expiry_precedes_its_sla_cannot_be_declared():
    """Checked for the defaults and for every per-stakes override.

    The override is where this hides: the defaults look right and one class of item quietly
    self-closes, never appearing as a breach.
    """
    with pytest.raises(ValueError, match="Every item would close unanswered"):
        POLICY.model_copy(update={"default_expiry_minutes": 60}).model_validate(
            POLICY.model_dump() | {"default_expiry_minutes": 60}
        )
    with pytest.raises(ValueError, match="expire before"):
        POLICY.model_validate(POLICY.model_dump() | {"expiry_minutes_by_stakes": {"HIGH": 60}})


# --------------------------------------------------------------------------------------------
# Clause 1: depth and capacity change availability and earliest_available_at.
# --------------------------------------------------------------------------------------------


def test_queue_depth_and_capacity_change_capability_availability(world):
    """§14.4.1, measured: the same queue, at three depths, reporting three different answers."""
    queue = _queue(world)

    empty = queue.capability(PROJECT, T0)
    assert empty.depth == 0 and empty.capacity == 2
    assert empty.available is True
    assert empty.earliest_available_at == T0, "room now means available now"
    assert empty.estimated_human_minutes == 0

    _escalate(world, "rvw:1", "cfl:1")
    one = queue.capability(PROJECT, T0)
    assert one.depth == 1
    assert one.available is True
    assert one.earliest_available_at == T0
    assert one.estimated_human_minutes == 30, "the backlog, not the marginal item"

    _escalate(world, "rvw:2", "cfl:2")
    full = queue.capability(PROJECT, T0)
    assert full.depth == 2
    assert full.available is False, "at capacity, human review is not available"
    assert full.estimated_human_minutes == 60
    assert full.earliest_available_at == T0 + dt.timedelta(hours=4), (
        "the earliest due_at -- the next moment a slot is expected to free. Reporting `now` while "
        "saturated would tell a planner human review is instantaneous"
    )
    assert full.policy_ref == "rqp:lab@1.0.0"


def test_an_assigned_item_still_counts_toward_depth(world):
    """Somebody having picked a task up is not somebody having finished it.

    A queue that stopped counting assigned items would report depth 0 while forty reviews sat
    half-done -- the same distinction `v3.3-a14` draws for the outstanding-review invariant.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute(
        "UPDATE review_items SET status = 'ASSIGNED', assigned_actor_id = 'act:test'"
        " WHERE review_id = 'rvw:1'"
    )
    assert _queue(world).depth(PROJECT) == 1
    assert _queue(world).capability(PROJECT, T0).depth == 1


def test_a_breached_item_is_reported_separately_from_depth(world):
    """A queue within capacity and entirely overdue is not a healthy queue, and one number hides
    it."""
    _escalate(world, "rvw:1", "cfl:1")
    at_breach = _queue(world).capability(PROJECT, T0 + dt.timedelta(hours=5))
    assert at_breach.depth == 1
    assert at_breach.breached == 1
    assert at_breach.available is True, "late is not the same as full"


def test_zero_capacity_means_no_human_review_rather_than_no_limit(world):
    """The `v3.3-a10` lesson about budget caps, applied to a queue: absent and zero are two
    different facts, and a field where omission means "no limit" cannot say the second."""
    world.execute("UPDATE review_queue_policies SET capacity = 0 WHERE policy_id = 'rqp:lab'")
    capability = _queue(world).capability(PROJECT, T0)
    assert capability.capacity == 0
    assert capability.depth == 0
    assert capability.available is False
    assert capability.earliest_available_at == T0 + dt.timedelta(hours=24), (
        "nothing dated to read a date off, so the declared default SLA rather than `now`"
    )


def test_depth_is_project_scoped(world):
    """SEC-002 does not exempt the review queue, and a shared depth would leak the other
    project's backlog into this project's plan."""
    _escalate(world, "rvw:1", "cfl:1")
    assert _queue(world).depth(PROJECT) == 1
    assert _queue(world).depth("prj:nobody") == 0


# --------------------------------------------------------------------------------------------
# Clause 3: an expired item leaves PENDING via the declared policy.
# --------------------------------------------------------------------------------------------


def test_an_item_past_its_expiry_is_reported_as_overdue(world):
    """Expired is not the same as breached. Breached is late and still worth an answer."""
    _escalate(world, "rvw:1", "cfl:1")
    queue = _queue(world)

    assert queue.overdue(PROJECT, T0 + dt.timedelta(hours=5)) == ()
    assert queue.capability(PROJECT, T0 + dt.timedelta(hours=5)).breached == 1

    overdue = queue.overdue(PROJECT, T0 + dt.timedelta(hours=49))
    assert [item.review_id for item in overdue] == ["rvw:1"]


def test_a_retried_escalation_is_still_idempotent_after_the_policy_landed(world):
    """`011e` replaced `authority_conflict_escalate`, so the locked P13 guarantee is re-asserted.

    A retried episode must get the review that already gates the conflict, not a second one -- and
    it must get it even though the retry would now also have to be priced.
    """
    first = _escalate(world, "rvw:1", "cfl:1")
    again = SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=SqlConflictStore(world).get(PROJECT, "cfl:1"),  # type: ignore[arg-type]
        review=ReviewItem(
            review_id="rvw:duplicate",
            project_id=PROJECT,
            subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
            subject_id="cfl:1",
            stakes="HIGH",
            reason="AUTHORITY_INCOMPARABLE",
            trace_id=TRACE,
            created_at=T0 + dt.timedelta(minutes=5),
        ),
    )
    assert again.review_id == first.review_id == "rvw:1"
    assert again.due_at == first.due_at, "the retry is not a second pricing"
    assert world.execute("SELECT count(*) FROM review_items").fetchone()[0] == 1


def test_a_retried_escalation_succeeds_even_if_the_policy_was_retired(world):
    """The ordering inside the function, asserted.

    The idempotence check runs *before* the policy lookup on purpose: the first escalation was
    priced, and a retry is not a second pricing. A lab that deactivates its queue policy must not
    find that retrying an episode now fails on a review that already exists.
    """
    _escalate(world, "rvw:1", "cfl:1")
    world.execute("UPDATE review_queue_policies SET active = FALSE WHERE policy_id = 'rqp:lab'")

    again = SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=SqlConflictStore(world).get(PROJECT, "cfl:1"),  # type: ignore[arg-type]
        review=ReviewItem(
            review_id="rvw:duplicate",
            project_id=PROJECT,
            subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
            subject_id="cfl:1",
            stakes="HIGH",
            reason="AUTHORITY_INCOMPARABLE",
            trace_id=TRACE,
            created_at=T0,
        ),
    )
    assert again.review_id == "rvw:1"


def test_earliest_available_at_is_never_in_the_past(world):
    """A full queue whose items are ALL already breached must not report a moment that has gone.

    Found by the M0b sign-off audit. Unclamped, `min(due_at)` over a saturated, entirely-overdue
    queue returns a timestamp behind `now` -- and a planner reading it would schedule against the
    queue on the strength of a date that proves the opposite: those items are not nearly done, they
    are late.

    §14.4.1 says depth, availability, SLA and expiry *feed* `earliest_available_at` and defines no
    formula, so the floor is a stated implementation rule, not a derived one: whatever else the
    capability reports, human review cannot have become available in the past.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _escalate(world, "rvw:2", "cfl:2")

    # Capacity is 2 and both items are HIGH, so both were due 4h after T0. Ask 10 days later.
    now = T0 + dt.timedelta(days=10)
    capability = _queue(world).capability(PROJECT, now)

    assert capability.depth == 2 and capability.capacity == 2
    assert capability.available is False, "the queue is full"
    assert capability.breached == 2, "and every item is past its SLA"
    assert capability.earliest_available_at >= now, (
        f"earliest_available_at {capability.earliest_available_at.isoformat()} is before "
        f"now {now.isoformat()}; human review cannot have become available in the past"
    )
    assert capability.earliest_available_at == now, "the floor, reported as a bound"


def test_a_full_but_unbreached_queue_still_reports_its_real_next_slot(world):
    """The clamp must not flatten the useful case into `now`.

    Same saturated queue, asked *before* the SLA runs out: the answer is the genuine earliest
    `due_at`, which is later than `now` and is the number a planner actually wants.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _escalate(world, "rvw:2", "cfl:2")

    now = T0 + dt.timedelta(hours=1)
    capability = _queue(world).capability(PROJECT, now)

    assert capability.available is False
    assert capability.breached == 0
    assert capability.earliest_available_at == T0 + dt.timedelta(hours=4)
    assert capability.earliest_available_at > now
