"""COST-001: nothing dispatches before the budget is checked, and cost is never one number.

    §17.17  Before each LLM/tool call, BudgetGate MUST check project/episode caps.
            Exceed -> refuse/escalate; never silently continue.
    §9.4    不得把全部成本壓縮成單一 `normalized_cost` 作為唯一決策依據 (VER-003).
    v3.3-a6 超出 session budget 時 BudgetGate MUST 提供 supervisor/human approval path,
            approval 本身記為帶 actor_id 的事件.

Three properties are easy to state and easy to lose:

*   **Gate before spend.** A ledger that records what already happened is accounting, not a gate.
    The decision has to be a function of an *estimate*, taken before the call.
*   **Cost stays a vector.** Six weeks of MPW shuttle is not "expensive", it is slow + irreversible
    + schedule-coupled. Any `total()` that returns a single number invites a comparison that throws
    those away, so this module must not offer one.
*   **Approval is scoped.** An approval that can be replayed onto a second action, or that survives
    its expiry, is a standing permission nobody granted.

Written before the implementation. Every negative case below is a way a plausible budget gate says
yes when it should not.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from lab_brain.core.budget import (
    BUDGET_OVERRUN_SCOPE,
    BudgetApproval,
    BudgetDecision,
    BudgetPolicy,
    BudgetRequest,
    DispatchOutcome,
    authorize_dispatch,
    evaluate_budget,
)
from lab_brain.core.models import (
    CAPPED_DIMENSIONS,
    Actor,
    ActorType,
    BudgetCaps,
    CostEntry,
    CostKind,
    CostVector,
    DependencyRisk,
    ProjectMembership,
)
from lab_brain.core.repositories import InMemoryBudgetApprovalClaims

pytestmark = [pytest.mark.requirement("COST-001"), pytest.mark.spec_test("T-COST-001")]

NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
EPISODE = "ep:rs-anomaly-1"
ACTOR = "actor:alice"
SUPERVISOR = "actor:prof-lin"
ACTION = "act:run_charge_dc_sweep#7"

POLICY = BudgetPolicy(
    policy_id="pol:session-default",
    policy_version="1.0.0",
    project_id=PROJECT,
    # human_minutes, token_count and license_seat_s are left unstated -- `None`, meaning this
    # policy does not constrain them. That is a different fact from a cap of zero; see
    # `test_a_cap_of_zero_permits_nothing` below, which is the pair this one must be read with.
    caps=BudgetCaps(wall_clock_s=3600, money_estimate=Decimal("50.00"), compute_units=100),
)


# A competent approver: an active human who is an active member of this project and has been
# granted budget authority explicitly. Every negative case below removes exactly one of those.
SUPERVISOR_ACTOR = Actor(actor_id=SUPERVISOR, actor_type=ActorType.HUMAN, display_name="Prof. Lin")
SUPERVISOR_MEMBERSHIP = ProjectMembership(
    actor_id=SUPERVISOR,
    project_id=PROJECT,
    role="supervisor",
    approval_scopes=frozenset({BUDGET_OVERRUN_SCOPE}),
)


def request(**overrides: object) -> BudgetRequest:
    defaults: dict[str, object] = {
        "action_ref": ACTION,
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "actor_id": ACTOR,
        "estimate": CostVector(wall_clock_s=60, money_estimate=Decimal("1.00")),
        "consumed": CostVector(),
        "policy": POLICY,
        "approval": None,
        "approver": SUPERVISOR_ACTOR,
        "approver_membership": SUPERVISOR_MEMBERSHIP,
        "now": NOW,
    }
    defaults.update(overrides)
    return BudgetRequest(**defaults)  # type: ignore[arg-type]


def over_budget(**overrides: object) -> BudgetRequest:
    """A request that needs an approval, so the approver checks are actually reached."""
    defaults: dict[str, object] = {
        "estimate": CostVector(money_estimate=Decimal("75.00")),
        "approval": approval(),
    }
    defaults.update(overrides)
    return request(**defaults)


def approval(**overrides: object) -> BudgetApproval:
    defaults: dict[str, object] = {
        "approval_id": "apr:1",
        "approver_actor_id": SUPERVISOR,
        "project_id": PROJECT,
        "episode_id": EPISODE,
        "action_ref": ACTION,
        "policy_id": POLICY.policy_id,
        "policy_version": POLICY.policy_version,
        "approved_overrun": CostVector(money_estimate=Decimal("100.00")),
        "granted_at": NOW - dt.timedelta(minutes=5),
        "expires_at": NOW + dt.timedelta(minutes=30),
    }
    defaults.update(overrides)
    return BudgetApproval(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# Fail closed. Each is a way "we could not decide" could become "go ahead".
# --------------------------------------------------------------------------------------------


def test_a_request_with_no_policy_is_blocked():
    """No budget context is not an absent constraint. An unbudgeted project is not a free one."""
    decision = evaluate_budget(request(policy=None))
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "no budget policy" in decision.reason


def test_a_request_with_no_estimate_is_blocked():
    """The gate is a function of the estimate. Without one there is nothing to check against caps.

    This is the difference between a gate and a ledger: an unestimated call cannot be admitted on
    the promise of recording its cost afterwards.
    """
    decision = evaluate_budget(request(estimate=None))
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "no cost estimate" in decision.reason


def test_a_policy_for_another_project_is_blocked():
    """Checking the wrong project's caps is not checking caps."""
    decision = evaluate_budget(
        request(policy=POLICY.model_copy(update={"project_id": "prj:other"}))
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "different project" in decision.reason


def test_an_estimate_within_caps_is_allowed():
    """The gate must be passable, or it is a prohibition."""
    decision = evaluate_budget(request())
    assert decision.outcome is DispatchOutcome.ALLOWED
    assert decision.exceeded_dimensions == ()


# --------------------------------------------------------------------------------------------
# Exceeding caps: refuse or escalate, never silently continue.
# --------------------------------------------------------------------------------------------


def test_exceeding_a_cap_blocks_and_names_the_dimension():
    """ "Over budget" is not actionable. *Which* dimension, by how much, is."""
    decision = evaluate_budget(request(estimate=CostVector(money_estimate=Decimal("75.00"))))
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "money_estimate" in decision.exceeded_dimensions
    assert decision.escalation_available is True


def test_consumed_cost_counts_towards_the_cap():
    """Caps are on the session, not on the single call.

    A gate that only inspects the request lets a thousand individually-cheap calls through.
    """
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("10.00")),
            consumed=CostVector(money_estimate=Decimal("45.00")),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "money_estimate" in decision.exceeded_dimensions


def test_every_capped_dimension_is_enforced_independently():
    """One dimension over is over. There is no trading wall-clock against money."""
    for dimension, estimate in (
        ("wall_clock_s", CostVector(wall_clock_s=7200)),
        ("money_estimate", CostVector(money_estimate=Decimal("999"))),
        ("compute_units", CostVector(compute_units=500)),
    ):
        decision = evaluate_budget(request(estimate=estimate))
        assert decision.outcome is DispatchOutcome.BLOCKED, dimension
        assert dimension in decision.exceeded_dimensions, dimension


def test_an_uncapped_dimension_does_not_block():
    """A cap of None is "not limited here", and must not be read as a cap of zero."""
    decision = evaluate_budget(request(estimate=CostVector(human_minutes=600)))
    assert decision.outcome is DispatchOutcome.ALLOWED


# --------------------------------------------------------------------------------------------
# A cap of zero. `v3.3-a10` / §17.19.1.
#
# This is the pair of tests the old implementation could not pass, and the reason it could not is
# worth stating: `caps` was a CostVector, every dimension of which defaults to 0, so `cap_for()`
# could not tell "this policy says nothing about tokens" from "this policy permits no tokens". It
# resolved the ambiguity as *uncapped* -- and a budget deliberately frozen at zero admitted
# everything. The failure is silent, unbounded, and in the one direction a budget exists to prevent.
# --------------------------------------------------------------------------------------------


def test_a_cap_of_zero_permits_nothing():
    """`0` is a cap, not a missing cap. Any spend in that dimension is over it."""
    frozen = POLICY.model_copy(update={"caps": BudgetCaps(money_estimate=Decimal("0"))})
    decision = evaluate_budget(
        request(estimate=CostVector(money_estimate=Decimal("0.01")), policy=frozen)
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "money_estimate" in decision.exceeded_dimensions


def test_a_cap_of_zero_blocks_every_capped_dimension_independently():
    """One frozen dimension is enough, and freezing one must not depend on freezing the rest."""
    for dimension in CAPPED_DIMENSIONS:
        amount = Decimal("1") if dimension == "money_estimate" else 1
        frozen = POLICY.model_copy(update={"caps": BudgetCaps(**{dimension: 0})})
        decision = evaluate_budget(
            request(estimate=CostVector(**{dimension: amount}), policy=frozen)
        )
        assert decision.outcome is DispatchOutcome.BLOCKED, dimension
        assert dimension in decision.exceeded_dimensions, dimension


def test_a_cap_of_zero_admits_a_zero_estimate():
    """The cap must be satisfiable at zero, or it is a prohibition rather than a cap.

    A free action -- an in-memory lookup with no token, no money and no seat -- is still admissible
    under a frozen budget. If this failed, "cap of zero" would mean "gate closed", and the two are
    not the same rule.
    """
    frozen = POLICY.model_copy(update={"caps": BudgetCaps(token_count=0)})
    decision = evaluate_budget(request(estimate=CostVector(), policy=frozen))
    assert decision.outcome is DispatchOutcome.ALLOWED


def test_an_unstated_cap_and_a_zero_cap_are_different_values():
    """At the model, before any gate logic: the type must be able to hold both."""
    assert BudgetCaps().cap_for("token_count") is None
    assert BudgetCaps(token_count=0).cap_for("token_count") == 0


def test_caps_are_not_a_cost_vector():
    """Pinned, because reuse is what caused the bug.

    `CostVector` defaults every additive dimension to zero so a partial *estimate* stays usable.
    Caps need the opposite default, and a type that has to serve both ends up guessing.
    """
    assert not isinstance(POLICY.caps, CostVector)
    with pytest.raises(ValueError, match="not a cappable dimension"):
        BudgetCaps().cap_for("irreversible")


def test_a_zero_cap_can_still_be_released_by_an_approval():
    """A frozen budget is a budget, so §14.3's approval path applies to it unchanged."""
    frozen = POLICY.model_copy(update={"caps": BudgetCaps(money_estimate=Decimal("0"))})
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("10.00")),
            policy=frozen,
            approval=approval(approved_overrun=CostVector(money_estimate=Decimal("10.00"))),
        )
    )
    assert decision.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL


# --------------------------------------------------------------------------------------------
# Tokens are a dimension of their own. `v3.3-a10` / COST-001.
# --------------------------------------------------------------------------------------------


def test_tokens_are_capped_and_accumulate():
    """COST-001 names tokens among the ledger's minimum dimensions, so the gate must see them."""
    policy = POLICY.model_copy(update={"caps": BudgetCaps(token_count=1000)})
    decision = evaluate_budget(
        request(
            estimate=CostVector(token_count=400),
            consumed=CostVector(token_count=700),
            policy=policy,
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "token_count" in decision.exceeded_dimensions


def test_tokens_are_not_compute_units():
    """The substitution v3.3-a10 forbids, asserted rather than trusted.

    If tokens were folded into `compute_units`, a token-only estimate would consume the compute cap
    and a compute cap would silently limit tokens. Both directions are checked, because either
    would mean one integer is answering two questions.
    """
    tokens_only = CostVector(token_count=10_000)
    assert tokens_only.compute_units == 0

    compute_capped = POLICY.model_copy(update={"caps": BudgetCaps(compute_units=1)})
    assert (
        evaluate_budget(request(estimate=tokens_only, policy=compute_capped)).outcome
        is DispatchOutcome.ALLOWED
    )

    token_capped = POLICY.model_copy(update={"caps": BudgetCaps(token_count=1)})
    assert (
        evaluate_budget(
            request(estimate=CostVector(compute_units=10_000), policy=token_capped)
        ).outcome
        is DispatchOutcome.ALLOWED
    )

    assert tokens_only.plus(CostVector(token_count=5)).token_count == 10_005


# --------------------------------------------------------------------------------------------
# Approval: scoped, single-purpose, expiring.
# --------------------------------------------------------------------------------------------


def test_a_scoped_approval_unblocks_the_overrun():
    """v3.3-a6: an implementation that only ever refuses does not satisfy COST-001."""
    decision = evaluate_budget(
        request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval())
    )
    assert decision.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL
    assert decision.approval_id == "apr:1"
    assert SUPERVISOR in decision.reason, "the decision must record who authorised the overrun"


def test_an_approval_for_a_different_action_is_refused():
    """The replay case. One approval, one action.

    Without this, a supervisor approving an expensive sweep silently authorises every later call in
    the session -- which is a standing permission nobody granted.
    """
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(action_ref="act:something_else#1"),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "different action" in decision.reason


def test_an_approval_for_a_different_project_is_refused():
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(project_id="prj:other"),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "different project" in decision.reason


def test_an_approval_for_a_different_episode_is_refused():
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(episode_id="ep:other"),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "different episode" in decision.reason


def test_an_expired_approval_is_refused():
    """An approval that outlives its window is a standing permission."""
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(expires_at=NOW - dt.timedelta(seconds=1)),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "expired" in decision.reason


def test_an_approval_from_the_future_is_refused():
    """Clock skew or a fabricated record must not pre-authorise anything."""
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(granted_at=NOW + dt.timedelta(minutes=1)),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "not yet valid" in decision.reason


def test_an_already_consumed_approval_is_refused():
    """Single use. Re-presenting the same approval must not buy a second overrun."""
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(),
            consumed_approval_ids=frozenset({"apr:1"}),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "already been used" in decision.reason


def test_an_approval_against_a_superseded_policy_version_is_refused():
    """Caps changed after the approval was granted, so what was approved is no longer what runs."""
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("75.00")),
            approval=approval(policy_version="0.9.0"),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "policy version" in decision.reason


def test_an_approval_does_not_cover_an_overrun_larger_than_it_authorised():
    """An approval is for an amount, not a blank cheque."""
    decision = evaluate_budget(
        request(
            estimate=CostVector(money_estimate=Decimal("5000.00")),
            approval=approval(approved_overrun=CostVector(money_estimate=Decimal("100.00"))),
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "exceeds the approved overrun" in decision.reason


def test_an_approval_is_not_consulted_when_nothing_is_over_budget():
    """An in-budget call must not consume an approval it did not need."""
    decision = evaluate_budget(request(approval=approval()))
    assert decision.outcome is DispatchOutcome.ALLOWED
    assert decision.approval_id is None


# --------------------------------------------------------------------------------------------
# Who signed it. §14.3 / §14.4.
#
# Before P5-fix the only thing checked about `approver_actor_id` was that the string was there. Any
# caller able to build a BudgetApproval could name any id and release any overrun, which made the
# §14.3 supervisor path decorative. Each test below removes exactly one of the four facts an
# approver needs, leaving the other three intact, so a single check going missing cannot hide
# behind its neighbours.
# --------------------------------------------------------------------------------------------


def test_an_approval_whose_approver_cannot_be_resolved_is_refused():
    """An approval nobody can be identified as having given is an unsigned one."""
    decision = evaluate_budget(over_budget(approver=None, approver_membership=None))
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "could not be resolved" in decision.reason


def test_an_approval_naming_one_actor_and_carrying_another_is_refused():
    """The gate is the last line: a repository returning a neighbouring row is not authorisation."""
    someone_else = SUPERVISOR_ACTOR.model_copy(update={"actor_id": "actor:someone-else"})
    decision = evaluate_budget(over_budget(approver=someone_else))
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "not the actor:prof-lin the approval names" in decision.reason


def test_an_inactive_approver_is_refused():
    """Disabling an account suspends its authority everywhere at once. That is what it is for."""
    decision = evaluate_budget(
        over_budget(approver=SUPERVISOR_ACTOR.model_copy(update={"active": False}))
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "not active" in decision.reason


@pytest.mark.parametrize("actor_type", [ActorType.SERVICE, ActorType.AGENT_ROLE])
def test_a_non_human_approver_is_refused(actor_type):
    """The self-signing case. §14.3 makes the overrun path a supervisor/human decision.

    An agent role that can approve its own overrun has no budget, only a formality -- and it is the
    agent, not a person, that the cap exists to constrain.
    """
    decision = evaluate_budget(
        over_budget(approver=SUPERVISOR_ACTOR.model_copy(update={"actor_type": actor_type}))
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert actor_type.value in decision.reason
    assert "supervisor/human" in decision.reason


def test_an_approver_with_no_membership_of_the_project_is_refused():
    """Authority over one project's budget is not authority over another's."""
    decision = evaluate_budget(over_budget(approver_membership=None))
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "no membership of" in decision.reason


def test_an_approver_whose_membership_is_for_another_project_is_refused():
    """The cross-project case, checked rather than trusted from the caller's lookup."""
    decision = evaluate_budget(
        over_budget(
            approver_membership=SUPERVISOR_MEMBERSHIP.model_copy(update={"project_id": "prj:other"})
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "prj:other" in decision.reason


def test_an_approver_whose_membership_was_revoked_is_refused():
    """The row survives revocation so the audit trail does; the authority does not."""
    decision = evaluate_budget(
        over_budget(approver_membership=SUPERVISOR_MEMBERSHIP.model_copy(update={"active": False}))
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "not active" in decision.reason


def test_an_approver_without_budget_authority_is_refused():
    """Being a member is not being an approver. §14.4 makes approval authority a separate grant.

    This is the case a role-name comparison would have let through: a project lead with every
    clearance and no budget scope is exactly the person who looks authorised and is not.
    """
    decision = evaluate_budget(
        over_budget(
            approver_membership=SUPERVISOR_MEMBERSHIP.model_copy(
                update={"approval_scopes": frozenset({"REVIEW_QUEUE"})}
            )
        )
    )
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert BUDGET_OVERRUN_SCOPE in decision.reason
    assert "REVIEW_QUEUE" in decision.reason


def test_the_default_membership_grants_no_budget_authority():
    """Fail closed at construction: `approval_scopes` defaults to empty, as does the DB column."""
    assert (
        BUDGET_OVERRUN_SCOPE
        not in ProjectMembership(
            actor_id=SUPERVISOR, project_id=PROJECT, role="supervisor"
        ).approval_scopes
    )


# --------------------------------------------------------------------------------------------
# ONCE is a property of the record, not of the caller's memory. §17.17.1.
# --------------------------------------------------------------------------------------------


def test_authorize_dispatch_claims_the_approval_it_spends():
    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:1", ACTION)
    decision = authorize_dispatch(over_budget(), claims)
    assert decision.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL
    assert claims.consumed_at("apr:1") == NOW


def test_a_second_dispatch_with_the_same_approval_is_refused_even_if_the_caller_forgot():
    """The bug the `consumed_approval_ids` hint could not close.

    The second call passes the *same* request -- empty `consumed_approval_ids` and all -- so the
    pure gate has no way to know. Only the store does, and it must be the thing that says no.
    """
    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:1", ACTION)
    first = authorize_dispatch(over_budget(), claims)
    second = authorize_dispatch(over_budget(), claims)
    assert first.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL
    assert second.outcome is DispatchOutcome.BLOCKED
    assert "already consumed" in second.reason


def test_concurrent_dispatches_of_one_approval_produce_exactly_one_winner():
    """Sequential single use is easy. This is the property that needs the lock.

    Eight threads released together onto one approval. Any implementation that checks and then
    writes -- rather than testing and setting under one lock -- lets more than one through here.
    """
    import concurrent.futures

    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:1", ACTION)
    start = __import__("threading").Barrier(8)

    def attempt() -> DispatchOutcome:
        start.wait()
        return authorize_dispatch(over_budget(), claims).outcome

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = [future.result() for future in [pool.submit(attempt) for _ in range(8)]]

    assert outcomes.count(DispatchOutcome.ALLOWED_BY_APPROVAL) == 1, outcomes
    assert outcomes.count(DispatchOutcome.BLOCKED) == 7


def test_an_approval_cannot_be_claimed_for_an_action_it_was_not_granted_for():
    """Belt and braces with the gate's own `action_ref` check, at the other end of the path."""
    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:1", "act:something_else#1")
    assert claims.claim("apr:1", ACTION, NOW) is False


def test_claiming_an_unknown_approval_fails_rather_than_succeeding_silently():
    assert InMemoryBudgetApprovalClaims().claim("apr:ghost", ACTION, NOW) is False


def test_dispatch_without_a_claim_store_refuses_an_approval_dependent_call():
    """Fail closed. An approval that is single-use in the docstring is unlimited in fact."""
    decision = authorize_dispatch(over_budget(), None)
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert "no claim store" in decision.reason


def test_an_in_budget_dispatch_consumes_no_approval():
    """A supervisor's release must not be burned by a call that did not need it."""
    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:1", ACTION)
    decision = authorize_dispatch(request(approval=approval()), claims)
    assert decision.outcome is DispatchOutcome.ALLOWED
    assert claims.consumed_at("apr:1") is None


def test_a_refused_approval_is_not_consumed():
    """Losing on authority must not spend the approval; the overrun was never released."""
    claims = InMemoryBudgetApprovalClaims()
    claims.register("apr:1", ACTION)
    decision = authorize_dispatch(over_budget(approver=None, approver_membership=None), claims)
    assert decision.outcome is DispatchOutcome.BLOCKED
    assert claims.consumed_at("apr:1") is None


# --------------------------------------------------------------------------------------------
# Approval relieves the BUDGET block and nothing else.
# --------------------------------------------------------------------------------------------


def test_a_budget_approval_does_not_authorise_dispatch_on_its_own():
    """The decision says the budget permits, not that the action may run.

    §14.3 lists several gates. A supervisor releasing a budget must not be readable as clearing
    the fabrication gate, the critique path or an ACL. Named `budget_permits` rather than
    `allowed` so a caller cannot mistake one for the other.
    """
    decision = evaluate_budget(
        request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval())
    )
    assert decision.budget_permits is True
    assert not hasattr(decision, "allowed"), (
        "a budget decision must not expose a bare `allowed`; it answers one question of several"
    )


def test_a_budget_approval_does_not_relieve_the_critique_gate():
    """§7.6's independent critique path is a different gate with a different authority.

    Checked against the real gate rather than asserted, because "these are separate" is exactly
    the kind of claim that rots once someone wires the two together.
    """
    from lab_brain.core.critique_gate import (
        DispatchRequest,
        Reversibility,
        evaluate_dispatch,
    )

    budget = evaluate_budget(
        request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval())
    )
    assert budget.budget_permits is True

    critique = evaluate_dispatch(
        DispatchRequest(action_id=ACTION, reversibility=Reversibility.IRREVERSIBLE)
    )
    assert not critique.allowed, (
        "a budget approval must not make an irreversible action dispatchable without critique"
    )


# --------------------------------------------------------------------------------------------
# Cost is a vector. VER-003 / §9.4.
# --------------------------------------------------------------------------------------------


def test_cost_vector_carries_every_spec_dimension():
    """§9.4's nine dimensions, by name. A missing one is a cost the planner cannot see.

    Nine since `v3.3-a10` added `token_count`. This list is written out rather than read from the
    spec on purpose -- `tests/spec/test_schema_drift.py` does the derived comparison, and a test
    that derived its expectation from the same document would agree with any amendment, including
    one that deleted a dimension.
    """
    for field in (
        "wall_clock_s",
        "human_minutes",
        "money_estimate",
        "compute_units",
        "token_count",
        "license_seat_s",
        "earliest_available_at",
        "irreversible",
        "dependency_risk",
    ):
        assert field in CostVector.model_fields, f"§9.4 declares {field}"


def test_cost_vector_offers_no_scalar_collapse():
    """VER-003. The absence is the feature.

    A `total()` or `normalized_cost` would be used for comparison the moment it existed, and a
    six-week irreversible shuttle would sort next to a long cheap simulation.
    """
    for forbidden in ("total", "normalized_cost", "scalar", "sum", "__lt__", "__gt__"):
        assert not hasattr(CostVector, forbidden) or forbidden.startswith("__"), forbidden
    vector = CostVector(wall_clock_s=10, money_estimate=Decimal("1"))
    with pytest.raises(TypeError):
        _ = vector < CostVector(wall_clock_s=20)  # type: ignore[operator]


def test_irreversible_and_waiting_time_are_not_costs_to_be_averaged():
    """They are qualifiers, not magnitudes -- the point §9.4 makes with the MPW example."""
    shuttle = CostVector(
        wall_clock_s=3_628_800,
        irreversible=True,
        earliest_available_at=NOW + dt.timedelta(weeks=6),
        dependency_risk=DependencyRisk.HIGH,
    )
    assert shuttle.irreversible is True
    assert shuttle.earliest_available_at is not None
    assert shuttle.dependency_risk is DependencyRisk.HIGH


# --------------------------------------------------------------------------------------------
# Ledger and determinism.
# --------------------------------------------------------------------------------------------


def test_a_cost_entry_records_estimate_and_actual_separately():
    """Both, and distinguishable. An estimate overwritten by the actual loses the gate's input."""
    estimated = CostEntry(
        cost_entry_id="cost:1",
        project_id=PROJECT,
        episode_id=EPISODE,
        actor_or_slot=ACTOR,
        action_ref=ACTION,
        cost_kind=CostKind.ESTIMATED,
        cost=CostVector(money_estimate=Decimal("1.00")),
        recorded_at=NOW,
    )
    actual = estimated.model_copy(
        update={
            "cost_entry_id": "cost:2",
            "cost_kind": CostKind.ACTUAL,
            "cost": CostVector(money_estimate=Decimal("1.37")),
        }
    )
    assert estimated.cost_kind is CostKind.ESTIMATED
    assert actual.cost_kind is CostKind.ACTUAL
    assert estimated.action_ref == actual.action_ref == ACTION


def test_a_cost_entry_is_traceable_to_action_project_episode_and_actor():
    """COST-001: a cost nobody can attribute cannot be governed."""
    for field in ("action_ref", "project_id", "episode_id", "actor_or_slot", "cost_kind"):
        assert field in CostEntry.model_fields


def test_the_decision_is_deterministic():
    """Same inputs and policy version, same decision -- so an audit can replay it.

    `now` is an explicit input for this reason: a gate that reads the clock cannot be replayed.
    """
    args = request(estimate=CostVector(money_estimate=Decimal("75.00")), approval=approval())
    first, second = evaluate_budget(args), evaluate_budget(args)
    assert isinstance(first, BudgetDecision)
    assert (first.outcome, first.reason, first.exceeded_dimensions, first.approval_id) == (
        second.outcome,
        second.reason,
        second.exceeded_dimensions,
        second.approval_id,
    )


def test_the_decision_records_the_policy_version_it_was_made_under():
    """Caps change. A recorded decision that does not say which caps applied cannot be reviewed."""
    decision = evaluate_budget(request())
    assert decision.policy_version == POLICY.policy_version
