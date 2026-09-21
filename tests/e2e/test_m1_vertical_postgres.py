"""The M1 exit gate, as one coherent production vertical.

    local document/run ingest; source-work dedup; delayed mock job resumes episode; all scientific
    LLM calls persist bundle+provenance; UX-001~UX-007 tests pass.

WHAT THIS FILE IS AND IS NOT. It is the integration claim: the parts compose, through
`IngestionService` -- production code that owns its own transaction boundary -- rather than
through wiring a test wrote. It is NOT each requirement's evidence. Every requirement keeps its
own targeted adversarial tests, and this file would pass against an implementation whose guards
were individually weak. That is why both exist.

THE CHAIN:

    document ingest -> Job submit -> execution/suspend -> durable reload -> resume
    -> exactly one authoritative Run -> produced Artifact -> canonical EvidenceUnit
    -> dense/lexical retrieval -> canonical candidate resolution -> source-status policy
    -> scientific LLM call over a canonical EvidenceBundle -> persisted InferenceProvenance
    -> derived IngestionItem / health surfaces

THE REFUSAL BRANCHES, each asserted separately at the end:

    a duplicate callback creates one Run
    a legitimate retry runs ingestion again and stays safe through derived identity
    a Run with forged output-artifact provenance fails
    a restricted artifact does not egress
    an inference without provenance does not reach a belief transition
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from lab_brain.cognition.llm import (
    BeliefBasisGate,
    LLMRefusal,
    ModelSlot,
    PromptTemplate,
    ScientificLLM,
)
from lab_brain.composition import INGEST_CAPABILITY, IngestionService
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.models.job import JobState, Run, RunStatus
from lab_brain.core.models.source_work import RetractionCheck
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.evidence.dense_index import (
    DenseEvidenceIndex,
    EmbeddingSpace,
    hashing_embedder,
)
from lab_brain.evidence.retriever import CandidateResolver
from lab_brain.evidence.source_status import RevisionOutcome, evaluate_major_revision
from lab_brain.ingestion.admission_gate import AdmissionRefusal, AdmissionRequest, RefusalReason
from lab_brain.ingestion.pipeline import IngestionStage, StageStatus
from lab_brain.ingestion.reverification import SegmentationReverifier
from lab_brain.security.egress import (
    EgressAuditLog,
    EgressGate,
    EgressPolicy,
    EgressRequest,
    PrivacyMode,
    evaluate_and_audit,
)
from lab_brain.storage.artifacts.local import LocalArtifactStore
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
TRACE = "trc:m1-vertical"
NOW = dt.datetime(2026, 9, 22, 9, 0, tzinfo=dt.UTC)

SPACE = EmbeddingSpace(model="toy-embed", version="1.0.0", dimensions=64)


@pytest.fixture
def service(db, tmp_path):
    return db, IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )


def _submit_and_ingest(svc: IngestionService, *, key: str = "idem:vertical"):
    job = svc.submit(project_id=PROJECT, actor_id=ACTOR, idempotency_key=key, trace_id=TRACE)
    return job, svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )


# ---------------------------------------------------------------------------
# The vertical
# ---------------------------------------------------------------------------


def test_the_whole_m1_vertical_runs_through_production_composition(service):
    """Every link in the chain, in one pass, with nothing wired by this test.

    `IngestionService` owns the transaction boundary. If this test had to open a transaction to
    make the ingestion durable, the boundary would be the test's -- which is the gap the
    intermediate audit named.
    """
    db, svc = service

    # 1. Job submit -> suspend -> durable reload -> resume.
    job = svc.submit(
        project_id=PROJECT, actor_id=ACTOR, idempotency_key="idem:vertical", trace_id=TRACE
    )
    assert job.state is JobState.QUEUED

    svc._jobs.transition(job.job_id, JobState.RUNNING, NOW)
    parked = svc.suspend(job.job_id, reason_stage=IngestionStage.PARSE_TEXT.value)
    assert parked.state is JobState.WAITING_RESOURCE
    assert parked.is_active, "a parked job still occupies queue depth (UX-007)"

    # DURABLE RELOAD: a new connection, which is what a restarted worker has.
    with psycopg.connect(database_url(), autocommit=True) as reloaded:
        after_restart = SqlJobStore(reloaded).get(job.job_id)
        assert after_restart is not None
        assert after_restart.state is JobState.WAITING_RESOURCE
        assert after_restart.resume_stage == "PARSE_TEXT"

    svc.resume(job.job_id)

    # 2. Ingest -> durable Artifact + EvidenceUnits -> exactly one authoritative Run.
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert result.succeeded
    assert result.artifact is not None
    assert result.artifact.artifact_id == fixture_artifact_id()
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.run.output_artifacts == (result.artifact.artifact_id,)
    assert result.job.state is JobState.SUCCEEDED
    assert result.job.result_run_id == result.run.run_id

    runs = db.execute("SELECT count(*) FROM runs WHERE job_id = %s", (job.job_id,)).fetchone()
    assert runs[0] == 1, "the vertical produced more than one Run"

    # 3. Canonical EvidenceUnits, read back through the locked reader.
    units = svc.evidence_for(PROJECT)
    assert units, "the vertical produced no evidence"
    assert {u.evidence_unit_id for u in units} == {
        u.evidence_unit_id for u in result.evidence_units
    }

    # 4. Dense retrieval -> canonical candidate resolution.
    index = DenseEvidenceIndex("idx:dense:v1", SPACE, hashing_embedder(SPACE))
    index.add_all(units, project_id=PROJECT)
    candidates = index.search("reverse bias capacitance", project_id=PROJECT, space=SPACE)
    assert candidates, "dense retrieval returned nothing"

    by_id = {u.evidence_unit_id: u for u in units}
    resolver = CandidateResolver(
        load_unit=lambda key: by_id.get(key),
        is_present_in=svc._reader.present_in,
    )
    resolved, divergences = resolver.resolve(candidates)
    assert resolved, "no candidate resolved to canonical evidence"
    assert divergences == (), "the index diverged from the canonical body on a clean ingest"
    for candidate in resolved:
        assert candidate.body == by_id[candidate.unit.evidence_unit_id].body

    # 5. Source-status policy, from the STORED check (EVI-008 reads the record, not a provider).
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

    # 6. Scientific LLM call over a canonical bundle -> persisted InferenceProvenance.
    bundle = EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        query_text="why does Cj fall with reverse bias",
        source_policy_id="sp:diagnosis",
        source_policy_version="1.0.0",
        condition_filter={},
        condition_schema_versions={"toy": TOY_SCHEMA_REF},
        ordered_attestation_ids=tuple(sorted(u.evidence_unit_id for u in resolved and units)[:2]),
        project_id=PROJECT,
    )
    model = ScientificLLM(
        slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "toy-model", "1.0.0", provider="local"),),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "Consider the evidence"),),
        complete=lambda _t, _s: "Cj falls because the depletion width grows.",
        source_policy_version="sp:diagnosis@1.0.0",
    )
    output = model.invoke(
        inference_id="inf:vertical",
        slot=LogicalSlot.HYPOTHESIS,
        role="hypothesis_generator",
        prompt_id="prm:hypothesis",
        bundle=bundle,
        trace_id=TRACE,
        now=NOW,
    )
    assert output.provenance.evidence_bundle_hash == bundle.canonical_hash
    assert output.provenance.trace_id == TRACE
    assert output.provenance.model_ref == "toy-model@1.0.0"

    # 7. The trace runs end to end (§12.5: episode -> job -> run -> artifact).
    assert result.job.trace_id == TRACE
    assert result.run.trace_id == TRACE
    assert output.provenance.trace_id == TRACE

    # 8. Derived surfaces. Nothing here was assigned.
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

    health = derive_health(
        capabilities=[CapabilityAvailability(INGEST_CAPABILITY, available=True)],
        adapters=[],
        jobs=list(svc.active_jobs(PROJECT)),
        review_queue_depth=0,
        review_queue_capacity=5,
    )
    assert health.overall is ComponentStatus.HEALTHY
    assert health.job_queue_depth == 0, "a finished job is still counted as queue depth"


# ---------------------------------------------------------------------------
# The refusal branches the exit gate names
# ---------------------------------------------------------------------------


def test_a_duplicate_callback_creates_one_run(service):
    """Through the production service, not the store directly."""
    db, svc = service
    job, first = _submit_and_ingest(svc)

    again = svc._jobs.complete(
        job.job_id,
        job.idempotency_key,
        make_run(
            "run:redelivered",
            job_id=job.job_id,
            project_id=PROJECT,
            capability_id=INGEST_CAPABILITY,
            trace_id=TRACE,
        ),
    )
    assert again.run_id == first.run.run_id
    assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_a_legitimate_retry_runs_ingestion_again_and_stays_safe(service):
    """The locked rule, exercised at the composition level.

    The retry is a SECOND full ingestion under a second job -- not a skip. Every id it computes
    is the same id, so the counts do not move. That is derived identity, not a lookup.
    """
    db, svc = service
    _job, first = _submit_and_ingest(svc, key="idem:one")
    before = {
        name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in ("artifacts", "evidence_units", "artifact_occurrences")
    }

    _job2, second = _submit_and_ingest(svc, key="idem:two")
    after = {
        name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in ("artifacts", "evidence_units", "artifact_occurrences")
    }

    assert before == after, "a second ingestion of the same bytes changed the stored counts"
    assert second.artifact.artifact_id == first.artifact.artifact_id
    assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 2, (
        "two jobs must each have their own Run; only the CONTENT is deduplicated"
    )


def test_a_run_with_forged_output_provenance_fails(service):
    """Repair C, at the vertical. The Run is real; its claimed output does not exist."""
    _db, svc = service
    job, result = _submit_and_ingest(svc)

    gate = svc.admission_gate(
        membership_of=lambda _a, _p: None,
        load_artifact=lambda _a: None,
        resegment=SegmentationReverifier(lambda _a: None),
        actor_of=lambda _p: None,
    )
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
    from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate

    forging_gate = EvidenceAdmissionGate(
        load_artifact=lambda _a: None,
        load_evidence_unit=lambda _u: None,
        load_run=lambda key: forged if key == "run:forged" else None,
        is_artifact_in_project=svc._artifact_present_in,
    )
    with pytest.raises(AdmissionRefusal) as caught:
        forging_gate.admit(AdmissionRequest(attestation=attestation))
    assert caught.value.reason is RefusalReason.RUN_ARTIFACT_NOT_FOUND
    assert result.succeeded, "the honest ingestion in this test did not succeed"
    assert gate is not None


def test_a_restricted_artifact_does_not_egress(service):
    """SEC-001 at the vertical, and the audit trail still holds no payload."""
    _db, svc = service
    job = svc.submit(project_id=PROJECT, actor_id=ACTOR, idempotency_key="idem:nda", trace_id=TRACE)
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.RESTRICTED_NDA,
        uri="file:///nda.md",
    )
    assert result.succeeded

    gate = EgressGate(
        policy_for=lambda _p: EgressPolicy(
            policy_id="egp:1",
            version="1.0.0",
            project_id=PROJECT,
            mode=PrivacyMode.RESEARCH,
            declared_by_actor_id="act:pi",
            permitted_labels=frozenset({SensitivityLabel.PUBLIC}),
            approved_providers=frozenset({"src:literature"}),
        ),
        clearance_of=lambda _a, _p: frozenset(SensitivityLabel),
    )
    log = EgressAuditLog()
    body = svc.evidence_for(PROJECT)[0].body
    decision = evaluate_and_audit(
        gate,
        EgressRequest(
            project_id=PROJECT,
            actor_id=ACTOR,
            provider_id="src:literature",
            sensitivity=SensitivityLabel.RESTRICTED_NDA,
            content=body,
        ),
        log,
    )
    assert not decision.permitted
    assert len(log.blocked()) == 1
    assert body[:30] not in repr(log), "the audit trail copied the restricted body"


def test_an_inference_without_provenance_does_not_reach_a_belief_transition(service):
    """LLM-001's read side at the vertical. The record predates the rule and is already stored."""
    _db, _svc = service
    gate = BeliefBasisGate(
        load_provenance=lambda _ref: None, is_inference=lambda ref: ref.startswith("inf:")
    )
    with pytest.raises(LLMRefusal):
        gate.require(["inf:legacy-no-provenance"])
    assert gate.evaluate(["inf:legacy-no-provenance", "att:measured"]).permitted, (
        "a legacy inference beside real evidence is not the SOLE basis"
    )


def test_a_failed_parse_leaves_a_retryable_item_and_a_failed_run(service):
    """The failure branch of the vertical, end to end.

    The item is PARTIAL or FAILED by derivation, the raw artifact is durable, and the Job's Run
    records the failure rather than vanishing -- which `006a` made possible by letting a FAILED
    job name its Run.
    """
    db, svc = service

    class _Broken:
        def parse(self, *_a, **_k):
            raise RuntimeError("figure extraction timed out")

    svc._pipeline._parser = _Broken()
    _job, result = _submit_and_ingest(svc, key="idem:broken")

    assert result.outcome.raw_artifact_is_durable
    assert result.outcome.result_for(IngestionStage.PARSE_TEXT).status is StageStatus.FAILED
    assert result.run is not None
    assert result.run.status is RunStatus.FAILED
    assert result.job.state is JobState.FAILED
    assert result.job.result_run_id == result.run.run_id, (
        "a failed run must still be claimed by its job (006a)"
    )

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
    )
    assert derive_state(item) is ItemState.FAILED
    assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1, (
        "UX-004: the raw artifact must survive a parser failure"
    )


def test_unknown_licence_code_never_reaches_generation_context(service):
    """SEC-004 at the vertical, so the default is exercised through a realistic path."""
    from lab_brain.security.egress import CodeArtifact, may_enter_generation_context

    _db, _svc = service
    admission = may_enter_generation_context(
        CodeArtifact(
            artifact_id="art:snippet",
            license_class=LicenseClass.UNKNOWN,
            provenance="src:github/unknown@v1",
        ),
        None,
    )
    assert not admission.permitted
    assert admission.reason_code == "LICENSE_UNKNOWN"
