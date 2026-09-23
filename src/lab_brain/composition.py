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

from lab_brain.cognition.inference import ScientificInferenceService
from lab_brain.cognition.llm import BeliefBasisGate, ScientificLLM
from lab_brain.core.models.access import Actor, ArtifactOccurrence, ProjectMembership
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel, SourceOrigin
from lab_brain.core.models.episode import EpisodeState, ResearchEpisode
from lab_brain.core.models.evidence_unit import EvidenceUnit
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import InferenceProvenance
from lab_brain.core.models.job import Job, JobState, Run, RunStatus
from lab_brain.core.repositories.episodes import SqlEpisodeStore
from lab_brain.core.repositories.inference import SqlInferenceProvenanceStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.scientific_read import (
    AuthorizedCandidateResolver,
    AuthorizedUnit,
    ScientificReadGate,
    UnitSecurityDescriptor,
)
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.ingestion.pipeline import ErrorClass as StageErrorClass
from lab_brain.ingestion.pipeline import (
    IngestionOutcome,
    IngestionPipeline,
    IngestionStage,
    StageStatus,
)
from lab_brain.ingestion.reverification import SegmentationReverifier
from lab_brain.security.classification import ContextClassifier
from lab_brain.storage.artifacts.interface import ArtifactStore
from lab_brain.storage.postgres.evidence_units import PostgresEvidenceUnitReader
from lab_brain.storage.postgres.ingestion_writer import PostgresIngestionWriter
from lab_brain.storage.postgres.surface_store import PostgresSurfaceStore
from lab_brain.surface.catalog import MessageCatalog, default_catalog
from lab_brain.surface.disclosure import DiagnosticsService
from lab_brain.surface.errors import ErrorClass
from lab_brain.surface.ingestion_item import IngestionItem

#: The capability an ingestion job runs under. Named once, because `006a` requires the Run's
#: capability to equal the Job's and a literal repeated at both ends is a literal that drifts.
INGEST_CAPABILITY = "cap:ingest_document"
INGEST_BACKEND = "backend:local_parser"

#: §6's `SourceOrigin` (six members) mapped onto §17.22's `source_kind` (three). The CHECK in
#: `012` is the narrower vocabulary because the inbox column answers "how did this arrive" for a
#: human triaging a list, not "which subsystem produced it".
#:
#: Written as an exhaustive dict rather than a default: a seventh `SourceOrigin` would raise a
#: KeyError here at the moment it is added, which is a better failure than silently filing an
#: unmapped origin under CONNECTOR and having the inbox quietly misdescribe it.
_SOURCE_KIND: dict[SourceOrigin, str] = {
    SourceOrigin.UPLOAD: "UPLOAD",
    SourceOrigin.WATCHER_FILESYSTEM: "WATCHER",
    SourceOrigin.WATCHER_GIT: "WATCHER",
    SourceOrigin.EXTERNAL_CONNECTOR: "CONNECTOR",
    # A run output and a derived artifact both enter through the system rather than through a
    # person or a watcher; CONNECTOR is the closest of §17.22's three and neither is user-facing
    # at M1.
    SourceOrigin.RUN_OUTPUT: "CONNECTOR",
    SourceOrigin.DERIVED: "CONNECTOR",
}


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
        self._episodes = SqlEpisodeStore(connection)
        self._inferences = SqlInferenceProvenanceStore(connection)
        self._surface = PostgresSurfaceStore(connection)
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

    def _persist_surface(
        self,
        outcome: IngestionOutcome,
        *,
        job: Job,
        display_name: str,
        source_kind: str,
        submitted_at: dt.datetime,
    ) -> None:
        """`012`'s rows: the inbox item, its stage attempts, and an ErrorRecord per failure.

        ONE TRANSACTION, because `012`'s stage/error trigger is deferred to the commit boundary:
        a stage result naming an error must find it, and the error is projected from the same
        failure. Either write order is legitimate inside one transaction and neither is across
        two, which is exactly why the constraint is deferred rather than a foreign key.

        WRITTEN AFTER THE EVIDENCE, NOT BEFORE. The inbox is a projection of what happened; an
        item row written first would be visible while the ingestion it describes was still in
        flight, and a reader would derive a state from stage results that do not yet exist.

        The item's state is NOT written, because there is no column to write it to. A reader runs
        `derive_state` over these rows.
        """
        with self._connection.transaction():
            self._surface.record_item(
                item_id=outcome.item_id,
                project_id=outcome.project_id,
                actor_id=outcome.actor_id or job.project_id,
                trace_id=job.trace_id,
                raw_artifact_id=(
                    outcome.artifact.artifact_id if outcome.artifact is not None else None
                ),
                source_kind=source_kind,
                display_name=display_name,
                submitted_at=submitted_at,
            )
            error_ids: dict[str, str] = {}
            for result in outcome.stage_results:
                if result.status is not StageStatus.FAILED or result.reason_code is None:
                    continue
                record = self._surface.record_error(
                    project_id=outcome.project_id,
                    trace_id=job.trace_id,
                    error_class=ErrorClass(
                        (result.error_class or StageErrorClass.SYSTEM_ERROR).value
                    ),
                    reason_code=result.reason_code,
                    component=f"lab_brain.ingestion.{result.stage.value.lower()}",
                    occurred_at=result.finished_at or result.started_at,
                    item_id=outcome.item_id,
                    job_id=job.job_id,
                    attempt_count=job.attempt_count,
                    max_attempts=job.max_attempts,
                )
                error_ids[result.reason_code] = record.error_id
            self._surface.record_stage_results(
                outcome.item_id,
                tuple(outcome.stage_results),
                job_id=job.job_id,
                error_ids=error_ids,
            )

    # -- the surface reads the CLI is built on ------------------------------

    def inbox(self, project_id: str) -> tuple[IngestionItem, ...]:
        """§17.22's rows for one project. State is derived by the caller, never returned."""
        return self._surface.items_for_project(project_id)

    def diagnostics(self, catalog: MessageCatalog | None = None) -> DiagnosticsService:
        """UX-003's production service over durable `012` rows.

        `load_detail` resolves nothing at M1 and says so by returning `None`: `012` stores
        `technical_detail_ref` as a POINTER and no store backs it yet. The consequence is
        conservative in the right direction -- an actor holding the scope sees the default
        payload rather than detail that does not exist -- and the scope check, the redaction and
        the not-found semantics are all still the service's.
        """
        return DiagnosticsService(
            catalog=catalog or default_catalog(),
            load_error=self._surface.error,
            load_detail=lambda _ref: None,
            membership_of=self._load_membership,
        )

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

        ``episode_id`` is optional here and checked when supplied: `006b` refuses a Job whose
        project or trace differs from its episode's. Optional because M1 still admits an
        ingestion outside any episode -- a watcher drop has no research activity behind it -- and
        making it mandatory would force callers to invent one.
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
        self._persist_surface(
            outcome,
            job=job,
            display_name=uri,
            source_kind=_SOURCE_KIND[source_origin],
            submitted_at=job.submitted_at,
        )

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
        self._persist_surface(
            outcome,
            job=job,
            display_name=artifact.uri or artifact.artifact_id,
            source_kind=_SOURCE_KIND[artifact.source_origin],
            submitted_at=job.submitted_at,
        )

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

    # -- episodes (§17.3) ---------------------------------------------------

    def open_episode(
        self, *, project_id: str, goal: str, trace_id: str, episode_id: str | None = None
    ) -> ResearchEpisode:
        """Start a research episode. §12.5's trace begins here.

        The episode owns the trace and every Job in it inherits that trace -- `006b` refuses a
        Job on a different one, so the chain cannot be broken at its head.
        """
        return self._episodes.open(
            ResearchEpisode(
                episode_id=episode_id or new_id("episode"),
                project_id=project_id,
                trace_id=trace_id,
                goal=goal,
                state=EpisodeState.EVIDENCE_GATHERING,
                start_time=self._clock(),
            )
        )

    def suspend_episode(self, episode_id: str, *, reason: str) -> ResearchEpisode:
        """Park the EPISODE, not just its job.

        The exit gate says the episode resumes. A parked job whose episode is still
        EVIDENCE_GATHERING would leave a resumer unable to tell which activity to pick up --
        which is the distinction the clause is drawing.
        """
        return self._episodes.suspend(episode_id, reason=reason, at=self._clock())

    def resume_episode(self, episode_id: str) -> ResearchEpisode:
        return self._episodes.resume(episode_id)

    def episode(self, episode_id: str) -> ResearchEpisode | None:
        return self._episodes.get(episode_id)

    def jobs_of_episode(self, episode_id: str) -> tuple[str, ...]:
        """Membership by query. §17.8 forbids the parallel-array shape."""
        return self._episodes.jobs_of(episode_id)

    # -- scientific inference (§17.14) --------------------------------------

    def inference_service(self, llm: ScientificLLM) -> ScientificInferenceService:
        """The production scientific-inference operation for this deployment (LLM-001).

        ONE OPERATION, not a call followed by a write. `record_inference` used to be public and
        the vertical composed `invoke(); record_inference()` by hand -- so a crash between them
        left a scientific model output with no durable provenance, which is the only case the
        exit gate's "all scientific LLM calls persist" sentence was about. `infer` does not
        return until the record has been written, committed and reloaded.

        The LLM is a parameter rather than a constructor field because a deployment may have no
        model slot configured at all, and an `IngestionService` that refused to build without one
        would make ingestion depend on cognition.
        """
        return ScientificInferenceService(llm=llm, store=self._inferences, commit=self._connection)

    def classifier(self) -> ContextClassifier:
        """Derives what material carries, from the rows ingestion wrote (SEC-001, §14.1).

        Built on the SAME occurrence loader `read_gate` uses. A separate lookup here would let
        the label that decides a read and the label that decides an egress drift apart -- and the
        egress one is the copy that would be quietly more permissive, because that is the
        direction a bug in a send path fails.
        """
        return ContextClassifier(
            load_occurrence=self._load_occurrence,
            artifact_of_attestation=self._artifact_of_attestation,
        )

    def _artifact_of_attestation(self, attestation_id: str, project_id: str) -> str | None:
        """§17.2's `source_artifact_id`, project-scoped.

        Scoped because an attestation resolved without a project would let a bundle name a row in
        somebody else's project and inherit its classification -- which is a downgrade available
        to anyone who can guess an id.
        """
        row = self._connection.execute(
            "SELECT source_artifact_id FROM attestations "
            "WHERE attestation_id = %s AND project_id = %s",
            (attestation_id, project_id),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def inference(self, inference_id: str) -> InferenceProvenance | None:
        return self._inferences.get(inference_id)

    def belief_basis_gate(self) -> BeliefBasisGate:
        """§7.6's read side, reading the DURABLE record.

        Wired to the store rather than to a caller-supplied set: the rule is about inferences
        that are already in the database, and a gate backed by whatever a caller happened to
        hand it would answer about a different population.
        """
        return BeliefBasisGate(
            load_provenance=self._inferences.get,
            is_inference=lambda ref: ref.startswith("inf:"),
        )

    def read_gate(self) -> ScientificReadGate:
        """The ONE authorization boundary for scientific reads (SEC-002, R-7).

        Built from this deployment's stores. Every verdict it returns is `can_read_artifact`'s;
        this method supplies the three records that gate needs and nothing else.
        """
        return ScientificReadGate(
            load_actor=self._load_actor,
            load_membership=self._load_membership,
            load_occurrence=self._load_occurrence,
        )

    def evidence_for(self, *, actor_id: str, project_id: str) -> tuple[AuthorizedUnit, ...]:
        """Canonical evidence this actor may read.

        THE ACTOR IS REQUIRED. The previous signature took only a project and returned canonical
        bodies -- an occurrence proves presence, not authorization, so a member with INTERNAL
        clearance received RESTRICTED_NDA text and every check the call made passed honestly.

        ONE QUERY FOR DESCRIPTORS, THEN BODIES FOR THE ALLOWED ONES. `security_index_for_project`
        returns `(unit_id, artifact_id)` pairs and no text; the refused units are never loaded.
        The previous shape read every body first and filtered, which is a correct filter over an
        exposure that had already happened.

        Returns `AuthorizedUnit`, not `EvidenceUnit`, so the decision that authorized each body
        travels with it: a bare list is indistinguishable from a list nobody checked.
        """
        descriptors = tuple(
            UnitSecurityDescriptor(evidence_unit_id=unit_id, artifact_id=artifact_id)
            for unit_id, artifact_id in self._reader.security_index_for_project(project_id)
        )
        return self.candidate_resolver().resolve_descriptors(
            descriptors, actor_id=actor_id, project_id=project_id
        )

    def candidate_resolver(self) -> AuthorizedCandidateResolver:
        """Retrieval → canonical bodies, authorized.

        Wraps rather than replaces EVI-010's locked boundary: a candidate still carries no body
        and the canonical unit is still re-loaded by identity. What is added is the question
        §17.25.1 cannot answer -- and the order in which it is asked.

        THERE IS NO ACCESSOR FOR THE RAW READER. An intermediate shape exported one as
        `unauthorized_reader()` and treated the name as the control. It is not: a production
        service that returns a canonical-body loader answering to nobody has a public bypass
        whatever it is called, and the M1 vertical was calling it. The reader is a private field
        used by this class's own trusted paths; a test that needs the low-level loader builds one.
        """
        return AuthorizedCandidateResolver(
            gate=self.read_gate(),
            artifact_of=self._reader.artifact_of,
            load_unit=self._reader.load,
        )

    def admission_gate(
        self,
        *,
        actor_id: str,
        load_artifact: Callable[[str], Artifact | None],
        resegment: SegmentationReverifier,
    ) -> EvidenceAdmissionGate:
        """The gate, wired to THIS deployment's stores and to one ACL.

        `can_read` goes through `ScientificReadGate`, which is the same boundary
        `evidence_for` and the candidate resolver use. Before this repair the composition root
        built its own closure over `can_read_artifact` -- correct, and a second place the ACL was
        assembled. Every resolver is supplied, so none of the fail-closed branches is reached by
        a misconfiguration rather than by an attack.
        """
        gate = self.read_gate()

        def can_read(artifact_id: str, project_id: str) -> bool:
            return bool(
                gate.authorize_artifact(
                    actor_id=actor_id, project_id=project_id, artifact_id=artifact_id
                )
            )

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

    def _load_actor(self, actor_id: str) -> Actor | None:
        row = self._connection.execute(
            "SELECT actor_id, actor_type, display_name, active FROM actors WHERE actor_id = %s",
            (actor_id,),
        ).fetchone()
        if row is None:
            return None
        return Actor.model_validate(
            {
                "actor_id": row[0],
                "actor_type": row[1],
                "display_name": row[2],
                "active": row[3],
            }
        )

    def _load_membership(self, actor_id: str, project_id: str) -> ProjectMembership | None:
        row = self._connection.execute(
            "SELECT actor_id, project_id, role, sensitivity_clearance, approval_scopes, active "
            "FROM project_memberships WHERE actor_id = %s AND project_id = %s",
            (actor_id, project_id),
        ).fetchone()
        if row is None:
            return None
        return ProjectMembership.model_validate(
            {
                "actor_id": row[0],
                "project_id": row[1],
                "role": row[2],
                "sensitivity_clearance": tuple(row[3] or ()),
                "approval_scopes": tuple(row[4] or ()),
                "active": row[5],
            }
        )

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
