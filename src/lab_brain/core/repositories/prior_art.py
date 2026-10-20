"""Durable storage for PriorArtSearchRecords and the novelty statuses that cite them (SRC-003).

A NOVELTY STATUS CANNOT BE WRITTEN WITHOUT ITS SEARCH, in either implementation: the in-memory store
resolves the cited record and applies `novelty_coverage_problems`, and `002b`'s foreign key and
trigger do the same for any writer of SQL. "無覆蓋率記錄的 novelty status MUST 被拒絕" is a property
of where statuses are stored, not of the auditor that happened to produce this one.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.prior_art import (
    DateRange,
    NoveltyAssessment,
    PriorArtMatch,
    PriorArtSearchRecord,
    PriorArtSource,
    novelty_coverage_problems,
)
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class PriorArtStoreError(RepositoryError):
    """A search record or novelty status write violated an invariant."""


@runtime_checkable
class PriorArtStore(Protocol):
    def add_search(self, record: PriorArtSearchRecord) -> PriorArtSearchRecord: ...

    def search(self, search_id: str) -> PriorArtSearchRecord | None: ...

    def add_assessment(self, assessment: NoveltyAssessment) -> NoveltyAssessment: ...

    def assessment(self, assessment_id: str) -> NoveltyAssessment | None: ...


class InMemoryPriorArtStore:
    def __init__(self) -> None:
        self._searches: dict[str, PriorArtSearchRecord] = {}
        self._assessments: dict[str, NoveltyAssessment] = {}

    def add_search(self, record: PriorArtSearchRecord) -> PriorArtSearchRecord:
        existing = self._searches.get(record.search_id)
        if existing is not None and existing != record:
            raise PriorArtStoreError(f"prior-art search {record.search_id} is append-only")
        self._searches[record.search_id] = record
        return record

    def search(self, search_id: str) -> PriorArtSearchRecord | None:
        return self._searches.get(search_id)

    def add_assessment(self, assessment: NoveltyAssessment) -> NoveltyAssessment:
        existing = self._assessments.get(assessment.assessment_id)
        if existing is not None:
            if existing != assessment:
                raise PriorArtStoreError(f"assessment {assessment.assessment_id} is append-only")
            return existing
        record = self._searches.get(assessment.search_id)
        if record is None:
            raise PriorArtStoreError(
                f"novelty assessment {assessment.assessment_id} cites search "
                f"{assessment.search_id}, which does not exist. SRC-003: a novelty status with no "
                "coverage record MUST be refused"
            )
        problems = novelty_coverage_problems(record, assessment)
        if problems:
            raise PriorArtStoreError(
                f"novelty assessment {assessment.assessment_id} refused: {'; '.join(problems)}"
            )
        self._assessments[assessment.assessment_id] = assessment
        return assessment

    def assessment(self, assessment_id: str) -> NoveltyAssessment | None:
        return self._assessments.get(assessment_id)


_SEARCH_COLUMNS = (
    "search_id",
    "project_id",
    "episode_id",
    "intent",
    "sources",
    "queries",
    "date_range",
    "retrieved_at",
    "source_policy_version",
    "result_count",
    "deduped_work_count",
    "limitations",
    "coverage_notes",
    "external_source_record_ids",
    "inference_provenance_id",
)

#: `novelty_status` in `002b` (see its note); `status` on the model, as SRC-003 words it.
_ASSESSMENT_COLUMNS = (
    "assessment_id",
    "project_id",
    "episode_id",
    "subject_id",
    "search_id",
    "novelty_status",
    "scope",
    "global_coverage_required",
    "prior_art_matrix",
    "inference_provenance_id",
    "created_at",
)


class SqlPriorArtStore:
    """PostgreSQL implementation over `002b`."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_search(self, record: PriorArtSearchRecord) -> PriorArtSearchRecord:
        r = record
        self._connection.execute(
            f"INSERT INTO prior_art_search_records ({', '.join(_SEARCH_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_SEARCH_COLUMNS))}) "
            "ON CONFLICT (search_id) DO NOTHING",
            (
                r.search_id,
                r.project_id,
                r.episode_id,
                r.intent,
                json.dumps([s.model_dump(mode="json") for s in r.sources]),
                list(r.queries),
                json.dumps(r.date_range.model_dump(mode="json")) if r.date_range else None,
                r.retrieved_at,
                r.source_policy_version,
                r.result_count,
                r.deduped_work_count,
                list(r.limitations),
                r.coverage_notes,
                list(r.external_source_record_ids),
                r.inference_provenance_id,
            ),
        )
        stored = self.search(r.search_id)
        if stored != r:
            raise PriorArtStoreError(f"prior-art search {r.search_id} is recorded differently")
        return r

    def search(self, search_id: str) -> PriorArtSearchRecord | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_SEARCH_COLUMNS)} FROM prior_art_search_records "
            "WHERE search_id = %s",
            (search_id,),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_SEARCH_COLUMNS, row, strict=True))
        values["sources"] = tuple(PriorArtSource.model_validate(s) for s in values["sources"])
        if values["date_range"] is not None:
            values["date_range"] = DateRange.model_validate(values["date_range"])
        retrieved = values["retrieved_at"]
        assert isinstance(retrieved, dt.datetime)
        return PriorArtSearchRecord.model_validate(values)

    def add_assessment(self, assessment: NoveltyAssessment) -> NoveltyAssessment:
        a = assessment
        self._connection.execute(
            f"INSERT INTO novelty_assessments ({', '.join(_ASSESSMENT_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_ASSESSMENT_COLUMNS))}) "
            "ON CONFLICT (assessment_id) DO NOTHING",
            (
                a.assessment_id,
                a.project_id,
                a.episode_id,
                a.subject_id,
                a.search_id,
                a.status.value,
                a.scope.value,
                [c.value for c in a.global_coverage_required],
                json.dumps([m.model_dump(mode="json") for m in a.prior_art_matrix]),
                a.inference_provenance_id,
                a.created_at,
            ),
        )
        stored = self.assessment(a.assessment_id)
        if stored != a:
            raise PriorArtStoreError(f"assessment {a.assessment_id} is recorded differently")
        return a

    def assessment(self, assessment_id: str) -> NoveltyAssessment | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_ASSESSMENT_COLUMNS)} FROM novelty_assessments "
            "WHERE assessment_id = %s",
            (assessment_id,),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_ASSESSMENT_COLUMNS, row, strict=True))
        values["status"] = values.pop("novelty_status")
        values["prior_art_matrix"] = tuple(
            PriorArtMatch.model_validate(m) for m in values["prior_art_matrix"]
        )
        return NoveltyAssessment.model_validate(values)


__all__ = [
    "InMemoryPriorArtStore",
    "PriorArtStore",
    "PriorArtStoreError",
    "SqlPriorArtStore",
]
