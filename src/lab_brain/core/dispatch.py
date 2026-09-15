"""The execution seam: nothing reaches the outside world except through here (OPS-003, COST-001).

WHAT THIS IS, AND WHY IT IS ONE FUNCTION.

Until P6 the budget gate and the cost ledger were correct and unreachable. `evaluate_budget` refused
everything it should refuse, `authorize_dispatch` made single use atomic and durable, the ledger was
append-only in the database -- and **nothing called any of it** (risk R-10). A gate with no caller
is a rule, not an enforcement, and the gap between the two is where every "we thought that was
checked" incident lives.

This module is that caller. It is deliberately the *only* one: a side effect that can be performed
without passing through :func:`dispatch_action` is a side effect nobody budgeted, traced or costed,
so the seam has to be narrow enough that going around it is visible in review.

THE ORDER IS THE CONTRACT.

    1. open a span                      RUNNING, under the trace, parented where it belongs
    2. ask the budget                   authorize_dispatch -- caps, approval, authority, ONCE
    3. if refused: close BLOCKED        and *return*. `perform` is never called
    4. record the ESTIMATED cost        the gate's input, and the evidence for its admission
    5. perform the side effect          the only step that touches anything external
    6. record the ACTUAL cost           what it really cost, beside what we predicted
    7. close the span                   SUCCEEDED, with both ledger entries linked

Step 3 is the whole point. §17.17 says the gate runs "before each LLM/tool call", and a gate that
runs beside the call rather than before it is accounting. `perform` is a callable this function
invokes, not a value it receives, so "we checked the budget after spending the money" is not an
ordering bug that can be introduced here -- it is unrepresentable.

WHY THE LEDGER IS NOT WRITTEN FOR A REFUSED DISPATCH. The first version of this function recorded
the estimate before asking, on the reasoning that "we refused, and here is the size of what we
refused" is how an over-tight cap gets noticed. A test found the flaw: `cost_entries` holds one
ESTIMATED row per ``action_ref``, so an attempt that was refused would consume that slot, and the
*legitimate* retry after a supervisor approves the overrun could then never record its estimate.
A governance refusal would have permanently poisoned the action it refused.

So the ledger records money and the trace records attempts, which is the right division: the
BLOCKED span carries the reason and the estimate in its metadata, so the magnitude of a refusal is
still visible to anyone reading the episode, without occupying a slot reserved for something that
actually ran.

WHAT THIS DOES *NOT* GATE, deliberately. §7.6's independent critique path and SEC-002's ACLs are
different gates with different authorities, and a budget approval explicitly releases neither
(§17.17.1). `lab_brain.core.critique_gate` already makes the §7.6 rule executable and is still
uncalled -- risk R-8 -- because SRC-002 is M3. This function is where it will attach, and wiring it
in now would be claiming an M3 requirement from an M0b slice. The extension point is named rather
than built.

BLOCKED IS NOT FAILED. A budget refusal closes the span ``BLOCKED``. UX-002 states that budget
exhaustion classifies as POLICY_BLOCK and not FAILED, and the distinction decides who gets paged: a
governance refusal needs a supervisor, a failure needs an engineer. (UX-002 is M1; this is
consistency with it, not a claim to discharge it.)
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lab_brain.core.budget import (
    BudgetApprovalClaims,
    BudgetDecision,
    BudgetRequest,
    authorize_dispatch,
)
from lab_brain.core.models.cost import CAPPED_DIMENSIONS, CostEntry, CostKind, CostVector
from lab_brain.core.models.execution_span import (
    SUBJECT_FIELD_FOR_TYPE,
    ExecutionSpan,
    SpanStatus,
    SpanType,
)
from lab_brain.core.repositories.budget import CostLedger
from lab_brain.core.repositories.observability import SpanRepository


class DispatchRefused(RuntimeError):
    """The seam was asked to dispatch something it will not dispatch at all.

    Distinct from a budget refusal, which is a normal, recorded outcome with a span and a reason.
    This is a wiring error -- an unusable estimate, a span that cannot be opened -- and it raises
    rather than returning a BLOCKED result so it cannot be mistaken for governance working.
    """


@dataclass(frozen=True)
class ActionOutcome:
    """What a performed action reports about itself.

    ``actual_cost`` is required. An action that will not say what it cost cannot be admitted to the
    ledger, and defaulting it to the estimate would make systematic under-estimation invisible --
    which is the specific thing §17.17's two-row estimate/actual design exists to expose.
    """

    actual_cost: CostVector
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchableAction:
    """One thing to dispatch, and everything the trace needs to describe it.

    ``perform`` is a zero-argument callable rather than an already-computed result, because the
    ordering guarantee in the module docstring depends on this function being the one that invokes
    it. Handing in a value would mean the side effect had already happened.
    """

    span_id: str
    trace_id: str
    span_type: SpanType
    estimate_entry_id: str
    actual_entry_id: str
    perform: Callable[[], ActionOutcome]

    parent_span_id: str | None = None
    episode_id: str | None = None
    #: The **Actor** this interval is attributed to, and a real one: `execution_spans.actor_id` is
    #: a foreign key into `actors` (§14.4 -- no governance without "who"). It is deliberately not
    #: the same value as ``BudgetRequest.actor_id``, which is `actor_or_slot` and is wider: a §7.3
    #: LLM slot incurs cost but is not an Actor. So a span for a slot's work carries the human or
    #: agent-role actor it runs under, or None -- never the slot name, which would be a dangling
    #: reference dressed up as attribution.
    actor_id: str | None = None
    #: The §17.19.1 subject reference, if this span type takes one. Validated against the type by
    #: `ExecutionSpan` itself, so a mismatch fails here rather than producing an unreassemblable
    #: trace.
    subject_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchResult:
    """The span, the budget decision, and whether the side effect actually happened.

    ``performed`` is recorded separately from the span status rather than inferred from it. A
    reader asking "did this touch the outside world" must not have to reason about which statuses
    imply that; it is the single most important fact in the record.
    """

    span: ExecutionSpan
    decision: BudgetDecision
    performed: bool
    outcome: ActionOutcome | None = None

    @property
    def blocked(self) -> bool:
        return self.span.status is SpanStatus.BLOCKED


def dispatch_action(
    action: DispatchableAction,
    budget: BudgetRequest,
    *,
    spans: SpanRepository,
    ledger: CostLedger,
    claims: BudgetApprovalClaims | None,
    now: Callable[[], dt.datetime],
) -> DispatchResult:
    """Dispatch ``action`` if and only if the budget permits, recording the trace either way.

    ``now`` is a callable, not a timestamp: a span has a start and an end and they are different
    moments, so a single injected value would record every action as instantaneous. It stays
    injected rather than read from the clock so a dispatch can be replayed in a test without
    sleeping.

    ``budget`` is passed whole rather than assembled here. The gate needs the policy, the session's
    consumed total, the approval and the approver, and every one of those is a lookup this function
    has no business performing -- keeping them as inputs is what makes the decision replayable
    from the audit record (see `lab_brain.core.budget`).
    """
    if budget.estimate is None:
        # The gate would refuse this anyway. Raising instead makes it a wiring error rather than a
        # governance outcome: an unestimated dispatch is a caller that has not been written yet,
        # not a project that has run out of money, and recording it as BLOCKED would put it in the
        # supervisor's queue.
        raise DispatchRefused(
            f"{budget.action_ref} has no cost estimate. The gate decides from an estimate taken "
            "before the call, so there is nothing to dispatch -- this is a missing estimator, not "
            "a budget refusal"
        )
    subject_field = SUBJECT_FIELD_FOR_TYPE.get(action.span_type)
    if action.subject_id is not None and subject_field is None:
        raise DispatchRefused(
            f"a {action.span_type.value} span takes no subject reference, but subject_id "
            f"{action.subject_id!r} was supplied"
        )

    # Placed explicitly rather than splatted into kwargs: the three fields are mutually exclusive
    # and `ExecutionSpan` enforces which one this span type may carry, so naming them keeps that
    # agreement checkable by the type checker instead of only at runtime.
    subject = action.subject_id if subject_field is not None else None
    started = now()
    span = spans.open(
        ExecutionSpan(
            span_id=action.span_id,
            trace_id=action.trace_id,
            parent_span_id=action.parent_span_id,
            span_type=action.span_type,
            episode_id=action.episode_id,
            actor_id=action.actor_id,
            model_call_id=subject if subject_field == "model_call_id" else None,
            job_id=subject if subject_field == "job_id" else None,
            retrieval_id=subject if subject_field == "retrieval_id" else None,
            start_time=started,
            status=SpanStatus.RUNNING,
            metadata=dict(action.metadata),
        )
    )

    decision = authorize_dispatch(budget, claims)
    if not decision.budget_permits:
        # No ledger row. See the module docstring: the estimate slot is reserved for the attempt
        # that ran, or a refusal would block the retry that a supervisor's approval exists to
        # enable. The refusal's magnitude lives on the span instead, where it is still readable.
        return DispatchResult(
            span=spans.close(
                span.span_id,
                status=SpanStatus.BLOCKED,
                end_time=now(),
                metadata={
                    **span.metadata,
                    "budget_reason": decision.reason,
                    "budget_exceeded": list(decision.exceeded_dimensions),
                    # Stringified because a cap can be a Decimal and the column is JSONB: a float
                    # here would round money differently on two machines, which §9.4 forbids.
                    "budget_estimate": {
                        dimension: str(getattr(budget.estimate, dimension))
                        for dimension in CAPPED_DIMENSIONS
                    },
                },
            ),
            decision=decision,
            performed=False,
        )

    # The gate's input, recorded before the side effect and kept afterwards: §17.17 keeps the
    # estimate as its own row precisely so systematic under-estimation stays visible next to the
    # actual instead of being overwritten by it.
    estimate_entry = ledger.record(
        CostEntry(
            cost_entry_id=action.estimate_entry_id,
            project_id=budget.project_id,
            episode_id=budget.episode_id,
            actor_or_slot=budget.actor_id,
            action_ref=budget.action_ref,
            cost_kind=CostKind.ESTIMATED,
            cost=budget.estimate,
            recorded_at=started,
        )
    )

    try:
        outcome = action.perform()
    except Exception:
        # No ACTUAL entry. An action that raised did not report a cost, and substituting the
        # estimate would record a number nobody measured -- in the one place whose purpose is to
        # make estimates checkable against reality. The span says FAILED and the estimate stands
        # alone, which is the truth: we predicted this, we tried, we do not know what it cost.
        # A richer failure channel is `Job.structured_error` (§17.16), which arrives with OPS-001.
        spans.close(
            span.span_id,
            status=SpanStatus.FAILED,
            end_time=now(),
            cost_entry_ids=(estimate_entry.cost_entry_id,),
            metadata=span.metadata,
        )
        raise

    actual_entry = ledger.record(
        CostEntry(
            cost_entry_id=action.actual_entry_id,
            project_id=budget.project_id,
            episode_id=budget.episode_id,
            actor_or_slot=budget.actor_id,
            action_ref=budget.action_ref,
            cost_kind=CostKind.ACTUAL,
            cost=outcome.actual_cost,
            approval_id=decision.approval_id,
            recorded_at=now(),
        )
    )
    return DispatchResult(
        span=spans.close(
            span.span_id,
            status=SpanStatus.SUCCEEDED,
            end_time=now(),
            cost_entry_ids=(estimate_entry.cost_entry_id, actual_entry.cost_entry_id),
            metadata={**span.metadata, **outcome.metadata},
        ),
        decision=decision,
        performed=True,
        outcome=outcome,
    )


__all__ = [
    "ActionOutcome",
    "DispatchRefused",
    "DispatchResult",
    "DispatchableAction",
    "dispatch_action",
]
