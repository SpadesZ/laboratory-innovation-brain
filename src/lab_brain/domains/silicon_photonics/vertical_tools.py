"""VS-SP-001's typed tools and the workflows that execute its capabilities (§25.2, §24.3, SIM-003).

    DOM-SP-TOOL-001  run_charge_dc_sweep            run      carrier profile over reverse bias
    DOM-SP-TOOL-003  run_mesh_sensitivity           run      two mesh variants, stability delta
    DOM-SP-TOOL-005  inspect_contact_connectivity   inspect  contacts, vias, connected regions
    DOM-SP-TOOL-011  inspect_normalization_basis    inspect  drawn vs normalization length

The fourth is not in §10.2.2's canonical table, which is the MINIMUM set; §25.1's "model check"
needs a reader of the extraction's normalization basis, and DOM-SP-TOOL-011 is the next free id in
the one scheme §10.2.1 allows (007-010 are Appendix B's ring/mode tools).

ONE REQUEST SHAPE FOR ALL FOUR, AND IT BINDS THE JOB. Each request wraps the `SimulationRequest`
that `run_simulation` executes and names that request's Job through `job_binding`, so the
dispatcher checks the Episode it prices against the Episode whose Job runs, before the gate, for
the inspections as for the solves. The request's capability is fixed by its class and checked at
construction: an `InspectContactConnectivityRequest` wrapping a DC sweep cannot be built.

A WORKFLOW IS: dispatch the tool, read the Run's STORED output, apply the named rule. The authority
the outcome carries is derived, not declared -- for a solve, `backend_validity.fidelity_for` reads
the Run's own validity record, so a non-converged sweep yields SIM_COARSE whatever the capability
promised (SIM-002). For an inspection it is DESIGN_INSPECTION: there is nothing to converge.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Final, Self

from pydantic import model_validator

from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.models.job import Run
from lab_brain.domains.silicon_photonics import backend_validity, diagnosis, vertical
from lab_brain.domains.silicon_photonics.authority_policy import SIM_STANDARD
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN
from lab_brain.domains.silicon_photonics.tools import (
    INPUT_DEVICE_PROJECT,
    SIMULATOR_RESOURCE_ID,
    SimulationRunner,
)
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.execution import WaitingForResource
from lab_brain.tools.scope import ExecutionScope, JobBinding, require_same_scope
from lab_brain.tools.simulation import SimulationRequest
from lab_brain.verification.workflows import (
    ObservedOutcome,
    WorkflowContext,
    WorkflowResult,
    WorkflowStatus,
)

TOOL_VERSION: Final = "1.0.0"

DC_TOOL_ID: Final = "DOM-SP-TOOL-001"
MESH_TOOL_ID: Final = "DOM-SP-TOOL-003"
CONNECTIVITY_TOOL_ID: Final = "DOM-SP-TOOL-005"
NORMALIZATION_TOOL_ID: Final = "DOM-SP-TOOL-011"


class DesignExecutionRequest(ToolRequest):
    """The typed face of one recorded execution against a device project."""

    capability_id: ClassVar[str]
    tool_name: ClassVar[str]
    execution: SimulationRequest

    @model_validator(mode="after")
    def _the_envelope_and_its_execution_are_one_execution(self) -> Self:
        require_same_scope(
            ExecutionScope(
                layer=type(self).__name__,
                project_id=self.project_id,
                trace_id=self.trace_id,
                episode_id=self.episode_id,
                capability_id=self.capability_id,
            ),
            ExecutionScope(
                layer=f"{type(self).__name__}.execution",
                project_id=self.execution.project_id,
                trace_id=self.execution.trace_id,
                episode_id=self.execution.episode_id,
                capability_id=self.execution.capability_id,
            ),
            detail=(
                f"{self.tool_name} would be gated as one execution and run as another; the gate "
                "prices the envelope and the backend receives the nested request"
            ),
        )
        return self

    def job_binding(self) -> JobBinding:
        return JobBinding(
            job_id=self.execution.job_id,
            scope=ExecutionScope(
                layer="SimulationRequest",
                project_id=self.execution.project_id,
                trace_id=self.execution.trace_id,
                episode_id=self.execution.episode_id,
                capability_id=self.execution.capability_id,
            ),
        )


class ChargeDcSweepRequest(DesignExecutionRequest):
    capability_id: ClassVar[str] = vertical.CAP_CHARGE_DC
    tool_name: ClassVar[str] = "run_charge_dc_sweep"


class MeshSensitivityRequest(DesignExecutionRequest):
    capability_id: ClassVar[str] = vertical.CAP_MESH_SENSITIVITY
    tool_name: ClassVar[str] = "run_mesh_sensitivity"


class ContactConnectivityRequest(DesignExecutionRequest):
    capability_id: ClassVar[str] = vertical.CAP_INSPECT_CONNECTIVITY
    tool_name: ClassVar[str] = "inspect_contact_connectivity"


class NormalizationBasisRequest(DesignExecutionRequest):
    capability_id: ClassVar[str] = vertical.CAP_EXTRACTION_CONSISTENCY
    tool_name: ClassVar[str] = "inspect_normalization_basis"


class DesignExecutionResult(ToolResult):
    """A Run, or a wait for a seat -- exactly one (as `ChargeAcSweepResult`)."""

    run_id: str | None = None
    waiting_on_resource: str | None = None
    output_artifacts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> Self:
        if (self.run_id is None) == (self.waiting_on_resource is None):
            raise ValueError(
                f"{self.tool_id} returned run_id={self.run_id!r} and "
                f"waiting_on_resource={self.waiting_on_resource!r}; exactly one must be set"
            )
        if self.waiting_on_resource is not None and self.output_artifacts:
            raise ValueError(f"{self.tool_id} is waiting and reports outputs")
        return self


class DesignExecutionTool:
    """Holds the runner and nothing else. Every tool of this module is this class."""

    def __init__(
        self, tool_id: str, request_type: type[DesignExecutionRequest], runner: SimulationRunner
    ) -> None:
        self._tool_id = tool_id
        self._request_type = request_type
        self._runner = runner

    @property
    def request_model(self) -> type[DesignExecutionRequest]:
        return self._request_type

    @property
    def result_model(self) -> type[DesignExecutionResult]:
        return DesignExecutionResult

    def __call__(self, request: ToolRequest) -> DesignExecutionResult:
        assert isinstance(request, self._request_type)  # the registry checked it
        outcome = self._runner(request.execution)
        if isinstance(outcome, WaitingForResource):
            return DesignExecutionResult(
                tool_id=self._tool_id,
                tool_version=TOOL_VERSION,
                waiting_on_resource=outcome.resource_id,
                warnings=(f"no seat on {outcome.resource_id}; the job is WAITING_RESOURCE",),
            )
        elapsed = max(0, int((outcome.run.end_time - outcome.run.start_time).total_seconds()))
        return DesignExecutionResult(
            tool_id=self._tool_id,
            tool_version=TOOL_VERSION,
            run_id=outcome.run.run_id,
            output_artifacts=outcome.run.output_artifacts,
            warnings=outcome.run.warnings,
            actual_cost=CostVector(
                wall_clock_s=elapsed,
                license_seat_s=elapsed if outcome.lease is not None else 0,
            ),
        )


def _run_descriptor(
    tool_id: str, name: str, capability_id: str, produces: str, validity: str
) -> ToolDescriptor:
    return ToolDescriptor(
        tool_id=tool_id,
        name=name,
        tool_class=ToolClass.RUN,
        domain=DOMAIN,
        version=TOOL_VERSION,
        capability_id=capability_id,
        conditions_schema_version=vertical.DEVICE_SCHEMA_REF,
        requires=(INPUT_DEVICE_PROJECT,),
        produces=(produces,),
        resource_id=SIMULATOR_RESOURCE_ID,
        notes={
            "validity_schema": validity,
            "backend": "provider-independent; the only backends wired in this repository are "
            "the deterministic mocks in lab_brain.tool_providers.lumerical.mock_vertical",
        },
    )


def _inspect_descriptor(tool_id: str, name: str, produces: str, rule: str) -> ToolDescriptor:
    return ToolDescriptor(
        tool_id=tool_id,
        name=name,
        tool_class=ToolClass.INSPECT,
        domain=DOMAIN,
        version=TOOL_VERSION,
        cost_contract=vertical.COST_DESIGN_INSPECTION,
        requires=(INPUT_DEVICE_PROJECT,),
        produces=(produces,),
        notes={
            "rule": rule,
            "execution": "solver-free local reader, recorded as a Job/Run (EPI-002); no seat",
        },
    )


def descriptors() -> tuple[tuple[ToolDescriptor, type[DesignExecutionRequest]], ...]:
    return (
        (
            _run_descriptor(
                DC_TOOL_ID,
                "run_charge_dc_sweep",
                vertical.CAP_CHARGE_DC,
                vertical.OBS_CARRIER,
                backend_validity.SCHEMA_REF,
            ),
            ChargeDcSweepRequest,
        ),
        (
            _run_descriptor(
                MESH_TOOL_ID,
                "run_mesh_sensitivity",
                vertical.CAP_MESH_SENSITIVITY,
                vertical.OBS_MESH,
                backend_validity.SCHEMA_REF,
            ),
            MeshSensitivityRequest,
        ),
        (
            _inspect_descriptor(
                CONNECTIVITY_TOOL_ID,
                "inspect_contact_connectivity",
                vertical.OBS_CONNECTIVITY,
                diagnosis.CONNECTIVITY_RULE,
            ),
            ContactConnectivityRequest,
        ),
        (
            _inspect_descriptor(
                NORMALIZATION_TOOL_ID,
                "inspect_normalization_basis",
                vertical.OBS_NORMALIZATION,
                diagnosis.NORMALIZATION_RULE,
            ),
            NormalizationBasisRequest,
        ),
    )


# -- workflows ---------------------------------------------------------------------------------


class DesignWorkflow:
    """Dispatch one tool, read the Run's stored output, apply one versioned rule."""

    def __init__(
        self,
        *,
        capability_id: str,
        tool_id: str,
        request_type: type[DesignExecutionRequest],
        observable_ref: str,
        space_id: str,
        rule_ref: str,
        epistemic_type: EpistemicType,
        authority: Callable[[Run], str],
    ) -> None:
        self._capability_id = capability_id
        self._tool_id = tool_id
        self._request_type = request_type
        self._observable = observable_ref
        self._space = space_id
        self._rule = rule_ref
        self._epistemic = epistemic_type
        self._authority = authority

    @property
    def capability_id(self) -> str:
        return self._capability_id

    @property
    def tool_ids(self) -> tuple[str, ...]:
        return (self._tool_id,)

    def execute(self, context: WorkflowContext) -> WorkflowResult:
        request = self._request_type(
            project_id=context.project_id,
            trace_id=context.trace_id,
            episode_id=context.episode_id,
            execution=context.execution_request(),
        )
        dispatched = context.dispatch(self._tool_id, request)
        if dispatched.blocked:
            return WorkflowResult(
                status=WorkflowStatus.BUDGET_BLOCKED,
                detail=f"{dispatched.decision.outcome.value}: {dispatched.decision.reason}",
            )
        result = dispatched.result
        assert isinstance(result, DesignExecutionResult)  # the registry checked it
        if result.waiting_on_resource is not None:
            return WorkflowResult(
                status=WorkflowStatus.AWAITING_RESOURCE,
                detail=f"job {context.job_id} is WAITING_RESOURCE on {result.waiting_on_resource}",
            )
        assert result.run_id is not None
        run = context.load_run(result.run_id)
        if run is None or run.status.value != "SUCCEEDED" or not run.output_artifacts:
            return WorkflowResult(
                status=WorkflowStatus.FAILED,
                run_id=result.run_id,
                detail=f"run {result.run_id} did not succeed with a stored output",
            )
        stored = context.read_artifact(run.output_artifacts[0])
        outcome, detail = diagnosis.RULES[self._rule](stored)
        return WorkflowResult(
            status=WorkflowStatus.EXECUTED,
            run_id=run.run_id,
            outcomes=(
                ObservedOutcome(
                    observable_ref=self._observable,
                    outcome_space_id=self._space,
                    outcome_space_version=vertical.SPACE_VERSION,
                    outcome=outcome,
                    epistemic_type=self._epistemic,
                    authority_class=self._authority(run),
                    method_ref=self._rule,
                    value_ref=f"{run.output_artifacts[0]}#{self._observable}",
                    detail=detail,
                ),
            ),
        )


def _solved(run: Run) -> str:
    return backend_validity.fidelity_for(dict(run.backend_validity), SIM_STANDARD)


def _inspected(run: Run) -> str:
    del run
    return vertical.DESIGN_INSPECTION


def workflows() -> tuple[DesignWorkflow, ...]:
    spec: tuple[tuple[str, str, type[DesignExecutionRequest], str, str, str, Any, Any], ...] = (
        (
            vertical.CAP_CHARGE_DC,
            DC_TOOL_ID,
            ChargeDcSweepRequest,
            vertical.OBS_CARRIER,
            vertical.SPACE_CARRIER,
            diagnosis.CARRIER_RULE,
            EpistemicType.SIMULATED,
            _solved,
        ),
        (
            vertical.CAP_MESH_SENSITIVITY,
            MESH_TOOL_ID,
            MeshSensitivityRequest,
            vertical.OBS_MESH,
            vertical.SPACE_MESH,
            diagnosis.MESH_RULE,
            EpistemicType.SIMULATED,
            _solved,
        ),
        (
            vertical.CAP_INSPECT_CONNECTIVITY,
            CONNECTIVITY_TOOL_ID,
            ContactConnectivityRequest,
            vertical.OBS_CONNECTIVITY,
            vertical.SPACE_CONNECTIVITY,
            diagnosis.CONNECTIVITY_RULE,
            EpistemicType.OBSERVED,
            _inspected,
        ),
        (
            vertical.CAP_EXTRACTION_CONSISTENCY,
            NORMALIZATION_TOOL_ID,
            NormalizationBasisRequest,
            vertical.OBS_NORMALIZATION,
            vertical.SPACE_NORMALIZATION,
            diagnosis.NORMALIZATION_RULE,
            EpistemicType.OBSERVED,
            _inspected,
        ),
    )
    return tuple(
        DesignWorkflow(
            capability_id=capability,
            tool_id=tool,
            request_type=request,
            observable_ref=observable,
            space_id=space,
            rule_ref=rule,
            epistemic_type=epistemic,
            authority=authority,
        )
        for capability, tool, request, observable, space, rule, epistemic, authority in spec
    )


__all__ = [
    "CONNECTIVITY_TOOL_ID",
    "DC_TOOL_ID",
    "MESH_TOOL_ID",
    "NORMALIZATION_TOOL_ID",
    "ChargeDcSweepRequest",
    "ContactConnectivityRequest",
    "DesignExecutionRequest",
    "DesignExecutionResult",
    "DesignExecutionTool",
    "DesignWorkflow",
    "MeshSensitivityRequest",
    "NormalizationBasisRequest",
    "descriptors",
    "workflows",
]
