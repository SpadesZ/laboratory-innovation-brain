"""What an episode's stored records say each executed check meant: the episode page's read model.

READ-ONLY, AND NOTHING HERE DECIDES. The research service already decided everything: which
predictions each certificate declared and designated, which RelationJudgments an observed outcome
instantiated, which transitions a TransitionPolicy authorised. This module reads those rows back for
a reader, per executed check of one research run:

    the Observation the check's Run produced, and its admitted Attestation;
    every typed Prediction the episode's hypotheses declared over that observable -- with whether
        it is comparable to the observed outcome (`verification.evidence.comparable`, the rule
        `evidence_from_run` applied) and whether its certificate designates it as the falsifier;
    the RelationJudgments the Observation instantiated, and for each the governed belief events it
        triggered and the transition decisions that considered it.

Nothing is inferred. A check whose outcome matches no declared prediction is reported as matching
none -- never as supporting or contradicting anything, whatever the outcome's name suggests -- and a
relation with no recorded decision is reported as exactly that. Genesis events are admissions, not
revisions, and are never counted as something a check moved. No report text is read: everything
here comes from typed rows, and a row that is not there is shown as not recorded.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.models.hypothesis_set import HypothesisCertificate
from lab_brain.core.models.prediction import Prediction
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.research.continuation import verification_key_prefix
from lab_brain.verification.evidence import comparable
from lab_brain.verification.workflows import ObservedOutcome


@dataclass(frozen=True)
class DeclaredPrediction:
    """One typed prediction a hypothesis declared, as a reader needs it."""

    hypothesis_id: str
    mechanism: str
    prediction_id: str
    observable: str
    outcome_space: str
    expected_outcome: str
    effects: tuple[str, ...]
    #: The certificate designates it as the falsifier: what verification adjudicates.
    designated_falsifier: bool


@dataclass(frozen=True)
class Transition:
    """A governed belief event an observed relation triggered -- never a genesis admission."""

    event_id: str
    hypothesis_id: str
    mechanism: str
    from_state: str
    to_state: str
    policy: str
    decision_id: str | None
    decision: str | None


@dataclass(frozen=True)
class Decision:
    """A transition decision that considered a relation, whether or not it authorised a move."""

    decision_id: str
    hypothesis_id: str
    result: str
    policy: str
    from_state: str
    to_state: str


@dataclass(frozen=True)
class Relation:
    relation_id: str
    relation_type: str
    hypothesis_id: str
    mechanism: str
    prediction_id: str | None
    transitions: tuple[Transition, ...]
    decisions: tuple[Decision, ...]


@dataclass(frozen=True)
class CheckResult:
    """One observed outcome of one executed check, and what the records say it did."""

    run_id: str
    observation_id: str
    attestation_id: str | None
    epistemic_type: str | None
    observable: str
    outcome: str
    outcome_space: str | None
    #: Every prediction declared over this observable, split by `comparable` to the outcome.
    matched: tuple[DeclaredPrediction, ...]
    unmatched: tuple[DeclaredPrediction, ...]
    relations: tuple[Relation, ...]

    @property
    def transitions(self) -> tuple[Transition, ...]:
        return tuple(t for r in self.relations for t in r.transitions)


@dataclass(frozen=True)
class ExecutedCheck:
    """A verification Run of the episode, as its row says: which check, when, and how it ended."""

    run_id: str
    capability_id: str
    status: str
    started_at: dt.datetime | None


@dataclass(frozen=True)
class EpisodeView:
    """The read model of one research run of one episode. Empty mappings mean "not recorded"."""

    #: Every verification Run of the episode, in start order -- any research run's.
    executed: tuple[ExecutedCheck, ...] = ()
    #: run id of an executed check -> its observed outcomes (normally one).
    results: Mapping[str, tuple[CheckResult, ...]] = field(default_factory=dict)
    #: hypothesis id -> every prediction its certificate declared, in prediction-id order.
    predictions: Mapping[str, tuple[DeclaredPrediction, ...]] = field(default_factory=dict)
    #: capability id -> its action type, as the episode's verification plans recorded it.
    action_types: Mapping[str, str] = field(default_factory=dict)

    def falsifiers(self, hypothesis_id: str) -> tuple[DeclaredPrediction, ...]:
        return tuple(p for p in self.predictions.get(hypothesis_id, ()) if p.designated_falsifier)


def _declared(certificate: HypothesisCertificate) -> tuple[DeclaredPrediction, ...]:
    designated = set(certificate.falsifier_prediction_ids)
    return tuple(
        DeclaredPrediction(
            hypothesis_id=certificate.hypothesis_id,
            mechanism=certificate.hypothesis.mechanism,
            prediction_id=p.prediction_id,
            observable=p.observable_ref,
            outcome_space=p.outcome_space_ref,
            expected_outcome=p.expected_outcome,
            effects=tuple(e.relation_type.value for e in p.relation_effect_if_observed),
            designated_falsifier=p.prediction_id in designated,
        )
        for p in certificate.predictions
    )


def _observed(
    observable: str,
    outcome: str,
    space: str | None,
    epistemic: str | None,
    method: Mapping[str, Any],
) -> ObservedOutcome | None:
    """The outcome as `comparable` reads it; `None` when the attestation does not name its space."""
    if not space or "@" not in space:
        return None
    space_id, _, version = space.rpartition("@")
    return ObservedOutcome(
        observable_ref=observable,
        outcome_space_id=space_id,
        outcome_space_version=version,
        outcome=outcome,
        epistemic_type=EpistemicType(epistemic) if epistemic else EpistemicType.OBSERVED,
        authority_class=str(method.get("authority_class", "")),
        method_ref=str(method.get("method_ref", "")),
    )


def load_episode_view(connection: Any, *, project_id: str, episode_id: str) -> EpisodeView:
    """The read model of one episode: every verification Run it has, and what each meant."""
    set_row = connection.execute(
        "SELECT hypothesis_set_id FROM research_runs WHERE project_id = %s AND episode_id = %s"
        " AND hypothesis_set_id IS NOT NULL ORDER BY ordinal LIMIT 1",
        (project_id, episode_id),
    ).fetchone()
    certificates: tuple[HypothesisCertificate, ...] = (
        SqlHypothesisStore(connection).certificates_in_set(str(set_row[0])) if set_row else ()
    )
    predictions = {c.hypothesis_id: _declared(c) for c in certificates}
    typed: dict[str, Prediction] = {p.prediction_id: p for c in certificates for p in c.predictions}
    declared = {p.prediction_id: p for ps in predictions.values() for p in ps}
    mechanisms = {c.hypothesis_id: c.hypothesis.mechanism for c in certificates}

    action_types: dict[str, str] = {}
    for (rationale,) in connection.execute(
        "SELECT rationale FROM verification_plans WHERE project_id = %s AND episode_id = %s"
        " ORDER BY created_at",
        (project_id, episode_id),
    ).fetchall():
        value = rationale if isinstance(rationale, dict) else json.loads(rationale or "{}")
        for tradeoff in value.get("tradeoffs", []):
            action_types.setdefault(str(tradeoff["action_id"]), str(tradeoff["action_type"]))

    # Verification checks only -- the loop's own jobs, by the key `prior_verification` reads --
    # not the episode's document ingestion.
    prefix = verification_key_prefix(episode_id)
    executed = tuple(
        ExecutedCheck(run_id=str(r[0]), capability_id=str(r[1]), status=str(r[2]), started_at=r[3])
        for r in connection.execute(
            "SELECT r.run_id, r.capability_id, r.status, r.start_time FROM runs r"
            " JOIN jobs j ON j.job_id = r.job_id"
            " WHERE j.project_id = %s AND j.episode_id = %s AND left(j.idempotency_key, %s) = %s"
            " ORDER BY r.start_time, r.run_id",
            (project_id, episode_id, len(prefix), prefix),
        ).fetchall()
    )
    results: dict[str, tuple[CheckResult, ...]] = {}
    for run_id in (x.run_id for x in executed):
        found: list[CheckResult] = []
        for observation_id, observable, value in connection.execute(
            "SELECT observation_id, metric_or_event, coalesce(value_text, value_numeric::text)"
            " FROM observations WHERE project_id = %s AND run_id = %s"
            " ORDER BY created_at, observation_id",
            (project_id, run_id),
        ).fetchall():
            attestation = connection.execute(
                "SELECT attestation_id, epistemic_type, authority_class, method FROM attestations"
                " WHERE project_id = %s AND observation_id = %s ORDER BY attestation_id LIMIT 1",
                (project_id, observation_id),
            ).fetchone()
            method: dict[str, Any] = {}
            if attestation is not None:
                raw = attestation[3]
                method = dict(raw if isinstance(raw, dict) else json.loads(raw or "{}"))
                method.setdefault("authority_class", attestation[2])
            space = method.get("outcome_space")
            observed = _observed(
                str(observable),
                str(value),
                str(space) if space else None,
                str(attestation[1]) if attestation is not None else None,
                method,
            )
            over = [p for p in declared.values() if p.observable == observable]
            matched = tuple(
                p
                for p in over
                if observed is not None and comparable(typed[p.prediction_id], observed)
            )
            relations = tuple(
                _relation(connection, project_id, episode_id, row, mechanisms)
                for row in connection.execute(
                    "SELECT relation_id, relation_type, to_entity_id,"
                    " attributes ->> 'prediction_id' FROM relation_judgments"
                    " WHERE project_id = %s AND from_entity_id = %s ORDER BY relation_id",
                    (project_id, observation_id),
                ).fetchall()
            )
            found.append(
                CheckResult(
                    run_id=run_id,
                    observation_id=str(observation_id),
                    attestation_id=str(attestation[0]) if attestation is not None else None,
                    epistemic_type=str(attestation[1]) if attestation is not None else None,
                    observable=str(observable),
                    outcome=str(value),
                    outcome_space=str(space) if space else None,
                    matched=matched,
                    unmatched=tuple(p for p in over if p not in matched),
                    relations=relations,
                )
            )
        results[run_id] = tuple(found)
    return EpisodeView(
        executed=executed, results=results, predictions=predictions, action_types=action_types
    )


def _relation(
    connection: Any,
    project_id: str,
    episode_id: str,
    row: Sequence[Any],
    mechanisms: Mapping[str, str],
) -> Relation:
    relation_id, relation_type, hypothesis_id, prediction_id = (str(v) if v else None for v in row)
    assert relation_id and relation_type and hypothesis_id
    transitions = tuple(
        Transition(
            event_id=str(r[0]),
            hypothesis_id=str(r[1]),
            mechanism=mechanisms.get(str(r[1]), str(r[1])),
            from_state=str(r[2]),
            to_state=str(r[3]),
            policy=f"{r[4]}@{r[5]}",
            decision_id=str(r[6]) if r[6] else None,
            decision=str(r[7]) if r[7] else None,
        )
        for r in connection.execute(
            "SELECT e.event_id, e.target_id, e.from_state, e.to_state, e.policy_id,"
            " e.policy_version, d.decision_id, d.result FROM belief_revision_event_relations l"
            " JOIN belief_revision_events e ON e.event_id = l.event_id"
            " LEFT JOIN belief_transition_decisions d"
            " ON d.decision_id = e.authorization_decision_id"
            " WHERE l.relation_id = %s AND e.project_id = %s AND e.from_state IS NOT NULL"
            " ORDER BY e.occurred_at, e.event_id",
            (relation_id, project_id),
        ).fetchall()
    )
    decisions = tuple(
        Decision(
            decision_id=str(r[0]),
            hypothesis_id=str(r[1]),
            result=str(r[2]),
            policy=f"{r[3]}@{r[4]}",
            from_state=str(r[5]),
            to_state=str(r[6]),
        )
        for r in connection.execute(
            "SELECT decision_id, subject_id, result, policy_id, policy_version, from_state,"
            " to_state FROM belief_transition_decisions"
            " WHERE project_id = %s AND episode_id = %s"
            " AND decision_input_snapshot::jsonb -> 'admitted_relations' @> %s::jsonb"
            " ORDER BY created_at, decision_id",
            (project_id, episode_id, json.dumps([{"relation_id": relation_id}])),
        ).fetchall()
    )
    return Relation(
        relation_id=relation_id,
        relation_type=relation_type,
        hypothesis_id=hypothesis_id,
        mechanism=mechanisms.get(hypothesis_id, hypothesis_id),
        prediction_id=prediction_id,
        transitions=transitions,
        decisions=decisions,
    )


__all__ = [
    "CheckResult",
    "Decision",
    "DeclaredPrediction",
    "EpisodeView",
    "ExecutedCheck",
    "Relation",
    "Transition",
    "load_episode_view",
]
