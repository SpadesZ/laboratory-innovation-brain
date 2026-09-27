"""What the SiPh pack contributes to VS-SP-001, checked without a database (§25, DOM-SP-001, EXT-001).

§25.2   typed tools for the first vertical: DOM-SP-TOOL-001/003/005 (+011), each through the
        registry, each executing as a recorded Job/Run.
§25.4   raw artifacts 被 hash 且在 parsing 前已 durably 保存; mock/real backend 都走 typed contract.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from lab_brain.core.authority import AuthorityPolicyRegistry
from lab_brain.core.models.enums import AuthorityComparison, EpistemicType
from lab_brain.core.models.identifiers import content_hash_for
from lab_brain.domains.silicon_photonics import backend_validity, diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.authority_policy import (
    MEAS_CALIBRATED,
    SIM_COARSE,
    SIM_STANDARD,
    SIM_VALIDATION,
    SiliconPhotonicsAuthorityPolicy,
)
from lab_brain.domains.silicon_photonics.vertical_tools import (
    CONNECTIVITY_TOOL_ID,
    ContactConnectivityRequest,
    DesignExecutionResult,
)
from lab_brain.tool_providers.lumerical.mock_vertical import (
    MockChargeDcBackend,
    MockMeshSensitivityBackend,
)
from lab_brain.tools.outputs import InMemoryRunOutputSink
from lab_brain.tools.routing import CapabilityRoutedRunner
from lab_brain.tools.simulation import SimulationContractError, SimulationRequest
from lab_brain.verification.workflows import (
    WorkflowError,
    WorkflowRegistry,
    WorkflowResult,
    WorkflowStatus,
)
from tests.vertical_fixtures import device_for, load_fixture
from tests.vertical_units import registries

T0 = dt.datetime(2026, 9, 27, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:pack"


def _device(**overrides: object) -> diagnosis.DeviceProject:
    fx = load_fixture()
    return diagnosis.DeviceProject.model_validate({**fx["nominal_device"], **overrides})


def _request(capability_id: str, artifact_id: str) -> SimulationRequest:
    return SimulationRequest(
        request_id="req:1",
        project_id=PROJECT,
        trace_id="trc:1",
        episode_id="epi:1",
        job_id="job:1",
        capability_id=capability_id,
        input_artifacts=(artifact_id,),
        conditions={"device_length_um": "500"},
        conditions_schema_version=sp.DEVICE_SCHEMA_REF,
    )


def _execute(backend_type, device, capability_id):  # type: ignore[no-untyped-def]
    sink = InMemoryRunOutputSink()
    source = sink.put(project_id=PROJECT, data=device.to_bytes())
    execution = backend_type(sink=sink, now=lambda: T0).execute(_request(capability_id, source))
    return sink, source, execution


@pytest.mark.parametrize(
    ("case_id", "backend", "capability", "rule", "expected"),
    [
        (
            "contact-open-via",
            diagnosis.ContactConnectivityReader,
            sp.CAP_INSPECT_CONNECTIVITY,
            diagnosis.CONNECTIVITY_RULE,
            "DISCONTINUOUS",
        ),
        (
            "contact-thin-overlap",
            diagnosis.ContactConnectivityReader,
            sp.CAP_INSPECT_CONNECTIVITY,
            diagnosis.CONNECTIVITY_RULE,
            "DISCONTINUOUS",
        ),
        (
            "mesh-coarse-access",
            diagnosis.ContactConnectivityReader,
            sp.CAP_INSPECT_CONNECTIVITY,
            diagnosis.CONNECTIVITY_RULE,
            "CONTINUOUS",
        ),
        (
            "normalization-taper",
            diagnosis.NormalizationBasisReader,
            sp.CAP_EXTRACTION_CONSISTENCY,
            diagnosis.NORMALIZATION_RULE,
            "DISAGREES",
        ),
        (
            "contact-open-via",
            diagnosis.NormalizationBasisReader,
            sp.CAP_EXTRACTION_CONSISTENCY,
            diagnosis.NORMALIZATION_RULE,
            "AGREES",
        ),
        (
            "mesh-coarse-access",
            MockMeshSensitivityBackend,
            sp.CAP_MESH_SENSITIVITY,
            diagnosis.MESH_RULE,
            "UNSTABLE",
        ),
        (
            "dopant-counterdoped",
            MockMeshSensitivityBackend,
            sp.CAP_MESH_SENSITIVITY,
            diagnosis.MESH_RULE,
            "STABLE",
        ),
        (
            "dopant-counterdoped",
            MockChargeDcBackend,
            sp.CAP_CHARGE_DC,
            diagnosis.CARRIER_RULE,
            "COMPENSATED",
        ),
        (
            "mesh-coarse-access",
            MockChargeDcBackend,
            sp.CAP_CHARGE_DC,
            diagnosis.CARRIER_RULE,
            "NOMINAL",
        ),
    ],
)
def test_the_outcome_follows_from_the_device_description_through_the_stored_bytes(
    case_id, backend, capability, rule, expected
):  # type: ignore[no-untyped-def]
    """The backend writes raw facts; the rule reads the STORED bytes back by id and classifies."""
    fx = load_fixture()
    device = device_for(fx, next(c for c in fx["cases"] if c["case_id"] == case_id))
    sink, source, execution = _execute(backend, device, capability)
    (output,) = execution.output_artifacts
    stored = sink.read(output)
    assert content_hash_for(output).endswith(__import__("hashlib").sha256(stored).hexdigest())
    assert sink.present_in(output, PROJECT)
    outcome, _detail = diagnosis.RULES[rule](stored)
    assert outcome == expected
    # The raw output names the project it read and never names a verdict.
    payload = json.loads(stored)
    assert payload["project_artifact_id"] == source
    assert expected not in json.dumps(payload)


def test_a_reader_is_recorded_as_a_solver_free_execution_and_a_mock_never_claims_a_vendor():
    _, source, reading = _execute(
        diagnosis.ContactConnectivityReader, _device(), sp.CAP_INSPECT_CONNECTIVITY
    )
    assert reading.backend_validity_schema == diagnosis.INSPECTION_VALIDITY_REF
    assert reading.backend_validity["project_hash"] == content_hash_for(source)
    assert reading.backend_validity["rule_ref"] == diagnosis.CONNECTIVITY_RULE
    assert reading.environment == {"execution": "local", "solver": "none"}
    _, _, solve = _execute(MockChargeDcBackend, _device(), sp.CAP_CHARGE_DC)
    assert solve.backend_validity["solver_id"].startswith("mock.charge.")
    assert "CHARGE" not in solve.backend_validity["solver_id"]
    assert solve.environment["vendor_sdk"] == "none"


def test_a_solve_that_does_not_converge_is_recorded_and_earns_only_coarse_authority():
    """SIM-002 in VS-SP-001: the capability declares SIM_STANDARD at best; the Run decides."""
    _, _, solve = _execute(
        MockMeshSensitivityBackend, _device(solver_converges=False), sp.CAP_MESH_SENSITIVITY
    )
    assert solve.backend_validity["convergence_status"] == backend_validity.NOT_CONVERGED
    assert backend_validity.fidelity_for(dict(solve.backend_validity), SIM_STANDARD) == SIM_COARSE
    _, _, converged = _execute(MockMeshSensitivityBackend, _device(), sp.CAP_MESH_SENSITIVITY)
    assert backend_validity.fidelity_for(dict(converged.backend_validity), SIM_STANDARD) == (
        SIM_STANDARD
    )


def test_the_rules_version_their_thresholds_and_refuse_malformed_output():
    assert Decimal("100") == diagnosis.MIN_CONTACT_OVERLAP_NM
    for rule in diagnosis.RULES:
        name, _, version = rule.rpartition("@")
        assert name.startswith("sp.rule.") and version == "1.0.0"
    with pytest.raises(diagnosis.DesignError):
        diagnosis.classify_mesh(b'{"variants": []}')
    with pytest.raises(diagnosis.DesignError):
        diagnosis.classify_connectivity(b"not json")
    with pytest.raises(diagnosis.DesignError):
        diagnosis.DeviceProject.parse(b'{"format": "something else"}')


def test_design_inspection_ranks_with_validation_fidelity_and_never_against_a_measurement():
    """`auth:silicon_photonics@1.1.0` passes the registry's order laws; 1.0.0 is unchanged."""
    registry = AuthorityPolicyRegistry()
    registry.register(SiliconPhotonicsAuthorityPolicy())
    registry.register(sp.VerticalAuthorityPolicy())
    v11, v10 = sp.VerticalAuthorityPolicy(), SiliconPhotonicsAuthorityPolicy()
    assert v11.compare(sp.DESIGN_INSPECTION, SIM_VALIDATION) is AuthorityComparison.EQUIVALENT
    assert v11.meets(SIM_STANDARD, sp.DESIGN_INSPECTION)
    assert not v11.meets(SIM_STANDARD, SIM_COARSE)
    assert v11.compare(sp.DESIGN_INSPECTION, MEAS_CALIBRATED) is AuthorityComparison.INCOMPARABLE
    for a in v10.authority_classes:
        for b in v10.authority_classes:
            assert v11.compare(a, b) is v10.compare(a, b), (a, b)


def test_the_pack_registers_its_capabilities_tools_spaces_validator_and_workflows():
    regs = registries()
    for capability_id in (
        sp.CAP_INSPECT_CONNECTIVITY,
        sp.CAP_EXTRACTION_CONSISTENCY,
        sp.CAP_MESH_SENSITIVITY,
        sp.CAP_CHARGE_DC,
        sp.CAP_FOURPOINT_PROBE,
        sp.CAP_FABRICATE_SPLIT,
    ):
        assert regs.capabilities.resolve(capability_id).domain == "silicon_photonics"
    assert regs.capabilities.resolve(sp.CAP_FABRICATE_SPLIT).irreversible
    assert regs.workflows.registered() == tuple(
        sorted(
            (
                sp.CAP_CHARGE_DC,
                sp.CAP_EXTRACTION_CONSISTENCY,
                sp.CAP_INSPECT_CONNECTIVITY,
                sp.CAP_MESH_SENSITIVITY,
            )
        )
    )
    # A person must act for these two: there is no workflow to pretend with.
    assert regs.workflows.resolve(sp.CAP_FOURPOINT_PROBE) is None
    assert regs.workflows.resolve(sp.CAP_FABRICATE_SPLIT) is None
    for space in sp.outcome_spaces():
        assert (
            regs.disagreement_metrics.for_space(space.outcome_space_id, space.version) is not None
        )
    assert regs.tools.descriptor(CONNECTIVITY_TOOL_ID).capability_id is None
    assert regs.tools.descriptor(CONNECTIVITY_TOOL_ID).cost_contract == sp.COST_DESIGN_INSPECTION


def test_a_workflow_is_refused_for_an_unknown_capability_or_tool():
    regs = registries()
    stray = WorkflowRegistry()

    class Stray:
        capability_id = "cap:sp.nobody_declared_this"
        tool_ids = (CONNECTIVITY_TOOL_ID,)

        def execute(self, context):  # type: ignore[no-untyped-def]
            raise AssertionError

    stray.register(Stray())
    with pytest.raises(WorkflowError, match="no pack registered as a Capability"):
        stray.verify(regs.capabilities, regs.tools)

    class NoTool(Stray):
        capability_id = sp.CAP_INSPECT_CONNECTIVITY
        tool_ids = ("DOM-SP-TOOL-099",)

    other = WorkflowRegistry()
    other.register(NoTool())
    with pytest.raises(WorkflowError, match="not a registered typed tool"):
        other.verify(regs.capabilities, regs.tools)

    class Untyped(Stray):
        tool_ids = ()

    with pytest.raises(WorkflowError, match="declares no tools"):
        WorkflowRegistry().register(Untyped())
    with pytest.raises(WorkflowError, match="must name its Run"):
        WorkflowResult(status=WorkflowStatus.EXECUTED)


def test_a_request_cannot_wrap_another_capabilitys_execution_and_a_result_is_one_thing():
    sink = InMemoryRunOutputSink()
    source = sink.put(project_id=PROJECT, data=_device().to_bytes())
    with pytest.raises(ValueError, match="capability"):
        ContactConnectivityRequest(
            project_id=PROJECT,
            trace_id="trc:1",
            episode_id="epi:1",
            execution=_request(sp.CAP_CHARGE_DC, source),
        )
    with pytest.raises(ValueError, match="exactly one"):
        DesignExecutionResult(tool_id=CONNECTIVITY_TOOL_ID, tool_version="1.0.0")


def test_the_routed_runner_refuses_a_capability_with_no_backend():
    runner = CapabilityRoutedRunner(
        backends={},
        jobs=None,
        broker=None,
        validity=None,
        now=lambda: T0,
        domain=None,  # type: ignore[arg-type]
    )
    with pytest.raises(SimulationContractError, match="no backend is wired"):
        runner(_request(sp.CAP_CHARGE_DC, "art:sha256:" + "0" * 64))


def test_observed_outcomes_are_never_inferred():
    """A workflow executes code, not a model: its outcomes are OBSERVED or SIMULATED (EVI-003)."""
    from lab_brain.domains.silicon_photonics.vertical_tools import workflows

    for workflow in workflows():
        assert workflow._epistemic in {EpistemicType.OBSERVED, EpistemicType.SIMULATED}
