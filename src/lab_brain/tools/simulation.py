"""The provider-independent simulation execution contract (SIM-001, §10.1, §10.3, §17.4).

    SIM-001  每次 CHARGE run 必須保存 solver version、project hash、mesh/bias/config、
             exit/convergence status。
    T-SIM-001  run manifest 缺 solver/project/conditions/validity 任一必要欄位即拒絕升級
               正式 evidence。

READ THE TWO LINES TOGETHER AND THE DESIGN FOLLOWS. §25.3's sentence names CHARGE-specific things
-- solver version, mesh, bias, convergence. §17.4's sentence forbids core from knowing any of them:
*Core MUST NOT hard-code solver_settings / mesh_convergence / calibration fields.* Those are not in
tension. What core owns is that a backend execution declares **which validity schema it conforms
to** and carries a payload; what the DomainPack owns is that the schema named
`silicon_photonics/simulator_validity@1.0.0` requires `solver_version`, `project_hash`,
`mesh_config_ref`, `bias_config_ref` and `convergence_status`.

So `BackendValiditySchema` below has a `required_fields` tuple and no opinion about what goes in
it, and `validate_backend_validity` is the check T-SIM-001 asks for. A `mesh_convergence` field in
this module would be the EXT-001 violation, one file early.

WHY THE BACKEND PROTOCOL IS NOT "the Lumerical interface with the names changed". A provider
adapter written against `lumapi` and then abstracted afterwards keeps the shape of the thing it
was abstracted from. The seam here is written from §17.4 instead: a `SimulationRequest` carries
exactly the inputs a Run manifest records, and a `BackendExecution` carries exactly the outputs.
A backend that cannot fill those is a backend whose results cannot become evidence, which is the
right thing to discover at the seam rather than at admission.

THERE IS NO REAL LUMERICAL HERE, AND NOTHING PRETENDS OTHERWISE. No module in this repository
imports `lumapi`, opens a session or consumes a license seat; `lab_brain.tool_providers.lumerical`
contains a deterministic mock and says so in its own docstring, and
`test_no_vendor_sdk_is_imported_anywhere` fails if that changes without the accompanying work. What
is proven by M2 is the contract; TST-001's second half -- the same case replayed against a real
project on a licensed machine -- is not discharged and is recorded as risk R-1.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.condition import ConditionSchemaRef
from lab_brain.core.models.job import Run, RunStatus
from lab_brain.tools.extraction import NumericalSeries
from lab_brain.tools.resources import ResourceDemand


class SimulationContractError(ValueError):
    """A simulation request or execution does not satisfy the contract."""


class BackendValidityError(ValueError):
    """A backend-validity payload does not satisfy the schema it names (SIM-001)."""


class BackendValiditySchema(CoreModel):
    """§17.10's DomainPack-supplied validity schema, as core is allowed to know it.

        §17.10  Silicon Photonics SimulatorValidityV1 is a DomainPack-specific BackendValidity
                schema; core has no standalone SimulatorValidity table.

    Core knows that such a schema has an identity, a version and a list of fields that must be
    present and non-empty. It does not know, and must never learn, that one of those fields is
    called `mesh_config_ref`.
    """

    schema_id: str
    version: str
    domain: str
    #: Field names SIM-001 refuses a Run without. The DomainPack states them.
    required_fields: tuple[str, ...]
    #: Fields that may appear. Declared so an unexpected key is visible rather than silently
    #: carried -- a validity payload that grew a field nobody declared is a schema change nobody
    #: versioned.
    optional_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _requires_something(self) -> Self:
        if not self.required_fields:
            raise BackendValidityError(
                f"validity schema {self.ref} declares no required fields. SIM-001 refuses a run "
                "manifest missing any required validity field, so a schema that requires nothing "
                "makes the refusal unreachable -- which reads, in a test report, as compliance"
            )
        if overlap := sorted(set(self.required_fields) & set(self.optional_fields)):
            raise BackendValidityError(
                f"validity schema {self.ref} lists {overlap} as both required and optional"
            )
        return self

    @property
    def ref(self) -> str:
        return f"{self.domain}/{self.schema_id}@{self.version}"

    def violations(self, payload: dict[str, Any]) -> tuple[str, ...]:
        """Everything wrong with ``payload`` under this schema. Sorted, so messages are stable.

        Absent AND empty both count. A `convergence_status` of `""` is not a convergence status,
        and treating it as present is how a validity record becomes a field nobody filled in.
        """
        problems = [
            f"missing or empty required field {name!r}"
            for name in sorted(self.required_fields)
            if payload.get(name) in (None, "", (), [], {})
        ]
        known = set(self.required_fields) | set(self.optional_fields)
        problems += [f"undeclared field {name!r}" for name in sorted(set(payload) - known)]
        return tuple(problems)


class BackendValidityRegistry:
    """Resolve a validity schema by its reference, or fail closed.

    Same shape and same reason as `AuthorityPolicyRegistry`: a mapping that returned `None` would
    make "no such schema" and "the Run named a schema nobody registered" the same answer, and both
    would then read as "no validity was required".
    """

    def __init__(self) -> None:
        self._schemas: dict[str, BackendValiditySchema] = {}

    def register(self, schema: BackendValiditySchema) -> BackendValiditySchema:
        existing = self._schemas.get(schema.ref)
        if existing is not None and existing != schema:
            raise BackendValidityError(
                f"a different validity schema is already registered as {schema.ref}. Validity "
                "schemas are versioned so that a change gets a new version; replacing one in "
                "place would revalidate every past Run against rules it never saw"
            )
        self._schemas[schema.ref] = schema
        return schema

    def resolve(self, ref: str) -> BackendValiditySchema:
        found = self._schemas.get(ref)
        if found is None:
            raise BackendValidityError(
                f"no backend-validity schema is registered as {ref!r}. Core ships none -- §17.10 "
                "makes them DomainPack-supplied -- so there is nothing to fall back to, and an "
                "unvalidatable Run is not a validated one (SIM-001, AGT-011)"
            )
        return found

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))


class SimulationRequest(CoreModel):
    """What a backend is asked to do. Exactly §17.4's *input* half, and nothing else.

    Written from the manifest rather than from a solver API, so a backend that cannot be driven
    from these fields is a backend whose Runs would be missing manifest fields -- discovered here
    instead of at admission.
    """

    request_id: str
    project_id: str
    trace_id: str
    job_id: str
    capability_id: str

    input_artifacts: tuple[str, ...] = ()
    input_parameters: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str

    #: §10.7. `None` means the execution takes no external seat.
    resource_demand: ResourceDemand | None = None

    @model_validator(mode="after")
    def _conditions_are_versioned_and_present(self) -> Self:
        ConditionSchemaRef.parse(self.conditions_schema_version)
        if not self.conditions:
            raise SimulationContractError(
                f"simulation request {self.request_id} declares no conditions. A simulated result "
                "with no conditions is not reproducible evidence: nothing downstream can decide "
                "whether it is comparable to another run (EVI-005, §6.8)"
            )
        return self


class BackendExecution(CoreModel):
    """What a backend reports. Exactly §17.4's *output* half.

    ``series`` is the in-flight numerical payload handed to an extractor and is NOT part of the
    manifest: §17.4 stores arrays by reference (`numerical_array_refs`), because a manifest that
    inlined a bias sweep would be a manifest nobody can diff.
    """

    backend_id: str
    backend_version: str
    status: RunStatus
    #: SIM-001's own sentence, in the shape §17.10 permits core to see it.
    backend_validity_schema: str
    backend_validity: dict[str, Any] = Field(default_factory=dict)

    output_artifacts: tuple[str, ...] = ()
    numerical_array_refs: tuple[str, ...] = ()
    series: tuple[NumericalSeries, ...] = ()
    warnings: tuple[str, ...] = ()

    environment: dict[str, Any] = Field(default_factory=dict)
    code_provenance: str
    start_time: dt.datetime
    end_time: dt.datetime

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.end_time < self.start_time:
            raise SimulationContractError("execution ends before it starts")
        if self.status is RunStatus.SUCCEEDED and not self.output_artifacts:
            raise SimulationContractError(
                "a SUCCEEDED execution produced no artifacts; EVI-009 requires a SIMULATED "
                "attestation's run reference to trace to produced artifacts, so a successful run "
                "with nothing behind it cannot support one"
            )
        return self


@runtime_checkable
class SimulationBackend(Protocol):
    """§10.1's `simulation` backend type, provider-independent.

    Four members and no session, connection or script. A backend that needed an `eval_script` to
    be driven would not fit here, which is SIM-003 expressed as a type rather than as a review
    comment.
    """

    @property
    def backend_id(self) -> str: ...

    @property
    def backend_version(self) -> str: ...

    @property
    def validity_schema_ref(self) -> str:
        """Which `BackendValiditySchema` this backend's validity payloads conform to."""
        ...

    def execute(self, request: SimulationRequest) -> BackendExecution: ...


def validate_backend_validity(
    execution: BackendExecution, registry: BackendValidityRegistry
) -> None:
    """T-SIM-001's check: refuse an execution whose validity record is incomplete.

    Raises rather than returning findings, because there is one caller and one correct response.
    `SimulationRunner` calls it BEFORE minting the Run, so an execution with an unusable validity
    record never becomes a manifest -- "refused promotion to formal evidence" is stronger if the
    record never exists than if it exists and is filtered later.
    """
    schema = registry.resolve(execution.backend_validity_schema)
    problems = schema.violations(execution.backend_validity)
    if problems:
        raise BackendValidityError(
            f"backend {execution.backend_id} {execution.backend_version} produced a validity "
            f"record that does not satisfy {schema.ref}: {'; '.join(problems)}. SIM-001 refuses to "
            "promote such a run to formal evidence"
        )


def manifest_for(
    *,
    run_id: str,
    request: SimulationRequest,
    execution: BackendExecution,
    domain: str | None,
    reproducibility_manifest_hash: str,
) -> Run:
    """Assemble §17.4's Run from the request and the execution. No field is defaulted away.

    THE POINT OF DOING IT HERE rather than in each backend: `006a`'s audit finding was that
    `job_complete` persisted a subset of §17.4 and eight fields were silently replaced by column
    defaults. A backend assembling its own manifest would reintroduce exactly that, once per
    provider, and the providers would disagree about which fields matter.
    """
    return Run(
        run_id=run_id,
        job_id=request.job_id,
        project_id=request.project_id,
        capability_id=request.capability_id,
        backend_id=execution.backend_id,
        domain=domain,
        trace_id=request.trace_id,
        input_artifacts=request.input_artifacts,
        input_parameters=dict(request.input_parameters),
        conditions=dict(request.conditions),
        conditions_schema_version=request.conditions_schema_version,
        environment={
            **dict(execution.environment),
            # Recorded here rather than left to the backend: SIM-001 names the solver VERSION, and
            # a manifest that identified the backend but not its version would compare two runs of
            # different solvers as if they were the same.
            "backend_version": execution.backend_version,
        },
        code_provenance=execution.code_provenance,
        backend_validity={
            **dict(execution.backend_validity),
            # The schema the payload conforms to travels WITH the payload. Without it a reloaded
            # Run carries validity fields nobody can check, because which schema they satisfy is
            # not derivable from the values.
            "schema_ref": execution.backend_validity_schema,
        },
        status=execution.status,
        warnings=execution.warnings,
        output_artifacts=execution.output_artifacts,
        numerical_array_refs=execution.numerical_array_refs,
        start_time=execution.start_time,
        end_time=execution.end_time,
        reproducibility_manifest_hash=reproducibility_manifest_hash,
    )


__all__ = [
    "BackendExecution",
    "BackendValidityError",
    "BackendValidityRegistry",
    "BackendValiditySchema",
    "SimulationBackend",
    "SimulationContractError",
    "SimulationRequest",
    "manifest_for",
    "validate_backend_validity",
]
