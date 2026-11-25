"""G0 trust boundaries, round 6: the SQL readers apply the rules the Python readers apply.

Round 5 (`003f`) gave the Python relation reader (`SqlRelationStore` + `MeasurementProvenance`) a
measurement-provenance rule: once the owner enrols a signing key for an (instrument, capability),
an unsigned or unverifiable measurement of that pair is not support. The SQL readers of the same
evidence -- the confirmation rule (`cwg_state`, `cwg_evidence`), `011l`'s root-cause check and the
`011z` write gate -- did not know the rule, so SQL counted what Python refused (T-1r):

T1  after enrolment, the projection refuses a history whose promotion counted an unsigned
    measurement (SUPPORT_UNVERIFIED); `cwg_state` still reads SUPPORTED.
T2  `cwg_evidence` (what the SQL confirmation rule counts as support) still lists the SUPPORTS.
T3  the `011z` gate still accepts a decision snapshot counting that SUPPORTS.
T4  `011l` refuses a CONFIRMED analysis of that cause only for a later reason, not because the
    cause is not SUPPORTED.
T5  the strict mode is a setting of the services' process only: in strict mode Python refuses an
    unsigned measurement of an unenrolled pair, and no SQL reader can see the mode.

Q-r  the services' role adds an external-snapshot quarantine, which (by `005f`) demotes a belief.

Every attack is made through the deployment's least-privilege services' role where the services
write, and as the schema owner where only the owner can. Engineering evidence only. G0 is NOT
PASSED.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest

from lab_brain.core.models import BeliefState, RelationType
from lab_brain.security.measurement_provenance import MODE_ENV, enrol
from lab_brain.security.reviewer_identity import SigningKey
from tests.e2e.test_g0_boundary_round4_postgres import _attempt, _services_episode, _write
from tests.e2e.test_g0_boundary_round5_postgres import (
    _external_attestation,
    g_attempt_with_trigger,
)
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import _product_relations
from tests.e2e.test_g0_trust_boundaries_postgres import (
    SUPPORT_ONLY,
    _honest,
    _owner_registers,
    _read,
    _stored_support,
    _unscreened,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles


def _pair_of(g: Guarded, attestation: str) -> tuple[str, str]:
    """The (instrument, capability) of the run behind an attestation."""
    ((instrument, capability),) = g.db.execute(
        "SELECT u.backend_id, u.capability_id FROM attestations a"
        " LEFT JOIN observations o ON o.observation_id = a.observation_id"
        " JOIN runs u ON u.run_id = coalesce(a.run_id, o.run_id)"
        " WHERE a.attestation_id = %s",
        (attestation,),
    ).fetchall()
    return str(instrument), str(capability)


def _owner_enrols_for(g: Guarded, attestation: str) -> None:
    """The schema owner enrols a signing key for the pair that measured `attestation`."""
    instrument, capability = _pair_of(g, attestation)
    key = SigningKey.generate()
    enrol(
        g.db,
        public_key=key.public_key,
        key_id=key.key_id,
        instrument_id=instrument,
        capability_ids=[capability],
        reason="runner key for this instrument (G0 round 6)",
        actor_id=g.actor,
    )


def _promoted_on_a_measurement(g: Guarded, roles: Any) -> tuple[str, Any, Any]:
    """An unscreened hypothesis promoted honestly on a stored, unsigned measurement:
    (hypothesis, the SUPPORTS, the written transition)."""
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        relation = _stored_support(app, g, hypothesis)
        written = _attempt(_services_episode(app, g), g, hypothesis, policy)
    assert written.event is not None
    assert _read(_honest(g), hypothesis) == BeliefState.SUPPORTED.value
    return hypothesis, relation, written


def _sql_support(g: Guarded, hypothesis: str) -> set[str]:
    return {
        str(r[0])
        for r in g.db.execute(
            "SELECT relation_id FROM cwg_evidence(%s, %s) WHERE relation_type = 'SUPPORTS'",
            (PROJECT, hypothesis),
        ).fetchall()
    }


def _python_support(g: Guarded, hypothesis: str) -> set[str]:
    return {
        r.relation_id
        for r in _product_relations(g).admitted_for_subject(PROJECT, hypothesis)
        if r.relation_type is RelationType.SUPPORTS
    }


# =============================================================================================
# T-1r: SQL counts what Python refuses
# =============================================================================================


@pytest.mark.xfail(strict=True, reason="T-1r: the SQL state reader ignores measurement provenance")
def test_t1r_the_sql_state_is_not_supported_on_a_measurement_python_refuses(guarded, roles):
    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    python = _read(_honest(g), hypothesis)
    ((sql,),) = g.db.execute("SELECT cwg_state(%s, %s)", (PROJECT, hypothesis)).fetchall()
    print(f"T1 after enrolment: projection -> {python}; cwg_state -> {sql}")
    assert python == "REFUSED:SUPPORT_UNVERIFIED"
    assert sql is None


@pytest.mark.xfail(strict=True, reason="T-1r: cwg_evidence ignores measurement provenance")
def test_t1r_the_sql_confirmation_rule_does_not_count_a_support_python_refuses(guarded, roles):
    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    assert relation.relation_id in _sql_support(g, hypothesis) & _python_support(g, hypothesis)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    python, sql = _python_support(g, hypothesis), _sql_support(g, hypothesis)
    print(f"T2 after enrolment: Python admits {sorted(python)}; cwg_evidence {sorted(sql)}")
    assert relation.relation_id not in python
    assert sql == python


@pytest.mark.xfail(strict=True, reason="T-1r: the 011z gate ignores measurement provenance")
def test_t1r_the_write_gate_refuses_a_snapshot_counting_a_support_python_refuses(guarded, roles):
    g = guarded
    _hypothesis, relation, written = _promoted_on_a_measurement(g, roles)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    ((problem,),) = g.db.execute(
        "SELECT belief_snapshot_problem(project_id, subject_id, decision_input_snapshot::jsonb)"
        " FROM belief_transition_decisions WHERE decision_id = %s",
        (written.authorization.decision_id,),
    ).fetchall()
    print(f"T3 the gate on the same snapshot after enrolment: {problem!r}")
    assert problem is not None and "measurement provenance" in problem, problem


def _confirm(app: Any, g: Guarded, hypothesis: str, evidence: str) -> BaseException | None:
    _, refused = _write(
        lambda: app.execute(
            "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id,"
            " symptom, expected_behavior, observed_behavior, candidate_causes,"
            " confirmed_root_cause, root_cause_evidence_ids, failure_class,"
            " resolution_status, created_at)"
            " VALUES (%s, %s, %s, 'loss high', 'low loss', 'high loss', %s, %s, %s,"
            " 'contact', 'CONFIRMED', now())",
            (
                f"fa:r6-{uuid.uuid4().hex[:8]}",
                PROJECT,
                g.episode,
                [hypothesis],
                hypothesis,
                [evidence],
            ),
        )
    )
    return refused


@pytest.mark.xfail(strict=True, reason="T-1r: 011l reads a state Python refuses")
def test_t1r_a_root_cause_is_not_confirmed_on_a_support_python_refuses(guarded, roles):
    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    with roles.connect(roles.app) as app:
        refused = _confirm(app, g, hypothesis, relation.supporting_attestation_ids[0])
    print(f"T4 CONFIRMED on a support Python refuses: {refused!r}")
    assert refused is not None
    assert "current belief state is no history" in str(refused), refused


@pytest.mark.xfail(strict=True, reason="T-1r: the strict mode is invisible to SQL")
def test_t1r_strict_mode_is_the_owners_and_sql_reads_it(guarded, roles, monkeypatch):
    """The owner sets strict mode; an unsigned measurement of an unenrolled pair is then support
    for neither Python nor SQL, and the services cannot switch the mode back."""
    from lab_brain.security import measurement_provenance as mp

    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    monkeypatch.setenv(MODE_ENV, "strict")
    setter = getattr(mp, "set_mode", None)
    assert setter is not None, "no owner setting of the mode exists"
    setter(g.db, "strict", reason="every runner signs (G0 round 6)", actor_id=g.actor)
    python, sql = _python_support(g, hypothesis), _sql_support(g, hypothesis)
    assert relation.relation_id not in python
    assert sql == python
    with roles.connect(roles.app) as app:
        refused = _write(
            lambda: setter(app, "enrolled", reason="the services want it back", actor_id=g.actor)
        )[1]
    assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused


# =============================================================================================
# Q-r: who may quarantine an external snapshot
# =============================================================================================


@pytest.mark.xfail(strict=True, reason="Q-r: any writer may quarantine an external snapshot")
def test_qr_the_services_cannot_demote_a_belief_by_quarantining_a_snapshot(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    attestation = _external_attestation(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written = g_attempt_with_trigger(app, g, hypothesis, policy, attestation)
        assert written.event is not None
        ((snapshot,),) = g.db.execute(
            "SELECT method ->> 'snapshot_id' FROM attestations WHERE attestation_id = %s",
            (attestation,),
        ).fetchall()
        _, refused = _write(
            lambda: app.execute(
                "INSERT INTO external_snapshot_quarantine (snapshot_id, project_id, reason_code)"
                " VALUES (%s, %s, 'QUARANTINED_BY_OPERATOR')",
                (snapshot, PROJECT),
            )
        )
    state = _read(_honest(g), hypothesis)
    print(f"Q-r the services quarantine {snapshot}: refused={refused!r}; projection -> {state}")
    assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused
    assert state == BeliefState.SUPPORTED.value
