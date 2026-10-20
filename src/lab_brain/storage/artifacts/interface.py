"""The artifact store seam, and the compensation contract OPS-004 requires (§12.3).

TWO STORES, ONE UNIT OF WORK, NO DISTRIBUTED TRANSACTION.

Ingestion writes bytes to an object store and rows to PostgreSQL. There is no transaction
spanning both, and pretending otherwise is the failure OPS-004 names: a crash between the two
leaves either an orphan blob nobody can find or -- far worse -- a database row referencing bytes
that were never written, which reads as admitted evidence and resolves to nothing.

So the seam is explicit about which half is authoritative and what happens when the other fails:

    1. stage bytes      reversible. A staged blob is not yet addressable as an artifact.
    2. commit the DB    the authoritative moment. After this the artifact exists.
    3. promote bytes    makes the staged blob addressable.

    failure at 2  ->  discard the staged blob. Nothing ever referenced it.
    failure at 3  ->  compensate: roll the DB back to before step 2.

Step 3 can fail and that is the case worth designing for, because it is the one where the
database already says the artifact exists. ``ArtifactStore.discard`` is therefore required to be
idempotent and total: a compensating action that can itself fail leaves the inconsistency it was
called to remove.

WHY NOT "WRITE BYTES FIRST, THEN THE ROW". Because an orphan blob is invisible. Nothing points at
it, no query finds it, and it costs storage forever. Staging makes the orphan window bounded and
sweepable, and the sweep has a name (``list_staged``) rather than being an operations ticket.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ArtifactStoreError(RuntimeError):
    """The artifact store could not complete an operation."""


class StagedBlobNotFound(ArtifactStoreError):
    """A staged blob was promoted or discarded that the store has no record of."""


@dataclass(frozen=True)
class StagedBlob:
    """A reversible byte write. Not yet an artifact.

    ``content_hash`` is computed by the store on stage, not supplied by the caller. A caller that
    supplied it could stage bytes under an identity they do not hash to, and every content-address
    guarantee downstream would rest on that claim.
    """

    staging_id: str
    content_hash: str
    size_bytes: int


@runtime_checkable
class ArtifactStore(Protocol):
    """Where artifact bytes live. PostgreSQL holds the rows; this holds the content."""

    def stage(self, data: bytes) -> StagedBlob:
        """Write ``data`` reversibly and return its computed identity."""
        ...

    def promote(self, staging_id: str, content_hash: str) -> str:
        """Make a staged blob addressable by content hash. Returns the store URI.

        ``content_hash`` is passed again and checked against the staged blob's own: promotion is
        the moment the bytes become the artifact the database row names, and a mismatch here means
        the caller has confused two staged blobs.
        """
        ...

    def discard(self, staging_id: str) -> None:
        """Remove a staged blob. MUST be idempotent and MUST NOT raise if already gone.

        This is the compensating action. If it can fail, the compensation can fail, and OPS-004's
        "no dangling reference" becomes conditional on this call having happened to succeed.
        """
        ...

    def open(self, content_hash: str) -> bytes:
        """Read promoted bytes back. Raises ``ArtifactStoreError`` if absent."""
        ...

    def exists(self, content_hash: str) -> bool: ...

    def list_staged(self) -> tuple[str, ...]:
        """Staging ids still present — the sweep for blobs orphaned by a hard crash.

        A process killed between ``stage`` and ``promote`` leaves a staged blob with no
        compensator running. Without this the only remedy is manual inspection of the store.
        """
        ...


__all__ = [
    "ArtifactStore",
    "ArtifactStoreError",
    "StagedBlob",
    "StagedBlobNotFound",
]
