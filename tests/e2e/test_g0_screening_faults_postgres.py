"""Fault injection for exploratory screening: interrupted checks, half-written evidence, refusals.

Each test breaks one thing on the open-via device, through the web workspace, on a fresh database,
and shows the record stays whole and the stage fails closed:

    evidence persistence   the screening record cannot be written after the reading's Observation
                           and Attestation were: the unit rolls back -- no Observation or
                           Attestation the screening record does not account for -- the stage is
                           recorded FAILED, nothing is conditioned, nothing is confirmed
    interrupted check      the reader raises mid-check: its Job is closed FAILED
                           (SCREENING_INTERRUPTED), nothing it might have read is admitted, the
                           checks after it are NOT_RUN
    dead run               a screening Job left RUNNING by a process that died is closed FAILED by
                           the next continuation, which never resumes it
    pre-execution refusal  a check whose estimate turns paid is REFUSED before any Job exists
    in-flight refusal      a workflow that calls a tool it never declared is REFUSED before the call
                           is dispatched
    SQL                    an EXECUTED screening record whose Observations do not exist is refused
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.screening import SqlScreeningStore
from lab_brain.domains.silicon_photonics import diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.vertical_tools import DesignWorkflow
from lab_brain.research.report_store import SqlResearchReportStore
from lab_brain.verification import screening as screening_module
from lab_brain.verification.capability_registry import CapabilityRegistry
from lab_brain.verification.screening import SCREENING_KEY_PREFIX
from tests.e2e.test_g0_exploratory_screening_postgres import (
    SCREENING,
    device,
    research,
    rows,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _token
from tests.fake_llm_provider import FakeProvider
from tests.g0_standin import StandIn

pytestmark = pytest.mark.postgres


@pytest.fixture
def standin() -> Iterator[tuple[FakeProvider, StandIn]]:
    model = StandIn()
    provider = FakeProvider(api_key=KEY, rewrite=model.rewrite).start()
    yield provider, model
    provider.stop()


def _browser(db: Any, tmp_path: Any, fake: Any) -> Any:
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60, research_features=SCREENING)
    _activated(db, browser, fake)
    return browser


def _screening_evidence(db: Any, episode: str) -> int:
    """Observations admitted from screening Runs of this episode."""
    ((n,),) = rows(
        db,
        "SELECT count(*) FROM observations o JOIN runs u ON u.run_id = o.run_id"
        " JOIN jobs j ON j.job_id = u.job_id WHERE j.episode_id = %s"
        " AND j.idempotency_key LIKE 'scr:%%'",
        episode,
    )
    return int(n)


def _statuses(db: Any, episode: str) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in rows(
            db,
            "SELECT capability_id, status FROM screening_observations WHERE episode_id = %s",
            episode,
        )
    }


def _stage(db: Any, episode: str) -> tuple[str, str]:
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=episode)
    (stage,) = [s for s in recorded.report.stages if s.stage == "screening"]
    return stage.status, stage.detail


def test_a_screening_record_that_cannot_be_written_leaves_no_orphan_evidence(
    db, tmp_path, standin, monkeypatch
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    original = SqlScreeningStore.add_observation

    def failing(self: SqlScreeningStore, observation: Any) -> Any:
        if observation.status.value == "EXECUTED":
            raise RuntimeError("injected: the screening record could not be written")
        return original(self, observation)

    monkeypatch.setattr(SqlScreeningStore, "add_observation", failing)
    episode = research(browser, device("contact-open-via"))
    # The reading ran (its Run is the execution record) but its evidence rolled back with it.
    assert rows(
        db,
        "SELECT 1 FROM runs u JOIN jobs j ON j.job_id = u.job_id WHERE j.episode_id = %s"
        " AND j.idempotency_key LIKE 'scr:%%'",
        episode,
    )
    assert _screening_evidence(db, episode) == 0
    assert not rows(
        db,
        "SELECT 1 FROM screening_observations WHERE episode_id = %s AND status = 'EXECUTED'",
        episode,
    )
    assert not rows(db, "SELECT 1 FROM screening_conditioned_hypotheses")
    status, detail = _stage(db, episode)
    assert status == "FAILED" and "injected" in detail
    ((outcome,),) = rows(
        db,
        "SELECT coalesce(outcome_status, '') FROM research_episodes WHERE episode_id = %s",
        episode,
    )
    assert "CONFIRMED" not in outcome


def test_an_interrupted_check_closes_its_job_admits_nothing_and_stops_the_stage(
    db, tmp_path, standin, monkeypatch
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)

    def crash(self: Any, request: Any) -> Any:
        raise RuntimeError("injected: the reader process died")

    # The first selected check (extraction consistency) crashes; the connectivity one after it.
    monkeypatch.setattr(diagnosis.NormalizationBasisReader, "execute", crash)
    episode = research(browser, device("contact-open-via"))
    assert _statuses(db, episode) == {
        sp.CAP_EXTRACTION_CONSISTENCY: "FAILED",
        sp.CAP_INSPECT_CONNECTIVITY: "NOT_RUN",
    }
    ((state, error),) = rows(
        db,
        "SELECT state, structured_error ->> 'code' FROM jobs WHERE episode_id = %s"
        " AND capability_id = %s AND idempotency_key LIKE 'scr:%%'",
        episode,
        sp.CAP_EXTRACTION_CONSISTENCY,
    )
    assert state == "FAILED", (state, error)
    assert _screening_evidence(db, episode) == 0
    assert not rows(db, "SELECT 1 FROM screening_conditioned_hypotheses")


def test_a_screening_job_a_dead_run_left_open_is_closed_by_the_continuation(db, tmp_path, standin):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    episode = research(browser, device("contact-open-via"))
    ((trace,),) = rows(db, "SELECT trace_id FROM research_episodes WHERE episode_id = %s", episode)
    # A process that died mid-check: its Job submitted and RUNNING, never completed.
    jobs = SqlJobStore(db)
    now = dt.datetime.now(dt.UTC)
    stale = jobs.submit(
        Job(
            job_id="job:stale-screening",
            project_id=PROJECT,
            episode_id=episode,
            capability_id=sp.CAP_INSPECT_CONNECTIVITY,
            trace_id=trace,
            idempotency_key=f"{SCREENING_KEY_PREFIX}{episode}:stale",
            submitted_at=now,
        )
    )
    jobs.transition(stale.job_id, JobState.RUNNING, now)
    continued = browser.post(
        f"/episodes/{episode}/continue", {"csrf": _token(browser.get(f"/episodes/{episode}"))}
    )
    assert continued.status == 303, _text(continued)[:600]
    ((state, code),) = rows(
        db, "SELECT state, structured_error ->> 'code' FROM jobs WHERE job_id = %s", stale.job_id
    )
    assert (state, code) == ("FAILED", "SCREENING_INTERRUPTED")
    reports = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=episode)
    assert any("left open by an interrupted run" in n for n in reports[-1].report.notes)
    # Nothing was resumed or read again.
    assert not rows(db, "SELECT 1 FROM runs WHERE job_id = %s", stale.job_id)


def test_a_check_whose_estimate_turns_paid_is_refused_before_any_job(
    db, tmp_path, standin, monkeypatch
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    original = screening_module.preflight

    class _Paid:
        """The registry as the check is about to run: the connectivity reading now costs money."""

        def __init__(self, inner: CapabilityRegistry) -> None:
            self._inner = inner

        def get(self, capability_id: str) -> Any:
            return self._inner.get(capability_id)

        def estimate(self, capability_id: str, params: Any) -> CostVector:
            cost = self._inner.estimate(capability_id, params)
            if capability_id == sp.CAP_INSPECT_CONNECTIVITY:
                return cost.model_copy(update={"money_estimate": Decimal("5")})
            return cost

    def at_execution(**kwargs: Any) -> list[str]:
        return original(**{**kwargs, "capabilities": _Paid(kwargs["capabilities"])})

    monkeypatch.setattr(screening_module, "preflight", at_execution)
    episode = research(browser, device("contact-open-via"))
    statuses = _statuses(db, episode)
    assert statuses[sp.CAP_INSPECT_CONNECTIVITY] == "REFUSED", statuses
    ((detail,),) = rows(
        db,
        "SELECT detail FROM screening_observations WHERE episode_id = %s AND capability_id = %s",
        episode,
        sp.CAP_INSPECT_CONNECTIVITY,
    )
    assert "refused before execution" in detail and "cost money" in detail
    assert not rows(
        db,
        "SELECT 1 FROM jobs WHERE episode_id = %s AND capability_id = %s",
        episode,
        sp.CAP_INSPECT_CONNECTIVITY,
    ), "no Job was submitted for the refused check"


def test_a_tool_call_the_workflow_never_declared_is_refused_before_it_is_dispatched(
    db, tmp_path, standin, monkeypatch
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    # The workflow passes preflight with its declared tool, then calls another one first.
    original = DesignWorkflow.execute

    def rogue(self: DesignWorkflow, context: Any) -> Any:
        context.dispatch("DOM-SP-TOOL-999", None)
        return original(self, context)

    monkeypatch.setattr(DesignWorkflow, "execute", rogue)
    episode = research(browser, device("contact-open-via"))
    statuses = _statuses(db, episode)
    assert set(statuses.values()) <= {"REFUSED", "NOT_RUN"} and "REFUSED" in statuses.values()
    assert _screening_evidence(db, episode) == 0
    assert not rows(
        db,
        "SELECT 1 FROM runs u JOIN jobs j ON j.job_id = u.job_id WHERE j.episode_id = %s"
        " AND j.idempotency_key LIKE 'scr:%%'",
        episode,
    ), "nothing was dispatched, so no Run exists"
    assert not rows(
        db,
        "SELECT 1 FROM jobs WHERE episode_id = %s AND idempotency_key LIKE 'scr:%%'"
        " AND state <> 'FAILED'",
        episode,
    )


def test_sql_refuses_an_executed_screening_record_without_its_evidence(db, tmp_path, standin):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    episode = research(browser, device("contact-open-via"))
    ((plan_id, run_id),) = rows(
        db,
        "SELECT s.plan_id, s.run_id FROM screening_observations s WHERE s.episode_id = %s"
        " AND s.capability_id = %s",
        episode,
        sp.CAP_INSPECT_CONNECTIVITY,
    )
    with (
        pytest.raises(psycopg.errors.RaiseException, match="every reading must be an Observation"),
        db.transaction(force_rollback=True),
    ):
        db.execute(
            "INSERT INTO screening_observations (screening_observation_id, plan_id, project_id,"
            " episode_id, rank, capability_id, status, run_id, observation_ids, estimated_cost,"
            " evidence_line, recorded_at) VALUES ('sob:no-evidence', %s, %s, %s, 7, %s,"
            " 'EXECUTED', %s, ARRAY['obs:missing'], '{}'::jsonb, 'line', now())",
            (plan_id, PROJECT, episode, sp.CAP_INSPECT_CONNECTIVITY, run_id),
        )
