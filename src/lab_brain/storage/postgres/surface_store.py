"""The production writer and reader for `012`'s surface tables (UX-001, UX-003, §17.22, §17.23).

WHAT WAS MISSING. `012` created `ingestion_items`, `ingestion_stage_results` and `error_records`
with their invariants, and the UX projections were tested against items a test constructed. So the
*projection* was proven and the *rows* were not: nothing in production wrote one, and
`lab-brain inbox` had nothing to read even if it had been wired.

THIS WRITES ROWS AND DERIVES EVERYTHING ELSE. The division is §17.22's, not a preference:

    written    what happened -- the item, its stage attempts, the errors those failures projected
    derived    what it means -- `ItemState`, computed by `derive_state` on every read

There is no `state` column to write to, so there is no code path here that could set one. A reader
that returned a stored state would be the second source of truth §17.22 forbids, and this module
could not produce one even by mistake.

DUPLICATE IS A RELATION BETWEEN ITEMS. Under ART-001 identical bytes are the same artifact, so
"this is a duplicate" cannot be a property of one row: it is *an earlier item in this project
already holds this artifact*. Derived on write from `ingestion_items` itself -- see `012a`, which
removed the column-level CHECK that made the correct value unrepresentable.

ERROR IDS ARE MINTED, NOT ACCEPTED. §17.23 wants `ERR-YYYYMMDD-NNNN`, stable and project-scoped,
because it is what a human quotes into a support channel. Minting it here keeps the format in one
place; a caller-supplied id would eventually be a UUID somebody pasted, and the requirement is
about what a person can read aloud.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from lab_brain.ingestion.pipeline import ErrorClass as StageErrorClass
from lab_brain.ingestion.pipeline import IngestionStage, StageResult, StageStatus
from lab_brain.surface.errors import ErrorClass, ErrorRecord
from lab_brain.surface.ingestion_item import IngestionItem

#: How many times a mint collision is retried before giving up. Two concurrent failures in one
#: project on one day can pick the same ordinal; the primary key refuses the second, and retrying
#: is correct because the next ordinal is now free. Bounded rather than looping: an unbounded
#: retry against a genuinely broken sequence is an outage that looks like a hang.
_MINT_ATTEMPTS = 8


class _Connection(Protocol):
    """The psycopg slice this module uses, structurally (AGT-007)."""

    def execute(self, query: str, params: tuple[Any, ...] = ..., /) -> Any: ...


class SurfaceStoreError(RuntimeError):
    """A surface row could not be written or did not round-trip."""


_ITEM_COLUMNS = (
    "item_id",
    "project_id",
    "actor_id",
    "trace_id",
    "raw_artifact_id",
    "source_kind",
    "display_name",
    "submitted_at",
    "duplicate_of_artifact_id",
    "duplicate_of_source_work_id",
    "last_updated_at",
)

_ERROR_COLUMNS = (
    "error_id",
    "project_id",
    "trace_id",
    "job_id",
    "span_id",
    "item_id",
    "error_class",
    "reason_code",
    "component",
    "occurred_at",
    "attempt_count",
    "max_attempts",
    "next_retry_at",
    "technical_detail_ref",
    "resolved_at",
)


class PostgresSurfaceStore:
    """`012`'s three tables. Writes what happened; never writes what it means."""

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    # -- writes -------------------------------------------------------------

    def record_item(
        self,
        *,
        item_id: str,
        project_id: str,
        actor_id: str,
        trace_id: str,
        raw_artifact_id: str | None,
        source_kind: str,
        display_name: str,
        submitted_at: dt.datetime,
        duplicate_of_source_work_id: str | None = None,
    ) -> str | None:
        """Insert the inbox row. Returns the artifact it duplicates, if any.

        `ON CONFLICT DO UPDATE` on `last_updated_at` only. A re-ingestion under the same item is
        the same item and must not silently acquire a different actor, trace or artifact -- those
        would be a different ingestion wearing an existing id, and the inbox would show one row
        for two events.

        DUPLICATE IS RESOLVED BEFORE THE INSERT, against the other items in this project. Doing it
        after would make the first item of a pair a duplicate of the second on a re-read, since
        both would then exist.
        """
        duplicate_of = self._earlier_holder(
            project_id=project_id, artifact_id=raw_artifact_id, item_id=item_id
        )
        self._connection.execute(
            f"INSERT INTO ingestion_items ({', '.join(_ITEM_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_ITEM_COLUMNS))}) "
            "ON CONFLICT (item_id) DO UPDATE SET last_updated_at = EXCLUDED.last_updated_at",
            (
                item_id,
                project_id,
                actor_id,
                trace_id,
                raw_artifact_id,
                source_kind,
                display_name,
                submitted_at,
                duplicate_of,
                duplicate_of_source_work_id,
                submitted_at,
            ),
        )
        return duplicate_of

    def _earlier_holder(
        self, *, project_id: str, artifact_id: str | None, item_id: str
    ) -> str | None:
        """The artifact id, when an earlier item in this project already holds it.

        Returns the artifact rather than the other item's id because §17.22's field is
        `duplicate_of_artifact_id` -- and under ART-001 that is the same id this item carries,
        which is the point `012a` exists to record.
        """
        if artifact_id is None:
            return None
        row = self._connection.execute(
            "SELECT 1 FROM ingestion_items WHERE project_id = %s AND raw_artifact_id = %s "
            "AND item_id <> %s LIMIT 1",
            (project_id, artifact_id, item_id),
        ).fetchone()
        return artifact_id if row is not None else None

    def record_stage_results(
        self,
        item_id: str,
        results: tuple[StageResult, ...],
        *,
        job_id: str | None = None,
        error_ids: dict[str, str] | None = None,
    ) -> None:
        """One row per stage attempt.

        THE ATTEMPT NUMBER IS DERIVED FROM WHAT IS ALREADY STORED, not from the caller. UX-004's
        retry re-runs a stage, and a retry that reused attempt 1 would overwrite the record of the
        failure it is retrying -- which is the history PARTIAL and FAILED are derived from.
        """
        by_reason = error_ids or {}
        for result in results:
            attempt = self._next_attempt(item_id, result.stage)
            self._connection.execute(
                "INSERT INTO ingestion_stage_results (item_id, stage, attempt, status, job_id, "
                "error_id, reason_code, error_class, output_refs, started_at, finished_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    item_id,
                    result.stage.value,
                    attempt,
                    result.status.value,
                    job_id,
                    by_reason.get(result.reason_code or ""),
                    result.reason_code,
                    None if result.error_class is None else result.error_class.value,
                    list(result.output_refs),
                    result.started_at,
                    result.finished_at,
                ),
            )

    def _next_attempt(self, item_id: str, stage: IngestionStage) -> int:
        row = self._connection.execute(
            "SELECT coalesce(max(attempt), 0) + 1 FROM ingestion_stage_results "
            "WHERE item_id = %s AND stage = %s",
            (item_id, stage.value),
        ).fetchone()
        return 1 if row is None else int(row[0])

    def record_error(
        self,
        *,
        project_id: str,
        trace_id: str,
        error_class: ErrorClass,
        reason_code: str,
        component: str,
        occurred_at: dt.datetime,
        item_id: str | None = None,
        job_id: str | None = None,
        span_id: str | None = None,
        attempt_count: int = 0,
        max_attempts: int = 1,
        next_retry_at: dt.datetime | None = None,
        technical_detail_ref: str | None = None,
    ) -> ErrorRecord:
        """Project one failure into §17.23's user-layer record and return it.

        NOT A SECOND SOURCE OF TRUTH, which §17.23 says outright: nothing here is authoritative
        about the failure, and the row exists so a human has a stable reference to quote. The
        classification is carried rather than re-derived, because the class decides who acts and
        the component that failed is the one that knows.

        `next_retry_at` on an unretryable class is refused by `012`'s CHECK rather than by this
        method. That is deliberate: a writer-side check holds for writers that come through this
        writer.
        """
        last: Exception | None = None
        for _ in range(_MINT_ATTEMPTS):
            error_id = self._mint_error_id(occurred_at)
            try:
                self._connection.execute(
                    f"INSERT INTO error_records ({', '.join(_ERROR_COLUMNS)}) "
                    f"VALUES ({', '.join(['%s'] * len(_ERROR_COLUMNS))})",
                    (
                        error_id,
                        project_id,
                        trace_id,
                        job_id,
                        span_id,
                        item_id,
                        error_class.value,
                        reason_code,
                        component,
                        occurred_at,
                        attempt_count,
                        max_attempts,
                        next_retry_at,
                        technical_detail_ref,
                        None,
                    ),
                )
            except Exception as exc:
                last = exc
                continue
            stored = self.error(error_id)
            if stored is None:  # pragma: no cover - the insert either landed or raised
                raise SurfaceStoreError(f"error {error_id} vanished after being written")
            return stored
        raise SurfaceStoreError(
            f"could not mint an error id for {project_id} after {_MINT_ATTEMPTS} attempts "
            f"({last}). UX-003 lets a user quote this reference, so reusing one would point two "
            "different failures at the same explanation"
        )

    def _mint_error_id(self, occurred_at: dt.datetime) -> str:
        """`ERR-YYYYMMDD-NNNN`, the next free ordinal for that day.

        Global rather than per-project despite the id being described as project-scoped: the
        column is the primary key, so two projects sharing an ordinal on the same day would
        collide. Scoped *lookup* is what §17.24 requires and `DiagnosticsService` enforces -- an
        id from another project returns not-found, which is a property of the read and not of the
        numbering.
        """
        day = occurred_at.strftime("%Y%m%d")
        row = self._connection.execute(
            "SELECT coalesce(max(substring(error_id from 14)::int), 0) + 1 FROM error_records "
            "WHERE error_id LIKE %s",
            (f"ERR-{day}-%",),
        ).fetchone()
        ordinal = 1 if row is None else int(row[0])
        return f"ERR-{day}-{ordinal:04d}"

    # -- reads --------------------------------------------------------------

    def items_for_project(self, project_id: str) -> tuple[IngestionItem, ...]:
        """Every inbox row in one project, with its stage results and error references.

        NO STATE COMES BACK, because none is stored. The caller runs `derive_state`, which is the
        same function the contract tests exercise -- so the terminal and the service cannot
        disagree about what a row means.

        `review_ids` and `conflict_ids` are empty here and that is a real gap rather than an
        omission: §17.19.1's `subject_type` vocabulary is CONFLICT | AUTHORITY_CONFLICT, so a
        ReviewItem cannot currently point at an IngestionItem, and no durable row exists to read.
        Inventing a subject type to fill the field would be a spec change smuggled in as a query.
        """
        rows = self._connection.execute(
            f"SELECT {', '.join(_ITEM_COLUMNS)} FROM ingestion_items "
            "WHERE project_id = %s ORDER BY submitted_at, item_id",
            (project_id,),
        ).fetchall()
        return tuple(self._hydrate_item(row) for row in rows)

    def _hydrate_item(self, row: tuple[Any, ...]) -> IngestionItem:
        values = dict(zip(_ITEM_COLUMNS, row, strict=True))
        item_id = str(values["item_id"])
        return IngestionItem(
            item_id=item_id,
            project_id=str(values["project_id"]),
            actor_id=str(values["actor_id"]),
            trace_id=str(values["trace_id"]),
            raw_artifact_id=values["raw_artifact_id"],
            source_kind=str(values["source_kind"]),
            display_name=str(values["display_name"]),
            submitted_at=values["submitted_at"],
            stage_results=self._stage_results(item_id),
            duplicate_of_artifact_id=values["duplicate_of_artifact_id"],
            duplicate_of_source_work_id=values["duplicate_of_source_work_id"],
            error_ids=self._error_ids(item_id),
            job_ids=self._job_ids(item_id),
            last_updated_at=values["last_updated_at"],
        )

    def _stage_results(self, item_id: str) -> tuple[StageResult, ...]:
        """The stored attempts, newest attempt per stage.

        The projection asks "did this stage succeed", and the answer is the latest attempt: a
        retry that fixed a parse must not leave the item FAILED because attempt 1 is still on
        record. The earlier attempts stay in the table -- they are the history UX-004 needs -- and
        are simply not what the current state derives from.
        """
        rows = self._connection.execute(
            "SELECT DISTINCT ON (stage) stage, status, reason_code, error_class, output_refs, "
            "started_at, finished_at FROM ingestion_stage_results WHERE item_id = %s "
            "ORDER BY stage, attempt DESC",
            (item_id,),
        ).fetchall()
        return tuple(
            StageResult(
                stage=IngestionStage(str(row[0])),
                status=StageStatus(str(row[1])),
                reason_code=row[2],
                # `StageErrorClass` is the pipeline's copy of §17.23's five names. The alias keeps
                # the two visibly distinct: this is what a *stage* emitted, and
                # `surface.errors.ErrorClass` is what an §17.23 record carries.
                error_class=None if row[3] is None else StageErrorClass(str(row[3])),
                output_refs=tuple(row[4] or ()),
                started_at=row[5],
                finished_at=row[6],
            )
            for row in rows
        )

    def _error_ids(self, item_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT error_id FROM error_records WHERE item_id = %s ORDER BY occurred_at, error_id",
            (item_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _job_ids(self, item_id: str) -> tuple[str, ...]:
        """Which jobs touched this item, by query. §17.8's rule again: no parallel array."""
        rows = self._connection.execute(
            "SELECT DISTINCT job_id FROM ingestion_stage_results "
            "WHERE item_id = %s AND job_id IS NOT NULL ORDER BY job_id",
            (item_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def error(self, error_id: str) -> ErrorRecord | None:
        """One error by id, UNSCOPED.

        Deliberately not project-scoped: §17.24's scoping is `DiagnosticsService`'s, which checks
        membership *before* the lookup and returns the same not-found for a foreign id as for a
        nonexistent one. A scoped read here would answer a different question and the service
        would have two places to get the oracle wrong.
        """
        row = self._connection.execute(
            f"SELECT {', '.join(_ERROR_COLUMNS)} FROM error_records WHERE error_id = %s",
            (error_id,),
        ).fetchone()
        if row is None:
            return None
        values = dict(zip(_ERROR_COLUMNS, row, strict=True))
        return ErrorRecord(
            error_id=str(values["error_id"]),
            project_id=str(values["project_id"]),
            trace_id=str(values["trace_id"]),
            error_class=ErrorClass(str(values["error_class"])),
            reason_code=str(values["reason_code"]),
            component=str(values["component"]),
            occurred_at=values["occurred_at"],
            attempt_count=int(values["attempt_count"]),
            max_attempts=int(values["max_attempts"]),
            next_retry_at=values["next_retry_at"],
            job_id=values["job_id"],
            span_id=values["span_id"],
            item_id=values["item_id"],
            technical_detail_ref=values["technical_detail_ref"],
            resolved_at=values["resolved_at"],
        )


__all__ = ["PostgresSurfaceStore", "SurfaceStoreError"]
