"""The execution seam: the budget is checked BEFORE the side effect, and the trace records both.

    §17.17  Before each LLM/tool call, BudgetGate MUST check project/episode caps.
    OPS-003 Execution observability MUST persist trace/span contract ... with status and cost refs.

This is the file that closes the gap risk R-10 named. The budget gate and the cost ledger were
correct and uncalled: `evaluate_budget` refused what it should, the claim was atomic and durable,
the ledger was append-only -- and nothing in the system asked any of them anything.

The property that matters most here cannot be checked by inspecting a result. "Did the budget get
consulted before the money was spent" is a question about *order*, so every test below that cares
about it uses an action whose `perform` records the fact that it ran, or refuses to run at all.
An assertion on the returned decision would pass just as happily if the call had already happened.
"""

from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal

import pytest

from lab_brain.core.budget import (
    BUDGET_OVERRUN_SCOPE,
    BudgetApproval,
    BudgetPolicy,
    BudgetRequest,
    DispatchOutcome,
)
from lab_brain.core.dispatch import (
    ActionOutcome,
    DispatchableAction,
    DispatchRefused,
    dispatch_action,
)
from lab_brain.core.models import (
    Actor,
    ActorType,
    BudgetCaps,
    CostKind,
    CostVector,
    ExecutionSpan,
    ProjectMembership,
    SpanStatus,
    SpanType,
)
from lab_brain.core.repositories import (
    InMemoryBudgetApprovalClaims,
    InMemoryCostLedger,
    InMemorySpanRepository,
    SpanLifecycleError,
)

pytestmark = [
    pytest.mark.requirement("OPS-003"),
    pytest.mark.spec_test("T-OPS-003"),
]

T0 = dt.datetime(2026, 9, 15, 9, 0, tzinfo=dt.UTC)
TRACE = "trc:episode-1"
PROJECT = "prj:photonics"
EPISODE = "ep:rs-anomaly-1"
SLOT = "slot:planner"
SUPERVISOR = "act:prof-lin"
ACTION = "act:run_charge_dc_sweep#7"

POLICY = BudgetPolicy(
    policy_id="pol:session-default",
    policy_version="1.0.0",
    project_id=PROJECT,
    caps=BudgetCaps(money_estimate=Decimal("50.00"), token_count=100_000),
)
SUPERVISOR_ACTOR = Actor(actor_id=SUPERVISOR, actor_type=ActorType.HUMAN)
SUPERVISOR_MEMBERSHIP = ProjectMembership(
    actor_id=SUPERVISOR,
    project_id=PROJECT,
    role="supervisor",
    approval_scopes=frozenset({BUDGET_OVERRUN_SCOPE}),
)


def clock():
    """A monotonic fake clock. A span has a start and an end; one value makes every action
    instantaneous and hides the thing observability measures."""
    ticks = itertools.count()
    return lambda: T0 + dt.timedelta(seconds=next(ticks))


def budget_request(**overrides: object) -> BudgetRequest:
    defaults: dict[str, object] = {
        "action_ref": ACTION,
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "actor_id": SLOT,
        "estimate": CostVector(money_estimate=Decimal("1.00"), token_count=1_200),
        "consumed": CostVector(),
        "policy": POLICY,
        "now": T0,
        "approver": SUPERVISOR_ACTOR,
        "approver_membership": SUPERVISOR_MEMBERSHIP,
    }
    defaults.update(overrides)
    return BudgetRequest(**defaults)  # type: ignore[arg-type]


def approval(**overrides: object) -> BudgetApproval:
    defaults: dict[str, object] = {
        "approval_id": "apr:1",
        "approver_actor_id": SUPERVISOR,
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "action_ref": ACTION,
        "policy_id": POLICY.policy_id,
        "policy_version": POLICY.policy_version,
        "approved_overrun": CostVector(money_estimate=Decimal("100.00")),
        "granted_at": T0 - dt.timedelta(minutes=5),
        "expires_at": T0 + dt.timedelta(minutes=30),
    }
    defaults.update(overrides)
    return BudgetApproval(**defaults)  # type: ignore[arg-type]


class Recorder:
    """An action that records whether it ran, and what it cost when it did."""

    def __init__(self, actual: CostVector | None = None) -> None:
        self.calls = 0
        self._actual = actual or CostVector(money_estimate=Decimal("1.37"), token_count=1_310)

    def __call__(self) -> ActionOutcome:
        self.calls += 1
        return ActionOutcome(actual_cost=self._actual, metadata={"ran": True})


def forbidden() -> ActionOutcome:
    """An action that must never be reached. The ordering guarantee, made executable."""
    raise AssertionError(
        "the side effect ran. The budget gate is supposed to decide BEFORE this is called, and a "
        "gate that runs beside the call rather than before it is accounting, not a gate"
    )


def action(perform, **overrides: object) -> DispatchableAction:
    defaults: dict[str, object] = {
        "span_id": "spn:tool",
        "trace_id": TRACE,
        "span_type": SpanType.TOOL_CALL,
        "estimate_entry_id": "cost:est-1",
        "actual_entry_id": "cost:act-1",
        "perform": perform,
        "episode_id": EPISODE,
        "actor_id": SLOT,
    }
    defaults.update(overrides)
    return DispatchableAction(**defaults)  # type: ignore[arg-type]


def seam(**overrides):
    # The span store is given the ledger, so cost refs are checked here exactly as
    # `execution_span_close` checks them in SQL. The seam is the caller that can supply it, so it
    # is the caller that should -- an unchecked ref is only tolerable where nothing can resolve it.
    ledger = InMemoryCostLedger()
    defaults = {
        "spans": InMemorySpanRepository(ledger=ledger),
        "ledger": ledger,
        "claims": InMemoryBudgetApprovalClaims(),
        "now": clock(),
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------------------------
# The ordering guarantee. This is why the seam exists.
# --------------------------------------------------------------------------------------------


def test_an_over_budget_action_is_never_performed():
    """The whole point. `forbidden` raises if it is reached, so passing proves the order."""
    kit = seam()
    result = dispatch_action(
        action(forbidden),
        budget_request(estimate=CostVector(money_estimate=Decimal("75.00"))),
        **kit,
    )
    assert result.performed is False
    assert result.blocked is True
    assert result.span.status is SpanStatus.BLOCKED


def test_an_unbudgeted_project_never_reaches_the_side_effect():
    """An unbudgeted project is not an unlimited one, and the refusal happens before dispatch."""
    result = dispatch_action(action(forbidden), budget_request(policy=None), **seam())
    assert result.performed is False
    assert "no budget policy" in result.decision.reason


def test_an_approval_from_an_unauthorised_signer_never_reaches_the_side_effect():
    """The Phase C authority checks, now reached through the seam rather than only in isolation."""
    result = dispatch_action(
        action(forbidden),
        budget_request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(),
            approver=SUPERVISOR_ACTOR.model_copy(update={"actor_type": ActorType.AGENT_ROLE}),
        ),
        **seam(),
    )
    assert result.performed is False
    assert "supervisor/human" in result.decision.reason


def test_an_in_budget_action_is_performed_exactly_once():
    """The seam must be passable, and must not retry on its own initiative."""
    recorder = Recorder()
    result = dispatch_action(action(recorder), budget_request(), **seam())
    assert recorder.calls == 1
    assert result.performed is True
    assert result.span.status is SpanStatus.SUCCEEDED


def test_a_dispatch_with_no_estimate_is_a_wiring_error_not_a_budget_refusal():
    """A missing estimator is not a project out of money.

    Recording it as BLOCKED would put a programming mistake in the supervisor's approval queue.
    """
    with pytest.raises(DispatchRefused, match="no cost estimate"):
        dispatch_action(action(forbidden), budget_request(estimate=None), **seam())


# --------------------------------------------------------------------------------------------
# Status and cost refs. OPS-003's two named outputs.
# --------------------------------------------------------------------------------------------


def test_a_successful_dispatch_links_both_the_estimate_and_the_actual():
    """§17.17 keeps them as two rows; the span has to point at both or the trace is half a story."""
    kit = seam()
    result = dispatch_action(action(Recorder()), budget_request(), **kit)

    assert result.span.cost_entry_ids == ("cost:est-1", "cost:act-1")
    ledger = kit["ledger"]
    assert ledger.entry("cost:est-1").cost_kind is CostKind.ESTIMATED
    assert ledger.entry("cost:act-1").cost_kind is CostKind.ACTUAL
    assert ledger.entry("cost:est-1").cost.token_count == 1_200
    assert ledger.entry("cost:act-1").cost.token_count == 1_310


def test_a_blocked_dispatch_writes_nothing_to_the_ledger():
    """The ledger records money; the trace records attempts.

    An earlier version recorded the estimate before asking, so that a refusal's magnitude was
    visible. It had a defect this test pins: `cost_entries` holds one ESTIMATED row per
    `action_ref`, so a refused attempt consumed the slot and the legitimate retry after a
    supervisor approved the overrun could never record its own estimate. A governance refusal
    would have permanently poisoned the action it refused.
    """
    kit = seam()
    result = dispatch_action(
        action(forbidden),
        budget_request(estimate=CostVector(money_estimate=Decimal("75.00"))),
        **kit,
    )
    assert result.span.cost_entry_ids == ()
    assert kit["ledger"].entry("cost:est-1") is None
    assert kit["ledger"].entry("cost:act-1") is None


def test_an_approved_retry_of_a_refused_action_can_still_record_its_estimate():
    """The defect the test above describes, from the other side.

    Refuse once, then approve and retry the *same* action_ref -- which is the whole point of the
    §14.3 approval path. If the refusal had taken the ledger slot, this would fail on a uniqueness
    violation rather than dispatching.
    """
    kit = seam()
    kit["claims"].register("apr:1", ACTION)
    over = CostVector(money_estimate=Decimal("75.00"))

    refused = dispatch_action(action(forbidden), budget_request(estimate=over), **kit)
    assert refused.performed is False

    recorder = Recorder()
    retried = dispatch_action(
        action(recorder, span_id="spn:tool-retry"),
        budget_request(estimate=over, approval=approval()),
        **kit,
    )
    assert retried.performed is True
    assert recorder.calls == 1
    assert kit["ledger"].entry("cost:est-1").cost.money_estimate == Decimal("75.00")


def test_a_blocked_span_records_the_reason_and_the_magnitude():
    """A BLOCKED span with no reason tells the reviewer only that something did not happen.

    The magnitude has to be there too, or "the cap is too tight" is unarguable from the record.
    """
    kit = seam()
    result = dispatch_action(
        action(forbidden),
        budget_request(estimate=CostVector(token_count=500_000)),
        **kit,
    )
    assert "token_count" in result.span.metadata["budget_reason"]
    assert result.span.metadata["budget_exceeded"] == ["token_count"]
    assert result.span.metadata["budget_estimate"]["token_count"] == "500000"


def test_an_action_released_by_an_approval_records_the_approval_on_the_actual_cost():
    """COST-001: the ledger shows not only that the money went but that someone signed for it."""
    kit = seam()
    kit["claims"].register("apr:1", ACTION)
    result = dispatch_action(
        action(Recorder()),
        budget_request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval()),
        **kit,
    )
    assert result.decision.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL
    assert kit["ledger"].entry("cost:act-1").approval_id == "apr:1"


def test_an_approval_the_store_has_never_heard_of_is_refused():
    """Fail closed, and say so accurately.

    The gate has already checked this approval's scope and its signer's authority, so a claim that
    finds no such row is a data-integrity problem rather than contention. It must still refuse --
    and the reason must not assert that the approval "was consumed", because it never existed.
    """
    kit = seam()
    result = dispatch_action(
        action(forbidden),
        budget_request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval()),
        **kit,
    )
    assert result.performed is False
    assert "no unconsumed approval with that id exists" in result.decision.reason


def test_a_failing_action_records_no_actual_cost():
    """An action that raised did not report a cost, and the estimate must not stand in for one.

    Substituting it would put an unmeasured number in the one place whose purpose is to make
    estimates checkable against reality.
    """
    kit = seam()

    def boom() -> ActionOutcome:
        raise RuntimeError("backend exploded")

    with pytest.raises(RuntimeError, match="backend exploded"):
        dispatch_action(action(boom), budget_request(), **kit)

    span = kit["spans"].get("spn:tool")
    assert span.status is SpanStatus.FAILED
    assert span.cost_entry_ids == ("cost:est-1",)
    assert kit["ledger"].entry("cost:act-1") is None


def test_a_failure_is_failed_and_a_refusal_is_blocked():
    """They are different statuses because they send different people (UX-002)."""
    kit = seam()

    def boom() -> ActionOutcome:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        dispatch_action(action(boom), budget_request(), **kit)
    assert kit["spans"].get("spn:tool").status is SpanStatus.FAILED

    kit2 = seam()
    blocked = dispatch_action(
        action(forbidden),
        budget_request(estimate=CostVector(money_estimate=Decimal("999"))),
        **kit2,
    )
    assert blocked.span.status is SpanStatus.BLOCKED


# --------------------------------------------------------------------------------------------
# The trace. Threading, not just recording.
# --------------------------------------------------------------------------------------------


def _root(kit) -> None:
    """The episode span every dispatch below parents itself to.

    Opened explicitly because a parent must exist and be in the same trace (010b). The first
    version of this file dispatched under a `spn:root` it never created, and the parent check added
    in P6-fix is what caught it.
    """
    kit["spans"].open(
        ExecutionSpan(
            span_id="spn:root",
            trace_id=TRACE,
            span_type=SpanType.EPISODE,
            episode_id=EPISODE,
            start_time=T0,
            status=SpanStatus.RUNNING,
        )
    )


def test_the_span_is_parented_and_traced_as_asked():
    kit = seam()
    _root(kit)
    dispatch_action(
        action(
            Recorder(), parent_span_id="spn:root", span_type=SpanType.LLM_CALL, subject_id="mc:1"
        ),
        budget_request(),
        **kit,
    )
    span = kit["spans"].get("spn:tool")
    assert (span.trace_id, span.parent_span_id) == (TRACE, "spn:root")
    assert span.span_type is SpanType.LLM_CALL
    assert span.model_call_id == "mc:1"


def test_dispatching_under_a_parent_that_does_not_exist_records_nothing():
    """A span claiming an absent parent is corrupt, and the seam must not half-record it."""
    kit = seam()
    with pytest.raises(SpanLifecycleError, match="which is not recorded"):
        dispatch_action(action(forbidden, parent_span_id="spn:nowhere"), budget_request(), **kit)
    assert kit["spans"].get("spn:tool") is None
    assert kit["ledger"].entry("cost:est-1") is None


def test_a_subject_on_a_type_that_takes_none_is_refused_before_anything_is_recorded():
    kit = seam()
    with pytest.raises(DispatchRefused, match="takes no subject reference"):
        dispatch_action(
            action(forbidden, span_type=SpanType.EPISODE, subject_id="job:1"),
            budget_request(),
            **kit,
        )
    assert kit["spans"].get("spn:tool") is None
    assert kit["ledger"].entry("cost:est-1") is None


def test_the_span_ends_after_it_starts():
    """The injected clock advances, so a real duration is recorded rather than zero."""
    kit = seam()
    result = dispatch_action(action(Recorder()), budget_request(), **kit)
    assert result.span.duration_s is not None and result.span.duration_s > 0


# --------------------------------------------------------------------------------------------
# The seam inherits the approval rules rather than reimplementing them.
# --------------------------------------------------------------------------------------------


def test_one_approval_releases_one_dispatch_through_the_seam():
    """ONCE, observed end to end: the second identical dispatch is blocked and never performed.

    The same request object both times, so the pure gate has no way to tell the calls apart --
    only the claim store does, which is the property Phase C's atomic claim exists for.
    """
    kit = seam()
    kit["claims"].register("apr:1", ACTION)
    over = budget_request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval())

    first = dispatch_action(action(Recorder()), over, **kit)
    second = dispatch_action(action(forbidden, span_id="spn:tool-2"), over, **kit)

    assert first.performed is True
    assert second.performed is False
    assert "already consumed" in second.decision.reason


def test_dispatch_without_a_claim_store_refuses_an_approval_dependent_action():
    """Fail closed, and without performing anything."""
    result = dispatch_action(
        action(forbidden),
        budget_request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval()),
        **seam(claims=None),
    )
    assert result.performed is False
    assert "no claim store" in result.decision.reason


def test_the_seam_does_not_claim_to_have_cleared_the_critique_gate():
    """§7.6 is a different gate with a different authority (§17.17.1).

    The seam is where `critique_gate` will attach in M3. Until then a caller must not read a
    successful dispatch as critique having happened, so the result exposes no such claim.
    """
    kit = seam()
    result = dispatch_action(action(Recorder()), budget_request(), **kit)
    for forbidden_attr in ("critique_cleared", "allowed", "approved"):
        assert not hasattr(result, forbidden_attr), forbidden_attr
    assert result.decision.budget_permits is True
