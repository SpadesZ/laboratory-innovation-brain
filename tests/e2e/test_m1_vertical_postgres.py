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

AND WHAT CHANGED AFTER THE SECOND AUDIT, because this file was itself the evidence for two claims
it undermined:

    it called `svc.unauthorized_reader()` to fetch canonical bodies -- so the production
    composition root still exported a bypass, and the M1 vertical was the caller proving it was
    reachable. The accessor is gone; a test that needs the low-level loader builds one.

    it composed `invoke(); record_inference()` by hand -- so the vertical demonstrated exactly the
    two-call shape whose gap leaves a model output with no durable provenance. It now calls the
    production operation, which does not return until the record is reloaded and compared.

    it ended with a CLI over an `ErrorRecord` the test constructed. It now runs the real `main()`
    against the durable `012` rows the ingestion wrote.

Every read of canonical evidence goes through `ScientificReadGate`, every external effect goes
through `AuthorizedExternalRunner`, and every egress classification is derived from
`ArtifactOccurrence` rows rather than declared by this file. It cannot reach around any of them,
because the composition root does not expose a way to.

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
from lab_brain.core.repositories.evidence import SqlAttestationStore
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
from lab_brain.interfaces.cli import main
from lab_brain.interfaces.config import DSN_VARIABLE
from lab_brain.security.egress import EgressAuditLog, EgressGate, EgressPolicy, PrivacyMode
from lab_brain.security.external import (
    AuthorizedExternalRunner,
    ExternalEffectRefused,
    ExternalReach,
)
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.storage.postgres.evidence_units import PostgresEvidenceUnitReader
from lab_brain.surface.errors import BudgetRefused, ErrorClass, ErrorRecord, decide_retry
from lab_brain.surface.health import CapabilityAvailability, ComponentStatus, derive_health
from lab_brain.surface.ingestion_item import ItemState, derive_state
from tests.conftest_fixtures import TOY_SCHEMA_REF, make_attestation
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


def _env() -> dict[str, str]:
    """The environment `main` reads its DSN from.

    Passed as a mapping rather than set on the process: `read_settings` takes one so a test does
    not have to mutate `os.environ` and hope the teardown runs. The CLI opens its own connection
    from this, which is the point -- a test that handed `main` an already-open connection would
    be testing everything except the wiring that was missing.
    """
    return {DSN_VARIABLE: database_url()}


def raw_reader(db) -> PostgresEvidenceUnitReader:
    """The ACL-free canonical loader, built HERE as test infrastructure.

    Production exposes none. This file previously called `svc.unauthorized_reader()` -- which is
    to say the M1 vertical, the document that certifies the system composes correctly, was the
    proof that a public bypass existed and was reachable. Building the reader locally makes it
    scaffolding: the tests below need the plaintext in order to assert its ABSENCE from the
    authorized surfaces.
    """
    return PostgresEvidenceUnitReader(db)


def attest(db, artifact_id: str, *, attestation_id: str = "att:vertical") -> str:
    """A durable Attestation pointing at a real Artifact, so egress classification is derivable.

    SEC-001's classification is now read from provenance: bundle -> attestation ->
    `source_artifact_id` -> that artifact's occurrence in this project (§14.1). A bundle naming
    attestations that do not exist is unclassifiable and refused, which is correct and makes this
    row a REQUIREMENT of the vertical rather than decoration -- the model call cannot be
    authorized without the evidence trail that says what it is sending.
    """
    db.execute(
        "INSERT INTO source_works (source_work_id, work_type, title, trust_class) "
        "VALUES ('swk:test', 'TECHNICAL_REPORT', 'Rs anomaly report', 'INTERNAL_MEASUREMENT') "
        "ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO claims (claim_id, normalized_proposition) "
        "VALUES ('clm:test', 'Cj falls with reverse bias') ON CONFLICT DO NOTHING"
    )
    # EVI-005: an attestation's conditions are interpreted under a REGISTERED schema version.
    domain, rest = TOY_SCHEMA_REF.split("/", 1)
    schema_id, version = rest.split("@", 1)
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema, "
        "comparator_version) VALUES (%s, %s, %s, "
        '\'{"type": "object", "properties": {}}\'::jsonb, \'1.0.0\') '
        "ON CONFLICT DO NOTHING",
        (domain, schema_id, version),
    )
    SqlAttestationStore(db).add(
        make_attestation(
            attestation_id=attestation_id,
            # Exactly one source. §17.2 requires that: an attestation claiming both an artifact
            # and a work cannot say which one the locator is into.
            source_artifact_id=artifact_id,
            source_work_id=None,
            project_id=PROJECT,
            # No conditions: EVI-005 validates every declared field against the registered
            # schema, and this row exists to carry a `source_artifact_id`, not to exercise
            # condition matching -- which has its own suite.
            conditions={},
        )
    )
    return attestation_id


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


def _model(runner, classifier, *, reach=ExternalReach.LOCAL) -> ScientificLLM:
    return ScientificLLM(
        slots=(
            ModelSlot(LogicalSlot.HYPOTHESIS, "toy-model", "1.0.0", provider="local", reach=reach),
        ),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "Consider the evidence"),),
        complete=lambda _t, _s: "Cj falls because the depletion width grows.",
        runner=runner,
        classifier=classifier,
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
    index.add_all(raw_reader(db).load_for_project(PROJECT), project_id=PROJECT)
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

    # 7. ONE PRODUCTION OPERATION: authorize -> invoke -> durable write -> reload -> return.
    #
    # Not `invoke(); record_inference()`. That pair was two operations with a gap between them,
    # and a crash in the gap leaves a scientific model output with no durable provenance -- the
    # only case the exit gate's "all scientific LLM calls persist" sentence is about. `infer` does
    # not return until the record has been written, committed and compared.
    #
    # The egress classification is DERIVED from the bundle's attestation, which is why `attest`
    # above is load-bearing rather than decoration: an unclassifiable bundle is refused, so the
    # call is only authorized because the evidence trail says what is being sent.
    attest(db, result.artifact.artifact_id)
    bundle = _bundle(("att:vertical",))
    durable_inference = svc.inference_service(_model(_runner(), svc.classifier())).infer(
        inference_id="inf:vertical",
        slot=LogicalSlot.HYPOTHESIS,
        role="hypothesis_generator",
        prompt_id="prm:hypothesis",
        bundle=bundle,
        trace_id=TRACE,
        project_id=PROJECT,
        actor_id=ACTOR,
        now=NOW,
    )

    # 8. RELOAD the provenance through a new connection, and check exact equality.
    with psycopg.connect(database_url(), autocommit=True) as fresh:
        store = SqlInferenceProvenanceStore(fresh)
        durable = store.get("inf:vertical")
        assert durable is not None
        assert durable == durable_inference.provenance
        assert durable.evidence_bundle_hash == bundle.canonical_hash
        assert durable.trace_id == TRACE
        assert store.output_for("inf:vertical") == durable_inference.text

        # And the belief gate reads THAT record, not a set this test supplied.
        gate = IngestionService(
            connection=fresh, artifact_store=LocalArtifactStore(".")
        ).belief_basis_gate()
        assert gate.evaluate([durable_inference.basis_ref]).permitted
        assert not gate.evaluate(["inf:never-recorded"]).permitted

    # 9. One trace, end to end (§12.5).
    assert {episode.trace_id, result.job.trace_id, result.run.trace_id, durable.trace_id} == {TRACE}

    # 10. The DURABLE inbox, derived -- not an item this test constructed.
    view = svc.inbox(actor_id=ACTOR, project_id=PROJECT)
    items = view.items
    assert [i.item_id for i in items] == [result.outcome.item_id]
    item = items[0]
    assert item.raw_artifact_id == result.artifact.artifact_id
    assert item.job_ids == (job.job_id,)
    assert derive_state(item, jobs=[result.job]) is ItemState.READY

    # 11. The REAL CLI, through a new process-shaped connection. `main` reads its DSN from the
    # mapping it is given, opens the connection, and closes it -- which is the wiring that
    # `run_inbox` alone cannot exercise, and the wiring that did not exist.
    out = io.StringIO()
    assert main(["inbox", "--project", PROJECT, "--actor", ACTOR], out=out, env=_env()) == 0
    printed = out.getvalue()
    assert "READY=1" in printed
    assert result.outcome.item_id in printed

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
    db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    _job, result = _ingest(svc)
    secret = raw_reader(db).load_for_project(PROJECT)[0].body

    refused = svc.evidence_for(actor_id=UNCLEARED, project_id=PROJECT)
    assert refused == ()
    assert secret not in repr(refused)

    index = DenseEvidenceIndex("idx:dense:v1", SPACE, hashing_embedder(SPACE))
    index.add_all(raw_reader(db).load_for_project(PROJECT), project_id=PROJECT)
    candidates = index.search("reverse bias", project_id=PROJECT, space=SPACE, limit=50)
    by_actor = svc.candidate_resolver().resolve(candidates, actor_id=UNCLEARED, project_id=PROJECT)
    assert by_actor == ()
    assert secret not in repr(by_actor)
    assert result.succeeded


def test_external_egress_cannot_bypass_the_gate(world):
    """SEC-001 at the vertical. The transport is fatal, so this proves ordering."""
    db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)
    _job, result = _ingest(svc, label=SensitivityLabel.RESTRICTED_NDA)
    body = raw_reader(db).load_for_project(PROJECT)[0].body
    attest(db, result.artifact.artifact_id)

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
        classifier=svc.classifier(),
    )
    # The caller ATTEMPTS THE DOWNGRADE, declaring PUBLIC over RESTRICTED_NDA evidence. Under the
    # old signature this was a supported call and the gate answered correctly about a fiction.
    with pytest.raises(ExternalEffectRefused):
        cloud._invoke(
            inference_id="inf:leak",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=_bundle(("att:vertical",)),
            trace_id=TRACE,
            project_id=PROJECT,
            actor_id=ACTOR,
            escalate=frozenset({SensitivityLabel.PUBLIC}),
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


def test_the_real_cli_explains_a_durable_error_without_leaking_detail(world):
    """UX-003 through the REAL entry point, over a row the ingestion actually wrote.

    The previous version of this test built an `ErrorRecord` in memory and handed it to a
    `DiagnosticsService` it also built. That proved the disclosure rules and nothing about
    whether anything ever produced such a row or whether the command could reach one.

    Here a parse failure writes an `error_records` row, `main` opens its own connection, and the
    catalog text comes back. `--technical` is refused without the scope, which is the check §17.24
    requires to be server-side.
    """
    _db, svc = world
    svc.open_episode(project_id=PROJECT, goal="g", trace_id=TRACE, episode_id=EPISODE)

    class _Broken:
        def parse(self, *_a, **_k):
            raise RuntimeError("figure extraction timed out")

    svc._pipeline._parser = _Broken()
    _job, result = _ingest(svc, key="idem:cli-error")

    errors = svc.inbox(actor_id=ACTOR, project_id=PROJECT).items[0].error_ids
    assert errors, "the failed parse wrote no ErrorRecord, so there is nothing to explain"
    error_id = errors[0]
    assert error_id.startswith("ERR-"), "§17.23's reference is what a human quotes"

    out = io.StringIO()
    assert (
        main(["explain", error_id, "--project", PROJECT, "--actor", ACTOR], out=out, env=_env())
        == 0
    )
    printed = out.getvalue()
    assert error_id in printed
    assert TRACE in printed
    assert "Traceback" not in printed

    # Technical detail is an authorization decision, and this actor holds no scope.
    technical = io.StringIO()
    assert (
        main(
            ["explain", error_id, "--project", PROJECT, "--actor", ACTOR, "--technical"],
            out=technical,
            env=_env(),
        )
        == 0
    )
    assert "DIAGNOSTICS_SCOPE_REQUIRED" in technical.getvalue()
    assert result.outcome.result_for(IngestionStage.PARSE_TEXT).status is StageStatus.FAILED


def test_the_real_cli_cannot_be_used_to_probe_another_projects_errors(world):
    """§17.24's oracle rule at the vertical, through the real command.

    An id that never existed and an id in a project this actor cannot see must produce the SAME
    response -- an attacker enumerating ids learns which exist from any difference. Compared after
    substituting the id, so the only remaining difference would be a real one.
    """
    db, _svc = world
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other') "
        "ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO error_records (error_id, project_id, trace_id, error_class, reason_code, "
        "component, occurred_at) VALUES ('ERR-20260101-0001', 'prj:other', 'trc:other', "
        "'SYSTEM_ERROR', 'PARSE_TEXT_FAILED', 'FigureParser', %s)",
        (NOW,),
    )

    missing = io.StringIO()
    assert (
        main(
            ["explain", "ERR-20260922-9999", "--project", PROJECT, "--actor", ACTOR],
            out=missing,
            env=_env(),
        )
        == 1
    )
    foreign = io.StringIO()
    assert (
        main(
            ["explain", "ERR-20260101-0001", "--project", PROJECT, "--actor", ACTOR],
            out=foreign,
            env=_env(),
        )
        == 1
    )
    assert missing.getvalue().replace("ERR-20260922-9999", "<id>") == foreign.getvalue().replace(
        "ERR-20260101-0001", "<id>"
    )


def test_the_cli_refuses_to_run_without_configuration(world):
    """No default connection. A command that quietly reached a plausible local database would
    eventually report on the wrong one, confidently."""
    out = io.StringIO()
    assert main(["inbox", "--project", PROJECT, "--actor", ACTOR], out=out, env={}) == 2
    assert DSN_VARIABLE in out.getvalue()


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
