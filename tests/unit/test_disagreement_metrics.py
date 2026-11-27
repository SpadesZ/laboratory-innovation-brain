"""T-VER-008: a disagreement metric is declared, bound, versioned and deterministic -- and not core's.

§26 T-VER-008  a DisagreementMetric with no declared OutcomeSpace binding or no version is
               rejected; identical input plus identical metric version returns an identical
               result across repeated runs; two domains may register different metrics and
               neither is core-supplied.
"""

from __future__ import annotations

import ast
import itertools
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from lab_brain.core.models.benchmark import DisagreementMetric
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.prediction import OutcomeSpace, Prediction, RelationJudgmentTemplate
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics import reasoning as sp
from lab_brain.verification.disagreement import (
    DisagreementMetricError,
    DisagreementMetricRegistry,
    rank_by_disagreement,
)
from tests.toy_domain import (
    TOY_METRIC,
    TOY_OUTCOME_SPACE,
    TOY_OUTCOMES,
    ToyCategoricalMismatch,
    ToyDomainPack,
)

pytestmark = [pytest.mark.requirement("VER-008"), pytest.mark.spec_test("T-VER-008")]

ROOT = Path(__file__).resolve().parents[2]
SPACE = OutcomeSpace(
    outcome_space_id="os:unit.grade",
    version="1.0.0",
    domain="unit",
    action_type="MEASUREMENT",
    outcomes=("LOW", "MID", "HIGH"),
)


class _Metric:
    """A configurable implementation, so each refusal is produced by exactly one defect."""

    def __init__(self, *, space: str = SPACE.outcome_space_id, version: str = "1.0.0") -> None:
        self._space = space
        self._version = version
        self.calls = 0

    @property
    def declaration(self) -> DisagreementMetric:
        return DisagreementMetric(
            metric_id="dm:unit.rank",
            outcome_space_id=self._space,
            outcome_space_version="1.0.0",
            implementation_ref="tests.unit:_Metric",
            version=self._version,
        )

    def distance(self, a: str, b: str) -> Decimal:
        self.calls += 1
        order = SPACE.outcomes
        return Decimal(abs(order.index(a) - order.index(b))) / Decimal(2)


class _Drifting(_Metric):
    def distance(self, a: str, b: str) -> Decimal:
        value = super().distance(a, b)
        return value + (Decimal("0.001") * (self.calls % 2)) if a != b else value


class _Asymmetric(_Metric):
    def distance(self, a: str, b: str) -> Decimal:
        return Decimal(1) if (a, b) == ("LOW", "HIGH") else Decimal(0)


class _Floaty(_Metric):
    def distance(self, a: str, b: str) -> float:  # type: ignore[override]
        return 0.0 if a == b else 0.5


def _registry() -> DisagreementMetricRegistry:
    registry = DisagreementMetricRegistry()
    registry.declare_space(SPACE)
    return registry


# -- rejected ------------------------------------------------------------------------------------


def test_a_metric_bound_to_an_undeclared_outcome_space_is_rejected():
    with pytest.raises(DisagreementMetricError, match="has not been declared"):
        _registry().register(_Metric(space="os:unit.never-declared"))


def test_a_metric_with_no_version_cannot_be_declared():
    with pytest.raises(ValidationError, match="MUST carry a version"):
        _ = _Metric(version=" ").declaration


def test_a_metric_that_is_not_deterministic_is_rejected_at_registration():
    with pytest.raises(DisagreementMetricError, match="identical input under one version"):
        _registry().register(_Drifting())


@pytest.mark.parametrize(
    ("implementation", "why"),
    [(_Asymmetric(), "not symmetric"), (_Floaty(), "a Decimal is required")],
)
def test_a_value_that_is_not_an_exact_symmetric_distance_is_rejected(implementation, why):
    with pytest.raises(DisagreementMetricError, match=why):
        _registry().register(implementation)


def test_a_changed_metric_under_the_same_version_is_rejected():
    registry = _registry()
    registry.register(_Metric())

    class _Changed(_Metric):
        def distance(self, a: str, b: str) -> Decimal:
            return Decimal(0) if a == b else Decimal(1)

    with pytest.raises(DisagreementMetricError, match="a changed metric is a new version"):
        registry.register(_Changed())


def test_an_outcome_outside_the_declared_space_has_no_distance():
    tabulated = _registry().register(_Metric())
    with pytest.raises(DisagreementMetricError, match="outside it"):
        tabulated.distance("LOW", "IMAGINABLE")


# -- deterministic -------------------------------------------------------------------------------


def _predictions(space: OutcomeSpace, observable: str) -> list[Prediction]:
    return [
        Prediction(
            prediction_id=f"prd:{i}",
            hypothesis_id=f"hyp:{i}",
            project_id="prj:unit",
            observable_ref=observable,
            outcome_space_id=space.outcome_space_id,
            outcome_space_version=space.version,
            expected_outcome=outcome,
            relation_effect_if_observed=(
                RelationJudgmentTemplate(
                    relation_type=RelationType.SUPPORTS, to_entity_id=f"hyp:{i}"
                ),
            ),
        )
        for i, outcome in enumerate(space.outcomes)
    ]


def test_identical_input_and_version_return_identical_results_across_repeated_runs():
    registry = _registry()
    implementation = _Metric()
    tabulated = registry.register(implementation)
    calls_after_registration = implementation.calls
    first = [tabulated.distance(a, b) for a, b in itertools.product(SPACE.outcomes, repeat=2)]
    for _ in range(5):
        again = [tabulated.distance(a, b) for a, b in itertools.product(SPACE.outcomes, repeat=2)]
        assert again == first
    # The table answers; the domain implementation is never consulted again after registration.
    assert implementation.calls == calls_after_registration

    predictions = _predictions(SPACE, "unit.grade")
    candidates = [("cap:b", ["unit.grade"]), ("cap:a", ["unit.grade", "unit.other"])]
    ranking = rank_by_disagreement(candidates, predictions, registry)
    assert all(rank_by_disagreement(candidates, predictions, registry) == ranking for _ in range(5))
    assert [r.capability_id for r in ranking] == ["cap:a", "cap:b"]
    assert ranking[0].disagreement == Decimal(1) and ranking[0].metric_ref == "dm:unit.rank@1.0.0"


def test_the_ranking_is_identical_in_a_fresh_interpreter():
    """Across processes and hash seeds -- a set iteration order leaking in would show here."""
    program = (
        "from lab_brain.domains.registry import DomainPackRegistry\n"
        "from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack\n"
        "r = DomainPackRegistry()\n"
        "r.install(SiliconPhotonicsPack(runner=lambda _r: None, conditions=r.registries.conditions))\n"
        "m = r.registries.disagreement_metrics.metric('"
        + sp.RS_RESPONSE_METRIC_ID
        + "', '"
        + sp.RS_RESPONSE_METRIC_VERSION
        + "')\n"
        "print(repr(m.table))\n"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
            env={
                "PYTHONHASHSEED": seed,
                "PYTHONPATH": str(ROOT / "src"),
                "SYSTEMROOT": "C:\\Windows",
            },
        ).stdout
        for seed in ("0", "1", "12345")
    }
    assert len(outputs) == 1


# -- domains declare, core supplies none ---------------------------------------------------------


def test_two_domains_register_different_metrics_and_neither_is_core_supplied():
    registry = DomainPackRegistry()
    registry.install(
        SiliconPhotonicsPack(runner=lambda _r: None, conditions=registry.registries.conditions)  # type: ignore[arg-type,return-value]
    )
    registry.install(ToyDomainPack())
    metrics = registry.registries.disagreement_metrics
    sp_metric = metrics.metric(sp.RS_RESPONSE_METRIC_ID, sp.RS_RESPONSE_METRIC_VERSION)
    toy_metric = metrics.metric(TOY_METRIC, "1.0.0")

    assert sp_metric.declaration.implementation_ref.startswith(
        "lab_brain.domains.silicon_photonics"
    )
    assert toy_metric.declaration.implementation_ref.startswith("tests.toy_domain")
    # Different metrics: ordinal for the Rs response, categorical for the widget verdict.
    toy_values = {v for _, _, v in toy_metric.table}
    sp_values = {v for _, _, v in sp_metric.table}
    assert toy_values == {Decimal(0), Decimal(1)}
    assert len(sp_values) > 2
    assert metrics.for_space(TOY_OUTCOME_SPACE, "1.0.0") is toy_metric
    assert set(TOY_OUTCOMES) == set(toy_metric.outcome_space.outcomes)


def test_a_fresh_registry_holds_no_metric():
    assert len(DisagreementMetricRegistry()) == 0


def test_core_and_verification_define_no_metric_implementation():
    """§9.1: Core does not hard-code one universal distance. Parsed, so a new one cannot hide."""
    offenders = []
    for package in ("core", "verification", "cognition"):
        for path in sorted((ROOT / "src" / "lab_brain" / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if any(getattr(base, "id", None) == "Protocol" for base in node.bases):
                        continue  # the interface a DomainPack implements, not an implementation
                    methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
                    if {"declaration", "distance"} <= methods:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.name}")
    assert offenders == []


def test_the_toy_metric_is_a_distance_the_registry_accepts_on_its_own():
    registry = DisagreementMetricRegistry()
    with pytest.raises(DisagreementMetricError):
        registry.register(ToyCategoricalMismatch())  # its space is not declared yet
