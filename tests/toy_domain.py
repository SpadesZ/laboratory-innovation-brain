"""A second DomainPack, in `tests/` — EXT-001's whole question (§24.5).

    EXT-001    在不修改 core models、core repositories 與 orchestration state machine 的前提下，
               加入一個 ToyDomain 或第二個真實 domain，並能註冊 condition schema、validator、
               tool 與 benchmark。若必須修改 core 才能加入第二 domain，代表 extension boundary 失敗。
    T-EXT-001  新增 ToyDomain 時 core package 無 source modification；plugin registration 即運作。

IT LIVES OUTSIDE `src/` AND THAT IS THE ARGUMENT, not a convention. §26 asks whether adding a domain
requires *core package source modification*. A toy domain shipped inside `src/lab_brain/` would be
a domain the shipped package already contains, and the test would then be checking that an import
succeeds -- which proves nothing about the boundary. `tests/toy_authority.py` made the same move
for EPI-004's comparator in M0b, and the reasoning is identical: if the fixture were under `src/`,
it would become the de facto default the rule exists to prevent.

DELIBERATELY NOT SILICON PHOTONICS, AND DELIBERATELY NOT PLAUSIBLE. `widget_stiffness`,
`TOY_TIER_A` and `blip_count` carry no physical meaning. A toy domain named with real quantities
invites the reading that core knows what they are, and the second domain EXT-001 imagines is
supposed to be one nobody anticipated -- so this one is written as though nobody had.

WHAT IT EXERCISES. Every §24.3 method M2 authorises, against the real registries, with no core
change and no special case anywhere: a condition schema and comparator, an authority ranking with
a genuine INCOMPARABLE pair, a backend-validity schema whose required fields are its own, a
validator returning a real `ValidationReport`, a metric extractor over the SHARED extraction
contract, a Capability with its own cost estimator, three typed tools across three verb classes,
and a benchmark.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar, Final

from lab_brain.core.authority import AuthorityPolicyRegistry
from lab_brain.core.models.benchmark import DisagreementMetric
from lab_brain.core.models.capability import ActionType, Capability
from lab_brain.core.models.condition import (
    ConditionMatch,
    ConditionSchemaRegistration,
)
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.enums import AuthorityComparison, ConditionMatchState, FieldStatus
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.core.models.validation import (
    ValidationFinding,
    ValidationReport,
    ValidationStatus,
    report,
)
from lab_brain.domains.base import (
    BenchmarkRegistry,
    ExtractorRegistry,
    SpecialistRegistry,
    SpecialistRole,
    ValidatorRegistry,
)
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.tools.contracts import ToolClass, ToolDescriptor, ToolRequest, ToolResult
from lab_brain.tools.extraction import (
    ExtractedQuantity,
    ExtractionInput,
    ExtractionResult,
)
from lab_brain.tools.registry import ToolRegistry
from lab_brain.tools.simulation import BackendValidityRegistry, BackendValiditySchema
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.disagreement import DisagreementMetricRegistry

TOY_DOMAIN: Final = "toy_widgets"
TOY_VERSION: Final = "1.0.0"
TOY_SCHEMA_REF: Final = f"{TOY_DOMAIN}/widget_bench@1.0.0"
TOY_VALIDITY_REF: Final = f"{TOY_DOMAIN}/widget_validity@1.0.0"
TOY_CAPABILITY: Final = "cap:toy.widget_bench"
TOY_COST_CONTRACT: Final = "cost:toy.widget_bench@1.0.0"
TOY_LOCAL_COST_CONTRACT: Final = "cost:toy.local@1.0.0"
TOY_RESOURCE: Final = "license:toy-bench-seat"

TOY_OBSERVABLE_RAW: Final = "toy.blip_series"
TOY_OBSERVABLE_METRIC: Final = "toy.widget_stiffness"
TOY_OBSERVABLE_REPORT: Final = "toy.widget_report"

#: A genuine INCOMPARABLE pair, like `tests/toy_authority.py` has -- `TOY_SIDEBAND` participates in
#: no ranking, which is the case §10.5.1 exists for.
TOY_TIER_A: Final = "TOY_TIER_A"
TOY_TIER_B: Final = "TOY_TIER_B"
TOY_SIDEBAND: Final = "TOY_SIDEBAND"
TOY_AUTHORITY_CLASSES: Final = (TOY_SIDEBAND, TOY_TIER_A, TOY_TIER_B)

TOY_RULE: Final = "TOY-RULE-001"

#: M3 / VER-008. The ToyDomain's OutcomeSpace and metric. CATEGORICAL, deliberately unlike the
#: Silicon Photonics pack's ordinal distance: VER-008's "two domains may register different
#: metrics and neither is core-supplied" needs two metrics that actually differ.
TOY_OUTCOME_SPACE: Final = "os:toy.widget_verdict"
TOY_OUTCOMES: Final = ("STIFF", "FLOPPY", "BROKEN")
TOY_METRIC: Final = "dm:toy.categorical_mismatch"


class ToyCategoricalMismatch:
    """0 when two predictions agree, 1 when they differ. No order, because the outcomes have none."""

    @property
    def declaration(self) -> DisagreementMetric:
        return DisagreementMetric(
            metric_id=TOY_METRIC,
            outcome_space_id=TOY_OUTCOME_SPACE,
            outcome_space_version="1.0.0",
            implementation_ref="tests.toy_domain:ToyCategoricalMismatch",
            version="1.0.0",
        )

    def distance(self, a: str, b: str) -> Decimal:
        return Decimal(0) if a == b else Decimal(1)


TOY_SPECIALIST: Final = SpecialistRole(
    role_id="toy.specialist.widgets",
    domain=TOY_DOMAIN,
    description="widget mechanics",
    prompt_id="prm:toy.specialist.widgets",
    prompt_version="1.0.0",
    prompt_template="You are the widget specialist.",
    evidence_domains=(TOY_DOMAIN,),
    focus_terms=("blip", "stiffness"),
)


class ToyConditionComparator:
    version: str = "1.0.0"

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        schema: ConditionSchemaRegistration,
    ) -> ConditionMatch:
        differing = sorted(
            field
            for field in schema.known_fields
            if field in left and field in right and left[field] != right[field]
        )
        shared = sorted(
            field
            for field in schema.known_fields
            if field in left and field in right and left[field] == right[field]
        )
        if differing:
            from lab_brain.core.models.condition import ConditionMismatch

            return ConditionMatch(
                state=ConditionMatchState.INCOMPATIBLE,
                mismatches=tuple(
                    ConditionMismatch(
                        field=field, left=left[field], right=right[field], reason="differs"
                    )
                    for field in differing
                ),
                tolerance_policy_version=self.version,
                schema_ref=schema.ref,
            )
        if not shared:
            return ConditionMatch(
                state=ConditionMatchState.UNKNOWN,
                unknowns=("(nothing comparable)",),
                tolerance_policy_version=self.version,
                schema_ref=schema.ref,
            )
        return ConditionMatch(
            state=ConditionMatchState.EXACT,
            matched_fields=tuple(shared),
            tolerance_policy_version=self.version,
            schema_ref=schema.ref,
        )


class ToyAuthority:
    policy_id: ClassVar[str] = "auth:toy_widgets"
    policy_version: ClassVar[str] = "1.0.0"
    authority_classes: ClassVar[tuple[str, ...]] = TOY_AUTHORITY_CLASSES
    _rank: ClassVar[dict[str, int]] = {TOY_TIER_B: 1, TOY_TIER_A: 2}

    def compare(self, a: str, b: str) -> AuthorityComparison:
        if a == b:
            return AuthorityComparison.EQUIVALENT
        if a not in self._rank or b not in self._rank:
            return AuthorityComparison.INCOMPARABLE
        if self._rank[a] == self._rank[b]:
            return AuthorityComparison.EQUIVALENT
        return (
            AuthorityComparison.STRONGER
            if self._rank[a] > self._rank[b]
            else AuthorityComparison.WEAKER
        )

    def meets(self, required_rule: str, candidate: str) -> bool:
        return self.compare(candidate, required_rule) in (
            AuthorityComparison.STRONGER,
            AuthorityComparison.EQUIVALENT,
        )


class ToySubject:
    """Anything at all. The toy validator takes whatever it is handed."""

    def __init__(self, subject_id: str, blips: int) -> None:
        self.subject_id = subject_id
        self.blips = blips


class ToyValidator:
    validator_id: ClassVar[str] = "validate_widget_blips"
    validator_version: ClassVar[str] = "1.0.0"

    def validate(self, subject: object) -> ValidationReport:
        blips = getattr(subject, "blips", None)
        status = (
            ValidationStatus.PASS
            if isinstance(blips, int) and blips >= 0
            else ValidationStatus.FAIL
        )
        return report(
            subject_type="TOY_WIDGET",
            subject_id=str(getattr(subject, "subject_id", "(unknown)")),
            validator_id=self.validator_id,
            validator_version=self.validator_version,
            findings=(
                ValidationFinding(
                    rule_id=TOY_RULE,
                    rule_version="1.0.0",
                    status=status,
                    message=f"blips={blips}",
                ),
            ),
        )


class ToyExtractor:
    """Uses the SHARED `ExtractionInput` / `ExtractionResult`, not a toy-specific pair.

    That is the load-bearing part of this fixture for the extension boundary: a second domain must
    be able to enter the same extraction vocabulary without core learning anything about widgets.
    """

    extractor_id: ClassVar[str] = "extract_widget_stiffness"
    extractor_version: ClassVar[str] = "1.0.0"
    required_series: ClassVar[tuple[str, ...]] = ("blip_count",)
    produces: ClassVar[tuple[str, ...]] = ("widget_stiffness",)

    def extract(self, payload: ExtractionInput) -> ExtractionResult:
        series = payload.series_named("blip_count")
        quantity = (
            ExtractedQuantity(name="widget_stiffness", status=FieldStatus.UNKNOWN)
            if series is None
            else ExtractedQuantity(
                name="widget_stiffness",
                value=sum(series.values, Decimal(0)),
                unit="blips",
                status=FieldStatus.DERIVED,
                normalization_basis="per_widget",
                method={"model": "sum", "extractor": self.extractor_id},
            )
        )
        return ExtractionResult(
            tool_id="DOM-TOY-TOOL-004",
            tool_version=self.extractor_version,
            source=payload.source,
            quantities=(quantity,),
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
        )

    @property
    def request_model(self) -> type[ExtractionInput]:
        return ExtractionInput

    @property
    def result_model(self) -> type[ExtractionResult]:
        return ExtractionResult

    def __call__(self, request: ToolRequest) -> ExtractionResult:
        assert isinstance(request, ExtractionInput)
        return self.extract(request)


class ToyBenchRequest(ToolRequest):
    widget_id: str


class ToyBenchResult(ToolResult):
    blips: int


class ToyBenchTool:
    @property
    def request_model(self) -> type[ToyBenchRequest]:
        return ToyBenchRequest

    @property
    def result_model(self) -> type[ToyBenchResult]:
        return ToyBenchResult

    def __call__(self, request: ToolRequest) -> ToyBenchResult:
        assert isinstance(request, ToyBenchRequest)
        return ToyBenchResult(tool_id="DOM-TOY-TOOL-001", tool_version="1.0.0", blips=3)


class ToyValidateRequest(ToolRequest):
    widget_id: str
    blips: int


class ToyValidateResult(ToolResult):
    report: ValidationReport


class ToyValidateTool:
    def __init__(self, validator: ToyValidator) -> None:
        self._validator = validator

    @property
    def request_model(self) -> type[ToyValidateRequest]:
        return ToyValidateRequest

    @property
    def result_model(self) -> type[ToyValidateResult]:
        return ToyValidateResult

    def __call__(self, request: ToolRequest) -> ToyValidateResult:
        assert isinstance(request, ToyValidateRequest)
        return ToyValidateResult(
            tool_id="DOM-TOY-TOOL-006",
            tool_version="1.0.0",
            report=self._validator.validate(ToySubject(request.widget_id, request.blips)),
        )


def estimate_toy_cost(params: Mapping[str, Any]) -> CostVector:
    return CostVector(wall_clock_s=1, license_seat_s=1)


class ToyDomainPack:
    """§24.3, for the methods M2 authorises. No core file names this class."""

    def __init__(self) -> None:
        self._validator = ToyValidator()
        self._extractor = ToyExtractor()

    @property
    def id(self) -> str:
        return TOY_DOMAIN

    @property
    def version(self) -> str:
        return TOY_VERSION

    def register_condition_schema(self, registry: ConditionSchemaRegistry) -> None:
        registration = ConditionSchemaRegistration(
            domain=TOY_DOMAIN,
            schema_id="widget_bench",
            version="1.0.0",
            comparator_version="1.0.0",
            json_schema={
                "type": "object",
                "required": ["widget_grade"],
                "properties": {"widget_grade": {"type": "string"}},
                "additionalProperties": False,
            },
        )
        registry.register_schema(registration)
        registry.register_comparator(TOY_DOMAIN, "widget_bench", ToyConditionComparator())

    def register_evidence_authority_policy(self, registry: AuthorityPolicyRegistry) -> None:
        registry.register(ToyAuthority())

    def register_backend_validity_schemas(self, registry: BackendValidityRegistry) -> None:
        registry.register(
            BackendValiditySchema(
                schema_id="widget_validity",
                version="1.0.0",
                domain=TOY_DOMAIN,
                required_fields=("bench_id", "bench_version"),
                optional_fields=("notes",),
            )
        )

    def register_validators(self, registry: ValidatorRegistry) -> None:
        registry.register(self._validator)

    def register_metric_extractors(self, registry: ExtractorRegistry) -> None:
        registry.register(self._extractor)

    def register_capabilities(self, registry: CapabilityRegistry) -> None:
        registry.register_estimator(TOY_COST_CONTRACT, estimate_toy_cost)
        registry.register_estimator(TOY_LOCAL_COST_CONTRACT, estimate_toy_cost)
        registry.register(
            Capability(
                capability_id=TOY_CAPABILITY,
                domain=TOY_DOMAIN,
                action_type=ActionType.MEASUREMENT,
                backend_id="toy.bench",
                produces=(TOY_OBSERVABLE_RAW,),
                authority_class=TOY_TIER_A,
                conditions_schema_version=TOY_SCHEMA_REF,
                license_constraints=(TOY_RESOURCE,),
                estimate_cost_contract=TOY_COST_CONTRACT,
                version="1.0.0",
            )
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.register(
            ToolDescriptor(
                tool_id="DOM-TOY-TOOL-001",
                name="run_widget_bench",
                tool_class=ToolClass.RUN,
                domain=TOY_DOMAIN,
                version="1.0.0",
                capability_id=TOY_CAPABILITY,
                conditions_schema_version=TOY_SCHEMA_REF,
                produces=(TOY_OBSERVABLE_RAW,),
                resource_id=TOY_RESOURCE,
            ),
            ToyBenchTool(),
        )
        registry.register(
            ToolDescriptor(
                tool_id="DOM-TOY-TOOL-004",
                name="extract_widget_stiffness",
                tool_class=ToolClass.EXTRACT,
                domain=TOY_DOMAIN,
                version="1.0.0",
                cost_contract=TOY_LOCAL_COST_CONTRACT,
                requires=(TOY_OBSERVABLE_RAW,),
                produces=(TOY_OBSERVABLE_METRIC,),
            ),
            self._extractor,
        )
        registry.register(
            ToolDescriptor(
                tool_id="DOM-TOY-TOOL-006",
                name="validate_widget_blips",
                tool_class=ToolClass.VALIDATE,
                domain=TOY_DOMAIN,
                version="1.0.0",
                cost_contract=TOY_LOCAL_COST_CONTRACT,
                requires=(TOY_OBSERVABLE_METRIC,),
                produces=(TOY_OBSERVABLE_REPORT,),
            ),
            ToyValidateTool(self._validator),
        )

    def register_benchmarks(self, registry: BenchmarkRegistry) -> None:
        registry.register("bench:toy.widgets", "tests/fixtures/toy_widgets/")

    def register_specialists(self, registry: SpecialistRegistry) -> None:
        registry.register(TOY_SPECIALIST)

    def register_disagreement_metrics(self, registry: DisagreementMetricRegistry) -> None:
        registry.declare_space(
            OutcomeSpace(
                outcome_space_id=TOY_OUTCOME_SPACE,
                version="1.0.0",
                domain=TOY_DOMAIN,
                action_type="MEASUREMENT",
                outcomes=TOY_OUTCOMES,
            )
        )
        registry.register(ToyCategoricalMismatch())


__all__ = [
    "TOY_AUTHORITY_CLASSES",
    "TOY_CAPABILITY",
    "TOY_COST_CONTRACT",
    "TOY_DOMAIN",
    "TOY_LOCAL_COST_CONTRACT",
    "TOY_OBSERVABLE_METRIC",
    "TOY_OBSERVABLE_RAW",
    "TOY_OBSERVABLE_REPORT",
    "TOY_RESOURCE",
    "TOY_RULE",
    "TOY_SCHEMA_REF",
    "TOY_SIDEBAND",
    "TOY_TIER_A",
    "TOY_TIER_B",
    "TOY_VALIDITY_REF",
    "TOY_VERSION",
    "ToyAuthority",
    "ToyBenchRequest",
    "ToyBenchResult",
    "ToyConditionComparator",
    "ToyDomainPack",
    "ToyExtractor",
    "ToySubject",
    "ToyValidateRequest",
    "ToyValidateResult",
    "ToyValidator",
    "estimate_toy_cost",
]
