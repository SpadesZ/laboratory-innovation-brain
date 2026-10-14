"""The Causal Warrant Gate, end to end on PostgreSQL: the counterexamples and the controls.

1. PROXY SUPPORT. Recorded reproduction: `epi:7b56877f` (2026-10-13, `prj:bench-gemini`). The true
mechanism (a length normalization error) was not among the rivals, and a hypothesis whose mechanism
cannot change the normalization basis declared `sp.normalization_basis = DISAGREES -> SUPPORTS`.
The check observed DISAGREES because of the true cause, and the loop CONFIRMED the wrong
mechanism. Reproduced here without a model: `run_case` takes the fixture as data, so the
counterexample is the fixture with the normalization rival's mechanism and statement replaced and
its predictions kept -- the certificate shape the recorded run produced.

2. SHARED SUPPORT. Found while designing the gate: when another rival also affirms the outcome --
as SUPPORTS or as PREDICTS -- one observation does not tell the two apart. Before the gate it
promoted both and the loop confirmed whichever hypothesis id sorted first.

THE CONTROLS ARE THE POINT AS MUCH AS THE COUNTEREXAMPLES. A gate that refused everything would pass
every negative test here. So the catalog mechanism must still confirm on its own check; a mechanism
nobody catalogued must be confirmable once a person warrants its link; and a shared observation
must stop blocking once the rival is excluded by its own warranted refutation.

`docs/implementation/causal-warrant-gate-v1.md` is the design these tests hold.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import io
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.failure import ResolutionStatus
from lab_brain.core.models.review import ReviewStatus
from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore, WarrantStoreError
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.interfaces import cli
from lab_brain.verification.loop import StopReason
from tests.debate_fixtures import ACTOR, PROJECT
from tests.postgres_fixtures import database_url
from tests.vertical_fixtures import case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres

CASE = "normalization-taper"
PROXY_MECHANISM = "missing contact-resistance correction"
NOVEL_MECHANISM = "taper sections counted into the normalization length"
DOMAIN_REF = "dds:sp.rs_anomaly_mechanisms@1.0.0#normalization_error"
REVIEWER = "act:pi"
#: Long enough that a review created on the fixture's clock is still open at T0.
EXPIRY_MINUTES = 10_000_000
T0 = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.UTC)


def _queue(db: Any) -> None:
    """A review queue and an accountable reviewer, so a warrant can be asked for and answered."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'M3') ON CONFLICT DO NOTHING",
        (PROJECT,),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
        " ON CONFLICT DO NOTHING",
        (REVIEWER, REVIEWER),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'PI', ARRAY['PUBLIC', 'INTERNAL'],"
        " ARRAY[]::text[], TRUE) ON CONFLICT DO NOTHING",
        (REVIEWER, PROJECT),
    )
    db.execute(
        "INSERT INTO review_queue_policies (policy_id, version, project_id, capacity,"
        " default_sla_minutes, default_expiry_minutes, declared_by_actor_id, effective_from,"
        " active) VALUES ('rqp:test', '1.0.0', %s, 10, 60, %s, %s, %s, TRUE)",
        (PROJECT, EXPIRY_MINUTES, REVIEWER, T0),
    )


def _renamed(mechanism: str, statement: str) -> dict[str, Any]:
    """The fixture with the normalization rival's mechanism and statement replaced."""
    fx = copy.deepcopy(load_fixture())
    rival = fx["mechanisms"]["normalization_error"]
    rival["mechanism"] = mechanism
    rival["statement"] = statement
    return fx


def _proxy() -> dict[str, Any]:
    return _renamed(
        PROXY_MECHANISM,
        "The extraction omits the contact-resistance correction term, leaving the reported series "
        "resistance uncorrected.",
    )


def _shared(effect: str) -> dict[str, Any]:
    """The contact rival also affirms the normalization check's DISAGREES, as `effect`."""
    fx = copy.deepcopy(load_fixture())
    contact = fx["mechanisms"]["contact_discontinuity"]
    affirm = next(
        p
        for p in fx["mechanisms"]["normalization_error"]["predictions"]
        if p["relation_effect"] == "SUPPORTS"
    )
    contact["predictions"] = [*contact["predictions"], {**affirm, "relation_effect": effect}]
    return fx


def _promoted(run: Any) -> set[str]:
    return {
        str(run.mechanism_of(t.hypothesis_id))
        for s in run.result.steps
        for t in s.transitions
        if t.to_state == "SUPPORTED" and t.event_id
    }


# -- controls -----------------------------------------------------------------------------------


def test_the_catalog_mechanism_confirms_on_its_own_check_with_a_domain_warrant(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    assert run.result.stop_reason is StopReason.CONFIRMED
    assert run.mechanism_of(run.result.confirmed_root_cause) == "normalization_error"
    assert analysis.failure_class == "length normalization error"
    assert analysis.warrant_refs == (DOMAIN_REF,)


def test_a_person_can_warrant_an_uncatalogued_mechanism_and_only_then_it_confirms(db):
    """A genuinely new account of the true cause is not refused -- and not confirmed unasked."""
    _queue(db)
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert "normalization_error" not in _promoted(run)
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    assert review.subject_type.value == "DIAGNOSTIC_WARRANT"

    grant = store.resolve(
        resolution_id="res:warrant-1",
        grant_id="dwg:1",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        actor_id=REVIEWER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=tuple(sorted(run.certificates_by_mechanism.values())),
        resolved_at=T0,
    )
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(run.request)
    assert resumed.stop_reason is StopReason.CONFIRMED
    assert resumed.failure_analysis.failure_class == NOVEL_MECHANISM
    assert resumed.failure_analysis.warrant_refs == (grant.grant_id,)


# -- proxy support --------------------------------------------------------------------------------


def test_a_proxy_support_is_never_promoted_and_a_person_is_asked(db):
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    assert analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert analysis.resolution_status is ResolutionStatus.OPEN
    assert "normalization_error" not in _promoted(run)
    proxy = run.certificates_by_mechanism["normalization_error"]
    (review,) = SqlDiagnosticWarrantStore(db).outstanding(PROJECT)
    asked = db.execute(
        "SELECT to_entity_id, relation_type, attributes ->> 'outcome' FROM relation_judgments"
        " WHERE relation_id = %s",
        (review.subject_id,),
    ).fetchone()
    assert tuple(asked) == (proxy, "SUPPORTS", "DISAGREES")
    # The relation names who claimed what the outcome means -- the prediction's author -- not
    # only the person who ran the episode.
    authored = db.execute(
        "SELECT r.inference_provenance_id, p.inference_provenance_id FROM relation_judgments r"
        " JOIN predictions p ON p.prediction_id = r.attributes ->> 'prediction_id'"
        " WHERE r.relation_id = %s",
        (review.subject_id,),
    ).fetchone()
    assert authored[0] is not None and authored[0] == authored[1]
    refusals = [
        t.refusal for s in run.result.steps for t in s.transitions if t.hypothesis_id == proxy
    ]
    assert refusals and all(r and r.startswith("DIAGNOSTIC_WARRANT_MISSING") for r in refusals)


def test_without_a_review_queue_the_question_is_recorded_and_the_belief_stays(db):
    """Fail closed: nobody can be asked, so nothing moves, and the record says why."""
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    proxy = run.certificates_by_mechanism["normalization_error"]
    refusals = [
        t.refusal or "" for s in run.result.steps for t in s.transitions if t.hypothesis_id == proxy
    ]
    assert any("no active review queue policy" in r for r in refusals)


def test_a_refused_warrant_never_counts_and_is_not_asked_again(db):
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.resolve(
        resolution_id="res:warrant-2",
        grant_id="dwg:2",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.REJECTED,
        actor_id=REVIEWER,
        rationale="a missing contact-resistance term cannot change the normalization length",
        considered_rival_ids=(),
        resolved_at=T0,
    )
    with pytest.raises(WarrantStoreError, match="already"):
        store.resolve(
            resolution_id="res:warrant-3",
            grant_id="dwg:3",
            review_id=review.review_id,
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            actor_id=REVIEWER,
            rationale="second thoughts",
            considered_rival_ids=(),
            resolved_at=T0,
        )
    assert run.loop is not None and run.request is not None
    # Resumed with nothing runnable, so the loop re-evaluates every belief and executes nothing.
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert "normalization_error" not in _promoted(run)
    assert store.outstanding(PROJECT) == ()
    asked = db.execute(
        "SELECT count(*) FROM review_items WHERE subject_type = 'DIAGNOSTIC_WARRANT'"
    ).fetchone()
    assert asked[0] == 1, "a refused warrant is an answer, not a question to ask again"
    status = db.execute(
        "SELECT status FROM review_items WHERE review_id = %s", (review.review_id,)
    ).fetchone()
    assert status[0] == ReviewStatus.REJECTED.value


def test_only_a_human_member_of_the_project_can_answer(db):
    _queue(db)
    fx = _proxy()
    run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    with pytest.raises(WarrantStoreError, match="not an active human member"):
        store.resolve(
            resolution_id="res:warrant-4",
            grant_id="dwg:4",
            review_id=review.review_id,
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            actor_id="act:nobody",
            rationale="r",
            considered_rival_ids=(),
            resolved_at=T0,
        )


# -- shared support -------------------------------------------------------------------------------


@pytest.mark.parametrize("queue", [False, True], ids=["no-queue", "queue"])
@pytest.mark.parametrize("effect", ["SUPPORTS", "PREDICTS"])
def test_a_shared_observation_confirms_only_after_the_rival_is_excluded_by_its_own_check(
    db, effect, queue
):
    """The rival's own declared check refutes it; then, and only then, the true cause stands.

    With a review queue the rival's unwarranted support has a question waiting -- and once a
    warranted refutation excludes the rival, that question can no longer change the answer.
    """
    if queue:
        _queue(db)
    fx = _shared(effect)
    run = run_case(db, fx, case_by_id(fx, CASE))
    steps = run.result.steps
    assert steps[0].chosen == sp.CAP_EXTRACTION_CONSISTENCY
    assert sp.CAP_INSPECT_CONNECTIVITY in [s.chosen for s in steps[1:]], (
        "the loop must test the rival that shares the observation before confirming"
    )
    assert run.result.stop_reason is StopReason.CONFIRMED
    assert run.mechanism_of(run.result.confirmed_root_cause) == "normalization_error"
    assert "contact_discontinuity" not in _promoted(run)


@pytest.mark.parametrize("effect", ["SUPPORTS", "PREDICTS"])
def test_a_shared_observation_whose_rival_cannot_be_tested_confirms_nothing(db, effect):
    fx = _shared(effect)
    case = {**case_by_id(fx, CASE), "unavailable": [sp.CAP_INSPECT_CONNECTIVITY]}
    run = run_case(db, fx, case)
    analysis = run.result.failure_analysis
    assert analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert "normalization_error" in _promoted(run), "its support is warranted; it is SUPPORTED"
    assert any("does not tell them apart" in note for note in run.result.notes), run.result.notes


def test_the_report_names_the_unproposed_class_whose_signature_was_observed(db):
    """The recorded failure's missing rival, named without adding a hypothesis or moving a belief."""
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert any(
        "declared signature of 'length normalization error'" in note
        and "no hypothesis in this set states" in note
        for note in run.result.notes
    ), run.result.notes


def test_a_person_answers_through_the_command_line(db):
    _queue(db)
    fx = _proxy()
    run_case(db, fx, case_by_id(fx, CASE))
    (review,) = SqlDiagnosticWarrantStore(db).outstanding(PROJECT)

    def cli_run(*argv: str) -> tuple[int, str]:
        out = io.StringIO()
        code = cli.main(
            list(argv),
            out=out,
            env={"LAB_BRAIN_DATABASE_URL": database_url()},
            connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
        )
        return code, out.getvalue()

    who = ("--project", PROJECT, "--actor", REVIEWER)
    code, listed = cli_run("review", "list", *who)
    assert code == 0 and review.review_id in listed
    code, packet = cli_run("review", "show", review.review_id, *who)
    assert code == 0 and PROXY_MECHANISM in packet and "DISAGREES SUPPORTS" in packet
    code, refused = cli_run("review", "list", "--project", PROJECT, "--actor", "act:nobody")
    assert code == 1 and review.review_id not in refused
    code, answered = cli_run(
        "review",
        "resolve",
        review.review_id,
        *who,
        "--outcome",
        "REJECTED",
        "--rationale",
        "a missing contact-resistance term cannot change the normalization length",
    )
    assert code == 0 and "NOT_WARRANTED" in answered
    code, again = cli_run(
        "review", "resolve", review.review_id, *who, "--outcome", "APPROVED", "--rationale", "x"
    )
    assert code == 1 and "No outstanding review" in again


def test_the_person_who_ran_the_episode_cannot_warrant_its_relations(db):
    _queue(db)
    fx = _proxy()
    run_case(db, fx, case_by_id(fx, CASE))
    # The researcher who ran the episode is a member too -- membership is not what refuses them.
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC', 'INTERNAL'],"
        " ARRAY[]::text[], TRUE) ON CONFLICT DO NOTHING",
        (ACTOR, PROJECT),
    )
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    with pytest.raises(WarrantStoreError, match="ran the episode"):
        store.resolve(
            resolution_id="res:self",
            grant_id="dwg:self",
            review_id=review.review_id,
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            actor_id=ACTOR,
            rationale="my own run looks right to me",
            considered_rival_ids=(),
            resolved_at=T0,
        )


def test_an_expired_review_is_not_answered_late(db):
    _queue(db)
    fx = _proxy()
    run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    assert review.expires_at is not None
    with pytest.raises(WarrantStoreError, match="expired"):
        store.resolve(
            resolution_id="res:late",
            grant_id="dwg:late",
            review_id=review.review_id,
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            actor_id=REVIEWER,
            rationale="late",
            considered_rival_ids=(),
            resolved_at=review.expires_at + dt.timedelta(minutes=1),
        )


def _contact_with_a_proxy_falsifier() -> dict[str, Any]:
    """The true contact cause, as the catalog states it, plus the recorded `epi:6174b0fe` shape:
    a falsifier on the normalization basis, which a contact defect cannot change."""
    fx = copy.deepcopy(load_fixture())
    contact = fx["mechanisms"]["contact_discontinuity"]
    proxy = next(
        p
        for p in fx["mechanisms"]["normalization_error"]["predictions"]
        if p["relation_effect"] == "CONTRADICTS"
    )
    contact["predictions"] = [*contact["predictions"], copy.deepcopy(proxy)]
    return fx


def test_an_unwarranted_falsifier_neither_vetoes_nor_is_ignored(db):
    """Before the gate, the proxy falsifier rejected the hypothesis; with SUPPORTS also present it
    silently froze it. Now the warranted support counts, the falsifier goes to a person, and the
    cause is confirmed once that person says the normalization basis cannot speak to it."""
    _queue(db)
    fx = _contact_with_a_proxy_falsifier()
    case = case_by_id(fx, "contact-open-via")
    run = run_case(db, fx, case)
    contact = run.certificates_by_mechanism["contact_discontinuity"]
    assert "contact_discontinuity" in _promoted(run), "the warranted support was vetoed"
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    # Parked, not concluded: waiting on a person -- for the warrant answer, or for a check only a
    # person can run.
    assert run.result.failure_analysis.resolution_status is ResolutionStatus.OPEN
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    asked = db.execute(
        "SELECT to_entity_id, relation_type FROM relation_judgments WHERE relation_id = %s",
        (review.subject_id,),
    ).fetchone()
    assert tuple(asked) == (contact, "CONTRADICTS")
    store.resolve(
        resolution_id="res:proxy-falsifier",
        grant_id="dwg:proxy-falsifier",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.REJECTED,
        actor_id=REVIEWER,
        rationale="an open contact via does not change the extraction's normalization length",
        considered_rival_ids=(),
        resolved_at=T0,
    )
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.stop_reason is StopReason.CONFIRMED
    assert resumed.confirmed_root_cause == contact


# -- the database holds the rules for every writer ------------------------------------------------


def test_a_grant_written_directly_is_refused_whoever_writes_it(db):
    """A grant exists only as its review's closure: a raw INSERT -- by a member or not -- with the
    review left QUEUED and no resolution is refused, and the proxy stays unconfirmed."""
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    (review,) = SqlDiagnosticWarrantStore(db).outstanding(PROJECT)
    relation = db.execute(
        "SELECT to_entity_id, attributes ->> 'prediction_id' FROM relation_judgments"
        " WHERE relation_id = %s",
        (review.subject_id,),
    ).fetchone()
    for granter in ("act:llm-agent", REVIEWER):
        db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
            " ON CONFLICT DO NOTHING",
            (granter, granter),
        )
        with pytest.raises(psycopg.Error, match=r"not an active human member|not the closure"):
            db.execute(
                "INSERT INTO diagnostic_warrant_grants (grant_id, project_id, review_id,"
                " relation_id, relation_type, hypothesis_id, prediction_id, verdict,"
                " granted_by_actor_id, granted_at, rationale) VALUES (%s, %s, %s, %s, 'SUPPORTS',"
                " %s, %s, 'WARRANTED', %s, %s, 'forged')",
                (
                    f"dwg:forged-{granter}",
                    PROJECT,
                    review.review_id,
                    review.subject_id,
                    relation[0],
                    relation[1],
                    granter,
                    T0,
                ),
            )
    assert db.execute("SELECT count(*) FROM diagnostic_warrant_grants").fetchone()[0] == 0
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED


def test_a_relation_cannot_be_rewritten_under_its_warrant(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    (relation_id,) = next(s.relation_ids for s in run.result.steps if s.relation_ids)
    with pytest.raises(psycopg.Error, match="immutable"):
        db.execute(
            'UPDATE relation_judgments SET attributes = attributes || \'{"outcome": "AGREES"}\''
            " WHERE relation_id = %s",
            (relation_id,),
        )
    # An invalidation is still a recordable fact.
    db.execute(
        "UPDATE relation_judgments SET valid_to = %s, invalidation_reason = 'superseded'"
        " WHERE relation_id = %s",
        (T0, relation_id),
    )


def test_a_confirmation_citing_a_warrant_that_does_not_exist_is_refused(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    with pytest.raises(psycopg.Error, match="neither a declaration reference"):
        db.execute(
            "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
            " expected_behavior, observed_behavior, candidate_causes, confirmed_root_cause,"
            " root_cause_evidence_ids, failure_class, resolution_status, created_at,"
            " warrant_refs) VALUES ('fan:fake-warrant', %s, %s, 's', 'e', 'o', %s, %s, %s, 'c',"
            " 'CONFIRMED', %s, ARRAY['dwg:nobody-granted-this'])",
            (
                PROJECT,
                analysis.episode_id,
                list(analysis.candidate_causes),
                analysis.confirmed_root_cause,
                list(analysis.root_cause_evidence_ids),
                T0,
            ),
        )
