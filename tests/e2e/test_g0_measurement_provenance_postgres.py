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

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from lab_brain.core.models import RelationType
from lab_brain.core.repositories.jobs import SqlJobStore
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import _product_relations
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


@pytest.mark.xfail(
    strict=True,
    reason="T-1: a fabricated measurement the services' role stored is admitted as support",
)
def test_t1_a_fabricated_measurement_is_not_admitted_as_support(guarded, roles, monkeypatch):
    monkeypatch.setenv("LAB_BRAIN_MEASUREMENT_PROVENANCE", "strict")
    g = guarded
    with roles.connect(roles.app) as app:
        observation, attestation = _fabricated(g, app, "fabricated")
    admitted = _admitted_support(g, _product_relations(g))
    print(f"T-1 fabricated {observation} ({attestation}): product admits {sorted(admitted)}")
    assert f"rel:{observation}" not in admitted
