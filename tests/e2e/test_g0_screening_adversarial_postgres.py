"""Adversarial screening: what changes or lies between selection and execution is refused.

Each case runs the open-via device through the web workspace on a fresh database and breaks one
promise the screening stage relies on. The plan was made honestly; the world changes before the
check runs, or a component misdescribes itself:

    capability drift       between selection and execution the capability is unregistered, turns
                           licensed, privacy-bound or irreversible, starts needing a seat or a person,
                           loses its local declaration, or its input turns out to be another
                           project's: REFUSED before any Job exists
    false "local"          the pack declares a local reading but the Run records remote execution:
                           the reading is not admitted as evidence (the stage cannot un-send what a
                           lying backend sent -- see the report's residual risks)
    substituted tool       the workflow's declared tool is rebound to a licence seat after preflight
                           passed: REFUSED in flight, before the call is dispatched
    duplicate callback     a Job's completion delivered twice records one Run, and a second
                           screening record for the same check is refused by SQL
    lost conditioning      the hypothesis proposed after screening and its conditioning record are
                           one unit: if the record cannot be written, no unconditioned post-screening
                           hypothesis survives to escape the SUPPORTS guard
    revoked membership     once membership ends, the episode page, its report export and the
                           screening section are refused; another project's member never sees them
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.job import JobState
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.screening import SqlScreeningStore
from lab_brain.domains.silicon_photonics import diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.vertical_tools import DesignWorkflow
from lab_brain.verification import screening as screening_module
from tests.e2e.test_g0_exploratory_screening_postgres import (
    SCREENING,
    device,
    research,
    rows,
)
from tests.e2e.test_research_episode_postgres import ACTOR, PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.fake_llm_provider import FakeProvider
from tests.g0_standin import StandIn

pytestmark = pytest.mark.postgres

CHECK = sp.CAP_INSPECT_CONNECTIVITY


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


def _status_and_detail(db: Any, episode: str, capability_id: str = CHECK) -> tuple[str, str]:
    ((status, detail),) = rows(
        db,
        "SELECT status, detail FROM screening_observations WHERE episode_id = %s"
        " AND capability_id = %s",
        episode,
        capability_id,
    )
    return str(status), str(detail)


def _jobs_for(db: Any, episode: str, capability_id: str = CHECK) -> list[tuple[Any, ...]]:
    return rows(
        db,
        "SELECT job_id FROM jobs WHERE episode_id = %s AND capability_id = %s"
        " AND idempotency_key LIKE 'scr:%%'",
        episode,
        capability_id,
    )


def _evidence(db: Any, episode: str) -> int:
    ((n,),) = rows(
        db,
        "SELECT count(*) FROM observations o JOIN runs u ON u.run_id = o.run_id"
        " JOIN jobs j ON j.job_id = u.job_id WHERE j.episode_id = %s"
        " AND j.idempotency_key LIKE 'scr:%%' AND j.capability_id = %s",
        episode,
        CHECK,
    )
    return int(n)


# -- capability drift between selection and execution -------------------------------------------


class _Drifted:
    """The capability registry as the check is about to run, with one change to the screened check."""

    def __init__(self, inner: Any, *, fields: dict[str, Any], cost: dict[str, Any], gone: bool):
        self._inner, self._fields, self._cost, self._gone = inner, fields, cost, gone

    def get(self, capability_id: str) -> Any:
        found = self._inner.get(capability_id)
        if capability_id != CHECK or found is None:
            return found
        return None if self._gone else found.model_copy(update=self._fields)

    def estimate(self, capability_id: str, params: Any) -> CostVector:
        cost: CostVector = self._inner.estimate(capability_id, params)
        return cost.model_copy(update=self._cost) if capability_id == CHECK else cost


class _ReboundTools:
    def __init__(self, inner: Any, **override: Any) -> None:
        self._inner, self._override = inner, override

    def descriptor(self, tool_id: str) -> Any:
        return self._inner.descriptor(tool_id).model_copy(update=self._override)


def _norms_without_local(norms: Any) -> dict[str, Any]:
    return {
        k: (v.model_copy(update={"execution": "REMOTE"}) if k == CHECK else v)
        for k, v in norms.items()
    }


DRIFT: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], str]] = {
    "unregistered": (
        lambda kw: {"capabilities": _Drifted(kw["capabilities"], fields={}, cost={}, gone=True)},
        "no longer registered",
    ),
    "licensed": (
        lambda kw: {
            "capabilities": _Drifted(
                kw["capabilities"],
                fields={"license_constraints": ("vendor-eula",)},
                cost={},
                gone=False,
            )
        },
        "licence constraints",
    ),
    "privacy_bound": (
        lambda kw: {
            "capabilities": _Drifted(
                kw["capabilities"],
                fields={"privacy_constraints": ("export-controlled",)},
                cost={},
                gone=False,
            )
        },
        "privacy constraints",
    ),
    "irreversible": (
        lambda kw: {
            "capabilities": _Drifted(
                kw["capabilities"], fields={"irreversible": True}, cost={}, gone=False
            )
        },
        "irreversible",
    ),
    "needs_a_seat": (
        lambda kw: {
            "capabilities": _Drifted(
                kw["capabilities"], fields={}, cost={"license_seat_s": 30}, gone=False
            )
        },
        "licence seat",
    ),
    "needs_a_person": (
        lambda kw: {
            "capabilities": _Drifted(
                kw["capabilities"], fields={}, cost={"human_minutes": 15}, gone=False
            )
        },
        "a person",
    ),
    "declared_remote": (
        lambda kw: {"norms": _norms_without_local(kw["norms"])},
        "local reading that sends nothing out",
    ),
    "tool_bound_to_a_seat": (
        lambda kw: {"tools": _ReboundTools(kw["tools"], resource_id="license:sp-charge-seat")},
        "contends for resource",
    ),
    "tool_runs_another_capability": (
        lambda kw: {"tools": _ReboundTools(kw["tools"], capability_id=sp.CAP_CHARGE_DC)},
        "executes another capability",
    ),
    "cross_project_input": (
        lambda kw: {"in_project": lambda _artifact, _project: False},
        "is not this project's",
    ),
}


@pytest.mark.parametrize("change", sorted(DRIFT))
def test_a_check_that_drifted_after_selection_is_refused_before_any_job(
    db, tmp_path, standin, monkeypatch, change
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    original = screening_module.preflight
    make, why = DRIFT[change]

    def at_execution(**kwargs: Any) -> list[str]:
        if kwargs["capability_id"] != CHECK:
            return original(**kwargs)
        return original(**{**kwargs, **make(kwargs)})

    monkeypatch.setattr(screening_module, "preflight", at_execution)
    episode = research(browser, device("contact-open-via"))
    status, detail = _status_and_detail(db, episode)
    assert status == "REFUSED" and "refused before execution" in detail and why in detail, detail
    assert not _jobs_for(db, episode), "a refused check never becomes a Job"
    assert _evidence(db, episode) == 0
    assert not rows(db, "SELECT 1 FROM screening_conditioned_hypotheses")


# -- a backend that misdescribes itself ----------------------------------------------------------


def test_a_reading_the_run_records_as_remote_is_not_admitted(db, tmp_path, standin, monkeypatch):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    original = diagnosis.ContactConnectivityReader.execute

    def remote(self: Any, request: Any) -> Any:
        done = original(self, request)
        return done.model_copy(update={"environment": {"execution": "remote", "host": "elsewhere"}})

    monkeypatch.setattr(diagnosis.ContactConnectivityReader, "execute", remote)
    episode = research(browser, device("contact-open-via"))
    status, detail = _status_and_detail(db, episode)
    assert status == "FAILED" and "must be a local reading" in detail, detail
    assert _evidence(db, episode) == 0, "a remote reading is not screened evidence"
    assert not rows(db, "SELECT 1 FROM screening_conditioned_hypotheses")


def test_a_declared_tool_rebound_after_preflight_is_refused_in_flight(
    db, tmp_path, standin, monkeypatch
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    original = DesignWorkflow.execute

    def substituted(self: DesignWorkflow, context: Any) -> Any:
        # Preflight has passed. Now the declared tool's registration changes under the workflow.
        live = screening_module._tool_problems  # the in-flight guard reads the registry again

        def rebound(tool_id: str, capability_id: str, tools: Any) -> list[str]:
            return live(tool_id, capability_id, _ReboundTools(tools, resource_id="x"))

        monkeypatch.setattr(screening_module, "_tool_problems", rebound)
        return original(self, context)

    monkeypatch.setattr(DesignWorkflow, "execute", substituted)
    episode = research(browser, device("contact-open-via"))
    statuses = dict(
        rows(
            db,
            "SELECT capability_id, status FROM screening_observations WHERE episode_id = %s",
            episode,
        )
    )
    assert "REFUSED" in statuses.values(), statuses
    ((detail,),) = rows(
        db,
        "SELECT detail FROM screening_observations WHERE episode_id = %s AND status = 'REFUSED'",
        episode,
    )
    assert "contends for resource x" in detail, detail
    assert not rows(
        db,
        "SELECT 1 FROM runs u JOIN jobs j ON j.job_id = u.job_id WHERE j.episode_id = %s"
        " AND j.idempotency_key LIKE 'scr:%%'",
        episode,
    ), "nothing was dispatched"


# -- duplicate callbacks and retries ------------------------------------------------------------


def test_a_completion_delivered_twice_records_one_run_and_one_screening_record(
    db, tmp_path, standin
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    episode = research(browser, device("contact-open-via"))
    ((job_id,),) = _jobs_for(db, episode)
    jobs = SqlJobStore(db)
    job = jobs.get(job_id)
    assert job is not None and job.state is JobState.SUCCEEDED
    run = jobs.get_run(str(job.result_run_id))
    assert run is not None

    # The same completion again, as a retried callback would deliver it.
    again = jobs.complete(job_id, job.idempotency_key, run)
    assert again.run_id == run.run_id
    ((n,),) = rows(db, "SELECT count(*) FROM runs WHERE job_id = %s", job_id)
    assert n == 1

    # A second screening record of the same check in the same episode: refused by SQL.
    (recorded,) = [
        o
        for o in SqlScreeningStore(db).observations_for_episode(PROJECT, episode)
        if o.capability_id == CHECK
    ]
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        db.transaction(force_rollback=True),
    ):
        SqlScreeningStore(db).add_observation(
            # Another id and another rank, so only the one-reading-per-line rule can refuse it.
            recorded.model_copy(update={"screening_observation_id": "sob:duplicate", "rank": 99})
        )


# -- the hypothesis and its conditioning are one unit -------------------------------------------


def test_a_lost_conditioning_record_leaves_no_unconditioned_post_screening_hypothesis(
    db, tmp_path, standin, monkeypatch
):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)

    def failing(self: Any, record: Any) -> Any:
        raise RuntimeError("injected: the conditioning record could not be written")

    monkeypatch.setattr(SqlScreeningStore, "add_conditioned", failing)
    episode = research(browser, device("contact-open-via"))
    assert not rows(db, "SELECT 1 FROM screening_conditioned_hypotheses")
    # Every hypothesis of the episode that says it came after screening is gone with its record:
    # an unconditioned one would escape the SUPPORTS guard, which keys on the conditioning row.
    assert not rows(
        db,
        "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s"
        " AND mechanism ILIKE '%%after screening%%'",
        episode,
    )
    ((outcome,),) = rows(
        db,
        "SELECT coalesce(outcome_status, '') FROM research_episodes WHERE episode_id = %s",
        episode,
    )
    assert "CONFIRMED" not in outcome


# -- membership --------------------------------------------------------------------------------


def test_revoked_membership_loses_the_episode_its_report_and_its_screening(db, tmp_path, standin):
    fake, _model = standin
    browser = _browser(db, tmp_path, fake)
    episode = research(browser, device("contact-open-via"))
    page = f"/episodes/{episode}"
    export = f"/episodes/{episode}/runs/1/report.md"
    shown = browser.get(page)
    assert shown.status == 200 and "screening" in _text(shown).lower()
    assert browser.get(export).status == 200

    db.execute(
        "UPDATE project_memberships SET active = false WHERE actor_id = %s AND project_id = %s",
        (ACTOR, PROJECT),
    )
    for path in (page, export, f"/episodes/{episode}/runs/1/summary.html"):
        refused = browser.get(path)
        assert refused.status in (403, 404), (path, refused.status)
        body = _text(refused)
        # The refusal may echo the id that was asked for; it must show nothing recorded under it.
        for recorded in ("DISCONTINUOUS", "ABNORMAL", sp.OBS_CONNECTIVITY, "after screening"):
            assert recorded not in body, (path, recorded)
    # The record itself is untouched by the refusal.
    assert rows(db, "SELECT 1 FROM screening_observations WHERE episode_id = %s", episode)
