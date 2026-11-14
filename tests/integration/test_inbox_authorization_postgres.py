"""T-UX-001 / T-SEC-002 — the inbox authorizes its Actor, and derives all seven states.

TWO DEFECTS, AND THE FIRST IS THE EMBARRASSING ONE.

**`--actor` was presentation-only governance.** The parser required it, `main` parsed it, and the
inbox branch called `service.inbox(project_id)` and threw it away. Any string reached any
project's items. A flag that is demanded and ignored is worse than no flag: the command *looks*
governed, and a reviewer reading the argument parser would conclude it was.

**Six of the seven states were unreachable from durable rows.** `review_ids` and `conflict_ids`
came back empty because the reader never asked for them, and the CLI passed no live Job list. So
NEEDS_REVIEW could not happen, PROCESSING could not happen, and the surface tests that "proved"
the derivation were run against items a test had constructed by hand.

The second defect had a false excuse attached, which is why it survived a review: the reader's
docstring claimed §17.19.1's `subject_type` vocabulary was `CONFLICT | AUTHORITY_CONFLICT` so no
ReviewItem could name an item. `011h` had already added `EXTRACTION_UNCERTAINTY` for exactly this,
and `enqueue_extraction_review` had already been writing those rows. A stated limitation that is
false is more dangerous than an unstated one -- it tells the next reader to stop looking.

EVERY PROBE HERE GOES THROUGH `main`. A test calling `service.inbox(...)` would cover the
authorization and not the wiring; a test calling `build_inbox(items)` would cover neither.
"""

from __future__ import annotations

import datetime as dt
import io

import pytest

from lab_brain.composition import IngestionService
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.job import JobState
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.interfaces.cli import main
from lab_brain.interfaces.config import DSN_VARIABLE
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.surface.ingestion_item import ItemState
from tests.evidence_fixtures import fixture_bytes
from tests.postgres_fixtures import database_url

pytestmark = [pytest.mark.postgres]

PROJECT = "prj:test"
OTHER = "prj:other"
TRACE = "trc:inbox"
NOW = dt.datetime(2026, 9, 23, 9, 0, tzinfo=dt.UTC)

MEMBER = "act:member"
UNKNOWN = "act:never-existed"
DISABLED = "act:disabled"
NON_MEMBER = "act:non-member"
REVOKED = "act:revoked"
FOREIGN = "act:foreign"


def env() -> dict[str, str]:
    return {DSN_VARIABLE: database_url()}


@pytest.fixture
def world(db, tmp_path):
    """Six actors differing in exactly one fact each, and one real ingestion to protect."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    for actor_id, active in (
        (MEMBER, True),
        (DISABLED, False),
        (NON_MEMBER, True),
        (REVOKED, True),
        (FOREIGN, True),
    ):
        db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name, active) "
            "VALUES (%s, 'HUMAN', %s, %s) ON CONFLICT DO NOTHING",
            (actor_id, actor_id, active),
        )
    for actor_id, project, active in (
        (MEMBER, PROJECT, True),
        # A DISABLED account with a perfectly good membership. Only `Actor.active` differs.
        (DISABLED, PROJECT, True),
        # Membership revoked; the row survives so the audit trail does.
        (REVOKED, PROJECT, False),
        # A fully active member -- of the other project.
        (FOREIGN, OTHER, True),
    ):
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
            "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['INTERNAL'], "
            "ARRAY[]::text[], %s)",
            (actor_id, project, active),
        )

    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )
    job = svc.submit(
        project_id=PROJECT, actor_id=MEMBER, idempotency_key="idem:inbox", trace_id=TRACE
    )
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=MEMBER,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert result.succeeded, "the fixture ingestion failed"
    return db, svc, result


def _queue_policy(db) -> None:
    """The active ReviewQueue policy `extraction_review_enqueue` prices from.

    Required rather than incidental: `011e` makes the SLA the policy's, never the caller's, so a
    project with no active policy cannot enqueue at all. That is the right refusal -- a review
    with a deadline nobody agreed to is a queue slot the planner cannot price.
    """
    db.execute(
        "INSERT INTO review_queue_policies (policy_id, version, project_id, capacity, "
        "default_sla_minutes, default_expiry_minutes, reviewer_minutes_per_day, "
        "effective_from, active, declared_by_actor_id) "
        "VALUES ('rqp:test', '1.0.0', %s, 50, 240, 480, 480, %s, TRUE, %s) "
        "ON CONFLICT DO NOTHING",
        (PROJECT, NOW, MEMBER),
    )


def _inbox(actor: str, project: str = PROJECT) -> tuple[int, str]:
    out = io.StringIO()
    code = main(["inbox", "--project", project, "--actor", actor], out=out, env=env())
    return code, out.getvalue()


# ---------------------------------------------------------------------------
# 1. The five refusals, through the real command
# ---------------------------------------------------------------------------


@pytest.mark.requirement("SEC-002")
@pytest.mark.spec_test("T-SEC-002")
@pytest.mark.parametrize(
    ("actor", "why"),
    [
        (UNKNOWN, "an actor that does not resolve"),
        (DISABLED, "a globally disabled account with a valid membership"),
        (NON_MEMBER, "a real actor with no membership of this project"),
        (REVOKED, "a member whose membership was revoked"),
        (FOREIGN, "an active, cleared member of a DIFFERENT project"),
    ],
)
def test_the_inbox_refuses_and_says_nothing_about_the_project(world, actor, why):
    """Five ways to fail, one answer, and the answer discloses nothing.

    Each case varies exactly ONE fact from the member who succeeds below, so a probe passing for
    the wrong reason shows up as its neighbour also passing.

    THE ITEM ID MUST NOT APPEAR, and neither must the summary line. An empty table would already
    be a disclosure: it tells a non-member the project exists and is simply quiet, and the
    difference between "no such project" and "nothing here today" is exactly the enumeration
    §17.24 forbids for error ids.
    """
    _db, _svc, result = world
    code, printed = _inbox(actor)

    assert code == 1, f"{why} was given an inbox"
    assert result.outcome.item_id not in printed
    assert "READY" not in printed
    assert "ITEM" not in printed, "the table header alone confirms the project is readable"
    assert printed.strip() == f"No inbox for {actor} in {PROJECT}."


def test_every_refusal_is_the_same_answer_except_for_the_names(world):
    """No oracle. The five refusals differ only where the actor id is substituted.

    Naming the reason -- "disabled", "not a member", "revoked" -- would be a directory of who
    belongs to which project, readable by anyone who can run the command.
    """
    _db, _svc, _result = world
    rendered = {
        actor: _inbox(actor)[1].replace(actor, "<actor>")
        for actor in (UNKNOWN, DISABLED, NON_MEMBER, REVOKED, FOREIGN)
    }
    assert len(set(rendered.values())) == 1, rendered


def test_the_service_raises_rather_than_returning_an_empty_view(world):
    """The refusal is at the service, not a rendering choice in the CLI.

    A CLI that filtered an authorized-but-empty list would put the decision in the presentation
    layer -- which is where every other surface would then have to repeat it.
    """
    _db, svc, _result = world
    with pytest.raises(ScientificReadRefused):
        svc.inbox(actor_id=NON_MEMBER, project_id=PROJECT)
    with pytest.raises(ScientificReadRefused):
        svc.inbox(actor_id=DISABLED, project_id=PROJECT)


def test_a_member_still_gets_their_inbox(world):
    """The positive control. Without it every assertion above could be a command that refuses
    everyone, which would satisfy the letter of the requirement and be useless."""
    _db, _svc, result = world
    code, printed = _inbox(MEMBER)
    assert code == 0
    assert result.outcome.item_id in printed
    assert "READY=1" in printed


def test_a_foreign_member_gets_their_own_project(world):
    """And the refusal is about THIS project, not about the actor.

    `act:foreign` is refused for `prj:test` and served for `prj:other` -- so the check is
    per-project membership rather than a global allow-list, which is what SEC-002 requires and
    what a coarser implementation would get wrong in the direction that looks fine.
    """
    _db, _svc, result = world
    assert _inbox(FOREIGN, OTHER)[0] == 0
    assert result.outcome.item_id not in _inbox(FOREIGN, OTHER)[1]


# ---------------------------------------------------------------------------
# 2. All seven states, from durable rows, through the real command
# ---------------------------------------------------------------------------


def _state_of(printed: str, item_id: str) -> str:
    for line in printed.splitlines():
        if line.startswith(item_id):
            return line[len(item_id) :].split()[0]
    raise AssertionError(f"{item_id} is not in the rendered inbox:\n{printed}")


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_ready_is_derived_from_durable_rows(world):
    _db, _svc, result = world
    assert _state_of(_inbox(MEMBER)[1], result.outcome.item_id) == ItemState.READY.value


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_processing_comes_from_a_live_job_not_from_the_item(world):
    """§17.22: PROCESSING when a Job is QUEUED / RUNNING / WAITING_RESOURCE.

    The item's rows do not change -- every stage already succeeded. What changes is the Job, and
    the CLI now reads it. Previously `jobs_for` was accepted and ignored, so a document still
    being worked on read as READY: the one answer a user must not be given about unfinished work.
    """
    db, svc, result = world
    item_id = result.outcome.item_id

    # A second job on the same item, still QUEUED. The ingest job is already terminal and `006`
    # refuses a terminal job moving back -- correctly, which is why this attaches a new one
    # rather than rewinding history. A follow-on stage looks exactly like this.
    follow_on = svc.submit(
        project_id=PROJECT, actor_id=MEMBER, idempotency_key="idem:follow", trace_id=TRACE
    )
    db.execute(
        "INSERT INTO ingestion_stage_results (item_id, stage, attempt, status, job_id, "
        "started_at, finished_at) VALUES (%s, 'SEGMENT', 2, 'SUCCEEDED', %s, %s, %s)",
        (item_id, follow_on.job_id, NOW, NOW),
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.PROCESSING.value

    # And it goes back once that job finishes, so this is the Job's state and not a latch.
    svc._jobs.transition(follow_on.job_id, JobState.RUNNING, NOW)
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.PROCESSING.value
    db.execute(
        "UPDATE jobs SET state = 'SUCCEEDED', finished_at = %s WHERE job_id = %s",
        (NOW, follow_on.job_id),
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.READY.value


@pytest.mark.requirement("UX-005")
@pytest.mark.spec_test("T-UX-005")
def test_needs_review_comes_from_the_one_review_queue_and_leaves_when_it_is_answered(world):
    """THE probe the audit asked for: ingest -> enqueue_extraction_review -> real CLI -> expire.

    `011h`'s `EXTRACTION_UNCERTAINTY` is the subject type, the item is the subject, and
    `extraction_review_enqueue` is the production path. UX-005 prohibits a second review surface
    because ReviewQueue depth prices human attention in §14.4.1 -- so this reads the same queue
    the planner reads, and nothing here writes to the item.

    THE ANSWER GOES THROUGH `review_expire`, the production statement, because `v3.3-a14` refuses
    a terminal review with no `decision_ref`: a human decision with no record of what was decided
    is not a resolution, and a conflict closed behind one would be unauditable. Hand-writing an
    APPROVED row would have tested a state the system cannot reach.

    And the item leaves NEEDS_REVIEW **without anything writing to it** -- the state follows the
    queue. An implementation that had latched a flag on the item would still say NEEDS_REVIEW.
    """
    db, _svc, result = world
    item_id = result.outcome.item_id
    _queue_policy(db)
    store = SqlReviewItemStore(db)
    review_id = store.enqueue_extraction_review(
        review_id="rvw:uncertain",
        project_id=PROJECT,
        item_id=item_id,
        stakes="HIGH",
        reason="two fields extracted with low confidence",
        trace_id=TRACE,
        created_at=NOW,
    )
    assert review_id == "rvw:uncertain"
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.NEEDS_REVIEW.value
    assert "NEEDS_REVIEW=1" in _inbox(MEMBER)[1]

    review = store.get(PROJECT, review_id)
    assert review is not None
    store.expire(
        review=review,
        governance_event_id="gev:swept",
        resolution_id="res:swept",
        actor_id=MEMBER,
        reason_code="REVIEW_SLA_EXPIRED",
        rationale="nobody answered before the declared deadline",
        now=NOW + dt.timedelta(days=2),
        trace_id=TRACE,
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.READY.value

    # The review itself is still attached to the item -- the history survives, only the state
    # moved. `review_ids` is what was reviewed; the queue is what is outstanding.
    assert review_id in _svc_review_ids(db, item_id)


def _svc_review_ids(db, item_id: str) -> tuple[str, ...]:
    rows = db.execute(
        "SELECT review_id FROM review_items WHERE subject_id = %s", (item_id,)
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


@pytest.mark.requirement("UX-005")
@pytest.mark.spec_test("T-UX-005")
def test_an_assigned_review_is_still_outstanding(world):
    """ASSIGNED counts as open. Somebody picked it up and has not answered.

    The item is no more ready than it was, and telling a user otherwise would mean a document
    became usable the moment a reviewer opened it rather than the moment they decided.
    """
    db, _svc, result = world
    item_id = result.outcome.item_id
    _queue_policy(db)
    SqlReviewItemStore(db).enqueue_extraction_review(
        review_id="rvw:picked-up",
        project_id=PROJECT,
        item_id=item_id,
        stakes="LOW",
        reason="uncertain units",
        trace_id=TRACE,
        created_at=NOW,
    )
    db.execute(
        "UPDATE review_items SET status = 'ASSIGNED', assigned_actor_id = %s "
        "WHERE review_id = 'rvw:picked-up'",
        (MEMBER,),
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.NEEDS_REVIEW.value


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_needs_review_also_comes_from_a_blocking_conflict(world):
    """§17.22's other NEEDS_REVIEW input. A conflict names the item among its subjects.

    BLOCKING **and** unresolved. The probe flips each half separately, because a reader that
    checked only one would agree with this one on the happy path and be wrong about a resolved
    blocking conflict -- which is the common case after somebody has done the work.
    """
    db, _svc, result = world
    item_id = result.outcome.item_id
    db.execute(
        "INSERT INTO conflicts (conflict_id, project_id, conflict_type, resolution_status, "
        "blocking, subject_refs, detected_at, detected_by_actor_or_slot, trace_id) "
        "VALUES ('cfl:retracted', %s, 'SOURCE_RETRACTION_CONFLICT', 'OPEN', TRUE, ARRAY[%s], "
        "%s, %s, %s)",
        (PROJECT, item_id, NOW, MEMBER, TRACE),
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.NEEDS_REVIEW.value


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_a_non_blocking_conflict_does_not_make_an_item_need_review(world):
    """The other half of the conjunction, as its own probe rather than an edit.

    `011a` makes `blocking` immutable and conflicts append-only, both deliberately -- its refusal
    says flipping `blocking` to false is the quietest way to unblock a belief with no record that
    anything happened. So this is a fresh item with a non-blocking conflict: a disagreement the
    lab has chosen to live with, which must not present as work a human owes.
    """
    db, _svc, result = world
    item_id = result.outcome.item_id
    db.execute(
        "INSERT INTO conflicts (conflict_id, project_id, conflict_type, resolution_status, "
        "blocking, subject_refs, detected_at, detected_by_actor_or_slot, trace_id) "
        "VALUES ('cfl:noted', %s, 'INDEPENDENCE_UNRESOLVED', 'OPEN', FALSE, ARRAY[%s], "
        "%s, %s, %s)",
        (PROJECT, item_id, NOW, MEMBER, TRACE),
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.READY.value


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_duplicate_comes_from_a_second_item_over_the_same_bytes(world):
    """§17.22's DUPLICATE: identical bytes, so no new scientific value.

    Two items, same artifact -- which under ART-001 is the same artifact id, not a second row.
    The second item is the duplicate; the first stays READY, because a document does not become
    a duplicate of itself when somebody uploads it again.
    """
    _db, svc, first = world
    job = svc.submit(
        project_id=PROJECT, actor_id=MEMBER, idempotency_key="idem:again", trace_id=TRACE
    )
    second = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=MEMBER,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report_copy.md",
    )
    printed = _inbox(MEMBER)[1]
    assert _state_of(printed, second.outcome.item_id) == ItemState.DUPLICATE.value
    assert _state_of(printed, first.outcome.item_id) == ItemState.READY.value
    assert "DUPLICATE=1" in printed


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_failed_and_blocked_and_partial_come_from_real_stage_rows(db, tmp_path):
    """The three failure states, each from a different durable cause, in one project.

    FAILED   every value-producing stage failed -- the document produced nothing.
    BLOCKED  a stage failed with POLICY_BLOCK. Above FAILED in §17.22's precedence, which is
             why a secret-scan quarantine sends an approver rather than an engineer.
    PARTIAL  one value-producing stage succeeded and another failed.

    The precedence is asserted, not just the states: the BLOCKED item also has failed stages, so
    an implementation that evaluated FAILED first would call it FAILED and send the wrong person.
    """
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name, active) "
        "VALUES (%s, 'HUMAN', %s, TRUE) ON CONFLICT DO NOTHING",
        (MEMBER, MEMBER),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['INTERNAL'], "
        "ARRAY[]::text[], TRUE)",
        (MEMBER, PROJECT),
    )
    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )

    class _Broken:
        def parse(self, *_a, **_k):
            raise RuntimeError("figure extraction timed out")

    svc._pipeline._parser = _Broken()
    job = svc.submit(
        project_id=PROJECT, actor_id=MEMBER, idempotency_key="idem:failed", trace_id=TRACE
    )
    failed = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=MEMBER,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///broken.md",
    )
    assert not failed.succeeded
    item_id = failed.outcome.item_id
    printed = _inbox(MEMBER)[1]
    assert _state_of(printed, item_id) == ItemState.FAILED.value

    # PARTIAL: one value-producing stage now reads SUCCEEDED beside the failure.
    db.execute(
        "INSERT INTO ingestion_stage_results (item_id, stage, attempt, status, started_at, "
        "finished_at) VALUES (%s, 'SEGMENT', 1, 'SUCCEEDED', %s, %s)",
        (item_id, NOW, NOW),
    )
    assert _state_of(_inbox(MEMBER)[1], item_id) == ItemState.PARTIAL.value

    # BLOCKED: reclassify the failure as a policy refusal. Both failure rows are still there, so
    # this also pins the precedence -- BLOCKED wins over FAILED and over PARTIAL.
    db.execute(
        "UPDATE ingestion_stage_results SET error_class = 'POLICY_BLOCK' "
        "WHERE item_id = %s AND status = 'FAILED'",
        (item_id,),
    )
    printed = _inbox(MEMBER)[1]
    assert _state_of(printed, item_id) == ItemState.BLOCKED.value
    assert "BLOCKED=1" in printed
