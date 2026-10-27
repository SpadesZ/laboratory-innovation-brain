"""The live failure, replayed with exploratory screening: rivals that miss the open via, a coverage
review that declines, and a governed look where nobody was looking.

A stand-in Hypothesis Engine (`tests.g0_standin`) answers as the recorded Gemini runs did -- five
rivals cued by the report's words, none about contact connectivity, and every coverage gap declined
because "the evidence does not point there". Through the web workspace, on a fresh database:

    the look        screening reads exactly the observables no rival predicts, under
                    `screening:research-run@1.0.0`, as Jobs and Runs, and keeps every reading --
                    normal ones included -- as an Observation and an Attestation
    the new cycle   an ABNORMAL reading (the open via's DISCONTINUOUS) prompts one review; the rival
                    it adds is recorded as conditioned on that reading
    no shortcut     that reading supports nothing: no SUPPORTS relation to the post-screening rival,
                    the same inspection is never run again by verification, the belief does not
                    move and the episode is not CONFIRMED -- and SQL refuses the shortcut for any
                    writer (`012y`): the screened observation, an older observation, a deterministic
                    repeat; a prospective, different reading is still allowed
    no leak         the plan is the same for every device; the stand-in was shown no case id,
                    label or answer
    sound device    both readings NORMAL: no review, no new rival, both readings kept
    two faults      both readings ABNORMAL: two rivals, each conditioned on its own reading
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.core.models.job import Job, JobState
from lab_brain.core.models.observation import Observation
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.research.report_store import SqlResearchReportStore
from lab_brain.research.service import ResearchFeatures
from tests.e2e.test_research_episode_postgres import GOAL, PROJECT, REPORT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _token
from tests.fake_llm_provider import FakeProvider
from tests.g0_standin import StandIn
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "fixtures/vertical/sp_rs_root_cause_benchmark.json").read_text(encoding="utf-8")
)
SIMULATIONS = [sp.CAP_MESH_SENSITIVITY, sp.CAP_CHARGE_DC, "cap:sp.charge_ac_sweep"]


def device(case_id: str, **override: str) -> bytes:
    """The device file the user uploads: the case's device, nothing else from the fixture."""
    case = next(c for c in FIXTURE["cases"] if c["case_id"] == case_id)
    return json.dumps({**FIXTURE["nominal_device"], **case["device"], **override}).encode()


@pytest.fixture
def standin() -> Iterator[tuple[FakeProvider, StandIn]]:
    model = StandIn()
    provider = FakeProvider(api_key=KEY, rewrite=model.rewrite).start()
    yield provider, model
    provider.stop()


def research(browser: Browser, data: bytes) -> str:
    """One research run through the workspace; returns the episode it opened."""
    sent = browser.post(
        "/runs",
        {
            "csrf": _token(browser.get("/runs/new")),
            "project": PROJECT,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": [(REPORT.name, REPORT.read_bytes())],
            "verification_input": [("device.json", data)],
        },
    )
    assert sent.status == 303, _text(sent)[:800]
    found = re.search(r"/episodes/([^?#]+)", sent.location)
    assert found
    return unquote(found.group(1))


def rows(db: Any, sql: str, *args: object) -> list[tuple[Any, ...]]:
    return list(db.execute(sql, args).fetchall())


def readings(db: Any, episode: str) -> dict[str, str]:
    return {
        str(r["observable_ref"]): f"{r['outcome']}:{r['finding']}"
        for (payload,) in rows(
            db, "SELECT readings FROM screening_observations WHERE episode_id = %s", episode
        )
        for r in payload
    }


def test_screening_finds_the_open_via_nobody_predicted_and_supports_nothing(db, tmp_path, standin):
    fake, model = standin
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    open_via = research(browser, device("contact-open-via"))

    # The look: the two screenable observables no rival predicts, in the policy's order.
    ((plan_id, policy, unaddressed, selected),) = rows(
        db,
        "SELECT plan_id, policy_id || '@' || policy_version, unaddressed_observables,"
        " selected_capability_ids FROM screening_plans WHERE episode_id = %s",
        open_via,
    )
    assert policy == "screening:research-run@1.0.0"
    # Whatever else nobody predicts (a simulation's observable, say) is not screenable here.
    assert {sp.OBS_CONNECTIVITY, sp.OBS_NORMALIZATION} <= set(unaddressed)
    assert selected == [sp.CAP_EXTRACTION_CONSISTENCY, sp.CAP_INSPECT_CONNECTIVITY]
    assert readings(db, open_via) == {
        sp.OBS_CONNECTIVITY: "DISCONTINUOUS:ABNORMAL",
        sp.OBS_NORMALIZATION: "AGREES:NORMAL",
    }
    # Each reading is a Job, a Run and an admitted Observation + Attestation -- the normal one too.
    for observable in (sp.OBS_CONNECTIVITY, sp.OBS_NORMALIZATION):
        ((jobs,),) = rows(
            db,
            "SELECT count(*) FROM jobs j JOIN runs u ON u.job_id = j.job_id"
            " JOIN observations o ON o.run_id = u.run_id"
            " JOIN attestations a ON a.observation_id = o.observation_id"
            " WHERE j.episode_id = %s AND o.metric_or_event = %s"
            " AND j.idempotency_key LIKE 'scr:%%'",
            open_via,
            observable,
        )
        assert jobs == 1, observable
    # ... and none of them relates to anything.
    assert not rows(
        db,
        "SELECT 1 FROM relation_judgments r JOIN observations o ON o.observation_id ="
        " r.from_entity_id JOIN runs u ON u.run_id = o.run_id JOIN jobs j ON j.job_id = u.job_id"
        " WHERE j.idempotency_key LIKE 'scr:%%'",
    )

    # The new cycle: one rival, conditioned on the abnormal reading it accounts for.
    ((hypothesis, conditioned_on, inference),) = rows(
        db,
        "SELECT c.hypothesis_id, c.screening_observation_ids, c.inference_id"
        " FROM screening_conditioned_hypotheses c WHERE c.episode_id = %s",
        open_via,
    )
    ((mechanism,),) = rows(
        db, "SELECT mechanism FROM hypotheses WHERE hypothesis_id = %s", hypothesis
    )
    assert "after screening" in mechanism
    ((check,),) = rows(
        db,
        "SELECT capability_id FROM screening_observations WHERE screening_observation_id = %s",
        conditioned_on[0],
    )
    assert check == sp.CAP_INSPECT_CONNECTIVITY

    # No shortcut: nothing supports it, verification did not read the via again, nothing moved.
    assert not rows(
        db,
        "SELECT 1 FROM relation_judgments WHERE to_entity_id = %s AND relation_type = 'SUPPORTS'",
        hypothesis,
    )
    assert not rows(
        db,
        "SELECT 1 FROM jobs WHERE episode_id = %s AND capability_id = %s"
        " AND idempotency_key NOT LIKE 'scr:%%'",
        open_via,
        sp.CAP_INSPECT_CONNECTIVITY,
    ), "the screened inspection is never repeated on the same input"
    assert not rows(
        db,
        "SELECT 1 FROM belief_revision_events WHERE target_id = %s AND to_state <> 'ACTIVE'",
        hypothesis,
    )
    ((outcome,),) = rows(
        db,
        "SELECT coalesce(outcome_status, '') FROM research_episodes WHERE episode_id = %s",
        open_via,
    )
    assert "CONFIRMED" not in outcome
    assert not rows(
        db,
        "SELECT 1 FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
        PROJECT,
        SIMULATIONS,
    )

    # The report says all of it, in its own section, and marks the rival's provenance.
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=open_via)
    report = recorded.report
    assert report.screening is not None and report.screening.plan_id == plan_id
    assert report.screening.review_status == "DONE"
    assert [line.disposition for line in report.screening.review] == ["CERTIFIED"]
    assert report.screening.not_repeated == (sp.CAP_INSPECT_CONNECTIVITY,) or (
        sp.CAP_INSPECT_CONNECTIVITY in report.screening.not_repeated
    )
    origins = {h.hypothesis_id: h.origin for h in report.hypotheses}
    assert origins[hypothesis] == "POST_SCREENING"
    assert sum(o == "POST_SCREENING" for o in origins.values()) == 1
    assert report.conclusion.status != "CONFIRMED"
    assert "cannot support it" in report.conclusion.statement
    (stage,) = [s for s in report.stages if s.stage == "screening"]
    assert stage.status == "DONE" and "1 abnormal" in stage.detail
    # The review call was a recorded inference that saw the readings by alias.
    ((parameters,),) = rows(
        db, "SELECT parameters FROM inference_provenance WHERE inference_id = %s", inference
    )
    assert any(v in json.dumps(parameters) for v in ("O1", "O2"))

    # The page says it in Traditional Chinese, with the English term beside it, and names no
    # raw identifier for the checks or outcomes.
    browser.post("/locale", {"csrf": _token(browser.get("/")), "locale": "zh-TW", "next": "/"})
    page = _text(browser.get(f"/episodes/{open_via}").text)
    for said in (
        "探索性篩檢（exploratory screening）",
        "接點連通性檢查（connectivity inspection）：讀到 接點連通性（contact connectivity） = "
        "不連續（discontinuous）",
        "——異常",
        "該讀取不能作為它的支持",
        "篩檢後提出",
        "重複同一個讀取不是獨立的證據",
    ):
        assert said in page, said

    # SQL refuses the shortcut for any writer (012y).
    _sql_guard_refuses_post_hoc_support(db, open_via, hypothesis, conditioned_on[0])

    # No leak: the stand-in saw no case id, no fixture note, no label.
    shown = json.dumps(model.reads)
    for forbidden in ("contact-open-via", "truth", "cathode via never drawn", '"expected"'):
        assert forbidden not in shown, forbidden


def _sql_guard_refuses_post_hoc_support(
    db: Any, episode: str, hypothesis: str, screening_observation: str
) -> None:
    ((run_id, observation_ids),) = rows(
        db,
        "SELECT run_id, observation_ids FROM screening_observations"
        " WHERE screening_observation_id = %s",
        screening_observation,
    )
    ((attestation,),) = rows(
        db, "SELECT attestation_id FROM attestations WHERE observation_id = %s", observation_ids[0]
    )
    jobs = SqlJobStore(db)
    screened = jobs.get_run(run_id)
    assert screened is not None
    later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    earlier = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)

    def run_like(name: str, parameters: dict[str, str]) -> str:
        job = jobs.submit(
            Job(
                job_id=f"job:guard-{name}",
                project_id=PROJECT,
                episode_id=episode,
                capability_id=screened.capability_id,
                trace_id=screened.trace_id,
                idempotency_key=f"guard:{name}",
                submitted_at=later,
            )
        )
        jobs.transition(job.job_id, JobState.RUNNING, later)
        run = jobs.complete(
            job.job_id,
            job.idempotency_key,
            screened.model_copy(
                update={
                    "run_id": f"run:guard-{name}",
                    "job_id": job.job_id,
                    "input_parameters": parameters,
                    "start_time": later,
                    "end_time": later,
                }
            ),
        )
        return run.run_id

    def observe(run: str, name: str, at: dt.datetime) -> str:
        observation = Observation(
            observation_id=f"obs:guard-{name}",
            run_id=run,
            metric_or_event=sp.OBS_CONNECTIVITY,
            value="DISCONTINUOUS",
            conditions=dict(screened.conditions),
            conditions_schema_version=screened.conditions_schema_version,
            method_ref="sp.rule.contact_connectivity@1.0.0",
            project_id=PROJECT,
            created_at=at,
        )
        db.execute(
            "INSERT INTO observations (observation_id, run_id, metric_or_event, value_text,"
            " conditions, conditions_schema_version, method_ref, project_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)",
            (
                observation.observation_id,
                run,
                observation.metric_or_event,
                observation.value,
                json.dumps(observation.conditions),
                observation.conditions_schema_version,
                observation.method_ref,
                PROJECT,
                at,
            ),
        )
        return observation.observation_id

    def relate(source: str) -> None:
        db.execute(
            "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
            " relation_type, supporting_attestation_ids, project_id)"
            " VALUES (%s, %s, %s, 'SUPPORTS', %s, %s)",
            (f"rel:guard-{source}", source, hypothesis, [attestation], PROJECT),
        )

    def refused(source: str, why: str) -> None:
        with (
            pytest.raises(psycopg.errors.RaiseException, match=why),
            db.transaction(force_rollback=True),
        ):
            relate(source)

    with db.transaction(force_rollback=True):
        repeat = run_like("repeat", dict(screened.input_parameters))
        different = run_like("different", {"variant": "independent reading"})
        # (a) the screened observation itself
        refused(observation_ids[0], "cannot SUPPORT it")
        # (b) an observation older than the hypothesis
        refused(observe(different, "older", earlier), "predates hypothesis")
        # (c) a deterministic repeat of the screened reading, recorded later
        refused(observe(repeat, "repeat", later), "repeats the screened reading")
        # ... and a prospective, different reading may relate: the guard does not freeze it.
        with db.transaction(force_rollback=True):
            relate(observe(different, "prospective", later))


def test_a_sound_device_reads_normal_and_keeps_every_reading(db, tmp_path, standin):
    fake, model = standin
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    sound = research(browser, device("probe-artifact"))
    assert readings(db, sound) == {
        sp.OBS_CONNECTIVITY: "CONTINUOUS:NORMAL",
        sp.OBS_NORMALIZATION: "AGREES:NORMAL",
    }
    assert not rows(db, "SELECT 1 FROM screening_conditioned_hypotheses")
    assert not [kind for kind, _ in model.reads if kind == "screening"], "no review was asked"
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=sound)
    assert recorded.report.screening is not None
    assert recorded.report.screening.review_status == "NOT_NEEDED"
    assert {c.status for c in recorded.report.screening.checks} == {"EXECUTED"}


def test_two_faults_two_readings_two_conditioned_rivals_and_the_same_plan(db, tmp_path, standin):
    fake, _model = standin
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    both = research(browser, device("contact-open-via", extraction_normalization_length_um="1000"))
    sound = research(browser, device("probe-artifact"))
    assert readings(db, both) == {
        sp.OBS_CONNECTIVITY: "DISCONTINUOUS:ABNORMAL",
        sp.OBS_NORMALIZATION: "DISAGREES:ABNORMAL",
    }
    conditioned = rows(
        db,
        "SELECT c.hypothesis_id, s.capability_id FROM screening_conditioned_hypotheses c"
        " JOIN screening_observations s ON s.screening_observation_id ="
        " c.screening_observation_ids[1] WHERE c.episode_id = %s ORDER BY 2",
        both,
    )
    assert [c[1] for c in conditioned] == [
        sp.CAP_EXTRACTION_CONSISTENCY,
        sp.CAP_INSPECT_CONNECTIVITY,
    ]
    # Same rivals, same deployment -> the same plan, whatever the device holds.
    plans = rows(
        db,
        "SELECT episode_id, unaddressed_observables, selected_capability_ids, candidates"
        " FROM screening_plans WHERE episode_id = ANY(%s)",
        [both, sound],
    )
    assert len(plans) == 2 and plans[0][1:] == plans[1][1:]


def test_screening_switched_off_takes_no_reading(db, tmp_path, standin):
    fake, _model = standin
    _setup(db)
    browser = _deployment(
        tmp_path,
        inference_deadline=60,
        research_features=ResearchFeatures(exploratory_screening=False),
    )
    _activated(db, browser, fake)
    episode = research(browser, device("contact-open-via"))
    assert not rows(db, "SELECT 1 FROM screening_plans")
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=episode)
    (stage,) = [s for s in recorded.report.stages if s.stage == "screening"]
    assert stage.status == "SKIPPED"
    # The baseline the live runs had: the via was never read.
    assert not rows(
        db,
        "SELECT 1 FROM jobs WHERE episode_id = %s AND capability_id = %s",
        episode,
        sp.CAP_INSPECT_CONNECTIVITY,
    )
