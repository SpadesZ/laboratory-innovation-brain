"""Deterministic stand-ins for VS-SP-001's two solver runs. **Not Lumerical.** (TST-001, R-1)

    DOM-SP-TOOL-001  run_charge_dc_sweep     carrier profiles, bias points, convergence
    DOM-SP-TOOL-003  run_mesh_sensitivity    mesh variants, extracted metric, stability delta

WHAT THESE ARE. `SimulationBackend`s that read the `DeviceProject` a request names, compute a
declared analytic stand-in, write the raw result through the `RunOutputSink` (so the Run cites the
bytes the execution emitted), and report a complete `simulator_validity` record. They exist to
prove the contract and to give the benchmark a backend whose answer follows from the device's
geometry and configuration -- never from a label of what is wrong with it.

WHAT THESE ARE NOT, stated plainly for the same reason `mock.py` states it:

    - not Lumerical CHARGE; no `lumapi`, no licence seat is held (a seat is still DEMANDED and
      leased through §10.7's broker, because the capability declares one and the contention path
      is part of what VS-SP-001 exercises);
    - their numbers are not physics. The mesh model makes the extracted Rs drift once the access
      mesh edge exceeds a resolution length; the DC model reports the net free-carrier density
      left after counter-doping. Both are chosen so a rule's threshold is decided by the device
      description, legibly;
    - every Run they produce says `solver_id = mock.charge.*`.

A real provider replaces these behind the same `SimulationBackend` contract; the licensed replay
TST-001 asks for is not available in this environment and is not claimed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any, ClassVar, Final

from lab_brain.core.canonical_json import canonical_bytes
from lab_brain.core.models.identifiers import content_hash_for
from lab_brain.core.models.job import RunStatus
from lab_brain.domains.silicon_photonics import backend_validity
from lab_brain.domains.silicon_photonics.diagnosis import OUTPUT_MEDIA_TYPE, DeviceProject
from lab_brain.tools.outputs import RunOutputSink
from lab_brain.tools.simulation import BackendExecution, SimulationRequest

MESH_BACKEND_ID: Final = "mock.charge.mesh"
DC_BACKEND_ID: Final = "mock.charge.dc"
MOCK_VERSION: Final = "0.1.0"

#: The mock's Rs per unit length for a well-resolved access region, ohm.um. A round number of this
#: mock, measured from nothing.
RS_RESOLVED: Final = Decimal("1200")
#: Mesh edge below which the mock's access region is resolved, nanometres.
RESOLUTION_EDGE_NM: Final = Decimal("10")
#: How strongly an unresolved mesh inflates the mock's extracted Rs, per resolution length.
ARTIFACT_GAIN: Final = Decimal("0.5")
#: The DC sweep's bias points, volts (reverse bias negative), as decimal strings.
DC_BIAS_POINTS: Final = ("0", "-1", "-2", "-3")


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.001")))


class _MockSolver:
    backend_id: ClassVar[str]
    backend_version: ClassVar[str] = MOCK_VERSION
    validity_schema_ref: ClassVar[str] = backend_validity.SCHEMA_REF
    duration_s: ClassVar[int]

    def __init__(self, *, sink: RunOutputSink, now: Callable[[], dt.datetime]) -> None:
        self._sink = sink
        self._now = now

    def _result(self, project: DeviceProject) -> dict[str, Any]:
        raise NotImplementedError

    def execute(self, request: SimulationRequest) -> BackendExecution:
        if len(request.input_artifacts) != 1:
            raise ValueError(f"{self.backend_id} solves exactly one device project")
        source = request.input_artifacts[0]
        started = self._now()
        project = DeviceProject.parse(self._sink.read(source))
        converged = project.solver_converges
        status = backend_validity.CONVERGED if converged else backend_validity.NOT_CONVERGED
        payload = {
            "solver_id": self.backend_id,
            "solver_version": self.backend_version,
            "project_artifact_id": source,
            "device_id": project.device_id,
            "convergence_status": status,
            **self._result(project),
        }
        output = self._sink.emit(
            project_id=request.project_id,
            media_type=OUTPUT_MEDIA_TYPE,
            data=canonical_bytes(payload),
        )
        return BackendExecution(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            # An execution that ran and did not converge still SUCCEEDED as an execution; its
            # authority is lowered by `backend_validity.fidelity_for` (SIM-002), as in `mock.py`.
            status=RunStatus.SUCCEEDED,
            backend_validity_schema=self.validity_schema_ref,
            backend_validity={
                "solver_id": self.backend_id,
                "solver_version": self.backend_version,
                "project_hash": content_hash_for(source),
                "mesh_config_ref": source,
                "bias_config_ref": source,
                "convergence_status": status,
                "iterations": 1,
            },
            output_artifacts=(output,),
            warnings=() if converged else ("solver did not converge",),
            environment={"provider": "mock", "vendor_sdk": "none"},
            code_provenance=f"{self.backend_id}@{self.backend_version}",
            start_time=started,
            end_time=started + dt.timedelta(seconds=self.duration_s),
        )


class MockMeshSensitivityBackend(_MockSolver):
    """Two mesh variants: the project's access-region edge, and that edge halved."""

    backend_id: ClassVar[str] = MESH_BACKEND_ID
    duration_s: ClassVar[int] = 240

    @staticmethod
    def rs_at(edge_nm: Decimal) -> Decimal:
        excess = max(Decimal(0), edge_nm - RESOLUTION_EDGE_NM) / RESOLUTION_EDGE_NM
        return RS_RESOLVED * (Decimal(1) + ARTIFACT_GAIN * excess)

    def _result(self, project: DeviceProject) -> dict[str, Any]:
        edge = Decimal(project.access_mesh_max_edge_nm)
        refined = edge / 2
        return {
            "metric": "rs_per_length",
            "unit": "ohm.um",
            "variants": [
                {"max_edge_nm": _q(edge), "rs_ohm_um": _q(self.rs_at(edge))},
                {"max_edge_nm": _q(refined), "rs_ohm_um": _q(self.rs_at(refined))},
            ],
        }


class MockChargeDcBackend(_MockSolver):
    """A reverse-bias DC sweep reporting the access region's net free-carrier density."""

    backend_id: ClassVar[str] = DC_BACKEND_ID
    duration_s: ClassVar[int] = 600

    def _result(self, project: DeviceProject) -> dict[str, Any]:
        rib = Decimal(project.rib_doping_cm3)
        counter = Decimal(project.counterdoping_cm3)
        net = max(Decimal(0), rib - counter)
        return {
            "bias_points_v": list(DC_BIAS_POINTS),
            "rib_doping_cm3": str(rib),
            "counterdoping_cm3": str(counter),
            "net_carrier_cm3": [str(net) for _ in DC_BIAS_POINTS],
        }


__all__ = [
    "DC_BACKEND_ID",
    "MESH_BACKEND_ID",
    "MOCK_VERSION",
    "MockChargeDcBackend",
    "MockMeshSensitivityBackend",
]
