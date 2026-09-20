"""Local-filesystem artifact store, and an in-memory one for the backend-free suite.

Both implement the same ``ArtifactStore`` protocol and the same staging discipline, for the
reason ``InMemory*Repository`` gives: a fake that accepts what the real store rejects makes a
green suite meaningless. In particular both make ``discard`` total -- removing a blob that is
already gone is a no-op, not an error -- because OPS-004's compensation is only a guarantee if the
compensating call cannot itself fail.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from lab_brain.core.models.identifiers import compute_content_hash, parse_content_hash
from lab_brain.storage.artifacts.interface import (
    ArtifactStoreError,
    StagedBlob,
    StagedBlobNotFound,
)


def _hash_to_relative_path(content_hash: str) -> Path:
    """``sha256:ab12...`` -> ``sha256/ab/12/ab12...``.

    Fanned out two levels: a flat directory of content hashes degrades badly on every filesystem
    once a lab has a few hundred thousand artifacts, and re-sharding later would change every
    stored URI.
    """
    algorithm, digest = parse_content_hash(content_hash)
    return Path(algorithm) / digest[:2] / digest[2:4] / digest


class LocalArtifactStore:
    """Content-addressed blobs under a root directory.

    Promotion is a rename within the same filesystem, which is atomic on POSIX and on NTFS. That
    matters: a promotion implemented as copy-then-delete has a window where both a partial target
    and the source exist, and a crash inside it produces exactly the half-written artifact the
    content hash is supposed to make impossible.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._staging = self._root / "_staging"
        self._objects = self._root / "objects"
        self._staging.mkdir(parents=True, exist_ok=True)
        self._objects.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def stage(self, data: bytes) -> StagedBlob:
        staging_id = f"stg:{uuid.uuid4()}"
        path = self._staging / staging_id.replace(":", "_")
        path.write_bytes(data)
        return StagedBlob(
            staging_id=staging_id,
            content_hash=compute_content_hash(data),
            size_bytes=len(data),
        )

    def _staging_path(self, staging_id: str) -> Path:
        return self._staging / staging_id.replace(":", "_")

    def promote(self, staging_id: str, content_hash: str) -> str:
        source = self._staging_path(staging_id)
        if not source.is_file():
            raise StagedBlobNotFound(
                f"no staged blob {staging_id!r}; it was already promoted, discarded, or never "
                "staged. Promotion must not silently create an empty artifact"
            )
        actual = compute_content_hash(source.read_bytes())
        if actual != content_hash:
            raise ArtifactStoreError(
                f"staged blob {staging_id!r} hashes to {actual}, not the {content_hash} it is "
                "being promoted as; the database row would name bytes this blob does not hold"
            )
        target = self._objects / _hash_to_relative_path(content_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # Same content hash means same bytes. The artifact is already stored; drop the
            # duplicate rather than rewriting it, and let the caller's row point at what is there.
            source.unlink(missing_ok=True)
            return target.as_uri()
        os.replace(source, target)
        return target.as_uri()

    def discard(self, staging_id: str) -> None:
        """Total and idempotent — see the protocol docstring."""
        self._staging_path(staging_id).unlink(missing_ok=True)

    def open(self, content_hash: str) -> bytes:
        path = self._objects / _hash_to_relative_path(content_hash)
        if not path.is_file():
            raise ArtifactStoreError(f"no stored artifact for {content_hash}")
        return path.read_bytes()

    def exists(self, content_hash: str) -> bool:
        return (self._objects / _hash_to_relative_path(content_hash)).is_file()

    def list_staged(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name.replace("_", ":", 1) for path in self._staging.iterdir() if path.is_file()
            )
        )

    def destroy(self) -> None:
        """Remove everything. Test teardown only; never called by the ingestion path."""
        shutil.rmtree(self._root, ignore_errors=True)


class InMemoryArtifactStore:
    """The same contract without a filesystem, for the backend-free suite (AGT-007)."""

    def __init__(self) -> None:
        self._staged: dict[str, bytes] = {}
        self._objects: dict[str, bytes] = {}
        #: Set by a test to make the next promote fail, so the compensating path is exercised by
        #: an actual failure rather than by calling the compensator directly. See OPS-004: "the
        #: compensating path MUST be verified by fault injection".
        self.fail_next_promote = False

    def stage(self, data: bytes) -> StagedBlob:
        staging_id = f"stg:{uuid.uuid4()}"
        self._staged[staging_id] = data
        return StagedBlob(
            staging_id=staging_id,
            content_hash=compute_content_hash(data),
            size_bytes=len(data),
        )

    def promote(self, staging_id: str, content_hash: str) -> str:
        if self.fail_next_promote:
            self.fail_next_promote = False
            raise ArtifactStoreError("injected promote failure (fault injection, OPS-004)")
        data = self._staged.get(staging_id)
        if data is None:
            raise StagedBlobNotFound(f"no staged blob {staging_id!r}")
        actual = compute_content_hash(data)
        if actual != content_hash:
            raise ArtifactStoreError(
                f"staged blob {staging_id!r} hashes to {actual}, not {content_hash}"
            )
        self._objects[content_hash] = data
        del self._staged[staging_id]
        return f"memory://{content_hash}"

    def discard(self, staging_id: str) -> None:
        self._staged.pop(staging_id, None)

    def open(self, content_hash: str) -> bytes:
        try:
            return self._objects[content_hash]
        except KeyError:
            raise ArtifactStoreError(f"no stored artifact for {content_hash}") from None

    def exists(self, content_hash: str) -> bool:
        return content_hash in self._objects

    def list_staged(self) -> tuple[str, ...]:
        return tuple(sorted(self._staged))


__all__ = ["InMemoryArtifactStore", "LocalArtifactStore"]
