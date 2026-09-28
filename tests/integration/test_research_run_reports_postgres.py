"""`012d` against writers that do not go through the workspace.

A recorded report is what one finished research run returned. The database refuses a report for a
run that has not finished, was interrupted or failed; a report about another episode, project or
actor; a report whose conclusion is not the outcome the run recorded; a report that does not name
its run; and any edit or deletion.
"""

from __future__ import annotations

import json

import psycopg
import pytest

pytestmark = pytest.mark.postgres

PROJECT = "prj:test"
ACTOR = "act:test"
EPISODE = "epi:reports"
T0 = "2026-09-28T00:00:00Z"


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "episode_id": EPISODE,
        "project_id": PROJECT,
        "actor_id": ACTOR,
        "episode_state": "SUSPENDED",
        "conclusion": {"status": "PROVISIONAL", "statement": "not confirmed"},
        "provenance": ["Episode `epi:reports`; research run `rrn:one` (run 1 of this episode)."],
    }
    report.update(overrides)
    return report


def _record(db, report: dict[str, object], run_id: str = "rrn:one") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO research_run_reports (research_run_id, episode_id, project_id, report,"
        " recorded_at) VALUES (%s, %s, %s, %s::jsonb, %s)",
        (run_id, report["episode_id"], report["project_id"], json.dumps(report), T0),
    )


@pytest.fixture
def run(db):  # type: ignore[no-untyped-def]
    """Run 1 of an episode, live: opened and not yet finished."""
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other')")
    db.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, state, start_time)"
        " VALUES (%s, %s, 'trc:r', 'why', 'EVIDENCE_GATHERING', %s)",
        (EPISODE, PROJECT, T0),
    )
    db.execute(
        "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id, ordinal,"
        " started_at) VALUES ('rrn:one', %s, %s, %s, 1, %s)",
        (EPISODE, PROJECT, ACTOR, T0),
    )
    return db


def _finish(db, outcome: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "UPDATE research_runs SET finished_at = %s, outcome = %s WHERE research_run_id = 'rrn:one'",
        (T0, outcome),
    )


def test_a_finished_runs_own_report_is_recorded_once_and_never_edited(run):
    _finish(run, "SUSPENDED:PROVISIONAL")
    _record(run, _report())
    with pytest.raises(psycopg.errors.UniqueViolation):
        _record(run, _report())
    with pytest.raises(psycopg.Error, match="append-only"):
        run.execute("UPDATE research_run_reports SET report = '{}'::jsonb")
    with pytest.raises(psycopg.Error, match="append-only"):
        run.execute("DELETE FROM research_run_reports")


@pytest.mark.parametrize("outcome", [None, "INTERRUPTED", "FAILED:RuntimeError"])
def test_a_run_that_returned_no_report_has_none_recorded(run, outcome):
    if outcome is not None:
        _finish(run, outcome)
    with pytest.raises(psycopg.Error, match="did not return a report"):
        _record(run, _report())


def test_the_report_must_be_about_its_runs_episode_project_and_actor(run):
    _finish(run, "SUSPENDED:PROVISIONAL")
    with pytest.raises(psycopg.Error, match="names episode"):
        _record(run, _report(project_id="prj:other"))
    with pytest.raises(psycopg.Error, match="not about its episode, project and actor"):
        run.execute(
            "INSERT INTO research_run_reports (research_run_id, episode_id, project_id, report,"
            " recorded_at) VALUES ('rrn:one', %s, %s, %s::jsonb, %s)",
            (EPISODE, PROJECT, json.dumps(_report(actor_id="act:someone-else")), T0),
        )


def test_the_report_must_conclude_what_the_run_recorded_and_name_the_run(run):
    _finish(run, "SUSPENDED:PROVISIONAL")
    with pytest.raises(psycopg.Error, match="concludes COMPLETED:CONFIRMED"):
        _record(run, _report(episode_state="COMPLETED", conclusion={"status": "CONFIRMED"}))
    with pytest.raises(psycopg.Error, match="does not name that run"):
        _record(run, _report(provenance=["Episode `epi:reports`; research run `rrn:two`."]))
