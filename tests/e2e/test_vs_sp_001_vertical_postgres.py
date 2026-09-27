"""VS-SP-001, end to end on PostgreSQL (TST-001 / T-E2E-SP-001, VER-001 / T-VER-001, §25.4).

    T-E2E-SP-001  Rs anomaly mock fixture 完整跑通 ingest → diagnose → test → evidence →
                  failure/heuristic candidate。
    T-VER-001     Planner 先檢查已存在 evidence / cheap actions；只有較便宜層不足時才升級
                  simulator，並記錄選擇理由。

§25.4's definition of done, as the assertions below read it off durable rows:

    CLI 可從一個 project/fixture 建立 episode                 `lab-brain episode open`
    raw artifacts 被 hash 且在 parsing 前已 durably 保存       the report, the device project and
                                                              every Run's output
    系統提出並保存 ≥2 個 competing hypotheses，每個都有 typed   M3's debate, admitted certificates
      Prediction
    Planner 先檢查 ... 低成本動作，再在需要時升級 simulator     the persisted VerificationPlans
    mock/real backend 都走 typed contract                     typed tools -> Job -> Run
    結果觸發 fidelity-aware update，且轉移由 TransitionPolicy   BeliefRevisionEvents with ALLOW
      授權並產生 BeliefRevisionEvent                          Decisions; coarse only challenges
    confirmed root cause 可追溯到 Run/Evidence/Artifact        `011l` accepted the analysis
    同類失敗形成可審核 heuristic candidate                     PENDING_REVIEW, after a recurrence
    整個流程在 Knowledge Inbox 中呈現為一個 IngestionItem + episode

WHAT IS MOCKED, AND SAID. The hypotheses come from M3's deterministic MockScientist; the solves
from `tool_providers.lumerical.mock_vertical`; the device from a normalized mock project. No model,
no licence seat and no probe station is used. The licensed replay is
`test_vs_sp_001_licensed_replay.py`, marked `lumerical`.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import psycopg
import pytest

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.capability import ActionType
from lab_brain.core.models.failure import ResolutionStatus
from lab_brain.core.models.verification import PlanDecision
from lab_brain.core.repositories.failures import SqlFailureStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.verification_plans import SqlVerificationPlanStore
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.interfaces import cli
from lab_brain.verification.loop import StopReason
from lab_brain.verification.workflows import WorkflowStatus
from tests.debate_fixtures import ACTOR, PROJECT, TRACE
from tests.postgres_fixtures import database_url
from tests.vertical_fixtures import case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "fixtures" / "evidence" / "rs_anomaly_report.md"
EPISODE = "epi:vs1"


def _member(db) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'VS-SP-001') ON CONFLICT DO NOTHING",
        (PROJECT,),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
        " ON CONFLICT DO NOTHING",
        (ACTOR, ACTOR),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC', 'INTERNAL'],"
        " ARRAY[]::text[], TRUE) ON CONFLICT DO NOTHING",
        (ACTOR, PROJECT),
    )


def _open_episode_from_the_cli(tmp_path: Path) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        [
            "episode",
            "open",
            str(REPORT),
            "--project",
            PROJECT,
            "--actor",
            ACTOR,
            "--goal",
            "diagnose the Rs anomaly",
            "--trace",
            TRACE,
            "--episode",
            EPISODE,
            "--artifact-root",
            str(tmp_path),
        ],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    return code, out.getvalue()


@pytest.mark.requirement("TST-001")
@pytest.mark.spec_test("T-E2E-SP-001")
def test_the_rs_anomaly_runs_from_ingest_to_a_reviewable_heuristic_candidate(db, tmp_path):
    fx = load_fixture()
    _member(db)

    # -- ingest: the CLI opens the episode from the fixture; raw bytes stored before parsing -----
    code, printed = _open_episode_from_the_cli(tmp_path)
    assert code == 0, printed
    report_id = "art:sha256:" + hashlib.sha256(REPORT.read_bytes()).hexdigest()
    assert f"artifact={report_id}" in printed
    assert "READY=1" in printed
    stored = db.execute(
        "SELECT source_origin FROM artifacts WHERE artifact_id = %s", (report_id,)
    ).fetchone()
    assert stored == ("UPLOAD",)
    assert db.execute(
        "SELECT project_id, trace_id FROM research_episodes WHERE episode_id = %s", (EPISODE,)
    ).fetchone() == (PROJECT, TRACE)

    # -- diagnose -> test -> evidence, in that episode ---------------------------------------------
    run = run_case(db, fx, case_by_id(fx, "contact-open-via"), episode_id=EPISODE)
    result = run.result

    # >= 2 competing hypotheses, each with typed predictions, admitted through §8's gate.
    certificates = run.debate.certificates
    assert len(certificates) >= 2
    assert run.debate.hypothesis_set.root_cause
    for certificate in certificates:
        assert certificate.predictions
        assert db.execute(
            "SELECT count(*) FROM predictions WHERE hypothesis_id = %s",
            (certificate.hypothesis_id,),
        ).fetchone()[0] == len(certificate.predictions)

    # Every executed action is a typed tool -> Job -> Run whose output bytes are stored and hashed.
    jobs = SqlJobStore(db)
    executed = [s for s in result.steps if s.status is WorkflowStatus.EXECUTED]
    assert executed
    for step in executed:
        assert step.run_id is not None
        durable = jobs.get_run(step.run_id)
        assert durable is not None and durable.status.value == "SUCCEEDED"
        assert durable.job_id == step.job_id and durable.trace_id == TRACE
        for artifact_id in durable.output_artifacts:
            origin = db.execute(
                "SELECT source_origin, content_hash FROM artifacts WHERE artifact_id = %s",
                (artifact_id,),
            ).fetchone()
            assert origin is not None and origin[0] == "RUN_OUTPUT"
            assert artifact_id == f"art:{origin[1]}"
        spans = db.execute(
            "SELECT count(*) FROM execution_spans WHERE episode_id = %s AND span_type ="
            " 'TOOL_CALL'",
            (EPISODE,),
        ).fetchone()[0]
        assert spans >= len(executed)

    # Evidence: Observation(run) -> Attestation(run, not INFERRED) -> relations with EXACT match.
    rows = db.execute(
        "SELECT a.epistemic_type, a.run_id, a.authority_class, o.run_id FROM attestations a"
        " JOIN observations o ON o.observation_id = a.observation_id WHERE a.project_id = %s",
        (PROJECT,),
    ).fetchall()
    assert rows and all(r[0] in ("OBSERVED", "SIMULATED") and r[1] == r[3] for r in rows)
    matches = db.execute(
        "SELECT DISTINCT m.state FROM relation_judgments r"
        " JOIN condition_matches m ON m.condition_match_id = r.condition_match_ref"
        " WHERE r.project_id = %s",
        (PROJECT,),
    ).fetchall()
    assert matches == [("EXACT",)]

    # Belief moved only through TransitionPolicy: every non-genesis event cites an ALLOW Decision.
    contact = run.certificates_by_mechanism["contact_discontinuity"]
    normalization = run.certificates_by_mechanism["normalization_error"]
    assert result.stop_reason is StopReason.CONFIRMED
    moves = {
        (t.hypothesis_id, t.to_state)
        for step in result.steps
        for t in step.transitions
        if t.event_id is not None
    }
    assert (contact, "SUPPORTED") in moves and (normalization, "CONTRADICTED") in moves
    ungoverned = db.execute(
        "SELECT count(*) FROM belief_revision_events e WHERE e.project_id = %s"
        " AND e.from_state IS NOT NULL AND NOT EXISTS (SELECT 1 FROM belief_transition_decisions"
        " d WHERE d.decision_id = e.authorization_decision_id AND d.result = 'ALLOW')",
        (PROJECT,),
    ).fetchone()[0]
    assert ungoverned == 0

    # The failure analysis: CONFIRMED, stored past `011l`, its evidence traced to Run and Artifact.
    analysis = result.failure_analysis
    assert analysis.resolution_status is ResolutionStatus.CONFIRMED
    assert analysis.confirmed_root_cause == contact
    assert SqlFailureStore(db).analysis(PROJECT, analysis.failure_analysis_id) == analysis
    assert result.trace is not None and result.trace.artifact_ids
    assert set(result.trace.capability_ids) == {sp.CAP_INSPECT_CONNECTIVITY}
    assert result.candidates == ()  # one failure is not yet a pattern

    # -- the same class of failure recurs on another device: a reviewable candidate --------------
    again = run_case(db, fx, case_by_id(fx, "contact-thin-overlap"))
    assert again.result.stop_reason is StopReason.CONFIRMED
    (candidate,) = again.result.candidates
    assert candidate.status == "PENDING_REVIEW"
    assert set(candidate.derived_from_failures) == {
        analysis.failure_analysis_id,
        again.result.failure_analysis.failure_analysis_id,
    }
    assert candidate.suggested_checks == (sp.CAP_INSPECT_CONNECTIVITY,)
    assert candidate.source_artifact_ids and candidate.source_locators
    assert SqlFailureStore(db).candidates(PROJECT) == (candidate,)
    # The earlier failure was consulted before the second episode planned (§6.9).
    first_plan = again.result.plans[0]
    assert analysis.failure_analysis_id in first_plan.rationale.precedents

    # -- the Knowledge Inbox shows the ingestion as one item of the project ----------------------
    items = db.execute(
        "SELECT count(*) FROM ingestion_items WHERE project_id = %s", (PROJECT,)
    ).fetchone()[0]
    assert items == 1


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_the_simulator_is_reached_only_after_the_cheaper_layer_and_every_plan_says_why(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, "mesh-coarse-access"))
    plans = SqlVerificationPlanStore(db).plans_for_episode(
        PROJECT, "epi:mesh-coarse-access-least_cost"
    )
    assert plans == run.result.plans, "the plans the loop acted on are the plans on record"
    capabilities = run.registry.registries.capabilities
    kinds = [capabilities.resolve(p.chosen_action_id).action_type for p in plans]
    assert kinds[:2] == [ActionType.ANALYTICAL_RULE_CHECK, ActionType.ANALYTICAL_RULE_CHECK]
    assert kinds[2] is ActionType.SIMULATION
    simulator_plan = plans[2]
    assert simulator_plan.rationale.decision is PlanDecision.ACT
    tried = {step.action_id: step.reason for step in simulator_plan.rationale.escalation}
    assert set(tried) == {sp.CAP_INSPECT_CONNECTIVITY, sp.CAP_EXTRACTION_CONSISTENCY}
    assert all("executed earlier in this episode" in reason for reason in tried.values())
    assert "2 check(s) already executed" in simulator_plan.rationale.summary
    # Every candidate in every plan carries a predicted discriminating outcome and a cost.
    for p in plans:
        for action_id in p.candidate_action_ids:
            summary = p.sufficiency_results[action_id]
            assert summary.sufficient == bool(summary.discriminating)
        assert {t.action_id for t in p.rationale.tradeoffs} == set(p.candidate_action_ids)
    assert run.result.stop_reason is StopReason.CONFIRMED
    assert run.mechanism_of(run.result.confirmed_root_cause) == "mesh_artifact"


@pytest.mark.requirement("VER-001")
@pytest.mark.spec_test("T-VER-001")
def test_a_coarse_solve_may_challenge_and_may_not_confirm(db):
    """§25.4's fidelity-aware update: a non-converged solve earns SIM_COARSE, which SIM-002's
    challenge policy accepts and neither the reject nor the promote policy does."""
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, "dopant-nonconverged"))
    result = run.result
    mesh = run.certificates_by_mechanism["mesh_artifact"]
    dopant = run.certificates_by_mechanism["dopant_compensation"]
    moves = {(t.hypothesis_id, t.to_state) for s in result.steps for t in s.transitions}
    assert (mesh, "CHALLENGED") in moves and (mesh, "CONTRADICTED") not in moves
    assert all(h != dopant for h, _ in moves), "coarse support must not move the dopant rival"
    coarse = [o for s in result.steps for o in s.outcomes if o.authority_class == "SIM_COARSE"]
    assert {o.observable_ref for o in coarse} == {sp.OBS_MESH, sp.OBS_CARRIER}
    assert result.stop_reason is StopReason.HUMAN_ACTION_REQUIRED
    assert result.steps[-1].chosen == sp.CAP_FOURPOINT_PROBE
    assert result.failure_analysis.resolution_status is ResolutionStatus.OPEN


def test_a_licence_outage_parks_the_solve_and_cheap_checks_still_run(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, "outage-mesh"))
    last = run.result.steps[-1]
    assert run.result.stop_reason is StopReason.AWAITING_RESOURCE
    assert last.chosen == sp.CAP_MESH_SENSITIVITY
    parked = SqlJobStore(db).get(last.job_id)
    assert parked is not None and parked.state.value == "WAITING_RESOURCE"
    assert run.result.failure_analysis.resolution_status is ResolutionStatus.OPEN
    contact = run.certificates_by_mechanism["contact_discontinuity"]
    moves = {(t.hypothesis_id, t.to_state) for s in run.result.steps for t in s.transitions}
    assert (contact, "CONTRADICTED") in moves


def test_nothing_sufficient_left_ends_inconclusive_and_confirms_nothing(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, "probe-lab-closed"))
    assert run.result.stop_reason is StopReason.NO_SUFFICIENT_ACTION
    assert run.result.failure_analysis.resolution_status is ResolutionStatus.INCONCLUSIVE
    assert run.result.failure_analysis.confirmed_root_cause is None
    assert run.result.plans[-1].rationale.decision is PlanDecision.NO_SUFFICIENT_ACTION
    rejected = {
        t.hypothesis_id
        for s in run.result.steps
        for t in s.transitions
        if t.to_state == BeliefState.CONTRADICTED.value and t.event_id
    }
    assert len(rejected) == 4
