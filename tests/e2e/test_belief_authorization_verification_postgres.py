"""EPI-005: a stored event is not authorized until its Decision re-derives (§17.14.1, `v3.3-a12`).

THE ONE FORGERY THE DATABASE CANNOT CATCH, AND WHY IT IS NOT THE DATABASE'S FAULT.

`005d` refuses an event whose authorization is absent, is not an ALLOW, belongs to another project
or subject, was computed under another policy version, covers another transition, or whose
`input_hash` does not bind its snapshot. What it cannot refuse is a Decision that is *correct in
every one of those respects* and whose snapshot, when actually evaluated, returns DENY or a NEED_*
outcome. Deciding that requires running `TransitionPolicy.evaluate`, and PostgreSQL cannot -- the
only way it could would be a second copy of the evaluator living in SQL, which would make §8.2.1
stop being the single source of semantic truth and start being one of two that drift.

So §17.14.1 places the obligation on the reader:

    If it does not [re-derive], or if the inputs cannot be reconstructed, the authorization MUST
    be treated as absent -- the event MUST NOT be created and a stored event MUST NOT be accepted
    as authorized.

P8 implemented the first half and not the second: `record_transition` re-derived before minting,
while `replay` took a bare `BeliefRevisionEvent`. This module is the test that would have caught
that, written the way the audit specified -- forge through raw SQL, let the database accept it,
then load through the real stores and run the real projector.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.belief import (
    UnverifiedBeliefRevision,
    VerificationFailure,
    authorize_transition,
    replay,
    verified_history,
    verify_stored_revision,
)
from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.models import (
    BeliefState,
    HypothesisView,
    IndependenceSummary,
    RelationJudgment,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)
from lab_brain.core.models.decision import DecisionInputSnapshot
from lab_brain.core.repositories import SqlBeliefEventStore, SqlTransitionPolicyStore
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from tests.conftest_fixtures import make_artifact
from tests.postgres_fixtures import admit_hypothesis_identity

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-005"),
    pytest.mark.spec_test("T-EPI-005"),
]

T0 = dt.datetime(2026, 9, 16, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"  # the project the shared `db` fixture seeds
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:verify-1"

GENESIS = TransitionPolicy(
    policy_id="pol:admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)
#: Requires two independent attestations. The forged snapshot below supplies zero, which is what
#: makes its real outcome NEED_MORE_EVIDENCE while it claims ALLOW.
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    min_independent_attestations=2,
)


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    # M3 / R-12 (`011j`): a belief event names a hypothesis admitted through §8's gate in its own
    # project, so the identity this fixture always meant is established first.
    admit_hypothesis_identity(db, HYP)
    artifact = make_artifact(b"authorization verification fixture")
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
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0', %s::jsonb, '1.0.0')",
        ('{"type": "object", "properties": {}}',),
    )
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, epistemic_type, source_artifact_id,"
        " locator, conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance) VALUES ('att:1', 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb,"
        " 'core/sch_test@1.0.0', %s, '1.0.0', %s::jsonb)",
        (
            artifact.artifact_id,
            PROJECT,
            '{"extractor_id": "ext:t", "extractor_version": "1.0.0"}',
        ),
    )
    db.execute(
        "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
        " relation_type, project_id, actor_id)"
        " VALUES ('rel:1', 'att:1', 'clm:1', 'SUPPORTS', %s, 'act:test')",
        (PROJECT,),
    )
    policies = SqlTransitionPolicyStore(db)
    policies.register(GENESIS)
    policies.register(PROMOTE)
    return db


def _supporting() -> RelationJudgment:
    return RelationJudgment(
        relation_id="rel:1",
        from_entity_id="att:1",
        to_entity_id=HYP,
        relation_type=RelationType.SUPPORTS,
        project_id=PROJECT,
        supporting_attestation_ids=("att:1",),
    )


def _stores(connection):  # type: ignore[no-untyped-def]
    return {
        "decisions": SqlBeliefTransitionDecisionStore(connection),
        "policies": SqlTransitionPolicyStore(connection),
    }


def _forge_semantically(connection, decision_id: str = "dec:forged") -> str:  # type: ignore[no-untyped-def]
    """Write a Decision that is format-perfect and semantically false.

    Canonical six-input snapshot, correct `input_hash`, correct project/subject/policy/from→to,
    `result` and `evaluated_decision` both recording ALLOW -- and the snapshot supplies zero
    independent attestations against a policy that requires two, so evaluating it really returns
    NEED_MORE_EVIDENCE. Everything `005d` can check is satisfied.
    """
    snapshot = DecisionInputSnapshot(
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        admitted_relations=(_supporting(),),
        independence_summary=IndependenceSummary(independent_count=0),
        candidate_to_state=BeliefState.SUPPORTED,
    )
    real = PROMOTE.evaluate(
        snapshot.hypothesis,
        snapshot.admitted_relations,
        None,
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )
    assert real.outcome is not TransitionOutcome.ALLOW, (
        "the forgery must be a forgery: these inputs have to really fail"
    )

    claimed = real.model_copy(
        update={
            "outcome": TransitionOutcome.ALLOW,
            "reason_code": TransitionReason.POLICY_SATISFIED,
        }
    )
    connection.execute(
        "INSERT INTO belief_transition_decisions (decision_id, project_id, subject_id, result,"
        " policy_id, policy_version, from_state, to_state, decision_input_snapshot, input_hash,"
        " evaluated_decision, created_at)"
        " VALUES (%s, %s, %s, 'ALLOW', %s, %s, 'ACTIVE', 'SUPPORTED', %s, %s, %s, %s)",
        (
            decision_id,
            PROJECT,
            HYP,
            PROMOTE.policy_id,
            PROMOTE.version,
            snapshot.canonical_bytes_text(),
            snapshot.input_hash(),
            canonicalize(claimed.model_dump(mode="json")),
            T0,
        ),
    )
    return decision_id


def _append_event(connection, decision_id: str, event_id: str = "bre:forged") -> None:  # type: ignore[no-untyped-def]
    """Write the event through the supported append function, citing the forged authorization."""
    connection.execute(
        "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, 'ACTIVE', 'SUPPORTED',"
        " %s, %s, %s, %s, NULL, NULL, NULL, %s, %s, %s)",
        (
            event_id,
            PROJECT,
            HYP,
            ["att:1"],
            [],
            PROMOTE.policy_id,
            PROMOTE.version,
            T0,
            TRACE,
            decision_id,
        ),
    )


# --------------------------------------------------------------------------------------------
# The load-bearing case.
# --------------------------------------------------------------------------------------------


def test_the_database_accepts_the_semantic_forgery_and_that_is_expected(world):
    """Stated as its own assertion rather than assumed.

    If `005d` ever started refusing this, the test below would pass for a reason that has nothing
    to do with the read gate, and the gap would reopen silently the next time the schema changed.
    The database is *supposed* to accept this row -- it cannot run the policy.
    """
    decision_id = _forge_semantically(world)
    _append_event(world, decision_id)

    stored = SqlBeliefEventStore(world).get("bre:forged")
    assert stored is not None, "the forgery must really be in the table"
    assert stored.authorization_decision_id == decision_id


def test_a_semantically_forged_authorization_fails_closed_on_the_read_side(world):
    """The P0 the P8 audit found. Format-perfect, ALLOW-labelled, and it re-derives to non-ALLOW.

    Asserted on `VerificationFailure.NOT_REDERIVABLE` rather than on a message: a gate that failed
    closed for a different reason -- a missing policy, say -- would look identical from the
    outside and would not be this guard working.
    """
    decision_id = _forge_semantically(world)
    _append_event(world, decision_id)

    stored = SqlBeliefEventStore(world).get("bre:forged")
    assert stored is not None

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verify_stored_revision(event=stored, **_stores(world))
    assert caught.value.reason is VerificationFailure.NOT_REDERIVABLE


def test_the_forged_event_cannot_reach_the_projection(world):
    """The consequence that matters: the belief does not move.

    `verified_history` refuses the whole history rather than filtering the bad revision out. A
    history containing one unverifiable revision is not that history minus the revision -- and
    returning a projection built from the rest would hide that something wrote a belief nobody
    authorised.
    """
    _append_genesis(world)
    decision_id = _forge_semantically(world)
    _append_event(world, decision_id)

    history = SqlBeliefEventStore(world).history(PROJECT, HYP)
    assert [event.event_id for event in history] == ["bre:0", "bre:forged"]

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verified_history(project_id=PROJECT, target_id=HYP, events=history, **_stores(world))
    assert caught.value.reason is VerificationFailure.NOT_REDERIVABLE

    # And the belief is still where admission left it, reached without the forged revision.
    genesis_only = verified_history(
        project_id=PROJECT, target_id=HYP, events=history[:1], **_stores(world)
    )
    projection = replay(PROJECT, HYP, genesis_only)
    assert projection.current_state is BeliefState.ACTIVE
    assert projection.applied == ("bre:0",)
    assert "bre:forged" not in projection.applied


def test_replay_cannot_be_handed_a_stored_event_directly(world):
    """The seam is structural, not advisory.

    `replay` takes `VerifiedBeliefRevision`; handing it the `BeliefRevisionEvent` the store
    returned is the exact mistake P8 shipped, and it now cannot type-check *or* run. Asserted
    because "we changed the signature" is only a guarantee while something checks it.
    """
    _append_genesis(world)
    history = SqlBeliefEventStore(world).history(PROJECT, HYP)

    with pytest.raises(AttributeError):
        replay(PROJECT, HYP, history)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# The positive round trip. The gate has to be passable or belief could never change.
# --------------------------------------------------------------------------------------------


def _append_genesis(connection) -> None:  # type: ignore[no-untyped-def]
    from lab_brain.core.belief import admit_hypothesis

    SqlBeliefEventStore(connection).append(
        admit_hypothesis(
            event_id="bre:0",
            policy=GENESIS,
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=replay(PROJECT, HYP, ()),
            occurred_at=T0 - dt.timedelta(hours=1),
            trace_id=TRACE,
            triggering_relations=(_supporting(),),
        )
    )


def test_an_honest_authorization_survives_the_whole_round_trip(world):
    """authorize_transition -> persist -> reload -> verify -> replay, through the real stores.

    The point of the slice is that this is the *only* thing that survives it.
    """
    _append_genesis(world)

    honest = authorize_transition(
        decision_id="dec:honest",
        policy=PROMOTE,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        admitted_relations=(_supporting(),),
        independence_summary=IndependenceSummary(independent_count=2),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    )
    assert honest.result is TransitionOutcome.ALLOW, honest.evaluated.reason_code
    SqlBeliefTransitionDecisionStore(world).record(honest)
    _append_event(world, "dec:honest", event_id="bre:1")

    history = SqlBeliefEventStore(world).history(PROJECT, HYP)
    revisions = verified_history(
        project_id=PROJECT, target_id=HYP, events=history, **_stores(world)
    )
    assert [r.origin for r in revisions] == ["ADMISSION", "TRANSITION"]

    projection = replay(PROJECT, HYP, revisions)
    assert projection.current_state is BeliefState.SUPPORTED
    assert projection.applied == ("bre:0", "bre:1")
    assert projection.skipped == ()


def test_genesis_verifies_without_an_authorization(world):
    """Admission is §8's separate gate, so a genesis event is verified against a different rule."""
    _append_genesis(world)
    stored = SqlBeliefEventStore(world).get("bre:0")
    assert stored is not None

    verified = verify_stored_revision(event=stored, **_stores(world))
    assert verified.origin == "ADMISSION"
    assert verified.event.authorization_decision_id is None


# --------------------------------------------------------------------------------------------
# One case per fail-closed condition the ruling named.
# --------------------------------------------------------------------------------------------


def test_a_missing_policy_version_fails_closed(world):
    """An authorization whose policy is not registered cannot be re-run, so it authorises nothing.

    Reached by deleting the policy the honest authorization cites, which is the real shape: the
    Decision was legitimate when written and the policy has since gone.
    """
    _append_genesis(world)
    honest = authorize_transition(
        decision_id="dec:honest",
        policy=PROMOTE,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        admitted_relations=(_supporting(),),
        independence_summary=IndependenceSummary(independent_count=2),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    )
    SqlBeliefTransitionDecisionStore(world).record(honest)
    _append_event(world, "dec:honest", event_id="bre:1")
    stored = SqlBeliefEventStore(world).get("bre:1")
    assert stored is not None

    class NoPolicies:
        def get(self, policy_id: str, version: str) -> None:
            return None

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verify_stored_revision(
            event=stored,
            decisions=SqlBeliefTransitionDecisionStore(world),
            policies=NoPolicies(),
        )
    assert caught.value.reason is VerificationFailure.POLICY_NOT_FOUND


def test_an_unresolvable_authority_comparator_fails_closed(world):
    """Named but unavailable. Refused rather than re-derived without it.

    Evaluating without the comparator that was used answers a different question, and the answer
    would read as a confirmation. §17.14.1 also forbids storing the comparison results, so there
    is nothing to fall back on -- by design (§10.5.1).
    """

    class Comparator:
        policy_id = "auth:toy"
        policy_version = "1.0.0"

        def compare(self, a: str, b: str):  # pragma: no cover - identity is what is under test
            raise AssertionError("must not be called")

        def meets(self, required_rule: str, candidate: str) -> bool:
            return True

    _append_genesis(world)
    honest = authorize_transition(
        decision_id="dec:withauth",
        policy=PROMOTE,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        admitted_relations=(_supporting(),),
        authority_policy=Comparator(),
        independence_summary=IndependenceSummary(independent_count=2),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    )
    SqlBeliefTransitionDecisionStore(world).record(honest)
    _append_event(world, "dec:withauth", event_id="bre:1")
    stored = SqlBeliefEventStore(world).get("bre:1")
    assert stored is not None

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verify_stored_revision(event=stored, **_stores(world))
    assert caught.value.reason is VerificationFailure.COMPARATOR_UNRESOLVED

    # Supplied, and it verifies -- so the refusal above is about availability, not about the
    # comparator being present at all.
    verified = verify_stored_revision(
        event=stored,
        authority_policies={("auth:toy", "1.0.0"): Comparator()},
        **_stores(world),
    )
    assert verified.origin == "TRANSITION"


def test_a_comparator_identity_mismatch_fails_closed(world):
    """The right key, the wrong comparator, is still the wrong comparator.

    `rederive_decision` compares identity and version against the snapshot, so a resolver that
    returns something under the expected key does not satisfy the check by itself.
    """

    class Recorded:
        policy_id = "auth:toy"
        policy_version = "1.0.0"

        def compare(self, a: str, b: str):  # pragma: no cover
            raise AssertionError("must not be called")

        def meets(self, required_rule: str, candidate: str) -> bool:
            return True

    class Impostor(Recorded):
        policy_id = "auth:other"
        policy_version = "9.9.9"

    _append_genesis(world)
    honest = authorize_transition(
        decision_id="dec:withauth",
        policy=PROMOTE,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        admitted_relations=(_supporting(),),
        authority_policy=Recorded(),
        independence_summary=IndependenceSummary(independent_count=2),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    )
    SqlBeliefTransitionDecisionStore(world).record(honest)
    _append_event(world, "dec:withauth", event_id="bre:1")
    stored = SqlBeliefEventStore(world).get("bre:1")
    assert stored is not None

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verify_stored_revision(
            event=stored,
            authority_policies={("auth:toy", "1.0.0"): Impostor()},
            **_stores(world),
        )
    assert caught.value.reason is VerificationFailure.NOT_REDERIVABLE
