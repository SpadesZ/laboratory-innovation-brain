"""The v1.4 protocol, the evaluator's rule v1.4, the plan, and the held-out seed rule.

WHAT v1.4 CHANGES, AND WHY (root causes found on development seeds; the v1.3 held-out and
benchmark ranges were seen in round 4 and are development data now):

    rival closure   v1.3 closed a rival of an answer when a passed registration of the answer
                    "separated" it: the two PREDICTIONS were >= tau_risky apart. That is not
                    discrimination: the observation can lie between them and satisfy both. In every
                    residual false endorsement of v1.3 (held-out `leakage.substrate-06` claimed as
                    `scatter.sidewall` at caps 24/48; aliased `geometry.width_wide-03` at cap 8;
                    benchmark `noise_glitch-06` and `noise_only_null-04` at cap 8) a rival closed
                    this way predicted the very runs that "closed" it as well as, or better than,
                    the answer. v1.4 (evaluator): a rival is closed only when the evaluator's OWN
                    prediction of it -- computed from the data recorded before a registration of
                    the answer that passed -- FAILS on that registration's runs, or when a
                    registration of the rival itself failed
    grammar rivals  v1.3 held an answer against "no effect" and no-more-complex CATALOG hypotheses
                    only; a claim could be SUPPORTED while a grammar shape (the declared term
                    grammar) was still adequate and predicted differently somewhere the arm could
                    still measure (observed: `geometry.width_wide-03`, where every adequate grammar
                    shape predicts a power-sweep response the claim does not, and power_sweep was
                    never run). v1.4: every grammar shape adequate on all the data whose fitted
                    prediction is >= tau_risky (combined SD, `max_runs` runs) from the answer's
                    fitted prediction on some AVAILABLE experiment is a rival. A grammar shape is
                    ONE cause (a declared composition moves two channels of one cause), so it counts
                    as one component under the parsimony rule. A "no effect" answer is held
                    against grammar shapes too, at their FIT (they declare no smallest effect): a
                    shape whose fitted effect is >= tau_risky from zero is evidence of an effect
                    the catalog may not express (observed on development seeds: a SUPPORTED "no
                    effect" on a world whose removed family left a 3-sigma coupling shift)
    arm             the v1.4 gate (B7) uses the v1.4 verdict; its rival tests aim at a separation of
                    `tau_close` (so that a wrong rival is likely to FAIL, not merely be far), and
                    choose the test that is expected to close the most open rivals per unit cost

Everything else is v1.3's (identity-only registrations, the evaluator's own predictions and
alternatives, multi-run tests, the null equivalence test, the parsimony fallback).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.model import stable_digest
from lab_brain.discovery_safety.v12.model import DEVELOPMENT, SeedRange
from lab_brain.discovery_safety.v13.model import PLAN as PLAN_V13
from lab_brain.discovery_safety.v13.model import EvaluatorRule, SafetyProtocolV13


@dataclass(frozen=True)
class EvaluatorRuleV14(EvaluatorRule):
    """v1.3's rule (`EvaluatorRule`), plus:

    closure        a rival R of the answer A is closed iff (a) some complete registration of A
                   passed and R's evaluator prediction for that registration (R refitted to the data
                   recorded before it; a "no effect" answer's catalog rival at its smallest declared
                   effect) fails the pass test on the same runs, or (b) a complete registration of
                   R itself failed. Separation of the predictions alone closes nothing
    grammar rivals every grammar shape adequate on all the data (global test) whose fitted
                   prediction is >= `tau_risky` from the answer's fitted prediction for `max_runs`
                   runs of some available experiment; one cause (<= 1 component)
    rivals         "no effect" while adequate; catalog hypotheses as in v1.3 (adequate, no more
                   components, distinguishable by the engine's oracle; for a grammar answer: by the
                   fitted-prediction test above); grammar rivals (for a "no effect" answer: at
                   their fit, separated from zero)
    """

    version: str = "1.4.0"
    closure_by_failed_prediction: bool = True
    grammar_rivals: bool = True


EVALUATOR_RULE_V14 = EvaluatorRuleV14()


@dataclass(frozen=True)
class SafetyProtocolV14(SafetyProtocolV13):
    """v1.3's switches, plus:

    tau_close        a rival test aims at this separation (combined SD) between the answer and the
                     rival, so that a wrong rival is likely to fail the pass test (at
                     tau_close = 4.5 a rival whose truth is the answer fails with probability > 0.9
                     on a one-entry experiment); `tau_risky` is the floor when nothing affordable
                     reaches it
    batch_rivals     a rival test is chosen to close the most open rivals per unit cost (not only
                     the strongest one)
    max_rival_tests  raised from 4: there are more rivals to close
    """

    version: str = "1.4.0"
    tau_close: float = 4.5
    batch_rivals: bool = True
    max_rival_tests: int = 6


SAFETY_V14 = SafetyProtocolV14()


# -- the held-out seed rule -----------------------------------------------------------------------

#: The domain string of the held-out seed derivation (fixed before the design freeze).
HOLDOUT_DOMAIN = "lab-brain/discovery-safety-v1.4/held-out-seeds@1"
HELD_OUT_V14 = "HELD_OUT_FOR_V1_4"
#: The roles a seed is derived for: the held-out worlds (both the family-removed and the control
#: setting) and the benchmark world kinds.
HOLDOUT_ROLES = ("held-out-worlds", "benchmark-worlds")


def holdout_base_seed(commit: str, role: str, used: tuple[int, ...]) -> tuple[int, int]:
    """(base seed, attempt) for `role`, derived from the design-freeze commit's FULL id:

        attempt k = 0, 1, 2, ...: digest = SHA-256(HOLDOUT_DOMAIN || 0x00 || role || 0x00 ||
        commit || 0x00 || k (decimal)); base = 3_000_000_000 + 1000 * (int(digest) mod 1_000_000);
        the first attempt whose base lies at least 20_000 from every range in `used` is taken.

    Nobody can choose the seeds before the freeze: the commit id is not known until it exists."""
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("the held-out seeds are derived from a full 40-hex commit id")
    for attempt in range(1000):
        text = f"{HOLDOUT_DOMAIN}\x00{role}\x00{commit}\x00{attempt}"
        digest = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        base = 3_000_000_000 + 1000 * (digest % 1_000_000)
        if all(abs(base - u) >= 20_000 for u in used):
            return base, attempt
    raise ValueError("no non-overlapping seed range found")  # pragma: no cover


@dataclass(frozen=True)
class EvaluationPlanV14:
    """Everything the v1.4 evaluation runs and how it is scored, declared before it runs. The
    held-out base seeds are NOT here: they are derived from the freeze commit (`holdout_base_seed`)
    after the freeze is pushed."""

    plan_id: str = "lab-brain/discovery-safety-v1.4-evaluation"
    arms: tuple[tuple[str, str], ...] = (
        ("B4", "frozen engine + safety gate v1.1 (the current offline safety BASELINE)"),
        ("B6", "safety gate v1.3, unchanged"),
        ("B7", "safety gate v1.4 (closure by failed prediction, grammar rivals)"),
    )
    #: The cap grid: every arm runs every world once per cap. Dense, so that each arm's anytime
    #: answers (the answer it commits to under each cap) cover the realized-cost range.
    budgets: tuple[int, ...] = (6, 8, 10, 12, 16, 24, 48)
    scoring: str = (
        "sai35-candidate.5 classify_outcome+verified_evidence+assertion_status (61af6ef); "
        "evaluator-computed EvaluatorRuleV14"
    )
    distinguish_tau: float = 5.0
    distinguish_replicates: int = 4
    #: Per-world matching: two anytime answers are at equal realized cost iff their realized costs
    #: differ by at most this many units (experiment costs are 1-3 units).
    per_world_tolerance: int = 1
    bootstrap_resamples: int = 2000
    #: (Y, X): differences are Y - X, paired on identical worlds.
    comparisons: tuple[tuple[str, str], ...] = (("B7", "B4"), ("B6", "B4"), ("B7", "B6"))
    #: Fewer worlds than v1.3 (10 / 15) for run time: seven caps and a slower arm.
    held_out_per_class: int = 8
    benchmark_per_kind: int = 12
    #: Every range seen before v1.4 is development data now, including v1.3's held-out (3218044000)
    #: and benchmark (3729592000) ranges.
    development: tuple[SeedRange, ...] = (
        *PLAN_V13.development,
        SeedRange("v1.3 held-out worlds (seen in round 4)", 3_218_044_000, 10, DEVELOPMENT),
        SeedRange("v1.3 benchmark worlds (seen in round 4)", 3_729_592_000, 15, DEVELOPMENT),
    )
    seeds_used_before: tuple[int, ...] = (
        *PLAN_V13.seeds_used_before,
        *(r.base_seed for r in PLAN_V13.held_out),
        PLAN_V13.benchmark_worlds.base_seed,
    )

    def __post_init__(self) -> None:
        if list(self.budgets) != sorted(set(self.budgets)):
            raise ValueError("caps increase")
        if self.per_world_tolerance < 0:
            raise ValueError("a tolerance is not negative")

    @property
    def used(self) -> tuple[int, ...]:
        return tuple(sorted({*self.seeds_used_before, *(r.base_seed for r in self.development)}))

    def held_out_seeds(self, commit: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        used = self.used
        for role in HOLDOUT_ROLES:
            base, attempt = holdout_base_seed(commit, role, used)
            out[role] = {"base_seed": base, "attempt": attempt}
            used = (*used, base)
        return out

    @property
    def digest(self) -> str:
        return stable_digest(self)


PLAN = EvaluationPlanV14()


__all__ = [
    "EVALUATOR_RULE_V14",
    "HELD_OUT_V14",
    "HOLDOUT_DOMAIN",
    "HOLDOUT_ROLES",
    "PLAN",
    "SAFETY_V14",
    "EvaluationPlanV14",
    "EvaluatorRuleV14",
    "SafetyProtocolV14",
    "holdout_base_seed",
]
