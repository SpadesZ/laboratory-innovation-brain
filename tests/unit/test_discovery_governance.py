"""Governance of the offline Discovery Loop, checked structurally rather than promised in prose.

no confirmation      the engine has no CONFIRMED vocabulary and no path to a belief event, a
                     root-cause conclusion, a warrant or a store
domain-agnostic      the engine imports no DomainPack and names no physical quantity (§24.1/2);
                     a scenario is handed to it as data
offline              no network, database, subprocess, model runtime or simulator import
deterministic        no clock, no unseeded randomness, no module-level mutable state
pre-registered       the protocol's defaults are pinned by digest; the existing-LIB arm differs
                     from the discovery arm only in declared switches, never in a statistic
frozen catalog       the ring catalog is pinned by digest and is not installed in the product
"""

from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

import pytest

from lab_brain.discovery.model import AnomalyState, DiscoveryState, Outcome, ReframingKind
from lab_brain.discovery.protocol import DISCOVERY, EXISTING_LIB_STYLE, DiscoveryProtocol
from lab_brain.spec import repo_root

ENGINE = repo_root() / "src" / "lab_brain" / "discovery"


def _modules() -> list[tuple[Path, ast.Module]]:
    files = sorted(ENGINE.glob("*.py"))
    assert len(files) >= 12, "the engine package was not found where expected"
    return [(p, ast.parse(p.read_text(encoding="utf-8"), filename=str(p))) for p in files]


def _imports(tree: ast.Module) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return found


FORBIDDEN_IMPORTS = (
    # §24.2 and the closed scenario boundary.
    "lab_brain.domains",
    "lab_brain.tool_providers",
    # The governed write paths a discovery loop must never reach.
    "lab_brain.core.belief",
    "lab_brain.core.root_cause",
    "lab_brain.core.episode",
    "lab_brain.core.warrant",
    "lab_brain.core.repositories",
    "lab_brain.verification",
    "lab_brain.research",
    "lab_brain.storage",
    "lab_brain.security",
    # No model, no network, no database, no process.
    "lab_brain.llm_runtime",
    "lab_brain.cognition",
    "socket",
    "http",
    "urllib",
    "requests",
    "psycopg",
    "subprocess",
    # No clock, no ambient randomness.
    "time",
    "datetime",
    "uuid",
    "secrets",
)


@pytest.mark.parametrize("forbidden", FORBIDDEN_IMPORTS)
def test_the_engine_never_imports(forbidden):
    offenders = [
        f"{path.name} -> {module}"
        for path, tree in _modules()
        for module in _imports(tree)
        if module == forbidden or module.startswith(f"{forbidden}.")
    ]
    assert not offenders, offenders


def test_the_only_core_and_evaluation_imports_are_pure_types_and_statistics():
    allowed = {
        "lab_brain.core.canonical_json",
        "lab_brain.core.models.hypothesis",
        "lab_brain.evaluation.stats",
    }
    reached = {
        module
        for _, tree in _modules()
        for module in _imports(tree)
        if module.startswith(("lab_brain.core", "lab_brain.evaluation"))
    }
    assert reached <= allowed, reached - allowed


#: §24.1's leak terms (`test_core_architecture_invariants`) plus the scenario's own vocabulary.
_LEAK = re.compile(
    "|".join(
        rf"\b{t}\b"
        for t in (
            "wavelength",
            "bias_voltage",
            "doping",
            "mesh_convergence",
            "charge_solver",
            "resonance",
            "free_spectral_range",
            "photonics",
            "silicon",
            "lumerical",
        )
    )
)


def test_the_engine_names_no_physical_quantity():
    offenders = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if _LEAK.search(name.lower()):
                    offenders.append(f"{path.name}:{node.lineno} {name}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) < 80
                and _LEAK.search(node.value.lower())
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert not offenders, offenders


def test_there_is_no_confirmed_anywhere_in_the_engine():
    for vocabulary in (DiscoveryState, AnomalyState, ReframingKind, Outcome):
        assert all("CONFIRM" not in m.name and "CONFIRM" not in m.value for m in vocabulary)
    offenders = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if "CONFIRM" in name.upper() and "UNCONFIRM" not in name.upper():
                    offenders.append(f"{path.name}:{node.lineno} {name}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) < 80
                and "CONFIRMED" in node.value
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert not offenders, offenders


def test_the_engine_holds_no_module_level_mutable_state_and_no_unseeded_randomness():
    offenders = []
    for path, tree in _modules():
        for node in tree.body:
            value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
            targets = (
                node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
            )
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                continue  # the export list, read by import machinery only
            if isinstance(
                value, ast.List | ast.Dict | ast.Set | ast.ListComp | ast.DictComp | ast.SetComp
            ):
                offenders.append(f"{path.name}:{node.lineno} module-level mutable")
        for node in ast.walk(tree):
            if isinstance(node, ast.Global | ast.Nonlocal):
                offenders.append(f"{path.name}:{node.lineno} global")
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "random"
                and node.attr != "Random"
            ):
                offenders.append(f"{path.name}:{node.lineno} random.{node.attr}")
    assert not offenders, offenders


#: The pre-registered protocol. Changing a threshold or a switch default changes this digest, and
#: with it the frozen benchmark's manifest: the change is a new protocol version, reviewed.
DISCOVERY_DIGEST = "sha256:5473507ce99d2f41918361c35ebf33efa18770e91baf7a7d8f76008462560c97"


def test_the_protocol_defaults_are_pinned():
    assert DiscoveryProtocol() == DISCOVERY
    assert DISCOVERY.digest == DISCOVERY_DIGEST


#: What the discovery arm adds over the existing loop's shape. Everything else -- every statistic
#: and threshold -- must be identical, so a difference between the arms can only come from these.
DISCOVERY_SWITCHES = {
    "anomalies",
    "noise_test",
    "expansion",
    "measurement_chain_review",
    "reframing",
    "closure",
    "indistinguishable_guard",
    "report_classes",
    "min_prospective_tests",
    "decisive_replication",
    "rival_closure",
}


def test_the_existing_lib_arm_differs_only_in_declared_switches():
    differing = {
        f.name
        for f in fields(DiscoveryProtocol)
        if getattr(DISCOVERY, f.name) != getattr(EXISTING_LIB_STYLE, f.name)
    }
    assert differing == DISCOVERY_SWITCHES


def test_the_ring_catalog_is_pinned_and_not_installed_in_the_product():
    from lab_brain.domains.silicon_photonics import discovery_catalog

    assert discovery_catalog.ring_catalog().digest == discovery_catalog.CATALOG_DIGEST
    pack = repo_root() / "src" / "lab_brain" / "domains" / "silicon_photonics"
    for path in sorted(pack.glob("*.py")):
        if path.name == "discovery_catalog.py":
            continue
        assert "discovery_catalog" not in path.read_text(encoding="utf-8"), path.name
