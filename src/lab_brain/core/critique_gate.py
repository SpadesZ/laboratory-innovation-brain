"""§7.6 independent critique path — the dispatch gate (SRC-002).

§7.6 states one rule with **two** triggers:

    重大 REJECT / irreversible action 必須經 independent critique path:
      至少改變 retrieval bundle、reasoning policy 或 model route,
      並由 external evidence / verification adjudicate。

Amendment v3.3-a6 bound only the first. ``T-SRC-002`` gated ``BELIEF_REVISION``, so a decision that
moved a hypothesis to REJECTED was covered — and an irreversible action that never touched belief
state was not reached at all. Submitting a layout for fabrication or booking an MPW shuttle slot is
irreversible, costs six weeks, and under the old wording needed no critique whatsoever.

So the gate is a decision over the action, not over the belief transition it happens to cause.

WHY THIS IS A PURE FUNCTION

No I/O, no clock, no randomness. The same request yields the same decision, which is what lets
`T-SRC-002`'s negative fixtures assert a refusal rather than mock one. It lives in ``core`` because
it is epistemic policy, not domain knowledge: a DomainPack declares *that* tape-out is irreversible,
this module decides what that implies (AGT-011, §24.2).

WHAT HUMAN APPROVAL IS NOT

An approval and a critique answer different questions. Approval answers *who is accountable*;
critique answers *whether the conclusion was independently challenged*. A professor approving a
tape-out does not make the reasoning behind it independently examined, so
:func:`evaluate_dispatch` refuses an irreversible action carrying a valid approval and no critique.
§14.3's fabrication gate requires the approval **as well**, not instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Reversibility(StrEnum):
    """Whether an action can be undone once dispatched.

    ``IRREVERSIBLE`` is the trigger §7.6 names. It is declared per Capability by the DomainPack
    (§9.3's cost profile: fabrication is 極高 + 高延遲 + 不可逆), never inferred here.
    """

    REVERSIBLE = "REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"


class CritiqueAxis(StrEnum):
    """The three axes §7.6 accepts as making a critique path independent.

    "Independent" means the critique did not simply re-run the original reasoning. Changing any one
    of these is sufficient; changing none of them means the critique saw the same evidence through
    the same policy on the same model, which is the groupthink §15.4 is about.
    """

    RETRIEVAL_BUNDLE = "RETRIEVAL_BUNDLE"
    REASONING_POLICY = "REASONING_POLICY"
    MODEL_ROUTE = "MODEL_ROUTE"


class Adjudicator(StrEnum):
    """What settled the critique.

    ``MODEL_OPINION`` is listed so it can be **refused** explicitly rather than falling through a
    permissive default. §7.6 requires external evidence or a verification result; a second model
    pass is another inference, and adjudicating one inference with another is the circularity
    EVI-003 forbids at the evidence layer.
    """

    EXTERNAL_EVIDENCE = "EXTERNAL_EVIDENCE"
    VERIFICATION_RESULT = "VERIFICATION_RESULT"
    MODEL_OPINION = "MODEL_OPINION"


#: Adjudicators §7.6 accepts. Derived from the enum rather than re-listed, so adding a member
#: forces a decision here instead of silently defaulting to permitted.
ACCEPTED_ADJUDICATORS = frozenset({Adjudicator.EXTERNAL_EVIDENCE, Adjudicator.VERIFICATION_RESULT})


@dataclass(frozen=True)
class CritiqueRecord:
    """A completed critique, and how it differed from the reasoning it examined."""

    critique_id: str
    differs_in: frozenset[CritiqueAxis] = field(default_factory=frozenset)
    adjudicated_by: Adjudicator = Adjudicator.MODEL_OPINION

    @property
    def is_independent(self) -> bool:
        """Both halves of §7.6's test, not either half.

        A critique that changed the retrieval bundle but was then settled by a model opinion is not
        independent, and neither is one adjudicated by measurement that re-used the identical
        bundle, policy and route.
        """
        return bool(self.differs_in) and self.adjudicated_by in ACCEPTED_ADJUDICATORS

    def why_not_independent(self) -> str:
        if not self.differs_in:
            return (
                f"critique {self.critique_id} differs from the original reasoning in no axis; "
                f"§7.6 requires at least one of {', '.join(sorted(a.value for a in CritiqueAxis))}"
            )
        if self.adjudicated_by not in ACCEPTED_ADJUDICATORS:
            return (
                f"critique {self.critique_id} was adjudicated by {self.adjudicated_by.value}; "
                "§7.6 requires external evidence or a verification result, because adjudicating "
                "one inference with another settles nothing"
            )
        return ""


@dataclass(frozen=True)
class HumanApproval:
    """Who authorised the action. Records accountability, not independent examination."""

    actor_id: str
    approved_at: str


@dataclass(frozen=True)
class DispatchRequest:
    """An action asking to be dispatched.

    ``causes_belief_revision`` is carried so the gate can be shown to ignore it for an irreversible
    action. That is the whole point of amendment v3.3-a7: the old contract only bound decisions that
    moved belief state.
    """

    action_id: str
    reversibility: Reversibility
    causes_belief_revision: bool = False
    is_major_reject: bool = False
    critique: CritiqueRecord | None = None
    human_approval: HumanApproval | None = None

    @property
    def needs_independent_critique(self) -> bool:
        """§7.6's two triggers, as a disjunction."""
        return self.reversibility is Reversibility.IRREVERSIBLE or self.is_major_reject


@dataclass(frozen=True)
class DispatchDecision:
    """The gate's verdict. ``reason`` is always populated, including on allow."""

    allowed: bool
    reason: str
    trigger: str = ""


def evaluate_dispatch(request: DispatchRequest) -> DispatchDecision:
    """Decide whether an action may be dispatched under §7.6 (SRC-002).

    Fails closed: an action that needs a critique and has none is refused, and so is one whose
    critique is not independent. Nothing here consults an approval to satisfy the critique
    requirement — see the module docstring for why they are not interchangeable.
    """
    if not request.needs_independent_critique:
        return DispatchDecision(
            allowed=True,
            reason=f"{request.action_id} is reversible and is not a major REJECT; "
            "§7.6's critique path is not triggered",
        )

    trigger = (
        "irreversible action"
        if request.reversibility is Reversibility.IRREVERSIBLE
        else "major REJECT"
    )

    if request.critique is None:
        detail = ""
        if request.human_approval is not None:
            # Stated in the refusal rather than left implicit: the tempting reading is that a
            # signed-off action has been scrutinised enough.
            detail = (
                f" A human approval by {request.human_approval.actor_id} is present and does not "
                "substitute: approval records accountability, critique records independent "
                "challenge."
            )
        return DispatchDecision(
            allowed=False,
            reason=f"{request.action_id} is blocked: {trigger} requires a completed independent "
            f"critique path (§7.6) and none is recorded.{detail}",
            trigger=trigger,
        )

    if not request.critique.is_independent:
        return DispatchDecision(
            allowed=False,
            reason=f"{request.action_id} is blocked: {trigger} requires an *independent* critique "
            f"path. {request.critique.why_not_independent()}",
            trigger=trigger,
        )

    return DispatchDecision(
        allowed=True,
        reason=f"{request.action_id} may dispatch: {trigger} was examined by independent critique "
        f"{request.critique.critique_id}, differing in "
        f"{', '.join(sorted(axis.value for axis in request.critique.differs_in))} and adjudicated "
        f"by {request.critique.adjudicated_by.value}",
        trigger=trigger,
    )


__all__ = [
    "ACCEPTED_ADJUDICATORS",
    "Adjudicator",
    "CritiqueAxis",
    "CritiqueRecord",
    "DispatchDecision",
    "DispatchRequest",
    "HumanApproval",
    "Reversibility",
    "evaluate_dispatch",
]
