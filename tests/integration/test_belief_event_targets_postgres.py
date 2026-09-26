"""R-12, closed (M3 / EPI-001, `011j`): a belief event names a hypothesis admitted in its project.

    `v3.3-a12` / §17.13  Genesis 不參與此義務 ... `target_id` 仍無 foreign key（R-12），留給
                         EPI-001/M3。

Every write path is tried -- the Python store, `belief_revision_event_append`, a bare INSERT -- and
the foreign key is shown to hold on its own with the explanatory trigger switched off, so the
guarantee does not rest on the trigger. M0b's rule that two projects may use the same hypothesis id
is kept, because identity is the (project_id, hypothesis_id) pair M0b's replay already keys on.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg
import pytest

from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.repositories.belief_events import SqlBeliefEventStore
from tests.debate_fixtures import ADMISSION_POLICY, PROJECT, T0, TRACE, build_world
from tests.postgres_fixtures import admit_hypothesis_identity

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-001"),
    pytest.mark.spec_test("T-EPI-001"),
]

ROOT = Path(__file__).resolve().parents[2]
OTHER = "prj:m3-other"


class _Rollback(Exception):
    """Raised to leave a transaction that deliberately weakened the schema, undoing it."""


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    built = build_world(connection=db)
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    return built


def _basis(world):  # type: ignore[no-untyped-def]
    return next(iter(world.attestations.values()))


def _genesis(world, hypothesis_id: str, *, project_id: str = PROJECT, event_id: str = "bre:ghost"):  # type: ignore[no-untyped-def]
    basis = _basis(world)
    return admit_hypothesis(
        event_id=event_id,
        policy=ADMISSION_POLICY,
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        prior=EpistemicStateProjection(
            project_id=project_id, target_id=hypothesis_id, current_state=None, last_event_id=None
        ),
        occurred_at=T0,
        trace_id=TRACE,
        triggering_attestations=(basis,) if basis.project_id == project_id else (),
    )


def _append_sql(db, event_id: str, project_id: str, target: str, attestation_id: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, NULL, 'ACTIVE',"
        " ARRAY[%s], ARRAY[]::text[], %s, %s, NULL, NULL, NULL, %s, %s, NULL)",
        (
            event_id,
            project_id,
            target,
            attestation_id,
            ADMISSION_POLICY.policy_id,
            ADMISSION_POLICY.version,
            T0,
            TRACE,
        ),
    )


def _events(db, target: str) -> int:  # type: ignore[no-untyped-def]
    return db.execute(
        "SELECT count(*) FROM belief_revision_events WHERE target_id = %s", (target,)
    ).fetchone()[0]


def test_no_write_path_can_target_a_hypothesis_nobody_admitted(world, db):
    with pytest.raises(psycopg.errors.RaiseException, match="never admitted"):
        SqlBeliefEventStore(db).append(_genesis(world, "hyp:ghost"))
    with pytest.raises(psycopg.errors.RaiseException, match="never admitted"):
        _append_sql(db, "bre:ghost-fn", PROJECT, "hyp:ghost", _basis(world).attestation_id)
    with pytest.raises(psycopg.errors.RaiseException, match="never admitted"):
        db.execute(
            "INSERT INTO belief_revision_events (event_id, project_id, target_type, target_id,"
            " from_state, to_state, policy_id, policy_version, occurred_at, trace_id)"
            " VALUES ('bre:ghost-raw', %s, 'HYPOTHESIS', 'hyp:ghost', NULL, 'ACTIVE', %s, %s,"
            " %s, %s)",
            (PROJECT, ADMISSION_POLICY.policy_id, ADMISSION_POLICY.version, T0, TRACE),
        )
    assert _events(db, "hyp:ghost") == 0


def test_an_event_cannot_target_another_projects_hypothesis(world, db):
    """The key is the pair: a hypothesis admitted in one project is not a target in another."""
    outcome = world.debate.run(world.request())
    admitted = outcome.certificates[0].hypothesis_id
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance) SELECT 'att:other', claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, %s, extractor_version,"
        " extraction_provenance FROM attestations WHERE attestation_id = %s",
        (OTHER, _basis(world).attestation_id),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="never admitted"):
        _append_sql(db, "bre:cross", OTHER, admitted, "att:other")
    assert _events(db, admitted) == 1  # its own genesis, in its own project


def test_the_foreign_key_holds_on_its_own(world, db):
    """With the explanatory trigger switched off, the key alone still refuses (then rolled back)."""
    with pytest.raises(_Rollback), db.transaction():
        db.execute(
            "ALTER TABLE belief_revision_events"
            " DISABLE TRIGGER hypothesis_revisions_meet_m3_preconditions_trg"
        )
        with pytest.raises(
            psycopg.errors.ForeignKeyViolation,
            match="belief_revision_events_target_is_an_admitted_hypothesis",
        ):
            _append_sql(db, "bre:fk", PROJECT, "hyp:ghost", _basis(world).attestation_id)
        raise _Rollback
    enabled = db.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgname = 'hypothesis_revisions_meet_m3_preconditions_trg'"
    ).fetchone()[0]
    assert enabled == "O", "the rollback restored the trigger"


def test_two_projects_may_use_the_same_hypothesis_id(world, db):
    """M0b's rule, kept: identity is (project_id, hypothesis_id), and the histories stay apart."""
    for project in (PROJECT, OTHER):
        admit_hypothesis_identity(db, "hyp:shared", project_id=project, actor_id="act:researcher")
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance) SELECT 'att:other', claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, %s, extractor_version,"
        " extraction_provenance FROM attestations WHERE attestation_id = %s",
        (OTHER, _basis(world).attestation_id),
    )
    _append_sql(db, "bre:mine", PROJECT, "hyp:shared", _basis(world).attestation_id)
    _append_sql(db, "bre:theirs", OTHER, "hyp:shared", "att:other")
    store = SqlBeliefEventStore(db)
    assert [e.event_id for e in store.history(PROJECT, "hyp:shared")] == ["bre:mine"]
    assert [e.event_id for e in store.history(OTHER, "hyp:shared")] == ["bre:theirs"]


def test_the_identity_is_the_pair_in_the_schema(db):
    rows = dict(
        db.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname IN ('hypotheses_pkey',"
            " 'belief_revision_events_target_is_an_admitted_hypothesis',"
            " 'predictions_hypothesis_in_project')"
        ).fetchall()
    )
    assert rows["hypotheses_pkey"] == "PRIMARY KEY (project_id, hypothesis_id)"
    assert rows["belief_revision_events_target_is_an_admitted_hypothesis"] == (
        "FOREIGN KEY (project_id, target_id) REFERENCES hypotheses(project_id, hypothesis_id)"
    )
    assert "(project_id, hypothesis_id)" in rows["predictions_hypothesis_in_project"]


def test_the_migration_refuses_to_close_r12_over_an_unadmitted_history(world, db):
    """`011j`'s first block, replayed against a database holding an orphan history: it refuses
    with the remedy rather than validating around the orphan (`NOT VALID` would have hidden it)."""
    source = (ROOT / "migrations" / "011j_belief_event_targets.sql").read_text(encoding="utf-8")
    guard = re.search(r"DO \$\$.*?\$\$;", source, re.DOTALL)
    assert guard is not None
    with pytest.raises(_Rollback), db.transaction():
        db.execute(
            "ALTER TABLE belief_revision_events"
            " DROP CONSTRAINT belief_revision_events_target_is_an_admitted_hypothesis"
        )
        db.execute(
            "ALTER TABLE belief_revision_events"
            " DISABLE TRIGGER hypothesis_revisions_meet_m3_preconditions_trg"
        )
        _append_sql(db, "bre:legacy-orphan", PROJECT, "hyp:legacy", _basis(world).attestation_id)
        with pytest.raises(psycopg.errors.RaiseException, match="011j: 1 belief revision event"):
            db.execute(guard.group(0))
        raise _Rollback
    assert _events(db, "hyp:legacy") == 0
