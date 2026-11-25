"""Evaluator-side diagnosis: why an answer that could have been SUPPORTED was not, and how much
rival discrimination each run bought.

Everything here is computed by the EVALUATOR from its own ledger and the world's truth (which the
arm never sees); it decides no level and credits nothing. Two products:

    abstention cause   for a run whose answer is not SUPPORTED on a world whose truth a held
                       hypothesis expresses ("supportable" world), the truth's identity T is
                       examined on the run's recorded data. Each open rival R of T is placed by
                       s = the largest separation of R's prediction (at its fit to the data) from
                       the world's TRUE noise-free mean over the available experiments at up to
                       `max_runs` runs: INDISTINGUISHABLE if s < `tau_indistinguishable` (one test
                       fails R with probability below ~0.3), WEAK if s < `tau_refutable` (closure
                       by one test is a coin toss), REFUTABLE otherwise. Run-level cause, first
                       that applies:

        TRUTH_TEST_FAILED   Holm over T's complete registrations rejects one (noise against the
                            truth): CORRECT to withhold
        TRUTH_NOT_AT_RISK   no complete registration of T passed a risky test (the arm never put
                            the truth at risk: claim selection / engine / gate flow): AVOIDABLE
        INDISTINGUISHABLE   some open rival is INDISTINGUISHABLE: the rule cannot close it under
                            the world's noise: CORRECT abstention
        WEAK_RIVAL          some open rival is only WEAK: NOISE-LIMITED (closable by chance)
        NEVER_TARGETED      every open rival is refutable, the greedy cover of refuting tests is
                            affordable with the budget left, and some rival was never put at risk
                            (no passed registration of T on which R's prediction is >= tau_risky
                            from T's, and no registration of R): AVOIDABLE (planner)
        TARGETED_SURVIVED   ... affordable, every rival was put at risk and survived: AVOIDABLE
        SPENT_ELSEWHERE     the cover costs more than the budget left and some refutable open
                            rival was never put at risk: the budget went to tests that did not
                            target it: AVOIDABLE (allocation)
        BUDGET_EXHAUSTED    the cover costs more than the budget left and every open rival was put
                            at risk: BUDGET-LIMITED

    refutations        rivals CLOSED BY A FAILED PREDICTION in the run (v1.4 closure (a) or (b))
                       for every identity the arm registered with a passed test, deduplicated, by
                       kind ("no effect", catalog, grammar); a refutation of an identity matching
                       the truth is counted separately as an incorrect refutation. Separation
                       without a failed prediction is never counted.

The "true mean" separation is an oracle quantity (the world's noise-free response); it is used here
only to classify, never to score.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.model import NULL_HYPOTHESIS, ExperimentSpec, Hypothesis
from lab_brain.discovery_safety.v12.ledger import holm_rejections
from lab_brain.discovery_safety.v13.ledger import (
    MEASURE,
    REGISTER,
    LedgerEvent,
    observations_before,
)
from lab_brain.discovery_safety.v13.rule import CATALOG, RescoredTest, separation
from lab_brain.discovery_safety.v14.rule import RescorerV14, Rival, closed_by, open_rivals_v14

TRUTH_TEST_FAILED = "TRUTH_TEST_FAILED"
TRUTH_NOT_AT_RISK = "TRUTH_NOT_AT_RISK"
INDISTINGUISHABLE = "INDISTINGUISHABLE"
WEAK_RIVAL = "WEAK_RIVAL"
NEVER_TARGETED = "NEVER_TARGETED"
TARGETED_SURVIVED = "TARGETED_SURVIVED"
SPENT_ELSEWHERE = "SPENT_ELSEWHERE"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
CAUSES = (
    TRUTH_TEST_FAILED,
    TRUTH_NOT_AT_RISK,
    INDISTINGUISHABLE,
    WEAK_RIVAL,
    NEVER_TARGETED,
    TARGETED_SURVIVED,
    SPENT_ELSEWHERE,
    BUDGET_EXHAUSTED,
)
#: The buckets: the data could not have avoided it (CORRECT), noise decides (NOISE_LIMITED), the
#: cap decides (BUDGET_LIMITED), or another use of the same budget could have (AVOIDABLE).
BUCKETS = {
    TRUTH_TEST_FAILED: "correct",
    INDISTINGUISHABLE: "correct",
    WEAK_RIVAL: "noise_limited",
    BUDGET_EXHAUSTED: "budget_limited",
    TRUTH_NOT_AT_RISK: "avoidable",
    NEVER_TARGETED: "avoidable",
    TARGETED_SURVIVED: "avoidable",
    SPENT_ELSEWHERE: "avoidable",
}
CORRECT_CAUSES = tuple(c for c, b in BUCKETS.items() if b == "correct")
AVOIDABLE_CAUSES = tuple(c for c, b in BUCKETS.items() if b == "avoidable")

TrueMean = Callable[[ExperimentSpec], Mapping[str, float]]


@dataclass(frozen=True)
class RivalDiagnosis:
    identity: str
    label: str
    kind: str
    #: Largest separation of the rival's prediction from the TRUE mean over the available
    #: experiments at max_runs runs.
    true_separation: float
    #: The cheapest (cost, experiment, runs) reaching tau_refutable from the true mean, if any.
    refute_cost: int | None
    refute_experiment: str
    targeted: bool


@dataclass
class Diagnosis:
    cause: str
    truth_identity: str
    open_rivals: int
    rivals: list[RivalDiagnosis] = field(default_factory=list)
    unspent: int = 0
    cover_cost: int | None = None

    def as_json(self, top: int = 5) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for r in self.rivals:
            kinds[r.kind] = kinds.get(r.kind, 0) + 1
        return {
            "cause": self.cause,
            "open_rivals": self.open_rivals,
            "open_rival_kinds": dict(sorted(kinds.items())),
            "unspent": self.unspent,
            "cover_cost": self.cover_cost,
            "weak_or_indistinguishable_rivals": sum(
                1 for r in self.rivals if r.refute_cost is None
            ),
            "never_targeted_rivals": sum(
                1 for r in self.rivals if r.refute_cost is not None and not r.targeted
            ),
            "examples": [
                {
                    "label": r.label,
                    "kind": r.kind,
                    "true_separation": round(r.true_separation, 3),
                    "refute_cost": r.refute_cost,
                    "refute_experiment": r.refute_experiment,
                    "targeted": r.targeted,
                }
                for r in self.rivals[:top]
            ],
        }


def truth_identity(
    rescorer: RescorerV14, truth: Hypothesis | None, matches: Callable[[Hypothesis], bool]
) -> str:
    """The identity the evaluator holds for the truth ('' when no held hypothesis expresses it)."""
    if truth is not None and truth.is_null:
        return NULL_HYPOTHESIS.fingerprint
    if truth is not None and truth.fingerprint in rescorer.catalog:
        return truth.fingerprint
    candidates = sorted(
        (len(h.components), h.hypothesis_id, h.fingerprint)
        for h in rescorer.catalog.values()
        if matches(h)
    )
    return candidates[0][2] if candidates else ""


def _true_separation(
    rescorer: RescorerV14,
    identity: str,
    rival: Rival,
    data: Sequence[Any],
    true_mean: TrueMean,
    tau: float,
) -> tuple[float, int | None, str]:
    best, cost, where = 0.0, None, ""
    top = rescorer.rule.max_runs
    for x in rescorer.available:
        e = rescorer.experiments[x]
        theirs = rescorer.predict_rival(identity, rival.identity, data, e)
        if theirs is None:
            continue
        truth = (dict(true_mean(e)), {k.entry_id: 0.0 for k in e.entries})
        for n in range(1, top + 1):
            s = separation(truth, theirs, e, n)
            best = max(best, s)
            if s >= tau and (cost is None or n * e.cost < cost):
                cost, where = n * e.cost, f"{x}x{n}"
                break
    return best, cost, where


def _targeted(
    rescorer: RescorerV14,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
    rival: str,
) -> bool:
    for t in tests:
        if not t.complete:
            continue
        if t.identity == rival:
            return True
        if t.identity != identity or not t.passed:
            continue
        e = rescorer.experiments[t.experiment_id]
        data = observations_before(events, t.register_index)
        mine = rescorer.predict(identity, data, e)
        theirs = rescorer.predict_rival(identity, rival, data, e)
        if (
            mine is not None
            and theirs is not None
            and separation(mine, theirs, e, t.runs) >= rescorer.rule.tau_risky
        ):
            return True
    return False


def _cover_cost(
    rivals: Sequence[RivalDiagnosis], options: Mapping[str, tuple[int, set[str]]]
) -> int:
    """A greedy set cover of the rivals by refuting tests (cost per newly covered rival)."""
    left = {r.identity for r in rivals}
    total = 0
    while left:
        best: tuple[float, str] | None = None
        for key, (cost, covers) in sorted(options.items()):
            gain = len(covers & left)
            if gain and (best is None or cost / gain < best[0]):
                best = (cost / gain, key)
        if best is None:
            break
        cost, covers = options[best[1]]
        total += cost
        left -= covers
    return total


def diagnose(
    rescorer: RescorerV14,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    identity: str,
    true_mean: TrueMean,
    cap: int,
    spent: int,
    tau_refutable: float = 4.5,
    tau_indistinguishable: float = 2.0,
) -> Diagnosis:
    """Why the truth's identity is not SUPPORTED on this record (see the module docstring)."""
    unspent = cap - spent
    mine = [t for t in tests if t.identity == identity and t.complete]
    if any(holm_rejections([t.p_value for t in mine], rescorer.rule.alpha)):
        return Diagnosis(TRUTH_TEST_FAILED, identity, 0, unspent=unspent)
    if not any(t.passed and t.risky for t in mine):
        return Diagnosis(TRUTH_NOT_AT_RISK, identity, 0, unspent=unspent)
    data = observations_before(events, len(events))
    rivals = open_rivals_v14(rescorer, events, tests, identity)
    out: list[RivalDiagnosis] = []
    options: dict[str, tuple[int, set[str]]] = {}
    top = rescorer.rule.max_runs
    for r in rivals:
        s, cost, where = _true_separation(rescorer, identity, r, data, true_mean, tau_refutable)
        out.append(
            RivalDiagnosis(
                r.identity,
                r.label,
                r.kind,
                s,
                cost,
                where,
                _targeted(rescorer, events, tests, identity, r.identity),
            )
        )
        if cost is not None:
            for x in rescorer.available:
                e = rescorer.experiments[x]
                theirs = rescorer.predict_rival(identity, r.identity, data, e)
                if theirs is None:
                    continue
                truth = (dict(true_mean(e)), {k.entry_id: 0.0 for k in e.entries})
                for n in range(1, top + 1):
                    if separation(truth, theirs, e, n) >= tau_refutable:
                        options.setdefault(f"{x}x{n}", (n * e.cost, set()))[1].add(r.identity)
    out.sort(key=lambda d: (d.refute_cost is not None, d.true_separation, d.label))
    if not out:  # pragma: no cover - a supported identity is not diagnosed
        return Diagnosis(TRUTH_NOT_AT_RISK, identity, 0, unspent=unspent)
    if any(d.true_separation < tau_indistinguishable for d in out):
        return Diagnosis(INDISTINGUISHABLE, identity, len(out), out, unspent)
    if any(d.refute_cost is None for d in out):
        return Diagnosis(WEAK_RIVAL, identity, len(out), out, unspent)
    cover = _cover_cost(out, options)
    untargeted = any(not d.targeted for d in out)
    if cover <= unspent:
        cause = NEVER_TARGETED if untargeted else TARGETED_SURVIVED
    else:
        cause = SPENT_ELSEWHERE if untargeted else BUDGET_EXHAUSTED
    return Diagnosis(cause, identity, len(out), out, unspent, cover)


# -- refutations (the efficiency metric) --------------------------------------------------------


@dataclass(frozen=True)
class Refutations:
    #: Distinct identities closed by a failed prediction (v1.4 closure) in this run.
    refuted: int
    #: ... of which the identity expresses the truth (a failed prediction of the truth).
    incorrect: int
    runs: int
    registrations: int
    #: Correct refutations by the refuted identity's kind ("null", "catalog", "grammar").
    by_kind: Mapping[str, int] = field(default_factory=dict)


def refutations(
    rescorer: RescorerV14,
    events: Sequence[LedgerEvent],
    tests: Sequence[RescoredTest],
    is_truth: Callable[[str], bool],
) -> Refutations:
    """Rivals closed by a FAILED prediction (never by separation alone): for every identity with a
    passed complete registration, its v1.4 rivals on all the data that `closed_by` closes; plus
    every identity whose own complete registration failed."""
    refuted: set[str] = set()
    for t in tests:
        if t.complete and not t.passed:
            refuted.add(t.identity)
    claims = sorted({t.identity for t in tests if t.complete and t.passed})
    data = observations_before(events, len(events))
    for identity in claims:
        if rescorer.kind(identity) is None:
            continue
        for r in rescorer.rivals_v14(identity, data):
            if r.identity in refuted:
                continue
            if closed_by(rescorer, events, tests, identity, r.identity) is not None:
                refuted.add(r.identity)
    incorrect = sum(1 for i in refuted if is_truth(i))
    by_kind: dict[str, int] = {}
    for i in refuted:
        if not is_truth(i):
            k = rescorer.kind(i) or "unknown"
            by_kind[k] = by_kind.get(k, 0) + 1
    return Refutations(
        by_kind=dict(sorted(by_kind.items())),
        refuted=len(refuted),
        incorrect=incorrect,
        runs=sum(1 for e in events if e.kind == MEASURE),
        registrations=sum(1 for e in events if e.kind == REGISTER),
    )


def truth_predicate(
    rescorer: RescorerV14, matches: Callable[[Hypothesis], bool], truth_id: str
) -> Callable[[str], bool]:
    """Whether an identity expresses the truth (catalog: the judge's match; the truth's own
    identity; grammar shapes and others: never, a conservative choice that can only under-count
    incorrect refutations of grammar shapes)."""

    def is_truth(identity: str) -> bool:
        if identity and identity == truth_id:
            return True
        if rescorer.kind(identity) == CATALOG:
            return matches(rescorer.catalog[identity])
        return False

    return is_truth


__all__ = [
    "AVOIDABLE_CAUSES",
    "BUCKETS",
    "BUDGET_EXHAUSTED",
    "CAUSES",
    "CORRECT_CAUSES",
    "INDISTINGUISHABLE",
    "NEVER_TARGETED",
    "SPENT_ELSEWHERE",
    "TARGETED_SURVIVED",
    "TRUTH_NOT_AT_RISK",
    "TRUTH_TEST_FAILED",
    "WEAK_RIVAL",
    "Diagnosis",
    "Refutations",
    "RivalDiagnosis",
    "diagnose",
    "refutations",
    "truth_identity",
    "truth_predicate",
]
