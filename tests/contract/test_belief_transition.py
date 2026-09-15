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
    BeliefProjection,
    BeliefScopeError,
    BeliefTransitionRefused,
    admit_hypothesis,
    record_transition,
)
from lab_brain.core.models import (
    BeliefRevisionEvent,
    BeliefState,
    TransitionDecision,
    TransitionOutcome,
    TransitionReason,
)
from tests.contract.test_transition_policy import hypothesis, policy, relation

pytestmark = [pytest.mark.requirement("EPI-005"), pytest.mark.spec_test("T-EPI-005")]

T0 = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:episode-1"


def allow(**overrides: object) -> TransitionDecision:
    defaults: dict[str, object] = {
        "outcome": TransitionOutcome.ALLOW,
        "reason_code": TransitionReason.POLICY_SATISFIED,
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "independent_attestation_count": 2,
    }
    defaults.update(overrides)
    return TransitionDecision(**defaults)  # type: ignore[arg-type]


def prior(state: BeliefState | None = BeliefState.ACTIVE, **overrides: object) -> BeliefProjection:
    defaults: dict[str, object] = {
        "project_id": PROJECT,
        "target_id": HYP,
        "current_state": state,
        "last_event_id": None if state is None else "bre:0",
    }
    defaults.update(overrides)
    return BeliefProjection(**defaults)  # type: ignore[arg-type]


def create(**overrides: object) -> BeliefRevisionEvent:
    """The event `record_transition` authorises, unwrapped from its capability.

    Unwrapping here keeps the assertions about the *event*. The capability itself is the subject of
    `test_the_authorization_capability_cannot_be_forged_by_accident` and of the store tests.
    """
    defaults: dict[str, object] = {
        "event_id": "bre:1",
        "decision": allow(),
        "policy": policy(),
        "hypothesis": hypothesis(),
        "candidate_to_state": BeliefState.SUPPORTED,
        "prior": prior(),
        "occurred_at": T0,
        "trace_id": TRACE,
        "triggering_relations": (relation(),),
    }
    defaults.update(overrides)
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


@pytest.mark.parametrize(
    "outcome",
    [
        TransitionOutcome.DENY,
        TransitionOutcome.NEED_MORE_EVIDENCE,
        TransitionOutcome.NEED_HUMAN_REVIEW,
    ],
)
def test_no_event_may_be_created_from_a_non_allow_decision(outcome):
    """The commonest bypass: run `evaluate`, ignore the answer, write the event anyway.

    NEED_HUMAN_REVIEW is the dangerous one -- it reads as progress, so a caller that treats
    "not DENY" as permission promotes exactly the beliefs a human was supposed to look at.
    """
    with pytest.raises(BeliefTransitionRefused, match="no belief revision"):
        create(decision=allow(outcome=outcome, reason_code=TransitionReason.HUMAN_GATE_REQUIRED))


def test_an_allow_from_another_policy_does_not_carry_over():
    with pytest.raises(BeliefTransitionRefused, match="does not carry over"):
        create(decision=allow(policy_id="pol:something-else"))


def test_an_allow_from_another_version_of_the_same_policy_does_not_carry_over():
    """Versions exist because the rules changed. An ALLOW under 1.0.0 is not one under 2.0.0."""
    with pytest.raises(BeliefTransitionRefused, match="does not carry over"):
        create(decision=allow(policy_version="2.0.0"))


def test_an_allow_for_one_transition_cannot_justify_another():
    """An ALLOW for ACTIVE -> SUPPORTED reused to record ACTIVE -> CONTRADICTED."""
    with pytest.raises(BeliefTransitionRefused, match="authorises ACTIVE -> SUPPORTED"):
        create(candidate_to_state=BeliefState.CONTRADICTED)


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
        create(triggering_relations=())


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
        decision=allow(),
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
