"""The measurement statement and its signer (G0 T-1 prototype, no database).

Every field the statement binds changes the bytes signed, so a signature made for one run, job,
nonce, capability, instrument, raw output or time does not verify for another; the runner computes
the digest from the bytes it produced and signs only for its own capabilities.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from lab_brain.security.measurement_provenance import (
    MODE_ENV,
    MeasurementRunner,
    ProvenanceStatus,
    _verify,
    content_hash,
    measurement_statement,
    raw_digest,
    strict_mode,
)
from lab_brain.security.reviewer_identity import SigningKey

AT = dt.datetime(2026, 11, 21, 9, 0, tzinfo=dt.UTC)
FIELDS = {
    "job_id": "job:1",
    "run_id": "run:1",
    "nonce": "n-1",
    "capability_id": "cap:probe",
    "instrument_id": "lab.probe_station",
    "digest": raw_digest([content_hash(b"raw")]),
    "measured_at": AT,
}


def _runner() -> MeasurementRunner:
    return MeasurementRunner(
        SigningKey.generate(), instrument_id="lab.probe_station", capability_ids=("cap:probe",)
    )


def _signed(runner: MeasurementRunner) -> tuple[bytes, str]:
    signed = runner.sign(
        job_id="job:1",
        run_id="run:1",
        nonce="n-1",
        capability_id="cap:probe",
        outputs=(b"raw",),
        measured_at=AT,
    )
    return measurement_statement(**FIELDS), signed.signature  # type: ignore[arg-type]


def test_the_signature_verifies_over_exactly_the_statement() -> None:
    runner = _runner()
    statement, signature = _signed(runner)
    assert _verify(runner.public_key, signature, statement)


@pytest.mark.parametrize(
    ("field", "other"),
    [
        ("job_id", "job:2"),
        ("run_id", "run:2"),
        ("nonce", "n-2"),
        ("capability_id", "cap:other"),
        ("instrument_id", "lab.other_station"),
        ("digest", raw_digest([content_hash(b"made up")])),
        ("measured_at", AT + dt.timedelta(microseconds=1)),
    ],
)
def test_every_bound_field_changes_what_verifies(field: str, other: object) -> None:
    runner = _runner()
    _, signature = _signed(runner)
    assert not _verify(
        runner.public_key, signature, measurement_statement(**{**FIELDS, field: other})
    )  # type: ignore[arg-type]


def test_another_key_does_not_verify() -> None:
    _, signature = _signed(_runner())
    statement = measurement_statement(**FIELDS)  # type: ignore[arg-type]
    assert not _verify(_runner().public_key, signature, statement)


def test_the_statement_is_domain_separated_and_versioned() -> None:
    statement = measurement_statement(**FIELDS)  # type: ignore[arg-type]
    assert b'"kind":"lab-brain/measurement-provenance"' in statement
    assert b'"version":1' in statement


def test_the_runner_signs_only_its_capabilities_and_only_raw_bytes() -> None:
    runner = _runner()
    with pytest.raises(ValueError, match="does not sign"):
        runner.sign(
            job_id="j",
            run_id="r",
            nonce="n",
            capability_id="cap:other",
            outputs=(b"x",),
            measured_at=AT,
        )
    with pytest.raises(ValueError, match="no raw output"):
        runner.sign(
            job_id="j",
            run_id="r",
            nonce="n",
            capability_id="cap:probe",
            outputs=(),
            measured_at=AT,
        )
    signed = runner.sign(
        job_id="j",
        run_id="r",
        nonce="n",
        capability_id="cap:probe",
        outputs=(b"b", b"a"),
        measured_at=AT,
    )
    assert signed.raw_digest == raw_digest([content_hash(b"a"), content_hash(b"b")])
    assert dataclasses.replace(signed).key_id == runner.key_id


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        measurement_statement(**{**FIELDS, "measured_at": AT.replace(tzinfo=None)})  # type: ignore[arg-type]


def test_the_mode_fails_closed() -> None:
    assert not strict_mode({})
    assert not strict_mode({MODE_ENV: "enrolled"})
    assert strict_mode({MODE_ENV: "strict"})
    assert strict_mode({MODE_ENV: "typo"})


def test_only_verified_and_not_required_count() -> None:
    counting = {s for s in ProvenanceStatus if s.counts}
    assert counting == {ProvenanceStatus.VERIFIED, ProvenanceStatus.NOT_REQUIRED}
