"""Measurement provenance (G0 residual T-1, prototype): a measurement counts as its signer says.

THE THREAT. The services' role writes runs, observations and attestations; it is the path every
real measurement takes into the database. A compromised or mistaken services process can store a
measurement no instrument made, and nothing in the row tells it apart.

THE BOUNDARY. A key the services never hold. The instrument host or simulation runner keeps an
Ed25519 key (`MeasurementRunner`, its own process and file permissions); the schema owner enrols
its public key for one instrument (a `runs.backend_id`) and the capabilities it may sign for
(`003f`, owner only). For each run request (a Job) the database issues a nonce; when the run is
over the runner signs `measurement_statement` -- the job and run ids, that nonce, the capability,
the instrument, the digest of the raw output bytes it produced, and the time -- and the services
relay the signature. `MeasurementProvenance` verifies it against what the database holds now and
fails closed: anything but VERIFIED is not counted as support for an enforced (instrument,
capability).

WHAT A VERIFIED MEASUREMENT MEANS. The holder of an enrolled, unrevoked key signed, after the
database issued the job's nonce, that this capability on this instrument produced exactly these
output bytes for this job and run. It does NOT mean the bytes describe the physical world (a lying
sensor, a mis-configured instrument), that the runner's host was honest (whoever holds the key
signs anything), that the key was not stolen, or that the observation value the services extracted
from the bytes is faithful -- the observation row is still the services' write.

ENFORCEMENT. The deployment setting `LAB_BRAIN_MEASUREMENT_PROVENANCE` (the Owner's):
    enrolled (default)  per (instrument, capability): once any key was ever enrolled for the pair,
                        a measurement of it must verify; a pair with no enrolment is NOT_REQUIRED
                        and keeps counting, labelled unverified (the product's offline backends,
                        whose runner is the services' own process today, are unchanged);
    strict              every measurement must verify; anything else is not support.
Any other value is read as strict (fail closed). An attestation with no run behind it is not a
measurement and is left to the other rules. Every `SqlRelationStore` applies it to every SUPPORTS
it admits or re-checks, so all product readers share one definition.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from lab_brain.core.canonical_json import canonical_bytes, canonical_hash
from lab_brain.core.models import RelationJudgment, RelationType
from lab_brain.security.reviewer_identity import SigningKey

#: Domain separation: a measurement signature is never a valid enrolment, answer or authorization.
STATEMENT_KIND = "lab-brain/measurement-provenance"
STATEMENT_VERSION = 1
#: How far a runner's clock may run ahead of the database's when it dates a measurement.
SKEW = dt.timedelta(minutes=5)
#: The deployment setting naming the enforcement mode.
MODE_ENV = "LAB_BRAIN_MEASUREMENT_PROVENANCE"


def strict_mode(env: Mapping[str, str] | None = None) -> bool:
    """Whether every measurement must verify. Unset or `enrolled`: per enrolled pair only."""
    value = (os.environ if env is None else env).get(MODE_ENV, "enrolled").strip().lower()
    return value != "enrolled"


def raw_digest(content_hashes: Iterable[str]) -> str:
    """The digest of a run's raw outputs: the canonical hash of their sorted content hashes
    (`artifacts.content_hash`, `sha256:<hex>` of the bytes)."""
    return canonical_hash(sorted(content_hashes))


def content_hash(data: bytes) -> str:
    """What the artifact store records for `data`."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _instant(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("a measurement time is timezone-aware")
    return value.astimezone(dt.UTC).isoformat(timespec="microseconds")


def measurement_statement(
    *,
    job_id: str,
    run_id: str,
    nonce: str,
    capability_id: str,
    instrument_id: str,
    digest: str,
    measured_at: dt.datetime,
) -> bytes:
    """The exact bytes a runner signs: canonical JSON, versioned, with its own kind."""
    return canonical_bytes(
        {
            "kind": STATEMENT_KIND,
            "version": STATEMENT_VERSION,
            "job_id": job_id,
            "run_id": run_id,
            "nonce": nonce,
            "capability_id": capability_id,
            "instrument_id": instrument_id,
            "raw_digest": digest,
            "measured_at": _instant(measured_at),
        }
    )


@dataclass(frozen=True)
class SignedMeasurement:
    """What a runner hands back to the services, to be relayed into `measurement_signatures`."""

    job_id: str
    run_id: str
    nonce: str
    key_id: str
    raw_digest: str
    measured_at: dt.datetime
    signature: str


class MeasurementRunner:
    """The instrument host or simulation runner: holds the private key, which the services do not.

    It computes the digest from the raw bytes it produced itself -- never from a digest a caller
    hands it -- and signs only for its own instrument and its enrolled capabilities.
    """

    def __init__(
        self, key: SigningKey, *, instrument_id: str, capability_ids: Iterable[str]
    ) -> None:
        self._key = key
        self.instrument_id = instrument_id
        self.capability_ids = frozenset(capability_ids)

    @property
    def public_key(self) -> str:
        return self._key.public_key

    @property
    def key_id(self) -> str:
        return self._key.key_id

    def sign(
        self,
        *,
        job_id: str,
        run_id: str,
        nonce: str,
        capability_id: str,
        outputs: Sequence[bytes],
        measured_at: dt.datetime,
    ) -> SignedMeasurement:
        if capability_id not in self.capability_ids:
            raise ValueError(f"{self.instrument_id} does not sign for {capability_id}")
        if not outputs:
            raise ValueError("a measurement with no raw output is not signed")
        digest = raw_digest(content_hash(b) for b in outputs)
        statement = measurement_statement(
            job_id=job_id,
            run_id=run_id,
            nonce=nonce,
            capability_id=capability_id,
            instrument_id=self.instrument_id,
            digest=digest,
            measured_at=measured_at,
        )
        return SignedMeasurement(
            job_id=job_id,
            run_id=run_id,
            nonce=nonce,
            key_id=self._key.key_id,
            raw_digest=digest,
            measured_at=measured_at,
            signature=self._key.sign(statement),
        )


class ProvenanceStatus(StrEnum):
    #: Signed by an enrolled, unrevoked key for this instrument and capability, over this run.
    VERIFIED = "VERIFIED"
    #: No key was ever enrolled for this (instrument, capability): unverified, still counted.
    NOT_REQUIRED = "NOT_REQUIRED"
    UNSIGNED = "UNSIGNED"
    UNKNOWN_KEY = "UNKNOWN_KEY"
    KEY_REVOKED = "KEY_REVOKED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NONCE_MISMATCH = "NONCE_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    TIME_MISMATCH = "TIME_MISMATCH"
    BAD_SIGNATURE = "BAD_SIGNATURE"
    NO_RUN = "NO_RUN"

    @property
    def counts(self) -> bool:
        """Whether a measurement in this state may be counted as evidence (NOT_REQUIRED is given
        only where the mode does not require a signature)."""
        return self in (ProvenanceStatus.VERIFIED, ProvenanceStatus.NOT_REQUIRED)

    @property
    def verified(self) -> bool:
        return self is ProvenanceStatus.VERIFIED


@dataclass(frozen=True)
class Provenance:
    status: ProvenanceStatus
    detail: str


def _verify(public_key: str, signature: str, message: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True)).verify(
            base64.b64decode(signature, validate=True), message
        )
    except (InvalidSignature, ValueError):
        return False
    return True


class MeasurementProvenance:
    """The reader: what the database holds about a run's measurement provenance, verified now."""

    def __init__(
        self, connection: Any, *, strict: bool | None = None, skew: dt.timedelta = SKEW
    ) -> None:
        self._c = connection
        self._skew = skew
        self.strict = strict_mode() if strict is None else strict

    def enforced(self, instrument_id: str, capability_id: str) -> bool:
        """Whether any key was ever enrolled for this pair (revoked keys included: revoking the
        only key must not switch the requirement off)."""
        row = self._c.execute(
            "SELECT 1 FROM measurement_signing_keys"
            " WHERE instrument_id = %s AND %s = ANY (capability_ids) LIMIT 1",
            (instrument_id, capability_id),
        ).fetchone()
        return row is not None

    def run(self, run_id: str) -> Provenance:
        found = self._c.execute(
            "SELECT job_id, capability_id, backend_id, output_artifacts FROM runs"
            " WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if found is None:
            return Provenance(ProvenanceStatus.NO_RUN, f"no run {run_id} is recorded")
        job_id, capability_id, instrument_id, outputs = found
        signed = self._c.execute(
            "SELECT s.job_id, s.nonce, s.key_id, s.raw_digest, s.measured_at, s.signature,"
            " s.recorded_at, n.job_id, n.issued_at"
            " FROM measurement_signatures s LEFT JOIN measurement_nonces n ON n.nonce = s.nonce"
            " WHERE s.run_id = %s",
            (run_id,),
        ).fetchone()
        if signed is None:
            if self.strict or self.enforced(instrument_id, capability_id):
                return Provenance(
                    ProvenanceStatus.UNSIGNED,
                    f"run {run_id} of {capability_id} on {instrument_id} carries no signature, "
                    "and that instrument signs its measurements",
                )
            return Provenance(
                ProvenanceStatus.NOT_REQUIRED,
                f"no signing key is enrolled for {capability_id} on {instrument_id}: unverified",
            )
        s_job, nonce, key, digest, measured_at, signature, recorded_at, n_job, issued_at = signed
        if s_job != job_id or n_job != job_id:
            return Provenance(
                ProvenanceStatus.NONCE_MISMATCH,
                f"the signature of run {run_id} is bound to job {s_job} / nonce of {n_job}, "
                f"not to its job {job_id}",
            )
        enrolled = self._c.execute(
            "SELECT k.public_key, k.instrument_id, k.capability_ids, r.revoked_at"
            " FROM measurement_signing_keys k"
            " LEFT JOIN measurement_signing_key_revocations r ON r.key_id = k.key_id"
            " WHERE k.key_id = %s",
            (key,),
        ).fetchone()
        if enrolled is None:
            return Provenance(ProvenanceStatus.UNKNOWN_KEY, f"key {key} is not enrolled")
        public_key, key_instrument, key_capabilities, revoked_at = enrolled
        if revoked_at is not None and revoked_at <= recorded_at:
            return Provenance(
                ProvenanceStatus.KEY_REVOKED,
                f"key {key} was revoked at {revoked_at}, before run {run_id}'s signature arrived",
            )
        if key_instrument != instrument_id or capability_id not in key_capabilities:
            return Provenance(
                ProvenanceStatus.OUT_OF_SCOPE,
                f"key {key} signs for {sorted(key_capabilities)} on {key_instrument}, not "
                f"{capability_id} on {instrument_id}",
            )
        hashes = [
            str(r[0])
            for r in self._c.execute(
                "SELECT content_hash FROM artifacts WHERE artifact_id = ANY (%s)", (list(outputs),)
            ).fetchall()
        ]
        if len(hashes) != len(set(outputs)) or raw_digest(hashes) != digest:
            return Provenance(
                ProvenanceStatus.DIGEST_MISMATCH,
                f"run {run_id}'s recorded outputs are not the raw bytes its signer measured",
            )
        if not (issued_at <= measured_at <= recorded_at + self._skew):
            return Provenance(
                ProvenanceStatus.TIME_MISMATCH,
                f"run {run_id} is dated {measured_at}, outside [{issued_at} (nonce issued), "
                f"{recorded_at} + {self._skew} (signature recorded)]",
            )
        statement = measurement_statement(
            job_id=job_id,
            run_id=run_id,
            nonce=nonce,
            capability_id=capability_id,
            instrument_id=instrument_id,
            digest=digest,
            measured_at=measured_at,
        )
        if not _verify(public_key, signature, statement):
            return Provenance(
                ProvenanceStatus.BAD_SIGNATURE,
                f"the signature of run {run_id} does not verify under key {key}",
            )
        return Provenance(ProvenanceStatus.VERIFIED, f"run {run_id} signed by {key}")

    def attestation(self, project_id: str, attestation_id: str) -> Provenance | None:
        """The provenance of the run behind an attestation, or None if no run stands behind it
        (not a measurement: literature, a person's reading)."""
        row = self._c.execute(
            "SELECT coalesce(a.run_id, o.run_id) FROM attestations a"
            " LEFT JOIN observations o"
            "   ON o.observation_id = a.observation_id AND o.project_id = a.project_id"
            " WHERE a.attestation_id = %s AND a.project_id = %s",
            (attestation_id, project_id),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return self.run(str(row[0]))

    def support_problem(self, relation: RelationJudgment) -> str | None:
        """Why a SUPPORTS is not support on measurement provenance, or None: every supporting
        attestation whose run measured with an enforced (instrument, capability) must verify."""
        if relation.relation_type is not RelationType.SUPPORTS:
            return None
        for attestation_id in relation.supporting_attestation_ids:
            found = self.attestation(relation.project_id, attestation_id)
            if found is not None and not found.status.counts:
                return f"{attestation_id}: measurement provenance {found.status}: {found.detail}"
        return None


def relay(connection: Any, signed: SignedMeasurement) -> None:
    """The services' part: record what the runner returned (they cannot forge it)."""
    connection.execute(
        "INSERT INTO measurement_signatures (run_id, job_id, nonce, key_id, raw_digest,"
        " measured_at, signature, recorded_at, recorded_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, now(), '')",
        (
            signed.run_id,
            signed.job_id,
            signed.nonce,
            signed.key_id,
            signed.raw_digest,
            signed.measured_at,
            signed.signature,
        ),
    )


def issue_nonce(connection: Any, job_id: str) -> str:
    """The database's nonce for a job that has not finished (`003f`); one per job."""
    row = connection.execute(
        "INSERT INTO measurement_nonces (nonce, job_id, issued_at, issued_by)"
        " VALUES ('', %s, now(), '') RETURNING nonce",
        (job_id,),
    ).fetchone()
    return str(row[0])


def enrol(
    connection: Any,
    *,
    public_key: str,
    key_id: str,
    instrument_id: str,
    capability_ids: Sequence[str],
    reason: str,
    actor_id: str,
) -> None:
    """The schema owner's enrolment of a runner's public key (refused for anyone else)."""
    connection.execute(
        "INSERT INTO measurement_signing_keys (key_id, public_key, instrument_id, capability_ids,"
        " reason, actor_id, enrolled_at, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, now(), '')",
        (key_id, public_key, instrument_id, list(capability_ids), reason, actor_id),
    )


def revoke(connection: Any, *, key_id: str, reason: str, actor_id: str) -> None:
    connection.execute(
        "INSERT INTO measurement_signing_key_revocations (key_id, reason, actor_id, revoked_at,"
        " recorded_by) VALUES (%s, %s, %s, now(), '')",
        (key_id, reason, actor_id),
    )


def combined(
    *checks: Callable[[RelationJudgment], str | None] | None,
) -> Callable[[RelationJudgment], str | None]:
    """A support verifier that reports the first problem any of `checks` finds."""

    def check(relation: RelationJudgment) -> str | None:
        for one in checks:
            if one is not None and (problem := one(relation)) is not None:
                return problem
        return None

    return check
