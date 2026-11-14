"""VS-SP-001's design model, its solver-free readers, and the rules that turn stored output into
outcomes (§25.1, §25.2, DOM-SP-001).

    §25.1  H1 access/contact discontinuity | H2 mesh/convergence artifact |
           H3 contact/material/normalization model issue
           -> connectivity inspection / mesh sensitivity / model check
    §10.2.1 inspect_*  reads geometry/config/state without solving; produces Observation.

THE DEVICE PROJECT IS A NORMALIZED MOCK EQUIVALENT, AND SAYS SO. §25.1's input is "Existing CHARGE
project / normalized mock equivalent". No CHARGE project exists in this repository (risk R-1), so
the input is `DeviceProject`: a small, typed, content-addressed JSON description of a PN phase
shifter -- drawn length, contacts, extraction normalization, access-region mesh, doping. Every field
is one a real project export carries; none is a label of what is wrong with the device. The
readers and the mock solvers compute from these fields, so a fault is visible only as the geometry
or configuration that would cause it.

READERS READ; RULES CLASSIFY; BOTH ARE VERSIONED. A reader (`ContactConnectivityReader`,
`NormalizationBasisReader`) executes as a local, solver-free backend and writes the raw facts it
read -- contacts and their overlaps, the two lengths -- as the Run's output artifact. It decides
nothing. The rule (`classify_*`) reads those STORED bytes and names the outcome of the declared
OutcomeSpace, with its threshold stated here and its `rule_id@version` recorded on the evidence. A
threshold change is a rule version bump, so evidence produced under the old one stays identifiable
(§6.18) -- DOM-SP-001's "rule/validator 版本必須記錄" applied to diagnosis.

WHY A LOCAL READER STILL PRODUCES A RUN. EPI-002 makes a confirmed root cause trace to a Run and
an Artifact, and VS-SP-001's point is that the cheapest check -- the inspection -- is often the one
that confirms. So the reading executes as a Job whose Run records the reader's identity and
version, the
input project's hash and the rule set, through the same execution seam every backend uses. The
`inspect_*` DESCRIPTOR still names no capability and no seat: it is not backend-bound in §10.2.1's
sense (no solver, no licence), it is merely recorded.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any, ClassVar, Final, Literal

from pydantic import Field

from lab_brain.core.canonical_json import canonical_bytes
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.identifiers import content_hash_for
from lab_brain.core.models.job import RunStatus
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN
from lab_brain.tools.outputs import RunOutputSink
from lab_brain.tools.simulation import BackendExecution, BackendValiditySchema, SimulationRequest

DEVICE_PROJECT_FORMAT: Final = "sp.device_project@1"
DEVICE_PROJECT_MEDIA_TYPE: Final = "application/vnd.lab-brain.sp-device-project+json"
OUTPUT_MEDIA_TYPE: Final = "application/json"

#: The validity schema a solver-free reading's Run carries (SIM-001's discipline, for a reader).
INSPECTION_VALIDITY_ID: Final = "design_inspection_validity"
INSPECTION_VALIDITY_VERSION: Final = "1.0.0"
INSPECTION_VALIDITY_REF: Final = f"{DOMAIN}/{INSPECTION_VALIDITY_ID}@{INSPECTION_VALIDITY_VERSION}"

# -- outcomes ----------------------------------------------------------------------------------

CONTINUOUS: Final = "CONTINUOUS"
DISCONTINUOUS: Final = "DISCONTINUOUS"
AGREES: Final = "AGREES"
DISAGREES: Final = "DISAGREES"
STABLE: Final = "STABLE"
UNSTABLE: Final = "UNSTABLE"
NOMINAL: Final = "NOMINAL"
COMPENSATED: Final = "COMPENSATED"
ELEVATED: Final = "ELEVATED"

# -- rules: thresholds are the rule; changing one is a version bump ----------------------------

#: A contact whose via-to-diffusion overlap is below this does not carry the access current.
CONNECTIVITY_RULE: Final = "sp.rule.contact_connectivity@1.0.0"
MIN_CONTACT_OVERLAP_NM: Final = Decimal("100")
#: Relative disagreement between the extraction's normalization length and the drawn length.
NORMALIZATION_RULE: Final = "sp.rule.normalization_basis@1.0.0"
NORMALIZATION_TOLERANCE: Final = Decimal("0.01")
#: Relative change of extracted Rs between the two mesh variants.
MESH_RULE: Final = "sp.rule.mesh_stability@1.0.0"
MESH_STABILITY_TOLERANCE: Final = Decimal("0.05")
#: Counter-doping as a fraction of the rib's design doping.
CARRIER_RULE: Final = "sp.rule.carrier_compensation@1.0.0"
COMPENSATION_THRESHOLD: Final = Decimal("0.3")


class DesignError(ValueError):
    """A device project or a stored reader output is not what the rule expects."""


class ContactSpec(CoreModel):
    contact_id: str
    region: str
    via_to_metal: bool
    #: Via-to-diffusion overlap, nanometres, decimal string.
    overlap_nm: str


class DeviceProject(CoreModel):
    """The normalized mock equivalent of a CHARGE project. See the module docstring."""

    format: Literal["sp.device_project@1"] = DEVICE_PROJECT_FORMAT
    device_id: str
    drawn_length_um: str
    contacts: tuple[ContactSpec, ...] = Field(min_length=2)
    extraction_normalization_length_um: str
    access_mesh_max_edge_nm: str
    rib_doping_cm3: str
    counterdoping_cm3: str
    solver_converges: bool = True

    @classmethod
    def parse(cls, data: bytes) -> DeviceProject:
        try:
            return cls.model_validate(json.loads(data.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as bad:
            raise DesignError(f"not a {DEVICE_PROJECT_FORMAT} project: {bad}") from bad

    def to_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    def conditions(self) -> dict[str, str]:
        """The diagnosis conditions this device fixes (`pn_junction_device@1.0.0`)."""
        return {"device_length_um": self.drawn_length_um}


def inspection_validity_schema() -> BackendValiditySchema:
    return BackendValiditySchema(
        schema_id=INSPECTION_VALIDITY_ID,
        version=INSPECTION_VALIDITY_VERSION,
        domain=DOMAIN,
        required_fields=("reader_id", "reader_version", "project_hash", "rule_ref"),
        optional_fields=("notes",),
    )


def _decimal(value: Any, what: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as bad:
        raise DesignError(f"{what}={value!r} is not a decimal") from bad


def _read_json(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as bad:
        raise DesignError(f"stored output is not JSON: {bad}") from bad
    if not isinstance(payload, dict):
        raise DesignError("stored output is not a JSON object")
    return payload


# -- the readers ---------------------------------------------------------------------------------


class _DesignReader:
    """A solver-free local backend: read the project, write the raw facts, decide nothing."""

    backend_id: ClassVar[str]
    backend_version: ClassVar[str] = "1.0.0"
    validity_schema_ref: ClassVar[str] = INSPECTION_VALIDITY_REF
    rule_ref: ClassVar[str]

    def __init__(self, *, sink: RunOutputSink, now: Callable[[], dt.datetime]) -> None:
        self._sink = sink
        self._now = now

    def _facts(self, project: DeviceProject) -> dict[str, Any]:
        raise NotImplementedError

    def execute(self, request: SimulationRequest) -> BackendExecution:
        if len(request.input_artifacts) != 1:
            raise DesignError(
                f"{self.backend_id} reads exactly one device project; got "
                f"{list(request.input_artifacts)}"
            )
        source = request.input_artifacts[0]
        started = self._now()
        project = DeviceProject.parse(self._sink.read(source))
        payload = {
            "reader_id": self.backend_id,
            "reader_version": self.backend_version,
            "project_artifact_id": source,
            "device_id": project.device_id,
            **self._facts(project),
        }
        output = self._sink.emit(
            project_id=request.project_id,
            media_type=OUTPUT_MEDIA_TYPE,
            data=canonical_bytes(payload),
        )
        return BackendExecution(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            status=RunStatus.SUCCEEDED,
            backend_validity_schema=self.validity_schema_ref,
            backend_validity={
                "reader_id": self.backend_id,
                "reader_version": self.backend_version,
                "project_hash": content_hash_for(source),
                "rule_ref": self.rule_ref,
            },
            output_artifacts=(output,),
            environment={"execution": "local", "solver": "none"},
            code_provenance=f"{self.backend_id}@{self.backend_version}",
            start_time=started,
            end_time=self._now(),
        )


class ContactConnectivityReader(_DesignReader):
    """DOM-SP-TOOL-005's backend: contacts, their via and overlap, and the connected regions."""

    backend_id: ClassVar[str] = "sp.local.contact_connectivity_reader"
    rule_ref: ClassVar[str] = CONNECTIVITY_RULE

    def _facts(self, project: DeviceProject) -> dict[str, Any]:
        return {
            "contacts": [
                {
                    "contact_id": c.contact_id,
                    "region": c.region,
                    "via_to_metal": c.via_to_metal,
                    "overlap_nm": c.overlap_nm,
                }
                for c in sorted(project.contacts, key=lambda c: c.contact_id)
            ],
            # The regions a via actually ties to metal: the drawn access path, as read.
            "connected_regions": sorted(c.region for c in project.contacts if c.via_to_metal),
        }


class NormalizationBasisReader(_DesignReader):
    """DOM-SP-TOOL-011's backend: the drawn length and the length the extraction divides by."""

    backend_id: ClassVar[str] = "sp.local.normalization_basis_reader"
    rule_ref: ClassVar[str] = NORMALIZATION_RULE

    def _facts(self, project: DeviceProject) -> dict[str, Any]:
        return {
            "drawn_length_um": project.drawn_length_um,
            "normalization_length_um": project.extraction_normalization_length_um,
        }


# -- the rules -------------------------------------------------------------------------------------


def classify_connectivity(data: bytes) -> tuple[str, dict[str, Any]]:
    payload = _read_json(data)
    violations = sorted(
        str(c["contact_id"])
        for c in payload.get("contacts", [])
        if not c.get("via_to_metal")
        or _decimal(c.get("overlap_nm"), "overlap_nm") < MIN_CONTACT_OVERLAP_NM
    )
    if not payload.get("contacts"):
        raise DesignError("connectivity output lists no contacts")
    outcome = DISCONTINUOUS if violations else CONTINUOUS
    return outcome, {"violations": violations, "min_overlap_nm": str(MIN_CONTACT_OVERLAP_NM)}


def classify_normalization(data: bytes) -> tuple[str, dict[str, Any]]:
    payload = _read_json(data)
    drawn = _decimal(payload.get("drawn_length_um"), "drawn_length_um")
    used = _decimal(payload.get("normalization_length_um"), "normalization_length_um")
    if drawn <= 0:
        raise DesignError("drawn length must be positive")
    mismatch = abs(used - drawn) / drawn
    outcome = DISAGREES if mismatch > NORMALIZATION_TOLERANCE else AGREES
    return outcome, {"relative_mismatch": str(mismatch.normalize()), "tolerance": "0.01"}


def classify_mesh(data: bytes) -> tuple[str, dict[str, Any]]:
    payload = _read_json(data)
    variants = payload.get("variants", [])
    if len(variants) != 2:
        raise DesignError("a mesh sensitivity output compares exactly two variants")
    coarse = _decimal(variants[0]["rs_ohm_um"], "rs_ohm_um")
    fine = _decimal(variants[1]["rs_ohm_um"], "rs_ohm_um")
    if fine <= 0:
        raise DesignError("refined Rs must be positive")
    delta = abs(coarse - fine) / fine
    outcome = UNSTABLE if delta > MESH_STABILITY_TOLERANCE else STABLE
    return outcome, {"stability_delta": str(delta.quantize(Decimal("0.0001")))}


def classify_carrier(data: bytes) -> tuple[str, dict[str, Any]]:
    payload = _read_json(data)
    rib = _decimal(payload.get("rib_doping_cm3"), "rib_doping_cm3")
    counter = _decimal(payload.get("counterdoping_cm3"), "counterdoping_cm3")
    if rib <= 0:
        raise DesignError("rib doping must be positive")
    ratio = counter / rib
    outcome = COMPENSATED if ratio > COMPENSATION_THRESHOLD else NOMINAL
    return outcome, {"compensation_ratio": str(ratio.quantize(Decimal("0.0001")))}


#: rule ref -> classifier. What a workflow names; what an Attestation records.
RULES: Final[Mapping[str, Callable[[bytes], tuple[str, dict[str, Any]]]]] = {
    CONNECTIVITY_RULE: classify_connectivity,
    NORMALIZATION_RULE: classify_normalization,
    MESH_RULE: classify_mesh,
    CARRIER_RULE: classify_carrier,
}


__all__ = [
    "AGREES",
    "CARRIER_RULE",
    "COMPENSATED",
    "CONNECTIVITY_RULE",
    "CONTINUOUS",
    "DEVICE_PROJECT_FORMAT",
    "DEVICE_PROJECT_MEDIA_TYPE",
    "DISAGREES",
    "DISCONTINUOUS",
    "ELEVATED",
    "INSPECTION_VALIDITY_REF",
    "MESH_RULE",
    "NOMINAL",
    "NORMALIZATION_RULE",
    "RULES",
    "STABLE",
    "UNSTABLE",
    "ContactConnectivityReader",
    "ContactSpec",
    "DesignError",
    "DeviceProject",
    "NormalizationBasisReader",
    "classify_carrier",
    "classify_connectivity",
    "classify_mesh",
    "classify_normalization",
    "inspection_validity_schema",
]
