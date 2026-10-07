"""The Silicon Photonics product vertical: what this pack supplies to `lab_brain.research` (§25.1).

    §25.1  H1 access/contact discontinuity | H2 mesh/convergence artifact |
           H3 contact/material/normalization model issue
           -> connectivity inspection / mesh sensitivity / model check

THE MECHANISM CATALOG IS DOMAIN KNOWLEDGE, DECLARED HERE. Five rival mechanisms for "Rs extremely
high and weakly bias-dependent" -- §25.1's three, with the model issue split into its two
checkable forms, plus the two a lab raises in practice (counter-doping, probe contact). Each names
its falsifier, the cheapest check that tests it, and one SUPPORTS and one CONTRADICTS prediction
over the observable that check produces, in this pack's declared OutcomeSpaces; the CONTRADICTS
one is designated as the typed falsifier. The words that
point at a mechanism in a record (`cues`) and against it (`counter_cues`) are what the local
rule-based reasoner reads; with a language model configured they are simply unused.

WHAT THIS DEPLOYMENT CAN EXECUTE, AND WHAT IT CANNOT. `product_vertical` installs the pack with a
backend for every capability that can run here: the two solver-free design readers
(`ContactConnectivityReader`, `NormalizationBasisReader`) -- local, deterministic, recorded as Runs.
No simulation backend is wired: this repository contains no licensed Lumerical provider and this
deployment has no installation or seat (TST-001, risk R-1). Every SIMULATION capability is therefore
marked UNAVAILABLE with that reason, so the planner never selects one and nothing is mocked in its
place; the orchestrator asks the declared descriptors separately what the best next action WOULD be
and reports it as a pending requirement. Measurement and fabrication have no workflow at all -- a
person performs them -- and stay plannable as requests for a person to act.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from lab_brain.cognition.catalog_reasoner import (
    CatalogMechanism,
    CatalogPrediction,
    MechanismCatalog,
)
from lab_brain.core.models.capability import ActionType, Availability
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.authority_policy import (
    SiliconPhotonicsAuthorityPolicy,
    transition_policies,
)
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN
from lab_brain.domains.silicon_photonics.plugin import DEBATE_BENCHMARK_ID, SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics.tools import INPUT_DEVICE_PROJECT
from lab_brain.research.vertical import (
    BlockedCapability,
    InputRefused,
    ProductVertical,
    VerificationInput,
)
from lab_brain.tools.execution import ExecutionOutcome
from lab_brain.tools.routing import CapabilityRoutedRunner
from lab_brain.tools.simulation import SimulationRequest
from lab_brain.verification.sufficiency import TransitionTarget

CATALOG_ID = "sp.rs_anomaly_mechanisms"
CATALOG_VERSION = "1.0.0"

SIMULATOR_UNAVAILABLE = (
    "no simulation backend is wired in this deployment: this repository has no licensed "
    "Lumerical provider, and no Lumerical installation or licence seat is configured "
    "(TST-001, risk R-1)"
)
SIMULATOR_REQUIRES = (
    "a Lumerical DEVICE/CHARGE installation with a licence seat, and the licensed provider "
    "module wired in place of the missing backend"
)


#: Each mechanism's typed falsifier: the CONTRADICTS half of its `_pair`.
_FALSIFIER = "falsifier"


def _pair(
    observable: str, space: str, supports: str, contradicts: str
) -> tuple[CatalogPrediction, CatalogPrediction]:
    return (
        CatalogPrediction("supports", observable, space, sp.SPACE_VERSION, supports, "SUPPORTS"),
        CatalogPrediction(
            _FALSIFIER, observable, space, sp.SPACE_VERSION, contradicts, "CONTRADICTS"
        ),
    )


def mechanism_catalog() -> MechanismCatalog:
    """§25.1's rivals for the Rs anomaly, versioned as one catalog."""
    return MechanismCatalog(
        catalog_id=CATALOG_ID,
        version=CATALOG_VERSION,
        primary_terms=("series", "resistance", "rs", "bias", "contact"),
        mechanisms=(
            CatalogMechanism(
                key="contact_discontinuity",
                statement="An access or contact discontinuity dominates the series resistance.",
                mechanism="access contact discontinuity",
                assumptions=(
                    "the contact via geometry is taken unmodified from the device project",
                ),
                confounders=("probe contact resistance during measurement",),
                falsifier=(
                    "the connectivity inspection finds every contact tied to metal with full "
                    "overlap"
                ),
                minimal_test_ref=sp.CAP_INSPECT_CONNECTIVITY,
                predictions=_pair(
                    sp.OBS_CONNECTIVITY,
                    sp.SPACE_CONNECTIVITY,
                    diagnosis.DISCONTINUOUS,
                    diagnosis.CONTINUOUS,
                ),
                falsifier_prediction_keys=(_FALSIFIER,),
                cues=("contact via", "access region", "contact resistance", "contact-resistance"),
                counter_cues=("contact continuity verified",),
            ),
            CatalogMechanism(
                key="normalization_error",
                statement=(
                    "A length normalization error in extraction inflates the per-length resistance."
                ),
                mechanism="length normalization error",
                assumptions=("the extraction divides by a single device length",),
                confounders=("taper sections excluded from the drawn length",),
                falsifier="the extraction's normalization length matches the drawn length",
                minimal_test_ref=sp.CAP_EXTRACTION_CONSISTENCY,
                predictions=_pair(
                    sp.OBS_NORMALIZATION,
                    sp.SPACE_NORMALIZATION,
                    diagnosis.DISAGREES,
                    diagnosis.AGREES,
                ),
                falsifier_prediction_keys=(_FALSIFIER,),
                cues=("normalization", "normalisation", "per length", "per-length"),
                counter_cues=("normalization crosschecked",),
            ),
            CatalogMechanism(
                key="mesh_artifact",
                statement=(
                    "A mesh convergence artifact in the access region inflates the extracted "
                    "series resistance."
                ),
                mechanism="mesh convergence artifact",
                assumptions=("the solver mesh in the access region is the project default",),
                confounders=("solver tolerance settings",),
                falsifier="refining the access mesh leaves the extracted Rs unchanged",
                minimal_test_ref=sp.CAP_MESH_SENSITIVITY,
                predictions=_pair(sp.OBS_MESH, sp.SPACE_MESH, diagnosis.UNSTABLE, diagnosis.STABLE),
                falsifier_prediction_keys=(_FALSIFIER,),
                cues=("mesh", "convergence"),
                counter_cues=("refinement left rs unchanged",),
            ),
            CatalogMechanism(
                key="dopant_compensation",
                statement=(
                    "Counter-doping compensates the rib and raises the resistance of the "
                    "undepleted access path."
                ),
                mechanism="dopant compensation in the rib",
                assumptions=("the implant recipe matches the process design kit",),
                confounders=("anneal temperature variation",),
                falsifier="the DC sweep shows the design free-carrier density in the access region",
                minimal_test_ref=sp.CAP_CHARGE_DC,
                predictions=_pair(
                    sp.OBS_CARRIER, sp.SPACE_CARRIER, diagnosis.COMPENSATED, diagnosis.NOMINAL
                ),
                falsifier_prediction_keys=(_FALSIFIER,),
                cues=("counterdoping", "compensation", "doping", "implant"),
                counter_cues=("implant dose measured nominal",),
            ),
            CatalogMechanism(
                key="probe_artifact",
                statement=(
                    "Probe contact resistance in the two-point measurement inflates the reported "
                    "series resistance."
                ),
                mechanism="measurement probe contact artifact",
                assumptions=("the anomaly was measured with a two point probe",),
                confounders=("pad metallization variation",),
                falsifier="a four point measurement reports the same series resistance",
                minimal_test_ref=sp.CAP_FOURPOINT_PROBE,
                predictions=_pair(
                    sp.OBS_PROBE, sp.SPACE_PROBE, diagnosis.ELEVATED, diagnosis.NOMINAL
                ),
                falsifier_prediction_keys=(_FALSIFIER,),
                cues=("probe contact", "two point", "two-point", "instrumentation"),
                counter_cues=("four point probing confirms",),
            ),
        ),
    )


def read_device_project(data: bytes) -> VerificationInput:
    """The user's device project, read as the pack's declared verification input."""
    try:
        device = diagnosis.DeviceProject.parse(data)
    except diagnosis.DesignError as bad:
        raise InputRefused(str(bad)) from bad
    return VerificationInput(
        kind=INPUT_DEVICE_PROJECT,
        conditions=device.conditions(),
        conditions_schema_version=sp.DEVICE_SCHEMA_REF,
        summary=(
            f"device {device.device_id}, drawn length {device.drawn_length_um} um, "
            f"{len(device.contacts)} contacts"
        ),
    )


def product_vertical(
    *,
    outputs: Any,
    jobs: Any,
    broker: Any,
    now: Callable[[], dt.datetime],
) -> ProductVertical:
    """The pack as THIS deployment can run it. See the module docstring."""
    registry = DomainPackRegistry()
    backends = {
        sp.CAP_INSPECT_CONNECTIVITY: diagnosis.ContactConnectivityReader(sink=outputs, now=now),
        sp.CAP_EXTRACTION_CONSISTENCY: diagnosis.NormalizationBasisReader(sink=outputs, now=now),
    }
    runner = CapabilityRoutedRunner(
        backends=backends,
        jobs=jobs,
        broker=broker,
        validity=registry.registries.backend_validity,
        now=now,
        domain=DOMAIN,
    )
    registry.install(SiliconPhotonicsPack(runner=runner, conditions=registry.registries.conditions))
    capabilities = registry.registries.capabilities
    blocked: list[BlockedCapability] = []
    for capability in sorted(capabilities, key=lambda c: c.capability_id):
        if capability.action_type is ActionType.SIMULATION and (
            capability.capability_id not in backends
        ):
            capabilities.set_availability(capability.capability_id, Availability.UNAVAILABLE)
            blocked.append(
                BlockedCapability(
                    capability_id=capability.capability_id,
                    action_type=capability.action_type.value,
                    reason=SIMULATOR_UNAVAILABLE,
                    requires=SIMULATOR_REQUIRES,
                )
            )

    # The declared descriptors, for "what would the best next action be" -- never executed.
    planning = DomainPackRegistry()
    planning.install(
        SiliconPhotonicsPack(
            runner=_never_run,
            conditions=planning.registries.conditions,
        )
    )
    authority = sp.VerticalAuthorityPolicy()
    v1 = SiliconPhotonicsAuthorityPolicy()
    return ProductVertical(
        domain=DOMAIN,
        registry=registry,
        planning_capabilities=planning.registries.capabilities,
        blocked=tuple(blocked),
        catalog=mechanism_catalog(),
        intent="DIAGNOSIS",
        stakes="HIGH",
        selection_policy=sp.selection_policy(),
        targets=tuple(
            TransitionTarget(policy=policy, to_state=to_state)
            for policy, to_state in sp.diagnosis_targets()
        ),
        transition_policies=(*transition_policies(), *sp.vertical_transition_policies()),
        authority_policy=authority,
        authority_policies={
            (v1.policy_id, v1.policy_version): v1,
            (authority.policy_id, authority.policy_version): authority,
        },
        condition_schemas=(sp.device_schema_registration(),),
        debate_benchmark_id=DEBATE_BENCHMARK_ID,
        input_media_type=diagnosis.DEVICE_PROJECT_MEDIA_TYPE,
        read_input=read_device_project,
        backends={
            capability_id: f"{type(backend).__name__} (local, solver-free design reader)"
            for capability_id, backend in backends.items()
        },
    )


def _never_run(request: SimulationRequest) -> ExecutionOutcome:
    del request
    raise RuntimeError(
        "the planning registry is read to answer what the best next action would be; it never "
        "executes anything"
    )


__all__ = [
    "CATALOG_ID",
    "CATALOG_VERSION",
    "SIMULATOR_REQUIRES",
    "SIMULATOR_UNAVAILABLE",
    "mechanism_catalog",
    "product_vertical",
    "read_device_project",
]
