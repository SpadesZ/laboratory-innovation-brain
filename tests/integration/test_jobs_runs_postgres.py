"""OPS-001 against PostgreSQL — the same behaviour, plus the guarantees only a database gives.

The shared scenarios from `tests/job_fixtures.py` run here against `SqlJobStore`. If one of them
passes in `tests/contract/test_job_lifecycle.py` and fails here, the in-memory store is more
permissive than production and the backend-free suite has been proving nothing.

What only this file can assert:

    durability      a *new store on a new connection* sees the completed job and its Run. The
                    in-memory version of that test is honest about being weaker.
    real concurrency two connections, a barrier, and `job_complete` deciding the winner. The
                    in-memory race uses threads over one lock; this one uses two transactions,
                    which is the situation the lock was standing in for.
    raw-SQL bypass  every guard reachable by a writer who never calls this repository. `011a`'s
                    lesson for the fifth time: a guard that holds for callers who go through the
                    guard holds for callers who go through the guard.
"""

from __future__ import annotations

import threading

import psycopg
import pytest

from lab_brain.core.models.job import JobState, RunStatus
from lab_brain.core.repositories.jobs import SqlJobStore
from tests.job_fixtures import CAPABILITY, OTHER_PROJECT, SCENARIOS, at, make_job, make_run
from tests.postgres_fixtures import database_url

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("OPS-001"),
    pytest.mark.spec_test("T-OPS-001"),
]


@pytest.fixture
def jobs_db(db):
    """The standard database plus the second project the cross-project scenarios need."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (OTHER_PROJECT, "Other Project"),
    )
    return db


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.__name__[len("scenario_") :])
def test_shared_lifecycle_behaviour(jobs_db, scenario):
    """Every scenario the in-memory store passes, against the real one."""
    scenario(SqlJobStore(jobs_db))


def test_state_and_idempotency_survive_a_reload(jobs_db):
    """ "MUST survive process/repository reload" -- with a genuinely separate connection.

    A second `SqlJobStore` on the same connection would prove only that the object has no hidden
    cache. This opens a new connection, which is what a restarted worker does, and then delivers
    the callback *again* from it: the redelivery has to find the existing Run through the
    database, because there is no process memory left to find it in.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:reload"))
    store.transition("job:reload", JobState.RUNNING, at(1))
    first = store.complete("job:reload", "idem:1", make_run("run:reload", job_id="job:reload"))

    with psycopg.connect(database_url(), autocommit=True) as reloaded:
        after = SqlJobStore(reloaded)
        job = after.get("job:reload")
        assert job is not None
        assert job.state is JobState.SUCCEEDED
        assert job.result_run_id == "run:reload"
        assert after.run_for_job("job:reload") is not None

        redelivered = after.complete(
            "job:reload", "idem:1", make_run("run:after-restart", job_id="job:reload")
        )
        assert redelivered.run_id == first.run_id
        assert after.get_run("run:after-restart") is None


def test_two_connections_delivering_at_once_produce_one_run(jobs_db):
    """The real race: two transactions, not two threads over one lock.

    Both open their own connection, meet at a barrier, and call `job_complete` with different
    proposed run ids. `FOR UPDATE` inside the function serialises them; the loser observes the
    winner's row and returns it. Exactly one Run, and both callers get the same answer.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:race"))
    store.transition("job:race", JobState.RUNNING, at(1))

    barrier = threading.Barrier(2)
    answers: list[str] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def deliver(label: str) -> None:
        try:
            with psycopg.connect(database_url(), autocommit=True) as connection:
                own = SqlJobStore(connection)
                run = make_run(f"run:{label}", job_id="job:race")
                barrier.wait(timeout=10)
                result = own.complete("job:race", "idem:1", run)
            with lock:
                answers.append(result.run_id)
        except BaseException as exc:
            with lock:
                failures.append(exc)

    threads = [threading.Thread(target=deliver, args=(label,)) for label in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not failures, f"a delivery raised: {failures}"
    assert len(set(answers)) == 1, f"the two connections disagreed: {answers}"
    total = jobs_db.execute("SELECT count(*) FROM runs WHERE job_id = 'job:race'").fetchone()
    assert total[0] == 1


# ---------------------------------------------------------------------------
# Raw SQL — the writer who never calls the repository
# ---------------------------------------------------------------------------


def test_raw_sql_cannot_give_a_job_a_second_run(jobs_db):
    """The constraint, not the function. This is the backstop behind `FOR UPDATE`."""
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:one"))
    store.transition("job:one", JobState.RUNNING, at(1))
    store.complete("job:one", "idem:1", make_run("run:one", job_id="job:one"))

    with pytest.raises(psycopg.errors.UniqueViolation):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, trace_id, "
            "conditions_schema_version, code_provenance, status, output_artifacts, start_time, "
            "end_time, reproducibility_manifest_hash) VALUES "
            "('run:sneaked', 'job:one', 'prj:test', 'c', 'b', 't', 'cs', 'g', 'SUCCEEDED', "
            "ARRAY['art:x'], now(), now(), 'h')"
        )


def test_raw_sql_cannot_reopen_a_terminal_job(jobs_db):
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:term"))
    store.transition("job:term", JobState.RUNNING, at(1))
    store.transition("job:term", JobState.CANCELLED, at(2))

    with pytest.raises(psycopg.errors.RaiseException, match="terminal job is a finished fact"):
        jobs_db.execute("UPDATE jobs SET state = 'RUNNING' WHERE job_id = 'job:term'")


def test_raw_sql_cannot_rewrite_which_run_a_job_resolved_to(jobs_db):
    """Write-once on `result_run_id`.

    Rewriting it would move every attestation citing that run onto a different execution, and
    every one of those attestations would still look perfectly well-formed.

    NOTE ON THE SETUP. An earlier version of this test built its second Run with a raw INSERT and
    left it unclaimed. `006a`'s deferred trigger now refuses that, so the setup itself became
    illegal -- which is the guard working on the test that was quietly depending on the defect.
    Both runs are now created through the one completion path.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:wo"))
    store.transition("job:wo", JobState.RUNNING, at(1))
    store.complete("job:wo", "idem:1", make_run("run:wo", job_id="job:wo"))

    store.submit(make_job("job:other", idempotency_key="idem:other"))
    store.transition("job:other", JobState.RUNNING, at(1))
    store.complete("job:other", "idem:other", make_run("run:elsewhere", job_id="job:other"))

    with pytest.raises(psycopg.errors.RaiseException, match="already resolved to run"):
        jobs_db.execute("UPDATE jobs SET result_run_id = 'run:elsewhere' WHERE job_id = 'job:wo'")


def test_raw_sql_cannot_attach_a_run_to_a_job_that_does_not_exist(jobs_db):
    with pytest.raises(psycopg.errors.RaiseException, match="does not exist"):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, trace_id, "
            "conditions_schema_version, code_provenance, status, output_artifacts, start_time, "
            "end_time, reproducibility_manifest_hash) VALUES "
            "('run:orphan', 'job:ghost', 'prj:test', 'c', 'b', 't', 'cs', 'g', 'SUCCEEDED', "
            "ARRAY['art:x'], now(), now(), 'h')"
        )


def test_raw_sql_cannot_record_a_succeeded_run_that_produced_nothing(jobs_db):
    """EVI-009's provenance edge, held by a CHECK rather than by the writer remembering."""
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:empty"))

    with pytest.raises(psycopg.errors.CheckViolation, match="runs_succeeded_produced_something"):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, trace_id, "
            "conditions_schema_version, code_provenance, status, start_time, end_time, "
            "reproducibility_manifest_hash) VALUES "
            "('run:hollow', 'job:empty', 'prj:test', 'c', 'b', 't', 'cs', 'g', 'SUCCEEDED', "
            "now(), now(), 'h')"
        )


def test_raw_sql_cannot_scope_a_run_away_from_its_job(jobs_db):
    """SEC-002 through the side door: a run in a project its job is not in."""
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:scope"))

    with pytest.raises(psycopg.errors.RaiseException, match="side door"):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, trace_id, "
            "conditions_schema_version, code_provenance, status, output_artifacts, start_time, "
            "end_time, reproducibility_manifest_hash) VALUES "
            "('run:leak', 'job:scope', %s, 'c', 'b', 't', 'cs', 'g', 'SUCCEEDED', "
            "ARRAY['art:x'], now(), now(), 'h')",
            (OTHER_PROJECT,),
        )


def test_the_idempotency_key_is_unique_per_project_not_globally(jobs_db):
    """Two projects may use the same caller-chosen key; one project may not use it twice."""
    jobs_db.execute(
        "INSERT INTO jobs (job_id, project_id, capability_id, trace_id, idempotency_key, "
        "submitted_at) VALUES ('job:mine', 'prj:test', 'c', 't', 'quarterly', now())"
    )
    jobs_db.execute(
        "INSERT INTO jobs (job_id, project_id, capability_id, trace_id, idempotency_key, "
        "submitted_at) VALUES ('job:theirs', %s, 'c', 't', 'quarterly', now())",
        (OTHER_PROJECT,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        jobs_db.execute(
            "INSERT INTO jobs (job_id, project_id, capability_id, trace_id, idempotency_key, "
            "submitted_at) VALUES ('job:again', 'prj:test', 'c', 't', 'quarterly', now())"
        )


def test_a_failed_run_is_recorded_rather_than_discarded(jobs_db):
    """§6.10 needs failed executions; §17.4 requires a manifest per execution.

    Through `complete()` now, not `add_run()`. That is `006a`'s point: one mechanism, and the
    failed run is just as durably claimed by its job as a successful one.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:fail"))
    store.transition("job:fail", JobState.RUNNING, at(1))
    stored = store.complete(
        "job:fail",
        "idem:1",
        make_run("run:fail", job_id="job:fail", status=RunStatus.FAILED, outputs=()),
    )
    assert stored.status is RunStatus.FAILED
    reread = store.get_run("run:fail")
    assert reread is not None
    assert reread.output_artifacts == ()
    job = store.get("job:fail")
    assert job.state is JobState.FAILED
    assert job.result_run_id == "run:fail"


# ---------------------------------------------------------------------------
# Repair B — a Run may not exist unclaimed by its Job
# ---------------------------------------------------------------------------


def test_a_run_cannot_be_committed_without_its_job_resolving_to_it(jobs_db):
    """THE Repair-B probe. Reproduced against `006` before `006a` closed it.

    `add_run` was INSERT Run then UPDATE Job, with nothing binding the two. A crash, a rollback
    of the second statement, or any raw writer doing the same thing left a Run row that is
    readable, joinable and citable while `jobs.result_run_id` was still NULL -- a durable
    execution record that nothing identifies as the authoritative output of anything.

    The guard is deferred to COMMIT for `011d`'s reason: the valid operation necessarily passes
    through that exact state between its two statements, so a per-statement trigger would look
    stricter and make completion impossible.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:unclaimed"))
    store.transition("job:unclaimed", JobState.RUNNING, at(1))

    with (
        pytest.raises(psycopg.errors.RaiseException, match="resolves to nothing"),
        jobs_db.transaction(),
    ):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, "
            "trace_id, conditions_schema_version, code_provenance, status, output_artifacts, "
            "start_time, end_time, reproducibility_manifest_hash) VALUES "
            "('run:orphaned', 'job:unclaimed', 'prj:test', %s, 'b', 'trc:1', 'cs', 'g', "
            "'SUCCEEDED', ARRAY['art:x'], now(), now(), 'h')",
            (CAPABILITY,),
        )

    assert jobs_db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0, (
        "the unclaimed run survived the failed transaction"
    )


def test_the_intermediate_unclaimed_state_inside_one_transaction_is_allowed(jobs_db):
    """The other side of deferring, pinned so nobody 'fixes' it into a per-statement trigger.

    `job_complete` inserts the Run before the Job can reference it -- the reference is a foreign
    key, so the row must exist first. Between those statements the pair reads exactly like the
    defect above. What matters is what survives COMMIT.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:ok"))
    store.transition("job:ok", JobState.RUNNING, at(1))
    run = store.complete("job:ok", "idem:1", make_run("run:ok", job_id="job:ok"))
    assert run.run_id == "run:ok"
    assert store.get("job:ok").result_run_id == "run:ok"


def test_a_job_cannot_stop_resolving_to_its_run(jobs_db):
    """The same invariant from the Job side.

    Clearing `result_run_id` back to NULL would re-create the forbidden pair without touching
    `runs`, so the constraint trigger on that table would never fire. Write-once already refuses
    a change between two non-null values; this closes the change to NULL.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:abandon"))
    store.transition("job:abandon", JobState.RUNNING, at(1))
    store.complete("job:abandon", "idem:1", make_run("run:abandon", job_id="job:abandon"))

    with pytest.raises(psycopg.errors.RaiseException, match="cannot stop resolving"):
        jobs_db.execute("UPDATE jobs SET result_run_id = NULL WHERE job_id = 'job:abandon'")


def test_there_is_only_one_job_complete_function(jobs_db):
    """`006a` DROPs the thirteen-parameter signature rather than leaving it beside the new one.

    PostgreSQL overloads by argument list. Leaving the old signature would keep the lossy path
    callable, and a caller that omitted the manifest would still succeed -- which is the defect,
    not a compatibility shim.
    """
    signatures = jobs_db.execute(
        "SELECT count(*) FROM pg_proc WHERE proname = 'job_complete'"
    ).fetchone()
    assert signatures[0] == 1, "a second job_complete overload exists; the lossy path is callable"


def test_the_completion_path_rejects_a_contradictory_trace(jobs_db):
    """§12.5's chain, held by the database rather than by the repository remembering.

    Raw SQL, so the repository's pre-check is not what refuses it.
    """
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:trace"))
    store.transition("job:trace", JobState.RUNNING, at(1))

    with pytest.raises(psycopg.errors.RaiseException, match="one trace through episode"):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, trace_id, "
            "conditions_schema_version, code_provenance, status, output_artifacts, start_time, "
            "end_time, reproducibility_manifest_hash) VALUES "
            "('run:detached', 'job:trace', 'prj:test', %s, 'b', 'trc:SOMEWHERE-ELSE', 'cs', 'g', "
            "'SUCCEEDED', ARRAY['art:x'], now(), now(), 'h')",
            (CAPABILITY,),
        )


def test_the_completion_path_rejects_a_contradictory_capability(jobs_db):
    """An execution of something nobody asked for reads its authority class from the wrong row."""
    store = SqlJobStore(jobs_db)
    store.submit(make_job("job:cap"))
    store.transition("job:cap", JobState.RUNNING, at(1))

    with pytest.raises(psycopg.errors.RaiseException, match="nobody asked for"):
        jobs_db.execute(
            "INSERT INTO runs (run_id, job_id, project_id, capability_id, backend_id, trace_id, "
            "conditions_schema_version, code_provenance, status, output_artifacts, start_time, "
            "end_time, reproducibility_manifest_hash) VALUES "
            "('run:wrongcap', 'job:cap', 'prj:test', 'cap:something-else', 'b', 'trc:1', 'cs', "
            "'g', 'SUCCEEDED', ARRAY['art:x'], now(), now(), 'h')"
        )
