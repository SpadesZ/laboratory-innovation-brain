"""`011k` for every writer of SQL: a stored plan's choice is its own ranking's first sufficient
action (VER-001), a selection policy version is immutable (VER-005), plans are append-only."""

from __future__ import annotations

import json

import pytest

from lab_brain.core.models.verification import PlanDecision
from lab_brain.core.repositories.verification_plans import (
    SqlVerificationPlanStore,
    VerificationPlanStoreError,
)
from lab_brain.domains.silicon_photonics import vertical as sp
from tests.vertical_units import PROJECT, T0, plan, registries, rivals

pytestmark = pytest.mark.postgres


def _seed(db) -> SqlVerificationPlanStore:  # type: ignore[no-untyped-def]
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'unit')", (PROJECT,))
    db.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, start_time)"
        " VALUES ('epi:unit', %s, 'trc:unit', 'diagnose', %s)",
        (PROJECT, T0),
    )
    store = SqlVerificationPlanStore(db)
    store.add_policy(sp.selection_policy())
    return store


def _raw_insert(db, **overrides):  # type: ignore[no-untyped-def]
    base = plan(registries(), rivals()).plan
    row = {
        "plan_id": "vpl:raw",
        "project_id": base.project_id,
        "episode_id": base.episode_id,
        "candidate_action_ids": list(base.candidate_action_ids),
        "ranked_action_ids": list(base.ranked_action_ids),
        "sufficiency_results": json.dumps(
            {k: v.model_dump(mode="json") for k, v in base.sufficiency_results.items()}
        ),
        "pareto_front_ids": list(base.pareto_front_ids),
        "selection_policy_id": base.selection_policy_id,
        "selection_policy_version": base.selection_policy_version,
        "chosen_action_id": base.chosen_action_id,
        "rationale_ref": "vpl:raw#rationale",
        "rationale": json.dumps(base.rationale.model_dump(mode="json")),
        "created_at": T0,
    }
    row.update(overrides)
    columns = ", ".join(row)
    db.execute(
        f"INSERT INTO verification_plans ({columns}) VALUES ({', '.join(['%s'] * len(row))})",
        tuple(row.values()),
    )


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_a_plan_round_trips_through_the_model(db):
    store = _seed(db)
    stored = store.add_plan(plan(registries(), rivals()).plan)
    assert store.get_plan(PROJECT, stored.plan_id) == stored
    assert store.plans_for_episode(PROJECT, "epi:unit") == (stored,)
    assert store.get_plan("prj:other", stored.plan_id) is None


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_sql_refuses_a_plan_that_passes_over_a_cheaper_sufficient_action(db):
    _seed(db)
    base = plan(registries(), rivals()).plan
    expensive = next(
        a for a in reversed(base.ranked_action_ids) if base.sufficiency_results[a].sufficient
    )
    with pytest.raises(Exception, match="first sufficient action of its own ranking"):
        _raw_insert(db, chosen_action_id=expensive)


@pytest.mark.requirement("VER-005")
@pytest.mark.spec_test("T-VER-005")
def test_sql_refuses_a_ranking_that_is_not_the_candidates(db):
    _seed(db)
    base = plan(registries(), rivals()).plan
    with pytest.raises(Exception, match="not a permutation"):
        _raw_insert(db, ranked_action_ids=list(base.ranked_action_ids[:-1]))


def test_sql_refuses_stopping_while_an_action_is_sufficient_and_a_foreign_rationale(db):
    _seed(db)
    base = plan(registries(), rivals()).plan
    stop = base.rationale.model_copy(update={"decision": PlanDecision.NO_SUFFICIENT_ACTION})
    with pytest.raises(Exception, match="no action is sufficient"):
        _raw_insert(
            db,
            chosen_action_id=None,
            rationale=json.dumps(stop.model_dump(mode="json")),
        )
    with pytest.raises(Exception, match="rationale_is_its_own"):
        _raw_insert(db, rationale_ref="vpl:someone-else#rationale")


@pytest.mark.requirement("VER-005")
@pytest.mark.spec_test("T-VER-005")
def test_a_selection_policy_version_is_immutable_and_a_plan_is_append_only(db):
    store = _seed(db)
    with pytest.raises(Exception, match="immutable"):
        db.execute(
            "UPDATE selection_policies SET lexicographic_fallback = ARRAY['wall_clock_s']"
            " WHERE policy_id = %s",
            (sp.SELECTION_POLICY_ID,),
        )
    changed = sp.selection_policy().model_copy(
        update={"lexicographic_fallback": sp.selection_policy().lexicographic_fallback[::-1]}
    )
    with pytest.raises(VerificationPlanStoreError, match="already recorded differently"):
        store.add_policy(changed)
    with pytest.raises(Exception, match="selection_policies_order_cost_dimensions"):
        db.execute(
            "INSERT INTO selection_policies (policy_id, version, pareto_dimensions,"
            " lexicographic_fallback, tie_break_rule, effective_from)"
            " VALUES ('slp:scalar', '1.0.0', ARRAY['normalized_cost', 'wall_clock_s'],"
            " ARRAY['wall_clock_s'], 'CAPABILITY_ID', now())"
        )
    stored = store.add_plan(plan(registries(), rivals()).plan)
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM verification_plans WHERE plan_id = %s", (stored.plan_id,))
    with pytest.raises(Exception, match="append-only"):
        db.execute(
            "UPDATE verification_plans SET chosen_action_id = NULL WHERE plan_id = %s",
            (stored.plan_id,),
        )
