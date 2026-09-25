"""LLM-002: a gate is armed only by a calibrated BenchmarkPolicy, and no gate module types a number.

§15.4  門檻由校準產生（LLM-002）：hard gates 必須引用版本化的 BenchmarkPolicy，且校準證據可
       追溯。校準前不得任意 hard-code 門檻數字。
"""

from __future__ import annotations

import ast
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from lab_brain.core.benchmark_gate import evaluate_gate
from lab_brain.core.models.benchmark import BenchmarkPolicy, MetricDirection
from lab_brain.core.repositories.benchmark import BenchmarkStoreError, InMemoryBenchmarkStore

pytestmark = [pytest.mark.requirement("LLM-002"), pytest.mark.spec_test("T-LLM-002")]

ROOT = Path(__file__).resolve().parents[2]
T0 = dt.datetime(2026, 9, 26, tzinfo=dt.UTC)

#: Every module that decides whether an LLM-002 gate passes, or feeds it the value.
GATE_MODULES = (
    "src/lab_brain/core/benchmark_gate.py",
    "src/lab_brain/core/revision_gate.py",
    "src/lab_brain/cognition/debate_metrics.py",
    "src/lab_brain/cognition/brain.py",
    "src/lab_brain/core/models/benchmark.py",
    "src/lab_brain/core/repositories/benchmark.py",
)


def _policy(**overrides: object) -> BenchmarkPolicy:
    fields: dict[str, object] = {
        "policy_id": "bp:unit",
        "domain": "toy_widgets",
        "benchmark_set_id": "bench:toy.widgets",
        "metric_key": "critic_bundle_divergence",
        "threshold": Decimal("0.25"),
        "direction": MetricDirection.AT_LEAST,
        "calibrated_at": T0,
        "sample_size": 12,
        "calibration_artifact_refs": ("benchmark-run:bench:toy.widgets#sha256:abc",),
        "version": "1.0.0",
    }
    fields.update(overrides)
    return BenchmarkPolicy(**fields)  # type: ignore[arg-type]


def _is_count(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and getattr(node.func, "id", None) == "len"


def test_no_gate_module_compares_a_metric_against_a_typed_number():
    """Parsed: a numeric literal in a comparison is allowed only against a count (`len(...)`).

    `len(admitted) < 2` is EPI-001's "at least two rivals", a count of objects; `divergence < 0.3`
    would be a threshold nobody calibrated. A threshold-shaped module constant is refused too.
    """
    offenders: list[str] = []
    for relative in GATE_MODULES:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                numeric = [
                    o
                    for o in operands
                    if (
                        isinstance(o, ast.Constant)
                        and isinstance(o.value, int | float)
                        and not isinstance(o.value, bool)
                    )
                    or (isinstance(o, ast.Call) and getattr(o.func, "id", None) == "Decimal")
                ]
                if numeric and not any(_is_count(o) for o in operands):
                    offenders.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = getattr(target, "id", "")
                    if "THRESHOLD" in name.upper() and isinstance(node.value, ast.Constant):
                        offenders.append(f"{relative}:{node.lineno}: constant {name}")
    assert offenders == []


# -- the gate ------------------------------------------------------------------------------------


def test_with_no_calibrated_policy_the_gate_records_and_enforces_nothing():
    verdict = evaluate_gate("critic_bundle_divergence", Decimal("0.01"), None)
    assert not verdict.enforced and verdict.passed is None and not verdict.blocks
    assert verdict.value == Decimal("0.01")


def test_an_armed_gate_passes_and_fails_on_the_calibrated_side():
    armed = _policy(active=True)
    assert evaluate_gate("critic_bundle_divergence", Decimal("0.25"), armed).passed
    assert evaluate_gate("critic_bundle_divergence", Decimal("0.2499"), armed).blocks
    at_most = _policy(active=True, direction=MetricDirection.AT_MOST)
    assert evaluate_gate("critic_bundle_divergence", Decimal("0.2"), at_most).passed


def test_an_armed_gate_fails_closed_on_an_unmeasured_value():
    assert evaluate_gate("critic_bundle_divergence", None, _policy(active=True)).blocks


def test_a_policy_with_no_direction_records_a_distribution_and_enforces_nothing():
    verdict = evaluate_gate(
        "critic_bundle_divergence", Decimal("0.01"), _policy(active=True, direction=None)
    )
    assert not verdict.enforced and not verdict.blocks
    with pytest.raises(ValueError, match="no direction"):
        _policy(direction=None).passes(Decimal("1"))


def test_an_inactive_or_foreign_policy_cannot_arm_a_gate():
    with pytest.raises(ValueError, match="not active"):
        evaluate_gate("critic_bundle_divergence", Decimal("0.5"), _policy())
    with pytest.raises(ValueError, match="calibrates"):
        evaluate_gate("position_diversity", Decimal("0.5"), _policy(active=True))


# -- the schema ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"calibration_artifact_refs": ()}, "at least 1"),
        ({"calibration_artifact_refs": (" ",)}, "blank calibration artifact"),
        ({"calibration_artifact_refs": ("a", "a")}, "twice"),
        ({"sample_size": 0}, "greater than or equal to 1"),
        ({"version": ""}, "blank version"),
        ({"benchmark_set_id": " "}, "blank benchmark_set_id"),
        ({"metric_key": ""}, "blank metric_key"),
        ({"threshold": Decimal("NaN")}, "finite number"),
    ],
)
def test_a_policy_that_cannot_say_where_its_threshold_came_from_cannot_be_built(overrides, match):
    with pytest.raises(ValidationError, match=match):
        _policy(**overrides)


def test_a_calibrated_version_is_immutable_and_one_version_is_active_per_gate():
    store = InMemoryBenchmarkStore()
    first = store.add_policy(_policy())
    with pytest.raises(BenchmarkStoreError, match="immutable"):
        store.add_policy(_policy(threshold=Decimal("0.3")))
    second = store.add_policy(_policy(version="1.1.0", threshold=Decimal("0.3")))
    assert (
        store.active_for(
            domain=first.domain,
            benchmark_set_id=first.benchmark_set_id,
            metric_key=first.metric_key,
        )
        is None
    )
    store.activate(first.policy_id, first.version)
    store.activate(second.policy_id, second.version)
    active = store.active_for(
        domain=first.domain, benchmark_set_id=first.benchmark_set_id, metric_key=first.metric_key
    )
    assert active is not None and active.version == "1.1.0"
    assert not store.policy(first.policy_id, first.version).active  # type: ignore[union-attr]
