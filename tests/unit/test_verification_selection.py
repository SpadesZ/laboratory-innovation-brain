"""T-VER-003 and T-VER-005: cost is a vector, and the ranking is a deterministic, versioned policy.

T-VER-003  CostVector 可表達時間/人力/錢/license/不可逆；Planner 不依賴單一 normalized_cost。
T-VER-005  same actions/state/policy produce identical ranking across repeated runs; tie is
           resolved by configured lexicographic fallback.
"""

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from lab_brain.core.models.cost import CostVector, DependencyRisk
from lab_brain.core.models.verification import (
    CostDimension,
    PlanDecision,
    PlanRationale,
    SelectionPolicy,
    SufficiencySummary,
    VerificationPlan,
)
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.verification.selection import (
    SelectionCandidate,
    cost_order,
    dimension_value,
    dominates,
    pareto_layers,
    rank,
)
from tests.vertical_units import plan, registries, rivals

T0 = dt.datetime(2026, 9, 27, tzinfo=dt.UTC)


def _policy(fallback: tuple[CostDimension, ...], version: str = "1.0.0") -> SelectionPolicy:
    return SelectionPolicy(
        policy_id="slp:unit",
        version=version,
        pareto_dimensions=(CostDimension.WALL_CLOCK_S, CostDimension.HUMAN_MINUTES),
        lexicographic_fallback=fallback,
        effective_from=T0,
    )


def _c(action_id: str, sufficient: bool = True, **cost: object) -> SelectionCandidate:
    return SelectionCandidate(
        action_id=action_id,
        cost=CostVector(**cost),  # type: ignore[arg-type]
        sufficient=sufficient,
        discriminating=False,
    )


# ---------------------------------------------------------------------------------------------
# VER-003 -- a vector, never a scalar
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("VER-003")
@pytest.mark.spec_test("T-VER-003")
def test_the_cost_vector_expresses_time_people_money_licence_and_irreversibility():
    cost = CostVector(
        wall_clock_s=6 * 7 * 24 * 3600,
        human_minutes=600,
        money_estimate=Decimal("40000"),
        license_seat_s=0,
        irreversible=True,
        dependency_risk=DependencyRisk.HIGH,
    )
    assert dimension_value(cost, CostDimension.WALL_CLOCK_S) == Decimal(6 * 7 * 24 * 3600)
    assert dimension_value(cost, CostDimension.HUMAN_MINUTES) == Decimal(600)
    assert dimension_value(cost, CostDimension.MONEY_ESTIMATE) == Decimal("40000")
    assert dimension_value(cost, CostDimension.LICENSE_SEAT_S) == Decimal(0)
    assert dimension_value(cost, CostDimension.IRREVERSIBLE) == (1,)
    assert dimension_value(cost, CostDimension.DEPENDENCY_RISK) > dimension_value(
        CostVector(), CostDimension.DEPENDENCY_RISK
    )
    # A later availability is "more expensive" than now, without being a duration.
    assert dimension_value(CostVector(), CostDimension.EARLIEST_AVAILABLE_AT) < dimension_value(
        CostVector(earliest_available_at=T0), CostDimension.EARLIEST_AVAILABLE_AT
    )


@pytest.mark.requirement("VER-003")
@pytest.mark.spec_test("T-VER-003")
def test_a_policy_cannot_be_a_single_normalized_cost():
    """One Pareto dimension is a scalar under another name; an unknown dimension is refused."""
    with pytest.raises(ValidationError, match="single normalized cost"):
        SelectionPolicy(
            policy_id="slp:scalar",
            version="1.0.0",
            pareto_dimensions=(CostDimension.MONEY_ESTIMATE,),
            lexicographic_fallback=(CostDimension.MONEY_ESTIMATE,),
            effective_from=T0,
        )
    with pytest.raises(ValidationError):
        SelectionPolicy(
            policy_id="slp:scalar",
            version="1.0.0",
            pareto_dimensions=("normalized_cost", "wall_clock_s"),  # type: ignore[arg-type]
            lexicographic_fallback=(CostDimension.WALL_CLOCK_S,),
            effective_from=T0,
        )
    with pytest.raises(ValidationError, match="repeats a dimension"):
        _policy((CostDimension.WALL_CLOCK_S, CostDimension.WALL_CLOCK_S))
    with pytest.raises(ValidationError, match="no lexicographic fallback"):
        _policy(())


@pytest.mark.requirement("VER-003")
@pytest.mark.spec_test("T-VER-003")
def test_equal_scalar_totals_do_not_make_candidates_equal():
    """Two actions whose 'sum' of dimensions is the same are ranked by the declared order.

    A normalized_cost planner would call these a tie. The policy says a person's attention is
    scarcer than elapsed time, so the one that needs nobody goes first -- in either input order.
    """
    policy = _policy((CostDimension.HUMAN_MINUTES, CostDimension.WALL_CLOCK_S))
    solve = _c("cap:solve", wall_clock_s=90, human_minutes=0)
    person = _c("cap:person", wall_clock_s=0, human_minutes=90)
    assert not dominates(solve.cost, person.cost, policy.pareto_dimensions)
    assert not dominates(person.cost, solve.cost, policy.pareto_dimensions)
    assert rank([solve, person], policy).ranked_ids == ("cap:solve", "cap:person")
    assert rank([person, solve], policy).ranked_ids == ("cap:solve", "cap:person")


@pytest.mark.requirement("VER-003")
@pytest.mark.spec_test("T-VER-003")
def test_the_vs_sp_001_plan_presents_every_candidates_whole_cost_vector():
    regs = registries()
    result = plan(regs, rivals())
    fabricate = next(
        t for t in result.plan.rationale.tradeoffs if t.action_id == sp.CAP_FABRICATE_SPLIT
    )
    assert fabricate.cost["irreversible"] is True
    assert fabricate.cost["human_minutes"] == 600
    assert fabricate.cost["dependency_risk"] == "HIGH"
    probe = next(
        t for t in result.plan.rationale.tradeoffs if t.action_id == sp.CAP_FOURPOINT_PROBE
    )
    assert probe.cost["license_seat_s"] == 0 and probe.cost["human_minutes"] == 90
    # The irreversible fabrication is ranked last although it is sufficient.
    assert result.plan.ranked_action_ids[-1] == sp.CAP_FABRICATE_SPLIT
    assert result.plan.sufficiency_results[sp.CAP_FABRICATE_SPLIT].sufficient


# ---------------------------------------------------------------------------------------------
# VER-005 -- deterministic, versioned selection
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("VER-005")
@pytest.mark.spec_test("T-VER-005")
def test_the_same_candidates_and_policy_rank_identically_in_any_input_order():
    policy = sp.selection_policy()
    candidates = [
        _c("cap:a", wall_clock_s=2),
        _c("cap:b", wall_clock_s=240, license_seat_s=240, compute_units=16),
        _c("cap:c", wall_clock_s=600, license_seat_s=600, compute_units=40),
        _c("cap:d", wall_clock_s=14400, human_minutes=90, money_estimate=Decimal(250)),
        _c("cap:e", sufficient=False, wall_clock_s=1),
    ]
    first = rank(candidates, policy)
    shuffler = random.Random(20260927)
    for _ in range(25):
        shuffled = candidates[:]
        shuffler.shuffle(shuffled)
        again = rank(shuffled, policy)
        assert again.ranked_ids == first.ranked_ids
        assert again.front_ids == first.front_ids
        assert again.layers == first.layers
    # Insufficient last whatever it costs; within the sufficient group, the declared order.
    assert first.ranked_ids == ("cap:a", "cap:b", "cap:d", "cap:c", "cap:e")


@pytest.mark.requirement("VER-005")
@pytest.mark.spec_test("T-VER-005")
def test_a_tie_on_the_pareto_front_is_resolved_by_the_configured_fallback():
    """Same candidates, two policy VERSIONS that differ only in fallback order -> two rankings,
    each reproducible. The fallback, not the implementation, decides."""
    solve = _c("cap:solve", wall_clock_s=90, human_minutes=0)
    person = _c("cap:person", wall_clock_s=10, human_minutes=30)
    assert pareto_layers(
        [solve, person], (CostDimension.WALL_CLOCK_S, CostDimension.HUMAN_MINUTES)
    ) == {
        "cap:solve": 0,
        "cap:person": 0,
    }
    people_first = _policy((CostDimension.HUMAN_MINUTES, CostDimension.WALL_CLOCK_S), "1.0.0")
    time_first = _policy((CostDimension.WALL_CLOCK_S, CostDimension.HUMAN_MINUTES), "2.0.0")
    assert rank([solve, person], people_first).ranked_ids == ("cap:solve", "cap:person")
    assert rank([solve, person], time_first).ranked_ids == ("cap:person", "cap:solve")
    # Fully equal on every declared dimension: the tie-break rule (capability id) decides.
    twin_a, twin_b = _c("cap:twin-b", wall_clock_s=5), _c("cap:twin-a", wall_clock_s=5)
    assert rank([twin_a, twin_b], people_first).ranked_ids == ("cap:twin-a", "cap:twin-b")
    assert cost_order([twin_a, twin_b], people_first) == ("cap:twin-a", "cap:twin-b")


@pytest.mark.requirement("VER-005")
@pytest.mark.spec_test("T-VER-005")
def test_the_planner_returns_an_identical_plan_for_identical_input_and_policy_version():
    regs = registries()
    first = plan(regs, rivals()).plan
    for _ in range(5):
        again = plan(registries(), rivals()).plan
        assert again.ranked_action_ids == first.ranked_action_ids
        assert again.sufficiency_results == first.sufficiency_results
        assert again.pareto_front_ids == first.pareto_front_ids
        assert again.chosen_action_id == first.chosen_action_id
        assert again.rationale == first.rationale
    assert (first.selection_policy_id, first.selection_policy_version) == (
        sp.SELECTION_POLICY_ID,
        sp.SELECTION_POLICY_VERSION,
    )


@pytest.mark.requirement("VER-005")
@pytest.mark.spec_test("T-VER-005")
def test_a_plan_whose_choice_is_not_its_first_sufficient_action_cannot_be_built():
    base = plan(registries(), rivals()).plan
    later = next(a for a in base.ranked_action_ids[1:] if base.sufficiency_results[a].sufficient)
    with pytest.raises(ValidationError, match="first sufficient action"):
        VerificationPlan.model_validate({**base.model_dump(), "chosen_action_id": later})
    with pytest.raises(ValidationError, match="ranks"):
        VerificationPlan.model_validate(
            {**base.model_dump(), "ranked_action_ids": base.ranked_action_ids[:-1]}
        )
    with pytest.raises(ValidationError, match="another plan's rationale"):
        VerificationPlan.model_validate(
            {**base.model_dump(), "rationale_ref": "vpl:other#rationale"}
        )
    stop = PlanRationale(decision=PlanDecision.NO_SUFFICIENT_ACTION, summary="stop")
    with pytest.raises(ValidationError, match="no action is sufficient"):
        VerificationPlan.model_validate(
            {
                **base.model_dump(),
                "chosen_action_id": None,
                "rationale": stop.model_dump(),
            }
        )
    lone = SufficiencySummary(sufficient=False, reason="NO_OUTCOME_CHANGES_THE_DECISION")
    assert not lone.sufficient
