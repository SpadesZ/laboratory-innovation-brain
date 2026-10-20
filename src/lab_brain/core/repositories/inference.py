"""Durable storage for scientific inference provenance (LLM-001, §17.14, §7.6).

WHAT "PERSIST" HAS TO MEAN. The M1 exit gate says *all scientific LLM calls persist
bundle+provenance*. An implementation that builds an `InferenceProvenance` and returns it has
persisted nothing; the claim only becomes true when the record survives the process that made it.
So the contract here is write-then-reload, and the test that matters opens a **new connection**
and asserts exact model equality.

WHY THE STORE ALSO HOLDS THE OUTPUT TEXT. §17.14 describes the provenance of an object rather
than the object, and it is tempting to store only the provenance. But §7.6's read-side rule asks
whether a *stored inference* may found a belief transition, and an answer with no record of what
the inference said cannot be reviewed by the human the rule sends it to. At M1 every scientific
output is text; a typed object reference belongs with the slice that introduces typed outputs.

APPEND-ONLY IS ENFORCED BY `003d`, not here. A repository-level check would hold for callers who
come through the repository.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from lab_brain.cognition.llm import ScientificOutput
from lab_brain.core.models.inference import InferenceProvenance
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class InferenceStoreError(RepositoryError):
    """A provenance write or read violated an invariant."""


@runtime_checkable
class InferenceProvenanceStore(Protocol):
    """The durable boundary for §17.14 records."""

    def record(self, output: ScientificOutput, *, project_id: str) -> InferenceProvenance: ...

    def get(self, inference_id: str) -> InferenceProvenance | None: ...

    def output_for(self, inference_id: str) -> str | None: ...

    def list_for_bundle(self, evidence_bundle_hash: str) -> tuple[InferenceProvenance, ...]: ...


_COLUMNS = (
    "inference_id",
    "role",
    "logical_slot",
    "provider",
    "model_id",
    "model_version",
    "prompt_id",
    "prompt_version",
    "evidence_bundle_hash",
    "source_policy_version",
    "parameters",
    "created_at",
    "trace_id",
)


class InMemoryInferenceProvenanceStore:
    """Backend-free implementation, for the same reason every other store has one.

    Append-only here too: a store that allowed overwriting in memory and not in PostgreSQL would
    let a backend-free test prove a property the real system does not have -- which is the exact
    shape of divergence the shared Job suite caught three times.
    """

    def __init__(self) -> None:
        self._records: dict[str, InferenceProvenance] = {}
        self._outputs: dict[str, str] = {}

    def record(self, output: ScientificOutput, *, project_id: str) -> InferenceProvenance:
        provenance = output.provenance
        existing = self._records.get(provenance.inference_id)
        if existing is not None:
            if existing != provenance:
                raise InferenceStoreError(
                    f"inference {provenance.inference_id} is already recorded with different "
                    "provenance; §7.6 judges belief admissibility against this row, so a record "
                    "that can be rewritten is one that can be made to claim a model it did not "
                    "come from"
                )
            return existing
        self._records[provenance.inference_id] = provenance
        self._outputs[provenance.inference_id] = output.text
        return provenance

    def get(self, inference_id: str) -> InferenceProvenance | None:
        return self._records.get(inference_id)

    def output_for(self, inference_id: str) -> str | None:
        return self._outputs.get(inference_id)

    def list_for_bundle(self, evidence_bundle_hash: str) -> tuple[InferenceProvenance, ...]:
        return tuple(
            sorted(
                (
                    p
                    for p in self._records.values()
                    if p.evidence_bundle_hash == evidence_bundle_hash
                ),
                key=lambda p: (p.created_at, p.inference_id),
            )
        )


class SqlInferenceProvenanceStore:
    """PostgreSQL implementation. Reads rebuild through the model.

    A row that drifted -- a repair script, a partial restore -- would otherwise be handed back as
    provenance, and §7.6 would then judge a belief transition against a record that never
    validated. Same boundary reasoning as `PostgresEvidenceUnitReader`.
    """

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def record(self, output: ScientificOutput, *, project_id: str) -> InferenceProvenance:
        """Write the provenance and the output it describes.

        `ON CONFLICT DO NOTHING` on the primary key: a retried write of the SAME inference is a
        no-op, and a DIFFERENT provenance under an existing id is refused by re-reading and
        comparing rather than by silently winning. `003d`'s append-only trigger makes an UPDATE
        impossible regardless of what this method does.
        """
        p = output.provenance
        self._connection.execute(
            f"INSERT INTO inference_provenance ({', '.join(_COLUMNS)}, project_id, output_text) "
            f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}, %s, %s) "
            "ON CONFLICT (inference_id) DO NOTHING",
            (
                p.inference_id,
                p.role,
                p.logical_slot.value,
                p.provider,
                p.model_id,
                p.model_version,
                p.prompt_id,
                p.prompt_version,
                p.evidence_bundle_hash,
                p.source_policy_version,
                json.dumps(p.parameters),
                p.created_at,
                p.trace_id,
                project_id,
                output.text,
            ),
        )
        stored = self.get(p.inference_id)
        if stored is None:  # pragma: no cover - the insert either landed or conflicted
            raise InferenceStoreError(f"inference {p.inference_id} vanished after being written")
        if stored != p:
            raise InferenceStoreError(
                f"inference {p.inference_id} is already recorded with different provenance "
                f"(stored model {stored.model_ref}, submitted {p.model_ref}); §7.6 judges belief "
                "admissibility against this row"
            )
        return stored

    def get(self, inference_id: str) -> InferenceProvenance | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM inference_provenance WHERE inference_id = %s",
            (inference_id,),
        ).fetchone()
        return None if row is None else _from_row(row)

    def output_for(self, inference_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT output_text FROM inference_provenance WHERE inference_id = %s",
            (inference_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def list_for_bundle(self, evidence_bundle_hash: str) -> tuple[InferenceProvenance, ...]:
        """Every inference made over one canonical bundle.

        The query EVI-006's hash exists to make answerable: "which conclusions rest on this
        exact evidence set", which is what a contamination rollback (§6.18) needs to select on.
        """
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM inference_provenance "
            "WHERE evidence_bundle_hash = %s ORDER BY created_at, inference_id",
            (evidence_bundle_hash,),
        ).fetchall()
        return tuple(_from_row(row) for row in rows)


def _from_row(row: tuple[object, ...]) -> InferenceProvenance:
    values = dict(zip(_COLUMNS, row, strict=True))
    return InferenceProvenance.model_validate(values)


__all__ = [
    "InMemoryInferenceProvenanceStore",
    "InferenceProvenanceStore",
    "InferenceStoreError",
    "SqlInferenceProvenanceStore",
]
