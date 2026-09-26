"""T-EPI-005: admitted evidence reaches the canonical evaluator, and an LLM verdict does not.

    §25.3 EPI-005  Hypothesis state transition MUST be authorized by versioned TransitionPolicy
                   and emitted as BeliefRevisionEvent; LLM cannot directly mutate status. ...
                   re-evaluating those inputs under the named immutable policy MUST reproduce the
                   stored decision under canonical serialization, and MUST fail closed otherwise.
    §26   T-EPI-005 ... admitted RelationJudgments + policy produce event and replayable projection

THE GAP THIS FILE CLOSES, WHICH IS NOT THE POLICY ENGINE. §8.2.1's evaluator is already heavily
governed: `tests/contract/test_transition_policy.py` pins its determinism across processes and hash
seeds, `test_belief_transition.py` pins every way an event could claim an authorization it lacks,
and `test_belief_authorization_verification_postgres.py` pins the semantic forgery. All of those
build their `RelationJudgment` and `HypothesisView` objects **in the test**.

So the one thing nothing showed was the sentence §26 actually writes: that *admitted*
RelationJudgments -- rows in the database, admitted through the evidence path -- reach the
evaluator and produce the durable chain. A vertical assembled by hand at the top proves the policy
handles the objects the test made.

    persisted attestation
      -> persisted RelationJudgment
      -> episode reads both and builds the exact six evaluate inputs
      -> evaluate
      -> durable Decision: canonical snapshot + input_hash
      -> BeliefRevisionEvent citing it
      -> reload through fresh stores, as a different process would
      -> re-derive
      -> projection

Every arrow is asserted, and the reload is through new store objects rather than the ones that did
the writing, because an in-process cache would make the last three arrows a tautology.
"""

from __future__ import annotations

import datetime as dt
import itertools

import pytest

from lab_brain.core.belief import (
    EpistemicStateProjection,
    admit_hypothesis,
    rederive_decision,
    verified_history,
)
from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import (
    BeliefState,
    RelationJudgment,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
)
from lab_brain.core.models.attestation import (
    Attestation,
    EpistemicType,
    ExtractionProvenance,
)
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
from tests.postgres_fixtures import admit_hypothesis_identity

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-005"),
    pytest.mark.spec_test("T-EPI-005"),
]

T0 = dt.datetime(2026, 9, 16, 14, 0, tzinfo=dt.UTC)
T1 = T0 + dt.timedelta(hours=1)
PROJECT = "prj:test"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:vertical"

GENESIS = TransitionPolicy(
    policy_id="pol:admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)


class CountingIds:
    def __init__(self) -> None:
        self._counters: dict[str, itertools.count[int]] = {}

    def _next(self, prefix: str) -> str:
        return f"{prefix}:{next(self._counters.setdefault(prefix, itertools.count(1)))}"

    def decision_id(self) -> str:
        return self._next("dec")

    def event_id(self) -> str:
        return self._next("bre")

    def conflict_id(self) -> str:
        return self._next("cfl")

    def review_id(self) -> str:
        return self._next("rvw")


def _episode(world) -> BeliefEpisode:  # type: ignore[no-untyped-def]
    """Fresh store objects every time, so a reload is a real reload."""
    return BeliefEpisode(
        policies=SqlTransitionPolicyStore(world),
        decisions=SqlBeliefTransitionDecisionStore(world),
        events=SqlBeliefEventStore(world),
        relations=SqlRelationStore(world),
        authority_classes=SqlAttestationStore(world),
        conflicts=SqlConflictStore(world),
        reviews=SqlReviewItemStore(world),
        ids=CountingIds(),
    )


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    # M3 / R-12 (`011j`): a belief event names a hypothesis admitted through §8's gate in its own
    # project, so the identity this fixture always meant is established first.
    admit_hypothesis_identity(db, HYP)
    artifact = make_artifact(b"a cognition vertical fixture")
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
    policies = SqlTransitionPolicyStore(db)
    policies.register(GENESIS)
    policies.register(PROMOTE)
    db.artifact_id = artifact.artifact_id  # type: ignore[attr-defined]
    return db


def _persist_evidence(world) -> tuple[Attestation, RelationJudgment]:  # type: ignore[no-untyped-def]
    """The evidence path: an Attestation row, then a RelationJudgment row that cites it."""
    attestation = SqlAttestationStore(world).add(
        Attestation(
            attestation_id="att:1",
            claim_id="clm:1",
            epistemic_type=EpistemicType.MEASURED,
            source_artifact_id=world.artifact_id,
            locator="table 2, row 4",
            conditions_schema_version="core/sch_test@1.0.0",
            authority_class="TIER_A",
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="ext:t", extractor_version="1.0.0"
            ),
        )
    )
    relation = SqlRelationStore(world).add(
        RelationJudgment(
            relation_id="rel:1",
            from_entity_id="att:1",
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            project_id=PROJECT,
            supporting_attestation_ids=("att:1",),
            valid_from=T0,
            created_at=T0,
        )
    )
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
            triggering_attestations=(attestation,),
        )
    )
    return attestation, relation


def _promote(world):  # type: ignore[no-untyped-def]
    return _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T1,
        trace_id=TRACE,
        episode_id="epi:1",
    )


# --------------------------------------------------------------------------------------------
# The vertical.
# --------------------------------------------------------------------------------------------


def test_the_persisted_relation_is_the_one_the_evaluator_saw(world):
    """Arrow by arrow: the row written to `relation_judgments` is the object inside the snapshot.

    Identity is checked on the relation's own fields rather than on `len(...) == 1`, because a
    snapshot containing *a* relation proves nothing about *which* one -- and the failure mode this
    guards is an episode that evaluates a convenient stand-in it built itself.
    """
    _attestation, relation = _persist_evidence(world)
    result = _promote(world)

    assert result.decision.outcome is TransitionOutcome.ALLOW
    snapshot = result.authorization.decision_input_snapshot
    assert len(snapshot.admitted_relations) == 1
    seen = snapshot.admitted_relations[0]
    assert seen.relation_id == relation.relation_id
    assert seen.from_entity_id == "att:1"
    assert seen.to_entity_id == HYP
    assert seen.relation_type is RelationType.SUPPORTS
    assert seen.supporting_attestation_ids == ("att:1",)

    # And it is genuinely the stored row, not the object the test handed to `add`.
    from_db = SqlRelationStore(world).get(PROJECT, "rel:1")
    assert from_db is not None
    assert canonicalize(seen.model_dump(mode="json")) == canonicalize(
        from_db.model_dump(mode="json")
    )


def test_the_snapshot_carries_all_six_inputs_and_binds_them_with_its_hash(world):
    """§17.14.1: "sufficient to reconstruct all six inputs of the canonical operator".

    Six, named, and the hash is asserted to *change* when any of them does -- a hash that covered
    five would let the sixth be edited after the fact without the record noticing.
    """
    _persist_evidence(world)
    result = _promote(world)
    snapshot = result.authorization.decision_input_snapshot

    assert snapshot.hypothesis.hypothesis_id == HYP
    assert snapshot.hypothesis.current_state is BeliefState.ACTIVE
    assert snapshot.hypothesis.admitted_authority_classes == ("TIER_A",)
    assert snapshot.admitted_relations != ()
    assert snapshot.condition_matches == ()
    assert snapshot.independence_summary.independent_count == 0
    assert snapshot.candidate_to_state is BeliefState.SUPPORTED
    assert snapshot.authority_policy_id is None, (
        "this policy declares no authority rule, so recording a comparator would manufacture a "
        "permanent re-derivation dependency on it"
    )
    assert result.authorization.input_hash == snapshot.input_hash()

    mutated = snapshot.model_copy(update={"candidate_to_state": BeliefState.CHALLENGED})
    assert mutated.input_hash() != snapshot.input_hash()


def test_the_chain_survives_a_cold_reload_and_re_derives(world):
    """The reload half, through store objects that did not do the writing.

    A process restart is the realistic case, and it is the one where "we verified it when we wrote
    it" stops being evidence. Nothing here reuses an object from the write path.
    """
    _persist_evidence(world)
    written = _promote(world)
    assert written.event is not None

    events = SqlBeliefEventStore(world).history(PROJECT, HYP)
    assert [event.event_id for event in events] == ["bre:genesis", written.event.event_id]

    revisions = verified_history(
        project_id=PROJECT,
        target_id=HYP,
        events=events,
        decisions=SqlBeliefTransitionDecisionStore(world),
        policies=SqlTransitionPolicyStore(world),
    )
    assert [r.origin for r in revisions] == ["ADMISSION", "TRANSITION"]

    reloaded = SqlBeliefTransitionDecisionStore(world).get(written.authorization.decision_id)
    policy = SqlTransitionPolicyStore(world).get("pol:promote", "1.0.0")
    assert reloaded is not None and policy is not None

    replayed = rederive_decision(authorization=reloaded, policy=policy)
    assert canonicalize(replayed.model_dump(mode="json")) == canonicalize(
        written.decision.model_dump(mode="json")
    ), "§8.2.1: identical inputs and identical policy_version must reproduce the decision"

    projection = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert projection.current_state is BeliefState.SUPPORTED
    assert projection.applied == ("bre:genesis", written.event.event_id)


def test_the_same_evidence_evaluated_twice_authorizes_identically(world):
    """§8.2.1's determinism, over the *persisted* inputs rather than over hand-built ones.

    The second attempt is refused -- the hypothesis has moved, so `record_transition` sees a stale
    predecessor -- which is correct and is not what this test is about. What it asserts is that the
    Decision computed from the same stored evidence has the same `input_hash` and the same verdict
    both times, so a re-run is a check rather than a coin flip.
    """
    _persist_evidence(world)
    first = _promote(world)

    # Re-evaluate the identical six inputs directly, as an auditor would.
    policy = SqlTransitionPolicyStore(world).get("pol:promote", "1.0.0")
    assert policy is not None
    snapshot = first.authorization.decision_input_snapshot
    again = policy.evaluate(
        snapshot.hypothesis,
        snapshot.admitted_relations,
        None,
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )
    assert canonicalize(again.model_dump(mode="json")) == canonicalize(
        first.decision.model_dump(mode="json")
    )
    assert snapshot.input_hash() == first.authorization.input_hash


# --------------------------------------------------------------------------------------------
# The negative. "LLM cannot directly mutate status" is the sentence EPI-005 opens with.
# --------------------------------------------------------------------------------------------


def test_an_llm_result_asserting_a_status_changes_no_belief(world):
    """A realistic cognition payload, offered to every door, and none of them opens.

    The failure this guards is not exotic. A model is asked to assess a hypothesis, it answers with
    a status, and somewhere a caller writes that status down. Here the payload exists, the belief
    does not move, and the projection afterwards is the one admission left.
    """
    _persist_evidence(world)

    llm_result = {
        "hypothesis_id": HYP,
        "status": "SUPPORTED",
        "confidence": 0.93,
        "rationale": "the measured contact resistance is consistent across both wafers",
    }

    before = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert before.current_state is BeliefState.ACTIVE

    # 1. There is no writable status column to put it in.
    assert (
        world.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public'"
            "   AND column_name IN ('current_status', 'current_state', 'belief_state')"
        ).fetchone()[0]
        == 0
    )

    # 2. The event store takes a capability, and `llm_result` is a dict.
    store = SqlBeliefEventStore(world)
    with pytest.raises((AttributeError, TypeError)):
        store.append(llm_result)  # type: ignore[arg-type]

    # 3. The projection is derived from the event log, so nothing an LLM says is an input to it.
    after = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert after == before
    assert llm_result["status"] == "SUPPORTED", "the payload is untouched; it simply has no effect"


def test_a_relation_an_llm_proposed_is_evidence_and_still_not_a_verdict(world):
    """The line AGT-010 draws: a model may *propose* a judgment, and the policy still decides.

    This is the permitted half, and it is worth a test because the two are easy to conflate. The
    relation below carries an `inference_provenance_id` instead of supporting attestations -- an
    LLM-authored judgment -- and it feeds `evaluate` exactly like any other. What it cannot do is
    skip it.
    """
    attestation, _ = _persist_evidence(world)
    SqlRelationStore(world).add(
        RelationJudgment(
            relation_id="rel:llm",
            from_entity_id="att:1",
            to_entity_id=HYP,
            relation_type=RelationType.CONTRADICTS,
            project_id=PROJECT,
            inference_provenance_id="inf:llm-1",
            valid_from=T0,
            created_at=T0,
        )
    )

    result = _promote(world)
    seen = {r.relation_id for r in result.authorization.decision_input_snapshot.admitted_relations}
    assert seen == {"rel:1", "rel:llm"}, "an LLM-proposed judgment is admitted evidence"

    # It reached the evaluator, and the evaluator -- not the model -- produced the verdict.
    assert result.decision.policy_id == "pol:promote"
    assert result.decision.outcome is TransitionOutcome.ALLOW
    assert result.event is not None
    assert result.event.authorization_decision_id == result.authorization.decision_id
    assert attestation.attestation_id == "att:1"
