"""The canonical read boundary for evidence units (§17.25, EVI-010).

WHY THIS EXISTS RATHER THAN A `SELECT` AT EACH CALL SITE.

A stored row is not evidence. It becomes evidence when it is rebuilt through ``EvidenceUnit``,
because that is where every invariant is re-checked:

    identity   recomputed from (artifact_id, structural_path, content_digest)
    digest     recomputed from the body
    witness    recomputed from the conformance fields
    rule 1     the declared bound conditions must be present in body + inherited context
    typing     a TABLE has table context, a FIGURE has figure context, neither has the other's

Hand a caller a raw row and none of that runs. A row that drifted -- a repair script, a partial
restore, a bad migration, a writer that bypassed the triggers -- reaches a scientific consumer
still looking like evidence. The M1-P1 e2e proved the *pattern* by rebuilding through the model
inline; this makes it a boundary, so "did that call site remember to revalidate" stops being a
question anyone has to ask per call site.

DELIBERATELY SMALL. This is a reader, not a repository layer: no caching, no unit of work, no
write path, no query builder. Writes still go through the ingestion pipeline and the migrations'
triggers, which is where they belong. Adding more here would expand the slice for no guarantee
that is not already held somewhere better.

WHAT IT DOES NOT DO. Enforce project scope. Presence is `EvidenceUnitOccurrence` (§17.25.1) and
the authority on it is the admission gate's resolver -- duplicating the check here would be a
second copy of a SEC-002 rule, which ADR-0012's whole shape exists to avoid. ``present_in`` is
offered as the query the gate's resolver is built from, not as an enforcement point.
"""

from __future__ import annotations

from typing import Any, Protocol

from lab_brain.core.models.enums import EvidenceUnitType
from lab_brain.core.models.evidence_unit import (
    EvidenceUnit,
    FigureContext,
    SegmenterProvenance,
    SourceLocator,
    TableContext,
)

#: Column order this reader selects and rebuilds from. One tuple, used by both the SELECT and the
#: constructor, so a column added to one cannot silently misalign the other.
_COLUMNS = (
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
    "created_at",
)


class _Connection(Protocol):
    """The slice of a psycopg connection this reader uses.

    Typed structurally so the module does not import psycopg: `AGT-007` requires the suite to be
    verifiable with no database, and a top-level driver import would break collection wherever
    psycopg is absent.
    """

    def execute(self, query: str, params: tuple[Any, ...] = ..., /) -> Any: ...


class EvidenceUnitReadError(RuntimeError):
    """A stored row could not be rebuilt as a valid EvidenceUnit.

    Raised rather than returned, and deliberately not caught anywhere in the read path: a row
    that fails revalidation is a corrupted scientific record, and the only safe response is to
    stop rather than hand back a partially trusted object.
    """


class PostgresEvidenceUnitReader:
    """Loads evidence units from PostgreSQL, always through the model."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def load(self, evidence_unit_id: str) -> EvidenceUnit | None:
        """One unit by identity, rebuilt and revalidated. ``None`` if no such row exists."""
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM evidence_units WHERE evidence_unit_id = %s",
            (evidence_unit_id,),
        ).fetchone()
        if row is None:
            return None
        return self._rebuild(row, evidence_unit_id)

    def load_for_project(self, project_id: str) -> tuple[EvidenceUnit, ...]:
        """Every unit present in one project, via the occurrence (§17.25.1).

        The join is the point: a unit is *in* a project because an occurrence says so, not
        because a column on the unit does -- ADR-0012 removed that column.
        """
        rows = self._connection.execute(
            f"SELECT {', '.join('u.' + name for name in _COLUMNS)} FROM evidence_units u "
            "JOIN evidence_unit_occurrences o USING (evidence_unit_id) "
            "WHERE o.project_id = %s ORDER BY u.structural_path",
            (project_id,),
        ).fetchall()
        return tuple(self._rebuild(row, row[0]) for row in rows)

    def present_in(self, evidence_unit_id: str, project_id: str) -> bool:
        """§17.25.1 presence. The query an admission gate's resolver is built from.

        Offered rather than enforced here -- see the module docstring. A reader that also decided
        access would be a second place SEC-002 is implemented.
        """
        return (
            self._connection.execute(
                "SELECT 1 FROM evidence_unit_occurrences "
                "WHERE evidence_unit_id = %s AND project_id = %s",
                (evidence_unit_id, project_id),
            ).fetchone()
            is not None
        )

    # -- rebuilding ---------------------------------------------------------

    def _rebuild(self, row: tuple[Any, ...], evidence_unit_id: str) -> EvidenceUnit:
        values = dict(zip(_COLUMNS, row, strict=True))
        try:
            return EvidenceUnit(
                evidence_unit_id=values["evidence_unit_id"],
                artifact_id=values["artifact_id"],
                source_work_id=values["source_work_id"],
                unit_type=EvidenceUnitType(values["unit_type"]),
                structural_path=values["structural_path"],
                locator=SourceLocator.model_validate(values["locator"]),
                body=values["body"],
                content_digest=values["content_digest"],
                parent_unit_id=values["parent_unit_id"],
                subdivision_index=values["subdivision_index"],
                subdivision_reason=values["subdivision_reason"],
                inherited_context=tuple(values["inherited_context"] or ()),
                conditions=values["conditions"] or {},
                conditions_schema_version=values["conditions_schema_version"],
                bound_condition_texts=tuple(values["bound_condition_texts"] or ()),
                segmentation_witness=values["segmentation_witness"],
                table_context=(
                    TableContext.model_validate(values["table_context"])
                    if values["table_context"]
                    else None
                ),
                figure_context=(
                    FigureContext.model_validate(values["figure_context"])
                    if values["figure_context"]
                    else None
                ),
                provenance=SegmenterProvenance(
                    parser_id=values["parser_id"],
                    parser_version=values["parser_version"],
                    segmenter_id=values["segmenter_id"],
                    segmenter_version=values["segmenter_version"],
                    segmented_at=values["segmented_at"],
                    token_limit=values["token_limit"],
                ),
                created_at=values["created_at"],
            )
        except Exception as exc:
            # The row exists and is not a valid evidence unit. Naming the id is what makes this
            # actionable; swallowing it and returning None would report the corruption as absence.
            raise EvidenceUnitReadError(
                f"stored row for evidence unit {evidence_unit_id} does not revalidate as an "
                f"EvidenceUnit: {exc}. The row has drifted from what it claims to be, and is "
                "refused rather than returned as evidence (§17.25, EVI-010)"
            ) from exc


__all__ = ["EvidenceUnitReadError", "PostgresEvidenceUnitReader"]
