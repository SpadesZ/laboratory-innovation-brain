"""G0 residual T-1 (High): a stored-but-fabricated measurement is accepted as evidence.

The services' role writes runs, observations and attestations: it is the path every real
measurement takes into the database. Nothing in a stored row tells a reading an instrument (or a
simulation runner) produced from one the services' process made up. Here the services' role
records a four-point-probe measurement that never happened -- an export artifact of its own bytes,
a SUCCEEDED Run on the probe station, an ELEVATED reading and its attestation -- for a test the
episode's person really did pre-register (`011s`, signed `011w`), and cites it as SUPPORTS.

The product's relation reader (the one every belief decision reads) must not admit it as support
once the deployment asks for measurement provenance (`LAB_BRAIN_MEASUREMENT_PROVENANCE=strict`:
a measurement counts only if a key the services never hold signed it). The setting is the Owner's;
the default leaves every unenrolled instrument's measurements counted, unverified.

Prototype (`003f`, `lab_brain.security.measurement_provenance`): the instrument's runner signs a
statement binding job, run, a database nonce, capability, instrument, raw-output digest and time;
the owner enrols its key; every `SqlRelationStore` verifies and fails closed. The tests below show
the fabricated measurement refused, a runner-signed one admitted, and each forgery the services
could attempt without the key labelled and refused.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import copy
import datetime as dt
from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from lab_brain.core.models import RelationType
from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.security.measurement_provenance import (
    MODE_ENV,
    MeasurementProvenance,
    MeasurementRunner,
    SignedMeasurement,
    enrol,
    issue_nonce,
    relay,
    revoke,
)
from lab_brain.security.reviewer_identity import SigningKey
from tests.e2e.test_g0_screening_independence_postgres import PROBE_METHOD, Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import _product_relations
from tests.e2e.test_g0_trust_boundaries_postgres import _try
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles


def _as(g: Guarded, connection: Any) -> Guarded:
    """The same episode's helpers, writing through `connection`."""
    other = copy.copy(g)
    other.db = connection
    other.jobs = SqlJobStore(connection)
    return other


def _fabricated(g: Guarded, app: Any, name: str) -> tuple[str, str]:
    """The person's real pre-registration; the services' role's made-up measurement of it and
    its SUPPORTS. Returns (observation, attestation)."""
    authorization = g.authorize(name)
    services = _as(g, app)
    observation, attestation = services.measured(name, authorization=authorization)
    services.support(observation, [attestation], prediction=g.prediction())
    return observation, attestation


def _admitted_support(g: Guarded, relations: Any) -> set[str]:
    return {
        r.relation_id
        for r in relations.admitted_for_subject(PROJECT, g.hypothesis)
        if r.relation_type is RelationType.SUPPORTS
    }


def test_t1_a_fabricated_measurement_is_not_admitted_as_support(guarded, roles, monkeypatch):
    monkeypatch.setenv("LAB_BRAIN_MEASUREMENT_PROVENANCE", "strict")
    g = guarded
    with roles.connect(roles.app) as app:
        observation, attestation = _fabricated(g, app, "fabricated")
    admitted = _admitted_support(g, _product_relations(g))
    print(f"T-1 fabricated {observation} ({attestation}): product admits {sorted(admitted)}")
    assert f"rel:{observation}" not in admitted


# =============================================================================================
# The prototype boundary (`003f`, `security.measurement_provenance`)
# =============================================================================================

INSTRUMENT = "lab.probe_station"


def _runner(capabilities: tuple[str, ...] | None = None) -> MeasurementRunner:
    return MeasurementRunner(
        SigningKey.generate(),
        instrument_id=INSTRUMENT,
        capability_ids=capabilities or (sp.CAP_FOURPOINT_PROBE,),
    )


def _enrol(g: Guarded, runner: MeasurementRunner, instrument: str = INSTRUMENT) -> None:
    """The schema owner enrols the runner's public key for its instrument and capabilities."""
    enrol(
        g.db,
        public_key=runner.public_key,
        key_id=runner.key_id,
        instrument_id=instrument,
        capability_ids=sorted(runner.capability_ids),
        reason="probe station runner key (G0 T-1 prototype)",
        actor_id=g.actor,
    )


def _export(name: str) -> bytes:
    """The raw bytes `Guarded.artifact(f"probe export {name}")` records."""
    return f"artifact probe export {name}".encode()


def _measure(
    g: Guarded,
    app: Any,
    name: str,
    *,
    sign: Callable[[str, str, str], Any] | None = None,
    export_of: str | None = None,
) -> tuple[str, str, str]:
    """A pre-registered probe measurement written by the services' role: the Job, its nonce (asked
    of the database while the job runs), the Run, the reading and its SUPPORTS. `sign(job, run,
    nonce)` returns what the services relay (a runner's `SignedMeasurement`), or None for an
    unsigned measurement. Returns (job, run, relation)."""
    authorization = g.authorize(name)
    services = _as(g, app)
    if export_of is None:
        export = services.artifact(f"probe export {name}", captured_at=g.later)
    else:  # the very bytes another run recorded
        ((export,),) = g.db.execute(
            "SELECT output_artifacts[1] FROM runs WHERE run_id = %s", (f"run:ind-{export_of}",)
        ).fetchall()
    job = services.jobs.submit(
        Job(
            job_id=f"job:ind-{name}",
            project_id=PROJECT,
            episode_id=g.episode,
            capability_id=sp.CAP_FOURPOINT_PROBE,
            trace_id=g.screened.trace_id,
            idempotency_key=f"ind:{name}",
            submitted_at=g.later,
        )
    )
    g.db.execute(
        "INSERT INTO verification_authorization_jobs (authorization_id, job_id, bound_at)"
        " VALUES (%s, %s, now())",
        (authorization, job.job_id),
    )
    services.jobs.transition(job.job_id, JobState.RUNNING, g.later)
    nonce = issue_nonce(app, job.job_id)
    run_id = f"run:ind-{name}"
    services.jobs.complete(
        job.job_id,
        job.idempotency_key,
        g.screened.model_copy(
            update={
                "run_id": run_id,
                "job_id": job.job_id,
                "capability_id": sp.CAP_FOURPOINT_PROBE,
                "backend_id": INSTRUMENT,
                "input_artifacts": (),
                "input_parameters": {"variant": name},
                "output_artifacts": (export,),
                "start_time": g.later,
                "end_time": g.later,
            }
        ),
    )
    if sign is not None:
        signed = sign(job.job_id, run_id, nonce)
        if signed is not None:
            relay(app, signed)
    observation = services.observe(run_id, name, sp.OBS_PROBE, "ELEVATED")
    evidence = services.attest(observation, run_id, PROBE_METHOD)
    services.support(observation, [evidence], prediction=g.prediction())
    return job.job_id, run_id, f"rel:{observation}"


def _honest_signer(runner: MeasurementRunner, name: str) -> Callable[[str, str, str], Any]:
    def sign(job: str, run: str, nonce: str) -> Any:
        return runner.sign(
            job_id=job,
            run_id=run,
            nonce=nonce,
            capability_id=sp.CAP_FOURPOINT_PROBE,
            outputs=(_export(name),),
            measured_at=dt.datetime.now(dt.UTC),
        )

    return sign


def _status(g: Guarded, run_id: str) -> str:
    return MeasurementProvenance(g.db).run(run_id).status.value


def test_t1_a_runner_signed_measurement_is_admitted_in_strict_mode(guarded, roles, monkeypatch):
    """The positive control: the probe station's enrolled runner signs; the services relay it."""
    monkeypatch.setenv(MODE_ENV, "strict")
    g = guarded
    runner = _runner()
    _enrol(g, runner)
    with roles.connect(roles.app) as app:
        _job, run, relation = _measure(g, app, "signed", sign=_honest_signer(runner, "signed"))
    assert _status(g, run) == "VERIFIED"
    assert relation in _admitted_support(g, _product_relations(g))


def _replayed(g: Guarded, app: Any, runner: MeasurementRunner) -> Callable[[str, str, str], Any]:
    """A genuine signature of another run (signed for that run's job and nonce), relayed for this
    one under this job's nonce."""
    _job, _run, _rel = _measure(g, app, "genuine", sign=_honest_signer(runner, "genuine"))
    ((signature, digest, _signed_at),) = g.db.execute(
        "SELECT signature, raw_digest, measured_at FROM measurement_signatures WHERE run_id = %s",
        (_run,),
    ).fetchall()

    def sign(job: str, run: str, nonce: str) -> Any:
        # Dated now, after this job's nonce, so only the signature itself can tell.
        now = dt.datetime.now(dt.UTC)
        return SignedMeasurement(job, run, nonce, runner.key_id, digest, now, signature)

    return sign


ATTACKS: dict[str, tuple[str, Callable[..., Any]]] = {
    # The services' own measurement, as before the prototype: no signature at all.
    "unsigned": ("UNSIGNED", lambda g, app, runner: None),
    # Signed with a key the services made themselves (never enrolled).
    "own_key": (
        "UNKNOWN_KEY",
        lambda g, app, runner: _honest_signer(_runner(), "own_key"),
    ),
    # A genuine signature of another run, replayed.
    "replayed": ("BAD_SIGNATURE", _replayed),
    # The same, onto a run whose recorded output is other bytes.
    "replayed_other_bytes": ("DIGEST_MISMATCH", _replayed),
    # The runner signed other bytes than the export the services recorded for the run.
    "tampered_bytes": (
        "DIGEST_MISMATCH",
        lambda g, app, runner: _honest_signer(runner, "what the instrument really read"),
    ),
    # Signed before the database issued the job's nonce (precomputed).
    "precomputed": (
        "TIME_MISMATCH",
        lambda g, app, runner: (
            lambda job, run, nonce: runner.sign(
                job_id=job,
                run_id=run,
                nonce=nonce,
                capability_id=sp.CAP_FOURPOINT_PROBE,
                outputs=(_export("precomputed"),),
                measured_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
            )
        ),
    ),
}


@pytest.mark.parametrize("attack", sorted(ATTACKS))
def test_t1_a_measurement_without_a_verifying_signature_is_not_support(
    guarded, roles, monkeypatch, attack
):
    monkeypatch.setenv(MODE_ENV, "strict")
    g = guarded
    runner = _runner()
    _enrol(g, runner)
    expected, signer = ATTACKS[attack]
    with roles.connect(roles.app) as app:
        _job, run, relation = _measure(
            g,
            app,
            attack,
            sign=signer(g, app, runner),
            export_of="genuine" if attack == "replayed" else None,
        )
    status = _status(g, run)
    admitted = _admitted_support(g, _product_relations(g))
    print(f"T-1 {attack}: provenance {status}; admitted {relation in admitted}")
    assert status == expected
    assert relation not in admitted


def test_t1_a_revoked_key_no_longer_verifies(guarded, roles, monkeypatch):
    monkeypatch.setenv(MODE_ENV, "strict")
    g = guarded
    runner = _runner()
    _enrol(g, runner)
    revoke(g.db, key_id=runner.key_id, reason="key left the probe station host", actor_id=g.actor)
    with roles.connect(roles.app) as app:
        _job, run, relation = _measure(g, app, "revoked", sign=_honest_signer(runner, "revoked"))
    assert _status(g, run) == "KEY_REVOKED"
    assert relation not in _admitted_support(g, _product_relations(g))


def test_t1_a_key_enrolled_for_another_instrument_is_out_of_scope(guarded, roles, monkeypatch):
    monkeypatch.setenv(MODE_ENV, "strict")
    g = guarded
    runner = _runner()
    _enrol(g, runner, instrument="lab.another_station")
    with roles.connect(roles.app) as app:
        _job, run, relation = _measure(g, app, "scope", sign=_honest_signer(runner, "scope"))
    assert _status(g, run) == "OUT_OF_SCOPE"
    assert relation not in _admitted_support(g, _product_relations(g))


def test_t1_enrolment_enforces_its_pair_in_the_default_mode(guarded, roles, monkeypatch):
    """Default mode: once the probe station's key is enrolled, its unsigned measurement is not
    support; with no enrolment the same measurement counts, labelled NOT_REQUIRED."""
    monkeypatch.delenv(MODE_ENV, raising=False)
    g = guarded
    with roles.connect(roles.app) as app:
        _j, before, relation_before = _measure(g, app, "unenrolled")
    assert _status(g, before) == "NOT_REQUIRED"
    assert relation_before in _admitted_support(g, _product_relations(g))
    _enrol(g, _runner())
    with roles.connect(roles.app) as app:
        _j, after, relation_after = _measure(g, app, "enrolled")
    assert _status(g, after) == "UNSIGNED"
    # Enrolment switches the pair on for its earlier unsigned measurements too.
    assert _status(g, before) == "UNSIGNED"
    admitted = _admitted_support(g, _product_relations(g))
    assert relation_after not in admitted and relation_before not in admitted


def test_t1_the_services_cannot_enrol_revoke_or_choose_what_the_database_issues(guarded, roles):
    g = guarded
    runner = _runner()
    with roles.connect(roles.app) as app:
        refused = _try(lambda: _enrol(_as(g, app), runner))
        assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused
        _enrol(g, runner)
        assert isinstance(
            _try(lambda: revoke(app, key_id=runner.key_id, reason="x" * 12, actor_id=g.actor)),
            psycopg.errors.InsufficientPrivilege,
        )
        for statement in (
            "UPDATE measurement_signing_keys SET instrument_id = 'elsewhere'",
            "DELETE FROM measurement_signing_keys",
        ):
            assert isinstance(_try(lambda s=statement: app.execute(s)), psycopg.Error), statement
        job, run, _relation = _measure(g, app, "issued", sign=_honest_signer(runner, "issued"))
        # A nonce is the database's value, one per job, and only while the job runs.
        assert _try(lambda: issue_nonce(app, job)) is not None
        ((chosen,),) = app.execute(
            "SELECT count(*) FROM measurement_nonces WHERE nonce = 'chosen-by-the-services'"
        ).fetchall()
        assert chosen == 0
        for statement in (
            "UPDATE measurement_signatures SET raw_digest = 'sha256:00'",
            "DELETE FROM measurement_signatures",
            "UPDATE measurement_nonces SET issued_at = issued_at - interval '1 day'",
        ):
            assert isinstance(_try(lambda s=statement: app.execute(s)), psycopg.Error), statement
    assert _status(g, run) == "VERIFIED"


def test_t1_the_database_issues_the_nonce_value_and_time(guarded, roles):
    g = guarded
    with roles.connect(roles.app) as app:
        job = _as(g, app).jobs.submit(
            Job(
                job_id="job:ind-nonce",
                project_id=PROJECT,
                episode_id=g.episode,
                capability_id=sp.CAP_FOURPOINT_PROBE,
                trace_id=g.screened.trace_id,
                idempotency_key="ind:nonce",
                submitted_at=g.later,
            )
        )
        ((nonce, at),) = app.execute(
            "INSERT INTO measurement_nonces (nonce, job_id, issued_at, issued_by)"
            " VALUES ('chosen-by-the-services', %s, '2000-01-01', 'me') RETURNING nonce, issued_at",
            (job.job_id,),
        ).fetchall()
    assert nonce != "chosen-by-the-services"
    assert at.year == dt.datetime.now(dt.UTC).year


def test_t1_db_roles_leave_the_services_select_on_keys_and_insert_on_records(su, roles):
    """The Owner's revocation (separate commit): after repeated `db-roles` and migrations the
    services' role reads the key tables only, and inserts (never edits) nonces and signatures."""
    import subprocess
    import sys
    from pathlib import Path

    from lab_brain.interfaces.deployment import grant_database_roles
    from tests.e2e.test_g0_trust_boundaries_postgres import _privileges

    root = Path(__file__).resolve().parents[2]
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    subprocess.run([sys.executable, str(root / "scripts" / "migrate.py")], check=True)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    for table, expected in (
        ("measurement_signing_keys", {"SELECT"}),
        ("measurement_signing_key_revocations", {"SELECT"}),
        ("measurement_nonces", {"SELECT", "INSERT"}),
        ("measurement_signatures", {"SELECT", "INSERT"}),
    ):
        held = {p for p, ok in _privileges(su, roles.app, table).items() if ok}
        assert held == expected, (table, held)
        assert _privileges(su, roles.reader, table)["SELECT"], table
