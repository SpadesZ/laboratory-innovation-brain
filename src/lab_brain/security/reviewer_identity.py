"""Reviewer identity: Ed25519 keys, authority-signed enrolments, and the checks that use them.

THE TRUST ANCHOR IS OUTSIDE THE DATABASE. `ReviewerTrust` is built from the deployment's review
authorities -- one line per authority, `<actor id> ed25519:<base64 public key>`, in the file
`LAB_BRAIN_REVIEW_AUTHORITIES` names -- never from a table. Whoever can write the database can
write an enrolment row; only an authority's private key makes one verify. With no authority
configured, no answer verifies: warrant reviews can be asked but not answered, and the gate stays
closed.

WHAT A VERIFIED ANSWER MEANS. Its signature verifies under the key of an enrolment that:
    - an authority pinned here signed, for the same project and person;
    - was made before the answer, by an authority who is not the reviewer;
    - was not revoked with effect at or before the answer's time.
It does not mean the reviewer was right. It means the named person gave this exact answer.

WHAT IT DOES NOT COVER. The holder of an authority key can enrol anyone, and whoever controls the
deployment's configuration chooses the authorities. Both are the deployment's root of trust,
outside the reach of a database writer, and named as such in the V1.1 design record.
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from lab_brain.core.models.reviewer import (
    ReviewerEnrolment,
    ReviewerKeyRevocation,
    enrolment_statement,
    is_public_key,
    key_id,
    revocation_statement,
)
from lab_brain.core.models.warrant import DiagnosticWarrantGrant

#: The deployment setting naming the review authorities file.
AUTHORITIES_ENV = "LAB_BRAIN_REVIEW_AUTHORITIES"
#: The passphrase of an encrypted reviewer or authority key, when one is used.
PASSPHRASE_ENV = "LAB_BRAIN_REVIEW_KEY_PASSPHRASE"


class IdentityUnverified(ValueError):
    """A signed reviewer record does not verify, or nothing it needs is configured."""


@dataclass(frozen=True)
class ReviewAuthority:
    """One pinned authority: the person it acts as, and its public key."""

    actor_id: str
    public_key: str

    @property
    def key_id(self) -> str:
        return key_id(self.public_key)


def _public(public_key: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))


def _verify(public_key: str, signature: str, message: bytes) -> bool:
    try:
        _public(public_key).verify(base64.b64decode(signature, validate=True), message)
    except (InvalidSignature, ValueError):
        return False
    return True


def parse_authorities(text: str) -> tuple[ReviewAuthority, ...]:
    """Authorities from the file format: `<actor id> ed25519:<base64>` per line, `#` comments.

    Malformed lines are refused rather than skipped: a trust anchor that silently dropped a line
    would be a different trust anchor from the one its operator wrote.
    """
    found: list[ReviewAuthority] = []
    for number, line in enumerate(text.splitlines(), start=1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        parts = body.split()
        if (
            len(parts) != 2
            or not parts[0].startswith("act:")
            or not parts[1].startswith("ed25519:")
        ):
            raise IdentityUnverified(
                f"review authorities line {number} is not `<act:id> ed25519:<base64 key>`"
            )
        public_key = parts[1].removeprefix("ed25519:")
        if not is_public_key(public_key):
            raise IdentityUnverified(f"review authorities line {number} has no Ed25519 key")
        found.append(ReviewAuthority(actor_id=parts[0], public_key=public_key))
    ids = [a.key_id for a in found]
    if len(set(ids)) != len(ids):
        raise IdentityUnverified("a review authority key is listed twice")
    return tuple(found)


class ReviewerTrust:
    """The deployment's pinned review authorities and every check that rests on them."""

    def __init__(self, authorities: Sequence[ReviewAuthority] = ()) -> None:
        self._by_key: Mapping[str, ReviewAuthority] = {a.key_id: a for a in authorities}

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> ReviewerTrust:
        return cls(parse_authorities(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> ReviewerTrust:
        """The configured authorities, or none -- in which case no answer will verify."""
        return cls.configured_at(env.get(AUTHORITIES_ENV, ""))

    @classmethod
    def configured_at(cls, path: str) -> ReviewerTrust:
        """The authorities in the file at `path`, or none for an empty path.

        A path that is named but unreadable or malformed raises: a deployment that meant to pin
        an authority and silently pinned none would fail closed without saying why.
        """
        return cls() if not path.strip() else cls.from_file(path.strip())

    @property
    def authorities(self) -> tuple[ReviewAuthority, ...]:
        return tuple(sorted(self._by_key.values(), key=lambda a: a.key_id))

    @property
    def configured(self) -> bool:
        return bool(self._by_key)

    def authority(self, authority_key_id: str) -> ReviewAuthority | None:
        return self._by_key.get(authority_key_id)

    def _authority_for(self, actor_id: str, authority_key_id: str, what: str) -> ReviewAuthority:
        if not self._by_key:
            raise IdentityUnverified(
                f"{what} cannot be verified: this deployment pins no review authority "
                f"({AUTHORITIES_ENV})"
            )
        authority = self._by_key.get(authority_key_id)
        if authority is None:
            raise IdentityUnverified(
                f"{what} is signed by {authority_key_id}, which is not a pinned review authority"
            )
        if authority.actor_id != actor_id:
            raise IdentityUnverified(
                f"{what} names {actor_id} as its authority, but {authority_key_id} is "
                f"{authority.actor_id}'s key"
            )
        return authority

    def verify_enrolment(self, enrolment: ReviewerEnrolment) -> None:
        what = f"enrolment {enrolment.enrolment_id}"
        authority = self._authority_for(
            enrolment.authority_actor_id, enrolment.authority_key_id, what
        )
        if authority.actor_id == enrolment.actor_id:
            raise IdentityUnverified(f"{what}: an authority does not enrol itself")
        if authority.key_id == enrolment.key_id:
            raise IdentityUnverified(f"{what}: an authority key is not a reviewer key")
        if not _verify(
            authority.public_key, enrolment.authority_signature, enrolment_statement(enrolment)
        ):
            raise IdentityUnverified(f"{what}: the authority's signature does not verify")

    def verify_revocation(self, revocation: ReviewerKeyRevocation) -> None:
        what = f"revocation {revocation.revocation_id}"
        authority = self._authority_for(
            revocation.authority_actor_id, revocation.authority_key_id, what
        )
        if not _verify(
            authority.public_key,
            revocation.authority_signature,
            revocation_statement(revocation),
        ):
            raise IdentityUnverified(f"{what}: the authority's signature does not verify")

    def verify_grant(
        self,
        grant: DiagnosticWarrantGrant,
        enrolment: ReviewerEnrolment | None,
        revocations: Iterable[ReviewerKeyRevocation] = (),
    ) -> None:
        """Raise `IdentityUnverified` unless `grant` is an answer its named reviewer signed."""
        what = f"answer {grant.grant_id}"
        if grant.enrolment_id is None or grant.signature is None:
            raise IdentityUnverified(f"{what} is unsigned")
        if enrolment is None or enrolment.enrolment_id != grant.enrolment_id:
            raise IdentityUnverified(f"{what} names enrolment {grant.enrolment_id}, not recorded")
        if (enrolment.project_id, enrolment.actor_id) != (
            grant.project_id,
            grant.granted_by_actor_id,
        ):
            raise IdentityUnverified(
                f"{what} is by {grant.granted_by_actor_id} in {grant.project_id}, but enrolment "
                f"{enrolment.enrolment_id} is {enrolment.actor_id}'s in {enrolment.project_id}"
            )
        self.verify_enrolment(enrolment)
        if grant.granted_at < enrolment.enrolled_at:
            raise IdentityUnverified(f"{what} predates the enrolment of the key it is signed with")
        for revocation in revocations:
            if revocation.enrolment_id != enrolment.enrolment_id:
                continue
            self.verify_revocation(revocation)
            if revocation.effective_at <= grant.granted_at:
                raise IdentityUnverified(
                    f"{what} is signed with a key revoked from "
                    f"{revocation.effective_at.isoformat()}"
                )
        if not _verify(enrolment.public_key, grant.signature, grant.statement()):
            raise IdentityUnverified(f"{what}: the reviewer's signature does not verify")


class SigningKey:
    """A private Ed25519 key held by a reviewer or an authority, never by the database."""

    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key

    @classmethod
    def generate(cls) -> SigningKey:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, path: str | os.PathLike[str], passphrase: bytes | None = None) -> SigningKey:
        data = Path(path).read_bytes()
        try:
            key = serialization.load_pem_private_key(data, password=passphrase)
        except (TypeError, ValueError) as exc:
            raise IdentityUnverified(
                f"{path} is not a readable Ed25519 private key: {exc}"
            ) from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise IdentityUnverified(f"{path} is not an Ed25519 private key")
        return cls(key)

    def save(self, path: str | os.PathLike[str], passphrase: bytes | None = None) -> None:
        """Write the key as PEM, readable by its owner only; never over an existing file."""
        encryption: serialization.KeySerializationEncryption = (
            serialization.BestAvailableEncryption(passphrase)
            if passphrase
            else serialization.NoEncryption()
        )
        data = self._key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption
        )
        target = Path(path)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)

    @property
    def public_key(self) -> str:
        raw = self._key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return base64.b64encode(raw).decode("ascii")

    @property
    def key_id(self) -> str:
        return key_id(self.public_key)

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self._key.sign(message)).decode("ascii")


def sign_enrolment(
    authority: SigningKey,
    *,
    authority_actor_id: str,
    enrolment_id: str,
    project_id: str,
    actor_id: str,
    public_key: str,
    enrolled_at: dt.datetime,
) -> ReviewerEnrolment:
    """An enrolment signed by `authority` (whose actor must be someone other than `actor_id`)."""
    unsigned = {
        "enrolment_id": enrolment_id,
        "project_id": project_id,
        "actor_id": actor_id,
        "public_key": public_key,
        "enrolled_at": enrolled_at,
        "authority_actor_id": authority_actor_id,
        "authority_key_id": authority.key_id,
    }
    placeholder = ReviewerEnrolment.model_validate(
        {**unsigned, "authority_signature": base64.b64encode(bytes(64)).decode("ascii")}
    )
    return placeholder.model_copy(
        update={"authority_signature": authority.sign(enrolment_statement(placeholder))}
    )


def sign_revocation(
    authority: SigningKey,
    *,
    authority_actor_id: str,
    revocation_id: str,
    enrolment_id: str,
    project_id: str,
    effective_at: dt.datetime,
    reason: str,
) -> ReviewerKeyRevocation:
    placeholder = ReviewerKeyRevocation.model_validate(
        {
            "revocation_id": revocation_id,
            "enrolment_id": enrolment_id,
            "project_id": project_id,
            "effective_at": effective_at,
            "reason": reason,
            "authority_actor_id": authority_actor_id,
            "authority_key_id": authority.key_id,
            "authority_signature": base64.b64encode(bytes(64)).decode("ascii"),
        }
    )
    return placeholder.model_copy(
        update={"authority_signature": authority.sign(revocation_statement(placeholder))}
    )


@dataclass(frozen=True)
class ReviewerSigner:
    """What `resolve` needs to sign an answer: whose it is, under which enrolment, and the key."""

    actor_id: str
    enrolment_id: str
    key: SigningKey

    def sign(self, message: bytes) -> str:
        return self.key.sign(message)


def passphrase_from(env: Mapping[str, str]) -> bytes | None:
    value = env.get(PASSPHRASE_ENV)
    return value.encode("utf-8") if value else None


class EnrolmentSource(Protocol):
    """Where enrolments and revocations are stored (the warrant stores)."""

    def enrolment(self, project_id: str, enrolment_id: str) -> ReviewerEnrolment | None: ...

    def revocations(
        self, project_id: str, enrolment_id: str
    ) -> tuple[ReviewerKeyRevocation, ...]: ...


def grant_authenticator(
    source: EnrolmentSource, trust: ReviewerTrust
) -> Callable[[DiagnosticWarrantGrant], str | None]:
    """`core.warrant.GrantAuthenticator` over stored enrolments and the pinned authorities."""

    def authenticate(grant: DiagnosticWarrantGrant) -> str | None:
        enrolment = (
            None
            if grant.enrolment_id is None
            else source.enrolment(grant.project_id, grant.enrolment_id)
        )
        revocations = (
            ()
            if enrolment is None
            else source.revocations(grant.project_id, grant.enrolment_id or "")
        )
        try:
            trust.verify_grant(grant, enrolment, revocations)
        except IdentityUnverified as refused:
            return str(refused)
        return None

    return authenticate


__all__ = [
    "AUTHORITIES_ENV",
    "PASSPHRASE_ENV",
    "EnrolmentSource",
    "IdentityUnverified",
    "ReviewAuthority",
    "ReviewerSigner",
    "ReviewerTrust",
    "SigningKey",
    "grant_authenticator",
    "parse_authorities",
    "passphrase_from",
    "sign_enrolment",
    "sign_revocation",
]
