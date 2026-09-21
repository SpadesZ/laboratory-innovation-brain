"""Builders and the shared OPS-001 behaviour suite (§17.16, §17.4, §10.7, §12.4).

WHY THE ASSERTIONS LIVE HERE RATHER THAN IN ONE TEST FILE.

`InMemoryJobStore` and `SqlJobStore` have to behave identically, and the failure mode that costs
the most is the in-memory one being *more permissive*: a backend-free suite then passes against a
fake while the real invariant is broken in production. Writing the behaviour twice -- once per
file -- is how the two copies drift until they no longer describe the same contract.

So each scenario below takes a store and asserts. `tests/contract/test_job_lifecycle.py` runs them
against the in-memory store with no backend; `tests/integration/test_jobs_runs_postgres.py` runs
the same functions against PostgreSQL. A scenario that passes in one and fails in the other is
exactly the report worth having.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models.job import Job, JobState, JobTransitionError, Run, RunStatus
from lab_brain.core.repositories.jobs import IdempotencyKeyMismatch, JobStore, JobStoreError

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"
CAPABILITY = "cap:ingest_document"
BACKEND = "backend:local_parser"
SCHEMA_REF = "toy.conditions@1.0.0"

T0 = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)


def at(seconds: int) -> dt.datetime:
    """A deterministic clock. Real timestamps make ordering assertions flaky for no benefit."""
    return T0 + dt.timedelta(seconds=seconds)


def make_job(
    job_id: str = "job:1",
    *,
    project_id: str = PROJECT,
    idempotency_key: str = "idem:1",
    max_attempts: int = 1,
    **overrides: object,
) -> Job:
    payload: dict[str, object] = {
        "job_id": job_id,
        "project_id": project_id,
        "capability_id": CAPABILITY,
        "trace_id": "trc:1",
        "idempotency_key": idempotency_key,
        "submitted_at": T0,
        "max_attempts": max_attempts,
    }
    payload.update(overrides)
    return Job.model_validate(payload)


def make_run(
    run_id: str = "run:1",
    *,
    job_id: str = "job:1",
    project_id: str = PROJECT,
    outputs: tuple[str, ...] = ("art:produced",),
    status: RunStatus = RunStatus.SUCCEEDED,
    **overrides: object,
) -> Run:
    payload: dict[str, object] = {
        "run_id": run_id,
        "job_id": job_id,
        "project_id": project_id,
        "capability_id": CAPABILITY,
        "backend_id": BACKEND,
        "trace_id": "trc:1",
        "conditions_schema_version": SCHEMA_REF,
        "code_provenance": "git:0123456789abcdef",
        "status": status,
        "output_artifacts": outputs,
        "start_time": at(10),
        "end_time": at(20),
        "reproducibility_manifest_hash": "sha256:manifest",
    }
    payload.update(overrides)
    return Run.model_validate(payload)


# ---------------------------------------------------------------------------
# The scenarios. Each takes a store and asserts one property of OPS-001.
# ---------------------------------------------------------------------------


def scenario_submit_is_idempotent_on_the_key(store: JobStore) -> None:
    """A client that retries a submission it is unsure landed gets one job, not two.

    The second call carries a *different* job_id, which is what a retrying client would generate.
    Conflicting on the primary key would let it through and create a second job for one logical
    submission -- so the conflict target is the idempotency key.
    """
    first = store.submit(make_job("job:a", idempotency_key="idem:same"))
    second = store.submit(make_job("job:b", idempotency_key="idem:same"))
    assert second.job_id == first.job_id == "job:a"
    assert store.get("job:b") is None


def scenario_the_same_key_in_another_project_is_a_different_job(store: JobStore) -> None:
    """Scoped per project, for the reason `v3.3-a18` gives about evidence units.

    Two projects legitimately submit "ingest my quarterly report" under the same caller-chosen
    key. A global unique index would make the second project's submission collide with the
    first's and silently return someone else's job.
    """
    mine = store.submit(make_job("job:mine", project_id=PROJECT, idempotency_key="quarterly"))
    theirs = store.submit(
        make_job("job:theirs", project_id=OTHER_PROJECT, idempotency_key="quarterly")
    )
    assert mine.job_id != theirs.job_id
    assert theirs.project_id == OTHER_PROJECT


def scenario_suspend_and_resume_round_trip(store: JobStore) -> None:
    """§10.7's WAITING_RESOURCE edge, both directions, ending in exactly one Run.

    This is T-OPS-001's "delayed mock job 可 suspend/resume" in its smallest honest form: the job
    parks for a resource, is resumed, and completes. Asserting the states along the way rather
    than only the end matters -- a store that skipped straight to SUCCEEDED would satisfy the
    final assertion and record a lifecycle that never happened.
    """
    store.submit(make_job("job:s"))
    running = store.transition("job:s", JobState.RUNNING, at(1))
    assert running.started_at == at(1)

    parked = store.transition("job:s", JobState.WAITING_RESOURCE, at(2))
    assert parked.state is JobState.WAITING_RESOURCE
    assert parked.is_active, "a parked job is still occupying queue depth (UX-007)"
    assert parked.finished_at is None

    resumed = store.transition("job:s", JobState.RUNNING, at(3))
    assert resumed.state is JobState.RUNNING
    assert resumed.started_at == at(1), "resuming is not a second start"

    run = store.complete("job:s", "idem:1", make_run("run:s", job_id="job:s"))
    assert run.run_id == "run:s"
    assert store.get("job:s").state is JobState.SUCCEEDED  # type: ignore[union-attr]


def scenario_a_duplicate_completion_creates_no_second_run(store: JobStore) -> None:
    """THE OPS-001 probe. §10.7: idempotency_key 防止重複 callback 產生第二個 run.

    The redeliveries propose *different* run ids, which is what a retrying deliverer that mints an
    id per attempt would do. All three calls must return the first Run. A store that returned the
    proposal would hand the caller a Run that does not exist.
    """
    store.submit(make_job("job:d"))
    store.transition("job:d", JobState.RUNNING, at(1))

    first = store.complete("job:d", "idem:1", make_run("run:first", job_id="job:d"))
    again = store.complete("job:d", "idem:1", make_run("run:second", job_id="job:d"))
    third = store.complete("job:d", "idem:1", make_run("run:third", job_id="job:d"))

    assert first.run_id == again.run_id == third.run_id == "run:first"
    assert store.get_run("run:second") is None
    assert store.get_run("run:third") is None
    assert store.run_for_job("job:d").run_id == "run:first"  # type: ignore[union-attr]


def scenario_a_completion_under_the_wrong_key_is_refused(store: JobStore) -> None:
    """A callback for submission A delivered against job B.

    Completing anyway would attribute one execution's output to another's request, and the
    resulting Run would be perfectly well-formed -- nothing downstream could detect it. So this
    fails closed rather than trusting the job_id alone.
    """
    store.submit(make_job("job:w", idempotency_key="idem:right"))
    store.transition("job:w", JobState.RUNNING, at(1))
    with pytest.raises(IdempotencyKeyMismatch):
        store.complete("job:w", "idem:wrong", make_run("run:w", job_id="job:w"))
    assert store.run_for_job("job:w") is None


def scenario_a_terminal_job_cannot_be_reopened(store: JobStore) -> None:
    """A finished fact stays finished. Every edge out of a terminal state is refused."""
    store.submit(make_job("job:t"))
    store.transition("job:t", JobState.RUNNING, at(1))
    store.transition("job:t", JobState.FAILED, at(2), structured_error={"reason_code": "BOOM"})

    for target in (JobState.RUNNING, JobState.SUCCEEDED, JobState.QUEUED, JobState.CANCELLED):
        with pytest.raises((JobTransitionError, JobStoreError)):
            store.transition("job:t", target, at(3))


def scenario_illegal_transitions_are_refused(store: JobStore) -> None:
    """The edges `JOB_TRANSITIONS` does not declare.

    QUEUED -> WAITING_RESOURCE is the interesting one: a job that never started cannot be parked
    for a resource it never asked for, and allowing it would make "waiting on the world" and
    "waiting on the scheduler" indistinguishable -- which is the distinction UX-007 reads.
    """
    store.submit(make_job("job:i"))
    with pytest.raises(JobTransitionError):
        store.transition("job:i", JobState.WAITING_RESOURCE, at(1))
    with pytest.raises(JobTransitionError):
        store.transition("job:i", JobState.SUCCEEDED, at(1))


def scenario_queue_depth_counts_only_active_jobs(store: JobStore) -> None:
    """UX-007's Job queue depth, and why terminal jobs must not be counted.

    A depth that never falls is a health signal that never recovers, which trains an operator to
    ignore it.
    """
    store.submit(make_job("job:q1", idempotency_key="k1"))
    store.submit(make_job("job:q2", idempotency_key="k2"))
    store.transition("job:q2", JobState.RUNNING, at(1))
    store.transition("job:q2", JobState.WAITING_RESOURCE, at(2))
    assert store.active_depth(PROJECT) == 2

    store.submit(make_job("job:q3", idempotency_key="k3"))
    store.transition("job:q3", JobState.RUNNING, at(1))
    store.complete("job:q3", "k3", make_run("run:q3", job_id="job:q3"))
    assert store.active_depth(PROJECT) == 2, "a finished job is not queue depth"
    assert store.active_depth(OTHER_PROJECT) == 0


def scenario_the_recorded_run_traces_to_its_artifacts(store: JobStore) -> None:
    """EVI-009's provenance edge: a Run reference resolves to produced Artifact(s)."""
    store.submit(make_job("job:art"))
    store.transition("job:art", JobState.RUNNING, at(1))
    run = store.complete(
        "job:art",
        "idem:1",
        make_run("run:art", job_id="job:art", outputs=("art:x", "art:y")),
    )
    assert run.produced("art:x")
    assert run.produced("art:y")
    assert not run.produced("art:never-made")


#: A Run with NOTHING left at its default. Every §17.4 field carries a value that differs from
#: what the column would supply if the completion path dropped it -- non-empty arrays, non-empty
#: JSONB, a domain, warnings, numerical refs. That is the point: the defect this fixture exists
#: to catch was a completion path that silently replaced eight omitted fields with column
#: defaults, which is invisible against a fixture whose fields *are* the defaults.
FULL_MANIFEST: dict[str, object] = {
    "domain": "silicon_photonics",
    "input_artifacts": ("art:input-a", "art:input-b"),
    "input_parameters": {"sweep": "bias", "points": 7, "nested": {"solver": "fdtd"}},
    "conditions": {"bias_v": -2.0, "temperature_c": 25.0},
    "environment": {"os": "linux", "python": "3.12.10", "container": "sha256:abc"},
    "backend_validity": {"mesh_converged": True, "calibration_ref": "cal:2026-09"},
    "warnings": ("mesh near tolerance", "one sweep point extrapolated"),
    "numerical_array_refs": ("arr:sweep-1", "arr:sweep-2"),
}


def make_full_run(
    run_id: str = "run:full",
    *,
    job_id: str = "job:full",
    project_id: str = PROJECT,
    **overrides: object,
) -> Run:
    """A Run whose every §17.4 field is non-default. See ``FULL_MANIFEST``."""
    return make_run(
        run_id,
        job_id=job_id,
        project_id=project_id,
        outputs=("art:produced-1", "art:produced-2"),
        **{**FULL_MANIFEST, **overrides},
    )


def scenario_the_whole_run_manifest_survives_the_round_trip(store: JobStore) -> None:
    """REPAIR A. §17.4 has twenty-one fields and the PostgreSQL path persisted thirteen.

    The eight it dropped -- domain, input_artifacts, input_parameters, conditions, environment,
    backend_validity, warnings, numerical_array_refs -- were not rejected. They were silently
    replaced by column defaults, so `InMemoryJobStore` kept them and `SqlJobStore` did not, and
    the backend-free suite was green on the store that remembered.

    Those are exactly the fields that make a Run *replayable*. §10.3: 每次 backend 執行必須產生
    可重播的 manifest（§17.4）。缺少任一必要欄位即拒絕升級為正式 evidence. An execution whose
    environment and backend_validity were dropped on the way to storage is a Run nobody can
    replay, and nothing anywhere said so.

    The assertion is canonical model equality -- not field spot-checks, which is how eight
    missing fields went unnoticed in the first place.
    """
    store.submit(make_job("job:full", idempotency_key="idem:full"))
    store.transition("job:full", JobState.RUNNING, at(1))
    proposed = make_full_run()

    returned = store.complete("job:full", "idem:full", proposed)
    assert returned == proposed, "the completion path altered the Run it was given"

    reloaded = store.get_run(proposed.run_id)
    assert reloaded == proposed, (
        "the stored Run differs from the one submitted. Compare field by field: a value that "
        "came back as (), {} or None was dropped and replaced by a column default"
    )
    # Named explicitly as well, because equality on a model whose fields were *all* defaulted
    # would still pass if the fixture itself were weak.
    assert reloaded.domain == "silicon_photonics"
    assert reloaded.input_artifacts == ("art:input-a", "art:input-b")
    assert reloaded.input_parameters["nested"] == {"solver": "fdtd"}
    assert reloaded.conditions == {"bias_v": -2.0, "temperature_c": 25.0}
    assert reloaded.environment["python"] == "3.12.10"
    assert reloaded.backend_validity["mesh_converged"] is True
    assert reloaded.warnings == ("mesh near tolerance", "one sweep point extrapolated")
    assert reloaded.numerical_array_refs == ("arr:sweep-1", "arr:sweep-2")


def scenario_a_run_contradicting_its_job_is_refused_on_every_linkage_field(
    store: JobStore,
) -> None:
    """REPAIR A's other half: four fields, refused identically by both stores.

    Before the repair PostgreSQL *derived* trace_id and capability_id from the job while the
    in-memory store ignored them entirely -- so a contradictory callback was silently corrected
    in one backend and silently trusted in the other. Neither is acceptable and they were not
    even the same wrong.

    Checked rather than derived, because deriving hands the caller a record that disagrees with
    what it asked for and says nothing.
    """
    store.submit(make_job("job:link", idempotency_key="idem:link"))
    store.transition("job:link", JobState.RUNNING, at(1))

    contradictions = {
        "job_id": "job:somewhere-else",
        "project_id": OTHER_PROJECT,
        "capability_id": "cap:not-what-was-asked-for",
        "trace_id": "trc:another-trace",
    }
    for field, wrong in contradictions.items():
        payload: dict[str, object] = {"job_id": "job:link"}
        payload[field] = wrong
        bad = make_run("run:link", **payload)  # type: ignore[arg-type]
        with pytest.raises(JobStoreError) as caught:
            store.complete("job:link", "idem:link", bad)
        assert field in str(caught.value), (
            f"the refusal for a contradictory {field} does not name the field"
        )
        assert store.run_for_job("job:link") is None, f"a bad {field} still created a Run"


def scenario_a_failed_run_completes_its_job_as_failed(store: JobStore) -> None:
    """REPAIR B. One completion mechanism, including for executions that did not succeed.

    Before `006a` a FAILED run could not go through `job_complete` -- the job would have been
    marked SUCCEEDED -- so it went through `add_run`, which was the second, weaker path. Folding
    it in here is what lets that path be deleted rather than hardened.

    The Run is still recorded (§6.10 needs failed executions; §17.4 requires a manifest per
    execution) and the Job durably resolves to it, which is the invariant `add_run` could break.
    """
    store.submit(make_job("job:failed", idempotency_key="idem:failed"))
    store.transition("job:failed", JobState.RUNNING, at(1))

    failed = make_run("run:failed", job_id="job:failed", status=RunStatus.FAILED, outputs=())
    returned = store.complete("job:failed", "idem:failed", failed)
    assert returned == failed

    job = store.get("job:failed")
    assert job is not None
    assert job.state is JobState.FAILED, "a failed execution left its job in a non-failed state"
    assert job.result_run_id == "run:failed", (
        "the job does not resolve to its run. A Run whose Job does not point at it is citable "
        "with nothing recording whose output it is"
    )
    assert store.run_for_job("job:failed") == failed


#: Every scenario, so both backends run the same list and neither can quietly omit one.
SCENARIOS = (
    scenario_the_whole_run_manifest_survives_the_round_trip,
    scenario_a_run_contradicting_its_job_is_refused_on_every_linkage_field,
    scenario_a_failed_run_completes_its_job_as_failed,
    scenario_submit_is_idempotent_on_the_key,
    scenario_the_same_key_in_another_project_is_a_different_job,
    scenario_suspend_and_resume_round_trip,
    scenario_a_duplicate_completion_creates_no_second_run,
    scenario_a_completion_under_the_wrong_key_is_refused,
    scenario_a_terminal_job_cannot_be_reopened,
    scenario_illegal_transitions_are_refused,
    scenario_queue_depth_counts_only_active_jobs,
    scenario_the_recorded_run_traces_to_its_artifacts,
)
