"""`012c` against writers that do not go through the research service.

The service refuses a foreign, finished or busy episode before it writes anything
(`tests/e2e/test_research_continuation_postgres.py`). These tests write the rows directly, as a
buggy or hostile caller would, and show the database refusing every one of the shortcuts the
service's checks exist to prevent: another actor continuing an episode, a run on an episode that was
not resumed through `episode_resume`, a run on a finished episode, two live runs, a continuation
over a different hypothesis set, a second hypothesis set under an episode that already reasons over
one, and rewriting or deleting the ledger.
"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.postgres

PROJECT = "prj:test"
OTHER = "prj:other"
OPENER = "act:test"
COLLEAGUE = "act:colleague"
EPISODE = "epi:ledger"
T0 = "2026-09-28T00:00:00Z"


def _set(db, set_id: str, episode_id: str = EPISODE, project_id: str = PROJECT) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO hypothesis_sets (set_id, project_id, episode_id, question, research_intent,"
        " stakes, root_cause, source_policy_id, source_policy_version,"
        " inverted_retrieval_required, created_at)"
        " VALUES (%s, %s, %s, 'why', 'DIAGNOSIS', 'NORMAL', TRUE, 'srcpol:diagnosis', '1.0.0',"
        " FALSE, %s)",
        (set_id, project_id, episode_id, T0),
    )


def _run(  # type: ignore[no-untyped-def]
    db,
    run_id: str,
    ordinal: int,
    *,
    actor: str = OPENER,
    set_id: str | None = None,
    episode_id: str = EPISODE,
    project_id: str = PROJECT,
) -> None:
    db.execute(
        "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id, ordinal,"
        " hypothesis_set_id, started_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (run_id, episode_id, project_id, actor, ordinal, set_id, T0),
    )


def _finish(db, run_id: str, outcome: str = "SUSPENDED:PROVISIONAL") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "UPDATE research_runs SET finished_at = %s, outcome = %s WHERE research_run_id = %s",
        (T0, outcome, run_id),
    )


@pytest.fixture
def ledger(db):  # type: ignore[no-untyped-def]
    """An episode gathering evidence, opened by OPENER's run 1 over hypothesis set `hst:one`."""
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'Colleague')",
        (COLLEAGUE,),
    )
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'Other')", (OTHER,))
    db.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, state, start_time)"
        " VALUES (%s, %s, 'trc:ledger', 'why', 'EVIDENCE_GATHERING', %s)",
        (EPISODE, PROJECT, T0),
    )
    _run(db, "rrn:one", 1)
    _set(db, "hst:one")
    db.execute(
        "UPDATE research_runs SET hypothesis_set_id = 'hst:one' WHERE research_run_id = 'rrn:one'"
    )
    return db


def _refused(db, match: str, sql: str, *params: object) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.Error, match=match):
        db.execute(sql, params)


def test_only_the_opener_continues_an_episode(ledger):
    _finish(ledger, "rrn:one")
    with pytest.raises(psycopg.Error, match="only the actor who opened"):
        _run(ledger, "rrn:two", 2, actor=COLLEAGUE, set_id="hst:one")
    _run(ledger, "rrn:two", 2, set_id="hst:one")  # the opener may


def test_a_run_starts_only_on_an_episode_resumed_through_its_lifecycle(ledger):
    _finish(ledger, "rrn:one")
    ledger.execute("SELECT episode_suspend(%s, 'awaiting simulator', %s)", (EPISODE, T0))
    with pytest.raises(psycopg.Error, match="starts only on an episode gathering evidence"):
        _run(ledger, "rrn:two", 2, set_id="hst:one")
    ledger.execute("SELECT episode_resume(%s)", (EPISODE,))
    _run(ledger, "rrn:two", 2, set_id="hst:one")


def test_a_finished_episode_receives_no_run(ledger):
    _finish(ledger, "rrn:one", "COMPLETED:CONFIRMED")
    ledger.execute(
        "UPDATE research_episodes SET state = 'COMPLETED', outcome_status = 'CONFIRMED:h',"
        " end_time = %s WHERE episode_id = %s",
        (T0, EPISODE),
    )
    with pytest.raises(psycopg.Error, match="is COMPLETED"):
        _run(ledger, "rrn:two", 2, set_id="hst:one")


def test_one_live_run_per_episode(ledger):
    with pytest.raises(psycopg.errors.UniqueViolation, match="one_live_run_per_episode"):
        _run(ledger, "rrn:two", 2, set_id="hst:one")


def test_runs_are_numbered_in_order(ledger):
    _finish(ledger, "rrn:one")
    with pytest.raises(psycopg.Error, match="the next run of that episode is 2"):
        _run(ledger, "rrn:three", 3, set_id="hst:one")


def test_a_continuation_reasons_over_the_episodes_own_set(ledger):
    _finish(ledger, "rrn:one")
    with pytest.raises(psycopg.Error, match="own hypothesis set hst:one"):
        _run(ledger, "rrn:two", 2, set_id=None)


def test_no_second_hypothesis_set_under_an_episode_that_already_reasons_over_one(ledger):
    with pytest.raises(psycopg.Error, match="parallel reasoning history"):
        _set(ledger, "hst:two")
    # An episode no research run has recorded a set for is not affected (M3's own episodes).
    ledger.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, start_time)"
        " VALUES ('epi:m3', %s, 'trc:m3', 'why', %s)",
        (PROJECT, T0),
    )
    _set(ledger, "hst:m3-a", episode_id="epi:m3")
    _set(ledger, "hst:m3-b", episode_id="epi:m3")


def test_a_run_cannot_name_another_projects_episode(ledger):
    ledger.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, state, start_time)"
        " VALUES ('epi:foreign', %s, 'trc:f', 'why', 'EVIDENCE_GATHERING', %s)",
        (OTHER, T0),
    )
    with pytest.raises(psycopg.Error, match="does not span projects"):
        _run(ledger, "rrn:probe", 1, episode_id="epi:foreign", project_id=PROJECT)


def test_the_recorded_set_must_be_the_episodes_own(ledger):
    ledger.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, state, start_time)"
        " VALUES ('epi:second', %s, 'trc:s', 'why', 'EVIDENCE_GATHERING', %s)",
        (PROJECT, T0),
    )
    _run(ledger, "rrn:second", 1, episode_id="epi:second")
    with pytest.raises(psycopg.Error, match="is not a set of episode epi:second"):
        ledger.execute(
            "UPDATE research_runs SET hypothesis_set_id = 'hst:one'"
            " WHERE research_run_id = 'rrn:second'"
        )


def test_the_ledger_is_recorded_once_and_never_rewritten(ledger):
    _refused(
        ledger,
        "recorded once",
        "UPDATE research_runs SET hypothesis_set_id = NULL WHERE research_run_id = 'rrn:one'",
    )
    _refused(
        ledger,
        "identity is immutable",
        "UPDATE research_runs SET actor_id = %s WHERE research_run_id = 'rrn:one'",
        COLLEAGUE,
    )
    _finish(ledger, "rrn:one")
    _refused(
        ledger,
        "its record is final",
        "UPDATE research_runs SET outcome = 'COMPLETED:CONFIRMED' WHERE research_run_id = 'rrn:one'",
    )
    _refused(ledger, "append-only", "DELETE FROM research_runs WHERE research_run_id = 'rrn:one'")
