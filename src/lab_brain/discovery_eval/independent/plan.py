"""The pre-registered analysis plan, written before anyone has seen a result on the sealed set.

Every value here is in the kit manifest (`plan_digest`); the analysis code refuses a checkpoint,
metric or comparison that is not in this plan (SAI 3.5 Appendix J §3.3.1, S2-CE-5).

PRIMARY ENDPOINT (one). The paired per-case difference, candidate minus baseline, in the
EXACT_IDENTIFICATION indicator at the primary checkpoint c* = the cap, over the cases whose truth
the engine's catalog expresses (categories declared, composition, null): the scalar Appendix J §5
proposes. The primary comparison is the newest filled candidate slot against the v1.1 baseline B4:
B8 - B4 when the B8 slot is pinned at freeze time, otherwise B7 - B4. Interval: paired percentile
bootstrap over cases (10,000 resamples, SHA-256 counter-mode indices, seed fixed below), 95 %.

SAFETY CO-PRIMARY. The paired difference, candidate minus baseline, in the candidate.5 ERROR
indicator (FORCE_FIT, WRONG_CLAIM, UNSUPPORTED_CLAIM, or a deficient run) at c*, over every
non-aliased case; non-inferiority margin 0.02 on the upper bound of the same bootstrap interval.

DEFICIENT RUNS (Appendix J §3.4). A run that is not COMPLETED (crashed, invalid, truncated, or a
trace that fails verification) stays in every denominator and is scored AGAINST its own arm in
every paired comparison: as 0 on a credit indicator and 1 on an error indicator when it is the
candidate's, as 1 on credit and 0 on error when it is the baseline's. A deficient record can never
help the arm that produced it. If more than 2 % of all runs are deficient for reasons other than
a crash, or more than 5 % of cases have a deficient run in a compared arm, the study is
COST_UNMATCHED / INVALID and supports no claim that one arm is better.

DECISION RULES (applied mechanically by `analysis.decide`):

    BETTER        primary lower bound > 0 AND safety upper bound <= margin
    WORSE         primary upper bound < 0, OR safety lower bound > 0
    SAFETY_FAIL   primary lower bound > 0 but safety upper bound > margin
    INCONCLUSIVE  anything else
    INVALID       the study-level deficiency limits above are exceeded

SECONDARY (labelled secondary, Holm-adjusted across the listed comparisons within each metric and
checkpoint family, never able to replace the primary result): every comparison in
`comparisons` at every checkpoint of the ladder for credited (EXACT, INDISTINGUISHABLE, VALIDATED
NEW), exact, error and face-value correct; exact McNemar tests on the discordant pairs; the
anytime curve (credited and exact against checkpoint); per-category counts; realized cost
distributions; the area under the anytime curve over the ladder.

NOT ANSWERABLE BY THIS PLAN. Arm A (a frontier model) and arm B (the PostgreSQL LIB workflow) do
not exist offline; this kit compares offline arms (B4, B6, B7, B8 when pinned) only. It is not a
G-D result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from lab_brain.core.canonical_json import canonical_hash

PRIMARY_CATEGORIES = ("declared", "composition", "null")
SAFETY_EXCLUDED = ("aliased_held_out",)
METRICS = ("exact", "credited", "error", "own_correct")


@dataclass(frozen=True)
class AnalysisPlan:
    plan_id: str = "lab-brain/discovery-independent-eval-kit/analysis-plan@1"
    scoring: str = (
        "SAI 3.5 candidate.5 categories (spec commit 61af6ef) judged by the frozen v1.4 evaluator "
        "rule (EvaluatorRuleV14 1.4.0) on evaluator-held evidence before each declaration"
    )
    #: The single run's cap: every arm runs every case ONCE with this many cost units.
    cap: int = 48
    #: Frozen realized-cost checkpoints (strictly increasing, the last is the cap).
    ladder: tuple[int, ...] = (6, 8, 12, 16, 24, 32, 48)
    primary_checkpoint: int = 48
    primary_metric: str = "exact"
    primary_categories: tuple[str, ...] = PRIMARY_CATEGORIES
    safety_metric: str = "error"
    safety_excluded_categories: tuple[str, ...] = SAFETY_EXCLUDED
    non_inferiority_margin: float = 0.02
    baseline: str = "B4"
    #: The primary candidate: the first of these whose slot is filled at freeze time.
    primary_candidates: tuple[str, ...] = ("B8", "B7")
    #: Secondary comparisons (candidate, reference), when both slots are filled.
    comparisons: tuple[tuple[str, str], ...] = (
        ("B8", "B4"),
        ("B7", "B4"),
        ("B6", "B4"),
        ("B8", "B7"),
        ("B7", "B6"),
    )
    secondary_metrics: tuple[str, ...] = METRICS
    confidence: float = 0.95
    bootstrap_resamples: int = 10_000
    bootstrap_seed: int = 20261124
    multiplicity: str = (
        "primary: none (one endpoint); safety: non-inferiority on the same interval; secondary: "
        "Holm across the filled comparisons for each (metric, checkpoint), at family-wise 0.05, on "
        "exact McNemar p-values; intervals are reported unadjusted and labelled so"
    )
    #: Study-level limits (Appendix J §3.4 / §8).
    max_incident_share: float = 0.02
    max_deficient_case_share: float = 0.05
    #: Wall-clock limit per run in the composition root (a run past it is CRASHED).
    run_seconds: int = 1800
    arm_session_rule: str = (
        "the arm states each measurement's session; the evaluator refuses a session that goes "
        "back (INVALID) and records it; it does not assign sessions"
    )

    def __post_init__(self) -> None:
        if list(self.ladder) != sorted(set(self.ladder)) or not self.ladder:
            raise ValueError("the ladder strictly increases")
        if self.ladder[-1] != self.cap or self.primary_checkpoint not in self.ladder:
            raise ValueError("the ladder ends at the cap and holds the primary checkpoint")
        if self.primary_metric not in METRICS or self.safety_metric not in METRICS:
            raise ValueError("unknown metric")

    def as_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["non_inferiority_margin"] = format(self.non_inferiority_margin, ".4f")
        out["confidence"] = format(self.confidence, ".4f")
        out["max_incident_share"] = format(self.max_incident_share, ".4f")
        out["max_deficient_case_share"] = format(self.max_deficient_case_share, ".4f")
        out["comparisons"] = [list(c) for c in self.comparisons]
        return out

    @property
    def digest(self) -> str:
        return canonical_hash(self.as_json())

    def primary_comparison(self, filled: tuple[str, ...]) -> tuple[str, str]:
        for arm in self.primary_candidates:
            if arm in filled:
                return arm, self.baseline
        raise ValueError("no primary candidate arm is filled")

    def filled_comparisons(self, filled: tuple[str, ...]) -> list[tuple[str, str]]:
        return [(a, b) for a, b in self.comparisons if a in filled and b in filled]

    def checkpoint(self, value: int) -> int:
        if value not in self.ladder:
            raise ValueError(f"checkpoint {value} is not in the frozen ladder {self.ladder}")
        return value


PLAN = AnalysisPlan()

__all__ = ["METRICS", "PLAN", "PRIMARY_CATEGORIES", "SAFETY_EXCLUDED", "AnalysisPlan"]
