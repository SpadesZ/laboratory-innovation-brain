"""Static guard for SIM-003: no `eval_script`-class public interface anywhere.

SIM-003 was added by maintainer ruling on SPEC-ISSUE-003. P19 and §10.2 state a hard MUST -- tool
invocation goes through a typed ToolRegistry, and no tool, Capability or backend adapter may
expose an arbitrary script-execution entry point. The Risk Register lists it as a P0 defence
against evaluator corruption: an agent that can hand a solver arbitrary script text can move the
metric definition along with the solver config, and then "the numbers improved" means nothing.

Before the ruling this MUST was registered against VER-002, whose test only checks that a backend
without a Capability descriptor cannot be planned. Those are different propositions -- a backend
can hold a perfectly valid descriptor and still expose `eval_script(code: str)`.

Unmarked, deliberately. SIM-003 is allocated to M2, where T-SIM-003 will assert both halves: this
static half *and* that every invocation resolves through the typed registry, which needs the
registry to exist. Marking it now would claim a requirement discharged on half a pass condition.
The guard runs from today regardless, so the forbidden shape cannot be introduced and then have
to be removed later.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lab_brain.spec import repo_root

#: Names that denote handing arbitrary code or script text to an executor. Matched on public
#: callables and their parameters. A leading underscore is not an exemption -- SIM-003 speaks of
#: public interfaces, but a private helper with this shape is one refactor away from being one,
#: so both are reported and any genuine exception must be argued explicitly.
_FORBIDDEN_CALLABLE_PATTERN = re.compile(
    r"""^_*(
          eval_script | evalscript | exec_script | run_script | execute_script
        | eval_code   | exec_code   | run_code    | execute_code
        | eval_string | exec_string
        | run_arbitrary | execute_arbitrary
        | lsf_exec | lumapi_eval
    )$""",
    re.VERBOSE,
)

#: Parameter names that would let arbitrary program text cross a tool boundary.
_FORBIDDEN_PARAM_PATTERN = re.compile(
    r"^_*(script|script_text|script_source|code_text|code_source|lsf_script|eval_string)$"
)

#: Python builtins that execute program text. Legitimate nowhere in this codebase.
_FORBIDDEN_BUILTINS = frozenset({"eval", "exec", "compile"})

_SOURCE_ROOT = "src/lab_brain"


def source_files() -> list[Path]:
    return sorted((repo_root() / "src" / "lab_brain").rglob("*.py"))


@pytest.fixture(scope="module")
def parsed() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in source_files()
    ]


def _location(path: Path, node: ast.AST) -> str:
    relative = path.relative_to(repo_root()).as_posix()
    return f"{relative}:{getattr(node, 'lineno', '?')}"


def test_source_tree_is_not_empty(parsed):
    """Guard against this whole file passing because nothing was scanned."""
    assert len(parsed) > 10, f"only {len(parsed)} source files parsed; scan target is wrong"


def test_no_callable_named_like_an_arbitrary_script_executor(parsed):
    offenders = [
        f"{_location(path, node)} def {node.name}"
        for path, tree in parsed
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and _FORBIDDEN_CALLABLE_PATTERN.match(node.name)
    ]
    assert not offenders, (
        "SIM-003: arbitrary script-execution entry points found. Tool invocation must go "
        f"through the typed ToolRegistry: {offenders}"
    )


def test_no_parameter_accepts_arbitrary_script_text(parsed):
    """A typed signature that takes `script: str` is untyped where it matters."""
    offenders: list[str] = []
    for path, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            arguments = [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ]
            if node.args.vararg:
                arguments.append(node.args.vararg)
            if node.args.kwarg:
                arguments.append(node.args.kwarg)
            offenders.extend(
                f"{_location(path, node)} {node.name}({argument.arg}: ...)"
                for argument in arguments
                if _FORBIDDEN_PARAM_PATTERN.match(argument.arg)
            )
    assert not offenders, f"SIM-003: parameters accepting arbitrary script text: {offenders}"


def test_no_class_exposes_an_arbitrary_script_method(parsed):
    offenders = [
        f"{_location(path, method)} {node.name}.{method.name}"
        for path, tree in parsed
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for method in node.body
        if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
        and _FORBIDDEN_CALLABLE_PATTERN.match(method.name)
    ]
    assert not offenders, f"SIM-003: classes exposing a script-execution method: {offenders}"


def test_no_call_to_eval_exec_or_compile(parsed):
    """The builtin form of the same hazard.

    ``pydantic``-style dynamic construction does not need these; a call here would mean program
    text is being executed somewhere in the scientific path.
    """
    offenders = [
        f"{_location(path, node)} {node.func.id}(...)"
        for path, tree in parsed
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FORBIDDEN_BUILTINS
    ]
    assert not offenders, f"SIM-003: program text executed via builtins: {offenders}"


def test_the_guard_detects_the_forbidden_shapes(tmp_path):
    """Non-vacuity: each pattern must actually match what it claims to.

    Without this, a typo in a regex would leave the guard permanently green.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "def eval_script(script: str) -> None:\n"
        "    exec(script)\n"
        "\n"
        "class Bridge:\n"
        "    def run_script(self, code_text: str) -> None:\n"
        "        eval(code_text)\n",
        encoding="utf-8",
    )
    tree = ast.parse(probe.read_text(encoding="utf-8"))

    functions = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _FORBIDDEN_CALLABLE_PATTERN.match(node.name)
    ]
    assert set(functions) == {"eval_script", "run_script"}

    parameters = [
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for argument in node.args.args
        if _FORBIDDEN_PARAM_PATTERN.match(argument.arg)
    ]
    assert set(parameters) == {"script", "code_text"}

    builtins_called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FORBIDDEN_BUILTINS
    }
    assert builtins_called == {"exec", "eval"}
