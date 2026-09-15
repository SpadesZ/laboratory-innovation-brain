"""The database enforces the event log, not only the Python model (EPI-003).

Same rule as the cost ledger and the span table: a model invariant holds for callers who go through
the model, and a migration, a support script or a future service writes SQL. If "belief revision is
append-only" holds only in `BeliefRevisionEvent`, it holds only in Python -- and §6.18's whole point
is that nobody can repair a belief by editing the current status.

So each invariant is asserted twice: once against the model in tests/contract/, once here against
the schema.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os

import psycopg
import pytest

from lab_brain.core.belief import authorize_transition, rederive_decision
from lab_brain.core.models import (
    BeliefRevisionEvent,
    BeliefState,
    BeliefTargetType,
    TransitionOutcome,
)
from lab_brain.core.models.decision import BeliefTransitionDecision
from lab_brain.core.repositories import (
    BeliefEventError,
    InMemoryBeliefEventStore,
    NonDurableClaimStoreError,
    SqlBeliefEventStore,
)
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from tests.conftest_fixtures import forged_authorization, make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-003"),
    pytest.mark.spec_test("T-EPI-003"),
]

T0 = dt.datetime(2026, 9, 15, 10, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
TARGET = "hyp:rs-contact-resistance"
TRACE = "trc:episode-1"
DEFAULT_URL = "postgresql://lab_brain:lab_brain@localhost:5433/lab_brain"


@pytest.fixture
def seeded(db):  # type: ignore[no-untyped-def]
    """A project, an actor, one attestation and one relation the events can legitimately cite.

    Real rows rather than ids, because a triggering reference is a foreign key -- §6.18's rollback
    is the join "which events did this attestation trigger", and the point of the join table is
    that the reference resolves.
    """
    artifact = make_artifact(b"a belief-event fixture")
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, uri, media_type, source_origin,"
        " lineage_id, lineage_revision) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            artifact.artifact_id,
            artifact.content_hash,
            artifact.uri,
            artifact.media_type,
            artifact.source_origin.value,
            artifact.lineage_id,
            artifact.lineage_revision,
        ),
    )
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'rs high')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0',"
        ' \'{"type": "object", "properties": {}}\'::jsonb, \'1.0.0\')'
        " ON CONFLICT DO NOTHING"
    )
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance)"
        " VALUES ('att:1', 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb,"
        " 'core/sch_test@1.0.0', %s, '1.0.0',"
        ' \'{"extractor_id": "ext:test", "extractor_version": "1.0.0"}\'::jsonb)',
        (artifact.artifact_id, PROJECT),
    )
    db.execute(
        "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
        " relation_type, project_id, actor_id)"
        " VALUES ('rel:1', 'att:1', 'clm:1', 'SUPPORTS', %s, 'act:test')",
        (PROJECT,),
    )
    # The policy every event below cites. Registered because migration 005b made an event's
    # `(policy_id, policy_version)` a foreign key into `transition_policies` -- an event whose
    # authorising policy version does not exist cannot be re-derived, which is the whole point of
    # `v3.3-a11`. This fixture predates that constraint and the constraint is what broke it.
    db.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state)"
        " VALUES ('pol:hypothesis-default', '1.0.0', 'ACTIVE', 'SUPPORTED')"
    )
    # `v3.3-a12` makes a non-genesis event's authorization required, so the fixture has to record
    # one. Computed by actually evaluating the policy rather than hand-written: a fixture that
    # asserted its own ALLOW would be the forgery these tests are about.
    _real_authorization(db)
    return db


def _real_authorization(
    db,  # type: ignore[no-untyped-def]
    decision_id: str = "dec:1",
    **overrides: object,
) -> BeliefTransitionDecision:
    """An authorization produced by `authorize_transition` and stored through its real store."""
    from tests.contract.test_transition_policy import hypothesis, policy, relation, summary

    defaults: dict[str, object] = {
        "decision_id": decision_id,
        "policy": policy(),
        "hypothesis": hypothesis(project_id=PROJECT, hypothesis_id=TARGET),
        "admitted_relations": (relation(project_id=PROJECT, to_entity_id=TARGET),),
        "independence_summary": summary(),
        "candidate_to_state": BeliefState.SUPPORTED,
        "created_at": T0,
    }
    defaults.update(overrides)
    decision = authorize_transition(**defaults)  # type: ignore[arg-type]
    return SqlBeliefTransitionDecisionStore(db).record(decision)


def event(**overrides: object) -> BeliefRevisionEvent:
    defaults: dict[str, object] = {
        "event_id": "bre:1",
        "project_id": PROJECT,
        "target_type": BeliefTargetType.HYPOTHESIS,
        "target_id": TARGET,
        "from_state": BeliefState.ACTIVE,
        "to_state": BeliefState.SUPPORTED,
        "triggering_relation_ids": ("rel:1",),
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "authorization_decision_id": "dec:1",
        "occurred_at": T0,
        "trace_id": TRACE,
    }
    defaults.update(overrides)
    if defaults.get("from_state") is None:
        defaults["authorization_decision_id"] = None
    return BeliefRevisionEvent(**defaults)  # type: ignore[arg-type]


def _stored(db, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    """An event in the table, written the supported way.

    Not `_raw`: since migration `005c` a bare INSERT of an event with no trigger references is
    refused by a deferred constraint trigger, so the only way to get a *valid* row in is the append
    function -- which is the point of that constraint.
    """
    SqlBeliefEventStore(db).append(forged_authorization(event(**overrides)))


def _raw(db, event_id: str = "bre:1", **overrides: object) -> None:  # type: ignore[no-untyped-def]
    """Insert straight into the table, bypassing the model and the append function.

    Used for the constraint tests, where the row is *expected* to be refused. A row that would be
    accepted cannot be written this way any more (see `_stored`).
    """
    values: dict[str, object] = {
        "event_id": event_id,
        "project_id": PROJECT,
        "target_type": "HYPOTHESIS",
        "target_id": TARGET,
        "from_state": "ACTIVE",
        "to_state": "SUPPORTED",
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "authorization_decision_id": "dec:1",
        "occurred_at": T0,
        "trace_id": TRACE,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({k})s" for k in values)
    db.execute(f"INSERT INTO belief_revision_events ({columns}) VALUES ({placeholders})", values)


# --------------------------------------------------------------------------------------------
# Append-only. §6.18 / AGT-009.
# --------------------------------------------------------------------------------------------


def test_an_event_cannot_be_updated(seeded):
    """The sentence this table exists for: 不得靠手改 current status.

    If a recorded revision could be edited, nobody could tell later which beliefs were derived and
    which were asserted.
    """
    _stored(seeded)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute(
            "UPDATE belief_revision_events SET to_state = 'CONTRADICTED' WHERE event_id = 'bre:1'"
        )


def test_an_event_cannot_be_deleted(seeded):
    """Deleting the inconvenient events is the cheapest way to make a belief look well-founded."""
    _stored(seeded)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute("DELETE FROM belief_revision_events WHERE event_id = 'bre:1'")


def test_the_trigger_references_cannot_be_changed(seeded):
    """The same rewrite one level down.

    An event whose citations can be edited afterwards still claims it was authorised by evidence it
    no longer names.
    """
    SqlBeliefEventStore(seeded).append(forged_authorization(event()))
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute("DELETE FROM belief_revision_event_relations WHERE event_id = 'bre:1'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute(
            "UPDATE belief_revision_event_relations SET relation_id = 'rel:1'"
            " WHERE event_id = 'bre:1'"
        )


def test_an_event_id_cannot_be_reused(seeded):
    """One id, one revision. A second event under the same id is a replacement in disguise."""
    _stored(seeded)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _stored(seeded)


# --------------------------------------------------------------------------------------------
# A transition has to be a transition, at the schema level too.
# --------------------------------------------------------------------------------------------


def test_an_event_that_changes_nothing_is_rejected(seeded):
    """Refused twice over since 005c, and the trigger gets there first.

    A BEFORE INSERT trigger runs before CHECK constraints, so what fires is the policy-governance
    check: no registered policy can govern ACTIVE -> ACTIVE (005b forbids it), so no event can
    record it. The `actually_change_state` CHECK remains as the second line, unreachable through a
    registered policy -- which is the right order, since the trigger's message says *why*.
    """
    with pytest.raises(psycopg.errors.RaiseException, match="never authorised by it"):
        _raw(seeded, from_state="ACTIVE", to_state="ACTIVE")


def test_an_event_out_of_a_terminal_state_is_rejected(seeded):
    """Also caught by the governance trigger first: 005b forbids a policy out of a terminal state,
    so no registered policy governs the pair this event records."""
    for terminal in ("EVOLVED", "SUPERSEDED"):
        with pytest.raises(psycopg.errors.RaiseException, match="never authorised by it"):
            _raw(seeded, f"bre:{terminal}", from_state=terminal, to_state="ACTIVE")


def test_an_unknown_state_is_rejected(seeded):
    """Notably REJECTED, which §8.2.1's prose implies and §8.2's lifecycle does not contain.

    The governance trigger reaches it first -- no policy governs a transition to a state that does
    not exist -- and the CHECK on the column stands behind it.
    """
    with pytest.raises(psycopg.errors.RaiseException, match="never authorised by it"):
        _raw(seeded, to_state="REJECTED")
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute(
            "INSERT INTO transition_policies (policy_id, version, from_state,"
            " candidate_to_state) VALUES ('pol:bad', '1.0.0', 'ACTIVE', 'REJECTED')"
        )


def test_an_unknown_target_type_is_rejected(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        _raw(seeded, target_type="CLAIM")


def test_an_event_requires_a_real_project(seeded):
    """`v3.3-a11`: the project is what makes a scoped replay expressible at all.

    Since `v3.3-a12` the authorization trigger reaches this row first -- an authorization for
    `prj:test` does not cover an event in `prj:nowhere` -- so the refusal is reported there and
    the project foreign key sits behind it. Both are asserted: the message here, the constraint's
    continued existence in `test_the_project_foreign_key_is_still_in_place_behind_the_trigger`.
    """
    with pytest.raises(
        (psycopg.errors.ForeignKeyViolation, psycopg.errors.RaiseException),
        match=r"violates foreign key|does not transfer",
    ):
        _raw(seeded, project_id="prj:nowhere")


def test_the_project_foreign_key_is_still_in_place_behind_the_trigger(seeded):
    """The trigger fires first, so the constraint is asserted by name rather than by behaviour.

    Without this, dropping the foreign key would leave the suite green: the trigger would keep
    refusing the one case the test above exercises, and a row that slipped past the trigger would
    have nothing left to check it.
    """
    found = seeded.execute(
        "SELECT 1 FROM pg_constraint WHERE conrelid = 'belief_revision_events'::regclass"
        " AND contype = 'f' AND confrelid = 'projects'::regclass"
    ).fetchone()
    assert found is not None, "belief_revision_events no longer references projects"


def test_an_event_requires_a_real_actor_when_one_is_named(seeded):
    """§14.4: no governance without "who". A manual correction attributed to nobody attributes
    nothing."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _raw(seeded, actor_id="act:ghost")


# --------------------------------------------------------------------------------------------
# The event and its references are one fact. The lesson 010b cost, applied up front.
# --------------------------------------------------------------------------------------------


def test_an_event_citing_an_attestation_that_does_not_exist_writes_nothing(seeded):
    """Not "writes the event and fails the reference" -- writes nothing.

    These tables are append-only in both directions, so a half-written event could never be
    completed *or* removed. That is strictly worse than the span defect 010b fixed, which is why
    the append is one statement from the start.
    """
    store = SqlBeliefEventStore(seeded)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        store.append(forged_authorization(event(triggering_attestation_ids=("att:nowhere",))))

    # The row count first, deliberately. It is the property; `store.get()` would raise on a
    # half-written event and the failure would land on hydration rather than on the thing that
    # went wrong -- which is the mistake the P6 audit caught in the span atomicity tests.
    rows = seeded.execute("SELECT count(*) FROM belief_revision_events").fetchone()
    assert rows[0] == 0, "the event row must not have been written without its references"
    refs = seeded.execute("SELECT count(*) FROM belief_revision_event_attestations").fetchone()
    assert refs[0] == 0
    assert store.get("bre:1") is None


def test_an_event_with_no_triggers_is_refused_by_the_database(seeded):
    """The rule cannot live in a CHECK -- it spans the join tables -- so it lives in the append.

    Asserted against the function rather than the model, because the model's validator is not what
    a support script writing SQL would go through.
    """
    with pytest.raises(psycopg.errors.RaiseException, match="cites no triggering"):
        seeded.execute(
            "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, 'ACTIVE',"
            " 'SUPPORTED', ARRAY[]::text[], ARRAY[]::text[], 'pol:hypothesis-default', '1.0.0',"
            " NULL, NULL, NULL, %s, %s, 'dec:1')",
            ("bre:empty", PROJECT, TARGET, T0, TRACE),
        )
    rows = seeded.execute("SELECT count(*) FROM belief_revision_events").fetchone()
    assert rows[0] == 0


def test_an_event_and_all_its_references_become_visible_together(seeded):
    store = SqlBeliefEventStore(seeded)
    store.append(
        forged_authorization(
            event(triggering_attestation_ids=("att:1",), triggering_relation_ids=("rel:1",))
        )
    )
    loaded = store.get("bre:1")
    assert loaded is not None
    assert loaded.triggering_attestation_ids == ("att:1",)
    assert loaded.triggering_relation_ids == ("rel:1",)
    assert loaded.from_state is BeliefState.ACTIVE
    assert loaded.to_state is BeliefState.SUPPORTED
    assert loaded.policy_id == "pol:hypothesis-default"


# --------------------------------------------------------------------------------------------
# Reading the log back.
# --------------------------------------------------------------------------------------------


def test_history_is_ordered_and_scoped_to_its_target(seeded):
    """Total order, so the projection a replay produces is reproducible.

    Written out of order and with a second target present, because insertion order and "this
    target's history" are exactly what a naive implementation conflates.
    """
    seeded.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state)"
        " VALUES ('pol:challenge', '1.0.0', 'ACTIVE', 'CHALLENGED')"
    )
    store = SqlBeliefEventStore(seeded)
    _forged_decision(seeded, "dec:challenge", policy_id="pol:challenge", to_state="CHALLENGED")
    store.append(
        forged_authorization(
            event(
                event_id="bre:2",
                from_state=BeliefState.ACTIVE,
                to_state=BeliefState.CHALLENGED,
                policy_id="pol:challenge",
                authorization_decision_id="dec:challenge",
                occurred_at=T0 + dt.timedelta(minutes=2),
            )
        )
    )
    seeded.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state)"
        " VALUES ('pol:activate', '1.0.0', 'ADMITTED', 'ACTIVE')"
    )
    _forged_decision(
        seeded,
        "dec:activate",
        policy_id="pol:activate",
        from_state="ADMITTED",
        to_state="ACTIVE",
    )
    store.append(
        forged_authorization(
            event(
                event_id="bre:1",
                from_state=BeliefState.ADMITTED,
                to_state=BeliefState.ACTIVE,
                policy_id="pol:activate",
                authorization_decision_id="dec:activate",
            )
        )
    )
    _forged_decision(
        seeded,
        "dec:other",
        subject_id="hyp:something-else",
    )
    store.append(
        forged_authorization(
            event(
                event_id="bre:other",
                target_id="hyp:something-else",
                authorization_decision_id="dec:other",
            )
        )
    )

    assert [e.event_id for e in store.history(PROJECT, TARGET)] == ["bre:1", "bre:2"]
    assert [e.event_id for e in store.history(PROJECT, "hyp:something-else")] == ["bre:other"]


def test_a_project_history_is_expressible_at_all(seeded):
    """The property `v3.3-a11` added. Before it, a replay could only be installation-wide."""
    store = SqlBeliefEventStore(seeded)
    store.append(forged_authorization(event()))
    assert [e.event_id for e in store.project_history(PROJECT)] == ["bre:1"]
    assert store.project_history("prj:other") == ()


def test_the_store_requires_a_durable_connection():
    """An event written inside a transaction the caller rolls back is a revision that happened
    and left no record -- which is the failure EPI-003 exists to remove."""
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), connect_timeout=5
    )
    try:
        with pytest.raises(NonDurableClaimStoreError, match="autocommit=True"):
            SqlBeliefEventStore(connection)
    finally:
        connection.rollback()
        connection.close()


# --------------------------------------------------------------------------------------------
# The in-memory store enforces the same contract.
# --------------------------------------------------------------------------------------------


def test_the_in_memory_store_also_refuses_unresolvable_triggers():
    """Parity. A fake that accepts what the database rejects makes a green suite meaningless."""
    store = InMemoryBeliefEventStore(known_relation_ids={"rel:1"})
    store.append(forged_authorization(event()))
    with pytest.raises(BeliefEventError, match="do not resolve"):
        store.append(
            forged_authorization(event(event_id="bre:2", triggering_relation_ids=("rel:nowhere",)))
        )


def test_the_in_memory_store_also_refuses_a_reused_event_id():
    store = InMemoryBeliefEventStore(known_relation_ids={"rel:1"})
    store.append(forged_authorization(event()))
    with pytest.raises(BeliefEventError, match="already recorded"):
        store.append(forged_authorization(event(to_state=BeliefState.CONTRADICTED)))


# --------------------------------------------------------------------------------------------
# P7 audit governance gaps, closed in the database by migration 005c.
#
# The Python gates refuse all three already. The audit's point is that a Python gate binds only
# callers who go through it, and a support script, a migration or a future service writes SQL.
# --------------------------------------------------------------------------------------------


def test_an_event_must_record_the_transition_its_policy_governs(seeded):
    """Gap 1, the part that *is* closable without new spec semantics.

    005b made the event cite a registered policy; it did not check that the policy governs the
    transition the event records. So `pol:hypothesis-default@1.0.0` (ACTIVE -> SUPPORTED) could
    back an event recording ADMITTED -> ACTIVE, and nothing would object.

    The consistent forgery -- an event that records exactly what its policy governs, for which no
    ALLOW was ever computed -- is still possible and is SPEC-ISSUE-011 / R-13.
    """
    seeded.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state)"
        " VALUES ('pol:activate', '1.0.0', 'ADMITTED', 'ACTIVE')"
    )
    _forged_decision(
        seeded,
        "dec:activate",
        policy_id="pol:activate",
        from_state="ADMITTED",
        to_state="ACTIVE",
    )
    with pytest.raises(psycopg.errors.RaiseException, match="never authorised by it"):
        _raw(seeded, from_state="ADMITTED", to_state="ACTIVE")


def test_a_transition_policy_cannot_back_a_genesis_event_in_the_database(seeded):
    """Gap 1, the admission half. §8's admission gate is a separate path, enforced in SQL.

    Without this, an event that had simply dropped its predecessor would be indistinguishable from
    a legitimate admission -- which would make the one un-gated write into a general bypass.
    """
    with pytest.raises(psycopg.errors.RaiseException, match="is a transition policy"):
        _raw(seeded, from_state=None, to_state="SUPPORTED")


def test_an_admission_policy_cannot_back_a_transition_in_the_database(seeded):
    """And the other direction, or admission becomes a gate with no predecessor check."""
    seeded.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state,"
        " is_admission) VALUES ('pol:admission', '1.0.0', 'DRAFT', 'ACTIVE', TRUE)"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="is an admission policy"):
        _raw(seeded, policy_id="pol:admission", from_state="ACTIVE", to_state="SUPPORTED")


def test_an_admission_event_is_accepted_through_its_own_policy(seeded):
    """The admission path has to be usable, or a hypothesis could never get a first state."""
    seeded.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state,"
        " is_admission) VALUES ('pol:admission', '1.0.0', 'DRAFT', 'ACTIVE', TRUE)"
    )
    SqlBeliefEventStore(seeded).append(
        forged_authorization(
            event(
                event_id="bre:0",
                from_state=None,
                to_state=BeliefState.ACTIVE,
                policy_id="pol:admission",
            )
        )
    )
    row = seeded.execute(
        "SELECT from_state, to_state FROM belief_revision_events WHERE event_id = 'bre:0'"
    ).fetchone()
    assert row == (None, "ACTIVE")


def test_the_database_refuses_a_cross_project_attestation_reference(seeded):
    """Gap 3. Not a trigger -- the project is carried into the join table and constrained from both
    sides, so the row cannot be formed at all.

    `att:1` belongs to `prj:test`, and the event below belongs to `prj:test` too. The reference is
    unwritable whichever project it claims: claim another project and the event-side foreign key
    fails, and a reference claiming `prj:test` for an attestation in another project fails on the
    attestation side. Both directions are exercised.
    """
    SqlBeliefEventStore(seeded).append(forged_authorization(event(event_id="bre:mine")))

    # The event is in prj:test, so a reference claiming prj:other cannot match the event side.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        seeded.execute(
            "INSERT INTO belief_revision_event_attestations"
            " (event_id, attestation_id, project_id) VALUES ('bre:mine', 'att:1', 'prj:other')"
        )

    # And an attestation from another project cannot be cited under this event's project.
    seeded.execute("INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other')")
    seeded.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance)"
        " SELECT 'att:foreign', claim_id, epistemic_type, source_artifact_id, locator, conditions,"
        " conditions_schema_version, 'prj:other', extractor_version, extraction_provenance"
        " FROM attestations WHERE attestation_id = 'att:1'"
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        seeded.execute(
            "INSERT INTO belief_revision_event_attestations"
            " (event_id, attestation_id, project_id) VALUES ('bre:mine', 'att:foreign', 'prj:test')"
        )


def test_the_database_refuses_a_cross_project_relation_reference(seeded):
    """The same for relations -- one foreign relation is as bad as one foreign attestation.

    The event already cites `rel:1`, so a second reference to it would collide on the primary key
    before reaching the project constraint. A *different* relation, belonging to another project,
    is the case that matters anyway.
    """
    SqlBeliefEventStore(seeded).append(forged_authorization(event(event_id="bre:mine")))
    seeded.execute("INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other')")
    seeded.execute(
        "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
        " relation_type, project_id, actor_id)"
        " VALUES ('rel:foreign', 'att:1', 'clm:1', 'SUPPORTS', 'prj:other', 'act:test')"
    )
    for claimed in ("prj:other", "prj:test"):
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            seeded.execute(
                "INSERT INTO belief_revision_event_relations (event_id, relation_id, project_id)"
                " VALUES ('bre:mine', 'rel:foreign', %s)",
                (claimed,),
            )


def test_raw_sql_cannot_create_an_orphan_event(seeded):
    """Gap 3's second half. An event citing no evidence survives every §6.18 rollback.

    Enforced by a DEFERRED constraint trigger, which is what makes it work at all: under the
    autocommit connections these stores require, a bare INSERT is its own transaction and commits
    with zero references, while `belief_revision_event_append` writes the event and its references
    in one statement. A non-deferred trigger would refuse both, because the event row necessarily
    exists before its references do.
    """
    # A *fully authorised* orphan, so the only thing wrong with it is the missing evidence. An
    # unauthorised one would now be refused earlier and this test would pass for the wrong reason.
    with pytest.raises(psycopg.errors.RaiseException, match="cites no triggering"):
        seeded.execute(
            "INSERT INTO belief_revision_events (event_id, project_id, target_type, target_id,"
            " from_state, to_state, policy_id, policy_version, authorization_decision_id,"
            " occurred_at, trace_id)"
            " VALUES ('bre:orphan', %s, 'HYPOTHESIS', %s, 'ACTIVE', 'SUPPORTED',"
            " 'pol:hypothesis-default', '1.0.0', 'dec:1', %s, %s)",
            (PROJECT, TARGET, T0, TRACE),
        )
    rows = seeded.execute(
        "SELECT count(*) FROM belief_revision_events WHERE event_id = 'bre:orphan'"
    ).fetchone()
    assert rows[0] == 0, "the orphan must not have been committed"


def test_the_append_function_still_works_under_the_deferred_check(seeded):
    """The constraint has to be satisfiable by the supported path, or nothing could be written."""
    SqlBeliefEventStore(seeded).append(forged_authorization(event()))
    assert SqlBeliefEventStore(seeded).get("bre:1") is not None


@pytest.mark.parametrize(
    ("kind", "name", "guards"),
    [
        (
            "trigger",
            "belief_revision_events_match_their_policy",
            "an event cannot record a transition its cited policy does not govern",
        ),
        (
            "trigger",
            "belief_revision_events_cite_evidence",
            "raw SQL cannot leave an event with no triggering evidence",
        ),
        (
            "constraint",
            "belief_revision_event_attestations_attestation_in_project",
            "an event cannot cite an attestation belonging to another project",
        ),
        (
            "constraint",
            "belief_revision_event_relations_relation_in_project",
            "an event cannot cite a relation belonging to another project",
        ),
    ],
)
def test_the_governance_objects_are_present_in_the_database(seeded, kind, name, guards):
    """Name each `005c` object so deleting one fails here, rather than only by inference.

    Every guard below also has a behavioural test that exercises it, and those are the tests that
    matter. This one exists for attribution: a behavioural test going red tells you *something*
    broke, while this tells you which object is missing. Proving they are load-bearing was done
    additively instead of by dropping them -- on a schema built up to `005b`, the three writes the
    audit reported are accepted; with `005c` applied, each is refused.
    """
    catalog = (
        "SELECT 1 FROM pg_trigger WHERE tgname = %s AND NOT tgisinternal"
        if kind == "trigger"
        else "SELECT 1 FROM pg_constraint WHERE conname = %s"
    )
    assert seeded.execute(catalog, (name,)).fetchone() is not None, (
        f"{kind} {name} is missing, so nothing enforces that {guards}"
    )


# --------------------------------------------------------------------------------------------
# `v3.3-a12` / SPEC-ISSUE-011. The authorization is enforced by the database, not only by the
# gate. Every case below writes raw SQL, because that is the caller the gate cannot reach: a
# support script, a migration, a future service. "Only a legal ALLOW authorises" has to survive
# all of them or it is a Python convention wearing a schema's clothes.
# --------------------------------------------------------------------------------------------


def _forged_decision(
    db,  # type: ignore[no-untyped-def]
    decision_id: str = "dec:forged",
    **overrides: object,
) -> str:
    """Write a decision row straight into the table, bypassing `authorize_transition`.

    The snapshot is arbitrary text with a *correct* hash, so the row satisfies the hash CHECK and
    the refusal under test has to come from somewhere else. A forgery that failed the hash check
    would prove only that the hash check works, which is a different test (below).
    """
    snapshot = f'{{"forged":"{decision_id}"}}'
    values: dict[str, object] = {
        "decision_id": decision_id,
        "project_id": PROJECT,
        "subject_id": TARGET,
        "decision_type": "BELIEF_TRANSITION",
        "result": "ALLOW",
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "from_state": "ACTIVE",
        "to_state": "SUPPORTED",
        "decision_input_snapshot": snapshot,
        "input_hash": "sha256:" + hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        "evaluated_decision": '{"outcome":"ALLOW"}',
        "created_at": T0,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({k})s" for k in values)
    db.execute(
        f"INSERT INTO belief_transition_decisions ({columns}) VALUES ({placeholders})", values
    )
    return str(values["decision_id"])


def test_a_non_genesis_event_with_no_authorization_cannot_exist(seeded):
    """The headline case the maintainer named: everything legal except the ALLOW.

    Legal policy, legal transition, legal evidence, correct project -- and no authorization. Before
    `v3.3-a12` this row was writable and indistinguishable from an evaluated transition. The
    CHECK refuses it, so the absence is not merely unchecked, it is unrepresentable.
    """
    with pytest.raises(psycopg.errors.RaiseException, match="no authorization_decision_id"):
        _raw(seeded, "bre:unauthorised", authorization_decision_id=None)

    assert (
        seeded.execute(
            "SELECT count(*) FROM belief_revision_events WHERE event_id = 'bre:unauthorised'"
        ).fetchone()[0]
        == 0
    )


def test_an_event_citing_an_authorization_that_does_not_exist_is_refused(seeded):
    """Naming a decision is not the same as there being one."""
    with pytest.raises(psycopg.errors.RaiseException, match="does not exist"):
        _raw(seeded, "bre:dangling", authorization_decision_id="dec:nonexistent")


@pytest.mark.parametrize("result", ["DENY", "NEED_MORE_EVIDENCE", "NEED_HUMAN_REVIEW"])
def test_a_forged_non_allow_authorization_does_not_authorise(seeded, result):
    """A stored Decision that refused the transition cannot be used to record it.

    NEED_HUMAN_REVIEW is the one worth naming: it reads as progress, so a caller treating
    "not DENY" as permission would promote exactly the beliefs a human was meant to see.
    """
    decision_id = _forged_decision(seeded, f"dec:{result.lower()}", result=result)
    with pytest.raises(psycopg.errors.RaiseException, match="Only ALLOW authorises"):
        _raw(seeded, "bre:forged", authorization_decision_id=decision_id)


def test_a_decision_whose_hash_does_not_bind_its_snapshot_cannot_be_stored(seeded):
    """The database recomputes the hash rather than trusting it.

    This is why the snapshot column is TEXT and not jsonb: jsonb would normalise the bytes, and
    the check would have to accept whatever hash the writer supplied.
    """
    with pytest.raises(psycopg.errors.CheckViolation, match="input_hash_binds_the_snapshot"):
        _forged_decision(seeded, "dec:badhash", input_hash="sha256:" + "0" * 64)


def test_an_authorization_from_another_project_cannot_be_cited(seeded):
    """Composite foreign key, so the cross-project reference is unrepresentable.

    Refused from both directions in one test: the decision genuinely exists, and it is genuinely
    an ALLOW for this subject and this transition. Only the project differs.
    """
    seeded.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:other', 'other')"
        " ON CONFLICT DO NOTHING"
    )
    _forged_decision(seeded, "dec:elsewhere", project_id="prj:other")

    with pytest.raises(
        (psycopg.errors.RaiseException, psycopg.errors.ForeignKeyViolation),
        match=r"does not transfer|violates foreign key",
    ):
        _raw(seeded, "bre:crossproject", authorization_decision_id="dec:elsewhere")


def test_an_authorization_for_another_subject_cannot_be_cited(seeded):
    """An ALLOW is for one hypothesis; the sibling reuse is the cheapest bypass there is."""
    _forged_decision(seeded, "dec:sibling", subject_id="hyp:something-else")
    with pytest.raises(psycopg.errors.RaiseException, match="does not transfer"):
        _raw(seeded, "bre:sibling", authorization_decision_id="dec:sibling")


def test_an_authorization_computed_under_another_policy_cannot_be_cited(seeded):
    """§8.2.1's determinism holds within one policy version and says nothing across two."""
    seeded.execute(
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state)"
        " VALUES ('pol:other', '1.0.0', 'ACTIVE', 'SUPPORTED')"
    )
    _forged_decision(seeded, "dec:otherpolicy", policy_id="pol:other")
    with pytest.raises(psycopg.errors.RaiseException, match="does not carry over"):
        _raw(seeded, "bre:otherpolicy", authorization_decision_id="dec:otherpolicy")


def test_an_authorization_for_another_transition_cannot_be_cited(seeded):
    """An ALLOW for ACTIVE -> SUPPORTED reused to record ACTIVE -> CONTRADICTED."""
    # Same policy on both sides, so the policy check cannot fire and the state check is what is
    # actually under test. The decision is internally wrong -- it names a policy governing
    # ACTIVE -> SUPPORTED while claiming to cover ACTIVE -> CHALLENGED -- which is precisely the
    # shape of a hand-written authorization.
    _forged_decision(seeded, "dec:otherstate", to_state="CHALLENGED")
    with pytest.raises(psycopg.errors.RaiseException, match=r"covers ACTIVE -> CHALLENGED"):
        _raw(seeded, "bre:otherstate", authorization_decision_id="dec:otherstate")


def test_a_genesis_event_cannot_carry_a_transition_authorization(seeded):
    """Admission is a separate gate (§8); letting it borrow transition authority reopens P7's gap.

    Without this, `authorization_decision_id` would be optional in practice -- write a genesis
    event with one and the exemption becomes a general bypass again, which is exactly the shape of
    the finding 005c was written to close.
    """
    seeded.execute(
        "INSERT INTO transition_policies"
        " (policy_id, version, from_state, candidate_to_state, is_admission)"
        " VALUES ('pol:genesis', '1.0.0', 'DRAFT', 'ACTIVE', TRUE)"
    )
    _forged_decision(seeded, "dec:forgenesis")
    with pytest.raises(psycopg.errors.CheckViolation, match="genesis_has_no_authorization"):
        _raw(
            seeded,
            "bre:genesisauth",
            from_state=None,
            to_state="ACTIVE",
            policy_id="pol:genesis",
            authorization_decision_id="dec:forgenesis",
        )


def test_a_stored_authorization_cannot_be_edited_or_removed(seeded):
    """Append-only, for the same reason the events are.

    An authorization that can be rewritten afterwards is not evidence that anything was
    authorised -- and the attack it enables is quieter than editing the event, because nobody
    reads the decision table expecting it to change.
    """
    _forged_decision(seeded, "dec:immutable")

    for statement in (
        "UPDATE belief_transition_decisions SET result = 'DENY' WHERE decision_id = 'dec:immutable'",
        "DELETE FROM belief_transition_decisions WHERE decision_id = 'dec:immutable'",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            seeded.execute(statement)

    assert (
        seeded.execute(
            "SELECT result FROM belief_transition_decisions WHERE decision_id = 'dec:immutable'"
        ).fetchone()[0]
        == "ALLOW"
    )


def test_a_decision_must_name_a_registered_policy_version(seeded):
    """Same reason `005b` made the event's policy a foreign key: an unregistered policy cannot
    be re-run, and an authorization that cannot be re-run is the thing `v3.3-a12` forbids."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="policy_fkey"):
        _forged_decision(seeded, "dec:ghostpolicy", policy_version="9.9.9")


def test_a_decision_that_revises_nothing_is_refused(seeded):
    """A transition from a state to itself is not a transition (same rule as §17.13's events)."""
    with pytest.raises(psycopg.errors.CheckViolation, match="change_state"):
        _forged_decision(seeded, "dec:noop", from_state="SUPPORTED", to_state="SUPPORTED")


def test_only_belief_transition_decisions_live_in_this_table(seeded):
    """§17.14.1 reserves `Decision` for other decision types; they must not land here silently."""
    with pytest.raises(psycopg.errors.CheckViolation, match="decision_type"):
        _forged_decision(seeded, "dec:othertype", decision_type="BUDGET_APPROVAL")


def test_half_an_authority_identity_is_refused_by_the_schema_too(seeded):
    """Asserted in the model and here, because a support script writes SQL."""
    with pytest.raises(psycopg.errors.CheckViolation, match="authority_identity_is_whole"):
        _forged_decision(seeded, "dec:halfauth", authority_policy_id="auth:toy")


def test_the_supported_path_still_writes_an_authorized_event(seeded):
    """The battery above must not have made the legal path impossible.

    Written through `authorize_transition` and the two real stores, so this is the end-to-end
    shape: evaluate, record the authorization, append the event that cites it.
    """
    decision = _real_authorization(seeded, decision_id="dec:supported")
    SqlBeliefEventStore(seeded).append(
        forged_authorization(event(authorization_decision_id=decision.decision_id))
    )

    loaded = SqlBeliefEventStore(seeded).get("bre:1")
    assert loaded is not None
    assert loaded.authorization_decision_id == decision.decision_id

    stored = SqlBeliefTransitionDecisionStore(seeded).get(decision.decision_id)
    assert stored is not None
    assert stored.result is TransitionOutcome.ALLOW
    assert stored.input_hash == stored.decision_input_snapshot.input_hash()


def test_a_stored_authorization_still_re_derives_after_a_round_trip(seeded):
    """The point of storing the inputs: they survive the database and still reproduce.

    A snapshot that round-tripped into something that no longer evaluates the same way would make
    the whole record ceremonial, and canonical serialization is what this is here to check.
    """
    from tests.contract.test_transition_policy import policy as toy_policy

    _real_authorization(seeded, decision_id="dec:roundtrip")
    reloaded = SqlBeliefTransitionDecisionStore(seeded).get("dec:roundtrip")
    assert reloaded is not None

    replayed = rederive_decision(authorization=reloaded, policy=toy_policy())
    assert replayed == reloaded.evaluated
