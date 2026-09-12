"""Static collection of requirement/test markers from the test tree.

T-SPEC-001 must answer "does a real test exist for this Requirement ID, and does any
test point at an ID the spec does not declare?". Both questions are about the test
*source*, so they are answered by parsing it with ``ast`` -- static analysis cannot be
defeated by a test that fails to import.

CRITICAL: "a marker exists" is not "a test runs". A decorated function that pytest never
collects would otherwise satisfy the milestone-DONE ratchet without executing anything,
which defeats the entire point of the harness. This module therefore reproduces pytest's
*collection* rules rather than merely looking for decorators:

    - module filename must match ``test_*.py``
    - a function must be named ``test_*``
    - a method counts only inside a class named ``Test*`` that declares no ``__init__``
      (pytest skips such classes with a warning)
    - nesting deeper than one class level is not collected

Reproducing the rules statically is still a model of pytest, not pytest. The model is
cross-checked against real ``--collect-only`` output by
``tests/spec/test_marker_collection.py``, so drift between the two is itself a failure.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lab_brain.spec.parser import repo_root

_MARKER_REQUIREMENT = "requirement"
_MARKER_SPEC_TEST = "spec_test"

#: pytest's defaults (python_files / python_functions / python_classes). Kept here rather
#: than read from config because a change to either must be a deliberate, reviewed edit.
_TEST_FILE_GLOB = "test_*.py"
_TEST_FUNCTION_PREFIX = "test"
_TEST_CLASS_PREFIX = "Test"


@dataclass(frozen=True)
class MarkedTest:
    """A pytest-collectable test function annotated with traceability markers."""

    module: str
    function: str
    requirement_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    lineno: int
    class_name: str | None = None

    @property
    def location(self) -> str:
        owner = f"{self.class_name}::" if self.class_name else ""
        return f"{self.module}::{owner}{self.function}:{self.lineno}"

    @property
    def node_id(self) -> str:
        """The pytest node ID this test should appear under, without parametrisation."""
        owner = f"::{self.class_name}" if self.class_name else ""
        return f"{self.module}{owner}::{self.function}"


@dataclass(frozen=True)
class RejectedMarker:
    """A marker found on something pytest will not collect.

    Surfaced rather than dropped: a marker in this list is almost always someone
    accidentally -- or deliberately -- claiming coverage that never executes.
    """

    module: str
    name: str
    lineno: int
    reason: str

    @property
    def location(self) -> str:
        return f"{self.module}::{self.name}:{self.lineno}"


def tests_root() -> Path:
    return repo_root() / "tests"


def is_test_function_name(name: str) -> bool:
    return name.startswith(_TEST_FUNCTION_PREFIX)


def is_test_class(node: ast.ClassDef) -> bool:
    """pytest collects ``Test*`` classes, and skips any that define ``__init__``."""
    if not node.name.startswith(_TEST_CLASS_PREFIX):
        return False
    return not any(
        isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name == "__init__"
        for child in node.body
    )


def _marker_name(node: ast.expr) -> str | None:
    """Return the marker name for ``@pytest.mark.<name>(...)`` decorators."""
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call is not None else node
    if not isinstance(target, ast.Attribute):
        return None
    owner = target.value
    if not (isinstance(owner, ast.Attribute) and owner.attr == "mark"):
        return None
    return target.attr


def _string_args(node: ast.expr) -> tuple[str, ...]:
    if not isinstance(node, ast.Call):
        return ()
    return tuple(
        arg.value
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    )


def _traceability_markers(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    requirement_ids: tuple[str, ...] = ()
    test_ids: tuple[str, ...] = ()
    for decorator in node.decorator_list:
        name = _marker_name(decorator)
        if name == _MARKER_REQUIREMENT:
            requirement_ids += _string_args(decorator)
        elif name == _MARKER_SPEC_TEST:
            test_ids += _string_args(decorator)
    return requirement_ids, test_ids


def _collect_from_module(
    path: Path, module_name: str
) -> tuple[list[MarkedTest], list[RejectedMarker]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collected: list[MarkedTest] = []
    rejected: list[RejectedMarker] = []

    def record_function(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        inherited: tuple[tuple[str, ...], tuple[str, ...]],
        class_name: str | None,
        class_reason: str | None,
    ) -> None:
        own = _traceability_markers(node)
        requirement_ids = inherited[0] + own[0]
        test_ids = inherited[1] + own[1]
        if not requirement_ids and not test_ids:
            return
        if class_reason is not None:
            rejected.append(RejectedMarker(module_name, node.name, node.lineno, class_reason))
            return
        if not is_test_function_name(node.name):
            rejected.append(
                RejectedMarker(
                    module_name,
                    node.name,
                    node.lineno,
                    f"function name does not start with {_TEST_FUNCTION_PREFIX!r}, "
                    "so pytest does not collect it",
                )
            )
            return
        collected.append(
            MarkedTest(
                module=module_name,
                function=node.name,
                requirement_ids=requirement_ids,
                test_ids=test_ids,
                lineno=node.lineno,
                class_name=class_name,
            )
        )

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            record_function(node, ((), ()), None, None)
            continue
        if not isinstance(node, ast.ClassDef):
            continue

        inherited = _traceability_markers(node)
        reason: str | None = None
        if not node.name.startswith(_TEST_CLASS_PREFIX):
            reason = (
                f"class {node.name!r} does not start with {_TEST_CLASS_PREFIX!r}, "
                "so pytest does not collect its methods"
            )
        elif not is_test_class(node):
            reason = f"class {node.name!r} defines __init__, so pytest skips it"

        if reason is not None and (inherited[0] or inherited[1]):
            rejected.append(RejectedMarker(module_name, node.name, node.lineno, reason))

        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                record_function(child, inherited, node.name, reason)
            elif isinstance(child, ast.ClassDef):
                nested = _traceability_markers(child)
                if nested[0] or nested[1]:
                    rejected.append(
                        RejectedMarker(
                            module_name,
                            child.name,
                            child.lineno,
                            "nested class; pytest does not collect markers at this depth",
                        )
                    )

    return collected, rejected


@lru_cache(maxsize=4)
def _scan(root: Path) -> tuple[tuple[MarkedTest, ...], tuple[RejectedMarker, ...]]:
    if not root.is_dir():
        return (), ()
    collected: list[MarkedTest] = []
    rejected: list[RejectedMarker] = []
    for path in sorted(root.rglob(_TEST_FILE_GLOB)):
        module_name = path.relative_to(root).as_posix()
        module_collected, module_rejected = _collect_from_module(path, module_name)
        collected.extend(module_collected)
        rejected.extend(module_rejected)
    return tuple(collected), tuple(rejected)


def collect_marked_tests(root: Path | None = None) -> tuple[MarkedTest, ...]:
    """Marked functions pytest will actually collect."""
    return _scan(root or tests_root())[0]


def rejected_markers(root: Path | None = None) -> tuple[RejectedMarker, ...]:
    """Traceability markers found on things pytest will not collect."""
    return _scan(root or tests_root())[1]


def covered_requirement_ids(root: Path | None = None) -> frozenset[str]:
    return frozenset(
        requirement_id
        for test in collect_marked_tests(root)
        for requirement_id in test.requirement_ids
    )


def referenced_test_ids(root: Path | None = None) -> frozenset[str]:
    return frozenset(
        test_id for test in collect_marked_tests(root) for test_id in test.test_ids
    )
