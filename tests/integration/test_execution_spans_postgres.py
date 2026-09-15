"""The database enforces the span contract, not only the Python model (OPS-003).

Same rule as the cost ledger: a model invariant holds for callers who go through the model. A
migration, a support script or a future service writes SQL. If "a span is opened once and closed
once" and "a span describes at most one thing" live only in `ExecutionSpan`, they hold only in
Python.

So each invariant is asserted twice -- once against the model in tests/contract/, once here against
the schema.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import os
import threading
from collections.abc import Iterator

import psycopg
import pytest

from lab_brain.core.models import ExecutionSpan, SpanStatus, SpanType
from lab_brain.core.repositories import (
    NonDurableClaimStoreError,
    SpanLifecycleError,
    SqlSpanRepository,
    TraceCorruptionError,
    TraceView,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("OPS-003"),
    pytest.mark.spec_test("T-OPS-003"),
]

T0 = dt.datetime(2026, 9, 15, 9, 0, tzinfo=dt.UTC)
TRACE = "trc:episode-1"
DEFAULT_URL = "postgresql://lab_brain:lab_brain@localhost:5433/lab_brain"


@pytest.fixture
def spans(db):  # type: ignore[no-untyped-def]
    """`db` truncates the span tables per test; they cannot be cleared with DELETE (append-only)."""
    return db


def _insert(db, span_id: str, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "span_id": span_id,
        "trace_id": TRACE,
        "span_type": "EPISODE",
        "episode_id": "ep:1",
        "start_time": T0,
        "status": "RUNNING",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({k})s" for k in values)
    db.execute(f"INSERT INTO execution_spans ({columns}) VALUES ({placeholders})", values)


# --------------------------------------------------------------------------------------------
# Shape constraints.
# --------------------------------------------------------------------------------------------


def test_a_span_cannot_be_its_own_parent(spans):
    with pytest.raises(psycopg.errors.CheckViolation, match="not_its_own_parent"):
        _insert(spans, "spn:1", parent_span_id="spn:1")


def test_a_span_cannot_carry_two_subjects(spans):
    with pytest.raises(psycopg.errors.CheckViolation, match="at_most_one_subject"):
        _insert(spans, "spn:1", span_type="JOB", job_id="job:1", retrieval_id="bdl:1")


def test_a_subject_must_match_the_span_type(spans):
    with pytest.raises(psycopg.errors.CheckViolation, match="subject_matches_type"):
        _insert(spans, "spn:1", span_type="JOB", retrieval_id="bdl:1")


def test_a_type_with_no_subject_takes_none(spans):
    with pytest.raises(psycopg.errors.CheckViolation, match="subject_matches_type"):
        _insert(spans, "spn:1", span_type="RUN", job_id="job:1")


def test_an_unknown_span_type_is_rejected(spans):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(spans, "spn:1", span_type="PROBABLY_FINE")


def test_an_unknown_status_is_rejected(spans):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(spans, "spn:1", status="MAYBE")


def test_a_running_span_has_no_end_and_a_finished_one_does(spans):
    """Both directions, as one constraint: `(status = 'RUNNING') = (end_time IS NULL)`."""
    with pytest.raises(psycopg.errors.CheckViolation, match="terminal_status_is_ended"):
        _insert(spans, "spn:1", status="RUNNING", end_time=T0 + dt.timedelta(seconds=1))
    with pytest.raises(psycopg.errors.CheckViolation, match="terminal_status_is_ended"):
        _insert(spans, "spn:2", status="SUCCEEDED")


def test_a_span_cannot_end_before_it_starts(spans):
    with pytest.raises(psycopg.errors.CheckViolation, match="ends_after_it_starts"):
        _insert(
            spans,
            "spn:1",
            status="SUCCEEDED",
            end_time=T0 - dt.timedelta(seconds=1),
        )


def test_a_parent_must_exist(spans):
    """A dangling parent makes the trace unreassemblable in a way nothing would report."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert(spans, "spn:1", parent_span_id="spn:nowhere")


def test_an_unknown_actor_is_rejected(spans):
    """§14.4: no governance without "who". A span attributed to nobody attributes nothing."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert(spans, "spn:1", actor_id="act:ghost")


# --------------------------------------------------------------------------------------------
# Opened once, closed once, never deleted.
# --------------------------------------------------------------------------------------------


def test_a_closed_span_cannot_be_reopened_or_re_closed(spans):
    _insert(spans, "spn:1")
    spans.execute(
        "UPDATE execution_spans SET status = 'SUCCEEDED', end_time = %s WHERE span_id = 'spn:1'",
        (T0 + dt.timedelta(seconds=1),),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="already SUCCEEDED"):
        spans.execute(
            "UPDATE execution_spans SET status = 'FAILED', end_time = %s WHERE span_id = 'spn:1'",
            (T0 + dt.timedelta(seconds=2),),
        )


def test_closing_a_span_cannot_rewrite_what_it_was(spans):
    """A close records how a span ended. Changing its trace or start time makes it another span."""
    _insert(spans, "spn:1")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        spans.execute(
            "UPDATE execution_spans SET status = 'SUCCEEDED', end_time = %s, trace_id = 'trc:other'"
            " WHERE span_id = 'spn:1'",
            (T0 + dt.timedelta(seconds=1),),
        )


def test_a_span_cannot_be_deleted(spans):
    """Observability that the observed thing can prune is not evidence."""
    _insert(spans, "spn:1")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        spans.execute("DELETE FROM execution_spans WHERE span_id = 'spn:1'")


# --------------------------------------------------------------------------------------------
# Cost refs are checked references, not free text.
# --------------------------------------------------------------------------------------------


def test_a_cost_ref_must_name_a_real_ledger_entry(spans):
    """An array column would have let a span cite a cost entry that does not exist.

    OPS-003 asks for cost *refs*; a ref that resolves to nothing is the failure this requirement
    exists to prevent, so it is a foreign key rather than an array of TEXT.
    """
    _insert(spans, "spn:1")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        spans.execute(
            "INSERT INTO execution_span_cost_entries (span_id, cost_entry_id)"
            " VALUES ('spn:1', 'cost:nowhere')"
        )


def test_the_same_cost_entry_is_not_linked_twice(spans):
    """A double-counted cost is worse than a missing one: it looks like evidence."""
    _insert(spans, "spn:1")
    spans.execute(
        "INSERT INTO budget_policies (policy_id, policy_version, project_id, cap_money_estimate)"
        " VALUES ('pol:s', '1.0.0', 'prj:test', 50.00)"
    )
    spans.execute(
        "INSERT INTO cost_entries"
        " (cost_entry_id, project_id, episode_id, actor_or_slot, action_ref, cost_kind)"
        " VALUES ('cost:1', 'prj:test', 'ep:1', 'slot:planner', 'act:1', 'ESTIMATED')"
    )
    spans.execute(
        "INSERT INTO execution_span_cost_entries (span_id, cost_entry_id)"
        " VALUES ('spn:1', 'cost:1')"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        spans.execute(
            "INSERT INTO execution_span_cost_entries (span_id, cost_entry_id)"
            " VALUES ('spn:1', 'cost:1')"
        )


# --------------------------------------------------------------------------------------------
# The repository, against the real table.
# --------------------------------------------------------------------------------------------


@pytest.fixture
def transactional_connection() -> Iterator[psycopg.Connection]:
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), connect_timeout=5
    )
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def second_connection() -> Iterator[psycopg.Connection]:
    """A genuinely separate session, so the concurrent-close race is a race."""
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), autocommit=True, connect_timeout=5
    )
    with connection:
        yield connection


def test_the_span_store_requires_a_durable_connection(transactional_connection):
    """Same rule as the approval claim, same reason.

    A span written inside a transaction the caller later rolls back is an execution that happened
    and left no trace, which is precisely what observability exists to prevent.
    """
    with pytest.raises(NonDurableClaimStoreError, match="autocommit=True"):
        SqlSpanRepository(transactional_connection)


def test_a_span_round_trips_through_the_repository(spans):
    repo = SqlSpanRepository(spans)
    repo.open(
        ExecutionSpan(
            span_id="spn:llm",
            trace_id=TRACE,
            span_type=SpanType.LLM_CALL,
            episode_id="ep:1",
            actor_id="act:test",
            model_call_id="mc:1",
            start_time=T0,
            status=SpanStatus.RUNNING,
            metadata={"slot": "HYPOTHESIS"},
        )
    )
    loaded = repo.get("spn:llm")
    assert loaded is not None
    assert loaded.span_type is SpanType.LLM_CALL
    assert loaded.model_call_id == "mc:1"
    assert loaded.metadata == {"slot": "HYPOTHESIS"}
    assert loaded.status is SpanStatus.RUNNING


def test_the_repository_refuses_to_re_close_a_closed_span(spans):
    repo = SqlSpanRepository(spans)
    repo.open(
        ExecutionSpan(
            span_id="spn:1",
            trace_id=TRACE,
            span_type=SpanType.EPISODE,
            episode_id="ep:1",
            start_time=T0,
            status=SpanStatus.RUNNING,
        )
    )
    repo.close("spn:1", SpanStatus.SUCCEEDED, T0 + dt.timedelta(seconds=1))
    with pytest.raises(SpanLifecycleError):
        repo.close("spn:1", SpanStatus.FAILED, T0 + dt.timedelta(seconds=2))


# --------------------------------------------------------------------------------------------
# Closing a span is atomic with its cost refs. P6 audit blocker 1.
#
# The defect: `close()` issued the status UPDATE and then one INSERT per ref, each committing on
# its own under the autocommit connection these stores require. So an invalid ref left the span
# permanently SUCCEEDED with partial links, and the close-once trigger refused every retry -- the
# two facts OPS-003 exists to make reliable were exactly the pair that could diverge, permanently.
# --------------------------------------------------------------------------------------------


def _ledger_entry(db, cost_entry_id: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO budget_policies (policy_id, policy_version, project_id)"
        " VALUES ('pol:s', '1.0.0', 'prj:test') ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO cost_entries"
        " (cost_entry_id, project_id, episode_id, actor_or_slot, action_ref, cost_kind)"
        " VALUES (%s, 'prj:test', 'ep:1', 'slot:planner', %s, 'ESTIMATED')",
        (cost_entry_id, f"act:{cost_entry_id}"),
    )


def _open(repo, span_id: str = "spn:1", **overrides):  # type: ignore[no-untyped-def]
    fields: dict[str, object] = {
        "span_id": span_id,
        "trace_id": TRACE,
        "span_type": SpanType.EPISODE,
        "episode_id": "ep:1",
        "start_time": T0,
        "status": SpanStatus.RUNNING,
    }
    fields.update(overrides)
    return repo.open(ExecutionSpan(**fields))  # type: ignore[arg-type]


def _expect_failure(call) -> BaseException:  # type: ignore[no-untyped-def]
    """Run ``call``, require it to raise, and hand back the exception.

    Deliberately not `pytest.raises(..., match=...)`. The property under test is the *state* the
    database is left in, and the exception's type and wording belong to whichever layer refused --
    the plpgsql RAISE now, a driver FK violation before 010b. A test that asserted the message
    would go red under the non-atomic implementation for the wrong reason and never reach the
    assertions that matter. Message quality is checked separately, below.
    """
    try:
        call()
    except Exception as exc:
        return exc
    raise AssertionError("expected the close to be refused, but it succeeded")


def test_an_invalid_second_cost_ref_leaves_the_span_running_with_no_links(spans):
    """The exact reproduction from the audit, now refused as a whole.

    One valid ref and one that names nothing. Before 010b this committed the terminal status and
    the first link and then raised, leaving a span that could never be closed correctly.
    """
    repo = SqlSpanRepository(spans)
    _open(repo)
    _ledger_entry(spans, "cost:valid")

    _expect_failure(
        lambda: repo.close(
            "spn:1",
            SpanStatus.SUCCEEDED,
            T0 + dt.timedelta(seconds=1),
            cost_entry_ids=("cost:valid", "cost:missing"),
        )
    )

    still = spans.execute(
        "SELECT status, end_time FROM execution_spans WHERE span_id = 'spn:1'"
    ).fetchone()
    assert still[0] == "RUNNING", "the span must stay open, or it can never be closed correctly"
    assert still[1] is None
    links = spans.execute(
        "SELECT count(*) FROM execution_span_cost_entries WHERE span_id = 'spn:1'"
    ).fetchone()
    assert links[0] == 0, "no partial links; the valid ref must not have been committed either"


def test_the_span_is_still_closable_after_a_refused_close(spans):
    """The consequence that made the defect permanent: a retry has to be possible."""
    repo = SqlSpanRepository(spans)
    _open(repo)
    _ledger_entry(spans, "cost:valid")

    _expect_failure(
        lambda: repo.close("spn:1", SpanStatus.SUCCEEDED, T0, cost_entry_ids=("cost:missing",))
    )

    closed = repo.close(
        "spn:1", SpanStatus.SUCCEEDED, T0 + dt.timedelta(seconds=1), ("cost:valid",)
    )
    assert closed.status is SpanStatus.SUCCEEDED
    assert closed.cost_entry_ids == ("cost:valid",)


def test_the_refusal_names_the_cost_entry_that_was_missing(spans):
    """Separate from the state assertions on purpose -- this one is about the message.

    "Something was wrong with your cost refs" is not actionable when a span cites four of them.
    """
    repo = SqlSpanRepository(spans)
    _open(repo)
    failure = _expect_failure(
        lambda: repo.close("spn:1", SpanStatus.SUCCEEDED, T0, cost_entry_ids=("cost:missing",))
    )
    assert "cost:missing" in str(failure)
    assert "does not exist" in str(failure)


def test_all_valid_refs_become_visible_together_with_the_terminal_status(spans):
    """The positive half: status and every ref land in the same statement."""
    repo = SqlSpanRepository(spans)
    _open(repo)
    for entry in ("cost:a", "cost:b", "cost:c"):
        _ledger_entry(spans, entry)

    repo.close(
        "spn:1",
        SpanStatus.SUCCEEDED,
        T0 + dt.timedelta(seconds=1),
        cost_entry_ids=("cost:a", "cost:b", "cost:c"),
    )
    row = spans.execute(
        "SELECT s.status, count(l.cost_entry_id) FROM execution_spans s"
        " LEFT JOIN execution_span_cost_entries l ON l.span_id = s.span_id"
        " WHERE s.span_id = 'spn:1' GROUP BY s.status"
    ).fetchone()
    assert row == ("SUCCEEDED", 3)
    assert SqlSpanRepository(spans).get("spn:1").cost_entry_ids == (
        "cost:a",
        "cost:b",
        "cost:c",
    )


def test_two_concurrent_closes_produce_exactly_one_winner(spans, second_connection):
    """The row lock inside the function still gives one winner, across two real sessions."""
    repo = SqlSpanRepository(spans)
    _open(repo)
    _ledger_entry(spans, "cost:a")
    start = threading.Barrier(2)

    def attempt(connection) -> bool:
        start.wait(timeout=10)
        try:
            SqlSpanRepository(connection).close(
                "spn:1", SpanStatus.SUCCEEDED, T0 + dt.timedelta(seconds=1), ("cost:a",)
            )
            return True
        except SpanLifecycleError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            f.result(timeout=30)
            for f in [pool.submit(attempt, c) for c in (spans, second_connection)]
        ]

    assert results.count(True) == 1, f"expected exactly one winner, got {results}"
    assert (
        spans.execute(
            "SELECT count(*) FROM execution_span_cost_entries WHERE span_id = 'spn:1'"
        ).fetchone()[0]
        == 1
    )


def test_the_close_function_refuses_to_close_to_running(spans):
    """Closing records how an interval ended; RUNNING is not an ending."""
    repo = SqlSpanRepository(spans)
    _open(repo)
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be closed to RUNNING"):
        spans.execute(
            "SELECT execution_span_close('spn:1', 'RUNNING', %s, '{}'::jsonb, ARRAY[]::text[])",
            (T0,),
        )


# --------------------------------------------------------------------------------------------
# A parent span is in the same trace. P6 audit blocker 2.
#
# 010a's FK required only that the parent exist. A child in trace B with a parent in trace A was
# accepted, and `trace('B')` then returned a child whose parent was absent -- which the old
# reconstruction silently treated as a root, laundering a corrupt edge into a plausible tree.
# --------------------------------------------------------------------------------------------


def test_a_child_cannot_name_a_parent_in_another_trace(spans):
    _insert(spans, "spn:parent", trace_id="trc:A")
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="same_trace"):
        _insert(
            spans,
            "spn:child",
            trace_id="trc:B",
            parent_span_id="spn:parent",
            span_type="RETRIEVAL",
            retrieval_id="bdl:1",
        )


def test_a_parent_in_the_same_trace_is_accepted(spans):
    """The constraint has to be satisfiable, or no trace could have more than one span."""
    _insert(spans, "spn:parent", trace_id="trc:A")
    _insert(
        spans,
        "spn:child",
        trace_id="trc:A",
        parent_span_id="spn:parent",
        span_type="RETRIEVAL",
        retrieval_id="bdl:1",
    )
    row = spans.execute(
        "SELECT parent_span_id FROM execution_spans WHERE span_id = 'spn:child'"
    ).fetchone()
    assert row[0] == "spn:parent"


def test_a_trace_containing_a_cross_trace_orphan_fails_loudly(spans):
    """Reconstruction must not repair its own input.

    Built by hand, because 010b makes the database refuse to store it -- which is the point. If a
    corrupt trace is ever assembled from a partial read, `ordered()` says so rather than producing
    something that reads as evidence.
    """
    view = TraceView(
        trace_id="trc:B",
        spans=(
            ExecutionSpan(
                span_id="spn:child",
                trace_id="trc:B",
                parent_span_id="spn:elsewhere",
                span_type=SpanType.RETRIEVAL,
                retrieval_id="bdl:1",
                start_time=T0,
                status=SpanStatus.RUNNING,
            ),
        ),
    )
    with pytest.raises(TraceCorruptionError, match="whose parent is not in it"):
        view.ordered()


def test_the_repository_refuses_to_open_an_already_finished_span(spans):
    repo = SqlSpanRepository(spans)
    with pytest.raises(SpanLifecycleError, match="opened as SUCCEEDED"):
        repo.open(
            ExecutionSpan(
                span_id="spn:1",
                trace_id=TRACE,
                span_type=SpanType.EPISODE,
                start_time=T0,
                end_time=T0 + dt.timedelta(seconds=1),
                status=SpanStatus.SUCCEEDED,
            )
        )
