"""T-OPS-003: one episode trace reconstructs the chain and the cost entries that went with it.

    §26      OPS-003 | T-OPS-003 | e2e | one episode trace reconstructs
             retrieval → LLM → job → run → artifact and associated cost entries.
    §12.5    `trace_id` 貫穿 episode → retrieval → LLM call → job → run → artifact.

Everything here goes through the real seam and the real database. The actions are mocks -- there is
no LLM slot configured and no Lumerical seat (AGT-007, risks R-1) -- but the budget gate, the cost
ledger, the approval claim and the span store are the production ones, and the reconstruction reads
back out of PostgreSQL rather than out of the objects the test just built.

WHAT THIS DOES **NOT** YET DISCHARGE. §26's pass condition names `run → artifact`. A Run is
§17.4's manifest and lives in Appendix A's `006_jobs_runs.sql`, which is not built: OPS-001 is M1.
So the RUN span below records a run that has no row to point at, and the artifact is reached through
span metadata rather than a checked reference. The trace contract, the seam and the cost refs are
real and exercised; the last link is a stated gap, recorded in IMPLEMENTATION_STATUS.md rather than
implied to be finished. OPS-003 therefore stays IN_PROGRESS.
"""

from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal

import pytest

from lab_brain.core.budget import BudgetPolicy, BudgetRequest
from lab_brain.core.dispatch import ActionOutcome, DispatchableAction, dispatch_action
from lab_brain.core.models import (
    ArtifactOccurrence,
    BudgetCaps,
    CostKind,
    CostVector,
    ExecutionSpan,
    SensitivityLabel,
    SourceOrigin,
    SpanStatus,
    SpanType,
)
from lab_brain.core.repositories import (
    InMemoryBudgetApprovalClaims,
    SqlCostLedger,
    SqlSpanRepository,
)
from tests.conftest_fixtures import make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("OPS-003"),
    pytest.mark.spec_test("T-OPS-003"),
]

T0 = dt.datetime(2026, 9, 15, 9, 0, tzinfo=dt.UTC)
TRACE = "trc:episode-rs-anomaly"
EPISODE = "ep:rs-anomaly-1"
PROJECT = "prj:test"
SLOT = "slot:planner"
# The span's actor_id is an FK into `actors`; a §7.3 slot is not an Actor (see DispatchableAction).
SPAN_ACTOR = "act:test"


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """A project, an actor, and one budget policy generous enough to admit the whole episode."""
    db.execute(
        "INSERT INTO budget_policies (policy_id, policy_version, project_id,"
        " cap_money_estimate, cap_token_count, cap_wall_clock_s)"
        " VALUES ('pol:s', '1.0.0', 'prj:test', 50.00, 100000, 86400)"
    )
    return db


def clock():
    ticks = itertools.count()
    return lambda: T0 + dt.timedelta(seconds=next(ticks))


POLICY = BudgetPolicy(
    policy_id="pol:s",
    policy_version="1.0.0",
    project_id=PROJECT,
    caps=BudgetCaps(money_estimate=Decimal("50.00"), token_count=100_000, wall_clock_s=86_400),
)


def budget(action_ref: str, estimate: CostVector, consumed: CostVector) -> BudgetRequest:
    return BudgetRequest(
        action_ref=action_ref,
        project_id=PROJECT,
        episode_id=EPISODE,
        actor_id=SLOT,
        estimate=estimate,
        consumed=consumed,
        policy=POLICY,
        now=T0,
    )


def test_one_episode_trace_reconstructs_the_chain_and_its_cost_entries(world):
    """The pass condition, end to end, read back out of the database.

    Four dispatches under one trace_id: a retrieval, an LLM call parented to it, a job parented to
    the LLM call, and a run parented to the job that produces an artifact. Each one goes through
    the budget gate before its side effect and leaves an estimate and an actual in the ledger.
    """
    spans = SqlSpanRepository(world)
    ledger = SqlCostLedger(world)
    claims = InMemoryBudgetApprovalClaims()
    now = clock()

    # The episode's own span. Opened directly rather than dispatched: an episode is not an action
    # with a cost, it is the interval the actions happen inside.
    spans.open(
        ExecutionSpan(
            span_id="spn:episode",
            trace_id=TRACE,
            span_type=SpanType.EPISODE,
            episode_id=EPISODE,
            actor_id="act:test",
            start_time=now(),
            status=SpanStatus.RUNNING,
        )
    )

    consumed = CostVector()
    steps = (
        (
            "spn:retrieval",
            "spn:episode",
            SpanType.RETRIEVAL,
            "bdl:1",
            "act:retrieve#1",
            CostVector(wall_clock_s=2),
            CostVector(wall_clock_s=3),
        ),
        (
            "spn:llm",
            "spn:retrieval",
            SpanType.LLM_CALL,
            "mc:1",
            "act:hypothesise#1",
            CostVector(token_count=4_000, money_estimate=Decimal("0.40")),
            CostVector(token_count=4_312, money_estimate=Decimal("0.43")),
        ),
        (
            "spn:job",
            "spn:llm",
            SpanType.JOB,
            "job:1",
            "act:submit_charge_sweep#1",
            CostVector(wall_clock_s=600, compute_units=8),
            CostVector(wall_clock_s=651, compute_units=8),
        ),
    )

    for span_id, parent, span_type, subject, action_ref, estimate, actual in steps:
        result = dispatch_action(
            DispatchableAction(
                span_id=span_id,
                trace_id=TRACE,
                span_type=span_type,
                parent_span_id=parent,
                episode_id=EPISODE,
                actor_id=SPAN_ACTOR,
                subject_id=subject,
                estimate_entry_id=f"cost:{span_id}-est",
                actual_entry_id=f"cost:{span_id}-act",
                perform=lambda a=actual: ActionOutcome(actual_cost=a),
            ),
            budget(action_ref, estimate, consumed),
            spans=spans,
            ledger=ledger,
            claims=claims,
            now=now,
        )
        assert result.performed is True, span_id
        consumed = consumed.plus(actual)

    # The run, which produces an artifact. The artifact is a real content-addressed row; the link
    # from the span to it is metadata, because Run does not exist as an entity until M1.
    artifact = make_artifact(
        b"Rs=12.4 ohm, Cj=31 fF\n",
        uri="file:///runs/1/summary.csv",
        media_type="text/csv",
        source_origin=SourceOrigin.RUN_OUTPUT,
    )
    world.execute(
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
    occurrence = ArtifactOccurrence(
        artifact_id=artifact.artifact_id,
        project_id=PROJECT,
        sensitivity_label=SensitivityLabel.CONFIDENTIAL_LAB,
        ingested_by_actor_id="act:test",
    )
    world.execute(
        "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label,"
        " ingested_by_actor_id) VALUES (%s, %s, %s, %s)",
        (
            occurrence.artifact_id,
            occurrence.project_id,
            occurrence.sensitivity_label.value,
            occurrence.ingested_by_actor_id,
        ),
    )

    run = dispatch_action(
        DispatchableAction(
            span_id="spn:run",
            trace_id=TRACE,
            span_type=SpanType.RUN,
            parent_span_id="spn:job",
            episode_id=EPISODE,
            actor_id=SPAN_ACTOR,
            estimate_entry_id="cost:spn:run-est",
            actual_entry_id="cost:spn:run-act",
            perform=lambda: ActionOutcome(
                actual_cost=CostVector(wall_clock_s=12, compute_units=1),
                metadata={"output_artifact_ids": [artifact.artifact_id], "run_id": "run:1"},
            ),
        ),
        budget("act:extract_metrics#1", CostVector(wall_clock_s=15), consumed),
        spans=spans,
        ledger=ledger,
        claims=claims,
        now=now,
    )
    assert run.performed is True

    spans.close("spn:episode", SpanStatus.SUCCEEDED, now())

    # ---- reconstruction, from the database ----
    view = SqlSpanRepository(world).trace(TRACE)
    order = [span.span_id for span in view.ordered()]
    assert order == ["spn:episode", "spn:retrieval", "spn:llm", "spn:job", "spn:run"], order

    types = [span.span_type for span in view.ordered()]
    assert types == [
        SpanType.EPISODE,
        SpanType.RETRIEVAL,
        SpanType.LLM_CALL,
        SpanType.JOB,
        SpanType.RUN,
    ]

    assert all(span.status is SpanStatus.SUCCEEDED for span in view.spans)
    assert view.open_spans() == ()

    # Every dispatched step contributed an estimate and an actual, and the trace names all of them.
    refs = view.cost_entry_ids()
    assert len(refs) == 8, refs
    for span_id in ("spn:retrieval", "spn:llm", "spn:job", "spn:run"):
        assert f"cost:{span_id}-est" in refs
        assert f"cost:{span_id}-act" in refs

    # The refs resolve, and the estimate/actual pair for the LLM call is the one the gate saw.
    estimated = ledger.entry("cost:spn:llm-est")
    actual = ledger.entry("cost:spn:llm-act")
    assert estimated is not None and actual is not None
    assert estimated.cost_kind is CostKind.ESTIMATED
    assert actual.cost_kind is CostKind.ACTUAL
    assert estimated.cost.token_count == 4_000
    assert actual.cost.token_count == 4_312, "the actual is kept beside the estimate, not over it"

    # The subject references thread the chain §12.5 describes.
    by_id = {span.span_id: span for span in view.ordered()}
    assert by_id["spn:retrieval"].retrieval_id == "bdl:1"
    assert by_id["spn:llm"].model_call_id == "mc:1"
    assert by_id["spn:job"].job_id == "job:1"

    # ... and the artifact, reached through metadata. Stated as the weak link it is.
    assert by_id["spn:run"].metadata["output_artifact_ids"] == [artifact.artifact_id]
    stored = world.execute(
        "SELECT content_hash FROM artifacts WHERE artifact_id = %s", (artifact.artifact_id,)
    ).fetchone()
    assert stored[0] == artifact.content_hash

    # One trace, one episode, nothing from anywhere else.
    assert {span.trace_id for span in view.spans} == {TRACE}
    assert {span.episode_id for span in view.spans} == {EPISODE}


def test_a_refused_step_leaves_the_trace_readable_and_spends_nothing(world):
    """The other half of observability: an episode that was stopped has to say so.

    A budget refusal mid-episode must leave a BLOCKED span in the same trace, with the reason, and
    must not have performed anything or written to the ledger.
    """
    spans = SqlSpanRepository(world)
    ledger = SqlCostLedger(world)
    now = clock()

    spans.open(
        ExecutionSpan(
            span_id="spn:episode",
            trace_id=TRACE,
            span_type=SpanType.EPISODE,
            episode_id=EPISODE,
            start_time=now(),
            status=SpanStatus.RUNNING,
        )
    )

    def must_not_run() -> ActionOutcome:
        raise AssertionError("the budget refused this; the side effect must not have happened")

    result = dispatch_action(
        DispatchableAction(
            span_id="spn:expensive",
            trace_id=TRACE,
            span_type=SpanType.LLM_CALL,
            parent_span_id="spn:episode",
            episode_id=EPISODE,
            actor_id=SPAN_ACTOR,
            subject_id="mc:2",
            estimate_entry_id="cost:blocked-est",
            actual_entry_id="cost:blocked-act",
            perform=must_not_run,
        ),
        budget("act:hypothesise#2", CostVector(token_count=500_000), CostVector()),
        spans=spans,
        ledger=ledger,
        claims=InMemoryBudgetApprovalClaims(),
        now=now,
    )

    assert result.performed is False
    assert result.span.status is SpanStatus.BLOCKED
    assert "token_count" in result.span.metadata["budget_reason"]

    view = SqlSpanRepository(world).trace(TRACE)
    assert [s.span_id for s in view.ordered()] == ["spn:episode", "spn:expensive"]
    assert view.cost_entry_ids() == (), "a refused dispatch spends nothing"
    assert ledger.entry("cost:blocked-est") is None
    assert ledger.entry("cost:blocked-act") is None

    rows = world.execute("SELECT count(*) FROM cost_entries").fetchone()
    assert rows[0] == 0
