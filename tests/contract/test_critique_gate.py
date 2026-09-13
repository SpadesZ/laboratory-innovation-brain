"""§7.6's independent critique path has two triggers, not one (SRC-002).

    重大 REJECT / irreversible action 必須經 independent critique path

Amendment v3.3-a6 bound only the first. `T-SRC-002` gated `BELIEF_REVISION`, so a decision moving a
hypothesis to REJECTED was covered, and an irreversible action that never touched belief state was
not reached at all. Submitting a layout for fabrication is irreversible and costs six weeks; under
the old contract it needed no critique whatsoever.

These are the negative fixtures amendment v3.3-a7 requires. They cover the dispatch clause of
`T-SRC-002` only — SourcePolicy switching by research intent, inverted retrieval and
`CritiqueReport.inverted_bundle_id` traceability are M3 work and are not claimed here.
"""

from __future__ import annotations

import pytest

from lab_brain.core.critique_gate import (
    ACCEPTED_ADJUDICATORS,
    Adjudicator,
    CritiqueAxis,
    CritiqueRecord,
    DispatchRequest,
    HumanApproval,
    Reversibility,
    evaluate_dispatch,
)

pytestmark = [pytest.mark.requirement("SRC-002"), pytest.mark.spec_test("T-SRC-002")]


def _independent(critique_id: str = "crit-1") -> CritiqueRecord:
    return CritiqueRecord(
        critique_id=critique_id,
        differs_in=frozenset({CritiqueAxis.RETRIEVAL_BUNDLE}),
        adjudicated_by=Adjudicator.EXTERNAL_EVIDENCE,
    )


def test_an_irreversible_action_without_critique_is_refused_even_with_no_belief_revision():
    """The gap amendment v3.3-a7 closed, asserted directly.

    `causes_belief_revision=False` is the condition under which the old contract said nothing. A
    tape-out submission changes no hypothesis status, so gating `BELIEF_REVISION` left it entirely
    ungoverned.
    """
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="tapeout-submit",
            reversibility=Reversibility.IRREVERSIBLE,
            causes_belief_revision=False,
        )
    )
    assert not decision.allowed
    assert decision.trigger == "irreversible action"
    assert "independent critique path" in decision.reason


def test_human_approval_does_not_substitute_for_critique():
    """Approval answers *who is accountable*; critique answers *whether it was challenged*.

    This is the substitution the spec explicitly forbids, and the one most likely to feel
    reasonable: a professor has signed off, so surely it has been scrutinised. §14.3's fabrication
    gate requires the approval **as well as** the critique, not instead of it.
    """
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="mpw-shuttle-book",
            reversibility=Reversibility.IRREVERSIBLE,
            causes_belief_revision=False,
            human_approval=HumanApproval(
                actor_id="actor:prof-lin", approved_at="2026-09-13T00:00:00Z"
            ),
        )
    )
    assert not decision.allowed
    assert "does not substitute" in decision.reason
    assert "actor:prof-lin" in decision.reason, "the refusal should name the approval it rejected"


def test_a_critique_that_changed_nothing_is_not_independent():
    """§7.6 requires the critique to differ in bundle, policy or route. None means re-running it."""
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="tapeout-submit",
            reversibility=Reversibility.IRREVERSIBLE,
            critique=CritiqueRecord(
                critique_id="crit-same",
                differs_in=frozenset(),
                adjudicated_by=Adjudicator.EXTERNAL_EVIDENCE,
            ),
        )
    )
    assert not decision.allowed
    assert "differs from the original reasoning in no axis" in decision.reason


def test_a_critique_adjudicated_by_another_model_is_not_independent():
    """Adjudicating one inference with another settles nothing.

    The bundle changed, so the weaker half of the test passes — which is exactly why both halves
    have to be checked rather than either.
    """
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="tapeout-submit",
            reversibility=Reversibility.IRREVERSIBLE,
            critique=CritiqueRecord(
                critique_id="crit-model",
                differs_in=frozenset({CritiqueAxis.MODEL_ROUTE}),
                adjudicated_by=Adjudicator.MODEL_OPINION,
            ),
        )
    )
    assert not decision.allowed
    assert "adjudicated by MODEL_OPINION" in decision.reason


def test_a_major_reject_without_critique_is_refused():
    """The first trigger, still enforced. v3.3-a7 added a trigger; it removed nothing."""
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="reject-hypothesis-h7",
            reversibility=Reversibility.REVERSIBLE,
            causes_belief_revision=True,
            is_major_reject=True,
        )
    )
    assert not decision.allowed
    assert decision.trigger == "major REJECT"


def test_an_irreversible_action_with_an_independent_critique_may_dispatch():
    """The gate must be passable, or it is a prohibition rather than a gate."""
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="tapeout-submit",
            reversibility=Reversibility.IRREVERSIBLE,
            critique=_independent(),
        )
    )
    assert decision.allowed
    assert "crit-1" in decision.reason
    assert "RETRIEVAL_BUNDLE" in decision.reason


def test_a_reversible_non_reject_action_is_not_gated():
    """§7.6 names two triggers. Gating everything would make the distinction meaningless."""
    decision = evaluate_dispatch(
        DispatchRequest(
            action_id="run-eigenmode-sweep",
            reversibility=Reversibility.REVERSIBLE,
            causes_belief_revision=False,
        )
    )
    assert decision.allowed
    assert "not triggered" in decision.reason


@pytest.mark.parametrize("axis", list(CritiqueAxis))
def test_any_single_axis_satisfies_the_independence_requirement(axis):
    """§7.6 says 至少改變 one of the three, so each alone must be sufficient."""
    record = CritiqueRecord(
        critique_id="crit-axis",
        differs_in=frozenset({axis}),
        adjudicated_by=Adjudicator.VERIFICATION_RESULT,
    )
    assert record.is_independent, axis


def test_model_opinion_is_not_an_accepted_adjudicator():
    """Pinned so a later edit cannot quietly widen the set.

    `MODEL_OPINION` exists in the enum precisely so it can be refused explicitly rather than
    falling through a permissive default. If it ever joins `ACCEPTED_ADJUDICATORS`, §7.6's
    "由 external evidence / verification adjudicate" has been abandoned and this must fail.
    """
    assert Adjudicator.MODEL_OPINION not in ACCEPTED_ADJUDICATORS
    assert set(ACCEPTED_ADJUDICATORS) == {
        Adjudicator.EXTERNAL_EVIDENCE,
        Adjudicator.VERIFICATION_RESULT,
    }


def test_the_gate_is_deterministic():
    """Same request, same verdict. Without this the negative fixtures prove nothing durable."""
    request = DispatchRequest(
        action_id="tapeout-submit",
        reversibility=Reversibility.IRREVERSIBLE,
        critique=_independent(),
    )
    first, second = evaluate_dispatch(request), evaluate_dispatch(request)
    assert (first.allowed, first.reason, first.trigger) == (
        second.allowed,
        second.reason,
        second.trigger,
    )
