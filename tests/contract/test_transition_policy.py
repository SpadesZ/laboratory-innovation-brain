"""EPI-005: a belief transition is a versioned deterministic policy decision, not an LLM vote.

    §8.2.1  TransitionPolicy 是版本化、可測試的 deterministic-first policy。LLM ... **不得**
            直接把 ACTIVE 改成 SUPPORTED/REJECTED。
    §8.2.1  This signature is normative (EPI-005). No other name or arity may appear elsewhere:
            TransitionPolicy.evaluate(hypothesis, admitted_relations, authority_policy,
            condition_matches, independence_summary, candidate_to_state) -> TransitionDecision
    §8.2.1  Deterministic: identical inputs + identical policy_version MUST return identical
            TransitionDecision.
    §10.5.1 INCOMPARABLE is a legitimate result and MUST NOT be silently coerced into an ordering.
    §6.17   TransitionPolicy 若宣告 independence_basis 高於 WORK, MUST 回傳 NEED_HUMAN_REVIEW
            而非假裝已滿足。

Every negative case below is a way a plausible policy says ALLOW when it must not, or invents a
fact rather than escalating. The determinism cases are the ones that cannot be checked by reading
the code: they run the decision twice, and once in a *fresh process*, because the failure mode is
unstable set iteration, which a single process hides.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from typing import ClassVar

import pytest

from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.models import (
    AuthorityComparison,
    BeliefState,
    ConditionMatch,
    ConditionMatchState,
    ConditionMismatch,
    ConditionSchemaRef,
    HypothesisView,
    IndependenceBasis,
    IndependenceSummary,
    RelationJudgment,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)
from lab_brain.core.models.conflict import Conflict, ConflictType
from lab_brain.spec import repo_root

pytestmark = [pytest.mark.requirement("EPI-005"), pytest.mark.spec_test("T-EPI-005")]

T0 = dt.datetime(2026, 9, 15, 11, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"


class ToyAuthority:
    """A stand-in DomainPack comparator. Core owns the abstraction and none of the rules (§10.5).

    `MEASURED` is stronger than `SIMULATED`; `HEURISTIC` does not rank against either -- which is
    the whole reason INCOMPARABLE exists, and the case this class is here to produce.
    """

    policy_id = "auth:toy"
    policy_version = "toy-1.0.0"
    authority_classes: ClassVar[tuple[str, ...]] = ("HEURISTIC", "MEASURED", "SIMULATED")
    _rank: ClassVar[dict[str, int]] = {"SIMULATED": 1, "MEASURED": 2}

    def compare(self, a: str, b: str) -> AuthorityComparison:
        # Reflexivity before the ranking lookup, so an unranked class still ranks with itself --
        # the same law that caught a bug in `tests/toy_authority.py`.
        if a == b:
            return AuthorityComparison.EQUIVALENT
        return self._compare(a, b)

    def _compare(self, a: str, b: str) -> AuthorityComparison:
        if a not in self._rank or b not in self._rank:
            return AuthorityComparison.INCOMPARABLE
        if self._rank[a] == self._rank[b]:
            return AuthorityComparison.EQUIVALENT
        return (
            AuthorityComparison.STRONGER
            if self._rank[a] > self._rank[b]
            else AuthorityComparison.WEAKER
        )

    def meets(self, required_rule: str, candidate: str) -> bool:
        return self.compare(candidate, required_rule) in (
            AuthorityComparison.STRONGER,
            AuthorityComparison.EQUIVALENT,
        )


def policy(**overrides: object) -> TransitionPolicy:
    defaults: dict[str, object] = {
        "policy_id": "pol:hypothesis-default",
        "version": "1.0.0",
        "from_state": BeliefState.ACTIVE,
        "candidate_to_state": BeliefState.SUPPORTED,
        "required_relation_types": (RelationType.SUPPORTS,),
        "min_independent_attestations": 2,
        "independence_basis": IndependenceBasis.WORK,
    }
    defaults.update(overrides)
    return TransitionPolicy(**defaults)  # type: ignore[arg-type]


def hypothesis(**overrides: object) -> HypothesisView:
    defaults: dict[str, object] = {
        "hypothesis_id": HYP,
        "project_id": PROJECT,
        "current_state": BeliefState.ACTIVE,
        "stakes": "HIGH",
    }
    defaults.update(overrides)
    return HypothesisView(**defaults)  # type: ignore[arg-type]


def relation(relation_type: RelationType = RelationType.SUPPORTS, **overrides: object):
    defaults: dict[str, object] = {
        "relation_id": "rel:1",
        "from_entity_id": "att:1",
        "to_entity_id": HYP,
        "relation_type": relation_type,
        "project_id": PROJECT,
        # RelationJudgment requires provenance for an epistemic relation -- an M0a invariant, and
        # the right one: a SUPPORTS judgment nobody can attribute is not evidence.
        "supporting_attestation_ids": ("att:1",),
    }
    defaults.update(overrides)
    return RelationJudgment(**defaults)  # type: ignore[arg-type]


def conflict(**overrides: object) -> Conflict:
    """A typed §17.19.3 conflict. Blocking and OPEN unless a case says otherwise."""
    defaults: dict[str, object] = {
        "conflict_id": "cfl:1",
        "project_id": PROJECT,
        "conflict_type": ConflictType.SIM_TO_REAL_CONFLICT,
        "subject_refs": (HYP,),
        "blocking": True,
        "detected_at": dt.datetime(2026, 9, 16, 9, 0, tzinfo=dt.UTC),
        "detected_by_actor_or_slot": "act:test",
        "trace_id": "trc:1",
    }
    defaults.update(overrides)
    return Conflict(**defaults)  # type: ignore[arg-type]


def summary(**overrides: object) -> IndependenceSummary:
    defaults: dict[str, object] = {
        "basis": IndependenceBasis.WORK,
        "independent_count": 2,
        "unknown_count": 0,
    }
    defaults.update(overrides)
    return IndependenceSummary(**defaults)  # type: ignore[arg-type]


def run(
    pol: TransitionPolicy | None = None,
    hyp: HypothesisView | None = None,
    relations: tuple[RelationJudgment, ...] | None = None,
    authority: object = None,
    matches: tuple[ConditionMatch, ...] = (),
    independence: IndependenceSummary | None = None,
    to_state: BeliefState = BeliefState.SUPPORTED,
):
    return (pol or policy()).evaluate(
        hyp or hypothesis(),
        relations if relations is not None else (relation(),),
        authority,  # type: ignore[arg-type]
        matches,
        independence or summary(),
        to_state,
    )


# --------------------------------------------------------------------------------------------
# The signature is normative. §8.2.1 / T-EPI-005.
# --------------------------------------------------------------------------------------------


def test_only_evaluate_exists_and_it_has_the_declared_arity():
    """T-EPI-005: "only `evaluate` signature exists in the codebase (no `should_transition`)".

    A second entry point is how a caller ends up using the one that skips a check.
    """
    import inspect

    for forbidden in ("should_transition", "can_transition", "decide", "can_promote", "transition"):
        assert not hasattr(TransitionPolicy, forbidden), forbidden

    parameters = list(inspect.signature(TransitionPolicy.evaluate).parameters)
    assert parameters == [
        "self",
        "hypothesis",
        "admitted_relations",
        "authority_policy",
        "condition_matches",
        "independence_summary",
        "candidate_to_state",
    ]


def test_no_module_in_the_tree_defines_a_rival_transition_operator():
    """The rule is about the codebase, not one class, so it is checked against the codebase.

    Scans for a *definition*, not a mention: `transition.py`'s own docstring says there is
    deliberately no `should_transition`, and a naive substring search flagged that sentence. A
    guard that fires on its own documentation gets deleted rather than fixed.
    """
    rivals = ("should_transition", "can_transition", "can_promote", "decide_transition")
    offenders = sorted(
        f"{path.relative_to(repo_root()).as_posix()}:{name}"
        for path in (repo_root() / "src").rglob("*.py")
        for name in rivals
        if f"def {name}" in path.read_text(encoding="utf-8")
    )
    assert offenders == [], f"a rival transition operator is defined in {offenders}"


def test_the_decision_carries_everything_8_2_1_declares():
    decision = run()
    for field in (
        "outcome",
        "reason_code",
        "policy_id",
        "policy_version",
        "blocking_conflict_ids",
        "required_authority_gap",
        "independent_attestation_count",
        "review_item_spec",
    ):
        assert field in type(decision).model_fields, f"§8.2.1 declares {field}"


def test_the_decision_records_the_policy_that_made_it():
    """`v3.3-a11`'s reason for existing: a version alone cannot select what to re-run."""
    decision = run()
    assert (decision.policy_id, decision.policy_version) == ("pol:hypothesis-default", "1.0.0")


def test_the_decision_exposes_no_bare_allowed_flag():
    """Several gates answer several questions; a caller must not read one as all of them."""
    decision = run()
    assert decision.permits_transition is True
    assert not hasattr(decision, "allowed")


# --------------------------------------------------------------------------------------------
# The gate must be passable, or it is a prohibition.
# --------------------------------------------------------------------------------------------


def test_a_satisfied_policy_allows_the_transition():
    decision = run()
    assert decision.outcome is TransitionOutcome.ALLOW
    assert decision.reason_code is TransitionReason.POLICY_SATISFIED
    assert decision.independent_attestation_count == 2
    assert decision.review_item_spec is None


# --------------------------------------------------------------------------------------------
# Refusals. Each names what to do next, which is what a reason_code is for.
# --------------------------------------------------------------------------------------------


def test_a_transition_this_policy_does_not_govern_is_denied():
    """A policy for ACTIVE -> SUPPORTED must not answer about ADMITTED -> ACTIVE."""
    assert (
        run(hyp=hypothesis(current_state=BeliefState.ADMITTED)).reason_code
        is TransitionReason.TRANSITION_NOT_GOVERNED
    )
    assert (
        run(to_state=BeliefState.CONTRADICTED).reason_code
        is TransitionReason.TRANSITION_NOT_GOVERNED
    )


def test_a_missing_required_relation_type_needs_more_evidence():
    """Actionable: the planner can go and get a SUPPORTS relation."""
    decision = run(relations=(relation(RelationType.CONTRADICTS),))
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert decision.reason_code is TransitionReason.MISSING_REQUIRED_RELATION_TYPE


def test_no_relations_at_all_needs_more_evidence():
    decision = run(relations=())
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE


def test_an_unknown_count_does_not_help_reach_the_threshold():
    """EVI-004: DEPENDENCE_UNKNOWN contributes 0, and the shortfall must not be guessed away.

    Five unclassified attestations and one independent one is not six independent ones.
    """
    decision = run(independence=summary(independent_count=1, unknown_count=5))
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert decision.reason_code is TransitionReason.INSUFFICIENT_INDEPENDENT_ATTESTATIONS
    assert decision.independent_attestation_count == 1, "the unknowns are not counted in"


def test_an_independence_basis_above_work_needs_human_review():
    """§6.17 / FIX-6, by name. Same-lab, same-wafer and same-instrument correlation is not modelled.

    The forbidden behaviour is *pretending to be satisfied*, so an ALLOW here would be the defect.
    """
    for basis in (
        IndependenceBasis.GROUP,
        IndependenceBasis.SAMPLE,
        IndependenceBasis.INSTRUMENT,
        IndependenceBasis.METHOD,
    ):
        decision = run(pol=policy(independence_basis=basis))
        assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW, basis
        assert decision.reason_code is TransitionReason.INDEPENDENCE_BASIS_NOT_MODELLED
        assert decision.review_item_spec is not None


def test_a_summary_computed_on_a_different_basis_needs_human_review():
    """Counting under one basis and gating under another is a comparison of two different things."""
    decision = run(independence=summary(basis=IndependenceBasis.GROUP))
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW


def test_a_blocking_conflict_prevents_allow_and_is_named_in_the_decision():
    """§23.4: blocking Conflict 會阻止 ALLOW 並出現在 TransitionDecision.blocking_conflict_ids."""
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(
            conflicts=(conflict(conflict_id="cfl:2"), conflict(conflict_id="cfl:1")),
        ),
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.BLOCKING_CONFLICT
    assert decision.blocking_conflict_ids == ("cfl:1", "cfl:2"), "sorted, so the record is stable"


def test_a_policy_that_ignores_conflicts_is_not_blocked_by_them():
    """The field has to be meaningful in both directions, or it is decoration."""
    decision = run(hyp=hypothesis(conflicts=(conflict(),)))
    assert decision.outcome is TransitionOutcome.ALLOW


def test_an_explicit_human_gate_cannot_satisfy_itself():
    decision = run(pol=policy(human_gate=True))
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.HUMAN_GATE_REQUIRED


# --------------------------------------------------------------------------------------------
# Authority is a partial order. §10.5.1.
# --------------------------------------------------------------------------------------------


def test_incomparable_authority_needs_human_review_and_never_an_ordering():
    """The rule §10.5.1 states outright: INCOMPARABLE MUST NOT be coerced into an ordering.

    A heuristic and a measurement do not rank. Answering DENY would be a ranking ("weaker"), and
    answering ALLOW would be the opposite one; both invent the fact the comparator refused to give.
    """
    decision = run(
        pol=policy(required_authority_rule="MEASURED"),
        hyp=hypothesis(admitted_authority_classes=("HEURISTIC",)),
        authority=ToyAuthority(),
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE
    assert decision.required_authority_gap == "MEASURED"
    spec = decision.review_item_spec
    assert spec is not None
    assert spec.subject_type == "AUTHORITY_CONFLICT", "§8.2.1 names this subject_type"
    assert spec.subject_id == HYP
    assert spec.stakes == "HIGH", "§8.2.1 passes hypothesis.stakes through"


def test_insufficient_authority_is_denied_with_the_gap_named():
    """Ranked and found wanting is a different answer from unrankable."""
    decision = run(
        pol=policy(required_authority_rule="MEASURED"),
        hyp=hypothesis(admitted_authority_classes=("SIMULATED",)),
        authority=ToyAuthority(),
    )
    assert decision.outcome is TransitionOutcome.DENY
    assert decision.reason_code is TransitionReason.AUTHORITY_INSUFFICIENT
    assert decision.required_authority_gap == "MEASURED"


def test_sufficient_authority_allows():
    decision = run(
        pol=policy(required_authority_rule="SIMULATED"),
        hyp=hypothesis(admitted_authority_classes=("MEASURED",)),
        authority=ToyAuthority(),
    )
    assert decision.outcome is TransitionOutcome.ALLOW


def test_a_required_authority_rule_with_no_comparator_does_not_pass():
    """A rule nothing can test is not a satisfied rule.

    Escalates rather than DENYing: the usual cause is a caller that has not wired the DomainPack
    comparator, which is a wiring problem a human should see.
    """
    decision = run(
        pol=policy(required_authority_rule="MEASURED"),
        hyp=hypothesis(admitted_authority_classes=("MEASURED",)),
        authority=None,
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW


def test_a_required_authority_rule_with_no_evidence_classes_does_not_pass():
    decision = run(
        pol=policy(required_authority_rule="MEASURED"),
        hyp=hypothesis(admitted_authority_classes=()),
        authority=ToyAuthority(),
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW


# --------------------------------------------------------------------------------------------
# Condition matches. §17.19's UNKNOWN is not INCOMPATIBLE.
# --------------------------------------------------------------------------------------------


def _match(state: ConditionMatchState) -> ConditionMatch:
    """A ConditionMatch in ``state``, with whatever that state requires to be well-formed.

    `ConditionMatch` refuses an UNKNOWN with no recorded unknown field and an INCOMPATIBLE with no
    recorded mismatch -- an M0a invariant, and the right one: a verdict with nothing behind it is
    not reviewable. So the fixture supplies the evidence each state needs rather than weakening
    the model to suit the test.
    """
    extra: dict[str, object] = {}
    if state is ConditionMatchState.UNKNOWN:
        extra["unknowns"] = ("bias_v",)
    elif state is ConditionMatchState.INCOMPATIBLE:
        extra["mismatches"] = (
            ConditionMismatch(field="bias_v", left=0.0, right=3.3, reason="outside tolerance"),
        )
    return ConditionMatch(
        state=state,
        schema_ref=ConditionSchemaRef(domain="core", schema_id="sch_test", version="1.0.0"),
        tolerance_policy_version="1.0.0",
        **extra,  # type: ignore[arg-type]
    )


def test_a_missing_condition_match_needs_more_evidence():
    decision = run(pol=policy(required_condition_match=(ConditionMatchState.EXACT,)), matches=())
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert decision.reason_code is TransitionReason.CONDITION_MATCH_MISSING


def test_an_unacceptable_condition_match_is_denied():
    decision = run(
        pol=policy(required_condition_match=(ConditionMatchState.EXACT,)),
        matches=(_match(ConditionMatchState.INCOMPATIBLE),),
    )
    assert decision.outcome is TransitionOutcome.DENY
    assert decision.reason_code is TransitionReason.CONDITION_MATCH_UNACCEPTABLE


def test_an_unknown_condition_match_needs_human_review_not_a_verdict():
    """§17.19 keeps UNKNOWN distinct from INCOMPATIBLE on purpose.

    "We cannot tell whether these conditions are comparable" and "they are not comparable" lead to
    different gate outcomes, and collapsing them loses the escalation signal.
    """
    decision = run(
        pol=policy(required_condition_match=(ConditionMatchState.EXACT,)),
        matches=(_match(ConditionMatchState.UNKNOWN),),
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.CONDITION_MATCH_UNKNOWN


def test_an_acceptable_condition_match_allows():
    decision = run(
        pol=policy(
            required_condition_match=(ConditionMatchState.EXACT, ConditionMatchState.COMPATIBLE)
        ),
        matches=(_match(ConditionMatchState.COMPATIBLE),),
    )
    assert decision.outcome is TransitionOutcome.ALLOW


# --------------------------------------------------------------------------------------------
# Determinism. §8.2.1, and the half of T-EPI-005 that cannot be read off the code.
# --------------------------------------------------------------------------------------------


def test_repeated_calls_on_identical_inputs_give_an_identical_decision():
    """Compared under canonical serialization, as §26 requires -- not by field spot-checks."""
    args = {
        # A real §17.19.3 type: `"X"` was a placeholder here and is now refused at construction,
        # which is the vocabulary guard EPI-006 added doing its job on this project's own tests.
        "pol": policy(
            required_authority_rule="MEASURED",
            blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",),
        ),
        "hyp": hypothesis(admitted_authority_classes=("MEASURED", "SIMULATED")),
        "authority": ToyAuthority(),
        "matches": (_match(ConditionMatchState.EXACT),),
    }
    first = run(**args)  # type: ignore[arg-type]
    second = run(**args)  # type: ignore[arg-type]
    assert canonicalize(first.model_dump(mode="json")) == canonicalize(
        second.model_dump(mode="json")
    )


def test_the_decision_does_not_depend_on_the_order_the_inputs_arrive_in():
    """Two callers assembling the same evidence in different orders must get the same answer.

    Otherwise "identical inputs" would mean "identical *sequences*", and a replay that rebuilt the
    evidence set from the database -- which has its own ordering -- would disagree with the
    original decision.
    """
    forwards = run(
        pol=policy(required_authority_rule="SIMULATED"),
        hyp=hypothesis(admitted_authority_classes=("MEASURED", "SIMULATED")),
        authority=ToyAuthority(),
        relations=(relation(), relation(relation_id="rel:2", relation_type=RelationType.TESTS)),
    )
    backwards = run(
        pol=policy(required_authority_rule="SIMULATED"),
        hyp=hypothesis(admitted_authority_classes=("SIMULATED", "MEASURED")),
        authority=ToyAuthority(),
        relations=(relation(relation_id="rel:2", relation_type=RelationType.TESTS), relation()),
    )
    assert canonicalize(forwards.model_dump(mode="json")) == canonicalize(
        backwards.model_dump(mode="json")
    )


#: Hash seeds the determinism check runs under.
#:
#: EIGHT, NOT TWO, AND THE NUMBER WAS EARNED. The first version of this test used two seeds and a
#: three-element authority set -- and a deliberate mutation that iterated that set unordered and
#: reported one of its members *passed* it, because those two particular seeds happened to produce
#: the same iteration order for those three particular strings. Measured afterwards: across eight
#: seeds a three-element set of short strings yields three distinct first elements, so two seeds
#: was simply too small a sample to see the variation it was written to detect.
#:
#: A determinism test that agrees with a nondeterministic implementation is worse than none, so the
#: sample is now eight seeds over a six-element set.
_HASH_SEEDS = ("0", "1", "2", "7", "13", "42", "12345", "99991")


def test_the_decision_is_identical_in_a_fresh_process():
    """The determinism test that matters, and the one a single process cannot perform.

    Set iteration order depends on `PYTHONHASHSEED`, which is randomised per process. A policy that
    iterated a set and put a member in its decision would pass every in-process check and then
    disagree with itself on the day an auditor re-ran it. Every subprocess, under every seed, must
    produce a byte-identical canonical decision.
    """
    classes = (
        "MEASURED",
        "SIMULATED",
        "HEURISTIC_A",
        "HEURISTIC_B",
        "HEURISTIC_C",
        "HEURISTIC_D",
    )
    script = (
        "import sys\n"
        "sys.path.insert(0, 'src')\n"
        "sys.path.insert(0, '.')\n"
        "from tests.contract.test_transition_policy import "
        "ToyAuthority, hypothesis, policy, relation, summary, _match\n"
        "from lab_brain.core.canonical_json import canonicalize\n"
        "from lab_brain.core.models import BeliefState, ConditionMatchState\n"
        f"d = policy(required_authority_rule='SIMULATED').evaluate(\n"
        f"    hypothesis(admitted_authority_classes={classes!r}),\n"
        "    (relation(),), ToyAuthority(), (_match(ConditionMatchState.EXACT),), summary(),\n"
        "    BeliefState.SUPPORTED)\n"
        "print(canonicalize(d.model_dump(mode='json')))\n"
    )
    outputs: dict[str, str] = {}
    for seed in _HASH_SEEDS:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        )
        assert result.returncode == 0, f"seed {seed}: {result.stderr}"
        outputs[seed] = result.stdout.strip()

    assert all(outputs.values()), "a subprocess produced no decision at all"
    distinct = set(outputs.values())
    assert len(distinct) == 1, (
        "the decision differs between processes with different hash seeds, so something in "
        "`evaluate` iterates an unordered collection:\n"
        + "\n".join(f"  {seed}: {value}" for seed, value in sorted(outputs.items()))
    )


def test_evaluate_reads_no_clock_and_no_randomness():
    """Static guard on the module, so the property is visible rather than only observed.

    A policy that consulted the time would give a different answer on the day somebody audited it,
    which is the specific thing §8.2.1's determinism sentence forbids.
    """
    source = (repo_root() / "src" / "lab_brain" / "core" / "models" / "transition.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def _decide(", 1)[1]
    for forbidden in ("utc_now", "datetime.now", "time.time", "random.", "uuid4", "os.environ"):
        assert forbidden not in body, f"`evaluate` reaches for {forbidden}"


def test_effective_from_is_recorded_but_not_consulted():
    """Selecting the applicable version is the caller's job.

    A policy that filtered itself by comparing `effective_from` against the current time would read
    a clock, and a replay would then re-run today's policy against yesterday's evidence.
    """
    past = policy(effective_from=T0 - dt.timedelta(days=365))
    future = policy(effective_from=T0 + dt.timedelta(days=365))
    assert run(pol=past).outcome is run(pol=future).outcome is TransitionOutcome.ALLOW
