"""The v1.1 safety protocol, its new records, and the pre-registered evaluation plan.

WHAT v1.1 ADDS TO v1.0 (both declared here, before any v1.1 evaluation world ran):

    refit fixpoint     v1.0 decides which experiments the claim "predicts a signal in" ONCE, at the
                       fit made before the probes. The probes move the fitted amplitudes, so an
                       experiment can become a signal experiment only after a refit -- and v1.0
                       then endorses without it (reproduced on development seeds:
                       `docs/audit/discovery-safety-v1.1-2026-11-04/refit-bypass-before.log`).
                       v1.1 recomputes the signal set after EVERY admitted observation (each probe,
                       each replicate, each exclusion as noise), probes a newly emerged signal
                       experiment before any null one, and endorses only when every experiment
                       that was a signal experiment at ANY of those fits -- the final one included
                       -- was run. The union is never smaller than v1.0's set, so on the same data
                       v1.1's coverage requirement is never weaker than v1.0's
    localized checks   v1.0's adequacy is one global chi-square plus a 4-sigma per-entry bound. A
                       deviation confined to one or two experiments is diluted in the global sum.
                       v1.1 adds, for each DISTINCT experiment among the admitted observations, the
                       chi-square of that experiment's standardised residuals (all its entries,
                       all its replicates) under the hypothesis's global fit, with k = the number
                       of residuals; the family of per-experiment p-values is tested with Holm's
                       step-down procedure at family-wise level `alpha_localized`. Any rejection
                       makes the hypothesis inadequate, exactly like a global failure (it is
                       replicated, and the completeness check holds every catalog hypothesis to it)

    Using k (not k minus fitted parameters) for a per-experiment test under a GLOBAL fit makes the
    test conservative: fitted residuals are smaller than the noise, so it rejects less often than
    its nominal level when the hypothesis is right.

THE EVALUATION PLAN (`PLAN`) is declared beside the protocol and hashed with it: the development
seeds the design was tuned on, the previously inspected evaluation seeds (reported, labelled, never
held-out for v1.1), and the NEW held-out seeds, derived from fixed strings so that nobody chose
them. They are generated (and the worlds run) only after the design-freeze commit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from lab_brain.discovery.model import DiscoveryResult, stable_digest
from lab_brain.discovery_safety.model import AdequacyTest, SafetyAssessment, SafetyProtocol

#: Holm's step-down procedure over the per-experiment p-values (the only correction declared).
HOLM = "holm-step-down"


@dataclass(frozen=True)
class SafetyProtocolV11(SafetyProtocol):
    """v1.0's thresholds unchanged, plus the two v1.1 additions.

    refit_fixpoint     recompute the signal set after every admitted observation; coverage is over
                       the union of every signal set computed (False: v1.0's single pre-probe set)
    localized_check    the per-experiment predictive checks (False: v1.0's global test only)
    alpha_localized    their family-wise level, over the distinct experiments observed (Holm)
    defer_localized_replication  a failure of the localized checks ALONE is replicated only once
                       nothing affordable is left to probe (a global failure is replicated at once,
                       as in v1.0). Development showed that replicating a localized false alarm
                       first can spend the unit a decisive probe needed; deferring keeps every
                       probe v1.0 would have run, and an unaffordable replicate leaves the failure
                       UNREPLICATED -- abstention, never endorsement
    max_noise_exclusions_per_experiment  v1.0 attributes a failing observation to noise whenever
                       the claim is adequate without it (its replicate included). Repeated, that
                       ratchet can exclude a systematic deviation one observation at a time
                       (development: two of three `cutback` runs excluded, a surrogate endorsed).
                       In v1.1 an experiment that already had this many observations excluded as
                       noise does not get another: a further failure there counts as REPRODUCED

    Fixed on development seeds only (5_000_000, 1 and 7_000_000; `PLAN`) before any v1.1
    evaluation world was generated. `signal_coverage` stays 1.0: the Human Owner approved the
    STRICT setting on 2026-11-04 (no endorsement without verified adequacy; lower low-budget
    in-catalog accuracy accepted for far fewer force-fits) as the frozen default.
    """

    version: str = "1.1.0"
    refit_fixpoint: bool = True
    localized_check: bool = True
    alpha_localized: float = 1e-2
    localized_correction: str = HOLM
    defer_localized_replication: bool = True
    max_noise_exclusions_per_experiment: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0 < self.alpha_localized < 1:
            raise ValueError("alpha_localized is a probability")
        if self.max_noise_exclusions_per_experiment < 0:
            raise ValueError("max_noise_exclusions_per_experiment is a count")
        if self.localized_correction != HOLM:
            raise ValueError(f"the only declared multiplicity correction is {HOLM}")


SAFETY_V11 = SafetyProtocolV11()


@dataclass(frozen=True)
class LocalizedCheck:
    """One experiment's predictive check under a hypothesis's global fit."""

    experiment_id: str
    #: The admitted observations of this experiment (replicates), in the order taken.
    observations: tuple[str, ...]
    chi2: float
    #: Residuals in the statistic (entries x replicates); also its degrees of freedom.
    k: int
    p_value: float
    #: Holm's level for this p-value's rank: alpha / (m - rank).
    level: float
    rejected: bool
    #: The observation of this experiment with the largest |standardised residual|, and that value.
    worst_observation: str
    worst_z: float


@dataclass(frozen=True)
class AdequacyTestV11(AdequacyTest):
    """v1.0's record (global test) extended with the localized checks. `adequate` is the v1.1
    decision: the global test AND (when enabled) no Holm rejection."""

    global_adequate: bool = True
    localized: tuple[LocalizedCheck, ...] = ()
    #: Experiments whose check was rejected (declared order of first observation).
    localized_failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefitCoverage:
    """How the signal set moved with the fit, and whether coverage held under the last one."""

    #: The signal set at the fit made before any probe (what v1.0 judges coverage against).
    initial_signals: tuple[str, ...]
    #: The signal set at the fit to every admitted observation, after the last one.
    final_signals: tuple[str, ...]
    #: The union of every signal set computed, in declared order: what coverage is judged against.
    signal_history: tuple[str, ...]
    #: In the union but not in the initial set: predictions that emerged only after a refit.
    emerged_after_refit: tuple[str, ...]
    #: How many times the signal set was recomputed (once per admitted observation, and at the end).
    recomputations: int
    #: Signal experiments (of the union) never run.
    uncovered: tuple[str, ...]
    #: True when every experiment of the union was run: coverage is a fixpoint under the final fit.
    stable: bool


@dataclass(frozen=True)
class SafeRunV11:
    """The scored result, the engine's own result, the assessment (v1.0's record, written under the
    v1.1 protocol), and what v1.1 adds: the refit trace and the claim's localized checks."""

    result: DiscoveryResult
    engine: DiscoveryResult
    assessment: SafetyAssessment
    refit: RefitCoverage | None
    #: The claim's members' final adequacy tests, with their localized checks.
    member_tests: tuple[AdequacyTestV11, ...] = field(default=())


# -- the pre-registered evaluation plan ------------------------------------------------------


def derived_base_seed(label: str) -> int:
    """A base seed nobody chose: 3_000_000_000 + 1000 * (SHA-256(label) mod 1_000_000).

    Every seed range run before is below 2_100_000_000, and a base reaches at most base + 15_999
    (16 classes x 1000), so a derived base is disjoint from all of them by construction."""
    digest = int(hashlib.sha256(label.encode("utf-8")).hexdigest(), 16)
    return 3_000_000_000 + 1000 * (digest % 1_000_000)


@dataclass(frozen=True)
class SeedRange:
    label: str
    base_seed: int
    #: Worlds per class (held-out generator) or per kind (benchmark world generator).
    per_group: int
    role: str


DEVELOPMENT = "DEVELOPMENT"
PREVIOUSLY_INSPECTED = "PREVIOUSLY_INSPECTED_NOT_HELD_OUT_FOR_V1_1"
HELD_OUT_V11 = "HELD_OUT_FOR_V1_1"

HELD_OUT_LABEL = "lab-brain/discovery-safety-v1.1/held-out-worlds/2026-11-04"
CURVE_LABEL = "lab-brain/discovery-safety-v1.1/benchmark-worlds/2026-11-04"


@dataclass(frozen=True)
class EvaluationPlanV11:
    """Everything the v1.1 evaluation runs, declared before it runs."""

    plan_id: str = "lab-brain/discovery-safety-v1.1-evaluation"
    arms: tuple[tuple[str, str], ...] = (
        ("B2", "frozen Discovery engine (2026-11-01), no safety layer"),
        ("B3", "frozen engine + out-of-catalog safety gate v1.0"),
        ("B4", "frozen engine + out-of-catalog safety gate v1.1"),
    )
    budgets: tuple[int, ...] = (8, 12, 24, 48)
    #: Realized-cost checkpoints, as fractions of each run's cap (pre-registered ladder).
    checkpoints: tuple[float, ...] = (0.25, 0.5, 1.0)
    development: tuple[SeedRange, ...] = (
        SeedRange("v1.0 development held-out worlds", 5_000_000, 6, DEVELOPMENT),
        SeedRange("engine development worlds", 1, 6, DEVELOPMENT),
        SeedRange("v1.1 development held-out worlds", 7_000_000, 15, DEVELOPMENT),
    )
    previously_inspected: tuple[SeedRange, ...] = (
        SeedRange("P3 held-out worlds", 2_026_610_200, 15, PREVIOUSLY_INSPECTED),
        SeedRange("v1.0 new held-out worlds", 2_026_810_400, 15, PREVIOUSLY_INSPECTED),
    )
    held_out: tuple[SeedRange, ...] = (
        SeedRange(HELD_OUT_LABEL, derived_base_seed(HELD_OUT_LABEL), 15, HELD_OUT_V11),
    )
    #: The benchmark's world kinds (in-catalog, compositions, noise-only, undeclared truth).
    benchmark_worlds: SeedRange = SeedRange(
        CURVE_LABEL, derived_base_seed(CURVE_LABEL), 25, HELD_OUT_V11
    )
    #: Base seeds of every range run before v1.1 (all evaluation and development ranges).
    seeds_used_before: tuple[int, ...] = (
        1,
        5_000_000,
        2_026_110_100,
        2_026_110_200,
        2_026_610_200,
        2_026_810_400,
    )

    def __post_init__(self) -> None:
        fresh = [*self.held_out, self.benchmark_worlds]
        used = [*self.seeds_used_before, *(r.base_seed for r in self.development)]
        for r in fresh:
            for base in used:
                if abs(r.base_seed - base) < 20_000:
                    raise ValueError(f"{r.label} overlaps a seed range used before ({base})")
        if sorted(self.checkpoints) != list(self.checkpoints) or self.checkpoints[-1] != 1.0:
            raise ValueError("checkpoints increase and end at the cap")

    @property
    def digest(self) -> str:
        return stable_digest(self)


PLAN = EvaluationPlanV11()


__all__ = [
    "CURVE_LABEL",
    "DEVELOPMENT",
    "HELD_OUT_LABEL",
    "HELD_OUT_V11",
    "HOLM",
    "PLAN",
    "PREVIOUSLY_INSPECTED",
    "SAFETY_V11",
    "AdequacyTestV11",
    "EvaluationPlanV11",
    "LocalizedCheck",
    "RefitCoverage",
    "SafeRunV11",
    "SafetyProtocolV11",
    "SeedRange",
    "derived_base_seed",
]
