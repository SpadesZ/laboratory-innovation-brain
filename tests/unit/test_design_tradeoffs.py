"""T-VER-007: multi-objective trade-offs are preserved and presented (P10).

T-VER-007  a single scalar figure of merit cannot decide keep/discard; multi-objective
           trade-offs are preserved and presented; a scalar-only OutcomeSpace over design
           quality requires explicit declared justification.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.verification.tradeoff import (
    DESIGN_QUALITY,
    Candidate,
    Direction,
    Objective,
    ScalarFigureOfMeritRefused,
    ScalarJustification,
    compare,
    require_design_space_justification,
)
from tests.vertical_units import plan, registries, rival

OBJECTIVES = (
    Objective("insertion_loss_db", Direction.MINIMIZE, "dB"),
    Objective("vpi_l_v_cm", Direction.MINIMIZE, "V.cm"),
    Objective("bandwidth_ghz", Direction.MAXIMIZE, "GHz"),
)


def _designs() -> list[Candidate]:
    return [
        Candidate(
            "dsg:low-loss",
            {
                "insertion_loss_db": Decimal("2.1"),
                "vpi_l_v_cm": Decimal("2.4"),
                "bandwidth_ghz": Decimal("35"),
            },
        ),
        Candidate(
            "dsg:efficient",
            {
                "insertion_loss_db": Decimal("3.6"),
                "vpi_l_v_cm": Decimal("1.1"),
                "bandwidth_ghz": Decimal("28"),
            },
        ),
        Candidate(
            "dsg:fast",
            {
                "insertion_loss_db": Decimal("3.0"),
                "vpi_l_v_cm": Decimal("2.0"),
                "bandwidth_ghz": Decimal("55"),
            },
        ),
        Candidate(
            "dsg:dominated",
            {
                "insertion_loss_db": Decimal("3.7"),
                "vpi_l_v_cm": Decimal("2.5"),
                "bandwidth_ghz": Decimal("27"),
            },
        ),
    ]


@pytest.mark.requirement("VER-007")
@pytest.mark.spec_test("T-VER-007")
def test_only_a_dominated_design_is_discarded_and_every_trade_off_is_kept():
    comparison = compare(_designs(), OBJECTIVES)
    assert comparison.front == ("dsg:efficient", "dsg:fast", "dsg:low-loss")
    assert not comparison.verdicts["dsg:dominated"].keep
    assert comparison.verdicts["dsg:dominated"].dominated_by == (
        "dsg:efficient",
        "dsg:fast",
        "dsg:low-loss",
    )
    # The best design on any single objective is not the only one kept.
    by_loss = min(_designs(), key=lambda c: c.values["insertion_loss_db"])
    assert by_loss.candidate_id == "dsg:low-loss"
    assert len(comparison.front) == 3


@pytest.mark.requirement("VER-007")
@pytest.mark.spec_test("T-VER-007")
def test_the_trade_off_is_presented_with_every_objective_and_the_reason_for_each_verdict():
    table = compare(_designs(), OBJECTIVES).table()
    assert "insertion_loss_db (min)" in table and "bandwidth_ghz (max)" in table
    for design in _designs():
        assert design.candidate_id in table
    assert (
        "| dsg:dominated | 3.7 | 2.5 | 27 | no | dsg:efficient, dsg:fast, dsg:low-loss |" in table
    )


@pytest.mark.requirement("VER-007")
@pytest.mark.spec_test("T-VER-007")
def test_a_single_scalar_figure_of_merit_cannot_decide_keep_or_discard_unjustified():
    with pytest.raises(ScalarFigureOfMeritRefused, match="scalar figure of merit"):
        compare(_designs(), OBJECTIVES[:1])
    with pytest.raises(ScalarFigureOfMeritRefused, match="rationale and its author"):
        ScalarJustification(
            subject_ref="cmp:loss-only",
            rationale=" ",
            declared_by_actor_id="act:pi",
            declared_at=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        )
    justified = compare(
        _designs(),
        OBJECTIVES[:1],
        justification=ScalarJustification(
            subject_ref="cmp:loss-only",
            rationale="a passive link budget where loss is the only open specification",
            declared_by_actor_id="act:pi",
            declared_at=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        ),
    )
    assert justified.front == ("dsg:low-loss",)
    assert justified.justification is not None


@pytest.mark.requirement("VER-007")
@pytest.mark.spec_test("T-VER-007")
def test_a_scalar_only_design_quality_outcome_space_requires_declared_justification():
    scalar = OutcomeSpace(
        outcome_space_id="os:sp.design_fom",
        version="1.0.0",
        domain="silicon_photonics",
        action_type="SIMULATION",
        hypothesis_type=DESIGN_QUALITY,
        outcomes=("BETTER", "SAME", "WORSE"),
        order_or_metric_ref="dm:sp.fom_rank@1.0.0",
    )
    with pytest.raises(ScalarFigureOfMeritRefused, match="explicit declared justification"):
        require_design_space_justification(scalar, {})
    require_design_space_justification(
        scalar,
        {
            scalar.ref: ScalarJustification(
                subject_ref=scalar.ref,
                rationale="the figure of merit is the contract's single acceptance criterion",
                declared_by_actor_id="act:pi",
                declared_at=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
            )
        },
    )
    # Diagnosis spaces are not design-quality spaces and need no justification.
    result = plan(registries(), (rival("contact"),))
    assert result.plan.chosen_action_id is not None


@pytest.mark.requirement("VER-007")
@pytest.mark.spec_test("T-VER-007")
def test_the_verification_plan_presents_the_cost_trade_off_rather_than_a_single_score():
    result = plan(registries(), (rival("contact"), rival("mesh"), rival("probe")))
    tradeoffs = {t.action_id: t for t in result.plan.rationale.tradeoffs}
    assert set(tradeoffs) == set(result.plan.candidate_action_ids)
    # The probe and the mesh study are both on the Pareto front: neither dominates the other.
    mesh, probe = tradeoffs["cap:sp.mesh_sensitivity"], tradeoffs["cap:sp.fourpoint_probe"]
    assert mesh.pareto_layer == probe.pareto_layer
    assert mesh.dominated_by == () or "cap:sp.fourpoint_probe" not in mesh.dominated_by
    for record in tradeoffs.values():
        assert {"wall_clock_s", "human_minutes", "money_estimate", "license_seat_s"} <= set(
            record.cost
        )
