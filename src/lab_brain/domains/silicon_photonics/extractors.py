"""`extract_cj_rs` — DOM-SP-TOOL-004, and the reason it is one tool (EVI-001, DOM-SP-002).

    §10.2.2  `extract_cj_rs` produces Cj_per_length and Rs_per_length in one contract, with shared
             units / normalization basis / bias / frequency conditions / extraction method.
             Splitting it would allow simulated and measured paths to diverge in normalization.
    EVI-001  Cj/Rs evidence 必須含 unit、normalization basis、bias/frequency conditions 與
             extraction method。
    DOM-SP-002  extractor 必須 backend-agnostic；simulation 與 measurement 共用定義與
             normalization provenance。

ONE CLASS, TWO MODALITIES, AND NO BRANCH ON WHICH. The method below never asks whether its input
came from a solver or an instrument, and that absence is the requirement rather than a
simplification: the moment `if source.is_simulated:` appears in an extraction path, the simulated
and measured definitions of Cj have started to diverge and nothing will report it. What the
extractor *does* carry through is `payload.source`, unchanged, so the result still knows which
modality produced it -- shared contract, distinct provenance.

THE MODEL IS DECLARED AND VERSIONED, NOT ASSUMED. A small-signal impedance can be reduced to a
capacitance in more than one way, and which reduction was used is part of what EVI-001 means by
"extraction method". This extractor declares the series-RC reduction

    Z(omega) = Rs + 1 / (j * omega * Cj)
      =>  Rs = Re(Z)
          Cj = -1 / (omega * Im(Z))          (Im(Z) < 0 for a capacitive device)

and records the model name, the formula, the frequency it was evaluated at and the constant it used
in `ExtractedQuantity.method`. A different reduction is a different extractor version, which is what
makes §6.18's contamination rollback able to quarantine one and not the other.

NORMALIZATION IS PER UNIT LENGTH, AND THE TWO QUANTITIES NORMALIZE IN OPPOSITE DIRECTIONS. For a
distributed junction the capacitance scales with length and the series resistance scales inversely,
so

    Cj_per_length = Cj_total / L        (fF/um)
    Rs_per_length = Rs_total * L        (ohm.um)

Getting that backwards produces numbers that look plausible and are not comparable between devices,
which is precisely the failure EVI-001's "normalization basis" clause exists to make visible. The
basis string travels with every value.

DECIMAL THROUGHOUT. `canonical_json` refuses floats because a value that rounds differently on two
machines cannot be hashed reproducibly; an extracted Cj that differs in the last place between a
re-run and the original makes "did the extraction change" unanswerable. `TWO_PI` is a declared
constant recorded in the method provenance rather than `math.pi`, so the arithmetic is exactly
reproducible and the precision used is part of the record.

NOTHING HERE IS A LAB VALUE. The formula is the textbook series-RC reduction and the tolerances are
declared thresholds; no measured device parameter, geometry or process assumption from any real
project appears in this file or in the fixtures that exercise it.
"""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from typing import ClassVar, Final

from lab_brain.core.models.condition import ConditionSchemaError
from lab_brain.core.models.enums import FieldStatus
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.tools.contracts import ToolRequest
from lab_brain.tools.extraction import (
    ExtractedQuantity,
    ExtractionContractError,
    ExtractionInput,
    ExtractionResult,
    missing_series,
)

TOOL_ID: Final = "DOM-SP-TOOL-004"
TOOL_NAME: Final = "extract_cj_rs"
EXTRACTOR_ID: Final = "extract_cj_rs"
EXTRACTOR_VERSION: Final = "1.0.0"

#: 2*pi to the working precision. Declared rather than computed from `math.pi` so the value that
#: produced a number is in the record: a future build linking a different libm would otherwise
#: change extracted values with nothing to point at.
TWO_PI: Final = Decimal("6.283185307179586476925286766559")

#: Working precision for the reduction. Fixed and recorded, for the same reason as TWO_PI.
PRECISION: Final = 28
#: Digits kept in the emitted value. Deliberately fewer than the working precision: the trailing
#: digits of a Decimal division are an artefact of the precision, not of the measurement, and
#: publishing them would invite a comparison that is really comparing rounding.
OUTPUT_DIGITS: Final = 9

#: The observables this extractor is asked for, and the series it needs to produce them.
CJ: Final = "Cj_per_length"
RS: Final = "Rs_per_length"
PRODUCES: Final[tuple[str, ...]] = (CJ, RS)

SERIES_FREQUENCY: Final = "frequency_hz"
SERIES_REAL: Final = "impedance_real_ohm"
SERIES_IMAG: Final = "impedance_imag_ohm"
REQUIRED_SERIES: Final[tuple[str, ...]] = (SERIES_REAL, SERIES_IMAG)

CJ_UNIT: Final = "fF/um"
RS_UNIT: Final = "ohm.um"
NORMALIZATION_BASIS: Final = "per_unit_device_length_um"

#: Farads -> femtofarads.
_FEMTO: Final = Decimal("1e15")


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _quantize(value: Decimal) -> Decimal:
    """Round to the declared output precision, half-even. Deterministic on every platform."""
    exponent = value.adjusted() - (OUTPUT_DIGITS - 1)
    return value.quantize(Decimal(1).scaleb(exponent))


class CjRsExtractor:
    """§10.2.1's `extract_*` contract for Cj and Rs. Backend-agnostic, by construction.

    Satisfies `lab_brain.tools.extraction.MetricExtractor`, which is the ONE protocol both
    modalities go through -- there is deliberately no simulated variant and no measured variant.

    THE CONDITION REGISTRY IS A REQUIRED DEPENDENCY, not an optional one, and the reason is the
    same one that made `DiagnosticsService.actor_of` required: an optional check is not a check.
    EVI-001 requires the bias/frequency conditions to be present, the registered schema
    `silicon_photonics/pn_junction_ac@1.0.0` is what declares which fields those are, and an
    extractor constructed without a registry could only skip the check. So it is a constructor
    argument with no default, and `test_the_extractor_cannot_be_built_without_a_condition_registry`
    fails if that changes.
    """

    extractor_id: ClassVar[str] = EXTRACTOR_ID
    extractor_version: ClassVar[str] = EXTRACTOR_VERSION
    required_series: ClassVar[tuple[str, ...]] = REQUIRED_SERIES
    produces: ClassVar[tuple[str, ...]] = PRODUCES

    def __init__(self, conditions: ConditionSchemaRegistry) -> None:
        self._conditions = conditions

    def extract(self, payload: ExtractionInput) -> ExtractionResult:
        """Reduce one impedance sample to Cj and Rs, normalized and provenanced.

        TWO KINDS OF ABSENCE, AND THEY GET DIFFERENT ANSWERS. The distinction is EVI-001 against
        EVI-002 and it is the whole shape of this method:

            a missing scientific VALUE            -> UNKNOWN, with a warning. EVI-002 forbids
              (no impedance series, a reactance      filling an absent field with a typical value,
               the series-RC model cannot           and `ExtractedQuantity` refuses to pair
               reduce)                              UNKNOWN with a number so the two cannot be
                                                    confused.
            missing condition PROVENANCE          -> REFUSED. EVI-001 requires unit, normalization
              (no `bias_v`, no `frequency_hz`,       basis, bias/frequency conditions and extraction
               no `device_length_um`, an             method TOGETHER; a DERIVED value whose
               undeclared field, an unregistered     conditions are absent is not a weaker result,
               schema version)                       it is a number nobody can compare to another
                                                    laboratory's. T-EVI-001 says "admission fail".

        Returning UNKNOWN for the second would conflate them, and the conflation is the direction
        that matters: it would let a sweep with no recorded bias produce a well-formed record whose
        only defect is invisible.
        """
        # EVI-001's condition half, against the REGISTERED schema rather than a second list kept
        # here. `validate` refuses a malformed reference, an unregistered version, a missing
        # required field and an undeclared field -- all four, in one place, and the DomainPack's
        # registration is the source of truth for which fields those are (§24.1).
        self._require_conditions(payload)

        warnings: list[str] = []
        absent = missing_series(self, payload)
        warnings.extend(f"series {name!r} was not supplied" for name in absent)

        conditions = payload.source.conditions
        length = _decimal(conditions.get("device_length_um"))
        # NO RECOVERY FROM THE SERIES. An earlier version fell back to the `frequency_hz` array
        # when the condition record omitted it, which silently manufactured the provenance EVI-001
        # requires be recorded: the arrays say what the instrument swept, the conditions say what
        # the record claims about it, and substituting one for the other means a sweep with no
        # declared frequency produces a Cj that looks fully conditioned.
        frequency = _decimal(conditions.get("frequency_hz"))

        real = payload.series_named(SERIES_REAL)
        imag = payload.series_named(SERIES_IMAG)

        blockers: list[str] = list(absent)
        if length is None or length <= 0:
            blockers.append("condition 'device_length_um' is present but not a positive number")
        if frequency is None or frequency <= 0:
            blockers.append("condition 'frequency_hz' is present but not a positive number")

        if blockers:
            warnings.extend(blockers)
            return self._unknown(payload, tuple(warnings), reason="; ".join(sorted(set(blockers))))

        assert length is not None and frequency is not None  # guarded above
        assert real is not None and imag is not None  # `absent` was empty

        with localcontext() as context:
            context.prec = PRECISION
            rs_total = real.values[0]
            reactance = imag.values[0]

            rs_quantity = ExtractedQuantity(
                name=RS,
                value=_quantize(rs_total * length),
                unit=RS_UNIT,
                status=FieldStatus.DERIVED,
                normalization_basis=NORMALIZATION_BASIS,
                method=self._method(
                    formula="Rs_per_length = Re(Z) * device_length_um",
                    frequency=frequency,
                    length=length,
                ),
            )

            if reactance >= 0:
                # A non-negative reactance is not capacitive, so the series-RC reduction does not
                # apply. UNKNOWN rather than a negative capacitance: EVI-002, and a negative Cj
                # would propagate as a plausible-looking number into every comparison.
                warnings.append(
                    f"reactance {reactance} is not negative, so the series-RC reduction does not "
                    "describe this sample; Cj is not derivable from it"
                )
                cj_quantity = ExtractedQuantity(name=CJ, status=FieldStatus.UNKNOWN)
            else:
                try:
                    cj_farad = Decimal(-1) / (TWO_PI * frequency * reactance)
                except (DivisionByZero, InvalidOperation):  # pragma: no cover - guarded above
                    cj_quantity = ExtractedQuantity(name=CJ, status=FieldStatus.UNKNOWN)
                else:
                    cj_quantity = ExtractedQuantity(
                        name=CJ,
                        value=_quantize(cj_farad * _FEMTO / length),
                        unit=CJ_UNIT,
                        status=FieldStatus.DERIVED,
                        normalization_basis=NORMALIZATION_BASIS,
                        method=self._method(
                            formula="Cj_per_length = -1 / (2*pi*f*Im(Z)) / device_length_um",
                            frequency=frequency,
                            length=length,
                        ),
                    )

        return ExtractionResult(
            tool_id=TOOL_ID,
            tool_version=EXTRACTOR_VERSION,
            source=payload.source,
            quantities=(cj_quantity, rs_quantity),
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            warnings=tuple(warnings),
        )

    # -- the tool-registry face ---------------------------------------------
    #
    # `ToolImplementation` is what `ToolRegistry.invoke` type-checks against; `MetricExtractor` is
    # what a DomainPack registers. Both are satisfied by the same object on purpose: two adapters
    # around one reduction is how the registry path and the direct path start to differ.

    @property
    def request_model(self) -> type[ExtractionInput]:
        return ExtractionInput

    @property
    def result_model(self) -> type[ExtractionResult]:
        return ExtractionResult

    def __call__(self, request: ToolRequest) -> ExtractionResult:
        """Widened to `ToolRequest` because `ToolImplementation.__call__` is.

        A narrower parameter would not satisfy the protocol -- arguments are contravariant -- and
        the registry would then accept this object only through `Any`, which is the type check
        SIM-003 is asking for being skipped at the one boundary it exists to guard. The registry
        has already verified the concrete type against `request_model`; the assert records that.
        """
        assert isinstance(request, ExtractionInput)
        return self.extract(request)

    # -- internals -----------------------------------------------------------

    def _require_conditions(self, payload: ExtractionInput) -> None:
        """EVI-001's condition clause, delegated to the registered schema.

        DELEGATED, NOT DUPLICATED. `silicon_photonics/pn_junction_ac@1.0.0` already declares
        `bias_v`, `frequency_hz` and `device_length_um` as required; a second list here would be
        two statements of one contract, and they would be corrected separately. The registry also
        supplies the two refusals a hand-written list would miss -- an undeclared field, and a
        version nobody registered.
        """
        source = payload.source
        try:
            self._conditions.validate(source.conditions, source.conditions_schema_version)
        except ConditionSchemaError as invalid:
            raise ExtractionContractError(
                f"{self.extractor_id} cannot produce Cj/Rs from source "
                f"{source.provenance_ref} under {source.conditions_schema_version}: {invalid}. "
                "EVI-001 requires unit, normalization basis, "
                "bias/frequency conditions and extraction method together -- a DERIVED value whose "
                "condition provenance is absent is not a weaker result, it is a number nobody can "
                "compare to another laboratory's (T-EVI-001: admission fail)"
            ) from invalid

    def _method(self, *, formula: str, frequency: Decimal, length: Decimal) -> dict[str, object]:
        """EVI-001's extraction method, structured so it can be compared rather than read."""
        return {
            "model": "series_rc",
            "formula": formula,
            "frequency_hz": str(frequency),
            "device_length_um": str(length),
            "two_pi": str(TWO_PI),
            "precision": PRECISION,
            "output_digits": OUTPUT_DIGITS,
            "extractor": f"{self.extractor_id}@{self.extractor_version}",
        }

    def _unknown(
        self, payload: ExtractionInput, warnings: tuple[str, ...], *, reason: str
    ) -> ExtractionResult:
        """Both quantities UNKNOWN, with the reason in the warnings. EVI-002's honest answer."""
        return ExtractionResult(
            tool_id=TOOL_ID,
            tool_version=EXTRACTOR_VERSION,
            source=payload.source,
            quantities=(
                ExtractedQuantity(name=CJ, status=FieldStatus.UNKNOWN),
                ExtractedQuantity(name=RS, status=FieldStatus.UNKNOWN),
            ),
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            warnings=(*warnings, f"extraction not attempted: {reason}"),
        )


__all__ = [
    "CJ",
    "CJ_UNIT",
    "EXTRACTOR_ID",
    "EXTRACTOR_VERSION",
    "NORMALIZATION_BASIS",
    "OUTPUT_DIGITS",
    "PRECISION",
    "PRODUCES",
    "REQUIRED_SERIES",
    "RS",
    "RS_UNIT",
    "SERIES_IMAG",
    "SERIES_REAL",
    "TOOL_ID",
    "TOOL_NAME",
    "TWO_PI",
    "CjRsExtractor",
]
