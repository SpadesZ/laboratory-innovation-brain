"""Durable ResearchEpisode storage (OPS-001, §17.3, §12.1).

Thin, because the invariants are `006b`'s: suspend and resume are single SQL statements so the
state and its timestamp cannot diverge, both are idempotent on the target state (the thing that
resumes a suspended episode is a worker that may itself have restarted mid-resume), and a Job is
refused if it is on a different trace or in a different project from its episode.

Reads rebuild through `ResearchEpisode`, so a row that drifted raises rather than being handed
back as an episode a resumer would act on.
"""

from __future__ import annotations

from lab_brain.core.models.episode import EpisodeState, ResearchEpisode
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError

_COLUMNS = (
    "episode_id",
    "project_id",
    "trace_id",
    "goal",
    "state",
    "outcome_status",
    "start_time",
    "end_time",
    "suspended_at",
    "suspend_reason",
)


class EpisodeStoreError(RepositoryError):
    """An episode write violated a lifecycle invariant."""


class SqlEpisodeStore:
    """PostgreSQL storage for §17.3's minimum subset."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def open(self, episode: ResearchEpisode) -> ResearchEpisode:
        """Register an episode. Idempotent on `episode_id`.

        Idempotent rather than strict, for the reason `JobStore.submit` is: a client that retries
        a submission it is unsure landed is behaving correctly, and punishing it pushes the retry
        logic back into every caller.
        """
        self._connection.execute(
            f"INSERT INTO research_episodes ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}) "
            "ON CONFLICT (episode_id) DO NOTHING",
            (
                episode.episode_id,
                episode.project_id,
                episode.trace_id,
                episode.goal,
                episode.state.value,
                episode.outcome_status,
                episode.start_time,
                episode.end_time,
                episode.suspended_at,
                episode.suspend_reason,
            ),
        )
        stored = self.get(episode.episode_id)
        if stored is None:  # pragma: no cover
            raise EpisodeStoreError(f"episode {episode.episode_id} vanished after being written")
        return stored

    def get(self, episode_id: str) -> ResearchEpisode | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM research_episodes WHERE episode_id = %s",
            (episode_id,),
        ).fetchone()
        return None if row is None else _from_row(row)

    def suspend(self, episode_id: str, *, reason: str, at: object) -> ResearchEpisode:
        """Park the episode. One statement, so state and timestamp cannot diverge."""
        try:
            self._connection.execute("SELECT episode_suspend(%s, %s, %s)", (episode_id, reason, at))
        except Exception as exc:
            raise EpisodeStoreError(f"episode_suspend refused {episode_id}: {exc}") from exc
        return self._reload(episode_id)

    def resume(self, episode_id: str) -> ResearchEpisode:
        """Resume the SAME episode. The clause the exit gate actually states."""
        try:
            self._connection.execute("SELECT episode_resume(%s)", (episode_id,))
        except Exception as exc:
            raise EpisodeStoreError(f"episode_resume refused {episode_id}: {exc}") from exc
        return self._reload(episode_id)

    def close(self, episode_id: str, *, outcome: str, at: object) -> ResearchEpisode:
        self._connection.execute(
            "UPDATE research_episodes SET state = %s, outcome_status = %s, end_time = %s, "
            "suspended_at = NULL, suspend_reason = NULL WHERE episode_id = %s",
            (EpisodeState.COMPLETED.value, outcome, at, episode_id),
        )
        return self._reload(episode_id)

    def jobs_of(self, episode_id: str) -> tuple[str, ...]:
        """Which jobs belong to this episode.

        A QUERY, not a column. §17.8 forbids the parallel-array shape, and an array here would be
        a second source of truth for the relation `jobs.episode_id` already holds -- two answers
        that disagree silently the first time one is written without the other.
        """
        rows = self._connection.execute(
            "SELECT job_id FROM jobs WHERE episode_id = %s ORDER BY submitted_at, job_id",
            (episode_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _reload(self, episode_id: str) -> ResearchEpisode:
        episode = self.get(episode_id)
        if episode is None:  # pragma: no cover - the function raises before this is reachable
            raise EpisodeStoreError(f"episode {episode_id} vanished mid-transition")
        return episode


def _from_row(row: tuple[object, ...]) -> ResearchEpisode:
    return ResearchEpisode.model_validate(dict(zip(_COLUMNS, row, strict=True)))


__all__ = ["EpisodeStoreError", "SqlEpisodeStore"]
