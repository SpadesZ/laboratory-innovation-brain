"""A verification result, as evidence: Run -> Observation -> Attestation -> RelationJudgment.

    SYS-001  Artifact/SourceWork -> Claim/Observation -> Attestation -> RelationJudgment ->
             TransitionPolicy -> BeliefRevisionEvent -> EpistemicStateProjection.
    §9.1     relations_from(y) = for each Prediction p bound to an ACTIVE hypothesis where
             p.observable_ref matches action.produces and y is comparable to p.expected_outcome:
             instantiate p.relation_effect_if_observed
    EVI-009  MEASURED/SIMULATED evidence MUST reference the Run and/or Artifact it was derived from.

THE PLANNER'S HYPOTHETICAL RELATIONS AND THE LOOP'S REAL ONES COME FROM THE SAME RULE. §9.1 decides
sufficiency by instantiating the relations a declared Prediction says an outcome would produce;
after the action runs, the relations that enter belief are instantiated from the SAME predictions,
for the outcome actually observed. Nothing here judges whether the outcome "supports" a hypothesis:
the hypothesis's own certificate declared that, before the action was chosen, and the certificate is
immutable (`011i`). An outcome no prediction mentions produces an Observation and an Attestation and
no relation -- it is on record and moves nothing.

"COMPARABLE" IS STRICT: same observable, same OutcomeSpace id AND version, same outcome. A
prediction bound to another version of the space made a claim about that version's vocabulary, and
reading it against this one is the silent re-interpretation VER-004 exists to prevent.

WHAT THIS MODULE WRITES: nothing. It builds the objects; the loop admits the Attestation through
M1's `EvidenceAdmissionGate` (EVI-009, EVI-003) and persists them. A relation carries the
ConditionMatch between the Run's conditions and the diagnosis's, so a result obtained on a different
device cannot license a transition on this one (EVI-005).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lab_brain.core.models.attestation import Attestation, ExtractionProvenance
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.enums import ExtractionStatus
from lab_brain.core.models.job import Run, RunStatus
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.prediction import Prediction
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.verification.workflows import ObservedOutcome


class RunEvidenceError(ValueError):
    """A run result cannot become evidence as offered."""


@dataclass(frozen=True)
class RunEvidence:
    observation: Observation
    attestation: Attestation
    relations: tuple[RelationJudgment, ...]
    #: The predictions whose declared effect this outcome instantiated, in relation order.
    matched_prediction_ids: tuple[str, ...]


def _method(method_ref: str) -> tuple[str, str]:
    rule, separator, version = method_ref.rpartition("@")
    if not separator or not rule or not version:
        raise RunEvidenceError(
            f"method_ref {method_ref!r} is not `rule_id@version`. §6.18's contamination rollback "
            "selects evidence by the version of what produced it; an unversioned rule makes a "
            "quarantine impossible"
        )
    return rule, version


def comparable(prediction: Prediction, outcome: ObservedOutcome) -> bool:
    """§9.1's `y is comparable to p.expected_outcome`, in the strict form the docstring gives."""
    return (
        prediction.observable_ref == outcome.observable_ref
        and prediction.outcome_space_id == outcome.outcome_space_id
        and prediction.outcome_space_version == outcome.outcome_space_version
        and prediction.expected_outcome == outcome.outcome
    )


def evidence_from_run(
    *,
    run: Run,
    outcome: ObservedOutcome,
    predictions: Sequence[Prediction],
    condition_match: ConditionMatch,
    actor_id: str,
    mint: Callable[[str], str],
    at: dt.datetime,
) -> RunEvidence:
    """The evidence one observed outcome of one SUCCEEDED Run amounts to."""
    if run.status is not RunStatus.SUCCEEDED:
        raise RunEvidenceError(
            f"run {run.run_id} is {run.status.value}; a run that did not succeed is a record of an "
            "attempt, not evidence (EVI-009)"
        )
    if not run.output_artifacts:
        raise RunEvidenceError(f"run {run.run_id} produced no artifact to trace to (EVI-009)")
    rule_id, rule_version = _method(outcome.method_ref)
    observation = Observation(
        observation_id=mint("observation"),
        run_id=run.run_id,
        metric_or_event=outcome.observable_ref,
        value_ref=outcome.value_ref,
        value=outcome.outcome,
        unit=outcome.unit,
        conditions=dict(run.conditions),
        conditions_schema_version=run.conditions_schema_version,
        method_ref=outcome.method_ref,
        project_id=run.project_id,
        created_at=at,
    )
    attestation = Attestation(
        attestation_id=mint("attestation"),
        observation_id=observation.observation_id,
        epistemic_type=outcome.epistemic_type,
        run_id=run.run_id,
        locator=f"run:{run.run_id}#{outcome.observable_ref}",
        conditions=dict(run.conditions),
        conditions_schema_version=run.conditions_schema_version,
        units=outcome.unit,
        method={
            "method_ref": outcome.method_ref,
            "outcome_space": f"{outcome.outcome_space_id}@{outcome.outcome_space_version}",
            "outcome": outcome.outcome,
            "detail": dict(outcome.detail),
        },
        extraction_status=ExtractionStatus.STAGE_B_STRUCTURED,
        authority_class=outcome.authority_class,
        project_id=run.project_id,
        extractor_version=rule_version,
        extraction_provenance=ExtractionProvenance(
            extractor_id=rule_id,
            extractor_version=rule_version,
            extracted_at=at,
            stage=ExtractionStatus.STAGE_B_STRUCTURED,
        ),
        created_at=at,
    )
    relations: list[RelationJudgment] = []
    matched: list[str] = []
    for prediction in sorted(predictions, key=lambda p: (p.hypothesis_id, p.prediction_id)):
        if prediction.project_id != run.project_id or not comparable(prediction, outcome):
            continue
        matched.append(prediction.prediction_id)
        for effect in prediction.relation_effect_if_observed:
            relations.append(
                RelationJudgment(
                    relation_id=mint("relation"),
                    from_entity_id=observation.observation_id,
                    to_entity_id=effect.to_entity_id,
                    relation_type=effect.relation_type,
                    attributes={
                        "prediction_id": prediction.prediction_id,
                        "outcome": outcome.outcome,
                        "outcome_space": prediction.outcome_space_ref,
                        "run_id": run.run_id,
                        "capability_id": run.capability_id,
                    },
                    supporting_attestation_ids=(attestation.attestation_id,),
                    condition_match_ref=condition_match.condition_match_id,
                    actor_id=actor_id,
                    project_id=run.project_id,
                    valid_from=at,
                    created_at=at,
                )
            )
    return RunEvidence(
        observation=observation,
        attestation=attestation,
        relations=tuple(relations),
        matched_prediction_ids=tuple(matched),
    )


__all__ = [
    "RunEvidence",
    "RunEvidenceError",
    "comparable",
    "evidence_from_run",
]
