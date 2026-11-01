"""A verification authorization is a statement its person signed (011w).

On 58c68be an authorization was a row: anyone holding the services' database role could pre-register
a test in a real member's name, and a post-screening hypothesis could then be supported by a check
"authorized" by nobody. The first test below was written first and failed there (the unsigned row
was accepted). The rest are the attacks the signature has to survive -- each at the layer that can
see it:

    SQL (011w trigger and rule (l)) -- the frame
        unsigned                       refused at write; a pre-011w unsigned row licenses nothing
        another person's enrolment     refused at write
        a warrant enrolment            not an authorizer enrolment (its scope is signed)
        revoked key                    refused at write once recorded; and at admission when the
                                       revocation took effect before the signature
        future / before the hypothesis refused at write
    Python (every read that counts it: evidence sink, collector `unverified_authorization`)
        a forged signature, an enrolment row a database writer forged, a row edited after it was
        signed, a signature replayed onto another authorization, no authority pinned

The legitimate path -- signed by an enrolled person, verified under the pinned authority -- still
supports (`test_g0_prospective_verification_postgres.py`), so evidence admission is not weakened:
every rule of 011s still applies, the signature is one more.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.reviewer import (
    VERIFICATION_AUTHORIZATION_SCOPE,
    WARRANT_REVIEW_SCOPE,
)
from lab_brain.evaluation import scoring
from lab_brain.evaluation.collect import support_provenance
from lab_brain.security.reviewer_identity import ReviewerTrust, SigningKey, sign_enrolment
from lab_brain.verification.prospective import (
    AuthorizationSigner,
    ProspectiveRefused,
    SqlVerificationAuthorizations,
    support_problem,
)
from tests.e2e.test_g0_exploratory_screening_postgres import rows
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT

pytestmark = pytest.mark.postgres

_INSERT = (
    "INSERT INTO verification_authorizations (authorization_id, project_id, episode_id,"
    " hypothesis_id, prediction_ids, capability_id, declaration_hash, actor_id, rationale,"
    " created_at, enrolment_id, signature, signed_at)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s)"
)


def _digest(g: Guarded, capability: str) -> str:
    ((digest,),) = rows(
        g.db,
        "SELECT declaration_hash FROM capability_declarations WHERE capability_id = %s",
        capability,
    )
    return str(digest)


def _row(
    g: Guarded,
    name: str,
    *,
    signer: AuthorizationSigner | None,
    actor: str | None = None,
    signed_at: dt.datetime | None = None,
    signature: str | None = None,
) -> tuple[Any, ...]:
    """The values of an authorization of the rival by `actor`, signed by `signer` (or not), in
    the column order of `_INSERT`."""
    person = actor or g.actor
    fields = {
        "authorization_id": f"vauth:{name}",
        "project_id": PROJECT,
        "episode_id": g.episode,
        "hypothesis_id": g.hypothesis,
        "prediction_ids": [g.prediction()],
        "capability_id": "cap:sp.fourpoint_probe",
        "declaration_hash": _digest(g, "cap:sp.fourpoint_probe"),
        "rationale": f"test {name}",
    }
    values = list(fields.values())
    values.insert(7, person)  # actor_id comes before rationale
    if signer is None:
        return (*values, None, None, None)
    enrolment, signed, at = g.keys.signed_columns(signer, signed_at=signed_at, **fields)
    return (*values, enrolment, signature or signed, at)


def _insert(g: Guarded, values: tuple[Any, ...]) -> None:
    g.db.execute(_INSERT, values)


def _supported_by(g: Guarded, authorization: str, name: str) -> RelationJudgment:
    """A measurement bound to `authorization`, offered as SUPPORTS through SQL (the frame)."""
    observation, evidence = g.measured(name, authorization=authorization)
    g.support(observation, [evidence], prediction=g.prediction())
    return RelationJudgment.model_validate(
        {
            "relation_id": f"rel:{observation}",
            "from_entity_id": observation,
            "to_entity_id": g.hypothesis,
            "relation_type": RelationType.SUPPORTS,
            "attributes": {"prediction_id": g.prediction(), "outcome": "ELEVATED"},
            "supporting_attestation_ids": (evidence,),
            "project_id": PROJECT,
        }
    )


def _python_refuses(g: Guarded, relation: RelationJudgment, why: str) -> None:
    problem = support_problem(g.db, relation)
    assert problem is not None and why in problem, problem
    (facts,) = support_provenance(g.db, g.hypothesis)
    assert facts["unverified_authorization"] is True
    assert not scoring.admissible(facts)


# -- the defect ---------------------------------------------------------------------------------


def test_an_unsigned_authorization_in_a_members_name_is_refused(guarded):
    g = guarded
    with (
        pytest.raises(psycopg.errors.RaiseException, match="unsigned"),
        g.db.transaction(force_rollback=True),
    ):
        g.db.execute(
            "INSERT INTO verification_authorizations (authorization_id, project_id, episode_id,"
            " hypothesis_id, prediction_ids, capability_id, declaration_hash, actor_id,"
            " rationale, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
            (
                "vauth:forged-by-the-services",
                PROJECT,
                g.episode,
                g.hypothesis,
                [g.prediction()],
                "cap:sp.fourpoint_probe",
                _digest(g, "cap:sp.fourpoint_probe"),
                g.actor,
                "nobody signed this",
            ),
        )


def test_the_signed_path_still_supports(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        relation = _supported_by(g, g.authorize("signed"), "signed")
        assert support_problem(g.db, relation) is None
        (facts,) = support_provenance(g.db, g.hypothesis)
        assert all(facts[f] is False for f in scoring.SUPPORT_FACTS), facts


# -- the frame, in SQL --------------------------------------------------------------------------


def test_a_signature_under_another_persons_enrolment_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name) VALUES"
            " ('act:colleague', 'HUMAN', 'a colleague')"
        )
        g.db.execute(
            "INSERT INTO project_memberships (project_id, actor_id, role) VALUES"
            " (%s, 'act:colleague', 'RESEARCHER')",
            (PROJECT,),
        )
        colleague = g.keys.signer(PROJECT, "act:colleague")
        values = list(_row(g, "borrowed", signer=colleague))
        values[7] = g.actor  # the row claims the episode's person; the key is the colleague's
        with (
            pytest.raises(psycopg.errors.RaiseException, match=r"not .*authorizer key"),
            g.db.transaction(force_rollback=True),
        ):
            _insert(g, tuple(values))


def test_a_warrant_enrolment_is_not_an_authorizer_enrolment(guarded):
    g = guarded
    key = SigningKey.generate()
    warrant = sign_enrolment(
        g.keys.authority,
        authority_actor_id=g.keys.authority_actor,
        enrolment_id=f"enr:warrant:{secrets.token_hex(4)}",
        project_id=PROJECT,
        actor_id=g.actor,
        public_key=key.public_key,
        enrolled_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
        scope=WARRANT_REVIEW_SCOPE,
    )
    with g.db.transaction(force_rollback=True):
        with pytest.raises(ProspectiveRefused, match="VERIFICATION_AUTHORIZATION"):
            from lab_brain.verification.prospective import enrol_authorizer

            enrol_authorizer(g.db, warrant)
        # Stored in the warrant table, it cannot sign an authorization: the enrolment must be an
        # authorizer enrolment of that person (the foreign key and the trigger).
        from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore

        SqlDiagnosticWarrantStore(g.db).enrol(warrant)
        signer = AuthorizationSigner(g.actor, warrant.enrolment_id, key)
        with (
            pytest.raises(psycopg.errors.Error),
            g.db.transaction(force_rollback=True),
        ):
            _insert(g, _row(g, "warrant-key", signer=signer))
    # And the warrant table never takes an authorizer enrolment.
    authorizer = warrant.model_copy(update={"scope": VERIFICATION_AUTHORIZATION_SCOPE})
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        g.db.transaction(force_rollback=True),
    ):
        from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore

        try:
            SqlDiagnosticWarrantStore(g.db).enrol(authorizer)
        except Exception as wrapped:
            raise wrapped.__cause__ or wrapped from None


def test_a_revoked_key_signs_nothing_more(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        signer = g.keys.signer(PROJECT, g.actor)
        g.keys.revoke(PROJECT, signer, effective_at=dt.datetime.now(dt.UTC))
        with (
            pytest.raises(psycopg.errors.RaiseException, match="revoked"),
            g.db.transaction(force_rollback=True),
        ):
            _insert(g, _row(g, "after-revocation", signer=signer))


def test_a_revocation_effective_before_the_signature_withdraws_the_authorization(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("compromised")
        relation = _supported_by(g, authorization, "compromised")
        # The key is found compromised; the authority dates the revocation before the signature.
        signer = g.keys.signer(PROJECT, g.actor)
        g.keys.revoke(
            PROJECT, signer, effective_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=30)
        )
        (problem,) = rows(
            g.db,
            "SELECT prospective_authorization_problem(c, u, %s) FROM"
            " screening_conditioned_hypotheses c, runs u, observations o"
            " WHERE c.hypothesis_id = %s AND o.observation_id = %s AND u.run_id = o.run_id",
            g.prediction(),
            g.hypothesis,
            relation.from_entity_id,
        )
        assert problem[0] is not None and "revoked before it signed" in problem[0]
        assert support_problem(g.db, relation) is not None


@pytest.mark.parametrize(
    ("offset", "why"),
    [(dt.timedelta(hours=1), "in the future"), (-dt.timedelta(days=3650), "before")],
)
def test_a_signature_dated_in_the_future_or_before_the_hypothesis_is_refused(guarded, offset, why):
    g = guarded
    with g.db.transaction(force_rollback=True):
        signer = g.keys.signer(
            PROJECT, g.actor, enrolled_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=3651)
        )
        with (
            pytest.raises(psycopg.errors.RaiseException, match=why),
            g.db.transaction(force_rollback=True),
        ):
            _insert(g, _row(g, "dated", signer=signer, signed_at=dt.datetime.now(dt.UTC) + offset))


def test_an_unsigned_row_from_before_011w_licenses_nothing(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.db.execute(
            "ALTER TABLE verification_authorizations"
            " DISABLE TRIGGER verification_authorization_is_signed_trg"
        )
        try:
            _insert(g, _row(g, "legacy", signer=None))
        finally:
            g.db.execute(
                "ALTER TABLE verification_authorizations"
                " ENABLE TRIGGER verification_authorization_is_signed_trg"
            )
        with (
            pytest.raises(psycopg.errors.RaiseException, match="unsigned"),
            g.db.transaction(force_rollback=True),
        ):
            _supported_by(g, "vauth:legacy", "legacy")


# -- the signature, in Python -------------------------------------------------------------------


def test_a_forged_signature_passes_the_frame_and_supports_nothing(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        signer = g.keys.signer(PROJECT, g.actor)
        forged = SigningKey.generate().sign(b"anything")  # right shape, wrong key
        _insert(g, _row(g, "forged", signer=signer, signature=forged))
        relation = _supported_by(g, "vauth:forged", "forged")  # SQL cannot tell
        _python_refuses(g, relation, "signature does not verify")


def test_an_enrolment_a_database_writer_forged_supports_nothing(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        impostor = SigningKey.generate()  # the writer's own "authority"
        key = SigningKey.generate()
        from lab_brain.verification.prospective import enrol_authorizer

        enrolment = sign_enrolment(
            impostor,
            authority_actor_id=g.keys.authority_actor,  # claims the real authority's name
            enrolment_id="enr:vauth:forged",
            project_id=PROJECT,
            actor_id=g.actor,
            public_key=key.public_key,
            enrolled_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
            scope=VERIFICATION_AUTHORIZATION_SCOPE,
        )
        enrol_authorizer(g.db, enrolment)
        signer = AuthorizationSigner(g.actor, enrolment.enrolment_id, key)
        _insert(g, _row(g, "forged-enrolment", signer=signer))
        relation = _supported_by(g, "vauth:forged-enrolment", "forged-enrolment")
        _python_refuses(g, relation, "not a pinned review authority")


def test_a_row_edited_after_it_was_signed_supports_nothing(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("edited")
        g.db.execute(
            "ALTER TABLE verification_authorizations"
            " DISABLE TRIGGER verification_authorizations_are_append_only_trg"
        )
        try:
            g.db.execute(
                "UPDATE verification_authorizations SET rationale = 'a different reason'"
                " WHERE authorization_id = %s",
                (authorization,),
            )
        finally:
            g.db.execute(
                "ALTER TABLE verification_authorizations"
                " ENABLE TRIGGER verification_authorizations_are_append_only_trg"
            )
        relation = _supported_by(g, authorization, "edited")
        _python_refuses(g, relation, "signature does not verify")


def test_a_signature_replayed_onto_another_authorization_supports_nothing(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        original = g.authorize("original")
        ((signature,),) = rows(
            g.db,
            "SELECT signature FROM verification_authorizations WHERE authorization_id = %s",
            original,
        )
        signer = g.keys.signer(PROJECT, g.actor)
        _insert(g, _row(g, "replayed", signer=signer, signature=str(signature)))
        relation = _supported_by(g, "vauth:replayed", "replayed")
        _python_refuses(g, relation, "signature does not verify")


def test_with_no_authority_pinned_nothing_verifies(guarded, monkeypatch):
    g = guarded
    monkeypatch.delenv("LAB_BRAIN_REVIEW_AUTHORITIES", raising=False)
    with g.db.transaction(force_rollback=True):
        relation = _supported_by(g, g.authorize("unpinned"), "unpinned")
        _python_refuses(g, relation, "pins no review authority")
        # Given the pinned authority explicitly, the same row verifies.
        assert support_problem(g.db, relation, g.keys.trust) is None
        assert support_problem(g.db, relation, ReviewerTrust()) is not None


def test_the_store_signs_with_the_persons_key_only(guarded):
    g = guarded
    other = AuthorizationSigner("act:someone-else", "enr:x", SigningKey.generate())
    with pytest.raises(ProspectiveRefused, match="cannot sign an authorization by"):
        SqlVerificationAuthorizations(g.db).authorize(
            authorization_id="vauth:wrong-signer",
            project_id=PROJECT,
            hypothesis_id=g.hypothesis,
            prediction_ids=[g.prediction()],
            capability_id="cap:sp.fourpoint_probe",
            actor_id=g.actor,
            rationale="x",
            signer=other,
        )
