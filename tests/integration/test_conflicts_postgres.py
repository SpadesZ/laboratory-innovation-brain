"""EPI-006: the database enforces the conflict contract, not only the model (migration `011a`).

Same rule as the cost ledger, the span table and the belief event log, and this project has now
learned it four times: a model invariant holds for callers who go through the model, and a
migration, a support script or a future service writes SQL. If "a conflict does not stop blocking
without the event that closed it" holds only in `Conflict`, it holds only in Python.

WHAT THE DATABASE DELIBERATELY DOES NOT DO. It does not decide which `conflict_type` values gate
belief -- that is `blocking`, supplied by the domain -- and it does not evaluate
`TransitionPolicy.blocking_conflict_policy`, because §8.2.1 lives in Python and a second copy in
SQL would make semantic truth two definitions that drift (`v3.3-a13`). Every test below is about
what makes those decisions trustworthy rather than about making them here.
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from lab_brain.core.models.conflict import (
    Conflict,
    ConflictResolutionStatus,
    ConflictType,
)
from lab_brain.core.repositories.conflicts import ConflictStoreError, SqlConflictStore
from tests.conftest_fixtures import make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-006"),
    pytest.mark.spec_test("T-EPI-006"),
]

T0 = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
OTHER = "prj:other"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:conflict-1"


@pytest.fixture
def seeded(db):  # type: ignore[no-untyped-def]
    """A second project, and one real belief revision event a closure may legitimately cite.

    The event is real rather than an id: `conflicts.resolution_event_id` is a composite foreign
    key into `belief_revision_events (event_id, project_id)`, which is what makes a cross-project
    closure unrepresentable instead of merely wrong.
    """
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    artifact = make_artifact(b"a conflict fixture")
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
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'rs')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0', %s::jsonb, '1.0.0')",
        ('{"type": "object", "properties": {}}',),
    )
    for project in (PROJECT, OTHER):
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type,"
            " source_artifact_id, locator, conditions, conditions_schema_version, project_id,"
            " extractor_version, extraction_provenance)"
            " VALUES (%s, 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb, 'core/sch_test@1.0.0',"
            " %s, '1.0.0', %s::jsonb)",
            (
                f"att:{project}",
                artifact.artifact_id,
                project,
                '{"extractor_id": "ext:t", "extractor_version": "1.0.0"}',
            ),
        )
        db.execute(
            "INSERT INTO transition_policies (policy_id, version, from_state,"
            " candidate_to_state, is_admission) VALUES (%s, '1.0.0', 'DRAFT', 'ACTIVE', TRUE)"
            " ON CONFLICT DO NOTHING",
            (f"pol:genesis-{project}",),
        )
        # A genesis event, so no §17.14.1 authorization is required -- this fixture is about
        # conflicts, and dragging `v3.3-a12`'s Decision machinery in would make every failure
        # here ambiguous between the two slices.
        db.execute(
            "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, NULL, 'ACTIVE',"
            " %s, ARRAY[]::text[], %s, '1.0.0', NULL, NULL, NULL, %s, %s, NULL)",
            (
                f"bre:{project}",
                project,
                HYP,
                [f"att:{project}"],
                f"pol:genesis-{project}",
                T0,
                TRACE,
            ),
        )
    return db


def conflict(**overrides: object) -> Conflict:
    defaults: dict[str, object] = {
        "conflict_id": "cfl:1",
        "project_id": PROJECT,
        "conflict_type": ConflictType.SIM_TO_REAL_CONFLICT,
        "subject_refs": (HYP,),
        "blocking": True,
        "detected_at": T0,
        "detected_by_actor_or_slot": "act:test",
        "trace_id": TRACE,
    }
    defaults.update(overrides)
    return Conflict(**defaults)  # type: ignore[arg-type]


def _raw(db, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    """Insert straight into the table, bypassing the model.

    Used for the constraint tests, where the row is *expected* to be refused. Going through the
    model would test the model again, which is not what any of these are about.
    """
    values: dict[str, object] = {
        "conflict_id": "cfl:raw",
        "project_id": PROJECT,
        "conflict_type": "SIM_TO_REAL_CONFLICT",
        "resolution_status": "OPEN",
        "blocking": True,
        "subject_refs": [HYP],
        "detected_at": T0,
        "detected_by_actor_or_slot": "act:test",
        "trace_id": TRACE,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({key})s" for key in values)
    db.execute(f"INSERT INTO conflicts ({columns}) VALUES ({placeholders})", values)


# --------------------------------------------------------------------------------------------
# Storability and the supported path.
# --------------------------------------------------------------------------------------------


def test_a_conflict_round_trips_through_the_store(seeded):
    """Read back through the model's validator, so a row it would reject cannot be handed on."""
    store = SqlConflictStore(seeded)
    store.record(conflict(supporting_refs=("att:prj:test",), episode_id="epi:1"))

    loaded = store.get(PROJECT, "cfl:1")
    assert loaded is not None
    assert loaded.conflict_type is ConflictType.SIM_TO_REAL_CONFLICT
    assert loaded.subject_refs == (HYP,)
    assert loaded.blocking is True
    assert loaded.blocks_transitions
    assert loaded.resolution_status is ConflictResolutionStatus.OPEN


def test_closing_a_conflict_records_the_event_and_lifts_the_block(seeded):
    store = SqlConflictStore(seeded)
    store.record(conflict())

    closed = store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id=f"bre:{PROJECT}",
        resolved_at=T0,
    )
    assert closed.resolution_status is ConflictResolutionStatus.RESOLVED
    assert closed.resolution_event_id == f"bre:{PROJECT}"
    assert not closed.blocks_transitions


@pytest.mark.parametrize(
    "status",
    [
        ConflictResolutionStatus.RESOLVED,
        ConflictResolutionStatus.ACCEPTED_AS_OPEN_QUESTION,
        ConflictResolutionStatus.EXPIRED,
    ],
)
def test_every_unblocking_status_closes_through_the_event_path(seeded, status):
    """All three, because the P10 audit found the obligation written for one of them."""
    store = SqlConflictStore(seeded)
    store.record(conflict())

    closed = store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id=f"bre:{PROJECT}",
        resolved_at=T0,
        status=status,
    )
    assert closed.resolution_status is status
    assert not closed.blocks_transitions


# --------------------------------------------------------------------------------------------
# The vocabularies are closed in the schema.
# --------------------------------------------------------------------------------------------


def test_an_unknown_conflict_type_is_refused_by_the_database(seeded):
    """§17.19.3: 衝突不得只以字串或散落旗標表示 -- including via raw SQL."""
    with pytest.raises(psycopg.errors.CheckViolation, match="conflict_type"):
        _raw(seeded, conflict_type="SIM_TO_REAL_CONFLIC")


def test_an_unknown_resolution_status_is_refused_by_the_database(seeded):
    """Closure details supplied on purpose, so the *vocabulary* check is the one that fires.

    Without them the closure constraint refuses the row first -- an unknown status is not one of
    the two unresolved ones, so it reads as a closure with nothing to back it. The row is refused
    either way, but a test that accepted the first refusal would pass with the vocabulary CHECK
    deleted.
    """
    with pytest.raises(psycopg.errors.CheckViolation, match="resolution_status"):
        _raw(
            seeded,
            resolution_status="PROBABLY_FINE",
            resolved_at=T0,
            resolution_event_id=f"bre:{PROJECT}",
        )


def test_a_conflict_with_no_subject_is_refused_by_the_database(seeded):
    """A conflict about nothing cannot appear in any hypothesis's `unresolved_conflicts`."""
    with pytest.raises(psycopg.errors.CheckViolation, match="subject_refs"):
        _raw(seeded, subject_refs=[])


def test_a_conflict_must_name_a_real_project(seeded):
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="project"):
        _raw(seeded, project_id="prj:nowhere")


# --------------------------------------------------------------------------------------------
# Closure. The invariant the audit found applied to one status of three.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["RESOLVED", "ACCEPTED_AS_OPEN_QUESTION", "EXPIRED"])
def test_raw_sql_cannot_write_an_unblocked_conflict_with_no_closure_event(seeded, status):
    """The headline case: change the enum, unblock the belief, record nothing.

    All three statuses stop a conflict blocking, so all three require the event. Before this the
    Python model guarded only RESOLVED, and the database guarded none of them.
    """
    with pytest.raises(psycopg.errors.CheckViolation, match="closure_matches_status"):
        _raw(seeded, conflict_id="cfl:noevent", resolution_status=status)


@pytest.mark.parametrize("status", ["OPEN", "UNDER_REVIEW"])
def test_raw_sql_cannot_write_an_unresolved_conflict_carrying_closure_details(seeded, status):
    """The other direction: a conflict that still blocks must not look half-closed."""
    with pytest.raises(psycopg.errors.CheckViolation, match="closure_matches_status"):
        _raw(
            seeded,
            conflict_id="cfl:halfclosed",
            resolution_status=status,
            resolved_at=T0,
            resolution_event_id=f"bre:{PROJECT}",
        )


def test_a_closure_event_from_another_project_is_unrepresentable(seeded):
    """Composite foreign key, so the cross-project closure cannot be written at all.

    The event genuinely exists -- it is the other project's genesis -- so only the project
    differs, and that is the only thing being tested.
    """
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="resolution_event_in_project"):
        _raw(
            seeded,
            conflict_id="cfl:crossproject",
            resolution_status="RESOLVED",
            resolved_at=T0,
            resolution_event_id=f"bre:{OTHER}",
        )


def test_a_closure_event_that_does_not_exist_is_refused(seeded):
    """Naming an event is not the same as there being one."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _raw(
            seeded,
            conflict_id="cfl:ghostevent",
            resolution_status="RESOLVED",
            resolved_at=T0,
            resolution_event_id="bre:nonexistent",
        )


# --------------------------------------------------------------------------------------------
# The scientific identity is immutable, and nothing is ever deleted.
# --------------------------------------------------------------------------------------------


def test_a_conflict_cannot_be_deleted(seeded):
    """Removing one erases the reason a belief was blocked."""
    SqlConflictStore(seeded).record(conflict())

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute("DELETE FROM conflicts WHERE conflict_id = 'cfl:1'")
    assert (
        seeded.execute("SELECT count(*) FROM conflicts WHERE conflict_id = 'cfl:1'").fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("conflict_type", "'PROVENANCE_CONFLICT'"),
        ("blocking", "FALSE"),
        ("subject_refs", "ARRAY['hyp:something-else']"),
        ("detected_at", "now()"),
        ("detected_by_actor_or_slot", "'act:someone-else'"),
        ("trace_id", "'trc:rewritten'"),
        ("project_id", "'prj:other'"),
    ],
)
def test_raw_update_cannot_rewrite_the_scientific_identity(seeded, column, value):
    """Each of these rewrites what the disagreement *was* rather than resolving it.

    `blocking = FALSE` is the one worth naming: it is the quietest way to unblock a belief, since
    it leaves the conflict OPEN and apparently untouched while the policy stops seeing it.
    """
    SqlConflictStore(seeded).record(conflict())

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        seeded.execute(f"UPDATE conflicts SET {column} = {value} WHERE conflict_id = 'cfl:1'")


def test_raw_update_cannot_close_a_conflict_by_status_alone(seeded):
    """The trigger says it before the CHECK does, in language an operator can act on."""
    SqlConflictStore(seeded).record(conflict())

    # The wording widened with `v3.3-a15`: a closure now needs an event **and its kind**, since
    # a governance closure populates a different column. The obligation is unchanged.
    with pytest.raises(psycopg.errors.RaiseException, match="without a closure event"):
        seeded.execute(
            "UPDATE conflicts SET resolution_status = 'EXPIRED' WHERE conflict_id = 'cfl:1'"
        )
    assert SqlConflictStore(seeded).get(PROJECT, "cfl:1").blocks_transitions  # type: ignore[union-attr]


def test_escalating_to_under_review_is_allowed_and_keeps_the_block(seeded):
    """§8.2.1: the review resolving is what lifts the block, not the review starting."""
    SqlConflictStore(seeded).record(conflict())
    # Status only. `review_id` is a checked composite foreign key since `011b`, so setting it to
    # an id no review has is refused -- which is the constraint working, and why escalation goes
    # through `authority_conflict_escalate` rather than a bare UPDATE. The earlier version of
    # this test set `review_id = 'rvw:1'` and started failing the moment the reference became
    # real.
    seeded.execute(
        "UPDATE conflicts SET resolution_status = 'UNDER_REVIEW' WHERE conflict_id = 'cfl:1'"
    )

    escalated = SqlConflictStore(seeded).get(PROJECT, "cfl:1")
    assert escalated is not None
    assert escalated.resolution_status is ConflictResolutionStatus.UNDER_REVIEW
    assert escalated.blocks_transitions, "a conflict under review has not been resolved"


def test_a_conflict_cannot_be_resolved_twice(seeded):
    """Re-resolving would overwrite the event that justified the first close."""
    store = SqlConflictStore(seeded)
    store.record(conflict())
    store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id=f"bre:{PROJECT}",
        resolved_at=T0,
    )

    with pytest.raises(ConflictStoreError):
        store.resolve(
            project_id=PROJECT,
            conflict_id="cfl:1",
            resolution_event_id=f"bre:{PROJECT}",
            resolved_at=T0,
        )
    assert store.get(PROJECT, "cfl:1").resolution_event_id == f"bre:{PROJECT}"  # type: ignore[union-attr]


def test_raw_update_cannot_reforge_a_closed_conflict(seeded):
    """The same refusal against SQL, since the store is not the only writer."""
    store = SqlConflictStore(seeded)
    store.record(conflict())
    store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id=f"bre:{PROJECT}",
        resolved_at=T0,
    )

    with pytest.raises(psycopg.errors.RaiseException, match="already RESOLVED"):
        seeded.execute(
            "UPDATE conflicts SET resolution_status = 'OPEN', resolved_at = NULL,"
            " resolution_event_id = NULL WHERE conflict_id = 'cfl:1'"
        )


def test_the_close_function_is_project_scoped(seeded):
    """Closing through the wrong project must fail rather than close the wrong record."""
    SqlConflictStore(seeded).record(conflict())

    # `011c` split this message: the lookup now distinguishes "no such conflict in this project"
    # from "already closed", which is more precise and is what a project-scoped miss actually is.
    with pytest.raises(
        psycopg.errors.RaiseException, match=r"does not exist|absent or already closed"
    ):
        seeded.execute(
            "SELECT conflict_close('cfl:1', %s, 'RESOLVED', %s, %s)",
            (OTHER, f"bre:{OTHER}", T0),
        )
    assert SqlConflictStore(seeded).get(PROJECT, "cfl:1").blocks_transitions  # type: ignore[union-attr]


def test_the_close_function_refuses_a_non_closure_status(seeded):
    """Moving a conflict to review is a different operation and must not carry an event."""
    SqlConflictStore(seeded).record(conflict())

    with pytest.raises(psycopg.errors.RaiseException, match="is not a closure"):
        seeded.execute(
            "SELECT conflict_close('cfl:1', %s, 'UNDER_REVIEW', %s, %s)",
            (PROJECT, f"bre:{PROJECT}", T0),
        )


# --------------------------------------------------------------------------------------------
# Project scope on reads. SEC-002 applies to conflicts like every other read.
# --------------------------------------------------------------------------------------------


def test_subject_reads_are_scoped_by_project(seeded):
    """Two projects may legitimately reference the same hypothesis id."""
    store = SqlConflictStore(seeded)
    store.record(conflict(conflict_id="cfl:mine"))
    store.record(conflict(conflict_id="cfl:theirs", project_id=OTHER))

    assert [c.conflict_id for c in store.for_subject(PROJECT, HYP)] == ["cfl:mine"]
    assert [c.conflict_id for c in store.for_subject(OTHER, HYP)] == ["cfl:theirs"]


def test_a_conflict_in_another_project_is_not_readable_by_id(seeded):
    SqlConflictStore(seeded).record(conflict(project_id=OTHER))
    assert SqlConflictStore(seeded).get(PROJECT, "cfl:1") is None


def test_the_unresolved_view_excludes_closed_conflicts(seeded):
    """What a `HypothesisView` is built from -- filtered in SQL, on the same two statuses."""
    store = SqlConflictStore(seeded)
    store.record(conflict(conflict_id="cfl:open"))
    store.record(conflict(conflict_id="cfl:closed"))
    store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:closed",
        resolution_event_id=f"bre:{PROJECT}",
        resolved_at=T0,
    )

    unresolved = store.unresolved_for_subject(PROJECT, HYP)
    assert [c.conflict_id for c in unresolved] == ["cfl:open"]


def test_subject_reads_are_deterministically_ordered(seeded):
    """The result feeds `evaluate`, whose determinism is only as good as its inputs'."""
    store = SqlConflictStore(seeded)
    for index in (3, 1, 2):
        store.record(
            conflict(
                conflict_id=f"cfl:{index}",
                detected_at=T0 + dt.timedelta(minutes=index),
            )
        )

    assert [c.conflict_id for c in store.for_subject(PROJECT, HYP)] == [
        "cfl:1",
        "cfl:2",
        "cfl:3",
    ]


def test_the_store_refuses_a_non_durable_connection(db):  # type: ignore[no-untyped-def]
    """Same contract as every other store: a conflict written inside a transaction the caller
    later rolls back is a block that was recorded and then was not."""
    from lab_brain.core.repositories import NonDurableClaimStoreError

    db.autocommit = False
    try:
        with pytest.raises(NonDurableClaimStoreError):
            SqlConflictStore(db)
    finally:
        db.rollback()
        db.autocommit = True


# --------------------------------------------------------------------------------------------
# §26's T-EPI-006 has a clause nothing in this module proved until M0b closure:
#
#     AUTHORITY_CONFLICT from an INCOMPARABLE comparison creates a Conflict linked to the
#     auto-created ReviewItem
#
# Every test above records its conflicts with `store.record(conflict(...))`. That proves the table
# holds them; it says nothing about a Conflict *arising* from a comparison. The test below records
# no conflict and creates no review -- an INCOMPARABLE comparison does both.
# --------------------------------------------------------------------------------------------


def test_an_incomparable_comparison_creates_a_linked_conflict_and_review(seeded):
    """The automatic half of EPI-006, driven by the episode rather than by the test.

    Nothing here names a conflict_id or a review_id as *input*. The episode is given a hypothesis,
    a policy whose `required_authority_rule` cannot be satisfied and a comparator that answers
    INCOMPARABLE; the typed `AUTHORITY_CONFLICT` and its queued reviewer are the consequence.
    """
    import datetime as dt

    from lab_brain.core.authority import AuthorityPolicyRegistry
    from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
    from lab_brain.core.episode import BeliefEpisode
    from lab_brain.core.models import (
        BeliefState,
        RelationJudgment,
        RelationType,
        TransitionOutcome,
        TransitionPolicy,
        TransitionReason,
    )
    from lab_brain.core.repositories import (
        SqlAttestationStore,
        SqlBeliefEventStore,
        SqlRelationStore,
        SqlTransitionPolicyStore,
    )
    from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
    from lab_brain.core.repositories.reviews import (
        SqlReviewItemStore,
        SqlReviewQueuePolicyStore,
    )
    from lab_brain.core.review_queue import ReviewQueuePolicy
    from tests.toy_authority import ToyAuthorityPolicy

    promote = TransitionPolicy(
        policy_id="pol:promote",
        version="1.0.0",
        from_state=BeliefState.ACTIVE,
        candidate_to_state=BeliefState.SUPPORTED,
        required_relation_types=(RelationType.SUPPORTS,),
        required_authority_rule="TIER_A",
        blocking_conflict_policy=("AUTHORITY_CONFLICT",),
    )
    SqlTransitionPolicyStore(seeded).register(promote)
    SqlReviewQueuePolicyStore(seeded).register(
        ReviewQueuePolicy(
            policy_id="rqp:test",
            version="1.0.0",
            project_id=PROJECT,
            capacity=8,
            default_sla_minutes=24 * 60,
            default_expiry_minutes=72 * 60,
            # `v3.3-a15`: who declared the SLA an automatic expiry would execute.
            declared_by_actor_id="act:test",
            effective_from=T0,
        )
    )
    # SIDEBAND is the class the toy comparator cannot rank against TIER_A -- INCOMPARABLE, not a
    # shortfall, which is the distinction this clause turns on.
    seeded.execute(
        "UPDATE attestations SET authority_class = 'SIDEBAND' WHERE attestation_id = %s",
        (f"att:{PROJECT}",),
    )
    SqlRelationStore(seeded).add(
        RelationJudgment(
            relation_id="rel:1",
            from_entity_id=f"att:{PROJECT}",
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            project_id=PROJECT,
            supporting_attestation_ids=(f"att:{PROJECT}",),
            valid_from=T0,
            created_at=T0,
        )
    )
    SqlBeliefEventStore(seeded).append(
        admit_hypothesis(
            event_id="bre:admit",
            policy=TransitionPolicy(
                policy_id=f"pol:genesis-{PROJECT}",
                version="1.0.0",
                from_state=BeliefState.DRAFT,
                candidate_to_state=BeliefState.ACTIVE,
                is_admission=True,
            ),
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=EpistemicStateProjection(
                project_id=PROJECT, target_id=HYP, current_state=None, last_event_id=None
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(SqlAttestationStore(seeded).get(PROJECT, f"att:{PROJECT}"),),  # type: ignore[arg-type]
        )
    )

    registry = AuthorityPolicyRegistry()
    registry.register(ToyAuthorityPolicy())

    class _Ids:
        def decision_id(self) -> str:
            return "dec:auto"

        def event_id(self) -> str:
            return "bre:auto"

        def conflict_id(self) -> str:
            return "cfl:auto"

        def review_id(self) -> str:
            return "rvw:auto"

    assert seeded.execute("SELECT count(*) FROM conflicts").fetchone()[0] == 0

    result = BeliefEpisode(
        policies=SqlTransitionPolicyStore(seeded),
        decisions=SqlBeliefTransitionDecisionStore(seeded),
        events=SqlBeliefEventStore(seeded),
        relations=SqlRelationStore(seeded),
        authority_classes=SqlAttestationStore(seeded),
        conflicts=SqlConflictStore(seeded),
        reviews=SqlReviewItemStore(seeded),
        ids=_Ids(),
        authority_policies=registry.as_mapping(),
    ).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
        authority_policy_ref=(ToyAuthorityPolicy().policy_id, ToyAuthorityPolicy().policy_version),
    )

    assert result.decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert result.decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE

    created = SqlConflictStore(seeded).get(PROJECT, "cfl:auto")
    assert created is not None, "the Conflict must exist without the test recording one"
    assert created.conflict_type is ConflictType.AUTHORITY_CONFLICT
    assert created.blocking is True
    assert created.subject_refs == (HYP,), "the hypothesis is one hop away (§17.19.3)"
    assert created.resolution_status is ConflictResolutionStatus.UNDER_REVIEW
    assert created.blocks_transitions, "UNDER_REVIEW still blocks; the resolution lifts it"

    # Linked to the auto-created ReviewItem, which is the clause in full.
    linked = SqlReviewItemStore(seeded).get(PROJECT, created.review_id)  # type: ignore[arg-type]
    assert linked is not None
    assert linked.subject_id == "cfl:auto", "§17.19.3: the review's subject is the conflict_id"
    assert linked.is_outstanding

    # And the conflict now reaches the next HypothesisView and keeps the belief where it was.
    assert [
        c.conflict_id for c in SqlConflictStore(seeded).unresolved_for_subject(PROJECT, HYP)
    ] == ["cfl:auto"]
    assert result.projection.current_state is BeliefState.ACTIVE
    assert result.projection.unresolved_conflicts == ("cfl:auto",)
