"""§17.5.1's typed Prediction and the OutcomeSpace it must be bound to (VER-006).

    §17.5.1  Prediction 把「假說預測什麼」變成機器可解的物件。沒有它，Verification Planner
             只能讓 LLM 猜測某個 outcome 是否會改變信念狀態，等於繞過 TransitionPolicy。

WHY A TYPE AND NOT A STRING, WHICH IS THE WHOLE REQUIREMENT. A prediction written as prose can only
be interpreted by asking a model what it implies -- and "would this outcome change the belief
state?" is the question `TransitionPolicy.evaluate` exists to answer. So a prose prediction does
not merely lose structure; it moves a belief decision into an LLM, which is the one thing EPI-005
and AGT-016 both forbid. `relation_effect_if_observed` is the field that closes it: the prediction
says, in advance and in typed form, exactly which `RelationJudgment` an observation would produce.

WHAT IS NOT HERE. §9.1's `sufficient(action)` and the Verification Planner are M4 (VER-001/VER-003).
This module supplies the object VER-006 requires and the instantiation that
`evaluate_hypothetical` consumes -- `plausible()`, the DomainPack validator, Capability feasibility
and the cost-ranked plan are the planner's, and building half of one here would make the seam look
finished.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.enums import ConditionMatchState, RelationType
from lab_brain.core.models.relation import EPISTEMIC_RELATION_TYPES, RelationJudgment

#: The relation types a Prediction may declare as its effect (§17.5.1).
#:
#: Exactly §17.8's epistemic four, and the same set `evaluate` counts. A prediction whose effect
#: was `CITES` would instantiate a hypothetical relation that no `required_relation_types` can be
#: satisfied by, so the action would be reported sufficient on the strength of a relation that
#: cannot move belief.
PREDICTION_EFFECT_TYPES = frozenset(EPISTEMIC_RELATION_TYPES)


class OutcomeSpace(CoreModel):
    """§17.19.2's declared, versioned space of outcomes an action may yield.

    THE DECLARED SET IS THE POINT (VER-004). "Planner MUST NOT invent outcomes. An outcome that is
    merely imaginable is not plausible." An outcome space that could be extended at planning time
    would make that sentence unenforceable, so membership is decided against a frozen tuple and a
    version, and a Prediction records **which version** it was bound to.

    `explicit_exclusions` is separate from simply leaving an outcome out, and the difference is
    recorded rather than derived: an outcome absent from `outcomes` was never in the space, while
    an excluded one was considered and ruled out. §9.1's `plausible()` needs the second to be
    visible -- "we know this cannot happen here" is evidence, and deleting it loses the reason.
    """

    outcome_space_id: str
    version: str
    domain: str
    action_type: str
    hypothesis_type: str | None = None
    schema_version: str | None = None
    outcomes: tuple[str, ...] = Field(min_length=1)
    order_or_metric_ref: str | None = None
    explicit_exclusions: tuple[str, ...] = ()
    validity_bounds: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _outcomes_are_distinct_and_exclusions_are_real(self) -> Self:
        """Two rules that both protect membership from meaning two things.

        A duplicated outcome makes "is y a member" depend on which copy is found, and an exclusion
        naming an outcome the space never declared is a rule about nothing -- which reads, to
        anyone auditing why a plan was refused, exactly like a rule that fired.
        """
        if len(set(self.outcomes)) != len(self.outcomes):
            duplicated = sorted({o for o in self.outcomes if self.outcomes.count(o) > 1})
            raise ValueError(
                f"outcome space {self.outcome_space_id}@{self.version} declares {duplicated} more "
                "than once; membership must be one fact, not two"
            )
        stray = sorted(set(self.explicit_exclusions) - set(self.outcomes))
        if stray:
            raise ValueError(
                f"outcome space {self.outcome_space_id}@{self.version} excludes {stray}, which it "
                "never declared. An exclusion naming a non-member is a rule about nothing, and "
                "reads like a rule that fired to anyone auditing why a plan was refused"
            )
        return self

    @property
    def ref(self) -> str:
        """`id@version`, the form a Prediction's binding is read back as."""
        return f"{self.outcome_space_id}@{self.version}"

    def admits(self, outcome: str) -> bool:
        """Whether ``outcome`` is a declared, non-excluded member of *this version*."""
        return outcome in self.outcomes and outcome not in self.explicit_exclusions


class RelationJudgmentTemplate(CoreModel):
    """§17.5.1: the `RelationJudgment` an observation would produce, declared in advance.

    A template rather than a relation, because the thing it describes has not happened. It carries
    no `relation_id`, no provenance and no `valid_from`: those are facts about an observation that
    was made, and a template that had them would be a judgment asserting an experiment nobody ran.
    """

    relation_type: RelationType
    #: The hypothesis this effect lands on (§17.5.1).
    to_entity_id: str
    #: The authority class the producing Capability would yield -- declared, because the planner
    #: must be able to ask "would evidence of *this* quality clear the gate" before spending on it.
    implied_authority_class: str | None = None
    implied_condition_match: ConditionMatchState | None = None

    @model_validator(mode="after")
    def _the_effect_must_be_able_to_move_belief(self) -> Self:
        if self.relation_type not in PREDICTION_EFFECT_TYPES:
            raise ValueError(
                f"relation_type {self.relation_type.value} cannot be a prediction effect. §17.5.1 "
                "declares SUPPORTS | CONTRADICTS | TESTS | PREDICTS, and a bookkeeping relation "
                "would make an action look sufficient on the strength of a judgment that cannot "
                "change any belief state"
            )
        return self

    def instantiate(
        self, *, relation_id: str, from_entity_id: str, project_id: str
    ) -> RelationJudgment:
        """Build the hypothetical `RelationJudgment` this template describes.

        `inference_provenance_id` records the prediction the relation came from, which is what
        keeps §17.5.1's "never invented by the planner or by an LLM at planning time" checkable
        after the fact rather than merely asserted: every hypothetical relation names its origin.

        The result is an ordinary `RelationJudgment` and is **never persisted** -- see
        `TransitionPolicy.evaluate_hypothetical`, which is the only thing that consumes it.
        """
        return RelationJudgment(
            relation_id=relation_id,
            from_entity_id=from_entity_id,
            to_entity_id=self.to_entity_id,
            relation_type=self.relation_type,
            project_id=project_id,
            inference_provenance_id=from_entity_id,
        )


class Prediction(CoreModel):
    """§17.5.1's typed prediction, bound to a declared OutcomeSpace **version** (VER-006)."""

    prediction_id: str
    hypothesis_id: str
    project_id: str
    #: What is measured or computed. §9.1 matches this against `action.produces`.
    observable_ref: str
    outcome_space_id: str
    outcome_space_version: str
    #: MUST be a member of the declared OutcomeSpace (§17.5.1). Checked at admission, against the
    #: space itself -- see `bind`, because a model cannot validate this alone.
    expected_outcome: str
    direction: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str | None = None
    relation_effect_if_observed: tuple[RelationJudgmentTemplate, ...] = Field(min_length=1)
    inference_provenance_id: str | None = None

    @model_validator(mode="after")
    def _every_effect_lands_on_this_hypothesis(self) -> Self:
        """§17.5.1: `to_entity_id` is *the* hypothesis_id.

        An effect pointing elsewhere would let a prediction about hypothesis A be used to argue
        that an action discriminates hypothesis B, which is the shape of a planner justifying an
        expensive measurement with somebody else's prediction.
        """
        stray = sorted(
            {
                effect.to_entity_id
                for effect in self.relation_effect_if_observed
                if effect.to_entity_id != self.hypothesis_id
            }
        )
        if stray:
            raise ValueError(
                f"prediction {self.prediction_id} is bound to {self.hypothesis_id} but declares "
                f"effects on {stray}. A prediction's effects land on its own hypothesis"
            )
        return self

    @property
    def outcome_space_ref(self) -> str:
        return f"{self.outcome_space_id}@{self.outcome_space_version}"

    def hypothetical_relations(
        self, *, project_id: str, id_prefix: str = "rel:hypothetical"
    ) -> tuple[RelationJudgment, ...]:
        """Instantiate this prediction's effects, in declaration order.

        Deterministic ids, derived from the prediction rather than generated: these relations feed
        `evaluate_hypothetical`, whose result §26 requires to be identical across repeated calls on
        identical inputs. A `uuid4()` here would make two runs of one plan disagree.
        """
        return tuple(
            effect.instantiate(
                relation_id=f"{id_prefix}:{self.prediction_id}:{index}",
                from_entity_id=self.prediction_id,
                project_id=project_id,
            )
            for index, effect in enumerate(self.relation_effect_if_observed)
        )


class PredictionAdmissionError(ValueError):
    """A Prediction was offered that its declared OutcomeSpace does not admit (VER-006).

    Its own type, because §26 requires the refusal to happen "at admission" and a caller that
    caught a bare `ValueError` would not be able to tell this from a malformed field.
    """


def bind(prediction: Prediction, space: OutcomeSpace) -> Prediction:
    """Admit a Prediction against the exact OutcomeSpace version it names, or refuse it.

    THE VERSION IS PART OF THE CHECK, NOT CONTEXT. §17.5.1 says the expected outcome must be a
    member of "its declared OutcomeSpace **version**", so validating against a *different* version
    of the same space -- even a newer one that happens to contain the outcome -- answers a question
    nobody asked. Spaces change; a prediction admitted under v1 is a claim about v1.

    This is a function rather than a validator on the model for the reason `ConditionSchemaRegistry`
    is: the model cannot reach the registry, and a model that silently skipped the check when no
    space was available would make admission optional exactly when it matters.
    """
    if (space.outcome_space_id, space.version) != (
        prediction.outcome_space_id,
        prediction.outcome_space_version,
    ):
        raise PredictionAdmissionError(
            f"prediction {prediction.prediction_id} is bound to "
            f"{prediction.outcome_space_ref} but was offered {space.ref}. A prediction admitted "
            "under one version is a claim about that version, and a space's membership changes"
        )
    if not space.admits(prediction.expected_outcome):
        reason = (
            "is explicitly excluded by"
            if prediction.expected_outcome in space.explicit_exclusions
            else "is not declared by"
        )
        raise PredictionAdmissionError(
            f"prediction {prediction.prediction_id} expects {prediction.expected_outcome!r}, "
            f"which {reason} {space.ref} (declared: {sorted(space.outcomes)}). VER-004: a planner "
            "MUST NOT invent outcomes, and an outcome that is merely imaginable is not plausible"
        )
    return prediction


__all__ = [
    "PREDICTION_EFFECT_TYPES",
    "OutcomeSpace",
    "Prediction",
    "PredictionAdmissionError",
    "RelationJudgmentTemplate",
    "bind",
]
