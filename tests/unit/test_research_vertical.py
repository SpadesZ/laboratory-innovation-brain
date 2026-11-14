"""The Silicon Photonics product vertical, and the research package's dependency boundary.

What the deployment can run is stated, not assumed: every SIMULATION capability is UNAVAILABLE
with a reason (no licensed backend exists here), the solver-free readers run, and the planning
registry keeps the declared descriptors for the "what would be best" question only.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import pytest

from lab_brain.core.models.capability import ActionType, Availability
from lab_brain.domains.silicon_photonics.product import (
    SIMULATOR_UNAVAILABLE,
    mechanism_catalog,
    product_vertical,
    read_device_project,
)
from lab_brain.research.vertical import InputRefused, load_vertical_factory

ROOT = Path(__file__).resolve().parents[2]


def _vertical():  # type: ignore[no-untyped-def]
    return product_vertical(
        outputs=None, jobs=None, broker=None, now=lambda: dt.datetime(2026, 9, 28, tzinfo=dt.UTC)
    )


def test_every_simulation_is_blocked_with_its_reason_and_nothing_else_is():
    vertical = _vertical()
    capabilities = vertical.registry.registries.capabilities
    simulations = {c.capability_id for c in capabilities if c.action_type is ActionType.SIMULATION}
    assert simulations and {b.capability_id for b in vertical.blocked} == simulations
    for capability in capabilities:
        blocked = capability.capability_id in simulations
        assert (capability.availability is Availability.UNAVAILABLE) is blocked
    assert all(
        b.reason == SIMULATOR_UNAVAILABLE and "Lumerical" in b.reason for b in vertical.blocked
    )
    assert set(vertical.backends) == {
        "cap:sp.inspect_contact_connectivity",
        "cap:sp.extraction_consistency",
    }
    # The planning registry keeps the declared descriptors, untouched by this deployment.
    for capability_id in simulations:
        declared = vertical.planning_capabilities.resolve(capability_id)
        assert declared.availability is not Availability.UNAVAILABLE


def test_the_catalog_predicts_only_over_outcome_spaces_the_pack_declares():
    vertical = _vertical()
    metrics = vertical.registry.registries.disagreement_metrics
    for mechanism in mechanism_catalog().mechanisms:
        assert vertical.registry.registries.capabilities.get(mechanism.minimal_test_ref)
        for prediction in mechanism.predictions:
            space = metrics.outcome_space(
                prediction.outcome_space_id, prediction.outcome_space_version
            )
            assert space is not None, prediction
            assert prediction.expected_outcome in space.outcomes


def test_the_device_project_is_read_or_refused():
    fx = json.loads(
        (ROOT / "fixtures/vertical/sp_rs_root_cause_benchmark.json").read_text(encoding="utf-8")
    )
    reading = read_device_project(json.dumps(fx["nominal_device"]).encode())
    assert reading.conditions == {"device_length_um": "500"}
    assert "PS-500" in reading.summary
    with pytest.raises(InputRefused):
        read_device_project(b"{not json")


def test_the_vertical_is_selected_by_name():
    assert load_vertical_factory("silicon_photonics") is product_vertical
    with pytest.raises(LookupError, match="installed"):
        load_vertical_factory("ring_resonators")


def test_the_research_orchestrator_imports_no_pack_and_no_provider():
    """§24.2: orchestration never names a DomainPack; the deployment selects one by name."""
    forbidden = ("lab_brain.domains.silicon_photonics", "lab_brain.tool_providers")
    for path in (ROOT / "src/lab_brain/research").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"
