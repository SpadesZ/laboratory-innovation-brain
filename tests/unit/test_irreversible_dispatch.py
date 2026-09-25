"""SRC-002's second trigger: an irreversible action does not dispatch without independent critique.

    SRC-002  §7.6 的 independent critique path 有兩個 trigger，非只一個：重大 REJECT 與
             irreversible action。標記為 irreversible 的 Capability/action MUST NOT 被 dispatch，
             除非 independent critique 已完成 —— 即使該 action 完全不造成 belief transition。...
             human approval 本身不可取代 critique。
    T-SRC-002 負面 fixture：標記 irreversible 的 action 在 critique 未完成時 MUST NOT dispatch，
             即使 `causes_belief_revision = false`；且帶有效 human approval 但無 critique 時仍
             MUST NOT dispatch。

A tool dispatch causes no belief transition by construction -- `BudgetedToolDispatcher` writes no
event -- so every refusal below is the `causes_belief_revision = false` case the row names. The
tool is a fatal spy: "refused" means it was never entered, and the approval claim is asserted
unspent, because a refusal that consumed a supervisor's one-time approval would be a second harm.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from lab_brain.core.budget import BUDGET_OVERRUN_SCOPE, BudgetApproval, BudgetPolicy
from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.capability import ActionType, Capability
from lab_brain.core.models.cost import BudgetCaps, CostVector
from lab_brain.core.models.enums import ActorType
from lab_brain.core.models.job import Job
from lab_brain.core.repositories.budget import InMemoryBudgetApprovalClaims, InMemoryCostLedger
from lab_brain.core.repositories.jobs import InMemoryJobStore
from lab_brain.core.repositories.observability import InMemorySpanRepository
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.dispatch import BudgetedToolDispatcher, ToolAction, ToolDispatchRefused
from lab_brain.tools.registry import ToolRegistry
from lab_brain.tools.scope import ExecutionScope, JobBinding
from lab_brain.verification.capability_registry import CapabilityRegistry
from tests.debate_fixtures import EPISODE, PROJECT, TRACE, build_world, load_fixture

pytestmark = [pytest.mark.requirement("SRC-002"), pytest.mark.spec_test("T-SRC-002")]

NOW = dt.datetime(2026, 9, 27, 9, 0, tzinfo=dt.UTC)
CAPABILITY = "cap:test.tapeout"
CONTRACT = "cost:test.tapeout@1.0.0"
ACTION = "act:submit-tapeout"
JOB = "job:tapeout"
ESTIMATE = CostVector(money_estimate=Decimal("50"))


class TapeoutRequest(ToolRequest):
    design: str

    def job_binding(self) -> JobBinding:
        return JobBinding(
            job_id=JOB,
            scope=ExecutionScope(
                layer="TapeoutRequest",
                project_id=self.project_id,
                trace_id=self.trace_id,
                episode_id=self.episode_id,
                capability_id=CAPABILITY,
            ),
        )


class TapeoutResult(ToolResult):
    order_id: str


class Spy:
    def __init__(self, *, fatal: bool) -> None:
        self.fatal = fatal
        self.entered: list[ToolRequest] = []

    @property
    def request_model(self) -> type[TapeoutRequest]:
        return TapeoutRequest

    @property
    def result_model(self) -> type[TapeoutResult]:
        return TapeoutResult

    def __call__(self, request: ToolRequest) -> TapeoutResult:
        self.entered.append(request)
        if self.fatal:
            raise AssertionError("an irreversible action was dispatched without its critique")
        return TapeoutResult(tool_id="DOM-TST-TOOL-100", tool_version="1.0.0", order_id="ord:1")


def _capabilities(*, irreversible: bool, estimate_irreversible: bool = False) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register_estimator(
        CONTRACT,
        lambda params: ESTIMATE.model_copy(update={"irreversible": estimate_irreversible}),
    )
    registry.register(
        Capability(
            capability_id=CAPABILITY,
            action_type=ActionType.FABRICATION if irreversible else ActionType.SIMULATION,
            backend_id="test.foundry",
            produces=("test.wafer",),
            authority_class="TIER_A",
            irreversible=irreversible,
            estimate_cost_contract=CONTRACT,
            version="1.0.0",
        )
    )
    return registry


def _dispatcher(
    tool: Spy, *, capabilities: CapabilityRegistry, critiques: Any
) -> tuple[Any, Any, Any, Any]:
    registry = ToolRegistry()
    registry.register(
        ToolDescriptor(
            tool_id="DOM-TST-TOOL-100",
            name="run_tapeout",
            tool_class=ToolClass.RUN,
            domain="testing",
            version="1.0.0",
            capability_id=CAPABILITY,
            conditions_schema_version="testing/tapeout@1.0.0",
            produces=("test.wafer",),
        ),
        tool,
    )
    jobs = InMemoryJobStore()
    jobs.submit(
        Job(
            job_id=JOB,
            project_id=PROJECT,
            episode_id=EPISODE,
            capability_id=CAPABILITY,
            trace_id=TRACE,
            idempotency_key="idem:tapeout",
            submitted_at=NOW - dt.timedelta(minutes=1),
        )
    )
    ledger = InMemoryCostLedger()
    spans = InMemorySpanRepository()
    claims = InMemoryBudgetApprovalClaims()
    dispatcher = BudgetedToolDispatcher(
        tools=registry,
        capabilities=capabilities,
        spans=spans,
        ledger=ledger,
        jobs=jobs,
        claims=claims,
        now=lambda: NOW,
        critiques=critiques,
    )
    return dispatcher, ledger, spans, claims


def _policy() -> BudgetPolicy:
    return BudgetPolicy(
        policy_id="bp:m3",
        policy_version="1.0.0",
        project_id=PROJECT,
        caps=BudgetCaps(money_estimate=Decimal("100")),  # the budget would ALLOW: not the refusal
    )


def _supervisor(claims: Any) -> dict[str, Any]:
    approval = BudgetApproval(
        approval_id="apr:tapeout",
        approver_actor_id="act:pi",
        project_id=PROJECT,
        episode_id=EPISODE,
        action_ref=ACTION,
        policy_id="bp:m3",
        policy_version="1.0.0",
        approved_overrun=CostVector(money_estimate=Decimal("100")),
        granted_at=NOW - dt.timedelta(minutes=5),
        expires_at=NOW + dt.timedelta(hours=1),
    )
    claims.register(approval.approval_id, ACTION)
    return {
        "approval": approval,
        "approver": Actor(actor_id="act:pi", actor_type=ActorType.HUMAN),
        "approver_membership": ProjectMembership(
            actor_id="act:pi",
            project_id=PROJECT,
            role="PI",
            approval_scopes=(BUDGET_OVERRUN_SCOPE,),
        ),
    }


def _action(**overrides: Any) -> ToolAction:
    payload: dict[str, Any] = {
        "tool_id": "DOM-TST-TOOL-100",
        "request": TapeoutRequest(
            project_id=PROJECT, trace_id=TRACE, episode_id=EPISODE, design="d1"
        ),
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "actor_or_slot": "act:researcher",
        "action_ref": ACTION,
        "trace_id": TRACE,
        "span_id": "spn:tapeout",
        "estimate_entry_id": "cst:tapeout-est",
        "actual_entry_id": "cst:tapeout-act",
    }
    payload.update(overrides)
    return ToolAction(**payload)


def _debated():  # type: ignore[no-untyped-def]
    case = next(c for c in load_fixture()["cases"] if c["case_id"] == "hard-1")
    world = build_world(case)
    return world, world.debate.run(world.request(case))


def _nothing_happened(tool: Spy, ledger: Any, spans: Any, claims: Any) -> None:
    assert tool.entered == []
    assert ledger.entry("cst:tapeout-est") is None and ledger.entry("cst:tapeout-act") is None
    assert spans.get("spn:tapeout") is None
    assert claims.consumed_at("apr:tapeout") is None


# -- refused ---------------------------------------------------------------------------------------


def test_an_irreversible_action_without_a_critique_is_not_dispatched():
    world, _ = _debated()
    tool = Spy(fatal=True)
    dispatcher, ledger, spans, claims = _dispatcher(
        tool, capabilities=_capabilities(irreversible=True), critiques=world.debates
    )
    supervisor = _supervisor(claims)
    with pytest.raises(ToolDispatchRefused):
        dispatcher.dispatch(_action(), policy=_policy())
    _nothing_happened(tool, ledger, spans, claims)
    # And a valid human approval does not substitute for the missing critique.
    with pytest.raises(ToolDispatchRefused, match="approval"):
        dispatcher.dispatch(_action(**supervisor), policy=_policy())
    _nothing_happened(tool, ledger, spans, claims)


def test_an_estimate_that_declares_irreversibility_is_enough_to_require_the_critique():
    world, _ = _debated()
    tool = Spy(fatal=True)
    dispatcher, ledger, spans, claims = _dispatcher(
        tool,
        capabilities=_capabilities(irreversible=False, estimate_irreversible=True),
        critiques=world.debates,
    )
    with pytest.raises(ToolDispatchRefused):
        dispatcher.dispatch(_action(), policy=_policy())
    _nothing_happened(tool, ledger, spans, claims)


def test_a_critique_that_was_never_stored_or_no_store_is_refused():
    world, _ = _debated()
    tool = Spy(fatal=True)
    dispatcher, ledger, spans, claims = _dispatcher(
        tool, capabilities=_capabilities(irreversible=True), critiques=world.debates
    )
    with pytest.raises(ToolDispatchRefused, match="not durably recorded"):
        dispatcher.dispatch(_action(critique_id="crq:imagined"), policy=_policy())
    blind, *_ = _dispatcher(tool, capabilities=_capabilities(irreversible=True), critiques=None)
    with pytest.raises(ToolDispatchRefused, match="not durably recorded"):
        blind.dispatch(_action(critique_id="crq:t-critique-0001"), policy=_policy())
    _nothing_happened(tool, ledger, spans, claims)


def test_a_critique_of_another_episode_examined_nothing_here():
    _, outcome = _debated()
    tool = Spy(fatal=True)
    other = outcome.critiques[0].model_copy(update={"episode_id": "epi:elsewhere"})

    class _Other:
        def get_critique(self, critique_id: str):  # type: ignore[no-untyped-def]
            return other

    elsewhere, ledger, spans, claims = _dispatcher(
        tool, capabilities=_capabilities(irreversible=True), critiques=_Other()
    )
    with pytest.raises(ToolDispatchRefused, match="examined nothing here"):
        elsewhere.dispatch(_action(critique_id=other.critique_id), policy=_policy())
    _nothing_happened(tool, ledger, spans, claims)


def test_a_critique_settled_by_model_opinion_does_not_release_an_irreversible_action():
    """§7.6: adjudication by external evidence. A critique citing nothing is another opinion."""
    world, outcome = _debated()
    uncited = next(c for c in outcome.critiques if not c.cited_attestation_ids)
    tool = Spy(fatal=True)
    dispatcher, ledger, spans, claims = _dispatcher(
        tool, capabilities=_capabilities(irreversible=True), critiques=world.debates
    )
    with pytest.raises(ToolDispatchRefused):
        dispatcher.dispatch(_action(critique_id=uncited.critique_id), policy=_policy())
    _nothing_happened(tool, ledger, spans, claims)


# -- permitted -------------------------------------------------------------------------------------


def test_an_independent_evidence_citing_critique_releases_the_irreversible_action():
    world, outcome = _debated()
    cited = next(c for c in outcome.critiques if c.cited_attestation_ids)
    assert cited.differs_in
    tool = Spy(fatal=False)
    dispatcher, _, _, _ = _dispatcher(
        tool, capabilities=_capabilities(irreversible=True), critiques=world.debates
    )
    result = dispatcher.dispatch(_action(critique_id=cited.critique_id), policy=_policy())
    assert result.performed and len(tool.entered) == 1


def test_a_reversible_action_is_untouched_by_the_critique_rule():
    """M2's behaviour, unchanged: no critique store, no critique, dispatched."""
    tool = Spy(fatal=False)
    dispatcher, _, _, _ = _dispatcher(
        tool, capabilities=_capabilities(irreversible=False), critiques=None
    )
    assert dispatcher.dispatch(_action(), policy=_policy()).performed
