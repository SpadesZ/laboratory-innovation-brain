"""Canonical JSON serialization — a **restricted profile** of RFC 8785 (JCS).

This is deliberately NOT a conformant RFC 8785 implementation, and must not be described as one.
It implements the subset of JCS that accepts a restricted value domain, and **fails closed** on
anything outside it. A caller cannot use it to canonicalize arbitrary JSON.

§17.14.1 requires an EvidenceBundle hash computed over a canonical serialization:

    canonical_hash(bundle) = SHA256(JCS/RFC8785 canonical JSON of hash_fields)
    ...不得 hash 任意 JSON 字串順序。

The property that matters is that two processes agreeing on the *content* must agree on the
*bytes*. A hash over `json.dumps(...)` with default settings does not have it: key order follows
insertion order, so the same bundle assembled by two code paths hashes differently and provenance
silently stops matching.

IMPLEMENTED (matches RFC 8785)

  - object keys sorted by UTF-16 code unit order (§3.2.3)
  - no insignificant whitespace (§3.2.1)
  - minimal string escaping (§3.2.2.2)
  - `true` / `false` / `null` literals
  - integers within ±(2^53 - 1), as plain decimal

NOT IMPLEMENTED — rejected, never guessed

  - **floats** (§3.2.2.3). JCS requires ECMAScript `Number::toString`: shortest round-tripping
    representation, exponent thresholds at 1e21 and 1e-7, negative zero. Implementing it subtly
    wrong yields hashes that agree on one machine and disagree on another, which is worse than
    refusing outright.
  - **integers beyond ±(2^53 - 1)**. JCS numbers are ECMAScript doubles, so a larger integer has
    no canonical form.
  - anything that is not `str` / `int` / `bool` / `None` / `list` / `tuple` / `dict`.

Consequence: a document this module accepts hashes identically to a conformant implementation.
A document it rejects would have hashed fine under a conformant one. That asymmetry is the design
— narrower and honest, rather than broad and occasionally wrong.

The restriction costs nothing here. Bundle identity hashes attestation IDs, a query string, policy
identifiers and condition *filters*; measured values live in Observations and the numerical store.
If a future requirement genuinely needs floats, implementing `Number::toString` correctly is the
price, and it should be paid deliberately rather than approximated.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Beyond this, an int is not exactly representable as an IEEE-754 double, so a JSON consumer
#: reading it as a number would round it. RFC 8785 serializes numbers via ECMAScript semantics,
#: where every number *is* a double -- so a larger integer has no canonical form.
MAX_SAFE_INTEGER = 2**53 - 1


class CanonicalizationError(TypeError):
    """A value cannot be canonicalized deterministically."""


def _utf16_sort_key(key: str) -> bytes:
    """RFC 8785 §3.2.3 sorts keys by UTF-16 code unit.

    Not the same as Python's default string ordering, which compares code points. The two diverge
    for characters outside the BMP: U+FFFD sorts *after* U+10000 by code point but *before* it by
    UTF-16 code unit, because the latter is encoded as a surrogate pair beginning 0xD800.
    Encoding to UTF-16BE and comparing bytes reproduces the required order exactly.
    """
    return key.encode("utf-16-be")


def _serialize(value: Any, path: str) -> str:
    if value is None:
        return "null"

    # bool before int: bool is a subclass of int, and `True` must serialize as `true`.
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalizationError(
                f"{path}: integer {value} exceeds the safe range (±{MAX_SAFE_INTEGER}). JCS "
                "numbers are ECMAScript doubles, so a larger integer has no canonical form. "
                "This profile rejects rather than rounds."
            )
        return str(value)

    if isinstance(value, float):
        raise CanonicalizationError(
            f"{path}: float values are outside this restricted JCS profile. Conformant RFC 8785 "
            "requires ECMAScript Number::toString semantics, which is easy to get subtly wrong "
            "and would yield hashes that differ between machines. Bundle identity hashes IDs, "
            "queries and filters -- measured values belong in Observations and the numerical "
            "store. Convert to a string if the value is genuinely part of identity."
        )

    if isinstance(value, str):
        # json.dumps with ensure_ascii=False produces exactly RFC 8785 §3.2.2.2 escaping:
        # the \b \f \n \r \t \" \\ shortcuts, and \u00xx lowercase hex for other C0 controls.
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, list | tuple):
        items = ",".join(_serialize(item, f"{path}[{index}]") for index, item in enumerate(value))
        return f"[{items}]"

    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"{path}: object keys must be strings, got {type(key).__name__}; "
                    "a non-string key has no defined canonical ordering"
                )
        members = ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{_serialize(value[key], f'{path}.{key}')}"
            for key in sorted(value, key=_utf16_sort_key)
        )
        return f"{{{members}}}"

    raise CanonicalizationError(
        f"{path}: {type(value).__name__} is outside this restricted JCS profile. Convert it to a "
        "string, int, bool, None, list or dict first -- an implicit conversion here would make "
        "the hash depend on this implementation's choices."
    )


def canonicalize(value: Any) -> str:
    """Return the canonical JSON form of ``value`` under the restricted JCS profile.

    Deterministic across processes and machines for any input this accepts. Raises
    :class:`CanonicalizationError` for anything outside the accepted domain -- see the module
    docstring for what is deliberately not implemented.
    """
    return _serialize(value, "$")


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON encoded as UTF-8, which is what gets hashed (RFC 8785 §3.1)."""
    return canonicalize(value).encode("utf-8")


def canonical_hash(value: Any) -> str:
    """SHA-256 over the canonical form, prefixed with the algorithm.

    The prefix is not decoration: it lets a future migration to another digest coexist with
    existing hashes instead of silently reinterpreting them, the same reason
    ``Artifact.content_hash`` carries one.
    """
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


__all__ = [
    "MAX_SAFE_INTEGER",
    "CanonicalizationError",
    "canonical_bytes",
    "canonical_hash",
    "canonicalize",
]
