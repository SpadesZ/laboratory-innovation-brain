"""G0 round 6, T-1r: SQL and Python count the same measurements, and both equal an oracle.

Every combination of what decides whether a measurement counts as support:

    enrolled   whether the owner ever enrolled a key for the run's (instrument, capability)
    signature  none, valid, invalid (a signature of another statement), or by a key the owner
               revoked before it arrived (only where a key is enrolled)
    verdict    whether the owner-run verifier has recorded its verdict (`003g`)
    mode       the owner's mode, `enrolled` or `strict` (`003g`, read by both sides)

For each, three answers must agree: SQL (`measurement_run_status`, and whether the SQL confirmation
rule's `cwg_evidence` lists the SUPPORTS), Python (`MeasurementProvenance.run(...).counts`, and
whether the product's relation reader admits the SUPPORTS), and an oracle written from the
toggles alone. Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import itertools
from typing import Any

import pytest

from lab_brain.core.models import RelationType
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.security.measurement_provenance import (
    MODE_ENV,
    MeasurementProvenance,
    MeasurementRunner,
    enrol,
    revoke,
    set_mode,
    verify_run,
)
from lab_brain.security.reviewer_identity import SigningKey
from tests.e2e.test_g0_measurement_provenance_postgres import _export, _measure
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import _product_relations
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles

SIGNATURES = ("none", "valid", "invalid", "revoked")


def _oracle(*, enrolled: bool, signature: str, verdict: bool, strict: bool) -> bool:
    if signature == "none":
        return not (strict or enrolled)
    return verdict and enrolled and signature == "valid"


def _cases() -> list[tuple[bool, str, bool]]:
    return [
        (enrolled, signature, verdict)
        for enrolled, signature, verdict in itertools.product(
            (False, True), SIGNATURES, (False, True)
        )
        # A key is revoked only once enrolled; with no signature there is nothing to verify.
        if not (signature == "revoked" and not enrolled) and not (signature == "none" and verdict)
    ]


def _signer(runner: MeasurementRunner, name: str, signature: str) -> Any:
    def sign(job: str, run: str, nonce: str) -> Any:
        if signature == "none":
            return None
        signed = runner.sign(
            job_id=job,
            run_id=run,
            nonce=nonce,
            capability_id=sp.CAP_FOURPOINT_PROBE,
            outputs=(_export(name),),
            measured_at=dt.datetime.now(dt.UTC),
        )
        if signature == "invalid":
            other = runner.sign(
                job_id=job,
                run_id=f"{run}-other",
                nonce=nonce,
                capability_id=sp.CAP_FOURPOINT_PROBE,
                outputs=(_export(name),),
                measured_at=dt.datetime.now(dt.UTC),
            )
            return dataclasses.replace(signed, signature=other.signature)
        return signed

    return sign


def test_t1r_sql_python_and_an_oracle_count_the_same_measurements(guarded, roles, monkeypatch):
    g = guarded
    monkeypatch.delenv(MODE_ENV, raising=False)
    runs: dict[tuple[bool, str, bool], tuple[str, str]] = {}
    with roles.connect(roles.app) as app:
        for n, (enrolled, signature, verdict) in enumerate(_cases()):
            name = f"diff{n}"
            instrument = f"lab.station_{n}"
            runner = MeasurementRunner(
                SigningKey.generate(),
                instrument_id=instrument,
                capability_ids=(sp.CAP_FOURPOINT_PROBE,),
            )
            if enrolled:
                enrol(
                    g.db,
                    public_key=runner.public_key,
                    key_id=runner.key_id,
                    instrument_id=instrument,
                    capability_ids=[sp.CAP_FOURPOINT_PROBE],
                    reason="differential runner key (G0 round 6)",
                    actor_id=g.actor,
                )
            if signature == "revoked":
                revoke(g.db, key_id=runner.key_id, reason="key left its host", actor_id=g.actor)
            _job, run, relation = _measure(
                g,
                app,
                name,
                sign=_signer(runner, name, signature),
                instrument=instrument,
            )
            if verdict:
                verify_run(g.db, run, actor_id=g.actor)
            runs[(enrolled, signature, verdict)] = (run, relation)

    seen: set[tuple[bool, bool]] = set()
    for strict in (False, True):
        if strict:
            set_mode(g.db, "strict", reason="differential: strict mode", actor_id=g.actor)
            monkeypatch.setenv(MODE_ENV, "strict")
        python_reader = MeasurementProvenance(g.db)
        admitted = {
            r.relation_id
            for r in _product_relations(g).admitted_for_subject(PROJECT, g.hypothesis)
            if r.relation_type is RelationType.SUPPORTS
        }
        listed = {
            str(r[0])
            for r in g.db.execute(
                "SELECT relation_id FROM cwg_evidence(%s, %s) WHERE relation_type = 'SUPPORTS'",
                (PROJECT, g.hypothesis),
            ).fetchall()
        }
        for (enrolled, signature, verdict), (run, relation) in sorted(runs.items()):
            expected = _oracle(
                enrolled=enrolled, signature=signature, verdict=verdict, strict=strict
            )
            ((sql_status,),) = g.db.execute("SELECT measurement_run_status(%s)", (run,)).fetchall()
            python = python_reader.run(run)
            sql = sql_status in ("VERIFIED", "NOT_REQUIRED")
            print(
                f"strict={strict} enrolled={enrolled} signature={signature} verdict={verdict}:"
                f" oracle={expected} sql={sql_status} python={python.status.value}"
                f" admitted={relation in admitted} listed={relation in listed}"
            )
            case = (strict, enrolled, signature, verdict)
            assert sql == expected, case
            assert python.status.counts == expected, case
            assert (relation in admitted) == expected, case
            assert (relation in listed) == expected, case
            seen.add((strict, expected))
    # Both outcomes are reached in both modes: the enumeration distinguishes something.
    assert seen == {(False, False), (False, True), (True, False), (True, True)}
