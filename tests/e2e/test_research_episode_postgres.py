"""The product vertical end to end on PostgreSQL: a user's goal and files in, one report out.

Driven through the real entry point, `lab_brain.interfaces.cli.main`, with the arguments a user
types: a research goal, a measurement report, a device project, and a local literature corpus with
a query the user declares public. No simulator exists here -- no licensed backend, no seat -- and
nothing replaces one: the tests assert that no simulation Job or Run was created, that the best next
simulation is reported as BLOCKED, and that the episode is parked rather than falsely finished.

Everything else in the report is checked against the rows the authoritative services wrote:
ingestion, admitted statements, the debate's hypotheses and critique, governed belief moves, the
verification plans, the executed Runs, the failure analysis and the external snapshots.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import psycopg
import pytest

from lab_brain.interfaces import cli
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "fixtures" / "evidence" / "rs_anomaly_report.md"
CORPUS = ROOT / "fixtures" / "external" / "literature_corpus.json"
PROJECT = "prj:ps-rs"
ACTOR = "act:rkuo"
GOAL = "Why is Rs extremely high and weakly bias dependent while Cj trends normally?"
SIMULATIONS = ("cap:sp.mesh_sensitivity", "cap:sp.charge_dc_sweep", "cap:sp.charge_ac_sweep")


def _member(db, actor: str = ACTOR, *, member: bool = True) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Rs anomaly') ON CONFLICT DO NOTHING",
        (PROJECT,),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)",
        (actor, actor),
    )
    if member:
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
            " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC', 'INTERNAL'],"
            " ARRAY[]::text[], TRUE)",
            (actor, PROJECT),
        )


def _device(tmp_path: Path, case_id: str) -> Path:
    fx = json.loads(
        (ROOT / "fixtures/vertical/sp_rs_root_cause_benchmark.json").read_text(encoding="utf-8")
    )
    case = next(c for c in fx["cases"] if c["case_id"] == case_id)
    path = tmp_path / f"{case['device']['device_id']}.device.json"
    path.write_text(json.dumps({**fx["nominal_device"], **case["device"]}), encoding="utf-8")
    return path


def _run(tmp_path: Path, *extra: str, actor: str = ACTOR) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        [
            "research",
            "run",
            "--project",
            PROJECT,
            "--actor",
            actor,
            "--goal",
            GOAL,
            "--measurement",
            str(REPORT),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            *extra,
        ],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    return code, out.getvalue()


def _one(db, query: str, *params: object) -> object:  # type: ignore[no-untyped-def]
    row = db.execute(query, params).fetchone()
    return None if row is None else row[0]


def test_a_real_user_input_travels_to_a_rendered_result_with_no_simulator(db, tmp_path):
    _member(db)
    device = _device(tmp_path, "mesh-coarse-access")
    report_path = tmp_path / "report.md"
    code, printed = _run(
        tmp_path,
        "--verification-input",
        str(device),
        "--literature-corpus",
        str(CORPUS),
        "--literature-query",
        "series resistance contact normalization reverse bias",
        "--report",
        str(report_path),
    )
    assert code == 0, printed
    written = report_path.read_text(encoding="utf-8")
    assert written.strip() == printed.strip(), "the report file is what was printed"

    # -- the episode: opened, and PARKED on the missing simulator rather than falsely finished --
    episode_id, state, reason = db.execute(
        "SELECT episode_id, state, suspend_reason FROM research_episodes WHERE project_id = %s",
        (PROJECT,),
    ).fetchone()
    assert state == "SUSPENDED" and "cap:sp.mesh_sensitivity" in reason
    assert f"# Research episode {episode_id}" in printed

    # -- input status: the document ingested and read; the device stored as the input -------------
    assert "| rs_anomaly_report.md | document | INTERNAL_MEASUREMENT | READY |" in printed
    units = _one(
        db,
        "SELECT count(*) FROM evidence_units WHERE artifact_id IN"
        " (SELECT raw_artifact_id FROM ingestion_items WHERE project_id = %s)",
        PROJECT,
    )
    statements = _one(
        db,
        "SELECT count(*) FROM attestations WHERE project_id = %s AND epistemic_type = 'REPORTED'"
        " AND extraction_provenance->>'extractor_id' = 'research.verbatim_statement'",
        PROJECT,
    )
    assert units and statements == units, "one verbatim statement per unit, all admitted"
    assert "device PS-504" in printed

    # -- external evidence: pinned, rights-governed, admitted only as REPORTED ------------------
    snapshots = db.execute(
        "SELECT retention, trust_class FROM external_snapshots WHERE project_id = %s", (PROJECT,)
    ).fetchall()
    assert snapshots and {t for _, t in snapshots} <= {"PEER_REVIEWED", "PREPRINT"}
    assert "### External literature -- `literature`" in printed
    assert "status RETRACTED" in printed, "a retracted paper is reported as such, not hidden"

    # -- competing hypotheses and the debate, by the local rule-based reasoner -----------------
    hypotheses = _one(db, "SELECT count(*) FROM hypotheses WHERE project_id = %s", PROJECT)
    assert hypotheses == 5
    models = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT model_id FROM inference_provenance WHERE project_id = %s", (PROJECT,)
        ).fetchall()
    }
    assert models == {"rules:sp.rs_anomaly_mechanisms"}
    assert _one(db, "SELECT count(*) FROM critique_reports WHERE project_id = %s", PROJECT)
    assert "No language model is configured or was called" in printed

    # -- verification: the cheap checks ran as Jobs with Runs; no simulation ran at all ---------
    executed = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT r.capability_id FROM runs r JOIN jobs j ON j.job_id = r.job_id"
            " WHERE j.episode_id = %s AND r.status = 'SUCCEEDED'",
            (episode_id,),
        ).fetchall()
    }
    assert executed >= {"cap:sp.inspect_contact_connectivity", "cap:sp.extraction_consistency"}
    assert not executed & set(SIMULATIONS)
    assert (
        _one(
            db,
            "SELECT count(*) FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
            PROJECT,
            list(SIMULATIONS),
        )
        == 0
    ), "a simulation job would be a mock or a lie"
    plans = _one(db, "SELECT count(*) FROM verification_plans WHERE episode_id = %s", episode_id)
    assert f"{plans} plan(s)" in printed, "the what-if plan is never stored"

    # -- belief: two rivals ruled out through governed, authorised moves -------------------------
    contradicted = _one(
        db,
        "SELECT count(DISTINCT target_id) FROM belief_revision_events WHERE project_id = %s"
        " AND to_state = 'CONTRADICTED'",
        PROJECT,
    )
    assert contradicted == 2
    ungoverned = _one(
        db,
        "SELECT count(*) FROM belief_revision_events e WHERE e.project_id = %s AND"
        " e.from_state IS NOT NULL AND NOT EXISTS (SELECT 1 FROM belief_transition_decisions d"
        " WHERE d.decision_id = e.authorization_decision_id AND d.result = 'ALLOW')",
        PROJECT,
    )
    assert ungoverned == 0

    # -- the result: provisional, with the simulation pending and blocked -----------------------
    assert "**PROVISIONAL**" in printed
    assert "Ruled out by executed checks:" in printed
    assert "- `cap:sp.mesh_sensitivity` (SIMULATION, best next action) -- **BLOCKED**" in printed
    assert "mesh convergence artifact -> SUPPORTED if UNSTABLE" in printed
    pending = printed.split("## Pending simulation actions", 1)[1].split("## Next steps", 1)[0]
    listed = [line.split("`")[1] for line in pending.splitlines() if line.startswith("- `cap:")]
    assert listed and set(listed) <= set(SIMULATIONS), "only what cannot run here is pending"
    assert "Awaiting a person: `cap:sp.fourpoint_probe`" in printed
    assert "no simulation was run and none was emulated" in printed
    assert (
        _one(db, "SELECT resolution_status FROM failure_analyses WHERE episode_id = %s", episode_id)
        == "OPEN"
    )


def test_a_cheap_check_confirms_the_cause_without_any_simulator(db, tmp_path):
    _member(db)
    code, printed = _run(
        tmp_path, "--verification-input", str(_device(tmp_path, "contact-open-via"))
    )
    assert code == 0, printed
    assert "**CONFIRMED** -- the root cause is access contact discontinuity" in printed
    assert "Confirmation trace: run `run:" in printed
    state, outcome = db.execute(
        "SELECT state, outcome_status FROM research_episodes WHERE project_id = %s", (PROJECT,)
    ).fetchone()
    assert state == "COMPLETED" and outcome.startswith("CONFIRMED:hyp:")
    assert "| pending simulation | SKIPPED | the root cause is confirmed |" in printed
    assert (
        _one(
            db,
            "SELECT count(*) FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
            PROJECT,
            list(SIMULATIONS),
        )
        == 0
    )
    assert "no external source was contacted" in printed


def test_without_a_verification_input_the_debate_still_reports_and_nothing_is_verified(
    db, tmp_path
):
    _member(db)
    code, printed = _run(tmp_path)
    assert code == 0, printed
    assert "| verification input | SKIPPED |" in printed
    assert "| hypotheses | DONE |" in printed
    assert "**NOT_REACHED**" in printed
    assert "Provide the pack's verification input" in printed
    assert _one(db, "SELECT count(*) FROM verification_plans WHERE project_id = %s", PROJECT) == 0


def test_a_non_member_gets_no_episode_and_no_report(db, tmp_path):
    _member(db, "act:outsider", member=False)
    code, printed = _run(tmp_path, actor="act:outsider")
    assert code == 1
    assert printed.strip() == f"No research for act:outsider in {PROJECT}."
    assert _one(db, "SELECT count(*) FROM research_episodes WHERE project_id = %s", PROJECT) == 0
    assert _one(db, "SELECT count(*) FROM artifacts") == 0


def test_a_literature_query_is_never_sent_without_being_declared(db, tmp_path):
    _member(db)
    code, printed = _run(tmp_path, "--literature-corpus", str(CORPUS))
    assert code == 2 and "declare public" in printed
    assert _one(db, "SELECT count(*) FROM research_episodes WHERE project_id = %s", PROJECT) == 0


def test_episode_open_mints_its_own_id_when_none_is_given(db, tmp_path):
    """The latent defect the product vertical found: `open_episode` minted an unregistered id
    kind, so `lab-brain episode open` without `--episode` could not work."""
    _member(db)
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
            GOAL,
            "--trace",
            "trc:open",
            "--artifact-root",
            str(tmp_path / "a"),
        ],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    assert code == 0, out.getvalue()
    assert out.getvalue().startswith("episode   epi:")
