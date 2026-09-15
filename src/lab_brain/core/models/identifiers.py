"""Entity identifiers, and the content addressing that ART-001 rests on.

Two kinds of identity exist here, and conflating them is the mistake this module is shaped to
prevent:

**Content-addressed** (``Artifact``). The identifier is a pure function of the bytes. The same
bytes always yield the same identifier; changing one byte yields a different one. There is no
code path that mints an artifact identifier from anything other than content, so "two artifacts
with the same bytes but different ids" is unrepresentable rather than merely discouraged.

**Event-addressed** (everything else). An ``Attestation`` is a distinct act of witnessing: the
same source attesting the same Claim twice is two attestations, so these identifiers are random.
Ordering comes from ``created_at``, not from the identifier.

Human-meaningful versioning is a third, separate thing -- ``lineage_id`` / ``lineage_revision``
/ ``previous_artifact_id`` (§6.1). "Version 2 of the report" is a lineage statement; it does not
and must not affect the content hash.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO, Final

#: Algorithm label carried in every content hash. Recorded explicitly so a future migration to
#: another digest can coexist with existing hashes instead of silently reinterpreting them.
HASH_ALGORITHM: Final = "sha256"

#: Read size for streaming hashes. Simulation outputs are routinely larger than memory.
_CHUNK_SIZE: Final = 1024 * 1024

ARTIFACT_ID_PREFIX: Final = "art"

_ID_PREFIXES: Final[dict[str, str]] = {
    "source_work": "swk",
    "claim": "clm",
    "observation": "obs",
    "attestation": "att",
    "relation": "rel",
    "condition_match": "cmt",
    "evidence_bundle": "bdl",
    "actor": "act",
    "project": "prj",
    "lineage": "lin",
    # P6 / OPS-003. A trace is minted once per episode and threaded through every span; a span id
    # is minted per execution interval. Separate kinds because they are separate identities --
    # reusing one id for both would make a trace indistinguishable from its own root span.
    "trace": "trc",
    "execution_span": "spn",
    # P7 / EPI-003, EPI-005.
    "belief_revision_event": "bre",
    "hypothesis": "hyp",
}


class ContentHashError(ValueError):
    """A content hash is malformed or inconsistent with the identity derived from it."""


def compute_content_hash(data: bytes) -> str:
    """Return the canonical content hash of ``data`` as ``"sha256:<hex>"``."""
    return f"{HASH_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


def compute_content_hash_from_chunks(chunks: Iterable[bytes]) -> str:
    """Hash an iterable of byte chunks without holding the whole payload in memory."""
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return f"{HASH_ALGORITHM}:{digest.hexdigest()}"


def _iter_stream(stream: IO[bytes]) -> Iterator[bytes]:
    while chunk := stream.read(_CHUNK_SIZE):
        yield chunk


def compute_content_hash_from_stream(stream: IO[bytes]) -> str:
    return compute_content_hash_from_chunks(_iter_stream(stream))


def compute_content_hash_from_path(path: Path) -> str:
    with path.open("rb") as stream:
        return compute_content_hash_from_stream(stream)


def parse_content_hash(content_hash: str) -> tuple[str, str]:
    """Split ``"sha256:<hex>"`` into ``(algorithm, hex)``, validating both halves."""
    algorithm, separator, hex_digest = content_hash.partition(":")
    if not separator:
        raise ContentHashError(f"content hash must be '<algorithm>:<hex>', got {content_hash!r}")
    if algorithm != HASH_ALGORITHM:
        raise ContentHashError(
            f"unsupported hash algorithm {algorithm!r}; this build writes {HASH_ALGORITHM!r}"
        )
    expected_length = hashlib.sha256().digest_size * 2
    if len(hex_digest) != expected_length:
        raise ContentHashError(
            f"{algorithm} digest must be {expected_length} hex characters, got {len(hex_digest)}"
        )
    if not all(character in "0123456789abcdef" for character in hex_digest):
        raise ContentHashError("content hash digest must be lowercase hexadecimal")
    return algorithm, hex_digest


def artifact_id_for(content_hash: str) -> str:
    """Derive the content-addressed ``artifact_id`` from a content hash.

    Total and injective, so ART-001's "same bytes -> same identity, one byte changed -> new
    identity" is a property of arithmetic rather than of an invariant someone has to maintain.
    """
    parse_content_hash(content_hash)
    return f"{ARTIFACT_ID_PREFIX}:{content_hash}"


def content_hash_for(artifact_id: str) -> str:
    """Inverse of :func:`artifact_id_for`."""
    prefix, separator, remainder = artifact_id.partition(":")
    if not separator or prefix != ARTIFACT_ID_PREFIX:
        raise ContentHashError(
            f"artifact id must start with {ARTIFACT_ID_PREFIX!r}:, got {artifact_id!r}"
        )
    parse_content_hash(remainder)
    return remainder


def new_id(kind: str) -> str:
    """Mint a random identifier for an event-addressed entity.

    Deliberately not usable for artifacts: ``kind`` must be a registered non-artifact entity,
    so there is no way to hand an ``Artifact`` a non-content-derived identity by mistake.
    """
    try:
        prefix = _ID_PREFIXES[kind]
    except KeyError:
        raise ValueError(
            f"unknown entity kind {kind!r}; known kinds: {sorted(_ID_PREFIXES)}. "
            "Artifacts are content-addressed -- use artifact_id_for()."
        ) from None
    return f"{prefix}:{uuid.uuid4()}"


__all__ = [
    "ARTIFACT_ID_PREFIX",
    "HASH_ALGORITHM",
    "ContentHashError",
    "artifact_id_for",
    "compute_content_hash",
    "compute_content_hash_from_chunks",
    "compute_content_hash_from_path",
    "compute_content_hash_from_stream",
    "content_hash_for",
    "new_id",
    "parse_content_hash",
]
