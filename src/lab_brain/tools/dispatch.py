"""The one supported production tool call: typed, budgeted, traced (COST-001 + SIM-003, §17.17).

    COST-001  Before each LLM/tool call, BudgetGate MUST check project/episode caps.
    SIM-003   Tool invocation MUST occur through a typed ToolRegistry.

THE DEFECT THIS MODULE CLOSES. Both requirements were satisfied, separately, by two seams that did
not meet. `ToolRegistry.invoke` gave SIM-003 a typed path with no budget; `dispatch_action` gave
COST-001 a budgeted path with no tool registry -- and `run_simulation`'s own docstring says budget
"belongs to `dispatch_action`", which was true and was nobody's job. So the shipped M2 chain,
`invoke -> ChargeAcSweepTool -> run_simulation -> backend.execute`, reached a simulator without
passing a gate. Satisfying one requirement through a path that bypasses the other satisfies
neither.

    resolve the descriptor      SIM-003. An unregistered tool is refused here, not later.
    resolve the estimate        §9.5 for `run_*` (its Capability), the descriptor's declared
                                `cost_contract` otherwise. No estimate -> no dispatch.
    build the BudgetRequest     caps, session consumption, approval -- all passed in, so the
                                decision stays replayable from the audit record.
    dispatch_action             opens the span, asks the gate, and calls `perform` ONLY on ALLOW.
      -> ToolRegistry.invoke    the typed call, inside `perform`, so it cannot happen first.
    actual cost                 measured, never copied from the estimate.
    close the span              SUCCEEDED with both ledger rows linked.

`perform` IS A CLOSURE THIS MODULE HANDS TO `dispatch_action`, WHICH IS THE WHOLE ORDERING
ARGUMENT. `dispatch_action` takes a callable rather than a value precisely so "we checked the
budget after spending the money" is unrepresentable; this module inherits that guarantee instead of
re-deriving it, and the tool call physically cannot occur before the gate returns ALLOW.

NOTHING IN `core.dispatch` CHANGED. §17.17's seam is hard-locked M0b code and is correct; what was
missing was a caller that combined it with the registry. This is that caller.

THE RAW REGISTRY IS STILL THERE, and is still the right thing for a unit test that is asking a
question about type checking rather than about governance. What is no longer true is that a
production orchestration surface exposes it as an ordinary side-effect path:
`tests/unit/test_budgeted_tool_dispatch.py::test_no_shipped_orchestration_surface_invokes_the_registry_directly`
parses the shipped package and fails if one does.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from lab_brain.core.budget import (
    BudgetApproval,
    BudgetApprovalClaims,
    BudgetDecision,
    BudgetPolicy,
    BudgetRequest,
)
from lab_brain.core.dispatch import ActionOutcome, DispatchableAction, dispatch_action
from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.execution_span import ExecutionSpan, SpanType
from lab_brain.core.repositories.budget import CostLedger
from lab_brain.core.repositories.observability import SpanRepository
from lab_brain.tools.contracts import ToolClass, ToolRequest, ToolResult
from lab_brain.tools.registry import ToolRegistry
from lab_brain.verification.capability_registry import (
    CapabilityNotRegistered,
    CapabilityRegistry,
)


class ToolDispatchRefused(RuntimeError):
    """The dispatch could not be attempted at all -- a wiring error, not a governance outcome.

    Distinct from a budget refusal, which is a normal, recorded result with a BLOCKED span and a
    reason. `DispatchRefused` in `core.dispatch` draws the same line for the same reason: a caller
    that cannot tell "the project ran out of money" from "this tool has no estimator" will route
    the second to a supervisor and wait.
    """


@dataclass(frozen=True)
class ToolAction:
    """One tool invocation, and everything the gate and the trace need to describe it.

    ``request`` is the typed payload the registry will check against the tool's declared
    `request_model`. It is carried rather than constructed here: the dispatcher does not know what
    any particular tool takes, which is the point of the registry.
    """

    tool_id: str
    request: ToolRequest
    project_id: str
    episode_id: str
    #: `actor_or_slot` for the ledger -- §17.17 makes it wider than `actor_id` because a §7.3 model
    #: slot incurs cost and is not an Actor.
    actor_or_slot: str
    action_ref: str
    trace_id: str

    span_id: str
    estimate_entry_id: str
    actual_entry_id: str
    parent_span_id: str | None = None
    #: The real Actor the span is attributed to (`execution_spans.actor_id` is a foreign key into
    #: `actors`). Deliberately not the same value as `actor_or_slot`.
    actor_id: str | None = None

    #: Passed to the estimator. §9.5's `estimate_cost(params) -> CostVector`.
    estimate_params: Mapping[str, Any] = field(default_factory=dict)

    approval: BudgetApproval | None = None
    approver: Actor | None = None
    approver_membership: ProjectMembership | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolDispatchResult:
    """What happened, with the tool's own result present only when it actually ran.

    ``result is None`` exactly when ``performed`` is False, which is the fact a caller most needs
    and must not have to infer from the span status.
    """

    span: ExecutionSpan
    decision: BudgetDecision
    performed: bool
    estimate: CostVector
    result: ToolResult | None = None

    @property
    def blocked(self) -> bool:
        return not self.performed


class BudgetedToolDispatcher:
    """Typed registry resolution, budget gate, then -- and only then -- the tool.

    Holds no clock of its own beyond the injected ``now``, and no connection: every store is passed
    in, so the same object runs against in-memory repositories and PostgreSQL.
    """

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        capabilities: CapabilityRegistry,
        spans: SpanRepository,
        ledger: CostLedger,
        claims: BudgetApprovalClaims | None,
        now: Callable[[], dt.datetime],
    ) -> None:
        self._tools = tools
        self._capabilities = capabilities
        self._spans = spans
        self._ledger = ledger
        self._claims = claims
        self._now = now

    # -- the estimate -------------------------------------------------------

    def estimate_for(self, tool_id: str, params: Mapping[str, Any]) -> CostVector:
        """§9.5's estimate for this tool, from the one source its verb class makes authoritative.

        `run_*` prices through its Capability, because §9.5 says the planner reads the descriptor
        and the descriptor is what carries `estimate_cost_contract`. Everything else prices through
        the `cost_contract` its own `ToolDescriptor` declares -- which `ToolDescriptor` requires,
        so there is no third case where a tool simply has no price.

        Raises rather than defaulting to zero. A tool nobody can price is a wiring error, and a
        zero default would make it indistinguishable from a tool that genuinely costs nothing --
        which is exactly the distinction COST-001's "never silently continue" is about.
        """
        descriptor = self._tools.descriptor(tool_id)
        if descriptor.tool_class is ToolClass.RUN:
            assert descriptor.capability_id is not None  # ToolDescriptor requires it
            try:
                return self._capabilities.estimate(descriptor.capability_id, params)
            except CapabilityNotRegistered as missing:
                raise ToolDispatchRefused(
                    f"tool {tool_id} is bound to capability {descriptor.capability_id}, which has "
                    f"no registered descriptor: {missing}. §9.5 forbids planning an undescribed "
                    "backend and COST-001 forbids calling an unpriced one; this is both"
                ) from missing

        assert descriptor.cost_contract is not None  # ToolDescriptor requires it
        estimator = self._capabilities.estimator(descriptor.cost_contract)
        if estimator is None:
            raise ToolDispatchRefused(
                f"tool {tool_id} declares cost contract {descriptor.cost_contract!r}, which is not "
                "registered. A local tool may legitimately cost nothing -- a zero CostVector says "
                "so -- but 'cheap' is not 'ungoverned', and an unpriceable call cannot pass a gate "
                "that decides from an estimate (COST-001, §17.17)"
            )
        return estimator(params)

    # -- the one supported call ---------------------------------------------

    def dispatch(
        self,
        action: ToolAction,
        *,
        policy: BudgetPolicy | None,
        consumed: CostVector | None = None,
    ) -> ToolDispatchResult:
        """Gate, then call. The tool runs only if the budget said ALLOW.

        ``policy`` may be `None` and the gate then refuses: `evaluate_budget` treats an absent
        policy as a refusal rather than as "no limits", which is the fail-closed direction. It is a
        parameter rather than a lookup so the decision can be replayed from the audit record
        against the caps that were in force, not against today's.
        """
        # SIM-003's half, first: an unregistered tool is refused before a span is opened, so a
        # typo cannot produce a BLOCKED span that reads as a governance refusal.
        descriptor = self._tools.descriptor(action.tool_id)
        estimate = self.estimate_for(action.tool_id, action.estimate_params)

        # Captured by the closure below. `dispatch_action` returns its own result and knows nothing
        # about tools, so this is how the typed result comes back out.
        captured: dict[str, ToolResult] = {}
        started = self._now()

        def perform() -> ActionOutcome:
            # THE ONLY PLACE A TOOL IS CALLED IN PRODUCTION. `dispatch_action` invokes this after
            # the gate has returned ALLOW and after the ESTIMATED row is recorded; it is never
            # reached on a refusal.
            result = self._tools.invoke(action.tool_id, action.request)
            captured["result"] = result
            return ActionOutcome(
                actual_cost=self._actual_cost(result, started),
                metadata={
                    "tool_id": descriptor.tool_id,
                    "tool_name": descriptor.name,
                    "tool_version": descriptor.version,
                    "tool_class": descriptor.tool_class.value,
                    "cost_reported_by_tool": result.actual_cost is not None,
                },
            )

        outcome = dispatch_action(
            DispatchableAction(
                span_id=action.span_id,
                trace_id=action.trace_id,
                # TOOL_CALL takes no subject reference (§17.19.1), which is why none is supplied:
                # the Job/Run a `run_*` tool produces gets its own JOB/RUN spans.
                span_type=SpanType.TOOL_CALL,
                estimate_entry_id=action.estimate_entry_id,
                actual_entry_id=action.actual_entry_id,
                perform=perform,
                parent_span_id=action.parent_span_id,
                episode_id=action.episode_id,
                actor_id=action.actor_id,
                metadata={
                    **action.metadata,
                    "tool_id": descriptor.tool_id,
                    "tool_name": descriptor.name,
                },
            ),
            BudgetRequest(
                action_ref=action.action_ref,
                project_id=action.project_id,
                episode_id=action.episode_id,
                actor_id=action.actor_or_slot,
                estimate=estimate,
                consumed=consumed or CostVector(),
                policy=policy,
                now=self._now(),
                approval=action.approval,
                approver=action.approver,
                approver_membership=action.approver_membership,
            ),
            spans=self._spans,
            ledger=self._ledger,
            claims=self._claims,
            now=self._now,
        )

        return ToolDispatchResult(
            span=outcome.span,
            decision=outcome.decision,
            performed=outcome.performed,
            estimate=estimate,
            result=captured.get("result"),
        )

    # -- internals ----------------------------------------------------------

    def _actual_cost(self, result: ToolResult, started: dt.datetime) -> CostVector:
        """Measured, never copied from the estimate.

        §17.17 keeps the estimate and the actual as separate rows so that systematic
        under-estimation stays visible; substituting the estimate would destroy the only evidence
        of it. So wall-clock is measured here -- this function owns the interval -- and every other
        dimension comes from what the tool itself reported, or is zero.

        A dimension recorded as zero because nobody measured it is NOT a claim that it cost
        nothing, and the span records `cost_reported_by_tool` so a reader can tell the two apart.
        """
        elapsed = max(0, int((self._now() - started).total_seconds()))
        reported = result.actual_cost
        if reported is None:
            return CostVector(wall_clock_s=elapsed)
        # The tool's own wall-clock wins when it measured one -- a backend that timed its solver
        # knows better than this wrapper, which also counted the registry's type check.
        return (
            reported
            if reported.wall_clock_s
            else reported.model_copy(update={"wall_clock_s": elapsed})
        )


__all__ = [
    "BudgetedToolDispatcher",
    "ToolAction",
    "ToolDispatchRefused",
    "ToolDispatchResult",
]
