"""What the Silicon Photonics pack declares for VS-SP-001 (§25, M4).

    §25.1  choose cheapest discriminative check -> run typed tool -> confirmed finding
    §25.4  Verification Planner 先檢查 historical case / connectivity / extraction consistency 等
           低成本動作，再在需要時升級 simulator

EVERYTHING HERE IS DATA THE PLANNER READS; NOTHING HERE PLANS. The planner is domain-agnostic
(§9). What makes it choose a connectivity inspection before a DC sweep is not a rule in this file
-- it is the CostVector each capability's estimator returns and the declared SelectionPolicy, the
same way it would choose for any domain.

THE VERIFICATION ACTIONS, AS CAPABILITIES (§9.3's action types, §9.4's cost vectors):

    cap:sp.inspect_contact_connectivity  RULE_CHECK   seconds, no seat     DESIGN_INSPECTION
    cap:sp.extraction_consistency        RULE_CHECK   seconds, no seat     DESIGN_INSPECTION
    cap:sp.mesh_sensitivity              SIMULATION   minutes, a seat      SIM_STANDARD
    cap:sp.charge_dc_sweep               SIMULATION   10 minutes, a seat   SIM_STANDARD
    cap:sp.fourpoint_probe               MEASUREMENT  hours, a person, $   MEAS_CALIBRATED
    cap:sp.fabricate_split_lot           FABRICATION  weeks, $$$, irreversible

(RULE_CHECK is §9.3's `ANALYTICAL_RULE_CHECK`.)

The two ids `cap:sp.extraction_consistency` and `cap:sp.mesh_sensitivity` are the ones M3's debate
fixture already names as its hypotheses' `minimal_test_ref`; M4 is where they became real.
Measurement and fabrication have no workflow: choosing one is a request for a person to act.

DESIGN_INSPECTION, AND WHY IT IS A NEW COMPARATOR VERSION (`auth:silicon_photonics@1.1.0`). A
reading of the design project is evidence about the DESIGNED device -- the family SIM-002's fidelity
classes already describe -- and it is not a solve: nothing converges or fails to. It ranks with a
validation-fidelity simulation (EQUIVALENT), above standard and coarse, and it is INCOMPARABLE with
measurement for §10.6's reason. `1.0.0` is unchanged and stays registered: every M2 decision was
authorised under it and must re-derive under it forever (§17.14.1).

THE POLICIES (`vertical_transition_policies`). M2's SIM-002 pair already governs ACTIVE->CHALLENGED
(coarse) and ACTIVE->CONTRADICTED (standard); VS-SP-001 reuses both unchanged. What it adds is the
move a confirmed finding needs, ACTIVE->SUPPORTED, in two versions of one rule -- one for evidence
about the designed device (rule SIM_STANDARD, so a coarse solve cannot confirm and an inspection
can) and one for evidence about the fabricated device (rule MEAS_CALIBRATED). Each requires a
SUPPORTS relation, an EXACT/COMPATIBLE ConditionMatch and one independent work.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar, Final

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.benchmark import DisagreementMetric
from lab_brain.core.models.capability import ActionType, Availability, Capability
from lab_brain.core.models.condition import ConditionSchemaRegistration
from lab_brain.core.models.cost import CostVector, DependencyRisk
from lab_brain.core.models.enums import AuthorityComparison, ConditionMatchState, RelationType
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.models.validation import (
    ValidationFinding,
    ValidationReport,
    ValidationStatus,
    report,
)
from lab_brain.core.models.verification import CostDimension, SelectionPolicy, TieBreakRule
from lab_brain.domains.silicon_photonics import diagnosis, reasoning
from lab_brain.domains.silicon_photonics.authority_policy import (
    CHALLENGE_POLICY_ID,
    MEAS_CALIBRATED,
    MEAS_UNCALIBRATED,
    POLICY_VERSION,
    REJECT_POLICY_ID,
    SIM_COARSE,
    SIM_STANDARD,
    SIM_VALIDATION,
    transition_policies,
)
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN
from lab_brain.domains.silicon_photonics.tools import (
    INPUT_DEVICE_PROJECT,
    OBSERVABLE_IMPEDANCE,
    SIMULATOR_RESOURCE_ID,
)
from lab_brain.verification.plausibility import CAPABILITY_FIELD, OutcomeSubject

# -- conditions --------------------------------------------------------------------------------

DEVICE_SCHEMA_ID: Final = "pn_junction_device"
DEVICE_SCHEMA_VERSION: Final = "1.0.0"
DEVICE_SCHEMA_REF: Final = f"{DOMAIN}/{DEVICE_SCHEMA_ID}@{DEVICE_SCHEMA_VERSION}"
DEVICE_COMPARATOR_VERSION: Final = "1.0.0"


def device_schema_registration() -> ConditionSchemaRegistration:
    """The diagnosis conditions: WHICH device. Geometry is this pack's column (§24.1).

    `device_length_um` is required for the reason `pn_junction_ac` requires it: it is the
    normalization basis (EVI-001) and it identifies the device a result is about. A mesh study of
    a 1 mm device is not evidence about a 500 um one, and the comparator makes it INCOMPATIBLE.
    """
    return ConditionSchemaRegistration(
        domain=DOMAIN,
        schema_id=DEVICE_SCHEMA_ID,
        version=DEVICE_SCHEMA_VERSION,
        comparator_version=DEVICE_COMPARATOR_VERSION,
        json_schema={
            "type": "object",
            "required": ["device_length_um"],
            "properties": {
                "device_length_um": {
                    "type": "string",
                    "description": "Drawn active length, micrometres; the normalization basis",
                },
                "temperature_k": {"type": "string", "description": "Device temperature, kelvin"},
            },
            "additionalProperties": False,
        },
    )


# -- observables and outcome spaces ---------------------------------------------------------------

OBS_CONNECTIVITY: Final = "sp.contact_connectivity"
OBS_NORMALIZATION: Final = "sp.normalization_basis"
OBS_MESH: Final = "sp.mesh_stability"
OBS_CARRIER: Final = "sp.carrier_profile"
OBS_PROBE: Final = "sp.probe_contact_resistance"

SPACE_VERSION: Final = "1.0.0"
SPACE_CONNECTIVITY: Final = "os:sp.contact_connectivity"
SPACE_NORMALIZATION: Final = "os:sp.normalization_basis"
SPACE_MESH: Final = "os:sp.mesh_stability"
SPACE_CARRIER: Final = "os:sp.carrier_profile"
SPACE_PROBE: Final = "os:sp.probe_contact_resistance"

#: observable -> (space id, outcomes, action type the space is read from). One space per
#: observable, which is what lets the outcome validator check a prediction's binding.
_SPACES: Final[Mapping[str, tuple[str, tuple[str, ...], str]]] = {
    OBS_CONNECTIVITY: (
        SPACE_CONNECTIVITY,
        (diagnosis.CONTINUOUS, diagnosis.DISCONTINUOUS),
        ActionType.ANALYTICAL_RULE_CHECK.value,
    ),
    OBS_NORMALIZATION: (
        SPACE_NORMALIZATION,
        (diagnosis.AGREES, diagnosis.DISAGREES),
        ActionType.ANALYTICAL_RULE_CHECK.value,
    ),
    OBS_MESH: (SPACE_MESH, (diagnosis.STABLE, diagnosis.UNSTABLE), ActionType.SIMULATION.value),
    OBS_CARRIER: (
        SPACE_CARRIER,
        (diagnosis.NOMINAL, diagnosis.COMPENSATED),
        ActionType.SIMULATION.value,
    ),
    OBS_PROBE: (
        SPACE_PROBE,
        (diagnosis.NOMINAL, diagnosis.ELEVATED),
        ActionType.MEASUREMENT.value,
    ),
}


def _metric_id(space_id: str) -> str:
    return "dm:" + space_id.removeprefix("os:") + ".mismatch"


def outcome_spaces() -> tuple[OutcomeSpace, ...]:
    return tuple(
        OutcomeSpace(
            outcome_space_id=space_id,
            version=SPACE_VERSION,
            domain=DOMAIN,
            action_type=action_type,
            hypothesis_type="ROOT_CAUSE",
            outcomes=outcomes,
            order_or_metric_ref=f"{_metric_id(space_id)}@1.0.0",
        )
        for _, (space_id, outcomes, action_type) in sorted(_SPACES.items())
    )


def space_for(observable_ref: str) -> tuple[str, str] | None:
    """The (id, version) this pack declares for an observable, or `None`."""
    if observable_ref == OBSERVABLE_IMPEDANCE:
        return (reasoning.RS_RESPONSE_SPACE_ID, reasoning.RS_RESPONSE_SPACE_VERSION)
    found = _SPACES.get(observable_ref)
    return None if found is None else (found[0], SPACE_VERSION)


def prediction_bindings() -> tuple[tuple[str, str, str], ...]:
    """This pack's prediction vocabulary: (observable_ref, space id, version) for every observable
    a hypothesis may predict over -- the same map `space_for` reads, the impedance included. Every
    one, whether or not this deployment can execute the check that observes it."""
    observables = (OBSERVABLE_IMPEDANCE, *_SPACES)
    return tuple(
        (observable, *found)
        for observable in sorted(observables)
        if (found := space_for(observable)) is not None
    )


class CategoricalMismatch:
    """VER-008 for a two-valued diagnosis space: 0 when the outcomes agree, 1 when they do not.

    Categorical because the outcomes are unordered facts -- "continuous" is not halfway to
    "discontinuous" -- and declared per space so each metric binds to exactly one version.
    """

    def __init__(self, space_id: str) -> None:
        self._space_id = space_id

    @property
    def declaration(self) -> DisagreementMetric:
        return DisagreementMetric(
            metric_id=_metric_id(self._space_id),
            outcome_space_id=self._space_id,
            outcome_space_version=SPACE_VERSION,
            implementation_ref=f"{__name__}:CategoricalMismatch",
            version="1.0.0",
        )

    def distance(self, a: str, b: str) -> Decimal:
        return Decimal(0) if a == b else Decimal(1)


def disagreement_metrics() -> tuple[CategoricalMismatch, ...]:
    return tuple(CategoricalMismatch(space_id) for space_id, _, _ in sorted(_SPACES.values()))


# -- capabilities and their cost estimators (§9.4, §9.5) -------------------------------------------

CAP_INSPECT_CONNECTIVITY: Final = "cap:sp.inspect_contact_connectivity"
CAP_EXTRACTION_CONSISTENCY: Final = "cap:sp.extraction_consistency"
CAP_MESH_SENSITIVITY: Final = "cap:sp.mesh_sensitivity"
CAP_CHARGE_DC: Final = "cap:sp.charge_dc_sweep"
CAP_FOURPOINT_PROBE: Final = "cap:sp.fourpoint_probe"
CAP_FABRICATE_SPLIT: Final = "cap:sp.fabricate_split_lot"

DESIGN_INSPECTION: Final = "DESIGN_INSPECTION"

COST_DESIGN_INSPECTION: Final = "cost:sp.design_inspection@1.0.0"
COST_MESH_SENSITIVITY: Final = "cost:sp.mesh_sensitivity@1.0.0"
COST_CHARGE_DC: Final = "cost:sp.charge_dc_sweep@1.0.0"
COST_FOURPOINT_PROBE: Final = "cost:sp.fourpoint_probe@1.0.0"
COST_FABRICATE_SPLIT: Final = "cost:sp.fabricate_split_lot@1.0.0"


def estimate_design_inspection(params: Mapping[str, Any]) -> CostVector:
    """Seconds of local reading. No seat, no money, no person."""
    del params
    return CostVector(wall_clock_s=2)


def estimate_mesh_sensitivity(params: Mapping[str, Any]) -> CostVector:
    """Two solves; the seat is held for both."""
    del params
    return CostVector(wall_clock_s=240, compute_units=16, license_seat_s=240)


def estimate_charge_dc(params: Mapping[str, Any]) -> CostVector:
    """A four-point reverse-bias DC sweep at standard fidelity."""
    del params
    return CostVector(wall_clock_s=600, compute_units=40, license_seat_s=600)


def estimate_fourpoint_probe(params: Mapping[str, Any]) -> CostVector:
    """A person at the probe station: attention and money, and hours of lab time."""
    del params
    return CostVector(
        wall_clock_s=4 * 3600,
        human_minutes=90,
        money_estimate=Decimal("250"),
        dependency_risk=DependencyRisk.MEDIUM,
    )


def estimate_fabricate_split(params: Mapping[str, Any]) -> CostVector:
    """§9.4's own example: high latency, irreversible, schedule-coupled -- not "high cost"."""
    del params
    return CostVector(
        wall_clock_s=6 * 7 * 24 * 3600,
        human_minutes=600,
        money_estimate=Decimal("40000"),
        irreversible=True,
        dependency_risk=DependencyRisk.HIGH,
    )


ESTIMATORS: Final = (
    (COST_DESIGN_INSPECTION, estimate_design_inspection),
    (COST_MESH_SENSITIVITY, estimate_mesh_sensitivity),
    (COST_CHARGE_DC, estimate_charge_dc),
    (COST_FOURPOINT_PROBE, estimate_fourpoint_probe),
    (COST_FABRICATE_SPLIT, estimate_fabricate_split),
)


def capabilities() -> tuple[Capability, ...]:
    common: dict[str, Any] = {"domain": DOMAIN, "version": "1.0.0"}
    return (
        Capability(
            capability_id=CAP_INSPECT_CONNECTIVITY,
            action_type=ActionType.ANALYTICAL_RULE_CHECK,
            backend_id=diagnosis.ContactConnectivityReader.backend_id,
            requires=(INPUT_DEVICE_PROJECT,),
            produces=(OBS_CONNECTIVITY,),
            authority_class=DESIGN_INSPECTION,
            conditions_schema_version=DEVICE_SCHEMA_REF,
            estimate_cost_contract=COST_DESIGN_INSPECTION,
            **common,
        ),
        Capability(
            capability_id=CAP_EXTRACTION_CONSISTENCY,
            action_type=ActionType.ANALYTICAL_RULE_CHECK,
            backend_id=diagnosis.NormalizationBasisReader.backend_id,
            requires=(INPUT_DEVICE_PROJECT,),
            produces=(OBS_NORMALIZATION,),
            authority_class=DESIGN_INSPECTION,
            conditions_schema_version=DEVICE_SCHEMA_REF,
            estimate_cost_contract=COST_DESIGN_INSPECTION,
            **common,
        ),
        Capability(
            capability_id=CAP_MESH_SENSITIVITY,
            action_type=ActionType.SIMULATION,
            backend_id="sp.charge.mesh",
            requires=(INPUT_DEVICE_PROJECT,),
            produces=(OBS_MESH,),
            authority_class=SIM_STANDARD,
            conditions_schema_version=DEVICE_SCHEMA_REF,
            license_constraints=(SIMULATOR_RESOURCE_ID,),
            estimate_cost_contract=COST_MESH_SENSITIVITY,
            **common,
        ),
        Capability(
            capability_id=CAP_CHARGE_DC,
            action_type=ActionType.SIMULATION,
            backend_id="sp.charge.dc",
            requires=(INPUT_DEVICE_PROJECT,),
            produces=(OBS_CARRIER,),
            authority_class=SIM_STANDARD,
            conditions_schema_version=DEVICE_SCHEMA_REF,
            license_constraints=(SIMULATOR_RESOURCE_ID,),
            estimate_cost_contract=COST_CHARGE_DC,
            **common,
        ),
        Capability(
            capability_id=CAP_FOURPOINT_PROBE,
            action_type=ActionType.MEASUREMENT,
            backend_id="lab.probe_station",
            requires=(),
            produces=(OBS_PROBE,),
            authority_class=MEAS_CALIBRATED,
            conditions_schema_version=DEVICE_SCHEMA_REF,
            estimate_cost_contract=COST_FOURPOINT_PROBE,
            **common,
        ),
        Capability(
            capability_id=CAP_FABRICATE_SPLIT,
            action_type=ActionType.FABRICATION,
            backend_id="foundry.mpw",
            requires=(),
            # A split lot with stepped implant dose, then measured: it would reveal compensation.
            produces=(OBS_CARRIER,),
            authority_class=MEAS_CALIBRATED,
            conditions_schema_version=DEVICE_SCHEMA_REF,
            irreversible=True,
            availability=Availability.AVAILABLE,
            estimate_cost_contract=COST_FABRICATE_SPLIT,
            **common,
        ),
    )


# -- authority, 1.1.0 ------------------------------------------------------------------------------

_FAMILIES: Final[Mapping[str, str]] = {
    SIM_COARSE: "DESIGNED",
    SIM_STANDARD: "DESIGNED",
    SIM_VALIDATION: "DESIGNED",
    DESIGN_INSPECTION: "DESIGNED",
    MEAS_UNCALIBRATED: "FABRICATED",
    MEAS_CALIBRATED: "FABRICATED",
}
_RANK: Final[Mapping[str, int]] = {
    SIM_COARSE: 1,
    SIM_STANDARD: 2,
    SIM_VALIDATION: 3,
    DESIGN_INSPECTION: 3,
    MEAS_UNCALIBRATED: 1,
    MEAS_CALIBRATED: 2,
}


class VerticalAuthorityPolicy:
    """`auth:silicon_photonics@1.1.0`: 1.0.0's two orders, plus DESIGN_INSPECTION. See above."""

    policy_id: ClassVar[str] = "auth:silicon_photonics"
    policy_version: ClassVar[str] = "1.1.0"
    authority_classes: ClassVar[tuple[str, ...]] = tuple(sorted(_RANK))

    def compare(self, a: str, b: str) -> AuthorityComparison:
        if a == b:
            return AuthorityComparison.EQUIVALENT
        if a not in _RANK or b not in _RANK or _FAMILIES[a] != _FAMILIES[b]:
            return AuthorityComparison.INCOMPARABLE
        if _RANK[a] == _RANK[b]:
            return AuthorityComparison.EQUIVALENT
        return AuthorityComparison.STRONGER if _RANK[a] > _RANK[b] else AuthorityComparison.WEAKER

    def meets(self, required_rule: str, candidate: str) -> bool:
        return self.compare(candidate, required_rule) in (
            AuthorityComparison.STRONGER,
            AuthorityComparison.EQUIVALENT,
        )


# -- transition policies ---------------------------------------------------------------------------

PROMOTE_POLICY_ID: Final = "policy:sp-vs001-promote"
PROMOTE_MEASURED_POLICY_ID: Final = "policy:sp-vs001-promote-measured"
VERTICAL_POLICY_VERSION: Final = "1.0.0"


def vertical_transition_policies() -> tuple[TransitionPolicy, ...]:
    """The ACTIVE->SUPPORTED pair a confirmed finding needs. Offered, not registered (§24.3)."""
    return (
        TransitionPolicy(
            policy_id=PROMOTE_POLICY_ID,
            domain=DOMAIN,
            version=VERTICAL_POLICY_VERSION,
            from_state=BeliefState.ACTIVE,
            candidate_to_state=BeliefState.SUPPORTED,
            required_relation_types=(RelationType.SUPPORTS,),
            required_condition_match=(ConditionMatchState.EXACT, ConditionMatchState.COMPATIBLE),
            required_authority_rule=SIM_STANDARD,
            min_independent_attestations=1,
            blocking_conflict_policy=("SIM_TO_REAL_CONFLICT", "VALIDITY_CONFLICT"),
        ),
        TransitionPolicy(
            policy_id=PROMOTE_MEASURED_POLICY_ID,
            domain=DOMAIN,
            version=VERTICAL_POLICY_VERSION,
            from_state=BeliefState.ACTIVE,
            candidate_to_state=BeliefState.SUPPORTED,
            required_relation_types=(RelationType.SUPPORTS,),
            required_condition_match=(ConditionMatchState.EXACT, ConditionMatchState.COMPATIBLE),
            required_authority_rule=MEAS_CALIBRATED,
            min_independent_attestations=1,
            blocking_conflict_policy=("SIM_TO_REAL_CONFLICT", "VALIDITY_CONFLICT"),
        ),
    )


def diagnosis_targets() -> tuple[tuple[TransitionPolicy, BeliefState], ...]:
    """Every governed move VS-SP-001 may attempt, in the order the loop tries them.

    REJECT before CHALLENGE, so a standard-fidelity contradiction rejects rather than stopping at
    the weaker move; the promote pair after both, so a hypothesis with a contradiction on record is
    never promoted past it by the order of evaluation.
    """
    m2 = {p.policy_id: p for p in transition_policies()}
    vertical = {p.policy_id: p for p in vertical_transition_policies()}
    return (
        (m2[REJECT_POLICY_ID], BeliefState.CONTRADICTED),
        (vertical[PROMOTE_POLICY_ID], BeliefState.SUPPORTED),
        (vertical[PROMOTE_MEASURED_POLICY_ID], BeliefState.SUPPORTED),
        (m2[CHALLENGE_POLICY_ID], BeliefState.CHALLENGED),
    )


assert POLICY_VERSION == "1.0.0"  # the M2 pair this vertical reuses, unchanged


# -- selection policy --------------------------------------------------------------------------

SELECTION_POLICY_ID: Final = "slp:sp.vs001"
SELECTION_POLICY_VERSION: Final = "1.0.0"


def selection_policy() -> SelectionPolicy:
    """The lab's declared ordering after Pareto filtering (VER-005). Irreversible last, then the
    scarce resources in the order §14.4.1 treats them -- a person's attention before money,
    money before a licence seat, a seat before elapsed time."""
    return SelectionPolicy(
        policy_id=SELECTION_POLICY_ID,
        version=SELECTION_POLICY_VERSION,
        pareto_dimensions=(
            CostDimension.IRREVERSIBLE,
            CostDimension.HUMAN_MINUTES,
            CostDimension.MONEY_ESTIMATE,
            CostDimension.LICENSE_SEAT_S,
            CostDimension.WALL_CLOCK_S,
            CostDimension.COMPUTE_UNITS,
        ),
        lexicographic_fallback=(
            CostDimension.IRREVERSIBLE,
            CostDimension.HUMAN_MINUTES,
            CostDimension.MONEY_ESTIMATE,
            CostDimension.LICENSE_SEAT_S,
            CostDimension.WALL_CLOCK_S,
            CostDimension.COMPUTE_UNITS,
        ),
        tie_break_rule=TieBreakRule.CAPABILITY_ID,
        effective_from=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
    )


# -- §9.1 clause 3/4: the outcome validator ---------------------------------------------------

#: observable -> the capabilities this pack declares can yield it.
_PRODUCERS: Final[Mapping[str, frozenset[str]]] = {
    OBS_CONNECTIVITY: frozenset({CAP_INSPECT_CONNECTIVITY}),
    OBS_NORMALIZATION: frozenset({CAP_EXTRACTION_CONSISTENCY}),
    OBS_MESH: frozenset({CAP_MESH_SENSITIVITY}),
    OBS_CARRIER: frozenset({CAP_CHARGE_DC, CAP_FABRICATE_SPLIT}),
    OBS_PROBE: frozenset({CAP_FOURPOINT_PROBE}),
}


class OutcomePlausibilityValidator:
    """`silicon_photonics.outcome_plausibility` -- §9.1's clauses 3 and 4 for this domain.

    Three versioned rules. The first two are about the OUTCOME: it must be read in the space this
    pack declares for its observable, and the conditions must carry the device length the
    outcome is normalized against (EVI-001). The third is about the CAPABILITY (clause 4): only a
    capability this pack declares as producing the observable can yield it.
    """

    validator_id: ClassVar[str] = "silicon_photonics.outcome_plausibility"
    validator_version: ClassVar[str] = "1.0.0"

    def validate(self, subject: object) -> ValidationReport:
        if not isinstance(subject, OutcomeSubject):
            raise TypeError("the outcome validator reads an OutcomeSubject")
        findings: list[ValidationFinding] = []
        declared = space_for(subject.observable_ref)
        if declared is not None and subject.outcome_space_ref != f"{declared[0]}@{declared[1]}":
            findings.append(
                ValidationFinding(
                    rule_id="sp.rule.outcome_space_binding",
                    rule_version="1.0.0",
                    status=ValidationStatus.FAIL,
                    message=(
                        f"{subject.observable_ref} is read in {declared[0]}@{declared[1]}, not "
                        f"{subject.outcome_space_ref}"
                    ),
                    subject_field="outcome_space",
                )
            )
        if subject.observable_ref in _PRODUCERS:
            length = subject.conditions.get("device_length_um")
            try:
                positive = length is not None and Decimal(str(length)) > 0
            except Exception:
                positive = False
            if not positive:
                findings.append(
                    ValidationFinding(
                        rule_id="sp.rule.normalization_basis_present",
                        rule_version="1.0.0",
                        status=ValidationStatus.FAIL,
                        message=(
                            f"no positive device_length_um in the conditions ({length!r}); an "
                            f"outcome of {subject.observable_ref} has no device to be about "
                            "(EVI-001)"
                        ),
                        subject_field="device_length_um",
                    )
                )
            if subject.capability_id not in _PRODUCERS[subject.observable_ref]:
                findings.append(
                    ValidationFinding(
                        rule_id="sp.rule.declared_producer",
                        rule_version="1.0.0",
                        status=ValidationStatus.FAIL,
                        message=(
                            f"{subject.capability_id} is not a declared producer of "
                            f"{subject.observable_ref}"
                        ),
                        subject_field=CAPABILITY_FIELD,
                    )
                )
        if not findings:
            findings.append(
                ValidationFinding(
                    rule_id="sp.rule.outcome_space_binding",
                    rule_version="1.0.0",
                    status=ValidationStatus.PASS,
                    message="declared binding, device length and producer all hold",
                )
            )
        return report(
            report_id=f"val:sp-outcome:{subject.capability_id}:{subject.outcome}",
            subject_type="VERIFICATION_OUTCOME",
            subject_id=f"{subject.capability_id}:{subject.observable_ref}={subject.outcome}",
            validator_id=self.validator_id,
            validator_version=self.validator_version,
            findings=tuple(findings),
        )


__all__ = [
    "CAP_CHARGE_DC",
    "CAP_EXTRACTION_CONSISTENCY",
    "CAP_FABRICATE_SPLIT",
    "CAP_FOURPOINT_PROBE",
    "CAP_INSPECT_CONNECTIVITY",
    "CAP_MESH_SENSITIVITY",
    "DESIGN_INSPECTION",
    "DEVICE_SCHEMA_REF",
    "ESTIMATORS",
    "OBS_CARRIER",
    "OBS_CONNECTIVITY",
    "OBS_MESH",
    "OBS_NORMALIZATION",
    "OBS_PROBE",
    "PROMOTE_MEASURED_POLICY_ID",
    "PROMOTE_POLICY_ID",
    "SELECTION_POLICY_ID",
    "SPACE_CARRIER",
    "SPACE_CONNECTIVITY",
    "SPACE_MESH",
    "SPACE_NORMALIZATION",
    "SPACE_PROBE",
    "SPACE_VERSION",
    "CategoricalMismatch",
    "OutcomePlausibilityValidator",
    "VerticalAuthorityPolicy",
    "capabilities",
    "device_schema_registration",
    "diagnosis_targets",
    "disagreement_metrics",
    "outcome_spaces",
    "selection_policy",
    "space_for",
    "vertical_transition_policies",
]
