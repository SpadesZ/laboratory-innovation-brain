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

PURE AND DETERMINISTIC. No clock, no I/O. ``now`` is an input, so a recorded decision can be
replayed from an audit record instead of re-derived against a system that has moved on.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.cost import CAPPED_DIMENSIONS, BudgetCaps, CostVector


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
    #: Approvals already spent. Single use is enforced here rather than by mutating the approval,
    #: so the function stays pure and the caller owns the record.
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


__all__ = [
    "BudgetApproval",
    "BudgetDecision",
    "BudgetPolicy",
    "BudgetRequest",
    "DispatchOutcome",
    "evaluate_budget",
]
