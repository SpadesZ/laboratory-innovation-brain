"""Typed tools, the provider-independent execution contract, and the seat pool (§10, M2).

DOMAIN-FREE BY CONSTRUCTION. Nothing in this package names a solver, an instrument or a physical
quantity. §24.2 permits `domains.silicon_photonics -> tools`, and forbids the reverse; the guard is
`tests/unit/test_extension_boundary.py`, which parses the import graph rather than trusting it.

    contracts.py   §10.2.1's four verb classes, and what each prefix promises
    dispatch.py    COST-001 + SIM-003 together: the one supported production tool call
    registry.py    SIM-003's typed ToolRegistry -- the only invocation path
    extraction.py  DOM-SP-002's one extractor boundary, shared by SIMULATED and MEASURED
    simulation.py  §17.4's request/execution seam and §17.10's backend-validity schemas
    resources.py   §10.7's license seats, and why "no seat" is not a failure
    scope.py       the project/trace/capability identities every layer must agree on
    execution.py   seat -> execute -> validate -> Run, in that order
"""

from lab_brain.tools.contracts import (
    ToolClass,
    ToolContractError,
    ToolDescriptor,
    ToolImplementation,
    ToolRequest,
    ToolResult,
)
from lab_brain.tools.dispatch import (
    BudgetedToolDispatcher,
    ToolAction,
    ToolDispatchRefused,
    ToolDispatchResult,
)
from lab_brain.tools.execution import (
    Executed,
    ExecutionOutcome,
    ResourceBindingError,
    WaitingForResource,
    bound_demand,
    run_simulation,
    simulated_source,
    submit_simulation_job,
)
from lab_brain.tools.extraction import (
    EXTRACTABLE_MODALITIES,
    ExtractedQuantity,
    ExtractionContractError,
    ExtractionInput,
    ExtractionResult,
    ExtractionSource,
    MetricExtractor,
    NumericalSeries,
    missing_series,
)
from lab_brain.tools.registry import (
    ToolInvocationError,
    ToolNotRegistered,
    ToolRegistrationError,
    ToolRegistry,
)
from lab_brain.tools.resources import (
    InMemoryResourceBroker,
    ResourceBroker,
    ResourceDemand,
    ResourceError,
    ResourceLease,
    ResourceUnavailable,
    availability_for,
)
from lab_brain.tools.scope import (
    ExecutionScope,
    ExecutionScopeMismatch,
    require_same_scope,
)
from lab_brain.tools.simulation import (
    BackendExecution,
    BackendValidityError,
    BackendValidityRegistry,
    BackendValiditySchema,
    SimulationBackend,
    SimulationContractError,
    SimulationRequest,
    manifest_for,
    validate_backend_validity,
)

__all__ = [
    "EXTRACTABLE_MODALITIES",
    "BackendExecution",
    "BackendValidityError",
    "BackendValidityRegistry",
    "BackendValiditySchema",
    "BudgetedToolDispatcher",
    "Executed",
    "ExecutionOutcome",
    "ExecutionScope",
    "ExecutionScopeMismatch",
    "ExtractedQuantity",
    "ExtractionContractError",
    "ExtractionInput",
    "ExtractionResult",
    "ExtractionSource",
    "InMemoryResourceBroker",
    "MetricExtractor",
    "NumericalSeries",
    "ResourceBindingError",
    "ResourceBroker",
    "ResourceDemand",
    "ResourceError",
    "ResourceLease",
    "ResourceUnavailable",
    "SimulationBackend",
    "SimulationContractError",
    "SimulationRequest",
    "ToolAction",
    "ToolClass",
    "ToolContractError",
    "ToolDescriptor",
    "ToolDispatchRefused",
    "ToolDispatchResult",
    "ToolImplementation",
    "ToolInvocationError",
    "ToolNotRegistered",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolRequest",
    "ToolResult",
    "WaitingForResource",
    "availability_for",
    "bound_demand",
    "manifest_for",
    "missing_series",
    "require_same_scope",
    "run_simulation",
    "simulated_source",
    "submit_simulation_job",
    "validate_backend_validity",
]
