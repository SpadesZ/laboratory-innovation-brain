"""The v1.5 arm protocol (B8), the plan, and the held-out seed rule.

WHAT v1.5 CHANGES, AND WHY (root causes measured on development seeds; the v1.4 held-out ranges
were seen in round 5 and are development data now; see docs/reports/discovery-safety-v1.5.md):

    nothing in the EVALUATOR: the rule is v1.4's (`EVALUATOR_RULE_V14`), byte for byte. Every
                    input that decides SUPPORTED is computed by the evaluator from its own ledger;
                    a rival is closed only by a FAILED prediction (or a failed registration of the
                    rival itself); grammar rivals and "no effect" against grammar shapes stay
    arm (B8)        B7's rival test aimed at a separation of tau_close from as many rivals as
                    possible, counting a rival as "reached" only past a fixed threshold, and
                    registered only the strongest rival. B8 chooses the rival test (experiment,
                    number of runs) that maximises the EXPECTED NUMBER OF RIVALS REFUTED -- the sum
                    over open rivals of the probability that the rival's prediction fails the
                    evaluator's pass test if the claim is true (noncentral chi-square under the
                    declared instrument noise and both predictive SDs) -- per unit cost, and
                    registers the rival most likely to fail on it. When every option is expected
                    to refute less than `min_expected_refutations`, B7's choice is used
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from lab_brain.discovery.model import stable_digest
from lab_brain.discovery_safety.v12.model import DEVELOPMENT, SeedRange
from lab_brain.discovery_safety.v14.model import PLAN as PLAN_V14
from lab_brain.discovery_safety.v14.model import SafetyProtocolV14


@dataclass(frozen=True)
class SafetyProtocolV15(SafetyProtocolV14):
    """v1.4's switches, plus:

    targeted_selection       choose rival tests by expected refutations per unit cost
    rival_first              run rival-targeted tests BEFORE the fixed-order signal probes while
                             one is expected to refute enough rivals
    min_expected_refutations below this expected count for every option, fall back to B7's choice
    max_targeted_tests       targeted tests in the front phase (the later rival tests keep their
                             own count, `max_rival_tests`)
    (a claim of "no effect" runs exactly as B7: see `_GateV15._targeting`)
    """

    version: str = "1.5.0"
    targeted_selection: bool = True
    rival_first: bool = True
    min_expected_refutations: float = 0.5
    max_targeted_tests: int = 6


SAFETY_V15 = SafetyProtocolV15()


# -- the held-out seed rule -----------------------------------------------------------------------

#: The domain string of the held-out seed derivation (fixed before the design freeze).
HOLDOUT_DOMAIN = "lab-brain/discovery-safety-v1.5/held-out-seeds@1"
HELD_OUT_V15 = "HELD_OUT_FOR_V1_5"
HOLDOUT_ROLES = ("held-out-worlds", "benchmark-worlds")


def holdout_base_seed(
    commit: str, role: str, used: tuple[int, ...], first_attempt: int = 0
) -> tuple[int, int]:
    """(base seed, attempt) for `role`, derived from the design-freeze commit's FULL id:

        attempt k = first_attempt, first_attempt + 1, ...: digest = SHA-256(HOLDOUT_DOMAIN ||
        0x00 || role || 0x00 || commit || 0x00 || k (decimal)); base = 3_000_000_000 + 1000 *
        (int(digest) mod 1_000_000); the first attempt whose base lies at least 20_000 from every
        range in `used` is taken.

    v1.4's rule with the v1.5 domain. `first_attempt` is 0 for the single clean run; a rerun that
    could not be avoided would start at 2 and be reported."""
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("the held-out seeds are derived from a full 40-hex commit id")
    for attempt in range(first_attempt, first_attempt + 1000):
        text = f"{HOLDOUT_DOMAIN}\x00{role}\x00{commit}\x00{attempt}"
        digest = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        base = 3_000_000_000 + 1000 * (digest % 1_000_000)
        if all(abs(base - u) >= 20_000 for u in used):
            return base, attempt
    raise ValueError("no non-overlapping seed range found")  # pragma: no cover


@dataclass(frozen=True)
class EvaluationPlanV15:
    """Everything the v1.5 evaluation runs and how it is scored, declared before it runs (the
    pre-registration in docs/reports/discovery-safety-v1.5-preregistration.md restates it)."""

    plan_id: str = "lab-brain/discovery-safety-v1.5-evaluation"
    arms: tuple[tuple[str, str], ...] = (
        ("B4", "frozen engine + safety gate v1.1 (the current offline safety BASELINE)"),
        ("B7", "safety gate v1.4, unchanged"),
        ("B8", "safety gate v1.5 (rival-targeted experiment choice)"),
    )
    budgets: tuple[int, ...] = (6, 8, 10, 12, 16, 24, 48)
    scoring: str = (
        "sai35-candidate.5 classify_outcome+verified_evidence+assertion_status (61af6ef); "
        "evaluator-computed EvaluatorRuleV14 (unchanged)"
    )
    per_world_tolerance: int = 1
    bootstrap_resamples: int = 2000
    #: (Y, X): differences are Y - X, paired on identical worlds. B4 IS the v1.1 baseline.
    comparisons: tuple[tuple[str, str], ...] = (("B8", "B7"), ("B8", "B4"), ("B7", "B4"))
    #: The primary comparison and the anchors of the decision rule.
    primary: tuple[str, str] = ("B8", "B7")
    primary_metric: str = "own_correct"
    primary_anchors: tuple[int, ...] = (12, 16, 24)
    held_out_per_class: int = 8
    benchmark_per_kind: int = 12
    #: Every range seen before v1.5 is development data now, including v1.4's held-out (3905077000)
    #: and benchmark (3168619000) ranges (SPENT: never again clean held-out evidence).
    development: tuple[SeedRange, ...] = (
        *PLAN_V14.development,
        SeedRange("v1.4 held-out worlds (seen in round 5, spent)", 3_905_077_000, 8, DEVELOPMENT),
        SeedRange("v1.4 benchmark worlds (seen in round 5, spent)", 3_168_619_000, 12, DEVELOPMENT),
    )
    seeds_used_before: tuple[int, ...] = (
        *PLAN_V14.seeds_used_before,
        3_905_077_000,
        3_168_619_000,
    )

    def __post_init__(self) -> None:
        if list(self.budgets) != sorted(set(self.budgets)):
            raise ValueError("caps increase")
        if not set(self.primary_anchors) <= set(self.budgets):
            raise ValueError("anchors are caps of the plan")

    @property
    def used(self) -> tuple[int, ...]:
        return tuple(sorted({*self.seeds_used_before, *(r.base_seed for r in self.development)}))

    def held_out_seeds(self, commit: str, first_attempt: int = 0) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        used = self.used
        for role in HOLDOUT_ROLES:
            base, attempt = holdout_base_seed(commit, role, used, first_attempt)
            out[role] = {"base_seed": base, "attempt": attempt}
            used = (*used, base)
        return out

    @property
    def digest(self) -> str:
        return stable_digest(self)


PLAN = EvaluationPlanV15()


__all__ = [
    "HELD_OUT_V15",
    "HOLDOUT_DOMAIN",
    "HOLDOUT_ROLES",
    "PLAN",
    "SAFETY_V15",
    "EvaluationPlanV15",
    "SafetyProtocolV15",
    "holdout_base_seed",
]
