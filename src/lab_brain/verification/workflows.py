"""§24.3's `register_workflows`: how a planned Capability becomes an execution (VS-SP-001).

    §24.3   DomainPack.register_workflows(registry)
    §9.5    Planner 只讀 Capability descriptor，不知道 backend 名稱.
    §25.4   mock/real backend 都走 typed contract.

THE PLANNER CHOOSES A CAPABILITY; SOMETHING HAS TO KNOW WHAT RUNNING IT MEANS. That knowledge is the
domain's -- which typed tools to call, in what order, how to read the tool's stored output back into
an outcome of the declared OutcomeSpace -- and core must not have it. So a DomainPack registers one
`VerificationWorkflow` per capability it can execute, and the loop resolves the chosen capability
here and nowhere else. A capability with no workflow is still plannable (a four-point measurement is
a real option with a real cost); choosing it means a person has to act, and the loop says so
instead of pretending to have executed it.

WHAT A WORKFLOW IS HANDED, AND WHAT IT IS NOT. `WorkflowContext` carries the durable Job the loop
submitted, a `dispatch` that goes through `BudgetedToolDispatcher` (so COST-001's gate, the span
and both ledger rows happen for every tool call), `read_artifact`, which reads a stored artifact's
bytes back by id, and `load_run`, which reads the durable Run manifest. It is handed no store, no
connection and no belief path: a workflow can execute typed tools and read what they stored, and
it cannot write evidence or move a belief. The loop does that, through the admission gate and
`TransitionPolicy`, from what the workflow reports.

THE OUTCOME IS READ FROM THE STORED BYTES. A workflow reports an `ObservedOutcome` it derived from
the Run's output artifact as persisted -- content-addressed and durable before the Run was minted --
never from the backend's in-flight object. §25.4's "raw artifacts 被 hash 且在 parsing 前已
durably 保存" is therefore true of every verification result, not only of ingested documents.

THE REGISTRY IS CHECKED AT INSTALL. `verify` refuses a workflow bound to a capability nobody
registered, one that names a tool the ToolRegistry does not hold, and two workflows for one
capability. A pack whose workflow could not run would otherwise be discovered by the first episode
that chose it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.capability import Capability
from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.models.job import Run
from lab_brain.tools.contracts import ToolRequest
from lab_brain.tools.dispatch import ToolDispatchResult
from lab_brain.tools.registry import ToolNotRegistered, ToolRegistry
from lab_brain.tools.resources import ResourceDemand
from lab_brain.tools.simulation import SimulationRequest
from lab_brain.verification.capability_registry import CapabilityRegistry


class WorkflowError(RuntimeError):
    """A workflow was registered or resolved in a way that cannot run."""


class WorkflowStatus(StrEnum):
    #: The tools ran, a Run is durable, and the outcomes below were read from its stored output.
    EXECUTED = "EXECUTED"
    #: No seat (§10.7). The Job is WAITING_RESOURCE; this is contention, not failure.
    AWAITING_RESOURCE = "AWAITING_RESOURCE"
    #: The budget gate refused the tool call (COST-001). Nothing executed.
    BUDGET_BLOCKED = "BUDGET_BLOCKED"
    #: The backend ran and its Run did not succeed. Recorded, never evidence.
    FAILED = "FAILED"


@dataclass(frozen=True)
class ObservedOutcome:
    """One outcome of a declared OutcomeSpace, read from a Run's stored output."""

    observable_ref: str
    outcome_space_id: str
    outcome_space_version: str
    outcome: str
    #: EVI-003's type for what the execution did: SIMULATED for a solve, OBSERVED for a reading
    #: of a design artifact. Never INFERRED -- a workflow runs code, not a model.
    epistemic_type: EpistemicType
    #: The authority the Run actually earned (e.g. lowered to coarse on non-convergence), which may
    #: be below what the Capability descriptor declares it can yield at best.
    authority_class: str
    #: `rule_id@version` of the domain rule that turned stored numbers into this outcome.
    method_ref: str
    unit: str | None = None
    #: Where in the output artifact the classified quantity lives.
    value_ref: str | None = None
    #: The numbers behind the classification, for the rationale a person reads.
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowResult:
    status: WorkflowStatus
    run_id: str | None = None
    outcomes: tuple[ObservedOutcome, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        executed = self.status is WorkflowStatus.EXECUTED
        if executed and (self.run_id is None or not self.outcomes):
            raise WorkflowError(
                "an EXECUTED workflow must name its Run and at least one outcome read from it; "
                "a result with no Run behind it is not a verification result (EPI-002)"
            )
        if not executed and self.outcomes:
            raise WorkflowError(
                f"a {self.status.value} workflow reports outcomes; nothing executed, so nothing "
                "could have been observed"
            )


@dataclass(frozen=True)
class WorkflowContext:
    """Everything a workflow may use to execute one planned action. See the module docstring."""

    project_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    capability: Capability
    #: The durable Job the loop submitted for this action (§17.16). The Run, lease and completion
    #: identities `run_simulation` needs are derived from it by the runner (`tools.routing`), so a
    #: redelivered execution of the same Job completes the same Run.
    job_id: str
    request_id: str
    input_artifacts: tuple[str, ...]
    conditions: Mapping[str, Any]
    conditions_schema_version: str
    resource_demand: ResourceDemand | None
    #: Through `BudgetedToolDispatcher`. Returns the dispatcher's result unchanged.
    dispatch: Callable[[str, ToolRequest], ToolDispatchResult]
    #: A stored artifact's bytes, by artifact id.
    read_artifact: Callable[[str], bytes]
    #: The durable Run by id -- the manifest `run_simulation` minted, validity record included.
    load_run: Callable[[str], Run | None]
    input_parameters: Mapping[str, Any] = field(default_factory=dict)

    def execution_request(self) -> SimulationRequest:
        """The §17.4 input half for this action, bound to the loop's Job."""
        return SimulationRequest(
            request_id=self.request_id,
            project_id=self.project_id,
            trace_id=self.trace_id,
            episode_id=self.episode_id,
            job_id=self.job_id,
            capability_id=self.capability.capability_id,
            input_artifacts=self.input_artifacts,
            input_parameters=dict(self.input_parameters),
            conditions=dict(self.conditions),
            conditions_schema_version=self.conditions_schema_version,
            resource_demand=self.resource_demand,
        )


@runtime_checkable
class VerificationWorkflow(Protocol):
    """How one Capability is executed. Registered by the DomainPack that owns the capability."""

    @property
    def capability_id(self) -> str: ...

    @property
    def tool_ids(self) -> tuple[str, ...]:
        """Every typed tool this workflow may dispatch -- checked against the ToolRegistry."""
        ...

    def execute(self, context: WorkflowContext) -> WorkflowResult: ...


class WorkflowRegistry:
    """Capability id -> workflow. One per capability; verified against the other registries."""

    def __init__(self) -> None:
        self._workflows: dict[str, VerificationWorkflow] = {}

    def register(self, workflow: VerificationWorkflow) -> VerificationWorkflow:
        if not isinstance(workflow, VerificationWorkflow):
            raise WorkflowError(
                f"{workflow!r} is not a VerificationWorkflow: it must declare the capability it "
                "executes, the typed tools it dispatches, and execute(context)"
            )
        if not workflow.tool_ids:
            raise WorkflowError(
                f"workflow for {workflow.capability_id} declares no tools. §10.2 makes every "
                "execution a typed tool call; a workflow that calls none executes untyped code"
            )
        existing = self._workflows.get(workflow.capability_id)
        if existing is not None and existing is not workflow:
            raise WorkflowError(
                f"a different workflow is already registered for {workflow.capability_id}; which "
                "one ran would depend on registration order"
            )
        self._workflows[workflow.capability_id] = workflow
        return workflow

    def resolve(self, capability_id: str) -> VerificationWorkflow | None:
        """The workflow for a capability, or `None` when executing it needs a person."""
        return self._workflows.get(capability_id)

    def verify(self, capabilities: CapabilityRegistry, tools: ToolRegistry) -> None:
        """Every workflow names a registered capability and only registered tools."""
        for capability_id, workflow in sorted(self._workflows.items()):
            if capabilities.get(capability_id) is None:
                raise WorkflowError(
                    f"workflow registered for {capability_id}, which no pack registered as a "
                    "Capability. The planner can never choose it, so the workflow is dead code "
                    "that reads as a capability (VER-002)"
                )
            for tool_id in workflow.tool_ids:
                try:
                    tools.descriptor(tool_id)
                except ToolNotRegistered as missing:
                    raise WorkflowError(
                        f"workflow for {capability_id} dispatches {tool_id}, which is not a "
                        f"registered typed tool: {missing}"
                    ) from missing

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._workflows))

    def __iter__(self) -> Iterator[VerificationWorkflow]:
        return iter(self._workflows[key] for key in sorted(self._workflows))

    def __len__(self) -> int:
        return len(self._workflows)


__all__ = [
    "ObservedOutcome",
    "VerificationWorkflow",
    "WorkflowContext",
    "WorkflowError",
    "WorkflowRegistry",
    "WorkflowResult",
    "WorkflowStatus",
]
