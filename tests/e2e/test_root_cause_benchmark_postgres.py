"""M4's exit gate: the fixed, non-cherry-picked VS-SP-001 benchmark (§26.1, VER-001, TST-001).

    §26.1 M4  fixed benchmark set (not cherry-picked) demonstrates root-cause correctness and
              avoids unnecessary high-cost action in predefined cases.

Runs every case of `fixtures/vertical/sp_rs_root_cause_benchmark.json` under M4's planner and the
simulate-first baseline, each episode from a freshly reset database, and asserts two things: the
gate's conditions hold, and the committed report is exactly what this run renders -- so a change
that moves any case's outcome, action sequence or cost fails here and the diff shows what moved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_brain.verification.root_cause_benchmark import render_report
from tests.postgres_fixtures import reset_database
from tests.vertical_fixtures import (
    FIXTURE_PATH,
    LEAST_COST,
    SIMULATE_FIRST,
    load_fixture,
    run_benchmark,
)

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "benchmarks" / "root_cause_benchmark_report.md"


@pytest.fixture(scope="module")
def benchmark(postgres_connection):  # type: ignore[no-untyped-def]
    run = run_benchmark(postgres_connection, reset_database)
    reset_database(postgres_connection)
    return run


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_the_fixed_benchmark_passes_the_m4_exit_gate(benchmark):
    conditions = {name: (ok, detail) for name, ok, detail in benchmark.conditions()}
    assert benchmark.passes, conditions
    primary = benchmark.of(LEAST_COST)
    assert len(primary) == len(load_fixture()["cases"])
    assert all(r.correct for r in primary)
    assert sum(r.unjustified_escalations for r in primary) == 0
    assert sum(r.unnecessary_high_cost for r in primary) == 0


@pytest.mark.requirement("TST-001")
@pytest.mark.spec_test("T-E2E-SP-001")
def test_the_benchmark_covers_every_way_the_loop_can_end(benchmark):
    """Not cherry-picked: cases the loop cannot resolve are in the set and end unresolved."""
    stops = {r.stop for r in benchmark.of(LEAST_COST)}
    assert stops == {
        "CONFIRMED",
        "AWAITING_RESOURCE",
        "HUMAN_ACTION_REQUIRED",
        "NO_SUFFICIENT_ACTION",
    }
    unresolved = [r for r in benchmark.of(LEAST_COST) if r.confirmed is None]
    assert len(unresolved) >= 3
    fx = load_fixture()
    mechanisms_confirmed = {r.confirmed for r in benchmark.of(LEAST_COST) if r.confirmed}
    assert mechanisms_confirmed == set(fx["mechanisms"]) - {"probe_artifact"}


def test_the_baseline_is_measurably_worse_on_the_same_cases(benchmark):
    primary, baseline = benchmark.of(LEAST_COST), benchmark.of(SIMULATE_FIRST)
    assert sum(r.unjustified_escalations for r in baseline) > 0
    assert sum(r.high_cost_executed for r in baseline) > sum(r.high_cost_executed for r in primary)
    assert sum(r.correct for r in baseline) < sum(r.correct for r in primary)


def test_the_committed_report_is_current(benchmark):
    rendered = render_report(benchmark, FIXTURE_PATH.relative_to(ROOT).as_posix()) + "\n"
    committed = REPORT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == rendered, (
        "benchmarks/root_cause_benchmark_report.md is stale: regenerate it with "
        "`python scripts/run_root_cause_benchmark.py --disposable`"
    )
