"""T-VER-006: typed Predictions, a declared OutcomeSpace, and a hypothetical that changes nothing.

    §25.3 VER-006  Hypothesis predictions MUST be typed Prediction objects bound to a declared
                   OutcomeSpace version, carrying RelationJudgmentTemplate effects. Sufficiency
                   MUST be computed via side-effect-free `TransitionPolicy.evaluate_hypothetical`;
                   planner or LLM MUST NOT invent hypothetical relations.
    §26   T-VER-006 | contract/unit | Prediction with out-of-space expected_outcome is rejected at
                   admission; `evaluate_hypothetical` persists nothing (no relation rows, no
                   BeliefRevisionEvent, projection unchanged); an action with no bound Prediction
                   over its produces is reported NOT sufficient; identical inputs return identical
                   TransitionDecision.

THE FOUR CLAUSES, AND THE THIRD IS THE ONE THAT LOOKS LIKE A DETAIL. "An action with no bound
Prediction over its produces is reported NOT sufficient" reads like a boundary case; §9.1 spells
out why it is the whole requirement: *absence of a declared prediction is not evidence of
discriminative power*. A planner that treated "no prediction" as "might be informative" would rank
measurements by an LLM's guess about what they would show, which is exactly the bypass §17.5.1
opens by naming.

The "persists nothing" clause is asserted against a real database in
`tests/e2e/test_hypothetical_evaluation_postgres.py` -- counting rows is the only version of that
claim worth making, and it needs rows to count.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import (
    BeliefState,
    ConditionMatchState,
    HypothesisView,
    IndependenceSummary,
    OutcomeSpace,
    Prediction,
    PredictionAdmissionError,
    RelationJudgment,
    RelationJudgmentTemplate,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)
from lab_brain.core.models.prediction import bind
from lab_brain.core.sufficiency import InsufficientReason, evaluate_sufficiency

pytestmark = [pytest.mark.requirement("VER-006"), pytest.mark.spec_test("T-VER-006")]

PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"

#: Requires one SUPPORTS relation. Nothing admitted supplies one, so the baseline is
#: NEED_MORE_EVIDENCE and a prediction that would produce one is genuinely discriminating.
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)

SPACE = OutcomeSpace(
    outcome_space_id="osp:resistance-trend",
    version="1.0.0",
    domain="toy",
    action_type="measurement",
    outcomes=("INCREASES", "FLAT", "DECREASES", "UNMEASURABLE"),
    explicit_exclusions=("UNMEASURABLE",),
)


def view(**overrides: object) -> HypothesisView:
    defaults: dict[str, object] = {
        "hypothesis_id": HYP,
        "project_id": PROJECT,
        "current_state": BeliefState.ACTIVE,
        "stakes": "HIGH",
    }
    defaults.update(overrides)
    return HypothesisView(**defaults)  # type: ignore[arg-type]


def prediction(**overrides: object) -> Prediction:
    defaults: dict[str, object] = {
        "prediction_id": "prd:1",
        "hypothesis_id": HYP,
        "project_id": PROJECT,
        "observable_ref": "obs:contact-resistance-vs-anneal",
        "outcome_space_id": SPACE.outcome_space_id,
        "outcome_space_version": SPACE.version,
        "expected_outcome": "DECREASES",
        "relation_effect_if_observed": (
            RelationJudgmentTemplate(
                relation_type=RelationType.SUPPORTS,
                to_entity_id=HYP,
                implied_authority_class="TIER_A",
                implied_condition_match=ConditionMatchState.COMPATIBLE,
            ),
        ),
    }
    defaults.update(overrides)
    return Prediction(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# Clause 1: admission against the declared space *version*.
# --------------------------------------------------------------------------------------------


def test_a_prediction_inside_its_declared_space_is_admitted():
    assert bind(prediction(), SPACE).expected_outcome == "DECREASES"


def test_an_outcome_the_space_never_declared_is_refused_at_admission():
    """VER-004: a planner MUST NOT invent outcomes, and an imaginable one is not plausible."""
    with pytest.raises(PredictionAdmissionError, match="is not declared by"):
        bind(prediction(expected_outcome="OSCILLATES"), SPACE)


def test_an_explicitly_excluded_outcome_is_refused_and_says_so_differently():
    """Excluded and never-declared are different facts and the message distinguishes them.

    An outcome absent from the space was never in it; an excluded one was considered and ruled out.
    Anyone auditing why a plan was refused needs to know which, because the second is a claim the
    domain made and the first is a gap.
    """
    with pytest.raises(PredictionAdmissionError, match="is explicitly excluded by"):
        bind(prediction(expected_outcome="UNMEASURABLE"), SPACE)


def test_admission_is_against_the_exact_version_not_the_nearest_one():
    """A prediction admitted under v1 is a claim about v1.

    The v2 space below genuinely contains the outcome -- so a check that ignored the version would
    pass, and would be answering a question nobody asked. Spaces change.
    """
    v2 = SPACE.model_copy(update={"version": "2.0.0", "outcomes": (*SPACE.outcomes, "OSCILLATES")})
    with pytest.raises(PredictionAdmissionError, match="was offered"):
        bind(prediction(expected_outcome="OSCILLATES", outcome_space_version="2.0.0"), SPACE)
    with pytest.raises(PredictionAdmissionError, match="was offered"):
        bind(prediction(), v2)
    # And bound to its own version it is fine.
    assert bind(prediction(expected_outcome="OSCILLATES", outcome_space_version="2.0.0"), v2)


def test_a_space_cannot_exclude_an_outcome_it_never_declared():
    """A rule about nothing reads like a rule that fired."""
    with pytest.raises(ValueError, match="never declared"):
        SPACE.model_copy(update={"explicit_exclusions": ("NOT_A_MEMBER",)}).model_validate(
            SPACE.model_dump() | {"explicit_exclusions": ["NOT_A_MEMBER"]}
        )


def test_a_space_cannot_declare_one_outcome_twice():
    with pytest.raises(ValueError, match="more than once"):
        OutcomeSpace(
            outcome_space_id="osp:dup",
            version="1.0.0",
            domain="toy",
            action_type="measurement",
            outcomes=("FLAT", "FLAT"),
        )


# --------------------------------------------------------------------------------------------
# The effects are typed, and they land on their own hypothesis.
# --------------------------------------------------------------------------------------------


def test_a_prediction_must_carry_at_least_one_typed_effect():
    """§17.5.1's `relation_effect_if_observed[]` is what makes the prediction machine-readable.

    Without it the planner is back to asking a model what an outcome would imply, which is the
    bypass the whole section exists to remove.
    """
    with pytest.raises(ValueError):
        prediction(relation_effect_if_observed=())


@pytest.mark.parametrize(
    "relation_type", [RelationType.CITES, RelationType.SAME_WORK_AS, RelationType.PRODUCES]
)
def test_an_effect_that_cannot_move_belief_is_refused(relation_type):
    """A `CITES` effect would make an action look sufficient on a judgment no policy counts."""
    with pytest.raises(ValueError, match="cannot be a prediction effect"):
        RelationJudgmentTemplate(relation_type=relation_type, to_entity_id=HYP)


def test_an_effect_on_another_hypothesis_is_refused():
    """The shape of a planner justifying an expensive measurement with somebody else's prediction."""
    with pytest.raises(ValueError, match="declares effects on"):
        prediction(
            relation_effect_if_observed=(
                RelationJudgmentTemplate(
                    relation_type=RelationType.SUPPORTS, to_entity_id="hyp:something-else"
                ),
            )
        )


def test_instantiated_relations_name_the_prediction_they_came_from():
    """§17.5.1: hypothetical relations are "never invented by the planner or by an LLM".

    Checkable after the fact rather than merely asserted: every hypothetical relation records its
    origin, so a relation that appeared from nowhere is visible as one that names nothing.
    """
    instantiated = prediction().hypothetical_relations(project_id=PROJECT)
    assert len(instantiated) == 1
    relation = instantiated[0]
    assert relation.relation_type is RelationType.SUPPORTS
    assert relation.to_entity_id == HYP
    assert relation.from_entity_id == "prd:1"
    assert relation.inference_provenance_id == "prd:1"
    assert relation.project_id == PROJECT


def test_instantiation_is_deterministic():
    """Ids derived from the prediction, not generated. §26 requires identical inputs to return an
    identical decision, and a `uuid4()` here would make two runs of one plan disagree."""
    first = prediction().hypothetical_relations(project_id=PROJECT)
    second = prediction().hypothetical_relations(project_id=PROJECT)
    assert [r.relation_id for r in first] == [r.relation_id for r in second]


# --------------------------------------------------------------------------------------------
# Clause 3: no bound Prediction over `produces` -> NOT sufficient. §9.1's explicit rule.
# --------------------------------------------------------------------------------------------


def test_an_action_with_no_prediction_over_its_produces_is_not_sufficient():
    """ "Absence of a declared prediction is not evidence of discriminative power" (§9.1).

    Reported with its own reason code, because "not sufficient" and "we could not tell" would
    otherwise be the same answer -- and a planner that read this one as uncertainty would go and
    spend money to find out.
    """
    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view(),
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces="obs:something-nobody-predicted",
        predictions=(bind(prediction(), SPACE),),
        outcome_spaces=(SPACE,),
    )
    assert result.sufficient is False
    assert result.reason is InsufficientReason.NO_PREDICTION_OVER_PRODUCES


def test_a_prediction_belonging_to_another_hypothesis_does_not_count():
    """Same observable, different hypothesis. It predicts something, just not about this belief."""
    other = prediction(
        prediction_id="prd:other",
        hypothesis_id="hyp:other",
        relation_effect_if_observed=(
            RelationJudgmentTemplate(relation_type=RelationType.SUPPORTS, to_entity_id="hyp:other"),
        ),
    )
    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view(),
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=other.observable_ref,
        predictions=(other,),
        outcome_spaces=(SPACE,),
    )
    assert result.reason is InsufficientReason.NO_PREDICTION_OVER_PRODUCES


def test_an_unresolvable_outcome_space_fails_closed():
    """Deciding membership by assumption is what a declared space exists to prevent."""
    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view(),
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=prediction().observable_ref,
        predictions=(prediction(),),
        outcome_spaces=(),
    )
    assert result.sufficient is False
    assert result.reason is InsufficientReason.OUTCOME_SPACE_UNRESOLVED


# --------------------------------------------------------------------------------------------
# The positive: a prediction whose outcome would change the verdict.
# --------------------------------------------------------------------------------------------


def test_a_prediction_that_would_change_the_verdict_is_sufficient():
    """§9.1's first disjunct, end to end, with the baseline carried so the claim is arguable."""
    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view(),
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=prediction().observable_ref,
        predictions=(bind(prediction(), SPACE),),
        outcome_spaces=(SPACE,),
    )
    assert result.sufficient is True
    assert result.baseline.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert result.baseline.reason_code is TransitionReason.MISSING_REQUIRED_RELATION_TYPE
    assert [outcome for outcome, _ in result.discriminating_outcomes] == ["DECREASES"]
    assert result.discriminating_outcomes[0][1].outcome is TransitionOutcome.ALLOW


def test_a_prediction_that_changes_nothing_is_not_sufficient():
    """The already-satisfied case. A measurement that cannot move the verdict is not worth the
    budget, whatever it would show."""
    already = RelationJudgment(
        relation_id="rel:existing",
        from_entity_id="att:1",
        to_entity_id=HYP,
        relation_type=RelationType.SUPPORTS,
        project_id=PROJECT,
        supporting_attestation_ids=("att:1",),
    )
    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view(),
        admitted_relations=(already,),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=prediction().observable_ref,
        predictions=(bind(prediction(), SPACE),),
        outcome_spaces=(SPACE,),
    )
    assert result.baseline.outcome is TransitionOutcome.ALLOW
    assert result.sufficient is False
    assert result.reason is InsufficientReason.NO_OUTCOME_CHANGES_THE_DECISION


def test_the_answer_names_the_clauses_it_did_not_evaluate():
    """§9.1 has more clauses than M0b implements, and the result says so rather than implying it
    checked them. A caller reading `sufficient=True` as §9.1's full predicate would be overclaiming
    by two clauses -- VER-004's DomainPack validator and the blocking-conflict disjunct."""
    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view(),
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=prediction().observable_ref,
        predictions=(bind(prediction(), SPACE),),
        outcome_spaces=(SPACE,),
    )
    assert len(result.unevaluated_clauses) == 2
    assert any("VER-004" in clause for clause in result.unevaluated_clauses)
    assert any("v3.3-a14" in clause for clause in result.unevaluated_clauses)


# --------------------------------------------------------------------------------------------
# Clause 4: identical inputs return an identical TransitionDecision.
# --------------------------------------------------------------------------------------------


def test_evaluate_hypothetical_is_deterministic_across_repeated_calls():
    """Called five times because a comparator or a set iteration that answered differently on the
    second call would register cleanly and then decide plans inconsistently."""
    hypothetical = prediction().hypothetical_relations(project_id=PROJECT)
    results = [
        PROMOTE.evaluate_hypothetical(
            view(), (), hypothetical, None, (), IndependenceSummary(), BeliefState.SUPPORTED
        )
        for _ in range(5)
    ]
    assert all(result == results[0] for result in results)


def test_evaluate_hypothetical_does_not_depend_on_the_order_it_is_handed_relations():
    """Two relations, both orders, one answer. Otherwise "identical inputs" would quietly mean
    "identical *sequences*", and a planner that assembled predictions from a set would get a
    different plan on a different run."""
    second = prediction(
        prediction_id="prd:2",
        relation_effect_if_observed=(
            RelationJudgmentTemplate(relation_type=RelationType.TESTS, to_entity_id=HYP),
        ),
    )
    a = prediction().hypothetical_relations(project_id=PROJECT)
    b = second.hypothetical_relations(project_id=PROJECT)

    forwards = PROMOTE.evaluate_hypothetical(
        view(), (), (*a, *b), None, (), IndependenceSummary(), BeliefState.SUPPORTED
    )
    backwards = PROMOTE.evaluate_hypothetical(
        view(), (), (*b, *a), None, (), IndependenceSummary(), BeliefState.SUPPORTED
    )
    assert forwards == backwards


def test_a_hypothetical_relation_is_not_counted_as_an_independent_attestation():
    """Sufficiency asks whether an outcome *would* change the verdict, not whether the evidence has
    already been gathered. Inflating the independence count answers the second question.

    The policy below needs two independent attestations and has none. The prediction supplies the
    missing relation type, and the verdict still moves only as far as the independence shortfall.
    """
    strict = PROMOTE.model_copy(update={"min_independent_attestations": 2})
    projected = strict.evaluate_hypothetical(
        view(),
        (),
        prediction().hypothetical_relations(project_id=PROJECT),
        None,
        (),
        IndependenceSummary(independent_count=0),
        BeliefState.SUPPORTED,
    )
    assert projected.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert projected.reason_code is TransitionReason.INSUFFICIENT_INDEPENDENT_ATTESTATIONS
    assert projected.independent_attestation_count == 0


def test_a_blocking_conflict_still_blocks_a_hypothetical():
    """`evaluate_hypothetical` is the same decision procedure, so it cannot be a way around a gate.

    A planner using it to discover that an expensive measurement "would promote the belief" while a
    blocking conflict is open would be planning against a state the policy will not permit.
    """
    from tests.contract.test_transition_policy import conflict

    gated = PROMOTE.model_copy(update={"blocking_conflict_policy": ("SIM_TO_REAL_CONFLICT",)})
    blocked = gated.evaluate_hypothetical(
        view(conflicts=(conflict(project_id=PROJECT),)),
        (),
        prediction().hypothetical_relations(project_id=PROJECT),
        None,
        (),
        IndependenceSummary(),
        BeliefState.SUPPORTED,
    )
    assert blocked.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert blocked.reason_code is TransitionReason.BLOCKING_CONFLICT
