"""A policy version is durable and immutable, and an event must cite a registered one (EPI-005).

`v3.3-a11` put `(policy_id, policy_version)` on the event so a past decision can be re-run. That is
an empty promise unless the policy itself survives unchanged: re-running 1.0.0 requires 1.0.0 to
still be exactly what it was after 2.0.0 superseded it.

So this file checks the two things Python cannot: that the stored version cannot be edited, and that
an event citing a version nobody registered is refused by the schema rather than by a caller who
remembered to look.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import psycopg
import pytest

from lab_brain.core.models import (
    BeliefState,
    ConditionMatchState,
    IndependenceBasis,
    RelationType,
    TransitionPolicy,
)
from lab_brain.core.repositories import SqlTransitionPolicyStore
from tests.conftest_fixtures import make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-005"),
    pytest.mark.spec_test("T-EPI-005"),
]

T0 = dt.datetime(2026, 9, 15, 11, 0, tzinfo=dt.UTC)


def policy(**overrides: object) -> TransitionPolicy:
    defaults: dict[str, object] = {
        "policy_id": "pol:hypothesis-default",
        "version": "1.0.0",
        "from_state": BeliefState.ACTIVE,
        "candidate_to_state": BeliefState.SUPPORTED,
        "required_relation_types": (RelationType.SUPPORTS,),
        "required_condition_match": (ConditionMatchState.EXACT,),
        "min_independent_attestations": 2,
        "independence_basis": IndependenceBasis.WORK,
        "blocking_conflict_policy": ("SIM_TO_REAL_CONFLICT",),
        "effective_from": T0,
    }
    defaults.update(overrides)
    return TransitionPolicy(**defaults)  # type: ignore[arg-type]


def test_a_policy_round_trips_with_every_declared_field(db):
    """Including the arrays and the nullable fields: a policy that reads back different is not the
    policy that decided."""
    store = SqlTransitionPolicyStore(db)
    store.register(policy())
    loaded = store.get("pol:hypothesis-default", "1.0.0")

    assert loaded is not None
    assert loaded.from_state is BeliefState.ACTIVE
    assert loaded.candidate_to_state is BeliefState.SUPPORTED
    assert loaded.required_relation_types == (RelationType.SUPPORTS,)
    assert loaded.required_condition_match == (ConditionMatchState.EXACT,)
    assert loaded.min_independent_attestations == 2
    assert loaded.independence_basis is IndependenceBasis.WORK
    assert loaded.blocking_conflict_policy == ("SIM_TO_REAL_CONFLICT",)
    assert loaded.human_gate is False
    assert loaded.effective_from == T0
    assert loaded.supersedes is None


def test_two_versions_of_one_policy_coexist(db):
    """The property the whole table exists for: superseding does not erase what decided before."""
    store = SqlTransitionPolicyStore(db)
    store.register(policy())
    store.register(policy(version="2.0.0", min_independent_attestations=5, supersedes="1.0.0"))

    assert store.get("pol:hypothesis-default", "1.0.0").min_independent_attestations == 2
    assert store.get("pol:hypothesis-default", "2.0.0").min_independent_attestations == 5


def test_a_registered_version_cannot_be_edited(db):
    """A changed rule is a new version.

    If 1.0.0 could be edited, re-running it to re-derive a past decision would compare today's
    rules against yesterday's evidence and call the difference a bug in the record.
    """
    SqlTransitionPolicyStore(db).register(policy())
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        db.execute(
            "UPDATE transition_policies SET min_independent_attestations = 1"
            " WHERE policy_id = 'pol:hypothesis-default' AND version = '1.0.0'"
        )


def test_a_registered_version_cannot_be_deleted(db):
    SqlTransitionPolicyStore(db).register(policy())
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        db.execute("DELETE FROM transition_policies WHERE policy_id = 'pol:hypothesis-default'")


def test_the_same_version_cannot_be_registered_twice(db):
    store = SqlTransitionPolicyStore(db)
    store.register(policy())
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.register(policy(min_independent_attestations=99))


def test_a_policy_out_of_a_terminal_state_is_rejected(db):
    """The policy table and the event table agree, rather than disagreeing at write time.

    A policy governing EVOLVED -> ACTIVE could authorise an event `belief_revision_events` would
    then refuse, which is a contradiction discovered at the worst moment.
    """
    with pytest.raises(psycopg.errors.CheckViolation, match="terminal_state"):
        db.execute(
            "INSERT INTO transition_policies (policy_id, version, from_state,"
            " candidate_to_state) VALUES ('pol:x', '1.0.0', 'SUPERSEDED', 'ACTIVE')"
        )


def test_a_policy_that_does_not_transition_is_rejected(db):
    with pytest.raises(psycopg.errors.CheckViolation, match="actually_transition"):
        db.execute(
            "INSERT INTO transition_policies (policy_id, version, from_state,"
            " candidate_to_state) VALUES ('pol:x', '1.0.0', 'ACTIVE', 'ACTIVE')"
        )


def test_a_policy_cannot_supersede_itself(db):
    with pytest.raises(psycopg.errors.CheckViolation, match="supersede_themselves"):
        db.execute(
            "INSERT INTO transition_policies (policy_id, version, from_state,"
            " candidate_to_state, supersedes)"
            " VALUES ('pol:x', '1.0.0', 'ACTIVE', 'SUPPORTED', '1.0.0')"
        )


def test_an_unmodelled_independence_basis_is_storable(db):
    """§6.17 requires `evaluate` to return NEED_HUMAN_REVIEW for a basis above WORK.

    That behaviour is only testable if such a policy can exist, so the schema permits it. Refusing
    it here would have made the rule untestable while looking stricter.
    """
    SqlTransitionPolicyStore(db).register(policy(independence_basis=IndependenceBasis.INSTRUMENT))
    loaded = SqlTransitionPolicyStore(db).get("pol:hypothesis-default", "1.0.0")
    assert loaded.independence_basis is IndependenceBasis.INSTRUMENT


def _authorization(db, decision_id: str = "dec:1") -> None:  # type: ignore[no-untyped-def]
    """The authorization `v3.3-a12` requires a non-genesis event to cite.

    Written straight into the table with a correctly bound hash: this module is about the *policy*
    foreign key, so the authorization only has to exist and be legitimate, not be the subject.
    """
    snapshot = '{"fixture":"transition-policies"}'
    db.execute(
        "INSERT INTO belief_transition_decisions (decision_id, project_id, subject_id, result,"
        " policy_id, policy_version, from_state, to_state, decision_input_snapshot, input_hash,"
        " evaluated_decision, created_at)"
        " VALUES (%s, 'prj:test', 'hyp:1', 'ALLOW', 'pol:hypothesis-default', '1.0.0',"
        " 'ACTIVE', 'SUPPORTED', %s, %s, '{\"outcome\":\"ALLOW\"}', %s)",
        (
            decision_id,
            snapshot,
            "sha256:" + hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
            T0,
        ),
    )


def _evidence(db) -> None:  # type: ignore[no-untyped-def]
    """One attestation an event may legitimately cite.

    Needed since `005c`: an event with no trigger references is refused, so a test about the
    *policy* foreign key still has to supply evidence to reach it.
    """
    artifact = make_artifact(b"transition policy fixture")
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
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'x')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0',"
        ' \'{"type": "object", "properties": {}}\'::jsonb, \'1.0.0\')'
    )
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance)"
        " VALUES ('att:1', 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb,"
        " 'core/sch_test@1.0.0', 'prj:test', '1.0.0',"
        ' \'{"extractor_id": "ext:test", "extractor_version": "1.0.0"}\'::jsonb)',
        (artifact.artifact_id,),
    )


def test_an_event_cannot_cite_a_policy_version_nobody_registered(db):
    """Migration 005b's foreign key. "Wrong policy version" stops being a Python-side check.

    Without it, an event could name `9.9.9` and the replay would have nothing to re-run -- which
    is exactly the unreplayability `v3.3-a11` was raised to remove.

    Refused twice over since `005c`, and the governance trigger reaches it first: a BEFORE INSERT
    trigger runs before foreign-key checks, so the message names the missing policy rather than the
    constraint. `belief_revision_events_cite_a_registered_policy` stands behind it -- asserted
    separately below, against the constraint catalogue, so both layers stay proven.
    """
    _evidence(db)
    with pytest.raises(psycopg.errors.RaiseException, match="is not registered"):
        db.execute(
            "SELECT belief_revision_event_append('bre:x', 'prj:test', 'HYPOTHESIS', 'hyp:1',"
            " 'ACTIVE', 'SUPPORTED', ARRAY['att:1'], ARRAY[]::text[], 'pol:nowhere', '9.9.9',"
            " NULL, NULL, NULL, %s, 'trc:1', 'dec:1')",
            (T0,),
        )
    assert (
        db.execute(
            "SELECT count(*) FROM belief_revision_events WHERE event_id = 'bre:x'"
        ).fetchone()[0]
        == 0
    )


def test_the_policy_foreign_key_is_still_in_place_behind_the_trigger(db):
    """The trigger is a message; the foreign key is the guarantee.

    A trigger can be dropped by one statement and a reviewer would see a friendlier error
    disappear, not an invariant. Asserting the constraint exists keeps `005b`'s guarantee visible
    even though `005c`'s trigger now answers first.
    """
    row = db.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conname = 'belief_revision_events_cite_a_registered_policy'"
    ).fetchone()
    assert row is not None, "005b's policy foreign key has been dropped"
    assert "transition_policies" in row[0]


def test_an_event_citing_a_registered_policy_is_accepted(db):
    """The constraint has to be satisfiable, or no event could ever be recorded.

    Written through `belief_revision_event_append` rather than a bare INSERT: since migration
    `005c` an event with no trigger references is refused by a deferred constraint trigger, so a
    raw insert would now fail for that reason and prove nothing about the policy foreign key.
    """
    SqlTransitionPolicyStore(db).register(policy())
    _evidence(db)
    _authorization(db)
    db.execute(
        "SELECT belief_revision_event_append('bre:x', 'prj:test', 'HYPOTHESIS', 'hyp:1',"
        " 'ACTIVE', 'SUPPORTED', ARRAY['att:1'], ARRAY[]::text[], 'pol:hypothesis-default',"
        " '1.0.0', NULL, NULL, NULL, %s, 'trc:1', 'dec:1')",
        (T0,),
    )
    row = db.execute(
        "SELECT policy_version FROM belief_revision_events WHERE event_id = 'bre:x'"
    ).fetchone()
    assert row[0] == "1.0.0"
