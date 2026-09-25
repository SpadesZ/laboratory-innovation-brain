"""PostgreSQL storage for EvidenceBundles (EVI-006, §17.14.1) -- the half `004a` had no reader for.

M0a built `evidence_bundles` and `evidence_bundle_members`, and every test that needed a bundle row
wrote it with raw SQL: nothing in the shipped package could store one. M3 is the first milestone
whose roles *produce* bundles -- a primary retrieval per position, and the Critic's inverted
retrieval -- and SRC-002 requires the inverted one to be SAVED ("保存 inverted EvidenceBundle"). So
this implements the existing `EvidenceBundleRepository` protocol rather than a second contract.

EVERY READ RECOMPUTES THE HASH. The protocol says a load "MUST verify the stored hash against a
freshly computed one", and it is the only thing that makes a stored hash evidence rather than a
label: a bundle whose members were altered by a repair script would otherwise be handed back under
the identity of the retrieval it no longer is.
"""

from __future__ import annotations

import json
from typing import Any

from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import DuplicateIdentityError, RepositoryError

_COLUMNS = (
    "bundle_id",
    "schema_version",
    "research_intent",
    "stakes",
    "query_text",
    "query_hash",
    "source_policy_id",
    "source_policy_version",
    "condition_filter",
    "condition_schema_versions",
    "source_snapshot_refs",
    "retrieval_trace_id",
    "project_id",
    "created_at",
    "canonical_hash",
)


class SqlEvidenceBundleRepository:
    """`EvidenceBundleRepository` over `004a`. Bundle and members in one transaction."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add(self, bundle: EvidenceBundle) -> EvidenceBundle:
        existing = self.get(bundle.bundle_id)
        if existing is not None:
            if existing.canonical_hash != bundle.canonical_hash:
                raise DuplicateIdentityError(
                    f"bundle_id {bundle.bundle_id} already stored with a different canonical_hash "
                    f"({existing.canonical_hash} vs {bundle.canonical_hash})"
                )
            return existing
        transaction = getattr(self._connection, "transaction", None)
        if transaction is None:  # pragma: no cover - every production connection has one
            raise RepositoryError("the bundle repository needs a transactional connection")
        with transaction():
            self._connection.execute(
                f"INSERT INTO evidence_bundles ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join(['%s'] * len(_COLUMNS))})",
                (
                    bundle.bundle_id,
                    bundle.schema_version,
                    bundle.research_intent.intent,
                    bundle.research_intent.stakes,
                    bundle.query_text,
                    bundle.query_hash,
                    bundle.source_policy_id,
                    bundle.source_policy_version,
                    json.dumps(bundle.condition_filter),
                    json.dumps(bundle.condition_schema_versions),
                    list(bundle.source_snapshot_refs),
                    bundle.retrieval_trace_id,
                    bundle.project_id,
                    bundle.created_at,
                    bundle.canonical_hash,
                ),
            )
            for position, attestation_id in enumerate(bundle.ordered_attestation_ids):
                self._connection.execute(
                    "INSERT INTO evidence_bundle_members (bundle_id, position, attestation_id) "
                    "VALUES (%s, %s, %s)",
                    (bundle.bundle_id, position, attestation_id),
                )
        stored = self.get(bundle.bundle_id)
        if stored is None or stored.canonical_hash != bundle.canonical_hash:
            raise RepositoryError(f"bundle {bundle.bundle_id} did not round-trip to its hash")
        return stored

    def get(self, bundle_id: str) -> EvidenceBundle | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM evidence_bundles WHERE bundle_id = %s",
            (bundle_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def find_by_hash(self, canonical_hash: str) -> tuple[EvidenceBundle, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM evidence_bundles WHERE canonical_hash = %s "
            "ORDER BY created_at, bundle_id",
            (canonical_hash,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def list_for_project(self, project_id: str) -> tuple[EvidenceBundle, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM evidence_bundles WHERE project_id = %s "
            "ORDER BY created_at, bundle_id",
            (project_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def _from_row(self, row: tuple[object, ...]) -> EvidenceBundle:
        values: dict[str, Any] = dict(zip(_COLUMNS, row, strict=True))
        stored_hash = values.pop("canonical_hash")
        values.pop("query_hash")
        members = self._connection.execute(
            "SELECT attestation_id FROM evidence_bundle_members WHERE bundle_id = %s "
            "ORDER BY position",
            (values["bundle_id"],),
        ).fetchall()
        bundle = EvidenceBundle(
            bundle_id=values["bundle_id"],
            schema_version=values["schema_version"],
            research_intent=ResearchIntent(
                intent=values["research_intent"], stakes=values["stakes"]
            ),
            query_text=values["query_text"],
            source_policy_id=values["source_policy_id"],
            source_policy_version=values["source_policy_version"],
            condition_filter=values["condition_filter"],
            condition_schema_versions=values["condition_schema_versions"],
            ordered_attestation_ids=tuple(str(m[0]) for m in members),
            source_snapshot_refs=tuple(values["source_snapshot_refs"]),
            retrieval_trace_id=values["retrieval_trace_id"],
            project_id=values["project_id"],
            created_at=values["created_at"],
        )
        if bundle.canonical_hash != stored_hash:
            raise RepositoryError(
                f"bundle {bundle.bundle_id} is stored under hash {stored_hash} but its content "
                f"hashes to {bundle.canonical_hash}; provenance citing it is unverifiable (EVI-006)"
            )
        return bundle


__all__ = ["SqlEvidenceBundleRepository"]
