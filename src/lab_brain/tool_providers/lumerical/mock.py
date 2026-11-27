"""A deterministic stand-in for a small-signal solver. **Not Lumerical.** (TST-001, R-1)

WHAT THIS IS. A `SimulationBackend` that computes a series-RC impedance from the conditions it is
handed, using a declared analytic model, and returns a §17.4-shaped execution with a complete
`simulator_validity` payload. It exists to prove the *contract*: that a backend can be driven from
a `SimulationRequest`, that its output can become a Run manifest, that SIM-001's validity check has
something real to check, and that seat contention is reachable.

WHAT THIS IS NOT, stated plainly because the alternative is a record that misleads an auditor:

    - it is not Lumerical, does not import `lumapi`, and holds no license seat;
    - its numbers are not physics -- they are an analytic model chosen so that a test can predict
      the extractor's output exactly;
    - a Run it produces is honestly labelled: `solver_id` is `mock.charge.ac`, never `CHARGE`.

`test_the_mock_never_claims_to_be_a_vendor_solver` asserts the third point, because it is the one
that would survive a careless copy into a real provider.

DETERMINISTIC MEANS TESTABLE, AND IT IS WHY THE MODEL IS ANALYTIC. Given a bias, a frequency and a
device length, this returns exactly one impedance, computed in `Decimal` at a fixed precision. So a
test can assert that `extract_cj_rs` recovers the capacitance the model was given -- a round trip
through the whole contract with an exactly known answer. A backend that returned noise could only
be tested for shape.

THE MODEL. A junction capacitance that falls with reverse bias in the textbook abrupt-junction way,
and a series resistance that is constant:

    Cj_per_length(V) = CJ0 / sqrt(1 - V / VBI)          for V <= 0   (reverse bias is negative)
    Rs_per_length    = RS0

    Cj_total = Cj_per_length * L        Rs_total = Rs_per_length / L
    Z = Rs_total - j / (2*pi*f*Cj_total)

CJ0, VBI and RS0 are declared constants of this mock with round values chosen for legibility. They
are NOT measurements, NOT taken from any project, and carry no claim about any real device -- see
the module constants, each of which says so.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, localcontext
from typing import ClassVar, Final

from lab_brain.core.models.job import RunStatus
from lab_brain.domains.silicon_photonics import backend_validity
from lab_brain.tools.extraction import NumericalSeries
from lab_brain.tools.simulation import BackendExecution, SimulationRequest

MOCK_BACKEND_ID: Final = "mock.charge.ac"
MOCK_BACKEND_VERSION: Final = "0.1.0"

#: Solver identity as it appears in `simulator_validity.solver_id`. Deliberately NOT "CHARGE":
#: a Run stamped with a vendor solver name that never ran is a provenance lie that survives every
#: downstream check, because the manifest is otherwise perfectly well formed.
MOCK_SOLVER_ID: Final = "mock.charge.ac"

# ---------------------------------------------------------------------------
# Model constants.
#
# ROUND NUMBERS, CHOSEN FOR LEGIBILITY, MEASURED FROM NOTHING. Each is a property of this mock and
# of no device: a reader who takes CJ0 as a plausible junction capacitance has read it wrong, and
# a fixture that asserts against it is asserting against the mock's arithmetic.
# ---------------------------------------------------------------------------

#: Zero-bias junction capacitance per unit length, fF/um.
CJ0: Final = Decimal("200")
#: Built-in potential, volts. Sets the curvature of the Cj(V) fall-off.
VBI: Final = Decimal("0.8")
#: Series resistance per unit length, ohm.um. Constant with bias, which is the *expected* trend
#: `validate_expected_trends` checks -- so an anomalous fixture is built by overriding it, not by
#: making the model noisy.
RS0: Final = Decimal("1200")

TWO_PI: Final = Decimal("6.283185307179586476925286766559")
_FEMTO: Final = Decimal("1e15")
PRECISION: Final = 40


class MockChargeAcBackend:
    """A deterministic small-signal backend. See the module docstring for what it does not claim.

    ``fail_convergence`` and ``rs_override`` exist so a test can produce the two records that
    matter without a second backend: a run that did not converge (which
    `backend_validity.fidelity_for` lowers to SIM_COARSE, so SIM-002's rejection gate refuses it)
    and a sweep whose Rs swings (which `validate_expected_trends` FAILs). Building those from
    separate fake backends would let the negative fixtures drift from the positive one.
    """

    backend_id: ClassVar[str] = MOCK_BACKEND_ID
    backend_version: ClassVar[str] = MOCK_BACKEND_VERSION
    validity_schema_ref: ClassVar[str] = backend_validity.SCHEMA_REF

    def __init__(
        self,
        *,
        clock: dt.datetime,
        duration_s: int = 30,
        fail_convergence: bool = False,
        rs_override: Decimal | None = None,
        artifact_id: str,
    ) -> None:
        self._clock = clock
        self._duration_s = duration_s
        self._fail_convergence = fail_convergence
        self._rs_override = rs_override
        self._artifact_id = artifact_id

    def execute(self, request: SimulationRequest) -> BackendExecution:
        """Compute one impedance sample and report it as a §17.4-shaped execution."""
        bias = Decimal(str(request.conditions["bias_v"]))
        frequency = Decimal(str(request.conditions["frequency_hz"]))
        length = Decimal(str(request.conditions["device_length_um"]))

        with localcontext() as context:
            context.prec = PRECISION
            cj_per_length = self._cj_per_length(bias)
            rs_per_length = self._rs_override if self._rs_override is not None else RS0

            cj_total_farad = cj_per_length * length / _FEMTO
            rs_total = rs_per_length / length
            reactance = Decimal(-1) / (TWO_PI * frequency * cj_total_farad)

        status = (
            backend_validity.NOT_CONVERGED if self._fail_convergence else backend_validity.CONVERGED
        )
        return BackendExecution(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            # The run still SUCCEEDED as an execution even when the solver did not converge: it
            # ran and produced a manifest. Whether its numbers may reject a hypothesis is an
            # AUTHORITY question, decided by `fidelity_for`, not a Run status question. Collapsing
            # the two would discard §6.10's non-converged execution record entirely.
            status=RunStatus.SUCCEEDED,
            backend_validity_schema=self.validity_schema_ref,
            backend_validity={
                "solver_id": MOCK_SOLVER_ID,
                "solver_version": self.backend_version,
                # §17.4 stores mesh and bias configuration BY REFERENCE. Content-addressed, so
                # what they point at is reproducible (ART-001).
                "project_hash": f"sha256:{self._artifact_id.removeprefix('art:')}",
                "mesh_config_ref": self._artifact_id,
                "bias_config_ref": self._artifact_id,
                "convergence_status": status,
                "iterations": 1,
            },
            output_artifacts=(self._artifact_id,),
            numerical_array_refs=(f"arr:{request.request_id}",),
            series=(
                NumericalSeries(name="bias_v", unit="V", values=(bias,)),
                NumericalSeries(name="frequency_hz", unit="Hz", values=(frequency,)),
                NumericalSeries(name="impedance_real_ohm", unit="ohm", values=(self._q(rs_total),)),
                NumericalSeries(
                    name="impedance_imag_ohm", unit="ohm", values=(self._q(reactance),)
                ),
            ),
            warnings=() if not self._fail_convergence else ("solver did not converge",),
            environment={"provider": "mock", "vendor_sdk": "none"},
            code_provenance=f"{MOCK_BACKEND_ID}@{MOCK_BACKEND_VERSION}",
            start_time=self._clock,
            end_time=self._clock + dt.timedelta(seconds=self._duration_s),
        )

    # -- the model ----------------------------------------------------------

    def _cj_per_length(self, bias: Decimal) -> Decimal:
        """Abrupt-junction depletion capacitance. See the module docstring for the formula."""
        ratio = Decimal(1) - bias / VBI
        if ratio <= 0:  # pragma: no cover - forward bias beyond built-in is out of scope
            return CJ0
        return CJ0 / ratio.sqrt()

    @staticmethod
    def _q(value: Decimal) -> Decimal:
        """Quantise to twelve significant digits so two runs return byte-identical series."""
        exponent = value.adjusted() - 11
        return value.quantize(Decimal(1).scaleb(exponent))

    def expected_cj_per_length(self, bias: Decimal) -> Decimal:
        """What the model was given, for a test to compare the extractor's answer against.

        Exposed so a round-trip test asserts against the MODEL rather than against a number
        transcribed from a previous run -- a transcribed constant makes the test pass after a
        change to the model and prove nothing.
        """
        with localcontext() as context:
            context.prec = PRECISION
            return self._cj_per_length(bias)


__all__ = [
    "CJ0",
    "MOCK_BACKEND_ID",
    "MOCK_BACKEND_VERSION",
    "MOCK_SOLVER_ID",
    "RS0",
    "VBI",
    "MockChargeAcBackend",
]
