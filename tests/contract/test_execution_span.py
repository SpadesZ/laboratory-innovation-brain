"""OPS-003: a trace is a tree of spans that reassembles, with status and cost refs.

    §12.5    `trace_id` 貫穿 episode → retrieval → LLM call → job → run → artifact.
    §17.19.1 ExecutionSpan { span_id, trace_id, parent_span_id?, span_type, episode_id?,
             actor_id?, model_call_id?/job_id?/retrieval_id?, start_time, end_time?, status,
             cost_entry_ids[], metadata{} }
    OPS-003  Execution observability MUST persist trace/span contract linking
             episode → retrieval/LLM/job/run/artifact with status and cost refs.

Written before the implementation. Each negative case is a span that would reassemble into a trace
nobody can read, or one that looks complete and is not.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models import (
    SUBJECT_FIELD_FOR_TYPE,
    TERMINAL_SPAN_STATUSES,
    ExecutionSpan,
    SpanStatus,
    SpanType,
    new_id,
)
from lab_brain.core.repositories import (
    InMemorySpanRepository,
    SpanLifecycleError,
    TraceView,
)

pytestmark = [pytest.mark.requirement("OPS-003"), pytest.mark.spec_test("T-OPS-003")]

T0 = dt.datetime(2026, 9, 15, 9, 0, tzinfo=dt.UTC)
TRACE = "trc:episode-1"
EPISODE = "ep:rs-anomaly-1"


def span(**overrides: object) -> ExecutionSpan:
    defaults: dict[str, object] = {
        "span_id": "spn:1",
        "trace_id": TRACE,
        "span_type": SpanType.EPISODE,
        "episode_id": EPISODE,
        "start_time": T0,
        "status": SpanStatus.RUNNING,
    }
    defaults.update(overrides)
    return ExecutionSpan(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# The declared contract.
# --------------------------------------------------------------------------------------------


def test_the_span_carries_every_field_17_19_1_declares():
    """By name. A field the spec declares and the model lacks is a link the trace cannot make."""
    for field in (
        "span_id",
        "trace_id",
        "parent_span_id",
        "span_type",
        "episode_id",
        "actor_id",
        "model_call_id",
        "job_id",
        "retrieval_id",
        "start_time",
        "end_time",
        "status",
        "cost_entry_ids",
        "metadata",
    ):
        assert field in ExecutionSpan.model_fields, f"§17.19.1 declares {field}"


def test_the_span_type_vocabulary_covers_the_12_5_chain():
    """§12.5 names episode → retrieval → LLM call → job → run; §17.17 adds tool calls."""
    for expected in ("EPISODE", "RETRIEVAL", "LLM_CALL", "TOOL_CALL", "JOB", "RUN"):
        assert expected in {member.value for member in SpanType}


def test_blocked_is_not_failed():
    """UX-002: budget exhaustion classifies as POLICY_BLOCK, not FAILED.

    Different statuses because they send different people: a governance refusal needs a
    supervisor, a breakage needs an engineer. Collapsing them wastes the on-call.
    """
    assert SpanStatus.BLOCKED is not SpanStatus.FAILED
    assert {SpanStatus.BLOCKED, SpanStatus.FAILED} <= TERMINAL_SPAN_STATUSES


# --------------------------------------------------------------------------------------------
# A span describes one thing. §17.19.1's `model_call_id?/job_id?/retrieval_id?`.
# --------------------------------------------------------------------------------------------


def test_a_span_cannot_carry_two_subjects():
    """Two subjects means two spans were never separated, and the cost lands on both."""
    with pytest.raises(ValueError, match="at most one thing"):
        span(span_type=SpanType.JOB, job_id="job:1", retrieval_id="ret:1")


def test_a_spans_subject_must_match_its_type():
    with pytest.raises(ValueError, match="subject is job_id"):
        span(span_type=SpanType.JOB, retrieval_id="ret:1")


def test_a_type_with_no_subject_reference_takes_none():
    """An EPISODE span's subject is the episode, which it already names in `episode_id`."""
    with pytest.raises(ValueError, match="takes no subject reference"):
        span(span_type=SpanType.EPISODE, job_id="job:1")


@pytest.mark.parametrize(
    ("span_type", "field"), sorted((t, f) for t, f in SUBJECT_FIELD_FOR_TYPE.items())
)
def test_each_declared_subject_is_accepted(span_type, field):
    """The mapping must be satisfiable, or these types could never be recorded."""
    built = span(span_type=span_type, **{field: "sub:1"})
    assert getattr(built, field) == "sub:1"


# --------------------------------------------------------------------------------------------
# A finished interval has an end. A running one does not.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(TERMINAL_SPAN_STATUSES))
def test_a_terminal_span_needs_an_end_time(status):
    """Duration is what observability is for; a finished span with no end has none."""
    with pytest.raises(ValueError, match="no end_time"):
        span(status=status)


def test_a_running_span_must_not_have_an_end_time():
    with pytest.raises(ValueError, match="RUNNING but has an end_time"):
        span(end_time=T0 + dt.timedelta(seconds=1))


def test_a_span_cannot_end_before_it_starts():
    with pytest.raises(ValueError, match="ends before it starts"):
        span(status=SpanStatus.SUCCEEDED, end_time=T0 - dt.timedelta(seconds=1))


def test_a_span_cannot_be_its_own_parent():
    """A cycle makes reconstruction non-terminating rather than merely wrong."""
    with pytest.raises(ValueError, match="its own parent"):
        span(parent_span_id="spn:1")


def test_a_cost_entry_cannot_be_listed_twice():
    """A double-counted cost is worse than a missing one: it looks like evidence."""
    with pytest.raises(ValueError, match="cost entry twice"):
        span(
            status=SpanStatus.SUCCEEDED,
            end_time=T0 + dt.timedelta(seconds=1),
            cost_entry_ids=("cost:1", "cost:1"),
        )


def test_duration_is_none_while_open_and_a_number_once_closed():
    assert span().duration_s is None
    closed = span().closed(SpanStatus.SUCCEEDED, T0 + dt.timedelta(seconds=90))
    assert closed.duration_s == 90.0
    assert closed.is_open is False


def test_closing_revalidates_rather_than_copying_blindly():
    """`closed()` is the one method whose job is to produce a valid closed span.

    `model_copy` skips validation, so without re-validation an end_time before the start would be
    constructible through exactly that method.
    """
    with pytest.raises(ValueError, match="ends before it starts"):
        span().closed(SpanStatus.SUCCEEDED, T0 - dt.timedelta(seconds=1))
    with pytest.raises(ValueError, match="terminal status"):
        span().closed(SpanStatus.RUNNING, T0)


def test_span_and_trace_ids_are_separate_kinds():
    """Reusing one id for both would make a trace indistinguishable from its own root span."""
    assert new_id("trace").startswith("trc:")
    assert new_id("execution_span").startswith("spn:")


# --------------------------------------------------------------------------------------------
# Reconstruction. This is what T-OPS-003 actually asks for.
# --------------------------------------------------------------------------------------------


def _tree() -> InMemorySpanRepository:
    """episode -> (retrieval, llm -> job), opened out of order on purpose."""
    spans = InMemorySpanRepository()
    spans.open(span(span_id="spn:root", span_type=SpanType.EPISODE))
    spans.open(
        span(
            span_id="spn:llm",
            parent_span_id="spn:root",
            span_type=SpanType.LLM_CALL,
            model_call_id="mc:1",
            start_time=T0 + dt.timedelta(seconds=20),
        )
    )
    spans.open(
        span(
            span_id="spn:retrieval",
            parent_span_id="spn:root",
            span_type=SpanType.RETRIEVAL,
            retrieval_id="bdl:1",
            start_time=T0 + dt.timedelta(seconds=10),
        )
    )
    spans.open(
        span(
            span_id="spn:job",
            parent_span_id="spn:llm",
            span_type=SpanType.JOB,
            job_id="job:1",
            start_time=T0 + dt.timedelta(seconds=30),
        )
    )
    return spans


def test_a_trace_reassembles_depth_first_by_start_time():
    """Insertion order is not execution order once anything runs concurrently."""
    order = [s.span_id for s in _tree().trace(TRACE).ordered()]
    assert order == ["spn:root", "spn:retrieval", "spn:llm", "spn:job"]


def test_reconstruction_is_deterministic_for_simultaneous_siblings():
    """Two spans in the same microsecond must still reconstruct identically every run."""
    spans = InMemorySpanRepository()
    spans.open(span(span_id="spn:root"))
    for sid in ("spn:b", "spn:a"):
        spans.open(
            span(
                span_id=sid,
                parent_span_id="spn:root",
                span_type=SpanType.RETRIEVAL,
                retrieval_id="bdl:1",
            )
        )
    first = [s.span_id for s in spans.trace(TRACE).ordered()]
    second = [s.span_id for s in spans.trace(TRACE).ordered()]
    assert first == second == ["spn:root", "spn:a", "spn:b"]


def test_a_span_whose_parent_is_missing_is_surfaced_not_dropped():
    """Losing a span because its parent is absent would silently shrink the evidence."""
    spans = InMemorySpanRepository()
    spans.open(span(span_id="spn:orphan", parent_span_id="spn:nowhere"))
    assert [s.span_id for s in spans.trace(TRACE).ordered()] == ["spn:orphan"]


def test_a_trace_collects_its_cost_refs_in_reconstruction_order():
    """OPS-003's "cost refs": the point of the trace is what each step cost."""
    spans = _tree()
    spans.close(
        "spn:retrieval",
        SpanStatus.SUCCEEDED,
        T0 + dt.timedelta(seconds=15),
        cost_entry_ids=("cost:retrieval",),
    )
    spans.close(
        "spn:llm",
        SpanStatus.SUCCEEDED,
        T0 + dt.timedelta(seconds=25),
        cost_entry_ids=("cost:llm-est", "cost:llm-act"),
    )
    assert spans.trace(TRACE).cost_entry_ids() == (
        "cost:retrieval",
        "cost:llm-est",
        "cost:llm-act",
    )


def test_a_trace_reports_what_is_still_open():
    """A trace that never closes is what a stuck episode looks like from outside."""
    spans = _tree()
    spans.close("spn:job", SpanStatus.SUCCEEDED, T0 + dt.timedelta(seconds=40))
    assert {s.span_id for s in spans.trace(TRACE).open_spans()} == {
        "spn:root",
        "spn:retrieval",
        "spn:llm",
    }


def test_an_empty_trace_is_an_empty_view_not_an_error():
    view = InMemorySpanRepository().trace("trc:nothing")
    assert isinstance(view, TraceView)
    assert view.ordered() == ()


# --------------------------------------------------------------------------------------------
# Opened once, closed once. The in-memory store enforces what the table enforces.
# --------------------------------------------------------------------------------------------


def test_a_span_cannot_be_opened_already_finished():
    """Recording a span already-closed loses the interval, which is the whole record."""
    spans = InMemorySpanRepository()
    with pytest.raises(SpanLifecycleError, match="opened as SUCCEEDED"):
        spans.open(span(status=SpanStatus.SUCCEEDED, end_time=T0 + dt.timedelta(seconds=1)))


def test_a_span_cannot_be_opened_twice():
    spans = InMemorySpanRepository()
    spans.open(span())
    with pytest.raises(SpanLifecycleError, match="already recorded"):
        spans.open(span())


def test_a_closed_span_is_not_re_decided():
    spans = InMemorySpanRepository()
    spans.open(span())
    spans.close("spn:1", SpanStatus.SUCCEEDED, T0 + dt.timedelta(seconds=1))
    with pytest.raises(SpanLifecycleError, match="already SUCCEEDED"):
        spans.close("spn:1", SpanStatus.FAILED, T0 + dt.timedelta(seconds=2))


def test_closing_an_unknown_span_fails_rather_than_creating_one():
    with pytest.raises(SpanLifecycleError, match="no span"):
        InMemorySpanRepository().close("spn:ghost", SpanStatus.SUCCEEDED, T0)
