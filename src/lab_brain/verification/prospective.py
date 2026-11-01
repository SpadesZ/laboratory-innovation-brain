"""Authorized, prospective verification of a hypothesis proposed after screening (`011s`).

A hypothesis its author proposed after seeing a screening reading cannot be supported by that
reading, by anything that existed before the hypothesis, or by a check nobody pre-registered.
`011s` holds those rules for every writer. This module is the governed path that lets a GENUINE
later check be recorded:

    1. authorize   an accountable person (an active HUMAN member of the project) pre-registers a
                   test: this post-screening hypothesis, these of its predictions, this DECLARED
                   capability, and why -- and SIGNS it (011w) with the key a review authority
                   enrolled for them as an authorizer in this project. The database dates it by
                   its own clock, after the hypothesis, checks the signature's frame, and never
                   lets it change; the signature itself is verified here, on every read that
                   counts it (`authorization_problem`): an authorization that does not verify
                   licenses nothing.
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
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.job import Job, Run, RunStatus
from lab_brain.core.models.prediction import Prediction
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.reviewer import (
    VERIFICATION_AUTHORIZATION_SCOPE,
    ReviewerEnrolment,
    ReviewerKeyRevocation,
    authorization_statement,
)
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.ingestion.admission_gate import AdmissionRequest, EvidenceAdmissionGate
from lab_brain.security.reviewer_identity import IdentityUnverified, ReviewerTrust, SigningKey
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
    #: 011w: the person's signature, its enrolment and the signer's time. None on a row written
    #: before 011w -- which licenses nothing.
    enrolment_id: str | None = None
    signature: str | None = None
    signed_at: dt.datetime | None = None

    def statement(self) -> bytes:
        """The exact bytes the person signed (`core.models.reviewer.authorization_statement`)."""
        if self.signed_at is None:
            raise ValueError(f"{self.authorization_id} is unsigned")
        return authorization_statement(
            authorization_id=self.authorization_id,
            project_id=self.project_id,
            episode_id=self.episode_id,
            hypothesis_id=self.hypothesis_id,
            prediction_ids=self.prediction_ids,
            capability_id=self.capability_id,
            declaration_hash=self.declaration_hash,
            actor_id=self.actor_id,
            rationale=self.rationale,
            signed_at=self.signed_at,
            enrolment_id=self.enrolment_id or "",
        )


@dataclass(frozen=True)
class AuthorizationSigner:
    """What `authorize` needs to sign: whose authorization, under which enrolment, and the key.
    The key is the person's -- held on their machine, never written to the database."""

    actor_id: str
    enrolment_id: str
    key: SigningKey


_COLUMNS = (
    "authorization_id, project_id, episode_id, hypothesis_id, prediction_ids, capability_id,"
    " declaration_hash, actor_id, rationale, created_at, enrolment_id, signature, signed_at"
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
        enrolment_id=None if row[10] is None else str(row[10]),
        signature=None if row[11] is None else str(row[11]),
        signed_at=row[12],
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
        signer: AuthorizationSigner,
        signed_at: dt.datetime | None = None,
    ) -> VerificationAuthorization:
        """Pre-register a test, signed by `signer` (011w). The database checks everything else
        and dates it (`011s`); the signature is verified on every read that counts it."""
        if signer.actor_id != actor_id:
            raise ProspectiveRefused(
                f"{signer.actor_id}'s key cannot sign an authorization by {actor_id}"
            )
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
        unsigned = VerificationAuthorization(
            authorization_id=authorization_id,
            project_id=project_id,
            episode_id=str(row[0]),
            hypothesis_id=hypothesis_id,
            prediction_ids=tuple(prediction_ids),
            capability_id=capability_id,
            declaration_hash=declared[1],
            actor_id=actor_id,
            rationale=rationale,
            created_at=dt.datetime.now(dt.UTC),
            enrolment_id=signer.enrolment_id,
            signed_at=signed_at or dt.datetime.now(dt.UTC),
        )
        signature = signer.key.sign(unsigned.statement())
        try:
            with self._c.transaction():
                self._c.execute(
                    "INSERT INTO verification_authorizations (authorization_id, project_id,"
                    " episode_id, hypothesis_id, prediction_ids, capability_id, declaration_hash,"
                    " actor_id, rationale, created_at, enrolment_id, signature, signed_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s)",
                    (
                        authorization_id,
                        project_id,
                        unsigned.episode_id,
                        hypothesis_id,
                        list(prediction_ids),
                        capability_id,
                        declared[1],
                        actor_id,
                        rationale,
                        signer.enrolment_id,
                        signature,
                        unsigned.signed_at,
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


# -- authorizer keys (011w) -----------------------------------------------------------------------

_ENROLMENT_COLUMNS = (
    "enrolment_id, project_id, actor_id, public_key, scope, enrolled_at, authority_actor_id,"
    " authority_key_id, authority_signature"
)
_REVOCATION_COLUMNS = (
    "revocation_id, enrolment_id, project_id, effective_at, reason, authority_actor_id,"
    " authority_key_id, authority_signature"
)


def enrol_authorizer(connection: Any, enrolment: ReviewerEnrolment) -> ReviewerEnrolment:
    """Record an authority-signed VERIFICATION_AUTHORIZATION enrolment. The database checks its
    frame (an active human member, one key one person); the authority's signature is checked on
    every read that relies on it."""
    if enrolment.scope != VERIFICATION_AUTHORIZATION_SCOPE:
        raise ProspectiveRefused(
            f"enrolment {enrolment.enrolment_id} is for {enrolment.scope}, not "
            f"{VERIFICATION_AUTHORIZATION_SCOPE}"
        )
    try:
        with connection.transaction():
            connection.execute(
                f"INSERT INTO verification_authorizer_enrolments ({_ENROLMENT_COLUMNS}, key_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    enrolment.enrolment_id,
                    enrolment.project_id,
                    enrolment.actor_id,
                    enrolment.public_key,
                    enrolment.scope,
                    enrolment.enrolled_at,
                    enrolment.authority_actor_id,
                    enrolment.authority_key_id,
                    enrolment.authority_signature,
                    enrolment.key_id,
                ),
            )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) is None:
            raise
        raise _refused(exc) from exc
    return enrolment


def revoke_authorizer(connection: Any, revocation: ReviewerKeyRevocation) -> ReviewerKeyRevocation:
    try:
        with connection.transaction():
            connection.execute(
                f"INSERT INTO verification_authorizer_revocations ({_REVOCATION_COLUMNS})"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    revocation.revocation_id,
                    revocation.enrolment_id,
                    revocation.project_id,
                    revocation.effective_at,
                    revocation.reason,
                    revocation.authority_actor_id,
                    revocation.authority_key_id,
                    revocation.authority_signature,
                ),
            )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) is None:
            raise
        raise _refused(exc) from exc
    return revocation


def _enrolment_of(connection: Any, project_id: str, enrolment_id: str) -> ReviewerEnrolment | None:
    row = connection.execute(
        f"SELECT {_ENROLMENT_COLUMNS} FROM verification_authorizer_enrolments"
        " WHERE project_id = %s AND enrolment_id = %s",
        (project_id, enrolment_id),
    ).fetchone()
    if row is None:
        return None
    return ReviewerEnrolment.model_validate(
        dict(zip(_ENROLMENT_COLUMNS.split(", "), row, strict=True))
    )


def _revocations_of(
    connection: Any, project_id: str, enrolment_id: str
) -> tuple[ReviewerKeyRevocation, ...]:
    rows = connection.execute(
        f"SELECT {_REVOCATION_COLUMNS} FROM verification_authorizer_revocations"
        " WHERE project_id = %s AND enrolment_id = %s ORDER BY revocation_id",
        (project_id, enrolment_id),
    ).fetchall()
    return tuple(
        ReviewerKeyRevocation.model_validate(
            dict(zip(_REVOCATION_COLUMNS.split(", "), row, strict=True))
        )
        for row in rows
    )


def authorization_problem(
    connection: Any, authorization: VerificationAuthorization, trust: ReviewerTrust
) -> str | None:
    """Why `authorization` licenses nothing -- it is unsigned, or its signature, its enrolment or
    the authority's signature on it does not verify under the pinned authorities, or its key was
    revoked before it signed -- or None. Read on every use: nothing about a verdict is cached."""
    enrolment = (
        None
        if authorization.enrolment_id is None
        else _enrolment_of(connection, authorization.project_id, authorization.enrolment_id)
    )
    revocations = (
        ()
        if enrolment is None
        else _revocations_of(connection, authorization.project_id, enrolment.enrolment_id)
    )
    try:
        trust.verify_authorization(
            what=f"authorization {authorization.authorization_id}",
            actor_id=authorization.actor_id,
            project_id=authorization.project_id,
            enrolment_id=authorization.enrolment_id,
            signature=authorization.signature,
            signed_at=authorization.signed_at,
            statement=authorization.statement() if authorization.signed_at else b"",
            enrolment=enrolment,
            revocations=revocations,
        )
    except IdentityUnverified as refused:
        return f"{refused} (011w): it licenses nothing"
    return None


def _trust(trust: ReviewerTrust | None) -> ReviewerTrust:
    return trust if trust is not None else ReviewerTrust.from_environment(os.environ)


def bound_authorization_problem(
    connection: Any,
    *,
    project_id: str,
    hypothesis_id: str,
    observation_id: str,
    attestation_ids: Sequence[str],
    trust: ReviewerTrust | None = None,
) -> str | None:
    """For a support of post-screening `hypothesis_id` resting on `observation_id` and the cited
    attestations: why an authorization a basis run is bound to does not verify
    (`authorization_problem`), or None. None also when the hypothesis is not post-screening, or no
    basis run is bound (the SQL rules report a missing authorization)."""
    conditioned = connection.execute(
        "SELECT 1 FROM screening_conditioned_hypotheses WHERE project_id = %s"
        " AND hypothesis_id = %s",
        (project_id, hypothesis_id),
    ).fetchone()
    if conditioned is None:
        return None
    ids = [
        str(r[0])
        for r in connection.execute(
            "SELECT DISTINCT b.authorization_id"
            "  FROM observations o"
            "  JOIN runs u ON u.run_id = o.run_id"
            "  JOIN verification_authorization_jobs b ON b.job_id = u.job_id"
            " WHERE o.observation_id = %s"
            "    OR o.observation_id IN (SELECT a.observation_id FROM attestations a"
            "                             WHERE a.attestation_id = ANY (%s))"
            " ORDER BY 1",
            (observation_id, list(attestation_ids)),
        ).fetchall()
    ]
    pinned = _trust(trust)
    store = SqlVerificationAuthorizations(connection)
    for authorization_id in ids:
        found = store.get(authorization_id)
        if found is None:  # pragma: no cover - a bound authorization always exists (FK)
            return f"authorization {authorization_id} is not recorded"
        problem = authorization_problem(connection, found, pinned)
        if problem is not None:
            return problem
    return None


def basis_authorization_problem(
    connection: Any, relation: RelationJudgment, trust: ReviewerTrust | None = None
) -> str | None:
    """`bound_authorization_problem` for one SUPPORTS relation; None for any other relation."""
    if relation.relation_type is not RelationType.SUPPORTS:
        return None
    return bound_authorization_problem(
        connection,
        project_id=relation.project_id,
        hypothesis_id=relation.to_entity_id,
        observation_id=relation.from_entity_id,
        attestation_ids=relation.supporting_attestation_ids,
        trust=trust,
    )


def support_problem(
    connection: Any, relation: RelationJudgment, trust: ReviewerTrust | None = None
) -> str | None:
    """Why `011s`/`011w` would refuse `relation` as SUPPORT, or None (also None when it is not a
    SUPPORTS of a post-screening hypothesis). The database's own rules, asked before writing --
    then the signatures of the authorizations it rests on, which only Python can verify."""
    if relation.relation_type is not RelationType.SUPPORTS:
        return None
    sql = _sql_support_problem(connection, relation)
    if sql is not None:
        return sql
    return basis_authorization_problem(connection, relation, trust)


def _sql_support_problem(connection: Any, relation: RelationJudgment) -> str | None:
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

    def __init__(self, sink: Any, connection: Any, trust: ReviewerTrust | None = None) -> None:
        self._sink = sink
        self._c = connection
        self._trust = trust
        self.downgraded: list[tuple[str, str]] = []

    def add_relation(self, relation: RelationJudgment) -> RelationJudgment:
        problem = support_problem(self._c, relation, self._trust)
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
    trust: ReviewerTrust | None = None,
) -> tuple[RunEvidence, tuple[RelationJudgment, ...]]:
    """Record a person's measurement as the one test `authorization_id` licensed.

    Job (bound while QUEUED) -> Run (output: the export, with its capture time) -> Observation ->
    Attestation (through the admission gate) -> relations from every prediction of the episode the
    outcome matches. A SUPPORTS `011s` refuses is recorded as CITES with the reason. Returns the
    evidence and the relations as stored. `trust`: the pinned review authorities the
    authorization's signature is checked against (default: `LAB_BRAIN_REVIEW_AUTHORITIES`).
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
    guarded = ProspectiveEvidenceSink(sink, connection, trust)
    stored = tuple(guarded.add_relation(r) for r in evidence.relations)
    return evidence, stored


__all__ = [
    "EMPIRICAL_KINDS",
    "AuthorizationSigner",
    "AuthorizedJobs",
    "MeasurementExport",
    "ProspectiveEvidenceSink",
    "ProspectiveRefused",
    "SqlVerificationAuthorizations",
    "VerificationAuthorization",
    "as_context",
    "authorization_problem",
    "basis_authorization_problem",
    "bound_authorization_problem",
    "enrol_authorizer",
    "record_authorized_measurement",
    "revoke_authorizer",
    "support_problem",
]
