"""Durable FailureAnalyses and CandidateHeuristics, and §6.9's case memory over them (`011l`).

    §6.9  歷史 ResearchEpisode 與 FailureAnalysis 是一等檢索目標。同類症狀再出現時，系統先提示過去的
          競爭原因與各自的驗證方式。

Both are append-only: a re-analysis is a new analysis, and a candidate is one mining pass's
proposal. `similar_failures` is the case memory the Verification Planner reads before planning:
CONFIRMED analyses of the same project whose symptom matches, most recent first. It matches the
normalised symptom exactly -- a similarity model would be a judgment the planner then leans on, and
precedents here inform a person; they decide nothing.

`011l` refuses, for any writer of SQL, a CONFIRMED analysis whose evidence does not trace to a
SUCCEEDED Run with output artifacts (EPI-002), and a candidate derived from anything but CONFIRMED
analyses.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.failure import CandidateHeuristic, FailureAnalysis, ResolutionStatus
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class FailureStoreError(RepositoryError):
    """A failure-analysis or candidate write violated an invariant."""


def normalise_symptom(symptom: str) -> str:
    return " ".join(symptom.lower().split())


@runtime_checkable
class FailureStore(Protocol):
    def add_analysis(self, analysis: FailureAnalysis) -> FailureAnalysis: ...

    def analysis(self, project_id: str, failure_analysis_id: str) -> FailureAnalysis | None: ...

    def analyses(self, project_id: str) -> tuple[FailureAnalysis, ...]: ...

    def similar_failures(self, project_id: str, symptom: str) -> tuple[str, ...]: ...

    def add_candidate(self, candidate: CandidateHeuristic) -> CandidateHeuristic: ...

    def candidates(self, project_id: str) -> tuple[CandidateHeuristic, ...]: ...


class InMemoryFailureStore:
    def __init__(self) -> None:
        self._analyses: dict[str, FailureAnalysis] = {}
        self._candidates: dict[str, CandidateHeuristic] = {}

    def add_analysis(self, analysis: FailureAnalysis) -> FailureAnalysis:
        if analysis.failure_analysis_id in self._analyses:
            raise FailureStoreError(f"{analysis.failure_analysis_id} is append-only")
        self._analyses[analysis.failure_analysis_id] = analysis
        return analysis

    def analysis(self, project_id: str, failure_analysis_id: str) -> FailureAnalysis | None:
        found = self._analyses.get(failure_analysis_id)
        return found if found is not None and found.project_id == project_id else None

    def analyses(self, project_id: str) -> tuple[FailureAnalysis, ...]:
        return tuple(
            sorted(
                (a for a in self._analyses.values() if a.project_id == project_id),
                key=lambda a: (a.created_at, a.failure_analysis_id),
            )
        )

    def similar_failures(self, project_id: str, symptom: str) -> tuple[str, ...]:
        wanted = normalise_symptom(symptom)
        return tuple(
            a.failure_analysis_id
            for a in reversed(self.analyses(project_id))
            if a.resolution_status is ResolutionStatus.CONFIRMED
            and normalise_symptom(a.symptom) == wanted
        )

    def add_candidate(self, candidate: CandidateHeuristic) -> CandidateHeuristic:
        if candidate.candidate_id in self._candidates:
            raise FailureStoreError(f"{candidate.candidate_id} is append-only")
        for failure_id in candidate.derived_from_failures:
            found = self.analysis(candidate.project_id, failure_id)
            if found is None or found.resolution_status is not ResolutionStatus.CONFIRMED:
                raise FailureStoreError(
                    f"candidate {candidate.candidate_id} is derived from {failure_id}, which is "
                    "not a CONFIRMED failure analysis of its project"
                )
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    def candidates(self, project_id: str) -> tuple[CandidateHeuristic, ...]:
        return tuple(
            sorted(
                (c for c in self._candidates.values() if c.project_id == project_id),
                key=lambda c: (c.created_at, c.candidate_id),
            )
        )


_ANALYSIS_COLUMNS = (
    "failure_analysis_id",
    "project_id",
    "episode_id",
    "symptom",
    "expected_behavior",
    "observed_behavior",
    "candidate_causes",
    "confirmed_root_cause",
    "root_cause_evidence_ids",
    "failure_class",
    "fix",
    "prevention_rule",
    "resolution_status",
    "created_at",
)

_CANDIDATE_COLUMNS = (
    "candidate_id",
    "project_id",
    "trigger_pattern",
    "suggested_checks",
    "rationale",
    "source_artifact_ids",
    "source_locators",
    "source_episode_ids",
    "miner_model_version",
    "status",
    "proposed_scope",
    "conflicts_with_existing_rules",
    "derived_from_failures",
    "created_at",
)

_ARRAYS = {
    "candidate_causes",
    "root_cause_evidence_ids",
    "suggested_checks",
    "source_artifact_ids",
    "source_locators",
    "source_episode_ids",
    "conflicts_with_existing_rules",
    "derived_from_failures",
}


def _row(model: Any, columns: tuple[str, ...]) -> tuple[Any, ...]:
    dumped = model.model_dump(mode="python")
    out: list[Any] = []
    for column in columns:
        value = dumped[column]
        if column in _ARRAYS:
            out.append(list(value))
        elif column == "proposed_scope":
            out.append(json.dumps(value))
        elif hasattr(value, "value"):
            out.append(value.value)
        else:
            out.append(value)
    return tuple(out)


def _tuples(values: dict[str, Any]) -> dict[str, Any]:
    return {k: tuple(v) if k in _ARRAYS else v for k, v in values.items()}


class SqlFailureStore:
    """PostgreSQL implementation over `011l`."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_analysis(self, analysis: FailureAnalysis) -> FailureAnalysis:
        self._connection.execute(
            f"INSERT INTO failure_analyses ({', '.join(_ANALYSIS_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_ANALYSIS_COLUMNS))})",
            _row(analysis, _ANALYSIS_COLUMNS),
        )
        stored = self.analysis(analysis.project_id, analysis.failure_analysis_id)
        if stored != analysis:
            raise FailureStoreError(f"{analysis.failure_analysis_id} did not round-trip")
        return analysis

    def analysis(self, project_id: str, failure_analysis_id: str) -> FailureAnalysis | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_ANALYSIS_COLUMNS)} FROM failure_analyses"
            " WHERE project_id = %s AND failure_analysis_id = %s",
            (project_id, failure_analysis_id),
        ).fetchone()
        if row is None:
            return None
        values = dict(zip(_ANALYSIS_COLUMNS, row, strict=True))
        return FailureAnalysis.model_validate(_tuples(values))

    def analyses(self, project_id: str) -> tuple[FailureAnalysis, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_ANALYSIS_COLUMNS)} FROM failure_analyses"
            " WHERE project_id = %s ORDER BY created_at, failure_analysis_id",
            (project_id,),
        ).fetchall()
        return tuple(
            FailureAnalysis.model_validate(_tuples(dict(zip(_ANALYSIS_COLUMNS, r, strict=True))))
            for r in rows
        )

    def similar_failures(self, project_id: str, symptom: str) -> tuple[str, ...]:
        wanted = normalise_symptom(symptom)
        return tuple(
            a.failure_analysis_id
            for a in reversed(self.analyses(project_id))
            if a.resolution_status is ResolutionStatus.CONFIRMED
            and normalise_symptom(a.symptom) == wanted
        )

    def add_candidate(self, candidate: CandidateHeuristic) -> CandidateHeuristic:
        self._connection.execute(
            f"INSERT INTO candidate_heuristics ({', '.join(_CANDIDATE_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_CANDIDATE_COLUMNS))})",
            _row(candidate, _CANDIDATE_COLUMNS),
        )
        return candidate

    def candidates(self, project_id: str) -> tuple[CandidateHeuristic, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_CANDIDATE_COLUMNS)} FROM candidate_heuristics"
            " WHERE project_id = %s ORDER BY created_at, candidate_id",
            (project_id,),
        ).fetchall()
        return tuple(
            CandidateHeuristic.model_validate(
                _tuples(dict(zip(_CANDIDATE_COLUMNS, r, strict=True)))
            )
            for r in rows
        )


__all__ = [
    "FailureStore",
    "FailureStoreError",
    "InMemoryFailureStore",
    "SqlFailureStore",
    "normalise_symptom",
]
