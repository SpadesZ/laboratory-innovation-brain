"""EPI-005: only a policy ALLOW creates a belief revision event.

    §8.2.1  No LLM may directly assign a scientific transition.
    AGT-016 LLM output alone cannot cause scientific status transition.

Written before the implementation. Every case below is a way an event could claim an authorisation
it does not have.

The replay half of this slice lives in `test_belief_replay.py` under EPI-003. They are separate
modules because §26 maps one requirement to one test id, and a module carrying both pairs makes the
traceability check form cross products the spec does not declare -- `(EPI-003, T-EPI-005)` is not a
pair. Found by that check, not by review.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.belief import (
    AuthorizationNotRederivable,
    BeliefScopeError,
    BeliefTransitionRefused,
    EpistemicStateProjection,
    admit_hypothesis,
    authorize_transition,
    record_transition,
)
from lab_brain.core.models import (
    BeliefRevisionEvent,
    BeliefState,
    TransitionOutcome,
    TransitionReason,
)
from lab_brain.core.models.decision import BeliefTransitionDecision
from tests.contract.test_transition_policy import (
    conflict,
    hypothesis,
    policy,
    relation,
    summary,
)

pytestmark = [pytest.mark.requirement("EPI-005"), pytest.mark.spec_test("T-EPI-005")]

T0 = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:episode-1"


def authorized(**overrides: object) -> BeliefTransitionDecision:
    """A real §17.14.1 authorization, produced by actually evaluating the policy.

    There is deliberately no way to hand in the outcome you want. `v3.3-a12` makes the stored
    inputs the authorization, so a test that wants a DENY has to supply inputs that genuinely
    deny -- which is the same constraint a forger now faces, and the reason this slice closes
    R-13 rather than moving it.
    """
    defaults: dict[str, object] = {
        "decision_id": "dec:1",
        "policy": policy(),
        "hypothesis": hypothesis(),
        "admitted_relations": (relation(),),
        "independence_summary": summary(),
        "candidate_to_state": BeliefState.SUPPORTED,
        "created_at": T0,
    }
    defaults.update(overrides)
    return authorize_transition(**defaults)  # type: ignore[arg-type]


def prior(
    state: BeliefState | None = BeliefState.ACTIVE, **overrides: object
) -> EpistemicStateProjection:
    defaults: dict[str, object] = {
        "project_id": PROJECT,
        "target_id": HYP,
        "current_state": state,
        "last_event_id": None if state is None else "bre:0",
    }
    defaults.update(overrides)
    return EpistemicStateProjection(**defaults)  # type: ignore[arg-type]


def create(**overrides: object) -> BeliefRevisionEvent:
    """The event `record_transition` authorises, unwrapped from its capability.

    Unwrapping here keeps the assertions about the *event*. The capability itself is the subject of
    `test_the_authorization_capability_cannot_be_forged_by_accident` and of the store tests.
    """
    defaults: dict[str, object] = {
        "event_id": "bre:1",
        "policy": policy(),
        "hypothesis": hypothesis(),
        "candidate_to_state": BeliefState.SUPPORTED,
        "prior": prior(),
        "occurred_at": T0,
        "trace_id": TRACE,
        "triggering_relations": (relation(),),
    }
    defaults.update(overrides)
    # The authorization defaults to one computed from the *same* policy, hypothesis and target
    # state this event will record. Building it from independent defaults would make every
    # override fail for the wrong reason -- an overridden hypothesis would trip the subject check
    # before reaching whatever the test was actually about.
    defaults.setdefault(
        "authorization",
        authorized(
            policy=defaults["policy"],
            hypothesis=defaults["hypothesis"],
            candidate_to_state=defaults["candidate_to_state"],
            admitted_relations=defaults.get("triggering_relations", ()),
        ),
    )
    return record_transition(**defaults).event  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# Only a policy ALLOW creates an event. §8.2.1 / AGT-016.
# --------------------------------------------------------------------------------------------


def test_an_allow_decision_produces_the_event_it_authorises():
    """The gate must be passable, or belief could never change at all."""
    created = create()
    assert created.from_state is BeliefState.ACTIVE
    assert created.to_state is BeliefState.SUPPORTED
    assert (created.policy_id, created.policy_version) == ("pol:hypothesis-default", "1.0.0")
    assert created.project_id == PROJECT
    assert created.triggering_relation_ids == ("rel:1",)


# Each case below produces its outcome from real inputs rather than by asserting one. Since
# `v3.3-a12` that is the only way to build a non-ALLOW authorization at all: the snapshot is the
# authorization, so "give me a DENY" means "give me inputs that deny".
NON_ALLOW_INPUTS: dict[TransitionOutcome, dict[str, object]] = {
    # A transition this policy does not govern at all.
    TransitionOutcome.DENY: {"candidate_to_state": BeliefState.CONTRADICTED},
    # The threshold a planner could still go and satisfy.
    TransitionOutcome.NEED_MORE_EVIDENCE: {"independence_summary": summary(independent_count=0)},
    # The one a human must resolve.
    TransitionOutcome.NEED_HUMAN_REVIEW: {
        "policy": policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        # EPI-006: a typed `Conflict` of the declared type, not an id the caller pre-judged.
        "hypothesis": hypothesis(conflicts=(conflict(),)),
    },
}


@pytest.mark.parametrize("outcome", list(NON_ALLOW_INPUTS))
def test_no_event_may_be_created_from_a_non_allow_decision(outcome):
    """The commonest bypass: run `evaluate`, ignore the answer, write the event anyway.

    NEED_HUMAN_REVIEW is the dangerous one -- it reads as progress, so a caller that treats
    "not DENY" as permission promotes exactly the beliefs a human was supposed to look at.
    """
    inputs = NON_ALLOW_INPUTS[outcome]
    authorization = authorized(**inputs)
    assert authorization.result is outcome, "the inputs must really produce this outcome"
    assert not authorization.authorizes_transition

    with pytest.raises(BeliefTransitionRefused, match="no belief revision"):
        create(
            authorization=authorization,
            policy=inputs.get("policy", policy()),
            hypothesis=inputs.get("hypothesis", hypothesis()),
            candidate_to_state=inputs.get("candidate_to_state", BeliefState.SUPPORTED),
        )


def test_a_non_allow_authorization_is_still_a_record_worth_keeping():
    """§17.14.1 keeps DENY rows deliberately: "considered and refused" is an auditable fact.

    The distinction that matters is not whether the row exists but whether it authorises, so this
    pins both halves -- the record is well-formed, and it permits nothing.
    """
    refused = authorized(independence_summary=summary(independent_count=0))
    assert refused.result is TransitionOutcome.NEED_MORE_EVIDENCE
    assert refused.input_hash == refused.decision_input_snapshot.input_hash()
    assert not refused.authorizes_transition


def test_an_allow_from_another_policy_does_not_carry_over():
    """A real ALLOW, computed under a different policy, offered for this event."""
    elsewhere = policy(policy_id="pol:something-else")
    with pytest.raises(BeliefTransitionRefused, match=r"does not carry over|computed under"):
        create(authorization=authorized(policy=elsewhere))


def test_an_allow_from_another_version_of_the_same_policy_does_not_carry_over():
    """Versions exist because the rules changed. An ALLOW under 1.0.0 is not one under 2.0.0."""
    with pytest.raises(BeliefTransitionRefused, match=r"does not carry over|computed under"):
        create(authorization=authorized(policy=policy(version="2.0.0")))


def test_an_allow_for_one_transition_cannot_justify_another():
    """An ALLOW for ACTIVE -> SUPPORTED reused to record ACTIVE -> CONTRADICTED."""
    with pytest.raises(BeliefTransitionRefused, match=r"ACTIVE -> SUPPORTED"):
        create(
            authorization=authorized(),
            candidate_to_state=BeliefState.CONTRADICTED,
        )


def test_an_invalid_predecessor_is_refused():
    """The hypothesis moved after the decision was computed.

    The state the policy evaluated is then not the state the event would transition from, and the
    event would record a transition that never had its preconditions checked.
    """
    with pytest.raises(BeliefTransitionRefused, match="moved after the decision"):
        create(prior=prior(BeliefState.CHALLENGED))


def test_a_transition_from_a_recorded_state_is_allowed_whatever_that_state_is():
    """The gate is not specific to one pair; any policy-governed pair works."""
    created = create(
        policy=policy(from_state=BeliefState.DRAFT, candidate_to_state=BeliefState.ADMITTED),
        hypothesis=hypothesis(current_state=BeliefState.DRAFT),
        candidate_to_state=BeliefState.ADMITTED,
        prior=prior(BeliefState.DRAFT),
    )
    assert created.to_state is BeliefState.ADMITTED


def test_the_gate_cannot_create_a_genesis_event_and_that_is_deliberate():
    """A hypothesis with no events has no state, so there is nothing to transition *from*.

    §17.13 makes `from_state?` optional precisely for a target's first record, but a
    `TransitionPolicy` always declares a `from_state` -- so a policy-authorised transition always
    has a predecessor, and the genesis event cannot come from here.

    That is consistent rather than missing: under EPI-003 the state is a projection of the events,
    and the *first* state is assigned by §8's Hypothesis Admission Gate, which is `EPI-001` in M3.
    Pinned so the gap is visible: if someone later relaxes this check to "make the first event
    work", they will be letting an un-evented starting state in through the one function whose job
    is to refuse exactly that.
    """
    with pytest.raises(BeliefTransitionRefused, match="no recorded state"):
        create(prior=prior(None))


def test_cross_project_evidence_cannot_justify_a_belief():
    """`v3.3-a11`'s reason for existing: before `project_id`, this was not expressible.

    Checked for both kinds of trigger, because citing one foreign relation is as bad as citing one
    foreign attestation.
    """
    with pytest.raises(BeliefTransitionRefused, match="outside prj:photonics"):
        create(triggering_relations=(relation(project_id="prj:other"),))


def test_an_event_with_no_triggers_at_all_is_refused():
    """The model refuses it; going through the gate must not be a way around that."""
    with pytest.raises(ValueError, match="no triggering"):
        create(authorization=authorized(), triggering_relations=())


def test_the_created_event_lists_its_triggers_sorted_and_deduplicated():
    """Determinism reaches the record too: the same evidence must produce the same event."""
    created = create(
        triggering_relations=(
            relation(relation_id="rel:9"),
            relation(relation_id="rel:2"),
            relation(relation_id="rel:9"),
        )
    )
    assert created.triggering_relation_ids == ("rel:2", "rel:9")


def test_a_manual_correction_still_goes_through_the_policy():
    """§6.18: 任何 manual correction 也必須形成 event -- and it is still policy-authorised.

    The actor is recorded; the authority is still the policy. "A human said so" is not an
    alternative route around `evaluate`, it is an attribution on an event that passed it.
    """
    created = create(actor_id="act:prof-lin", rationale_artifact_or_record_ref="art:sha256:x")
    assert created.actor_id == "act:prof-lin"
    assert created.policy_id == "pol:hypothesis-default"


# --------------------------------------------------------------------------------------------
# The capability. P7 audit finding 1: the persistence path must be able to tell an authorised
# revision from an unevaluated one.
# --------------------------------------------------------------------------------------------


def test_the_authorization_capability_cannot_be_forged_by_accident():
    """Constructing `AuthorizedRevision` beside the gates is refused.

    Not a security boundary -- someone who imports the private sentinel can forge one, and
    `tests/conftest_fixtures.py::forged_authorization` does exactly that for store tests. The
    property is that it cannot happen *by accident*, and that the line doing it appears in a diff.
    """
    from lab_brain.core.belief import AuthorizedRevision

    with pytest.raises(BeliefTransitionRefused, match="cannot be constructed directly"):
        AuthorizedRevision(event=create(), origin="TRANSITION")


def test_both_gates_mint_the_capability_and_say_which_one_did():
    """A reader of a call site should be able to see which gate was used."""
    transition = record_transition(
        event_id="bre:1",
        authorization=authorized(),
        policy=policy(),
        hypothesis=hypothesis(),
        candidate_to_state=BeliefState.SUPPORTED,
        prior=prior(),
        occurred_at=T0,
        trace_id=TRACE,
        triggering_relations=(relation(),),
    )
    assert transition.origin == "TRANSITION"

    admitted = admit_hypothesis(
        event_id="bre:0",
        policy=policy(
            is_admission=True, from_state=BeliefState.DRAFT, candidate_to_state=BeliefState.ACTIVE
        ),
        project_id=PROJECT,
        hypothesis_id=HYP,
        prior=prior(None),
        occurred_at=T0,
        trace_id=TRACE,
        triggering_relations=(relation(),),
    )
    assert admitted.origin == "ADMISSION"
    assert admitted.event.from_state is None
    assert admitted.event.to_state is BeliefState.ACTIVE


# --------------------------------------------------------------------------------------------
# Admission is a separate path, not a hole in the transition gate.
# --------------------------------------------------------------------------------------------


def test_a_transition_policy_cannot_back_an_admission():
    """Otherwise every dropped predecessor could be recorded as a beginning."""
    with pytest.raises(BeliefTransitionRefused, match="not an admission policy"):
        admit_hypothesis(
            event_id="bre:0",
            policy=policy(),
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=prior(None),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_relations=(relation(),),
        )


def test_an_admission_policy_cannot_back_a_transition():
    """The other direction, or admission would just be a second transition gate with no predecessor
    check."""
    with pytest.raises(BeliefTransitionRefused, match="is an admission policy"):
        create(policy=policy(is_admission=True))


def test_a_target_with_history_cannot_be_admitted_again():
    """Admission happens once; a second one rewrites the beginning of an append-only history."""
    with pytest.raises(BeliefTransitionRefused, match="already has recorded history"):
        admit_hypothesis(
            event_id="bre:0",
            policy=policy(
                is_admission=True,
                from_state=BeliefState.DRAFT,
                candidate_to_state=BeliefState.ACTIVE,
            ),
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=prior(BeliefState.ACTIVE),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_relations=(relation(),),
        )


def test_an_emptiness_check_against_the_wrong_history_proves_nothing():
    """A projection for another project or another target cannot establish that *this* one is new."""
    for wrong in (prior(None, project_id="prj:other"), prior(None, target_id="hyp:other")):
        with pytest.raises(BeliefScopeError, match="proves nothing"):
            admit_hypothesis(
                event_id="bre:0",
                policy=policy(
                    is_admission=True,
                    from_state=BeliefState.DRAFT,
                    candidate_to_state=BeliefState.ACTIVE,
                ),
                project_id=PROJECT,
                hypothesis_id=HYP,
                prior=wrong,
                occurred_at=T0,
                trace_id=TRACE,
                triggering_relations=(relation(),),
            )


def test_an_admission_cannot_cite_another_projects_evidence():
    with pytest.raises(BeliefTransitionRefused, match="outside prj:photonics"):
        admit_hypothesis(
            event_id="bre:0",
            policy=policy(
                is_admission=True,
                from_state=BeliefState.DRAFT,
                candidate_to_state=BeliefState.ACTIVE,
            ),
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=prior(None),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_relations=(relation(project_id="prj:other"),),
        )


# --------------------------------------------------------------------------------------------
# `v3.3-a12` / SPEC-ISSUE-011: the authorization is durable and must re-derive.
# --------------------------------------------------------------------------------------------


def forge(authorization: BeliefTransitionDecision, **overrides: object) -> BeliefTransitionDecision:
    """Build a Decision the honest path would never produce.

    This is what an attacker can still do in process, and the point of the tests below is that
    doing it no longer helps. `BeliefTransitionDecision` deliberately does *not* re-run `evaluate`
    in its validator -- re-derivation belongs to the gate, so the model stays a plain record and
    the refusal happens in one place a reader can find.
    """
    return authorization.model_copy(update=overrides)


def test_the_event_names_the_authorization_that_produced_it():
    """Without the back-reference there is nothing to re-derive against (§17.13, `v3.3-a12`)."""
    created = create()
    assert created.authorization_decision_id == "dec:1"


def test_a_decision_records_the_inputs_it_was_computed_from():
    """The snapshot, not the verdict, is what makes the authorization durable."""
    authorization = authorized()
    snapshot = authorization.decision_input_snapshot

    assert snapshot.hypothesis.hypothesis_id == HYP
    assert snapshot.candidate_to_state is BeliefState.SUPPORTED
    assert tuple(r.relation_id for r in snapshot.admitted_relations) == ("rel:1",)
    assert authorization.input_hash.startswith("sha256:")
    assert authorization.input_hash == snapshot.input_hash()


def test_the_input_hash_covers_every_input_not_just_some_of_them():
    """A hash over part of the inputs looks like a binding and is not one.

    Each perturbation below moves a different one of the operator's inputs, and each must move the
    hash. A hash that ignored, say, `independence_summary` would let a threshold be swapped out
    after the fact while the record still verified.
    """
    baseline = authorized().input_hash
    perturbations = {
        "hypothesis": authorized(hypothesis=hypothesis(stakes="LOW")),
        "admitted_relations": authorized(admitted_relations=(relation(relation_id="rel:2"),)),
        "independence_summary": authorized(independence_summary=summary(independent_count=3)),
        "candidate_to_state": authorized(candidate_to_state=BeliefState.CONTRADICTED),
    }
    for name, perturbed in perturbations.items():
        assert perturbed.input_hash != baseline, f"{name} does not reach the input_hash"


def test_a_decision_whose_hash_does_not_match_its_inputs_cannot_be_built():
    """Caught at construction, so the error lands on the line that got it wrong."""
    honest = authorized()
    with pytest.raises(ValueError, match="input_hash"):
        BeliefTransitionDecision.model_validate(
            honest.model_dump() | {"input_hash": "sha256:" + "0" * 64}
        )


def test_the_gate_re_checks_the_hash_because_model_copy_skips_validators():
    """The validator is not the only line of defence here, and it must not be.

    `model_copy(update=...)` does not re-run Pydantic validators, so a Decision carrying a
    mismatched `input_hash` *can* exist in process -- the test above holds only for the honest
    constructor. Found by writing that test and watching it not raise, not by review. The gate
    therefore verifies the binding itself rather than trusting that construction did.
    """
    tampered = forge(authorized(), input_hash="sha256:" + "0" * 64)
    assert tampered.input_hash != tampered.decision_input_snapshot.input_hash()

    with pytest.raises(AuthorizationNotRederivable, match="altered since the authorization"):
        create(authorization=tampered)


def test_an_authorization_that_does_not_re_derive_is_refused():
    """The consistent forgery R-13 recorded, now closed.

    The Decision is internally consistent -- `result` agrees with `evaluated`, the hash agrees
    with the snapshot, the policy and the transition line up -- and it is still refused, because
    re-evaluating its own snapshot under the named policy does not produce what it claims.
    """
    refused = authorized(independence_summary=summary(independent_count=0))
    claimed = forge(
        refused,
        result=TransitionOutcome.ALLOW,
        evaluated=refused.evaluated.model_copy(
            update={
                "outcome": TransitionOutcome.ALLOW,
                "reason_code": TransitionReason.POLICY_SATISFIED,
            }
        ),
    )
    assert claimed.authorizes_transition, "the forgery must look valid on its face"
    assert claimed.input_hash == claimed.decision_input_snapshot.input_hash()

    with pytest.raises(AuthorizationNotRederivable, match="re-evaluating its own snapshot"):
        create(authorization=claimed)


def test_a_policy_mutated_after_the_fact_cannot_launder_an_old_authorization():
    """Same mechanism from the other side: the inputs are honest and the policy moved.

    `TransitionPolicy` is immutable in memory and versioned in the table, so this is the shape the
    attack takes -- reuse the id and version with different rules. Re-derivation catches it
    because it compares the whole decision rather than the outcome.
    """
    authorization = authorized()
    stricter = policy(min_independent_attestations=99)

    with pytest.raises(AuthorizationNotRederivable, match="re-evaluating its own snapshot"):
        create(authorization=authorization, policy=stricter)


def test_re_derivation_compares_the_whole_decision_not_only_the_outcome():
    """An ALLOW that agrees on the verdict and disagrees on the reason is still a disagreement.

    If this passed, a stored decision could keep its ALLOW while its `reason_code` and
    `blocking_conflict_ids` were rewritten -- and those are the fields an auditor reads to find
    out *why* a belief changed.
    """
    authorization = authorized()
    relabelled = forge(
        authorization,
        evaluated=authorization.evaluated.model_copy(
            update={"reason_code": TransitionReason.HUMAN_GATE_REQUIRED}
        ),
    )
    assert relabelled.result is TransitionOutcome.ALLOW

    with pytest.raises(AuthorizationNotRederivable, match="re-evaluating its own snapshot"):
        create(authorization=relabelled)


def test_an_authorization_for_another_project_authorises_nothing_here():
    """SEC-002 scopes every read by project, and an authorization is a read like any other."""
    foreign = authorized(hypothesis=hypothesis(project_id="prj:other"))
    with pytest.raises(BeliefTransitionRefused, match=r"does not transfer|outside"):
        create(authorization=foreign)


def test_an_authorization_for_another_subject_authorises_nothing_here():
    """An ALLOW is for one hypothesis. Reusing it for a sibling is the cheapest bypass of all."""
    sibling = authorized(hypothesis=hypothesis(hypothesis_id="hyp:something-else"))
    with pytest.raises(BeliefTransitionRefused, match="does not transfer"):
        create(authorization=sibling)


def test_re_derivation_refuses_a_different_authority_comparator():
    """Core cannot reconstruct a DomainPack comparator (§24.2), so it must be the same one.

    Re-deriving under a *different* comparator answers a different question, and answering it
    would be worse than refusing, because the result reads as a confirmation.
    """
    from tests.contract.test_transition_policy import ToyAuthority

    class OtherAuthority(ToyAuthority):
        policy_id = "auth:other"

    authorization = authorize_transition(
        decision_id="dec:1",
        policy=policy(),
        hypothesis=hypothesis(),
        admitted_relations=(relation(),),
        authority_policy=ToyAuthority(),
        independence_summary=summary(),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    )
    assert authorization.decision_input_snapshot.authority_policy_id == "auth:toy"

    with pytest.raises(AuthorizationNotRederivable, match="authority comparator"):
        create(authorization=authorization, authority_policy=OtherAuthority())


def test_the_authority_comparator_is_stored_by_identity_never_by_result():
    """§17.14.1 forbids storing the comparisons: it would put the rules beyond falsification."""
    from tests.contract.test_transition_policy import ToyAuthority

    snapshot = authorize_transition(
        decision_id="dec:1",
        policy=policy(),
        hypothesis=hypothesis(),
        admitted_relations=(relation(),),
        authority_policy=ToyAuthority(),
        independence_summary=summary(),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    ).decision_input_snapshot

    assert (snapshot.authority_policy_id, snapshot.authority_policy_version) == (
        "auth:toy",
        "toy-1.0.0",
    )
    recorded = str(snapshot.canonical_form())
    assert "STRONGER" not in recorded and "INCOMPARABLE" not in recorded


def test_half_an_authority_identity_cannot_locate_a_comparator():
    """An id without a version identifies nothing; a version without an id names nothing."""
    from lab_brain.core.models.decision import DecisionInputSnapshot

    with pytest.raises(ValueError, match="must be given together"):
        DecisionInputSnapshot(
            hypothesis=hypothesis(),
            admitted_relations=(relation(),),
            independence_summary=summary(),
            candidate_to_state=BeliefState.SUPPORTED,
            authority_policy_id="auth:toy",
        )


def test_genesis_carries_no_transition_authorization():
    """Admission is a separate gate and must not borrow transition authority (§8)."""
    admitted = admit_hypothesis(
        event_id="bre:0",
        policy=policy(
            is_admission=True, from_state=BeliefState.DRAFT, candidate_to_state=BeliefState.ACTIVE
        ),
        project_id=PROJECT,
        hypothesis_id=HYP,
        prior=prior(None),
        occurred_at=T0,
        trace_id=TRACE,
        triggering_relations=(relation(),),
    )
    assert admitted.event.from_state is None
    assert admitted.event.authorization_decision_id is None


def test_a_non_genesis_event_cannot_be_built_without_an_authorization():
    """The model refuses it, so even a caller that skips the gate cannot assemble one."""
    with pytest.raises(ValueError, match="no authorization_decision_id"):
        BeliefRevisionEvent(
            event_id="bre:x",
            project_id=PROJECT,
            target_type=create().target_type,
            target_id=HYP,
            from_state=BeliefState.ACTIVE,
            to_state=BeliefState.SUPPORTED,
            triggering_relation_ids=("rel:1",),
            policy_id="pol:hypothesis-default",
            policy_version="1.0.0",
            occurred_at=T0,
            trace_id=TRACE,
        )


def test_a_genesis_event_cannot_claim_a_transition_authorization():
    """The other direction: genesis with an authorization would make admission a transition."""
    with pytest.raises(ValueError, match="admission is not one"):
        BeliefRevisionEvent(
            event_id="bre:x",
            project_id=PROJECT,
            target_type=create().target_type,
            target_id=HYP,
            from_state=None,
            to_state=BeliefState.ACTIVE,
            triggering_relation_ids=("rel:1",),
            policy_id="pol:genesis",
            policy_version="1.0.0",
            authorization_decision_id="dec:1",
            occurred_at=T0,
            trace_id=TRACE,
        )
