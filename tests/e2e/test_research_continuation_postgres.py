"""Continuing a research episode, adversarially, on PostgreSQL.

`research run --episode E` continues E; it never opens or reuses anything else. Driven through the
real entry point (`cli.main`) and, where a test needs a budget the CLI does not expose, through the
same `ResearchEpisodeService` the CLI calls. Every refusal is checked for its answer AND for the
database it leaves behind: a census of every table a research run writes, compared before and after.

    foreign ids       another project's episode, an unknown id, a colleague's episode and an
                      episode no research run opened all get one answer and write nothing
    suspended         the episode is resumed through `episode_resume` as itself: the same id, trace
                      and goal, the same hypothesis set and debate, no second debate, no check
                      executed twice, new plans appended, parked again on the missing simulator
    completed         a finished episode receives no new run, and nothing is written
    retry             a live run holds the episode; a run whose process died is recorded
                      INTERRUPTED and its RUNNING job FAILED; a job an earlier run parked behind a
                      budget is superseded rather than re-dispatched, and the continuation that has
                      the budget confirms the cause
"""

from __future__ import annotations

import io
from pathlib import Path

import psycopg
import pytest

from lab_brain.core.models.enums import TrustClass
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.episodes import SqlEpisodeStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.interfaces import cli
from lab_brain.research.continuation import (
    EpisodeFinished,
    ResearchRunRecord,
    SqlResearchRunStore,
)
from lab_brain.research.service import InputDocument, ResearchEpisodeService, ResearchRequest
from lab_brain.research.vertical import load_vertical_factory
from lab_brain.storage.artifacts.local import LocalArtifactStore
from tests.e2e.test_research_episode_postgres import ACTOR, GOAL, PROJECT, REPORT, _device, _member
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres

OTHER_PROJECT = "prj:other-lab"
MALLORY = "act:mallory"
COLLEAGUE = "act:colleague"

#: Every table a research run writes to, directly or through the services it composes.
CENSUS = (
    "research_episodes",
    "research_runs",
    "jobs",
    "runs",
    "artifacts",
    "ingestion_items",
    "evidence_units",
    "attestations",
    "claims",
    "relation_judgments",
    "hypothesis_sets",
    "hypotheses",
    "positions",
    "critique_reports",
    "debate_records",
    "evidence_bundles",
    "inference_provenance",
    "belief_revision_events",
    "belief_transition_decisions",
    "verification_plans",
    "failure_analyses",
    "execution_spans",
    "cost_entries",
    "external_snapshots",
)


def _census(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in CENSUS}


def _episode_row(db, episode_id: str) -> tuple[object, ...]:  # type: ignore[no-untyped-def]
    row = db.execute(
        "SELECT project_id, trace_id, goal, state, outcome_status, start_time, end_time,"
        " suspended_at, suspend_reason FROM research_episodes WHERE episode_id = %s",
        (episode_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _cli(tmp_path: Path, *args: str, actor: str = ACTOR, project: str = PROJECT) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        [
            "research",
            "run",
            "--project",
            project,
            "--actor",
            actor,
            "--artifact-root",
            str(tmp_path / "artifacts"),
            *args,
        ],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    return code, out.getvalue()


def _open(tmp_path: Path, db, case_id: str = "mesh-coarse-access") -> str:  # type: ignore[no-untyped-def]
    """A first run by ACTOR; returns the minted episode id."""
    device = _device(tmp_path, case_id)
    code, printed = _cli(
        tmp_path, "--goal", GOAL, "--measurement", str(REPORT), "--verification-input", str(device)
    )
    assert code == 0, printed
    row = db.execute(
        "SELECT episode_id FROM research_episodes WHERE project_id = %s ORDER BY start_time DESC"
        " LIMIT 1",
        (PROJECT,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _continue(tmp_path: Path, episode_id: str, *extra: str, **who: str) -> tuple[int, str]:
    return _cli(tmp_path, "--episode", episode_id, *extra, **who)


def _service(tmp_path: Path) -> ResearchEpisodeService:
    return ResearchEpisodeService(
        connection=psycopg.connect(database_url(), autocommit=True),
        artifact_store=LocalArtifactStore((tmp_path / "artifacts").resolve()),
        vertical_factory=load_vertical_factory("silicon_photonics"),
    )


def _runs(db, episode_id: str) -> list[tuple[object, ...]]:  # type: ignore[no-untyped-def]
    return [
        tuple(r)
        for r in db.execute(
            "SELECT ordinal, actor_id, hypothesis_set_id, verification_artifact_id, outcome"
            " FROM research_runs WHERE episode_id = %s ORDER BY ordinal",
            (episode_id,),
        ).fetchall()
    ]


# -- a suspended episode continues as itself ----------------------------------------------------


def test_a_suspended_episode_is_continued_as_itself_over_one_reasoning_history(db, tmp_path):
    _member(db)
    episode_id = _open(tmp_path, db)
    before_row = _episode_row(db, episode_id)
    assert before_row[3] == "SUSPENDED" and "cap:sp.mesh_sensitivity" in str(before_row[8])
    before = _census(db)
    executed_before = db.execute(
        "SELECT capability_id, job_id FROM jobs WHERE episode_id = %s AND state = 'SUCCEEDED'"
        " AND idempotency_key LIKE 'vs:%%' ORDER BY capability_id",
        (episode_id,),
    ).fetchall()
    assert len(executed_before) == 2, "the opening run executed both solver-free checks"
    (opening,) = _runs(db, episode_id)
    plans_before = {
        str(r[0])
        for r in db.execute(
            "SELECT plan_id FROM verification_plans WHERE episode_id = %s", (episode_id,)
        ).fetchall()
    }

    code, printed = _continue(tmp_path, episode_id)
    assert code == 0, printed
    after = _census(db)

    # -- the SAME episode, resumed through its lifecycle and parked again ---------------------
    assert f"# Research episode {episode_id}" in printed
    assert "## Continuation: run 2 of this episode" in printed
    assert (
        "Resumed from SUSPENDED (awaiting simulator for cap:sp.mesh_sensitivity) to "
        "EVIDENCE_GATHERING through episode_resume." in printed
    )
    row = _episode_row(db, episode_id)
    assert row[:3] == before_row[:3], "project, trace and goal are the episode's own"
    assert row[5] == before_row[5], "the episode's start is its first run's"
    assert row[3] == "SUSPENDED" and "cap:sp.mesh_sensitivity" in str(row[8])
    assert row[7] > before_row[7], "suspended anew, after being resumed"
    assert after["research_episodes"] == before["research_episodes"] == 1

    # -- ONE reasoning history: nothing debated, admitted or believed anew ---------------------
    for table in (
        "hypothesis_sets",
        "hypotheses",
        "positions",
        "critique_reports",
        "debate_records",
        "evidence_bundles",
        "inference_provenance",
        "belief_revision_events",
        "attestations",
        "ingestion_items",
        "external_snapshots",
    ):
        assert after[table] == before[table], f"{table} changed: {before[table]} -> {after[table]}"
    set_id = db.execute(
        "SELECT set_id FROM hypothesis_sets WHERE episode_id = %s", (episode_id,)
    ).fetchone()[0]
    assert f"| hypotheses | RESUMED | hypothesis set `{set_id}`" in printed
    assert "not debated again" in printed

    # -- no check executed twice; the new plan is appended to the episode ----------------------
    assert after["jobs"] == before["jobs"] and after["runs"] == before["runs"]
    for capability, job_id in executed_before:
        assert f"`{capability}` -- job `{job_id}`" in printed
    assert after["verification_plans"] > before["verification_plans"]
    # The planner was told what the episode already executed: those checks are not candidates,
    # and the plan says why, rather than finding them insufficient by coincidence.
    new_plans = [
        (str(r[0]), list(r[1]), str(r[2]))
        for r in db.execute(
            "SELECT plan_id, candidate_action_ids, rationale::text FROM verification_plans"
            " WHERE episode_id = %s",
            (episode_id,),
        ).fetchall()
        if str(r[0]) not in plans_before
    ]
    assert new_plans
    for _plan_id, candidates, rationale in new_plans:
        for capability, _job in executed_before:
            assert capability not in candidates
            assert capability in rationale and "executed earlier in this episode" in rationale
    assert after["failure_analyses"] == before["failure_analyses"] + 1
    assert "| verification | DONE | 1 plan(s), 0 check(s) executed" in printed

    # -- the ledger: two runs, one opener, one set, one input ----------------------------------
    runs = _runs(db, episode_id)
    assert [r[0] for r in runs] == [1, 2]
    assert {r[1] for r in runs} == {ACTOR}
    assert runs[1][2:4] == opening[2:4] == (set_id, opening[3])
    assert [r[4] for r in runs] == ["SUSPENDED:PROVISIONAL", "SUSPENDED:PROVISIONAL"]

    # -- and again: a continuation is repeatable, and still one history --------------------------
    code, printed = _continue(tmp_path, episode_id)
    assert code == 0, printed
    assert "## Continuation: run 3 of this episode" in printed
    assert _census(db)["hypothesis_sets"] == 1 and _census(db)["debate_records"] == 1
    assert [r[0] for r in _runs(db, episode_id)] == [1, 2, 3]


# -- foreign and unknown ids -------------------------------------------------------------------


def test_a_foreign_or_unknown_episode_id_gets_one_answer_and_nothing_is_written(db, tmp_path):
    _member(db)
    _member(db, COLLEAGUE)
    episode_id = _open(tmp_path, db)
    # Mallory is a researcher in her own project, and not in this one.
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'Other lab')", (OTHER_PROJECT,))
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'Mallory')",
        (MALLORY,),
    )
    for member in (MALLORY, ACTOR):  # the opener belongs to the other lab too
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
            " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC', 'INTERNAL'],"
            " ARRAY[]::text[], TRUE)",
            (member, OTHER_PROJECT),
        )
    # An episode in this project that no research run opened (M1's `episode open`).
    out = io.StringIO()
    assert (
        cli.main(
            [
                "episode",
                "open",
                "--project",
                PROJECT,
                "--actor",
                ACTOR,
                "--goal",
                "ingest only",
                "--episode",
                "epi:ingest-only",
                "--trace",
                "trc:ingest-only",
                "--artifact-root",
                str(tmp_path / "artifacts"),
                str(REPORT),
            ],
            out=out,
            env={"LAB_BRAIN_DATABASE_URL": database_url()},
            connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
        )
        == 0
    ), out.getvalue()
    before = _census(db)
    before_row = _episode_row(db, episode_id)

    def answer(eid: str, *, actor: str, project: str) -> str:
        code, printed = _continue(tmp_path, eid, actor=actor, project=project)
        assert code == 1, printed
        return printed.strip()

    unknown = "epi:does-not-exist"
    # Another project's episode, named from Mallory's own project: the answer an unknown id gets.
    foreign = answer(episode_id, actor=MALLORY, project=OTHER_PROJECT)
    assert foreign == f"No episode {episode_id} to continue for {MALLORY} in {OTHER_PROJECT}."
    assert foreign.replace(episode_id, unknown) == answer(
        unknown, actor=MALLORY, project=OTHER_PROJECT
    )
    # Even its opener cannot reach it from another project: the episode is bound to its own.
    assert answer(episode_id, actor=ACTOR, project=OTHER_PROJECT) == (
        f"No episode {episode_id} to continue for {ACTOR} in {OTHER_PROJECT}."
    )
    # Naming the episode's own project: she is not a member, so the project answers first.
    assert answer(episode_id, actor=MALLORY, project=PROJECT) == (
        f"No research for {MALLORY} in {PROJECT}."
    )
    # A colleague in the same project did not open it: the same answer as an unknown id.
    colleague = answer(episode_id, actor=COLLEAGUE, project=PROJECT)
    assert colleague == f"No episode {episode_id} to continue for {COLLEAGUE} in {PROJECT}."
    assert colleague.replace(episode_id, unknown) == answer(
        unknown, actor=COLLEAGUE, project=PROJECT
    )
    # An episode no research run opened is not a research episode, even to the actor who opened it.
    assert answer("epi:ingest-only", actor=ACTOR, project=PROJECT) == (
        f"No episode epi:ingest-only to continue for {ACTOR} in {PROJECT}."
    )
    # M1's `episode open` does not hand out another project's episode under its id either.
    out = io.StringIO()
    code = cli.main(
        [
            "episode",
            "open",
            "--project",
            OTHER_PROJECT,
            "--actor",
            MALLORY,
            "--goal",
            "probe",
            "--episode",
            episode_id,
            "--trace",
            "trc:probe",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            str(REPORT),
        ],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    printed = out.getvalue()
    assert code == 1 and "is already taken by another episode" in printed, printed
    assert PROJECT not in printed and str(before_row[1]) not in printed and GOAL not in printed

    assert _census(db) == before, "a refused continuation writes nothing"
    assert _episode_row(db, episode_id) == before_row, "the episode is untouched"


# -- a finished episode ------------------------------------------------------------------------


def test_a_completed_episode_receives_no_new_research_run(db, tmp_path):
    _member(db)
    confirmed = _open(tmp_path, db, "contact-open-via")
    assert _episode_row(db, confirmed)[3] == "COMPLETED"
    # And one closed as NOT_REACHED: no verification input, so nothing was verified.
    code, printed = _cli(tmp_path, "--goal", GOAL, "--measurement", str(REPORT))
    assert code == 0, printed
    not_reached = db.execute(
        "SELECT episode_id FROM research_episodes WHERE outcome_status = 'NOT_REACHED'"
    ).fetchone()[0]
    before = _census(db)
    rows = {e: _episode_row(db, e) for e in (confirmed, not_reached)}

    code, printed = _continue(tmp_path, confirmed)
    assert code == 1, printed
    assert f"Episode {confirmed} is COMPLETED (CONFIRMED:hyp:" in printed
    assert "a finished episode receives no new research run" in printed
    code, printed = _continue(tmp_path, not_reached)
    assert code == 1 and f"Episode {not_reached} is COMPLETED (NOT_REACHED)" in printed

    assert _census(db) == before
    assert {e: _episode_row(db, e) for e in rows} == rows
    assert [r[0] for r in _runs(db, confirmed)] == [1]

    # The service refuses it the same way, whatever the caller.
    with pytest.raises(EpisodeFinished):
        _service(tmp_path).run(
            ResearchRequest(
                project_id=PROJECT, actor_id=ACTOR, goal="", documents=(), episode_id=confirmed
            )
        )
    assert _census(db) == before


# -- what a continuation may carry ---------------------------------------------------------------


def test_a_continuation_takes_no_new_inputs_and_keeps_the_episode_goal(db, tmp_path):
    _member(db)
    episode_id = _open(tmp_path, db)
    before = _census(db)
    before_row = _episode_row(db, episode_id)

    code, printed = _continue(tmp_path, episode_id, "--measurement", str(REPORT))
    assert code == 2 and "--measurement cannot be added" in printed, printed
    code, printed = _continue(tmp_path, episode_id, "--symptom", "Rs is high")
    assert code == 2 and "--symptom" in printed, printed
    code, printed = _continue(tmp_path, episode_id, "--goal", "Is the modulator too slow?")
    assert code == 1 and "a continuation keeps the episode's goal" in printed, printed
    code, printed = _continue(tmp_path, episode_id, "--trace", "trc:another")
    assert code == 1 and "a continuation keeps the episode's trace" in printed, printed
    code, printed = _cli(tmp_path, "--measurement", str(REPORT))
    assert code == 2 and "--goal is required to open an episode" in printed, printed

    # The service holds the same line for a caller that is not the CLI.
    service = _service(tmp_path)
    document = InputDocument(
        name=REPORT.name,
        data=REPORT.read_bytes(),
        media_type="text/markdown",
        uri=REPORT.resolve().as_uri(),
        trust_class=TrustClass.INTERNAL_MEASUREMENT,
    )
    with pytest.raises(Exception, match="takes no new ones"):
        service.run(
            ResearchRequest(
                project_id=PROJECT,
                actor_id=ACTOR,
                goal="",
                documents=(document,),
                episode_id=episode_id,
            )
        )

    assert _census(db) == before
    assert _episode_row(db, episode_id) == before_row


# -- retry: live, interrupted and parked runs ----------------------------------------------------


def test_a_live_run_holds_the_episode_and_an_interrupted_one_is_recovered(db, tmp_path):
    _member(db)
    episode_id = _open(tmp_path, db)
    (opening,) = [
        r
        for r in SqlResearchRunStore(db).runs(project_id=PROJECT, episode_id=episode_id)
        if r.ordinal == 1
    ]
    before = _census(db)
    before_row = _episode_row(db, episode_id)

    # Another run is live: it holds the lease.
    other = psycopg.connect(database_url(), autocommit=True)
    ledger = SqlResearchRunStore(other)
    assert ledger.lease(episode_id)
    code, printed = _continue(tmp_path, episode_id)
    assert code == 1 and f"Episode {episode_id} has a research run in progress" in printed
    assert _census(db) == before and _episode_row(db, episode_id) == before_row

    # ...which then dies mid-run: resumed, recorded, one job RUNNING, and its connection gone.
    SqlEpisodeStore(other).resume(episode_id)
    ledger.start(
        ResearchRunRecord(
            research_run_id="rrn:died",
            episode_id=episode_id,
            project_id=PROJECT,
            actor_id=ACTOR,
            ordinal=2,
            hypothesis_set_id=opening.hypothesis_set_id,
            verification_artifact_id=opening.verification_artifact_id,
            symptom=opening.symptom,
            expected_behavior=opening.expected_behavior,
            observed_behavior=opening.observed_behavior,
            started_at=opening.started_at,
        )
    )
    jobs = SqlJobStore(other)
    trace = str(before_row[1])
    orphan = jobs.submit(
        Job(
            job_id="job:orphan",
            project_id=PROJECT,
            episode_id=episode_id,
            capability_id="cap:sp.extraction_consistency",
            trace_id=trace,
            idempotency_key=f"vs:{episode_id}:run2:0:cap:sp.extraction_consistency",
            submitted_at=opening.started_at,
        )
    )
    jobs.transition(orphan.job_id, JobState.RUNNING, opening.started_at)
    other.close()

    code, printed = _continue(tmp_path, episode_id)
    assert code == 0, printed
    assert "## Continuation: run 3 of this episode" in printed
    assert "run 2 was left unfinished by a process that ended; recorded INTERRUPTED" in printed
    assert "job `job:orphan` was left RUNNING by it with no Run; recorded FAILED" in printed
    runs = _runs(db, episode_id)
    assert [(r[0], r[4]) for r in runs] == [
        (1, "SUSPENDED:PROVISIONAL"),
        (2, "INTERRUPTED"),
        (3, "SUSPENDED:PROVISIONAL"),
    ]
    state, error = db.execute(
        "SELECT state, structured_error->>'code' FROM jobs WHERE job_id = 'job:orphan'"
    ).fetchone()
    assert (state, error) == ("FAILED", "RESEARCH_RUN_INTERRUPTED")
    assert _episode_row(db, episode_id)[3] == "SUSPENDED"
    assert _census(db)["hypothesis_sets"] == 1


def test_a_parked_check_is_superseded_and_the_continuation_confirms_the_cause(db, tmp_path):
    _member(db)
    device = _device(tmp_path, "contact-open-via")
    service = _service(tmp_path)
    document = InputDocument(
        name=REPORT.name,
        data=REPORT.read_bytes(),
        media_type="text/markdown",
        uri=REPORT.resolve().as_uri(),
        trust_class=TrustClass.INTERNAL_MEASUREMENT,
    )
    # No wall-clock budget: the first check is refused by the budget and its job parked.
    first = service.run(
        ResearchRequest(
            project_id=PROJECT,
            actor_id=ACTOR,
            goal=GOAL,
            documents=(document,),
            verification_input=(device.name, device.read_bytes()),
            wall_clock_budget_s=0,
        )
    )
    episode_id = first.episode_id
    assert first.episode_state == "SUSPENDED"
    (parked,) = db.execute(
        "SELECT job_id, idempotency_key, state FROM jobs WHERE episode_id = %s"
        " AND idempotency_key LIKE 'vs:%%'",
        (episode_id,),
    ).fetchall()
    assert parked[2] == "QUEUED" and parked[1].startswith(f"vs:{episode_id}:0:")
    sets_before = _census(db)["hypothesis_sets"]

    # The budget is there now. The same episode continues, and the cheap checks settle it.
    second = service.run(
        ResearchRequest(
            project_id=PROJECT, actor_id=ACTOR, goal="", documents=(), episode_id=episode_id
        )
    )
    assert second.episode_id == episode_id
    assert second.conclusion.status == "CONFIRMED" and second.episode_state == "COMPLETED"
    state, outcome = db.execute(
        "SELECT state, outcome_status FROM research_episodes WHERE episode_id = %s", (episode_id,)
    ).fetchone()
    assert state == "COMPLETED" and outcome.startswith("CONFIRMED:")

    # The parked job was superseded, not re-dispatched under its recorded ids...
    state, error = db.execute(
        "SELECT state, structured_error->>'code' FROM jobs WHERE job_id = %s", (parked[0],)
    ).fetchone()
    assert (state, error) == ("CANCELLED", "SUPERSEDED_BY_CONTINUATION")
    # ...and this run's jobs are keyed in its own namespace, each executed once.
    keys = [
        str(r[0])
        for r in db.execute(
            "SELECT idempotency_key FROM jobs WHERE episode_id = %s AND state = 'SUCCEEDED'"
            " AND idempotency_key LIKE 'vs:%%' ORDER BY submitted_at",
            (episode_id,),
        ).fetchall()
    ]
    assert keys and all(k.startswith(f"vs:{episode_id}:run2:") for k in keys)
    assert _census(db)["hypothesis_sets"] == sets_before == 1
    analyses = [
        str(r[0])
        for r in db.execute(
            "SELECT resolution_status FROM failure_analyses WHERE episode_id = %s"
            " ORDER BY created_at",
            (episode_id,),
        ).fetchall()
    ]
    assert analyses == ["OPEN", "CONFIRMED"]
    assert [r[4] for r in _runs(db, episode_id)] == ["SUSPENDED:PROVISIONAL", "COMPLETED:CONFIRMED"]


def test_a_verification_error_parks_the_episode_and_a_continuation_retries_it(
    db, tmp_path, monkeypatch
):
    """An error is not an answer: the episode is parked, not closed, and the retry is the SAME
    episode over the SAME hypotheses."""
    _member(db)
    device = _device(tmp_path, "contact-open-via")
    service = _service(tmp_path)

    def broken(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("the verification loop fell over")

    with monkeypatch.context() as patched:
        patched.setattr("lab_brain.verification.loop.VerificationLoop.run", broken)
        first = service.run(
            ResearchRequest(
                project_id=PROJECT,
                actor_id=ACTOR,
                goal=GOAL,
                documents=(
                    InputDocument(
                        name=REPORT.name,
                        data=REPORT.read_bytes(),
                        media_type="text/markdown",
                        uri=REPORT.resolve().as_uri(),
                        trust_class=TrustClass.INTERNAL_MEASUREMENT,
                    ),
                ),
                verification_input=(device.name, device.read_bytes()),
            )
        )
    assert any(s.stage == "verification" and s.status == "FAILED" for s in first.stages)
    assert first.episode_state == "SUSPENDED" and first.conclusion.status == "NOT_REACHED"
    state, reason = db.execute(
        "SELECT state, suspend_reason FROM research_episodes WHERE episode_id = %s",
        (first.episode_id,),
    ).fetchone()
    assert state == "SUSPENDED" and reason.startswith("verification failed")

    retried = service.run(
        ResearchRequest(
            project_id=PROJECT, actor_id=ACTOR, goal="", documents=(), episode_id=first.episode_id
        )
    )
    assert retried.episode_id == first.episode_id
    assert retried.conclusion.status == "CONFIRMED" and retried.episode_state == "COMPLETED"
    assert _census(db)["hypothesis_sets"] == 1
    assert [r[4] for r in _runs(db, first.episode_id)] == [
        "SUSPENDED:NOT_REACHED",
        "COMPLETED:CONFIRMED",
    ]
