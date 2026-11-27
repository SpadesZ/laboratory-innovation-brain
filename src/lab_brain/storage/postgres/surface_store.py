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

from lab_brain.core.models.conflict import UNRESOLVED_CONFLICT_STATUSES
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.review import OUTSTANDING_REVIEW_STATUSES
from lab_brain.ingestion.pipeline import ErrorClass as StageErrorClass
from lab_brain.ingestion.pipeline import IngestionStage, StageResult, StageStatus
from lab_brain.surface.disclosure import TechnicalDetail
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

    def record_technical_detail(
        self,
        *,
        detail_ref: str,
        project_id: str,
        sensitivity: SensitivityLabel,
        component: str,
        message: str,
        stack_ref: str | None = None,
        source_path: str | None = None,
        prompt_fragment: str | None = None,
    ) -> str:
        """§17.24's tier two, as a row of its own (`012b`).

        WRITTEN BEFORE THE ERROR RECORD THAT POINTS AT IT, inside the same transaction. `012b`'s
        trigger is deferred so either order is legal, but writing the target first means the
        common case never relies on the deferral -- and the deferral is there for the case where
        a writer genuinely cannot.

        `ON CONFLICT DO NOTHING` on the ref: a retried ingestion projects the same failure again
        and the row it asserts is the same row. Not deduplication -- the absence of a change.
        """
        self._connection.execute(
            "INSERT INTO technical_details (detail_ref, project_id, sensitivity, component, "
            "message, stack_ref, source_path, prompt_fragment) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (detail_ref) DO NOTHING",
            (
                detail_ref,
                project_id,
                sensitivity.value,
                component,
                message,
                stack_ref,
                source_path,
                prompt_fragment,
            ),
        )
        return detail_ref

    def technical_detail(self, detail_ref: str) -> TechnicalDetail | None:
        """Tier two by reference. UNSCOPED, deliberately.

        The scoping already happened: `DiagnosticsService` resolves the ErrorRecord against the
        actor's membership first, and only then reads `record.technical_detail_ref`. A second
        project filter here would be a second place to get §17.24's oracle rule wrong, and
        `012b`'s trigger already makes a cross-project reference unrepresentable rather than
        merely unreachable.
        """
        row = self._connection.execute(
            "SELECT detail_ref, sensitivity, component, message, stack_ref, source_path, "
            "prompt_fragment FROM technical_details WHERE detail_ref = %s",
            (detail_ref,),
        ).fetchone()
        if row is None:
            return None
        return TechnicalDetail(
            detail_ref=str(row[0]),
            sensitivity=SensitivityLabel(str(row[1])),
            component=str(row[2]),
            message=str(row[3]),
            stack_ref=row[4],
            source_path=row[5],
            prompt_fragment=row[6],
        )

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
        """Every inbox row in one project, with the references §17.22 derives state from.

        NO STATE COMES BACK, because none is stored. The caller runs `derive_state`, which is the
        same function the contract tests exercise -- so the terminal and the service cannot
        disagree about what a row means.

        `review_ids` AND `conflict_ids` ARE REAL. An earlier version of this docstring claimed
        §17.19.1's vocabulary was `CONFLICT | AUTHORITY_CONFLICT` so no ReviewItem could point at
        an item. That was stale and wrong the day it was written: `011h` added
        `EXTRACTION_UNCERTAINTY` for exactly this, and `enqueue_extraction_review` had already
        been writing those rows. NEEDS_REVIEW was unreachable from durable data because this
        reader never asked, not because the data could not exist -- which is the more dangerous
        kind of gap, since the limitation section said it was a schema constraint.
        """
        rows = self._connection.execute(
            f"SELECT {', '.join(_ITEM_COLUMNS)} FROM ingestion_items "
            "WHERE project_id = %s ORDER BY submitted_at, item_id",
            (project_id,),
        ).fetchall()
        return tuple(self._hydrate_item(row) for row in rows)

    def open_review_ids(self, project_id: str) -> frozenset[str]:
        """Reviews a human still owes an answer on (§17.19.1, UX-005).

        QUEUED and ASSIGNED only. An ASSIGNED review counts as open because somebody has picked
        it up and not answered -- the item is no more ready than it was. APPROVED, CORRECTED,
        REJECTED and EXPIRED are all answers, and an EXPIRED one is the answer `review_expire`
        wrote when nobody gave a better one; leaving the item NEEDS_REVIEW afterwards would park
        it forever on a review that no longer exists to be done.

        Read from the ONE queue. UX-005 prohibits a parallel review surface because ReviewQueue
        depth is what prices human attention in §14.4.1, and a second queue would consume the
        same reviewers while being invisible to the planner.
        """
        rows = self._connection.execute(
            "SELECT review_id FROM review_items WHERE project_id = %s AND status = ANY (%s)",
            (project_id, [status.value for status in sorted(OUTSTANDING_REVIEW_STATUSES)]),
        ).fetchall()
        return frozenset(str(row[0]) for row in rows)

    def blocking_conflict_ids(self, project_id: str) -> frozenset[str]:
        """Conflicts that are both BLOCKING and unresolved (§17.19.3).

        Both, and the conjunction matters. `blocking` is the domain's judgement that this kind of
        disagreement stops work; `resolution_status` is whether it still stands. A conflict that
        is blocking and RESOLVED holds nothing up, and one that is OPEN and non-blocking is a
        recorded disagreement the lab has decided to live with -- neither should make a document
        read as NEEDS_REVIEW.
        """
        rows = self._connection.execute(
            "SELECT conflict_id FROM conflicts WHERE project_id = %s AND blocking "
            "AND resolution_status = ANY (%s)",
            (project_id, [status.value for status in sorted(UNRESOLVED_CONFLICT_STATUSES)]),
        ).fetchall()
        return frozenset(str(row[0]) for row in rows)

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
            review_ids=self._review_ids(item_id, str(values["project_id"])),
            conflict_ids=self._conflict_ids(item_id, str(values["project_id"])),
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

    def _review_ids(self, item_id: str, project_id: str) -> tuple[str, ...]:
        """Every ReviewItem whose subject is this item (§17.22, UX-005, `011h`).

        `EXTRACTION_UNCERTAINTY` is the subject type `011h` added for exactly this, and
        `subject_id` is the item rather than the Attestation -- deliberately, because a reviewer
        needs the whole document to judge whether a field really is unknown (EVI-002). Pointing
        at one Attestation would show them a value with nothing to compare it against.

        ALL of them, not only the open ones. `derive_state` intersects these with the project's
        open set, so the item keeps the history of what was reviewed and the *state* follows the
        queue -- which is what makes "resolve the review and the CLI leaves NEEDS_REVIEW" a
        property of the queue rather than of a second write to the item.
        """
        rows = self._connection.execute(
            "SELECT review_id FROM review_items WHERE project_id = %s AND subject_id = %s "
            "AND subject_type = 'EXTRACTION_UNCERTAINTY' ORDER BY created_at, review_id",
            (project_id, item_id),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _conflict_ids(self, item_id: str, project_id: str) -> tuple[str, ...]:
        """Conflicts naming this item among their subjects (§17.19.3).

        `subject_refs` is an untyped array on purpose -- §17.19.3's conflicts are about whatever
        disagreed, and `011a` records that a conflict about nothing is unrepresentable. An
        ingestion item is a legitimate subject: a SOURCE_RETRACTION_CONFLICT is about the
        document that was retracted.

        Like `_review_ids`, this returns all of them and lets `derive_state` intersect with the
        project's blocking set.
        """
        rows = self._connection.execute(
            "SELECT conflict_id FROM conflicts WHERE project_id = %s AND %s = ANY (subject_refs) "
            "ORDER BY detected_at, conflict_id",
            (project_id, item_id),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

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
