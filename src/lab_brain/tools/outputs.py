"""Where a backend's raw output goes before the Run that cites it is minted (ART-001, EVI-009).

    §25.4    raw artifacts 被 hash 且在 parsing 前已 durably 保存.
    EVI-009  a SUCCEEDED run must trace to produced artifact(s).

M2's mock was handed the id of an artifact a test had inserted, so its Run cited bytes nobody had
produced. A verification result that confirms a root cause (EPI-002) cannot rest on that: the
artifact a Run names has to be the bytes the execution emitted. So a backend is handed a
`RunOutputSink`, writes its raw output through it, and puts the returned content-addressed id in
`BackendExecution.output_artifacts`. By the time `run_simulation` mints the Run, the bytes are
durable and hashed, and whatever reads the result later (a workflow classifying an outcome) reads
those stored bytes by id -- never the backend's in-flight object.

The protocol is two lines on purpose. Where the bytes live, how the artifact row and its project
occurrence are written, and how a failure between the two stores is compensated (OPS-004) belong to
the storage layer (`lab_brain.storage.postgres.run_outputs`); a backend knows none of it.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from lab_brain.core.models.identifiers import artifact_id_for


@runtime_checkable
class RunOutputSink(Protocol):
    def emit(self, *, project_id: str, media_type: str, data: bytes) -> str:
        """Store ``data`` durably as a RUN_OUTPUT artifact in ``project_id``; return its id."""
        ...

    def read(self, artifact_id: str) -> bytes:
        """The stored bytes of an artifact this sink (or ingestion) wrote. Raises if absent."""
        ...


class InMemoryRunOutputSink:
    """Content-addressed, per-process. For backend-free tests of the backends themselves."""

    def __init__(self) -> None:
        self._bytes: dict[str, bytes] = {}
        self._present: set[tuple[str, str]] = set()

    def emit(self, *, project_id: str, media_type: str, data: bytes) -> str:
        del media_type
        artifact_id = artifact_id_for("sha256:" + hashlib.sha256(data).hexdigest())
        self._bytes[artifact_id] = data
        self._present.add((artifact_id, project_id))
        return artifact_id

    def put(self, *, project_id: str, data: bytes) -> str:
        """Seed an input artifact (a device project) the way ingestion would have stored it."""
        return self.emit(project_id=project_id, media_type="application/json", data=data)

    def read(self, artifact_id: str) -> bytes:
        try:
            return self._bytes[artifact_id]
        except KeyError as missing:
            raise LookupError(f"no stored artifact {artifact_id}") from missing

    def present_in(self, artifact_id: str, project_id: str) -> bool:
        return (artifact_id, project_id) in self._present


__all__ = ["InMemoryRunOutputSink", "RunOutputSink"]
