"""The budget gate (COST-001, §17.17, §14.3).

    Before each LLM/tool call, BudgetGate MUST check project/episode caps.
    Exceed -> refuse/escalate; never silently continue.

GATE, NOT LEDGER. The decision is a function of an *estimate*, evaluated before the call. A
component that records what was spent after the fact is accounting; it cannot refuse anything. So
:func:`evaluate_budget` takes ``estimate`` and refuses outright when it is absent -- "we do not know
what this costs" is not a reason to proceed.

APPROVAL RELIEVES THE BUDGET AND NOTHING ELSE. §14.3 lists several gates, and a supervisor releasing
a spending cap has not cleared the fabrication gate, the independent critique path (§7.6) or an ACL
(SEC-002). :class:`BudgetDecision` therefore exposes ``budget_permits`` and no bare ``allowed``: a
caller that wants to dispatch has to ask each gate its own question, and cannot accidentally read
one answer as all of them.

AN APPROVAL IS NARROW. Scoped to one action in one episode of one project, under one policy version,
valid for a window, usable once, and for a stated amount. Each of those is a separate refusal below,
because an approval that survives any of them is a standing permission nobody granted.

AN APPROVAL IS ALSO *SIGNED BY SOMEONE IN PARTICULAR*. Until P5-fix the only thing checked about
``approver_actor_id`` was that the string was present, which made the §14.3 supervisor path
decorative: any caller able to construct a :class:`BudgetApproval` could put any id in that field
and release any overrun. §14.4 says ACLs must support project membership and **approval
authority**, and §14.3 says the overrun path is a *supervisor/human* decision, so four independent
facts are now required and each is refused separately -- the approver is that actor, the actor is
active and HUMAN, the actor is an active member of *this* project, and the membership carries
budget authority.

An AGENT_ROLE or SERVICE actor is refused outright. That is the self-signing case: an agent that can
approve its own overrun has no budget, only a formality.

PURE AND DETERMINISTIC. No clock, no I/O. ``now`` is an input, so a recorded decision can be
replayed from an audit record instead of re-derived against a system that has moved on.

WHICH IS WHY PURITY IS NOT ENOUGH FOR "ONCE". :func:`evaluate_budget` can only be told which
approvals were already spent; it cannot make spending one atomic, and two concurrent dispatches
holding the same approval will both be told yes. Single use is a property of the *record*, so it is
enforced by an atomic claim in the store -- see :func:`authorize_dispatch` and
:class:`BudgetApprovalClaims`. Callers that dispatch use that; ``evaluate_budget`` remains available
for replaying a recorded decision, which is a question about the past and consumes nothing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.cost import CAPPED_DIMENSIONS, BudgetCaps, CostVector
from lab_brain.core.models.enums import ActorType

#: The `ProjectMembership.approval_scopes` entry that authorises releasing a budget overrun
#: (§14.4 "approval authority", §14.3 "昂貴計算 gate").
#:
#: A named scope rather than a role string: §14.4 asks for approval *authority*, and roles drift --
#: "lead", "pi", "supervisor" and "admin" all end up meaning "probably allowed" in a codebase that
#: compares role names. A scope is granted explicitly to a membership or it is absent, and the
#: column defaults to `'{}'` so a membership created in raw SQL starts with no authority at all.
BUDGET_OVERRUN_SCOPE = "BUDGET_OVERRUN"

#: Actor types that may sign a budget overrun. §14.3 calls it a supervisor/human decision.
APPROVER_ACTOR_TYPES: frozenset[ActorType] = frozenset({ActorType.HUMAN})


class DispatchOutcome(StrEnum):
    """What the budget says. Three outcomes, because "allowed" and "allowed because a human
    signed for it" are different facts and the ledger has to tell them apart."""

    ALLOWED = "ALLOWED"
    ALLOWED_BY_APPROVAL = "ALLOWED_BY_APPROVAL"
    BLOCKED = "BLOCKED"


class BudgetPolicy(CoreModel):
    """Versioned caps for a project's session (§17.17, §17.19.1 as amended by `v3.3-a10`).

    ``caps`` is a :class:`BudgetCaps`, not a ``CostVector``. §17.19.1 now states the distinction the
    gate turns on: an absent / ``None`` cap is *not capped in this dimension*, a cap of ``0`` is
    *zero permitted*, and they are different facts.

    This class previously carried ``caps: CostVector`` plus a ``capped`` tuple naming which
    dimensions counted. Because ``CostVector`` defaults every dimension to zero, ``cap_for()`` had
    to guess which zeros were real, and it guessed *uncapped* -- so a policy that deliberately
    permitted nothing in a dimension permitted everything. Two representations of one fact, and the
    tie broken in the failing-open direction. Both are gone: the cap value is the whole answer.
    """

    policy_id: str
    policy_version: str
    project_id: str
    caps: BudgetCaps

    def cap_for(self, dimension: str) -> Decimal | int | None:
        """The cap in force, or ``None`` when this policy does not constrain ``dimension``.

        A returned ``0`` means zero permitted and must be compared against, not treated as absent.
        """
        return self.caps.cap_for(dimension)


class BudgetApproval(CoreModel):
    """A supervisor's release of a specific overrun (v3.3-a6, §14.3).

    Recorded as an event with the approver's ``actor_id`` -- COST-001 requires the approval itself
    to be attributable, not merely its effect.
    """

    approval_id: str
    approver_actor_id: str
    project_id: str
    episode_id: str
    action_ref: str
    policy_id: str
    policy_version: str
    #: How much overrun was authorised, per dimension. An approval is for an amount, not a blank
    #: cheque.
    approved_overrun: CostVector
    granted_at: dt.datetime
    expires_at: dt.datetime


@dataclass(frozen=True)
class BudgetRequest:
    """Everything the decision depends on, passed in rather than looked up.

    ``consumed`` is the session's spend so far: caps are on the session, and a gate that inspects
    only the current call lets a thousand individually-cheap ones through.
    """

    action_ref: str
    project_id: str
    episode_id: str
    actor_id: str
    estimate: CostVector | None
    consumed: CostVector
    policy: BudgetPolicy | None
    now: dt.datetime
    approval: BudgetApproval | None = None
    #: The approver's own Actor row, loaded by the caller and passed in like everything else, so
    #: the decision stays replayable. Required whenever ``approval`` is present: an approval whose
    #: signer cannot be resolved is an unsigned one.
    approver: Actor | None = None
    #: The approver's membership of ``project_id``. Carries the `approval_scopes` that decide
    #: whether this person may release a budget at all.
    approver_membership: ProjectMembership | None = None
    #: Approvals already known to be spent. This is a *hint*, not the enforcement: it lets a replay
    #: reproduce a recorded refusal, and it short-circuits an obvious re-presentation. Actual single
    #: use is the atomic claim in :func:`authorize_dispatch` -- a caller passing an empty set here
    #: must not thereby get a second use out of one approval.
    consumed_approval_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class BudgetDecision:
    """The verdict, the reason, and enough context to replay it.

    Named ``budget_permits`` rather than ``allowed`` on purpose -- see the module docstring.
    """

    outcome: DispatchOutcome
    reason: str
    policy_version: str | None = None
    exceeded_dimensions: tuple[str, ...] = ()
    escalation_available: bool = False
    approval_id: str | None = None

    @property
    def budget_permits(self) -> bool:
        return self.outcome in (DispatchOutcome.ALLOWED, DispatchOutcome.ALLOWED_BY_APPROVAL)


def _unauthorised(
    approval: BudgetApproval,
    approver: Actor | None,
    membership: ProjectMembership | None,
    project_id: str,
) -> str | None:
    """Why ``approver`` may not sign ``approval``, or ``None`` if they may.

    Fails closed on every path, and each path is a distinct way the previous implementation said
    yes. It checked that ``approver_actor_id`` was a non-empty string; it did not check that the
    string named a real actor, that the actor was still employed, that they were a person rather
    than the agent whose spending they were releasing, that they belonged to the project whose money
    it was, or that anyone had ever granted them the authority to do it.

    Ordered identity-first, like :func:`lab_brain.core.access.can_read_artifact`: resolve who is
    signing before saying anything about what they are allowed to sign, so a refusal never describes
    the project's budget arrangements to an actor with no standing in it.
    """
    if approver is None:
        return (
            f"its approver {approval.approver_actor_id} could not be resolved to an actor; an "
            "approval nobody can be identified as having given is an unsigned one (§14.4)"
        )
    if approver.actor_id != approval.approver_actor_id:
        # The gate is the last line. A repository bug that returned a neighbouring row must not
        # become an authorisation bug, so the supplied record has to be the one being claimed.
        return (
            f"the supplied approver record is {approver.actor_id}, not the "
            f"{approval.approver_actor_id} the approval names"
        )
    if not approver.active:
        return (
            f"approver {approver.actor_id} is not active; a disabled account's authority is "
            "suspended everywhere at once, which is the point of disabling it globally"
        )
    if approver.actor_type not in APPROVER_ACTOR_TYPES:
        return (
            f"approver {approver.actor_id} is a {approver.actor_type.value}, and §14.3 makes the "
            "overrun path a supervisor/human decision. A non-human actor approving a budget is a "
            "system signing its own permission slip"
        )

    if membership is None:
        return (
            f"approver {approver.actor_id} has no membership of {project_id}; authority over one "
            "project's budget is not authority over another's"
        )
    if membership.actor_id != approver.actor_id or membership.project_id != project_id:
        return (
            f"the supplied membership is {membership.actor_id} in {membership.project_id}, not "
            f"{approver.actor_id} in {project_id}"
        )
    if not membership.active:
        return (
            f"approver {approver.actor_id}'s membership of {project_id} is not active; the row is "
            "retained so the audit trail survives revocation, not so the authority does"
        )
    if BUDGET_OVERRUN_SCOPE not in membership.approval_scopes:
        held = ", ".join(sorted(membership.approval_scopes))
        return (
            f"approver {approver.actor_id} holds no {BUDGET_OVERRUN_SCOPE} scope in {project_id} "
            f"(holds: {held or 'none'}). Being a member is not being an approver, and §14.4 makes "
            "approval authority a separate grant"
        )
    return None


def _overruns(
    policy: BudgetPolicy, projected: CostVector, headroom: CostVector | None = None
) -> tuple[str, ...]:
    """Capped dimensions where the projected spend exceeds the cap (plus any approved headroom)."""
    over: list[str] = []
    for dimension in CAPPED_DIMENSIONS:
        cap = policy.cap_for(dimension)
        if cap is None:
            continue
        allowance = cap
        if headroom is not None:
            allowance = cap + getattr(headroom, dimension)
        if getattr(projected, dimension) > allowance:
            over.append(dimension)
    return tuple(over)


def evaluate_budget(request: BudgetRequest) -> BudgetDecision:
    """Decide whether the budget permits dispatching ``request.action_ref``.

    Fails closed at every step. The order is deliberate: missing context first, then the caps, then
    the approval -- so an in-budget call never consumes an approval it did not need.
    """
    if request.policy is None:
        return BudgetDecision(
            DispatchOutcome.BLOCKED,
            f"no budget policy for {request.project_id}; an unbudgeted project is not an "
            "unlimited one (§17.17)",
        )
    policy = request.policy
    if policy.project_id != request.project_id:
        return BudgetDecision(
            DispatchOutcome.BLOCKED,
            f"the supplied policy governs a different project ({policy.project_id}, not "
            f"{request.project_id}); checking the wrong caps is not checking caps",
            policy_version=policy.policy_version,
        )
    if request.estimate is None:
        return BudgetDecision(
            DispatchOutcome.BLOCKED,
            f"no cost estimate for {request.action_ref}; the gate decides from an estimate taken "
            "before the call, and an unestimated action cannot be admitted on the promise of "
            "recording its cost afterwards",
            policy_version=policy.policy_version,
        )

    projected = request.consumed.plus(request.estimate)
    exceeded = _overruns(policy, projected)
    if not exceeded:
        return BudgetDecision(
            DispatchOutcome.ALLOWED,
            f"{request.action_ref} fits within {policy.policy_id}@{policy.policy_version}",
            policy_version=policy.policy_version,
        )

    blocked = BudgetDecision(
        DispatchOutcome.BLOCKED,
        f"{request.action_ref} would exceed {policy.policy_id}@{policy.policy_version} in "
        f"{', '.join(exceeded)}; a supervisor may approve the overrun (§14.3)",
        policy_version=policy.policy_version,
        exceeded_dimensions=exceeded,
        escalation_available=True,
    )

    approval = request.approval
    if approval is None:
        return blocked

    def refuse(detail: str) -> BudgetDecision:
        return BudgetDecision(
            DispatchOutcome.BLOCKED,
            f"{request.action_ref} is over budget in {', '.join(exceeded)} and approval "
            f"{approval.approval_id} does not release it: {detail}",
            policy_version=policy.policy_version,
            exceeded_dimensions=exceeded,
            escalation_available=True,
        )

    # Authority first. An approval signed by someone with no standing is void whatever it says it
    # covers, and reporting a scope mismatch instead would describe the project's budget to a
    # stranger. Order affects the message, never the verdict -- every branch below refuses.
    unauthorised = _unauthorised(
        approval, request.approver, request.approver_membership, request.project_id
    )
    if unauthorised is not None:
        return refuse(unauthorised)

    if approval.approval_id in request.consumed_approval_ids:
        return refuse("it has already been used, and an approval authorises one action once")
    if approval.action_ref != request.action_ref:
        return refuse(
            f"it was granted for a different action ({approval.action_ref}); an approval that "
            "carries over is a standing permission nobody granted"
        )
    if approval.project_id != request.project_id:
        return refuse(f"it was granted for a different project ({approval.project_id})")
    if approval.episode_id != request.episode_id:
        return refuse(f"it was granted for a different episode ({approval.episode_id})")
    if approval.policy_id != policy.policy_id or approval.policy_version != policy.policy_version:
        return refuse(
            f"it was granted against policy version {approval.policy_id}@"
            f"{approval.policy_version}, and the caps in force are "
            f"{policy.policy_id}@{policy.policy_version}; what was approved is not what would run"
        )
    if request.now < approval.granted_at:
        return refuse("it is not yet valid")
    if request.now >= approval.expires_at:
        return refuse("it has expired")

    still_over = _overruns(policy, projected, headroom=approval.approved_overrun)
    if still_over:
        return refuse(
            f"the projected spend exceeds the approved overrun in {', '.join(still_over)}"
        )

    return BudgetDecision(
        DispatchOutcome.ALLOWED_BY_APPROVAL,
        f"{request.action_ref} exceeds {policy.policy_id}@{policy.policy_version} in "
        f"{', '.join(exceeded)}, released by approval {approval.approval_id} from "
        f"{approval.approver_actor_id}. This releases the budget only -- SEC-002, the §7.6 "
        "critique path and every other gate still apply",
        policy_version=policy.policy_version,
        exceeded_dimensions=exceeded,
        approval_id=approval.approval_id,
    )


@runtime_checkable
class BudgetApprovalClaims(Protocol):
    """Somewhere an approval can be *spent*, atomically, exactly once.

    §17.17.1 says an approval releases one action ONCE. A pure function cannot deliver that. The
    caller tells :func:`evaluate_budget` which approvals it believes are already spent, and two
    dispatches that both believe none are will both be told yes -- the same approval released twice,
    with each decision individually correct on the information it was given.

    So ``ONCE`` lives with the record. An implementation must make the transition from unconsumed to
    consumed indivisible; the SQL one does it in the ``WHERE`` clause of a single statement.
    """

    def claim(self, approval_id: str, action_ref: str, now: dt.datetime) -> bool:
        """Consume ``approval_id`` for ``action_ref``. ``True`` iff **this** call consumed it.

        Every losing caller -- already consumed, consumed by another action, unknown id -- gets
        ``False``. There is no partial success and no exception for the ordinary contention case,
        because a caller that must distinguish "I won" from "I lost" should not have to do it by
        catching.
        """
        ...


def authorize_dispatch(
    request: BudgetRequest, claims: BudgetApprovalClaims | None
) -> BudgetDecision:
    """Decide, and if the decision spends an approval, spend it -- atomically or not at all.

    The dispatch entry point. :func:`evaluate_budget` answers "what does the budget say", which is a
    question about the inputs and can be replayed. This answers "may this dispatch proceed now",
    which requires changing the world, and is therefore the one a caller about to make an
    LLM/tool call must use.

    ``claims`` has no default. Passing ``None`` is allowed and refuses any approval-dependent
    dispatch, which is the honest behaviour for a caller with nowhere to record consumption: the
    alternative is an approval that is single-use in the docstring and unlimited in fact. Making the
    parameter required means that choice is visible at the call site instead of inherited.

    An in-budget dispatch consumes nothing. The approval is only claimed when it is what makes the
    difference, so a supervisor's release is not silently burned by a call that did not need it.
    """
    decision = evaluate_budget(request)
    if decision.outcome is not DispatchOutcome.ALLOWED_BY_APPROVAL:
        return decision

    approval_id = decision.approval_id
    assert approval_id is not None, "ALLOWED_BY_APPROVAL always names the approval"

    if claims is None:
        return BudgetDecision(
            DispatchOutcome.BLOCKED,
            f"{request.action_ref} is over budget and approval {approval_id} would release it, but "
            "no claim store was supplied, so single use cannot be enforced. §17.17.1 makes ONCE "
            "part of what an approval is; an unenforceable ONCE is an unlimited approval",
            policy_version=decision.policy_version,
            exceeded_dimensions=decision.exceeded_dimensions,
            escalation_available=True,
        )

    if not claims.claim(approval_id, request.action_ref, request.now):
        return BudgetDecision(
            DispatchOutcome.BLOCKED,
            f"{request.action_ref} is over budget and approval {approval_id} could not be claimed: "
            "it was already consumed. An approval authorises one action once, and a concurrent "
            "dispatch that lost the race is refused rather than served a second release",
            policy_version=decision.policy_version,
            exceeded_dimensions=decision.exceeded_dimensions,
            escalation_available=True,
        )
    return decision


__all__ = [
    "APPROVER_ACTOR_TYPES",
    "BUDGET_OVERRUN_SCOPE",
    "BudgetApproval",
    "BudgetApprovalClaims",
    "BudgetDecision",
    "BudgetPolicy",
    "BudgetRequest",
    "DispatchOutcome",
    "authorize_dispatch",
    "evaluate_budget",
]
