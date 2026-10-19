"""Benchmark 1.1.0 under the candidate SP declarations 1.1.0 -- evidence, not a gate.

The candidate (`product.CANDIDATE_VERSION`) is not registered by the product; this runs it as a
deployment activating it would: 1.0.0 registered for what was concluded under it, 1.1.0 active, the
loop, the belief path, the confirmation verifier and SQL all reasoning under it, and the harness's
differential check holding SQL's confirmation rule and the loop's to the same verdict on every
episode (`CheckedLoop`). What it shows:

    expectations   every case ends where benchmark 1.1.0 says, except the cases it marks as
                   known limitations of BOTH declaration versions -- which still end wrong, so
                   this fails the day one of them is fixed and the benchmark is due a new version
    cause          the two cases 1.1.0 changed end where 1.0.0 expected under 1.0.0's
                   declarations: the declarations alone moved them
    VER-001        still no unjustified escalation and no high-cost action in a cheap case
    SQL            the registered rows carry the withdrawn links, and a malformed one is refused
    report         the committed report is what this run renders
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from lab_brain.verification.root_cause_benchmark import render_report
from tests.postgres_fixtures import reset_database
from tests.vertical_fixtures import (
    LEAST_COST,
    candidate_declarations,
    case_by_id,
    load_fixture,
    record_for,
    run_benchmark,
    run_case,
)

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "vertical" / "sp_rs_root_cause_benchmark_1.1.0.json"
REPORT = ROOT / "benchmarks" / "root_cause_benchmark_report_1.1.0_candidate.md"


@pytest.fixture(scope="module")
def benchmark(postgres_connection):  # type: ignore[no-untyped-def]
    candidate, registered = candidate_declarations()
    run = run_benchmark(
        postgres_connection,
        reset_database,
        path=FIXTURE,
        declarations=candidate,
        registered=registered,
    )
    reset_database(postgres_connection)
    return run


def test_every_case_ends_where_benchmark_1_1_0_says_but_its_known_limitations(benchmark):
    fx = load_fixture(FIXTURE)
    limitations = {c["case_id"] for c in fx["cases"] if c.get("known_limitation")}
    assert limitations, "the benchmark states what neither declaration version reaches"
    wrong = {r.case_id for r in benchmark.of(LEAST_COST) if not r.correct}
    assert wrong == limitations, (
        "a known limitation now ends where the benchmark says: the declarations improved, so "
        "the benchmark is due a new version"
        if wrong < limitations
        else f"cases ending where the benchmark does not say: {sorted(wrong - limitations)}"
    )
    primary = benchmark.of(LEAST_COST)
    assert sum(r.unjustified_escalations for r in primary) == 0
    assert sum(r.unnecessary_high_cost for r in primary) == 0
    changed = {c["case_id"] for c in fx["cases"] if c.get("changed_in") == "1.1.0"}
    assert changed == {"mesh-coarse-access"}
    assert all(r.correct for r in primary if r.case_id in changed)


@pytest.mark.parametrize("case_id", ["mesh-coarse-access", "probe-lab-closed"])
def test_under_1_0_0_the_cases_the_candidate_moves_end_where_they_did(db, case_id):
    """The control: same case, same loop, the product's own declarations. mesh-coarse-access
    ends where 1.0.0 expected (a mesh confirmation); probe-lab-closed ends where 1.1.0 expects
    too -- by 1.0.0's design-file refutations, the review found -- while the candidate moves it."""
    fx = load_fixture(FIXTURE)
    case = case_by_id(fx, case_id)
    record = record_for(run_case(db, fx, case), case)
    old = case.get("expected_in_1_0_0", case["expected"])
    assert (record.stop, record.confirmed) == (old["stop"], old.get("cause"))


@pytest.mark.parametrize("case_id", ["mesh-coarse-access"])
def test_a_withdrawn_link_goes_to_a_person_in_sql_and_in_the_loop_alike(db, case_id):
    """One case each, under the candidate: the loop stops for a person, and `run_case`'s
    differential check finds SQL's confirmation rule reading the same warrants."""
    candidate, registered = candidate_declarations()
    fx = load_fixture(FIXTURE)
    case = case_by_id(fx, case_id)
    run = run_case(db, fx, case, declarations=candidate, registered=registered)
    record = record_for(run, case)
    assert record.correct, (record.stop, record.confirmed, record.pending_action)


def test_sql_reads_a_withdrawn_link_as_no_domain_warrant(db):
    """SQL's own statement of the warrant rule (`cwg_evidence`, 012t), read directly: the loop
    never asks SQL to move belief on a link it cannot warrant, so the differential check alone
    would not see SQL reading one as DOMAIN. One case observes all three withdrawn links."""
    candidate, registered = candidate_declarations()
    fx = load_fixture(FIXTURE)
    run = run_case(
        db, fx, case_by_id(fx, "mesh-coarse-access"), declarations=candidate, registered=registered
    )
    assert run.request is not None
    warrants: dict[tuple[str, str], set[object]] = {}
    for certificate in run.request.certificates:
        mechanism = certificate.hypothesis.mechanism
        for row in db.execute(
            "SELECT relation_type, warrant FROM cwg_evidence(%s, %s)",
            (run.request.project_id, certificate.hypothesis.hypothesis_id),
        ).fetchall():
            warrants.setdefault((mechanism, row[0]), set()).add(row[1])
    assert warrants[("mesh convergence artifact", "SUPPORTS")] == {None}
    assert warrants[("access contact discontinuity", "CONTRADICTS")] == {None}
    assert warrants[("dopant compensation in the rib", "CONTRADICTS")] == {None}
    assert warrants[("length normalization error", "CONTRADICTS")] == {"DOMAIN"}, "the control"


def test_sql_registers_the_withdrawn_links_and_refuses_a_malformed_one(db):
    candidate, registered = candidate_declarations()
    fx = load_fixture(FIXTURE)
    run_case(
        db, fx, case_by_id(fx, "contact-open-via"), declarations=candidate, registered=registered
    )
    rows = db.execute(
        "SELECT set_ref, class_id, review_only, active FROM diagnostic_declarations"
        " ORDER BY set_ref, class_id"
    ).fetchall()
    held = {(r[0], r[1]): (list(r[2]), r[3]) for r in rows}
    assert {k[0] for k in held} == {"sp.rs_anomaly_mechanisms@1.0.0", candidate.ref}
    assert all(v == ([], False) for k, v in held.items() if k[0].endswith("@1.0.0"))
    assert held[(candidate.ref, "contact_discontinuity")] == (["CONTRADICTS"], True)
    assert held[(candidate.ref, "dopant_compensation")] == (["CONTRADICTS"], True)
    assert held[(candidate.ref, "mesh_artifact")] == (["SUPPORTS"], True)
    assert held[(candidate.ref, "normalization_error")] == ([], True)
    declaration = candidate.canonical_form()["declarations"][0]
    for bad in (["PREDICTS"], ["SUPPORTS", "SUPPORTS"], "SUPPORTS", [1]):
        with pytest.raises(psycopg.errors.RaiseException, match="malformed declaration"):
            db.execute(
                "INSERT INTO diagnostic_declaration_sets (set_id, version, domain, digest,"
                " declarations) VALUES ('sp.malformed', '1.0.0', 'x', %s, %s::jsonb)",
                ("sha256:" + "0" * 64, json.dumps([{**declaration, "review_only": bad}])),
            )


def test_the_committed_report_is_current(benchmark):
    candidate, _ = candidate_declarations()
    rendered = (
        render_report(
            benchmark,
            FIXTURE.relative_to(ROOT).as_posix(),
            title="VS-SP-001 root-cause benchmark 1.1.0 under CANDIDATE declarations (not active)",
            checked_by="tests/e2e/test_sp_candidate_declarations_postgres.py",
            declarations=f"{candidate.ref} ({candidate.digest}), registered beside 1.0.0",
        )
        + "\n"
    )
    committed = REPORT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == rendered, (
        f"{REPORT.relative_to(ROOT).as_posix()} is stale: regenerate it with "
        "`python scripts/run_root_cause_benchmark.py --disposable --candidate`"
    )
