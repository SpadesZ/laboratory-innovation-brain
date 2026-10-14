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

WHAT CASE MEMORY AND THE MINER MAY READ (Causal Warrant Gate). Only `trusted_confirmations`: a
CONFIRMED analysis that names its warrants, carries no flag (`012p`), and -- when it rests on a
person's answer -- whose answers the deployment's verifier accepts. Without a verifier, an analysis
resting on any reviewer answer is not trusted: nothing here checks a signature by default.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.failure import (
    CandidateHeuristic,
    FailureAnalysis,
    FailureAnalysisFlag,
    ResolutionStatus,
)
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class FailureStoreError(RepositoryError):
    """A failure-analysis or candidate write violated an invariant."""


def normalise_symptom(symptom: str) -> str:
    return " ".join(symptom.lower().split())


#: None when a stored confirmation may be relied on beyond its own record; otherwise why not.
ConfirmationVerifier = Callable[[FailureAnalysis], str | None]


def trust_refusal(
    analysis: FailureAnalysis,
    flags: tuple[FailureAnalysisFlag, ...],
    verify: ConfirmationVerifier | None,
) -> str | None:
    """Why a CONFIRMED analysis may not inform case memory or the miner, or None."""
    if analysis.resolution_status is not ResolutionStatus.CONFIRMED:
        return f"{analysis.failure_analysis_id} is {analysis.resolution_status.value}"
    if not analysis.warrant_refs:
        return (
            f"{analysis.failure_analysis_id} was confirmed with no diagnostic warrant (recorded "
            "before the Causal Warrant Gate)"
        )
    if flags:
        flag = flags[0]
        return f"{analysis.failure_analysis_id} is flagged {flag.kind.value}: {flag.statement}"
    if verify is not None:
        return verify(analysis)
    if any(not ref.startswith("dds:") for ref in analysis.warrant_refs):
        return (
            f"{analysis.failure_analysis_id} rests on a reviewer's answer and nothing here "
            "verifies its signature"
        )
    return None


@runtime_checkable
class FailureStore(Protocol):
    def add_analysis(self, analysis: FailureAnalysis) -> FailureAnalysis: ...

    def analysis(self, project_id: str, failure_analysis_id: str) -> FailureAnalysis | None: ...

    def analyses(self, project_id: str) -> tuple[FailureAnalysis, ...]: ...

    def similar_failures(self, project_id: str, symptom: str) -> tuple[str, ...]: ...

    def trusted_confirmations(self, project_id: str) -> tuple[FailureAnalysis, ...]: ...

    def add_candidate(self, candidate: CandidateHeuristic) -> CandidateHeuristic: ...

    def candidates(self, project_id: str) -> tuple[CandidateHeuristic, ...]: ...


class InMemoryFailureStore:
    def __init__(self, verify: ConfirmationVerifier | None = None) -> None:
        self._analyses: dict[str, FailureAnalysis] = {}
        self._candidates: dict[str, CandidateHeuristic] = {}
        self._flags: dict[str, list[FailureAnalysisFlag]] = {}
        self._verify = verify

    def add_flag(self, flag: FailureAnalysisFlag) -> FailureAnalysisFlag:
        analysis = self._analyses.get(flag.failure_analysis_id)
        if analysis is None or analysis.resolution_status is not ResolutionStatus.CONFIRMED:
            raise FailureStoreError(f"{flag.failure_analysis_id} is not a stored confirmation")
        self._flags.setdefault(flag.failure_analysis_id, []).append(flag)
        return flag

    def flags(self, project_id: str, failure_analysis_id: str) -> tuple[FailureAnalysisFlag, ...]:
        return tuple(
            f for f in self._flags.get(failure_analysis_id, []) if f.project_id == project_id
        )

    def trusted_confirmations(self, project_id: str) -> tuple[FailureAnalysis, ...]:
        return tuple(
            a
            for a in self.analyses(project_id)
            if trust_refusal(a, self.flags(project_id, a.failure_analysis_id), self._verify) is None
        )

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
            for a in reversed(self.trusted_confirmations(project_id))
            if normalise_symptom(a.symptom) == wanted
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
    "warrant_refs",
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
    "warrant_refs",
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


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value or ())


def _tuples(values: dict[str, Any]) -> dict[str, Any]:
    return {k: tuple(v) if k in _ARRAYS else v for k, v in values.items()}


_FLAG_COLUMNS = (
    "flag_id",
    "project_id",
    "failure_analysis_id",
    "kind",
    "statement",
    "evidence_refs",
    "analysis_digest",
    "recorded_by",
    "recorded_at",
)


class SqlFailureStore:
    """PostgreSQL implementation over `011l` (and `012p`'s flags)."""

    def __init__(
        self, connection: SqlConnection, verify: ConfirmationVerifier | None = None
    ) -> None:
        self._connection = connection
        self._verify = verify

    def add_analysis(self, analysis: FailureAnalysis) -> FailureAnalysis:
        try:
            self._connection.execute(
                f"INSERT INTO failure_analyses ({', '.join(_ANALYSIS_COLUMNS)})"
                f" VALUES ({', '.join(['%s'] * len(_ANALYSIS_COLUMNS))})",
                _row(analysis, _ANALYSIS_COLUMNS),
            )
        except Exception as exc:
            diag = getattr(exc, "diag", None)
            if getattr(exc, "sqlstate", None) is None and diag is None:
                raise
            # The database's own rule, as it said it: a refused confirmation is a finding.
            raise FailureStoreError(
                getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
            ) from exc
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

    def flags(self, project_id: str, failure_analysis_id: str) -> tuple[FailureAnalysisFlag, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_FLAG_COLUMNS)} FROM failure_analysis_flags"
            " WHERE project_id = %s AND failure_analysis_id = %s ORDER BY recorded_at, flag_id",
            (project_id, failure_analysis_id),
        ).fetchall()
        return tuple(
            FailureAnalysisFlag.model_validate(
                {**dict(zip(_FLAG_COLUMNS, r, strict=True)), "evidence_refs": _strings(r[5])}
            )
            for r in rows
        )

    def add_flag(self, flag: FailureAnalysisFlag) -> FailureAnalysisFlag:
        try:
            self._connection.execute(
                f"INSERT INTO failure_analysis_flags ({', '.join(_FLAG_COLUMNS)})"
                f" VALUES ({', '.join(['%s'] * len(_FLAG_COLUMNS))})",
                (
                    flag.flag_id,
                    flag.project_id,
                    flag.failure_analysis_id,
                    flag.kind.value,
                    flag.statement,
                    list(flag.evidence_refs),
                    flag.analysis_digest,
                    flag.recorded_by,
                    flag.recorded_at,
                ),
            )
        except Exception as exc:
            diag = getattr(exc, "diag", None)
            if getattr(exc, "sqlstate", None) is None and diag is None:
                raise
            raise FailureStoreError(
                getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
            ) from exc
        return flag

    def digest(self, failure_analysis_id: str) -> str | None:
        """The stored row's content digest, as a flag must name it (`failure_analysis_digest`)."""
        row = self._connection.execute(
            "SELECT failure_analysis_digest(f) FROM failure_analyses f"
            " WHERE f.failure_analysis_id = %s",
            (failure_analysis_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def trusted_confirmations(self, project_id: str) -> tuple[FailureAnalysis, ...]:
        """Confirmations case memory and the miner may read: see the module docstring."""
        return tuple(
            a
            for a in self.analyses(project_id)
            if trust_refusal(a, self.flags(project_id, a.failure_analysis_id), self._verify) is None
        )

    def similar_failures(self, project_id: str, symptom: str) -> tuple[str, ...]:
        wanted = normalise_symptom(symptom)
        return tuple(
            a.failure_analysis_id
            for a in reversed(self.trusted_confirmations(project_id))
            if normalise_symptom(a.symptom) == wanted
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
