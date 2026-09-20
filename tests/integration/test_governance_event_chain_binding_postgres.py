"""A GovernanceEvent may only close the chain it was written for (`v3.3-a16`, migration `011g`).

WHAT `011f` LEFT OPEN, AND WHY NO TEST CAUGHT IT. `v3.3-a15` made the closure reference a typed
pair and `011f` checks it from both sides: the Conflict and the ReviewResolution must agree on
`(resolution_event_kind, resolution_event_id)`. That proves the two halves of a closure tell one
story. It does not prove the story is *this* review's, because nothing loaded the referenced
`GovernanceEvent` to ask. Every test that existed drove `ReviewExpiryProcessor`, which never asks
for the forbidden shape -- so the far end of the reference was exercised only by the happy path and
held by nothing. That is the P12 blank-rationale lesson for the fourth time, and it is why every
negative case below speaks SQL:

    Review A, Conflict A, QueuePolicy P   ->  GovernanceEvent G   (entirely legitimate)

    raw SQL then presents G as proof that review B expired:
        ReviewResolution B (EXPIRED, governance_event_id = G)
        Review B   -> EXPIRED
        Conflict B -> ACCEPTED_AS_OPEN_QUESTION, governance_event_id = G

Before `011g` that committed. Same project, same policy, a real REVIEW_EXPIRY event -- and a block
lifted on an authority that was never granted for it. `test_a_governance_event_cannot_be_reused_to`
`_expire_a_second_review` is that exact construction, and it is the reason this module exists.

ONE PERTURBATION PER TEST, FROM ONE BASELINE. `_expiry_event` returns the event `review_expire`
would itself have written for an item; each negative test overrides exactly one field and asserts
the commit is refused. A test that changed two fields would pass while either guard held, which is
how a guard ends up exercised by a test that does not depend on it.
`test_a_correct_chain_built_entirely_by_hand_commits` is the positive control: without it, a
migration that refused every governance closure outright would turn this whole module green.

WHY COMMIT IS THE BOUNDARY. `011d`'s reasoning, unchanged: the one valid operation necessarily
passes through a state that reads like a violation, because `review_expire` terminalizes the review
before it closes the conflict. So the obligation is about what survives COMMIT, and every bypass
below runs on a non-autocommit connection and asserts on `commit()`.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterator, Mapping

import psycopg
import pytest

from lab_brain.core.models.conflict import Conflict, ConflictType
from lab_brain.core.models.review import ReviewItem, ReviewSubjectType
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore, SqlReviewQueuePolicyStore
from lab_brain.core.review_expiry import DefaultExpiryIdSource, ReviewExpiryProcessor
from lab_brain.core.review_queue import ReviewQueuePolicy
from tests.postgres_fixtures import DEFAULT_URL

#: ONE PAIR, FOR THE REASON `test_review_conflict_commit_invariant_postgres.py` STATES. Markers
#: multiply out, so declaring OPS-002 here as well would claim (OPS-002, T-EPI-006) -- a pair §26
#: does not map. T-EPI-006 is the honest single mapping: its §26 row is the one that says closing a
#: Conflict without a resolution event is rejected, and `v3.3-a16` is what makes "a resolution
#: event" mean "the event this review's resolution produced" rather than any event of the right
#: shape. OPS-002's side of the amendment -- who may execute an expiry at all -- is exercised under
#: its own pair in `test_review_expiry_postgres.py`.
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-006"),
    pytest.mark.spec_test("T-EPI-006"),
]

T0 = dt.datetime(2026, 9, 19, 9, 0, tzinfo=dt.UTC)
#: Well past the 48h HIGH expiry below, so every sweep here is genuinely overdue.
LATER = T0 + dt.timedelta(days=5)
PROJECT = "prj:test"
OTHER = "prj:other"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:chain-binding"

#: The professor who declared the SLA -- the standing authority for every expiry below.
DECLARER = "act:test"
#: The process that executes the sweep.
EXECUTOR = "act:sweeper"
#: A second real, active actor. Used only to substitute for one of the two above, so that each
#: refusal is about the *wrong* actor rather than about an unknown one (which the FK already
#: refuses, and which would prove a different guard).
BYSTANDER = "act:bystander"

_POLICY = ReviewQueuePolicy(
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

_GOVERNANCE_EVENT_COLUMNS = (
    "event_id",
    "project_id",
    "event_type",
    "subject_type",
    "subject_id",
    "related_conflict_id",
    "policy_id",
    "policy_version",
    "declared_by_actor_id",
    "actor_id",
    "reason_code",
    "rationale",
    "occurred_at",
    "trace_id",
    "episode_id",
)


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """Two projects, three actors and three queue policy versions.

    The two inactive extra policies exist so a substitution can cite a policy that genuinely
    *exists* -- `governance_events_policy_in_project` already refuses one that does not, and a test
    that tripped that foreign key would prove the composite FK rather than the version binding.
    """
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name)"
        " VALUES (%s, 'SERVICE', 'Expiry sweeper') ON CONFLICT DO NOTHING",
        (EXECUTOR,),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name)"
        " VALUES (%s, 'HUMAN', 'A colleague who declared nothing') ON CONFLICT DO NOTHING",
        (BYSTANDER,),
    )
    policies = SqlReviewQueuePolicyStore(db)
    policies.register(_POLICY)
    # A different policy, and a different version of the same policy. Same declarer on both, so a
    # test that swaps the policy perturbs the policy and nothing else.
    policies.register(_POLICY.model_copy(update={"policy_id": "rqp:other", "active": False}))
    policies.register(_POLICY.model_copy(update={"version": "2.0.0", "active": False}))
    policies.register(
        _POLICY.model_copy(update={"project_id": OTHER, "policy_id": "rqp:elsewhere"})
    )
    return db


@pytest.fixture
def raw(db) -> Iterator[psycopg.Connection]:  # type: ignore[no-untyped-def]
    """A transactional session: `commit()` is the boundary under test.

    Rolled back and **closed** on teardown rather than merely rolled back -- the `db` fixture opens
    the next test with a TRUNCATE, which needs an ACCESS EXCLUSIVE lock, and a session still
    holding a read lock would hang the suite rather than fail it.
    """
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), connect_timeout=5
    )
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _escalate(  # type: ignore[no-untyped-def]
    world, review_id: str, conflict_id: str, project_id: str = PROJECT
) -> ReviewItem:
    """A conflict and its gating review, through the real escalation path.

    Not written by hand: the item has to be *priced* by a declared policy for its expiry to be
    legitimate at all, and `authority_conflict_escalate` is what does that.
    """
    store = SqlConflictStore(world)
    store.record(
        Conflict(
            conflict_id=conflict_id,
            project_id=project_id,
            conflict_type=ConflictType.AUTHORITY_CONFLICT,
            subject_refs=(HYP,),
            blocking=True,
            detected_at=T0,
            detected_by_actor_or_slot=DECLARER,
            trace_id=TRACE,
        )
    )
    return SqlReviewItemStore(world).escalate_authority_conflict(
        conflict=store.get(project_id, conflict_id),  # type: ignore[arg-type]
        review=ReviewItem(
            review_id=review_id,
            project_id=project_id,
            subject_type=ReviewSubjectType.AUTHORITY_CONFLICT,
            subject_id=conflict_id,
            stakes="HIGH",
            reason="AUTHORITY_INCOMPARABLE",
            trace_id=TRACE,
            created_at=T0,
            estimated_human_minutes=30,
        ),
    )


def _sweep(connection, project_id: str = PROJECT):  # type: ignore[no-untyped-def]
    """The production caller, used only to manufacture a *legitimate* event to then misuse."""
    return ReviewExpiryProcessor(reviews=SqlReviewItemStore(connection)).sweep(
        project_id=project_id, now=LATER, actor_id=EXECUTOR, trace_id="trc:sweep"
    )


def _expiry_event(review: ReviewItem, conflict_id: str | None, event_id: str) -> dict[str, object]:
    """The GovernanceEvent `review_expire` would have written for this item.

    Returned as a mapping so a test can override exactly one key. Keeping the baseline correct is
    what makes each negative case a statement about one binding rather than about whichever
    mismatch the database happened to notice first.
    """
    return {
        "event_id": event_id,
        "project_id": review.project_id,
        "event_type": "REVIEW_EXPIRY",
        "subject_type": "REVIEW_ITEM",
        "subject_id": review.review_id,
        "related_conflict_id": conflict_id,
        "policy_id": review.queue_policy_id,
        "policy_version": review.queue_policy_version,
        "declared_by_actor_id": DECLARER,
        "actor_id": EXECUTOR,
        "reason_code": "REVIEW_SLA_EXPIRED",
        "rationale": "written by hand, to perturb exactly one binding at a time",
        "occurred_at": LATER,
        "trace_id": TRACE,
        "episode_id": review.episode_id,
    }


def _close_by_hand(
    cursor,  # type: ignore[no-untyped-def]
    *,
    review: ReviewItem,
    conflict_id: str,
    event: Mapping[str, object] | None,
    event_id: str,
    resolution_id: str = "res:by-hand",
    resolved_by_actor_id: str = EXECUTOR,
) -> None:
    """The four writes `review_expire` makes, made instead by raw SQL.

    Deliberately *not* `review_expire` and *not* `conflict_close`. Both already refuse most of
    what is attempted here, and a test that went through them would re-prove the two functions that
    were already right -- the bug was everything that reaches the tables without them.

    `event=None` skips the event insert, for the cases that reuse one written earlier.
    """
    if event is not None:
        cursor.execute(
            f"INSERT INTO governance_events ({', '.join(_GOVERNANCE_EVENT_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_GOVERNANCE_EVENT_COLUMNS))})",
            tuple(event[column] for column in _GOVERNANCE_EVENT_COLUMNS),
        )
    cursor.execute(
        "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
        " resolved_by_actor_id, resolved_at, rationale, governance_event_id,"
        " resolution_event_kind) VALUES (%s, %s, %s, 'EXPIRED', %s, %s, %s, %s, 'GOVERNANCE')",
        (
            resolution_id,
            review.review_id,
            review.project_id,
            resolved_by_actor_id,
            LATER,
            "the deadline passed with no human answer",
            event_id,
        ),
    )
    cursor.execute(
        "UPDATE review_items SET status = 'EXPIRED', decision_ref = %s"
        " WHERE review_id = %s AND project_id = %s",
        (resolution_id, review.review_id, review.project_id),
    )
    cursor.execute(
        "UPDATE conflicts SET resolution_status = 'ACCEPTED_AS_OPEN_QUESTION',"
        " resolution_event_kind = 'GOVERNANCE', governance_event_id = %s, resolved_at = %s"
        " WHERE conflict_id = %s AND project_id = %s",
        (event_id, LATER, conflict_id, review.project_id),
    )


def _forbidden_pairs(world) -> list[tuple[str, ...]]:  # type: ignore[no-untyped-def]
    """`011d`'s invariant, scanned directly. Must be empty after every test, refused or not.

    "The write failed" and "the database is still consistent" are different claims, and only the
    second one matters.
    """
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
# A. The missed P0, end to end: one review's event presented as another's closure proof.
# --------------------------------------------------------------------------------------------


def test_a_governance_event_cannot_be_reused_to_expire_a_second_review(world, raw):
    """The substitution `011f` committed, and the reason `011g` exists.

    Review A expires through the production caller, so its event is beyond reproach: right project,
    right policy, right declarer, a real `REVIEW_EXPIRY` written by `review_expire` itself. Raw SQL
    then hands that same event to review B as proof that B lapsed. Nothing about the event is
    forged; what is forged is the claim that it is about B.
    """
    first = _escalate(world, "rvw:1", "cfl:1")
    second = _escalate(world, "rvw:2", "cfl:2")

    # `limit=1` and nothing else: `overdue()` orders on `(expires_at, review_id)`, so review A
    # expires legitimately and review B is left outstanding with no event of its own to confuse
    # the construction. Both rows are otherwise identical, which is what makes the substitution
    # plausible enough to be worth refusing.
    swept = ReviewExpiryProcessor(reviews=SqlReviewItemStore(world)).sweep(
        project_id=PROJECT, now=LATER, actor_id=EXECUTOR, trace_id="trc:sweep", limit=1
    )
    assert [event.subject_id for event in swept.expired] == [first.review_id]
    assert SqlReviewItemStore(world).get(PROJECT, second.review_id).is_outstanding  # type: ignore[union-attr]

    borrowed = DefaultExpiryIdSource().governance_event_id(first.review_id)

    with raw.cursor() as cursor:
        _close_by_hand(cursor, review=second, conflict_id="cfl:2", event=None, event_id=borrowed)

    with pytest.raises(psycopg.errors.RaiseException, match="was written for review rvw:1"):
        raw.commit()
    raw.rollback()

    review = SqlReviewItemStore(world).get(PROJECT, second.review_id)
    assert review is not None and review.is_outstanding, "the borrowed authority must not expire it"
    assert SqlConflictStore(world).get(PROJECT, "cfl:2").blocks_transitions  # type: ignore[union-attr]
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 1
    assert _forbidden_pairs(world) == []


# --------------------------------------------------------------------------------------------
# B-G. One binding perturbed at a time, from a baseline that is otherwise exactly right.
# --------------------------------------------------------------------------------------------


def test_an_event_naming_another_review_as_its_subject_is_refused(world, raw):
    """B. `subject_id` names review A while the closure terminalizes review B.

    The same guard test A reaches, isolated: everything else on the event -- project, conflict,
    policy version, declarer, executor -- is correct for review B. Only the subject is another
    review's, which is the whole of what "this event is not about you" means.
    """
    _escalate(world, "rvw:1", "cfl:1")
    target = _escalate(world, "rvw:2", "cfl:2")

    event = _expiry_event(target, "cfl:2", "gev:substituted-subject")
    event["subject_id"] = "rvw:1"

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor,
            review=target,
            conflict_id="cfl:2",
            event=event,
            event_id="gev:substituted-subject",
        )

    with pytest.raises(psycopg.errors.RaiseException, match="was written for review rvw:1"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_an_event_naming_another_reviews_conflict_is_refused(world, raw):
    """C. `related_conflict_id` names conflict A while the closure targets conflict B.

    An expiry closes the block its own review was raised for. Naming another review's conflict
    claims an authority this deadline never carried -- and it is the field a reader would consult
    to find out which block lifted.
    """
    _escalate(world, "rvw:1", "cfl:1")
    target = _escalate(world, "rvw:2", "cfl:2")

    event = _expiry_event(target, "cfl:1", "gev:substituted-conflict")

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor,
            review=target,
            conflict_id="cfl:2",
            event=event,
            event_id="gev:substituted-conflict",
        )

    with pytest.raises(psycopg.errors.RaiseException, match="which review rvw:2 does not gate"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_an_event_that_claims_it_closed_nothing_cannot_close_a_conflict(world, raw):
    """C, the other direction. The review gates a conflict; the event names none.

    Not benign, and worth its own case because it reads as an omission rather than a substitution:
    the conflict cites this event as the reason its block lifted, while the event says it lifted
    nothing. Whichever row a later reader consults, the other contradicts it.
    """
    target = _escalate(world, "rvw:1", "cfl:1")

    event = _expiry_event(target, None, "gev:closed-nothing")

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor, review=target, conflict_id="cfl:1", event=event, event_id="gev:closed-nothing"
        )

    with pytest.raises(psycopg.errors.RaiseException, match="that event says it closed"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_an_event_citing_a_different_queue_policy_is_refused(world, raw):
    """D. A real policy in the right project, simply not the one this item was priced by.

    `rqp:other` exists and has the same declarer, so the only thing wrong is that it is not the
    standing decision that gave this reviewer their deadline.
    """
    target = _escalate(world, "rvw:1", "cfl:1")

    event = _expiry_event(target, "cfl:1", "gev:wrong-policy")
    event["policy_id"] = "rqp:other"

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor, review=target, conflict_id="cfl:1", event=event, event_id="gev:wrong-policy"
        )

    with pytest.raises(psycopg.errors.RaiseException, match="cites policy rqp:other"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_an_event_citing_a_different_version_of_the_right_policy_is_refused(world, raw):
    """E. The right policy, the wrong version.

    The narrower and more dangerous half of D: `rqp:lab@2.0.0` is the same standing decision after
    the lab revised it, and citing it retroactively is how an expiry under a deadline the reviewer
    never saw would be made to look legitimate. `review_expire` refuses this for callers who go
    through it; this is the same rule for a writer who did not.
    """
    target = _escalate(world, "rvw:1", "cfl:1")

    event = _expiry_event(target, "cfl:1", "gev:wrong-version")
    event["policy_version"] = "2.0.0"

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor, review=target, conflict_id="cfl:1", event=event, event_id="gev:wrong-version"
        )

    with pytest.raises(psycopg.errors.RaiseException, match=r"cites policy rqp:lab@2\.0\.0"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_an_event_naming_the_wrong_policy_declarer_is_refused(world, raw):
    """F. `declared_by_actor_id` is a real, active actor -- just not the one who declared it.

    §17.19.1 forbids inferring the standing authority from the executor. Restating it on the event
    is the same failure arrived at by writing it down: a sweep would look authorised by somebody who
    declared nothing, and the policy row that actually carries the authority says otherwise.
    """
    target = _escalate(world, "rvw:1", "cfl:1")

    event = _expiry_event(target, "cfl:1", "gev:wrong-declarer")
    event["declared_by_actor_id"] = BYSTANDER

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor, review=target, conflict_id="cfl:1", event=event, event_id="gev:wrong-declarer"
        )

    with pytest.raises(psycopg.errors.RaiseException, match="was declared by act:bystander"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


def test_a_resolution_crediting_a_different_actor_than_the_event_is_refused(world, raw):
    """G. The event says the sweeper ran it; the resolution says somebody else resolved it.

    Two accounts of who is accountable for this expiry. Whichever a reader consulted first would
    name the responsible party, and only one of them can be right.
    """
    target = _escalate(world, "rvw:1", "cfl:1")

    event = _expiry_event(target, "cfl:1", "gev:split-actor")

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor,
            review=target,
            conflict_id="cfl:1",
            event=event,
            event_id="gev:split-actor",
            resolved_by_actor_id=BYSTANDER,
        )

    with pytest.raises(psycopg.errors.RaiseException, match="was executed by act:sweeper"):
        raw.commit()
    raw.rollback()
    assert _forbidden_pairs(world) == []


# --------------------------------------------------------------------------------------------
# H. Cross-project reuse, which is unrepresentable rather than merely refused.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("half", "constraint"),
    [
        ("resolution", "review_resolutions_governance_event_in_project"),
        ("conflict", "conflicts_governance_event_in_project"),
    ],
)
def test_an_event_from_another_project_cannot_be_cited_at_all(world, raw, half, constraint):
    """H. SEC-002, held by a composite foreign key rather than by a check.

    Both references are `(event_id, project_id)` together, so an event in one project cannot be
    named from another -- refused on the statement rather than surviving to COMMIT. "Unrepresentable"
    is a stronger claim than "refused" and deserves demonstrating rather than assuming.

    PARAMETRIZED BECAUSE THE FIRST VERSION OF THIS TEST WAS NOT, AND THAT WAS THE BUG. It drove the
    whole four-statement closure and asserted on a message matching `governance_event_in_project`,
    which **both** constraint names contain. Relaxing either one on its own therefore left the test
    green, because the other still fired -- a test that proves "one of these two holds" while
    reading as though it proves both. Each half is now attempted alone, against its own constraint
    name, so relaxing either is individually red.
    """
    _escalate(world, "rvw:1", "cfl:1")
    assert _sweep(world).count == 1
    elsewhere = DefaultExpiryIdSource().governance_event_id("rvw:1")

    target = _escalate(world, "rvw:other", "cfl:other", project_id=OTHER)

    with (
        raw.cursor() as cursor,
        pytest.raises(psycopg.errors.ForeignKeyViolation, match=constraint),
    ):
        if half == "resolution":
            cursor.execute(
                "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
                " resolved_by_actor_id, resolved_at, rationale, governance_event_id,"
                " resolution_event_kind)"
                " VALUES ('res:cross', %s, %s, 'EXPIRED', %s, %s, 'r', %s, 'GOVERNANCE')",
                (target.review_id, OTHER, EXECUTOR, LATER, elsewhere),
            )
        else:
            cursor.execute(
                "UPDATE conflicts SET resolution_status = 'ACCEPTED_AS_OPEN_QUESTION',"
                " resolution_event_kind = 'GOVERNANCE', governance_event_id = %s, resolved_at = %s"
                " WHERE conflict_id = 'cfl:other' AND project_id = %s",
                (elsewhere, LATER, OTHER),
            )
    raw.rollback()

    review = SqlReviewItemStore(world).get(OTHER, "rvw:other")
    assert review is not None and review.is_outstanding
    assert _forbidden_pairs(world) == []


# --------------------------------------------------------------------------------------------
# I. The positive control. Without it, refusing everything would look like success.
# --------------------------------------------------------------------------------------------


def test_a_correct_chain_built_entirely_by_hand_commits(world, raw):
    """I. Every binding satisfied, written by raw SQL rather than by `review_expire`.

    This is what stops the migration above from being a blanket refusal of governance closures --
    the failure mode a suite of nine negative tests cannot detect on its own. It also pins the
    contract as *structural*: a writer that gets the chain right is not required to go through the
    supported function, only to produce what that function would have produced.
    """
    target = _escalate(world, "rvw:1", "cfl:1")
    event = _expiry_event(target, "cfl:1", "gev:by-hand")

    with raw.cursor() as cursor:
        _close_by_hand(
            cursor, review=target, conflict_id="cfl:1", event=event, event_id="gev:by-hand"
        )
    raw.commit()

    store = SqlReviewItemStore(world)
    review = store.get(PROJECT, "rvw:1")
    assert review is not None and not review.is_outstanding

    resolution = store.resolution_for(PROJECT, "rvw:1")
    assert resolution is not None and resolution.governance_event_id == "gev:by-hand"
    assert not resolution.settled_the_question

    conflict_row = world.execute(
        "SELECT resolution_status, resolution_event_kind, governance_event_id FROM conflicts"
        " WHERE conflict_id = 'cfl:1'"
    ).fetchone()
    assert conflict_row == ("ACCEPTED_AS_OPEN_QUESTION", "GOVERNANCE", "gev:by-hand")
    assert _forbidden_pairs(world) == []


def test_the_production_sweep_still_produces_a_chain_the_invariant_accepts(world):
    """The other positive control, and the one that matters operationally.

    `011g` tightened the commit boundary around a path nothing else exercises unattended. If the
    new bindings and what `review_expire` writes ever disagree, every sweep in production starts
    failing at COMMIT -- so the supported path is asserted against the tightened invariant directly.
    """
    _escalate(world, "rvw:1", "cfl:1")
    _escalate(world, "rvw:2", "cfl:2")

    result = _sweep(world)

    assert result.count == 2 and not result.refused
    assert {event.subject_id for event in result.expired} == {"rvw:1", "rvw:2"}
    assert all(event.declared_by_actor_id == DECLARER for event in result.expired)
    assert all(event.actor_id == EXECUTOR for event in result.expired)
    assert _forbidden_pairs(world) == []


# --------------------------------------------------------------------------------------------
# The row-local half: an expiry names the authority it executed.
# --------------------------------------------------------------------------------------------


def test_an_expiry_event_with_no_declared_authority_is_refused(world):
    """`v3.3-a16`: `declared_by_actor_id` is required on a REVIEW_EXPIRY.

    `v3.3-a15` made `review_queue_policies.declared_by_actor_id` NOT NULL, so a correct value
    always exists for this event type and an absent one can only mean the writer declined to record
    it -- leaving the executing service account as the only actor on the row, which is exactly the
    inference §17.19.1 forbids.
    """
    target = _escalate(world, "rvw:1", "cfl:1")
    event = _expiry_event(target, "cfl:1", "gev:anonymous")
    event["declared_by_actor_id"] = None

    with pytest.raises(psycopg.errors.CheckViolation, match="expiry_names_its_authority"):
        world.execute(
            f"INSERT INTO governance_events ({', '.join(_GOVERNANCE_EVENT_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_GOVERNANCE_EVENT_COLUMNS))})",
            tuple(event[column] for column in _GOVERNANCE_EVENT_COLUMNS),
        )
    assert world.execute("SELECT count(*) FROM governance_events").fetchone()[0] == 0


def test_the_model_refuses_an_expiry_that_names_no_declared_authority():
    """The same rule in the model, which catches it earlier and explains it."""
    from lab_brain.core.models.governance_event import (
        GovernanceEvent,
        GovernanceEventType,
        GovernanceSubjectType,
    )

    with pytest.raises(ValueError, match="without naming who declared"):
        GovernanceEvent(
            event_id="gev:anonymous",
            project_id=PROJECT,
            event_type=GovernanceEventType.REVIEW_EXPIRY,
            subject_type=GovernanceSubjectType.REVIEW_ITEM,
            subject_id="rvw:1",
            policy_id="rqp:lab",
            policy_version="1.0.0",
            actor_id=EXECUTOR,
            reason_code="REVIEW_SLA_EXPIRED",
            occurred_at=LATER,
            trace_id=TRACE,
        )


def test_a_blank_declared_authority_is_refused_by_the_model_too():
    """A required field satisfied by an empty string is an optional field with extra steps.

    The P12 blank-rationale finding, applied to the field that carries the standing authority.
    """
    from lab_brain.core.models.governance_event import (
        GovernanceEvent,
        GovernanceEventType,
        GovernanceSubjectType,
    )

    with pytest.raises(ValueError, match="without naming who declared"):
        GovernanceEvent(
            event_id="gev:blank",
            project_id=PROJECT,
            event_type=GovernanceEventType.REVIEW_EXPIRY,
            subject_type=GovernanceSubjectType.REVIEW_ITEM,
            subject_id="rvw:1",
            policy_id="rqp:lab",
            policy_version="1.0.0",
            declared_by_actor_id="   ",
            actor_id=EXECUTOR,
            reason_code="REVIEW_SLA_EXPIRED",
            occurred_at=LATER,
            trace_id=TRACE,
        )
