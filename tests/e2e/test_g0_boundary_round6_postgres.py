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


def test_t1r_the_sql_state_is_not_supported_on_a_measurement_python_refuses(guarded, roles):
    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    python = _read(_honest(g), hypothesis)
    ((sql,),) = g.db.execute("SELECT cwg_state(%s, %s)", (PROJECT, hypothesis)).fetchall()
    print(f"T1 after enrolment: projection -> {python}; cwg_state -> {sql}")
    assert python == "REFUSED:SUPPORT_UNVERIFIED"
    assert sql is None


def test_t1r_the_sql_confirmation_rule_does_not_count_a_support_python_refuses(guarded, roles):
    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    assert relation.relation_id in _sql_support(g, hypothesis) & _python_support(g, hypothesis)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    python, sql = _python_support(g, hypothesis), _sql_support(g, hypothesis)
    print(f"T2 after enrolment: Python admits {sorted(python)}; cwg_evidence {sorted(sql)}")
    assert relation.relation_id not in python
    assert sql == python


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


def test_t1r_a_root_cause_is_not_confirmed_on_a_support_python_refuses(guarded, roles):
    g = guarded
    hypothesis, relation, _written = _promoted_on_a_measurement(g, roles)
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    with roles.connect(roles.app) as app:
        refused = _confirm(app, g, hypothesis, relation.supporting_attestation_ids[0])
    print(f"T4 CONFIRMED on a support Python refuses: {refused!r}")
    assert refused is not None
    assert "current belief state is no history" in str(refused), refused


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


# =============================================================================================
# T-1r after the fix: who writes the verdicts, and the one case left to the owner
# =============================================================================================


def _signed_run(g: Guarded, app: Any, name: str) -> tuple[str, Any]:
    from tests.e2e.test_g0_measurement_provenance_postgres import (
        _enrol,
        _honest_signer,
        _measure,
        _runner,
    )

    runner = _runner()
    _enrol(g, runner)
    _job, run, _relation = _measure(g, app, name, sign=_honest_signer(runner, name))
    return run, runner


def test_t1r_the_services_cannot_record_a_verdict_or_edit_one(guarded, roles):
    from lab_brain.security.measurement_provenance import set_mode, verify_run

    g = guarded
    with roles.connect(roles.app) as app:
        run, _runner = _signed_run(g, app, "verdict")
        refused = _write(lambda: verify_run(app, run, actor_id=g.actor))[1]
        assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused
        assert verify_run(g.db, run, actor_id=g.actor) == "VERIFIED"
        set_mode(g.db, "enrolled", reason="the default, recorded (G0 round 6)", actor_id=g.actor)
        for statement in (
            "UPDATE measurement_verifications SET status = 'VERIFIED'",
            "DELETE FROM measurement_verifications",
            "UPDATE measurement_provenance_modes SET mode = 'enrolled'",
        ):
            assert isinstance(_write(lambda s=statement: app.execute(s))[1], psycopg.Error)


def test_t1r_residual_a_verdict_the_owner_writes_by_hand_is_counted_by_sql_only(guarded, roles):
    """The owner is the trust root: a VERIFIED verdict the owner inserts for a signature that
    does not verify is counted by SQL (which cannot check the signature) and refused by Python
    (which re-verifies it). The direction is Python refusing more, never counting more."""
    import dataclasses
    import datetime as dt

    from lab_brain.domains.silicon_photonics import vertical as sp
    from lab_brain.security.measurement_provenance import VERIFIER, MeasurementProvenance
    from tests.e2e.test_g0_measurement_provenance_postgres import _enrol, _export, _measure, _runner

    g = guarded
    runner = _runner()
    _enrol(g, runner)

    def forged(job: str, run: str, nonce: str) -> Any:
        signed = runner.sign(
            job_id=job,
            run_id=run,
            nonce=nonce,
            capability_id=sp.CAP_FOURPOINT_PROBE,
            outputs=(_export("by-hand"),),
            measured_at=dt.datetime.now(dt.UTC),
        )
        return dataclasses.replace(
            signed,
            signature=runner.sign(
                job_id=job,
                run_id=f"{run}-other",
                nonce=nonce,
                capability_id=sp.CAP_FOURPOINT_PROBE,
                outputs=(_export("by-hand"),),
                measured_at=dt.datetime.now(dt.UTC),
            ).signature,
        )

    with roles.connect(roles.app) as app:
        _job, run, _relation = _measure(g, app, "by-hand", sign=forged)
    g.db.execute(
        "INSERT INTO measurement_verifications (run_id, status, key_id, signature, detail,"
        " verifier, actor_id, verified_at, recorded_by)"
        " VALUES (%s, 'VERIFIED', '', '', 'written by hand', %s, %s, now(), '')",
        (run, VERIFIER, g.actor),
    )
    ((sql,),) = g.db.execute("SELECT measurement_run_status(%s)", (run,)).fetchall()
    python = MeasurementProvenance(g.db).run(run).status.value
    print(f"T-1r residual: owner's hand-written verdict -> SQL {sql}, Python {python}")
    assert (sql, python) == ("VERIFIED", "BAD_SIGNATURE")


def test_qr_an_owners_quarantine_records_who_and_why_and_stays(guarded):
    """The owner's quarantine still works (the fail-safe direction is kept, see the round-5 Q6
    test), but only with the deciding person and a reason; it is never released."""
    from lab_brain.core.repositories.external_sources import SqlExternalSourceStore

    g = guarded
    attestation = _external_attestation(g)
    ((snapshot,),) = g.db.execute(
        "SELECT method ->> 'snapshot_id' FROM attestations WHERE attestation_id = %s",
        (attestation,),
    ).fetchall()
    store = SqlExternalSourceStore(g.db)
    _, refused = _write(lambda: store.quarantine(PROJECT, snapshot, "QUARANTINED_BY_OPERATOR"))
    assert refused is not None and "records the person who decided it" in str(refused), refused
    store.quarantine(
        PROJECT,
        snapshot,
        "QUARANTINED_BY_OPERATOR",
        actor_id=g.actor,
        reason="scope of this read is in doubt (G0 round 6)",
    )
    ((actor, reason, by),) = g.db.execute(
        "SELECT decided_by_actor_id, reason, recorded_by FROM external_snapshot_quarantine"
        " WHERE snapshot_id = %s",
        (snapshot,),
    ).fetchall()
    assert (actor, by) == (g.actor, g.db.info.user) and "in doubt" in reason
    assert attestation in store.quarantined_attestation_ids(PROJECT)
    for statement in (
        "DELETE FROM external_snapshot_quarantine",
        "UPDATE external_snapshot_quarantine SET reason = 'released'",
    ):
        assert isinstance(_write(lambda s=statement: g.db.execute(s))[1], psycopg.Error)


# =============================================================================================
# Q-x: a relation resting on a quarantined external snapshot's attestation
# =============================================================================================


def _external_support(app: Any, g: Guarded, hypothesis: str, attestation: str) -> Any:
    """As the services' role: a SUPPORTS of the hypothesis resting on an external attestation."""
    from lab_brain.core.models import RelationJudgment
    from lab_brain.core.repositories.evidence import SqlRelationStore

    ((claim,),) = g.db.execute(
        "SELECT claim_id FROM attestations WHERE attestation_id = %s", (attestation,)
    ).fetchall()
    relation = RelationJudgment(
        relation_id=f"rel:r6-ext-{uuid.uuid4().hex[:8]}",
        from_entity_id=str(claim),
        to_entity_id=hypothesis,
        relation_type=RelationType.SUPPORTS,
        supporting_attestation_ids=(attestation,),
        project_id=PROJECT,
    )
    SqlRelationStore(app).add(relation)
    return relation


def _owner_quarantines_snapshot_of(g: Guarded, attestation: str) -> None:
    from lab_brain.core.repositories.external_sources import SqlExternalSourceStore

    ((snapshot,),) = g.db.execute(
        "SELECT method ->> 'snapshot_id' FROM attestations WHERE attestation_id = %s",
        (attestation,),
    ).fetchall()
    SqlExternalSourceStore(g.db).quarantine(
        PROJECT,
        snapshot,
        "QUARANTINED_BY_OPERATOR",
        actor_id=g.actor,
        reason="scope of this read is in doubt (G0 round 6)",
    )


def test_qx_a_relation_on_a_quarantined_snapshot_is_support_nowhere(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    attestation = _external_attestation(g)
    with roles.connect(roles.app) as app:
        relation = _external_support(app, g, hypothesis, attestation)
    assert relation.relation_id in _python_support(g, hypothesis) & _sql_support(g, hypothesis)
    _owner_quarantines_snapshot_of(g, attestation)
    python, sql = _python_support(g, hypothesis), _sql_support(g, hypothesis)
    print(f"Q-x after quarantine: Python admits {sorted(python)}; cwg_evidence {sorted(sql)}")
    assert relation.relation_id not in python
    assert relation.relation_id not in sql


def test_qx_a_promotion_that_counted_it_no_longer_counts(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    attestation = _external_attestation(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        _external_support(app, g, hypothesis, attestation)
        written = _attempt(_services_episode(app, g), g, hypothesis, policy)
    assert written.event is not None
    assert _read(_honest(g), hypothesis) == BeliefState.SUPPORTED.value
    _owner_quarantines_snapshot_of(g, attestation)
    python = _read(_honest(g), hypothesis)
    ((sql,),) = g.db.execute("SELECT cwg_state(%s, %s)", (PROJECT, hypothesis)).fetchall()
    ((problem,),) = g.db.execute(
        "SELECT belief_snapshot_problem(project_id, subject_id, decision_input_snapshot::jsonb)"
        " FROM belief_transition_decisions WHERE decision_id = %s",
        (written.authorization.decision_id,),
    ).fetchall()
    print(f"Q-x promotion after quarantine: projection {python}; cwg_state {sql}; gate {problem}")
    assert python == BeliefState.ACTIVE.value
    assert sql == BeliefState.ACTIVE.value
    assert problem is not None and "quarantined" in problem, problem


# =============================================================================================
# E-1: the episode page's "not counted" mark (a report that claims support)
# =============================================================================================


def _shown_as(g: Guarded, relation: str, hypothesis: str) -> str | None:
    """What the episode page says about a recorded SUPPORTS: None (counted) or why not."""
    from lab_brain.research.episode_view import _not_counted
    from lab_brain.verification import prospective

    verifier = prospective.prospective_support_verifier(g.db, g.keys.trust)
    return _not_counted(g.db, PROJECT, relation, "SUPPORTS", hypothesis, verifier)


def test_e1_the_episode_page_does_not_show_a_refused_measurement_as_counted(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    with roles.connect(roles.app) as app:
        relation = _stored_support(app, g, hypothesis)
    assert _shown_as(g, relation.relation_id, hypothesis) is None
    _owner_enrols_for(g, relation.supporting_attestation_ids[0])
    assert relation.relation_id not in _python_support(g, hypothesis)
    shown = _shown_as(g, relation.relation_id, hypothesis)
    print(f"E-1 measurement: every decision refuses it; the page says {shown!r}")
    assert shown is not None and "measurement provenance" in shown, shown


def test_e1_the_episode_page_does_not_show_quarantined_evidence_as_counted(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    attestation = _external_attestation(g)
    with roles.connect(roles.app) as app:
        relation = _external_support(app, g, hypothesis, attestation)
    _owner_quarantines_snapshot_of(g, attestation)
    assert relation.relation_id not in _python_support(g, hypothesis)
    shown = _shown_as(g, relation.relation_id, hypothesis)
    print(f"E-1 quarantine: every decision refuses it; the page says {shown!r}")
    assert shown is not None and "quarantined" in shown, shown


# =============================================================================================
# T-1s (open): a signature only Python can verify -- a verification authorization (011w)
# =============================================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "T-1s open: SQL cannot verify a verification authorization's signature (011w); closing "
        "it needs an owner-run verifier for authorizations, an Owner decision (see the round-6 "
        "report)"
    ),
)
def test_t1s_the_sql_confirmation_rule_does_not_count_support_on_a_forged_authorization(
    guarded, roles
):
    from tests.e2e.test_g0_forged_authorization_read_path_postgres import _forge, _support_as

    g = guarded
    with roles.connect(roles.app) as app:
        authorization = _forge(app, g, "r6-forged", SigningKey.generate().sign(b"never signed"))
        observation, evidence = g.measured("r6-forged", authorization=authorization)
        relation = _support_as(app, g, observation, evidence)
    python, sql = _python_support(g, g.hypothesis), _sql_support(g, g.hypothesis)
    print(f"T-1s forged authorization: Python admits {sorted(python)}; cwg_evidence {sorted(sql)}")
    assert relation not in python
    assert relation not in sql


# =============================================================================================
# C-1: single-row picks on the confirmation path break text ties byte-wise
# =============================================================================================

#: (function, the tie-break that must be byte-wise) -- `005h`.
BYTEWISE_PICKS = (
    ("cwg_bound_class", 'ORDER BY d.set_ref COLLATE "C", d.class_id COLLATE "C"'),
    ("confirmation_rule_breaches", 'ORDER BY set_ref COLLATE "C" LIMIT 1'),
    ("failure_analyses_confirmation_holds_the_rule", 'ORDER BY set_ref COLLATE "C" LIMIT 1'),
)


def test_c1_the_collation_hazard_is_real(db):
    """Byte-wise (C, and Python's str order) and a common ICU locale disagree on the kind of refs
    a declaration set may carry, so an un-collated tie-break depends on the database's locale."""
    ((bytewise, icu),) = db.execute(
        "SELECT 'B-set' < 'a-set' COLLATE \"C\", 'B-set' < 'a-set' COLLATE \"en-US-x-icu\""
    ).fetchall()
    assert (bytewise, icu) == ("B-set" < "a-set", False)


@pytest.mark.parametrize(("function", "tie_break"), BYTEWISE_PICKS)
def test_c1_the_confirmation_path_breaks_ties_bytewise(db, function, tie_break):
    ((definition,),) = db.execute(
        "SELECT pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.proname = %s", (function,)
    ).fetchall()
    assert tie_break in definition, f"{function}: {tie_break!r} not in its live definition"
