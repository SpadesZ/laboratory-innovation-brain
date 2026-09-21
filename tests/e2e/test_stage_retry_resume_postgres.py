"""UX-004's retry half, with Jobs real (§17.22, §17.16, OPS-001).

§26's T-UX-004 row asks for a parser-failure fixture that leaves a retrievable raw artifact, a
stage retry that re-runs *only* the failed stage and reuses `raw_artifact_id`, and duplicate retry
callbacks that create no second Run.

M1-P1 could demonstrate the first clause and not the other two: without Job and Run, "reuses the
job identity" and "creates no second Run" had nothing to be true of. Both are now checkable, and
the third clause is deliberately asserted through `job_complete` rather than through the pipeline
-- the pipeline is not where callback idempotency lives, and a test that proved it there would be
proving it of the wrong layer.

THE FAILURE INJECTED IS A REAL ONE. The parser is replaced with one that raises on its first call
and works on its second, which is what a transient extraction failure looks like. Nothing patches
the outcome object.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import SensitivityLabel
from lab_brain.core.models.job import JobState
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.ingestion.pipeline import IngestionPipeline, IngestionStage, StageStatus
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.storage.postgres import PostgresIngestionWriter
from tests.evidence_fixtures import fixture_bytes
from tests.job_fixtures import at, make_job, make_run

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("UX-004"),
    pytest.mark.spec_test("T-UX-004"),
]

PROJECT = "prj:test"
ACTOR = "act:test"


class _FailsOnceParser:
    """Wraps the real parser and fails the first call. A transient extraction failure."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.calls = 0

    def parse(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("figure extraction timed out")
        return self._inner.parse(*args, **kwargs)  # type: ignore[attr-defined]


@pytest.fixture
def wiring(db, tmp_path):
    store = LocalArtifactStore(tmp_path)
    writer = PostgresIngestionWriter(db)

    def commit(artifact, occurrence) -> None:
        with db.transaction():
            writer.commit_rows(artifact, occurrence)

    pipeline = IngestionPipeline(store, commit, lambda a, o: None)
    pipeline._parser = _FailsOnceParser(pipeline._parser)
    return db, store, writer, pipeline


def test_a_parser_failure_leaves_the_raw_artifact_durable_and_retryable(wiring):
    """Clause one, unchanged from M1-P1 and re-asserted because the resume path depends on it."""
    _db, store, _writer, pipeline = wiring
    outcome = pipeline.ingest(
        fixture_bytes(),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///report.md",
    )
    assert outcome.raw_artifact_is_durable
    assert outcome.result_for(IngestionStage.PARSE_TEXT).status is StageStatus.FAILED
    assert outcome.evidence_units == ()
    # The bytes are retrievable, which is what makes "no re-upload" possible at all.
    assert store.open(outcome.artifact.content_hash) == fixture_bytes()


def test_a_retry_resumes_at_the_failed_stage_and_reuses_the_raw_artifact(wiring):
    """Clause two. The retry passes the *stored* Artifact; no bytes are supplied again.

    Two things are asserted that a weaker test would skip: the artifact id is the same object the
    first attempt stored, and the earlier stages report SKIPPED rather than being absent. An item
    whose history began at PARSE_TEXT is indistinguishable from one whose raw store never
    happened, which UX-001 reads as FAILED.
    """
    db, _store, writer, pipeline = wiring
    first = pipeline.ingest(
        fixture_bytes(),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///report.md",
    )
    assert first.result_for(IngestionStage.PARSE_TEXT).status is StageStatus.FAILED

    resumed = pipeline.resume(
        artifact=first.artifact,
        occurrence=first.occurrence,
        item_id=first.item_id,
        project_id=PROJECT,
        actor_id=ACTOR,
    )

    assert resumed.item_id == first.item_id, "a retry continues an item, it does not start one"
    assert resumed.artifact.artifact_id == first.artifact.artifact_id
    assert resumed.result_for(IngestionStage.SECRET_SCAN).status is StageStatus.SKIPPED
    assert resumed.result_for(IngestionStage.RAW_STORE).status is StageStatus.SKIPPED
    assert resumed.result_for(IngestionStage.PARSE_TEXT).status is StageStatus.SUCCEEDED
    assert resumed.evidence_units, "the resumed run produced no evidence"

    writer.persist_evidence(resumed.evidence_units, resumed.evidence_occurrences)
    stored = db.execute("SELECT count(*) FROM artifacts").fetchone()[0]
    assert stored == 1, "the retry created a second artifact instead of reusing the first"


def test_the_retry_does_not_re_run_the_secret_scan(wiring):
    """SEC-003's verdict is a property of the bytes, and the bytes have not changed.

    Asserted by instrumenting the scanner rather than by reading the stage result, because a
    pipeline that re-scanned and then recorded SKIPPED would pass the assertion above.
    """
    _db, _store, _writer, pipeline = wiring
    scans = {"count": 0}
    inner = pipeline._scanner

    class _Counting:
        def scan(self, data: bytes):  # type: ignore[no-untyped-def]
            scans["count"] += 1
            return inner.scan(data)

    pipeline._scanner = _Counting()

    first = pipeline.ingest(
        fixture_bytes(),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///report.md",
    )
    assert scans["count"] == 1

    pipeline.resume(
        artifact=first.artifact,
        occurrence=first.occurrence,
        item_id=first.item_id,
        project_id=PROJECT,
        actor_id=ACTOR,
    )
    assert scans["count"] == 1, "the retry re-scanned bytes whose verdict was already recorded"


def test_duplicate_retry_callbacks_create_no_second_run(db):
    """Clause three, asserted at the layer that owns it.

    A retry is a new attempt of the same Job. Whatever the deliverer does -- one callback, three,
    two at once -- the Job resolves to one Run. This is `006_jobs_runs.sql`'s guarantee and is
    tested here against the retry *scenario* rather than in the abstract.
    """
    store = SqlJobStore(db)
    job = store.submit(make_job("job:retry", max_attempts=3))
    store.transition("job:retry", JobState.RUNNING, at(1))
    # Attempt one fails; the job is retried rather than finished.
    retried = store.transition(
        "job:retry",
        JobState.WAITING_RESOURCE,
        at(2),
        resume_stage=IngestionStage.PARSE_TEXT.value,
        attempt_count=1,
    )
    assert retried.resume_stage == "PARSE_TEXT"
    assert retried.attempts_remaining == 2

    store.transition("job:retry", JobState.RUNNING, at(3))
    first = store.complete("job:retry", job.idempotency_key, make_run("run:1", job_id="job:retry"))
    again = store.complete("job:retry", job.idempotency_key, make_run("run:2", job_id="job:retry"))

    assert first.run_id == again.run_id == "run:1"
    total = db.execute("SELECT count(*) FROM runs WHERE job_id = 'job:retry'").fetchone()[0]
    assert total == 1


def test_the_resumed_job_keeps_its_identity_across_the_retry(db):
    """ "reuses ... Job identity". A retry must not become a new submission.

    The retry resubmits under the same idempotency key, which is what a client that is unsure
    whether its retry landed would do. One job, not two, and the attempt count is preserved.
    """
    store = SqlJobStore(db)
    original = store.submit(make_job("job:same", idempotency_key="idem:retry", max_attempts=3))
    store.transition("job:same", JobState.RUNNING, at(1))
    store.transition("job:same", JobState.WAITING_RESOURCE, at(2), attempt_count=1)

    resubmitted = store.submit(
        make_job("job:different-id", idempotency_key="idem:retry", max_attempts=3)
    )
    assert resubmitted.job_id == original.job_id
    assert resubmitted.attempt_count == 1, "the resubmission reset the attempt count"
    assert resubmitted.state is JobState.WAITING_RESOURCE
    assert store.get("job:different-id") is None
