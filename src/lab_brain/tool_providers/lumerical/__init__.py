"""Lumerical provider slot — **mock only**. No license seat is held and no `lumapi` is imported.

READ THIS BEFORE WRITING ANYTHING THAT CLAIMS OTHERWISE.

There is no Lumerical installation, no license seat and no `lumapi` in this environment (risk R-1,
recorded in IMPLEMENTATION_STATUS.md since M0a). This package exists so the provider boundary is a
real seam rather than a diagram, and it contains exactly one module: a deterministic mock that
satisfies `lab_brain.tools.simulation.SimulationBackend`.

WHAT IS PROVEN AND WHAT IS NOT. What M2 establishes is the **contract**: a backend that can be
driven from a §17.4 request, that returns a §17.4 execution, that declares which validity schema
its payload conforms to, and that contends for a seat through §10.7. A real `charge.py` written
against `lumapi` would implement the same Protocol and change nothing above it.

What is NOT proven, and must not be written down as if it were: that Lumerical itself runs. TST-001
requires the same case to replay *both* on a mock dataset in CI *and* on a real Lumerical project
in a licensed environment, and only the first half is dischargeable here. The second half is open
and belongs to whoever has a seat.

`test_no_vendor_sdk_is_imported_anywhere` fails if any module in `src/` imports `lumapi` or its
relatives, which is not a prohibition on ever doing so -- it is a tripwire, so that adding a real
backend is a deliberate act with the accompanying environment work rather than an import that
quietly makes the test suite unrunnable on every machine without a license.

§18's tree also lists `bridge.py`, `session.py`, `license_pool.py`, `charge.py`, `mode.py`,
`fdtd.py` and `interconnect.py` here. None of them exists, deliberately: a file named `session.py`
containing `pass` is a claim that a session layer is designed, and it is not.
"""

from lab_brain.tool_providers.lumerical.mock import (
    MOCK_BACKEND_ID,
    MOCK_BACKEND_VERSION,
    MockChargeAcBackend,
)

__all__ = ["MOCK_BACKEND_ID", "MOCK_BACKEND_VERSION", "MockChargeAcBackend"]
