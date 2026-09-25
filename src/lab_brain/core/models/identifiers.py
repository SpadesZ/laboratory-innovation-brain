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

#: §17.25 / ADR-0011. Like `art`, a derived prefix rather than a minted one -- see
#: :func:`evidence_unit_id_for`.
EVIDENCE_UNIT_ID_PREFIX: Final = "evu"

_ID_PREFIXES: Final[dict[str, str]] = {
    "source_work": "swk",
    # M1 / EVI-010. A RetrievalRepresentation is event-addressed on purpose: re-indexing the same
    # unit produces a genuinely new artefact with its own build time, and collapsing two builds
    # into one identity would hide exactly the rebuild ADR-0011 requires be observable.
    "retrieval_representation": "rrp",
    "ingestion_item": "ing",
    # M1 / OPS-001. Both event-addressed, and separate kinds because they are separate
    # identities: a Job is a submission and a Run is an execution, and one submission may be
    # retried several times while producing exactly one Run. Sharing a prefix would make a job
    # indistinguishable from its own output in a log.
    "job": "job",
    "run": "run",
    # M1 / LLM-001. §17.14's `inference_id`.
    "inference": "inf",
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
    # M2 / §17.19.2. A ValidationReport is event-addressed: re-running a validator over the same
    # subject after a rule version changes is a genuinely new report, and collapsing the two into
    # one identity would hide the re-check that the version bump exists to make visible.
    "validation": "vld",
    # M2 / §10.7. A lease on a license seat. Event-addressed for the same reason a Run is: the
    # same Job acquiring a seat, releasing it and acquiring one again is two allocations, and a
    # contention audit asks which one was held when a third job was refused.
    "resource_lease": "lse",
    # M3 / §17.14.1, EPI-001, LLM-002, SRC-003. All event-addressed: a second debate over the same
    # question is a second debate, and a second prior-art search over the same concept is a second
    # search with its own coverage -- collapsing either into one identity would hide the repeat.
    "hypothesis_set": "hst",
    "prediction": "prd",
    "position": "pos",
    "critique": "crq",
    "debate": "dbt",
    "prior_art_search": "pas",
    "novelty_assessment": "nov",
    "research_contract": "rct",
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


def evidence_unit_id_for(artifact_id: str, structural_path: str, content_digest: str) -> str:
    """Derive an ``EvidenceUnit`` identity from the three things §17.25 says determine it.

    A third kind of identity, and it is here rather than in ``new_id`` for the reason ADR-0011
    exists: if a unit's identity were minted, re-running the segmenter over unchanged bytes would
    produce different ids for the same evidence, and every Attestation referencing the old ones
    would quietly point at nothing. Deriving it makes "the same evidence" a computable fact.

    The three inputs are exactly §17.25's, and each is load-bearing:

        artifact_id       which bytes. Two documents saying the same sentence are two units.
        structural_path   where in those bytes. The same sentence repeated in an abstract and a
                          conclusion is two units, and a reader needs to know which one was cited.
        content_digest    what the unit actually holds. Re-segmenting with different boundaries
                          yields a different body and therefore a different unit, rather than
                          silently redefining an existing one under its old id.

    Note what is absent: no embedding model, no version, no dimensionality, no reranker, no token
    window. That absence is the contract (§6.22, EVI-010) -- deleting and rebuilding an index
    cannot change any value this function returns.
    """
    parse_content_hash(content_digest)
    if not artifact_id.startswith(f"{ARTIFACT_ID_PREFIX}:"):
        raise ContentHashError(
            f"evidence unit identity needs an artifact id, got {artifact_id!r}; a unit that "
            "cannot name the bytes it came from is unauditable (§6.22)"
        )
    if not structural_path.strip():
        raise ContentHashError(
            "evidence unit identity needs a non-empty structural_path; without it two units from "
            "the same document with identical text would collapse into one"
        )
    # A length-prefixed join rather than a delimiter. `a|bc` and `ab|c` must not hash alike, and a
    # structural path is user-visible text that could contain any separator chosen here.
    parts = (artifact_id, structural_path, content_digest)
    payload = "".join(f"{len(part)}:{part}" for part in parts).encode("utf-8")
    return f"{EVIDENCE_UNIT_ID_PREFIX}:{compute_content_hash(payload)}"


def segmentation_witness_for(
    *,
    artifact_id: str,
    structural_path: str,
    body: str,
    inherited_context: Iterable[str],
    bound_condition_texts: Iterable[str],
    parser_id: str,
    parser_version: str,
    segmenter_id: str,
    segmenter_version: str,
) -> str:
    """Digest binding an evidence unit's conformance-relevant fields (§17.25, `v3.3-a18`).

    WHAT THIS IS FOR, and what it is emphatically not for.

    It is the storage-checkable half of SPEC-ISSUE-015's two-layer answer, and the exact analogue
    of `input_hash` in `v3.3-a12`: it lets the *store* reject a partially forged row -- body edited,
    witness left behind -- without re-serializing and without agreeing with the writer about field
    order. PostgreSQL can recompute it with `sha256()`, which is a byte operation; nothing has to
    read the prose.

    It does **not** stop a complete forgery. Anyone who knows this function can compute a
    consistent witness for any row they like. That is expected, it is stated in ADR-0012, and it is
    why the semantic layer exists: scientific admission re-runs the recorded segmenter over the
    artifact's content-addressed bytes and requires the unit to be among what comes out. Treating
    this digest as sufficient on its own would delete that layer and restore the issue.

    The field list is the conformance surface, not the whole row. `created_at` and
    `source_work_id` are excluded because they are not outputs of segmentation -- binding them
    would make the witness un-recomputable by a re-derivation that legitimately produces the same
    evidence at a different time.
    """
    parts = (
        artifact_id,
        structural_path,
        body,
        # Length-prefixed inside the sequence too: two adjacent context strings must not be able
        # to impersonate one longer string, which a plain join would permit.
        _length_prefixed(inherited_context),
        _length_prefixed(bound_condition_texts),
        parser_id,
        parser_version,
        segmenter_id,
        segmenter_version,
    )
    payload = "".join(f"{len(part)}:{part}" for part in parts).encode("utf-8")
    return compute_content_hash(payload)


def _length_prefixed(values: Iterable[str]) -> str:
    return "".join(f"{len(value)}:{value}" for value in values)


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
    "EVIDENCE_UNIT_ID_PREFIX",
    "HASH_ALGORITHM",
    "ContentHashError",
    "artifact_id_for",
    "compute_content_hash",
    "compute_content_hash_from_chunks",
    "compute_content_hash_from_path",
    "compute_content_hash_from_stream",
    "content_hash_for",
    "evidence_unit_id_for",
    "new_id",
    "parse_content_hash",
    "segmentation_witness_for",
]
