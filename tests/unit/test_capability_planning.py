"""T-VER-002 — a backend with no descriptor may not be planned (§9.5, §17.18).

    T-VER-002  Planner 對無 capability descriptor 的 backend 不可規劃；有 descriptor 時依
               produces/requires match。

TWO CLAUSES, AND THE FIRST IS A NEGATIVE. A negative needs something to be absent from, so the
registry is the only source of candidates and `plan_for_backend` refuses rather than returning an
empty plan -- "nothing satisfies the goal" and "you asked about a backend nobody described" are
different answers, and only the second is VER-002's.

VER-002's SECOND SENTENCE -- "sufficient candidate 有明確 state-transition/blocked-conflict
criterion" -- is `lab_brain.core.sufficiency.evaluate_sufficiency`, which M0b built for VER-006 and
which returns exactly that criterion. The planner calls it and does not reimplement it; the test at
the bottom pins that there is no second definition of "sufficient" in this module.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from lab_brain.core.models.capability import ActionType, Availability, Capability
from lab_brain.core.models.cost import CostVector
from lab_brain.verification.capability_registry import (
    CapabilityNotRegistered,
    CapabilityRegistrationError,
    CapabilityRegistry,
)
from lab_brain.verification.planner import (
    NO_DESCRIPTOR,
    REQUIRES_UNSATISFIED,
    UNAVAILABLE,
    PlanningRefused,
    VerificationPlanner,
)
from tests.refusals import refused

pytestmark = [pytest.mark.requirement("VER-002"), pytest.mark.spec_test("T-VER-002")]

CONTRACT = "cost:test@1.0.0"


def _estimator(params: Mapping[str, Any]) -> CostVector:
    return CostVector(wall_clock_s=int(params.get("seconds", 10)), license_seat_s=5)


def _capability(**overrides: object) -> Capability:
    payload: dict[str, object] = {
        "capability_id": "cap:sim",
        "action_type": ActionType.SIMULATION,
        "backend_id": "backend.described",
        "requires": ("in.device",),
        "produces": ("out.impedance",),
        "authority_class": "TIER_A",
        "estimate_cost_contract": CONTRACT,
        "version": "1.0.0",
    }
    payload.update(overrides)
    return Capability.model_validate(payload)


def _registry(*capabilities: Capability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register_estimator(CONTRACT, _estimator)
    for capability in capabilities or (_capability(),):
        registry.register(capability)
    return registry


# ---------------------------------------------------------------------------
# Clause 1 — no descriptor, no planning
# ---------------------------------------------------------------------------


def test_a_backend_with_no_descriptor_cannot_be_planned():
    """THE clause, and it RAISES rather than planning emptily.

    An empty plan is ambiguous -- it is also what "no candidate satisfies this goal" looks like --
    and the operational meanings are opposite: the first is a normal outcome, the second is a
    registration defect that silently excludes a backend from every plan until someone notices.
    """
    planner = VerificationPlanner(_registry())
    with pytest.raises(PlanningRefused) as raised:
        planner.plan_for_backend(
            "backend.undescribed", goal=("out.impedance",), available=frozenset({"in.device"})
        )
    assert raised.value.reason == NO_DESCRIPTOR
    assert "MUST NOT be planned" in raised.value.detail


def test_a_described_backend_plans():
    """The positive control. Without it, "refuse everything" satisfies the test above."""
    planner = VerificationPlanner(_registry())
    actions = planner.plan_for_backend(
        "backend.described", goal=("out.impedance",), available=frozenset({"in.device"})
    )
    assert [action.capability_id for action in actions] == ["cap:sim"]


def test_an_unregistered_capability_raises_rather_than_returning_none():
    with pytest.raises(CapabilityNotRegistered, match="MUST NOT be planned"):
        _registry().resolve("cap:nobody")


def test_a_capability_with_no_registered_estimator_cannot_be_registered():
    """Plannable and unpriceable is the failure that surfaces when a plan needs a number."""
    registry = CapabilityRegistry()
    with pytest.raises(CapabilityRegistrationError, match="is not registered"):
        registry.register(_capability())


# ---------------------------------------------------------------------------
# Clause 2 — produces / requires match
# ---------------------------------------------------------------------------


def test_matching_is_on_produces():
    planner = VerificationPlanner(_registry())
    assert planner.plan(goal=("out.something_else",), available=frozenset({"in.device"})) == ()
    assert planner.plan(goal=("out.impedance",), available=frozenset({"in.device"}))


def test_matching_is_also_on_requires_and_that_half_is_the_one_easy_to_drop():
    """A capability that produces the goal but needs an input nobody has is not a candidate.

    Planning it would put an action in the plan that cannot start, and the plan's cost estimate
    would then be a lower bound on something else entirely.
    """
    planner = VerificationPlanner(_registry())
    assert planner.plan(goal=("out.impedance",), available=frozenset()) == ()
    assert planner.plan(goal=("out.impedance",), available=frozenset({"in.device"}))


def test_an_unavailable_capability_is_not_a_candidate_and_a_degraded_one_is():
    """§17.24's distinction: DEGRADED waits, UNAVAILABLE is not planned."""
    registry = _registry(_capability(availability=Availability.DEGRADED))
    assert VerificationPlanner(registry).plan(
        goal=("out.impedance",), available=frozenset({"in.device"})
    )

    registry.set_availability("cap:sim", Availability.UNAVAILABLE)
    assert (
        VerificationPlanner(registry).plan(
            goal=("out.impedance",), available=frozenset({"in.device"})
        )
        == ()
    )


def test_require_reports_which_refusal_applies():
    """One gate, three reason codes, so a caller does not re-derive the distinction."""
    registry = _registry()
    planner = VerificationPlanner(registry)

    with pytest.raises(PlanningRefused) as unknown:
        planner.require("cap:nobody")
    assert unknown.value.reason == NO_DESCRIPTOR

    with pytest.raises(PlanningRefused) as unsatisfied:
        planner.require("cap:sim", available=frozenset())
    assert unsatisfied.value.reason == REQUIRES_UNSATISFIED

    registry.set_availability("cap:sim", Availability.UNAVAILABLE)
    with pytest.raises(PlanningRefused) as down:
        planner.require("cap:sim", available=frozenset({"in.device"}))
    assert down.value.reason == UNAVAILABLE


def test_planning_is_deterministic_and_not_ranked_by_a_scalar():
    """VER-003's prohibition applied to the planner, not only to the ledger.

    Candidates come back in a declared order and carry the whole `CostVector`. A planner that
    sorted by one number would have made the decision VER-003 forbids before `SelectionPolicy`
    (VER-005) ever saw the list.
    """
    cheap = _capability(capability_id="cap:cheap", backend_id="b.cheap")
    dear = _capability(capability_id="cap:dear", backend_id="b.dear")
    planner = VerificationPlanner(_registry(dear, cheap))

    first = planner.plan(goal=("out.impedance",), available=frozenset({"in.device"}))
    second = planner.plan(goal=("out.impedance",), available=frozenset({"in.device"}))
    assert (
        [a.capability_id for a in first]
        == [a.capability_id for a in second]
        == [
            "cap:cheap",
            "cap:dear",
        ]
    )
    assert all(isinstance(action.cost, CostVector) for action in first)
    assert not hasattr(first[0], "normalized_cost")


def test_the_estimator_is_resolved_by_name_and_produces_a_cost_vector():
    """§9.5's `estimate_cost(params) -> CostVector`, through the contract name on the descriptor."""
    registry = _registry()
    cost = registry.estimate("cap:sim", {"seconds": 45})
    assert cost.wall_clock_s == 45
    assert cost.license_seat_s == 5


def test_a_capability_cannot_be_priced_unless_it_could_also_be_planned():
    with pytest.raises(CapabilityNotRegistered):
        _registry().estimate("cap:nobody", {})


# ---------------------------------------------------------------------------
# §9.5 — the planner does not know backend names
# ---------------------------------------------------------------------------


def test_the_planner_never_reads_a_backend_id():
    """§9.5: Planner 只讀 Capability descriptor，不知道 backend 名稱.

    `backend_id` is on the descriptor because §17.18 declares it and a Run manifest needs it. What
    is forbidden is the planner *reasoning* about the value, so this parses the module and fails if
    any expression in it reads the attribute. `plan_for_backend` takes a backend id as an argument
    and passes it straight to the registry, which is a lookup rather than a judgement.
    """
    import ast
    import inspect

    import lab_brain.verification.planner as planner_module

    tree = ast.parse(inspect.getsource(planner_module))
    reads = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "backend_id"
    ]
    assert not reads, (
        f"the planner reads Capability.backend_id at {reads}; §9.5 says it does not know backend "
        "names, and a ranking that consulted one would be ranking by solver"
    )


def test_the_planner_declares_no_second_notion_of_sufficiency():
    """VER-002's second clause is `core.sufficiency`, not a copy of it here.

    §8.2.1 allows one definition of when a belief may move. A planner with its own would be a
    second, and the two would agree until one of them was corrected.
    """
    import ast
    import inspect

    import lab_brain.verification.planner as planner_module

    tree = ast.parse(inspect.getsource(planner_module))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and "sufficien" in node.name.lower()
    }
    assert not defined, (
        f"the planner defines {defined}; `evaluate_sufficiency` in core.sufficiency is VER-002's "
        "state-transition/blocked-conflict criterion and there may be only one"
    )


# ---------------------------------------------------------------------------
# §17.18 — the descriptor itself
# ---------------------------------------------------------------------------


def test_a_capability_that_produces_nothing_is_refused():
    with refused("declares no `produces`"):
        _capability(produces=())


def test_a_capability_cannot_require_what_it_produces():
    with refused("would schedule it against itself"):
        _capability(requires=("out.impedance",))


def test_only_an_externally_contended_action_may_declare_a_license_constraint():
    """§10.7's WAITING_RESOURCE is for a finite external resource, not for a repository read."""
    with refused("park work in WAITING_RESOURCE for a resource that does not exist"):
        _capability(
            action_type=ActionType.EXISTING_EVIDENCE_LOOKUP,
            license_constraints=("license:seat",),
        )
    assert _capability(
        action_type=ActionType.MEASUREMENT, license_constraints=("license:seat",)
    ).license_constraints


def test_a_descriptor_may_not_be_replaced_in_place():
    """§17.18 versions the descriptor, so a change gets a version and a past plan stays valid."""
    registry = _registry()
    with pytest.raises(CapabilityRegistrationError, match="unreproducible"):
        registry.register(_capability(version="2.0.0"))


def test_availability_is_state_and_may_change_without_a_version():
    """A licence server going busy is not a new capability."""
    registry = _registry()
    updated = registry.set_availability("cap:sim", Availability.DEGRADED)
    assert updated.availability is Availability.DEGRADED
    assert updated.version == "1.0.0"
    assert registry.resolve("cap:sim").availability is Availability.DEGRADED


def test_earliest_available_at_round_trips_for_ops_002():
    """§17.18's field feeding OPS-002's `earliest_available_at`. Present, typed, not a string."""
    when = dt.datetime(2026, 9, 24, 8, 0, tzinfo=dt.UTC)
    assert _capability(earliest_available_at=when).earliest_available_at == when


def test_the_cost_contract_cannot_be_replaced_in_place():
    registry = _registry()

    def other(params: Mapping[str, Any]) -> CostVector:
        return CostVector(money_estimate=Decimal("1"))

    with pytest.raises(CapabilityRegistrationError, match="reprice every past estimate"):
        registry.register_estimator(CONTRACT, other)
