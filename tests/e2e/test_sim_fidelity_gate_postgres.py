"""T-SIM-002 — a coarse contradiction CHALLENGES and may not REJECT (§8.2.1, §10.5, §10.6).

    SIM-002    coarse/low-fidelity contradiction 只能標記 CHALLENGED；要 REJECT hypothesis 必須過
               standard/validation fidelity gate。
    T-SIM-002  low-fidelity contradiction 只使 hypothesis → CHALLENGED，不得直接 → REJECTED。

`REJECTED` IS `CONTRADICTED` HERE. §8.2.1's prose says "SUPPORTED/REJECTED" and §8.2's diagram --
the normative one -- has CONTRADICTED as the negative terminal; SPEC-ISSUE-010 ruled on it, and
`BeliefState` has no REJECTED member. The test asserts the state §8.2 declares.

NO CORE FILE CHANGED TO MAKE THIS WORK, WHICH IS THE ARCHITECTURAL CLAIM. SIM-002 is an authority
question: "how much weight does a fidelity level carry" is §10.5's DomainPack column. So the
requirement is discharged by two registered §8.2.1 policy records and one comparator, and the
transition is still authorised by the single operator §8.2.1 declares. `TransitionPolicy.evaluate`
is untouched M0b code, hard-locked, and it is what refuses.

WHY THE COARSE CASE IS A *DENY* AND NOT A SILENT NO-OP. `evaluate` returns
DENY/AUTHORITY_INSUFFICIENT with the required rule in `required_authority_gap`, so a planner reading
the decision learns what would be needed rather than merely that nothing happened.

RUN THROUGH POSTGRESQL because the policies have to be durable: §8.2.1 records which policy version
authorised a transition, `005b` is where a version lives, and a fidelity gate that existed only in
memory would be one a replay could not re-derive.
"""

from __future__ import annotations

import pytest

from lab_brain.core.authority import AuthorityPolicyRegistry
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.condition import ConditionMatch, ConditionSchemaRef
from lab_brain.core.models.enums import AuthorityComparison, ConditionMatchState, RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    TransitionOutcome,
    TransitionReason,
)
from lab_brain.core.repositories.belief_events import SqlTransitionPolicyStore
from lab_brain.domains.silicon_photonics.authority_policy import (
    CHALLENGE_POLICY_ID,
    MEAS_CALIBRATED,
    REJECT_POLICY_ID,
    SIM_COARSE,
    SIM_STANDARD,
    SIM_VALIDATION,
    SiliconPhotonicsAuthorityPolicy,
    transition_policies,
)

pytestmark = [
    pytest.mark.requirement("SIM-002"),
    pytest.mark.spec_test("T-SIM-002"),
    pytest.mark.postgres,
]

PROJECT = "prj:sp"
HYPOTHESIS = "hyp:rs-anomaly"
AUTHORITY = SiliconPhotonicsAuthorityPolicy()


def _policies():
    return {policy.policy_id: policy for policy in transition_policies()}


def _exact_conditions() -> ConditionMatch:
    """Conditions out of the way, so the tests below are about AUTHORITY and nothing else.

    §8.2.1's `evaluate` checks conditions before authority, so a PARTIAL match here would produce
    the right verdict for the wrong reason -- which is the shape of test that keeps passing after
    the rule it was written for is removed.
    """
    return ConditionMatch(
        state=ConditionMatchState.EXACT,
        schema_ref=ConditionSchemaRef(
            domain="silicon_photonics", schema_id="pn_junction_ac", version="1.0.0"
        ),
        tolerance_policy_version="1.0.0",
    )


def _contradiction() -> tuple[RelationJudgment, ...]:
    """The admitted CONTRADICTS relation both policies require.

    It names a supporting attestation because §17.8 refuses an epistemic relation with no
    provenance -- support and contradiction are the system's load-bearing claims, and one nobody
    can trace is exactly what SYS-001 exists to prevent.
    """
    return (
        RelationJudgment(
            relation_id="rel:1",
            project_id=PROJECT,
            from_entity_id="obs:1",
            to_entity_id=HYPOTHESIS,
            relation_type=RelationType.CONTRADICTS,
            supporting_attestation_ids=("att:1",),
        ),
    )


def _view(*classes: str) -> HypothesisView:
    return HypothesisView(
        hypothesis_id=HYPOTHESIS,
        project_id=PROJECT,
        current_state=BeliefState.ACTIVE,
        admitted_authority_classes=classes,
    )


def _evaluate(policy_id: str, *classes: str, independent: int = 1):
    policy = _policies()[policy_id]
    return policy.evaluate(
        _view(*classes),
        _contradiction(),
        AUTHORITY,
        (_exact_conditions(),),
        IndependenceSummary(independent_count=independent),
        policy.candidate_to_state,
    )


# ---------------------------------------------------------------------------
# THE requirement
# ---------------------------------------------------------------------------


def test_a_coarse_contradiction_cannot_reject_the_hypothesis():
    """THE clause. DENY, with the gate it failed named in the decision."""
    decision = _evaluate(REJECT_POLICY_ID, SIM_COARSE)
    assert decision.outcome is TransitionOutcome.DENY
    assert decision.reason_code is TransitionReason.AUTHORITY_INSUFFICIENT
    assert decision.required_authority_gap == SIM_STANDARD
    assert not decision.permits_transition


def test_the_same_coarse_contradiction_does_challenge_the_hypothesis():
    """The other half of SIM-002, and it matters: a coarse result is not worthless.

    Without this, "refuse everything coarse" would satisfy the test above while discarding the
    signal the requirement says a low-fidelity contradiction DOES carry.
    """
    decision = _evaluate(CHALLENGE_POLICY_ID, SIM_COARSE)
    assert decision.outcome is TransitionOutcome.ALLOW
    assert _policies()[CHALLENGE_POLICY_ID].candidate_to_state is BeliefState.CHALLENGED


@pytest.mark.parametrize("fidelity", [SIM_STANDARD, SIM_VALIDATION])
def test_a_standard_or_validation_fidelity_contradiction_may_reject(fidelity: str):
    """The positive control for the gate: passing it is what rejection requires."""
    decision = _evaluate(REJECT_POLICY_ID, fidelity)
    assert decision.outcome is TransitionOutcome.ALLOW
    assert _policies()[REJECT_POLICY_ID].candidate_to_state is BeliefState.CONTRADICTED


def test_a_non_converged_run_is_coarse_whatever_the_backend_declared():
    """The lie the gate would otherwise be walked through.

    A provider adapter that stamped SIM_VALIDATION on a run that hit its iteration cap would reject
    a hypothesis on a result that did not converge. The declared class is a ceiling;
    `fidelity_for` decides what is actually reached, from the validity record.
    """
    from lab_brain.domains.silicon_photonics import backend_validity

    claimed = SIM_VALIDATION
    not_converged = {"convergence_status": backend_validity.NOT_CONVERGED}
    effective = backend_validity.fidelity_for(not_converged, claimed)
    assert effective == SIM_COARSE

    assert _evaluate(REJECT_POLICY_ID, effective).outcome is TransitionOutcome.DENY
    assert _evaluate(REJECT_POLICY_ID, claimed).outcome is TransitionOutcome.ALLOW


def test_rejection_also_requires_corroboration_a_single_run_cannot_supply():
    """The least recoverable move in §8.2 is gated twice, and the second gate is EVI-004's."""
    decision = _evaluate(REJECT_POLICY_ID, SIM_STANDARD, independent=0)
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert decision.reason_code is TransitionReason.INSUFFICIENT_INDEPENDENT_ATTESTATIONS


# ---------------------------------------------------------------------------
# §10.6 — simulated and measured do not rank
# ---------------------------------------------------------------------------


def test_a_measurement_does_not_automatically_outrank_a_simulation():
    """§10.5: "measurement 永遠最高" is not an assumption core makes, or this pack.

    A comparator that returned STRONGER here would encode the rule §10.5 names as forbidden, one
    layer out from core -- and §10.6's SIM_TO_REAL_CONFLICT would then never arise, because the
    disagreement would have been resolved by fiat.
    """
    assert AUTHORITY.compare(MEAS_CALIBRATED, SIM_VALIDATION) is AuthorityComparison.INCOMPARABLE
    assert AUTHORITY.compare(SIM_VALIDATION, MEAS_CALIBRATED) is AuthorityComparison.INCOMPARABLE


def test_an_incomparable_authority_escalates_rather_than_deciding():
    """EPI-004: INCOMPARABLE at a required gate is NEED_HUMAN_REVIEW with a ReviewItem spec."""
    decision = _evaluate(REJECT_POLICY_ID, MEAS_CALIBRATED)
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE
    assert decision.review_item_spec is not None
    assert decision.review_item_spec.subject_type == "AUTHORITY_CONFLICT"


def test_the_ranking_is_a_valid_partial_order_and_registration_is_what_checks_it():
    """§10.5.1's laws, verified by core over classes core does not know.

    Asserted through `register` rather than by re-implementing the laws here: a pack whose ranking
    is not an order must be *unable to install*, which is stronger than a test that notices.
    """
    registry = AuthorityPolicyRegistry()
    registry.register(AUTHORITY)
    assert registry.registered() == (("auth:silicon_photonics", "1.0.0"),)


def test_a_broken_ranking_cannot_be_registered():
    """Non-vacuity for the check above."""
    from lab_brain.core.authority import AuthorityConformanceError

    class Cyclic:
        policy_id = "auth:broken"
        policy_version = "1.0.0"
        authority_classes = ("A", "B", "C")

        def compare(self, a: str, b: str) -> AuthorityComparison:
            if a == b:
                return AuthorityComparison.EQUIVALENT
            order = {("A", "B"), ("B", "C"), ("C", "A")}
            if (a, b) in order:
                return AuthorityComparison.STRONGER
            return AuthorityComparison.WEAKER

        def meets(self, required_rule: str, candidate: str) -> bool:
            return self.compare(candidate, required_rule) in (
                AuthorityComparison.STRONGER,
                AuthorityComparison.EQUIVALENT,
            )

    with pytest.raises(AuthorityConformanceError, match="transitivity"):
        AuthorityPolicyRegistry().register(Cyclic())


# ---------------------------------------------------------------------------
# Durability — the gate has to survive a reload (§8.2.1, `005b`)
# ---------------------------------------------------------------------------


def test_the_fidelity_policies_are_durable_and_reload_identically(db):
    """A gate that existed only in memory is one a replay could not re-derive.

    §8.2.1 records which policy VERSION authorised a transition, so the record has to be in the
    store the event will point at -- and it has to come back equal, or the re-derivation §17.14.1
    requires would compare against something else.
    """
    store = SqlTransitionPolicyStore(db)
    for policy in transition_policies():
        store.register(policy)

    for policy in transition_policies():
        reloaded = store.get(policy.policy_id, policy.version)
        assert reloaded == policy, f"{policy.policy_id} did not reload equal"
        assert reloaded is not None and reloaded.domain == "silicon_photonics"


def test_the_two_policies_govern_different_transitions_and_neither_governs_the_other(db):
    """A policy asked about a transition it does not govern DENYs with TRANSITION_NOT_GOVERNED.

    So the challenge policy cannot be used to reject, which is the substitution SIM-002 would be
    defeated by: same inputs, the permissive policy, the terminal state.
    """
    challenge = _policies()[CHALLENGE_POLICY_ID]
    decision = challenge.evaluate(
        _view(SIM_COARSE),
        _contradiction(),
        AUTHORITY,
        (_exact_conditions(),),
        IndependenceSummary(independent_count=1),
        BeliefState.CONTRADICTED,
    )
    assert decision.outcome is TransitionOutcome.DENY
    assert decision.reason_code is TransitionReason.TRANSITION_NOT_GOVERNED
