"""T-LLM-002: the fixed SiPho debate benchmark, its comparison, and the calibration it produces.

    §15.4    Structured Debate 是否減少 groupthink 必須可證偽 ... 若增加多 Agent 只增加
             token 而不改善這些指標，應縮減角色/round。門檻由校準產生（LLM-002）。
    T-LLM-002  fixed SiPho benchmark produces baseline distributions; the benchmark MUST compare the
             debate mechanism against a baseline/disabled condition on the same cases, so a claim of
             groupthink reduction can be refuted by the result and not merely illustrated;
             BenchmarkPolicy schema stores metric/threshold/sample size/calibration artifacts/
             version; no hard gate before calibration; the benchmark MUST record per-case round
             count and show it varies with case difficulty.

THREE CONDITIONS, SAME CASES, SAME REASONER. Every case is run under

    DEBATE        the full protocol: Stage A specialists, the Critic's inverted retrieval,
                  escalation by trigger
    BASELINE      §26's "baseline/disabled condition": no Critic, no specialists -- the Hypothesis
                  Engine's set as proposed
    NO_INVERTED   the Critic without its own retrieval (§15.3's D, minus the mechanism §7.2
                  credits)

with the same deterministic model transport. So a difference between conditions is a difference
the protocol made, and nothing else.

THE VERDICT CAN COME OUT AGAINST THE DEBATE. `compare` returns SUPPORTED only when the debate kept
the true mechanism on a case the baseline lost it, never lost one the baseline kept, and changed a
final set at least once. A Critic that agrees with everything produces REFUTED on the same fixture
-- `tests/contract/test_debate_benchmark.py` runs exactly that -- which is what "refutable, not
merely illustrated" requires of the benchmark rather than of the implementation.

ROUNDS ARE CHECKED AGAINST DIFFICULTY, NOT RECORDED AND ADMIRED. `round_count_problems` fails a run
whose rounds are constant, do not rise with the fixture's declared difficulty order, or sit at the
configured maximum on every case -- the implementation §7.2 forbids even when every metric is
recorded correctly.

THE THRESHOLD IS READ OFF THE RUN. `calibrate` produces the one BenchmarkPolicy this repository arms
a gate with: `critic_bundle_divergence`, AT_LEAST the smallest debate-level divergence among debates
that kept the true mechanism, sample size and two calibration artifacts (the fixture digest and the
digest of the per-case result table) recorded. Nothing in this module or in any gate module is a
typed threshold.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import median
from typing import Any

from lab_brain.cognition.debate import DebateOutcome, DebatePolicy
from lab_brain.cognition.debate_metrics import CRITIC_BUNDLE_DIVERGENCE
from lab_brain.core.models.benchmark import BenchmarkPolicy, MetricDirection


class Condition(StrEnum):
    DEBATE = "DEBATE"
    BASELINE = "BASELINE"
    NO_INVERTED = "NO_INVERTED"


#: The declared policy of each condition. BASELINE switches off both multi-agent mechanisms, which
#: is §26's "disabled condition"; NO_INVERTED keeps the Critic and removes its own retrieval.
CONDITION_POLICIES: Mapping[Condition, DebatePolicy] = {
    Condition.DEBATE: DebatePolicy(),
    Condition.BASELINE: DebatePolicy(critic_enabled=False, specialists_enabled=False),
    Condition.NO_INVERTED: DebatePolicy(perform_inverted_retrieval=False),
}


class Verdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"


class CalibrationError(ValueError):
    """The run cannot produce a threshold: no debate kept the truth with a measurable divergence."""


RunCase = Callable[[Mapping[str, Any], Condition], DebateOutcome]


def _normal(text: str) -> str:
    return " ".join(text.lower().split())


@dataclass(frozen=True)
class CaseResult:
    """One case under one condition: what the protocol did and whether the truth survived it."""

    case_id: str
    difficulty: str
    condition: Condition
    rounds: int
    max_rounds: int
    stop_reason: str
    truth_retained: bool
    truth_proposed: bool
    admitted: int
    surviving: int
    critic_changed_final_set: bool
    position_diversity: Decimal | None
    critic_bundle_divergence: Decimal | None
    surviving_diversity: Decimal | None
    additional_evidence_items: int
    additional_token_count: int
    total_token_count: int
    triggers: tuple[str, ...]

    def as_row(self) -> dict[str, object]:
        def dec(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "case_id": self.case_id,
            "difficulty": self.difficulty,
            "condition": self.condition.value,
            "rounds": self.rounds,
            "max_rounds": self.max_rounds,
            "stop_reason": self.stop_reason,
            "truth_retained": self.truth_retained,
            "truth_proposed": self.truth_proposed,
            "admitted": self.admitted,
            "surviving": self.surviving,
            "critic_changed_final_set": self.critic_changed_final_set,
            "position_diversity": dec(self.position_diversity),
            "critic_bundle_divergence": dec(self.critic_bundle_divergence),
            "surviving_diversity": dec(self.surviving_diversity),
            "additional_evidence_items": self.additional_evidence_items,
            "additional_token_count": self.additional_token_count,
            "total_token_count": self.total_token_count,
            "triggers": list(self.triggers),
        }


def score(
    case: Mapping[str, Any],
    fixture: Mapping[str, Any],
    condition: Condition,
    outcome: DebateOutcome,
) -> CaseResult:
    """Score one outcome against the case's truth. The only place `truth` is read."""
    truth = _normal(fixture["mechanisms"][case["truth"]]["mechanism"])
    record = outcome.record
    mechanisms = {c.hypothesis_id: _normal(c.hypothesis.mechanism) for c in outcome.certificates}
    return CaseResult(
        case_id=case["case_id"],
        difficulty=case["difficulty"],
        condition=condition,
        rounds=record.rounds,
        max_rounds=record.max_rounds,
        stop_reason=record.stop_reason,
        truth_retained=truth in {mechanisms[h] for h in record.surviving_hypothesis_ids},
        truth_proposed=truth in set(mechanisms.values()),
        admitted=len(outcome.certificates),
        surviving=len(record.surviving_hypothesis_ids),
        critic_changed_final_set=record.critic_changed_final_set,
        position_diversity=record.position_diversity,
        critic_bundle_divergence=record.critic_bundle_divergence,
        surviving_diversity=record.surviving_hypothesis_diversity,
        additional_evidence_items=record.additional_evidence_items,
        additional_token_count=record.additional_token_count,
        total_token_count=sum(c.actual.token_count or 0 for c in outcome.calls),
        triggers=record.escalation_triggers,
    )


@dataclass(frozen=True)
class BenchmarkRun:
    benchmark_set_id: str
    fixture_version: str
    fixture_digest: str
    difficulty_order: tuple[str, ...]
    results: tuple[CaseResult, ...]

    def under(self, condition: Condition) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if r.condition is condition)

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical per-case table: the calibration's second artifact."""
        rows = [r.as_row() for r in self.results]
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate(
    fixture: Mapping[str, Any],
    run_case: RunCase,
    *,
    fixture_digest: str,
    conditions: Sequence[Condition] = tuple(Condition),
) -> BenchmarkRun:
    """Run every case under every condition, in fixture order, and score each outcome."""
    results = [
        score(case, fixture, condition, run_case(case, condition))
        for case in fixture["cases"]
        for condition in conditions
    ]
    return BenchmarkRun(
        benchmark_set_id=fixture["benchmark_set_id"],
        fixture_version=fixture["version"],
        fixture_digest=fixture_digest,
        difficulty_order=tuple(fixture["difficulty_order"]),
        results=tuple(results),
    )


# -- distributions -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Distribution:
    """n, and the min / median / max of the measured values; `None` entries are not measured."""

    n: int
    unmeasured: int
    minimum: Decimal | None
    median: Decimal | None
    maximum: Decimal | None

    @classmethod
    def of(cls, values: Sequence[Decimal | None]) -> Distribution:
        measured = sorted(v for v in values if v is not None)
        if not measured:
            return cls(len(values), len(values), None, None, None)
        return cls(
            n=len(values),
            unmeasured=len(values) - len(measured),
            minimum=measured[0],
            median=Decimal(str(median(measured))),
            maximum=measured[-1],
        )


DISTRIBUTION_METRICS: Mapping[str, Callable[[CaseResult], Decimal | None]] = {
    "rounds": lambda r: Decimal(r.rounds),
    "position_diversity": lambda r: r.position_diversity,
    CRITIC_BUNDLE_DIVERGENCE: lambda r: r.critic_bundle_divergence,
    "critic_changed_final_set": lambda r: Decimal(int(r.critic_changed_final_set)),
    "surviving_hypothesis_diversity": lambda r: r.surviving_diversity,
    "additional_evidence_items": lambda r: Decimal(r.additional_evidence_items),
    "additional_token_count": lambda r: Decimal(r.additional_token_count),
    "total_token_count": lambda r: Decimal(r.total_token_count),
}


def distributions(run: BenchmarkRun) -> dict[Condition, dict[str, Distribution]]:
    """T-LLM-002's "baseline distributions": every §15.4 metric, per condition."""
    return {
        condition: {
            name: Distribution.of([metric(r) for r in run.under(condition)])
            for name, metric in DISTRIBUTION_METRICS.items()
        }
        for condition in Condition
        if run.under(condition)
    }


# -- the two pass conditions --------------------------------------------------------------------


def rounds_by_difficulty(run: BenchmarkRun, condition: Condition) -> dict[str, tuple[int, ...]]:
    return {
        level: tuple(r.rounds for r in run.under(condition) if r.difficulty == level)
        for level in run.difficulty_order
    }


def round_count_problems(run: BenchmarkRun, condition: Condition = Condition.DEBATE) -> list[str]:
    """§7.2 / v3.3-a6: per-case rounds must vary with difficulty. Empty when they do."""
    results = run.under(condition)
    problems: list[str] = []
    if not results:
        return [f"no {condition.value} results to check"]
    if len({r.rounds for r in results}) == 1:
        problems.append(
            f"every {condition.value} case ran {results[0].rounds} round(s); a round count that "
            "does not vary is not a consequence of the evidence"
        )
    if all(r.rounds >= r.max_rounds for r in results):
        problems.append(
            f"every {condition.value} case ran the configured maximum of {results[0].max_rounds} "
            "rounds -- §7.2: 簡單問題不得固定跑 8 rounds"
        )
    by_level = rounds_by_difficulty(run, condition)
    means: list[tuple[str, Decimal]] = []
    for level, counts in by_level.items():
        if not counts:
            problems.append(f"difficulty {level} has no {condition.value} case")
            continue
        means.append((level, Decimal(sum(counts)) / Decimal(len(counts))))
    for (easier, low), (harder, high) in itertools.pairwise(means):
        if not high > low:
            problems.append(
                f"mean rounds do not rise from {easier} ({low:.2f}) to {harder} ({high:.2f}); "
                "the round count must vary with case difficulty"
            )
    return problems


@dataclass(frozen=True)
class Comparison:
    """DEBATE against BASELINE, case by case, on the true mechanism's survival."""

    verdict: Verdict
    debate_retained: int
    baseline_retained: int
    cases: int
    wins: tuple[str, ...]
    losses: tuple[str, ...]
    changed_final_set: int
    token_ratio: Decimal | None
    reasons: tuple[str, ...]


def compare(run: BenchmarkRun, *, against: Condition = Condition.BASELINE) -> Comparison:
    """The refutable claim. SUPPORTED needs a win, no loss, and a Critic that changed a set."""
    debate = {r.case_id: r for r in run.under(Condition.DEBATE)}
    other = {r.case_id: r for r in run.under(against)}
    shared = [c for c in debate if c in other]
    wins = tuple(c for c in shared if debate[c].truth_retained and not other[c].truth_retained)
    losses = tuple(c for c in shared if other[c].truth_retained and not debate[c].truth_retained)
    changed = sum(1 for c in shared if debate[c].critic_changed_final_set)
    debate_tokens = sum(debate[c].total_token_count for c in shared)
    other_tokens = sum(other[c].total_token_count for c in shared)
    reasons: list[str] = []
    if not shared:
        reasons.append("the conditions share no case")
    if not wins:
        reasons.append(
            f"the debate kept the true mechanism on no case {against.value} lost it -- more calls, "
            "no better answer (§15.4: 應縮減角色/round)"
        )
    if losses:
        reasons.append(
            f"the debate lost the true mechanism where {against.value} kept it: {losses}"
        )
    if changed == 0:
        reasons.append("the Critic changed no final hypothesis set")
    return Comparison(
        verdict=Verdict.REFUTED if reasons else Verdict.SUPPORTED,
        debate_retained=sum(1 for c in shared if debate[c].truth_retained),
        baseline_retained=sum(1 for c in shared if other[c].truth_retained),
        cases=len(shared),
        wins=wins,
        losses=losses,
        changed_final_set=changed,
        token_ratio=(
            (Decimal(debate_tokens) / Decimal(other_tokens)).quantize(Decimal("0.01"))
            if other_tokens
            else None
        ),
        reasons=tuple(reasons),
    )


# -- calibration --------------------------------------------------------------------------------


def calibration_samples(run: BenchmarkRun) -> tuple[Decimal, ...]:
    """Debate-level divergences of the DEBATE cases that kept the true mechanism."""
    return tuple(
        r.critic_bundle_divergence
        for r in run.under(Condition.DEBATE)
        if r.truth_retained and r.critic_bundle_divergence is not None
    )


def calibration_artifact_refs(run: BenchmarkRun) -> tuple[str, str]:
    return (
        f"fixture:{run.benchmark_set_id}@{run.fixture_version}#sha256:{run.fixture_digest}",
        f"benchmark-run:{run.benchmark_set_id}#sha256:{run.digest}",
    )


def calibrate(
    run: BenchmarkRun,
    *,
    domain: str,
    policy_id: str,
    version: str,
    calibrated_at: dt.datetime,
) -> BenchmarkPolicy:
    """The Critic-divergence gate, read off the run: AT_LEAST the smallest truth-keeping value.

    Inactive when produced -- activation is a separate, deliberate act (`BenchmarkStore.activate`),
    so running the benchmark never arms a gate by itself.
    """
    samples = calibration_samples(run)
    if not samples:
        raise CalibrationError(
            f"benchmark {run.benchmark_set_id} produced no DEBATE case that kept the true "
            "mechanism with a measurable Critic divergence; there is nothing to read a threshold "
            "off, and §15.4 forbids typing one"
        )
    return BenchmarkPolicy(
        policy_id=policy_id,
        domain=domain,
        benchmark_set_id=run.benchmark_set_id,
        metric_key=CRITIC_BUNDLE_DIVERGENCE,
        threshold=min(samples),
        direction=MetricDirection.AT_LEAST,
        calibrated_at=calibrated_at,
        sample_size=len(samples),
        calibration_artifact_refs=calibration_artifact_refs(run),
        version=version,
        active=False,
    )


# -- the report ---------------------------------------------------------------------------------


def _fmt(value: Decimal | None) -> str:
    return "—" if value is None else f"{value.normalize():f}"


def render_report(run: BenchmarkRun, policy: BenchmarkPolicy, fixture_path: str) -> str:
    comparison = compare(run)
    ablation = compare(run, against=Condition.NO_INVERTED)
    dists = distributions(run)
    side = policy.direction.value if policy.direction else "—"
    lines = [
        "# T-LLM-002 — Structured Debate Benchmark",
        "",
        "<!-- Generated by scripts/run_debate_benchmark.py. Do not edit by hand. -->",
        "",
        "| | |",
        "|---|---|",
        "| Requirement | `LLM-002` (§7.2, §15.4, §17.19.2, `v3.3-a3`, `v3.3-a6`) |",
        f"| Benchmark set | `{run.benchmark_set_id}` v{run.fixture_version} |",
        f"| Fixture | `{fixture_path}` |",
        f"| Fixture digest | `{run.fixture_digest}` |",
        f"| Per-case table digest | `{run.digest}` |",
        "| Model transport | deterministic mock (`tests/debate_fixtures.MockScientist`); no "
        "external model, search or licensed tool was called |",
        "",
        "## Verdict",
        "",
        f"- **DEBATE vs BASELINE: {comparison.verdict.value}.** True mechanism kept on "
        f"{comparison.debate_retained}/{comparison.cases} cases with the debate, "
        f"{comparison.baseline_retained}/{comparison.cases} without it; wins "
        f"{len(comparison.wins)}, losses {len(comparison.losses)}; the Critic changed "
        f"{comparison.changed_final_set} final sets; token cost x{_fmt(comparison.token_ratio)}.",
        f"- **DEBATE vs NO_INVERTED: {ablation.verdict.value}.** Without its own retrieval the "
        f"Critic keeps the truth on {ablation.baseline_retained}/{ablation.cases} cases.",
    ]
    for reason in comparison.reasons:
        lines.append(f"  - {reason}")
    problems = round_count_problems(run)
    lines.append(
        "- **Round count varies with difficulty: "
        + ("yes." if not problems else "NO — " + "; ".join(problems))
        + "** "
        + ", ".join(
            f"{level}: {list(counts)}"
            for level, counts in rounds_by_difficulty(run, Condition.DEBATE).items()
        )
    )
    lines += [
        "",
        "## Per-case results",
        "",
        "| case | difficulty | condition | rounds | stop | truth kept | admitted→surviving | "
        "Critic divergence | position diversity | extra tokens | triggers |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in run.results:
        lines.append(
            f"| {r.case_id} | {r.difficulty} | {r.condition.value} | {r.rounds} | "
            f"{r.stop_reason} | {'yes' if r.truth_retained else 'no'} | "
            f"{r.admitted}→{r.surviving} | {_fmt(r.critic_bundle_divergence)} | "
            f"{_fmt(r.position_diversity)} | {r.additional_token_count} | "
            f"{', '.join(r.triggers) or '—'} |"
        )
    lines += [
        "",
        "## Distributions (n / unmeasured / min / median / max)",
        "",
        "| metric | " + " | ".join(c.value for c in dists) + " |",
        "|---|" + "---|" * len(dists),
    ]
    for name in DISTRIBUTION_METRICS:
        cells = []
        for condition in dists:
            d = dists[condition][name]
            cells.append(
                f"{d.n} / {d.unmeasured} / {_fmt(d.minimum)} / {_fmt(d.median)} / {_fmt(d.maximum)}"
            )
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Calibrated BenchmarkPolicy",
        "",
        "| field | value |",
        "|---|---|",
        f"| policy | `{policy.ref}` |",
        f"| domain | `{policy.domain}` |",
        f"| metric | `{policy.metric_key}` |",
        f"| threshold | {_fmt(policy.threshold)} ({side}) |",
        f"| sample size | {policy.sample_size} |",
        f"| calibrated at | {policy.calibrated_at.isoformat()} |",
    ]
    for ref in policy.calibration_artifact_refs:
        lines.append(f"| calibration artifact | `{ref}` |")
    lines += [
        "",
        "Rule: the smallest debate-level Critic divergence among DEBATE cases that kept the true "
        "mechanism. The policy is produced **inactive**; a gate reads it only after it is "
        "activated, and before that every gate verdict is ADVISORY (no hard gate before "
        "calibration).",
        "",
        "## Limits",
        "",
        "- Ten cases, one domain, one deterministic reasoner. The threshold is a calibration of "
        "this benchmark, not a population estimate; re-calibrate when the fixture, the metric "
        "version or the model route changes.",
        "- The mock reasoner is answer-blind but mechanism-aware: it measures what the protocol "
        "does with evidence, not how well a real model reasons.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "CONDITION_POLICIES",
    "DISTRIBUTION_METRICS",
    "BenchmarkRun",
    "CalibrationError",
    "CaseResult",
    "Comparison",
    "Condition",
    "Distribution",
    "RunCase",
    "Verdict",
    "calibrate",
    "calibration_artifact_refs",
    "calibration_samples",
    "compare",
    "distributions",
    "evaluate",
    "render_report",
    "round_count_problems",
    "rounds_by_difficulty",
    "score",
]
