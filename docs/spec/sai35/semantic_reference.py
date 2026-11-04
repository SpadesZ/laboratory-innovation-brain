"""SAI 3.5 candidate: executable reference semantics and counterexamples (documentation tooling).

Version: 3.5.0-master-candidate.2. CANDIDATE — NOT ACTIVE. This file is not runtime code, is not
imported by the product and is not evidence that any capability exists. It states, in executable
form, the mathematical definitions that the normative text of docs/spec/SAI_3.5.md and its
appendices refers to, so that a reviewer can check the definitions against counterexamples instead
of against prose alone:

- Appendix S (mechanism-distinguishability.md): mechanism identity, pairwise distinguishability
  under an experiment set with parameter uncertainty, the three pair verdicts, the certified
  diversity bounds, true-cause scoring and novelty against prior art (S35-MECH-001, S35-CMP-005,
  S35-NOV-002).
- Appendix J (matched-budget-protocol.md) §3: scoring at frozen realized-cost checkpoints, the
  atomic-action rule, COST_UNMATCHED, and the superseded outcome-dependent rule kept only as a
  secondary sensitivity analysis (S35-CMP-002, S35-CMP-008).
- Appendix E §9 and Appendix A §3.1: the authorization ladder and the three termination
  dimensions (S35-HYP-001, S35-GOV-003, S35-LIFE-002, S35-LOOP-003, S35-REG-003).

Run: python docs/spec/sai35/semantic_reference.py --self-test

`check()` asserts every counterexample of the appendices. `self_test()` replaces each definition
with a known-wrong variant (a transitive merge, a raw count, the post-hoc matching rule, ...) and
requires `check()` to reject every one. The checker docs/spec/sai35/check_candidate.py runs both.
Standard library only.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

VERSION = "3.5.0-master-candidate.2"

DISTINGUISHABLE = "DISTINGUISHABLE"
INDISTINGUISHABLE = "INDISTINGUISHABLE"
UNRESOLVED = "UNRESOLVED"
COST_UNMATCHED = "COST_UNMATCHED"

# ---------------------------------------------------------------------------------------------
# Appendix S — mechanism identity and distinguishability
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Mechanism:
    """A held hypothesis's mechanism, as the reference needs it.

    `name` is a label and never enters identity or distinguishability. `forward_model` is the
    canonical, versioned forward-model declaration (Appendix S §2): identity is its hash.
    `points` is the parameter range Θ represented by a finite set of parameter points, each the
    vector of predicted means over the experiments of E (keyed by experiment id). `grid_error` is a
    certified bound, in standardized units, on how far the true range can come closer to another
    mechanism than the finite set shows (0 when the set is the whole range).
    """

    name: str
    forward_model: str
    points: tuple[Mapping[str, float], ...]
    grid_error: float = 0.0

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.forward_model.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExperimentSet:
    """E: experiment id -> (noise standard deviation of one replicate, declared replicates)."""

    version: str
    experiments: Mapping[str, tuple[float, int]]

    def standard_error(self, experiment: str) -> float:
        sigma, replicates = self.experiments[experiment]
        return sigma / replicates**0.5


def separation_bounds(a: Mechanism, b: Mechanism, e: ExperimentSet) -> tuple[float, float]:
    """[D_lo, D_hi] for D_E(a, b) = min over (θ, φ) of max over e in E of |μ_a − μ_b| / se_e.

    The minimum over parameters is the worst case (the parameters are free to make the two agree);
    the maximum over experiments is taken jointly for one parameter pair, because one parameter
    value must explain every experiment. The finite point sets give an upper bound; subtracting the
    certified grid errors gives a lower bound.
    """
    if not e.experiments:
        return 0.0, 0.0
    best = min(
        max(abs(p[x] - q[x]) / e.standard_error(x) for x in e.experiments)
        for p in a.points
        for q in b.points
    )
    return max(0.0, best - a.grid_error - b.grid_error), best


def pair_verdict(a: Mechanism, b: Mechanism, e: ExperimentSet, threshold: float) -> str:
    """DISTINGUISHABLE iff D_lo ≥ τ; INDISTINGUISHABLE iff D_hi < τ; otherwise UNRESOLVED."""
    if a.identity == b.identity:
        return INDISTINGUISHABLE  # an alias: identical forward model, whatever its name
    low, high = separation_bounds(a, b, e)
    if low >= threshold:
        return DISTINGUISHABLE
    if high < threshold:
        return INDISTINGUISHABLE
    return UNRESOLVED


def verdict_graph(
    held: Sequence[Mechanism], e: ExperimentSet, threshold: float
) -> dict[tuple[int, int], str]:
    return {
        (i, j): pair_verdict(held[i], held[j], e, threshold)
        for i, j in itertools.combinations(range(len(held)), 2)
    }


def _largest_clique(n: int, edge: Callable[[int, int], bool]) -> int:
    """Exact maximum clique by exhaustive search (the reference is for small n only)."""
    best = 0 if n == 0 else 1
    for size in range(2, n + 1):
        if any(all(edge(i, j) for i, j in itertools.combinations(c, 2))
               for c in itertools.combinations(range(n), size)):  # fmt: skip
            best = size
        else:
            break
    return best


def diversity_bounds(
    held: Sequence[Mechanism], e: ExperimentSet, threshold: float
) -> tuple[int, int]:
    """Certified diversity [lower, upper] (Appendix S §4).

    lower: the largest number of held mechanisms that are pairwise certified DISTINGUISHABLE under
    E (a maximum clique of the DISTINGUISHABLE graph). upper: the same with UNRESOLVED pairs counted
    as distinguishable. The headline figure is the lower bound; the upper bound is reported beside
    it while any pair is UNRESOLVED.
    """
    verdicts = verdict_graph(held, e, threshold)
    lower = _largest_clique(len(held), lambda i, j: verdicts[(i, j)] == DISTINGUISHABLE)
    upper = _largest_clique(len(held), lambda i, j: verdicts[(i, j)] != INDISTINGUISHABLE)
    return lower, upper


def neighbourhood(
    held: Sequence[Mechanism], index: int, e: ExperimentSet, threshold: float
) -> tuple[str, ...]:
    """What a claim for held[index] must report as not excluded (S35-SEL-002): every other held
    mechanism that is not certified DISTINGUISHABLE from it. Not an equivalence class."""
    return tuple(
        m.name
        for k, m in enumerate(held)
        if k != index and pair_verdict(held[index], m, e, threshold) != DISTINGUISHABLE
    )


def true_cause_score(
    claimed: Mechanism | None, truth: Mechanism | None, e: ExperimentSet, threshold: float
) -> tuple[bool, bool]:
    """(primary, upper) credit for true-cause discovery (S35-CMP-005 metric 1).

    primary: the claim is credited only when its mechanism is the true one or certified
    INDISTINGUISHABLE from it under the case's full E; in a no-mechanism case (truth None) only a
    stop (claimed None) is credited. upper: UNRESOLVED also credited; reported as a sensitivity
    bound, never as the primary figure.
    """
    if truth is None or claimed is None:
        return (claimed is None and truth is None,) * 2
    verdict = pair_verdict(claimed, truth, e, threshold)
    return verdict == INDISTINGUISHABLE, verdict != DISTINGUISHABLE


def novelty_against_prior_art(
    candidate: Mechanism, prior_art: Iterable[Mechanism], e: ExperimentSet, threshold: float
) -> str:
    """The mechanism part of the novelty classification (Appendix D §3, Appendix S §6)."""
    verdicts = [pair_verdict(candidate, k, e, threshold) for k in prior_art]
    if INDISTINGUISHABLE in verdicts:
        return "KNOWN_MECHANISM_REDISCOVERY"
    if UNRESOLVED in verdicts:
        return "NOVELTY_UNRESOLVED"  # at most a candidate with the unresolved pairs listed
    return "NEW_PHYSICAL_KNOWLEDGE_CANDIDATE"


def naive_name_count(held: Sequence[Mechanism], *_: object) -> tuple[int, int]:
    """WRONG (kept for the self-test): a raw count of hypotheses."""
    n = len({m.name for m in held})
    return n, n


def naive_transitive_classes(
    held: Sequence[Mechanism], e: ExperimentSet, threshold: float
) -> tuple[int, int]:
    """WRONG (kept for the self-test): connected components of 'not distinguishable', i.e. the
    transitive merge the master candidate.1 text and the 118a4ac prototype used."""
    parent = list(range(len(held)))

    def find(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for (i, j), verdict in verdict_graph(held, e, threshold).items():
        if verdict != DISTINGUISHABLE:
            parent[find(i)] = find(j)
    n = len({find(i) for i in range(len(held))})
    return n, n


# ---------------------------------------------------------------------------------------------
# Appendix J §3 — matched realized cost at frozen checkpoints
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """One atomic attempt: a model call, a tool call, an experiment, a retry or a failed try.
    `cost` is its full realized cost in frozen cost units, charged when the attempt starts."""

    kind: str
    cost: float


@dataclass(frozen=True)
class Answer:
    """An anytime answer committed by the arm (a mechanism name, or None for a stop)."""

    value: str | None
    stop: bool = False


@dataclass(frozen=True)
class ArmTrace:
    events: tuple[Attempt | Answer, ...]
    ledger_total: float  # the independent meter / provider ledger for the case and arm
    cap: float
    manifest_hash: str = "m"

    def charged_answers(self) -> list[tuple[float, Answer]]:
        charged, out = 0.0, []
        for event in self.events:
            if isinstance(event, Attempt):
                charged += event.cost
            else:
                out.append((charged, event))
                if event.stop:
                    break
        return out

    def realized_total(self) -> float:
        return sum(ev.cost for ev in self.events if isinstance(ev, Attempt))


@dataclass(frozen=True)
class FrozenProtocol:
    checkpoints: tuple[float, ...]  # strictly increasing, frozen at G-D0 before any arm runs
    primary: float  # one of the checkpoints
    tolerance: float  # allowed |ledger − attempts| in cost units
    protocol_hash: str = field(default="")

    def __post_init__(self) -> None:
        assert list(self.checkpoints) == sorted(set(self.checkpoints)), "checkpoints not frozen"
        assert self.primary in self.checkpoints, "primary checkpoint must be pre-registered"


def answer_at(trace: ArmTrace, checkpoint: float) -> str | None:
    """The answer held at a checkpoint: the last answer committed while the cumulative charge
    (the full cost of every attempt started before it) was ≤ checkpoint. An attempt that straddles
    the checkpoint therefore cannot supply evidence to the checkpoint's answer. With no answer
    committed in time, the arm holds no claim (scored as a stop without reason: not credited
    except in a no-mechanism case, where it is still not a *reasoned* stop; see Appendix J §3.4)."""
    held: str | None = None
    for charge, answer in trace.charged_answers():
        if charge > checkpoint:
            break
        held = answer.value
    return held


def cost_matched(
    traces: Mapping[str, ArmTrace], protocol: FrozenProtocol, checkpoint: float
) -> bool:
    """False → the case is COST_UNMATCHED at this checkpoint (Appendix J §3.3)."""
    if checkpoint not in protocol.checkpoints:
        raise ValueError("checkpoint not in the frozen protocol (post-hoc choice refused)")
    caps = {t.cap for t in traces.values()}
    manifests = {t.manifest_hash for t in traces.values()}
    if len(caps) != 1 or len(manifests) != 1 or checkpoint > next(iter(caps)):
        return False
    for t in traces.values():
        if abs(t.ledger_total - t.realized_total()) > protocol.tolerance:
            return False  # unrecorded attempts, failures, retries or model calls
        if not t.charged_answers():
            return False  # no anytime answer stamped with cumulative realized cost
    return True


def score_case(
    traces: Mapping[str, ArmTrace], protocol: FrozenProtocol, checkpoint: float | None = None
) -> dict[str, str | None] | str:
    """Primary scoring of one case: each arm's answer at the pre-registered checkpoint, or
    COST_UNMATCHED. Each arm's answer depends on its own trace only."""
    c = protocol.primary if checkpoint is None else checkpoint
    if not cost_matched(traces, protocol, c):
        return COST_UNMATCHED
    return {arm: answer_at(t, c) for arm, t in traces.items()}


def secondary_min_final_cost(traces: Mapping[str, ArmTrace]) -> dict[str, str | None]:
    """The superseded master candidate.1 rule (match at the smallest final realized cost among the
    arms). Outcome-dependent; kept ONLY as a labelled secondary sensitivity analysis."""
    level = min(t.realized_total() for t in traces.values())
    return {arm: answer_at(t, level) for arm, t in traces.items()}


# ---------------------------------------------------------------------------------------------
# Appendix E §9 and Appendix A §3.1 — authorization ladder and termination dimensions
# ---------------------------------------------------------------------------------------------

LADDER = (
    "SPEND_AUTHORIZED",  # an Owner gate or an envelope at AL2/AL3/AL4 covers the cost
    "ADMITTED",  # SAI 3.3 §8 Hypothesis Admission Gate
    "REGISTERED",  # S35-REG-001 prospective registration (+ per-hypothesis signature if required)
    "SUPPORTED",  # TransitionPolicy on admissible prospective evidence (S35-REG-004)
    "CONFIRMED",  # Causal Warrant Gate with a qualifying signed review (S35-CWG-001/002)
)


def reachable(facts: Mapping[str, bool]) -> str | None:
    """The highest rung whose own record exists AND every lower rung's record exists. No rung is
    implied by another: each needs its own record and authority."""
    top = None
    for rung in LADDER:
        if not facts.get(rung, False):
            break
        top = rung
    return top


def support_admissible(
    *, post_screening: bool, envelope_only: bool, per_hypothesis_signature: bool
) -> str:
    """S35-REG-003 with the OD-14 default: an envelope never replaces a per-hypothesis signed
    authorization that an inherited rule (011s rule (l), 011w) requires."""
    if post_screening and envelope_only and not per_hypothesis_signature:
        return "CITES"
    return "SUPPORTS"


@dataclass(frozen=True)
class Campaign:
    closed_state: str  # CLOSED_CONCLUDED | CLOSED_INSUFFICIENT_VALIDATION | CLOSED_STOPPED
    stop_record_complete: bool  # reason, what was tried, cost, what would be needed
    registered_tests_run: int  # system-selected, registered, executed, outcome recorded
    validated_outcome: bool  # CONTRADICTED/INCONCLUSIVE under a registered test, or CONFIRMED
    confirmed_claims: int  # stage-3 claims via the Causal Warrant Gate with signed review
    pending_handover: int = 0  # claims handed over, awaiting the Causal Warrant Gate


def termination(c: Campaign) -> tuple[str, str, str]:
    """(operational termination, experimental completion, scientific acceptance)."""
    closed = c.closed_state.startswith("CLOSED_")
    needs_stop = c.closed_state in ("CLOSED_INSUFFICIENT_VALIDATION", "CLOSED_STOPPED")
    valid = closed and (c.stop_record_complete or not needs_stop)
    if c.closed_state == "CLOSED_CONCLUDED" and not c.validated_outcome:
        valid = False
    operational = "VALID" if valid else "INVALID"
    if c.registered_tests_run == 0:
        experimental = "NOT_PERFORMED"
    elif c.validated_outcome:
        experimental = "COMPLETED"
    else:
        experimental = "PARTIAL"
    if valid and c.confirmed_claims > 0:
        scientific = "ACCEPTED_DISCOVERY"
    elif valid and c.pending_handover > 0:
        scientific = "PENDING_CAUSAL_WARRANT_GATE"
    else:
        scientific = "NONE"
    return operational, experimental, scientific


# ---------------------------------------------------------------------------------------------
# Counterexamples
# ---------------------------------------------------------------------------------------------


def _m(name: str, *values: float, model: str | None = None, grid: float = 0.0) -> Mechanism:
    return Mechanism(name, model or f"fm:{name}", tuple({"x": v} for v in values), grid)


E1 = ExperimentSet("E1", {"x": (1.0, 1)})
TAU = 1.0


def check(
    metric: Callable[..., tuple[int, int]] = diversity_bounds,
    score: Callable[..., object] = score_case,
) -> None:
    a, b, c = _m("A", 0.0), _m("B", 0.75), _m("C", 1.5)

    # S1-CE-1: the mandatory counterexample. A/B and B/C indistinguishable, A/C distinguishable.
    assert pair_verdict(a, b, E1, TAU) == INDISTINGUISHABLE
    assert pair_verdict(b, c, E1, TAU) == INDISTINGUISHABLE
    assert pair_verdict(a, c, E1, TAU) == DISTINGUISHABLE
    assert metric([a, b, c], E1, TAU) == (2, 2), "A~B, B~C, A/C: certified diversity is 2"
    assert neighbourhood([a, b, c], 1, E1, TAU) == ("A", "C"), "B's claim cannot exclude A or C"
    assert neighbourhood([a, b, c], 0, E1, TAU) == ("B",), "A's claim excludes C, not B"

    # S1-CE-2: renaming. Fifty aliases (same forward model, new names) add nothing.
    aliases = [_m(f"B{i}", 0.75, model="fm:B") for i in range(50)]
    assert metric([a, b, c, *aliases], E1, TAU) == (2, 2), "aliases inflated diversity"
    assert pair_verdict(b, aliases[0], E1, TAU) == INDISTINGUISHABLE

    # S1-CE-3: near-duplicates. Fifty distinct forward models within 0.1 of B add nothing.
    near = [_m(f"N{i}", 0.70 + 0.002 * i) for i in range(50)]
    assert metric([a, b, c, *near], E1, TAU) == (2, 2), "near-duplicates inflated diversity"

    # S1-CE-4: parameter uncertainty. Ranges that can be made to agree are not distinguishable,
    # even though their nominal points are 3 apart.
    wide_a, wide_b = _m("WA", 0.0, 1.0, 2.0), _m("WB", 2.5, 3.0)
    assert pair_verdict(wide_a, wide_b, E1, TAU) == INDISTINGUISHABLE

    # S1-CE-5: unresolved pairs widen the bounds and never raise the headline lower bound.
    u = _m("U", 2.6, grid=0.2)  # D_hi = 1.1 ≥ τ but D_lo = 0.9 < τ against C
    assert pair_verdict(c, u, E1, TAU) == UNRESOLVED
    assert metric([a, c, u], E1, TAU) == (2, 3)

    # S1-CE-6: experiment-set dependence. A second experiment can separate A and B.
    e2 = ExperimentSet("E2", {"x": (1.0, 1), "y": (1.0, 1)})
    a2 = Mechanism("A", "fm:A", ({"x": 0.0, "y": 0.0},))
    b2 = Mechanism("B", "fm:B", ({"x": 0.75, "y": 2.0},))
    c2 = Mechanism("C", "fm:C", ({"x": 1.5, "y": 0.0},))
    assert metric([a2, b2, c2], e2, TAU) == (3, 3)
    assert metric([a2, b2, c2], ExperimentSet("E2-x", {"x": (1.0, 1)}), TAU) == (2, 2)
    # Joint worst case: one parameter value must fit every experiment.
    joint = Mechanism("J", "fm:J", ({"x": 0.0, "y": 5.0}, {"x": 5.0, "y": 0.0}))
    origin = Mechanism("O", "fm:O", ({"x": 0.0, "y": 0.0},))
    assert pair_verdict(joint, origin, e2, TAU) == DISTINGUISHABLE

    # S1-CE-7: replicates. More replicates shrink the standard error and can separate A and B.
    assert pair_verdict(a, b, ExperimentSet("E1r4", {"x": (1.0, 4)}), TAU) == DISTINGUISHABLE

    # S1-CE-8: a monotone, non-gameable metric: adding one mechanism raises the lower bound by at
    # most one, and only when it is certified distinguishable from every member of a clique.
    for extra in (_m("X", 0.4), _m("Y", 3.0), _m("Z", 1.5, model="fm:C")):
        before, after = metric([a, b, c], E1, TAU)[0], metric([a, b, c, extra], E1, TAU)[0]
        assert after - before in (0, 1)
    assert metric([a, b, c, _m("Y", 3.0)], E1, TAU)[0] == 3

    # S1-CE-9: true-cause scoring ignores names and does not credit unresolved claims.
    truth = _m("truth", 0.0)
    assert true_cause_score(_m("renamed", 0.0, model="fm:truth"), truth, E1, TAU) == (True, True)
    assert true_cause_score(c, truth, E1, TAU) == (False, False)
    assert true_cause_score(_m("V", 1.1, grid=0.2), truth, E1, TAU) == (False, True)
    assert true_cause_score(None, None, E1, TAU) == (True, True)
    assert true_cause_score(b, None, E1, TAU) == (False, False)

    # S1-CE-10: novelty cannot be produced by renaming or by an unresolved comparison.
    assert novelty_against_prior_art(_m("new-name", 0.75, model="fm:B"), [b], E1, TAU) == (
        "KNOWN_MECHANISM_REDISCOVERY"
    )
    assert novelty_against_prior_art(u, [c], E1, TAU) == "NOVELTY_UNRESOLVED"
    assert novelty_against_prior_art(_m("far", 9.0), [a, c], E1, TAU) == (
        "NEW_PHYSICAL_KNOWLEDGE_CANDIDATE"
    )

    # S2 — matched realized cost.
    proto = FrozenProtocol(checkpoints=(25.0, 50.0, 100.0), primary=50.0, tolerance=0.0)

    def run(
        *steps: tuple[float, str | None], stop_at: int | None = None, ledger: float | None = None
    ) -> ArmTrace:
        events: list[Attempt | Answer] = [Answer(None)]
        for k, (cost, value) in enumerate(steps):
            events += [Attempt("experiment", cost), Answer(value, stop=(k == stop_at))]
        total = sum(cost for cost, _ in steps[: (stop_at + 1) if stop_at is not None else None])
        return ArmTrace(tuple(events), total if ledger is None else ledger, cap=100.0)

    # S2-CE-1: early stopping cannot move the comparison point. X is right at 10 and stops; Y is
    # right at 30. The superseded rule compares at 10 and declares X better "at equal budget".
    x = run((10.0, "T"), stop_at=0)
    y = run((10.0, None), (20.0, "T"), (20.0, "T"))
    assert secondary_min_final_cost({"X": x, "Y": y}) == {"X": "T", "Y": None}
    assert score({"X": x, "Y": y}, proto) == {"X": "T", "Y": "T"}
    # Each arm's primary answer depends only on its own trace.
    x_late = run((10.0, None), (80.0, "T"))
    assert score({"X": x_late, "Y": y}, proto)["Y"] == score({"X": x, "Y": y}, proto)["Y"]

    # S2-CE-2: an atomic experiment that straddles the checkpoint supplies nothing to it.
    straddle = run((40.0, None), (30.0, "T"))  # 40 → 70 crosses 50
    assert score({"S": straddle, "Y": y}, proto)["S"] is None
    assert score({"S": straddle, "Y": y}, proto, 100.0)["S"] == "T"

    # S2-CE-3: unrecorded failures, retries or model calls make the case COST_UNMATCHED.
    hidden = run((10.0, "T"), stop_at=0, ledger=35.0)
    assert score({"H": hidden, "Y": y}, proto) == COST_UNMATCHED

    # S2-CE-4: failed attempts and model calls are charged. Retrying until lucky is not free.
    lucky = ArmTrace(
        (
            Answer(None),
            *(Attempt("model_call", 2.0) for _ in range(20)),
            Attempt("experiment", 5.0),
            Answer("T"),
        ),
        ledger_total=45.0,
        cap=100.0,
    )
    assert answer_at(lucky, 25.0) is None and answer_at(lucky, 50.0) == "T"

    # S2-CE-5: a checkpoint chosen after seeing the results is refused.
    try:
        score({"X": x, "Y": y}, proto, 30.0)
    except ValueError:
        pass
    else:
        raise AssertionError("a post-hoc checkpoint was accepted")

    # S2-CE-6: unequal caps or manifests cannot be matched.
    capped = ArmTrace(y.events, y.ledger_total, cap=40.0)
    assert score({"X": x, "C": capped}, proto) == COST_UNMATCHED

    # S4 — the ladder: an authorized exploratory model call is spending, not evidence.
    assert reachable({"SPEND_AUTHORIZED": True}) == "SPEND_AUTHORIZED"
    assert reachable({"SPEND_AUTHORIZED": True, "SUPPORTED": True}) == "SPEND_AUTHORIZED"
    assert reachable({r: True for r in LADDER if r != "REGISTERED"}) == "ADMITTED"
    assert reachable(dict.fromkeys(LADDER, True)) == "CONFIRMED"
    assert support_admissible(post_screening=True, envelope_only=True,
                              per_hypothesis_signature=False) == "CITES"  # fmt: skip
    assert support_admissible(post_screening=True, envelope_only=True,
                              per_hypothesis_signature=True) == "SUPPORTS"  # fmt: skip

    # S4 — termination: a safe stop before any experiment is a valid operational termination,
    # not a completed experimental campaign and not a discovery.
    early = Campaign("CLOSED_STOPPED", True, 0, False, 0)
    assert termination(early) == ("VALID", "NOT_PERFORMED", "NONE")
    assert termination(Campaign("CLOSED_STOPPED", False, 0, False, 0))[0] == "INVALID"
    assert termination(Campaign("CLOSED_CONCLUDED", True, 2, True, 0)) == (
        "VALID", "COMPLETED", "NONE"
    )  # fmt: skip
    assert termination(Campaign("CLOSED_CONCLUDED", True, 1, True, 1)) == (
        "VALID", "COMPLETED", "ACCEPTED_DISCOVERY"
    )  # fmt: skip
    assert termination(Campaign("CLOSED_CONCLUDED", True, 0, False, 0))[0] == "INVALID"
    assert termination(Campaign("CLOSED_CONCLUDED", True, 1, True, 0, pending_handover=1))[2] == (
        "PENDING_CAUSAL_WARRANT_GATE"
    )


def _wrong_score_post_hoc(traces: Mapping[str, ArmTrace], protocol: FrozenProtocol,
                          checkpoint: float | None = None) -> object:  # fmt: skip
    del protocol, checkpoint
    return secondary_min_final_cost(traces)


def _wrong_score_no_straddle(traces: Mapping[str, ArmTrace], protocol: FrozenProtocol,
                             checkpoint: float | None = None) -> object:  # fmt: skip
    c = protocol.primary if checkpoint is None else checkpoint
    if not cost_matched(traces, protocol, c):
        return COST_UNMATCHED
    # WRONG: charges an attempt when it ends and reads the answer after it.
    out: dict[str, str | None] = {}
    for arm, t in traces.items():
        held, spent = None, 0.0
        for ev in t.events:
            if isinstance(ev, Attempt):
                if spent >= c:
                    break
                spent += ev.cost
            else:
                held = ev.value
        out[arm] = held
    return out


def _wrong_score_no_ledger(traces: Mapping[str, ArmTrace], protocol: FrozenProtocol,
                           checkpoint: float | None = None) -> object:  # fmt: skip
    c = protocol.primary if checkpoint is None else checkpoint
    return {arm: answer_at(t, c) for arm, t in traces.items()}


WRONG_VARIANTS: dict[str, dict[str, Callable[..., object]]] = {
    "raw hypothesis count": {"metric": naive_name_count},
    "transitive merge (connected components)": {"metric": naive_transitive_classes},
    "unresolved counted as distinguishable": {
        "metric": lambda h, e, t: (diversity_bounds(h, e, t)[1],) * 2
    },
    "post-hoc smallest-final-cost matching": {"score": _wrong_score_post_hoc},
    "straddling attempt credited to the checkpoint": {"score": _wrong_score_no_straddle},
    "no ledger reconciliation": {"score": _wrong_score_no_ledger},
}


def self_test() -> int:
    for name, overrides in WRONG_VARIANTS.items():
        try:
            check(**overrides)  # type: ignore[arg-type]
        except AssertionError:
            continue
        raise AssertionError(f"semantic self-test: wrong variant {name!r} was not rejected")
    return len(WRONG_VARIANTS)


def summary() -> str:
    return json.dumps({"version": VERSION, "wrong_variants_rejected": len(WRONG_VARIANTS)})


if __name__ == "__main__":
    check()
    message = "semantic reference: every counterexample holds"
    if "--self-test" in sys.argv:
        message += f"; all {self_test()} wrong variants rejected"
    print(message)
