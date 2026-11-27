"""SimulatorValidityV1 — the fields SIM-001 refuses a run manifest without (§17.10, §10.3).

    SIM-001    每次 CHARGE run 必須保存 solver version、project hash、mesh/bias/config、
               exit/convergence status。
    T-SIM-001  run manifest 缺 solver/project/conditions/validity 任一必要欄位即拒絕升級正式
               evidence。
    §17.10     Silicon Photonics SimulatorValidityV1 is a DomainPack-specific BackendValidity
               schema; core has no standalone SimulatorValidity table.

THIS FILE IS WHERE THE FOUR NAMES IN SIM-001 ARE ALLOWED TO EXIST. §17.4 forbids core from
hard-coding `solver_settings` / `mesh_convergence` / `calibration`, and §24.1 puts "mesh/solver/
calibration validity rules" in this pack's column. So core carries a `BackendValiditySchema` with a
`required_fields` tuple and no opinion about its contents, and the contents are here.

MESH AND BIAS CONFIG ARE *REFERENCES*, NOT INLINE SETTINGS. §17.4 stores arrays by reference for
the same reason: a validity record that inlined a mesh definition would be a record nobody can
diff, and the mesh itself is an input artifact with its own content hash. `mesh_config_ref` and
`bias_config_ref` point at artifacts; what they point at is reproducible because artifacts are
content-addressed (ART-001).

`convergence_status` IS REQUIRED AND MAY SAY "did not converge". SIM-001 asks for the *exit /
convergence status* to be saved, not for it to be good -- a non-converged run is a real execution
whose manifest §6.10 needs. What is refused is a manifest that does not say either way, because a
result whose convergence is unknown cannot be given an authority class honestly.
"""

from __future__ import annotations

from typing import Final

from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN
from lab_brain.tools.simulation import BackendValiditySchema

SCHEMA_ID: Final = "simulator_validity"
SCHEMA_VERSION: Final = "1.0.0"
SCHEMA_REF: Final = f"{DOMAIN}/{SCHEMA_ID}@{SCHEMA_VERSION}"

#: SIM-001's four clauses, as field names. One per clause, in the order the requirement states
#: them, so a reader can check the mapping without translating.
#:
#:     solver version          -> solver_id, solver_version
#:     project hash            -> project_hash
#:     mesh/bias/config        -> mesh_config_ref, bias_config_ref
#:     exit/convergence status -> convergence_status
#:
#: `solver_id` is split from `solver_version` because SIM-001 names the version and a version with
#: no product is not an identity: "2024-R2" is meaningless without knowing what it versions.
REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "solver_id",
    "solver_version",
    "project_hash",
    "mesh_config_ref",
    "bias_config_ref",
    "convergence_status",
)

#: Declared, and not required. Each is genuinely optional for a valid run and saying so keeps the
#: required list honest -- a required field that half the runs cannot supply becomes a field
#: everybody fills with a placeholder.
OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "validated_range",
    "residual_norm",
    "iterations",
    "notes",
)

#: Convergence values this pack recognises. Not a CHECK in core: §17.10 makes the vocabulary the
#: DomainPack's, and a core enum of solver exit states would be §24.1's forbidden column.
CONVERGED: Final = "CONVERGED"
NOT_CONVERGED: Final = "NOT_CONVERGED"
MAX_ITERATIONS: Final = "MAX_ITERATIONS"
CONVERGENCE_STATES: Final[tuple[str, ...]] = (CONVERGED, MAX_ITERATIONS, NOT_CONVERGED)

#: Convergence outcomes that may carry a fidelity above coarse. A run that hit its iteration cap
#: produced numbers, and they are usable as a challenge -- but SIM-002's rejection gate is the
#: thing they must not pass, and authority is where that is decided (see `authority_policy`).
CONVERGED_STATES: Final[frozenset[str]] = frozenset({CONVERGED})


def schema() -> BackendValiditySchema:
    """The registration. One schema, one version, refused if it requires nothing."""
    return BackendValiditySchema(
        schema_id=SCHEMA_ID,
        version=SCHEMA_VERSION,
        domain=DOMAIN,
        required_fields=REQUIRED_FIELDS,
        optional_fields=OPTIONAL_FIELDS,
    )


def fidelity_for(validity: dict[str, object], declared: str) -> str:
    """The authority class a run's validity record actually supports.

    DERIVED, NOT DECLARED, and that is the SIM-002 half that a backend could otherwise lie about.
    A provider adapter that stamped `SIM_VALIDATION` on a run that hit its iteration cap would walk
    straight through the rejection gate; here the declared class is a ceiling and the convergence
    status is what decides whether it is reached.

    Returns `SIM_COARSE` for anything that did not converge, whatever the backend claimed.
    """
    from lab_brain.domains.silicon_photonics.authority_policy import SIM_COARSE

    status = validity.get("convergence_status")
    if not isinstance(status, str) or status not in CONVERGED_STATES:
        return SIM_COARSE
    return declared


__all__ = [
    "CONVERGED",
    "CONVERGED_STATES",
    "CONVERGENCE_STATES",
    "MAX_ITERATIONS",
    "NOT_CONVERGED",
    "OPTIONAL_FIELDS",
    "REQUIRED_FIELDS",
    "SCHEMA_ID",
    "SCHEMA_REF",
    "SCHEMA_VERSION",
    "fidelity_for",
    "schema",
]
