"""M3 end to end on PostgreSQL: question -> debate -> competing set -> gated belief revision.

    T-EPI-001  root-cause episode 在驗證前保留至少兩個 active/competing hypotheses。
    T-SRC-002  DIAGNOSIS/NOVELTY 使用不同 source policies；high-stakes decision 未執行 inverted
               retrieval 時 BELIEF_REVISION 被拒絕；執行後 CritiqueReport.inverted_bundle_id 與
               bundle divergence 可追溯；critique path 在 retrieval bundle、reasoning policy 或
               model route 至少一項與原推論不同，且 adjudication 引用 external evidence 或
               verification result ... irreversible action 在 critique 未完成時 MUST NOT dispatch，
               即使 causes_belief_revision = false；帶有效 human approval 但無 critique 時仍 MUST NOT
               dispatch。

THE FLOW, EVERY ARROW DURABLE:

    question
      -> FAST_UTILITY query rewrite -> primary bundle under srcpol:diagnosis (stored)
      -> Hypothesis Engine (REASONING_PRIMARY): >=2 certificates -> §8 admission -> set + genesis
         events citing the primary bundle's attestations
      -> Domain Specialists (DomainPack-registered), each over its own domain bundle -> Positions
      -> Critic (REASONING_ADVERSARIAL): inverted retrieval (stored) -> CritiqueReport whose
         independence `005e` re-derives -> escalation by trigger -> the Critic's alternative
         certified and admitted -> round 2 -> no trigger -> stop
      -> Stage C: verification ranked over every active rival by the pack's disagreement metric
      -> DebateRecord with §15.4's metrics and the (advisory) LLM-002 gate reading
      -> HypothesisBrain.attempt_revision: M3 preconditions, then M1's governed transition

The model transport is the deterministic `MockScientist`; no external model, search or licensed
tool is called. Reloads go through a second connection, as a restarted worker would.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest

from lab_brain.cognition.debate import DebatePolicy
from lab_brain.cognition.novelty import SanitizedConcept
from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.models import BeliefState, RelationJudgment, RelationType, TransitionPolicy
from lab_brain.core.models.enums import EpistemicType, SensitivityLabel
from lab_brain.core.models.prior_art import DateRange
from lab_brain.core.repositories.belief_events import SqlBeliefEventStore
from lab_brain.core.repositories.debate import SqlDebateStore
from lab_brain.core.repositories.evidence import SqlRelationStore
from lab_brain.core.repositories.evidence_bundles import SqlEvidenceBundleRepository
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.prior_art import SqlPriorArtStore
from lab_brain.core.revision_gate import RevisionPrecondition, RevisionPreconditionFailed
from lab_brain.tools.dispatch import ToolDispatchRefused
from tests.debate_fixtures import (
    ACTOR,
    ADMISSION_POLICY,
    EPISODE,
    LITERATURE,
    PATENTS,
    PROJECT,
    T0,
    TRACE,
    budget_policy,
    build_world,
    load_fixture,
    make_certificate,
    make_set,
    novelty_tools,
)
from tests.postgres_fixtures import database_url
from tests.unit.test_irreversible_dispatch import (
    Spy,
    _action,
    _capabilities,
    _dispatcher,
    _supervisor,
)
from tests.unit.test_irreversible_dispatch import _policy as tool_budget

pytestmark = [pytest.mark.postgres]

LATER = T0 + dt.timedelta(days=1)
PROMOTE = TransitionPolicy(
    policy_id="tp:m3.promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)
REJECT = TransitionPolicy(
    policy_id="tp:m3.reject",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.CONTRADICTED,
    required_relation_types=(RelationType.CONTRADICTS,),
)


def _case(case_id: str) -> dict[str, Any]:
    return next(c for c in load_fixture()["cases"] if c["case_id"] == case_id)


def _world(db, case_id: str = "hard-1", **kwargs: Any):  # type: ignore[no-untyped-def]
    case = _case(case_id)
    world = build_world(case, connection=db, transition_policies=(PROMOTE, REJECT), **kwargs)
    assert world.brain is not None
    return world, world.brain.debate(world.request(case))


def _truth(outcome) -> str:  # type: ignore[no-untyped-def]
    mechanism = load_fixture()["mechanisms"]["dopant_compensation"]["mechanism"]
    return next(
        c.hypothesis_id for c in outcome.certificates if c.hypothesis.mechanism == mechanism
    )


def _factual(world, outcome):  # type: ignore[no-untyped-def]
    """Evidence the Critic's inverted retrieval found: external, REPORTED, not a model's opinion."""
    return world.attestations[outcome.inverted_bundles[0].ordered_attestation_ids[0]]


def _relation(db, relation_id: str, attestation_id: str, target: str, kind: RelationType) -> None:  # type: ignore[no-untyped-def]
    SqlRelationStore(db).add(
        RelationJudgment(
            relation_id=relation_id,
            from_entity_id=attestation_id,
            to_entity_id=target,
            relation_type=kind,
            project_id=PROJECT,
            supporting_attestation_ids=(attestation_id,),
            valid_from=T0,
            created_at=T0,
        )
    )


def _count(db, table: str) -> int:  # type: ignore[no-untyped-def]
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _revise(world, hypothesis_id: str, policy: TransitionPolicy, basis):  # type: ignore[no-untyped-def]
    return world.brain.attempt_revision(
        project_id=PROJECT,
        hypothesis_id=hypothesis_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidate_to_state=policy.candidate_to_state,
        occurred_at=LATER,
        trace_id=TRACE,
        triggering_attestations=basis,
        actor_id=ACTOR,
    )


# -- T-EPI-001 -----------------------------------------------------------------------------------


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_a_root_cause_episode_holds_at_least_two_active_competitors_before_verification(db):
    world, outcome = _world(db)
    assert outcome.hypothesis_set.root_cause
    # Before any verification -- nothing has been run, no transition attempted -- every admitted
    # rival is ACTIVE, the Critic's challenged ones included: a critique moves no belief.
    states = {
        c.hypothesis_id: world.episode.project(
            project_id=PROJECT, hypothesis_id=c.hypothesis_id
        ).current_state
        for c in outcome.certificates
    }
    active = [h for h, s in states.items() if s is BeliefState.ACTIVE]
    assert len(active) >= 2 and len(active) == len(outcome.certificates) == 3
    assert set(outcome.contradicted_ids) <= set(active)

    # Stage C plans verification over all of them.
    assert outcome.ranking and {h for h, _ in outcome.ranking[0].predictions} == set(active)

    # Reloaded by a process that did none of the writing.
    with psycopg.connect(database_url(), autocommit=True) as fresh:
        certificates = SqlHypothesisStore(fresh).certificates_in_set(outcome.hypothesis_set.set_id)
        assert certificates == outcome.certificates
        for certificate in certificates:
            genesis = SqlBeliefEventStore(fresh).history(PROJECT, certificate.hypothesis_id)[0]
            assert genesis.from_state is None and genesis.to_state is BeliefState.ACTIVE
            assert genesis.triggering_attestation_ids, "a genesis cites the evidence it rests on"
            assert genesis.inference_provenance_id == certificate.hypothesis.inference_provenance_id
        record = SqlDebateStore(fresh).get_debate_record(outcome.record.debate_id)
        assert record == outcome.record


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_the_debated_root_cause_is_promoted_on_external_evidence_and_its_rivals_stay_open(db):
    world, outcome = _world(db)
    truth = _truth(outcome)
    evidence = _factual(world, outcome)
    _relation(db, "rel:for-truth", evidence.attestation_id, truth, RelationType.SUPPORTS)

    result = _revise(world, truth, PROMOTE, (evidence,))

    assert result.transitioned and result.event is not None
    assert result.event.to_state is BeliefState.SUPPORTED
    assert result.event.authorization_decision_id == result.authorization.decision_id
    assert result.projection.current_state is BeliefState.SUPPORTED
    for other in outcome.certificates:
        if other.hypothesis_id != truth:
            assert (
                world.episode.project(
                    project_id=PROJECT, hypothesis_id=other.hypothesis_id
                ).current_state
                is BeliefState.ACTIVE
            )


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_a_single_plausible_cause_is_refused_before_any_decision_is_written(db):
    world, outcome = _world(db)
    lonely_set = make_set("hst:lonely", inverted_retrieval_required=False)
    lonely = make_certificate("normalization_error", lonely_set)
    SqlHypothesisStore(db).add_set(lonely_set)
    SqlHypothesisStore(db).add_certificate(lonely)
    evidence = _factual(world, outcome)
    SqlBeliefEventStore(db).append(
        admit_hypothesis(
            event_id="bre:lonely",
            policy=ADMISSION_POLICY,
            project_id=PROJECT,
            hypothesis_id=lonely.hypothesis_id,
            prior=EpistemicStateProjection(
                project_id=PROJECT,
                target_id=lonely.hypothesis_id,
                current_state=None,
                last_event_id=None,
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(evidence,),
        )
    )
    _relation(
        db, "rel:lonely", evidence.attestation_id, lonely.hypothesis_id, RelationType.SUPPORTS
    )
    decisions = _count(db, "belief_transition_decisions")

    with pytest.raises(RevisionPreconditionFailed) as refused:
        _revise(world, lonely.hypothesis_id, PROMOTE, (evidence,))

    assert RevisionPrecondition.SINGLE_PLAUSIBLE_CAUSE in refused.value.verdict.codes
    assert _count(db, "belief_transition_decisions") == decisions, "nothing written on a refusal"
    assert len(SqlBeliefEventStore(db).history(PROJECT, lonely.hypothesis_id)) == 1


# -- T-SRC-002 -----------------------------------------------------------------------------------


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_diagnosis_and_novelty_retrieve_under_different_source_policies(db):
    world, outcome = _world(db)
    store = SqlPriorArtStore(db)
    search, auditor = novelty_tools(world, [LITERATURE, PATENTS], store)
    policy = world.source_policies.for_intent("NOVELTY_AUDIT")
    concept = SanitizedConcept(
        subject_id=_truth(outcome),
        text="graded dopant compensation rib series resistance",
        declared_label=SensitivityLabel.INTERNAL,
        sanitized_by_actor_id="act:pi",
    )
    record, hits = search.search(
        concept=concept,
        queries=["dopant compensation series resistance"],
        date_range=DateRange(start=dt.date(2015, 1, 1), end=dt.date(2026, 9, 1)),
        policy=policy,
        project_id=PROJECT,
        episode_id=EPISODE,
        actor_id=ACTOR,
    )
    auditor.assess(
        concept=concept,
        record=record,
        hits=hits,
        policy=policy,
        stakes="NORMAL",
        trace_id=TRACE,
        actor_id=ACTOR,
        budget_policy=budget_policy(),
    )
    policies = {
        row[0] for row in db.execute("SELECT DISTINCT source_policy_id FROM evidence_bundles")
    }
    assert policies == {"srcpol:diagnosis", "srcpol:novelty-audit"}
    assert outcome.hypothesis_set.source_policy_id == "srcpol:diagnosis"


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_high_stakes_decision_without_inverted_retrieval_is_refused_belief_revision(db):
    world, outcome = _world(db, policy=DebatePolicy(perform_inverted_retrieval=False))
    assert outcome.hypothesis_set.inverted_retrieval_required
    target = outcome.certificates[0].hypothesis_id
    evidence = world.attestations[outcome.primary_bundle.ordered_attestation_ids[0]]
    _relation(db, "rel:for", evidence.attestation_id, target, RelationType.SUPPORTS)
    decisions, events = (
        _count(db, "belief_transition_decisions"),
        _count(db, "belief_revision_events"),
    )

    with pytest.raises(RevisionPreconditionFailed) as refused:
        _revise(world, target, PROMOTE, (evidence,))

    assert RevisionPrecondition.NO_INVERTED_RETRIEVAL in refused.value.verdict.codes
    assert (_count(db, "belief_transition_decisions"), _count(db, "belief_revision_events")) == (
        decisions,
        events,
    )


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_the_inverted_bundle_and_its_divergence_are_traceable_after_a_reload(db):
    world, outcome = _world(db)
    policy = world.source_policies.for_intent("DIAGNOSIS")
    with psycopg.connect(database_url(), autocommit=True) as fresh:
        debates = SqlDebateStore(fresh)
        bundles = SqlEvidenceBundleRepository(fresh)
        record = debates.get_debate_record(outcome.record.debate_id)
        assert record is not None and record.critic_bundle_divergence is not None
        for critique_id, round_entry in zip(record.critique_ids, record.per_round, strict=True):
            critique = debates.get_critique(critique_id)
            assert critique is not None
            assert critique.inverted_bundle_id == round_entry["inverted_bundle_id"]
            inverted = bundles.get(critique.inverted_bundle_id)
            primary = bundles.get(critique.primary_bundle_id)
            assert inverted is not None and primary is not None
            assert inverted.canonical_hash != primary.canonical_hash
            assert round_entry["critic_bundle_divergence"] is not None
            for attestation_id in inverted.ordered_attestation_ids:
                item = world.researcher.item(PROJECT, attestation_id)
                assert item is not None and item.trust_class in policy.inverted_source_classes
            # Independence, exhibited: re-derived by `005e` from the two provenance rows.
            assert "RETRIEVAL_BUNDLE" in critique.differs_in
            assert "MODEL_ROUTE" in critique.differs_in


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_reject_is_adjudicated_by_external_evidence_never_by_model_opinion(db):
    world, outcome = _world(db)
    rejected = outcome.contradicted_ids[0]
    evidence = _factual(world, outcome)
    _relation(db, "rel:against", evidence.attestation_id, rejected, RelationType.CONTRADICTS)
    opinion = evidence.model_copy(update={"epistemic_type": EpistemicType.INFERRED})

    with pytest.raises(RevisionPreconditionFailed) as refused:
        _revise(world, rejected, REJECT, (opinion,))
    assert refused.value.verdict.codes == {RevisionPrecondition.ADJUDICATED_BY_MODEL_OPINION}

    result = _revise(world, rejected, REJECT, (evidence,))
    assert result.event is not None and result.event.to_state is BeliefState.CONTRADICTED
    assert evidence.attestation_id in result.event.triggering_attestation_ids


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_an_irreversible_action_waits_for_the_durable_independent_critique(db):
    """No belief transition anywhere in this test (`causes_belief_revision = false`)."""
    _, outcome = _world(db)
    critiques = SqlDebateStore(db)
    events = _count(db, "belief_revision_events")

    fatal = Spy(fatal=True)
    dispatcher, _, _, claims = _dispatcher(
        fatal, capabilities=_capabilities(irreversible=True), critiques=critiques
    )
    with pytest.raises(ToolDispatchRefused):
        dispatcher.dispatch(_action(**_supervisor(claims)), policy=tool_budget())
    assert fatal.entered == [] and claims.consumed_at("apr:tapeout") is None

    cited = next(c for c in outcome.critiques if c.cited_attestation_ids)
    working = Spy(fatal=False)
    dispatcher, *_ = _dispatcher(
        working, capabilities=_capabilities(irreversible=True), critiques=critiques
    )
    assert dispatcher.dispatch(
        _action(critique_id=cited.critique_id), policy=tool_budget()
    ).performed
    assert _count(db, "belief_revision_events") == events
