"""T-UX-005 — NEEDS_REVIEW is a real ReviewItem in the existing queue (§17.22, §14.4.1, OPS-002).

§26's pass condition: *A low-confidence extraction fixture creates a ReviewItem visible in
ReviewQueue depth and measurably changes human-review Capability availability.*

WHY THE OBVIOUS IMPLEMENTATION IS THE FORBIDDEN ONE. A dedicated `extraction_reviews` table would
be easier -- no vocabulary to extend, no M0b code to think about -- and it is exactly the
"parallel review surface that bypasses ReviewQueue" UX-005 prohibits. The prohibition has teeth:
§14.4.1 makes ReviewQueue depth the input to `HumanReviewCapability.availability`, so a second
queue would consume the same reviewers' attention while being invisible to the planner that is
supposed to price it. The system would then plan as though review were free.

So `011h` adds one member to `review_items.subject_type` and changes nothing else. Every M0b
behaviour -- escalation, SLA/expiry, `review_expire`, the `011d` commit-boundary invariant --
reads `subject_type` only to distinguish AUTHORITY_CONFLICT, and none of them changes meaning
because a third value exists. OPS-002 and EPI-004/EPI-006 are not reopened, and
`test_m0b_conflict_review_behaviour_is_unchanged` is here to say so with an assertion rather than
a claim.

"MEASURABLY CHANGES AVAILABILITY" is asserted as a before/after on the same capability object,
not as "a non-default value appeared". A queue whose availability was already degraded would make
the weaker assertion pass without the new item doing anything.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models.review import ReviewStatus, ReviewSubjectType
from lab_brain.core.repositories.reviews import SqlReviewItemStore, SqlReviewQueuePolicyStore
from lab_brain.core.review_queue import ReviewQueue, ReviewQueuePolicy
from lab_brain.surface.ingestion_item import IngestionItem, ItemState, derive_state

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("UX-005"),
    pytest.mark.spec_test("T-UX-005"),
]

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"


@pytest.fixture
def queue(db):
    """A project with a REGISTERED active policy, because `011e` refuses items without one.

    Registered rather than constructed in memory: the enqueue path prices from the stored policy
    (see `extraction_review_enqueue`), so a policy that existed only in Python would let the test
    pass against a production path that could not run.
    """
    policy = ReviewQueuePolicy(
        policy_id="rqp:test",
        version="1.0.0",
        project_id=PROJECT,
        capacity=3,
        default_sla_minutes=240,
        default_expiry_minutes=480,
        sla_minutes_by_stakes={"HIGH": 60, "MEDIUM": 240, "LOW": 1440},
        expiry_minutes_by_stakes={"HIGH": 120, "MEDIUM": 480, "LOW": 2880},
        reviewer_minutes_per_day=480,
        declared_by_actor_id="act:test",
        effective_from=NOW - dt.timedelta(days=1),
        active=True,
    )
    SqlReviewQueuePolicyStore(db).register(policy)
    return db, ReviewQueue(policy=policy, reviews=SqlReviewItemStore(db)), policy


def _enqueue(db, item_id: str, *, stakes: str = "MEDIUM") -> str:
    """The production path: `SqlReviewItemStore.enqueue_extraction_review`.

    The subject is the IngestionItem, not one Attestation. §17.22 attaches `review_ids[]` to the
    item, and a reviewer judging whether a field is genuinely unknown (EVI-002) needs the
    document context -- one Attestation would show them a value with nothing to compare against.
    """
    return SqlReviewItemStore(db).enqueue_extraction_review(
        review_id=f"rvw:{item_id}",
        project_id=PROJECT,
        item_id=item_id,
        stakes=stakes,
        reason="figure caption did not yield a unit for the reported value",
        trace_id="trc:1",
        created_at=NOW,
    )


def test_a_low_confidence_extraction_creates_a_review_item_in_the_existing_queue(queue):
    """It goes in `review_items`. There is no second table."""
    db, review_queue, _policy = queue
    _enqueue(db, "itm:1")

    outstanding = review_queue.outstanding(PROJECT)
    assert len(outstanding) == 1
    assert outstanding[0].subject_type is ReviewSubjectType.EXTRACTION_UNCERTAINTY
    assert outstanding[0].subject_id == "itm:1"

    rows = db.execute(
        "SELECT count(*) FROM review_items WHERE subject_type = 'EXTRACTION_UNCERTAINTY'"
    ).fetchone()
    assert rows[0] == 1


def test_the_item_becomes_needs_review_because_the_queue_says_so(queue):
    """UX-001's NEEDS_REVIEW is derived from the *open* reviews, not from a flag on the item."""
    db, review_queue, _policy = queue
    _enqueue(db, "itm:1")

    item = IngestionItem(
        item_id="itm:1",
        project_id=PROJECT,
        actor_id="act:test",
        trace_id="trc:1",
        raw_artifact_id="art:raw",
        source_kind="UPLOAD",
        display_name="report.md",
        submitted_at=NOW,
        review_ids=("rvw:itm:1",),
    )
    open_ids = frozenset(r.review_id for r in review_queue.outstanding(PROJECT))
    assert derive_state(item, open_review_ids=open_ids) is ItemState.NEEDS_REVIEW


def test_it_measurably_changes_human_review_capability_availability(queue):
    """§14.4.1 / §26's "measurably changes". Before and after, same capability.

    Three assertions rather than one, because each could be satisfied alone by an implementation
    that did not really enqueue anything: depth rises, committed reviewer minutes rise, and the
    capability eventually reports unavailable when the queue fills.
    """
    db, review_queue, _policy = queue

    before = review_queue.capability(PROJECT, NOW)
    assert before.depth == 0
    assert before.available

    _enqueue(db, "itm:1")
    after = review_queue.capability(PROJECT, NOW)

    assert after.depth == before.depth + 1, "queue depth did not move"
    assert after.estimated_human_minutes > before.estimated_human_minutes, (
        "committed reviewer time did not move, so the planner still thinks review is free"
    )
    assert after.available, "one item of three should not exhaust the queue"

    for n in (2, 3):
        _enqueue(db, f"itm:{n}")
    full = review_queue.capability(PROJECT, NOW)
    assert full.depth == 3
    assert not full.available, "a queue at capacity still reported itself available"
    assert full.earliest_available_at > NOW


def test_the_extraction_review_is_swept_by_the_existing_expiry_path(queue):
    """OPS-002's expiry applies unchanged. A parallel surface would have needed its own sweeper
    -- and would have had none, so items would park in PENDING forever (§14.4)."""
    db, review_queue, policy = queue
    _enqueue(db, "itm:1")

    assert review_queue.overdue(PROJECT, NOW) == ()
    later = NOW + dt.timedelta(minutes=policy.expiry_minutes_for("MEDIUM") + 1)
    overdue = review_queue.overdue(PROJECT, later)
    assert len(overdue) == 1
    assert overdue[0].subject_type is ReviewSubjectType.EXTRACTION_UNCERTAINTY


def test_m0b_conflict_review_behaviour_is_unchanged(queue):
    """The claim "this extends rather than reopens", asserted.

    A conflict review and an extraction review sit in one queue, count toward one depth, and pool
    into one reviewer-time budget. If adding the vocabulary member had changed how M0b's items
    behave, this is where it would show.
    """
    db, review_queue, policy = queue
    # A real conflict, because `011b` requires a CONFLICT review's subject to resolve -- a review
    # pointing at nothing would sit in the queue describing a block nobody can find.
    db.execute(
        "INSERT INTO conflicts (conflict_id, project_id, conflict_type, resolution_status, "
        "blocking, subject_refs, detected_at, detected_by_actor_or_slot, trace_id) VALUES "
        "('cfl:1', %s, 'SIM_TO_REAL_CONFLICT', 'OPEN', TRUE, ARRAY['clm:1'], %s, 'act:test', "
        "'trc:1')",
        (PROJECT, NOW),
    )
    db.execute(
        "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes, "
        "reason, trace_id, created_at, queue_policy_id, queue_policy_version, due_at, "
        "expires_at, status, estimated_human_minutes) VALUES "
        "('rvw:conflict', %s, 'CONFLICT', 'cfl:1', 'HIGH', 'sim-to-real disagreement', 'trc:1', "
        "%s, 'rqp:test', '1.0.0', %s, %s, 'QUEUED', 45)",
        (
            PROJECT,
            NOW,
            policy.due_at(stakes="HIGH", created_at=NOW),
            policy.expires_at(stakes="HIGH", created_at=NOW),
        ),
    )
    _enqueue(db, "itm:1")

    outstanding = review_queue.outstanding(PROJECT)
    assert len(outstanding) == 2, "the two kinds are not sharing one queue"
    assert {r.subject_type for r in outstanding} == {
        ReviewSubjectType.CONFLICT,
        ReviewSubjectType.EXTRACTION_UNCERTAINTY,
    }
    capability = review_queue.capability(PROJECT, NOW)
    assert capability.depth == 2
    assert capability.estimated_human_minutes == 75, (
        "the two kinds are not pooling into one reviewer-time budget"
    )
    assert [r.review_id for r in outstanding] == sorted(r.review_id for r in outstanding)


def test_a_swept_extraction_review_leaves_the_queue(queue):
    """Depth must fall again, or availability never recovers and the signal becomes noise.

    Swept through OPS-002's `review_expire` rather than by assigning a terminal status:
    `v3.3-a14` requires a terminal review to record HOW it was resolved, and an extraction review
    nobody answers is exactly what 14.4's expiry path exists for. Using it here is also the proof
    that M0b's sweeper needed no change to handle the new subject type.
    """
    db, review_queue, policy = queue
    _enqueue(db, "itm:1")
    assert review_queue.depth(PROJECT) == 1

    later = NOW + dt.timedelta(minutes=policy.expiry_minutes_for("MEDIUM") + 1)
    # OPS-002's own sweeper, called with its own arguments. `review_expire` mints the
    # GovernanceEvent and the ReviewResolution itself -- `v3.3-a15`/`a16` require a closure to
    # belong to the chain it closes, so handing it a pre-built event would bypass the binding.
    db.execute(
        "SELECT review_expire(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "rres:sweep-1",
            "gov:sweep-1",
            "rvw:itm:1",
            PROJECT,
            "rqp:test",
            "1.0.0",
            "act:test",
            "SLA_ELAPSED",
            "nobody answered within the expiry window",
            later,
            "trc:1",
        ),
    )

    assert review_queue.depth(PROJECT) == 0
    assert review_queue.capability(PROJECT, later).available
    status = db.execute("SELECT status FROM review_items WHERE review_id = 'rvw:itm:1'").fetchone()
    assert status[0] == ReviewStatus.EXPIRED.value


def test_an_unknown_subject_type_is_still_refused(queue):
    """The vocabulary was EXTENDED, not opened.

    `011h` replaces the CHECK with a three-member one rather than dropping it. A free-text
    subject_type would let any future surface write whatever it liked into the one queue that
    prices human attention.
    """
    import psycopg

    db, _review_queue, policy = queue
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO review_items (review_id, project_id, subject_type, subject_id, stakes, "
            "reason, trace_id, created_at, queue_policy_id, queue_policy_version, due_at, "
            "expires_at, status) VALUES "
            "('rvw:bad', %s, 'SOMETHING_NEW', 'x', 'LOW', 'r', 'trc:1', %s, 'rqp:test', "
            "'1.0.0', %s, %s, 'QUEUED')",
            (
                PROJECT,
                NOW,
                policy.due_at(stakes="LOW", created_at=NOW),
                policy.expires_at(stakes="LOW", created_at=NOW),
            ),
        )


def test_the_enqueue_path_is_idempotent(queue):
    """A retrying ingestion worker must not consume reviewer capacity twice for one item.

    The second copy would be real queued work against a real capacity limit, and 14.4.1 prices
    human attention from exactly that depth -- so a duplicate makes the planner believe a
    reviewer is busier than they are.
    """
    db, review_queue, _policy = queue
    first = _enqueue(db, "itm:1")
    again = _enqueue(db, "itm:1")
    assert first == again
    assert review_queue.depth(PROJECT) == 1


def test_an_item_costing_no_reviewer_time_is_refused(queue):
    """A zero-cost review occupies a slot while telling the planner review is still free."""
    db, _review_queue, _policy = queue
    with pytest.raises(Exception, match="0 reviewer minutes"):
        SqlReviewItemStore(db).enqueue_extraction_review(
            review_id="rvw:free",
            project_id=PROJECT,
            item_id="itm:free",
            stakes="LOW",
            reason="r",
            trace_id="trc:1",
            created_at=NOW,
            estimated_minutes=0,
        )
