"""COST-001 for scientific model calls: every role's inference passes the budget gate first (M3).

    COST-001  Before each LLM/tool call, BudgetGate MUST check project/episode caps.

THE SEAM M2's FIRST REVIEW FOUND FOR TOOLS, CLOSED FOR MODELS BEFORE IT OPENS. M2's repair A was
that `ToolRegistry.invoke` reached a simulator without passing a gate, and the repair was a
composition: `BudgetedToolDispatcher` hands hard-locked `dispatch_action` a `perform` closure, so
the call cannot happen before ALLOW. M3 is the first milestone that makes many scientific model
calls per decision -- a debate is Stage A's positions, the Critic's rounds, the query rewrites --
and each one is an "LLM call" in COST-001's sentence. This module is the same composition for them:

    bind the scope        the call's project/episode/trace are the bundle's and the action's
    estimate              the declared cost contract for the slot, on the rendered prompt's tokens
    dispatch_action       opens an LLM_CALL span, asks the gate, calls `perform` ONLY on ALLOW
      -> infer/critique   `ScientificInferenceService`: authorized, durable, reloaded
    actual cost           tokens and wall-clock MEASURED from the call, never copied from the
                          estimate

`perform` IS A CLOSURE, SO THE MODEL CANNOT BE CALLED BEFORE THE GATE, and the span's subject is the
inference id minted before dispatch, so the LLM_CALL span and the `inference_provenance` row name
the same call (OPS-003).

A REFUSED CALL RAISES `InferenceBudgetBlocked` CARRYING THE BLOCKED SPAN. A role cannot continue
without its output, and returning `None` would invite a caller to proceed on a missing position. The
debate turns it into a recorded stop reason; nothing is retried behind the gate's back.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from lab_brain.cognition.inference import DurableInference, ScientificInferenceService
from lab_brain.core.budget import BudgetApprovalClaims, BudgetDecision, BudgetPolicy, BudgetRequest
from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.dispatch import ActionOutcome, DispatchableAction, dispatch_action
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.execution_span import ExecutionSpan, SpanType
from lab_brain.core.models.inference import InferenceProvenance, LogicalSlot
from lab_brain.core.repositories.budget import CostLedger
from lab_brain.core.repositories.observability import SpanRepository
from lab_brain.tools.scope import ExecutionScope, require_same_scope
from lab_brain.verification.capability_registry import CapabilityRegistry


def token_count(text: str) -> int:
    """Whitespace tokens. Declared, deterministic, and named in every debate record's metrics.

    Not a provider's tokenizer, and it does not pretend to be: a model-specific count would make
    the ledger depend on which provider answered, and M3 runs against deterministic mocks. What it
    must be is the SAME count for the estimate and the actual, so their difference is meaningful.
    """
    return len(text.split())


#: The cost contract every slot is priced by unless the composition registers another.
LLM_COST_CONTRACT_PREFIX = "cost:llm."


def cost_contract_for(slot: LogicalSlot) -> str:
    return f"{LLM_COST_CONTRACT_PREFIX}{slot.value.lower()}@1.0.0"


class InferenceBudgetBlocked(RuntimeError):
    """The gate refused the call. The model was not reached; the BLOCKED span is the record."""

    def __init__(self, span: ExecutionSpan, decision: BudgetDecision) -> None:
        super().__init__(
            f"model call {span.model_call_id} was refused by the budget gate: {decision.reason}"
        )
        self.span = span
        self.decision = decision


@dataclass(frozen=True)
class InferenceCall:
    """One scientific model call, and everything the gate and the trace need to describe it."""

    slot: LogicalSlot
    role: str
    prompt_id: str
    prompt_text: str
    bundle: EvidenceBundle
    context: Mapping[str, object]
    project_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    action_ref: str
    span_id: str
    estimate_entry_id: str
    actual_entry_id: str
    inference_id: str
    parent_span_id: str | None = None
    escalate: frozenset[SensitivityLabel] = frozenset()
    #: Set for §7.6's critique path: the inference being critiqued.
    critique_of: InferenceProvenance | None = None


@dataclass(frozen=True)
class BudgetedInference:
    inference: DurableInference
    span: ExecutionSpan
    decision: BudgetDecision
    estimate: CostVector
    actual: CostVector


class BudgetedInferenceDispatcher:
    """Scope binding, estimate, gate, then -- and only then -- the durable inference."""

    def __init__(
        self,
        *,
        service: ScientificInferenceService,
        estimators: CapabilityRegistry,
        spans: SpanRepository,
        ledger: CostLedger,
        claims: BudgetApprovalClaims | None,
        now: Callable[[], dt.datetime],
    ) -> None:
        self._service = service
        self._estimators = estimators
        self._spans = spans
        self._ledger = ledger
        self._claims = claims
        self._now = now

    def estimate(self, call: InferenceCall) -> CostVector:
        """The slot's declared contract, priced on the prompt the model will actually receive."""
        contract = cost_contract_for(call.slot)
        estimator = self._estimators.estimator(contract)
        if estimator is None:
            raise ValueError(
                f"no estimator is registered for {contract}; COST-001 gates each LLM call on an "
                "estimate, and a call nobody can price cannot pass a gate that decides from one"
            )
        return estimator({"prompt_tokens": _prompt_tokens(call)})

    def infer(
        self,
        call: InferenceCall,
        *,
        policy: BudgetPolicy | None,
        consumed: CostVector | None = None,
    ) -> BudgetedInference:
        # THE ENVELOPE FIRST, as M2's repair E established for tools: the bundle is what will be
        # classified and sent, and it must be this project's; the call is budgeted in the episode it
        # names and traced under the trace it names.
        require_same_scope(
            ExecutionScope(
                layer="InferenceCall",
                project_id=call.project_id,
                trace_id=call.trace_id,
                episode_id=call.episode_id,
            ),
            ExecutionScope(
                layer="EvidenceBundle",
                project_id=call.bundle.project_id,
                trace_id=call.trace_id,
                episode_id=call.episode_id,
            ),
            detail=(
                f"model call {call.inference_id} would have been gated in {call.project_id} and "
                f"sent evidence from {call.bundle.project_id}"
            ),
        )
        estimate = self.estimate(call)
        started = self._now()
        captured: dict[str, DurableInference] = {}

        def perform() -> ActionOutcome:
            # THE ONLY PLACE A ROLE'S MODEL IS CALLED. Reached only after ALLOW.
            if call.critique_of is not None:
                result = self._service.critique(
                    original=call.critique_of,
                    prompt_id=call.prompt_id,
                    bundle=call.bundle,
                    trace_id=call.trace_id,
                    project_id=call.project_id,
                    actor_id=call.actor_id,
                    inference_id=call.inference_id,
                    slot=call.slot,
                    escalate=call.escalate,
                    now=started,
                    context=call.context,
                )
            else:
                result = self._service.infer(
                    slot=call.slot,
                    role=call.role,
                    prompt_id=call.prompt_id,
                    bundle=call.bundle,
                    trace_id=call.trace_id,
                    project_id=call.project_id,
                    actor_id=call.actor_id,
                    inference_id=call.inference_id,
                    escalate=call.escalate,
                    now=started,
                    context=call.context,
                )
            captured["inference"] = result
            elapsed = max(0, int((self._now() - started).total_seconds()))
            return ActionOutcome(
                actual_cost=CostVector(
                    token_count=_prompt_tokens(call) + token_count(result.text),
                    wall_clock_s=elapsed,
                ),
                metadata={"role": call.role, "slot": call.slot.value, "prompt_id": call.prompt_id},
            )

        outcome = dispatch_action(
            DispatchableAction(
                span_id=call.span_id,
                trace_id=call.trace_id,
                span_type=SpanType.LLM_CALL,
                subject_id=call.inference_id,
                estimate_entry_id=call.estimate_entry_id,
                actual_entry_id=call.actual_entry_id,
                perform=perform,
                parent_span_id=call.parent_span_id,
                episode_id=call.episode_id,
                actor_id=call.actor_id,
                metadata={"role": call.role, "slot": call.slot.value},
            ),
            BudgetRequest(
                action_ref=call.action_ref,
                project_id=call.project_id,
                episode_id=call.episode_id,
                actor_id=call.actor_id,
                estimate=estimate,
                consumed=consumed or CostVector(),
                policy=policy,
                now=self._now(),
            ),
            spans=self._spans,
            ledger=self._ledger,
            claims=self._claims,
            now=self._now,
        )
        if not outcome.performed:
            raise InferenceBudgetBlocked(outcome.span, outcome.decision)
        assert outcome.outcome is not None
        return BudgetedInference(
            inference=captured["inference"],
            span=outcome.span,
            decision=outcome.decision,
            estimate=estimate,
            actual=outcome.outcome.actual_cost,
        )


def _prompt_tokens(call: InferenceCall) -> int:
    return token_count(call.prompt_text) + token_count(canonicalize(dict(call.context)))


__all__ = [
    "LLM_COST_CONTRACT_PREFIX",
    "BudgetedInference",
    "BudgetedInferenceDispatcher",
    "InferenceBudgetBlocked",
    "InferenceCall",
    "cost_contract_for",
    "token_count",
]
