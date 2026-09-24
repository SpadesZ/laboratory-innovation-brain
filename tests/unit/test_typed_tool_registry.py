"""T-SIM-003 — the typed registry half, and §10.2.1's four prefix contracts.

    SIM-003    Tool invocation MUST occur through a typed ToolRegistry. No tool, Capability or
               backend adapter may expose an arbitrary script-execution entry point
               (`eval_script`-class public interface). Untyped execution paths MUST be rejected
               by static conformance test.
    T-SIM-003  static test rejects any public tool/Capability/backend-adapter interface accepting
               arbitrary script or code text for execution (`eval_script`-class); every tool
               invocation resolves through the typed ToolRegistry.

TWO CLAUSES, AND UNTIL M2 ONLY ONE WAS TESTABLE. `tests/unit/test_no_arbitrary_script_execution.py`
has held the first clause since M0a and was deliberately left UNMARKED, because marking it would
have claimed SIM-003 discharged on half its pass condition -- its own docstring says so. The second
clause needs a registry to exist. It does now, so this file holds the second half and the marker
moves onto both.

THE WEAKEST FORM OF THE `eval_script` HAZARD IS NOT `exec()`. It is a tool boundary that accepts an
untyped payload and lets the implementation decide what it means: no forbidden name appears, the
static scan passes, and the contract is still the caller's to define. So the tests below are about
what the registry REFUSES -- a foreign request type, an implementation with no declared models, a
result of an undeclared type -- rather than about what it permits.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from lab_brain.core.models.validation import ValidationReport, report
from lab_brain.spec import repo_root
from lab_brain.tools.contracts import (
    RETIRED_TOOL_ID,
    ToolClass,
    ToolDescriptor,
    ToolRequest,
    ToolResult,
)
from lab_brain.tools.dispatch import BudgetedToolDispatcher
from lab_brain.tools.registry import (
    ToolInvocationError,
    ToolNotRegistered,
    ToolRegistrationError,
    ToolRegistry,
)
from tests.refusals import refused

pytestmark = [pytest.mark.requirement("SIM-003"), pytest.mark.spec_test("T-SIM-003")]


class Ping(ToolRequest):
    value: int


class Pong(ToolResult):
    doubled: int


class Elsewhere(ToolRequest):
    value: int


class DoublingTool:
    @property
    def request_model(self) -> type[Ping]:
        return Ping

    @property
    def result_model(self) -> type[Pong]:
        return Pong

    def __call__(self, request: ToolRequest) -> Pong:
        assert isinstance(request, Ping)
        return Pong(tool_id="DOM-TST-TOOL-001", tool_version="1.0.0", doubled=request.value * 2)


def _descriptor(**overrides: object) -> ToolDescriptor:
    payload: dict[str, object] = {
        "tool_id": "DOM-TST-TOOL-001",
        "name": "inspect_thing",
        "tool_class": ToolClass.INSPECT,
        "domain": "testing",
        "version": "1.0.0",
        # Required for every non-`run_*` tool: COST-001 gates each tool call, and a tool with no
        # price cannot pass a gate that decides from an estimate. See the budget probes in
        # tests/unit/test_budgeted_tool_dispatch.py.
        "cost_contract": "cost:test.local@1.0.0",
        "produces": ("test.thing",),
    }
    payload.update(overrides)
    return ToolDescriptor.model_validate(payload)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_descriptor(), DoublingTool())
    return registry


# ---------------------------------------------------------------------------
# Clause 2 — every invocation resolves through the typed registry
# ---------------------------------------------------------------------------


def test_an_invocation_goes_through_the_registry_and_returns_the_declared_type():
    """The positive control. Without it every refusal below is satisfied by refusing everything."""
    result = _registry().invoke(
        "DOM-TST-TOOL-001", Ping(project_id="prj:t", trace_id="trc:t", value=21)
    )
    assert isinstance(result, Pong)
    assert result.doubled == 42


def test_a_request_of_the_wrong_type_is_refused_before_the_tool_sees_it():
    """THE clause. A foreign payload never reaches the implementation.

    Asserted with a tool that would raise if entered, so "refused" is not satisfied by an
    implementation that happened to reject the object itself -- the refusal has to be the
    registry's.
    """
    entered: list[object] = []

    class Fatal(DoublingTool):
        def __call__(self, request: ToolRequest) -> Pong:
            entered.append(request)
            raise AssertionError("the implementation was reached with a foreign payload")

    registry = ToolRegistry()
    registry.register(_descriptor(), Fatal())
    with pytest.raises(ToolInvocationError, match="takes Ping but was given Elsewhere"):
        registry.invoke(
            "DOM-TST-TOOL-001", Elsewhere(project_id="prj:t", trace_id="trc:t", value=1)
        )
    assert entered == []


def test_there_is_no_accessor_that_hands_out_an_implementation():
    """A registry that returned the callable would be a dictionary, and the type check optional.

    Structural: it walks the public surface rather than checking for one known method name, so
    re-adding the capability as `get_impl` or `resolve_callable` fails too.
    """
    registry = _registry()
    for name in dir(registry):
        if name.startswith("_"):
            continue
        member = getattr(registry, name)
        if not callable(member) or name in {"invoke", "register"}:
            continue
        try:
            value = member("DOM-TST-TOOL-001") if name not in {"tool_ids", "of_class"} else member
        except (TypeError, LookupError, AttributeError):
            continue
        assert not isinstance(value, DoublingTool), (
            f"ToolRegistry.{name} returns the implementation; handing the callable back moves the "
            "type check to the caller, and SIM-003 requires invocation to go THROUGH the registry"
        )


def test_an_unregistered_tool_raises_rather_than_returning_none():
    with pytest.raises(ToolNotRegistered, match="no tool is registered"):
        _registry().invoke("DOM-TST-TOOL-999", Ping(project_id="p", trace_id="t", value=1))


def test_an_implementation_with_an_untyped_boundary_cannot_be_registered():
    """The `eval_script` hazard in its weakest form: a payload the contract does not describe."""

    class Untyped:
        @property
        def request_model(self) -> type:
            return dict  # type: ignore[return-value]

        @property
        def result_model(self) -> type[Pong]:
            return Pong

        def __call__(self, request: ToolRequest) -> Pong:  # pragma: no cover - never registered
            raise AssertionError

    with pytest.raises(ToolRegistrationError, match="not a ToolRequest subclass"):
        ToolRegistry().register(_descriptor(), Untyped())  # type: ignore[arg-type]


def test_a_result_of_an_undeclared_type_is_refused():
    class Liar(DoublingTool):
        def __call__(self, request: ToolRequest) -> Pong:
            return "not a result"  # type: ignore[return-value]

    registry = ToolRegistry()
    registry.register(_descriptor(), Liar())
    with pytest.raises(ToolInvocationError, match="declared it returns Pong"):
        registry.invoke("DOM-TST-TOOL-001", Ping(project_id="p", trace_id="t", value=1))


def test_a_mis_stamped_result_is_refused():
    """§6.18's rollback selects by version, so a result stamped with the wrong one survives it."""

    class WrongVersion(DoublingTool):
        def __call__(self, request: ToolRequest) -> Pong:
            return Pong(tool_id="DOM-TST-TOOL-001", tool_version="9.9.9", doubled=0)

    registry = ToolRegistry()
    registry.register(_descriptor(), WrongVersion())
    with pytest.raises(ToolInvocationError, match="contamination rollback"):
        registry.invoke("DOM-TST-TOOL-001", Ping(project_id="p", trace_id="t", value=1))


# ---------------------------------------------------------------------------
# §10.2.1 — the prefix declares the contract
# ---------------------------------------------------------------------------


def test_a_name_that_contradicts_its_verb_class_is_refused():
    with refused("the prefix declares the contract"):
        _descriptor(tool_class=ToolClass.RUN, name="extract_thing")


def test_a_run_tool_must_name_a_capability_and_a_condition_schema():
    """`run_*` is backend-bound: unplannable without a Capability, uncomparable without a schema."""
    with refused("names no capability_id"):
        _descriptor(
            tool_class=ToolClass.RUN, name="run_thing", conditions_schema_version="d/s@1.0.0"
        )
    with refused("declares no conditions_schema_version"):
        _descriptor(tool_class=ToolClass.RUN, name="run_thing", capability_id="cap:x")


def test_an_extract_tool_may_not_name_a_backend_or_a_seat():
    """DOM-SP-002, structurally. "Backend-agnostic" is a descriptor that CANNOT name a backend."""
    with refused("Only `run_*` is backend-bound"):
        _descriptor(tool_class=ToolClass.EXTRACT, name="extract_thing", capability_id="cap:x")
    with refused("Only a backend execution contends"):
        _descriptor(
            tool_class=ToolClass.EXTRACT,
            name="extract_thing",
            requires=("x",),
            resource_id="license:seat",
        )


def test_an_extract_tool_must_declare_what_it_consumes():
    """An extractor with no declared input cannot be checked against a paired fixture."""
    with refused("declares no `requires`"):
        _descriptor(tool_class=ToolClass.EXTRACT, name="extract_thing")


def test_a_non_run_tool_must_declare_a_cost_contract():
    """COST-001 gates *each* tool call, so a local tool still needs a price.

    A zero CostVector is a legitimate answer and "no answer" is not: `evaluate_budget` refuses an
    absent estimate outright, so a tool nobody can price is a tool that could only be called by
    going around the gate.
    """
    with refused("names no cost_contract"):
        _descriptor(cost_contract=None)


def test_a_run_tool_may_not_declare_a_second_cost_contract():
    """§9.5 makes the Capability authoritative; two contracts would be priced apart."""
    with refused("two sources for one number"):
        _descriptor(
            tool_class=ToolClass.RUN,
            name="run_thing",
            capability_id="cap:x",
            conditions_schema_version="d/s@1.0.0",
            cost_contract="cost:sneaky@1.0.0",
        )


def test_a_validate_tool_must_return_a_validation_report():
    """§17.19.2: never an unstructured boolean/string, refused at registration."""

    class BooleanValidator:
        @property
        def request_model(self) -> type[Ping]:
            return Ping

        @property
        def result_model(self) -> type[Pong]:
            return Pong

        def __call__(self, request: ToolRequest) -> Pong:  # pragma: no cover - never registered
            raise AssertionError

    with pytest.raises(ToolRegistrationError, match="carries no ValidationReport"):
        ToolRegistry().register(
            _descriptor(
                tool_class=ToolClass.VALIDATE, name="validate_thing", requires=("test.thing",)
            ),
            BooleanValidator(),
        )


def test_a_validate_tool_carrying_a_report_registers():
    """The positive control for the clause above."""

    class Reported(ToolResult):
        report: ValidationReport

    class RealValidator:
        @property
        def request_model(self) -> type[Ping]:
            return Ping

        @property
        def result_model(self) -> type[Reported]:
            return Reported

        def __call__(self, request: ToolRequest) -> Reported:
            return Reported(
                tool_id="DOM-TST-TOOL-002",
                tool_version="1.0.0",
                report=report(
                    subject_type="T",
                    subject_id="s",
                    validator_id="v",
                    validator_version="1.0.0",
                ),
            )

    registry = ToolRegistry()
    registry.register(
        _descriptor(
            tool_id="DOM-TST-TOOL-002",
            tool_class=ToolClass.VALIDATE,
            name="validate_thing",
            requires=("test.thing",),
            produces=("test.report",),
        ),
        RealValidator(),
    )
    assert registry.of_class(ToolClass.VALIDATE)[0].name == "validate_thing"


def test_the_retired_tool_id_scheme_is_refused_by_name():
    """§10.2.1 retires SP-CH-xx / SP-MO-xx / SP-IC-xx. A tool with two identities has none."""
    assert RETIRED_TOOL_ID.match("SP-CH-01")
    with refused("retired"):
        _descriptor(tool_id="SP-CH-01")


def test_two_tools_cannot_share_an_id_or_a_canonical_name():
    registry = _registry()
    with pytest.raises(ToolRegistrationError, match="already registered"):
        registry.register(_descriptor(), DoublingTool())
    with pytest.raises(ToolRegistrationError, match="already registered as DOM-TST-TOOL-001"):
        registry.register(_descriptor(tool_id="DOM-TST-TOOL-007"), DoublingTool())


# ---------------------------------------------------------------------------
# Clause 2, continued -- the PRODUCTION path. Moved here from the budget probes so each file
# claims one (requirement, test) pair: a module claiming COST-001 and SIM-003 with two test ids
# claims the cross product, and (COST-001, T-SIM-003) is not a pair 26 maps.
# ---------------------------------------------------------------------------


def test_no_shipped_orchestration_surface_invokes_the_registry_directly():
    """The raw registry is a mechanism; it must not be an ordinary production side-effect path.

    `ToolRegistry.invoke` is still the right thing for a unit test asking about type checking, and
    `BudgetedToolDispatcher` is the one place production calls it. Parsed rather than asserted by
    convention: the whole shipped package is scanned, and `dispatch.py` is the only file permitted
    to name the method.
    """
    source_root = repo_root() / "src" / "lab_brain"
    permitted = {Path("tools") / "dispatch.py"}
    offenders: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if relative in permitted:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{relative.as_posix()}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "invoke"
        )
    assert not offenders, (
        f"a shipped module calls `.invoke(...)` outside the budgeted dispatcher: {offenders}. "
        "COST-001 gates every tool call; a second entrance would be an unbudgeted side-effect path "
        "that satisfies SIM-003 by bypassing COST-001"
    )


def test_the_dispatcher_calls_the_registry_inside_the_perform_closure():
    """The ordering guarantee, read off the source rather than trusted.

    `dispatch_action` calls `perform` only after the gate returns ALLOW. So the tool call has to be
    INSIDE that closure -- a call at `dispatch` scope would run before the gate regardless of what
    any docstring said.
    """
    tree = ast.parse(inspect.getsource(BudgetedToolDispatcher))
    dispatch_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "dispatch"
    )
    perform = next(
        node
        for node in ast.walk(dispatch_fn)
        if isinstance(node, ast.FunctionDef) and node.name == "perform"
    )
    inside = {
        node.lineno
        for node in ast.walk(perform)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "invoke"
    }
    everywhere = {
        node.lineno
        for node in ast.walk(dispatch_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "invoke"
    }
    assert inside, "`dispatch` does not call the registry inside `perform`"
    assert everywhere == inside, (
        f"`dispatch` calls the registry outside the `perform` closure at {everywhere - inside}; "
        "that call happens before the budget gate has said anything"
    )
