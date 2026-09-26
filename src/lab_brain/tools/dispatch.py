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

    bind the execution scope    the action the gate will price and the request the registry will
                                execute must name one project, one trace and one Episode. See
                                `scope.py`.
    resolve the descriptor      SIM-003. An unregistered tool is refused here, not later.
    bind the durable Job        a request that executes a Job names it (`JobBinding`); the Job is
                                resolved and must be the same execution -- including the same
                                Episode -- BEFORE the gate, so a mismatch spends no approval and
                                writes no ledger row. A `run_*` request that names none is refused.
    resolve the estimate        §9.5 for `run_*` (its Capability), the descriptor's declared
                                `cost_contract` otherwise. No estimate -> no dispatch.
    critique an irreversible    M3 / SRC-002: an irreversible Capability -- or an estimate that says
      action                    irreversible -- needs a completed independent critique, checked by
                                M0b's `core.critique_gate`, BEFORE the gate; a human or budget
                                approval does not substitute. The adjudicator is read from the
                                DURABLE attestations the critique cites (`core.adjudication`):
                                INFERRED or DISPUTED evidence does not settle it, and a citation
                                that does not resolve refuses the action. Reversible actions are
                                untouched.
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
from typing import Any, Protocol

from lab_brain.core.adjudication import (
    AdjudicationBasisRefused,
    AttestationLookup,
    resolve_adjudication_basis,
)
from lab_brain.core.budget import (
    BudgetApproval,
    BudgetApprovalClaims,
    BudgetDecision,
    BudgetPolicy,
    BudgetRequest,
)
from lab_brain.core.critique_gate import (
    CritiqueAxis,
    CritiqueRecord,
    DispatchRequest,
    HumanApproval,
    Reversibility,
    evaluate_dispatch,
)
from lab_brain.core.dispatch import ActionOutcome, DispatchableAction, dispatch_action
from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.debate import CritiqueReport
from lab_brain.core.models.execution_span import ExecutionSpan, SpanType
from lab_brain.core.repositories.budget import CostLedger
from lab_brain.core.repositories.jobs import JobStore
from lab_brain.core.repositories.observability import SpanRepository
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.registry import ToolRegistry
from lab_brain.tools.scope import ExecutionScope, require_same_scope
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

    #: M3 / SRC-002. The independent CritiqueReport an IRREVERSIBLE action was examined by. Ignored
    #: for a reversible one. Named rather than embedded so the dispatcher reloads the durable record
    #: and a caller cannot hand it a critique that was never stored.
    critique_id: str | None = None


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

    ``jobs`` IS REQUIRED, not optional, and is only ever read. It is how the dispatcher learns which
    Episode the execution belongs to before it asks the gate about the Episode that is paying: the
    two are different rows (`ToolAction` and `Job`), and a dispatcher that could be built without
    the second could only ever compare the first with itself.
    """

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        capabilities: CapabilityRegistry,
        spans: SpanRepository,
        ledger: CostLedger,
        jobs: JobStore,
        claims: BudgetApprovalClaims | None,
        now: Callable[[], dt.datetime],
        critiques: CritiqueLookup | None = None,
        attestations: AttestationLookup | None = None,
    ) -> None:
        #: M3 / SRC-002. Optional because only an IRREVERSIBLE action consults them, and
        #: fail-closed: an irreversible action dispatched through a dispatcher with no critique
        #: store -- or with no attestation store to read the critique's evidence from -- is refused.
        self._critiques = critiques
        self._attestations = attestations
        self._tools = tools
        self._capabilities = capabilities
        self._spans = spans
        self._ledger = ledger
        self._jobs = jobs
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
        # THE EXECUTION ENVELOPE, BEFORE EVERYTHING -- before the descriptor is resolved, before an
        # estimate exists, before a span is opened, before `perform` is built.
        #
        # This dispatcher budgets against `ToolAction` and the registry executes against
        # `ToolRequest`. Two fields that are never compared are two fields that can differ, so a
        # request whose `project_id` was B could be admitted by project A's caps and then run
        # inside B. The gate is not wrong in that story; it is answering a question about a
        # different project than the one that executes.
        #
        # IT CANNOT MOVE INSIDE `perform`. `core.dispatch.dispatch_action` writes the ESTIMATED
        # ledger row and consumes the approval claim before it calls `perform`, and wraps the call
        # in `except Exception` (`core/dispatch.py:256`) -- so a check made there would fire after
        # the money was recorded and the approval spent, and would close the span FAILED, which is
        # the "the solver crashed" channel rather than "this envelope is invalid".
        #
        # THE EPISODE IS PART OF THE ENVELOPE. `BudgetRequest.episode_id`, both ledger rows and the
        # approval's scope are all `action.episode_id`; the implementation runs with the request's.
        # Compared here for the same reason as the project: the gate answering a question about
        # Episode E1 is not an answer about a request made in E2.
        require_same_scope(
            ExecutionScope(
                layer="ToolAction",
                project_id=action.project_id,
                trace_id=action.trace_id,
                episode_id=action.episode_id,
            ),
            ExecutionScope(
                layer="ToolRequest",
                project_id=action.request.project_id,
                trace_id=action.request.trace_id,
                episode_id=action.request.episode_id,
            ),
            detail=(
                f"tool {action.tool_id} would have been gated against one scope and executed in "
                "another. COST-001 gates the action; SIM-003 invokes the request; a mismatch makes "
                "the gate's answer true of a call nobody is about to make. Nothing is dispatched: "
                "no span, no ledger row, no approval consumed"
            ),
        )

        # SIM-003's half, next: an unregistered tool is refused before a span is opened, so a
        # typo cannot produce a BLOCKED span that reads as a governance refusal.
        descriptor = self._tools.descriptor(action.tool_id)

        # The durable Job, before the gate. See `_bind_to_durable_job`.
        self._bind_to_durable_job(action, descriptor)

        estimate = self.estimate_for(action.tool_id, action.estimate_params)

        # §7.6's second trigger, before the gate. See `_require_independent_critique`.
        self._require_independent_critique(action, descriptor, estimate)

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

    def _require_independent_critique(
        self, action: ToolAction, descriptor: ToolDescriptor, estimate: CostVector
    ) -> None:
        """SRC-002 / §7.6: an irreversible action does not dispatch without independent critique.

        THE EXTENSION POINT M0b NAMED. `core.dispatch` says the critique gate "is where it will
        attach" and left it uncalled (risk R-8) because SRC-002 is M3. `dispatch_action` is
        hard-locked, and this dispatcher is the one production path to a tool, so it attaches here,
        before the gate -- no span, no ledger row, no approval consumed on a refusal.

        IRREVERSIBILITY IS DECLARED, NEVER INFERRED: the Capability's `irreversible` flag, or the
        estimate's (§9.4). Either is enough; a reversible action passes through untouched, which is
        why no M2 behaviour changes.

        THE DECISION IS M0b's `evaluate_dispatch`, not a second rule. This builds its
        `DispatchRequest` from the durable CritiqueReport: the axes are the ones `005e` verified,
        and the adjudicator is PROVEN from the record, not inferred from the critique's having
        cited something. Every cited attestation is re-read from the attestation store in the
        action's project (`core.adjudication`): a citation that resolves nowhere refuses the
        action outright, INFERRED and DISPUTED ones are set aside, and only what remains can make
        the adjudicator EXTERNAL_EVIDENCE -- or VERIFICATION_RESULT, when it is a Run's witness.
        Nothing admissible left is MODEL_OPINION, which `evaluate_dispatch` refuses. A budget
        approval rides along as the `human_approval` so the refusal can say, in words, that it did
        not substitute.
        """
        irreversible = estimate.irreversible
        if descriptor.tool_class is ToolClass.RUN and descriptor.capability_id is not None:
            capability = self._capabilities.resolve(descriptor.capability_id)
            irreversible = irreversible or capability.irreversible
        if not irreversible:
            return
        record: CritiqueRecord | None = None
        if action.critique_id is not None:
            critique = (
                self._critiques.get_critique(action.critique_id)
                if self._critiques is not None
                else None
            )
            if critique is None:
                raise ToolDispatchRefused(
                    f"irreversible action {action.action_ref} names critique {action.critique_id}, "
                    "which is not durably recorded (or no critique store is wired). SRC-002: the "
                    "critique must be completed, and a completed critique is a stored one"
                )
            if (critique.project_id, critique.episode_id) != (
                action.project_id,
                action.episode_id,
            ):
                raise ToolDispatchRefused(
                    f"critique {critique.critique_id} belongs to {critique.project_id}/"
                    f"{critique.episode_id}, not to the action's {action.project_id}/"
                    f"{action.episode_id}; a critique of another decision examined nothing here"
                )
            if self._attestations is None:
                raise ToolDispatchRefused(
                    f"irreversible action {action.action_ref}: critique {critique.critique_id}'s "
                    "evidence cannot be read -- no attestation store is wired -- so its "
                    "adjudication by external evidence cannot be shown (§7.6). Refused rather "
                    "than assumed"
                )
            try:
                basis = resolve_adjudication_basis(
                    critique.cited_attestation_ids,
                    project_id=action.project_id,
                    attestations=self._attestations,
                )
            except AdjudicationBasisRefused as refused:
                raise ToolDispatchRefused(
                    f"irreversible action {action.action_ref}: critique {critique.critique_id} "
                    f"is refused as its adjudication basis. {refused}"
                ) from refused
            record = CritiqueRecord(
                critique_id=critique.critique_id,
                differs_in=frozenset(CritiqueAxis(axis) for axis in critique.differs_in),
                adjudicated_by=basis.adjudicator,
            )
        approval = action.approval
        decision = evaluate_dispatch(
            DispatchRequest(
                action_id=action.action_ref,
                reversibility=Reversibility.IRREVERSIBLE,
                causes_belief_revision=False,
                critique=record,
                human_approval=(
                    HumanApproval(
                        actor_id=approval.approver_actor_id,
                        approved_at=approval.granted_at.isoformat(),
                    )
                    if approval is not None
                    else None
                ),
            )
        )
        if not decision.allowed:
            raise ToolDispatchRefused(decision.reason)

    def _bind_to_durable_job(self, action: ToolAction, descriptor: ToolDescriptor) -> None:
        """The Episode that pays must be the Episode whose Job executes, decided BEFORE the gate.

        THE DEFECT THIS CLOSES. COST-001 prices, attributes and releases by `ToolAction.episode_id`;
        the execution belongs to `Job.episode_id`. With project, trace and capability all bound,
        those two could still differ -- two Episodes of one project can share a trace -- and the
        only comparison that could see it was `run_simulation`'s step 0. That runs inside
        `perform`, which `dispatch_action` calls only AFTER it has consumed the approval claim and
        written the ESTIMATED row. So the refusal came after the approval was spent and after the
        wrong Episode was charged: correct about the execution and too late about the money.

        So the request names the Job it will execute (`ToolRequest.job_binding`), and the Job is
        resolved and compared here, on all four dimensions, while nothing has happened: no span,
        no ledger row, no claim, no Job mutation, no seat, no backend. `run_simulation` still makes
        the same comparison at the moment of execution; see `scope.py` for why both exist.

        A `run_*` REQUEST THAT BINDS NO JOB IS REFUSED. §10.2.1 makes `run_*` backend-bound and a
        backend execution here is a Job (§17.16). A run request that did not say which Job it runs
        would skip this check without anyone noticing, and the Episode the gate priced would again
        be unrelated to the Episode that executed -- so its absence is a wiring error, not a pass.
        """
        binding = action.request.job_binding()
        if binding is None:
            if descriptor.tool_class is ToolClass.RUN:
                raise ToolDispatchRefused(
                    f"run tool {descriptor.tool_id} ({descriptor.name}) was dispatched with a "
                    f"{type(action.request).__name__} that binds no durable Job. A backend "
                    "execution is a Job (§17.16), and the Episode COST-001 prices has to be "
                    "checked against the Episode that Job belongs to before the gate -- a run "
                    "request that does not say which Job it runs cannot be"
                )
            return

        job = self._jobs.get(binding.job_id)
        if job is None:
            raise ToolDispatchRefused(
                f"tool {descriptor.tool_id} would execute job {binding.job_id}, which does not "
                "resolve. §17.16 makes the Job the durable record of what was admitted; there is "
                "no Episode to check the budget against and nothing to attribute a Run to"
            )
        require_same_scope(
            binding.scope,
            ExecutionScope(
                layer="Job",
                project_id=job.project_id,
                trace_id=job.trace_id,
                episode_id=job.episode_id,
                capability_id=job.capability_id,
            ),
            detail=(
                f"tool {descriptor.tool_id} was to be budgeted in episode {action.episode_id!r} "
                f"and would have executed job {job.job_id}, which belongs to a different scope. "
                "COST-001's caps, ledger rows and approval are the ToolAction's; the execution is "
                "the Job's. Refused before the gate: no span, no ledger row, no approval "
                "consumed, the Job untouched, no seat taken, no backend entered"
            ),
        )

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


class CritiqueLookup(Protocol):
    """What the dispatcher needs from the debate store: a durable CritiqueReport by id."""

    def get_critique(self, critique_id: str) -> CritiqueReport | None: ...


__all__ = [
    "BudgetedToolDispatcher",
    "CritiqueLookup",
    "ToolAction",
    "ToolDispatchRefused",
    "ToolDispatchResult",
]
