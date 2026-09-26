"""`v3.3-a14`'s cross-table invariant holds at the COMMIT boundary, against raw SQL (migration `011d`).

WHAT THE P12 AUDIT FOUND, AND WHY THESE TESTS LOOK THE WAY THEY DO. `011c` made
`review_resolve_and_close_conflict` the supported path and taught `conflict_close` to consult the
linked review. Both are correct, and every guard it added lives *inside a function* -- so a writer
who does not call the function is not guarded. Both half-states §17.19.1 forbids were still
reachable, and were demonstrated committing on a database migrated through `011c`:

    P0-A  INSERT a valid review_resolutions row, then
          UPDATE review_items SET status='APPROVED', decision_ref='<resolution>'
          -> committed, with the linked conflict still UNDER_REVIEW.

    P0-B  UPDATE conflicts SET resolution_status='RESOLVED', resolution_event_id=..., resolved_at=...
          -> committed, with the linked review still QUEUED.

**Nothing below goes through a repository, except the one test that is supposed to.** Tests that
called `SqlConflictStore` or `SqlReviewItemStore` would exercise `conflict_close` and
`review_resolve_and_close_conflict` again -- the two functions that were already right. The bug was
everything that reaches the tables without them, so these speak SQL.

WHY EVERY BYPASS RUNS ON A NON-AUTOCOMMIT CONNECTION. The obligation is about what survives COMMIT,
not about what any single statement leaves behind, and the distinction is load-bearing rather than
pedantic: the one *valid* operation necessarily passes through P0-A's exact shape, because
`review_resolve_and_close_conflict` terminalizes the review before it closes the conflict. A
per-statement trigger would refuse the only correct way to do this. So the tests drive an explicit
transaction and assert on `commit()` -- and `test_an_intermediate_half_state_inside_one_transaction_is_allowed`
asserts the other side of that, which is the part a stricter-looking implementation would break.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import os
import threading
from collections.abc import Iterator

import psycopg
import pytest

from tests.conftest_fixtures import make_artifact
from tests.postgres_fixtures import DEFAULT_URL, admit_hypothesis_identity

#: ONE PAIR, THOUGH THE INVARIANT SPANS TWO REQUIREMENTS. Markers multiply out, so declaring both
#: EPI-004 and EPI-006 here would claim (EPI-004, T-EPI-006) -- a pair §26 does not map, and
#: T-SPEC-001 says so. T-EPI-006 is the honest single mapping: its §26 row is the one that names
#: "a Conflict linked to the auto-created ReviewItem" and "resolving a Conflict without a
#: resolution_event_id is rejected", which is what every test below is about. EPI-004's side of the
#: same invariant -- the belief staying blocked until the review resolves -- is exercised under its
#: own pair in tests/e2e/test_authority_review_loop_postgres.py.
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-006"),
    pytest.mark.spec_test("T-EPI-006"),
]

T0 = dt.datetime(2026, 9, 16, 11, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
OTHER = "prj:other"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:commit-invariant"

#: The pair §17.19.1 forbids, in both directions, as one query. Every test ends by asserting this
#: is empty -- including the tests where the transaction was refused, because "the write failed"
#: and "the database is still consistent" are different claims and only the second one matters.
_FORBIDDEN_PAIRS = """
SELECT r.review_id, r.status, c.conflict_id, c.resolution_status
  FROM conflicts c
  JOIN review_items r ON r.review_id = c.review_id AND r.project_id = c.project_id
 WHERE (r.status IN ('QUEUED', 'ASSIGNED')
        AND c.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW'))
    OR (r.status NOT IN ('QUEUED', 'ASSIGNED')
        AND c.resolution_status IN ('OPEN', 'UNDER_REVIEW'))
"""


def _url() -> str:
    return os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL)


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
            # `v3.3-a15`: the standing authority an automatic expiry executes. Required,
            # and never inferred from whoever runs the sweep.
            declared_by_actor_id="act:test",
            effective_from=T0,
        )
    )


@pytest.fixture
def raw(db) -> Iterator[psycopg.Connection]:  # type: ignore[no-untyped-def]
    """A transactional session: `commit()` is the boundary under test.

    Rolled back and **closed** on teardown rather than merely rolled back. The `db` fixture opens
    the next test with a TRUNCATE, which needs an ACCESS EXCLUSIVE lock -- a session left holding
    even a read lock would hang the suite rather than fail it.
    """
    connection = psycopg.connect(_url(), connect_timeout=5)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def second(db) -> Iterator[psycopg.Connection]:  # type: ignore[no-untyped-def]
    """A genuinely separate autocommit session, so the concurrency tests are races."""
    connection = psycopg.connect(_url(), autocommit=True, connect_timeout=5)
    try:
        yield connection
    finally:
        connection.close()


def _event(db, event_id: str, project: str = PROJECT) -> str:  # type: ignore[no-untyped-def]
    """A real `BeliefRevisionEvent`, since every closure reference is a composite foreign key."""
    # M3 / R-12 (`011j`): the target is admitted first, in the event's project.
    admit_hypothesis_identity(db, f"hyp:{event_id}", project_id=project)
    db.execute(
        "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, NULL, 'ACTIVE',"
        " %s, ARRAY[]::text[], %s, '1.0.0', NULL, NULL, NULL, %s, %s, NULL)",
        (
            event_id,
            project,
            f"hyp:{event_id}",
            [f"att:{project}"],
            f"pol:genesis-{project}",
            T0,
            TRACE,
        ),
    )
    return event_id


def _conflict(db, conflict_id: str, project: str = PROJECT) -> str:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO conflicts (conflict_id, project_id, conflict_type, resolution_status,"
        " blocking, subject_refs, detected_at, detected_by_actor_or_slot, trace_id)"
        " VALUES (%s, %s, 'AUTHORITY_CONFLICT', 'OPEN', TRUE, ARRAY[%s], %s, 'act:test', %s)",
        (conflict_id, project, HYP, T0, TRACE),
    )
    return conflict_id


def _escalate(db, review_id: str, conflict_id: str, project: str = PROJECT) -> str:  # type: ignore[no-untyped-def]
    """Through the migration function, because this is setup rather than the thing under test."""
    return str(
        db.execute(
            "SELECT authority_conflict_escalate(%s, %s, %s, 'HIGH', 'AUTHORITY_INCOMPARABLE',"
            " %s, %s, 'TIER_A', NULL, 30)",
            (review_id, conflict_id, project, TRACE, T0),
        ).fetchone()[0]
    )


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """One project with an attestation and a genesis policy, plus a second project for SEC-002.

    No pre-created resolution and no pre-created closure event beyond the ones each test names.
    P11's fixture built a `BeliefRevisionEvent` before any escalation existed, and that is how an
    unrelated event came to stand in for a review's resolution.
    """
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    # M3 / R-12 (`011j`): a belief event names a hypothesis admitted through §8's gate in its own
    # project, so the identity this fixture always meant is established first.
    admit_hypothesis_identity(db, HYP, project_id=PROJECT)
    admit_hypothesis_identity(db, HYP, project_id=OTHER)
    artifact = make_artifact(b"a commit-invariant fixture")
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
    for project in (PROJECT, OTHER):
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type,"
            " source_artifact_id, locator, conditions, conditions_schema_version, project_id,"
            " extractor_version, extraction_provenance)"
            " VALUES (%s, 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb, 'core/sch_test@1.0.0',"
            " %s, '1.0.0', %s::jsonb)",
            (
                f"att:{project}",
                artifact.artifact_id,
                project,
                '{"extractor_id": "ext:t", "extractor_version": "1.0.0"}',
            ),
        )
        db.execute(
            "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state,"
            " is_admission) VALUES (%s, '1.0.0', 'DRAFT', 'ACTIVE', TRUE) ON CONFLICT DO NOTHING",
            (f"pol:genesis-{project}",),
        )
    _queue_policy(db, PROJECT)
    _queue_policy(db, OTHER, policy_id="rqp:other")
    return db


@pytest.fixture
def escalated(world):  # type: ignore[no-untyped-def]
    """`cfl:1` blocked, `rvw:1` QUEUED and linked, and `bre:1` available as a resolution event."""
    _conflict(world, "cfl:1")
    _escalate(world, "rvw:1", "cfl:1")
    _event(world, "bre:1")
    return world


def _resolution(cursor, resolution_id: str, review_id: str, outcome: str, event_id: str) -> None:
    cursor.execute(
        "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
        " resolved_by_actor_id, resolved_at, rationale, belief_revision_event_id)"
        " VALUES (%s, %s, %s, %s, 'act:test', %s, 'the reviewer looked and decided', %s)",
        (resolution_id, review_id, PROJECT, outcome, T0, event_id),
    )


def _close_conflict(cursor, conflict_id: str, event_id: str, status: str = "RESOLVED") -> None:
    """A bare UPDATE. This is the write `conflict_close` exists to mediate and cannot compel."""
    cursor.execute(
        "UPDATE conflicts SET resolution_status = %s, resolution_event_id = %s, resolved_at = %s,"
        " resolution_event_kind = 'BELIEF_REVISION' WHERE conflict_id = %s",
        (status, event_id, T0, conflict_id),
    )


def _assert_consistent(db) -> None:  # type: ignore[no-untyped-def]
    offending = db.execute(_FORBIDDEN_PAIRS).fetchall()
    assert offending == [], f"a state §17.19.1 forbids survived: {offending}"


# --------------------------------------------------------------------------------------------
# 1-2. P0-B: an outstanding review beside a closed conflict.
#
# `conflict_close` refuses this and is not the only writer. Both outstanding statuses are tested:
# ASSIGNED is the one most likely to be read as handled, because somebody is visibly on it.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("review_status", ["QUEUED", "ASSIGNED"])
@pytest.mark.parametrize("conflict_status", ["RESOLVED", "ACCEPTED_AS_OPEN_QUESTION", "EXPIRED"])
def test_raw_sql_cannot_commit_a_closed_conflict_behind_an_outstanding_review(
    escalated, raw, review_status, conflict_status
):
    """P0-B. Every closing status, against both outstanding statuses.

    All three conflict statuses stop a conflict blocking, so a per-status exemption here would be
    the same mistake the P10 audit found in the closure-event rule: the exemption becomes the path.
    """
    with raw.cursor() as cursor:
        if review_status == "ASSIGNED":
            cursor.execute(
                "UPDATE review_items SET status = 'ASSIGNED', assigned_actor_id = 'act:test'"
                " WHERE review_id = 'rvw:1'"
            )
        _close_conflict(cursor, "cfl:1", "bre:1", conflict_status)

    with pytest.raises(psycopg.errors.RaiseException, match=r"is still (QUEUED|ASSIGNED)"):
        raw.commit()

    raw.rollback()
    assert (
        escalated.execute(
            "SELECT resolution_status FROM conflicts WHERE conflict_id = 'cfl:1'"
        ).fetchone()[0]
        == "UNDER_REVIEW"
    ), "the block must still be in place"
    _assert_consistent(escalated)


# --------------------------------------------------------------------------------------------
# 3. P0-A: a terminal review beside an unresolved conflict.
# --------------------------------------------------------------------------------------------


def test_raw_sql_cannot_commit_a_terminal_review_while_its_conflict_stays_unresolved(
    escalated, raw
):
    """P0-A, exactly as the audit wrote it.

    The resolution row is *valid* -- correct review, correct project, real event, an outcome the
    vocabulary allows. `review_items_terminal_needs_a_decision` is satisfied, because it asks only
    whether a terminal review has a `decision_ref`. Nothing in `011c` looks at the conflict from
    this direction, and the reviewer's answer would have committed with the belief still blocked.
    """
    with raw.cursor() as cursor:
        _resolution(cursor, "res:1", "rvw:1", "APPROVED", "bre:1")
        cursor.execute(
            "UPDATE review_items SET status = 'APPROVED', decision_ref = 'res:1'"
            " WHERE review_id = 'rvw:1'"
        )

    with pytest.raises(psycopg.errors.RaiseException, match="is still UNDER_REVIEW"):
        raw.commit()

    raw.rollback()
    assert (
        escalated.execute("SELECT status FROM review_items WHERE review_id = 'rvw:1'").fetchone()[0]
        == "QUEUED"
    )
    assert (
        escalated.execute(
            "SELECT count(*) FROM review_resolutions WHERE resolution_id = 'res:1'"
        ).fetchone()[0]
        == 0
    ), "the refused transaction must leave no resolution row behind"
    _assert_consistent(escalated)


# --------------------------------------------------------------------------------------------
# 4-6. The terminal side is not only "a conflict also closed". It must be the *same* decision.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "status"),
    [("APPROVED", "CORRECTED"), ("REJECTED", "APPROVED"), ("EXPIRED", "REJECTED")],
)
def test_a_review_status_that_contradicts_its_resolutions_outcome_is_refused(
    escalated, raw, outcome, status
):
    """Two recordings of one human decision, disagreeing.

    `review_items.status` and `review_resolutions.outcome` are the same fact written twice, and
    nothing in `011c` compared them. A review APPROVED behind a resolution that says REJECTED is a
    record which contradicts itself, and whichever field a caller read first would settle the
    belief. Everything else about this transaction is correct, so the outcome mismatch is the only
    thing that can refuse it.
    """
    with raw.cursor() as cursor:
        _resolution(cursor, "res:1", "rvw:1", outcome, "bre:1")
        cursor.execute(
            "UPDATE review_items SET status = %s, decision_ref = 'res:1' WHERE review_id = 'rvw:1'",
            (status,),
        )
        _close_conflict(cursor, "cfl:1", "bre:1")

    with pytest.raises(psycopg.errors.RaiseException, match="two accounts of the same decision"):
        raw.commit()

    raw.rollback()
    _assert_consistent(escalated)


def test_a_terminal_review_citing_another_reviews_resolution_is_refused(world, raw):
    """`decision_ref` must name the record of *this* review's resolution.

    `review_items_decision_ref_in_project` requires only that the row exist in the same project,
    and `review_resolutions_one_per_review` guarantees each resolution belongs to exactly one
    review -- so this is representable, and it is one human's decision being reused as the
    justification for a second that never happened. The borrowed resolution here is entirely
    genuine: `rvw:2` really did resolve, and really did produce `bre:2`.
    """
    _conflict(world, "cfl:1")
    _escalate(world, "rvw:1", "cfl:1")
    _conflict(world, "cfl:2")
    _escalate(world, "rvw:2", "cfl:2")
    _event(world, "bre:2")
    world.execute(
        "SELECT review_resolve_and_close_conflict('res:2', 'rvw:2', %s, 'APPROVED', 'act:test',"
        " 'genuinely resolved', 'bre:2', 'RESOLVED', %s)",
        (PROJECT, T0),
    )

    with raw.cursor() as cursor:
        cursor.execute(
            "UPDATE review_items SET status = 'APPROVED', decision_ref = 'res:2'"
            " WHERE review_id = 'rvw:1'"
        )
        _close_conflict(cursor, "cfl:1", "bre:2")

    with pytest.raises(psycopg.errors.RaiseException, match="resolved review rvw:2 instead"):
        raw.commit()

    raw.rollback()
    assert (
        world.execute("SELECT status FROM review_items WHERE review_id = 'rvw:1'").fetchone()[0]
        == "QUEUED"
    )
    _assert_consistent(world)


def test_a_conflict_closed_against_an_event_its_review_did_not_produce_is_refused(escalated, raw):
    """Closure traceability, enforced where `conflict_close` cannot reach.

    `bre:unrelated` is a real event in the right project, which is precisely the substitution
    P11's end-to-end test made and `011c` taught `conflict_close` to refuse. This transaction never
    calls `conflict_close`.
    """
    _event(escalated, "bre:unrelated")

    with raw.cursor() as cursor:
        _resolution(cursor, "res:1", "rvw:1", "APPROVED", "bre:1")
        cursor.execute(
            "UPDATE review_items SET status = 'APPROVED', decision_ref = 'res:1'"
            " WHERE review_id = 'rvw:1'"
        )
        _close_conflict(cursor, "cfl:1", "bre:unrelated")

    with pytest.raises(
        psycopg.errors.RaiseException, match="is not proof that this review resolved"
    ):
        raw.commit()

    raw.rollback()
    _assert_consistent(escalated)


# --------------------------------------------------------------------------------------------
# 7. Cross-project linkage. SEC-002 does not exempt the review queue.
# --------------------------------------------------------------------------------------------


def test_a_cross_project_review_conflict_linkage_cannot_be_committed(world, raw):
    """Three ways to cross a project boundary, each refused, none of them committed.

    Made unrepresentable by composite foreign keys rather than by a trigger -- `011b` and `011c`
    own that -- so this asserts the transaction cannot complete rather than predicting which
    mechanism stops it. A cross-project link would let one project's reviewer lift another
    project's block, and the invariant above is scoped on `project_id`, so it would never even see
    the pair.
    """
    _conflict(world, "cfl:1")
    _escalate(world, "rvw:1", "cfl:1")
    _conflict(world, "cfl:other", OTHER)
    _event(world, "bre:other", OTHER)

    attempts = (
        # This project's conflict, gated by a review that does not exist here.
        "UPDATE conflicts SET review_id = 'rvw:other' WHERE conflict_id = 'cfl:1'",
        # The other project's conflict, gated by this project's review.
        "UPDATE conflicts SET review_id = 'rvw:1' WHERE conflict_id = 'cfl:other'",
        # A resolution filed in the other project for this project's review.
        "INSERT INTO review_resolutions (resolution_id, review_id, project_id, outcome,"
        " resolved_by_actor_id, resolved_at, rationale, belief_revision_event_id)"
        " VALUES ('res:foreign', 'rvw:1', 'prj:other', 'APPROVED', 'act:test', now(), 'r',"
        " 'bre:other')",
    )
    for statement in attempts:
        with (
            pytest.raises((psycopg.errors.ForeignKeyViolation, psycopg.errors.RaiseException)),
            raw.cursor() as cursor,
        ):
            cursor.execute(statement)
            raw.commit()
        raw.rollback()

    assert (
        world.execute("SELECT review_id FROM conflicts WHERE conflict_id = 'cfl:1'").fetchone()[0]
        == "rvw:1"
    )
    assert (
        world.execute("SELECT review_id FROM conflicts WHERE conflict_id = 'cfl:other'").fetchone()[
            0
        ]
        is None
    )
    _assert_consistent(world)


# --------------------------------------------------------------------------------------------
# 8. The supported path still works -- and the intermediate state it needs is still permitted.
# --------------------------------------------------------------------------------------------


def test_the_supported_atomic_resolve_and_close_commits(escalated, raw):
    """The whole point of the exercise: the correct operation is not collateral damage.

    Every identifier in the chain is asserted to be the same one, because "it committed" is a
    weaker claim than "it committed something coherent" -- and the P11 bug this slice descends from
    passed the first test.
    """
    with raw.cursor() as cursor:
        cursor.execute(
            "SELECT review_resolve_and_close_conflict('res:1', 'rvw:1', %s, 'APPROVED',"
            " 'act:test', 'the calibrated range covers the operating point', 'bre:1',"
            " 'RESOLVED', %s)",
            (PROJECT, T0),
        )
    raw.commit()

    row = escalated.execute(
        "SELECT r.status, r.decision_ref, res.resolution_id, res.outcome,"
        "       res.belief_revision_event_id, c.resolution_status, c.resolution_event_id"
        "  FROM review_items r"
        "  JOIN review_resolutions res ON res.review_id = r.review_id"
        "  JOIN conflicts c ON c.review_id = r.review_id"
        " WHERE r.review_id = 'rvw:1'"
    ).fetchone()
    status, decision_ref, resolution_id, outcome, resolution_event, conflict_status, closure = row

    assert status == "APPROVED"
    assert outcome == status, "the two recordings of the decision agree"
    assert decision_ref == resolution_id == "res:1"
    assert conflict_status == "RESOLVED"
    assert closure == resolution_event == "bre:1", "the closure cites this review's own event"
    _assert_consistent(escalated)


def test_an_intermediate_half_state_inside_one_transaction_is_allowed(escalated, raw):
    """Deferred, not per-statement -- and this is the test that pins that down.

    Between terminalizing the review and closing the conflict, the row pair reads exactly like
    P0-A. It has to: `review_resolve_and_close_conflict` writes the review first. An implementation
    that refused the half-state per statement would look stricter, pass every test above, and make
    the only correct way to resolve a review impossible. The obligation is about what survives
    COMMIT.
    """
    with raw.cursor() as cursor:
        _resolution(cursor, "res:1", "rvw:1", "APPROVED", "bre:1")
        cursor.execute(
            "UPDATE review_items SET status = 'APPROVED', decision_ref = 'res:1'"
            " WHERE review_id = 'rvw:1'"
        )
        # Mid-transaction, this session sees the pair §17.19.1 forbids. Nothing has objected.
        assert cursor.execute(_FORBIDDEN_PAIRS).fetchall() != [], (
            "the setup for this test no longer produces the intermediate state it is about"
        )
        _close_conflict(cursor, "cfl:1", "bre:1")

    raw.commit()
    _assert_consistent(escalated)


def test_the_forbidden_pair_is_invisible_to_other_sessions_before_commit(escalated, raw):
    """The intermediate state is not merely tolerated -- it is never observable.

    A reader on another connection sees the block still in place for the whole transaction, so
    "permitted inside one transaction" does not weaken `v3.3-a14`'s atomicity clause into
    "observable while it lasts".
    """
    with raw.cursor() as cursor:
        _resolution(cursor, "res:1", "rvw:1", "APPROVED", "bre:1")
        cursor.execute(
            "UPDATE review_items SET status = 'APPROVED', decision_ref = 'res:1'"
            " WHERE review_id = 'rvw:1'"
        )
        _assert_consistent(escalated)
        assert (
            escalated.execute(
                "SELECT status FROM review_items WHERE review_id = 'rvw:1'"
            ).fetchone()[0]
            == "QUEUED"
        )
        _close_conflict(cursor, "cfl:1", "bre:1")

    raw.commit()
    _assert_consistent(escalated)


# --------------------------------------------------------------------------------------------
# The rest of the surface the invariant covers, reachable only by SQL.
# --------------------------------------------------------------------------------------------


def test_a_second_conflict_cannot_be_gated_by_an_already_resolved_review(world, raw):
    """`conflicts.review_id` is not unique, and `review_resolve_and_close_conflict` assumed it was.

    Its `SELECT conflict_id INTO v_conflict_id FROM conflicts WHERE review_id = ...` takes one row
    when two match, so a second conflict pointed at the same review would be left open behind a
    terminal review -- P0-A by another route. The invariant checks every conflict a review gates
    rather than the first one it finds.
    """
    _conflict(world, "cfl:1")
    _escalate(world, "rvw:1", "cfl:1")
    _event(world, "bre:1")
    world.execute(
        "SELECT review_resolve_and_close_conflict('res:1', 'rvw:1', %s, 'APPROVED', 'act:test',"
        " 'resolved', 'bre:1', 'RESOLVED', %s)",
        (PROJECT, T0),
    )
    _conflict(world, "cfl:2")

    with raw.cursor() as cursor:
        cursor.execute("UPDATE conflicts SET review_id = 'rvw:1' WHERE conflict_id = 'cfl:2'")

    with pytest.raises(psycopg.errors.RaiseException, match="conflict cfl:2 is still OPEN"):
        raw.commit()

    raw.rollback()
    _assert_consistent(world)


def test_a_resolution_cannot_be_deleted_out_from_under_a_terminal_review(escalated, raw):
    """`decision_ref` points at a *durable* record. Deleting it erases what was decided."""
    escalated.execute(
        "SELECT review_resolve_and_close_conflict('res:1', 'rvw:1', %s, 'APPROVED', 'act:test',"
        " 'resolved', 'bre:1', 'RESOLVED', %s)",
        (PROJECT, T0),
    )

    with raw.cursor() as cursor:
        cursor.execute("DELETE FROM review_resolutions WHERE resolution_id = 'res:1'")

    with pytest.raises(
        (psycopg.errors.RaiseException, psycopg.errors.ForeignKeyViolation),
        match=r"res:1|decision_ref",
    ):
        raw.commit()

    raw.rollback()
    assert (
        escalated.execute(
            "SELECT count(*) FROM review_resolutions WHERE resolution_id = 'res:1'"
        ).fetchone()[0]
        == 1
    )


def test_a_resolutions_outcome_cannot_be_rewritten_after_the_review_is_terminal(escalated, raw):
    """Editing the resolution is the quietest way to change what a human decided.

    The review's status stays APPROVED and the conflict stays closed, so nothing else in the
    schema objects -- but the two accounts of the decision now disagree.
    """
    escalated.execute(
        "SELECT review_resolve_and_close_conflict('res:1', 'rvw:1', %s, 'APPROVED', 'act:test',"
        " 'resolved', 'bre:1', 'RESOLVED', %s)",
        (PROJECT, T0),
    )

    with raw.cursor() as cursor:
        cursor.execute(
            "UPDATE review_resolutions SET outcome = 'REJECTED' WHERE resolution_id = 'res:1'"
        )

    with pytest.raises(psycopg.errors.RaiseException, match="two accounts of the same decision"):
        raw.commit()

    raw.rollback()
    assert (
        escalated.execute(
            "SELECT outcome FROM review_resolutions WHERE resolution_id = 'res:1'"
        ).fetchone()[0]
        == "APPROVED"
    )


def test_a_resolutions_event_cannot_be_rewritten_after_its_conflict_closed(escalated, raw):
    """The other half of the same edit: repoint the resolution at a different event.

    The conflict's `resolution_event_id` is immutable once closed, so moving the resolution is the
    only way to break the chain from this direction -- and it breaks closure traceability without
    touching either row a reader would think to check.
    """
    escalated.execute(
        "SELECT review_resolve_and_close_conflict('res:1', 'rvw:1', %s, 'APPROVED', 'act:test',"
        " 'resolved', 'bre:1', 'RESOLVED', %s)",
        (PROJECT, T0),
    )
    _event(escalated, "bre:elsewhere")

    with raw.cursor() as cursor:
        cursor.execute(
            "UPDATE review_resolutions SET belief_revision_event_id = 'bre:elsewhere'"
            " WHERE resolution_id = 'res:1'"
        )

    with pytest.raises(
        psycopg.errors.RaiseException, match="is not proof that this review resolved"
    ):
        raw.commit()

    raw.rollback()


# --------------------------------------------------------------------------------------------
# Real concurrency. Two connections, a barrier, and no sequential second attempt anywhere.
#
# P12's atomicity test called the function twice in a row on one connection and the P12 handoff
# described it as the race being covered. A second call after the first has committed is a
# duplicate, not a race: it never exercises two transactions holding conflicting intentions at the
# same time, which is the only situation where a lost update or an orphan can appear.
# --------------------------------------------------------------------------------------------


def _race(fn, connections, timeout: float = 30.0):  # type: ignore[no-untyped-def]
    """Run `fn` on each connection at the same moment; return (successes, failures)."""
    start = threading.Barrier(len(connections))

    def attempt(connection):  # type: ignore[no-untyped-def]
        start.wait(timeout=10)
        try:
            return ("ok", fn(connection))
        except Exception as exc:
            # Deliberately broad: which error the loser gets is part of what is under test, and
            # narrowing this to the exception the current implementation happens to raise would
            # turn "the loser lost" into "the loser lost the way I expected".
            return ("failed", f"{type(exc).__name__}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(connections)) as pool:
        results = [
            f.result(timeout=timeout) for f in [pool.submit(attempt, c) for c in connections]
        ]

    return (
        [value for kind, value in results if kind == "ok"],
        [value for kind, value in results if kind == "failed"],
    )


def test_two_sessions_racing_to_resolve_one_review_leave_exactly_one_decision(escalated, second):
    """The resolution race, with different resolution ids and different events on each side.

    Different ids on purpose: two callers submitting the *same* resolution id would be separated by
    the primary key, which proves nothing about whether the review, the resolution and the conflict
    can be left describing different winners. Each session proposes its own resolution and its own
    closure event, so a lost update anywhere in the chain shows up as two records disagreeing about
    which decision closed the block.
    """
    _event(escalated, "bre:a")
    _event(escalated, "bre:b")

    def resolve(connection, resolution_id: str, event_id: str):  # type: ignore[no-untyped-def]
        connection.execute(
            "SELECT review_resolve_and_close_conflict(%s, 'rvw:1', %s, 'APPROVED', 'act:test',"
            " 'raced', %s, 'RESOLVED', %s)",
            (resolution_id, PROJECT, event_id, T0),
        )
        return resolution_id

    proposals = {id(escalated): ("res:a", "bre:a"), id(second): ("res:b", "bre:b")}
    won, lost = _race(
        lambda connection: resolve(connection, *proposals[id(connection)]), (escalated, second)
    )

    assert len(won) == 1, f"expected exactly one winner, got {won} with failures {lost}"
    assert len(lost) == 1, "the loser must hear about it rather than believe it won"
    winner = won[0]

    assert (
        escalated.execute(
            "SELECT count(*) FROM review_resolutions WHERE review_id = 'rvw:1'"
        ).fetchone()[0]
        == 1
    ), "two accounts of one human decision"

    row = escalated.execute(
        "SELECT r.status, r.decision_ref, res.resolution_id, res.belief_revision_event_id,"
        "       c.resolution_status, c.resolution_event_id"
        "  FROM review_items r"
        "  JOIN review_resolutions res ON res.review_id = r.review_id"
        "  JOIN conflicts c ON c.review_id = r.review_id"
        " WHERE r.review_id = 'rvw:1'"
    ).fetchone()
    status, decision_ref, resolution_id, resolution_event, conflict_status, closure = row

    assert status == "APPROVED", "terminal exactly once"
    assert conflict_status == "RESOLVED", "terminal exactly once"
    # All four describe the same winner.
    assert decision_ref == resolution_id == winner
    assert closure == resolution_event
    assert resolution_event == {"res:a": "bre:a", "res:b": "bre:b"}[winner]
    _assert_consistent(escalated)


def test_two_sessions_racing_to_escalate_one_conflict_leave_exactly_one_review(world, second):
    """The escalation race. `011b` overwrote `review_id` and orphaned the first reviewer.

    The loser may either raise or observe the winner, and both are correct outcomes -- which one
    happens depends on whether its snapshot was taken before or after the winner committed, and
    pinning that down would be testing the scheduler. What must hold either way is that exactly one
    review row exists, the conflict points at it, and no second queued reviewer was left behind
    holding a task for a block somebody else is already handling.
    """
    _conflict(world, "cfl:1")

    proposals = {id(world): "rvw:a", id(second): "rvw:b"}

    def escalate(connection):  # type: ignore[no-untyped-def]
        return str(
            connection.execute(
                "SELECT authority_conflict_escalate(%s, 'cfl:1', %s, 'HIGH',"
                " 'AUTHORITY_INCOMPARABLE', %s, %s, 'TIER_A', NULL, 30)",
                (proposals[id(connection)], PROJECT, TRACE, T0),
            ).fetchone()[0]
        )

    returned, failed = _race(escalate, (world, second))

    assert returned, f"both escalations failed: {failed}"
    assert len(set(returned)) == 1, (
        f"the sessions disagree about which review gates the conflict: {returned}"
    )
    winner = returned[0]

    rows = world.execute(
        "SELECT review_id FROM review_items WHERE subject_id = 'cfl:1' ORDER BY review_id"
    ).fetchall()
    assert [row[0] for row in rows] == [winner], f"orphan review rows: {rows}"
    assert (
        world.execute("SELECT review_id FROM conflicts WHERE conflict_id = 'cfl:1'").fetchone()[0]
        == winner
    )

    # And the retry is deterministic: the loser asking again gets the winner rather than a second
    # review, which is what makes a retried episode idempotent rather than merely harmless.
    assert escalate(second) == winner
    assert (
        world.execute("SELECT count(*) FROM review_items WHERE subject_id = 'cfl:1'").fetchone()[0]
        == 1
    )
    _assert_consistent(world)
