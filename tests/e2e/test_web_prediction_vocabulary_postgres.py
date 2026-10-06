"""From a model's prediction to the check that reads it, through the web workspace, on PostgreSQL.

A prediction's observable is a canonical identifier the verification planner matches exactly. With
a model route applied (the stand-in, whose research answers come from the pack's catalog through the
real role contracts and parsers) and a device project as the verification input, the predictions the
engine's parser admitted name observables the pack's capabilities produce -- so the local,
deterministic contact-connectivity check is planned and REALLY runs as a Job with a Run and an
output artifact, its Observation is admitted as evidence traceable to that Run, and belief moves
only through governed transitions, each with its ALLOW decision.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lab_brain.domains.silicon_photonics.vertical import prediction_bindings
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _research
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres

CHECK = "cap:sp.inspect_contact_connectivity"
SIMULATIONS = ["cap:sp.mesh_sensitivity", "cap:sp.charge_dc_sweep", "cap:sp.charge_ac_sweep"]


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _all(db, sql: str, *args: object) -> list[tuple]:  # type: ignore[no-untyped-def]
    return list(db.execute(sql, args).fetchall())


def test_an_admitted_prediction_plans_and_runs_the_check_that_reads_it(db, tmp_path, fake):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    sent = _research(browser, tmp_path, case="contact-open-via")
    assert sent.status == 303, _text(sent)[:500]
    episode = _all(db, "SELECT episode_id FROM research_episodes WHERE project_id = %s", PROJECT)[
        0
    ][0]

    # Every typed prediction is a declared binding, as the model was asked to copy it.
    declared = {(o, s, v) for o, s, v in prediction_bindings()}
    predictions = _all(
        db,
        "SELECT p.observable_ref, p.outcome_space_id, p.outcome_space_version"
        " FROM predictions p JOIN hypotheses h USING (hypothesis_id)"
        " WHERE h.created_in_episode = %s",
        episode,
    )
    assert predictions and set(predictions) <= declared
    models = {r[0] for r in _all(db, "SELECT DISTINCT model_id FROM inference_provenance")}
    assert models <= {"fake-reasoner", "fake-critic"}, "the hypotheses came through a model route"

    # The contact-connectivity check was planned and really ran: a Job, a Run, an output artifact.
    runs = _all(
        db,
        "SELECT j.job_id, j.state, r.run_id, r.status, r.output_artifacts FROM jobs j"
        " JOIN runs r ON r.job_id = j.job_id WHERE j.episode_id = %s AND j.capability_id = %s",
        episode,
        CHECK,
    )
    assert runs and runs[0][1] == "SUCCEEDED" and runs[0][3] == "SUCCEEDED"
    run_id, outputs = runs[0][2], runs[0][4]
    assert outputs
    plans = _all(
        db, "SELECT candidate_action_ids FROM verification_plans WHERE episode_id = %s", episode
    )
    assert any(CHECK in p[0] for p in plans)
    assert not _all(
        db,
        "SELECT 1 FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
        PROJECT,
        SIMULATIONS,
    ), "no simulation was run or emulated"

    # Its outcome is evidence traceable to that Run, and belief moved only by governed decisions.
    observations = _all(db, "SELECT observation_id FROM observations WHERE run_id = %s", run_id)
    assert observations
    attested = _all(db, "SELECT attestation_id FROM attestations WHERE run_id = %s", run_id)
    assert attested
    judgments = _all(
        db,
        "SELECT relation_id FROM relation_judgments WHERE supporting_attestation_ids && %s::text[]",
        [a[0] for a in attested],
    )
    assert judgments
    moves = _all(
        db,
        "SELECT e.to_state, d.result FROM belief_revision_events e LEFT JOIN"
        " belief_transition_decisions d ON d.decision_id = e.authorization_decision_id"
        " WHERE e.project_id = %s AND e.from_state IS NOT NULL",
        PROJECT,
    )
    assert moves and all(result == "ALLOW" for _, result in moves)
