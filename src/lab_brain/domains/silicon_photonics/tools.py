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

from lab_brain.core.models.validation import ValidationReport
from lab_brain.domains.silicon_photonics import backend_validity, extractors, validators
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN, SCHEMA_REF
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.execution import ExecutionOutcome, WaitingForResource
from lab_brain.tools.extraction import ExtractionInput, ExtractionResult
from lab_brain.tools.simulation import SimulationRequest

#: The seat this domain's simulator contends for (§10.7). A declared identity rather than a
#: literal at each call site, because a mistyped resource id parks a job behind a pool nobody
#: declared -- which the broker refuses precisely so it is a loud error and not a silent wait.
SIMULATOR_RESOURCE_ID: Final = "license:sp-charge-seat"

CHARGE_AC_TOOL_ID: Final = "DOM-SP-TOOL-002"
CHARGE_AC_TOOL_NAME: Final = "run_charge_ac_sweep"
CHARGE_AC_CAPABILITY: Final = "cap:sp.charge_ac_sweep"
CHARGE_AC_VERSION: Final = "1.0.0"

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
    """

    simulation: SimulationRequest


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
        return ChargeAcSweepResult(
            tool_id=CHARGE_AC_TOOL_ID,
            tool_version=CHARGE_AC_VERSION,
            run_id=outcome.run.run_id,
            numerical_array_refs=outcome.run.numerical_array_refs,
            output_artifacts=outcome.run.output_artifacts,
            warnings=outcome.run.warnings,
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
