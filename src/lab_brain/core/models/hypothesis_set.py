"""The competing-hypothesis set: the unit EPI-001's "at least two" is counted over (§3 P6, §8).

    EPI-001    至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被升級成 confirmed
               root cause。
    T-EPI-001  root-cause episode 在驗證前保留至少兩個 active/competing hypotheses。

WHY A SET IS A RECORD AND NOT A QUERY. "Competing" is a relation between hypotheses -- they are
rival answers to ONE question -- and two hypotheses that happen to share an episode are not thereby
rivals. So the question they compete to answer is stated once, here, and a hypothesis is admitted
INTO a set. The count EPI-001 cares about is then a count over a declared group rather than over
whatever an episode accumulated, and "a single plausible cause" is a set with one member -- visible
to the database, which refuses the promotion (`005e`).

THE POLICY FACTS ARE FROZEN AT CREATION. ``source_policy_id``/``source_policy_version`` and
``inverted_retrieval_required`` record which SourcePolicy selected the evidence and whether its
threshold was reached by ``stakes`` (SRC-002). They are recorded, not recomputed at revision time:
a policy revised after the debate must not retroactively excuse the debate from inverted retrieval,
nor retroactively convict one that followed the rules in force.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.hypothesis import Hypothesis
from lab_brain.core.models.prediction import Prediction


class HypothesisSet(CoreModel):
    """Rival answers to one question in one episode."""

    set_id: str
    project_id: str
    episode_id: str
    question: str
    research_intent: str
    stakes: str
    #: A root-cause set is the one EPI-001's promotion rule binds: its winner becomes a confirmed
    #: root cause, which a single plausible cause may not become directly.
    root_cause: bool = True
    source_policy_id: str
    source_policy_version: str
    #: SRC-002, evaluated once against the policy in force:
    #: `stakes >= inverted_retrieval_threshold`.
    inverted_retrieval_required: bool
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_set_states_its_question(self) -> Self:
        for name in ("question", "research_intent", "stakes", "source_policy_id"):
            if not getattr(self, name).strip():
                raise ValueError(
                    f"hypothesis set {self.set_id} has a blank {name}; competing hypotheses "
                    "compete to answer a stated question under a stated policy"
                )
        return self


class HypothesisCertificate(CoreModel):
    """A §8.1 certificate as M3 stores it: the Hypothesis, its set, its author and its predictions.

    A wrapper rather than new fields on `Hypothesis`, because `Hypothesis` is M0b's hard-locked
    model and its field set is the §8.1 contract T-SYS-001 checks. What M3 adds -- which set the
    hypothesis competes in, who authored it, and the typed Prediction objects its `prediction_ids`
    name -- lives beside it, and the wrapper refuses the one inconsistency it could otherwise hold:
    `prediction_ids` that are not exactly the predictions carried.

    THE TYPED FALSIFIER. `Hypothesis.falsifier` is the author's prose -- kept, shown as its
    explanation, and never consumed by a machine path. What a check can adjudicate is
    `falsifier_prediction_ids`: the carried predictions the author DESIGNATED as the falsifier, each
    declaring only CONTRADICTS on this hypothesis. A designation is what makes the falsifier
    machine-checkable; a CONTRADICTS prediction elsewhere in the certificate is not one. The model
    admits an empty designation so a certificate stored before it existed still reads back;
    admission refuses one (`certificate_completeness_problems`, `012n`).

    ONE FALSIFIER AUTHORITY. The prose and the designation can disagree -- a model wrote "agrees"
    and designated DISAGREES -- and nothing judges which is meant. Every machine consumer therefore
    reads the designation (`falsifier_predictions`, rendered by `typed_falsifier_text`): the
    Critic's inverted retrieval, the Critic, verification and belief. The prose is never compared
    with it, rewritten or used in its place.
    """

    hypothesis: Hypothesis
    hypothesis_set_id: str
    predictions: tuple[Prediction, ...] = ()
    falsifier_prediction_ids: tuple[str, ...] = ()
    authored_by_actor_id: str | None = None
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _one_order_for_one_certificate(cls, data: Any) -> Any:
        """Predictions and their ids in id order, so equal certificates compare equal.

        A certificate is a set of commitments, not a sequence; the order a caller listed them in is
        not part of what was admitted, and a store that returns them by id must round-trip to an
        equal value.
        """
        if not isinstance(data, dict):
            return data
        predictions = data.get("predictions")
        if predictions:
            data = {
                **data,
                "predictions": tuple(
                    sorted(
                        predictions,
                        key=lambda p: (
                            p.prediction_id if isinstance(p, Prediction) else p["prediction_id"]
                        ),
                    )
                ),
            }
        designated = data.get("falsifier_prediction_ids")
        if designated:
            data = {**data, "falsifier_prediction_ids": tuple(sorted(designated))}
        hypothesis = data.get("hypothesis")
        if isinstance(hypothesis, Hypothesis):
            data = {
                **data,
                "hypothesis": hypothesis.model_copy(
                    update={"prediction_ids": tuple(sorted(hypothesis.prediction_ids))}
                ),
            }
        return data

    @model_validator(mode="after")
    def _the_certificate_names_exactly_its_predictions(self) -> Self:
        carried = sorted(p.prediction_id for p in self.predictions)
        if sorted(self.hypothesis.prediction_ids) != carried:
            raise ValueError(
                f"hypothesis {self.hypothesis.hypothesis_id} names predictions "
                f"{sorted(self.hypothesis.prediction_ids)} and carries {carried}; §8.1's "
                "prediction_ids reference the typed objects, and a reference to an absent one is "
                "prose again"
            )
        stray = sorted(
            p.prediction_id
            for p in self.predictions
            if p.hypothesis_id != self.hypothesis.hypothesis_id
            or p.project_id != self.hypothesis.project_id
        )
        if stray:
            raise ValueError(
                f"predictions {stray} are carried by hypothesis "
                f"{self.hypothesis.hypothesis_id} but bound to another hypothesis or project"
            )
        return self

    @model_validator(mode="after")
    def _the_falsifier_is_a_carried_contradiction(self) -> Self:
        if len(set(self.falsifier_prediction_ids)) != len(self.falsifier_prediction_ids):
            raise ValueError(
                f"hypothesis {self.hypothesis.hypothesis_id} designates a falsifier prediction "
                "twice"
            )
        carried = {p.prediction_id: p for p in self.predictions}
        for prediction_id in self.falsifier_prediction_ids:
            prediction = carried.get(prediction_id)
            if prediction is None:
                raise ValueError(
                    f"hypothesis {self.hypothesis.hypothesis_id} designates falsifier prediction "
                    f"{prediction_id}, which its certificate does not carry; a falsifier is one of "
                    "the hypothesis's own typed predictions"
                )
            effects = sorted(
                {e.relation_type.value for e in prediction.relation_effect_if_observed}
            )
            if effects != [RelationType.CONTRADICTS.value]:
                raise ValueError(
                    f"hypothesis {self.hypothesis.hypothesis_id} designates falsifier prediction "
                    f"{prediction_id}, which declares {effects}; a falsifier declares only "
                    "CONTRADICTS"
                )
        return self

    @property
    def hypothesis_id(self) -> str:
        return self.hypothesis.hypothesis_id

    @property
    def falsifier_predictions(self) -> tuple[Prediction, ...]:
        """The designated typed falsifier, in prediction-id order: what verification adjudicates.
        Empty only for a certificate stored before the designation existed."""
        carried = {p.prediction_id: p for p in self.predictions}
        return tuple(carried[i] for i in self.falsifier_prediction_ids)


def typed_falsifier_text(prediction: Prediction) -> str:
    """One designated falsifier prediction as text, for search and for reading: its admitted
    facts and nothing else -- no inference, no paraphrase, no domain vocabulary.

        sp.normalization_basis = DISAGREES in os:sp.normalization_basis@1.0.0
            -> CONTRADICTS hyp:... (prd:...)
    """
    effects = "/".join(
        sorted({e.relation_type.value for e in prediction.relation_effect_if_observed})
    )
    return (
        f"{prediction.observable_ref} = {prediction.expected_outcome} in "
        f"{prediction.outcome_space_ref} -> {effects} {prediction.hypothesis_id} "
        f"({prediction.prediction_id})"
    )


__all__ = ["HypothesisCertificate", "HypothesisSet", "typed_falsifier_text"]
