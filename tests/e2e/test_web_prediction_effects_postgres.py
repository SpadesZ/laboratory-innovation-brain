"""PREDICTS, SUPPORTS and falsifiers alone, through the web workspace: what each makes of one check.

The recorded failure, as a regression: a route proposed the right mechanism (contact
discontinuity) and declared its forecast `sp.contact_connectivity = DISCONTINUOUS` as PREDICTS; the
local connectivity check really ran and observed DISCONTINUOUS. Here, with the stand-in model route
giving the same certificates in three shapes, on the same case (`contact-open-via`):

    PREDICTS            the observation instantiates a PREDICTS relation from that prediction, and
                        nothing promotes it: no SUPPORTS relation exists, no transition to SUPPORTED
                        is decided, the episode is not CONFIRMED
    SUPPORTS            the same observation instantiates SUPPORTS from the declared prediction, a
                        governed ALLOW decision promotes the hypothesis, the episode is CONFIRMED
    falsifiers only     the certificates are admitted; observations relate only through declared
                        CONTRADICTS predictions; nothing is supported and nothing is confirmed

The relation is always the declared effect for the exact outcome observed; the shape of the
certificate -- never the outcome's name -- decides it.
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

OBSERVABLE = "sp.contact_connectivity"


@pytest.fixture
def fake(request: pytest.FixtureRequest) -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY, **getattr(request, "param", {})).start()
    yield provider
    provider.stop()


def _all(db, sql: str, *args: object) -> list[tuple]:  # type: ignore[no-untyped-def]
    return list(db.execute(sql, args).fetchall())


def _run(db, tmp_path, fake) -> str:  # type: ignore[no-untyped-def]
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    sent = _research(browser, tmp_path, case="contact-open-via")
    assert sent.status == 303, _text(sent)[:500]
    ((episode,),) = _all(
        db, "SELECT episode_id FROM research_episodes WHERE project_id = %s", PROJECT
    )
    return str(episode)


def _connectivity_relations(db, episode: str) -> list[tuple]:  # type: ignore[no-untyped-def]
    """(relation type, hypothesis, observed outcome, the declaring prediction's own effect)."""
    return _all(
        db,
        "SELECT r.relation_type, r.to_entity_id, o.value_text, e ->> 'relation_type'"
        " FROM relation_judgments r JOIN observations o ON o.observation_id = r.from_entity_id"
        " JOIN runs u ON u.run_id = o.run_id JOIN jobs j ON j.job_id = u.job_id"
        " JOIN predictions p ON p.prediction_id = r.attributes ->> 'prediction_id',"
        " jsonb_array_elements(p.relation_effect_if_observed) e"
        " WHERE j.episode_id = %s AND o.metric_or_event = %s",
        episode,
        OBSERVABLE,
    )


def _supported(db, episode: str) -> list[tuple]:  # type: ignore[no-untyped-def]
    return _all(
        db,
        "SELECT d.subject_id, d.result FROM belief_transition_decisions d"
        " WHERE d.episode_id = %s AND d.to_state = 'SUPPORTED'",
        episode,
    )


def _outcome(db, episode: str) -> str:  # type: ignore[no-untyped-def]
    ((state, outcome),) = _all(
        db,
        "SELECT state, coalesce(outcome_status, '') FROM research_episodes WHERE episode_id = %s",
        episode,
    )
    return f"{state}:{outcome}"


def _observed(db, episode: str) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        r[0]
        for r in _all(
            db,
            "SELECT o.value_text FROM observations o JOIN runs u ON u.run_id = o.run_id"
            " JOIN jobs j ON j.job_id = u.job_id"
            " WHERE j.episode_id = %s AND o.metric_or_event = %s",
            episode,
            OBSERVABLE,
        )
    ]


@pytest.mark.parametrize("fake", [{"forecast_effect": "PREDICTS"}], indirect=True)
def test_an_observed_predicts_forecast_is_recorded_and_promotes_nothing(db, tmp_path, fake):
    episode = _run(db, tmp_path, fake)
    assert _observed(db, episode) == ["DISCONTINUOUS"]
    relations = _connectivity_relations(db, episode)
    assert relations and all(r[2] == "DISCONTINUOUS" for r in relations), relations
    # Each relation is the declared effect, and the forecast was declared PREDICTS: nothing turned
    # it into support.
    assert all(kind == declared for kind, _, _, declared in relations), relations
    assert "PREDICTS" in {r[0] for r in relations}
    assert not _all(
        db,
        "SELECT 1 FROM relation_judgments WHERE project_id = %s AND relation_type = 'SUPPORTS'",
        PROJECT,
    )
    assert _supported(db, episode) == []
    assert "CONFIRMED" not in _outcome(db, episode)


def test_an_observed_supports_forecast_is_promoted_through_a_governed_decision(db, tmp_path, fake):
    episode = _run(db, tmp_path, fake)
    assert _observed(db, episode) == ["DISCONTINUOUS"]
    supports = [r for r in _connectivity_relations(db, episode) if r[0] == "SUPPORTS"]
    assert supports and all(r[3] == "SUPPORTS" for r in supports), supports
    promoted = _supported(db, episode)
    assert (supports[0][1], "ALLOW") in promoted, promoted
    moved = _all(
        db,
        "SELECT e.from_state, e.to_state, d.result FROM belief_revision_events e"
        " JOIN belief_transition_decisions d ON d.decision_id = e.authorization_decision_id"
        " WHERE e.target_id = %s AND e.to_state = 'SUPPORTED'",
        supports[0][1],
    )
    assert moved == [("ACTIVE", "SUPPORTED", "ALLOW")], moved
    assert _outcome(db, episode).startswith("COMPLETED:CONFIRMED")


@pytest.mark.parametrize("fake", [{"falsifiers_only": True}], indirect=True)
def test_falsifiers_alone_are_admitted_and_confirm_nothing(db, tmp_path, fake):
    episode = _run(db, tmp_path, fake)
    declared = _all(
        db,
        "SELECT DISTINCT e ->> 'relation_type' FROM predictions p"
        " JOIN hypotheses h ON h.hypothesis_id = p.hypothesis_id,"
        " jsonb_array_elements(p.relation_effect_if_observed) e WHERE h.created_in_episode = %s",
        episode,
    )
    assert declared == [("CONTRADICTS",)], declared
    kinds = {
        r[0]
        for r in _all(
            db, "SELECT relation_type FROM relation_judgments WHERE project_id = %s", PROJECT
        )
    }
    assert kinds <= {"CONTRADICTS"}, kinds
    assert _supported(db, episode) == []
    assert "CONFIRMED" not in _outcome(db, episode)
