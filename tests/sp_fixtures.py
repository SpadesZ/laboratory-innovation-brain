"""Shared, synthetic, deterministic M2 fixtures.

EVERY NUMBER HERE IS INVENTED FOR LEGIBILITY. None of it is measured, none of it is transcribed
from a real project, and none of it encodes a device, a geometry or a process. The fixtures are
round decimals chosen so that a test can predict the extractor's output exactly, which is what
makes a round-trip assertion meaningful rather than a comparison against a previously-recorded
number.

THE PAIRED FIXTURES ARE THE POINT. `simulated_input` and `measured_input` build the SAME
`ExtractionInput` type with the SAME series names and the SAME conditions, differing only in
`ExtractionSource` -- which is exactly the M2 exit gate's "simulated + measured fixtures use the
same extractor contract", written so that the two cannot drift: they call one builder.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from lab_brain.core.models.enums import EpistemicType
from lab_brain.domains.silicon_photonics import backend_validity
from lab_brain.domains.silicon_photonics.condition_schema import (
    SCHEMA_REF,
    PnJunctionConditionComparator,
    registration,
)
from lab_brain.domains.silicon_photonics.extractors import CjRsExtractor
from lab_brain.evidence.condition_schema_registry import ConditionSchemaRegistry
from lab_brain.tools.extraction import ExtractionInput, ExtractionSource, NumericalSeries

NOW = dt.datetime(2026, 9, 23, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:sp"
TRACE = "trc:sp-1"

#: A synthetic device length. Round, and a property of the fixture only.
DEVICE_LENGTH_UM = Decimal("500")
#: A synthetic small-signal frequency. 1 MHz, chosen because it makes the arithmetic legible.
FREQUENCY_HZ = Decimal("1000000")
BIAS_V = Decimal("-1.0")

#: The impedance the fixtures carry. Series-RC at the frequency above:
#:   Re(Z) = Rs_total,  Im(Z) = -1/(2*pi*f*Cj_total)
#: The values are what `MockChargeAcBackend` computes for the same conditions, so the simulated
#: and measured fixtures are numerically identical and only their PROVENANCE differs.
IMPEDANCE_REAL_OHM = Decimal("2.4")
IMPEDANCE_IMAG_OHM = Decimal("-1195.22557344")

CONDITIONS: dict[str, object] = {
    "bias_v": str(BIAS_V),
    "frequency_hz": str(FREQUENCY_HZ),
    "device_length_um": str(DEVICE_LENGTH_UM),
    "temperature_k": "300",
}

VALIDITY: dict[str, object] = {
    "solver_id": "mock.charge.ac",
    "solver_version": "0.1.0",
    "project_hash": "sha256:" + "11" * 32,
    "mesh_config_ref": "art:sha256:" + "22" * 32,
    "bias_config_ref": "art:sha256:" + "22" * 32,
    "convergence_status": backend_validity.CONVERGED,
}


def condition_registry() -> ConditionSchemaRegistry:
    """A registry with the SiPh schema and comparator in it, built the way the pack builds one.

    Every extractor fixture goes through this rather than through `ConditionSchemaRegistry()`:
    `CjRsExtractor` validates EVI-001's conditions against the REGISTERED schema, so a test that
    handed it an empty registry would be testing the unregistered-version refusal by accident.
    """
    registry = ConditionSchemaRegistry()
    schema = registration()
    registry.register_schema(schema)
    registry.register_comparator(schema.domain, schema.schema_id, PnJunctionConditionComparator())
    return registry


def extractor() -> CjRsExtractor:
    """The extractor, with its required condition registry. There is no zero-argument form."""
    return CjRsExtractor(condition_registry())


def series(
    *,
    real: Decimal = IMPEDANCE_REAL_OHM,
    imag: Decimal = IMPEDANCE_IMAG_OHM,
) -> tuple[NumericalSeries, ...]:
    """The impedance payload. One builder, so both modalities carry identical arrays."""
    return (
        NumericalSeries(name="bias_v", unit="V", values=(BIAS_V,)),
        NumericalSeries(name="frequency_hz", unit="Hz", values=(FREQUENCY_HZ,)),
        NumericalSeries(name="impedance_real_ohm", unit="ohm", values=(real,)),
        NumericalSeries(name="impedance_imag_ohm", unit="ohm", values=(imag,)),
    )


def simulated_source(
    *,
    run_id: str = "run:sp-1",
    validity: dict[str, object] | None = None,
    conditions: dict[str, object] | None = None,
) -> ExtractionSource:
    return ExtractionSource(
        modality=EpistemicType.SIMULATED,
        run_id=run_id,
        project_id=PROJECT,
        backend_id="mock.charge.ac",
        backend_version="0.1.0",
        conditions=dict(conditions or CONDITIONS),
        conditions_schema_version=SCHEMA_REF,
        backend_validity_schema=backend_validity.SCHEMA_REF,
        backend_validity=dict(validity or VALIDITY),
    )


def measured_source(
    *,
    artifact_id: str = "art:sha256:" + "33" * 32,
    conditions: dict[str, object] | None = None,
) -> ExtractionSource:
    """The measured half of the pair. Same type, same conditions, different provenance.

    No `backend_validity` is required of a measurement: SIM-001 is about a *run manifest*, and
    §17.10 leaves an instrument's calibration record to the DomainPack. What the extractor contract
    requires of a measurement instead is the source Artifact, which is refused if absent.
    """
    return ExtractionSource(
        modality=EpistemicType.MEASURED,
        source_artifact_id=artifact_id,
        project_id=PROJECT,
        backend_id="lab.impedance_analyzer",
        backend_version="fixture-1",
        conditions=dict(conditions or CONDITIONS),
        conditions_schema_version=SCHEMA_REF,
    )


def extraction_input(source: ExtractionSource, **kwargs: Decimal) -> ExtractionInput:
    """One builder for both modalities. See the module docstring."""
    return ExtractionInput(
        project_id=PROJECT,
        trace_id=TRACE,
        source=source,
        series=series(**kwargs),
    )


def simulated_input(**kwargs: Decimal) -> ExtractionInput:
    return extraction_input(simulated_source(), **kwargs)


def measured_input(**kwargs: Decimal) -> ExtractionInput:
    return extraction_input(measured_source(), **kwargs)


__all__ = [
    "BIAS_V",
    "CONDITIONS",
    "DEVICE_LENGTH_UM",
    "FREQUENCY_HZ",
    "IMPEDANCE_IMAG_OHM",
    "IMPEDANCE_REAL_OHM",
    "NOW",
    "PROJECT",
    "TRACE",
    "VALIDITY",
    "condition_registry",
    "extraction_input",
    "extractor",
    "measured_input",
    "measured_source",
    "series",
    "simulated_input",
    "simulated_source",
]
