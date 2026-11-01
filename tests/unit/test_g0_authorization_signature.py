"""The signature on a verification authorization (011w), without a database.

`ReviewerTrust.verify_authorization` is the one check that proves a person authorized a test. Each
field of the authorization is inside what the person signed; the enrolment must be an authorizer
enrolment (its scope is inside the authority's signature), made by a pinned authority, before the
signature, and not revoked at the signature's time.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lab_brain.core.models.reviewer import (
    VERIFICATION_AUTHORIZATION_SCOPE,
    WARRANT_REVIEW_SCOPE,
    authorization_statement,
    grant_statement,
)
from lab_brain.security.reviewer_identity import (
    IdentityUnverified,
    ReviewAuthority,
    ReviewerTrust,
    SigningKey,
    sign_enrolment,
    sign_revocation,
)

NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
AUTHORITY = SigningKey.generate()
PERSON = SigningKey.generate()
TRUST = ReviewerTrust([ReviewAuthority(actor_id="act:authority", public_key=AUTHORITY.public_key)])

FIELDS: dict[str, Any] = {
    "authorization_id": "vauth:a",
    "project_id": "proj:p",
    "episode_id": "ep:1",
    "hypothesis_id": "hyp:h",
    "prediction_ids": ("pred:1",),
    "capability_id": "cap:sp.fourpoint_probe",
    "declaration_hash": "sha256:" + "d" * 64,
    "actor_id": "act:pi",
    "rationale": "an open via raises the probed resistance",
    "signed_at": NOW,
    "enrolment_id": "enr:1",
}


def _enrolment(scope: str = VERIFICATION_AUTHORIZATION_SCOPE, **changes: Any) -> Any:
    fields: dict[str, Any] = {
        "authority_actor_id": "act:authority",
        "enrolment_id": "enr:1",
        "project_id": "proj:p",
        "actor_id": "act:pi",
        "public_key": PERSON.public_key,
        "enrolled_at": NOW - dt.timedelta(days=1),
        "scope": scope,
    }
    fields.update(changes)
    return sign_enrolment(changes.pop("authority", AUTHORITY), **fields)


def _verify(*, enrolment: Any = None, signature: str | None = None, revocations=(), **changes):
    fields = {**FIELDS, **changes}
    statement = authorization_statement(**fields)
    TRUST.verify_authorization(
        what="authorization vauth:a",
        actor_id=fields["actor_id"],
        project_id=fields["project_id"],
        enrolment_id=fields["enrolment_id"],
        signature=signature if signature is not None else PERSON.sign(statement),
        signed_at=fields["signed_at"],
        statement=statement,
        enrolment=enrolment if enrolment is not None else _enrolment(),
        revocations=revocations,
    )


def test_a_signed_authorization_verifies():
    _verify()


@pytest.mark.parametrize(
    "field",
    [k for k in FIELDS if k not in ("signed_at", "enrolment_id", "actor_id", "project_id")],
)
def test_every_field_is_inside_the_signature(field):
    signature = PERSON.sign(authorization_statement(**FIELDS))
    changed = {
        "prediction_ids": ("pred:2",),
    }.get(field, str(FIELDS[field]) + "-changed")
    with pytest.raises(IdentityUnverified, match="does not verify"):
        _verify(signature=signature, **{field: changed})


def test_the_time_is_inside_the_signature():
    signature = PERSON.sign(authorization_statement(**FIELDS))
    with pytest.raises(IdentityUnverified, match="does not verify"):
        _verify(signature=signature, signed_at=NOW + dt.timedelta(seconds=1))


def test_a_warrant_enrolment_does_not_sign_an_authorization():
    with pytest.raises(IdentityUnverified, match="authorizes DIAGNOSTIC_WARRANT"):
        _verify(enrolment=_enrolment(scope=WARRANT_REVIEW_SCOPE))


def test_an_enrolment_by_an_unpinned_authority_does_not_count():
    impostor = sign_enrolment(
        SigningKey.generate(),
        authority_actor_id="act:authority",
        enrolment_id="enr:1",
        project_id="proj:p",
        actor_id="act:pi",
        public_key=PERSON.public_key,
        enrolled_at=NOW - dt.timedelta(days=1),
        scope=VERIFICATION_AUTHORIZATION_SCOPE,
    )
    with pytest.raises(IdentityUnverified, match="not a pinned review authority"):
        _verify(enrolment=impostor)


def test_a_signature_before_the_enrolment_does_not_count():
    with pytest.raises(IdentityUnverified, match="predates the enrolment"):
        _verify(enrolment=_enrolment(enrolled_at=NOW + dt.timedelta(seconds=1)))


def test_another_persons_enrolment_does_not_count():
    with pytest.raises(IdentityUnverified, match="is by act:pi"):
        _verify(enrolment=_enrolment(actor_id="act:colleague"))


def test_a_revocation_at_or_before_the_signature_withdraws_it_and_a_later_one_does_not():
    def revoked(at: dt.datetime) -> Any:
        return sign_revocation(
            AUTHORITY,
            authority_actor_id="act:authority",
            revocation_id="rev:1",
            enrolment_id="enr:1",
            project_id="proj:p",
            effective_at=at,
            reason="lost laptop",
        )

    with pytest.raises(IdentityUnverified, match="revoked"):
        _verify(revocations=(revoked(NOW),))
    _verify(revocations=(revoked(NOW + dt.timedelta(seconds=1)),))


def test_an_unsigned_authorization_does_not_verify():
    with pytest.raises(IdentityUnverified, match="unsigned"):
        TRUST.verify_authorization(
            what="authorization vauth:a",
            actor_id="act:pi",
            project_id="proj:p",
            enrolment_id=None,
            signature=None,
            signed_at=None,
            statement=b"",
            enrolment=None,
        )


def test_a_warrant_answer_signature_is_never_an_authorization_signature():
    """Domain separation: the same key's signature over a warrant answer does not verify here."""
    answer = grant_statement(
        grant_id="g",
        project_id="proj:p",
        review_id="r",
        relation_id="rel",
        relation_type="SUPPORTS",
        hypothesis_id="hyp:h",
        prediction_id="pred:1",
        verdict="WARRANTED",
        granted_by_actor_id="act:pi",
        granted_at=NOW,
        rationale="x",
        considered_rival_ids=(),
        identifies_class_ref=None,
        enrolment_id="enr:1",
    )
    with pytest.raises(IdentityUnverified, match="does not verify"):
        _verify(signature=PERSON.sign(answer))


def test_nothing_verifies_with_no_authority_pinned():
    statement = authorization_statement(**FIELDS)
    with pytest.raises(IdentityUnverified, match="pins no review authority"):
        ReviewerTrust().verify_authorization(
            what="authorization vauth:a",
            actor_id="act:pi",
            project_id="proj:p",
            enrolment_id="enr:1",
            signature=PERSON.sign(statement),
            signed_at=NOW,
            statement=statement,
            enrolment=_enrolment(),
        )
