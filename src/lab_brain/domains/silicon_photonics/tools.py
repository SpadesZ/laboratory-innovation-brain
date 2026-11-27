"""The typed tool faces of this pack's capabilities (§10.2.1, §10.2.2, SIM-003).

WHICH OF §10.2.2's SIX TOOLS ARE HERE, AND WHY NOT ALL SIX. M2's scope is "Lumerical mock/`run_*`,
backend-agnostic `extract_cj_rs`, backend validity" (§26.1) and its exit gate is the shared
extractor contract plus the license/resource queue. That needs one `run_*` producing the arrays, the
`extract_*` that reduces them, and the `validate_*` that reports on the result:

    DOM-SP-TOOL-002  run_charge_ac_sweep       the small-signal execution Cj/Rs is read from
    DOM-SP-TOOL-004  extract_cj_rs             the shared boundary both modalities enter through
    DOM-SP-TOOL-006  validate_expected_trends  the versioned rule DOM-SP-001 keeps out of core

`run_charge_dc_sweep` (001), `run_mesh_sensitivity` (003) and `inspect_contact_connectivity` (005)
are declared by §25.2 for the FIRST VERTICAL, which is M4's VS-SP-001 full loop -- registering
stubs for them now would put three unplannable capabilities in the registry and three tools nobody
can invoke, which is worse than their absence because a registry entry reads as a capability.

EVERY TOOL DECLARES ITS REQUEST AND RESULT TYPES. That is SIM-003's positive half: the registry
checks the payload against the declared type before the implementation is reached, so no tool here
has to decide what an unknown object means.
"""

from __future__ import annotations

from typing import Final, Protocol, Self, runtime_checkable

from pydantic import model_validator

from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.validation import ValidationReport
from lab_brain.domains.silicon_photonics import backend_validity, extractors, validators
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN, SCHEMA_REF
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.execution import ExecutionOutcome, WaitingForResource
from lab_brain.tools.extraction import ExtractionInput, ExtractionResult
from lab_brain.tools.scope import ExecutionScope, JobBinding, require_same_scope
from lab_brain.tools.simulation import SimulationRequest

#: The seat this domain's simulator contends for (§10.7). A declared identity rather than a
#: literal at each call site, because a mistyped resource id parks a job behind a pool nobody
#: declared -- which the broker refuses precisely so it is a loud error and not a silent wait.
SIMULATOR_RESOURCE_ID: Final = "license:sp-charge-seat"

CHARGE_AC_TOOL_ID: Final = "DOM-SP-TOOL-002"
CHARGE_AC_TOOL_NAME: Final = "run_charge_ac_sweep"
CHARGE_AC_CAPABILITY: Final = "cap:sp.charge_ac_sweep"
CHARGE_AC_VERSION: Final = "1.0.0"

#: §17.18's `estimate_cost_contract` for this pack's two LOCAL tools -- the extractor and the
#: validator. Neither has a Capability (§10.2.1 makes them backend-agnostic, and `ToolDescriptor`
#: refuses one that names a backend), so the contract lives on the tool descriptor instead.
#:
#: They are genuinely cheap: the estimator registered against this name returns a CostVector of
#: seconds and nothing else. That is the point rather than a concession -- COST-001 gates *each*
#: tool call, and a zero-cost call still passes the gate. "Cheap" is not "ungoverned".
LOCAL_TOOL_COST_CONTRACT: Final = "cost:sp.local_tool@1.0.0"

#: Observable kind names. Opaque to core, matched by the planner as strings (§9.5).
OBSERVABLE_IMPEDANCE: Final = "sp.small_signal_impedance"
OBSERVABLE_CJ_RS: Final = "sp.cj_rs_per_length"
OBSERVABLE_TREND_REPORT: Final = "sp.expected_trend_report"
INPUT_DEVICE_PROJECT: Final = "sp.device_project"


# ---------------------------------------------------------------------------
# DOM-SP-TOOL-002  run_charge_ac_sweep
# ---------------------------------------------------------------------------


class ChargeAcSweepRequest(ToolRequest):
    """The typed face of a small-signal execution.

    Carries a `SimulationRequest` rather than re-declaring its fields: §17.4's manifest inputs are
    already stated once, and a second copy here would be two places that have to agree about what
    an execution is.

    THE SCOPE IS STILL DECLARED TWICE, because `ToolRequest` requires `project_id`, `trace_id` and
    `episode_id` and `SimulationRequest` requires them too -- so the validator below makes them
    agree at construction. A `ChargeAcSweepRequest` for project A wrapping a simulation for project
    B, or budgeted in Episode E1 wrapping an execution for Episode E2, cannot be built, which means
    no stage downstream has to be careful about which of the two it read.
    """

    simulation: SimulationRequest

    @model_validator(mode="after")
    def _the_envelope_and_its_execution_are_one_execution(self) -> Self:
        """§17.16's scope, bound at the model boundary rather than checked by each caller.

        AT THE BOUNDARY BECAUSE THE ALTERNATIVE IS EVERY CALLER. The dispatcher binds the action to
        this request and `run_simulation` binds the nested request to the Job; without this
        validator the one hop between them -- the tool unwrapping `request.simulation` -- is the
        gap the other two guards do not cover, and it is the hop at which the payload stops being
        the thing that was budgeted.

        THE CAPABILITY IS CHECKED HERE AND NOWHERE EARLIER for the reason §10.2.1 gives: a
        `ToolAction` carries no capability and should not start to, since the capability is the
        *descriptor's* identity and a second copy on the action would be one more field that could
        disagree. `charge_ac_descriptor()` and this validator read the same `CHARGE_AC_CAPABILITY`
        constant, so the pack has one capability identity rather than two that must be kept in
        step -- and that is what makes the chain descriptor -> request -> Job hold end to end, with
        `run_simulation` closing the last link.

        This is a silicon photonics contract and it lives in the silicon photonics pack.
        `lab_brain.tools.scope` compares four identities and does not know what CHARGE is.
        """
        require_same_scope(
            ExecutionScope(
                layer="ChargeAcSweepRequest",
                project_id=self.project_id,
                trace_id=self.trace_id,
                episode_id=self.episode_id,
                capability_id=CHARGE_AC_CAPABILITY,
            ),
            ExecutionScope(
                layer="ChargeAcSweepRequest.simulation",
                project_id=self.simulation.project_id,
                trace_id=self.simulation.trace_id,
                episode_id=self.simulation.episode_id,
                capability_id=self.simulation.capability_id,
            ),
            detail=(
                f"{CHARGE_AC_TOOL_NAME} would have been gated and traced as one execution and run "
                "as another. The gate prices the envelope; the backend receives the nested "
                "request; nothing between them re-reads the envelope, so a difference here is a "
                "difference nothing downstream can detect"
            ),
        )
        return self

    def job_binding(self) -> JobBinding:
        """The Job this sweep executes: the nested request's, under the nested request's scope.

        READ OFF `self.simulation` AND NOTHING ELSE, because `ChargeAcSweepTool` hands exactly that
        object to the runner and `run_simulation` executes exactly its ``job_id``. The binding the
        dispatcher checks before the gate is therefore the execution that will happen, not a
        description of it assembled somewhere else -- and the validator above has already made the
        envelope and this scope agree, so action -> envelope -> execution -> Job is one chain.
        """
        return JobBinding(
            job_id=self.simulation.job_id,
            scope=ExecutionScope(
                layer="SimulationRequest",
                project_id=self.simulation.project_id,
                trace_id=self.simulation.trace_id,
                episode_id=self.simulation.episode_id,
                capability_id=self.simulation.capability_id,
            ),
        )


class ChargeAcSweepResult(ToolResult):
    """What the run tool reports -- including "no seat, the job is waiting".

    `run_id` rather than the Run object: the authoritative Run comes from `JobStore.complete`, and
    a tool result carrying its own copy would be a second record of one execution.

    `waiting_on_resource` IS A RESULT, NOT AN EXCEPTION, and that is §10.7 expressed in the tool
    contract. A run tool that raised on seat contention would make a working queue indistinguishable
    from a broken solver at every call site, and every caller would then have to re-derive the
    distinction. Exactly one of the two fields is set.
    """

    run_id: str | None = None
    waiting_on_resource: str | None = None
    numerical_array_refs: tuple[str, ...] = ()
    output_artifacts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> Self:
        set_fields = [self.run_id, self.waiting_on_resource]
        if len([value for value in set_fields if value is not None]) != 1:
            raise ValueError(
                f"{CHARGE_AC_TOOL_NAME} returned run_id={self.run_id!r} and "
                f"waiting_on_resource={self.waiting_on_resource!r}; an execution either produced a "
                "Run or is waiting for a seat, and a result that is both or neither leaves the "
                "caller to guess which"
            )
        if self.waiting_on_resource is not None and (
            self.numerical_array_refs or self.output_artifacts
        ):
            raise ValueError(
                f"{CHARGE_AC_TOOL_NAME} is waiting on {self.waiting_on_resource} and reports "
                "outputs; nothing executed, so there is nothing to have produced them"
            )
        return self

    @property
    def executed(self) -> bool:
        return self.run_id is not None


@runtime_checkable
class SimulationRunner(Protocol):
    """How this pack reaches the execution seam without importing a composition root.

    The pack declares what it needs and is handed it; `lab_brain.tools.execution.run_simulation`
    partially applied is the production implementation, and a test supplies a deterministic one.
    That direction is §24.2's: the domain depends on the tools interface, never the reverse.
    """

    def __call__(self, request: SimulationRequest) -> ExecutionOutcome: ...


class ChargeAcSweepTool:
    """The registry face of the small-signal execution.

    Holds the runner and nothing else -- no store, no broker, no connection. Seat acquisition,
    validity checking and Run minting all happen inside `run_simulation`, in the order its module
    docstring fixes, so this tool cannot perform them in a different one.
    """

    def __init__(self, runner: SimulationRunner) -> None:
        self._runner = runner

    @property
    def request_model(self) -> type[ChargeAcSweepRequest]:
        return ChargeAcSweepRequest

    @property
    def result_model(self) -> type[ChargeAcSweepResult]:
        return ChargeAcSweepResult

    def __call__(self, request: ToolRequest) -> ChargeAcSweepResult:
        assert isinstance(request, ChargeAcSweepRequest)  # the registry checked it
        outcome = self._runner(request.simulation)
        if isinstance(outcome, WaitingForResource):
            return ChargeAcSweepResult(
                tool_id=CHARGE_AC_TOOL_ID,
                tool_version=CHARGE_AC_VERSION,
                waiting_on_resource=outcome.resource_id,
                warnings=(
                    f"no seat on {outcome.resource_id}: {outcome.requested} requested, "
                    f"{outcome.available} free. The job is WAITING_RESOURCE (§10.7); this is "
                    "contention, not a simulation failure",
                ),
            )
        # §17.17's ACTUAL, measured rather than assumed. The Run knows exactly how long it took and
        # the seat was held for that interval, so this is the one dimension the tool is better
        # placed to report than the dispatcher's wrapper -- which would also be counting the
        # registry's type check and the ledger write.
        elapsed = max(0, int((outcome.run.end_time - outcome.run.start_time).total_seconds()))
        return ChargeAcSweepResult(
            tool_id=CHARGE_AC_TOOL_ID,
            tool_version=CHARGE_AC_VERSION,
            run_id=outcome.run.run_id,
            numerical_array_refs=outcome.run.numerical_array_refs,
            output_artifacts=outcome.run.output_artifacts,
            warnings=outcome.run.warnings,
            actual_cost=CostVector(
                wall_clock_s=elapsed,
                license_seat_s=elapsed if outcome.lease is not None else 0,
            ),
        )


def charge_ac_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id=CHARGE_AC_TOOL_ID,
        name=CHARGE_AC_TOOL_NAME,
        tool_class=ToolClass.RUN,
        domain=DOMAIN,
        version=CHARGE_AC_VERSION,
        capability_id=CHARGE_AC_CAPABILITY,
        conditions_schema_version=SCHEMA_REF,
        requires=(INPUT_DEVICE_PROJECT,),
        produces=(OBSERVABLE_IMPEDANCE,),
        resource_id=SIMULATOR_RESOURCE_ID,
        notes={
            "validity_schema": backend_validity.SCHEMA_REF,
            "backend": "provider-independent; the only backend wired in this repository is the "
            "deterministic mock in lab_brain.tool_providers.lumerical.mock",
        },
    )


# ---------------------------------------------------------------------------
# DOM-SP-TOOL-004  extract_cj_rs
# ---------------------------------------------------------------------------


def extract_cj_rs_descriptor() -> ToolDescriptor:
    """The backend-agnostic extractor. Names NO capability and NO resource, and that is checked.

    `ToolDescriptor` refuses an `extract_*` tool that names either -- see its validator. That is
    the structural form of DOM-SP-002: "backend-agnostic" is not a property of the implementation's
    good intentions, it is a descriptor that cannot name a backend.
    """
    return ToolDescriptor(
        tool_id=extractors.TOOL_ID,
        name=extractors.TOOL_NAME,
        tool_class=ToolClass.EXTRACT,
        domain=DOMAIN,
        version=extractors.EXTRACTOR_VERSION,
        cost_contract=LOCAL_TOOL_COST_CONTRACT,
        requires=(OBSERVABLE_IMPEDANCE,),
        produces=(OBSERVABLE_CJ_RS,),
        notes={
            "normalization_basis": extractors.NORMALIZATION_BASIS,
            "accepts": "SIMULATED and MEASURED; one ExtractionInput type for both (DOM-SP-002)",
        },
    )


# ---------------------------------------------------------------------------
# DOM-SP-TOOL-006  validate_expected_trends
# ---------------------------------------------------------------------------


class TrendValidationRequest(ToolRequest):
    subject: validators.TrendSubject


class TrendValidationResult(ToolResult):
    """Carries a `ValidationReport` and nothing else scientific.

    `ToolRegistry.register` refuses a `validate_*` tool whose result model has no
    `ValidationReport` field, which is §17.19.2's "never an unstructured boolean/string" enforced
    at registration rather than by convention. It carries no observable, because a validator that
    also produced one would be writing evidence (§10.2.1).
    """

    report: ValidationReport


class ExpectedTrendTool:
    """The registry face of `ExpectedTrendValidator`. One rule implementation, two interfaces."""

    def __init__(self, validator: validators.ExpectedTrendValidator) -> None:
        self._validator = validator

    @property
    def request_model(self) -> type[TrendValidationRequest]:
        return TrendValidationRequest

    @property
    def result_model(self) -> type[TrendValidationResult]:
        return TrendValidationResult

    def __call__(self, request: ToolRequest) -> TrendValidationResult:
        assert isinstance(request, TrendValidationRequest)  # the registry checked it
        return TrendValidationResult(
            tool_id=validators.TOOL_ID,
            tool_version=validators.VALIDATOR_VERSION,
            report=self._validator.validate(request.subject),
        )


def validate_trends_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id=validators.TOOL_ID,
        name=validators.TOOL_NAME,
        tool_class=ToolClass.VALIDATE,
        domain=DOMAIN,
        version=validators.VALIDATOR_VERSION,
        cost_contract=LOCAL_TOOL_COST_CONTRACT,
        requires=(OBSERVABLE_CJ_RS,),
        produces=(OBSERVABLE_TREND_REPORT,),
        notes={"rules": sorted(validators.RULES)},
    )


__all__ = [
    "CHARGE_AC_CAPABILITY",
    "CHARGE_AC_TOOL_ID",
    "CHARGE_AC_TOOL_NAME",
    "CHARGE_AC_VERSION",
    "INPUT_DEVICE_PROJECT",
    "LOCAL_TOOL_COST_CONTRACT",
    "OBSERVABLE_CJ_RS",
    "OBSERVABLE_IMPEDANCE",
    "OBSERVABLE_TREND_REPORT",
    "SIMULATOR_RESOURCE_ID",
    "ChargeAcSweepRequest",
    "ChargeAcSweepResult",
    "ChargeAcSweepTool",
    "ExpectedTrendTool",
    "ExtractionInput",
    "ExtractionResult",
    "SimulationRunner",
    "TrendValidationRequest",
    "TrendValidationResult",
    "charge_ac_descriptor",
    "extract_cj_rs_descriptor",
    "validate_trends_descriptor",
]
