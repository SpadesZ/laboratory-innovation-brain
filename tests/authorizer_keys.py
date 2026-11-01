"""Signed verification authorizations for the database tests (011w).

Since 011w a verification authorization is signed by its person, under an authorizer key a review
AUTHORITY enrolled for them in the project. The tests that need an authorization -- most of the
011s suite -- get one from here: a throwaway authority (pinned in a `ReviewerTrust`, never in the
database), an enrolment per person, and a signature over exactly the row the test inserts.

    keys = AuthorizerKeys(db)                      # one authority for this test
    signer = keys.signer(project, actor)           # enrols `actor`'s key in `project` once
    keys.signed_columns(signer, authorization_id=..., ...)  -> enrolment_id, signature, signed_at

`trust` is what the code under test must be given (or `LAB_BRAIN_REVIEW_AUTHORITIES` set to
`keys.authorities_file(tmp_path)`); without it no authorization verifies.
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lab_brain.core.models.reviewer import VERIFICATION_AUTHORIZATION_SCOPE, authorization_statement
from lab_brain.security.reviewer_identity import (
    ReviewAuthority,
    ReviewerTrust,
    SigningKey,
    sign_enrolment,
    sign_revocation,
)
from lab_brain.verification.prospective import (
    AuthorizationSigner,
    enrol_authorizer,
    revoke_authorizer,
)

AUTHORITY_ACTOR = "act:review-authority"


class AuthorizerKeys:
    def __init__(self, db: Any, authority_actor: str = AUTHORITY_ACTOR) -> None:
        self.db = db
        self.authority = SigningKey.generate()
        self.authority_actor = authority_actor
        self.trust = ReviewerTrust(
            [ReviewAuthority(actor_id=authority_actor, public_key=self.authority.public_key)]
        )
        self._signers: dict[tuple[str, str], AuthorizationSigner] = {}
        db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
            " ON CONFLICT (actor_id) DO NOTHING",
            (authority_actor, "review authority (test)"),
        )

    def authorities_file(self, directory: Path) -> Path:
        path = directory / f"review-authorities-{secrets.token_hex(4)}"
        path.write_text(
            f"{self.authority_actor} ed25519:{self.authority.public_key}\n", encoding="utf-8"
        )
        return path

    def signer(
        self, project_id: str, actor_id: str, *, enrolled_at: dt.datetime | None = None
    ) -> AuthorizationSigner:
        """`actor_id`'s authorizer key in `project_id`, enrolled by this authority (once)."""
        found = self._signers.get((project_id, actor_id))
        if found is not None:
            return found
        key = SigningKey.generate()
        enrolment = sign_enrolment(
            self.authority,
            authority_actor_id=self.authority_actor,
            enrolment_id=f"enr:vauth:{secrets.token_hex(6)}",
            project_id=project_id,
            actor_id=actor_id,
            public_key=key.public_key,
            enrolled_at=enrolled_at or dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
            scope=VERIFICATION_AUTHORIZATION_SCOPE,
        )
        enrol_authorizer(self.db, enrolment)
        signer = AuthorizationSigner(actor_id, enrolment.enrolment_id, key)
        self._signers[(project_id, actor_id)] = signer
        return signer

    def revoke(
        self, project_id: str, signer: AuthorizationSigner, *, effective_at: dt.datetime
    ) -> None:
        revoke_authorizer(
            self.db,
            sign_revocation(
                self.authority,
                authority_actor_id=self.authority_actor,
                revocation_id=f"rev:vauth:{secrets.token_hex(6)}",
                enrolment_id=signer.enrolment_id,
                project_id=project_id,
                effective_at=effective_at,
                reason="test revocation",
            ),
        )

    @staticmethod
    def signed_columns(
        signer: AuthorizationSigner,
        *,
        authorization_id: str,
        project_id: str,
        episode_id: str,
        hypothesis_id: str,
        prediction_ids: Sequence[str],
        capability_id: str,
        declaration_hash: str,
        rationale: str,
        signed_at: dt.datetime | None = None,
    ) -> tuple[str, str, dt.datetime]:
        """(enrolment_id, signature, signed_at) for exactly this authorization row."""
        at = signed_at or dt.datetime.now(dt.UTC)
        statement = authorization_statement(
            authorization_id=authorization_id,
            project_id=project_id,
            episode_id=episode_id,
            hypothesis_id=hypothesis_id,
            prediction_ids=tuple(prediction_ids),
            capability_id=capability_id,
            declaration_hash=declaration_hash,
            actor_id=signer.actor_id,
            rationale=rationale,
            signed_at=at,
            enrolment_id=signer.enrolment_id,
        )
        return signer.enrolment_id, signer.key.sign(statement), at


__all__ = ["AUTHORITY_ACTOR", "AuthorizerKeys"]
