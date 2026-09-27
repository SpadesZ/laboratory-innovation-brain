"""EPI-002, durable: the confirmed root cause's provenance query, and `011l` for every writer of SQL.

EPI-002    confirmed root cause 必須可以 trace 回 Run/Evidence/Artifact；LLM statement 不可作為證據。
T-EPI-002  confirmed root cause query 必須 trace 到 Relation/Attestation or Observation → Run →
           Artifact；只有 LLM statement 的 fixture 不得確認 root cause。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.enums import EpistemicType, RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.repositories.belief_events import SqlBeliefEventStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.revision_gate import RevisionPreconditionFailed
from lab_brain.core.root_cause import RootCauseRefusal, RootCauseRefused, trace_root_cause
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from lab_brain.verification.loop import StopReason
from tests.conftest_fixtures import make_attestation, make_extraction_provenance
from tests.debate_fixtures import ACTOR, PROJECT, TRACE
from tests.vertical_fixtures import VerticalRun, case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres

T = dt.datetime(2026, 9, 26, 12, 0, tzinfo=dt.UTC)


def _run(db: Any, case_id: str) -> VerticalRun:
    fx = load_fixture()
    return run_case(db, fx, case_by_id(fx, case_id))


def _model_statement(db: Any, run: VerticalRun, mechanism: str) -> str:
    """The LLM-only fixture: a model's reading that `mechanism` is the cause, and nothing else."""
    hypothesis_id = run.certificates_by_mechanism[mechanism]
    certificate = next(c for c in run.debate.certificates if c.hypothesis_id == hypothesis_id)
    inference = certificate.hypothesis.inference_provenance_id
    assert inference is not None, "the debate's certificates carry their inference provenance"
    attestation = make_attestation(
        attestation_id=f"att:llm-{mechanism}",
        epistemic_type=EpistemicType.INFERRED,
        claim_id="clm:test",
        source_work_id=None,
        source_artifact_id=run.device_artifact_id,
        project_id=PROJECT,
        conditions={"device_length_um": "500"},
        conditions_schema_version=sp.DEVICE_SCHEMA_REF,
        locator="model reading of the anomaly",
        extraction_provenance=make_extraction_provenance(inference_provenance_id=inference),
    )
    SqlAttestationStore(db).add(attestation)
    SqlRelationStore(db).add(
        RelationJudgment(
            relation_id=f"rel:llm-{mechanism}",
            from_entity_id=attestation.attestation_id,
            to_entity_id=hypothesis_id,
            relation_type=RelationType.SUPPORTS,
            supporting_attestation_ids=(attestation.attestation_id,),
            inference_provenance_id=inference,
            project_id=PROJECT,
            valid_from=T,
            created_at=T,
        )
    )
    return attestation.attestation_id


def _insert_analysis(db: Any, run: VerticalRun, cause: str, evidence: list[str]) -> None:
    db.execute(
        "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
        " expected_behavior, observed_behavior, candidate_causes, confirmed_root_cause,"
        " root_cause_evidence_ids, failure_class, resolution_status, created_at)"
        " VALUES (%s, %s, %s, 'Rs flat', 'design Rs', 'several times design', %s, %s, %s,"
        " 'forged', 'CONFIRMED', %s)",
        (
            "fan:forged",
            PROJECT,
            run.debate.hypothesis_set.episode_id,
            [c.hypothesis_id for c in run.debate.certificates],
            cause,
            evidence,
            T,
        ),
    )


def _trace(db: Any, run: VerticalRun, hypothesis_id: str) -> Any:
    sink = SqlEvidenceSink(connection=db, outputs=None)  # type: ignore[arg-type]
    return trace_root_cause(
        project_id=PROJECT,
        hypothesis_id=hypothesis_id,
        history=SqlBeliefEventStore(db).history,
        relation=sink.relation,
        attestation=sink.attestation,
        observation=sink.observation,
        run=SqlJobStore(db).get_run,
        artifact_exists=sink.artifact_exists,
    )


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_the_confirmed_root_cause_query_reaches_relation_attestation_run_and_artifact(db):
    run = _run(db, "contact-open-via")
    analysis = run.result.failure_analysis
    assert run.result.stop_reason is StopReason.CONFIRMED
    rows = db.execute(
        """
        SELECT f.confirmed_root_cause, r.relation_id, r.relation_type, a.attestation_id,
               a.epistemic_type, o.observation_id, run.run_id, run.status, art.artifact_id
          FROM failure_analyses f
          JOIN attestations a ON a.attestation_id = ANY (f.root_cause_evidence_ids)
          JOIN relation_judgments r ON a.attestation_id = ANY (r.supporting_attestation_ids)
                                   AND r.to_entity_id = f.confirmed_root_cause
          JOIN observations o ON o.observation_id = a.observation_id
          JOIN runs run ON run.run_id = o.run_id
          JOIN artifacts art ON art.artifact_id = ANY (run.output_artifacts)
         WHERE f.failure_analysis_id = %s
        """,
        (analysis.failure_analysis_id,),
    ).fetchall()
    assert rows, "the provenance query found no chain"
    for cause, _rel, kind, _att, epistemic, _obs, _run_id, status, _artifact in rows:
        assert cause == run.certificates_by_mechanism["contact_discontinuity"]
        assert kind == "SUPPORTS" and epistemic == "OBSERVED" and status == "SUCCEEDED"
    assert {r[8] for r in rows} == set(run.result.trace.artifact_ids)  # type: ignore[union-attr]
    assert {r[6] for r in rows} == set(run.result.trace.run_ids)  # type: ignore[union-attr]
    # The Run is the capability that was planned, executed under the episode's trace.
    (run_id,) = run.result.trace.run_ids  # type: ignore[union-attr]
    durable = SqlJobStore(db).get_run(run_id)
    assert durable is not None
    assert durable.capability_id == sp.CAP_INSPECT_CONNECTIVITY and durable.trace_id == TRACE


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_a_fixture_with_only_a_model_statement_cannot_confirm_a_root_cause(db):
    """Nothing verified the probe mechanism; a model says it is the cause. Belief does not move,
    the trace refuses, and `011l` refuses the analysis a writer tries to store anyway."""
    run = _run(db, "probe-lab-closed")
    probe = run.certificates_by_mechanism["probe_artifact"]
    llm = _model_statement(db, run, "probe_artifact")
    promote = next(
        p for p in sp.vertical_transition_policies() if p.policy_id == sp.PROMOTE_POLICY_ID
    )
    attestation = SqlAttestationStore(db).get(PROJECT, llm)
    assert attestation is not None
    with pytest.raises(RevisionPreconditionFailed, match="ADJUDICATED_BY_MODEL_OPINION"):
        run.brain.attempt_revision(
            project_id=PROJECT,
            hypothesis_id=probe,
            policy_id=promote.policy_id,
            policy_version=promote.version,
            candidate_to_state=BeliefState.SUPPORTED,
            occurred_at=T,
            trace_id=TRACE,
            triggering_attestations=(attestation,),
            actor_id=ACTOR,
            authority_policy_ref=("auth:silicon_photonics", "1.1.0"),
        )
    with pytest.raises(RootCauseRefused) as refused:
        _trace(db, run, probe)
    assert refused.value.reason is RootCauseRefusal.NOT_SUPPORTED
    with pytest.raises(Exception, match="only a SUPPORTED hypothesis"):
        _insert_analysis(db, run, probe, [llm])


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_sql_refuses_a_confirmation_resting_on_anything_but_executed_evidence(db):
    run = _run(db, "contact-open-via")
    contact = run.certificates_by_mechanism["contact_discontinuity"]
    llm = _model_statement(db, run, "contact_discontinuity")
    with pytest.raises(Exception, match="LLM statement"):
        _insert_analysis(db, run, contact, [llm])
    # A literature attestation from the debate: admissible evidence, but not what confirmed it.
    with pytest.raises(Exception, match="supports no current SUPPORTS relation"):
        _insert_analysis(db, run, contact, ["att:vs1-review"])
    with pytest.raises(Exception, match="not an attestation"):
        _insert_analysis(db, run, contact, ["att:nobody"])
    # A cause nobody admitted, and a candidate list naming one.
    with pytest.raises(Exception, match="not a hypothesis admitted"):
        db.execute(
            "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
            " expected_behavior, observed_behavior, candidate_causes, failure_class,"
            " resolution_status, created_at) VALUES ('fan:x', %s, %s, 's', 'e', 'o',"
            " ARRAY['hyp:imagined'], 'c', 'INCONCLUSIVE', %s)",
            (PROJECT, run.debate.hypothesis_set.episode_id, T),
        )
    # The genuine evidence still confirms: the trigger refuses forgeries, not the record.
    genuine = list(run.result.failure_analysis.root_cause_evidence_ids)
    _insert_analysis(db, run, contact, genuine)


def test_candidate_heuristics_rest_on_confirmed_failures_and_the_memory_is_append_only(db):
    run = _run(db, "contact-open-via")
    confirmed = run.result.failure_analysis
    episode = run.debate.hypothesis_set.episode_id
    db.execute(
        "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
        " expected_behavior, observed_behavior, candidate_causes, failure_class,"
        " resolution_status, created_at) VALUES ('fan:open', %s, %s, 's', 'e', 'o', %s,"
        " 'UNRESOLVED', 'INCONCLUSIVE', %s)",
        (PROJECT, episode, list(confirmed.candidate_causes), T),
    )

    def candidate(candidate_id: str, status: str, derived: str) -> None:
        db.execute(
            "INSERT INTO candidate_heuristics (candidate_id, project_id, trigger_pattern,"
            " suggested_checks, rationale, source_artifact_ids, source_locators,"
            " source_episode_ids, miner_model_version, status, derived_from_failures, created_at)"
            " VALUES (%s, %s, 'rs flat', ARRAY['cap:sp.inspect_contact_connectivity'], 'r', %s,"
            " ARRAY['run:x'], %s, 'm@1', %s, %s, %s)",
            (
                candidate_id,
                PROJECT,
                [run.device_artifact_id],
                [episode],
                status,
                [derived],
                T,
            ),
        )

    with pytest.raises(Exception, match="not a CONFIRMED failure"):
        candidate("chr:open", "PENDING_REVIEW", "fan:open")
    with pytest.raises(Exception, match="candidate_heuristics_status_check"):
        candidate("chr:active", "ACTIVE", confirmed.failure_analysis_id)
    candidate("chr:ok", "PENDING_REVIEW", confirmed.failure_analysis_id)
    with pytest.raises(Exception, match="append-only"):
        db.execute(
            "UPDATE candidate_heuristics SET status = 'ACTIVE' WHERE candidate_id = 'chr:ok'"
        )
    with pytest.raises(Exception, match="append-only"):
        db.execute(
            "UPDATE failure_analyses SET resolution_status = 'CONFIRMED' WHERE"
            " failure_analysis_id = 'fan:open'"
        )
    with pytest.raises(Exception, match="append-only"):
        db.execute(
            "DELETE FROM failure_analyses WHERE failure_analysis_id = %s",
            (confirmed.failure_analysis_id,),
        )
