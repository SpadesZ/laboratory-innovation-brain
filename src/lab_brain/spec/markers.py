"""Static collection of requirement/test markers from the test tree.

T-SPEC-001 must answer "does a real test exist for this Requirement ID, and does any
test point at an ID the spec does not declare?". Both questions are about the test
*source*, so they are answered by parsing it with ``ast`` rather than by importing
pytest internals -- static analysis cannot be defeated by a test that fails to import.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lab_brain.spec.parser import repo_root

_MARKER_REQUIREMENT = "requirement"
_MARKER_SPEC_TEST = "spec_test"


@dataclass(frozen=True)
class MarkedTest:
    """A test function annotated with traceability markers."""

    module: str
    function: str
    requirement_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    lineno: int

    @property
    def location(self) -> str:
        return f"{self.module}::{self.function}:{self.lineno}"


def tests_root() -> Path:
    return repo_root() / "tests"


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
    values: list[str] = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            values.append(arg.value)
    return tuple(values)


def _collect_from_module(path: Path, module_name: str) -> list[MarkedTest]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collected: list[MarkedTest] = []

    # Class-level markers apply to every test method inside the class.
    def walk(
        body: list[ast.stmt],
        inherited_req: tuple[str, ...],
        inherited_test: tuple[str, ...],
    ) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                class_req, class_test = inherited_req, inherited_test
                for decorator in node.decorator_list:
                    name = _marker_name(decorator)
                    if name == _MARKER_REQUIREMENT:
                        class_req = class_req + _string_args(decorator)
                    elif name == _MARKER_SPEC_TEST:
                        class_test = class_test + _string_args(decorator)
                walk(node.body, class_req, class_test)
                continue
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            requirement_ids, test_ids = inherited_req, inherited_test
            for decorator in node.decorator_list:
                name = _marker_name(decorator)
                if name == _MARKER_REQUIREMENT:
                    requirement_ids = requirement_ids + _string_args(decorator)
                elif name == _MARKER_SPEC_TEST:
                    test_ids = test_ids + _string_args(decorator)
            if requirement_ids or test_ids:
                collected.append(
                    MarkedTest(
                        module=module_name,
                        function=node.name,
                        requirement_ids=requirement_ids,
                        test_ids=test_ids,
                        lineno=node.lineno,
                    )
                )

    walk(tree.body, (), ())
    return collected


@lru_cache(maxsize=1)
def collect_marked_tests(root: Path | None = None) -> tuple[MarkedTest, ...]:
    """Parse every ``test_*.py`` under ``tests/`` and return annotated test functions."""
    resolved = root or tests_root()
    if not resolved.is_dir():
        return ()
    collected: list[MarkedTest] = []
    for path in sorted(resolved.rglob("test_*.py")):
        module_name = path.relative_to(resolved).as_posix()
        collected.extend(_collect_from_module(path, module_name))
    return tuple(collected)


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
