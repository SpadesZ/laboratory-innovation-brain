"""ResearchEpisode — the minimum §17.3 subset M1's exit gate needs (§12.1, OPS-001).

WHY THIS EXISTS RATHER THAN A JOB RELOAD.

The M1 exit gate says *delayed mock job resumes **episode***. A Job surviving a restart proves
the Job is durable; §12.1 makes an episode a state machine spanning many jobs, so what has to be
found again after a restart is *which research activity* the resumed job belongs to. Reading the
clause as if it said "job" would be substituting the easier claim for the stated one.

THE OMISSIONS ARE DECLARED. §17.3 lists sixteen fields and this carries six plus timing. Every
absent field is absent because the entity it references does not exist yet -- `hypothesis_ids`
needs EPI-001 (M3), `verification_plan_ids` needs VER-001 (M4), `failure_analysis_id` needs §17.6
(M4) -- and a column referencing a missing entity is an unapplyable migration rather than a
stricter schema. `006b`'s header lists each one with the requirement that brings it.

`job_ids[]` AND `run_ids[]` ARE NOT DEFERRED, THEY ARE REFUSED. `jobs.episode_id` already carries
the relation, and §17.8's rule -- no entity carries a parallel support array -- applies exactly:
an array here would be a second, unversioned source of truth for "which jobs belong to this
episode", and the two would disagree silently. Membership is a query.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from lab_brain.core.models.base import CoreModel


class EpisodeState(StrEnum):
    """§12.1's state machine, restricted to the states M1 can actually reach.

    The later states -- HYPOTHESIS_FORMATION onward -- arrive with the slices that drive them.
    Declaring states nothing can enter would put permanently unreachable values in the vocabulary
    and make "which states are live" a question no reader could answer from the code.

    ``SUSPENDED`` is M1's addition and it is the one the exit gate turns on: §12.1 describes the
    forward path and says nothing about parking, but §10.7's WAITING_RESOURCE makes parking a
    real operational state for the Job -- and an episode whose only job is parked is an episode
    that is parked.
    """

    CREATED = "CREATED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


TERMINAL_EPISODE_STATES: frozenset[EpisodeState] = frozenset(
    {EpisodeState.COMPLETED, EpisodeState.ABANDONED}
)


class ResearchEpisode(CoreModel):
    """§17.3's durable identity, scope, trace and state.

    ``trace_id`` is required and is where §12.5's chain begins: trace_id 貫穿 episode → retrieval
    → LLM call → job → run → artifact. `006b` refuses a Job on a different trace from its
    episode, so the chain cannot be broken at its head.
    """

    episode_id: str
    project_id: str
    trace_id: str
    goal: str
    state: EpisodeState = EpisodeState.CREATED
    outcome_status: str | None = None
    start_time: dt.datetime
    end_time: dt.datetime | None = None
    suspended_at: dt.datetime | None = None
    suspend_reason: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if (self.state in TERMINAL_EPISODE_STATES) != (self.end_time is not None):
            raise ValueError(
                f"episode {self.episode_id} is {self.state.value} with end_time="
                f"{self.end_time!r}; a finished episode has an end and an unfinished one does not"
            )
        if (self.state is EpisodeState.SUSPENDED) != (self.suspended_at is not None):
            raise ValueError(
                f"episode {self.episode_id} is {self.state.value} with suspended_at="
                f"{self.suspended_at!r}; an episode that parked records when, and one that did "
                "not must not carry a timestamp a resumer would read as real"
            )
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError(f"episode {self.episode_id} ends before it starts")
        return self

    @property
    def is_suspended(self) -> bool:
        return self.state is EpisodeState.SUSPENDED

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_EPISODE_STATES


__all__ = ["TERMINAL_EPISODE_STATES", "EpisodeState", "ResearchEpisode"]
