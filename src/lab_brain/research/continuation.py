"""Continuing a research episode: the same episode, the same reasoning, never a parallel one.

`lab-brain research run --episode E` does not open anything. It CONTINUES an episode its actor
opened earlier and that is parked -- SUSPENDED on a simulator, a person, a seat or a budget -- and
it refuses everything else, fail-closed and before any write:

    who        the episode must be in the requesting project and have been OPENED BY the requesting
               actor (`012c`'s opening run is the binding; episodes themselves carry no actor). An
               unknown id, another project's episode, a colleague's episode and an episode no
               research run opened all get ONE answer (`EpisodeNotContinuable`), so an episode id
               cannot be probed across projects or actors.
    when       a COMPLETED or ABANDONED episode receives no new run (`EpisodeFinished`). An episode
               another run is working on right now is refused (`EpisodeInProgress`); liveness is a
               session advisory lock held for the whole run, so a run whose process died releases
               it, and the next continuation records that run INTERRUPTED and carries on.
    how        through the authoritative lifecycle: `SqlEpisodeStore.resume` (`006b`'s
               `episode_resume`, which locks the row and refuses finished episodes). `012c` refuses
               to start a run on an episode that is not gathering evidence, so skipping the resume
               is not possible either.
    what       nothing new. A continuation takes no documents, no verification input, no literature
               and no new framing: it resumes the episode's own inputs. New evidence to debate is a
               new episode.

ONE REASONING HISTORY. The continuation reuses the hypothesis set the opening run debated -- loaded
from the durable debate record, positions, critiques and bundles -- and never debates again; `012c`
refuses a second hypothesis set in the episode. Verification resumes over that set's certificates
and their governed belief states, and its jobs keep their meaning across runs:

    executed   a check an earlier run executed (its Job SUCCEEDED) is EXCLUDED from planning --
               running it again would count one execution twice as independent support.
    parked     a job an earlier, finished run left QUEUED (behind a budget) or WAITING_RESOURCE
               (behind a seat) is CANCELLED as superseded, with the reason on the job. It is not
               re-dispatched: its dispatch attempt is already recorded under ids derived from that
               job, and a second attempt under the same ids would collide with -- or be mistaken
               for -- the first. The loop submits the check afresh if it still chooses it.
    orphaned   a job a run that died left RUNNING has no Run and an unknown outcome: FAILED, with
               RESEARCH_RUN_INTERRUPTED, and never resumed.
    new        every job this run submits is keyed in its own namespace
               (`vs:<episode>:run<n>:<step>:<capability>`), so no key an earlier run used is ever
               returned for a different submission. Within a run the keys are the loop's own: a
               retried submission is still the same job.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.cognition.debate import DebateOutcome
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.debate import SqlDebateStore
from lab_brain.core.repositories.evidence_bundles import SqlEvidenceBundleRepository
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.jobs import JobStore
from lab_brain.verification.least_cost import PlanningResult
from lab_brain.verification.loop import Planner

#: The namespace of the advisory lock a research run holds on its episode (`pg_try_advisory_lock`
#: with two int4 keys: this, and `hashtext(episode_id)`), so it cannot collide with another use.
LEASE_NAMESPACE = 20_260_928

#: Outcomes a run is finished with when it did not finish itself.
INTERRUPTED = "INTERRUPTED"

_COLUMNS = (
    "research_run_id",
    "episode_id",
    "project_id",
    "actor_id",
    "ordinal",
    "hypothesis_set_id",
    "verification_artifact_id",
    "symptom",
    "expected_behavior",
    "observed_behavior",
    "started_at",
    "finished_at",
    "outcome",
)


class ContinuationRefused(Exception):
    """The episode cannot be continued as asked. Nothing was written."""


class EpisodeNotContinuable(ContinuationRefused):
    """ONE answer for every "not yours to continue": unknown id, another project's episode, another
    actor's episode, an episode no research run opened. Built from the request alone, so the
    message cannot differ between them."""

    def __init__(self, *, episode_id: str, actor_id: str, project_id: str) -> None:
        super().__init__(f"No episode {episode_id} to continue for {actor_id} in {project_id}.")


class EpisodeFinished(ContinuationRefused):
    """The actor's own episode is COMPLETED or ABANDONED: it receives no new research run."""


class EpisodeInProgress(ContinuationRefused):
    """Another research run holds the episode right now."""


@dataclass(frozen=True)
class ResearchRunRecord:
    research_run_id: str
    episode_id: str
    project_id: str
    actor_id: str
    ordinal: int
    hypothesis_set_id: str | None
    verification_artifact_id: str | None
    symptom: str | None
    expected_behavior: str | None
    observed_behavior: str | None
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    outcome: str | None = None


class SqlResearchRunStore:
    """`012c`'s research runs, and the lease a run holds on its episode.

    Autocommit, as every research-run store: the advisory lock is SESSION-level, so it outlives the
    statements that take and use it and dies with the connection of a run that crashed.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    # -- the lease --------------------------------------------------------------------------------

    def lease(self, episode_id: str) -> bool:
        """Take the episode's run lease without waiting. False when a live run holds it."""
        row = self._connection.execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (LEASE_NAMESPACE, episode_id)
        ).fetchone()
        return bool(row[0])

    def release(self, episode_id: str) -> None:
        self._connection.execute(
            "SELECT pg_advisory_unlock(%s, hashtext(%s))", (LEASE_NAMESPACE, episode_id)
        )

    # -- the ledger -------------------------------------------------------------------------------

    def opener(self, *, project_id: str, episode_id: str) -> ResearchRunRecord | None:
        """The run that opened `episode_id` IN `project_id`. Scoped by both, always."""
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM research_runs"
            " WHERE episode_id = %s AND project_id = %s AND ordinal = 1",
            (episode_id, project_id),
        ).fetchone()
        return None if row is None else _record(row)

    def runs(self, *, project_id: str, episode_id: str) -> tuple[ResearchRunRecord, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM research_runs"
            " WHERE episode_id = %s AND project_id = %s ORDER BY ordinal",
            (episode_id, project_id),
        ).fetchall()
        return tuple(_record(row) for row in rows)

    def start(self, record: ResearchRunRecord) -> ResearchRunRecord:
        self._connection.execute(
            f"INSERT INTO research_runs ({', '.join(_COLUMNS[:11])}) "
            f"VALUES ({', '.join(['%s'] * 11)})",
            (
                record.research_run_id,
                record.episode_id,
                record.project_id,
                record.actor_id,
                record.ordinal,
                record.hypothesis_set_id,
                record.verification_artifact_id,
                record.symptom,
                record.expected_behavior,
                record.observed_behavior,
                record.started_at,
            ),
        )
        return record

    def record_verification_input(self, research_run_id: str, artifact_id: str) -> None:
        self._connection.execute(
            "UPDATE research_runs SET verification_artifact_id = %s WHERE research_run_id = %s",
            (artifact_id, research_run_id),
        )

    def record_hypothesis_set(self, research_run_id: str, set_id: str) -> None:
        self._connection.execute(
            "UPDATE research_runs SET hypothesis_set_id = %s WHERE research_run_id = %s",
            (set_id, research_run_id),
        )

    def finish(self, research_run_id: str, *, outcome: str, at: dt.datetime) -> None:
        self._connection.execute(
            "UPDATE research_runs SET finished_at = %s, outcome = %s"
            " WHERE research_run_id = %s AND finished_at IS NULL",
            (at, outcome, research_run_id),
        )

    def interrupt_live(
        self, *, project_id: str, episode_id: str, at: dt.datetime
    ) -> tuple[int, ...]:
        """Finish, as INTERRUPTED, the run(s) left live by a process that died.

        Called only while holding the episode's lease: a live row nobody holds the lease for is a
        run whose connection is gone.
        """
        rows = self._connection.execute(
            "UPDATE research_runs SET finished_at = greatest(%s, started_at), outcome = %s"
            " WHERE episode_id = %s AND project_id = %s AND finished_at IS NULL"
            " RETURNING ordinal",
            (at, INTERRUPTED, episode_id, project_id),
        ).fetchall()
        return tuple(sorted(int(row[0]) for row in rows))

    def other_hypothesis_sets(self, *, project_id: str, episode_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT set_id FROM hypothesis_sets WHERE episode_id = %s AND project_id = %s"
            " ORDER BY created_at, set_id",
            (episode_id, project_id),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)


def _record(row: Sequence[object]) -> ResearchRunRecord:
    values = dict(zip(_COLUMNS, row, strict=True))
    return ResearchRunRecord(**values)  # type: ignore[arg-type]


# -- the episode's verification so far ------------------------------------------------------------


@dataclass(frozen=True)
class PriorVerification:
    """The verification jobs earlier runs of the episode left, by what a continuation does with
    them."""

    #: capability -> the SUCCEEDED job that executed it. Never executed again in this episode.
    executed: Mapping[str, Job]
    #: Jobs earlier runs parked (QUEUED or WAITING_RESOURCE) that never ran. Superseded.
    parked: tuple[Job, ...]
    #: Jobs left RUNNING by a run that died. No Run was recorded for them.
    orphaned: tuple[Job, ...]


def verification_key_prefix(episode_id: str) -> str:
    """The prefix of every verification-loop job key in an episode (`VerificationLoop._submit`)."""
    return f"vs:{episode_id}:"


def prior_verification(
    jobs: Any, connection: Any, *, project_id: str, episode_id: str
) -> PriorVerification:
    prefix = verification_key_prefix(episode_id)
    rows = connection.execute(
        "SELECT job_id FROM jobs WHERE project_id = %s AND episode_id = %s"
        " AND left(idempotency_key, %s) = %s ORDER BY submitted_at, job_id",
        (project_id, episode_id, len(prefix), prefix),
    ).fetchall()
    executed: dict[str, Job] = {}
    parked: list[Job] = []
    orphaned: list[Job] = []
    for row in rows:
        job = jobs.get(str(row[0]))
        if job is None:  # pragma: no cover - read in the same session it was listed
            continue
        if job.state is JobState.SUCCEEDED:
            executed.setdefault(job.capability_id, job)
        elif job.state in (JobState.QUEUED, JobState.WAITING_RESOURCE):
            parked.append(job)
        elif job.state is JobState.RUNNING:
            orphaned.append(job)
    return PriorVerification(executed=executed, parked=tuple(parked), orphaned=tuple(orphaned))


class ExcludingPlanner:
    """The loop's planner, told what earlier runs of this episode already executed.

    The loop excludes what IT executed; this adds what the episode executed before it, so the
    planner never chooses a check a second time -- two Runs of one check would be counted as two
    independent sources.
    """

    def __init__(self, inner: Planner, executed_before: frozenset[str]) -> None:
        self._inner = inner
        self._before = executed_before

    def plan(self, **kwargs: Any) -> PlanningResult:
        exclude = frozenset(kwargs.pop("exclude", frozenset()))
        return self._inner.plan(exclude=exclude | self._before, **kwargs)


class ContinuationJobs:
    """The loop's JobStore for a continuation: every job it submits is keyed in this run's own
    namespace (`vs:<episode>:run<n>:<step>:<capability>`), so a key an earlier run used -- for a job
    that succeeded, failed or was superseded -- is never returned for a new submission. Everything
    else is the underlying store's.
    """

    def __init__(self, jobs: JobStore, *, episode_id: str, ordinal: int) -> None:
        self._jobs = jobs
        self._prefix = verification_key_prefix(episode_id)
        self._namespace = f"{self._prefix}run{ordinal}:"

    def submit(self, job: Job) -> Job:
        key = job.idempotency_key
        if key.startswith(self._prefix):
            key = self._namespace + key[len(self._prefix) :]
        return self._jobs.submit(job.model_copy(update={"idempotency_key": key}))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._jobs, name)


# -- the reasoning history ------------------------------------------------------------------------


def load_debate(connection: Any, *, project_id: str, episode_id: str, set_id: str) -> DebateOutcome:
    """The opening run's debate, exactly as recorded: set, certificates, positions, critiques and
    the bundles the critiques name. Raises `ContinuationRefused` if any of it is not on record --
    an incomplete history is not continued, and it is never replaced by a new debate."""
    hypotheses = SqlHypothesisStore(connection)
    debates = SqlDebateStore(connection)
    bundles = SqlEvidenceBundleRepository(connection)
    hypothesis_set = hypotheses.get_set(set_id)
    if (
        hypothesis_set is None
        or hypothesis_set.project_id != project_id
        or hypothesis_set.episode_id != episode_id
    ):
        raise ContinuationRefused(
            f"episode {episode_id}'s recorded hypothesis set {set_id} is not a set of this "
            "episode; its reasoning history cannot be continued"
        )
    records = debates.records_for_set(set_id)
    certificates = hypotheses.certificates_in_set(set_id)
    if len(records) != 1 or not certificates:
        raise ContinuationRefused(
            f"episode {episode_id}'s hypothesis set {set_id} has {len(records)} debate record(s) "
            f"and {len(certificates)} certificate(s); a continuation needs exactly the one debate "
            "that admitted it"
        )
    record = records[0]
    positions = tuple(debates.get_position(p) for p in record.position_ids)
    critiques = tuple(debates.get_critique(c) for c in record.critique_ids)
    if any(p is None for p in positions) or any(c is None for c in critiques):
        raise ContinuationRefused(
            f"debate {record.debate_id} names positions or critiques that are not on record"
        )
    stored_critiques = tuple(c for c in critiques if c is not None)
    primary_ids = {c.primary_bundle_id for c in stored_critiques} or {
        p.bundle_id for p in positions if p is not None
    }
    primary = bundles.get(sorted(primary_ids)[0]) if primary_ids else None
    inverted = tuple(
        bundles.get(b)
        for b in sorted({c.inverted_bundle_id for c in stored_critiques if c.inverted_bundle_id})
    )
    if primary is None or any(b is None for b in inverted):
        raise ContinuationRefused(f"debate {record.debate_id}'s evidence bundles are not on record")
    surviving = tuple(record.surviving_hypothesis_ids)
    return DebateOutcome(
        record=record,
        hypothesis_set=hypothesis_set,
        certificates=certificates,
        positions=tuple(p for p in positions if p is not None),
        critiques=stored_critiques,
        primary_bundle=primary,
        inverted_bundles=tuple(b for b in inverted if b is not None),
        ranking=(),
        surviving_ids=surviving,
        contradicted_ids=tuple(
            sorted(c.hypothesis_id for c in certificates if c.hypothesis_id not in surviving)
        ),
    )


__all__ = [
    "INTERRUPTED",
    "LEASE_NAMESPACE",
    "ContinuationJobs",
    "ContinuationRefused",
    "EpisodeFinished",
    "EpisodeInProgress",
    "EpisodeNotContinuable",
    "ExcludingPlanner",
    "PriorVerification",
    "ResearchRunRecord",
    "SqlResearchRunStore",
    "load_debate",
    "prior_verification",
    "verification_key_prefix",
]
