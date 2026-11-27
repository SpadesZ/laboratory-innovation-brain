"""M4's exit gate, as a computation over recorded loop outcomes (§26.1, VER-001).

    §26.1 M4  fixed benchmark set (not cherry-picked) demonstrates root-cause correctness and
              avoids unnecessary high-cost action in predefined cases.
    VER-001   若較便宜 evidence 已足夠，不得無理由升級到 simulator。

WHAT IS MEASURED, PER CASE AND STRATEGY:

    correct                 the loop ended where the fixture said it would, written before any
                            run: the confirmed cause for a resolvable case, the stop reason and the
                            next action for one that waits on a person or a seat, INCONCLUSIVE for
                            one nothing can resolve. A loop that confirmed SOMETHING on a case
                            whose answer is "you need a person" is wrong, not partially right.
    high-cost executed      SIMULATION / MEASUREMENT / FABRICATION actions actually executed
    unjustified escalation  a high-cost action executed while the SAME plan held a sufficient
                            action of a cheaper type (§9.3's rule checks, lookups, historical
                            comparison). This is VER-001's sentence, counted.
    unnecessary high cost   high-cost actions executed in a case the fixture marks
                            `cheap_resolvable` -- its cause is confirmable by a rule check alone.

THE GATE: the least-cost strategy is correct on every case, never escalates unjustifiably, and
executes no high-cost action where none is needed. And the benchmark must be able to tell: the
simulate-first baseline, run on the same cases through the same loop, must escalate unjustifiably
at least once -- otherwise the set cannot distinguish a cost-aware planner from a cost-blind one,
and passing it would demonstrate nothing.

Everything here is pure: the harness runs the episodes; this module judges and renders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from lab_brain.core.models.capability import ActionType
from lab_brain.core.models.cost import CostVector

HIGH_COST_TYPES = frozenset({ActionType.SIMULATION, ActionType.MEASUREMENT, ActionType.FABRICATION})
CHEAP_TYPES = frozenset(
    {
        ActionType.EXISTING_EVIDENCE_LOOKUP,
        ActionType.ANALYTICAL_RULE_CHECK,
        ActionType.HISTORICAL_CASE_COMPARISON,
    }
)


@dataclass(frozen=True)
class StepRecord:
    """One executed or requested action, with what its plan held beside it."""

    action_id: str
    action_type: ActionType
    executed: bool
    estimate: CostVector
    #: The other candidates of the same plan that were SUFFICIENT, with their types.
    sufficient_alternatives: tuple[tuple[str, ActionType], ...]

    @property
    def high_cost(self) -> bool:
        return self.action_type in HIGH_COST_TYPES

    @property
    def unjustified(self) -> bool:
        return (
            self.executed
            and self.high_cost
            and any(t in CHEAP_TYPES for _, t in self.sufficient_alternatives)
        )


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    strategy: str
    stop: str
    confirmed: str | None
    steps: tuple[StepRecord, ...]
    #: The action the loop stopped on (the one a person or a seat must supply), if any.
    pending_action: str | None
    heuristic_candidates: int
    expected: Mapping[str, object]
    cheap_resolvable: bool

    @property
    def executed(self) -> tuple[StepRecord, ...]:
        return tuple(s for s in self.steps if s.executed)

    @property
    def high_cost_executed(self) -> int:
        return sum(1 for s in self.executed if s.high_cost)

    @property
    def unjustified_escalations(self) -> int:
        return sum(1 for s in self.steps if s.unjustified)

    @property
    def unnecessary_high_cost(self) -> int:
        return self.high_cost_executed if self.cheap_resolvable else 0

    @property
    def cost(self) -> CostVector:
        total = CostVector()
        for step in self.executed:
            total = total.plus(step.estimate)
        return total

    @property
    def correct(self) -> bool:
        expected = self.expected
        if self.stop != expected.get("stop") or self.confirmed != expected.get("cause"):
            return False
        pending = expected.get("next_action") or expected.get("waiting_on")
        if pending is not None and self.pending_action != pending:
            return False
        wanted = expected.get("heuristic_candidates")
        return wanted is None or self.heuristic_candidates == wanted


@dataclass(frozen=True)
class BenchmarkRun:
    benchmark_set_id: str
    fixture_digest: str
    primary: str
    baseline: str
    records: tuple[CaseRecord, ...]

    def of(self, strategy: str) -> tuple[CaseRecord, ...]:
        return tuple(r for r in self.records if r.strategy == strategy)

    def conditions(self) -> tuple[tuple[str, bool, str], ...]:
        primary, baseline = self.of(self.primary), self.of(self.baseline)
        wrong = [r.case_id for r in primary if not r.correct]
        unjustified = sum(r.unjustified_escalations for r in primary)
        unnecessary = sum(r.unnecessary_high_cost for r in primary)
        baseline_unjustified = sum(r.unjustified_escalations for r in baseline)
        return (
            (
                "root-cause correctness: every case ends where the fixture says",
                not wrong,
                f"{len(primary) - len(wrong)}/{len(primary)} correct"
                + (f" (wrong: {', '.join(wrong)})" if wrong else ""),
            ),
            (
                "VER-001: no high-cost action while a cheaper sufficient action was planned",
                unjustified == 0,
                f"{unjustified} unjustified escalation(s)",
            ),
            (
                "no high-cost action in a cheap-resolvable case",
                unnecessary == 0,
                f"{unnecessary} unnecessary high-cost action(s)",
            ),
            (
                "the set discriminates: the simulate-first baseline escalates unjustifiably",
                baseline_unjustified > 0,
                f"baseline: {baseline_unjustified} unjustified escalation(s)",
            ),
        )

    @property
    def passes(self) -> bool:
        return all(ok for _, ok, _ in self.conditions())


def _cost_cell(cost: CostVector) -> str:
    money = cost.money_estimate.normalize() if cost.money_estimate else Decimal(0)
    return (
        f"{cost.wall_clock_s} s / seat {cost.license_seat_s} s / "
        f"{cost.human_minutes} min / ${money}"
    )


def render_report(run: BenchmarkRun, fixture_path: str) -> str:
    lines = [
        "# VS-SP-001 root-cause benchmark (M4 exit gate)",
        "",
        "Generated by `scripts/run_root_cause_benchmark.py`; checked by "
        "`tests/e2e/test_root_cause_benchmark_postgres.py`. Do not edit by hand.",
        "",
        f"- Benchmark set: `{run.benchmark_set_id}`",
        f"- Fixture: `{fixture_path}` (`{run.fixture_digest}`)",
        f"- Strategies: `{run.primary}` (M4's planner) vs `{run.baseline}` (baseline)",
        "- Backends: deterministic mocks and local design readers -- no Lumerical, no licence "
        "seat, no probe station. The licensed replay TST-001 asks for is not claimed.",
        "",
        "## Gate",
        "",
        "| Condition | Result | Detail |",
        "|---|---|---|",
    ]
    for name, ok, detail in run.conditions():
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += ["", f"**Overall: {'PASS' if run.passes else 'FAIL'}**", ""]
    for strategy in (run.primary, run.baseline):
        lines += [
            f"## `{strategy}`",
            "",
            "| Case | Stop | Confirmed | Correct | Executed (in order) | Pending | High-cost | "
            "Unjustified | Estimated cost |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in run.of(strategy):
            executed = ", ".join(s.action_id.removeprefix("cap:sp.") for s in r.executed) or "-"
            pending = (r.pending_action or "-").removeprefix("cap:sp.")
            lines.append(
                f"| {r.case_id} | {r.stop} | {r.confirmed or '-'} | "
                f"{'yes' if r.correct else 'NO'} | {executed} | {pending} | "
                f"{r.high_cost_executed} | {r.unjustified_escalations} | {_cost_cell(r.cost)} |"
            )
        records = run.of(strategy)
        total = CostVector()
        for r in records:
            total = total.plus(r.cost)
        lines += [
            "",
            f"Totals: {sum(r.correct for r in records)}/{len(records)} correct; "
            f"{sum(r.high_cost_executed for r in records)} high-cost action(s) executed; "
            f"{sum(r.unjustified_escalations for r in records)} unjustified; "
            f"estimated {_cost_cell(total)}.",
            "",
        ]
    return "\n".join(lines)


def evaluate(
    records: Sequence[CaseRecord],
    *,
    benchmark_set_id: str,
    fixture_digest: str,
    primary: str,
    baseline: str,
) -> BenchmarkRun:
    return BenchmarkRun(
        benchmark_set_id=benchmark_set_id,
        fixture_digest=fixture_digest,
        primary=primary,
        baseline=baseline,
        records=tuple(records),
    )


__all__ = [
    "CHEAP_TYPES",
    "HIGH_COST_TYPES",
    "BenchmarkRun",
    "CaseRecord",
    "StepRecord",
    "evaluate",
    "render_report",
]
