"""Every rule of a verification authorization, and the guard's own copy of each (`011s`).

The mutation battery showed these rules had no test of their own: a mutant that switched any one
off survived. Each is shown here on the real screened episode (`Guarded`).

    the authorization trigger   another episode; made before the hypothesis; a stale declaration
                                hash; a lookup as a "test"; a prediction of another hypothesis;
                                bound to a job of another capability
    the guard, rows edited      the same rules read again at SUPPORT time, with the authorization
                                (or the capability) written past its trigger -- standing in for
                                a trigger that failed or a database edited by hand: an
                                authorization of another hypothesis, of another capability, under
                                another declaration; a capability re-registered as another kind
    the guard's evidence rules  a declared lookup; an artifact recorded before the hypothesis
                                (whatever capture time it claims); a lineage naming an artifact
                                that was never recorded
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.capability import ActionType
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.plugin import PACK_VERSION
from lab_brain.storage.postgres.capabilities import register_pack_declarations
from tests.e2e.test_g0_screening_independence_postgres import PROBE_METHOD, Guarded, _refused
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT

pytestmark = pytest.mark.postgres

OLD = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
LOOKUP = "cap:sp.probe_lookup"
_COLUMNS = (
    "authorization_id, project_id, episode_id, hypothesis_id, prediction_ids, capability_id,"
    " declaration_hash, actor_id, rationale, created_at, enrolment_id, signature, signed_at"
)


def _copy(g: Guarded, source: str, name: str, **changes: Any) -> str:
    """A copy of authorization `source` named `vauth:<name>`, with `changes` (column: value)."""
    columns = [c.strip() for c in _COLUMNS.split(",")]
    select = ", ".join("%s" if c in changes or c == "authorization_id" else c for c in columns)
    values = [f"vauth:{name}", *[changes[c] for c in columns if c in changes]]
    g.db.execute(
        f"INSERT INTO verification_authorizations ({_COLUMNS}) SELECT {select}"
        " FROM verification_authorizations WHERE authorization_id = %s",
        (*values, source),
    )
    return f"vauth:{name}"


def _past_its_trigger(g: Guarded, source: str, name: str, **changes: Any) -> str:
    """`_copy`, with the authorization trigger switched off (the transaction rolls back)."""
    g.db.execute(
        "ALTER TABLE verification_authorizations"
        " DISABLE TRIGGER verification_authorization_is_prospective_trg"
    )
    try:
        return _copy(g, source, name, **changes)
    finally:
        g.db.execute(
            "ALTER TABLE verification_authorizations"
            " ENABLE TRIGGER verification_authorization_is_prospective_trg"
        )


def _refused_authorization(g: Guarded, why: str, **changes: Any) -> None:
    source = g.authorize("source")
    with (
        pytest.raises(psycopg.errors.RaiseException, match=why),
        g.db.transaction(force_rollback=True),
    ):
        _copy(g, source, "refused", **changes)


def _declare_lookup(g: Guarded) -> None:
    """A declared EXISTING_EVIDENCE_LOOKUP that reports the probed observable, as an owner would
    register one -- the kind the rules say can never be a prospective test."""
    probe = next(c for c in sp.capabilities() if c.capability_id == sp.CAP_FOURPOINT_PROBE)
    lookup = probe.model_copy(
        update={
            "capability_id": LOOKUP,
            "action_type": ActionType.EXISTING_EVIDENCE_LOOKUP,
            "backend_id": "sp.lookup",
        }
    )
    assert (
        register_pack_declarations(
            g.db, pack_id=sp.DOMAIN, pack_version=PACK_VERSION, capabilities=((lookup, ()),)
        )
        == ()
    )


# -- the authorization trigger ---------------------------------------------------------------


def test_an_authorization_of_another_episode_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _refused_authorization(g, "is a hypothesis of episode", episode_id="ep:another")


def test_an_authorization_made_before_its_hypothesis_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        source = g.authorize("source")
        g.db.execute("ALTER TABLE hypotheses DISABLE TRIGGER USER")
        g.db.execute(
            "UPDATE hypotheses SET created_at = now() + interval '1 day' WHERE hypothesis_id = %s",
            (g.hypothesis,),
        )
        g.db.execute("ALTER TABLE hypotheses ENABLE TRIGGER USER")
        with (
            pytest.raises(psycopg.errors.RaiseException, match="not after hypothesis"),
            g.db.transaction(force_rollback=True),
        ):
            _copy(g, source, "early")


def test_an_authorization_under_a_stale_declaration_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _refused_authorization(g, "is declared as", declaration_hash="sha256:" + "0" * 64)


def test_a_lookup_cannot_be_authorized_as_a_test(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _declare_lookup(g)
        with (
            pytest.raises(psycopg.errors.RaiseException, match="reads or judges existing"),
            g.db.transaction(force_rollback=True),
        ):
            g.authorize("lookup", capability_id=LOOKUP)


def test_an_authorization_naming_a_foreign_prediction_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _refused_authorization(g, "is not a prediction of", prediction_ids=["prd:another"])


def test_an_authorization_cannot_bind_a_job_of_another_capability(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("probe")
        with (
            pytest.raises(psycopg.errors.RaiseException, match=r"is not a .* job of episode"),
            g.db.transaction(force_rollback=True),
        ):
            # The screened capability's job, under an authorization of the four-point probe.
            g.run("other-capability", authorization=authorization)


# -- the guard reads each rule again ---------------------------------------------------------


def _bound_measurement(g: Guarded, authorization: str, name: str) -> tuple[str, str]:
    """A probe measurement bound to `authorization` past the binding trigger."""
    g.db.execute(
        "ALTER TABLE verification_authorization_jobs"
        " DISABLE TRIGGER verification_job_is_bound_before_it_runs_trg"
    )
    try:
        return g.measured(name, authorization=authorization)
    finally:
        g.db.execute(
            "ALTER TABLE verification_authorization_jobs"
            " ENABLE TRIGGER verification_job_is_bound_before_it_runs_trg"
        )


def test_the_guard_refuses_an_authorization_of_another_hypothesis(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        ((other,),) = g.db.execute(
            "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s"
            " AND hypothesis_id <> %s ORDER BY hypothesis_id LIMIT 1",
            (g.episode, g.hypothesis),
        ).fetchall()
        source = g.authorize("source")
        forged = _past_its_trigger(g, source, "other-hypothesis", hypothesis_id=other)
        observation, evidence = _bound_measurement(g, forged, "other-hypothesis")
        _refused(g, observation, "as a test of", [evidence], prediction=g.prediction())


def test_the_guard_refuses_an_authorization_of_another_capability(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        source = g.authorize("source")
        forged = _past_its_trigger(
            g, source, "other-capability", capability_id=g.screened.capability_id
        )
        observation, evidence = _bound_measurement(g, forged, "other-capability")
        _refused(g, observation, r"its authorization .* licensed", [evidence], g.prediction())


def test_the_guard_refuses_an_authorization_under_another_declaration(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        source = g.authorize("source")
        forged = _past_its_trigger(
            g, source, "other-declaration", declaration_hash="sha256:" + "1" * 64
        )
        observation, evidence = g.measured("other-declaration", authorization=forged)
        _refused(g, observation, "under another declaration", [evidence], g.prediction())


def test_the_guard_refuses_a_capability_re_registered_as_another_kind(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        observation, evidence = g.measured("rekinded", authorization=g.authorize("rekinded"))
        g.db.execute(
            "ALTER TABLE capabilities DISABLE TRIGGER capabilities_declared_contract_is_fixed_trg"
        )
        g.db.execute(
            "UPDATE capabilities SET action_type = 'SIMULATION' WHERE capability_id = %s",
            (sp.CAP_FOURPOINT_PROBE,),
        )
        g.db.execute(
            "ALTER TABLE capabilities ENABLE TRIGGER capabilities_declared_contract_is_fixed_trg"
        )
        _refused(g, observation, "registered as SIMULATION", [evidence], g.prediction())


# -- the guard's evidence rules --------------------------------------------------------------


def test_a_declared_lookup_cannot_support(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _declare_lookup(g)
        run = g.run(
            "lookup",
            capability_id=LOOKUP,
            backend_id="sp.lookup",
            input_artifacts=(),
            input_parameters={"variant": "lookup"},
            output_artifacts=(g.artifact("lookup result", captured_at=g.later),),
        )
        observation = g.observe(run, "lookup", sp.OBS_PROBE, "ELEVATED")
        evidence = g.attest(observation, run, PROBE_METHOD)
        _refused(g, observation, "reads existing evidence", [evidence], g.prediction())


def test_an_artifact_recorded_before_the_hypothesis_cannot_support(guarded):
    """Whatever capture time it claims: the row existed before the hypothesis was proposed."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("recorded-early")
        observation, evidence = g.measured("recorded-early", authorization=authorization)
        g.db.execute("ALTER TABLE artifacts DISABLE TRIGGER USER")
        g.db.execute(
            "UPDATE artifacts SET created_at = %s WHERE artifact_id = ANY ("
            " SELECT unnest(output_artifacts) FROM runs WHERE run_id = 'run:ind-recorded-early')",
            (OLD,),
        )
        g.db.execute("ALTER TABLE artifacts ENABLE TRIGGER USER")
        _refused(g, observation, "recorded before the hypothesis", [evidence], g.prediction())


def test_a_lineage_naming_an_unrecorded_artifact_cannot_support(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        missing = "art:sha256:" + hashlib.sha256(b"never recorded").hexdigest()
        export = g.artifact("derived export", captured_at=g.later, derived_from=(missing,))
        run = g.run(
            "unrecorded",
            authorization=g.authorize("unrecorded"),
            capability_id=sp.CAP_FOURPOINT_PROBE,
            backend_id="lab.probe_station",
            input_artifacts=(),
            input_parameters={"variant": "unrecorded"},
            output_artifacts=(export,),
        )
        observation = g.observe(run, "unrecorded", sp.OBS_PROBE, "ELEVATED")
        evidence = g.attest(observation, run, PROBE_METHOD)
        _refused(g, observation, "which is not recorded", [evidence], g.prediction())


def test_the_project_is_the_episodes(guarded):
    """The helpers above write into the episode's own project (a sanity check of the fixture)."""
    g = guarded
    ((project,),) = g.db.execute(
        "SELECT project_id FROM hypotheses WHERE hypothesis_id = %s", (g.hypothesis,)
    ).fetchall()
    assert project == PROJECT


def test_a_declaration_whose_hash_is_not_its_text_is_refused(guarded):
    """Even the schema owner cannot store a declaration under a hash that is not its SHA-256."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        _declare_lookup(g)
        with (
            pytest.raises(psycopg.errors.RaiseException, match="hash is not the SHA-256"),
            g.db.transaction(force_rollback=True),
        ):
            g.db.execute(
                "INSERT INTO capability_declarations (capability_id, capability_version, pack_id,"
                " pack_version, action_type, specification_media_types, declaration,"
                " declaration_hash, registered_by, registered_at)"
                " SELECT %s, capability_version, pack_id, pack_version, action_type,"
                " specification_media_types, declaration, 'sha256:' || repeat('0', 64),"
                " registered_by, registered_at FROM capability_declarations"
                " WHERE capability_id = %s",
                ("cap:sp.probe_lookup_copy", LOOKUP),
            )


def test_a_declaration_that_misstates_the_capability_is_refused(guarded):
    """A correctly hashed declaration that calls the lookup a MEASUREMENT: not the pack's code."""
    import json

    g = guarded
    with g.db.transaction(force_rollback=True):
        _declare_lookup(g)
        ((text,),) = g.db.execute(
            "SELECT declaration FROM capability_declarations WHERE capability_id = %s", (LOOKUP,)
        ).fetchall()
        forged = json.dumps({**json.loads(text), "action_type": "MEASUREMENT"})
        digest = "sha256:" + hashlib.sha256(forged.encode()).hexdigest()
        with (
            pytest.raises(psycopg.errors.RaiseException, match="does not describe"),
            g.db.transaction(force_rollback=True),
        ):
            g.db.execute(
                "INSERT INTO capability_declarations (capability_id, capability_version, pack_id,"
                " pack_version, action_type, specification_media_types, declaration,"
                " declaration_hash, registered_by, registered_at)"
                " SELECT capability_id, capability_version, pack_id, pack_version, 'MEASUREMENT',"
                " specification_media_types, %s, %s, registered_by, registered_at"
                " FROM capability_declarations WHERE capability_id = %s",
                (forged, digest, LOOKUP),
            )
