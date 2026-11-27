"""Causal Warrant Gate V1.1: adversarial checks a database writer without keys would try.

Each test is a write a person holding only the database credential can make -- the deployment's
single superuser connection -- and the assertion is what the gate does with it. None needs a
private key; where one is used it is the attacker's own, never the PI's or an authority's. The
superuser powers that disable triggers outright (`session_replication_role`, `ALTER TABLE ...
DISABLE TRIGGER`) are the database's root of trust and out of scope here; the signature checks do
not depend on triggers at all.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.failure import ResolutionStatus
from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.repositories.evidence import SqlRelationStore
from lab_brain.core.repositories.failures import SqlFailureStore
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore
from lab_brain.domains.silicon_photonics.product import diagnostic_declaration_set
from lab_brain.research.episode_view import load_episode_view
from lab_brain.storage.postgres.warrants import confirmation_verifier
from tests.debate_fixtures import PROJECT
from tests.e2e.test_causal_warrant_counterexample_postgres import (
    CASE,
    DOMAIN_REF,
    NOVEL_MECHANISM,
    REVIEWER,
    SIGNER,
    T0,
    _promoted,
    _queue,
    _renamed,
)
from tests.reviewer_keys import AUTHORITY, AUTHORITY_ACTOR, TRUST, key_for
from tests.vertical_fixtures import case_by_id, run_case

pytestmark = pytest.mark.postgres


def _novel(db: Any) -> Any:
    """The uncatalogued account of the true cause, its warrant review outstanding."""
    _queue(db)
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    return run_case(db, fx, case_by_id(fx, CASE))


def _write_answer(db: Any, review: Any, *, grant_id: str, signature: str, **fields: Any) -> None:
    """`diagnostic_warrant_resolve`, called directly as any connection can call it."""
    db.execute(
        "SELECT diagnostic_warrant_resolve(%s, %s, %s, %s, %s, %s, %s, ARRAY[]::text[], %s,"
        " %s, %s, %s)",
        (
            f"res:{grant_id}",
            grant_id,
            review.review_id,
            PROJECT,
            fields.get("outcome", "APPROVED"),
            fields.get("actor", REVIEWER),
            fields.get("rationale", "approved"),
            fields.get("at", T0),
            fields.get("enrolment", SIGNER.enrolment_id),
            signature,
            fields.get("identifies", DOMAIN_REF),
        ),
    )


def test_a_genuine_signature_replayed_onto_another_question_is_no_answer(db):
    """The PI's real signature over one answer, copied onto the answer to another review."""
    run = _novel(db)
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    genuine = store.resolve(
        resolution_id="res:genuine",
        grant_id="dwg:genuine",
        review_id=review.review_id,
        project_id=PROJECT,
        outcome=ReviewOutcome.REJECTED,
        signer=SIGNER,
        rationale="not this link",
        considered_rival_ids=(),
        resolved_at=T0,
    )
    # Another question on another relation of the same set, answered with the copied signature.
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
    (second,) = (r for r in store.outstanding(PROJECT) if r.review_id == "rvw:other")
    _write_answer(db, second, grant_id="dwg:replayed", signature=genuine.signature, identifies=None)
    resolver_notes = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert any(
        n.startswith(f"the answer recorded on {other} counts as no answer")
        for n in resolver_notes.notes
    ), resolver_notes.notes


def test_a_non_canonical_spelling_of_a_real_signature_is_refused_by_the_database(db):
    _novel(db)
    (review,) = SqlDiagnosticWarrantStore(db).outstanding(PROJECT)
    real = SIGNER.key.sign(b"anything")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    twin = real[:-3] + alphabet[alphabet.index(real[-3]) + 1] + real[-2:]
    with pytest.raises(psycopg.Error, match="signature_is_ed25519"):
        _write_answer(db, review, grant_id="dwg:twin", signature=twin)


def test_an_impostor_with_their_own_key_and_a_forged_enrolment_confirms_nothing_and_is_relied_on_nowhere(
    db,
):
    """Everything a keyless writer can put in the database at once: an enrolment row for the PI
    naming the pinned authority, signed by the impostor; an answer by "the PI" under it with an
    identity statement; then a direct CONFIRMED row. The loop confirms nothing; the database
    refuses the row; nothing relies on anything; the page shows nothing as relied on."""
    run = _novel(db)
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    impostor = key_for("act:impostor")
    db.execute(
        "INSERT INTO warrant_reviewer_enrolments (enrolment_id, project_id, actor_id, public_key,"
        " key_id, scope, enrolled_at, authority_actor_id, authority_key_id, authority_signature)"
        " VALUES ('enr:impostor', %s, %s, %s, %s, 'DIAGNOSTIC_WARRANT', %s, %s, %s, %s)",
        (
            PROJECT,
            REVIEWER,
            impostor.public_key,
            impostor.key_id,
            T0 - dt.timedelta(days=1),
            AUTHORITY_ACTOR,
            AUTHORITY.key_id,
            impostor.sign(b"an enrolment nobody authorised"),
        ),
    )
    _write_answer(
        db, review, grant_id="dwg:impostor", signature=impostor.sign(b"x"), enrolment="enr:impostor"
    )
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert "normalization_error" not in _promoted(run)
    novel = run.certificates_by_mechanism["normalization_error"]
    with pytest.raises(psycopg.Error, match="SUPPORTED"):
        db.execute(
            "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id, symptom,"
            " expected_behavior, observed_behavior, candidate_causes, confirmed_root_cause,"
            " root_cause_evidence_ids, failure_class, resolution_status, created_at, warrant_refs)"
            " VALUES ('fan:impostor', %s, %s, 's', 'e', 'o', %s, %s, ARRAY['att:x'],"
            " 'length normalization error', 'CONFIRMED', %s, ARRAY['dwg:impostor'])",
            (
                PROJECT,
                run.request.episode_id,
                sorted(run.certificates_by_mechanism.values()),
                novel,
                T0,
            ),
        )
    trusted = SqlFailureStore(
        db,
        verify=confirmation_verifier(db, TRUST, declaration_sets=(diagnostic_declaration_set(),)),
    )
    assert trusted.trusted_confirmations(PROJECT) == ()
    view = load_episode_view(db, project_id=PROJECT, episode_id=run.request.episode_id)
    assert all(c.status != "CONFIRMED" for c in view.conclusions)


def test_a_keyless_writer_can_withhold_a_genuine_answer_but_never_counterfeit_one(db):
    """Denial of service, recorded as such: a junk answer written first closes the question, so
    the PI's genuine answer is refused -- and the junk one counts for nothing. The episode waits;
    it is not confirmed and not refuted. (`012p` cannot tell a junk signature from a real one.)"""
    run = _novel(db)
    store = SqlDiagnosticWarrantStore(db)
    (review,) = store.outstanding(PROJECT)
    _write_answer(db, review, grant_id="dwg:junk", signature=key_for("act:junk").sign(b"x"))
    with pytest.raises(Exception, match="already"):
        store.resolve(
            resolution_id="res:late-genuine",
            grant_id="dwg:late-genuine",
            review_id=review.review_id,
            project_id=PROJECT,
            outcome=ReviewOutcome.APPROVED,
            signer=SIGNER,
            rationale="the genuine answer",
            considered_rival_ids=(),
            resolved_at=T0,
            identifies_class_ref=DOMAIN_REF,
        )
    resumed = run.loop.run(dataclasses.replace(run.request, available_inputs=frozenset()))
    assert resumed.failure_analysis.resolution_status is not ResolutionStatus.CONFIRMED
    assert resumed.stop_reason.value in ("AWAITING_REVIEW", "HUMAN_ACTION_REQUIRED")
