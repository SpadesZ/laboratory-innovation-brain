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
import os

import psycopg
import pytest

from lab_brain.core.models import BeliefRevisionEvent, BeliefState, BeliefTargetType
from lab_brain.core.repositories import (
    BeliefEventError,
    InMemoryBeliefEventStore,
    NonDurableClaimStoreError,
    SqlBeliefEventStore,
)
from tests.conftest_fixtures import make_artifact

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
    return db


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
        "occurred_at": T0,
        "trace_id": TRACE,
    }
    defaults.update(overrides)
    return BeliefRevisionEvent(**defaults)  # type: ignore[arg-type]


def _raw(db, event_id: str = "bre:1", **overrides: object) -> None:  # type: ignore[no-untyped-def]
    """Insert straight into the table, bypassing the model and the append function."""
    values: dict[str, object] = {
        "event_id": event_id,
        "project_id": PROJECT,
        "target_type": "HYPOTHESIS",
        "target_id": TARGET,
        "from_state": "ACTIVE",
        "to_state": "SUPPORTED",
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
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
    _raw(seeded)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute(
            "UPDATE belief_revision_events SET to_state = 'CONTRADICTED' WHERE event_id = 'bre:1'"
        )


def test_an_event_cannot_be_deleted(seeded):
    """Deleting the inconvenient events is the cheapest way to make a belief look well-founded."""
    _raw(seeded)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute("DELETE FROM belief_revision_events WHERE event_id = 'bre:1'")


def test_the_trigger_references_cannot_be_changed(seeded):
    """The same rewrite one level down.

    An event whose citations can be edited afterwards still claims it was authorised by evidence it
    no longer names.
    """
    SqlBeliefEventStore(seeded).append(event())
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute("DELETE FROM belief_revision_event_relations WHERE event_id = 'bre:1'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute(
            "UPDATE belief_revision_event_relations SET relation_id = 'rel:1'"
            " WHERE event_id = 'bre:1'"
        )


def test_an_event_id_cannot_be_reused(seeded):
    """One id, one revision. A second event under the same id is a replacement in disguise."""
    _raw(seeded)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _raw(seeded)


# --------------------------------------------------------------------------------------------
# A transition has to be a transition, at the schema level too.
# --------------------------------------------------------------------------------------------


def test_an_event_that_changes_nothing_is_rejected(seeded):
    with pytest.raises(psycopg.errors.CheckViolation, match="actually_change_state"):
        _raw(seeded, from_state="ACTIVE", to_state="ACTIVE")


def test_an_event_out_of_a_terminal_state_is_rejected(seeded):
    for terminal in ("EVOLVED", "SUPERSEDED"):
        with pytest.raises(psycopg.errors.CheckViolation, match="terminal_state"):
            _raw(seeded, f"bre:{terminal}", from_state=terminal, to_state="ACTIVE")


def test_an_unknown_state_is_rejected(seeded):
    """Notably REJECTED, which §8.2.1's prose implies and §8.2's lifecycle does not contain."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _raw(seeded, to_state="REJECTED")


def test_an_unknown_target_type_is_rejected(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        _raw(seeded, target_type="CLAIM")


def test_an_event_requires_a_real_project(seeded):
    """`v3.3-a11`: the project is what makes a scoped replay expressible at all."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _raw(seeded, project_id="prj:nowhere")


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
        store.append(event(triggering_attestation_ids=("att:nowhere",)))

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
            " 'SUPPORTED', ARRAY[]::text[], ARRAY[]::text[], 'pol:p', '1.0.0', NULL, NULL,"
            " NULL, %s, %s)",
            ("bre:empty", PROJECT, TARGET, T0, TRACE),
        )
    rows = seeded.execute("SELECT count(*) FROM belief_revision_events").fetchone()
    assert rows[0] == 0


def test_an_event_and_all_its_references_become_visible_together(seeded):
    store = SqlBeliefEventStore(seeded)
    store.append(event(triggering_attestation_ids=("att:1",), triggering_relation_ids=("rel:1",)))
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
    store = SqlBeliefEventStore(seeded)
    store.append(
        event(
            event_id="bre:2",
            from_state=BeliefState.ACTIVE,
            to_state=BeliefState.CHALLENGED,
            occurred_at=T0 + dt.timedelta(minutes=2),
        )
    )
    store.append(
        event(event_id="bre:1", from_state=BeliefState.ADMITTED, to_state=BeliefState.ACTIVE)
    )
    store.append(event(event_id="bre:other", target_id="hyp:something-else"))

    assert [e.event_id for e in store.history(TARGET)] == ["bre:1", "bre:2"]
    assert [e.event_id for e in store.history("hyp:something-else")] == ["bre:other"]


def test_a_project_history_is_expressible_at_all(seeded):
    """The property `v3.3-a11` added. Before it, a replay could only be installation-wide."""
    store = SqlBeliefEventStore(seeded)
    store.append(event())
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
    store.append(event())
    with pytest.raises(BeliefEventError, match="do not resolve"):
        store.append(event(event_id="bre:2", triggering_relation_ids=("rel:nowhere",)))


def test_the_in_memory_store_also_refuses_a_reused_event_id():
    store = InMemoryBeliefEventStore(known_relation_ids={"rel:1"})
    store.append(event())
    with pytest.raises(BeliefEventError, match="already recorded"):
        store.append(event(to_state=BeliefState.CONTRADICTED))
