"""The Silicon Photonics DomainPack (§11, §24.3, DOM-SP-001, DOM-SP-002).

    §11  第一個 DomainPack 是 Silicon Photonics。它提供 condition schema、EvidenceAuthority
         policy、backend validity、physical validators、metric extractors、specialist roles、
         Lumerical bindings 與 benchmarks。

EVERYTHING THIS PACK KNOWS IS IN THIS DIRECTORY, AND THAT IS THE CLAIM DOM-SP-001 TESTS. The Rs
trend rule, the fidelity ranking, the `simulator_validity` field list, the series-RC reduction and
the condition tolerances all live under `lab_brain/domains/silicon_photonics/`. Core has no place
to put any of them: `ValidationReport` keys findings by an opaque `rule_id`, `AuthorityPolicy` is a
Protocol with no default ranking, `BackendValiditySchema` carries a `required_fields` tuple and no
opinion about its contents, and `ExtractedQuantity` has a `normalization_basis` field and no idea
what a normalization basis is.

`register_*` METHODS TAKE THE REGISTRY, exactly as §24.3 declares. They do not return payloads for
core to install: what to do with a domain's condition schema is a decision, and core making it
would mean core knew something about the domain.

THE RUNNER IS A CONSTRUCTOR ARGUMENT, and it is the one dependency this pack has. `run_*` tools are
backend-bound by §10.2.1, so the tool needs a way to execute -- and a pack that reached for a
composition root would invert §24.2's dependency edge. So the runner is handed in: production wires
`lab_brain.tools.execution.run_simulation`, tests wire a deterministic stand-in, and neither is
named here.
"""

from __future__ import annotations

from typing import Final

from lab_brain.core.authority import AuthorityPolicyRegistry
from lab_brain.core.models.capability import ActionType, Availability, Capability
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.domains.base import (
    BenchmarkRegistry,
    DomainInstallError,
    ExtractorRegistry,
    SpecialistRegistry,
    ValidatorRegistry,
)
from lab_brain.domains.silicon_photonics import backend_validity, reasoning, tools
from lab_brain.domains.silicon_photonics.authority_policy import (
    SIM_STANDARD,
    SiliconPhotonicsAuthorityPolicy,
    transition_policies,
)
from lab_brain.domains.silicon_photonics.condition_schema import (
    DOMAIN,
    SCHEMA_REF,
    PnJunctionConditionComparator,
    registration,
)
from lab_brain.domains.silicon_photonics.extractors import CjRsExtractor
from lab_brain.domains.silicon_photonics.validators import ExpectedTrendValidator
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.tools.registry import ToolRegistry
from lab_brain.tools.simulation import BackendValidityRegistry
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.disagreement import DisagreementMetricRegistry

PACK_ID: Final = DOMAIN
PACK_VERSION: Final = "1.0.0"

#: §17.18's `estimate_cost_contract` -- the NAME of the estimator, resolved by the registry.
CHARGE_AC_COST_CONTRACT: Final = "cost:sp.charge_ac_sweep@1.0.0"

#: §15.1's benchmark identity for this pack. Thin on purpose: the benchmark machinery is LLM-002
#: in M3, and what EXT-001 needs is that a pack can register one at all.
BENCHMARK_ID: Final = "bench:sp.cj_rs_extraction"
BENCHMARK_FIXTURE: Final = "fixtures/silicon_photonics/cj_rs_paired/"

#: M3 / LLM-002. The FIXED SiPho debate benchmark -- §26's T-LLM-002 "fixed SiPho benchmark" --
#: whose baseline distributions calibrate the BenchmarkPolicy thresholds. Locked by digest; see
#: `lab_brain.cognition.debate_benchmark`.
DEBATE_BENCHMARK_ID: Final = "bench:sp.rs_anomaly_debate"
DEBATE_BENCHMARK_FIXTURE: Final = "fixtures/debate/sp_rs_anomaly_debate.json"


def reasoning_benchmark_id() -> str:
    return DEBATE_BENCHMARK_ID


def estimate_charge_ac_cost(params: object) -> CostVector:
    """§9.5's `estimate_cost(params) -> CostVector` for the small-signal execution.

    A VECTOR, NOT A NUMBER, and the seat time is the dimension that matters here: §9.4's example
    is the six-week shuttle, and the same argument applies at this scale -- a solver run that takes
    a license seat for ten minutes is not "cheaper" than one that takes twenty minutes of CPU and
    no seat, it is a different kind of cost. Collapsing them is what VER-003 forbids.

    Deliberately crude and deliberately declared. A real estimator calibrated against measured run
    times is M4's; what VER-002 needs is that a descriptor resolves to one at all, and a stub that
    pretended to be calibrated would be worse than one that says it is not.
    """
    points = 1
    if isinstance(params, dict):
        raw = params.get("bias_points", 1)
        if isinstance(raw, int) and raw > 0:
            points = raw
    return CostVector(
        wall_clock_s=30 * points,
        compute_units=4 * points,
        license_seat_s=30 * points,
        irreversible=False,
    )


def estimate_local_tool_cost(params: object) -> CostVector:
    """§9.5's estimator for this pack's `extract_*` and `validate_*` tools.

    A few seconds of wall-clock, no seat, no money, no compute units. That is not a way of
    declaring them exempt: a zero in a dimension is a positive claim that the dimension costs
    nothing, and it is the one dimension a caps policy can still refuse if a project has frozen
    its wall-clock budget at zero. COST-001 gates *each* tool call; this is what makes a local
    call gateable rather than skippable.
    """
    return CostVector(wall_clock_s=2)


class SiliconPhotonicsPack:
    """§24.3's protocol, for the methods M2 authorises. See the module docstring."""

    def __init__(self, runner: tools.SimulationRunner, conditions: ConditionSchemaRegistry) -> None:
        """Two dependencies, both required, both handed in rather than reached for.

        ``runner`` because §10.2.1 makes `run_*` backend-bound and a pack that reached for a
        composition root would invert §24.2's dependency edge.

        ``conditions`` because EVI-001's extractor validates against the REGISTERED schema, and an
        extractor built without a registry could only skip the check. Passing it at construction
        also lets `register_condition_schema` refuse a pack being installed into a *different*
        registry from the one its extractor validates against -- which would otherwise produce an
        extractor checking conditions against a schema that is not the one in force.
        """
        self._runner = runner
        self._conditions = conditions
        self._extractor = CjRsExtractor(conditions)
        self._validator = ExpectedTrendValidator()
        self._authority = SiliconPhotonicsAuthorityPolicy()
        self._comparator = PnJunctionConditionComparator()

    @property
    def id(self) -> str:
        return PACK_ID

    @property
    def version(self) -> str:
        return PACK_VERSION

    # -- §24.3 registrations ------------------------------------------------

    def register_condition_schema(self, registry: ConditionSchemaRegistry) -> None:
        if registry is not self._conditions:
            raise DomainInstallError(
                f"{PACK_ID} was constructed against one condition registry and is being installed "
                "into another. Its extractor validates EVI-001's conditions against the registry "
                "it holds, so installing it elsewhere would check every Cj/Rs record against a "
                "schema that is not the one in force"
            )
        schema = registration()
        registry.register_schema(schema)
        # The comparator is registered under the version the SCHEMA declares, not under "latest".
        # `get_comparator` resolves through `schema.comparator_version`, so a mismatch here fails
        # closed rather than comparing conditions under rules the schema never named.
        registry.register_comparator(schema.domain, schema.schema_id, self._comparator)

    def register_evidence_authority_policy(self, registry: AuthorityPolicyRegistry) -> None:
        # `register` verifies §10.5.1's laws over the declared classes before accepting. A ranking
        # that is not a partial order cannot be installed, which is stronger than a test that
        # checks it -- the pack cannot be present and wrong at the same time.
        registry.register(self._authority)

    def register_backend_validity_schemas(self, registry: BackendValidityRegistry) -> None:
        registry.register(backend_validity.schema())

    def register_validators(self, registry: ValidatorRegistry) -> None:
        registry.register(self._validator)

    def register_metric_extractors(self, registry: ExtractorRegistry) -> None:
        registry.register(self._extractor)

    def register_capabilities(self, registry: CapabilityRegistry) -> None:
        registry.register_estimator(CHARGE_AC_COST_CONTRACT, estimate_charge_ac_cost)
        # The local tools' estimator. Registered here rather than in `register_tools` because the
        # CapabilityRegistry is where estimators live (§9.5) and a tool's declared `cost_contract`
        # resolves against it -- one place a price comes from, whether or not the tool is
        # backend-bound.
        registry.register_estimator(tools.LOCAL_TOOL_COST_CONTRACT, estimate_local_tool_cost)
        registry.register(
            Capability(
                capability_id=tools.CHARGE_AC_CAPABILITY,
                domain=DOMAIN,
                action_type=ActionType.SIMULATION,
                backend_id="sp.charge.ac",
                requires=(tools.INPUT_DEVICE_PROJECT,),
                produces=(tools.OBSERVABLE_IMPEDANCE,),
                # SIM_STANDARD, not SIM_VALIDATION. A capability declares the authority it can
                # yield at best; `backend_validity.fidelity_for` then lowers it to SIM_COARSE for a
                # run that did not converge, so a non-converged result cannot walk through
                # SIM-002's rejection gate on the strength of what the descriptor claimed.
                authority_class=SIM_STANDARD,
                availability=Availability.AVAILABLE,
                conditions_schema_version=SCHEMA_REF,
                license_constraints=(tools.SIMULATOR_RESOURCE_ID,),
                irreversible=False,
                estimate_cost_contract=CHARGE_AC_COST_CONTRACT,
                version="1.0.0",
            )
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.register(tools.charge_ac_descriptor(), tools.ChargeAcSweepTool(self._runner))
        registry.register(tools.extract_cj_rs_descriptor(), self._extractor)
        registry.register(
            tools.validate_trends_descriptor(), tools.ExpectedTrendTool(self._validator)
        )

    def register_benchmarks(self, registry: BenchmarkRegistry) -> None:
        registry.register(BENCHMARK_ID, BENCHMARK_FIXTURE)
        # M3 / LLM-002. The fixed debate benchmark calibration is run against.
        registry.register(reasoning_benchmark_id(), DEBATE_BENCHMARK_FIXTURE)

    # -- M3 registrations (§24.3) -------------------------------------------

    def register_specialists(self, registry: SpecialistRegistry) -> None:
        registry.register(reasoning.SEMICONDUCTOR_SPECIALIST)
        registry.register(reasoning.NUMERICS_SPECIALIST)

    def register_disagreement_metrics(self, registry: DisagreementMetricRegistry) -> None:
        # The space first: the registry refuses a metric bound to an undeclared one (VER-008).
        registry.declare_space(reasoning.rs_response_space())
        registry.register(reasoning.RsResponseRankDistance())

    # -- offered, not registered -------------------------------------------

    def transition_policies(self) -> tuple[TransitionPolicy, ...]:
        """SIM-002's two §8.2.1 policy records.

        NOT a `register_*` method: §24.3 declares none for transition policies, and adding one
        would be this implementation inventing normative extension surface. The composition root
        registers them into the store `005b` provides.
        """
        return transition_policies()

    @property
    def authority_policy(self) -> SiliconPhotonicsAuthorityPolicy:
        return self._authority

    @property
    def extractor(self) -> CjRsExtractor:
        return self._extractor

    @property
    def validator(self) -> ExpectedTrendValidator:
        return self._validator


__all__ = [
    "BENCHMARK_FIXTURE",
    "BENCHMARK_ID",
    "CHARGE_AC_COST_CONTRACT",
    "DEBATE_BENCHMARK_FIXTURE",
    "DEBATE_BENCHMARK_ID",
    "PACK_ID",
    "PACK_VERSION",
    "SiliconPhotonicsPack",
    "estimate_charge_ac_cost",
    "estimate_local_tool_cost",
]
