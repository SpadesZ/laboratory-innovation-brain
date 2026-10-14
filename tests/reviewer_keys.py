"""Test reviewer identities for the Causal Warrant Gate V1.1: one authority, deterministic keys.

TEST CREDENTIALS ONLY. Every key here is derived from a fixed, public seed so a test run is
reproducible; none is a secret and none may be pinned by a deployment. `TRUST` pins the test
authority and nothing else, so a test that answers a review proves the full path: an authority
enrolled the reviewer's key, the reviewer signed the answer, and the read path verified both.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lab_brain.security.reviewer_identity import (
    ReviewAuthority,
    ReviewerSigner,
    ReviewerTrust,
    SigningKey,
    grant_authenticator,
    sign_enrolment,
)

#: The person the test authority acts as. Never a reviewer: an authority does not enrol itself.
AUTHORITY_ACTOR = "act:review-authority"
#: Before every test clock, so an enrolment always predates the reviews it answers.
ENROLLED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def key_for(name: str) -> SigningKey:
    """A deterministic Ed25519 key for `name` (test seed: SHA-256 of a public label)."""
    seed = hashlib.sha256(f"lab-brain test key: {name}".encode()).digest()
    return SigningKey(Ed25519PrivateKey.from_private_bytes(seed))


AUTHORITY = key_for(AUTHORITY_ACTOR)
TRUST = ReviewerTrust((ReviewAuthority(actor_id=AUTHORITY_ACTOR, public_key=AUTHORITY.public_key),))


def ensure_authority_actor(connection: Any) -> None:
    connection.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name, active)"
        " VALUES (%s, 'HUMAN', 'Review authority (test)', TRUE) ON CONFLICT DO NOTHING",
        (AUTHORITY_ACTOR,),
    )


def enrol(
    store: Any,
    *,
    project_id: str,
    actor_id: str,
    enrolment_id: str | None = None,
    at: dt.datetime = ENROLLED_AT,
    key: SigningKey | None = None,
) -> ReviewerSigner:
    """Enrol `actor_id`'s test key in `project_id` through `store`, and return its signer."""
    key = key or key_for(actor_id)
    enrolment = sign_enrolment(
        AUTHORITY,
        authority_actor_id=AUTHORITY_ACTOR,
        enrolment_id=enrolment_id or f"enr:{project_id}:{actor_id}",
        project_id=project_id,
        actor_id=actor_id,
        public_key=key.public_key,
        enrolled_at=at,
    )
    store.enrol(enrolment)
    return ReviewerSigner(actor_id=actor_id, enrolment_id=enrolment.enrolment_id, key=key)


def authenticator(store: Any) -> Any:
    return grant_authenticator(store, TRUST)


__all__ = [
    "AUTHORITY",
    "AUTHORITY_ACTOR",
    "ENROLLED_AT",
    "TRUST",
    "authenticator",
    "enrol",
    "ensure_authority_actor",
    "key_for",
]
