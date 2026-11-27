"""Passwords and tokens, with the standard library's established primitives only.

PASSWORDS are hashed with scrypt (`hashlib.scrypt`, RFC 7914) under a random 16-byte salt; the
stored form names its parameters, so a later, stronger cost still verifies every older hash, and
`needs_rehash` says when one should be upgraded. Verification is constant-time, and an unknown
account is checked against a dummy hash so a sign-in takes as long whether or not the email exists.

TOKENS -- session cookies, email verification and password-reset links -- are 32 random bytes
from `secrets`. Only their SHA-256 is stored: whoever reads the database cannot sign in or reset a
password with what they read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass


#: scrypt's cost: N = 2**15, r = 8, p = 1 (32 MiB, OWASP's minimum recommendation for scrypt).
@dataclass(frozen=True)
class ScryptCost:
    n: int = 2**15
    r: int = 8
    p: int = 1

    @property
    def maxmem(self) -> int:
        return 128 * self.n * self.r * 2 + 1024 * 1024


DEFAULT_COST = ScryptCost()

MIN_PASSWORD = 12
MAX_PASSWORD = 256

_HASH = re.compile(r"^scrypt\$(\d+)\$(\d+)\$(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)$")


class WeakPassword(ValueError):
    """The password does not meet the policy. `code` names which rule, for the interface to
    say in the reader's language."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def check_password_policy(password: str, *, email: str = "") -> None:
    """At least 12 characters, at most 256, not the email address, not one repeated character."""
    if len(password) < MIN_PASSWORD:
        raise WeakPassword("too_short", f"a password has at least {MIN_PASSWORD} characters")
    if len(password) > MAX_PASSWORD:
        raise WeakPassword("too_long", f"a password has at most {MAX_PASSWORD} characters")
    if email and password.strip().lower() == email.strip().lower():
        raise WeakPassword("is_email", "a password is not the email address")
    if len(set(password)) < 4:
        raise WeakPassword("repetitive", "a password uses more than a few distinct characters")


def _derive(password: str, salt: bytes, cost: ScryptCost) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=cost.n,
        r=cost.r,
        p=cost.p,
        maxmem=cost.maxmem,
        dklen=32,
    )


def hash_password(password: str, *, cost: ScryptCost = DEFAULT_COST) -> str:
    salt = secrets.token_bytes(16)
    key = _derive(password, salt, cost)
    b64 = base64.b64encode
    return f"scrypt${cost.n}${cost.r}${cost.p}${b64(salt).decode()}${b64(key).decode()}"


def _parse(stored: str) -> tuple[ScryptCost, bytes, bytes] | None:
    found = _HASH.match(stored or "")
    if found is None:
        return None
    n, r, p = (int(found.group(i)) for i in (1, 2, 3))
    if n < 2 or n & (n - 1) or n > 2**20 or not 1 <= r <= 32 or not 1 <= p <= 16:
        return None
    try:
        salt = base64.b64decode(found.group(4), validate=True)
        key = base64.b64decode(found.group(5), validate=True)
    except ValueError:
        return None
    return ScryptCost(n, r, p), salt, key


#: A hash of nothing anyone knows, checked when the account does not exist (equal timing).
_DUMMY = hash_password(secrets.token_urlsafe(32))


def verify_password(password: str, stored: str | None) -> bool:
    parsed = _parse(stored or "")
    if parsed is None:
        dummy = _parse(_DUMMY)
        assert dummy is not None
        _derive(password, dummy[1], dummy[0])
        return False
    cost, salt, key = parsed
    return hmac.compare_digest(_derive(password, salt, cost), key)


def needs_rehash(stored: str, *, cost: ScryptCost = DEFAULT_COST) -> bool:
    parsed = _parse(stored)
    return parsed is None or (parsed[0].n, parsed[0].r, parsed[0].p) < (cost.n, cost.r, cost.p)


def new_token() -> str:
    """32 random bytes, URL-safe: a session cookie, or the secret in a link."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What is stored for a token: its SHA-256, hex."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def keyed_digest(key: bytes, *parts: str) -> str:
    """HMAC-SHA-256 over the parts, for values that must be bound to a secret (CSRF tokens)."""
    return hmac.new(key, "\x1f".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")


def normalized_email(raw: str) -> str | None:
    """The address as accounts store it (trimmed, lower-case), or None if it is not one.

    Any domain is accepted: university and personal addresses alike.
    """
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        return None
    return email
