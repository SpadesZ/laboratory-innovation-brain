"""The production write side for artifacts and evidence units (ART-001, EVI-010, ADR-0010/0012).

WHAT GAP THIS CLOSES, STATED PRECISELY.

M1-P1 shipped with a recorded P2 limitation: *there is no production repository contract on the
write side*. `IngestionPipeline` takes `commit_rows` as an injected callable -- OPS-004 needed
the fault-injection point to be a parameter -- and the only implementations were test helpers.
What was proven was that the pipeline is idempotent and the schema accepts its output. What was
**not** proven was that a production writer exists which does this correctly.

This is that writer. It is the smallest thing that closes the gap, because OPS-001's resume path
is the first caller that genuinely needs one: a Job that resumes an ingestion has to persist from
production code, and a test helper cannot be that.

WHY THE CONFLICT CLAUSES ARE NOT A "HAVE I SEEN THIS" CHECK.

Every `ON CONFLICT DO NOTHING` here is targeted at a **derived** identity:

    artifacts                 (artifact_id)         = f(content bytes)
    artifact_occurrences      (artifact_id, project_id)
    evidence_units            (evidence_unit_id)    = f(artifact_id, structural_path, digest)
    evidence_unit_occurrences (evidence_unit_id, project_id)

A second write of the same bytes computes the same ids and therefore asserts a row that already
exists and is *identical*. Skipping it is not deduplication; it is the absence of a change. This
matters because the alternative -- `if already_seen(bytes): return` -- is explicitly locked out:
it moves the decision from the identity to a lookup, and a lookup can be wrong, stale, or racing.
The distinction is the same one `006_jobs_runs.sql` draws between storage idempotency and
callback idempotency, and the two must not be confused.

A *changed* boundary set at the same structural path produces a different `evidence_unit_id` and
hits `003a`'s unique path index instead -- the loud failure ADR-0012 wants for an attempted
re-segmentation. That path is deliberately not softened here.

NOT A REPOSITORY FRAMEWORK. No unit of work, no identity map, no query builder, no lazy loading.
Reads live in `PostgresEvidenceUnitReader`, which is locked. This writes four tables and nothing
else, and the guardrails it relies on are in the migrations where every other writer meets them
too.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.evidence_unit import EvidenceUnit, EvidenceUnitOccurrence


class _Connection(Protocol):
    """The slice of a psycopg connection this writer uses.

    Structural for the reason `PostgresEvidenceUnitReader` gives: AGT-007 requires the suite to be
    verifiable with no database, and a top-level driver import would break collection wherever
    psycopg is absent.
    """

    def execute(self, query: str, params: tuple[Any, ...] = ..., /) -> Any: ...


class IngestionWriteError(RuntimeError):
    """A write was refused. Raised rather than returned -- see `EvidenceUnitReadError`."""


_ARTIFACT_COLUMNS = (
    "artifact_id",
    "content_hash",
    "media_type",
    "uri",
    "lineage_id",
    "lineage_revision",
    "previous_artifact_id",
    "source_origin",
    "created_at",
    "captured_at",
    "author_or_device",
    "actor_id",
    "parser_version",
    "derived_from_artifact_ids",
    "rights_metadata",
    "secret_scan_status",
    "metadata",
)

_UNIT_COLUMNS = (
    "evidence_unit_id",
    "artifact_id",
    "source_work_id",
    "unit_type",
    "structural_path",
    "locator",
    "body",
    "content_digest",
    "parent_unit_id",
    "subdivision_index",
    "subdivision_reason",
    "inherited_context",
    "conditions",
    "conditions_schema_version",
    "bound_condition_texts",
    "segmentation_witness",
    "table_context",
    "figure_context",
    "parser_id",
    "parser_version",
    "segmenter_id",
    "segmenter_version",
    "segmented_at",
    "token_limit",
)


class PostgresIngestionWriter:
    """Writes an ingestion's output. Idempotent by derived identity, never by lookup."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    # -- artifacts ----------------------------------------------------------

    def write_artifact(self, artifact: Artifact) -> None:
        """Store the bytes' record.

        `ON CONFLICT (artifact_id) DO NOTHING` and not `DO UPDATE`: `artifacts_id_is_content_
        addressed` means an equal id implies equal bytes, so there is nothing an update could
        legitimately change. A writer that *did* update would be able to rewrite provenance --
        `actor_id`, `source_origin`, `secret_scan_status` -- for bytes somebody else ingested.
        """
        self._connection.execute(
            f"INSERT INTO artifacts ({', '.join(_ARTIFACT_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_ARTIFACT_COLUMNS))}) "
            "ON CONFLICT (artifact_id) DO NOTHING",
            (
                artifact.artifact_id,
                artifact.content_hash,
                artifact.media_type,
                artifact.uri,
                artifact.lineage_id,
                artifact.lineage_revision,
                artifact.previous_artifact_id,
                artifact.source_origin.value,
                artifact.created_at,
                artifact.captured_at,
                artifact.author_or_device,
                artifact.actor_id,
                artifact.parser_version,
                list(artifact.derived_from_artifact_ids),
                (
                    artifact.rights_metadata.model_dump_json()
                    if artifact.rights_metadata is not None
                    else None
                ),
                artifact.secret_scan_status.value,
                json.dumps(artifact.metadata),
            ),
        )

    def write_artifact_occurrence(self, occurrence: ArtifactOccurrence) -> None:
        """Place the artifact in a project (ADR-0010).

        `DO NOTHING` rather than `DO UPDATE` on the label, and this one is a security decision
        rather than a convenience: re-ingesting a document must not be able to *relabel* it. A
        second ingest under `PUBLIC` of bytes a project already holds as `RESTRICTED_NDA` would
        otherwise downgrade the classification with no approval and no audit record, which is
        exactly what §17.15's "explicit authorized action is required to lower classification"
        forbids. Reclassification is R-9's problem and needs an event, not an upsert.
        """
        self._connection.execute(
            "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label, "
            "ingested_by_actor_id, ingested_at) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (artifact_id, project_id) DO NOTHING",
            (
                occurrence.artifact_id,
                occurrence.project_id,
                occurrence.sensitivity_label.value,
                occurrence.ingested_by_actor_id,
                occurrence.ingested_at,
            ),
        )

    # -- evidence -----------------------------------------------------------

    def write_evidence_unit(self, unit: EvidenceUnit) -> None:
        """Store one canonical evidence unit.

        The conflict target is the derived primary key, which is what ADR-0011's derived identity
        buys: unchanged bytes re-segmented by the same recorded implementation produce the same
        id, so the second write is the absence of a change. A *different* boundary set at the
        same `structural_path` produces a different id and hits `003a`'s unique path index --
        left to fail loudly, because ADR-0012 makes re-segmentation unrepresentable on purpose.
        """
        self._connection.execute(
            f"INSERT INTO evidence_units ({', '.join(_UNIT_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_UNIT_COLUMNS))}) "
            "ON CONFLICT (evidence_unit_id) DO NOTHING",
            (
                unit.evidence_unit_id,
                unit.artifact_id,
                unit.source_work_id,
                unit.unit_type.value,
                unit.structural_path,
                unit.locator.model_dump_json(),
                unit.body,
                unit.content_digest,
                unit.parent_unit_id,
                unit.subdivision_index,
                unit.subdivision_reason.value if unit.subdivision_reason else None,
                list(unit.inherited_context),
                json.dumps(unit.conditions),
                unit.conditions_schema_version,
                list(unit.bound_condition_texts),
                unit.segmentation_witness,
                unit.table_context.model_dump_json() if unit.table_context else None,
                unit.figure_context.model_dump_json() if unit.figure_context else None,
                unit.provenance.parser_id,
                unit.provenance.parser_version,
                unit.provenance.segmenter_id,
                unit.provenance.segmenter_version,
                unit.provenance.segmented_at,
                unit.provenance.token_limit,
            ),
        )

    def write_evidence_occurrence(self, occurrence: EvidenceUnitOccurrence) -> None:
        """Record that this project holds this evidence (§17.25.1)."""
        self._connection.execute(
            "INSERT INTO evidence_unit_occurrences (evidence_unit_id, project_id, artifact_id, "
            "ingested_by_actor_id, first_seen_at) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (evidence_unit_id, project_id) DO NOTHING",
            (
                occurrence.evidence_unit_id,
                occurrence.project_id,
                occurrence.artifact_id,
                occurrence.ingested_by_actor_id,
                occurrence.first_seen_at,
            ),
        )

    # -- the pipeline seam --------------------------------------------------

    def commit_rows(self, artifact: Artifact, occurrence: ArtifactOccurrence) -> None:
        """The callable `IngestionPipeline` takes as ``commit_rows``.

        Bound as a method rather than passed as a closure so that the production wiring is a
        named object a test can assert on. OPS-004's compensation still owns the artifact-store
        side; this is only the database half of that unit of work, and it is deliberately not
        responsible for deciding whether to compensate.
        """
        self.write_artifact(artifact)
        self.write_artifact_occurrence(occurrence)

    def persist_evidence(
        self,
        units: tuple[EvidenceUnit, ...],
        occurrences: tuple[EvidenceUnitOccurrence, ...],
    ) -> None:
        """Units before occurrences: an occurrence's foreign key names the unit."""
        for unit in units:
            self.write_evidence_unit(unit)
        for occurrence in occurrences:
            self.write_evidence_occurrence(occurrence)


__all__ = ["IngestionWriteError", "PostgresIngestionWriter"]
