"""The M1 composition root — where the parts become a system (OPS-001, OPS-004, UX-004, SEC-002).

WHY THIS FILE EXISTS.

Every M1 part was built with its collaborators injected, which is what made each one testable and
each guard independently provable. The cost of that is real and was flagged by the intermediate
audit: the wiring lived in tests. A `with connection.transaction()` closure written inside a test
proves that the pieces *can* be composed, not that anything composes them.

So the transaction boundary is here, in production code, owned by a named object. The tests
exercise `IngestionService`; they do not define it.

WHAT THE BOUNDARY ACTUALLY IS, because "wrap it in a transaction" is not a design.

    the artifact store   NOT transactional. Bytes are staged, then promoted, and promotion can
                         fail after the database has committed. OPS-004's compensation owns that,
                         and this class does not try to absorb it into a transaction that cannot
                         contain it.
    the database         one transaction per durable step. Artifact+occurrence commit together
                         (a row with no occurrence is invisible to SEC-002); evidence units and
                         their occurrences commit together (an occurrence's foreign key names the
                         unit).
    the job              OUTSIDE both. `job_complete` takes its own row lock, and holding an
                         ingestion transaction open across it would make a slow parse block every
                         concurrent completion on that table.

Three boundaries, not one, because they fail differently. A single enclosing transaction would
have to be either too short to protect the evidence write or too long to let anything else run.

THE LOCKED RULE, RESTATED WHERE IT WOULD BE BROKEN. There is no `if already_seen: skip`. A retry
runs the whole pipeline again and writes again; every id it computes is the same id, so every
write asserts a row that already exists. Callback idempotency -- one Run per Job -- is a different
invariant with a different mechanism, and `006a` owns it. Conflating them is the single most
likely way to damage this system, which is why both this docstring and
`lab_brain.core.models.job`'s say so.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from lab_brain.core.access import can_read_artifact
from lab_brain.core.models.access import ArtifactOccurrence, ProjectMembership
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel, SourceOrigin
from lab_brain.core.models.evidence_unit import EvidenceUnit
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.job import Job, JobState, Run, RunStatus
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.ingestion.pipeline import IngestionOutcome, IngestionPipeline, IngestionStage
from lab_brain.ingestion.reverification import SegmentationReverifier
from lab_brain.storage.artifacts.interface import ArtifactStore
from lab_brain.storage.postgres.evidence_units import PostgresEvidenceUnitReader
from lab_brain.storage.postgres.ingestion_writer import PostgresIngestionWriter

#: The capability an ingestion job runs under. Named once, because `006a` requires the Run's
#: capability to equal the Job's and a literal repeated at both ends is a literal that drifts.
INGEST_CAPABILITY = "cap:ingest_document"
INGEST_BACKEND = "backend:local_parser"


class _Connection(Protocol):
    """The psycopg slice this module needs, structurally (AGT-007).

    Widened from `SqlConnection` by one method -- `transaction()` -- because the transaction
    boundary is what this module exists to own. The parameter type matches `SqlConnection`'s
    exactly so a real connection satisfies both without a cast.
    """

    autocommit: bool

    def execute(self, query: str, params: Sequence[object] = ..., /) -> Any: ...

    def transaction(self) -> AbstractContextManager[Any]: ...


@dataclass(frozen=True)
class IngestionResult:
    """What one production ingestion produced, end to end."""

    job: Job
    run: Run | None
    outcome: IngestionOutcome

    @property
    def artifact(self) -> Artifact | None:
        return self.outcome.artifact

    @property
    def evidence_units(self) -> tuple[EvidenceUnit, ...]:
        return self.outcome.evidence_units

    @property
    def succeeded(self) -> bool:
        return self.run is not None and self.run.status is RunStatus.SUCCEEDED


class IngestionService:
    """Job -> pipeline -> durable artifact/evidence -> authoritative Run.

    ONE OBJECT OWNS THE WIRING, so there is one place to read to know what a production ingestion
    does -- and one place a later slice has to change rather than every call site.
    """

    def __init__(
        self,
        *,
        connection: _Connection,
        artifact_store: ArtifactStore,
        clock: Callable[[], dt.datetime] = utc_now,
    ) -> None:
        self._connection = connection
        self._clock = clock
        self._writer = PostgresIngestionWriter(connection)
        self._jobs = SqlJobStore(connection)
        self._reader = PostgresEvidenceUnitReader(connection)
        self._store = artifact_store
        self._pipeline = IngestionPipeline(artifact_store, self._commit_rows, self._rollback_rows)

    # -- the transaction boundary, owned here -------------------------------

    def _commit_rows(self, artifact: Artifact, occurrence: ArtifactOccurrence) -> None:
        """Artifact and occurrence, together or not at all.

        Together because an artifact row with no occurrence is invisible to SEC-002: ADR-0010
        made presence a property of the occurrence, so the bytes would exist globally and belong
        to nobody -- readable by a query that forgot to join, and by nothing that remembered.
        """
        with self._connection.transaction():
            self._writer.commit_rows(artifact, occurrence)

    def _rollback_rows(self, artifact: Artifact, occurrence: ArtifactOccurrence) -> None:
        """OPS-004's compensation. Reached only when the artifact store fails to promote.

        Separate transaction, because the one that committed these rows is already closed --
        which is the whole reason a compensating write is needed rather than a rollback.
        """
        with self._connection.transaction():
            self._connection.execute(
                "DELETE FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
                (occurrence.artifact_id, occurrence.project_id),
            )
            self._connection.execute(
                "DELETE FROM artifacts WHERE artifact_id = %s", (artifact.artifact_id,)
            )

    def _persist_evidence(self, outcome: IngestionOutcome) -> None:
        """Units and occurrences, together. An occurrence's foreign key names its unit."""
        if not outcome.evidence_units:
            return
        with self._connection.transaction():
            self._writer.persist_evidence(outcome.evidence_units, outcome.evidence_occurrences)

    # -- the vertical -------------------------------------------------------

    def submit(
        self,
        *,
        project_id: str,
        actor_id: str,
        idempotency_key: str,
        trace_id: str,
        episode_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        """Register the Job before any work happens.

        Before, not after: UX-004's retry resumes a Job, and a Job created only on success would
        not exist for the failure that needs retrying.
        """
        return self._jobs.submit(
            Job(
                job_id=new_id("job"),
                project_id=project_id,
                episode_id=episode_id,
                capability_id=INGEST_CAPABILITY,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                submitted_at=self._clock(),
                max_attempts=max_attempts,
            )
        )

    def suspend(self, job_id: str, *, reason_stage: str | None = None) -> Job:
        """§10.7's WAITING_RESOURCE. The job keeps its place and its identity."""
        return self._jobs.transition(
            job_id, JobState.WAITING_RESOURCE, self._clock(), resume_stage=reason_stage
        )

    def resume(self, job_id: str) -> Job:
        return self._jobs.transition(job_id, JobState.RUNNING, self._clock())

    def ingest(
        self,
        data: bytes,
        *,
        job_id: str,
        actor_id: str,
        sensitivity_label: SensitivityLabel,
        uri: str,
        media_type: str = "text/markdown",
        source_origin: SourceOrigin = SourceOrigin.UPLOAD,
        source_metadata: dict[str, str] | None = None,
    ) -> IngestionResult:
        """Run the pipeline under ``job_id`` and complete it with exactly one Run.

        Idempotent through DERIVED identity for the content and through `job_complete` for the
        callback -- two mechanisms, deliberately not merged. Running this twice under the same
        job returns the same Run; running it twice under two jobs produces one Artifact and one
        set of EvidenceUnits with two occurrences, because the ids are functions of the bytes.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id} does not exist; submit it before ingesting")
        if job.state is JobState.QUEUED:
            job = self._jobs.transition(job_id, JobState.RUNNING, self._clock())

        started = self._clock()
        outcome = self._pipeline.ingest(
            data,
            project_id=job.project_id,
            # The actor is a parameter of the CALL, not read off the Job. §17.16 declares no
            # actor field, and inventing one would be the drift ADR-0010 was written about --
            # while `artifacts.actor_id` is a real foreign key, so a placeholder would fail at
            # the boundary rather than being quietly wrong.
            actor_id=actor_id,
            sensitivity_label=sensitivity_label,
            media_type=media_type,
            uri=uri,
            source_origin=source_origin,
            source_metadata=source_metadata,
        )
        self._persist_evidence(outcome)

        # The Run is minted OUTSIDE the ingestion transactions. `job_complete` takes its own row
        # lock, and holding a parse-length transaction across it would block every concurrent
        # completion on `jobs`.
        finished = self._clock()
        produced = (outcome.artifact.artifact_id,) if outcome.artifact is not None else ()
        status = RunStatus.SUCCEEDED if produced and outcome.evidence_units else RunStatus.FAILED
        run = self._jobs.complete(
            job_id,
            job.idempotency_key,
            Run(
                run_id=new_id("run"),
                job_id=job_id,
                project_id=job.project_id,
                capability_id=job.capability_id,
                backend_id=INGEST_BACKEND,
                trace_id=job.trace_id,
                input_parameters={"uri": uri, "media_type": media_type},
                conditions_schema_version="core.ingestion@1.0.0",
                environment={"pipeline": "local"},
                code_provenance="lab_brain.ingestion.pipeline@1.0.0",
                status=status,
                warnings=tuple(
                    r.reason_code or r.stage.value
                    for r in outcome.stage_results
                    if r.reason_code and r.stage is not IngestionStage.RAW_STORE
                ),
                output_artifacts=produced if status is RunStatus.SUCCEEDED else (),
                start_time=started,
                end_time=finished,
                reproducibility_manifest_hash=(
                    outcome.artifact.content_hash if outcome.artifact else "sha256:none"
                ),
            ),
        )
        return IngestionResult(job=self._jobs.get(job_id) or job, run=run, outcome=outcome)

    def retry(
        self,
        *,
        job_id: str,
        artifact: Artifact,
        occurrence: ArtifactOccurrence,
        item_id: str,
        actor_id: str,
        source_metadata: dict[str, str] | None = None,
    ) -> IngestionResult:
        """UX-004's resume: re-run the failed stage against bytes that are already durable.

        No re-upload, no re-scan, no new Artifact. The Job is the same Job -- which is what makes
        "creates no second Run" a property of this path rather than a coincidence.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id} does not exist")
        if job.state is JobState.WAITING_RESOURCE:
            job = self.resume(job_id)

        started = self._clock()
        outcome = self._pipeline.resume(
            artifact=artifact,
            occurrence=occurrence,
            item_id=item_id,
            project_id=job.project_id,
            actor_id=actor_id,
            source_metadata=source_metadata,
        )
        self._persist_evidence(outcome)

        finished = self._clock()
        status = RunStatus.SUCCEEDED if outcome.evidence_units else RunStatus.FAILED
        run = self._jobs.complete(
            job_id,
            job.idempotency_key,
            Run(
                run_id=new_id("run"),
                job_id=job_id,
                project_id=job.project_id,
                capability_id=job.capability_id,
                backend_id=INGEST_BACKEND,
                trace_id=job.trace_id,
                conditions_schema_version="core.ingestion@1.0.0",
                code_provenance="lab_brain.ingestion.pipeline@1.0.0",
                status=status,
                output_artifacts=(artifact.artifact_id,) if status is RunStatus.SUCCEEDED else (),
                start_time=started,
                end_time=finished,
                reproducibility_manifest_hash=artifact.content_hash,
            ),
        )
        return IngestionResult(job=self._jobs.get(job_id) or job, run=run, outcome=outcome)

    # -- reads, all of them project-scoped ----------------------------------

    def evidence_for(self, project_id: str) -> tuple[EvidenceUnit, ...]:
        """Canonical evidence, rebuilt through the model and scoped by occurrence."""
        return self._reader.load_for_project(project_id)

    def admission_gate(
        self,
        *,
        membership_of: Callable[[str, str], ProjectMembership | None],
        load_artifact: Callable[[str], Artifact | None],
        resegment: SegmentationReverifier,
        actor_of: Callable[[str], Any],
    ) -> EvidenceAdmissionGate:
        """The gate, wired to THIS deployment's stores.

        R-7's closing condition lives here: `can_read` is `lab_brain.core.access.can_read_artifact`
        -- the one ACL implementation -- reached through a production object rather than through a
        closure a test wrote. Every resolver is supplied, so none of the fail-closed branches is
        reached by a misconfiguration rather than by an attack.
        """

        def can_read(artifact_id: str, project_id: str) -> bool:
            occurrence = self._load_occurrence(artifact_id, project_id)
            actor = actor_of(project_id)
            membership = membership_of(getattr(actor, "actor_id", ""), project_id)
            return bool(can_read_artifact(actor, artifact_id, project_id, occurrence, membership))

        return EvidenceAdmissionGate(
            load_artifact=load_artifact,
            load_evidence_unit=self._reader.load,
            can_read=can_read,
            resegment=resegment,
            is_present_in=self._reader.present_in,
            load_run=self._jobs.get_run,
            is_artifact_in_project=self._artifact_present_in,
        )

    def _artifact_present_in(self, artifact_id: str, project_id: str) -> bool:
        """ADR-0010 presence for artifacts. The query, not a second copy of the ACL."""
        row = self._connection.execute(
            "SELECT 1 FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
            (artifact_id, project_id),
        ).fetchone()
        return row is not None

    def _load_occurrence(self, artifact_id: str, project_id: str) -> ArtifactOccurrence | None:
        row = self._connection.execute(
            "SELECT artifact_id, project_id, sensitivity_label, ingested_by_actor_id, "
            "ingested_at FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
            (artifact_id, project_id),
        ).fetchone()
        if row is None:
            return None
        return ArtifactOccurrence.model_validate(
            {
                "artifact_id": row[0],
                "project_id": row[1],
                "sensitivity_label": row[2],
                "ingested_by_actor_id": row[3],
                "ingested_at": row[4],
            }
        )

    def queue_depth(self, project_id: str) -> int:
        return self._jobs.active_depth(project_id)

    def active_jobs(self, project_id: str) -> Sequence[Job]:
        return self._jobs.list_active(project_id)


__all__ = ["INGEST_BACKEND", "INGEST_CAPABILITY", "IngestionResult", "IngestionService"]
