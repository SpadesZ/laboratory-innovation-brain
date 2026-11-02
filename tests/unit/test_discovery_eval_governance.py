"""Governance of the discovery evaluation tooling, checked structurally.

isolated        nothing in the shipped product imports the discovery engine or its evaluation
                tooling: Discovery stays offline and out of the research flow
offline         the evaluation package imports no DomainPack, no governed write path, no model
                runtime, no network, no database, no process and no clock
sealing only    `secrets` (fresh salts for sealing) is imported by the hidden-world module alone
no confirmation no CONFIRMED vocabulary anywhere in the package
frozen engine   the engine package holds exactly the files the 2026-11-01 manifest froze: the
                evaluation tooling lives beside it, not in it
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from lab_brain.spec import repo_root

SRC = repo_root() / "src" / "lab_brain"
PACKAGE = SRC / "discovery_eval"


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
)


def test_the_package_exists_with_its_modules():
    names = {p.name for p in PACKAGE.glob("*.py")}
    assert {"blind.py", "curves.py", "held_out.py", "hidden_worlds.py"} <= names


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_the_evaluation_package_never_imports(forbidden):
    offenders = [
        f"{path.name} -> {module}"
        for path, tree in _modules(PACKAGE)
        for module in _imports(tree)
        if module == forbidden or module.startswith(f"{forbidden}.")
    ]
    assert not offenders, offenders


def test_core_and_evaluation_imports_are_canonical_json_only():
    reached = {
        module
        for _, tree in _modules(PACKAGE)
        for module in _imports(tree)
        if module.startswith(("lab_brain.core", "lab_brain.evaluation"))
    }
    assert reached <= {"lab_brain.core.canonical_json"}, reached


def test_only_the_sealing_module_draws_fresh_randomness():
    users = sorted(
        path.name for path, tree in _modules(PACKAGE) if "secrets" in set(_imports(tree))
    )
    assert users == ["hidden_worlds.py"]


def test_nothing_in_the_shipped_product_imports_discovery():
    offenders = []
    for path, tree in _modules(SRC):
        relative = path.relative_to(SRC).parts
        if relative[0] in ("discovery", "discovery_eval"):
            continue
        for module in _imports(tree):
            if module.startswith(("lab_brain.discovery", "lab_brain.discovery_eval")):
                offenders.append(f"{path.relative_to(SRC)} -> {module}")
    # The ring scenario is data handed to the engine; it may import the engine's types, and
    # nothing in the product imports the scenario (test_discovery_governance holds that).
    allowed = {"domains/silicon_photonics/discovery_catalog.py"}
    assert {o.split(" -> ")[0] for o in offenders} <= allowed, offenders


def test_there_is_no_confirmed_in_the_evaluation_package():
    offenders = []
    for path, tree in _modules(PACKAGE):
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if "CONFIRM" in name.upper():
                    offenders.append(f"{path.name}:{node.lineno} {name}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) < 80
                and "CONFIRMED" in node.value
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert not offenders, offenders


def test_the_frozen_engine_package_holds_exactly_the_files_its_manifest_froze():
    manifest = json.loads(
        (
            repo_root()
            / "docs"
            / "audit"
            / "discovery-loop-offline-2026-11-01"
            / "evidence"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    frozen = {
        Path(p).name for p in manifest["sources_sha256"] if p.startswith("src/lab_brain/discovery/")
    }
    assert {p.name for p in (SRC / "discovery").glob("*.py")} == frozen
