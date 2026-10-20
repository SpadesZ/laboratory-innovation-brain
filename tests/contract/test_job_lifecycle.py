"""OPS-001 — the Job/Run lifecycle, backend-free (§17.16, §17.4, §10.7, §12.4).

The shared behaviour suite runs here against `InMemoryJobStore` and again in
`tests/integration/test_jobs_runs_postgres.py` against PostgreSQL. See `tests/job_fixtures.py`
for why the assertions are written once rather than twice.

What this file adds on top of the shared list is the part that is *only* checkable without a
backend -- model-level invariants and the concurrency property -- plus the guard that keeps the
SQL state machine and the Python one from drifting apart.
"""

from __future__ import annotations

import datetime as dt
import re
import threading

import pytest

from lab_brain.core.models.job import (
    JOB_TRANSITIONS,
    Job,
    JobState,
    JobTransitionError,
    Run,
    RunStatus,
)
from lab_brain.core.repositories.jobs import InMemoryJobStore
from lab_brain.spec.parser import repo_root
from tests.job_fixtures import SCENARIOS, at, make_job, make_run

pytestmark = [pytest.mark.requirement("OPS-001"), pytest.mark.spec_test("T-OPS-001")]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.__name__[len("scenario_") :])
def test_shared_lifecycle_behaviour(scenario):
    """Every scenario, against the backend-free store."""
    scenario(InMemoryJobStore())


# ---------------------------------------------------------------------------
# Concurrency — the property the whole design exists for
# ---------------------------------------------------------------------------


def test_concurrent_completions_produce_exactly_one_run():
    """Eight threads deliver the same completion at once. One Run.

    Sequential duplicate delivery is already covered by the shared scenario; this is the case that
    distinguishes a real guarantee from one that happens to hold when nothing interleaves. Each
    thread proposes its own run id, so a store that lost the race would leave two Runs and no fact
    saying which one the evidence should cite.
    """
    store = InMemoryJobStore()
    store.submit(make_job("job:race"))
    store.transition("job:race", JobState.RUNNING, at(1))

    barrier = threading.Barrier(8)
    returned: list[str] = []
    lock = threading.Lock()

    def deliver(n: int) -> None:
        barrier.wait()
        run = store.complete("job:race", "idem:1", make_run(f"run:{n}", job_id="job:race"))
        with lock:
            returned.append(run.run_id)

    threads = [threading.Thread(target=deliver, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(returned)) == 1, f"threads disagreed about the run: {sorted(set(returned))}"
    assert len(returned) == 8, "every thread must get an answer, not an error"
    winner = returned[0]
    assert store.run_for_job("job:race").run_id == winner  # type: ignore[union-attr]
    for n in range(8):
        if f"run:{n}" != winner:
            assert store.get_run(f"run:{n}") is None


def test_a_reload_sees_the_same_state():
    """ "Survives repository reload", for the store whose state is in a process.

    The in-memory store cannot actually outlive its process, so what is asserted is the honest
    version: a *second reference* to the same store observes the completed job and its Run. The
    durable half is asserted against PostgreSQL, where a new connection is a real reload.
    """
    store = InMemoryJobStore()
    store.submit(make_job("job:r"))
    store.transition("job:r", JobState.RUNNING, at(1))
    store.complete("job:r", "idem:1", make_run("run:r", job_id="job:r"))

    reader: InMemoryJobStore = store
    job = reader.get("job:r")
    assert job is not None
    assert job.state is JobState.SUCCEEDED
    assert job.result_run_id == "run:r"
    assert reader.run_for_job("job:r") is not None


# ---------------------------------------------------------------------------
# Model invariants
# ---------------------------------------------------------------------------


def test_a_terminal_job_must_carry_finished_at():
    with pytest.raises(ValueError, match="no finished_at"):
        make_job(state=JobState.SUCCEEDED)


def test_a_non_terminal_job_must_not_carry_finished_at():
    """The other direction, and it is the one that corrupts queue depth.

    A RUNNING job with a finished_at reads as active to UX-007 and as finished to anyone
    inspecting the timestamp, so the two disagree with no error anywhere.
    """
    with pytest.raises(ValueError, match="carries finished_at"):
        make_job(state=JobState.RUNNING, started_at=at(1), finished_at=at(2))


def test_a_failed_job_may_name_the_run_that_failed():
    """Changed by `006a`, and the change is the repair rather than a relaxation.

    The earlier rule allowed `result_run_id` only on SUCCEEDED, reasoning that a Run is the
    product of a job that succeeded. That is wrong twice: §17.4 requires a manifest per
    *execution*, and §6.10's failure analysis needs failed executions to exist. Worse, excluding
    FAILED is what forced failed runs down `add_run` -- the second, weaker persistence path the
    audit found -- so the rule was manufacturing the defect it looked like it was preventing.
    """
    job = make_job(
        state=JobState.FAILED, started_at=at(1), finished_at=at(2), result_run_id="run:x"
    )
    assert job.result_run_id == "run:x"


def test_a_cancelled_job_may_not_name_a_run():
    """The half of the old rule that survives: a cancelled job did not execute.

    Without this the relaxation above would let any terminal job carry a manifest, including one
    describing an execution that never happened.
    """
    with pytest.raises(ValueError, match="did not execute"):
        make_job(
            state=JobState.CANCELLED, started_at=at(1), finished_at=at(2), result_run_id="run:x"
        )


def test_attempt_count_may_not_exceed_max_attempts():
    """UX-002 stops retrying at max_attempts; exceeding it means the bound was not enforced."""
    with pytest.raises(ValueError, match="over max_attempts"):
        make_job(max_attempts=2, attempt_count=3)


def test_a_succeeded_run_with_no_outputs_is_refused():
    """EVI-009 again, at the model boundary.

    A successful run that produced nothing cannot support a MEASURED/SIMULATED attestation, and
    admitting the row would let a run reference resolve to a record with nothing behind it.
    """
    with pytest.raises(ValueError, match="no output_artifacts"):
        make_run(outputs=())


def test_a_failed_run_may_legitimately_produce_nothing():
    """The positive control for the rule above.

    Without this, a store that refused *every* empty-output run would pass the test above while
    making failure unrecordable -- and §6.10's failure analysis needs failed runs to exist.
    """
    run = make_run("run:failed", status=RunStatus.FAILED, outputs=())
    assert run.status is RunStatus.FAILED
    assert run.output_artifacts == ()


def test_a_run_cannot_end_before_it_starts():
    with pytest.raises(ValueError, match="ends before it starts"):
        make_run(start_time=at(50), end_time=at(10))


def test_transitioned_refuses_an_undeclared_edge_and_names_the_legal_ones():
    """The message matters: a refusal that does not say what *is* legal invites guessing."""
    job = make_job()
    with pytest.raises(JobTransitionError) as caught:
        job.transitioned(JobState.SUCCEEDED, at(1))
    assert "RUNNING" in str(caught.value)


def test_every_state_appears_in_the_transition_table():
    """A state missing from `JOB_TRANSITIONS` would KeyError at the moment it is reached.

    Cheap, and it catches the specific mistake of adding a state to the enum and forgetting the
    graph -- which fails at runtime in whichever code path first gets there, rather than here.
    """
    assert set(JOB_TRANSITIONS) == set(JobState)


# ---------------------------------------------------------------------------
# The two copies of the state machine
# ---------------------------------------------------------------------------


def test_the_sql_transition_table_matches_the_python_one():
    """`006_jobs_runs.sql` and `JOB_TRANSITIONS` are the same graph, compared rather than trusted.

    Two hand-written copies of a state machine drift. The drift is invisible until a job is
    RUNNING in PostgreSQL and QUEUED in memory, at which point the record disagrees with itself
    and no test that used only one of them would have noticed.
    """
    sql = (repo_root() / "migrations" / "006_jobs_runs.sql").read_text(encoding="utf-8")
    body = sql.split("v_legal := CASE OLD.state", 1)[1].split("END;", 1)[0]

    from_sql: dict[str, set[str]] = {}
    for state, targets in re.findall(r"WHEN '(\w+)'\s+THEN NEW\.state IN \(([^)]*)\)", body):
        from_sql[state] = set(re.findall(r"'(\w+)'", targets))

    from_python = {
        state.value: {target.value for target in targets}
        for state, targets in JOB_TRANSITIONS.items()
        if targets
    }
    assert from_sql == from_python


def test_the_sql_state_check_lists_exactly_the_enum():
    """The CHECK constraint's vocabulary and `JobState` are the same set."""
    sql = (repo_root() / "migrations" / "006_jobs_runs.sql").read_text(encoding="utf-8")
    clause = sql.split("state           TEXT NOT NULL DEFAULT 'QUEUED' CHECK (", 1)[1]
    listed = set(re.findall(r"'(\w+)'", clause.split(")", 1)[0]))
    assert listed == {state.value for state in JobState}


def test_naive_timestamps_are_rejected():
    """`as_of` replay compares timestamps across processes; one naive value breaks ordering."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Job.model_validate(
            {
                "job_id": "job:naive",
                "project_id": "prj:test",
                "capability_id": "cap:x",
                "trace_id": "trc:1",
                "idempotency_key": "k",
                "submitted_at": dt.datetime(2026, 9, 21, 12, 0),
            }
        )


def test_a_run_may_not_list_the_same_artifact_twice():
    """A double-counted output is worse than an unrecorded one because it looks like evidence."""
    with pytest.raises(ValueError, match="duplicate in output_artifacts"):
        make_run(outputs=("art:x", "art:x"))


def test_unknown_fields_are_refused_on_both_models():
    """`extra="forbid"`: a typo'd field silently dropped produces a record that lies."""
    for model, payload in (
        (Job, {"idempotancy_key": "typo"}),
        (Run, {"output_artifact": "typo"}),
    ):
        with pytest.raises(ValueError):
            model.model_validate({**_minimal(model), **payload})


def _minimal(model: type) -> dict[str, object]:
    if model is Job:
        return make_job().model_dump()
    return make_run().model_dump()
