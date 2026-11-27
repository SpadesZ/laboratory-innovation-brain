"""The DomainPack protocol, and the registries a pack is allowed to write into (§24.3, EXT-001).

    §24.5 / EXT-001  在不修改 core models、core repositories 與 orchestration state machine 的
                     前提下，加入一個 ToyDomain 或第二個真實 domain，並能註冊 condition schema、
                     validator、tool 與 benchmark。若必須修改 core 才能加入第二 domain，代表
                     extension boundary 失敗。

WHAT A PACK MAY DO, AND WHY THE LIST IS SHORT. §24.3 declares nineteen `register_*` / decision
methods. This protocol declares the subset M2 authorised -- condition schema, authority policy,
backend validity, validators, metric extractors, capabilities, tools -- plus the two M3 authorises:
`register_specialists` (§7.1's "N Domain Specialists", §26.1's "selected Domain Specialists") and
`register_disagreement_metrics` (VER-008) -- and the one M4 authorises: `register_workflows`
(§24.3), how a planned Capability becomes typed tool calls (`lab_brain.verification.workflows`).
§24.3's `declared_outcome_space(action, hypothesis)` and `disagreement_metric(outcome_space)` are
answered by the registries rather than by new pack methods: the space an action's outcome is read
in is the one the hypothesis's admitted Prediction is bound to and the pack declared through
`register_disagreement_metrics`, and the metric is `DisagreementMetricRegistry.for_space`. A pack
method returning the same object would be a second source for one answer. OutcomeSpaces reach the
registry through `register_disagreement_metrics`, because a metric is bound to one and they are
declared together.

`DomainRegistries` IS THE WHOLE EXTENSION SURFACE. A pack receives it, writes into it, and has no
other way in: it is handed no repository, no connection, no store and no projection. That is the
structural form of §24.1's "Core MUST NOT know" column -- a pack cannot write an Attestation, mint
a Run, mutate an EpistemicState or bypass admission, because it is never given anything that could.

    §24.2  FORBIDDEN:  core -> domains.silicon_photonics
                       evidence generic layer -> ring-specific constants
                       orchestration -> direct CHARGE/MODE imports

Enforced by `tests/unit/test_extension_boundary.py`, which parses the import graph. A rule stated
in prose and checked by review is a rule that holds until the week somebody is busy.

THE PACK IS NOT TRUSTED, IT IS CONSTRAINED. `install` does not merely call the pack's methods and
believe the result: `AuthorityPolicyRegistry.register` verifies §10.5.1's order laws, `ToolRegistry`
verifies §10.2.1's prefix contracts, `CapabilityRegistry` refuses a capability with no estimator,
and `BackendValidityRegistry` refuses a schema that requires nothing. A pack that registered
nonsense would be refused at install rather than discovered at a belief transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from lab_brain.core.authority import AuthorityPolicyRegistry
from lab_brain.core.models.validation import ValidationReport
from lab_brain.core.specialists import SpecialistRegistry, SpecialistRole
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.tools.extraction import MetricExtractor
from lab_brain.tools.registry import ToolRegistry
from lab_brain.tools.simulation import BackendValidityRegistry
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.disagreement import DisagreementMetricRegistry
from lab_brain.verification.workflows import WorkflowRegistry


class DomainInstallError(RuntimeError):
    """A DomainPack could not be installed as declared."""


@runtime_checkable
class DomainValidator(Protocol):
    """§17.19.2: a DomainPack validator returns a ValidationReport, never a bool or a string."""

    @property
    def validator_id(self) -> str: ...

    @property
    def validator_version(self) -> str: ...

    def validate(self, subject: object) -> ValidationReport: ...


class ValidatorRegistry:
    """Named validators, keyed by id. Refuses one that does not return a report.

    The check is at registration and it is a real one: a callable is invoked against nothing here,
    so what can be verified is the declared shape -- that the object satisfies `DomainValidator`
    and that its id and version are non-empty. The *return* type is verified by
    `ToolRegistry.register` for `validate_*` tools, where the result model is declared.
    """

    def __init__(self) -> None:
        self._validators: dict[str, DomainValidator] = {}

    def register(self, validator: DomainValidator) -> DomainValidator:
        if not isinstance(validator, DomainValidator):
            raise DomainInstallError(
                f"{validator!r} is not a DomainValidator: §17.19.2 requires a domain validator to "
                "expose validator_id, validator_version and validate() -> ValidationReport. A "
                "validator that returns a bare bool cannot name the rule that failed, so a "
                "VALIDITY_CONFLICT opened from it is one nobody can close"
            )
        if not validator.validator_id or not validator.validator_version:
            raise DomainInstallError(
                f"{validator!r} declares an empty id or version. DOM-SP-001 requires the rule "
                "version to be recorded; an unversioned validator makes a past report "
                "un-recheckable"
            )
        existing = self._validators.get(validator.validator_id)
        if existing is not None and existing is not validator:
            raise DomainInstallError(
                f"a different validator is already registered as {validator.validator_id}"
            )
        self._validators[validator.validator_id] = validator
        return validator

    def resolve(self, validator_id: str) -> DomainValidator:
        found = self._validators.get(validator_id)
        if found is None:
            raise DomainInstallError(
                f"no validator is registered as {validator_id!r}. Core ships none -- §24.1 puts "
                "physical validators in the DomainPack column -- so there is nothing to fall back "
                "to"
            )
        return found

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))

    def __len__(self) -> int:
        return len(self._validators)


class ExtractorRegistry:
    """Metric extractors, keyed by id. One protocol for simulated and measured (DOM-SP-002)."""

    def __init__(self) -> None:
        self._extractors: dict[str, MetricExtractor] = {}

    def register(self, extractor: MetricExtractor) -> MetricExtractor:
        if not isinstance(extractor, MetricExtractor):
            raise DomainInstallError(
                f"{extractor!r} does not satisfy MetricExtractor. There is one extractor protocol "
                "and both modalities go through it; a second protocol would make 'the same "
                "extractor contract' a claim about two things (DOM-SP-002)"
            )
        existing = self._extractors.get(extractor.extractor_id)
        if existing is not None and existing is not extractor:
            raise DomainInstallError(
                f"a different extractor is already registered as {extractor.extractor_id}. §6.18's "
                "contamination rollback selects by extractor version, so two implementations "
                "under one id make a quarantine incomplete in a way nothing reports"
            )
        self._extractors[extractor.extractor_id] = extractor
        return extractor

    def resolve(self, extractor_id: str) -> MetricExtractor:
        found = self._extractors.get(extractor_id)
        if found is None:
            raise DomainInstallError(f"no extractor is registered as {extractor_id!r}")
        return found

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._extractors))

    def __len__(self) -> int:
        return len(self._extractors)


class BenchmarkRegistry:
    """Named benchmark sets a pack declares. Identity and fixture location only.

    Deliberately thin. §15's benchmark *machinery* -- BenchmarkPolicy, calibration, thresholds --
    is LLM-002 in M3, and building it here would be claiming an M3 requirement. What EXT-001 needs
    is that a pack can register a benchmark at all, which is this.
    """

    def __init__(self) -> None:
        self._benchmarks: dict[str, str] = {}

    def register(self, benchmark_id: str, fixture_ref: str) -> None:
        if not benchmark_id or not fixture_ref:
            raise DomainInstallError("a benchmark needs an id and a fixture reference")
        existing = self._benchmarks.get(benchmark_id)
        if existing is not None and existing != fixture_ref:
            raise DomainInstallError(
                f"benchmark {benchmark_id} is already registered against {existing!r}. §26's M4 "
                "gate requires a FIXED benchmark set; repointing one at a different fixture is "
                "how a benchmark stops being fixed"
            )
        self._benchmarks[benchmark_id] = fixture_ref

    def fixture_for(self, benchmark_id: str) -> str:
        found = self._benchmarks.get(benchmark_id)
        if found is None:
            raise DomainInstallError(f"no benchmark is registered as {benchmark_id!r}")
        return found

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._benchmarks))

    def __len__(self) -> int:
        return len(self._benchmarks)


@dataclass
class DomainRegistries:
    """Everything a DomainPack may write into, and nothing else.

    THE ABSENCES ARE THE DESIGN. There is no repository here, no connection, no admission gate and
    no belief-event store. A pack physically cannot write an Attestation, mint a Run or mutate an
    EpistemicStateProjection, because it is never handed anything that could -- which is §24.1's
    "Core MUST NOT know" column enforced by what is reachable rather than by what is documented.
    """

    conditions: ConditionSchemaRegistry = field(default_factory=ConditionSchemaRegistry)
    authority: AuthorityPolicyRegistry = field(default_factory=AuthorityPolicyRegistry)
    backend_validity: BackendValidityRegistry = field(default_factory=BackendValidityRegistry)
    validators: ValidatorRegistry = field(default_factory=ValidatorRegistry)
    extractors: ExtractorRegistry = field(default_factory=ExtractorRegistry)
    capabilities: CapabilityRegistry = field(default_factory=CapabilityRegistry)
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    benchmarks: BenchmarkRegistry = field(default_factory=BenchmarkRegistry)
    #: M3. §7.1's Domain Specialists and VER-008's metrics (with the OutcomeSpaces they bind to).
    specialists: SpecialistRegistry = field(default_factory=SpecialistRegistry)
    disagreement_metrics: DisagreementMetricRegistry = field(
        default_factory=DisagreementMetricRegistry
    )
    #: M4. §24.3's `register_workflows`: capability id -> how it is executed.
    workflows: WorkflowRegistry = field(default_factory=WorkflowRegistry)


@runtime_checkable
class DomainPack(Protocol):
    """§24.3's protocol, restricted to the methods M2 authorises. See the module docstring.

    Every method takes the registry it writes into, exactly as §24.3 declares
    (`register_condition_schema(self, registry)`), rather than returning a payload core then
    installs. That direction matters: a pack that *returned* schemas would let core decide what to
    do with them, and "what to do with a domain's condition schema" is the thing core must not
    know.
    """

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def register_condition_schema(self, registry: ConditionSchemaRegistry) -> None: ...

    def register_evidence_authority_policy(self, registry: AuthorityPolicyRegistry) -> None: ...

    def register_backend_validity_schemas(self, registry: BackendValidityRegistry) -> None: ...

    def register_validators(self, registry: ValidatorRegistry) -> None: ...

    def register_metric_extractors(self, registry: ExtractorRegistry) -> None: ...

    def register_capabilities(self, registry: CapabilityRegistry) -> None: ...

    def register_tools(self, registry: ToolRegistry) -> None: ...

    def register_benchmarks(self, registry: BenchmarkRegistry) -> None: ...

    def register_specialists(self, registry: SpecialistRegistry) -> None: ...

    def register_disagreement_metrics(self, registry: DisagreementMetricRegistry) -> None: ...

    def register_workflows(self, registry: WorkflowRegistry) -> None: ...


__all__ = [
    "BenchmarkRegistry",
    "DomainInstallError",
    "DomainPack",
    "DomainRegistries",
    "DomainValidator",
    "ExtractorRegistry",
    "SpecialistRegistry",
    "SpecialistRole",
    "ValidatorRegistry",
]
