"""Governance of the out-of-catalog safety package, checked structurally.

isolated        nothing in the shipped product imports it: Discovery stays offline and out of the
                research flow, and the safety gate with it
offline         it imports no DomainPack, no governed write path, no model runtime, no network, no
                database, no process, no clock and no fresh randomness
no confirmation no CONFIRMED vocabulary anywhere in the package
frozen          the engine and evaluation packages hold exactly the files their manifests froze;
                the safety package lives beside them, and its own evidence names it
proposal        the stage-1 marker is a module constant written nowhere else in the package
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from lab_brain.spec import repo_root

SRC = repo_root() / "src" / "lab_brain"
PACKAGE = SRC / "discovery_safety"


def _modules(root: Path) -> list[tuple[Path, ast.Module]]:
    return [
        (p, ast.parse(p.read_text(encoding="utf-8"), filename=str(p)))
        for p in sorted(root.rglob("*.py"))
    ]


def _imports(tree: ast.Module) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return found


FORBIDDEN = (
    "lab_brain.domains",
    "lab_brain.tool_providers",
    "lab_brain.core.belief",
    "lab_brain.core.root_cause",
    "lab_brain.core.episode",
    "lab_brain.core.warrant",
    "lab_brain.core.repositories",
    "lab_brain.verification",
    "lab_brain.research",
    "lab_brain.storage",
    "lab_brain.security",
    "lab_brain.llm_runtime",
    "lab_brain.cognition",
    "lab_brain.surface",
    "lab_brain.interfaces",
    "socket",
    "http",
    "urllib",
    "requests",
    "psycopg",
    "subprocess",
    "time",
    "datetime",
    "uuid",
    "random",
    "secrets",
)


def test_the_package_exists_with_its_modules():
    names = {p.name for p in PACKAGE.glob("*.py")}
    assert {"model.py", "pairwise.py", "gate.py", "evaluation.py"} <= names


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_the_safety_package_never_imports(forbidden):
    offenders = [
        f"{path.name} -> {module}"
        for path, tree in _modules(PACKAGE)
        for module in _imports(tree)
        if module == forbidden or module.startswith(f"{forbidden}.")
    ]
    assert not offenders, offenders


def test_its_lab_brain_imports_are_the_engine_and_the_evaluation_tooling_only():
    reached = {
        module.split(".")[1]
        for _, tree in _modules(PACKAGE)
        for module in _imports(tree)
        if module.startswith("lab_brain.")
    }
    assert reached <= {"discovery", "discovery_eval", "discovery_safety"}, reached


def test_nothing_in_the_shipped_product_imports_the_safety_package():
    offenders = [
        f"{path.relative_to(SRC)} -> {module}"
        for path, tree in _modules(SRC)
        if path.relative_to(SRC).parts[0] != "discovery_safety"
        for module in _imports(tree)
        if module.startswith("lab_brain.discovery_safety")
    ]
    assert not offenders, offenders


def test_there_is_no_confirmed_in_the_safety_package():
    offenders = []
    for path, tree in _modules(PACKAGE):
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if "CONFIRM" in name.upper():
                    offenders.append(f"{path.name}:{node.lineno} {name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "CONFIRMED" in node.value and "NOT PASSED" not in node.value:
                    offenders.append(f"{path.name}:{node.lineno} {node.value[:60]!r}")
    assert not offenders, offenders


def test_the_stage_1_marker_is_written_once():
    hits = [
        f"{path.name}:{node.lineno}"
        for path, tree in _modules(PACKAGE)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "STAGE_1_EXPLORATORY_IDEA"
    ]
    assert hits == [hits[0]] and hits[0].startswith("model.py:"), hits


def test_the_frozen_packages_hold_exactly_their_frozen_files():
    audit = repo_root() / "docs" / "audit"
    engine = json.loads(
        (audit / "discovery-loop-offline-2026-11-01" / "evidence" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    evaluation = json.loads(
        (
            audit / "discovery-independent-evaluation-2026-11-02" / "evidence" / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    frozen_engine = {
        Path(p).name for p in engine["sources_sha256"] if p.startswith("src/lab_brain/discovery/")
    }
    frozen_eval = {
        Path(p).name
        for p in evaluation["evaluation_sources_sha256"]
        if p.startswith("src/lab_brain/discovery_eval/")
    }
    assert {p.name for p in (SRC / "discovery").glob("*.py")} == frozen_engine
    assert {p.name for p in (SRC / "discovery_eval").glob("*.py")} == frozen_eval
