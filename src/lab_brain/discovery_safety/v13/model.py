"""The v1.3 protocol, the evaluator's rule, and the pre-registered evaluation plan.

WHAT v1.3 CHANGES, AND WHY (Independent Chief Auditor findings on v1.2; reproduced on the unchanged
v1.2 code in `docs/audit/discovery-safety-v1.3-2026-11-11/evidence/reproduction_before.log`):

    evaluator-computed evidence  in v1.2 the arm wrote into each registration the predicted values,
                    their standard deviation, the alternatives a "risky" prediction is measured
                    against, the rule's thresholds and the fingerprint the prediction is filed
                    under, and the evaluator re-scored with those. In v1.3 the arm registers ONLY an
                    identity (a catalog hypothesis's forward-model fingerprint, a grammar shape's
                    fingerprint, or "no effect"), an experiment, the number of runs of the test, and
                    (optionally) a digest of the data it used. Everything that decides pass and
                    riskiness is computed by the evaluator (`EvaluatorRule`, `rule.py`) from the
                    measurements the evaluator itself recorded before the registration: it refits
                    the identity, predicts with the instrument sigma it owns and its own parameter
                    uncertainty, and chooses the alternatives itself
    boundary        the ledger is append-only and hash-chained, owned by the evaluator; the arm gets
                    a laboratory whose only write besides measuring is `register_identity`. In the
                    evaluation every arm runs in a separate OS process that never receives the
                    world, the truth, the meter or the ledger (`boundary.py`)
    multi-run tests a registered test may name n runs of one experiment (1 <= n <= `max_runs`); it
                    is scored on their mean. v1.2's rival and support tests were single runs that
                    had to separate by `tau_risky` on their own, so a rival whose effect is below
                    that in every single run could never be tested however much budget was left --
                    the root cause of v1.2's lost noise-only worlds (development log §C)
    null claims     "no effect" is risky only against effects the evaluator declares worth finding:
                    each catalog hypothesis still adequate on the earlier data, AT ITS SMALLEST
                    DECLARED EFFECT (its amplitude domain's bound nearest zero), with no parameter
                    uncertainty -- an equivalence-style test with the catalog's declared domains as
                    the smallest effects of interest. v1.2 measured "no effect" against fitted
                    alternatives, which on null data are themselves near zero, so a null claim
                    could never be risky
    rival exclusion a rival counts as excluded when its own evaluator-scored registration for a
                    test that separates it from the claim FAILED; adequacy alone (diluted over all
                    the data) is not required to reject it

Everything else is v1.2's (allocation ladder, gate-led claim, grammar discovery, thresholds).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.model import stable_digest
from lab_brain.discovery_safety.v12.model import (
    DEVELOPMENT,
    SafetyProtocolV12,
    SeedRange,
    derived_base_seed,
)
from lab_brain.discovery_safety.v12.model import (
    PLAN as PLAN_V12,
)


@dataclass(frozen=True)
class EvaluatorRule:
    """The evaluator's pre-declared rule for one registered test (never supplied by an arm).

    prediction   the identity refitted by the evaluator to the measurements recorded BEFORE the
                 registration: a catalog hypothesis within its declared domain (parameter
                 covariance from the fit; an unconstrained component contributes its half-range as
                 a standard deviation), a grammar shape by least squares (a shape the earlier data
                 do not constrain predicts nothing: the registration is void), "no effect" exactly
                 zero. Noise: each entry's declared instrument sigma, divided by sqrt(n) for the
                 mean of n runs
    pass         chi-square of z = (mean observed - predicted) / sqrt(sigma^2/n + sd^2) over the
                 experiment's entries has upper-tail p >= `alpha`, and every |z| <= `z_max`
    alternatives non-null identity: every catalog hypothesis, every grammar shape and "no effect"
                 that is ADEQUATE on the earlier data (global test at `alpha_adequacy`,
                 `z_adequacy`), with a forward model other than the identity's, at its own fit to
                 those data. "No effect": every catalog hypothesis adequate on the earlier data,
                 at its smallest declared effect, sd 0
    risky        the predicted mean is >= `tau_risky` combined standard units from at least one
                 alternative: sqrt(sum (m - a)^2 / (sigma^2/n + sd^2 + sd_a^2))
    support      some complete registration of the identity passed and is risky, and Holm's
                 step-down at family-wise `alpha` over ALL its complete registrations rejects none
    """

    rule_id: str = "lab-brain/discovery-evaluator-rule"
    version: str = "1.3.0"
    alpha: float = 1e-2
    z_max: float = 4.0
    tau_risky: float = 3.0
    alpha_adequacy: float = 1e-2
    z_adequacy: float = 4.0
    max_runs: int = 4
    #: The declared amplitude band of a grammar candidate answered as a new mechanism (the
    #: evaluator refits the shape to all the data and applies this band; v1.2's value).
    candidate_band: float = 0.5

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 1 or not 0 < self.alpha_adequacy < 1:
            raise ValueError("levels are probabilities")
        if self.max_runs < 1:
            raise ValueError("a test has at least one run")

    @property
    def digest(self) -> str:
        return stable_digest(self)


EVALUATOR_RULE = EvaluatorRule()


@dataclass(frozen=True)
class SafetyProtocolV13(SafetyProtocolV12):
    """v1.2's switches, plus:

    evaluator_rule_support  the gate decides support with the evaluator's public rule applied to
                            its own copy of the record (the evaluator re-derives it; nothing the
                            gate computes is trusted)
    multi_run_tests         support, rival and null tests may use up to `max_runs` runs
    rival_refuted_by_failed_registration  a rival whose own registration failed is excluded
    max_runs                runs per registered test, at most
    null_fallback           when the claim is not endorsed and "no effect" is still viable, assess
                            "no effect" with the budget left (parsimony fallback)
    """

    version: str = "1.3.0"
    evaluator_rule_support: bool = True
    multi_run_tests: bool = True
    rival_refuted_by_failed_registration: bool = True
    max_runs: int = 4
    null_fallback: bool = True


SAFETY_V13 = SafetyProtocolV13()


# -- the pre-registered evaluation plan ------------------------------------------------------

HELD_OUT_V13 = "HELD_OUT_FOR_V1_3"
HELD_OUT_LABEL = "lab-brain/discovery-safety-v1.3/held-out-worlds/2026-11-11"
BENCHMARK_LABEL = "lab-brain/discovery-safety-v1.3/benchmark-worlds/2026-11-11"


@dataclass(frozen=True)
class EvaluationPlanV13:
    """Everything the v1.3 evaluation runs and how it is scored, declared before it runs."""

    plan_id: str = "lab-brain/discovery-safety-v1.3-evaluation"
    arms: tuple[tuple[str, str], ...] = (
        ("B2", "frozen Discovery engine (2026-11-01), no safety layer"),
        ("B4", "frozen engine + safety gate v1.1 (the current offline safety BASELINE)"),
        ("B5", "safety gate v1.2, unchanged (its registrations re-scored by the v1.3 evaluator)"),
        ("B6", "safety gate v1.3 (identity registrations, multi-run tests, null equivalence)"),
    )
    #: Caps (each arm runs once per cap); the realized cost of each run is the metered charge.
    budgets: tuple[int, ...] = (6, 8, 12, 24, 48)
    #: Scoring: SAI 3.5 candidate.5 (spec commit 61af6ef) `classify_outcome` with
    #: `verified_evidence` (arm_supplied_inputs) and `AnswerStance`; levels re-derived by
    #: `EvaluatorRule` from the evaluator's own ledger.
    scoring: str = (
        "sai35-candidate.5 classify_outcome+verified_evidence+assertion_status (61af6ef); "
        "evaluator-computed EvaluatorRule"
    )
    distinguish_tau: float = 5.0
    distinguish_replicates: int = 4
    #: Matched realized cost: a pair of (arm, cap) cells is COST_MATCHED iff the paired-bootstrap
    #: 95 % interval of the mean realized-cost difference lies within +-`cost_tolerance` units.
    cost_tolerance: float = 1.0
    bootstrap_resamples: int = 2000
    #: (Y, X): differences are reported as Y - X, paired on identical worlds.
    comparisons: tuple[tuple[str, str], ...] = (
        ("B6", "B4"),
        ("B6", "B5"),
        ("B5", "B4"),
        ("B2", "B4"),
        ("B6", "B2"),
    )
    development: tuple[SeedRange, ...] = PLAN_V12.development
    held_out: tuple[SeedRange, ...] = (
        SeedRange(HELD_OUT_LABEL, derived_base_seed(HELD_OUT_LABEL), 10, HELD_OUT_V13),
    )
    benchmark_worlds: SeedRange = SeedRange(  # noqa: RUF009 -- a frozen dataclass
        BENCHMARK_LABEL, derived_base_seed(BENCHMARK_LABEL), 15, HELD_OUT_V13
    )
    #: Base seeds of every range run before v1.3: v1.2's list, v1.2's own held-out ranges, and
    #: every development range.
    seeds_used_before: tuple[int, ...] = (
        *PLAN_V12.seeds_used_before,
        *(r.base_seed for r in PLAN_V12.held_out),
        PLAN_V12.benchmark_worlds.base_seed,
    )

    def __post_init__(self) -> None:
        fresh = [*self.held_out, self.benchmark_worlds]
        used = [*self.seeds_used_before, *(r.base_seed for r in self.development)]
        for r in fresh:
            for base in used:
                if abs(r.base_seed - base) < 20_000:
                    raise ValueError(f"{r.label} overlaps a seed range used before ({base})")
        if list(self.budgets) != sorted(set(self.budgets)):
            raise ValueError("caps increase")

    @property
    def digest(self) -> str:
        return stable_digest(self)


PLAN = EvaluationPlanV13()


def plan_record(plan: EvaluationPlanV13 = PLAN) -> dict[str, Any]:
    from lab_brain.discovery.model import to_jsonable

    return {"plan": to_jsonable(plan), "digest": plan.digest}


@dataclass(frozen=True)
class ArmAnswer:
    """What an arm hands the evaluator when it stops (the only thing that crosses the boundary
    besides measurement requests and registrations). Plain data; nothing in it is trusted except
    as the arm's own statement of what it answers."""

    arm: str
    outcome: str
    #: NONE, CATALOG_CLAIM or NEW_MECHANISM.
    answer_kind: str
    #: The claimed catalog hypothesis ids (CATALOG_CLAIM; "hyp:null" for "no effect").
    claim: tuple[str, ...] = ()
    #: The grammar shape fingerprint of an answered new mechanism.
    new_mechanism: str = ""
    #: A grammar candidate left as a proposal beside an abstention (never the answer).
    grammar_proposal: str = ""
    #: The arm's own stance on its answer (SAI candidate.5 `AnswerStance`).
    labelled_proposal: bool = False
    acted_on: bool = False
    spent: int = 0
    reason: str = ""
    digest: str = ""
    notes: tuple[str, ...] = field(default=())

    def as_json(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "outcome": self.outcome,
            "answer_kind": self.answer_kind,
            "claim": list(self.claim),
            "new_mechanism": self.new_mechanism,
            "grammar_proposal": self.grammar_proposal,
            "labelled_proposal": self.labelled_proposal,
            "acted_on": self.acted_on,
            "spent": self.spent,
            "reason": self.reason,
            "digest": self.digest,
            "notes": list(self.notes),
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> ArmAnswer:
        return ArmAnswer(
            arm=str(d["arm"]),
            outcome=str(d["outcome"]),
            answer_kind=str(d["answer_kind"]),
            claim=tuple(str(c) for c in d.get("claim", ())),
            new_mechanism=str(d.get("new_mechanism", "")),
            grammar_proposal=str(d.get("grammar_proposal", "")),
            labelled_proposal=bool(d.get("labelled_proposal", False)),
            acted_on=bool(d.get("acted_on", False)),
            spent=int(d.get("spent", 0)),
            reason=str(d.get("reason", "")),
            digest=str(d.get("digest", "")),
            notes=tuple(str(n) for n in d.get("notes", ())),
        )


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "BENCHMARK_LABEL",
    "DEVELOPMENT",
    "EVALUATOR_RULE",
    "HELD_OUT_LABEL",
    "HELD_OUT_V13",
    "PLAN",
    "SAFETY_V13",
    "ArmAnswer",
    "EvaluationPlanV13",
    "EvaluatorRule",
    "SafetyProtocolV13",
    "plan_record",
    "text_digest",
]
