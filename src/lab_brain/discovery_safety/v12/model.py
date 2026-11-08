"""The v1.2 safety protocol, its records, and the pre-registered evaluation plan.

WHAT v1.2 CHANGES, AND WHY (root cause measured on development seeds; see the v1.2 report):

    allocation      v1.1's lost in-catalog identifications at small budgets are almost all
                    ADEQUACY_UNVERIFIED: the frozen engine spends the cap (half of it on
                    replicates of experiments it already ran: decisive replications and repeated
                    prospective tests), and what is left cannot pay for the claim's never-run
                    signal experiments. v1.2 runs the frozen engine on an ANYTIME LADDER of caps
                    through a gate-owned replay laboratory: the engine is re-run at cap c+1 only
                    while it has no claim and its stop was budget-bound; every measurement any
                    run made is kept (a re-run that asks for the k-th run of an experiment again
                    receives the recorded one, at no charge), so the realized cost is the cost of
                    DISTINCT measurements. The engine stops at the smallest cap at which it
                    claims, and the rest of the budget is the adequacy reserve. The engine's code
                    is untouched; only its cap is chosen
    registration    every adequacy probe is preceded by a REGISTERED PREDICTION (an evaluator-owned
                    ledger, `ledger.py`): the claim's predicted values for that run, hashed before
                    the run is requested. An endorsement additionally needs that at least one
                    risky registered prediction passed and that Holm's procedure over all of the
                    claim's registered predictions rejects none (`ledger.supported`). This is a
                    STRICTER rule than v1.1's, never a weaker one
    probe order     among the never-run signal experiments, the one whose predicted outcome is
                    farthest (per unit cost) from the strongest alternatives -- the best-fitting
                    other hypotheses the catalog expresses and the zero prediction -- is run first
    discovery       when no hypothesis the catalog expresses is adequate, candidate NEW mechanisms
                    are built from a pre-declared compositional grammar of terms (`grammar.py`; the
                    domain's declaration is handed in by the composition root), fitted to the
                    admitted data, and each adequate candidate's prediction for an unrun
                    discriminating experiment is registered before that experiment runs. A
                    candidate is answered only if its registered prediction passed, every rival
                    candidate the test separated failed, and it is adequate on all the data and
                    covers its signal experiments; otherwise it stays a PROPOSAL (never credited)

The adequacy criterion (v1.0's global test, v1.1's localized checks at Holm 0.01), `signal_coverage
= 1.0` (the Owner's STRICT setting, 2026-11-04) and every v1.0/v1.1 threshold are unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.model import DiscoveryResult, stable_digest
from lab_brain.discovery_safety.model import SafetyAssessment
from lab_brain.discovery_safety.v11.model import (
    AdequacyTestV11,
    RefitCoverage,
    SafetyProtocolV11,
)

#: Probe order: v1.1's (cheapest first, declared order on ties) or by separation per cost.
DECLARED_ORDER = "cheapest-first"
SEPARATION_ORDER = "separation-per-cost"


@dataclass(frozen=True)
class SafetyProtocolV12(SafetyProtocolV11):
    """v1.1's thresholds unchanged, plus the v1.2 switches (each one measured separately).

    anytime_allocation  run the engine on the cap ladder `ladder_start .. budget` (step 1) through
                        the replay laboratory, stopping at the first claim (False: v1.1's single
                        run at the full cap)
    ladder_start        the first cap on the ladder
    registered_probes   register a prediction before every adequacy probe (False: no ledger use)
    require_registered_support  endorse only a claim the ledger rule supports (`ledger.supported`)
    support_test        when every signal experiment was already run by the engine, spend one run
                        on a registered test of the claim (the most separating affordable
                        experiment; a replicate if nothing new is affordable)
    probe_order         DECLARED_ORDER or SEPARATION_ORDER
    alpha_prospective   family-wise level of the registered predictions of one mechanism (Holm)
    z_prospective       per-entry bound of a registered prediction
    tau_risky           a registered prediction is risky when it differs from a registered
                        alternative by at least this (combined standard units)
    max_alternatives    best-fitting other catalog hypotheses registered as alternatives
    discovery           build and prospectively test grammar candidates when the catalog is shown
                        incomplete (needs a grammar from the composition root)
    max_discovery_tests registered discovery tests per run, at most
    candidate_band      a fitted candidate's declared amplitude domain: fitted value times
                        (1 - band, 1 + band) -- fixed here, never chosen by the evaluator
    """

    version: str = "1.2.0"
    anytime_allocation: bool = True
    ladder_start: int = 2
    registered_probes: bool = True
    require_registered_support: bool = True
    support_test: bool = True
    probe_order: str = SEPARATION_ORDER
    alpha_prospective: float = 1e-2
    z_prospective: float = 4.0
    tau_risky: float = 3.0
    max_alternatives: int = 2
    rival_exclusion: bool = True
    max_rival_tests: int = 4
    gate_led: bool = True
    engine_fraction: float = 0.5
    discovery: bool = True
    max_discovery_tests: int = 3
    candidate_band: float = 0.5

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.probe_order not in (DECLARED_ORDER, SEPARATION_ORDER):
            raise ValueError(f"unknown probe order {self.probe_order!r}")
        if self.ladder_start < 1:
            raise ValueError("the ladder starts at a positive cap")
        if not 0 < self.alpha_prospective < 1:
            raise ValueError("alpha_prospective is a probability")
        if not 0 < self.candidate_band < 1:
            raise ValueError("candidate_band is a fraction in (0, 1)")
        if self.require_registered_support and not self.registered_probes:
            raise ValueError("registered support needs registered probes")


SAFETY_V12 = SafetyProtocolV12()


@dataclass(frozen=True)
class LadderStep:
    """One engine run on the anytime ladder."""

    cap: int
    outcome: str
    claim: tuple[str, ...]
    #: The engine's own spend at this cap (cached measurements included).
    engine_spent: int
    #: Distinct-measurement cost after this run (what the laboratory charged so far).
    charged_after: int


@dataclass(frozen=True)
class Allocation:
    """How the budget was split between the engine and the adequacy reserve."""

    budget: int
    ladder: tuple[LadderStep, ...]
    #: The cap of the engine run whose result was used.
    engine_cap: int
    #: Charged before the gate's own probes started (all engine runs, distinct measurements).
    charged_by_engine_runs: int
    #: Measurements an earlier ladder run made that the chosen run did not ask for (kept as data).
    orphan_measurements: tuple[str, ...]
    reserve: int


@dataclass(frozen=True)
class Registration:
    """What the gate registered (the ledger holds the same text; the evaluator re-derives it)."""

    ledger_index: int
    digest: str
    subject: str
    fingerprint: str
    experiment_id: str
    replicate: int
    purpose: str


@dataclass(frozen=True)
class GrammarCandidate:
    """A candidate mechanism built from grammar terms and fitted to the admitted data."""

    candidate_id: str
    terms: tuple[str, ...]
    #: The fitted amplitude per term (free sign), and its standard error.
    theta: tuple[float, ...]
    se: tuple[float, ...]
    #: The candidate's forward model: (experiment, entry, sensitivity) per term, zero omitted.
    tables: tuple[tuple[tuple[str, str, float], ...], ...]
    #: Declared amplitude domain per term (sign-definite band around the fitted value).
    domain: tuple[tuple[float, float], ...]
    fingerprint: str
    chi2: float
    p_value: float
    adequate: bool


@dataclass(frozen=True)
class DiscoveryTest:
    experiment_id: str
    replicate: int
    registrations: tuple[Registration, ...]
    observation_id: str
    #: Candidate ids whose registered prediction passed / failed (the gate's own scoring).
    passed: tuple[str, ...]
    failed: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryAttempt:
    """What the grammar stage did after the catalog was shown incomplete."""

    grammar_id: str
    grammar_digest: str
    candidates_considered: int
    adequate_before_test: tuple[str, ...]
    tests: tuple[DiscoveryTest, ...]
    survivors: tuple[str, ...]
    #: The answered new mechanism (the gate's own decision), or None.
    answered: GrammarCandidate | None
    #: The best remaining candidate when nothing was answered: a PROPOSAL, never credited.
    proposal: GrammarCandidate | None
    reason: str


@dataclass(frozen=True)
class SafeRunV12:
    result: DiscoveryResult
    engine: DiscoveryResult
    assessment: SafetyAssessment
    refit: RefitCoverage | None
    member_tests: tuple[AdequacyTestV11, ...]
    allocation: Allocation
    registrations: tuple[Registration, ...]
    #: The gate's own reading of the ledger rule for each claimed member (fingerprint -> bool).
    support: tuple[tuple[str, bool], ...]
    discovery: DiscoveryAttempt | None
    notes: tuple[str, ...] = field(default=())

    @property
    def answer_kind(self) -> str:
        if self.discovery is not None and self.discovery.answered is not None:
            return "NEW_MECHANISM"
        if self.result.claim:
            return "CATALOG_CLAIM"
        return "NONE"


# -- the pre-registered evaluation plan ------------------------------------------------------


def derived_base_seed(label: str) -> int:
    """A base seed nobody chose: 3_000_000_000 + 1000 * (SHA-256(label) mod 1_000_000)."""
    digest = int(hashlib.sha256(label.encode("utf-8")).hexdigest(), 16)
    return 3_000_000_000 + 1000 * (digest % 1_000_000)


@dataclass(frozen=True)
class SeedRange:
    label: str
    base_seed: int
    per_group: int
    role: str


DEVELOPMENT = "DEVELOPMENT"
HELD_OUT_V12 = "HELD_OUT_FOR_V1_2"

HELD_OUT_LABEL = "lab-brain/discovery-safety-v1.2/held-out-worlds/2026-11-08"
BENCHMARK_LABEL = "lab-brain/discovery-safety-v1.2/benchmark-worlds/2026-11-08"


@dataclass(frozen=True)
class EvaluationPlanV12:
    """Everything the v1.2 evaluation runs and how it is scored, declared before it runs."""

    plan_id: str = "lab-brain/discovery-safety-v1.2-evaluation"
    arms: tuple[tuple[str, str], ...] = (
        ("B2", "frozen Discovery engine (2026-11-01), no safety layer"),
        ("B3", "frozen engine + out-of-catalog safety gate v1.0"),
        ("B4", "frozen engine + out-of-catalog safety gate v1.1"),
        (
            "B5",
            "frozen engine on an anytime cap ladder + safety gate v1.2 (registered "
            "predictions, grammar discovery)",
        ),
    )
    budgets: tuple[int, ...] = (8, 12, 24, 48)
    checkpoints: tuple[float, ...] = (0.25, 0.5, 1.0)
    #: Scoring: SAI 3.5 candidate.4 `classify_outcome` (category, evidential level), re-derived
    #: by the evaluator from the ledger; every answer below SUPPORTED is PROPOSAL_ONLY.
    scoring: str = "sai35-candidate.4-classify_outcome+verified_evidence (ledger re-derived)"
    distinguish_tau: float = 5.0
    distinguish_replicates: int = 4
    development: tuple[SeedRange, ...] = (
        SeedRange("v1.0 development held-out worlds", 5_000_000, 6, DEVELOPMENT),
        SeedRange("engine development worlds", 1, 6, DEVELOPMENT),
        SeedRange("v1.1 development held-out worlds", 7_000_000, 15, DEVELOPMENT),
        SeedRange("v1.2 development held-out worlds", 8_000_000, 15, DEVELOPMENT),
    )
    held_out: tuple[SeedRange, ...] = (
        SeedRange(HELD_OUT_LABEL, derived_base_seed(HELD_OUT_LABEL), 15, HELD_OUT_V12),
    )
    benchmark_worlds: SeedRange = SeedRange(
        BENCHMARK_LABEL, derived_base_seed(BENCHMARK_LABEL), 25, HELD_OUT_V12
    )
    #: Base seeds of every range run before v1.2 (evaluation and development).
    seeds_used_before: tuple[int, ...] = (
        1,
        5_000_000,
        7_000_000,
        2_026_110_100,
        2_026_110_200,
        2_026_610_200,
        2_026_810_400,
        3_931_910_000,
        3_320_367_000,
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


PLAN = EvaluationPlanV12()


def plan_record(plan: EvaluationPlanV12 = PLAN) -> dict[str, Any]:
    from lab_brain.discovery.model import to_jsonable

    return {"plan": to_jsonable(plan), "digest": plan.digest}


__all__ = [
    "BENCHMARK_LABEL",
    "DECLARED_ORDER",
    "DEVELOPMENT",
    "HELD_OUT_LABEL",
    "HELD_OUT_V12",
    "PLAN",
    "SAFETY_V12",
    "SEPARATION_ORDER",
    "Allocation",
    "DiscoveryAttempt",
    "DiscoveryTest",
    "EvaluationPlanV12",
    "GrammarCandidate",
    "LadderStep",
    "Registration",
    "SafeRunV12",
    "SafetyProtocolV12",
    "SeedRange",
    "derived_base_seed",
    "plan_record",
]
