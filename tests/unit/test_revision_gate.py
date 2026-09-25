"""M3's preconditions on a belief transition of a certified hypothesis, over real debate output.

Every case starts from a debate the Hypothesis Brain actually ran (in memory) -- the critiques,
inverted bundles and debate record the gate reads are the ones the protocol wrote, not objects the
test assembled -- and then asks the gate about one candidate transition. The PostgreSQL e2e runs
the same questions through `HypothesisBrain.attempt_revision` and the `011i` trigger.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from lab_brain.cognition.debate import DebatePolicy
from lab_brain.cognition.debate_metrics import CRITIC_BUNDLE_DIVERGENCE
from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.benchmark import BenchmarkPolicy, MetricDirection
from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.revision_gate import RevisionPrecondition, RevisionPreconditionFailed
from lab_brain.domains.silicon_photonics.plugin import DEBATE_BENCHMARK_ID
from tests.debate_fixtures import (
    ADMISSION_POLICY,
    DOMAIN,
    PROJECT,
    T0,
    TRACE,
    build_world,
    load_fixture,
    make_certificate,
    make_set,
)

LATER = T0 + dt.timedelta(days=1)


def _case(case_id: str):  # type: ignore[no-untyped-def]
    return next(c for c in load_fixture()["cases"] if c["case_id"] == case_id)


def _debated(case_id: str = "hard-1", policy: DebatePolicy | None = None):  # type: ignore[no-untyped-def]
    case = _case(case_id)
    world = build_world(case, policy=policy)
    return world, world.debate.run(world.request(case))


def _factual(world, outcome):  # type: ignore[no-untyped-def]
    """An attestation the Critic's inverted retrieval found -- external evidence, not opinion."""
    found = outcome.inverted_bundles[0].ordered_attestation_ids[0]
    attestation = world.attestations[found]
    assert attestation.epistemic_type is not EpistemicType.INFERRED
    return attestation


def _inferred(world):  # type: ignore[no-untyped-def]
    any_id = sorted(world.attestations)[0]
    return world.attestations[any_id].model_copy(update={"epistemic_type": EpistemicType.INFERRED})


def _truth_and_rejected(world, outcome):  # type: ignore[no-untyped-def]
    truth_mechanism = load_fixture()["mechanisms"]["dopant_compensation"]["mechanism"]
    by_mechanism = {c.hypothesis.mechanism: c.hypothesis_id for c in outcome.certificates}
    truth = by_mechanism[truth_mechanism]
    rejected = outcome.contradicted_ids[0]
    return truth, rejected


# -- SRC-002 -----------------------------------------------------------------------------------


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_reject_backed_by_the_inverted_critique_and_external_evidence_may_proceed():
    world, outcome = _debated()
    _, rejected = _truth_and_rejected(world, outcome)
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=rejected,
        to_state=BeliefState.CONTRADICTED,
        triggering_attestations=[_factual(world, outcome)],
        at=LATER,
    )
    assert verdict.governs and verdict.permitted, verdict.refusals


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_reject_adjudicated_only_by_model_opinion_is_refused():
    """§7.6: adjudication MUST cite external evidence or a verification result."""
    world, outcome = _debated()
    _, rejected = _truth_and_rejected(world, outcome)
    for basis in ([], [_inferred(world)]):
        verdict = world.revision_gate.evaluate(
            project_id=PROJECT,
            hypothesis_id=rejected,
            to_state=BeliefState.CONTRADICTED,
            triggering_attestations=basis,
            at=LATER,
        )
        assert verdict.codes == {RevisionPrecondition.ADJUDICATED_BY_MODEL_OPINION}


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_reject_with_no_critique_at_all_is_refused():
    """The baseline condition: no Critic ran, so no REJECT has an independent critique path."""
    world, outcome = _debated(policy=DebatePolicy(critic_enabled=False))
    target = outcome.certificates[0].hypothesis_id
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=target,
        to_state=BeliefState.CONTRADICTED,
        triggering_attestations=[world.attestations[sorted(world.attestations)[0]]],
        at=LATER,
    )
    assert RevisionPrecondition.NO_INDEPENDENT_CRITIQUE in verdict.codes
    assert RevisionPrecondition.NO_INVERTED_RETRIEVAL in verdict.codes


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_high_stakes_decision_without_inverted_retrieval_may_not_enter_belief_revision():
    """§7.2 / SRC-002: stakes >= the policy threshold and the Critic did not invert -> refused.

    The ablation: the Critic ran and critiqued, but without its own retrieval. Every transition --
    promotion as well as rejection -- is refused, because the set's policy required the inversion.
    """
    world, outcome = _debated(policy=DebatePolicy(perform_inverted_retrieval=False))
    assert outcome.hypothesis_set.inverted_retrieval_required
    assert outcome.critiques and all(c.inverted_bundle_id is None for c in outcome.critiques)
    for certificate in outcome.certificates:
        for to_state in (BeliefState.SUPPORTED, BeliefState.CONTRADICTED):
            verdict = world.revision_gate.evaluate(
                project_id=PROJECT,
                hypothesis_id=certificate.hypothesis_id,
                to_state=to_state,
                triggering_attestations=[world.attestations[sorted(world.attestations)[0]]],
                at=LATER,
            )
            assert RevisionPrecondition.NO_INVERTED_RETRIEVAL in verdict.codes


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_below_the_policy_threshold_inverted_retrieval_is_not_required():
    """Stake-adaptive: a LOW-stakes diagnosis is below `srcpol:diagnosis`'s HIGH threshold."""
    case = _case("hard-1")
    world = build_world(case, policy=DebatePolicy(perform_inverted_retrieval=False))
    outcome = world.debate.run(world.request(case, stakes="LOW"))
    assert not outcome.hypothesis_set.inverted_retrieval_required
    truth, _ = _truth_and_rejected(world, outcome) if outcome.contradicted_ids else (None, None)
    target = truth or outcome.certificates[0].hypothesis_id
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=target,
        to_state=BeliefState.SUPPORTED,
        triggering_attestations=[],
        at=LATER,
    )
    assert verdict.permitted, verdict.refusals


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_critique_written_after_the_decision_does_not_count():
    world, outcome = _debated()
    _, rejected = _truth_and_rejected(world, outcome)
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=rejected,
        to_state=BeliefState.CONTRADICTED,
        triggering_attestations=[_factual(world, outcome)],
        at=T0,  # before the debate: its critiques did not exist yet
    )
    assert RevisionPrecondition.NO_INDEPENDENT_CRITIQUE in verdict.codes


# -- EPI-001 -----------------------------------------------------------------------------------


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_a_single_admitted_cause_cannot_be_promoted_even_when_written_around_the_service():
    """The adversarial writer: one certificate stored and admitted by hand, bypassing the set gate.

    `HypothesisAdmissionService` would never admit a set of one. A writer that went around it --
    storing a certificate and appending a genesis event itself -- produces exactly the state EPI-001
    forbids, and the promotion gate still refuses it.
    """
    world = build_world()
    hs = make_set(set_id="hst:lonely", inverted_retrieval_required=False)
    lonely = make_certificate("contact_discontinuity", hs)
    world.hypotheses.add_set(hs)
    world.hypotheses.add_certificate(lonely)
    world.events.append(
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
            triggering_attestations=[world.attestations[sorted(world.attestations)[0]]],
        )
    )
    with pytest.raises(RevisionPreconditionFailed) as refused:
        world.revision_gate.require(
            project_id=PROJECT,
            hypothesis_id=lonely.hypothesis_id,
            to_state=BeliefState.SUPPORTED,
            triggering_attestations=[world.attestations[sorted(world.attestations)[0]]],
            at=LATER,
        )
    assert refused.value.verdict.codes == {RevisionPrecondition.SINGLE_PLAUSIBLE_CAUSE}


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_a_non_root_cause_set_may_promote_its_only_member():
    """EPI-001 is about ROOT CAUSES; a single supported design hypothesis is not one."""
    world = build_world()
    hs = make_set(set_id="hst:design", root_cause=False, inverted_retrieval_required=False)
    only = make_certificate("contact_discontinuity", hs)
    world.hypotheses.add_set(hs)
    world.hypotheses.add_certificate(only)
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=only.hypothesis_id,
        to_state=BeliefState.SUPPORTED,
        triggering_attestations=[],
        at=LATER,
    )
    assert verdict.permitted


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_the_debated_root_cause_may_be_promoted_on_external_evidence():
    world, outcome = _debated()
    truth, _ = _truth_and_rejected(world, outcome)
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=truth,
        to_state=BeliefState.SUPPORTED,
        triggering_attestations=[_factual(world, outcome)],
        at=LATER,
    )
    assert verdict.permitted, verdict.refusals
    # Advisory: no calibrated policy is active, so the divergence was measured, not enforced.
    assert [v.enforced for v in verdict.gate_verdicts] == [False]


def test_a_hypothesis_without_a_certificate_is_outside_the_gate():
    """M0b's hard-locked semantics are not reached into: the gate reports that it does not govern."""
    world = build_world()
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id="hyp:m0b-era",
        to_state=BeliefState.SUPPORTED,
        triggering_attestations=[],
        at=LATER,
    )
    assert not verdict.governs and verdict.permitted


# -- LLM-002 -----------------------------------------------------------------------------------


def _armed(world, threshold: str) -> BenchmarkPolicy:  # type: ignore[no-untyped-def]
    policy = BenchmarkPolicy(
        policy_id="bp:test.divergence",
        domain=DOMAIN,
        benchmark_set_id=DEBATE_BENCHMARK_ID,
        metric_key=CRITIC_BUNDLE_DIVERGENCE,
        threshold=Decimal(threshold),
        direction=MetricDirection.AT_LEAST,
        calibrated_at=T0,
        sample_size=10,
        calibration_artifact_refs=("benchmark-run:test#sha256:0",),
        version="1.0.0",
    )
    world.benchmarks.add_policy(policy)
    return world.benchmarks.activate(policy.policy_id, policy.version)


@pytest.mark.requirement("LLM-002")
@pytest.mark.spec_test("T-LLM-002")
def test_an_armed_divergence_gate_refuses_a_debate_below_its_calibrated_threshold():
    world, outcome = _debated()
    truth, _ = _truth_and_rejected(world, outcome)
    assert outcome.record.critic_bundle_divergence == Decimal("0.5000")
    _armed(world, "0.6")
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=truth,
        to_state=BeliefState.SUPPORTED,
        triggering_attestations=[_factual(world, outcome)],
        at=LATER,
    )
    assert verdict.codes == {RevisionPrecondition.CRITIQUE_BELOW_CALIBRATED_DIVERGENCE}
    assert verdict.gate_verdicts[0].policy_ref == "bp:test.divergence@1.0.0"


@pytest.mark.requirement("LLM-002")
@pytest.mark.spec_test("T-LLM-002")
def test_an_armed_divergence_gate_passes_a_debate_that_meets_it():
    world, outcome = _debated()
    truth, _ = _truth_and_rejected(world, outcome)
    _armed(world, "0.3333")
    verdict = world.revision_gate.evaluate(
        project_id=PROJECT,
        hypothesis_id=truth,
        to_state=BeliefState.SUPPORTED,
        triggering_attestations=[_factual(world, outcome)],
        at=LATER,
    )
    assert verdict.permitted
    assert verdict.gate_verdicts[0].enforced and verdict.gate_verdicts[0].passed
