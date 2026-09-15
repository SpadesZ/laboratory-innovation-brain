"""The database enforces the span contract, not only the Python model (OPS-003).

Same rule as the cost ledger: a model invariant holds for callers who go through the model. A
migration, a support script or a future service writes SQL. If "a span is opened once and closed
once" and "a span describes at most one thing" live only in `ExecutionSpan`, they hold only in
Python.

So each invariant is asserted twice -- once against the model in tests/contract/, once here against
the schema.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterator

import psycopg
import pytest

from lab_brain.core.models import ExecutionSpan, SpanStatus, SpanType
from lab_brain.core.repositories import (
    NonDurableClaimStoreError,
    SpanLifecycleError,
    SqlSpanRepository,
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
