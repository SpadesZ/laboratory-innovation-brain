"""Who may answer a DIAGNOSTIC_WARRANT review, and how an answer proves who gave it (V1.1).

WHY A SIGNATURE, NOT AN ACTOR ID. Until V1.1 the answering actor was a parameter: of the CLI
(`--actor`) and of `diagnostic_warrant_resolve`. Anyone who could reach the database could answer
as the PI, and the gate's separation of duties -- not the episode's runner, not the hypothesis's
author -- was only as strong as a string. An answer now carries an Ed25519 signature over its
whole content, made with a key enrolled for that person in that project; the read path checks it
every time it counts the answer. A database writer can still write rows; it cannot write one that
verifies.

INDEPENDENT AUTHORIZATION. A reviewer key counts only when a review AUTHORITY enrolled it: the
authority signs the enrolment, and the authority's public key is pinned in the deployment's
configuration, outside the database, so nothing written to the database can mint an authority.
An authority never enrols itself, and one key belongs to one person.

THIS MODULE IS PURE. It defines the records and the exact bytes each signature covers. Producing
and checking signatures is `lab_brain.security.reviewer_identity`; the stores keep the rows.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import re
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.canonical_json import canonical_bytes
from lab_brain.core.models.base import CoreModel

#: The one review subject a reviewer key answers today.
WARRANT_REVIEW_SCOPE = "DIAGNOSTIC_WARRANT"

#: Domain separation: a signature over one kind of statement is never valid for another.
GRANT_STATEMENT = "lab-brain/diagnostic-warrant-grant/v1"
ENROLMENT_STATEMENT = "lab-brain/reviewer-enrolment/v1"
REVOCATION_STATEMENT = "lab-brain/reviewer-revocation/v1"

_ED25519_PUBLIC = 32
_ED25519_SIGNATURE = 64
_KEY_ID = re.compile(r"^rk:[0-9a-f]{32}$")


def _decoded(value: str, size: int) -> bytes | None:
    """The raw bytes, if `value` is their canonical base64 spelling and nothing else.

    Canonical, because base64 tolerates non-zero padding bits: without this one key or signature
    could be stored under several strings, and a string is what the database compares.
    """
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != size or base64.b64encode(raw).decode("ascii") != value:
        return None
    return raw


def is_public_key(value: str) -> bool:
    """Whether `value` is a base64 Ed25519 public key (32 bytes)."""
    return _decoded(value, _ED25519_PUBLIC) is not None


def is_signature(value: str) -> bool:
    """Whether `value` is a base64 Ed25519 signature (64 bytes)."""
    return _decoded(value, _ED25519_SIGNATURE) is not None


def key_id(public_key: str) -> str:
    """A key's stable identity: `rk:` and the first 128 bits of SHA-256 over its raw bytes."""
    raw = _decoded(public_key, _ED25519_PUBLIC)
    if raw is None:
        raise ValueError("not a base64 Ed25519 public key")
    return f"rk:{hashlib.sha256(raw).hexdigest()[:32]}"


def _instant(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat(timespec="microseconds")


class ReviewerEnrolment(CoreModel):
    """An authority's signed statement: this key answers warrant reviews for this person here."""

    enrolment_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    public_key: str
    scope: str = WARRANT_REVIEW_SCOPE
    enrolled_at: dt.datetime
    authority_actor_id: str = Field(min_length=1)
    authority_key_id: str
    authority_signature: str

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not is_public_key(self.public_key):
            raise ValueError(f"enrolment {self.enrolment_id} names no Ed25519 public key")
        if not _KEY_ID.match(self.authority_key_id):
            raise ValueError(f"enrolment {self.enrolment_id} names no authority key id")
        if not is_signature(self.authority_signature):
            raise ValueError(f"enrolment {self.enrolment_id} carries no Ed25519 signature")
        if self.scope != WARRANT_REVIEW_SCOPE:
            raise ValueError(f"enrolment {self.enrolment_id} is for {self.scope}")
        if self.authority_actor_id == self.actor_id:
            raise ValueError(
                f"{self.actor_id} cannot enrol their own reviewer key; authorization to answer "
                "is given by someone else"
            )
        return self

    @property
    def key_id(self) -> str:
        return key_id(self.public_key)


def enrolment_statement(enrolment: ReviewerEnrolment) -> bytes:
    """The bytes the authority signs to enrol a reviewer key."""
    return canonical_bytes(
        {
            "statement": ENROLMENT_STATEMENT,
            "enrolment_id": enrolment.enrolment_id,
            "project_id": enrolment.project_id,
            "actor_id": enrolment.actor_id,
            "public_key": enrolment.public_key,
            "scope": enrolment.scope,
            "enrolled_at": _instant(enrolment.enrolled_at),
            "authority_actor_id": enrolment.authority_actor_id,
            "authority_key_id": enrolment.authority_key_id,
        }
    )


class ReviewerKeyRevocation(CoreModel):
    """An authority's signed statement that an enrolled key answers nothing from `effective_at`.

    Answers signed before `effective_at` still count; the database also refuses any answer from
    a revoked enrolment once the revocation is recorded, whatever time it claims.
    """

    revocation_id: str = Field(min_length=1)
    enrolment_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    effective_at: dt.datetime
    reason: str = Field(min_length=1)
    authority_actor_id: str = Field(min_length=1)
    authority_key_id: str
    authority_signature: str

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not _KEY_ID.match(self.authority_key_id):
            raise ValueError(f"revocation {self.revocation_id} names no authority key id")
        if not is_signature(self.authority_signature):
            raise ValueError(f"revocation {self.revocation_id} carries no Ed25519 signature")
        return self


def revocation_statement(revocation: ReviewerKeyRevocation) -> bytes:
    """The bytes the authority signs to revoke an enrolment."""
    return canonical_bytes(
        {
            "statement": REVOCATION_STATEMENT,
            "revocation_id": revocation.revocation_id,
            "enrolment_id": revocation.enrolment_id,
            "project_id": revocation.project_id,
            "effective_at": _instant(revocation.effective_at),
            "reason": revocation.reason,
            "authority_actor_id": revocation.authority_actor_id,
            "authority_key_id": revocation.authority_key_id,
        }
    )


def grant_statement(
    *,
    grant_id: str,
    project_id: str,
    review_id: str,
    relation_id: str,
    relation_type: str,
    hypothesis_id: str,
    prediction_id: str,
    verdict: str,
    granted_by_actor_id: str,
    granted_at: dt.datetime,
    rationale: str,
    considered_rival_ids: tuple[str, ...],
    identifies_class_ref: str | None,
    enrolment_id: str,
) -> bytes:
    """The bytes a reviewer signs to answer one review: every field the answer consists of.

    The relation, its type, the hypothesis and the prediction are in it, so an answer cannot be
    moved onto another link; the verdict, rationale and identity statement are in it, so it
    cannot be edited into another answer.
    """
    return canonical_bytes(
        {
            "statement": GRANT_STATEMENT,
            "grant_id": grant_id,
            "project_id": project_id,
            "review_id": review_id,
            "relation_id": relation_id,
            "relation_type": relation_type,
            "hypothesis_id": hypothesis_id,
            "prediction_id": prediction_id,
            "verdict": verdict,
            "granted_by_actor_id": granted_by_actor_id,
            "granted_at": _instant(granted_at),
            "rationale": rationale.strip(),
            "considered_rival_ids": sorted(considered_rival_ids),
            "identifies_class_ref": identifies_class_ref,
            "enrolment_id": enrolment_id,
        }
    )


__all__ = [
    "ENROLMENT_STATEMENT",
    "GRANT_STATEMENT",
    "REVOCATION_STATEMENT",
    "WARRANT_REVIEW_SCOPE",
    "ReviewerEnrolment",
    "ReviewerKeyRevocation",
    "enrolment_statement",
    "grant_statement",
    "is_public_key",
    "is_signature",
    "key_id",
    "revocation_statement",
]
