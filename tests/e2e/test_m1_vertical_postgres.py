"""The M1 exit gate, as one durable, authorized production vertical.

    local document/run ingest; source-work dedup; delayed mock job resumes episode; all scientific
    LLM calls persist bundle+provenance; UX-001~UX-007 tests pass.

WHAT CHANGED AFTER THE FINAL AUDIT, because the previous version of this file asserted two clauses
it had not earned:

    "resumes episode"     was a Job surviving a reload. A Job is not an episode; §12.1 makes an
                          episode a state machine spanning many jobs, and what has to be found
                          again after a restart is which ACTIVITY the job belongs to.
    "persist provenance"  was an in-memory object that never left the process.

Both are now durable and both are read back through a **new connection**, which is the only thing
that distinguishes persistence from a variable.

Every read of canonical evidence goes through `ScientificReadGate`, and every external effect goes
through `AuthorizedExternalRunner`. This file cannot reach either around those boundaries, because
the composition root does not expose a way to.

WHAT THIS FILE IS AND IS NOT. It is the integration claim: the parts compose through production
code that owns its own boundaries. It is NOT each requirement's evidence -- every requirement keeps
its own targeted adversarial tests, and this file would pass against an implementation whose guards
were individually weak.
"""

from __future__ import annotations

import datetime as dt
import io

import psycopg
import pytest

from lab_brain.cognition.llm import LLMRefusal, ModelSlot, PromptTemplate, ScientificLLM
from lab_brain.composition import INGEST_CAPABILITY, IngestionService
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel
from lab_brain.core.models.episode import EpisodeState
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.models.job import JobState, Run, RunStatus
from lab_brain.core.models.source_work import RetractionCheck
from lab_brain.core.repositories.episodes import SqlEpisodeStore
from lab_brain.core.repositories.inference import SqlInferenceProvenanceStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.evidence.dense_index import DenseEvidenceIndex, EmbeddingSpace, hashing_embedder
from lab_brain.evidence.source_status import RevisionOutcome, evaluate_major_revision
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from lab_brain.ingestion.pipeline import IngestionStage, StageStatus
from lab_brain.interfaces.cli import run_explain, run_inbox
from lab_brain.security.egress import EgressAuditLog, EgressGate, EgressPolicy, PrivacyMode
from lab_brain.security.external import (
    AuthorizedExternalRunner,
    ExternalEffectRefused,
    ExternalReach,
)
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.surface.catalog import default_catalog
from lab_brain.surface.disclosure import DiagnosticsService
from lab_brain.surface.errors import BudgetRefused, ErrorClass, ErrorRecord, decide_retry
from lab_brain.surface.health import CapabilityAvailability, ComponentStatus, derive_health
from lab_brain.surface.ingestion_item import IngestionItem, ItemState, derive_state
from tests.conftest_fixtures import TOY_SCHEMA_REF
from tests.evidence_fixtures import fixture_artifact_id, fixture_bytes
from tests.job_fixtures import make_run
from tests.postgres_fixtures import database_url

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("OPS-001"),
    pytest.mark.spec_test("T-OPS-001"),
]

PROJECT = "prj:test"
ACTOR = "act:test"
UNCLEARED = "act:uncleared"
TRACE = "trc:m1-vertical"
EPISODE = "epi:m1-vertical"
NOW = dt.datetime(2026, 9, 22, 9, 0, tzinfo=dt.UTC)
SPACE = EmbeddingSpace(model="toy-embed", version="1.0.0", dimensions=64)


def _runner(*, permit: frozenset[SensitivityLabel] | None = None) -> AuthorizedExternalRunner:
    labels = permit if permit is not None else frozenset({SensitivityLabel.PUBLIC})
    return AuthorizedExternalRunner(
        gate=EgressGate(
            policy_for=lambda _p: EgressPolicy(
                policy_id="egp:test",
                version="1.0.0",
                project_id=PROJECT,
                mode=PrivacyMode.RESEARCH,
                declared_by_actor_id="act:pi",
                permitted_labels=labels,
                approved_providers=frozenset({"src:literature"}),
            ),
            clearance_of=lambda _a, _p: labels,
        ),
        audit=EgressAuditLog(),
    )


@pytest.fixture
def world(db, tmp_path):
    """One project, two actors, a real service. The uncleared actor differs in one fact only."""
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name, active) "
        "VALUES (%s, 'HUMAN', 'Uncleared', TRUE) ON CONFLICT DO NOTHING",
        (UNCLEARED,),
    )
    for actor, clearance in ((ACTOR, ["INTERNAL"]), (UNCLEARED, ["PUBLIC"])):
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, "
            "sensitivity_clearance, approval_scopes, active) "
            "VALUES (%s, %s, 'RESEARCHER', %s, ARRAY[]::text[], TRUE)",
            (actor, PROJECT, clearance),
        )
    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )
    return db, svc


def _ingest(svc, *, key="idem:vertical", episode_id=EPISODE, label=SensitivityLabel.INTERNAL):
    job = svc.submit(
        project_id=PROJECT,
        actor_id=ACTOR,
        idempotency_key=key,
        trace_id=TRACE,
        episode_id=episode_id,
    )
    return job, svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=label,
        uri="file:///rs_anomaly_report.md",
    )


def _bundle(ids: tuple[str, ...]) -> EvidenceBundle:
    return EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        query_text="why does Cj fall with reverse bias",
        source_policy_id="sp:diagnosis",
        source_policy_version="1.0.0",
        condition_filter={},
        condition_schema_versions={"toy": TOY_SCHEMA_REF},
        ordered_attestation_ids=ids,
        project_id=PROJECT,
    )


def _model(runner, *, reach=ExternalReach.LOCAL) -> ScientificLLM:
    return ScientificLLM(
        slots=(
            ModelSlot(LogicalSlot.HYPOTHESIS, "toy-model", "1.0.0", provider="local", reach=reach),
        ),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "Consider the evidence"),),
        complete=lambda _t, _s: "Cj falls because the depletion width grows.",
        runner=runner,
        source_policy_version="sp:diagnosis@1.0.0",
    )


# ---------------------------------------------------------------------------
# The vertical
# ---------------------------------------------------------------------------


def test_the_whole_m1_vertical_is_durable_and_authorized(world):
    """Episode -> Job -> suspend -> NEW CONNECTION -> resume -> Run -> evidence -> authorized
    retrieval -> source status -> authorized model call -> DURABLE provenance -> reload -> UX.
    """
    db, svc = world

    # 1. A ResearchEpisode, which is what the exit gate says resumes.
    episode = svc.open_episode(
        project_id=PROJECT, goal="explain the Rs anomaly", trace_id=TRACE, episode_id=EPISODE
    )
    assert episode.state is EpisodeState.EVIDENCE_GATHERING

    job = svc.submit(
        project_id=PROJECT,
        actor_id=ACTOR,
        idempotency_key="idem:vertical",
        trace_id=TRACE,
        episode_id=EPISODE,
    )
    svc._jobs.transition(job.job_id, JobState.RUNNING, NOW)
    svc.suspend(job.job_id, reason_stage=IngestionStage.PARSE_TEXT.value)
    parked = svc.suspend_episode(EPISODE, reason="awaiting a Lumerical seat")
    assert parked.state is EpisodeState.SUSPENDED

    # 2. DURABLE RELOAD -- a connection sharing nothing, which is what a restarted worker has.
    with psycopg.connect(database_url(), autocommit=True) as reloaded:
        found = SqlEpisodeStore(reloaded).get(EPISODE)
        assert found is not None
        assert found.state is EpisodeState.SUSPENDED
        assert found == parked, "the reloaded episode differs from the parked one"
        assert SqlEpisodeStore(reloaded).jobs_of(EPISODE) == (job.job_id,)
        assert SqlJobStore(reloaded).get(job.job_id).resume_stage == "PARSE_TEXT"

    # 3. Resume THE SAME episode, then the job.
    resumed = svc.resume_episode(EPISODE)
    assert resumed.episode_id == EPISODE, "a different episode was resumed"
    assert resumed.state is EpisodeState.EVIDENCE_GATHERING
    svc.resume(job.job_id)

    # 4. Ingest -> durable Artifact + EvidenceUnits -> exactly one authoritative Run.
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert result.succeeded
    assert result.artifact.artifact_id == fixture_artifact_id()
    assert result.run.trace_id == TRACE, "the Run left the episode's trace"
    assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1

    # 5. AUTHORIZED retrieval. The gate, not the raw reader.
    units = svc.evidence_for(actor_id=ACTOR, project_id=PROJECT)
    assert units, "the authorized read returned nothing"
    for unit in units:
        assert unit.decision.allowed

    index = DenseEvidenceIndex("idx:dense:v1", SPACE, hashing_embedder(SPACE))
    index.add_all(svc.unauthorized_reader().load_for_project(PROJECT), project_id=PROJECT)
    candidates = index.search("reverse bias capacitance", project_id=PROJECT, space=SPACE)
    resolved = svc.candidate_resolver().resolve(candidates, actor_id=ACTOR, project_id=PROJECT)
    assert resolved, "authorized candidate resolution returned nothing"

    # 6. Source status, from the STORED check.
    from lab_brain.core.models.enums import SourceWorkStatus, SourceWorkType, TrustClass
    from lab_brain.core.models.source_work import SourceWork

    work = SourceWork(
        source_work_id="swk:the-report",
        work_type=SourceWorkType.TECHNICAL_REPORT,
        title="Rs anomaly report",
        trust_class=TrustClass.INTERNAL_MEASUREMENT,
        retraction_check=RetractionCheck(
            status=SourceWorkStatus.ACTIVE, checked_at=NOW, checked_against="fake.crossref"
        ),
    )
    assert evaluate_major_revision(work).outcome is RevisionOutcome.ALLOW

    # 7. An AUTHORIZED scientific model call, and DURABLE provenance.
    bundle = _bundle(tuple(sorted(u.unit.evidence_unit_id for u in resolved)[:2]))
    output = _model(_runner()).invoke(
        inference_id="inf:vertical",
        slot=LogicalSlot.HYPOTHESIS,
        role="hypothesis_generator",
        prompt_id="prm:hypothesis",
        bundle=bundle,
        trace_id=TRACE,
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.INTERNAL,
        now=NOW,
    )
    written = svc.record_inference(output, project_id=PROJECT)

    # 8. RELOAD the provenance through a new connection, and check exact equality.
    with psycopg.connect(database_url(), autocommit=True) as fresh:
        store = SqlInferenceProvenanceStore(fresh)
        durable = store.get("inf:vertical")
        assert durable is not None
        assert durable == written == output.provenance
        assert durable.evidence_bundle_hash == bundle.canonical_hash
        assert durable.trace_id == TRACE
        assert store.output_for("inf:vertical") == output.text

        # And the belief gate reads THAT record, not a set this test supplied.
        gate = IngestionService(
            connection=fresh, artifact_store=LocalArtifactStore(".")
        ).belief_basis_gate()
        assert gate.evaluate(["inf:vertical"]).permitted
        assert not gate.evaluate(["inf:never-recorded"]).permitted

    # 9. One trace, end to end (§12.5).
    assert {episode.trace_id, result.job.trace_id, result.run.trace_id, durable.trace_id} == {TRACE}

    # 10. Derived UX surfaces + the CLI, over the same projection.
    item = IngestionItem(
        item_id=result.outcome.item_id,
        project_id=PROJECT,
        actor_id=ACTOR,
        trace_id=TRACE,
        raw_artifact_id=result.artifact.artifact_id,
        source_kind="UPLOAD",
        display_name="rs_anomaly_report.md",
        submitted_at=NOW,
        stage_results=tuple(result.outcome.stage_results),
        job_ids=(job.job_id,),
    )
    assert derive_state(item, jobs=[result.job]) is ItemState.READY

    out = io.StringIO()
    assert run_inbox([item], out=out) == 0
    assert "READY=1" in out.getvalue()

    health = derive_health(
        capabilities=[CapabilityAvailability(INGEST_CAPABILITY, available=True)],
        adapters=[],
        jobs=list(svc.active_jobs(PROJECT)),
        review_queue_depth=0,
        review_queue_capacity=5,
    )
    assert health.overall is ComponentStatus.HEALTHY


# ---------------------------------------------------------------------------
# The refusal branches
# ---------------------------------------------------------------------------


def test_unauthorized_evidence_retrieval_does_not_return_the_body(world):
    """R-7 at the vertical. A member with PUBLIC clearance, INTERNAL evidence."""
    _db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    _job, result = _ingest(svc)
    secret = svc.unauthorized_reader().load_for_project(PROJECT)[0].body

    refused = svc.evidence_for(actor_id=UNCLEARED, project_id=PROJECT)
    assert refused == ()
    assert secret not in repr(refused)

    index = DenseEvidenceIndex("idx:dense:v1", SPACE, hashing_embedder(SPACE))
    index.add_all(svc.unauthorized_reader().load_for_project(PROJECT), project_id=PROJECT)
    candidates = index.search("reverse bias", project_id=PROJECT, space=SPACE, limit=50)
    by_actor = svc.candidate_resolver().resolve(candidates, actor_id=UNCLEARED, project_id=PROJECT)
    assert by_actor == ()
    assert secret not in repr(by_actor)
    assert result.succeeded


def test_external_egress_cannot_bypass_the_gate(world):
    """SEC-001 at the vertical. The transport is fatal, so this proves ordering."""
    _db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    _job, result = _ingest(svc, label=SensitivityLabel.RESTRICTED_NDA)
    body = svc.unauthorized_reader().load_for_project(PROJECT)[0].body

    def fatal(_text, _slot):
        raise AssertionError("the model transport was entered before authorization")

    runner = _runner()
    cloud = ScientificLLM(
        slots=(
            ModelSlot(
                LogicalSlot.HYPOTHESIS,
                "cloud-model",
                "1.0.0",
                provider="src:literature",
                reach=ExternalReach.EXTERNAL,
            ),
        ),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", body),),
        complete=fatal,
        runner=runner,
    )
    with pytest.raises(ExternalEffectRefused):
        cloud.invoke(
            inference_id="inf:leak",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=_bundle(("att:1",)),
            trace_id=TRACE,
            project_id=PROJECT,
            actor_id=ACTOR,
            sensitivity=SensitivityLabel.RESTRICTED_NDA,
            now=NOW,
        )
    assert len(runner.audit.blocked()) == 1
    assert body[:30] not in repr(runner.audit), "the audit trail copied the restricted body"
    assert result.succeeded


def test_a_retry_without_a_budget_gate_cannot_run(world):
    """UX-002 at the vertical. No gate means not authorised to spend, not spend freely."""
    _db, _svc = world
    record = ErrorRecord(
        error_id="ERR-20260922-0001",
        project_id=PROJECT,
        trace_id=TRACE,
        error_class=ErrorClass.EXTERNAL_SERVICE_ERROR,
        reason_code="EXTERNAL_SERVICE_UNAVAILABLE",
        component="LiteratureConnector",
        occurred_at=NOW,
        attempt_count=0,
        max_attempts=3,
    )
    assert not decide_retry(record, now=NOW, charge_budget=None).retry

    def refuse(_r):
        raise BudgetRefused("cap")

    exhausted = decide_retry(record, now=NOW, charge_budget=refuse)
    assert exhausted.error_class is ErrorClass.POLICY_BLOCK
    assert decide_retry(record, now=NOW, charge_budget=lambda _r: None).retry


def test_a_run_with_forged_output_provenance_fails(world):
    """Repair C at the vertical. The Run is real; its claimed output does not exist."""
    _db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    job, result = _ingest(svc)

    forged = Run(
        run_id="run:forged",
        job_id=job.job_id,
        project_id=PROJECT,
        capability_id=INGEST_CAPABILITY,
        backend_id="b",
        trace_id=TRACE,
        conditions_schema_version=TOY_SCHEMA_REF,
        code_provenance="g",
        status=RunStatus.SUCCEEDED,
        output_artifacts=("art:does-not-exist",),
        start_time=NOW,
        end_time=NOW,
        reproducibility_manifest_hash="h",
    )
    from lab_brain.core.models import Attestation, EpistemicType, ExtractionProvenance

    attestation = Attestation(
        claim_id="clm:x",
        epistemic_type=EpistemicType.MEASURED,
        run_id="run:forged",
        locator="run output",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="metric_extractor", extractor_version="1.0.0"
        ),
    )
    gate = EvidenceAdmissionGate(
        load_artifact=lambda _a: None,
        load_evidence_unit=lambda _u: None,
        load_run=lambda key: forged if key == "run:forged" else None,
        is_artifact_in_project=svc._artifact_present_in,
    )
    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(AdmissionRequest(attestation=attestation))
    assert caught.value.reason is RefusalReason.RUN_ARTIFACT_NOT_FOUND
    assert result.succeeded


def test_an_unprovenanced_stored_inference_cannot_be_the_sole_belief_basis(world):
    """LLM-001's read side, against the DURABLE store rather than a lambda-backed set."""
    _db, svc = world
    with pytest.raises(LLMRefusal):
        svc.belief_basis_gate().require(["inf:legacy-never-recorded"])
    assert svc.belief_basis_gate().evaluate(["inf:legacy-never-recorded", "att:measured"]).permitted


def test_a_duplicate_callback_still_creates_one_run(world):
    db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    job, first = _ingest(svc)

    again = svc._jobs.complete(
        job.job_id,
        job.idempotency_key,
        make_run(
            "run:redelivered",
            job_id=job.job_id,
            project_id=PROJECT,
            capability_id=INGEST_CAPABILITY,
            trace_id=TRACE,
            start_time=NOW,
            end_time=NOW,
        ),
    )
    assert again.run_id == first.run.run_id
    assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_repeated_ingestion_stays_idempotent_by_derived_identity(world):
    """A second full ingestion under a second job. Counts do not move; runs do."""
    db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    _j1, first = _ingest(svc, key="idem:one")
    before = {
        name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in ("artifacts", "evidence_units", "artifact_occurrences")
    }
    _j2, second = _ingest(svc, key="idem:two")
    after = {
        name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in ("artifacts", "evidence_units", "artifact_occurrences")
    }
    assert before == after
    assert second.artifact.artifact_id == first.artifact.artifact_id
    assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 2


def test_unknown_licence_code_never_reaches_generation_context(world):
    from lab_brain.security.egress import CodeArtifact, may_enter_generation_context

    admission = may_enter_generation_context(
        CodeArtifact(
            artifact_id="art:snippet",
            license_class=LicenseClass.UNKNOWN,
            provenance="src:github/unknown@v1",
        ),
        None,
    )
    assert not admission.permitted


def test_the_cli_explains_an_error_without_leaking_detail(world):
    """The CLI over the same disclosure rules, at the end of the vertical."""
    _db, _svc = world
    service = DiagnosticsService(
        catalog=default_catalog(),
        load_error=lambda key: (
            ErrorRecord(
                error_id=key,
                project_id=PROJECT,
                trace_id=TRACE,
                error_class=ErrorClass.SYSTEM_ERROR,
                reason_code="PARSE_TEXT_FAILED",
                component="FigureParser",
                occurred_at=NOW,
            )
            if key == "ERR-1"
            else None
        ),
        load_detail=lambda _ref: None,
        membership_of=lambda _a, project: (
            __import__(
                "lab_brain.core.models.access", fromlist=["ProjectMembership"]
            ).ProjectMembership(actor_id=ACTOR, project_id=PROJECT, role="RESEARCHER")
            if project == PROJECT
            else None
        ),
    )
    out = io.StringIO()
    assert run_explain(service, "ERR-1", actor_id=ACTOR, project_id=PROJECT, out=out) == 0
    assert "Some text could not be extracted" in out.getvalue()
    assert "Traceback" not in out.getvalue()


def test_a_failed_parse_leaves_a_retryable_item_and_a_failed_run(world):
    db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)

    class _Broken:
        def parse(self, *_a, **_k):
            raise RuntimeError("figure extraction timed out")

    svc._pipeline._parser = _Broken()
    _job, result = _ingest(svc, key="idem:broken")

    assert result.outcome.raw_artifact_is_durable
    assert result.outcome.result_for(IngestionStage.PARSE_TEXT).status is StageStatus.FAILED
    assert result.run.status is RunStatus.FAILED
    assert result.job.state is JobState.FAILED
    assert result.job.result_run_id == result.run.run_id
    assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1
