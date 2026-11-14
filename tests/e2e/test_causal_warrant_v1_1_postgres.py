"""Causal Warrant Gate V1.1, end to end on PostgreSQL: the V1 audit's open gaps, closed or held.

1. IMPERSONATION (V1 review 8, A2). Anyone with database access could answer a warrant review as
   the PI: the answering actor was a parameter. Now an answer is signed under a key a pinned
   authority enrolled; a row written as the PI without the PI's key is recorded and counts for
   nothing, and an enrolment row written without the authority's key enrols nobody.
2. DIRECT CONFIRMED ROWS (review 8, finding 3). The database refused a confirmation only for its
   trace and its warrant references. It now evaluates the loop's confirmation rule over the
   recorded evidence, for every writer.
3. OPERATIONS. A review queue is declared by command; an overdue review is closed by the expiry
   sweep every research run performs, and asked again.
4. THE RECORDED FALSE CONFIRMATION. `fan:30d9407f` is flagged where it exists, by its exact
   content, without being edited.

The controls matter as much: a correctly signed answer still confirms, a confirmation that holds
the rule is still accepted, and a flagged conclusion is still on record.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import io
import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.failure import ResolutionStatus
from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.models.reviewer import grant_statement
from lab_brain.core.repositories.evidence import SqlRelationStore
from lab_brain.core.repositories.failures import SqlFailureStore
from lab_brain.core.repositories.warrants import (
    SqlDeclarationSetStore,
    SqlDiagnosticWarrantStore,
    WarrantStoreError,
)
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.product import diagnostic_declaration_set
from lab_brain.interfaces import cli
from lab_brain.research.episode_view import load_episode_view
from lab_brain.security.reviewer_identity import ReviewerSigner, sign_revocation
from lab_brain.storage.postgres.warrants import confirmation_verifier
from lab_brain.verification.loop import StopReason
from tests.debate_fixtures import ACTOR, PROJECT
from tests.e2e.test_causal_warrant_counterexample_postgres import (
    CASE,
    DOMAIN_REF,
    NOVEL_MECHANISM,
    REVIEWER,
    SIGNER,
    T0,
    _promoted,
    _proxy,
    _queue,
    _renamed,
    _shared,
)
from tests.postgres_fixtures import database_url, reset_database
from tests.reviewer_keys import AUTHORITY, AUTHORITY_ACTOR, TRUST, key_for
from tests.vertical_fixtures import assert_rules_agree, case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres


def _main(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        list(argv),
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    return code, out.getvalue()


def _forged_signature(statement: bytes) -> str:
    """What an impostor can produce: a valid Ed25519 signature -- under the wrong key."""
    return key_for("act:impostor").sign(statement)


# -- 1. who answered is proved ----------------------------------------------------------------


def test_an_answer_written_as_the_pi_without_the_pis_key_counts_for_nothing(db):
    """A2 as recorded: `diagnostic_warrant_resolve(..., 'act:pi', ..., --is-class)` from any
    connection. The database cannot check a signature, so the row is written; the loop counts it
    as no answer, nothing is promoted or confirmed, and the record says why."""
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    relation = db.execute(
        "SELECT relation_type, to_entity_id, attributes ->> 'prediction_id' FROM"
        " relation_judgments WHERE relation_id = %s",
        (review.subject_id,),
    ).fetchone()
    # The V1 call, unsigned, no longer exists.
    with pytest.raises(psycopg.Error, match="does not exist"):
        db.execute(
            "SELECT diagnostic_warrant_resolve(%s, %s, %s, %s, 'APPROVED', %s, 'forged',"
            " ARRAY[]::text[], %s, %s)",
            ("res:v1", "dwg:v1", review.review_id, PROJECT, REVIEWER, T0, DOMAIN_REF),
        )
    # Unsigned through the V1.1 function: refused.
    with pytest.raises(psycopg.Error, match="unsigned"):
        db.execute(
            "SELECT diagnostic_warrant_resolve(%s, %s, %s, %s, 'APPROVED', %s, 'forged',"
            " ARRAY[]::text[], %s, NULL, NULL, %s)",
            ("res:none", "dwg:none", review.review_id, PROJECT, REVIEWER, T0, DOMAIN_REF),
        )
    statement = grant_statement(
        grant_id="dwg:impostor",
        project_id=PROJECT,
        review_id=review.review_id,
        relation_id=review.subject_id,
        relation_type=str(relation[0]),
        hypothesis_id=str(relation[1]),
        prediction_id=str(relation[2]),
        verdict="WARRANTED",
        granted_by_actor_id=REVIEWER,
        granted_at=T0,
        rationale="forged",
        considered_rival_ids=(),
        identifies_class_ref=DOMAIN_REF,
        enrolment_id=SIGNER.enrolment_id,
    )
    db.execute(
        "SELECT diagnostic_warrant_resolve(%s, %s, %s, %s, 'APPROVED', %s, 'forged',"
        " ARRAY[]::text[], %s, %s, %s, %s)",
        (
            "res:impostor",
            "dwg:impostor",
            review.review_id,
            PROJECT,
            REVIEWER,
            T0,
            SIGNER.enrolment_id,
            _forged_signature(statement),
            DOMAIN_REF,
        ),
    )
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert "normalization_error" not in _promoted(run)
    assert any(
        n.startswith(f"the answer recorded on {review.subject_id} counts as no answer")
        and "reviewer's signature does not verify" in n
        for n in resumed.notes
    ), resumed.notes


def test_an_enrolment_written_without_the_authoritys_key_enrols_nobody(db):
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    impostor = key_for("act:impostor")
    # A row naming the pinned authority, signed by a key that is not it.
    db.execute(
        "INSERT INTO warrant_reviewer_enrolments (enrolment_id, project_id, actor_id, public_key,"
        " key_id, scope, enrolled_at, authority_actor_id, authority_key_id, authority_signature)"
        " VALUES ('enr:forged', %s, %s, %s, %s, 'DIAGNOSTIC_WARRANT', %s, %s, %s, %s)",
        (
            PROJECT,
            REVIEWER,
            impostor.public_key,
            impostor.key_id,
            T0 - dt.timedelta(days=1),
            AUTHORITY_ACTOR,
            AUTHORITY.key_id,
            impostor.sign(b"not the enrolment statement"),
        ),
    )
    store.resolve(
        resolution_id="res:forged-enrolment",
        grant_id="dwg:forged-enrolment",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=ReviewerSigner(actor_id=REVIEWER, enrolment_id="enr:forged", key=impostor),
        rationale="signed with a key nobody enrolled",
        considered_rival_ids=(),
        resolved_at=T0,
        identifies_class_ref=DOMAIN_REF,
    )
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert any("authority's signature does not verify" in n for n in resumed.notes), resumed.notes
    code, keys = _main("review", "keys", "--project", PROJECT, "--actor", REVIEWER)
    assert code == 0 and "enr:forged" in keys and "DOES NOT VERIFY" in keys


def test_the_database_refuses_self_enrolment_shared_keys_and_non_members(db):
    _queue(db)
    store = SqlDiagnosticWarrantStore(db)
    key = key_for(REVIEWER)

    def insert(enrolment_id: str, actor: str, authority: str, public_key: str, key_id: str) -> None:
        db.execute(
            "INSERT INTO warrant_reviewer_enrolments (enrolment_id, project_id, actor_id,"
            " public_key, key_id, scope, enrolled_at, authority_actor_id, authority_key_id,"
            " authority_signature) VALUES (%s, %s, %s, %s, %s, 'DIAGNOSTIC_WARRANT', %s, %s, %s,"
            " %s)",
            (
                enrolment_id,
                PROJECT,
                actor,
                public_key,
                key_id,
                T0,
                authority,
                AUTHORITY.key_id,
                AUTHORITY.sign(b"x"),
            ),
        )

    with pytest.raises(psycopg.Error, match="not_self_authorized"):
        insert("enr:self", REVIEWER, REVIEWER, key.public_key, key.key_id)
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
        " ON CONFLICT DO NOTHING",
        (ACTOR, ACTOR),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC'],"
        " ARRAY[]::text[], TRUE) ON CONFLICT DO NOTHING",
        (ACTOR, PROJECT),
    )
    with pytest.raises(psycopg.Error, match="already enrolled for another person"):
        insert("enr:shared", ACTOR, AUTHORITY_ACTOR, key.public_key, key.key_id)
    with pytest.raises(psycopg.Error, match="key_id_is_the_key"):
        insert("enr:mislabelled", ACTOR, AUTHORITY_ACTOR, key.public_key, "rk:" + "0" * 32)
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:outsider', 'HUMAN',"
        " 'outsider') ON CONFLICT DO NOTHING"
    )
    outsider = key_for("act:outsider")
    with pytest.raises(psycopg.Error, match="not an active human member"):
        insert(
            "enr:outsider", "act:outsider", AUTHORITY_ACTOR, outsider.public_key, outsider.key_id
        )
    with pytest.raises(psycopg.Error, match="append-only"):
        db.execute("UPDATE warrant_reviewer_enrolments SET actor_id = %s", (ACTOR,))
    assert [e.enrolment_id for e in store.enrolments(PROJECT)] == [SIGNER.enrolment_id]


def test_a_revoked_key_answers_nothing_more(db):
    _queue(db)
    fx = _proxy()
    run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.revoke(
        sign_revocation(
            AUTHORITY,
            authority_actor_id=AUTHORITY_ACTOR,
            revocation_id="rvk:pi",
            enrolment_id=SIGNER.enrolment_id,
            project_id=PROJECT,
            effective_at=T0 - dt.timedelta(minutes=1),
            reason="key exposed",
        )
    )
    with pytest.raises(WarrantStoreError, match="revoked"):
        store.resolve(
            resolution_id="res:revoked",
            grant_id="dwg:revoked",
            review_id=review.review_id,
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            signer=SIGNER,
            rationale="answered with a revoked key",
            considered_rival_ids=(),
            resolved_at=T0,
        )
    with pytest.raises(psycopg.Error, match="revoked key is not enrolled again"):
        db.execute(
            "INSERT INTO warrant_reviewer_enrolments (enrolment_id, project_id, actor_id,"
            " public_key, key_id, scope, enrolled_at, authority_actor_id, authority_key_id,"
            " authority_signature) SELECT 'enr:again', project_id, actor_id, public_key, key_id,"
            " scope, enrolled_at, authority_actor_id, authority_key_id, authority_signature"
            " FROM warrant_reviewer_enrolments WHERE enrolment_id = %s",
            (SIGNER.enrolment_id,),
        )


def test_a_signed_answer_still_confirms_and_is_relied_on_only_where_it_verifies(db):
    """The control: the novel account of the true cause, identified by the PI's signed answer,
    confirms -- and case memory relies on the conclusion only when it can verify that answer."""
    _queue(db)
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    run = run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.resolve(
        resolution_id="res:signed",
        grant_id="dwg:signed",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=SIGNER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=(),
        resolved_at=T0,
        identifies_class_ref=DOMAIN_REF,
    )
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(run.request)
    assert resumed.stop_reason is StopReason.CONFIRMED
    confirmed = resumed.failure_analysis.failure_analysis_id
    trusted = SqlFailureStore(
        db,
        verify=confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),)),
    )
    assert confirmed in {a.failure_analysis_id for a in trusted.trusted_confirmations(PROJECT)}
    unverifiable = SqlFailureStore(db)
    assert confirmed not in {
        a.failure_analysis_id for a in unverifiable.trusted_confirmations(PROJECT)
    }
    # An answer in the same set that does not verify withholds the conclusion from reuse: the
    # database counted it, and nothing can say it did not shape the record.
    other = next(
        r.relation_id
        for h in run.certificates_by_mechanism.values()
        for r in SqlRelationStore(db).admitted_for_subject(PROJECT, h)
        if r.relation_type.value in ("SUPPORTS", "CONTRADICTS")
        and r.relation_id != review.subject_id
    )
    db.execute(
        "SELECT diagnostic_warrant_review_enqueue('rvw:other', %s, %s, 'NORMAL', 'x', 'trc:x',"
        " %s, %s, 15)",
        (PROJECT, other, run.request.episode_id, T0),
    )
    db.execute(
        "SELECT diagnostic_warrant_resolve('res:other', 'dwg:other', 'rvw:other', %s, 'REJECTED',"
        " %s, 'forged', ARRAY[]::text[], %s, %s, %s)",
        (PROJECT, REVIEWER, T0, SIGNER.enrolment_id, _forged_signature(b"anything")),
    )
    assert confirmed not in {a.failure_analysis_id for a in trusted.trusted_confirmations(PROJECT)}


# -- 2. the confirmation rule, for every writer ---------------------------------------------------


def _insert(db: Any, analysis: Any, **overrides: Any) -> None:
    fields = {
        "failure_analysis_id": "fan:direct",
        "candidate_causes": list(analysis.candidate_causes),
        "confirmed_root_cause": analysis.confirmed_root_cause,
        "root_cause_evidence_ids": list(analysis.root_cause_evidence_ids),
        "failure_class": analysis.failure_class,
        "warrant_refs": list(analysis.warrant_refs),
        **overrides,
    }
    db.execute(
        "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
        " expected_behavior, observed_behavior, candidate_causes, confirmed_root_cause,"
        " root_cause_evidence_ids, failure_class, resolution_status, created_at, warrant_refs)"
        " VALUES (%(failure_analysis_id)s, %(project)s, %(episode)s, 's', 'e', 'o',"
        " %(candidate_causes)s, %(confirmed_root_cause)s, %(root_cause_evidence_ids)s,"
        " %(failure_class)s, 'CONFIRMED', %(at)s, %(warrant_refs)s)",
        {**fields, "project": PROJECT, "episode": analysis.episode_id, "at": T0},
    )


def _supported_but_unconfirmed(db: Any, run: Any, mechanism: str) -> Any:
    """What a direct writer would need: the cause, its traced evidence and its real warrant."""
    cause = run.certificates_by_mechanism[mechanism]
    support = db.execute(
        "SELECT r.supporting_attestation_ids FROM belief_revision_events e"
        " JOIN belief_revision_event_relations er ON er.event_id = e.event_id"
        " JOIN relation_judgments r ON r.relation_id = er.relation_id"
        " WHERE e.target_id = %s AND e.to_state = 'SUPPORTED' AND r.relation_type = 'SUPPORTS'"
        " ORDER BY e.occurred_at DESC LIMIT 1",
        (cause,),
    ).fetchone()
    declarations = diagnostic_declaration_set()
    declared = declarations.by_class(mechanism)
    assert declared is not None
    return _Analysis(
        episode_id=run.request.episode_id,
        candidate_causes=tuple(sorted(run.certificates_by_mechanism.values())),
        confirmed_root_cause=cause,
        root_cause_evidence_ids=tuple(support[0]),
        failure_class=declared.mechanism,
        warrant_refs=(declarations.domain_ref(declared),),
    )


@dataclasses.dataclass(frozen=True)
class _Analysis:
    episode_id: str
    candidate_causes: tuple[str, ...]
    confirmed_root_cause: str
    root_cause_evidence_ids: tuple[str, ...]
    failure_class: str
    warrant_refs: tuple[str, ...]


def test_a_direct_confirmation_of_one_of_two_observed_causes_is_refused(db):
    """Review 8, finding 3: two faults and no review queue; the loop concluded nothing, and a
    CONFIRMED row citing the cause's real warrant and evidence was accepted. Now it is refused,
    naming the other declared mechanism whose signature was observed."""
    fx = copy.deepcopy(load_fixture())
    rival = fx["mechanisms"]["normalization_error"]
    rival["mechanism"] = "missing contact-resistance correction"
    rival["statement"] = "The extraction omits the contact-resistance correction term."
    rival["predictions"] = [
        p for p in rival["predictions"] if p["relation_effect"] == "CONTRADICTS"
    ]
    case = copy.deepcopy(case_by_id(fx, "contact-open-via"))
    case["device"] = {**case["device"], "extraction_normalization_length_um": "1000"}
    run = run_case(db, fx, case)
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    forged = _supported_but_unconfirmed(db, run, "contact_discontinuity")
    with pytest.raises(psycopg.Error, match="declared signature of 'length normalization error'"):
        _insert(db, forged)


def test_a_direct_confirmation_over_an_undischarged_rival_is_refused(db):
    fx = _shared("PREDICTS")
    case = {**case_by_id(fx, CASE), "unavailable": [sp.CAP_INSPECT_CONNECTIVITY]}
    run = run_case(db, fx, case)
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    forged = _supported_but_unconfirmed(db, run, "normalization_error")
    with pytest.raises(psycopg.Error, match="affirm the observation supporting"):
        _insert(db, forged)


def test_a_direct_confirmation_must_name_every_rival_and_the_declared_class(db):
    """The control first: a second row repeating the loop's own confirmation is accepted."""
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    assert analysis.resolution_status is ResolutionStatus.CONFIRMED
    cause = analysis.confirmed_root_cause
    with pytest.raises(psycopg.Error, match="omits rivals"):
        _insert(db, analysis, failure_analysis_id="fan:alone", candidate_causes=[cause])
    with pytest.raises(psycopg.Error, match="is recorded as that class"):
        _insert(db, analysis, failure_analysis_id="fan:renamed", failure_class="something else")
    rival = next(h for h in analysis.candidate_causes if h != cause)
    with pytest.raises(psycopg.Error):
        _insert(db, analysis, failure_analysis_id="fan:rival", confirmed_root_cause=rival)
    _insert(db, analysis, failure_analysis_id="fan:repeat")


# -- 3. operations ------------------------------------------------------------------------------


def test_a_review_queue_is_declared_by_command_as_a_new_version(db):
    _queue(db)  # creates the project, its PI, and the test's own policy
    # A person who exists but is not a member of the project: expiry is not their decision here.
    code, printed = _main("admin", "review-queue", PROJECT, "--declared-by", AUTHORITY_ACTOR)
    assert code == 2 and "not an active person in" in printed, printed
    code, printed = _main(
        "admin", "review-queue", PROJECT, "--declared-by", REVIEWER, "--if-absent"
    )
    assert code == 0 and "unchanged" in printed
    code, printed = _main(
        "admin", "review-queue", PROJECT, "--declared-by", REVIEWER, "--expiry-minutes", "20160"
    )
    assert code == 0 and "replacing rqp:test@1.0.0" in printed, printed
    active = db.execute(
        "SELECT policy_id, version, default_expiry_minutes, declared_by_actor_id"
        " FROM review_queue_policies WHERE project_id = %s AND active",
        (PROJECT,),
    ).fetchall()
    assert [tuple(r) for r in active] == [
        ("rqp:" + PROJECT.removeprefix("prj:"), "1", 20160, REVIEWER)
    ]
    code, printed = _main(
        "admin", "review-queue", PROJECT, "--declared-by", REVIEWER, "--expiry-minutes", "20160"
    )
    assert code == 0 and "unchanged" in printed


def test_a_research_run_expires_overdue_reviews_before_it_verifies(db, tmp_path: Path):
    """Nothing else need schedule OPS-002's sweep: every run performs it for its project."""
    from tests.e2e.test_research_continuation_postgres import _continue, _open
    from tests.e2e.test_research_episode_postgres import ACTOR as RESEARCHER
    from tests.e2e.test_research_episode_postgres import PROJECT as LAB
    from tests.e2e.test_research_episode_postgres import _member

    _member(db)
    episode_id = _open(tmp_path, db)
    relation = db.execute(
        "SELECT r.relation_id FROM relation_judgments r JOIN hypotheses h"
        " ON h.hypothesis_id = r.to_entity_id WHERE r.project_id = %s"
        " AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS') AND h.created_in_episode = %s"
        " ORDER BY r.relation_id LIMIT 1",
        (LAB, episode_id),
    ).fetchone()
    assert relation is not None
    long_ago = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    db.execute(
        "INSERT INTO review_queue_policies (policy_id, version, project_id, capacity,"
        " default_sla_minutes, default_expiry_minutes, declared_by_actor_id, effective_from,"
        " active) VALUES ('rqp:lab', '1', %s, 10, 60, 120, %s, %s, TRUE)",
        (LAB, RESEARCHER, long_ago),
    )
    db.execute(
        "SELECT diagnostic_warrant_review_enqueue('rvw:overdue', %s, %s, 'NORMAL',"
        " 'DIAGNOSTIC_WARRANT_MISSING', 'trc:x', %s, %s, 15)",
        (LAB, relation[0], episode_id, long_ago),
    )
    # An overdue review of another subject: expiring it is a governance act on that subject (an
    # authority conflict's expiry would stop it blocking), so the research run leaves it alone.
    item = db.execute(
        "SELECT item_id FROM ingestion_items WHERE project_id = %s ORDER BY item_id LIMIT 1",
        (LAB,),
    ).fetchone()
    db.execute(
        "SELECT extraction_review_enqueue('rvw:other-subject', %s, %s, 'NORMAL', 'x', 'trc:x',"
        " %s, 15)",
        (LAB, item[0], long_ago),
    )
    code, printed = _continue(tmp_path, episode_id)
    assert code == 0, printed
    status = db.execute(
        "SELECT status FROM review_items WHERE review_id = 'rvw:overdue'"
    ).fetchone()
    assert status[0] == "EXPIRED"
    other = db.execute(
        "SELECT status FROM review_items WHERE review_id = 'rvw:other-subject'"
    ).fetchone()
    assert other[0] == "QUEUED", "a research run expires warrant questions only"
    closed = db.execute(
        "SELECT actor_id FROM governance_events WHERE subject_id = 'rvw:overdue'"
    ).fetchone()
    assert closed is not None and closed[0] == RESEARCHER


def test_registered_declarations_must_be_the_codes(db):
    declarations = diagnostic_declaration_set()
    store = SqlDeclarationSetStore(db)
    stale = list(declarations.model_dump(mode="json")["declarations"])
    db.execute(
        "INSERT INTO diagnostic_declaration_sets (set_id, version, domain, digest, declarations)"
        " VALUES (%s, %s, %s, %s, %s::jsonb)",
        (
            declarations.set_id,
            declarations.version,
            declarations.domain,
            "sha256:" + "0" * 64,
            json.dumps(stale),
        ),
    )
    with pytest.raises(WarrantStoreError, match="with digest sha256:0"):
        store.ensure((declarations,), declarations.ref)
    db.execute("TRUNCATE diagnostic_declaration_sets")
    store.ensure((declarations,), declarations.ref)
    store.ensure((declarations,), declarations.ref)  # idempotent
    with pytest.raises(psycopg.Error, match="append-only"):
        db.execute("UPDATE diagnostic_declaration_sets SET digest = digest")
    db.execute(
        "INSERT INTO diagnostic_declaration_sets (set_id, version, domain, digest, declarations,"
        " supersedes) SELECT set_id, '9.9.9', domain, digest, declarations, set_id || '@' ||"
        " version FROM diagnostic_declaration_sets WHERE set_id = %s",
        (declarations.set_id,),
    )
    with pytest.raises(WarrantStoreError, match=r"9.9.9, which this code does not declare"):
        store.ensure((declarations,), declarations.ref)
    # A set under ANOTHER id that declares a class on one of this code's observables is refused as
    # well: the SQL rule reads every active set, whatever it is called.
    db.execute("TRUNCATE diagnostic_declaration_sets")
    store.ensure((declarations,), declarations.ref)
    db.execute(
        "INSERT INTO diagnostic_declaration_sets (set_id, version, domain, digest, declarations)"
        " SELECT 'lookalike.set', '1', domain, digest, declarations FROM"
        " diagnostic_declaration_sets WHERE set_id = %s",
        (declarations.set_id,),
    )
    with pytest.raises(WarrantStoreError, match=r"lookalike.set@1, which this code does not"):
        store.ensure((declarations,), declarations.ref)


def test_reuse_refuses_a_domain_warrant_the_code_does_not_declare(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    verify = confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),))
    assert verify(analysis) is None
    forged = analysis.model_copy(
        update={"warrant_refs": ("dds:lookalike.set@1#normalization_error",)}
    )
    assert "names no declaration this code registers" in (verify(forged) or "")
    nothing = confirmation_verifier(db, TRUST, declaration_sets=())
    assert nothing(analysis) is not None, "a verifier that knows no declaration trusts none"


# -- 4. the recorded false confirmation -------------------------------------------------------------

FAN = "fan:30d9407f-f7ad-4b40-af4c-290edd5cc296"


def _replica_of_the_recorded_confirmation(db: Any) -> None:
    """The deployed row, as `contamination.out.txt` records it, inserted as it was in October:
    before `012o`, so with no warrant references. Its chain of evidence is not reproduced, so
    the row is written with triggers and keys suspended -- this test is about the flag, and the
    flag reads nothing but the row."""
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(
            "INSERT INTO projects (project_id, name) VALUES ('prj:bench-gemini', 'bench')"
            " ON CONFLICT DO NOTHING"
        )
        db.execute(
            "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
            " expected_behavior, observed_behavior, candidate_causes, confirmed_root_cause,"
            " root_cause_evidence_ids, failure_class, resolution_status, created_at)"
            " VALUES (%s, 'prj:bench-gemini', 'epi:7b56877f-9287-4075-a3c6-9980abab8eef',"
            " 'Rs high', 'design Rs', 'several times design',"
            " ARRAY['hyp:7c899579-5702-4307-b92d-0215496ea6ff'],"
            " 'hyp:7c899579-5702-4307-b92d-0215496ea6ff',"
            " ARRAY['att:e6831355-0121-4842-bced-50f8c23b437b'], 'missing correction artefact',"
            " 'CONFIRMED', '2026-10-13 12:20:37.335364+00')",
            (FAN,),
        )
    finally:
        db.execute("SET session_replication_role = origin")


def test_the_recorded_false_confirmation_is_flagged_and_left_as_written(db):
    _replica_of_the_recorded_confirmation(db)
    before = db.execute(
        "SELECT failure_analysis_digest(f) FROM failure_analyses f WHERE failure_analysis_id = %s",
        (FAN,),
    ).fetchone()[0]
    assert db.execute("SELECT flag_known_false_confirmations()").fetchone()[0] == 1
    assert db.execute("SELECT flag_known_false_confirmations()").fetchone()[0] == 0
    after = db.execute(
        "SELECT failure_analysis_digest(f) FROM failure_analyses f WHERE failure_analysis_id = %s",
        (FAN,),
    ).fetchone()[0]
    assert before == after, "the conclusion itself is untouched"
    store = SqlFailureStore(db)
    (flag,) = store.flags("prj:bench-gemini", FAN)
    assert flag.kind.value == "FALSE_CONFIRMATION" and flag.analysis_digest == before
    assert "length normalization error" in flag.statement
    assert store.trusted_confirmations("prj:bench-gemini") == ()
    view = load_episode_view(
        db, project_id="prj:bench-gemini", episode_id="epi:7b56877f-9287-4075-a3c6-9980abab8eef"
    )
    (conclusion,) = view.conclusions
    assert conclusion.status == "CONFIRMED" and conclusion.flags[0].kind == "FALSE_CONFIRMATION"
    assert conclusion.not_relied_on is not None
    with pytest.raises(psycopg.Error, match="append-only"):
        db.execute("UPDATE failure_analysis_flags SET statement = 'never mind'")


def test_a_row_that_is_not_the_recorded_one_is_not_flagged(db):
    """A deployment without that exact row gets nothing -- here, one field differs."""
    _replica_of_the_recorded_confirmation(db)
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(
            "UPDATE failure_analyses SET failure_class = 'something else'"
            " WHERE failure_analysis_id = %s",
            (FAN,),
        )
    finally:
        db.execute("SET session_replication_role = origin")
    assert db.execute("SELECT flag_known_false_confirmations()").fetchone()[0] == 0


def test_a_person_flags_a_conclusion_and_case_memory_stops_relying_on_it(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    store = SqlFailureStore(
        db,
        verify=confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),)),
    )
    assert analysis.failure_analysis_id in {
        a.failure_analysis_id for a in store.trusted_confirmations(PROJECT)
    }
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
        " ON CONFLICT DO NOTHING",
        (REVIEWER, REVIEWER),
    )
    flag_args = (
        "admin",
        "flag-analysis",
        analysis.failure_analysis_id,
        "--kind",
        "UNWARRANTED_CONFIRMATION",
        "--statement",
        "re-examined",
        "--evidence",
        "notebook",
        "--actor",
        REVIEWER,
    )
    code, printed = _main(*flag_args)
    assert code == 2 and "not an active member" in printed, "only a member flags a conclusion"
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'PI', ARRAY['PUBLIC'], ARRAY[]::text[], TRUE)"
        " ON CONFLICT DO NOTHING",
        (REVIEWER, PROJECT),
    )
    code, printed = _main(
        "admin",
        "flag-analysis",
        analysis.failure_analysis_id,
        "--kind",
        "UNWARRANTED_CONFIRMATION",
        "--statement",
        "re-examined: the extraction file was a draft",
        "--evidence",
        "lab notebook p. 12",
        "--actor",
        REVIEWER,
    )
    assert code == 0 and "flagged" in printed, printed
    assert analysis.failure_analysis_id not in {
        a.failure_analysis_id for a in store.trusted_confirmations(PROJECT)
    }
    assert store.similar_failures(PROJECT, analysis.symptom) == ()
    code, printed = _main(
        "admin",
        "flag-analysis",
        "fan:nothing",
        "--kind",
        "FALSE_CONFIRMATION",
        "--statement",
        "x",
        "--evidence",
        "y",
        "--actor",
        REVIEWER,
    )
    assert code == 2 and "no failure analysis" in printed


# -- more of the frame the database checks around a signature ---------------------------------------


def _resolve_as(db: Any, review: Any, signer: Any, at: dt.datetime) -> None:
    SqlDiagnosticWarrantStore(db).resolve(
        resolution_id=f"res:{signer.enrolment_id}:{at.isoformat()}",
        grant_id=f"dwg:{signer.enrolment_id}:{at.isoformat()}",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=signer,
        rationale="r",
        considered_rival_ids=(),
        resolved_at=at,
    )


def test_an_answer_is_signed_under_its_own_enrolment_and_after_it_and_the_question(db):
    _queue(db)
    fx = _proxy()
    run_case(db, fx, case_by_id(fx, CASE))
    (review,) = SqlDiagnosticWarrantStore(db).outstanding(PROJECT)
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:colleague', 'HUMAN',"
        " 'colleague') ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES ('act:colleague', %s, 'RESEARCHER', ARRAY['PUBLIC'],"
        " ARRAY[]::text[], TRUE)",
        (PROJECT,),
    )
    from tests.reviewer_keys import enrol

    colleague = enrol(SqlDiagnosticWarrantStore(db), project_id=PROJECT, actor_id="act:colleague")
    borrowed = ReviewerSigner(
        actor_id=REVIEWER, enrolment_id=colleague.enrolment_id, key=colleague.key
    )
    with pytest.raises(WarrantStoreError, match="is not act:pi's reviewer key"):
        _resolve_as(db, review, borrowed, T0)
    late_key = enrol(
        SqlDiagnosticWarrantStore(db),
        project_id=PROJECT,
        actor_id=REVIEWER,
        enrolment_id="enr:late",
        at=T0 + dt.timedelta(days=1),
        key=key_for("act:pi-new-laptop"),
    )
    with pytest.raises(WarrantStoreError, match="dated before enrolment"):
        _resolve_as(db, review, late_key, T0)
    with pytest.raises(WarrantStoreError, match="dated before review"):
        _resolve_as(db, review, SIGNER, review.created_at - dt.timedelta(minutes=1))


def test_an_authority_key_is_never_a_reviewer_key(db):
    _queue(db)
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:colleague', 'HUMAN',"
        " 'colleague') ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES ('act:colleague', %s, 'RESEARCHER', ARRAY['PUBLIC'],"
        " ARRAY[]::text[], TRUE)",
        (PROJECT,),
    )
    from tests.reviewer_keys import enrol

    with pytest.raises(WarrantStoreError, match="both as a review authority and as a reviewer"):
        enrol(
            SqlDiagnosticWarrantStore(db),
            project_id=PROJECT,
            actor_id="act:colleague",
            key=AUTHORITY,
        )


def test_revoking_a_key_from_before_its_answer_withdraws_the_answer(db):
    """The answer was signed, then the authority learned the key was compromised from earlier:
    the answer stops counting, the conclusion it supported stops being relied on, and the loop and
    the database agree that nothing is confirmable on it any more."""
    _queue(db)
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    run = run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.resolve(
        resolution_id="res:then-revoked",
        grant_id="dwg:then-revoked",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=SIGNER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=(),
        resolved_at=T0,
        identifies_class_ref=DOMAIN_REF,
    )
    store.revoke(
        sign_revocation(
            AUTHORITY,
            authority_actor_id=AUTHORITY_ACTOR,
            revocation_id="rvk:compromised",
            enrolment_id=SIGNER.enrolment_id,
            project_id=PROJECT,
            effective_at=T0 - dt.timedelta(hours=1),
            reason="the key was copied before this answer",
        )
    )
    assert run.loop is not None and run.request is not None
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert any("revoked from" in n for n in resumed.notes), resumed.notes


def test_a_class_binds_in_sql_only_over_its_whole_declaration(db):
    """`cwg_binds` -- the database's `DiagnosticDeclaration.binds`. Unreachable through the SP
    fixtures (the debate requires each hypothesis's designated falsifier, which completes the
    declaration), so asked directly of a hypothesis admitted with one signature and one refuting
    prediction."""
    from tests.postgres_fixtures import admit_hypothesis_identity

    db.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:test', 'test') ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:test', 'HUMAN',"
        " 'test') ON CONFLICT DO NOTHING"
    )
    admit_hypothesis_identity(db, "hyp:declared")

    def binds(supports: str, refutes: list[str]) -> bool:
        row = db.execute(
            "SELECT cwg_binds('prj:test', 'hyp:declared', 'test.observable', 'os:test.identity',"
            " '1.0.0', %s, %s)",
            (supports, refutes),
        ).fetchone()
        return bool(row[0])

    assert binds("OBSERVED", ["NOT_OBSERVED"]), "the whole declaration binds"
    assert not binds("OBSERVED", ["NOT_OBSERVED", "AMBIGUOUS"]), "a refuting outcome is missing"
    assert not binds("NOT_OBSERVED", ["OBSERVED"]), "the predictions disagree with the class"


def test_a_declaration_set_must_be_well_formed_and_supersede_its_own(db):
    declarations = diagnostic_declaration_set()
    body = list(declarations.model_dump(mode="json")["declarations"])

    def register(version: str, rows: Any, supersedes: str | None = None) -> None:
        db.execute(
            "INSERT INTO diagnostic_declaration_sets (set_id, version, domain, digest,"
            " declarations, supersedes) VALUES (%s, %s, 'test', %s, %s::jsonb, %s)",
            (
                "test.set",
                version,
                "sha256:" + "1" * 64,
                json.dumps(rows),
                supersedes,
            ),
        )

    with pytest.raises(psycopg.Error, match="twice"):
        register("1", [body[0], body[0]])
    with pytest.raises(psycopg.Error, match="malformed"):
        register("1", [{**body[0], "refutes_outcomes": []}])
    with pytest.raises(psycopg.Error, match="not an earlier registered version"):
        register("2", body, supersedes="test.set@1")
    register("1", body)
    register("2", body, supersedes="test.set@1")
    active = db.execute(
        "SELECT DISTINCT version FROM diagnostic_declarations WHERE set_id = 'test.set' AND active"
    ).fetchall()
    assert [r[0] for r in active] == ["2"]


def test_a_flag_names_the_exact_confirmation_it_flags(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    open_one = db.execute(
        "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
        " expected_behavior, observed_behavior, candidate_causes, failure_class,"
        " resolution_status, created_at) VALUES ('fan:open', %s, %s, 's', 'e', 'o', %s,"
        " 'UNRESOLVED', 'OPEN', %s) RETURNING failure_analysis_id",
        (PROJECT, analysis.episode_id, list(analysis.candidate_causes), T0),
    ).fetchone()

    def flag(target: str, digest: str) -> None:
        db.execute(
            "INSERT INTO failure_analysis_flags (flag_id, project_id, failure_analysis_id, kind,"
            " statement, evidence_refs, analysis_digest, recorded_by) VALUES (%s, %s, %s,"
            " 'FALSE_CONFIRMATION', 'wrong', ARRAY['audit'], %s, 'migration:test')",
            (f"flg:{target}", PROJECT, target, digest),
        )

    with pytest.raises(psycopg.Error, match="only a confirmation can be a false one"):
        flag(open_one[0], "sha256:" + "0" * 64)
    with pytest.raises(psycopg.Error, match="which is not what is stored"):
        flag(analysis.failure_analysis_id, "sha256:" + "0" * 64)
    digest = db.execute(
        "SELECT failure_analysis_digest(f) FROM failure_analyses f WHERE failure_analysis_id = %s",
        (analysis.failure_analysis_id,),
    ).fetchone()[0]
    flag(analysis.failure_analysis_id, digest)


# -- discrimination before confirmation (the science review's V1 and V9) ---------------------------


def test_two_faults_each_with_a_cheap_check_are_both_looked_at(db):
    """V1: an open cathode via AND a 2 % normalization mismatch. Both checks take two seconds.
    Before V1.1 the loop confirmed whichever check id sorted first and never inspected the via.
    Now every cheap check of an untested rival runs before a confirmation rests on its silence."""
    fx = load_fixture()
    case = copy.deepcopy(case_by_id(fx, "contact-open-via"))
    case["device"] = {**case["device"], "extraction_normalization_length_um": "510"}
    run = run_case(db, fx, case)
    executed = [s.chosen for s in run.result.steps if s.chosen is not None]
    assert sp.CAP_EXTRACTION_CONSISTENCY in executed and sp.CAP_INSPECT_CONNECTIVITY in executed
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert run.result.stop_reason is StopReason.COMPETING_SUPPORT


def test_a_cause_the_domain_declares_but_nobody_proposed_holds_the_conclusion(db):
    """V9, the recorded failure's shape: the true cause is not in the set. The contact defect is
    supported on its own check; the normalization check -- two seconds, declared, never run
    because nobody proposed the mechanism -- could have shown the other declared signature. So
    nothing is confirmed, and the note names the class and the check."""
    fx = copy.deepcopy(load_fixture())
    del fx["mechanisms"]["normalization_error"]
    case = copy.deepcopy(case_by_id(fx, "contact-thin-overlap"))
    case["device"] = {**case["device"], "extraction_normalization_length_um": "1000"}
    run = run_case(db, fx, case)
    assert run.result.stop_reason is StopReason.SUPPORTED_UNDISCRIMINATED
    assert run.result.failure_analysis.resolution_status is ResolutionStatus.OPEN
    assert any(
        "'length normalization error' was proposed by no hypothesis" in n
        and sp.CAP_EXTRACTION_CONSISTENCY in n
        for n in run.result.notes
    ), run.result.notes


def test_revoking_a_key_after_its_answer_moved_a_belief_withdraws_the_conclusion(db):
    """The answer confirmed the cause; then the authority learns the key was copied before the
    answer was given. The stored promotion no longer re-verifies: the conclusion stops being relied
    on, the database's rule no longer finds it confirmable, and continuing the episode records an
    open question instead of failing."""
    _queue(db)
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    run = run_case(db, fx, case_by_id(fx, CASE))
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.resolve(
        resolution_id="res:before-revocation",
        grant_id="dwg:before-revocation",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=SIGNER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=(),
        resolved_at=T0,
        identifies_class_ref=DOMAIN_REF,
    )
    assert run.loop is not None and run.request is not None
    confirmed = run.loop.run(run.request)
    assert confirmed.stop_reason is StopReason.CONFIRMED
    cause = confirmed.confirmed_root_cause
    store.revoke(
        sign_revocation(
            AUTHORITY,
            authority_actor_id=AUTHORITY_ACTOR,
            revocation_id="rvk:after",
            enrolment_id=SIGNER.enrolment_id,
            project_id=PROJECT,
            effective_at=T0 - dt.timedelta(hours=1),
            reason="the key was copied before this answer",
        )
    )
    breaches = db.execute(
        "SELECT confirmation_rule_breaches(%s, %s, %s)", (PROJECT, run.request.episode_id, cause)
    ).fetchone()[0]
    assert breaches, "the database no longer counts the revoked answer"
    trusted = SqlFailureStore(
        db,
        verify=confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),)),
    )
    assert confirmed.failure_analysis.failure_analysis_id not in {
        a.failure_analysis_id for a in trusted.trusted_confirmations(PROJECT)
    }
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is ResolutionStatus.OPEN
    assert any("does not re-verify" in n for n in resumed.notes), resumed.notes


def test_an_authority_revokes_from_the_command_line_from_a_stated_time(db, tmp_path: Path):
    _queue(db)
    run = run_case(db, *_novel_case())
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.resolve(
        resolution_id="res:to-withdraw",
        grant_id="dwg:to-withdraw",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=SIGNER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=(),
        resolved_at=T0,
    )
    authorities = tmp_path / "authorities"
    authorities.write_text(f"{AUTHORITY_ACTOR} ed25519:{AUTHORITY.public_key}\n", encoding="utf-8")
    authority_key = tmp_path / "authority.key"
    AUTHORITY.save(authority_key)
    env = {
        "LAB_BRAIN_DATABASE_URL": database_url(),
        "LAB_BRAIN_REVIEW_AUTHORITIES": str(authorities),
    }

    def revoke(at: str) -> tuple[int, str]:
        out = io.StringIO()
        code = cli.main(
            [
                "review",
                "revoke",
                SIGNER.enrolment_id,
                "--project",
                PROJECT,
                "--actor",
                AUTHORITY_ACTOR,
                "--authority-key",
                str(authority_key),
                "--reason",
                "the key was copied",
                "--effective-at",
                at,
            ],
            out=out,
            env=env,
            connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
        )
        return code, out.getvalue()

    code, printed = revoke("2999-01-01T00:00:00+00:00")
    assert code == 1 and "cannot be in the future" in printed, printed
    code, printed = revoke("2026-01-02T00:00:00+00:00")
    assert code == 0 and "withdraws dwg:to-withdraw" in printed, printed
    assert run.loop is not None


def _novel_case() -> tuple[Any, Any]:
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    return fx, case_by_id(fx, CASE)


def test_sql_reasons_under_the_codes_active_declaration_version_or_nothing_runs(db):
    current = diagnostic_declaration_set()
    later = current.model_copy(update={"version": "1.0.1"})
    store = SqlDeclarationSetStore(db)
    store.ensure((current, later), later.ref)
    with pytest.raises(WarrantStoreError, match="reasons under declaration set"):
        store.ensure((current, later), current.ref)


# -- reuse re-derives the conclusion (design review HIGH-1) ----------------------------------------


def _reuse_check(db: Any) -> Any:
    """The deployment's reuse check: answers and declarations, then the rule re-derived."""
    from lab_brain.domains.silicon_photonics.product import product_vertical
    from lab_brain.research.confirmation import confirmation_verifier as rederiving

    reading = product_vertical(outputs=None, jobs=None, broker=None, now=lambda: T0)
    return rederiving(
        db,
        trust=TRUST,
        declaration_sets=reading.declaration_sets,
        active=reading.active_declarations,
        authority_policies=reading.authority_policies,
        now=lambda: T0 + dt.timedelta(days=1),
    )


def _bypassing_triggers(db: Any, sql: str, params: Any) -> None:
    """A superuser writing past every trigger -- the root of trust, simulated."""
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(sql, params)
    finally:
        db.execute("SET session_replication_role = origin")


def test_reuse_rederives_what_the_database_triggers_could_not_stop(db):
    """A CONFIRMED row written past the triggers, citing the cause's real DOMAIN warrant and its
    real evidence, in an episode where the rule does not confirm it (two faults). The signature
    and declaration checks alone would rely on it; re-deriving the rule does not."""
    fx = copy.deepcopy(load_fixture())
    case = copy.deepcopy(case_by_id(fx, "contact-open-via"))
    case["device"] = {**case["device"], "extraction_normalization_length_um": "1000"}
    run = run_case(db, fx, case)
    assert run.result.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    forged = _supported_but_unconfirmed(db, run, "contact_discontinuity")
    _bypassing_triggers(
        db,
        "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
        " expected_behavior, observed_behavior, candidate_causes, confirmed_root_cause,"
        " root_cause_evidence_ids, failure_class, resolution_status, created_at, warrant_refs)"
        " VALUES ('fan:bypassed', %s, %s, 's', 'e', 'o', %s, %s, %s, %s, 'CONFIRMED', %s, %s)",
        (
            PROJECT,
            forged.episode_id,
            list(forged.candidate_causes),
            forged.confirmed_root_cause,
            list(forged.root_cause_evidence_ids),
            forged.failure_class,
            T0,
            list(forged.warrant_refs),
        ),
    )
    analysis = SqlFailureStore(db).analysis(PROJECT, "fan:bypassed")
    assert analysis is not None
    first_layer = confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),))
    assert first_layer(analysis) is None, "signatures and declarations alone would rely on it"
    why = _reuse_check(db)(analysis) or ""
    assert "does not confirm" in why, why
    reuse = SqlFailureStore(db, verify=_reuse_check(db))
    assert reuse.trusted_confirmations(PROJECT) == ()


def test_reuse_refuses_a_conclusion_whose_belief_history_was_edited_past_the_triggers(db):
    """No answer to check and every warrant declared, so only re-deriving the stored history can
    tell: the decision that made the cause SUPPORTED is edited past the triggers -- its evidence
    removed, its hash recomputed so the database's own CHECK still holds. The conclusion stays on
    record and nothing relies on it."""
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    assert analysis.resolution_status is ResolutionStatus.CONFIRMED
    assert _reuse_check(db)(analysis) is None
    (decision_id,) = db.execute(
        "SELECT authorization_decision_id FROM belief_revision_events"
        " WHERE project_id = %s AND target_id = %s AND to_state = 'SUPPORTED'"
        " ORDER BY occurred_at DESC LIMIT 1",
        (PROJECT, analysis.confirmed_root_cause),
    ).fetchone()
    edited = "(decision_input_snapshot::jsonb || '{\"admitted_relations\": []}')::text"
    _bypassing_triggers(
        db,
        f"UPDATE belief_transition_decisions SET decision_input_snapshot = {edited},"
        f" input_hash = 'sha256:' || encode(sha256(convert_to({edited}, 'UTF8')), 'hex')"
        " WHERE decision_id = %s",
        (decision_id,),
    )
    first_layer = confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),))
    assert first_layer(analysis) is None, "answers and declarations alone would rely on it"
    why = _reuse_check(db)(analysis) or ""
    assert "does not re-verify" in why and decision_id in why, why
    assert SqlFailureStore(db, verify=_reuse_check(db)).trusted_confirmations(PROJECT) == ()


def test_reuse_refuses_a_warrant_the_verified_record_does_not_give(db):
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    check = _reuse_check(db)
    assert check(analysis) is None, "the loop's own confirmation re-derives"
    invented = analysis.model_copy(update={"warrant_refs": (*analysis.warrant_refs, "dwg:nobody")})
    assert "which the verified record does not give" in (check(invented) or "")


def test_reuse_refuses_a_history_that_no_longer_reverifies(db):
    _queue(db)
    run = run_case(db, *_novel_case())
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    store.resolve(
        resolution_id="res:reuse-revoked",
        grant_id="dwg:reuse-revoked",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=SIGNER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=(),
        resolved_at=T0,
        identifies_class_ref=DOMAIN_REF,
    )
    assert run.loop is not None and run.request is not None
    confirmed = run.loop.run(run.request)
    assert confirmed.stop_reason is StopReason.CONFIRMED
    assert _reuse_check(db)(confirmed.failure_analysis) is None
    store.revoke(
        sign_revocation(
            AUTHORITY,
            authority_actor_id=AUTHORITY_ACTOR,
            revocation_id="rvk:reuse",
            enrolment_id=SIGNER.enrolment_id,
            project_id=PROJECT,
            effective_at=T0 - dt.timedelta(hours=1),
            reason="the key was copied",
        )
    )
    why = _reuse_check(db)(confirmed.failure_analysis) or ""
    assert "does not" in why, why


# -- hypothesis ids are unique per project, not globally (information-architecture audit F-04) ----

#: Sorts before PROJECT, so a lookup that ignores the project meets this project's rows first.
ELSEWHERE = "prj:a-elsewhere"


def _elsewhere(db: Any, hypothesis_id: str, *, mechanism: str, author: str | None) -> None:
    """A hypothesis with the same id in another project, written past every trigger."""
    _bypassing_triggers(
        db,
        "INSERT INTO hypotheses (hypothesis_id, project_id, hypothesis_set_id, statement,"
        " mechanism, assumptions, falsifier, confounders, minimal_test_ref, created_in_episode,"
        " authored_by_actor_id, created_at, falsifier_prediction_ids)"
        " VALUES (%s, %s, 'hst:elsewhere', 's', %s, ARRAY['a'], 'f', ARRAY['c'], 't',"
        " 'epi:elsewhere', %s, %s, ARRAY[%s])",
        (hypothesis_id, ELSEWHERE, mechanism, author, T0, f"prd:elsewhere:{hypothesis_id}"),
    )


def test_another_projects_hypothesis_of_the_same_id_does_not_change_its_class_in_sql(db):
    """SQL binds a hypothesis to a declared class from its own project's predictions. A row in
    another project with the same id -- the declared mechanism, and a prediction that reads the
    class's signature as a refutation -- would unbind it if the lookup ignored the project, and
    SQL would stop agreeing with the loop."""
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert run.result.stop_reason is StopReason.CONFIRMED
    cause = run.result.confirmed_root_cause
    assert cause is not None
    declared = diagnostic_declaration_set().by_class("normalization_error")
    assert declared is not None
    _elsewhere(db, cause, mechanism=declared.mechanism, author=REVIEWER)
    _bypassing_triggers(
        db,
        "INSERT INTO predictions (prediction_id, project_id, hypothesis_id, observable_ref,"
        " outcome_space_id, outcome_space_version, expected_outcome, conditions,"
        " relation_effect_if_observed, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s::jsonb, %s)",
        (
            f"prd:elsewhere:{cause}",
            ELSEWHERE,
            cause,
            declared.observable_ref,
            declared.outcome_space_id,
            declared.outcome_space_version,
            declared.supports_outcome,
            json.dumps([{"relation_type": "CONTRADICTS", "to_entity_id": cause}]),
            T0,
        ),
    )
    assert run.loop is not None and run.request is not None
    assert_rules_agree(db, run.loop, run.request)
    (breaches,) = db.execute(
        "SELECT confirmation_rule_breaches(%s, %s, %s)",
        (PROJECT, run.request.episode_id, cause),
    ).fetchone()
    assert not breaches, breaches


def test_the_author_check_reads_the_hypothesis_of_the_answers_own_project(db):
    """The person who authored a hypothesis cannot warrant it (V1). The check must read the
    hypothesis of the grant's project: here another project holds the same ids, authored by the
    reviewer, and a lookup that ignored the project would refuse an answer nobody's own claim
    is behind -- or, the other way round, admit an author's answer on their own claim."""
    _queue(db)
    fx, case = _novel_case()
    ids = sorted(run_case(db, fx, case).certificates_by_mechanism.values())
    reset_database(db)
    for hypothesis_id in ids:
        _elsewhere(db, hypothesis_id, mechanism="something else", author=REVIEWER)
    _queue(db)
    run_case(db, fx, case)
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    grant = store.resolve(
        resolution_id="res:elsewhere",
        grant_id="dwg:elsewhere",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.APPROVED,
        signer=SIGNER,
        rationale="a taper-inclusive length is exactly what makes the bases disagree",
        considered_rival_ids=(),
        resolved_at=T0,
        identifies_class_ref=DOMAIN_REF,
    )
    assert grant.granted_by_actor_id == REVIEWER
