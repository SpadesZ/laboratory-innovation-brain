"""The v1.1 evaluation's bookkeeping: categories, abstention reasons, proposals, costs, checkpoints.

Development seeds only (base 1). These tests hold the evaluation module to its definitions: one
category per run, a stage-1 proposal never counted as an identification, realized costs taken from
the laboratory's meter, and checkpoint answers that count only runs whose whole realized cost fits
under the checkpoint (commit-at-termination; never an invented interim answer).
"""

from __future__ import annotations

from functools import cache

import pytest

from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety.v11 import evaluation as ev
from lab_brain.discovery_safety.v11.model import PLAN, derived_base_seed
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    MOTIVATING_EXPERIMENT,
    ring_catalog,
    ring_scenario,
)

CATALOG = ring_catalog()
BUDGETS = (8, 24)


@cache
def _worlds() -> tuple[held_out.HeldOutWorld, ...]:
    return held_out.held_out_worlds(
        CATALOG, seeds_per_class=1, base_seed=DEVELOPMENT_BASE_SEED, protocol=DISCOVERY
    )


@cache
def held() -> tuple[ev.RunRecord, ...]:
    return tuple(
        ev.run_held_out_setting(
            CATALOG,
            _worlds(),
            budgets=BUDGETS,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            arms=ev.make_arms(),
        )
    )


@cache
def control() -> tuple[ev.RunRecord, ...]:
    return tuple(
        ev.run_control_setting(
            CATALOG,
            _worlds(),
            budgets=BUDGETS,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            arms=ev.make_arms(),
        )
    )


def test_every_run_has_exactly_one_category_and_held_out_has_no_identification():
    records = held()
    assert len(records) == len(_worlds()) * len(BUDGETS) * len(ev.ARM_IDS)
    assert {r.category for r in records} <= set(ev.CATEGORIES)
    assert not any(r.category == ev.CORRECT_IDENTIFICATION for r in records)
    assert all(r.spent <= r.budget for r in records)
    for r in records:
        assert (r.category == ev.NO_CLAIM) == (
            r.claim == () and r.outcome != "NO_EFFECT_BEYOND_NOISE"
        )
        assert (r.reason == "") == (r.category != ev.NO_CLAIM)


def test_safe_arms_report_their_gate_reasons_and_b2_its_outcome():
    reasons = {(r.arm, r.reason) for r in held() if r.category == ev.NO_CLAIM}
    safe = {reason for arm, reason in reasons if arm in (ev.B3_ID, ev.B4_ID)}
    assert safe and all(
        r.split(":")[0]
        in {
            "ADEQUACY_UNVERIFIED",
            "CLAIM_INADEQUATE",
            "CATALOG_INCOMPLETE",
            "CATALOG_INCOMPLETE_UNREPLICATED",
            "NO_ENGINE_CLAIM",
        }
        for r in safe
    )
    assert all(reason.startswith("STOPPED") for arm, reason in reasons if arm == "B2")


def test_a_proposal_is_never_an_identification_and_the_summary_refuses_one():
    records = [*held(), *control()]
    assert any(r.proposal for r in records)
    assert not any(r.proposal and r.category == ev.CORRECT_IDENTIFICATION for r in records)
    forged = [
        ev.RunRecord(
            "control",
            "w",
            "k",
            "B4",
            8,
            3,
            "x",
            ("hyp:a",),
            ev.CORRECT_IDENTIFICATION,
            "",
            True,
            False,
            "d",
        )
    ]
    with pytest.raises(AssertionError):
        ev.category_table(forged)


def test_the_control_identifies_the_truth_and_counts_alternatives_separately():
    table = ev.summarize(list(control()), BUDGETS)
    for budget in BUDGETS:
        for arm in ev.ARM_IDS:
            t = table[str(budget)][arm]["all"]
            assert sum(t[c]["k"] for c in ev.CATEGORIES) == t[ev.NO_CLAIM]["n"] == len(_worlds())
            assert t["proposals_counted_as_identification"] == 0
    assert table["24"]["B2"]["all"][ev.CORRECT_IDENTIFICATION]["k"] > 0
    assert table["comparison_basis"] == ev.EQUAL_CAP


def test_realized_cost_summary_is_exact():
    rows = [
        ev.RunRecord(
            "held_out", str(i), "k", "B2", 12, s, "o", (), ev.NO_CLAIM, "r", False, False, "d"
        )
        for i, s in enumerate((2, 4, 4, 9, 12))
    ]
    cost = ev.realized_cost(rows)
    assert (cost["mean"], cost["median"], cost["min"], cost["max"]) == (6.2, 4.0, 2, 12)
    assert cost["distribution"] == {"2": 1, "4": 2, "9": 1, "12": 1}
    assert (cost["p10"], cost["p90"]) == (2.0, 12.0)


def test_a_checkpoint_counts_only_runs_whose_whole_cost_fits():
    records = list(held())
    table = ev.checkpoint_table(records, BUDGETS, PLAN.checkpoints, primary_only=True)
    assert (
        table["comparison_basis"] == ev.CHECKPOINT_BASIS
        and "frozen engine" in table["anytime_missing"]
    )
    for budget in BUDGETS:
        for fraction in PLAN.checkpoints:
            at = table[str(budget)][f"{fraction:g}"]
            c = at["checkpoint_units"]
            assert c == int(fraction * budget)
            for arm in ev.ARM_IDS:
                mine = [r for r in records if r.budget == budget and r.arm == arm and not r.aliased]
                row = at["arms"][arm]
                assert row[ev.NO_ANSWER_COMMITTED]["k"] == sum(r.spent > c for r in mine)
                assert row[ev.FORCE_FIT]["k"] == sum(
                    r.spent <= c and r.category == ev.FORCE_FIT for r in mine
                )
        # At the full cap every run has committed: the checkpoint equals the equal-cap table.
        assert all(
            table[str(budget)]["1"]["arms"][a][ev.NO_ANSWER_COMMITTED]["k"] == 0 for a in ev.ARM_IDS
        )


def test_the_plan_seeds_are_derived_and_disjoint_from_everything_run_before():
    for r in (*PLAN.held_out, PLAN.benchmark_worlds):
        assert r.base_seed == derived_base_seed(r.label)
        assert r.base_seed > 2_100_000_000
    assert PLAN.budgets == (8, 12, 24, 48) and PLAN.checkpoints == (0.25, 0.5, 1.0)
    with pytest.raises(ValueError):
        type(PLAN)(seeds_used_before=(PLAN.held_out[0].base_seed,))


def test_the_benchmark_setting_runs_every_world_kind():
    scenario = ring_scenario(1, base_seed=DEVELOPMENT_BASE_SEED)
    records = ev.run_benchmark_setting(scenario, budgets=(12,), arms=ev.make_arms())
    assert len({r.kind for r in records}) == len({w.kind for w in scenario.worlds})
    table = ev.summarize(records, (12,))
    assert "per_kind" in table["12"]["B4"]
