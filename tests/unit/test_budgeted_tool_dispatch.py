"""T-COST-001 through the M2 tool layer — the gate a typed registry call used to go around.

    COST-001    每次 LLM/tool action 前必須經 BudgetGate
    T-COST-001  預算不足時 model/tool call 在產生外部 side effect 前被阻擋；該阻擋可經
                supervisor/human approval 解除
    SIM-003     Tool invocation MUST occur through a typed ToolRegistry

THE DEFECT. Both requirements held, separately, through two seams that did not meet:
`ToolRegistry.invoke` was typed and ungated, `dispatch_action` was gated and knew nothing about
tools. `run_simulation`'s own docstring said budget "belongs to `dispatch_action`" -- true, and
nobody's job -- so the shipped chain `invoke -> ChargeAcSweepTool -> run_simulation ->
backend.execute` reached a simulator without passing a gate.

EVERY PROBE BELOW USES A FATAL SPY. The backend and the tool implementation raise if entered, so
"blocked" is not satisfied by a tool that happened to return nothing: the refusal has to prevent
the call. A probe that only checked `performed is False` would pass against an implementation that
ran the simulator and discarded the result.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from lab_brain.core.budget import (
    BUDGET_OVERRUN_SCOPE,
    BudgetApproval,
    BudgetPolicy,
    DispatchOutcome,
)
from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.cost import BudgetCaps, CostKind, CostVector
from lab_brain.core.models.enums import ActorType
from lab_brain.core.models.execution_span import SpanStatus, SpanType
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.budget import (
    InMemoryBudgetApprovalClaims,
    InMemoryCostLedger,
)
from lab_brain.core.repositories.jobs import InMemoryJobStore
from lab_brain.core.repositories.observability import InMemorySpanRepository
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.dispatch import (
    BudgetedToolDispatcher,
    ToolAction,
    ToolDispatchRefused,
)
from lab_brain.tools.registry import ToolRegistry
from lab_brain.tools.scope import ExecutionScope, ExecutionScopeMismatch, JobBinding
from lab_brain.verification.capability_registry import CapabilityRegistry

pytestmark = [pytest.mark.requirement("COST-001"), pytest.mark.spec_test("T-COST-001")]

NOW = dt.datetime(2026, 9, 24, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:m2"
EPISODE = "epi:m2"
TRACE = "trc:m2"
ACTION = "act:run-sweep"
CONTRACT = "cost:test.sim@1.0.0"
CAPABILITY = "cap:test.sim"
#: The durable Job the sweep executes. Every `run_*` dispatch below names one, because the
#: dispatcher refuses a run request that does not (see the Episode section).
JOB = "job:1"

#: What the estimator says this action costs. Chosen so a cap of 100 admits it and a cap of 10
#: does not, with no arithmetic in the test.
ESTIMATE = CostVector(wall_clock_s=30, license_seat_s=30, money_estimate=Decimal("50"))


class SweepRequest(ToolRequest):
    """A `run_*` request, so it says which durable Job it executes and under which scope.

    The envelope's own scope is the execution's here -- there is no nested request -- which keeps
    the unit-level chain to the two links the dispatcher itself holds: action <-> request, and
    request <-> Job.
    """

    device: str
    job_id: str = JOB

    def job_binding(self) -> JobBinding:
        return JobBinding(
            job_id=self.job_id,
            scope=ExecutionScope(
                layer="SweepRequest",
                project_id=self.project_id,
                trace_id=self.trace_id,
                episode_id=self.episode_id,
                capability_id=CAPABILITY,
            ),
        )


class SweepResult(ToolResult):
    run_id: str


class FatalTool:
    """Raises if entered. A blocked dispatch must not reach it.

    The whole file turns on this class: "the tool did not run" asserted by a spy that would make a
    noise is a different claim from "the result was empty".
    """

    entered: list[ToolRequest]

    def __init__(self) -> None:
        self.entered = []

    @property
    def request_model(self) -> type[SweepRequest]:
        return SweepRequest

    @property
    def result_model(self) -> type[SweepResult]:
        return SweepResult

    def __call__(self, request: ToolRequest) -> SweepResult:
        self.entered.append(request)
        raise AssertionError(
            "the tool was reached without a budget ALLOW. COST-001: the gate runs BEFORE the call"
        )


class WorkingTool(FatalTool):
    def __call__(self, request: ToolRequest) -> SweepResult:
        self.entered.append(request)
        return SweepResult(
            tool_id="DOM-TST-TOOL-002",
            tool_version="1.0.0",
            run_id="run:1",
            actual_cost=CostVector(wall_clock_s=25, license_seat_s=25),
        )


class RaisingTool(FatalTool):
    def __call__(self, request: ToolRequest) -> SweepResult:
        self.entered.append(request)
        raise RuntimeError("the solver crashed")


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="DOM-TST-TOOL-002",
        name="run_sweep",
        tool_class=ToolClass.RUN,
        domain="testing",
        version="1.0.0",
        capability_id=CAPABILITY,
        conditions_schema_version="testing/sweep@1.0.0",
        produces=("test.impedance",),
    )


def _capabilities() -> CapabilityRegistry:
    from lab_brain.core.models.capability import ActionType, Capability

    registry = CapabilityRegistry()
    registry.register_estimator(CONTRACT, lambda params: ESTIMATE)
    registry.register(
        Capability(
            capability_id=CAPABILITY,
            action_type=ActionType.SIMULATION,
            backend_id="test.backend",
            produces=("test.impedance",),
            authority_class="TIER_A",
            estimate_cost_contract=CONTRACT,
            version="1.0.0",
        )
    )
    return registry


def _policy(*, money: int | None = 100) -> BudgetPolicy:
    return BudgetPolicy(
        policy_id="bp:test",
        policy_version="1.0.0",
        project_id=PROJECT,
        caps=BudgetCaps(money_estimate=None if money is None else Decimal(money)),
    )


def _job(**overrides: Any) -> Job:
    """The Job the sweep executes: same project, trace, Episode and capability as the action."""
    payload: dict[str, Any] = {
        "job_id": JOB,
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "capability_id": CAPABILITY,
        "trace_id": TRACE,
        "idempotency_key": "idem:1",
        "submitted_at": NOW - dt.timedelta(minutes=1),
    }
    payload.update(overrides)
    return Job(**payload)


def _jobs(job: Job | None = None) -> InMemoryJobStore:
    store = InMemoryJobStore()
    store.submit(_job() if job is None else job)
    return store


def _action(**overrides: Any) -> ToolAction:
    payload: dict[str, Any] = {
        "tool_id": "DOM-TST-TOOL-002",
        "request": SweepRequest(
            project_id=PROJECT, trace_id=TRACE, episode_id=EPISODE, device="d1"
        ),
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "actor_or_slot": "act:researcher",
        "action_ref": ACTION,
        "trace_id": TRACE,
        "span_id": "spn:1",
        "estimate_entry_id": "cst:est-1",
        "actual_entry_id": "cst:act-1",
    }
    payload.update(overrides)
    return ToolAction(**payload)


def _dispatcher(tool: FatalTool) -> tuple[BudgetedToolDispatcher, InMemoryCostLedger, Any]:
    registry = ToolRegistry()
    registry.register(_descriptor(), tool)
    ledger = InMemoryCostLedger()
    spans = InMemorySpanRepository()
    claims = InMemoryBudgetApprovalClaims()
    return (
        BudgetedToolDispatcher(
            tools=registry,
            capabilities=_capabilities(),
            spans=spans,
            ledger=ledger,
            jobs=_jobs(),
            claims=claims,
            now=lambda: NOW,
        ),
        ledger,
        claims,
    )


# ---------------------------------------------------------------------------
# The refusals. Each one asserts the backend was NOT entered.
# ---------------------------------------------------------------------------


def test_an_over_budget_tool_call_never_reaches_the_implementation():
    """THE probe. `run_charge_ac_sweep`-shaped action, cap below the estimate, fatal spy."""
    tool = FatalTool()
    dispatcher, _ledger, _ = _dispatcher(tool)

    outcome = dispatcher.dispatch(_action(), policy=_policy(money=10))

    assert tool.entered == [], "the tool ran despite being over budget"
    assert not outcome.performed and outcome.result is None
    assert outcome.decision.outcome is DispatchOutcome.BLOCKED
    assert "money_estimate" in outcome.decision.exceeded_dimensions
    assert outcome.span.status is SpanStatus.BLOCKED
    # UX-002: a governance refusal is BLOCKED, not FAILED -- different people get paged.
    assert outcome.span.status is not SpanStatus.FAILED


def test_a_missing_budget_policy_never_reaches_the_implementation():
    """No policy is a refusal, not "no limits". The fail-closed direction."""
    tool = FatalTool()
    dispatcher, _ledger, _ = _dispatcher(tool)

    outcome = dispatcher.dispatch(_action(), policy=None)

    assert tool.entered == []
    assert not outcome.performed
    assert outcome.decision.outcome is DispatchOutcome.BLOCKED
    assert outcome.span.status is SpanStatus.BLOCKED


def test_a_tool_that_cannot_be_priced_is_refused_before_a_span_is_opened():
    """An unpriceable tool is a wiring error, not a budget outcome.

    Refused by raising rather than by a BLOCKED span, so it does not land in a supervisor's queue
    looking like a project that ran out of money -- the distinction `DispatchRefused` draws in
    `core.dispatch`, one layer up.
    """
    tool = FatalTool()
    registry = ToolRegistry()
    registry.register(_descriptor(), tool)
    dispatcher = BudgetedToolDispatcher(
        tools=registry,
        capabilities=CapabilityRegistry(),  # no estimator, no capability
        spans=InMemorySpanRepository(),
        ledger=InMemoryCostLedger(),
        jobs=_jobs(),
        claims=None,
        now=lambda: NOW,
    )
    with pytest.raises(ToolDispatchRefused, match="no registered descriptor"):
        dispatcher.dispatch(_action(), policy=_policy())
    assert tool.entered == []


def test_an_unregistered_tool_is_refused_and_opens_no_span():
    """SIM-003's half inside the budgeted surface: the registry still decides what exists."""
    from lab_brain.tools.registry import ToolNotRegistered

    tool = FatalTool()
    dispatcher, _, _ = _dispatcher(tool)
    with pytest.raises(ToolNotRegistered):
        dispatcher.dispatch(_action(tool_id="DOM-TST-TOOL-999"), policy=_policy())
    assert tool.entered == []


# ---------------------------------------------------------------------------
# The execution envelope — the scope the gate prices IS the scope that executes
#
# THE DEFECT. `dispatch_action` budgets against `ToolAction.project_id` and the registry invokes
# with `ToolRequest.project_id`. Nothing compared them, so an action admitted by project A's caps
# could hand the implementation a request scoped to project B. The gate is not wrong in that story;
# it is answering a question about a different project than the one that runs.
#
# EVERY PROBE BELOW GIVES THE ACTION A BUDGET THAT WOULD HAVE PASSED, AND AN APPROVAL IT DOES NOT
# NEED. Both are deliberate. A cap of 100 against an estimate of 50 means the refusal cannot be the
# budget refusing; a registered approval means the test can show the claim was not spent, which is
# the difference between a call that can be retried once the wiring is fixed and one that cannot.
# ---------------------------------------------------------------------------


def _scope_wiring(
    tool: FatalTool,
    jobs: InMemoryJobStore | None = None,
) -> tuple[
    BudgetedToolDispatcher, InMemoryCostLedger, InMemorySpanRepository, InMemoryBudgetApprovalClaims
]:
    """Like `_dispatcher`, but hands back the span repository too.

    The probes below assert on what was *not* opened, and `_dispatcher` keeps its three-value shape
    so the fourteen tests written against it stay as they were.
    """
    registry = ToolRegistry()
    registry.register(_descriptor(), tool)
    ledger = InMemoryCostLedger()
    spans = InMemorySpanRepository(ledger)
    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:unused", ACTION)
    return (
        BudgetedToolDispatcher(
            tools=registry,
            capabilities=_capabilities(),
            spans=spans,
            ledger=ledger,
            jobs=_jobs() if jobs is None else jobs,
            claims=claims,
            now=lambda: NOW,
        ),
        ledger,
        spans,
        claims,
    )


def _assert_nothing_happened(
    tool: FatalTool,
    ledger: InMemoryCostLedger,
    spans: InMemorySpanRepository,
    claims: InMemoryBudgetApprovalClaims,
) -> None:
    """Every side effect `dispatch` is capable of, asserted absent.

    Written as one helper because the list is the claim: "the tool did not run" is the weakest part
    of it. A refusal that opened the span, wrote the ESTIMATED row and consumed the approval before
    deciding would satisfy `tool.entered == []` and would still have spent the retry.
    """
    assert tool.entered == [], "the implementation was invoked with a mismatched scope"
    assert ledger.entry("cst:est-1") is None, "an ESTIMATED row was written for a refused envelope"
    assert ledger.entry("cst:act-1") is None
    assert spans.get("spn:1") is None, "a span was opened before the envelope was checked"
    assert claims.consumed_at("apr:unused") is None, "an approval was spent on a refused envelope"


def test_an_action_and_request_naming_different_projects_never_reach_the_gate():
    """A cross-project envelope is refused before a span exists. NOT a BLOCKED decision.

    §17.17's BLOCKED span means "this project ran out of money", and a supervisor with
    `BUDGET_OVERRUN` scope can release it. There is no scope under which "execute inside a project
    the gate never evaluated" is releasable, so this leaves the governance channel entirely: it
    raises, and `dispatch` returns no `ToolDispatchResult` to mistake for a decision.
    """
    tool = FatalTool()
    dispatcher, ledger, spans, claims = _scope_wiring(tool)

    with pytest.raises(ExecutionScopeMismatch) as raised:
        dispatcher.dispatch(
            _action(
                request=SweepRequest(
                    project_id="prj:other", trace_id=TRACE, episode_id=EPISODE, device="d1"
                )
            ),
            policy=_policy(money=100),  # would have ALLOWED: the refusal is not the budget's
        )

    assert "ToolAction.project_id is 'prj:m2'" in str(raised.value)
    assert "ToolRequest.project_id is 'prj:other'" in str(raised.value)
    _assert_nothing_happened(tool, ledger, spans, claims)


def test_an_action_and_request_naming_different_traces_never_reach_the_gate():
    """OPS-003's half. A trace that changes mid-call reassembles into two unrelated halves.

    Separate from the project probe rather than bundled with it: a guard that compared only
    `project_id` would pass a combined assertion that had already failed on the first dimension,
    and `trace_id` is the field that makes the span tree readable at all.
    """
    tool = FatalTool()
    dispatcher, ledger, spans, claims = _scope_wiring(tool)

    with pytest.raises(ExecutionScopeMismatch) as raised:
        dispatcher.dispatch(
            _action(
                request=SweepRequest(
                    project_id=PROJECT, trace_id="trc:other", episode_id=EPISODE, device="d1"
                )
            ),
            policy=_policy(money=100),
        )

    assert "ToolAction.trace_id is 'trc:m2'" in str(raised.value)
    assert "ToolRequest.trace_id is 'trc:other'" in str(raised.value)
    # The projects agreed, so the refusal names the trace and only the trace.
    assert "project_id" not in str(raised.value)
    _assert_nothing_happened(tool, ledger, spans, claims)


def test_a_mismatched_envelope_is_refused_even_when_a_supervisor_approval_is_attached():
    """An approval releases an over-budget action. It does not authorise an incoherent one.

    The strongest form of the "not a budget decision" claim: give the refusal every reason to
    become `ALLOWED_BY_APPROVAL` -- a valid, scoped, unexpired approval from a PI who holds the
    scope -- and it still does not execute, and still does not consume the claim.
    """
    tool = FatalTool()
    dispatcher, ledger, spans, claims = _scope_wiring(tool)
    approval = BudgetApproval(
        approval_id="apr:unused",
        approver_actor_id="act:supervisor",
        project_id=PROJECT,
        episode_id=EPISODE,
        action_ref=ACTION,
        policy_id="bp:test",
        policy_version="1.0.0",
        approved_overrun=CostVector(money_estimate=Decimal("100")),
        granted_at=NOW - dt.timedelta(minutes=5),
        expires_at=NOW + dt.timedelta(hours=1),
    )

    with pytest.raises(ExecutionScopeMismatch):
        dispatcher.dispatch(
            _action(
                request=SweepRequest(
                    project_id="prj:other", trace_id=TRACE, episode_id=EPISODE, device="d1"
                ),
                approval=approval,
                approver=Actor(actor_id="act:supervisor", actor_type=ActorType.HUMAN),
                approver_membership=ProjectMembership(
                    actor_id="act:supervisor",
                    project_id=PROJECT,
                    role="PI",
                    approval_scopes=(BUDGET_OVERRUN_SCOPE,),
                ),
            ),
            policy=_policy(money=10),  # over budget AND mis-scoped: the envelope is decided first
        )

    _assert_nothing_happened(tool, ledger, spans, claims)


def test_a_matching_envelope_dispatches_and_the_tool_sees_the_scope_that_was_gated():
    """The positive control. Without it, refusing every dispatch satisfies all three probes above.

    Asserts the identity rather than the outcome: the request the implementation received carries
    the same project and trace the `BudgetRequest` was built from, which is the property the three
    refusals exist to preserve.
    """
    tool = WorkingTool()
    dispatcher, ledger, _spans, _claims = _scope_wiring(tool)
    action = _action()

    outcome = dispatcher.dispatch(action, policy=_policy(money=100))

    assert outcome.performed and len(tool.entered) == 1
    assert tool.entered[0].project_id == action.project_id == PROJECT
    assert tool.entered[0].trace_id == action.trace_id == TRACE
    assert outcome.span.trace_id == action.trace_id
    estimate = ledger.entry("cst:est-1")
    assert estimate is not None and estimate.project_id == action.project_id


# ---------------------------------------------------------------------------
# The Episode that pays is the Episode whose Job executes — decided before the gate
#
# THE DEFECT. COST-001 checks "project/episode caps", writes both ledger rows and releases an
# approval, all against `ToolAction.episode_id`. The execution belongs to `Job.episode_id`. With
# project, trace and capability bound, the two could still differ -- two Episodes of one project
# can share a trace -- and the only check that could see it was `run_simulation`'s step 0, inside
# `perform`, which `dispatch_action` reaches only after consuming the approval and writing the
# ESTIMATED row. Correct about the execution, too late about the money.
#
# EVERY PROBE HERE HAS AN APPROVAL REGISTERED AND A BUDGET THAT WOULD HAVE PASSED, as in the
# envelope section above, so "refused" cannot be the budget's refusal and "unconsumed" is a claim
# about a real claim. And every probe asserts the Job is exactly as it was: a pre-gate refusal that
# moved the Job would be a refusal after the fact with extra steps.
# ---------------------------------------------------------------------------


def _job_untouched(jobs: InMemoryJobStore, before: Job) -> None:
    after = jobs.get(before.job_id)
    assert after == before, "the durable Job was changed by a dispatch that was refused"
    assert after.state is JobState.QUEUED and after.attempt_count == 0
    assert after.result_run_id is None and jobs.run_for_job(before.job_id) is None


def test_an_action_and_request_naming_different_episodes_never_reach_the_gate():
    """The first link. The gate prices Episode E1; the request says it is made in E2.

    Project and trace agree, so the refusal names the Episode and only the Episode.
    """
    tool = FatalTool()
    dispatcher, ledger, spans, claims = _scope_wiring(tool)

    with pytest.raises(ExecutionScopeMismatch) as raised:
        dispatcher.dispatch(
            _action(
                request=SweepRequest(
                    project_id=PROJECT, trace_id=TRACE, episode_id="epi:other", device="d1"
                )
            ),
            policy=_policy(money=100),
        )

    message = str(raised.value)
    assert "ToolAction.episode_id is 'epi:m2'" in message
    assert "ToolRequest.episode_id is 'epi:other'" in message
    assert "project_id" not in message and "trace_id" not in message
    _assert_nothing_happened(tool, ledger, spans, claims)


def test_a_job_that_belongs_to_another_episode_is_refused_before_the_gate():
    """THE BLOCKER. Action, request, project, trace and capability all agree; the Job does not.

    The Job was submitted under a second Episode of the same project on the same trace -- the case
    no other dimension distinguishes. Before this repair the dispatcher asked the gate about E1,
    wrote E1's ESTIMATED row and only then reached a check that could see E2. Now nothing happens:
    no span, no ledger row, no approval consumed, the Job exactly as it was, the tool not entered.
    """
    tool = FatalTool()
    jobs = _jobs(_job(episode_id="epi:m2-other"))
    before = jobs.get(JOB)
    assert before is not None
    dispatcher, ledger, spans, claims = _scope_wiring(tool, jobs)

    with pytest.raises(ExecutionScopeMismatch) as raised:
        dispatcher.dispatch(_action(), policy=_policy(money=100))

    message = str(raised.value)
    assert "SweepRequest.episode_id is 'epi:m2'" in message
    assert "Job.episode_id is 'epi:m2-other'" in message
    for agreed in ("project_id", "trace_id", "capability_id"):
        assert agreed not in message, f"{agreed} agreed and was reported anyway"
    assert "budgeted in episode 'epi:m2'" in message
    _assert_nothing_happened(tool, ledger, spans, claims)
    _job_untouched(jobs, before)


def test_a_job_in_another_episode_does_not_spend_an_approval_that_would_have_released_it():
    """The approval half, made explicit: over budget, a valid scoped PI approval attached.

    `dispatch_action` consumes the claim before it calls `perform`, so a check made anywhere at or
    below `perform` spends this approval on an execution it never released. The approval is for
    ONE action in ONE Episode (§17.17.1); the Episode this Job belongs to never received one.
    """
    tool = FatalTool()
    jobs = _jobs(_job(episode_id="epi:m2-other"))
    before = jobs.get(JOB)
    assert before is not None
    dispatcher, ledger, spans, claims = _scope_wiring(tool, jobs)
    approval = BudgetApproval(
        approval_id="apr:unused",
        approver_actor_id="act:supervisor",
        project_id=PROJECT,
        episode_id=EPISODE,
        action_ref=ACTION,
        policy_id="bp:test",
        policy_version="1.0.0",
        approved_overrun=CostVector(money_estimate=Decimal("100")),
        granted_at=NOW - dt.timedelta(minutes=5),
        expires_at=NOW + dt.timedelta(hours=1),
    )

    with pytest.raises(ExecutionScopeMismatch, match=r"Job\.episode_id is 'epi:m2-other'"):
        dispatcher.dispatch(
            _action(
                approval=approval,
                approver=Actor(actor_id="act:supervisor", actor_type=ActorType.HUMAN),
                approver_membership=ProjectMembership(
                    actor_id="act:supervisor",
                    project_id=PROJECT,
                    role="PI",
                    approval_scopes=(BUDGET_OVERRUN_SCOPE,),
                ),
            ),
            policy=_policy(money=10),  # over budget: only the approval could release it
        )

    _assert_nothing_happened(tool, ledger, spans, claims)
    _job_untouched(jobs, before)


def test_a_job_that_names_no_episode_is_refused_before_the_gate():
    """`Job.episode_id` is nullable in the model; `None` is not the Episode that is paying."""
    tool = FatalTool()
    jobs = _jobs(_job(episode_id=None))
    before = jobs.get(JOB)
    assert before is not None
    dispatcher, ledger, spans, claims = _scope_wiring(tool, jobs)

    with pytest.raises(ExecutionScopeMismatch, match=r"Job\.episode_id is None"):
        dispatcher.dispatch(_action(), policy=_policy(money=100))

    _assert_nothing_happened(tool, ledger, spans, claims)
    _job_untouched(jobs, before)


@pytest.mark.parametrize(
    ("dimension", "value"),
    [
        ("project_id", "prj:other"),
        ("trace_id", "trc:other"),
        ("capability_id", "cap:test.other"),
    ],
)
def test_the_pre_gate_job_binding_holds_every_other_dimension_too(dimension: str, value: str):
    """The same resolution, the other three identities. Each was checked only inside `perform`.

    Repair E bound project, trace and capability to the Job at `run_simulation`'s step 0 -- before
    any Job mutation, seat or backend call, and after the approval and the ESTIMATED row. Resolving
    the Job before the gate for the Episode makes the other three free to move with it, and each is
    refused here naming itself alone.
    """
    tool = FatalTool()
    jobs = _jobs(_job(**{dimension: value}))
    before = jobs.get(JOB)
    assert before is not None
    dispatcher, ledger, spans, claims = _scope_wiring(tool, jobs)

    with pytest.raises(ExecutionScopeMismatch) as raised:
        dispatcher.dispatch(_action(), policy=_policy(money=100))

    message = str(raised.value)
    assert f"Job.{dimension} is {value!r}" in message
    assert "episode_id" not in message, "the Episode agreed and was reported anyway"
    _assert_nothing_happened(tool, ledger, spans, claims)
    _job_untouched(jobs, before)


class UnboundSweepRequest(ToolRequest):
    """A `run_*` request that does not say which Job it executes -- the base `job_binding`."""

    device: str


class UnboundFatalTool(FatalTool):
    @property
    def request_model(self) -> type[UnboundSweepRequest]:  # type: ignore[override]
        return UnboundSweepRequest


def test_a_run_request_that_binds_no_job_is_refused_before_the_gate():
    """Fail closed: the absence of a binding is not a pass.

    Were `None` accepted, a run tool whose request forgot to override `job_binding` would skip the
    pre-gate check without anyone noticing, and the Episode the gate priced would again be
    unrelated to the Episode that executed.
    """
    tool = UnboundFatalTool()
    dispatcher, ledger, spans, claims = _scope_wiring(tool)

    with pytest.raises(ToolDispatchRefused, match="binds no durable Job"):
        dispatcher.dispatch(
            _action(
                request=UnboundSweepRequest(
                    project_id=PROJECT, trace_id=TRACE, episode_id=EPISODE, device="d1"
                )
            ),
            policy=_policy(money=100),
        )

    _assert_nothing_happened(tool, ledger, spans, claims)


def test_a_request_binding_a_job_that_does_not_resolve_is_refused_before_the_gate():
    """No Job, no Episode to compare the budget with, and nothing to attribute a Run to."""
    tool = FatalTool()
    dispatcher, ledger, spans, claims = _scope_wiring(tool)

    with pytest.raises(ToolDispatchRefused, match="does not resolve"):
        dispatcher.dispatch(
            _action(
                request=SweepRequest(
                    project_id=PROJECT,
                    trace_id=TRACE,
                    episode_id=EPISODE,
                    device="d1",
                    job_id="job:ghost",
                )
            ),
            policy=_policy(money=100),
        )

    _assert_nothing_happened(tool, ledger, spans, claims)


def test_a_job_in_the_budgeted_episode_dispatches_and_every_record_names_that_episode():
    """The positive control, asserted as the invariant rather than as "it ran".

    ToolAction.episode_id == ToolRequest.episode_id == Job.episode_id, and the records COST-001
    writes -- both ledger rows and the span -- carry that same Episode.
    """
    tool = WorkingTool()
    jobs = _jobs()
    dispatcher, ledger, _spans, _claims = _scope_wiring(tool, jobs)
    action = _action()

    outcome = dispatcher.dispatch(action, policy=_policy(money=100))

    assert outcome.performed and len(tool.entered) == 1
    job = jobs.get(JOB)
    assert job is not None
    assert action.episode_id == tool.entered[0].episode_id == job.episode_id == EPISODE
    estimate, actual = ledger.entry("cst:est-1"), ledger.entry("cst:act-1")
    assert estimate is not None and actual is not None
    assert estimate.episode_id == actual.episode_id == job.episode_id
    assert outcome.span.episode_id == job.episode_id


# ---------------------------------------------------------------------------
# The positive controls
# ---------------------------------------------------------------------------


def test_an_in_budget_tool_call_runs_through_the_typed_registry():
    """Without this, "refuse everything" satisfies every probe above."""
    tool = WorkingTool()
    dispatcher, _ledger, _ = _dispatcher(tool)

    outcome = dispatcher.dispatch(_action(), policy=_policy())

    assert outcome.performed
    assert isinstance(outcome.result, SweepResult) and outcome.result.run_id == "run:1"
    assert len(tool.entered) == 1
    # It went through the registry: the payload the tool saw is the typed request, not a dict.
    assert isinstance(tool.entered[0], SweepRequest)
    assert outcome.span.status is SpanStatus.SUCCEEDED
    assert outcome.span.span_type is SpanType.TOOL_CALL


def test_a_scoped_supervisor_approval_releases_the_same_over_budget_action():
    """T-COST-001: the block MUST be liftable by a named human, and the approval is an event.

    §14.3's supervisor path is what separates a budget from a permanent refusal. The approval is
    narrow -- one action, one episode, one project, one policy version, once -- and every one of
    those is checked by `evaluate_budget`, which this test does not re-implement.
    """
    tool = WorkingTool()
    dispatcher, _ledger, claims = _dispatcher(tool)

    approval = BudgetApproval(
        approval_id="apr:1",
        approver_actor_id="act:supervisor",
        project_id=PROJECT,
        episode_id=EPISODE,
        action_ref=ACTION,
        policy_id="bp:test",
        policy_version="1.0.0",
        approved_overrun=CostVector(money_estimate=Decimal("100")),
        granted_at=NOW - dt.timedelta(minutes=5),
        expires_at=NOW + dt.timedelta(hours=1),
    )
    claims.register(approval.approval_id, ACTION)

    outcome = dispatcher.dispatch(
        _action(
            approval=approval,
            approver=Actor(actor_id="act:supervisor", actor_type=ActorType.HUMAN),
            approver_membership=ProjectMembership(
                actor_id="act:supervisor",
                project_id=PROJECT,
                role="PI",
                approval_scopes=(BUDGET_OVERRUN_SCOPE,),
            ),
        ),
        policy=_policy(money=10),
    )

    assert outcome.performed, outcome.decision.reason
    assert outcome.decision.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL
    assert outcome.decision.approval_id == "apr:1"
    assert len(tool.entered) == 1


def test_the_same_approval_cannot_release_a_second_call():
    """§17.17.1: ONCE is part of what an approval is, and it is the store that enforces it."""
    tool = WorkingTool()
    dispatcher, _, claims = _dispatcher(tool)
    approval = BudgetApproval(
        approval_id="apr:1",
        approver_actor_id="act:supervisor",
        project_id=PROJECT,
        episode_id=EPISODE,
        action_ref=ACTION,
        policy_id="bp:test",
        policy_version="1.0.0",
        approved_overrun=CostVector(money_estimate=Decimal("100")),
        granted_at=NOW - dt.timedelta(minutes=5),
        expires_at=NOW + dt.timedelta(hours=1),
    )
    claims.register(approval.approval_id, ACTION)
    supervisor = {
        "approval": approval,
        "approver": Actor(actor_id="act:supervisor", actor_type=ActorType.HUMAN),
        "approver_membership": ProjectMembership(
            actor_id="act:supervisor",
            project_id=PROJECT,
            role="PI",
            approval_scopes=(BUDGET_OVERRUN_SCOPE,),
        ),
    }

    first = dispatcher.dispatch(_action(**supervisor), policy=_policy(money=10))
    second = dispatcher.dispatch(
        _action(
            span_id="spn:2",
            estimate_entry_id="cst:est-2",
            actual_entry_id="cst:act-2",
            **supervisor,
        ),
        policy=_policy(money=10),
    )

    assert first.performed
    assert not second.performed, "one approval released two calls"
    assert len(tool.entered) == 1


# ---------------------------------------------------------------------------
# The ledger: estimate before, actual after, never substituted
# ---------------------------------------------------------------------------


def test_the_estimate_is_recorded_before_the_tool_runs_and_the_actual_after():
    """§17.17's two rows. The estimate is the gate's INPUT and the evidence for the admission."""
    tool = WorkingTool()
    dispatcher, ledger, _ = _dispatcher(tool)

    outcome = dispatcher.dispatch(_action(), policy=_policy())
    assert outcome.performed

    estimate = ledger.entry("cst:est-1")
    actual = ledger.entry("cst:act-1")
    assert estimate is not None and actual is not None
    assert estimate.cost_kind is CostKind.ESTIMATED
    assert actual.cost_kind is CostKind.ACTUAL
    assert estimate.cost == ESTIMATE
    assert estimate.action_ref == actual.action_ref == ACTION
    # Both rows are linked to the span, which is what makes the trace reassemblable (OPS-003).
    assert set(outcome.span.cost_entry_ids) == {"cst:est-1", "cst:act-1"}


def test_the_actual_is_measured_and_not_copied_from_the_estimate():
    """The half that makes systematic under-estimation visible.

    The working tool reports 25s and 25 seat-seconds against an estimate of 30/30/50 money. If the
    dispatcher substituted the estimate, the two rows would be equal and the ledger would prove
    nothing about the accuracy of anybody's prediction.
    """
    tool = WorkingTool()
    dispatcher, ledger, _ = _dispatcher(tool)
    dispatcher.dispatch(_action(), policy=_policy())

    actual = ledger.entry("cst:act-1")
    assert actual is not None
    assert actual.cost != ESTIMATE
    assert actual.cost.wall_clock_s == 25 and actual.cost.license_seat_s == 25
    # Money was never measured, so it is zero rather than the estimate's 50 -- and the span says
    # the tool reported its own cost, so a reader can tell "measured zero" from "not measured".
    assert actual.cost.money_estimate == Decimal(0)
    assert actual.cost.money_estimate != ESTIMATE.money_estimate


def test_a_refused_dispatch_records_no_ledger_row_at_all():
    """A governance refusal must not consume the estimate slot the retry will need.

    `core.dispatch`'s own reasoning, inherited: `cost_entries` holds one ESTIMATED row per
    `action_ref`, so recording the refused attempt would poison the legitimate retry a supervisor's
    approval exists to enable.
    """
    tool = FatalTool()
    dispatcher, ledger, _ = _dispatcher(tool)
    outcome = dispatcher.dispatch(_action(), policy=_policy(money=10))

    assert not outcome.performed
    assert ledger.entry("cst:est-1") is None
    assert ledger.entry("cst:act-1") is None
    # ...and the magnitude of what was refused is still readable, on the span.
    assert outcome.span.metadata["budget_reason"]
    assert outcome.span.metadata["budget_estimate"]["money_estimate"] == "50"


def test_a_failing_tool_leaves_a_failed_span_the_estimate_and_no_actual():
    """An action that raised did not report a cost, and substituting one would record a number
    nobody measured -- in the one place whose purpose is to make estimates checkable."""
    tool = RaisingTool()
    dispatcher, ledger, _ = _dispatcher(tool)

    with pytest.raises(RuntimeError, match="the solver crashed"):
        dispatcher.dispatch(_action(), policy=_policy())

    assert len(tool.entered) == 1, "the gate blocked a call it should have allowed"
    assert ledger.entry("cst:est-1") is not None
    assert ledger.entry("cst:act-1") is None


# ---------------------------------------------------------------------------
# Local tools are gated too
# ---------------------------------------------------------------------------


def test_a_zero_cost_local_tool_still_passes_the_gate():
    """ "Cheap" is not "ungoverned". COST-001 gates each tool call, not each expensive one."""

    class Ping(ToolRequest):
        pass

    class Pong(ToolResult):
        pass

    entered: list[ToolRequest] = []

    class Local:
        @property
        def request_model(self) -> type[Ping]:
            return Ping

        @property
        def result_model(self) -> type[Pong]:
            return Pong

        def __call__(self, request: ToolRequest) -> Pong:
            entered.append(request)
            return Pong(tool_id="DOM-TST-TOOL-004", tool_version="1.0.0")

    registry = ToolRegistry()
    registry.register(
        ToolDescriptor(
            tool_id="DOM-TST-TOOL-004",
            name="extract_thing",
            tool_class=ToolClass.EXTRACT,
            domain="testing",
            version="1.0.0",
            cost_contract="cost:test.local@1.0.0",
            requires=("test.impedance",),
            produces=("test.metric",),
        ),
        Local(),
    )
    capabilities = _capabilities()
    capabilities.register_estimator("cost:test.local@1.0.0", lambda params: CostVector())
    ledger = InMemoryCostLedger()
    dispatcher = BudgetedToolDispatcher(
        tools=registry,
        capabilities=capabilities,
        spans=InMemorySpanRepository(),
        ledger=ledger,
        jobs=InMemoryJobStore(),
        claims=InMemoryBudgetApprovalClaims(),
        now=lambda: NOW,
    )

    outcome = dispatcher.dispatch(
        _action(
            tool_id="DOM-TST-TOOL-004",
            request=Ping(project_id=PROJECT, trace_id=TRACE, episode_id=EPISODE),
        ),
        policy=_policy(),
    )
    assert outcome.performed
    assert outcome.estimate == CostVector(), "a zero estimate is a claim, not an exemption"
    # It passed THROUGH the gate: the estimate was recorded and the span is a real TOOL_CALL.
    assert ledger.entry("cst:est-1") is not None
    assert outcome.span.span_type is SpanType.TOOL_CALL


def test_a_local_tool_whose_contract_is_unregistered_is_refused():
    """A zero CostVector is a legitimate answer; having no answer is not."""

    class Ping(ToolRequest):
        pass

    class Pong(ToolResult):
        pass

    class Local:
        @property
        def request_model(self) -> type[Ping]:
            return Ping

        @property
        def result_model(self) -> type[Pong]:
            return Pong

        def __call__(self, request: ToolRequest) -> Pong:  # pragma: no cover - never reached
            raise AssertionError("an unpriceable tool ran")

    registry = ToolRegistry()
    registry.register(
        ToolDescriptor(
            tool_id="DOM-TST-TOOL-004",
            name="extract_thing",
            tool_class=ToolClass.EXTRACT,
            domain="testing",
            version="1.0.0",
            cost_contract="cost:nobody@1.0.0",
            requires=("test.impedance",),
            produces=("test.metric",),
        ),
        Local(),
    )
    dispatcher = BudgetedToolDispatcher(
        tools=registry,
        capabilities=_capabilities(),
        spans=InMemorySpanRepository(),
        ledger=InMemoryCostLedger(),
        jobs=InMemoryJobStore(),
        claims=None,
        now=lambda: NOW,
    )
    with pytest.raises(ToolDispatchRefused, match="'cheap' is not 'ungoverned'"):
        dispatcher.dispatch(
            _action(
                tool_id="DOM-TST-TOOL-004",
                request=Ping(project_id=PROJECT, trace_id=TRACE, episode_id=EPISODE),
            ),
            policy=_policy(),
        )


# ---------------------------------------------------------------------------
# The structural claim: production orchestration does not expose the raw registry
# ---------------------------------------------------------------------------


def test_estimate_for_prices_a_run_tool_through_its_capability():
    """§9.5: the Capability descriptor is the authoritative estimator for a backend-bound tool."""
    dispatcher, _, _ = _dispatcher(WorkingTool())
    assert dispatcher.estimate_for("DOM-TST-TOOL-002", {}) == ESTIMATE
