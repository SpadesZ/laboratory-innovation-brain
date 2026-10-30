"""Authorized, prospective verification of a hypothesis proposed after screening (`011s`).

A hypothesis its author proposed after seeing a screening reading cannot be supported by that
reading, by anything that existed before the hypothesis, or by a check nobody pre-registered.
`011s` holds those rules for every writer. This module is the governed path that lets a GENUINE
later check be recorded:

    1. authorize   an accountable person (an active HUMAN member of the project) pre-registers a
                   test: this post-screening hypothesis, these of its predictions, this DECLARED
                   capability, and why. The database dates it by its own clock, after the
                   hypothesis, and never lets it change.
    2. bind        the one Job that test licenses is bound to it while still QUEUED -- before
                   anything ran. `AuthorizedJobs` does this for the verification loop;
                   `record_authorized_measurement` does it for a person's measurement.
    3. record      the check's Run, Observation, Attestation and relations. SUPPORTS reaches the
                   hypothesis only if every `011s` rule holds: new data of known capture time,
                   captured after the authorization; clean lineage; a declared kind that produces
                   new evidence; the relation names a pre-registered prediction.

Without an authorization, or with a late one, or on retrospective data, the same outcome is still
RECORDED -- as context (`CITES`, with the refusal as its reason, by `ProspectiveEvidenceSink`) --
and supports nothing. A pre-screening hypothesis is unaffected.

WHAT AN ACCEPTED SUPPORT MEANS. A pre-registered, new and independent check as far as the records
show. It is not a physical confirmation, and it is only as true as what its writer recorded: a
capture time, a lineage or a media type the writer omits or misstates is not detected here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.job import Job, Run, RunStatus
from lab_brain.core.models.prediction import Prediction
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.ingestion.admission_gate import AdmissionRequest, EvidenceAdmissionGate
from lab_brain.storage.postgres.capabilities import PostgresCapabilityStore, declared_kind
from lab_brain.storage.postgres.run_outputs import SqlRunOutputSink
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from lab_brain.verification.evidence import RunEvidence, evidence_from_run
from lab_brain.verification.workflows import ObservedOutcome

#: Kinds whose output is empirical data a person or instrument captured.
EMPIRICAL_KINDS = frozenset({"MEASUREMENT", "FABRICATION"})


class ProspectiveRefused(RuntimeError):
    """A prospective verification could not be authorized or recorded as offered."""


@dataclass(frozen=True)
class VerificationAuthorization:
    authorization_id: str
    project_id: str
    episode_id: str
    hypothesis_id: str
    prediction_ids: tuple[str, ...]
    capability_id: str
    declaration_hash: str
    actor_id: str
    rationale: str
    created_at: dt.datetime


_COLUMNS = (
    "authorization_id, project_id, episode_id, hypothesis_id, prediction_ids, capability_id,"
    " declaration_hash, actor_id, rationale, created_at"
)


def _authorization(row: Sequence[Any]) -> VerificationAuthorization:
    return VerificationAuthorization(
        authorization_id=str(row[0]),
        project_id=str(row[1]),
        episode_id=str(row[2]),
        hypothesis_id=str(row[3]),
        prediction_ids=tuple(str(p) for p in row[4]),
        capability_id=str(row[5]),
        declaration_hash=str(row[6]),
        actor_id=str(row[7]),
        rationale=str(row[8]),
        created_at=row[9],
    )


def _refused(exc: Exception) -> ProspectiveRefused:
    diag = getattr(exc, "diag", None)
    message = getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
    return ProspectiveRefused(message)


class SqlVerificationAuthorizations:
    """`verification_authorizations` and the Job each one licenses."""

    def __init__(self, connection: Any) -> None:
        self._c = connection

    def authorize(
        self,
        *,
        authorization_id: str,
        project_id: str,
        hypothesis_id: str,
        prediction_ids: Sequence[str],
        capability_id: str,
        actor_id: str,
        rationale: str,
    ) -> VerificationAuthorization:
        """Pre-register a test. The database checks everything and dates it (`011s`)."""
        declared = declared_kind(self._c, capability_id)
        if declared is None:
            raise ProspectiveRefused(
                f"{capability_id} is not declared by a domain pack (capability_declarations); "
                "only a declared check can be pre-registered (011s)"
            )
        row = self._c.execute(
            "SELECT created_in_episode FROM hypotheses WHERE project_id = %s"
            " AND hypothesis_id = %s",
            (project_id, hypothesis_id),
        ).fetchone()
        if row is None:
            raise ProspectiveRefused(f"{hypothesis_id} is not a hypothesis of {project_id}")
        try:
            with self._c.transaction():
                self._c.execute(
                    "INSERT INTO verification_authorizations (authorization_id, project_id,"
                    " episode_id, hypothesis_id, prediction_ids, capability_id, declaration_hash,"
                    " actor_id, rationale, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
                    (
                        authorization_id,
                        project_id,
                        str(row[0]),
                        hypothesis_id,
                        list(prediction_ids),
                        capability_id,
                        declared[1],
                        actor_id,
                        rationale,
                    ),
                )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) is None:
                raise
            raise _refused(exc) from exc
        found = self.get(authorization_id)
        assert found is not None  # just written
        return found

    def get(self, authorization_id: str) -> VerificationAuthorization | None:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM verification_authorizations WHERE authorization_id = %s",
            (authorization_id,),
        ).fetchone()
        return None if row is None else _authorization(row)

    def unbound(self, project_id: str, episode_id: str) -> tuple[VerificationAuthorization, ...]:
        """Authorizations of this episode whose test has not run yet, oldest first."""
        rows = self._c.execute(
            f"SELECT {_COLUMNS} FROM verification_authorizations a"
            " WHERE project_id = %s AND episode_id = %s AND NOT EXISTS ("
            "   SELECT 1 FROM verification_authorization_jobs b"
            "    WHERE b.authorization_id = a.authorization_id)"
            " ORDER BY created_at, authorization_id",
            (project_id, episode_id),
        ).fetchall()
        return tuple(_authorization(r) for r in rows)

    def bind(self, authorization_id: str, job_id: str) -> None:
        """License `job_id` -- still QUEUED, with no Run -- as this authorization's one test."""
        try:
            with self._c.transaction():
                self._c.execute(
                    "INSERT INTO verification_authorization_jobs (authorization_id, job_id,"
                    " bound_at) VALUES (%s, %s, now())",
                    (authorization_id, job_id),
                )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) is None:
                raise
            raise _refused(exc) from exc

    def for_job(self, job_id: str) -> VerificationAuthorization | None:
        row = self._c.execute(
            f"SELECT {', '.join('a.' + c.strip() for c in _COLUMNS.split(','))}"
            " FROM verification_authorizations a JOIN verification_authorization_jobs b"
            " ON b.authorization_id = a.authorization_id WHERE b.job_id = %s",
            (job_id,),
        ).fetchone()
        return None if row is None else _authorization(row)


def support_problem(connection: Any, relation: RelationJudgment) -> str | None:
    """Why `011s` would refuse `relation` as SUPPORT, or None (also None when it is not a SUPPORTS
    of a post-screening hypothesis). The database's own rules, asked before writing."""
    if relation.relation_type is not RelationType.SUPPORTS:
        return None
    row = connection.execute(
        "SELECT prospective_basis_problem(c, h.created_at, %s, %s)"
        "  FROM screening_conditioned_hypotheses c"
        "  JOIN hypotheses h ON h.project_id = c.project_id AND h.hypothesis_id = c.hypothesis_id"
        " WHERE c.project_id = %s AND c.hypothesis_id = %s",
        (
            relation.from_entity_id,
            relation.attributes.get("prediction_id"),
            relation.project_id,
            relation.to_entity_id,
        ),
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def as_context(relation: RelationJudgment, reason: str) -> RelationJudgment:
    """The same observation recorded against the hypothesis as context, not as support."""
    return relation.model_copy(
        update={
            "relation_type": RelationType.CITES,
            "attributes": {
                **relation.attributes,
                "declared_effect": relation.relation_type.value,
                "not_support": reason,
            },
        }
    )


class ProspectiveEvidenceSink:
    """An evidence sink that records a SUPPORTS `011s` would refuse as CITES, with the reason.

    A verification run whose outcome a post-screening hypothesis predicted is real evidence; it is
    kept as context instead of failing the run. It never supports: the database would refuse it.
    """

    def __init__(self, sink: Any, connection: Any) -> None:
        self._sink = sink
        self._c = connection
        self.downgraded: list[tuple[str, str]] = []

    def add_relation(self, relation: RelationJudgment) -> RelationJudgment:
        problem = support_problem(self._c, relation)
        if problem is None:
            return self._sink.add_relation(relation)  # type: ignore[no-any-return]
        self.downgraded.append((relation.relation_id, problem))
        return self._sink.add_relation(as_context(relation, problem))  # type: ignore[no-any-return]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sink, name)


class AuthorizedJobs:
    """The loop's JobStore, binding each Job of an authorized capability to the oldest unbound
    authorization of this episode for it -- while the Job is QUEUED, before it runs."""

    def __init__(self, jobs: Any, authorizations: SqlVerificationAuthorizations) -> None:
        self._jobs = jobs
        self._authorizations = authorizations
        self.bound: list[tuple[str, str]] = []

    def submit(self, job: Job) -> Job:
        submitted = self._jobs.submit(job)
        if submitted.episode_id is None:
            return submitted  # type: ignore[no-any-return]
        for authorization in self._authorizations.unbound(
            submitted.project_id, submitted.episode_id
        ):
            if authorization.capability_id == submitted.capability_id:
                self._authorizations.bind(authorization.authorization_id, submitted.job_id)
                self.bound.append((authorization.authorization_id, submitted.job_id))
                break
        return submitted  # type: ignore[no-any-return]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._jobs, name)


@dataclass(frozen=True)
class MeasurementExport:
    """What a person measured: the instrument's export, and when the data was taken."""

    name: str
    media_type: str
    data: bytes
    captured_at: dt.datetime
    #: The instrument or station, as the person names it.
    device: str
    #: The outcome the person read from it, in the capability's declared space.
    reading: ObservedOutcome
    started_at: dt.datetime | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


def _episode_predictions(connection: Any, project_id: str, episode_id: str) -> list[Prediction]:
    hypotheses = SqlHypothesisStore(connection)
    found: list[Prediction] = []
    for (hypothesis_id,) in connection.execute(
        "SELECT hypothesis_id FROM hypotheses WHERE project_id = %s AND created_in_episode = %s"
        " ORDER BY hypothesis_id",
        (project_id, episode_id),
    ).fetchall():
        certificate = hypotheses.get_certificate(project_id, str(hypothesis_id))
        if certificate is not None:
            found.extend(certificate.predictions)
    return found


def record_authorized_measurement(
    *,
    connection: Any,
    outputs: SqlRunOutputSink,
    authorization_id: str,
    export: MeasurementExport,
    measured_by: str,
    trace_id: str,
    conditions: Mapping[str, Any],
    conditions_schema_version: str,
    compare: Callable[[Mapping[str, Any], Mapping[str, Any], str], ConditionMatch],
    mint: Callable[[str], str],
    now: Callable[[], dt.datetime],
) -> tuple[RunEvidence, tuple[RelationJudgment, ...]]:
    """Record a person's measurement as the one test `authorization_id` licensed.

    Job (bound while QUEUED) -> Run (output: the export, with its capture time) -> Observation ->
    Attestation (through the admission gate) -> relations from every prediction of the episode the
    outcome matches. A SUPPORTS `011s` refuses is recorded as CITES with the reason. Returns the
    evidence and the relations as stored.
    """
    authorizations = SqlVerificationAuthorizations(connection)
    authorization = authorizations.get(authorization_id)
    if authorization is None:
        raise ProspectiveRefused(f"no verification authorization {authorization_id}")
    declared = declared_kind(connection, authorization.capability_id)
    if declared is None or declared[0] not in EMPIRICAL_KINDS:
        raise ProspectiveRefused(
            f"{authorization.capability_id} is not a declared measurement; a person's export is "
            "recorded only as the output of a MEASUREMENT or FABRICATION"
        )
    capability = PostgresCapabilityStore(connection).get(authorization.capability_id)
    assert capability is not None  # declared implies registered (foreign key)
    at = now()
    if export.captured_at > at:
        raise ProspectiveRefused(
            f"the export says it was captured at {export.captured_at}, after now ({at}); a "
            "capture time in the future is not a record"
        )
    if export.reading.observable_ref not in capability.produces:
        raise ProspectiveRefused(
            f"{capability.capability_id} does not produce {export.reading.observable_ref}"
        )
    started = export.started_at or export.captured_at
    jobs = SqlJobStore(connection)
    job = jobs.submit(
        Job(
            job_id=mint("job"),
            project_id=authorization.project_id,
            episode_id=authorization.episode_id,
            capability_id=capability.capability_id,
            trace_id=trace_id,
            idempotency_key=f"vauth:{authorization.authorization_id}",
            # A measurement taken before it was submitted says so: the job records that time,
            # and `011s` then refuses it as begun before its authorization.
            submitted_at=min(at, started),
        )
    )
    authorizations.bind(authorization.authorization_id, job.job_id)
    artifact_id = outputs.put(
        project_id=authorization.project_id, media_type=export.media_type, data=export.data
    )
    connection.execute(
        "UPDATE artifacts SET captured_at = %s, author_or_device = %s, actor_id = %s"
        " WHERE artifact_id = %s AND captured_at IS NULL",
        (export.captured_at, export.device, measured_by, artifact_id),
    )
    manifest = {
        "authorization_id": authorization.authorization_id,
        "export": artifact_id,
        "captured_at": export.captured_at.isoformat(),
        "device": export.device,
        "measured_by": measured_by,
    }
    run = jobs.complete(
        job.job_id,
        job.idempotency_key,
        Run(
            run_id=mint("run"),
            job_id=job.job_id,
            project_id=authorization.project_id,
            capability_id=capability.capability_id,
            backend_id=capability.backend_id,
            domain=capability.domain,
            trace_id=trace_id,
            input_artifacts=(),
            input_parameters={"authorization_id": authorization.authorization_id},
            conditions=dict(conditions),
            conditions_schema_version=conditions_schema_version,
            environment={"device": export.device, "measured_by": measured_by},
            code_provenance=f"person:{measured_by}",
            backend_validity={},
            status=RunStatus.SUCCEEDED,
            output_artifacts=(artifact_id,),
            start_time=started,
            end_time=max(started, export.captured_at),
            reproducibility_manifest_hash=canonical_hash(manifest),
        ),
    )
    sink = SqlEvidenceSink(connection=connection, outputs=outputs)
    match = compare(dict(run.conditions), dict(conditions), conditions_schema_version)
    stored_match = sink.add_condition_match(
        match.model_copy(update={"condition_match_id": mint("condition_match"), "created_at": at})
    )
    evidence = evidence_from_run(
        run=run,
        outcome=export.reading,
        predictions=_episode_predictions(
            connection, authorization.project_id, authorization.episode_id
        ),
        condition_match=stored_match,
        actor_id=measured_by,
        mint=mint,
        at=at,
    )
    gate = EvidenceAdmissionGate(
        load_artifact=sink.load_artifact,
        load_evidence_unit=lambda _unit: None,
        load_run=jobs.get_run,
        is_artifact_in_project=sink.artifact_in_project,
    )
    attestation = gate.admit(AdmissionRequest(attestation=evidence.attestation))
    sink.add_observation(evidence.observation)
    sink.add_attestation(attestation)
    guarded = ProspectiveEvidenceSink(sink, connection)
    stored = tuple(guarded.add_relation(r) for r in evidence.relations)
    return evidence, stored


__all__ = [
    "EMPIRICAL_KINDS",
    "AuthorizedJobs",
    "MeasurementExport",
    "ProspectiveEvidenceSink",
    "ProspectiveRefused",
    "SqlVerificationAuthorizations",
    "VerificationAuthorization",
    "as_context",
    "record_authorized_measurement",
    "support_problem",
]
