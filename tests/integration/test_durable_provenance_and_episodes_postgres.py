"""LLM-001 and OPS-001 — the two clauses that were asserted without being durable.

    "all scientific LLM calls persist bundle+provenance"   was an in-memory object
    "delayed mock job resumes episode"                     was a Job surviving a reload

Both are now written to PostgreSQL and read back **through a new connection**, because that is the
only thing that distinguishes persistence from a variable. Every equality assertion below is on
the whole model, not on a field somebody remembered to check.
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from lab_brain.cognition.llm import BeliefBasisGate, LLMRefusal, ScientificOutput
from lab_brain.core.models.episode import EpisodeState, ResearchEpisode
from lab_brain.core.models.inference import InferenceProvenance, LogicalSlot
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.episodes import EpisodeStoreError, SqlEpisodeStore
from lab_brain.core.repositories.inference import (
    InferenceStoreError,
    SqlInferenceProvenanceStore,
)
from lab_brain.core.repositories.jobs import SqlJobStore
from tests.postgres_fixtures import database_url

pytestmark = [pytest.mark.postgres]

PROJECT = "prj:test"
NOW = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.UTC)
TRACE = "trc:durable"


def _provenance(inference_id: str = "inf:1", **overrides) -> InferenceProvenance:
    payload = {
        "inference_id": inference_id,
        "role": "hypothesis_generator",
        "logical_slot": LogicalSlot.HYPOTHESIS,
        "provider": "local",
        "model_id": "toy-model",
        "model_version": "1.0.0",
        "prompt_id": "prm:hypothesis",
        "prompt_version": "3.1.0",
        "evidence_bundle_hash": "sha256:" + "a" * 64,
        "source_policy_version": "sp:diagnosis@1.0.0",
        # Deliberately non-default and nested: a JSONB round trip that flattened this would show
        # up here and nowhere else.
        "parameters": {"temperature": 0.0, "seed": 7, "nested": {"reasoning_mode": "strict"}},
        "created_at": NOW,
        "trace_id": TRACE,
    }
    payload.update(overrides)
    return InferenceProvenance.model_validate(payload)


def _output(
    inference_id: str = "inf:1", text: str = "Cj falls as depletion widens."
) -> ScientificOutput:
    return ScientificOutput(text=text, provenance=_provenance(inference_id))


# ---------------------------------------------------------------------------
# LLM-001 — durable provenance
# ---------------------------------------------------------------------------


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_provenance_survives_a_new_connection_with_exact_equality(db):
    """THE durability probe. Write here, read through a connection that shares nothing.

    Exact model equality, not field spot-checks: the previous implementation's defect was that
    "persisted" described an object that never left the process, and a test asserting three
    fields would have passed against a dict.
    """
    written = SqlInferenceProvenanceStore(db).record(_output(), project_id=PROJECT)

    with psycopg.connect(database_url(), autocommit=True) as fresh:
        reloaded = SqlInferenceProvenanceStore(fresh).get("inf:1")
        assert reloaded is not None
        assert reloaded == written, "the stored provenance differs from what was submitted"
        assert reloaded.parameters == {
            "temperature": 0.0,
            "seed": 7,
            "nested": {"reasoning_mode": "strict"},
        }
        assert reloaded.evidence_bundle_hash == "sha256:" + "a" * 64
        assert reloaded.logical_slot is LogicalSlot.HYPOTHESIS


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_the_output_text_is_stored_beside_its_provenance(db):
    """§7.6 sends an unprovenanced inference to a human. Provenance with no record of what the
    inference SAID cannot be reviewed by that human."""
    store = SqlInferenceProvenanceStore(db)
    store.record(_output(text="a specific scientific claim"), project_id=PROJECT)
    assert store.output_for("inf:1") == "a specific scientific claim"


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_stored_inference_cannot_be_rewritten(db):
    """Append-only, enforced by `003d`.

    §7.6 judges belief admissibility against this row, so a record that can be edited is one that
    can be made to claim a model, prompt or evidence bundle it did not come from.
    """
    store = SqlInferenceProvenanceStore(db)
    store.record(_output(), project_id=PROJECT)

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute(
            "UPDATE inference_provenance SET model_id = 'gpt-9' WHERE inference_id = 'inf:1'"
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("DELETE FROM inference_provenance WHERE inference_id = 'inf:1'")


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_recording_the_same_inference_twice_is_a_no_op_and_a_conflicting_one_is_refused(db):
    """A retried write of the same record is fine; a different record under one id is not."""
    store = SqlInferenceProvenanceStore(db)
    first = store.record(_output(), project_id=PROJECT)
    again = store.record(_output(), project_id=PROJECT)
    assert first == again

    different = ScientificOutput(text="something else", provenance=_provenance(model_id="gpt-9"))
    with pytest.raises(InferenceStoreError, match="different provenance"):
        store.record(different, project_id=PROJECT)


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_the_belief_basis_gate_reads_the_durable_record(db):
    """§26: 僅測 admission 不足以通過. The read side must consult the STORE.

    Two inferences: one recorded, one that exists only as an id somebody kept. The gate must
    distinguish them by going to the database, not by consulting a set a caller supplied.
    """
    store = SqlInferenceProvenanceStore(db)
    store.record(_output("inf:modern"), project_id=PROJECT)

    gate = BeliefBasisGate(
        load_provenance=store.get, is_inference=lambda ref: ref.startswith("inf:")
    )
    assert gate.evaluate(["inf:modern"]).permitted
    assert not gate.evaluate(["inf:legacy-never-recorded"]).permitted
    with pytest.raises(LLMRefusal):
        gate.require(["inf:legacy-never-recorded"])

    # And across a reload, because a gate reading process memory would pass the above too.
    with psycopg.connect(database_url(), autocommit=True) as fresh:
        fresh_gate = BeliefBasisGate(
            load_provenance=SqlInferenceProvenanceStore(fresh).get,
            is_inference=lambda ref: ref.startswith("inf:"),
        )
        assert fresh_gate.evaluate(["inf:modern"]).permitted
        assert not fresh_gate.evaluate(["inf:legacy-never-recorded"]).permitted


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_inferences_are_findable_by_their_canonical_bundle_hash(db):
    """The query EVI-006's hash exists to make answerable, and §6.18's rollback selects on it."""
    store = SqlInferenceProvenanceStore(db)
    store.record(_output("inf:a"), project_id=PROJECT)
    store.record(_output("inf:b"), project_id=PROJECT)
    store.record(
        ScientificOutput(
            text="other evidence",
            provenance=_provenance("inf:c", evidence_bundle_hash="sha256:" + "b" * 64),
        ),
        project_id=PROJECT,
    )
    found = store.list_for_bundle("sha256:" + "a" * 64)
    assert [p.inference_id for p in found] == ["inf:a", "inf:b"]


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_blank_bundle_hash_cannot_be_stored(db):
    """The database refuses it too, for writers that never touch the repository."""
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO inference_provenance (inference_id, role, logical_slot, model_id, "
            "model_version, prompt_id, prompt_version, evidence_bundle_hash, created_at, "
            "trace_id, project_id, output_text) VALUES "
            "('inf:blank', 'r', 'HYPOTHESIS', 'm', '1', 'p', '1', '  ', now(), 't', %s, 'x')",
            (PROJECT,),
        )


# ---------------------------------------------------------------------------
# OPS-001 — the episode resumes, not merely the job
# ---------------------------------------------------------------------------


def _episode(episode_id: str = "epi:1") -> ResearchEpisode:
    return ResearchEpisode(
        episode_id=episode_id,
        project_id=PROJECT,
        trace_id=TRACE,
        goal="explain the Rs anomaly",
        state=EpisodeState.EVIDENCE_GATHERING,
        start_time=NOW,
    )


def _job(job_id: str = "job:1", *, episode_id: str | None = "epi:1", trace: str = TRACE) -> Job:
    return Job(
        job_id=job_id,
        project_id=PROJECT,
        episode_id=episode_id,
        capability_id="cap:ingest_document",
        trace_id=trace,
        idempotency_key=f"idem:{job_id}",
        submitted_at=NOW,
    )


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_the_episode_itself_suspends_and_resumes_across_a_reload(db):
    """THE exit-gate clause, read as written.

    A Job surviving a restart proves the Job is durable. What the gate says is that the EPISODE
    resumes -- so the episode is parked, a connection that shares nothing finds it parked, and
    the SAME episode id is resumed.
    """
    episodes = SqlEpisodeStore(db)
    episodes.open(_episode())
    SqlJobStore(db).submit(_job())

    parked = episodes.suspend("epi:1", reason="awaiting a Lumerical seat", at=NOW)
    assert parked.state is EpisodeState.SUSPENDED
    assert parked.suspended_at == NOW
    assert parked.suspend_reason == "awaiting a Lumerical seat"

    with psycopg.connect(database_url(), autocommit=True) as fresh:
        after_restart = SqlEpisodeStore(fresh)
        found = after_restart.get("epi:1")
        assert found is not None
        assert found.state is EpisodeState.SUSPENDED
        assert found == parked, "the reloaded episode differs from the parked one"

        resumed = after_restart.resume("epi:1")
        assert resumed.episode_id == "epi:1", "a DIFFERENT episode was resumed"
        assert resumed.state is EpisodeState.EVIDENCE_GATHERING
        assert resumed.suspended_at is None
        assert resumed.suspend_reason is None
        assert after_restart.jobs_of("epi:1") == ("job:1",)


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_the_resulting_run_is_associated_back_to_the_episodes_trace(db):
    """§12.5's chain: episode → job → run → artifact, on one trace."""
    from tests.job_fixtures import make_run

    SqlEpisodeStore(db).open(_episode())
    jobs = SqlJobStore(db)
    jobs.submit(_job())
    jobs.transition("job:1", JobState.RUNNING, NOW)
    run = jobs.complete(
        "job:1",
        "idem:job:1",
        make_run(
            "run:1",
            job_id="job:1",
            project_id=PROJECT,
            trace_id=TRACE,
            # This file's clock is a day after `job_fixtures`' default, and `006`'s
            # `jobs_finished_after_started` correctly refuses a run that ends before its job
            # started. Stated explicitly rather than by moving either clock: the constraint is
            # right and the fixture was the thing that disagreed.
            start_time=NOW + dt.timedelta(seconds=10),
            end_time=NOW + dt.timedelta(seconds=20),
        ),
    )
    assert run.trace_id == TRACE
    assert SqlEpisodeStore(db).get("epi:1").trace_id == run.trace_id


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_job_on_another_trace_cannot_join_an_episode(db):
    """The head of §12.5's chain, held by the database.

    `006a` refuses a Run that leaves its Job's trace; this closes the same gap one link earlier.
    Without it an episode could hold jobs on three traces and a reassembled trace would silently
    contain a third of the work.
    """
    SqlEpisodeStore(db).open(_episode())
    with pytest.raises(psycopg.errors.RaiseException, match="one trace through"):
        SqlJobStore(db).submit(_job("job:detached", trace="trc:somewhere-else"))


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_job_naming_an_episode_that_does_not_exist_is_refused(db):
    """`006` left `episode_id` unchecked because §17.3 was not built. It is now."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        SqlJobStore(db).submit(_job("job:orphan", episode_id="epi:ghost"))


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_job_with_no_episode_is_still_allowed(db):
    """A watcher drop has no research activity behind it.

    Making `episode_id` mandatory would force callers to invent an episode, and an invented
    episode is a worse record than an absent one.
    """
    stored = SqlJobStore(db).submit(_job("job:standalone", episode_id=None))
    assert stored.episode_id is None


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_suspend_and_resume_are_idempotent(db):
    """The worker that resumes a suspended episode may itself have restarted mid-resume."""
    episodes = SqlEpisodeStore(db)
    episodes.open(_episode())
    first = episodes.suspend("epi:1", reason="seat", at=NOW)
    again = episodes.suspend("epi:1", reason="different reason", at=NOW + dt.timedelta(hours=1))
    assert again == first, "a second suspend rewrote the parking record"

    episodes.resume("epi:1")
    twice = episodes.resume("epi:1")
    assert twice.state is EpisodeState.EVIDENCE_GATHERING


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_finished_episode_cannot_be_suspended_or_resumed(db):
    episodes = SqlEpisodeStore(db)
    episodes.open(_episode())
    episodes.close("epi:1", outcome="ANSWERED", at=NOW + dt.timedelta(hours=2))

    with pytest.raises(EpisodeStoreError, match="already"):
        episodes.suspend("epi:1", reason="too late", at=NOW)
    with pytest.raises(EpisodeStoreError, match="already"):
        episodes.resume("epi:1")


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_episode_membership_is_a_query_not_an_array(db):
    """§17.8 forbids the parallel-array shape: two sources of truth disagree silently."""
    episodes = SqlEpisodeStore(db)
    episodes.open(_episode())
    jobs = SqlJobStore(db)
    jobs.submit(_job("job:a"))
    jobs.submit(_job("job:b"))
    assert episodes.jobs_of("epi:1") == ("job:a", "job:b")

    columns = db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'research_episodes'"
    ).fetchall()
    names = {row[0] for row in columns}
    assert "job_ids" not in names
    assert "run_ids" not in names


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_suspended_episode_must_record_when_it_parked():
    """Found by the mutation battery, not by design.

    `a_suspended_episode_need_not_record_when` SURVIVED: every other test reaches the model
    through `episode_suspend`, which sets the state and the timestamp in one statement, so the
    model's own validator was never the thing that caught a contradictory pair. A reader would
    have believed that check was load-bearing, and a future caller constructing a
    `ResearchEpisode` directly -- a replay, a fixture, a migration backfill -- would have got a
    SUSPENDED episode with no `suspended_at`, which a resumer reads as "parked at the epoch".

    Both directions, because each is a different lie: SUSPENDED without a timestamp, and a
    timestamp on an episode that is running.
    """
    base = {
        "episode_id": "epi:bad",
        "project_id": PROJECT,
        "trace_id": TRACE,
        "goal": "g",
        "start_time": NOW,
    }
    with pytest.raises(ValueError, match="suspended_at"):
        ResearchEpisode.model_validate({**base, "state": EpisodeState.SUSPENDED})
    with pytest.raises(ValueError, match="suspended_at"):
        ResearchEpisode.model_validate(
            {**base, "state": EpisodeState.EVIDENCE_GATHERING, "suspended_at": NOW}
        )


@pytest.mark.requirement("OPS-001")
@pytest.mark.spec_test("T-OPS-001")
def test_a_terminal_episode_must_record_when_it_ended():
    """The same shape one field over, and the same reason it is worth asserting directly."""
    base = {
        "episode_id": "epi:bad",
        "project_id": PROJECT,
        "trace_id": TRACE,
        "goal": "g",
        "start_time": NOW,
    }
    with pytest.raises(ValueError, match="end_time"):
        ResearchEpisode.model_validate({**base, "state": EpisodeState.COMPLETED})
    with pytest.raises(ValueError, match="end_time"):
        ResearchEpisode.model_validate(
            {**base, "state": EpisodeState.EVIDENCE_GATHERING, "end_time": NOW}
        )
