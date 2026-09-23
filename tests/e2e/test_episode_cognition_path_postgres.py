"""T-SYS-001: the whole scientific state path, driven end to end, with no bypass available.

    §25.3 SYS-001  Core scientific state path MUST be Artifact/SourceWork -> Claim/Observation
                   -> Attestation -> RelationJudgment -> TransitionPolicy -> BeliefRevisionEvent
                   -> EpistemicStateProjection.
    §26   T-SYS-001 | architecture | static/conformance test rejects bypass from cognition
                   directly to EpistemicState update or support arrays on Attestation/Hypothesis.

TWO HALVES, AND ONLY ONE OF THEM WAS EVER TESTED. `tests/unit/test_core_architecture_invariants.py`
has asserted the *static* half since M0a -- no support arrays, no DomainPack import in core, frozen
models -- and said in its own docstring that it could not claim SYS-001 because EpistemicState and
the episode path did not exist. They exist now. This file is the other half: the path is walked for
real, through PostgreSQL, and the bypasses are attempted rather than assumed impossible.

WHAT "BYPASS" MEANS HERE, CONCRETELY. Not a hypothetical. Every one of these is something a
plausible LLM-driven implementation does:

    write the status directly                 refused -- the store takes AuthorizedRevision only
    build the event from a non-ALLOW          refused by record_transition
    return prose and have a caller apply it   there is nothing to apply it *to*
    skip evaluate and call the store          the capability cannot be constructed

THE ORDER OF THE TESTS IS THE ORDER OF THE PATH. Admission, evidence, relation, policy, decision,
event, projection -- then the three non-ALLOW branches, then the bypasses.
"""

from __future__ import annotations

import datetime as dt
import itertools

import pytest

from lab_brain.core.authority import AuthorityPolicyRegistry
from lab_brain.core.belief import (
    BeliefTransitionRefused,
    EpistemicStateProjection,
    UnverifiedBeliefRevision,
    VerificationFailure,
    admit_hypothesis,
)
from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.episode import BeliefEpisode, EpisodeRefused
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
from lab_brain.core.models.attestation import (
    Attestation,
    EpistemicType,
    ExtractionProvenance,
)
from lab_brain.core.models.conflict import ConflictResolutionStatus, ConflictType
from lab_brain.core.models.decision import DecisionInputSnapshot
from lab_brain.core.models.review import ReviewStatus, ReviewSubjectType
from lab_brain.core.repositories import (
    SqlAttestationStore,
    SqlBeliefEventStore,
    SqlRelationStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from tests.conftest_fixtures import make_artifact
from tests.toy_authority import ToyAuthorityPolicy

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("SYS-001"),
    pytest.mark.spec_test("T-SYS-001"),
]

T0 = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:episode"
EPISODE = "epi:1"

GENESIS = TransitionPolicy(
    policy_id="pol:admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)

#: Satisfiable: one SUPPORTS relation and no authority rule.
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    blocking_conflict_policy=("AUTHORITY_CONFLICT",),
)

#: Requires TIER_A. The evidence below carries SIDEBAND, which the toy comparator cannot rank
#: against it -- INCOMPARABLE, not a shortfall, which is the distinction EPI-004 turns on.
PROMOTE_AUTHORITY = PROMOTE.model_copy(
    update={"policy_id": "pol:promote-authority", "required_authority_rule": "TIER_A"}
)

#: Requires two independent attestations. Only used by the forgery below, whose snapshot
#: supplies zero -- which is what makes the claimed ALLOW re-derive to NEED_MORE_EVIDENCE.
PROMOTE_INDEPENDENT = PROMOTE.model_copy(
    update={"policy_id": "pol:promote-independent", "min_independent_attestations": 2}
)

#: Asks for a relation type nothing supplies -> NEED_MORE_EVIDENCE.
CONTRADICT = TransitionPolicy(
    policy_id="pol:contradict",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.CONTRADICTED,
    required_relation_types=(RelationType.CONTRADICTS,),
)

#: Governs a transition nobody is asking for -> DENY (TRANSITION_NOT_GOVERNED).
UNRELATED = TransitionPolicy(
    policy_id="pol:unrelated",
    version="1.0.0",
    from_state=BeliefState.CHALLENGED,
    candidate_to_state=BeliefState.INCONCLUSIVE,
)

AUTHORITY_REF = (ToyAuthorityPolicy().policy_id, ToyAuthorityPolicy().policy_version)


class CountingIds:
    """Predictable ids, because idempotence is unobservable when every run renames its rows."""

    def __init__(self) -> None:
        self._counters: dict[str, itertools.count[int]] = {}

    def _next(self, prefix: str) -> str:
        counter = self._counters.setdefault(prefix, itertools.count(1))
        return f"{prefix}:{next(counter)}"

    def decision_id(self) -> str:
        return self._next("dec")

    def event_id(self) -> str:
        return self._next("bre")

    def conflict_id(self) -> str:
        return self._next("cfl")

    def review_id(self) -> str:
        return self._next("rvw")


def _queue_policy(db, project_id: str, policy_id: str = "rqp:test") -> None:  # type: ignore[no-untyped-def]
    """Register the §14.4 SLA/expiry policy every escalation is priced from since `011e`.

    Not optional and not a convenience: `authority_conflict_escalate` refuses a project with no
    active queue policy, because an item with no deadline is the state §14.4 exists to forbid.
    """
    from lab_brain.core.repositories.reviews import SqlReviewQueuePolicyStore
    from lab_brain.core.review_queue import ReviewQueuePolicy

    SqlReviewQueuePolicyStore(db).register(
        ReviewQueuePolicy(
            policy_id=policy_id,
            version="1.0.0",
            project_id=project_id,
            capacity=16,
            default_sla_minutes=24 * 60,
            default_expiry_minutes=72 * 60,
            reviewer_minutes_per_day=240,
            # `v3.3-a15`: the standing authority an automatic expiry executes. Required,
            # and never inferred from whoever runs the sweep.
            declared_by_actor_id="act:test",
            effective_from=T0,
        )
    )


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """An artifact, a claim, a condition schema and the four policies -- through the real stores."""
    artifact = make_artifact(b"an episode fixture")
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
    _queue_policy(db, PROJECT)
    policies = SqlTransitionPolicyStore(db)
    for policy in (GENESIS, PROMOTE, PROMOTE_AUTHORITY, PROMOTE_INDEPENDENT, CONTRADICT, UNRELATED):
        policies.register(policy)
    db.artifact_id = artifact.artifact_id  # type: ignore[attr-defined]
    return db


def _attestation(world, attestation_id: str, authority_class: str | None) -> Attestation:
    """A persisted §17.2 attestation -- through `SqlAttestationStore`, not raw SQL.

    Going through the store is the point: SYS-001's path starts at the evidence, and a test that
    hand-rolled the INSERT would be asserting the policy handles objects the test made rather than
    objects the system stored.
    """
    return SqlAttestationStore(world).add(
        Attestation(
            attestation_id=attestation_id,
            claim_id="clm:1",
            epistemic_type=EpistemicType.REPORTED,
            source_artifact_id=world.artifact_id,
            locator="p.1",
            conditions_schema_version="core/sch_test@1.0.0",
            authority_class=authority_class,
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="ext:t", extractor_version="1.0.0"
            ),
        )
    )


def _supports(world, relation_id: str, attestation_id: str) -> RelationJudgment:
    return SqlRelationStore(world).add(
        RelationJudgment(
            relation_id=relation_id,
            from_entity_id=attestation_id,
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            project_id=PROJECT,
            supporting_attestation_ids=(attestation_id,),
            valid_from=T0,
            created_at=T0,
        )
    )


def _episode(world, ids: CountingIds | None = None) -> BeliefEpisode:
    registry = AuthorityPolicyRegistry()
    registry.register(ToyAuthorityPolicy())
    return BeliefEpisode(
        policies=SqlTransitionPolicyStore(world),
        decisions=SqlBeliefTransitionDecisionStore(world),
        events=SqlBeliefEventStore(world),
        relations=SqlRelationStore(world),
        authority_classes=SqlAttestationStore(world),
        conflicts=SqlConflictStore(world),
        reviews=SqlReviewItemStore(world),
        ids=ids or CountingIds(),
        authority_policies=registry.as_mapping(),
    )


def _admit(world) -> None:
    """§8's admission gate: the hypothesis gets a first state, and this path is not it.

    The admission cites its own attestation because §6.18 requires every event to name what
    triggered it -- an event with no triggers survives every contamination rollback and makes the
    replay quietly incomplete. `att:genesis` is never used as *support*: no relation points at the
    hypothesis through it, so it does not reach `evaluate`.
    """
    _attestation(world, "att:genesis", authority_class=None)
    SqlBeliefEventStore(world).append(
        admit_hypothesis(
            event_id="bre:genesis",
            policy=GENESIS,
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=EpistemicStateProjection(
                project_id=PROJECT, target_id=HYP, current_state=None, last_event_id=None
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(
                SqlAttestationStore(world).get(PROJECT, "att:genesis"),  # type: ignore[arg-type]
            ),
        )
    )


# --------------------------------------------------------------------------------------------
# 1. The positive vertical. ALLOW -> Decision -> Event -> verified replay -> projection.
# --------------------------------------------------------------------------------------------


def test_admitted_support_produces_a_decision_an_event_and_a_replayed_projection(world):
    """Fixture 1, and the shape of the whole requirement.

    Every stage is asserted to have *persisted*, because the failure this guards against is a path
    that computes the right answer in memory and writes half of it.
    """
    _admit(world)
    attestation = _attestation(world, "att:1", authority_class="TIER_A")
    relation = _supports(world, "rel:1", "att:1")

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
        episode_id=EPISODE,
        triggering_attestations=(attestation,),
    )

    assert result.decision.outcome is TransitionOutcome.ALLOW
    assert result.decision.reason_code is TransitionReason.POLICY_SATISFIED
    assert result.transitioned

    # The durable authorization (§17.14.1), re-readable and bound to its own inputs.
    stored_decision = SqlBeliefTransitionDecisionStore(world).get(result.authorization.decision_id)
    assert stored_decision is not None
    assert stored_decision.input_hash == stored_decision.decision_input_snapshot.input_hash()
    assert stored_decision.authorizes_transition

    # The event, citing it.
    assert result.event is not None
    assert result.event.authorization_decision_id == stored_decision.decision_id
    assert result.event.from_state is BeliefState.ACTIVE
    assert result.event.to_state is BeliefState.SUPPORTED
    assert result.event.triggering_attestation_ids == ("att:1",)
    assert result.event.triggering_relation_ids == (relation.relation_id,)

    # The projection, rebuilt from the log rather than returned from memory.
    assert result.projection.current_state is BeliefState.SUPPORTED
    assert result.projection.last_event_id == result.event.event_id
    assert result.projection.unresolved_conflicts == ()
    assert result.projection.projection_version == "1.0.0"

    # And again from a cold read, to prove the projection is derived and not cached.
    assert (
        _episode(world).project(project_id=PROJECT, hypothesis_id=HYP).current_state
        is BeliefState.SUPPORTED
    )


def test_the_relation_reaches_the_policy_from_the_database_not_from_the_caller(world):
    """The middle leg of SYS-001, which is the one a hand-built fixture silently skips.

    The episode is never handed the relation. It reads it, resolves the authority class off the
    attestation behind it, and puts both in the snapshot -- so the stored Decision proves the
    evidence travelled the path rather than being supplied at the end of it.
    """
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    _supports(world, "rel:1", "att:1")

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
    )

    snapshot = result.authorization.decision_input_snapshot
    assert [r.relation_id for r in snapshot.admitted_relations] == ["rel:1"]
    assert snapshot.admitted_relations[0].supporting_attestation_ids == ("att:1",)
    assert snapshot.hypothesis.admitted_authority_classes == ("TIER_A",), (
        "authority_class lives on Attestation and the policy is pure, so the episode must join them"
    )


def test_an_invalidated_relation_no_longer_reaches_the_policy(world):
    """A withdrawn judgment is history. Replaying today's decision against it would promote a
    belief on evidence somebody has since retracted."""
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    _supports(world, "rel:1", "att:1")
    SqlRelationStore(world).invalidate(
        project_id=PROJECT,
        relation_id="rel:1",
        reason="the cited table was an early draft",
        actor_id="act:test",
        at=T0 + dt.timedelta(minutes=30),
    )

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
    )
    assert result.decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert result.decision.reason_code is TransitionReason.MISSING_REQUIRED_RELATION_TYPE
    assert not result.transitioned


# --------------------------------------------------------------------------------------------
# 2. INCOMPARABLE authority. This is EPI-004's "auto", and it had no caller until now.
# --------------------------------------------------------------------------------------------


def test_incomparable_authority_auto_creates_the_conflict_and_the_review_and_no_event(world):
    """Fixture 2. Nothing in this test names a conflict or a review; the episode creates both."""
    _admit(world)
    attestation = _attestation(world, "att:1", authority_class="SIDEBAND")
    _supports(world, "rel:1", "att:1")

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote-authority",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
        episode_id=EPISODE,
        authority_policy_ref=AUTHORITY_REF,
        triggering_attestations=(attestation,),
        estimated_human_minutes=30,
    )

    assert result.decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert result.decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE
    assert result.escalated and not result.escalation_was_existing

    conflict = result.conflict
    assert conflict is not None
    assert conflict.conflict_type is ConflictType.AUTHORITY_CONFLICT
    assert conflict.blocking is True
    assert conflict.subject_refs == (HYP,), "the hypothesis is one hop away (§17.19.3, v3.3-a14)"
    assert conflict.episode_id == EPISODE

    review = result.review
    assert review is not None
    assert review.subject_type is ReviewSubjectType.AUTHORITY_CONFLICT
    assert review.subject_id == conflict.conflict_id
    assert review.status is ReviewStatus.QUEUED
    assert review.stakes == "HIGH", "carried from the decision, not re-derived"
    assert review.required_authority == "TIER_A"

    # Persisted and linked, read back cold.
    stored = SqlConflictStore(world).get(PROJECT, conflict.conflict_id)
    assert stored is not None
    assert stored.review_id == review.review_id
    assert stored.resolution_status is ConflictResolutionStatus.UNDER_REVIEW

    # AND NO EVENT. The belief did not move.
    assert not result.transitioned
    assert SqlBeliefEventStore(world).history(PROJECT, HYP) == (
        SqlBeliefEventStore(world).get("bre:genesis"),
    )
    assert result.projection.current_state is BeliefState.ACTIVE
    assert result.projection.unresolved_conflicts == (conflict.conflict_id,)


def test_a_retried_episode_reuses_the_same_conflict_and_review(world):
    """Fixture 3. A retry is legitimate; a second queued reviewer for one block is not.

    Both halves matter and they live in different places. `011c` makes the *escalation* idempotent
    per conflict, proven under real concurrency in P13. This asserts the half that is the episode's:
    a retry that minted a fresh conflict id would sail straight past that guarantee with two
    conflicts, two reviews and one hypothesis blocked twice.
    """
    _admit(world)
    _attestation(world, "att:1", authority_class="SIDEBAND")
    _supports(world, "rel:1", "att:1")

    def run(ids: CountingIds):  # type: ignore[no-untyped-def]
        return _episode(world, ids).attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:promote-authority",
            policy_version="1.0.0",
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0 + dt.timedelta(hours=1),
            trace_id=TRACE,
            episode_id=EPISODE,
            authority_policy_ref=AUTHORITY_REF,
        )

    # ONE id source across both runs, so the retry proposes *different* ids -- `cfl:2`, `rvw:2`.
    # That is the harder case and the realistic one: a retried episode does not remember what it
    # called things last time, so reusing the existing rows cannot come from the ids matching.
    ids = CountingIds()
    first = run(ids)
    second = run(ids)

    assert second.escalation_was_existing
    assert second.conflict is not None and first.conflict is not None
    assert second.conflict.conflict_id == first.conflict.conflict_id
    assert second.review is not None and first.review is not None
    assert second.review.review_id == first.review.review_id

    assert (
        world.execute(
            "SELECT count(*) FROM conflicts WHERE project_id = %s AND %s = ANY (subject_refs)",
            (PROJECT, HYP),
        ).fetchone()[0]
        == 1
    ), "a retried episode queued a second block"
    assert (
        world.execute(
            "SELECT count(*) FROM review_items WHERE project_id = %s", (PROJECT,)
        ).fetchone()[0]
        == 1
    ), "a retried episode queued a second reviewer"


def test_an_existing_blocking_conflict_prevents_both_promotion_and_rejection(world):
    """Fixture 4, in both directions. §8.2.1 blocks promotion *and* rejection until review.

    A gate that blocked promotions and let rejections through would satisfy the sentence as it is
    usually read while violating what it says: rejecting a hypothesis on authority nobody could
    rank is the same error as promoting one.
    """
    _admit(world)
    _attestation(world, "att:1", authority_class="SIDEBAND")
    _supports(world, "rel:1", "att:1")
    episode = _episode(world)
    blocked = episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote-authority",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
        authority_policy_ref=AUTHORITY_REF,
    )
    assert blocked.conflict is not None

    # Now a policy with no authority rule at all, whose relation requirement *is* satisfied. The
    # only thing standing between it and ALLOW is the conflict raised above.
    promotion = episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=2),
        trace_id=TRACE,
    )
    assert promotion.decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert promotion.decision.reason_code is TransitionReason.BLOCKING_CONFLICT
    assert promotion.decision.blocking_conflict_ids == (blocked.conflict.conflict_id,)
    assert not promotion.transitioned

    rejection = episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:contradict",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.CONTRADICTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=3),
        trace_id=TRACE,
    )
    assert not rejection.transitioned

    assert [e.event_id for e in SqlBeliefEventStore(world).history(PROJECT, HYP)] == ["bre:genesis"]


# --------------------------------------------------------------------------------------------
# 3. The quiet branches. A refusal that writes nothing is the easiest thing to get wrong.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy_id", "to_state", "outcome", "reason"),
    [
        (
            "pol:contradict",
            BeliefState.CONTRADICTED,
            TransitionOutcome.NEED_MORE_EVIDENCE,
            TransitionReason.MISSING_REQUIRED_RELATION_TYPE,
        ),
        (
            "pol:unrelated",
            BeliefState.INCONCLUSIVE,
            TransitionOutcome.DENY,
            TransitionReason.TRANSITION_NOT_GOVERNED,
        ),
    ],
    ids=["need_more_evidence", "deny"],
)
def test_a_refused_transition_writes_no_event_and_raises_no_conflict(
    world, policy_id, to_state, outcome, reason
):
    """Fixture 5. Neither refusal is an escalation, and treating either as one would queue human
    work for a question the policy already answered."""
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    _supports(world, "rel:1", "att:1")

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id=policy_id,
        policy_version="1.0.0",
        candidate_to_state=to_state,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
    )

    assert result.decision.outcome is outcome
    assert result.decision.reason_code is reason
    assert not result.transitioned and not result.escalated
    assert [e.event_id for e in SqlBeliefEventStore(world).history(PROJECT, HYP)] == ["bre:genesis"]
    assert world.execute("SELECT count(*) FROM conflicts").fetchone()[0] == 0
    assert world.execute("SELECT count(*) FROM review_items").fetchone()[0] == 0

    # The refusal is still recorded. §17.14.1 keeps a DENY because "this was considered and
    # refused" is a fact, and a planner that cannot see it will propose the same thing again.
    stored = SqlBeliefTransitionDecisionStore(world).get(result.authorization.decision_id)
    assert stored is not None and not stored.authorizes_transition


def test_the_projection_is_unchanged_by_every_refusal(world):
    """The state after three refusals is the state before them, event for event."""
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    _supports(world, "rel:1", "att:1")
    episode = _episode(world)
    before = episode.project(project_id=PROJECT, hypothesis_id=HYP, projected_at=T0)

    for policy_id, to_state in (
        ("pol:contradict", BeliefState.CONTRADICTED),
        ("pol:unrelated", BeliefState.INCONCLUSIVE),
    ):
        episode.attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id=policy_id,
            policy_version="1.0.0",
            candidate_to_state=to_state,
            stakes="HIGH",
            occurred_at=T0 + dt.timedelta(hours=1),
            trace_id=TRACE,
        )

    after = episode.project(project_id=PROJECT, hypothesis_id=HYP, projected_at=T0)
    assert after == before


# --------------------------------------------------------------------------------------------
# 4. The bypasses. Fixture 6, attempted rather than asserted impossible.
# --------------------------------------------------------------------------------------------


def test_cognition_cannot_write_a_projection_because_there_is_nothing_to_write_to(world):
    """The structural half: `EpistemicStateProjection` is derived, and there is no table for it.

    The bypass an LLM-driven implementation reaches for first is "set current_status". There is no
    such column anywhere in the schema -- status is rebuilt from `BeliefRevisionEvent` (§8.1) --
    and asserting the absence is what stops a well-meaning reintroduction.
    """
    # A belief-status column by any of its plausible names, anywhere in the schema.
    belief_named = world.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public'"
        "   AND column_name IN ('current_status', 'current_state', 'belief_state', 'belief_level',"
        "                       'hypothesis_status', 'epistemic_state')"
    ).fetchall()
    assert belief_named == [], (
        f"a writable belief-status column exists: {belief_named}. §8.1 rebuilds status from "
        "BeliefRevisionEvent, and a column is a place to set it instead"
    )

    #: Bare `status` columns are allowed only where the lifecycle is *not* scientific belief, and
    #: each one is named here so a new table carrying belief status fails rather than blending in.
    #: `review_items.status` is §17.19.1's queue state, `execution_spans.status` is §17.19.1's
    #: observability state, `conflicts.resolution_status` is §17.19.3's -- none of them is what a
    #: hypothesis is believed to be, and all three change through their own governed paths.
    #:
    #: `runs.status` joined them with OPS-001 (`006`). It is §17.4's execution outcome -- did this
    #: backend invocation succeed -- and is write-once with the Run. What a Run *means* for belief
    #: is decided downstream by AuthorityPolicy and TransitionPolicy over the attestations that
    #: cite it, never by reading this column. `jobs.state` is deliberately not in this set because
    #: it is not called `status`, and renaming it to match would make it look like one of these.
    #: `ingestion_stage_results.status` joined with `012`. It is §17.22's StageResult outcome --
    #: did this parse finish -- and UX-001 derives the ITEM's state from a precedence over these
    #: rather than reading any one of them as a verdict. Nothing about belief is representable in
    #: it; the vocabulary is SUCCEEDED/FAILED/SKIPPED/PENDING/DEGRADED.
    declared_non_belief = {
        "review_items",
        "execution_spans",
        "runs",
        "ingestion_stage_results",
    }
    bare_status = {
        table
        for table, _ in world.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_name = 'status'"
        ).fetchall()
    }
    assert bare_status <= declared_non_belief, (
        f"undeclared `status` column(s) on {sorted(bare_status - declared_non_belief)}. If this is "
        "a belief status it must not exist; if it is another lifecycle, declare it here"
    )
    assert not world.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public'"
        "   AND table_name LIKE '%projection%'"
    ).fetchall(), "a stored projection would be a status somebody could UPDATE"


def test_an_llm_verdict_cannot_become_an_event_without_passing_the_policy(world):
    """The behavioural half. A cognition result is prose; nothing consumes it as a verdict.

    This is the shape of the bypass §26 names: a model returns `{"status": "SUPPORTED"}` and a
    caller applies it. The event store takes `AuthorizedRevision`, which cannot be constructed
    outside `lab_brain.core.belief`, so the prose has nowhere to go -- and the only function that
    mints one refuses a non-ALLOW authorization.
    """
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    _supports(world, "rel:1", "att:1")

    llm_said = {"hypothesis_id": HYP, "status": "SUPPORTED", "confidence": "high"}
    assert "status" in llm_said  # it exists, and that is all it does

    # There is no store method that takes it.
    store = SqlBeliefEventStore(world)
    assert not [
        name
        for name in dir(store)
        if not name.startswith("_") and name in {"set_status", "apply", "update", "write_state"}
    ]

    # And the capability the store *does* take cannot be built by hand.
    from lab_brain.core.belief import AuthorizedRevision

    with pytest.raises(BeliefTransitionRefused, match="cannot be constructed directly"):
        AuthorizedRevision(event=SqlBeliefEventStore(world).get("bre:genesis"), origin="TRANSITION")  # type: ignore[arg-type]

    assert [e.event_id for e in store.history(PROJECT, HYP)] == ["bre:genesis"]


def test_an_episode_refuses_a_policy_that_is_not_registered(world):
    """An unregistered policy version cannot be re-derived later, so the transition it would
    authorise could never be audited -- refused before anything is evaluated."""
    _admit(world)
    with pytest.raises(EpisodeRefused, match="is not registered"):
        _episode(world).attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:promote",
            policy_version="9.9.9",
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0,
            trace_id=TRACE,
        )


def test_an_episode_refuses_an_admission_policy(world):
    """§8's admission gate is a separate path; running it here would make every dropped
    predecessor look like a beginning."""
    _admit(world)
    with pytest.raises(EpisodeRefused, match="admission policy"):
        _episode(world).attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:admission",
            policy_version="1.0.0",
            candidate_to_state=BeliefState.ACTIVE,
            stakes="HIGH",
            occurred_at=T0,
            trace_id=TRACE,
        )


def test_an_episode_refuses_a_hypothesis_with_no_admitted_history(world):
    """No admission, no state to transition from. Inventing one is how a transition becomes a
    beginning."""
    with pytest.raises(EpisodeRefused, match="no admitted history"):
        _episode(world).attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:promote",
            policy_version="1.0.0",
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0,
            trace_id=TRACE,
        )


def test_a_missing_authority_comparator_refuses_rather_than_queueing_a_human(world):
    """The distinction `evaluate` cannot make, and the episode can.

    `evaluate` reads a `None` comparator beside a `required_authority_rule` as
    AUTHORITY_INCOMPARABLE -- correct for a pure function that cannot tell "unrankable classes"
    from "nobody supplied a ranker". Escalating here would bill a configuration error to the one
    budget §14.4.1 calls scarce.
    """
    _admit(world)
    _attestation(world, "att:1", authority_class="SIDEBAND")
    _supports(world, "rel:1", "att:1")

    with pytest.raises(EpisodeRefused, match="no authority_policy_ref was supplied"):
        _episode(world).attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:promote-authority",
            policy_version="1.0.0",
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0,
            trace_id=TRACE,
        )
    assert world.execute("SELECT count(*) FROM review_items").fetchone()[0] == 0

    with pytest.raises(EpisodeRefused, match="is not registered"):
        _episode(world).attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:promote-authority",
            policy_version="1.0.0",
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0,
            trace_id=TRACE,
            authority_policy_ref=("auth:nobody", "1.0.0"),
        )
    assert world.execute("SELECT count(*) FROM review_items").fetchone()[0] == 0


def test_evidence_from_another_project_cannot_justify_this_projects_belief(world):
    """SEC-002 on the write path. The relation read is project-scoped, so the foreign judgment is
    simply not there -- and the transition reports missing evidence rather than borrowing it."""
    world.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:other', 'Other')"
        " ON CONFLICT DO NOTHING"
    )
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    SqlRelationStore(world).add(
        RelationJudgment(
            relation_id="rel:foreign",
            from_entity_id="att:1",
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            project_id="prj:other",
            actor_id="act:test",
            valid_from=T0,
            created_at=T0,
        )
    )

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
    )
    assert result.decision.reason_code is TransitionReason.MISSING_REQUIRED_RELATION_TYPE
    assert not result.transitioned


def test_a_forged_decision_written_by_raw_sql_never_reaches_the_projection(world):
    """`v3.3-a13`'s read-side obligation, exercised through the episode's own projection path.

    The database accepts this row -- it is internally consistent, and re-running `evaluate` in SQL
    would mean a second copy of §8.2.1 living there. The production read path re-derives, and the
    projection is left unchanged rather than quietly including a belief nobody authorised.
    """
    _admit(world)
    _attestation(world, "att:1", authority_class="TIER_A")
    relation = _supports(world, "rel:1", "att:1")
    episode = _episode(world)

    # Format-perfect and semantically false: canonical snapshot, correct `input_hash`, correct
    # project/subject/policy/from->to, `result` ALLOW -- and zero independent attestations against
    # a policy that requires two, so the snapshot really evaluates to NEED_MORE_EVIDENCE.
    snapshot = DecisionInputSnapshot(
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        admitted_relations=(relation,),
        independence_summary=IndependenceSummary(independent_count=0),
        candidate_to_state=BeliefState.SUPPORTED,
    )
    honest = PROMOTE_INDEPENDENT.evaluate(
        snapshot.hypothesis,
        snapshot.admitted_relations,
        None,
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )
    assert honest.outcome is not TransitionOutcome.ALLOW, "the forgery has to really fail"
    claimed = honest.model_copy(
        update={
            "outcome": TransitionOutcome.ALLOW,
            "reason_code": TransitionReason.POLICY_SATISFIED,
        }
    )
    world.execute(
        "INSERT INTO belief_transition_decisions (decision_id, project_id, subject_id, result,"
        " policy_id, policy_version, from_state, to_state, decision_input_snapshot, input_hash,"
        " evaluated_decision, created_at)"
        " VALUES ('dec:forged', %s, %s, 'ALLOW', %s, %s, 'ACTIVE', 'SUPPORTED', %s, %s, %s, %s)",
        (
            PROJECT,
            HYP,
            PROMOTE_INDEPENDENT.policy_id,
            PROMOTE_INDEPENDENT.version,
            snapshot.canonical_bytes_text(),
            snapshot.input_hash(),
            canonicalize(claimed.model_dump(mode="json")),
            T0,
        ),
    )
    world.execute(
        "SELECT belief_revision_event_append('bre:forged', %s, 'HYPOTHESIS', %s, 'ACTIVE',"
        " 'SUPPORTED', %s, %s, %s, %s, NULL, NULL, NULL, %s, %s, 'dec:forged')",
        (
            PROJECT,
            HYP,
            ["att:1"],
            [],
            PROMOTE_INDEPENDENT.policy_id,
            PROMOTE_INDEPENDENT.version,
            T0 + dt.timedelta(hours=1),
            TRACE,
        ),
    )
    # The database accepted it, and that is expected: re-running `evaluate` in SQL would mean a
    # second copy of §8.2.1 living there.
    assert SqlBeliefEventStore(world).get("bre:forged") is not None

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        episode.project(project_id=PROJECT, hypothesis_id=HYP)
    assert caught.value.reason is VerificationFailure.NOT_REDERIVABLE

    # And the episode cannot be driven past it either: the attempt re-projects first.
    with pytest.raises(UnverifiedBeliefRevision):
        episode.attempt_transition(
            project_id=PROJECT,
            hypothesis_id=HYP,
            policy_id="pol:promote",
            policy_version="1.0.0",
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0 + dt.timedelta(hours=2),
            trace_id=TRACE,
        )
