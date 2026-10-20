"""From a designated typed falsifier to a governed belief move, through the web workspace.

A model route is applied (the stand-in, whose research answers come from the pack's catalog through
the real role contracts and parsers) and a device project is the verification input. Every admitted
hypothesis designates its falsifier -- its own CONTRADICTS predictions -- and when a local,
deterministic check REALLY runs and observes exactly a designated falsifying outcome, the path is:
Run (with its output artifact) -> Observation -> Attestation (OBSERVED, tied to that Run) ->
RelationJudgment CONTRADICTS from that prediction -> the TransitionPolicy's decision ->
BeliefRevisionEvent authorised by an ALLOW decision. No relation exists that a prediction did not
declare for the exact outcome observed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.e2e.test_research_episode_postgres import PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _research
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres

CHECK = "cap:sp.extraction_consistency"
OBSERVABLE = "sp.normalization_basis"


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _all(db, sql: str, *args: object) -> list[tuple]:  # type: ignore[no-untyped-def]
    return list(db.execute(sql, args).fetchall())


def test_an_observed_designated_falsifier_moves_belief_through_a_governed_decision(
    db, tmp_path, fake
):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    sent = _research(browser, tmp_path, case="contact-open-via")
    assert sent.status == 303, _text(sent)[:500]
    (episode,) = _all(db, "SELECT episode_id FROM research_episodes WHERE project_id = %s", PROJECT)
    episode = episode[0]

    # 1-3: every admitted hypothesis designates a typed falsifier -- its own CONTRADICTS predictions.
    hypotheses = _all(
        db,
        "SELECT hypothesis_id, falsifier, falsifier_prediction_ids FROM hypotheses"
        " WHERE project_id = %s AND created_in_episode = %s",
        PROJECT,
        episode,
    )
    assert len(hypotheses) >= 2
    designated: dict[str, str] = {}
    for hypothesis_id, prose, ids in hypotheses:
        assert prose.strip() and ids, hypothesis_id
        for prediction_id in ids:
            owner, kinds = _all(
                db,
                "SELECT p.hypothesis_id, array_agg(DISTINCT e ->> 'relation_type')"
                " FROM predictions p, jsonb_array_elements(p.relation_effect_if_observed) e"
                " WHERE p.prediction_id = %s GROUP BY p.hypothesis_id",
                prediction_id,
            )[0]
            assert (owner, kinds) == (hypothesis_id, ["CONTRADICTS"])
            designated[prediction_id] = hypothesis_id
    models = {r[0] for r in _all(db, "SELECT DISTINCT model_id FROM inference_provenance")}
    assert models <= {"fake-reasoner", "fake-critic"}, "the hypotheses came through a model route"

    # 4: no relation that a prediction did not declare for the exact outcome observed.
    relations = _all(
        db,
        "SELECT r.relation_id, r.relation_type, r.to_entity_id, r.attributes ->> 'prediction_id',"
        " o.observation_id, coalesce(o.value_text, o.value_numeric::text), o.metric_or_event,"
        " o.run_id, a.attestation_id"
        " FROM relation_judgments r JOIN observations o ON o.observation_id = r.from_entity_id"
        " JOIN attestations a ON a.attestation_id = ANY (r.supporting_attestation_ids)"
        " WHERE r.project_id = %s",
        PROJECT,
    )
    assert relations
    for _, kind, target, prediction_id, _, value, observable, _, _ in relations:
        declared = _all(
            db,
            "SELECT p.hypothesis_id, p.observable_ref, p.expected_outcome, e ->> 'relation_type'"
            " FROM predictions p, jsonb_array_elements(p.relation_effect_if_observed) e"
            " WHERE p.prediction_id = %s",
            prediction_id,
        )
        assert declared == [(target, observable, value, kind)], prediction_id

    # 5-6: the normalization check really ran, observed AGREES -- the falsifier the normalization
    # hypothesis designated -- and the CONTRADICTS relation is that prediction's, traceable.
    (run,) = _all(
        db,
        "SELECT r.run_id, r.status, r.output_artifacts, j.state FROM runs r"
        " JOIN jobs j ON j.job_id = r.job_id WHERE j.episode_id = %s AND r.capability_id = %s",
        episode,
        CHECK,
    )
    run_id, status, outputs, state = run
    assert (status, state) == ("SUCCEEDED", "SUCCEEDED") and outputs
    assert _all(db, "SELECT 1 FROM artifacts WHERE artifact_id = ANY (%s)", outputs)
    falsified = [
        r
        for r in relations
        if r[7] == run_id and r[6] == OBSERVABLE and r[3] in designated and r[1] == "CONTRADICTS"
    ]
    assert len(falsified) == 1, relations
    relation_id, _, target, prediction_id, observation_id, value, _, _, attestation_id = falsified[
        0
    ]
    assert value == "AGREES" and designated[prediction_id] == target
    (attested,) = _all(
        db,
        "SELECT epistemic_type, run_id, observation_id FROM attestations WHERE attestation_id = %s",
        attestation_id,
    )
    assert attested == ("OBSERVED", run_id, observation_id)

    # 7-8: the TransitionPolicy decided, and the event it authorised carries an ALLOW decision.
    moved = _all(
        db,
        "SELECT e.event_id, e.target_id, e.from_state, e.to_state, e.policy_id, d.result,"
        " d.policy_id, d.subject_id FROM belief_revision_event_relations l"
        " JOIN belief_revision_events e ON e.event_id = l.event_id"
        " JOIN belief_transition_decisions d ON d.decision_id = e.authorization_decision_id"
        " WHERE l.relation_id = %s",
        relation_id,
    )
    assert len(moved) == 1, moved
    _, moved_target, from_state, to_state, policy, result, decided_by, subject = moved[0]
    assert (moved_target, subject) == (target, target)
    assert (from_state, to_state, result) == ("ACTIVE", "CONTRADICTED", "ALLOW")
    assert policy == decided_by
    ungoverned = _all(
        db,
        "SELECT e.event_id FROM belief_revision_events e WHERE e.project_id = %s"
        " AND e.from_state IS NOT NULL AND NOT EXISTS (SELECT 1 FROM belief_transition_decisions d"
        " WHERE d.decision_id = e.authorization_decision_id AND d.result = 'ALLOW')",
        PROJECT,
    )
    assert ungoverned == [], "every belief move has its ALLOW decision"
