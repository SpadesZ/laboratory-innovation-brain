"""The one extractor boundary simulated and measured evidence both enter through (DOM-SP-002).

    M2 exit gate  simulated + measured fixtures use the same extractor contract
    DOM-SP-002    Cj/Rs/Q/ER 等 extractor 必須 backend-agnostic；simulation 與 measurement
                  共用定義與 normalization provenance。
    §10.2.1       extract_*  backend-agnostic; consumes typed arrays + conditions; produces
                  metrics with normalization basis and method provenance. MUST accept both
                  simulated and measured fixtures.

"THE SAME CONTRACT" HAS TO BE STRUCTURAL OR IT IS NOTHING. Two extractors that return dictionaries
of the same shape satisfy every test anyone writes against the shape, and then one of them is
corrected and the other is not. §10.2.2 says so directly about this tool: "Splitting it would
allow simulated and measured paths to diverge in normalization". So there is ONE `ExtractionInput`,
ONE `ExtractionResult`, ONE `MetricExtractor` protocol, and the simulated and measured paths differ
in the *values* they carry -- never in the types.

AND YET `SIMULATED != MEASURED`. Uniformity of interface must not become uniformity of provenance:
a shared contract that erased where the numbers came from would make §10.6's SIM_TO_REAL_CONFLICT
undetectable, because there would be no two things to disagree. So `ExtractionSource.modality`
carries the canonical `EpistemicType` and every result keeps it, and:

    SIMULATED  MUST name the Run it came from, and MUST carry a backend-validity payload and the
               schema that payload conforms to (SIM-001). A solver result with no validity record
               cannot be promoted to formal evidence.
    MEASURED   MUST name the source Artifact the instrument produced. It may name a Run -- a
               measurement executed through a Job is a Run like any other -- but it is the
               artifact that is the primary record.

Those are different obligations under one contract, which is exactly the point: the contract is
shared, the provenance is not.

WHY THE VOCABULARY IS `EpistemicType` AND NOT A NEW ENUM. A parallel `SourceModality` would be a
second vocabulary for the distinction §17.2 already owns, and `Attestation.epistemic_type` is what
admission reads. Two enums meaning the same thing is how a record ends up SIMULATED on one side of
a boundary and MEASURED on the other.

NOTHING HERE NAMES A PHYSICAL QUANTITY. `Cj_per_length` is a string a DomainPack supplies; this
module knows that quantities have units, a normalization basis and a method, which is EVI-001's
shape and not silicon photonics' content (§24.1).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from lab_brain.core.models.attestation import EvidenceField
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.condition import ConditionSchemaRef
from lab_brain.core.models.enums import EpistemicType, FieldStatus
from lab_brain.tools.contracts import ToolRequest, ToolResult

#: The two modalities this boundary accepts, in the canonical §17.2 vocabulary.
#:
#: Deliberately the same frozenset the admission gate calls `REFERENCE_REQUIRED_TYPES`, and for the
#: same reason: these are the two epistemic types that assert something was *done*, so they are the
#: two that owe a reference to what did it (EVI-009).
EXTRACTABLE_MODALITIES: frozenset[EpistemicType] = frozenset(
    {EpistemicType.SIMULATED, EpistemicType.MEASURED}
)


class ExtractionContractError(ValueError):
    """An extraction input or result does not satisfy the shared contract."""


class NumericalSeries(CoreModel):
    """One named, united array of values, as handed to an extractor.

    ``Decimal``, not ``float``, and it is not fussiness. §9.4 already refuses float money for the
    reason that matters here too: a value that rounds differently on two machines is not
    reproducible, and an extracted Cj that differs in the last place between a re-run and the
    original makes "did the extraction change" unanswerable. `canonical_json` refuses floats
    outright for the same reason, so a float here would be a value that cannot reach a bundle hash.

    NOT PERSISTED AS A SERIES. §17.4 stores arrays by reference (`numerical_array_refs`); this is
    the in-flight payload between a backend (or a parsed instrument file) and an extractor.
    """

    name: str
    unit: str
    values: tuple[Decimal, ...]

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if not self.values:
            raise ExtractionContractError(
                f"series {self.name!r} is empty; an extractor handed no samples would have to "
                "either invent a value or return UNKNOWN, and only one of those is honest -- so "
                "the empty case is refused at the boundary rather than left to each extractor"
            )
        return self


class ExtractionSource(CoreModel):
    """Where the arrays came from, and the half of the contract that is NOT shared.

    Every field here survives into the `ExtractionResult`, which is what lets an Attestation built
    from an extraction satisfy EVI-009 without the extractor knowing what EVI-009 is.
    """

    #: SIMULATED or MEASURED. Refused otherwise -- see the module docstring.
    modality: EpistemicType
    #: §17.4's Run. Required for SIMULATED.
    run_id: str | None = None
    #: The instrument/source Artifact. Required for MEASURED.
    source_artifact_id: str | None = None
    project_id: str

    #: The solver for a simulation, the instrument for a measurement. One field, because from the
    #: extractor's side they are the same fact: *which apparatus produced these numbers*.
    backend_id: str
    backend_version: str

    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str

    #: SIM-001. The `BackendValidity` payload and the schema it conforms to. Required for
    #: SIMULATED; a measurement's calibration record is the same shape and is optional here
    #: because §17.10 makes backend validity a DomainPack concern and only the simulated side is
    #: made mandatory by SIM-001's text.
    backend_validity_schema: str | None = None
    backend_validity: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _provenance_matches_the_modality(self) -> Self:
        if self.modality not in EXTRACTABLE_MODALITIES:
            raise ExtractionContractError(
                f"extraction source declares modality {self.modality.value}; the shared extractor "
                f"contract accepts only {sorted(m.value for m in EXTRACTABLE_MODALITIES)}. An "
                "INFERRED or REPORTED payload entering here would acquire a normalization "
                "provenance it never had (EVI-003)"
            )
        ConditionSchemaRef.parse(self.conditions_schema_version)

        if self.modality is EpistemicType.SIMULATED:
            if self.run_id is None:
                raise ExtractionContractError(
                    "a SIMULATED extraction source names no run_id. §17.4 records one manifest per "
                    "execution and EVI-009 refuses simulated evidence that cannot trace to it; a "
                    "solver output with no Run is a number with a label"
                )
            if not self.backend_validity or self.backend_validity_schema is None:
                raise ExtractionContractError(
                    "a SIMULATED extraction source carries no backend validity and/or names no "
                    "schema for it. SIM-001 refuses to promote a run manifest missing "
                    "solver/project/conditions/validity to formal evidence, and an empty validity "
                    "payload is the missing case rather than a permissive one"
                )
        if self.modality is EpistemicType.MEASURED and self.source_artifact_id is None:
            raise ExtractionContractError(
                "a MEASURED extraction source names no source_artifact_id. The instrument's own "
                "record is the primary evidence for a measurement, and EVI-009 refuses one that "
                "cannot be traced to it"
            )
        return self

    @property
    def is_simulated(self) -> bool:
        return self.modality is EpistemicType.SIMULATED

    @property
    def provenance_ref(self) -> str:
        """The single reference an Attestation built from this must carry (EVI-009)."""
        reference = self.run_id if self.is_simulated else self.source_artifact_id
        assert reference is not None  # guaranteed by `_provenance_matches_the_modality`
        return reference


class ExtractionInput(ToolRequest):
    """What every `extract_*` tool is invoked with. One type, both modalities.

    A `ToolRequest`, so it goes through `ToolRegistry.invoke` like everything else (SIM-003) and
    inherits `project_id` / `trace_id`.
    """

    source: ExtractionSource
    series: tuple[NumericalSeries, ...]

    @model_validator(mode="after")
    def _series_are_distinct_and_the_project_agrees(self) -> Self:
        names = [series.name for series in self.series]
        if len(set(names)) != len(names):
            raise ExtractionContractError(
                f"extraction input repeats a series name: {sorted(names)}. An extractor resolving "
                "a name would silently take whichever copy it reached first"
            )
        if self.source.project_id != self.project_id:
            raise ExtractionContractError(
                f"extraction input is for project {self.project_id} but its source belongs to "
                f"{self.source.project_id}; resolving provenance across projects is how evidence "
                "inherits authority it was never granted (SEC-002)"
            )
        return self

    def series_named(self, name: str) -> NumericalSeries | None:
        return next((series for series in self.series if series.name == name), None)

    @property
    def series_names(self) -> frozenset[str]:
        return frozenset(series.name for series in self.series)


class ExtractedQuantity(CoreModel):
    """One metric, with everything EVI-001 requires around it.

        EVI-001  Cj/Rs evidence 必須含 unit、normalization basis、bias/frequency conditions 與
                 extraction method。

    Three of the four are fields here; the conditions are on the `ExtractionSource` because they
    describe the whole extraction rather than one quantity, and duplicating them per quantity would
    let two metrics from one sweep disagree about the bias they were taken at.

    ``status`` is `FieldStatus`, so "we could not compute this" is expressible. EVI-002 forbids
    inventing a plausible value, and an extractor with nowhere to say UNKNOWN is an extractor that
    has to.
    """

    name: str
    value: Decimal | None = None
    unit: str | None = None
    status: FieldStatus
    #: EVI-001. What the value is normalized against -- per unit length, per unit area, absolute.
    #: A Cj with no normalization basis is not comparable to another Cj, which is the whole
    #: purpose of extracting it.
    normalization_basis: str | None = None
    #: EVI-001. How it was computed, structured rather than prose so a DomainPack can version it.
    method: dict[str, Any] = Field(default_factory=dict)
    locator: str | None = None

    @model_validator(mode="after")
    def _absent_values_carry_nothing_and_present_ones_carry_everything(self) -> Self:
        absent = self.status in {FieldStatus.UNKNOWN, FieldStatus.NOT_REPORTED}
        if absent and self.value is not None:
            raise ExtractionContractError(
                f"quantity {self.name!r} is {self.status.value} and carries value {self.value}; "
                "EVI-002 requires an absent field to stay empty rather than be filled with a "
                "typical value"
            )
        if not absent and self.value is None:
            raise ExtractionContractError(
                f"quantity {self.name!r} is {self.status.value} with no value; a present status "
                "over nothing is the same claim as UNKNOWN made less legibly"
            )
        if not absent:
            missing = [
                label
                for label, present in (
                    ("unit", self.unit is not None),
                    ("normalization_basis", self.normalization_basis is not None),
                    ("extraction method", bool(self.method)),
                )
                if not present
            ]
            if missing:
                raise ExtractionContractError(
                    f"quantity {self.name!r} has a value but no {', '.join(missing)}. EVI-001 "
                    "requires unit, normalization basis, conditions and extraction method "
                    "together -- a number missing any one of them cannot be compared to another "
                    "laboratory's, which is the only reason to extract it"
                )
        return self

    def as_evidence_field(self) -> EvidenceField:
        """§17.9's per-field record, so an Attestation can carry this without a second conversion.

        `derivation` is the extraction method rendered deterministically: `EvidenceField` refuses a
        DERIVED field with no derivation, and a metric computed from an array is derived by
        definition.
        """
        derivation = (
            ", ".join(f"{key}={self.method[key]}" for key in sorted(self.method))
            if self.method
            else None
        )
        return EvidenceField(
            name=self.name,
            value=self.value,
            unit=self.unit,
            status=self.status,
            locator=self.locator,
            derivation=derivation if self.status is FieldStatus.DERIVED else None,
        )


class ExtractionResult(ToolResult):
    """What every `extract_*` tool returns. One type, both modalities, provenance intact."""

    source: ExtractionSource
    quantities: tuple[ExtractedQuantity, ...]
    extractor_id: str
    extractor_version: str

    @model_validator(mode="after")
    def _quantities_are_distinct(self) -> Self:
        names = [quantity.name for quantity in self.quantities]
        if len(set(names)) != len(names):
            raise ExtractionContractError(
                f"extraction result repeats a quantity name: {sorted(names)}"
            )
        if not names:
            raise ExtractionContractError(
                "extraction result declares no quantities; an extractor that produced nothing "
                "should say so with UNKNOWN entries, so the caller can tell 'not present' from "
                "'not attempted'"
            )
        return self

    def quantity(self, name: str) -> ExtractedQuantity | None:
        return next((q for q in self.quantities if q.name == name), None)

    @property
    def modality(self) -> EpistemicType:
        """SIMULATED or MEASURED. Never erased by the shared contract."""
        return self.source.modality

    def evidence_fields(self) -> dict[str, EvidenceField]:
        """§17.9 field states, keyed by name, ready for an `Attestation`."""
        return {q.name: q.as_evidence_field() for q in self.quantities}


@runtime_checkable
class MetricExtractor(Protocol):
    """§10.2.1's `extract_*` contract, as a type.

    ONE PROTOCOL FOR BOTH MODALITIES. There is deliberately no `SimulatedExtractor` and no
    `MeasuredExtractor`: the moment two protocols exist, "the same extractor contract" is a claim
    about two things rather than a property of one, and DOM-SP-002's paired fixtures would be
    testing that two implementations currently agree.
    """

    @property
    def extractor_id(self) -> str: ...

    @property
    def extractor_version(self) -> str: ...

    #: Series names this extractor needs. Declared so a missing input is a refusal at the boundary
    #: rather than an exception from inside arithmetic.
    @property
    def required_series(self) -> tuple[str, ...]: ...

    @property
    def produces(self) -> tuple[str, ...]: ...

    def extract(self, payload: ExtractionInput) -> ExtractionResult: ...


def missing_series(extractor: MetricExtractor, payload: ExtractionInput) -> tuple[str, ...]:
    """Declared inputs the payload does not supply. Sorted, so the message is deterministic."""
    return tuple(sorted(set(extractor.required_series) - payload.series_names))


__all__ = [
    "EXTRACTABLE_MODALITIES",
    "ExtractedQuantity",
    "ExtractionContractError",
    "ExtractionInput",
    "ExtractionResult",
    "ExtractionSource",
    "MetricExtractor",
    "NumericalSeries",
    "missing_series",
]
