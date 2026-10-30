"""Authorized independent post-screening verification: accepted only when pre-registered, new and
prospective -- and retrospective self-support stays impossible (`011s`).

On a real screened episode (open via; the post-screening rival also predicts that the PROBED
contact resistance is ELEVATED -- a four-point probe measurement, a person's act, can test it):

    accepted    an active project member pre-registers the test (rival, prediction, declared
                capability) after the rival exists; the Job is bound while QUEUED; the export is
                captured after the authorization; the SUPPORTS names the registered prediction
    refused     no authorization; an authorization bound after the check ran; a check that began,
                or data captured, before the authorization; data of 2020; a relation naming no
                registered prediction; a second job under one authorization; an authorization by
                a service actor, of a pre-screening hypothesis, or backdated by its writer
    preserved   the same old evidence recorded as context (CITES); old evidence supporting a
                hypothesis formed BEFORE screening

End to end, offline (stand-in model, the research workspace, `record_authorized_measurement`): the
authorized measurement is stored as SUPPORTS, the collector reports every fact false and the scorer
counts it admissible; a late-authorized or retrospective one is stored as CITES with the refusal as
its reason and supports nothing. The flow itself registered the pack's declared kinds.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.models.job import Job
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.domains.silicon_photonics import diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.product import product_vertical
from lab_brain.evaluation import scoring
from lab_brain.evaluation.collect import support_provenance
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.capabilities import PostgresResourceBroker
from lab_brain.storage.postgres.run_outputs import SqlRunOutputSink
from lab_brain.verification.prospective import (
    AuthorizedJobs,
    MeasurementExport,
    ProspectiveRefused,
    SqlVerificationAuthorizations,
    record_authorized_measurement,
)
from lab_brain.verification.workflows import ObservedOutcome
from tests.e2e.test_g0_exploratory_screening_postgres import rows
from tests.e2e.test_g0_screening_independence_postgres import Guarded, _refused
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT

pytestmark = pytest.mark.postgres

OLD = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


def _supports(g: Guarded) -> list[str]:
    return [
        str(r)
        for (r,) in rows(
            g.db,
            "SELECT relation_id FROM relation_judgments WHERE to_entity_id = %s"
            " AND relation_type = 'SUPPORTS'",
            g.hypothesis,
        )
    ]


# -- accepted --------------------------------------------------------------------------------


def test_the_flow_registered_the_packs_declared_kinds(guarded):
    g = guarded
    declared = dict(rows(g.db, "SELECT capability_id, action_type FROM capability_declarations"))
    assert declared[sp.CAP_FOURPOINT_PROBE] == "MEASUREMENT"
    assert declared[sp.CAP_INSPECT_CONNECTIVITY] == "ANALYTICAL_RULE_CHECK"
    ((media,),) = rows(
        g.db,
        "SELECT specification_media_types FROM capability_declarations WHERE capability_id = %s",
        sp.CAP_CHARGE_DC,
    )
    assert media == [diagnosis.DEVICE_PROJECT_MEDIA_TYPE]


def test_an_authorized_prospective_measurement_supports_the_rival(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("probe")
        observation, evidence = g.measured("authorized", authorization=authorization)
        g.support(observation, [evidence], prediction=g.prediction())
        assert _supports(g) == [f"rel:{observation}"]
        (facts,) = support_provenance(g.db, g.hypothesis)
        assert all(facts[f] is False for f in scoring.SUPPORT_FACTS), facts
        assert scoring.admissible(facts)


def _between(g: Guarded) -> dt.datetime:
    """A time after the rival was proposed and before the authorization (this transaction's)."""
    ((at,),) = rows(
        g.db,
        "SELECT created_at + (now() - created_at) / 2 FROM hypotheses WHERE hypothesis_id = %s",
        g.hypothesis,
    )
    return at  # type: ignore[no-any-return]


# -- refused ---------------------------------------------------------------------------------


def test_without_authorization_it_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        observation, evidence = g.measured("unauthorized")
        _refused(g, observation, "not pre-registered", cites=[evidence])


def test_an_authorization_cannot_be_bound_after_the_check_ran(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("late-bound")
        g.measured("ran-first")
        with (
            pytest.raises(psycopg.errors.RaiseException, match="bound before its check runs"),
            g.db.transaction(force_rollback=True),
        ):
            g.db.execute(
                "INSERT INTO verification_authorization_jobs (authorization_id, job_id, bound_at)"
                " VALUES (%s, 'job:ind-ran-first', now())",
                (authorization,),
            )


def test_a_check_that_began_before_its_authorization_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("began-early")
        observation, evidence = g.measured(
            "began-early", authorization=authorization, job_at=_between(g)
        )
        _refused(g, observation, "before its authorization", [evidence], prediction=g.prediction())


def test_data_captured_before_the_authorization_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("captured-early")
        observation, evidence = g.measured(
            "captured-early", authorization=authorization, captured_at=_between(g)
        )
        _refused(
            g,
            observation,
            "captured before its authorization",
            [evidence],
            prediction=g.prediction(),
        )


def test_retrospective_data_is_refused_even_when_authorized(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("retro")
        observation, evidence = g.measured("retro", authorization=authorization, captured_at=OLD)
        _refused(g, observation, "retrospective", [evidence], prediction=g.prediction())


def test_a_relation_naming_no_registered_prediction_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("unnamed")
        observation, evidence = g.measured("unnamed", authorization=authorization)
        _refused(g, observation, "pre-registered predictions", cites=[evidence])


def test_one_authorization_licenses_one_job(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("once")
        g.measured("first", authorization=authorization)
        with pytest.raises(psycopg.errors.UniqueViolation), g.db.transaction(force_rollback=True):
            g.measured("second", authorization=authorization)


def test_only_an_active_person_of_the_project_may_authorize(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name)"
            " VALUES ('act:engine', 'AGENT_ROLE', 'a model slot')"
        )
        with (
            pytest.raises(psycopg.errors.RaiseException, match="not an active person"),
            g.db.transaction(force_rollback=True),
        ):
            g.authorize("by-a-model", actor="act:engine")


def test_a_pre_screening_hypothesis_takes_no_authorization(guarded):
    g = guarded
    ((other,),) = rows(
        g.db,
        "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s AND hypothesis_id"
        " NOT IN (SELECT hypothesis_id FROM screening_conditioned_hypotheses)"
        " ORDER BY hypothesis_id LIMIT 1",
        g.episode,
    )
    with g.db.transaction(force_rollback=True):
        g.hypothesis, original = other, g.hypothesis
        try:
            with (
                pytest.raises(psycopg.errors.RaiseException, match="not proposed after screening"),
                g.db.transaction(force_rollback=True),
            ):
                g.authorize("pre-screening", predictions=["prd:none"])
        finally:
            g.hypothesis = original


def test_an_authorization_is_dated_by_the_database_and_never_changes(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("dated")
        g.db.execute(
            "INSERT INTO verification_authorizations (authorization_id, project_id, episode_id,"
            " hypothesis_id, prediction_ids, capability_id, declaration_hash, actor_id,"
            " rationale, created_at) SELECT 'vauth:backdated', project_id, episode_id,"
            " hypothesis_id, prediction_ids, capability_id, declaration_hash, actor_id,"
            " rationale, %s FROM verification_authorizations WHERE authorization_id = %s",
            (OLD, authorization),
        )
        ((stored,),) = rows(
            g.db,
            "SELECT created_at FROM verification_authorizations"
            " WHERE authorization_id = 'vauth:backdated'",
        )
        assert stored > OLD + dt.timedelta(days=365)
        with (
            pytest.raises(psycopg.errors.RaiseException, match="append-only"),
            g.db.transaction(force_rollback=True),
        ):
            g.db.execute(
                "UPDATE verification_authorizations SET created_at = %s"
                " WHERE authorization_id = %s",
                (OLD, authorization),
            )


def test_the_loop_binds_an_authorized_job_before_it_runs(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        authorization = g.authorize("loop")
        jobs = AuthorizedJobs(SqlJobStore(g.db), SqlVerificationAuthorizations(g.db))
        job = jobs.submit(
            Job(
                job_id="job:loop-probe",
                project_id=PROJECT,
                episode_id=g.episode,
                capability_id=sp.CAP_FOURPOINT_PROBE,
                trace_id=g.screened.trace_id,
                idempotency_key="loop:probe",
                submitted_at=g.later,
            )
        )
        assert jobs.bound == [(authorization, job.job_id)]
        assert SqlVerificationAuthorizations(g.db).for_job(job.job_id) is not None


# -- preserved -------------------------------------------------------------------------------


def test_retrospective_evidence_is_still_recorded_as_context(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        observation, evidence = g.measured("context", captured_at=OLD)
        g.db.execute(
            "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
            " relation_type, supporting_attestation_ids, project_id)"
            " VALUES (%s, %s, %s, 'CITES', %s, %s)",
            (f"rel:cites-{observation}", observation, g.hypothesis, [evidence], PROJECT),
        )
        assert not _supports(g)


def test_old_evidence_still_supports_a_hypothesis_formed_before_screening(guarded):
    g = guarded
    ((other,),) = rows(
        g.db,
        "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s AND hypothesis_id"
        " NOT IN (SELECT hypothesis_id FROM screening_conditioned_hypotheses)"
        " ORDER BY hypothesis_id LIMIT 1",
        g.episode,
    )
    with g.db.transaction(force_rollback=True):
        observation, evidence = g.measured("pre-screening", captured_at=OLD)
        g.db.execute(
            "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
            " relation_type, supporting_attestation_ids, project_id)"
            " VALUES (%s, %s, %s, 'SUPPORTS', %s, %s)",
            (f"rel:pre-{observation}", observation, other, [evidence], PROJECT),
        )


# -- end to end, offline ----------------------------------------------------------------------


def _record(g: Guarded, authorization: str, name: str, captured_at: dt.datetime) -> Any:
    store = InMemoryArtifactStore()
    now = lambda: dt.datetime.now(dt.UTC)  # noqa: E731
    outputs = SqlRunOutputSink(connection=g.db, store=store, now=now)
    vertical = product_vertical(
        outputs=outputs, jobs=SqlJobStore(g.db), broker=PostgresResourceBroker(g.db), now=now
    )
    counter = iter(range(1000))
    return record_authorized_measurement(
        connection=g.db,
        outputs=outputs,
        authorization_id=authorization,
        export=MeasurementExport(
            name=f"{name}.csv",
            media_type="text/csv",
            data=f"bias_v,r_ohm\n0.0,812.4\n# {name}\n".encode(),
            captured_at=captured_at,
            device="probe station 2",
            reading=ObservedOutcome(
                observable_ref=sp.OBS_PROBE,
                outcome_space_id=sp.SPACE_PROBE,
                outcome_space_version=sp.SPACE_VERSION,
                outcome="ELEVATED",
                epistemic_type=EpistemicType.MEASURED,
                authority_class="MEAS_CALIBRATED",
                method_ref="sp.rule.probe_contact@1.0.0",
                unit="ohm",
            ),
        ),
        measured_by=g.actor,
        trace_id=g.screened.trace_id,
        conditions=dict(g.screened.conditions),
        conditions_schema_version=g.screened.conditions_schema_version,
        compare=vertical.registry.registries.conditions.compare,
        mint=lambda kind: f"{kind}:{name}-{next(counter)}",
        now=now,
    )


def test_end_to_end_an_authorized_measurement_is_recorded_as_admissible_support(guarded):
    g = guarded
    auths = SqlVerificationAuthorizations(g.db)
    with g.db.transaction(force_rollback=True):
        auths.authorize(
            authorization_id="vauth:e2e",
            project_id=PROJECT,
            hypothesis_id=g.hypothesis,
            prediction_ids=[g.prediction()],
            capability_id=sp.CAP_FOURPOINT_PROBE,
            actor_id=g.actor,
            rationale="an open via should raise the probed contact resistance",
        )
        _evidence, stored = _record(g, "vauth:e2e", "e2e", dt.datetime.now(dt.UTC))
        to_rival = [r for r in stored if r.to_entity_id == g.hypothesis]
        assert [r.relation_type.value for r in to_rival] == ["SUPPORTS"]
        (facts,) = support_provenance(g.db, g.hypothesis)
        assert scoring.admissible(facts), facts


def test_end_to_end_a_late_authorized_measurement_is_context_not_support(guarded):
    g = guarded
    auths = SqlVerificationAuthorizations(g.db)
    # Taken after the rival existed, before anyone pre-registered a test of it.
    taken = dt.datetime.now(dt.UTC)
    with g.db.transaction(force_rollback=True):
        auths.authorize(
            authorization_id="vauth:late",
            project_id=PROJECT,
            hypothesis_id=g.hypothesis,
            prediction_ids=[g.prediction()],
            capability_id=sp.CAP_FOURPOINT_PROBE,
            actor_id=g.actor,
            rationale="registered after the data was taken",
        )
        _evidence, stored = _record(g, "vauth:late", "late", taken)
        (relation,) = [r for r in stored if r.to_entity_id == g.hypothesis]
        assert relation.relation_type.value == "CITES"
        assert "before its authorization" in relation.attributes["not_support"]
        assert not _supports(g)


def test_end_to_end_retrospective_data_is_context_not_support(guarded):
    g = guarded
    auths = SqlVerificationAuthorizations(g.db)
    with g.db.transaction(force_rollback=True):
        auths.authorize(
            authorization_id="vauth:old",
            project_id=PROJECT,
            hypothesis_id=g.hypothesis,
            prediction_ids=[g.prediction()],
            capability_id=sp.CAP_FOURPOINT_PROBE,
            actor_id=g.actor,
            rationale="an old log, registered today",
        )
        _evidence, stored = _record(g, "vauth:old", "old", OLD)
        (relation,) = [r for r in stored if r.to_entity_id == g.hypothesis]
        assert relation.relation_type.value == "CITES"
        assert not _supports(g)


def test_end_to_end_nothing_is_recorded_without_an_authorization(guarded):
    g = guarded
    with pytest.raises(ProspectiveRefused, match="no verification authorization"):
        _record(g, "vauth:nobody-made-this", "none", dt.datetime.now(dt.UTC))
