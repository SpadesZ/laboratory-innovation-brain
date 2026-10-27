"""The device structure summary this pack offers (`research.structure`), and its screening norms.

STRUCTURE. From the parsed `DeviceProject` -- which refuses any field it does not declare -- an
explicit allowlist of design fields, each with its JSON pointer, its unit and the pack's words for
it. `solver_converges` is left out and says why: it is the normalized mock's switch for how a mock
solver behaves, not a property of the drawn device, and a real project export has no such field.
No rule is applied: the summary never says CONTINUOUS, DISCONTINUOUS, AGREES or DISAGREES.

SCREENING NORMS. The two solver-free design readers are the pack's screenable checks. What a sound
design shows on each is domain knowledge about every device -- every contact tied to metal with
full overlap; the extraction dividing by the drawn length -- and is the same for every case.
"""

from __future__ import annotations

from typing import Final

from lab_brain.core.models.screening import ScreeningNorm
from lab_brain.domains.silicon_photonics import diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.research.structure import StructureEntry, StructureSummary

STRUCTURE_REF: Final = "sp.device_structure@1.0.0"

UNCERTAINTY: Final = (
    "values are as drawn in the design project; they carry the file's precision and no "
    "measurement uncertainty, and the fabricated device may differ from the drawing"
)


def structure_summary(data: bytes, artifact_id: str, project_id: str) -> StructureSummary:
    """The structure summary of one stored device project. Raises `DesignError` if unreadable."""
    device = diagnosis.DeviceProject.parse(data)
    entries = [
        StructureEntry(path="/device_id", label="device identifier", value=device.device_id),
        StructureEntry(
            path="/drawn_length_um",
            label="drawn active length",
            value=device.drawn_length_um,
            unit="um",
        ),
        StructureEntry(
            path="/extraction_normalization_length_um",
            label="length the parameter extraction divides by",
            value=device.extraction_normalization_length_um,
            unit="um",
        ),
    ]
    for index, contact in enumerate(device.contacts):
        base = f"/contacts/{index}"
        entries.extend(
            (
                StructureEntry(
                    path=f"{base}/contact_id", label="contact identifier", value=contact.contact_id
                ),
                StructureEntry(
                    path=f"{base}/region",
                    label=f"contact {contact.contact_id}: doped region it lands on",
                    value=contact.region,
                ),
                StructureEntry(
                    path=f"{base}/via_to_metal",
                    label=f"contact {contact.contact_id}: via drawn to the metal layer",
                    value="true" if contact.via_to_metal else "false",
                ),
                StructureEntry(
                    path=f"{base}/overlap_nm",
                    label=f"contact {contact.contact_id}: via-to-diffusion overlap",
                    value=contact.overlap_nm,
                    unit="nm",
                ),
            )
        )
    entries.extend(
        (
            StructureEntry(
                path="/access_mesh_max_edge_nm",
                label="simulation mesh: largest element edge in the access region",
                value=device.access_mesh_max_edge_nm,
                unit="nm",
            ),
            StructureEntry(
                path="/rib_doping_cm3",
                label="rib design doping",
                value=device.rib_doping_cm3,
                unit="cm^-3",
            ),
            StructureEntry(
                path="/counterdoping_cm3",
                label="counter-doping in the rib",
                value=device.counterdoping_cm3,
                unit="cm^-3",
            ),
        )
    )
    return StructureSummary(
        summary_ref=STRUCTURE_REF,
        project_id=project_id,
        source_artifact_id=artifact_id,
        entries=tuple(entries),
        excluded_fields=(
            "/solver_converges: the normalized mock's switch for mock-solver behaviour, not a "
            "property of the drawn device",
            "/format: the file format tag",
        ),
        uncertainty=UNCERTAINTY,
    )


def screening_norms() -> dict[str, ScreeningNorm]:
    return {
        sp.CAP_INSPECT_CONNECTIVITY: ScreeningNorm(
            capability_id=sp.CAP_INSPECT_CONNECTIVITY,
            reference_outcomes={sp.OBS_CONNECTIVITY: diagnosis.CONTINUOUS},
            purpose=(
                "a sound design ties every contact to metal with full overlap; a broken access "
                "path is invisible in an Rs table"
            ),
        ),
        sp.CAP_EXTRACTION_CONSISTENCY: ScreeningNorm(
            capability_id=sp.CAP_EXTRACTION_CONSISTENCY,
            reference_outcomes={sp.OBS_NORMALIZATION: diagnosis.AGREES},
            purpose=(
                "a sound extraction divides by the drawn length; a wrong basis scales every "
                "per-length value"
            ),
        ),
    }


__all__ = ["STRUCTURE_REF", "UNCERTAINTY", "screening_norms", "structure_summary"]
