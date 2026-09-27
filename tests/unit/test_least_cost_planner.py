"""VER-001 at the planner: cheap sufficient checks first, the simulator only when they cannot
decide, the reason recorded -- and no action at all when the record already decides.

    VER-001    下一個 verification action 必須有 predicted discriminatory outcome + estimated cost；
               若較便宜 evidence 已足夠，不得無理由升級到 simulator。
    T-VER-001  Planner 先檢查已存在 evidence / cheap actions；只有較便宜層不足時才升級 simulator，
               並記錄選擇理由。

These are the planner's half, in memory and without a database. The end-to-end half -- the same
choices made by the loop, persisted, and checked by `011k` -- is `tests/e2e/test_vs_sp_001_vertical_
postgres.py`.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.capability import ActionType, Availability
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import IndependenceSummary
from lab_brain.core.models.verification import PlanDecision
from lab_brain.domains.silicon_photonics import vertical as sp
from tests.vertical_units import T0, exact_match, plan, registries, rival, rivals


def _supported_by_inspection(mechanism: str):  # type: ignore[no-untyped-def]
    state = rival(mechanism)
    relation = RelationJudgment(
        relation_id=f"rel:{mechanism}",
        from_entity_id=f"obs:{mechanism}",
        to_entity_id=f"hyp:{mechanism}",
        relation_type=RelationType.SUPPORTS,
        supporting_attestation_ids=(f"att:{mechanism}",),
        condition_match_ref="cmt:unit",
        project_id=state.view.project_id,
        valid_from=T0,
        created_at=T0,
    )
    return type(state)(
        view=state.view.model_copy(update={"admitted_authority_classes": (sp.DESIGN_INSPECTION,)}),
        admitted_relations=(relation,),
        predictions=state.predictions,
        condition_matches=(exact_match(),),
        independence=IndependenceSummary(independent_count=1),
    )


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_the_cheapest_sufficient_check_is_chosen_and_it_is_not_the_simulator():
    regs = registries()
    result = plan(regs, rivals())
    chosen = result.plan.chosen_action_id
    assert result.plan.rationale.decision is PlanDecision.ACT
    assert regs.capabilities.resolve(chosen).action_type is ActionType.ANALYTICAL_RULE_CHECK
    # Every candidate carries a predicted discriminating outcome and an estimated cost.
    for action_id in result.plan.candidate_action_ids:
        summary = result.plan.sufficiency_results[action_id]
        assert summary.sufficient
        assert summary.discriminating, action_id
        assert action_id in result.costs
    solves = [
        a
        for a in result.plan.ranked_action_ids
        if regs.capabilities.resolve(a).action_type is ActionType.SIMULATION
    ]
    assert result.plan.ranked_action_ids.index(chosen) < min(
        result.plan.ranked_action_ids.index(a) for a in solves
    )


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_the_simulator_is_chosen_only_when_the_cheaper_layer_cannot_decide_and_says_why():
    """Contact and normalization already rejected: the inspections are still candidates -- their
    predictions exist -- but no outcome of theirs can move a CONTRADICTED rival. The mesh study is
    chosen, and the plan records, for each cheaper candidate, why it was passed over."""
    regs = registries()
    states = (
        rival("contact", state=BeliefState.CONTRADICTED),
        rival("normalization", state=BeliefState.CONTRADICTED),
        rival("mesh"),
        rival("dopant"),
    )
    result = plan(regs, states)
    assert result.plan.chosen_action_id == sp.CAP_MESH_SENSITIVITY
    passed_over = {step.action_id: step.reason for step in result.plan.rationale.escalation}
    assert set(passed_over) == {sp.CAP_EXTRACTION_CONSISTENCY, sp.CAP_INSPECT_CONNECTIVITY}
    for reason in passed_over.values():
        assert reason.startswith("not sufficient: NO_OUTCOME_CHANGES_THE_DECISION")
    assert "2 cheaper candidate(s) were considered first" in result.plan.rationale.summary


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_when_admitted_evidence_already_decides_nothing_new_is_spent():
    regs = registries()
    result = plan(regs, (_supported_by_inspection("contact"), rival("mesh")))
    assert result.plan.rationale.decision is PlanDecision.EXISTING_EVIDENCE_DECIDES
    assert result.plan.chosen_action_id is None
    assert any(
        "hyp:contact: ACTIVE -> SUPPORTED" in line
        for line in result.plan.rationale.existing_evidence
    )


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_nothing_sufficient_means_stopping_not_spending():
    regs = registries()
    states = tuple(
        rival(m, state=BeliefState.CONTRADICTED)
        for m in ("contact", "normalization", "mesh", "dopant", "probe")
    )
    result = plan(regs, states)
    assert result.plan.rationale.decision is PlanDecision.NO_SUFFICIENT_ACTION
    assert result.plan.chosen_action_id is None
    assert all(not s.sufficient for s in result.plan.sufficiency_results.values())


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_executed_and_unavailable_capabilities_are_not_candidates():
    regs = registries()
    regs.capabilities.set_availability(sp.CAP_FOURPOINT_PROBE, Availability.UNAVAILABLE)
    result = plan(
        regs,
        rivals(),
        exclude=frozenset({sp.CAP_EXTRACTION_CONSISTENCY, sp.CAP_INSPECT_CONNECTIVITY}),
    )
    candidates = set(result.plan.candidate_action_ids)
    assert sp.CAP_FOURPOINT_PROBE not in candidates
    assert not candidates & {sp.CAP_EXTRACTION_CONSISTENCY, sp.CAP_INSPECT_CONNECTIVITY}
    assert result.plan.chosen_action_id == sp.CAP_MESH_SENSITIVITY


class _Memory:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def similar_failures(self, project_id: str, symptom: str) -> tuple[str, ...]:
        self.asked.append((project_id, symptom))
        return ("fan:earlier-contact",)


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_the_historical_case_is_consulted_first_and_informs_without_deciding():
    regs = registries()
    memory = _Memory()
    with_history = plan(regs, rivals(), case_memory=memory, symptom="Rs flat and high")
    without = plan(registries(), rivals())
    assert memory.asked == [("prj:unit", "Rs flat and high")]
    assert with_history.plan.rationale.precedents == ("fan:earlier-contact",)
    assert with_history.plan.ranked_action_ids == without.plan.ranked_action_ids
    assert with_history.plan.chosen_action_id == without.plan.chosen_action_id
