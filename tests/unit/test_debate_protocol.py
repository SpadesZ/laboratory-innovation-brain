"""§7's Structured Debate, in memory: role I/O contracts, routing, intent policies, the protocol.

    §26.1 M3 exit gate  role I/O + Position/Critique contracts pass; Critic bundle divergence
                        measurable; benchmark thresholds calibrated and stored in BenchmarkPolicy
                        before gate enforcement.

The PostgreSQL e2e (`tests/e2e/test_hypothesis_brain_postgres.py`) runs the same protocol durably;
this file pins each rule where it is cheapest to see it fail.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from lab_brain.cognition.budgeted import InferenceBudgetBlocked
from lab_brain.cognition.debate import DebatePolicy, StopReason, Trigger
from lab_brain.cognition.debate_metrics import (
    ADDITIONAL_EVIDENCE_COST,
    CRITIC_BUNDLE_DIVERGENCE,
    POSITION_DIVERSITY,
    SURVIVING_DIVERSITY,
)
from lab_brain.cognition.llm import LLMRefusal
from lab_brain.cognition.roles import (
    RoleOutputRefused,
    parse_critique,
    parse_hypothesis_engine,
    parse_novelty,
    parse_query_terms,
    parse_specialist,
    require_input,
)
from lab_brain.cognition.routing import CognitiveRole, ModelRouter, RoutingError
from lab_brain.core.models.debate import (
    CritiqueReport,
    Objection,
    ObjectionKind,
    ObjectionSeverity,
    Position,
)
from lab_brain.core.models.enums import TrustClass
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.evidence.source_policy import (
    IntentSourcePolicy,
    SourcePolicyError,
    SourcePolicyRegistry,
    default_source_policies,
)
from tests.debate_fixtures import (
    PROJECT,
    MockScientist,
    build_world,
    load_fixture,
)

T0 = dt.datetime(2026, 9, 26, tzinfo=dt.UTC)


def _case(case_id: str):  # type: ignore[no-untyped-def]
    return next(c for c in load_fixture()["cases"] if c["case_id"] == case_id)


def _space():  # type: ignore[no-untyped-def]
    world = build_world()
    return {
        (s.outcome_space_id, s.version): s
        for s in world.registries.disagreement_metrics.declared_spaces()
    }


def _engine_reply(**changes: object) -> str:
    fx = load_fixture()
    doctor = MockScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space=fx["outcome_space"],
    )
    reply = {
        "hypotheses": [doctor._certificate(k) for k in ("contact_discontinuity", "mesh_artifact")],
        "position": {"mechanism_view": "contact", "uncertainties": [], "confounders": []},
    }
    reply.update(changes)
    return json.dumps(reply)


# -- §7.4 role I/O contracts ---------------------------------------------------------------------


def test_the_hypothesis_engine_contract_accepts_two_complete_certificates():
    proposals, position = parse_hypothesis_engine(_engine_reply(), spaces=_space(), minimum=2)
    assert len(proposals) == 2 and position.mechanism_view == "contact"
    assert all(p.predictions for p in proposals)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda h: h[:1], "at least 2 hypotheses"),
        (lambda h: [{**h[0], "falsifier": ""}, h[1]], "falsifier is missing"),
        (lambda h: [{**h[0], "predictions": []}, h[1]], "no typed prediction"),
        (
            lambda h: [
                {**h[0], "predictions": [{**h[0]["predictions"][0], "outcome_space_version": "9"}]},
                h[1],
            ],
            "was not shown",
        ),
        (
            lambda h: [
                {**h[0], "predictions": [{**h[0]["predictions"][0], "expected_outcome": "MAGIC"}]},
                h[1],
            ],
            "MUST NOT invent outcomes",
        ),
        (
            lambda h: [
                {**h[0], "predictions": [{**h[0]["predictions"][0], "relation_effect": "CITES"}]},
                h[1],
            ],
            "relation effect",
        ),
        (lambda h: [h[0], {**h[1], "key": h[0]["key"]}], "repeats"),
    ],
)
def test_the_hypothesis_engine_contract_refuses_what_exceeds_the_role(mutate, match):
    base = json.loads(_engine_reply())
    reply = json.dumps({**base, "hypotheses": mutate(base["hypotheses"])})
    with pytest.raises(RoleOutputRefused, match=match):
        parse_hypothesis_engine(reply, spaces=_space(), minimum=2)


def test_a_reply_that_is_not_a_json_object_is_refused():
    for text in ("not json", "[1, 2]"):
        with pytest.raises(RoleOutputRefused):
            parse_hypothesis_engine(text, spaces=_space(), minimum=2)


def test_a_specialist_states_a_position_on_the_rivals_it_was_shown_and_adds_none():
    ok = parse_specialist(
        json.dumps({"mechanism_view": "v", "favoured_hypothesis_ids": ["hyp:a"]}),
        role_id="sp.specialist",
        hypothesis_ids=["hyp:a", "hyp:b"],
    )
    assert ok.favoured == ("hyp:a",)
    with pytest.raises(RoleOutputRefused, match="not under consideration"):
        parse_specialist(
            json.dumps({"mechanism_view": "v", "favoured_hypothesis_ids": ["hyp:new"]}),
            role_id="sp.specialist",
            hypothesis_ids=["hyp:a"],
        )


def _objection(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "target_id": "hyp:a",
        "kind": "COUNTEREXAMPLE",
        "severity": "CONTRADICTS",
        "text": "the literature reports otherwise",
        "evidence_attestation_ids": ["att:shown"],
    }
    base.update(changes)
    return base


@pytest.mark.parametrize(
    ("objection", "match"),
    [
        (_objection(target_id="hyp:not-a-target"), "not a target"),
        (_objection(evidence_attestation_ids=["att:never-shown"]), "was not shown"),
        (_objection(evidence_attestation_ids=[]), "CONTRADICTS"),
        (_objection(kind="VIBES"), "VIBES"),
    ],
)
def test_the_critic_contract_refuses_invented_evidence_and_foreign_targets(objection, match):
    with pytest.raises(RoleOutputRefused, match=match):
        parse_critique(
            json.dumps({"objections": [objection]}),
            targets=["hyp:a"],
            shown_attestation_ids=["att:shown"],
        )


def test_the_critic_contract_accepts_a_cited_contradiction_and_an_uncited_challenge():
    draft = parse_critique(
        json.dumps(
            {
                "objections": [
                    _objection(),
                    _objection(
                        kind="MISSING_CONTROL", severity="CHALLENGES", evidence_attestation_ids=[]
                    ),
                ],
                "alternative_mechanisms": ["dopant compensation in the rib"],
                "falsifier_challenges": [
                    {"target_id": "hyp:a", "text": "the falsifier is untestable"}
                ],
            }
        ),
        targets=["hyp:a"],
        shown_attestation_ids=["att:shown"],
    )
    assert [o.severity for o in draft.objections] == [
        ObjectionSeverity.CONTRADICTS,
        ObjectionSeverity.CHALLENGES,
    ]
    assert draft.alternative_mechanisms == ("dopant compensation in the rib",)


def test_the_novelty_auditor_may_only_rate_records_the_search_returned():
    with pytest.raises(RoleOutputRefused, match="did not return"):
        parse_novelty(
            json.dumps(
                {
                    "matrix": [{"record_id": "doi:x", "overlap": "FULL"}],
                    "status": "KNOWN",
                    "scope": "INTERNAL",
                }
            ),
            record_ids=["doi:y"],
        )


def test_a_role_given_less_than_its_contract_is_refused_and_a_rewrite_must_return_terms():
    with pytest.raises(RoleOutputRefused, match="missing"):
        require_input(
            "ADVERSARIAL_CRITIC", frozenset({"evidence", "hypotheses"}), {"hypotheses": []}
        )
    with pytest.raises(RoleOutputRefused, match="no search terms"):
        parse_query_terms(json.dumps({"terms": []}))


def test_position_and_critique_contracts_hold_their_own_invariants():
    with pytest.raises(ValidationError):
        Objection(
            target_id="hyp:a",
            kind=ObjectionKind.COUNTEREXAMPLE,
            severity=ObjectionSeverity.CONTRADICTS,
            text="uncited",
        )
    world = build_world()
    outcome = world.debate.run(world.request())
    critique = outcome.critiques[0]
    with pytest.raises(ValidationError):
        CritiqueReport(
            **{**critique.model_dump(), "inverted_bundle_id": critique.primary_bundle_id}
        )
    with pytest.raises(ValidationError):
        CritiqueReport(**{**critique.model_dump(), "target_ids": ()})
    position = outcome.positions[0]
    with pytest.raises(ValidationError):
        Position(**{**position.model_dump(), "bundle_id": None})


# -- §7.3 routing ----------------------------------------------------------------------------------


def test_the_minimum_route_is_refused_at_construction():
    with pytest.raises(RoutingError, match="missing"):
        ModelRouter([LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY])
    with pytest.raises(RoutingError, match=r"not §7\.3 route slots"):
        ModelRouter([*_minimum(), LogicalSlot.HYPOTHESIS])


def _minimum() -> list[LogicalSlot]:
    return [LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY, LogicalSlot.EMBEDDING]


def test_roles_route_to_slots_and_the_critic_falls_back_to_primary():
    router = ModelRouter(_minimum())
    assert router.route(CognitiveRole.EVIDENCE_RESEARCHER) is LogicalSlot.FAST_UTILITY
    assert router.route(CognitiveRole.HYPOTHESIS_ENGINE) is LogicalSlot.REASONING_PRIMARY
    assert router.route(CognitiveRole.ADVERSARIAL_CRITIC) is LogicalSlot.REASONING_PRIMARY
    assert not router.critic_route_is_distinct()
    with_adversary = ModelRouter([*_minimum(), LogicalSlot.REASONING_ADVERSARIAL])
    assert (
        with_adversary.route(CognitiveRole.ADVERSARIAL_CRITIC) is LogicalSlot.REASONING_ADVERSARIAL
    )
    assert set(CognitiveRole) >= {
        CognitiveRole.SUPERVISOR,
        CognitiveRole.EVIDENCE_RESEARCHER,
        CognitiveRole.HYPOTHESIS_ENGINE,
        CognitiveRole.ADVERSARIAL_CRITIC,
        CognitiveRole.VERIFICATION_PLANNER,
        CognitiveRole.NOVELTY_AUDITOR,
    }


# -- §7.5 intent-aware SourcePolicy (SRC-002) ------------------------------------------------------


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_diagnosis_and_novelty_use_different_source_policies():
    registry = SourcePolicyRegistry(default_source_policies())
    diagnosis = registry.for_intent("DIAGNOSIS")
    novelty = registry.for_intent("NOVELTY_AUDIT")
    assert diagnosis.policy_id != novelty.policy_id
    assert diagnosis.source_classes[0] is TrustClass.INTERNAL_RUN  # internal matched runs first
    assert TrustClass.INTERNAL_RUN not in novelty.source_classes
    assert novelty.global_novelty_requires == {TrustClass.PEER_REVIEWED, TrustClass.PATENT}
    # Stake thresholds differ too: NORMAL novelty needs inversion, NORMAL diagnosis does not.
    assert novelty.requires_inverted_retrieval("NORMAL")
    assert not diagnosis.requires_inverted_retrieval("NORMAL")
    assert diagnosis.requires_inverted_retrieval("HIGH")
    # The Critic leaves lab history on a diagnosis.
    assert not set(diagnosis.inverted_source_classes) & set(diagnosis.source_classes)


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_an_undeclared_stakes_word_or_intent_is_refused_not_read_as_low():
    registry = SourcePolicyRegistry(default_source_policies())
    with pytest.raises(SourcePolicyError, match="not declared"):
        registry.for_intent("DIAGNOSIS").requires_inverted_retrieval("URGENT-ISH")
    with pytest.raises(SourcePolicyError, match="no source policy"):
        registry.for_intent("VIBES")
    with pytest.raises(SourcePolicyError, match="nowhere for the Critic"):
        IntentSourcePolicy(
            policy_id="srcpol:x",
            version="1.0.0",
            intent="DIAGNOSIS",
            source_classes=(TrustClass.INTERNAL_RUN,),
            inverted_source_classes=(),
        )


# -- the protocol ----------------------------------------------------------------------------------


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_stage_a_positions_each_name_their_own_bundle_and_specialists_see_domain_evidence():
    world = build_world(_case("hard-1"))
    outcome = world.debate.run(world.request(_case("hard-1")))
    stage_a = [p for p in outcome.positions if p.bundle_id != outcome.positions[-1].bundle_id]
    assert len({p.role_id for p in stage_a}) >= 3  # engine + the pack's two specialists
    for position in outcome.positions:
        bundle = world.bundles.get(position.bundle_id)
        recorded = world.provenance.get(position.inference_provenance_id)
        assert bundle is not None and recorded is not None
        assert recorded.evidence_bundle_hash == bundle.canonical_hash, (
            "a position names the bundle its inference was actually produced from"
        )


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_the_critic_inverts_the_retrieval_and_the_inverted_bundle_is_saved_and_traceable():
    case = _case("hard-1")
    world = build_world(case)
    outcome = world.debate.run(world.request(case))
    policy = world.source_policies.for_intent("DIAGNOSIS")
    primary = set(outcome.primary_bundle.ordered_attestation_ids)
    for critique in outcome.critiques:
        assert critique.performed_inverted_retrieval
        inverted = world.bundles.get(critique.inverted_bundle_id)  # saved (SRC-002)
        assert inverted is not None and inverted.bundle_id in {
            b.bundle_id for b in outcome.inverted_bundles
        }
        assert not set(inverted.ordered_attestation_ids) & primary, "inverted excludes the primary"
        for attestation_id in inverted.ordered_attestation_ids:
            item = world.researcher.item(PROJECT, attestation_id)
            assert item is not None and item.trust_class in policy.inverted_source_classes
        assert critique.differs_in and "RETRIEVAL_BUNDLE" in critique.differs_in
    # Divergence is measurable and recorded per round and for the debate.
    assert outcome.record.critic_bundle_divergence is not None
    assert [r["inverted_bundle_id"] for r in outcome.record.per_round] == [
        c.inverted_bundle_id for c in outcome.critiques
    ]


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_the_inverted_retrieval_never_returns_what_the_positions_already_saw():
    """MECHANISM_DISCOVERY's inverted classes overlap its primary ones (literature both ways), so
    only the exclusion keeps the Critic from re-reading the positions' own evidence as 'new'."""
    case = _case("hard-1")
    world = build_world(case)
    outcome = world.debate.run(world.request(case, intent="MECHANISM_DISCOVERY"))
    policy = world.source_policies.for_intent("MECHANISM_DISCOVERY")
    primary = set(outcome.primary_bundle.ordered_attestation_ids)
    reachable = {
        a
        for a in primary
        if (item := world.researcher.item(PROJECT, a)) is not None
        and item.trust_class in policy.inverted_source_classes
    }
    assert reachable, "non-vacuous: without the exclusion these would be retrieved again"
    assert outcome.inverted_bundles
    for bundle in outcome.inverted_bundles:
        assert not set(bundle.ordered_attestation_ids) & primary
    assert outcome.record.critic_bundle_divergence == 0, "nothing new is 0, never inflated"


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_critique_that_changes_no_bundle_policy_or_route_is_refused_as_not_independent():
    """§7.6: re-running the same inference is not a critique. No adversarial slot, no inversion."""
    case = _case("hard-1")
    world = build_world(
        case,
        adversarial_slot=False,
        policy=DebatePolicy(perform_inverted_retrieval=False, specialists_enabled=False),
    )
    with pytest.raises(LLMRefusal, match="CRITIQUE_ROUTE_UNCHANGED"):
        world.debate.run(world.request(case))


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_with_no_distinct_critic_route_independence_comes_from_the_evidence_path():
    case = _case("hard-1")
    world = build_world(case, adversarial_slot=False)
    outcome = world.debate.run(world.request(case))
    assert all(c.differs_in == ("RETRIEVAL_BUNDLE",) for c in outcome.critiques)


def test_a_critic_citing_evidence_it_was_not_shown_is_refused_and_its_inference_still_recorded():
    fx = load_fixture()
    liar = MockScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space=fx["outcome_space"],
        invent_citation=True,
    )
    world = build_world(_case("hard-1"), scientist=liar)
    with pytest.raises(RoleOutputRefused) as refused:
        world.debate.run(world.request(_case("hard-1")))
    assert "att:never-shown" in refused.value.detail
    assert refused.value.inference_id is not None
    assert world.provenance.get(refused.value.inference_id) is not None, (
        "a refused output is still a durable inference"
    )
    assert world.debates.critiques_targeting(PROJECT, "hyp:t-hypothesis-0001") == ()


@pytest.mark.requirement("LLM-002")
@pytest.mark.spec_test("T-LLM-002")
def test_rounds_are_earned_by_triggers_and_bounded_by_the_policy():
    easy = _case("easy-1")
    world = build_world(easy)
    simple = world.debate.run(world.request(easy))
    assert (
        simple.record.rounds == 1 and simple.record.stop_reason == StopReason.NO_ESCALATION_TRIGGER
    )

    hard = _case("hard-1")
    world = build_world(hard)
    contested = world.debate.run(world.request(hard))
    assert contested.record.rounds == 2
    assert Trigger.MAY_REJECT in contested.record.escalation_triggers
    assert Trigger.BUNDLES_MATERIALLY_CONFLICT in contested.record.escalation_triggers

    world = build_world(hard, policy=DebatePolicy(max_rounds=1))
    capped = world.debate.run(world.request(hard))
    assert capped.record.rounds == 1 and capped.record.stop_reason == StopReason.MAX_ROUNDS

    world = build_world(easy)
    asked = world.debate.run(world.request(easy, human_requested_rounds=3))
    assert asked.record.rounds == 3 and Trigger.HUMAN_REQUEST in asked.record.escalation_triggers


@pytest.mark.requirement("LLM-002")
@pytest.mark.spec_test("T-LLM-002")
def test_every_section_15_4_metric_is_recorded_with_its_version():
    case = _case("hard-1")
    world = build_world(case)
    record = world.debate.run(world.request(case)).record
    assert record.position_diversity is not None
    assert record.critic_bundle_divergence is not None
    assert record.critic_changed_final_set is True
    assert record.additional_evidence_items > 0 and record.additional_token_count > 0
    assert set(record.metric_versions) == {
        POSITION_DIVERSITY,
        SURVIVING_DIVERSITY,
        CRITIC_BUNDLE_DIVERGENCE,
        ADDITIONAL_EVIDENCE_COST,
    }
    assert record.gate_evaluations[-1]["round"] == "debate"
    assert world.debates.get_debate_record(record.debate_id) == record


def test_the_budget_gate_stops_a_debate_before_the_model_is_reached():
    """COST-001 carried into M3: a blocked call never reaches the model, and the record says so."""
    case = _case("hard-1")
    world = build_world(case)
    outcome = world.debate.run(world.request(case, tokens=1500))
    assert outcome.record.stop_reason == StopReason.BUDGET_BLOCKED
    assert len(world.scientist.prompts_seen) == len(outcome.calls)
    for call in outcome.calls:
        assert world.provenance.get(call.inference.inference_id) is not None

    world = build_world(case)
    with pytest.raises(InferenceBudgetBlocked):
        world.debate.run(world.request(case, tokens=100))
    assert world.scientist.prompts_seen == []


def test_stage_c_ranks_verification_over_every_active_rival_including_challenged_ones():
    case = _case("hard-1")
    world = build_world(case)
    outcome = world.debate.run(world.request(case))
    assert outcome.contradicted_ids, "the fixture's hard case has contradicted rivals"
    top = outcome.ranking[0]
    assert top.capability_id == "cap:sp.charge_ac_sweep" and top.disagreement is not None
    ranked_hypotheses = {h for h, _ in top.predictions}
    assert set(outcome.contradicted_ids) <= ranked_hypotheses
    assert set(outcome.surviving_ids) <= ranked_hypotheses


def test_the_supervisors_research_contract_is_the_debates_input():
    """§7.4 Supervisor/PI -> ResearchContract. Its question, intent, owner and budget carry over."""
    from lab_brain.cognition.debate import DebateRequest
    from lab_brain.core.models.debate import ResearchContract
    from lab_brain.core.models.enums import SensitivityLabel
    from tests.debate_fixtures import ADMISSION_POLICY, EPISODE, TRACE, budget_policy

    case = _case("hard-1")
    contract = ResearchContract(
        contract_id="rct:rs",
        project_id=PROJECT,
        question=case["question"],
        intent="DIAGNOSIS",
        success_criteria=("a verification action that separates the surviving mechanisms",),
        privacy_mode="RESEARCH",
        budget_id="bp:m3",
        stop_conditions=("no escalation trigger fires",),
        actor_id="act:pi",
    )
    common = {
        "episode_id": EPISODE,
        "trace_id": TRACE,
        "stakes": "HIGH",
        "domain": "silicon_photonics",
        "admission_policy": ADMISSION_POLICY,
        "question_label": SensitivityLabel.INTERNAL,
    }
    request = DebateRequest.from_contract(contract, budget_policy=budget_policy(), **common)
    assert (request.question, request.intent, request.actor_id) == (
        contract.question,
        "DIAGNOSIS",
        "act:pi",
    )
    world = build_world(case)
    outcome = world.debate.run(request)
    assert outcome.hypothesis_set.question == contract.question
    assert outcome.hypothesis_set.source_policy_id == "srcpol:diagnosis"

    other = budget_policy().__class__(
        policy_id="bp:elsewhere",
        policy_version="1.0.0",
        project_id=PROJECT,
        caps=budget_policy().caps,
    )
    with pytest.raises(ValueError, match="not a parameter a caller may swap"):
        DebateRequest.from_contract(contract, budget_policy=other, **common)
    with pytest.raises(ValidationError, match="blank question"):
        ResearchContract(**{**contract.model_dump(), "question": " "})
