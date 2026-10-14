"""The Causal Warrant Gate's sources, over PostgreSQL: one builder for every composition root.

The research service, its read side and the vertical test harness all resolve warrants the same
way -- certificates, attestations, observations and runs from their own stores, grants from
`012o` -- so the write path and the read path can never disagree about what a relation's warrant
or evidence line is. Each caller names the declaration sets its vertical registers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lab_brain.core.models.warrant import DiagnosticDeclarationSet, Link
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.observations import SqlObservationStore
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore
from lab_brain.core.warrant import EpisodeOutcomes, WarrantResolver


def sql_warrant_resolver(
    connection: Any,
    *,
    declaration_sets: Sequence[DiagnosticDeclarationSet],
    active: str | None,
) -> WarrantResolver:
    return WarrantResolver(
        certificates=SqlHypothesisStore(connection).get_certificate,
        attestations=SqlAttestationStore(connection).get,
        observations=SqlObservationStore(connection).get,
        runs=SqlJobStore(connection).get_run,
        grants=SqlDiagnosticWarrantStore(connection),
        relations=SqlRelationStore(connection).get,
        declaration_sets=declaration_sets,
        active=active,
    )


def episode_outcomes(connection: Any) -> EpisodeOutcomes:
    """Every outcome the episode's own runs observed, as (observation, observable, space, version,
    outcome) -- read off the attestations, so an outcome nobody predicted is seen too."""

    def read(project_id: str, episode_id: str) -> tuple[tuple[str, Link], ...]:
        rows = connection.execute(
            "SELECT o.observation_id, o.metric_or_event, a.method ->> 'outcome_space',"
            " a.method ->> 'outcome'"
            " FROM attestations a"
            " JOIN observations o ON o.observation_id = a.observation_id"
            " JOIN runs r ON r.run_id = o.run_id"
            " JOIN jobs j ON j.job_id = r.job_id"
            " WHERE a.project_id = %s AND j.episode_id = %s"
            " ORDER BY o.observation_id",
            (project_id, episode_id),
        ).fetchall()
        found: list[tuple[str, Link]] = []
        for observation_id, observable, space, outcome in rows:
            if not space or "@" not in str(space) or outcome is None:
                continue
            space_id, version = str(space).rsplit("@", 1)
            found.append((str(observation_id), (str(observable), space_id, version, str(outcome))))
        return tuple(found)

    return read


__all__ = ["episode_outcomes", "sql_warrant_resolver"]
