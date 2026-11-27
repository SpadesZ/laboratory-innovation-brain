"""TST-001's licensed half: the same case replayed on a real Lumerical project (risk R-1, P1).

    TST-001  同一案例要能以 mock dataset 在 CI 重播，並以真實 Lumerical project 在有 license 的環境重播。

The mock half is `test_vs_sp_001_vertical_postgres.py` and the benchmark. This half cannot run
here: there is no Lumerical seat in this environment and no licensed provider is wired in this
repository. It is marked `lumerical`, so it is deselected unless `LAB_BRAIN_TEST_LUMERICAL=1`, and
when enabled without a provider it FAILS rather than passing -- an enabled licensed gate that
silently succeeded would be the claim of an external run that did not occur.

What a licensed provider must supply to turn this green is exactly the typed contract the mocks
already satisfy: `SimulationBackend`s for `cap:sp.mesh_sensitivity` and `cap:sp.charge_dc_sweep`
(emitting raw output through a `RunOutputSink` and a complete `simulator_validity` record), wired
into `CapabilityRoutedRunner` in place of `tool_providers.lumerical.mock_vertical`.
"""

from __future__ import annotations

import importlib.util

import pytest


@pytest.mark.lumerical
@pytest.mark.requirement("TST-001")
@pytest.mark.spec_test("T-E2E-SP-001")
def test_the_rs_anomaly_replays_on_a_licensed_lumerical_project():
    provider = importlib.util.find_spec("lab_brain.tool_providers.lumerical.charge")
    if provider is None:
        pytest.fail(
            "no licensed Lumerical provider is wired (lab_brain.tool_providers.lumerical.charge "
            "does not exist); the licensed replay TST-001 requires has not been performed"
        )
    pytest.fail("a licensed provider exists but no replay harness is wired for it yet")
