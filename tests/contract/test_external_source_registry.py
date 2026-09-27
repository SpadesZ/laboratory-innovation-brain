"""The ExternalSourceAdapter registry's contract (§26.1 M5, AGT-008, SRC-001): what it refuses at
registration, what it clamps, and that removing or replacing a provider changes nothing else."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

import pytest

from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.sources.adapter import (
    ExternalSourceRecord,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
)
from lab_brain.sources.external import (
    ConnectorDeclaration,
    ConnectorRegistrationError,
    ConnectorRegistry,
)
from lab_brain.tool_providers.github import declaration as github_declaration
from tests.external_fixtures import ACTOR, PROJECT, build

SRC = Path(__file__).resolve().parents[2] / "src" / "lab_brain"


class _Liar:
    """A 'code host' that labels its records peer-reviewed and claims snapshots it cannot take."""

    def __init__(self, provider: str = "codehost", can_snapshot: bool = False) -> None:
        self._provider = provider
        self._can_snapshot = can_snapshot

    def provider_id(self) -> str:
        return self._provider

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(provider_id=self._provider, can_snapshot=self._can_snapshot)

    def healthcheck(self) -> SourceHealthReport:
        return SourceHealthReport(self._provider, True)

    def search(self, query: SourceQuery) -> Sequence[ExternalSourceRecord]:
        return ()

    def fetch(self, locator: str) -> ExternalSourceRecord | None:
        return None


def test_registration_refuses_declarations_that_contradict_the_adapter():
    registry = ConnectorRegistry()
    with pytest.raises(ConnectorRegistrationError, match="can_snapshot"):
        registry.register(
            _Liar(can_snapshot=True),
            ConnectorDeclaration("codehost", (TrustClass.TECHNICAL_ARTIFACT,), technical_only=True),
        )
    with pytest.raises(ConnectorRegistrationError, match="GH-003"):
        registry.register(
            _Liar(),
            ConnectorDeclaration("codehost", (TrustClass.PEER_REVIEWED,), technical_only=True),
        )
    with pytest.raises(ConnectorRegistrationError, match="does not match"):
        registry.register(_Liar(), github_declaration())
    for internal in (
        TrustClass.INTERNAL_RUN,
        TrustClass.INTERNAL_MEASUREMENT,
        TrustClass.EXPERT_HEURISTIC,
    ):
        with pytest.raises(ConnectorRegistrationError, match="P16"):
            registry.register(_Liar(), ConnectorDeclaration("codehost", (internal,)))
    registry.register(
        _Liar(), ConnectorDeclaration("codehost", (TrustClass.TECHNICAL_ARTIFACT,), True)
    )
    with pytest.raises(ConnectorRegistrationError, match="already registered"):
        registry.register(
            _Liar(), ConnectorDeclaration("codehost", (TrustClass.TECHNICAL_ARTIFACT,), True)
        )


@pytest.mark.requirement("GH-003")
@pytest.mark.spec_test("T-GH-003")
def test_a_provider_cannot_promote_its_own_records_above_its_ceiling():
    world = build()
    record = world.github.retrieve("github:photonics-lab/pn-modulator-sim@main:README.md").record
    assert world.registry.clamp(record) == record
    promoted = ExternalSourceRecord(**{**record.__dict__, "trust_class": TrustClass.PEER_REVIEWED})
    with pytest.raises(ConnectorRegistrationError, match="does not get to promote"):
        world.registry.clamp(promoted)


def test_removing_the_github_provider_changes_nothing_but_the_searched_set():
    world = build()
    before = world.service.discover(
        SourceQuery(text="series resistance"), project_id=PROJECT, actor_id=ACTOR
    )
    assert {r.provider for r in before} == {"github", "literature"}
    world.registry.remove("github")
    after = world.service.discover(
        SourceQuery(text="series resistance"), project_id=PROJECT, actor_id=ACTOR
    )
    assert {r.provider for r in after} == {"literature"}
    # The literature results are exactly what they were: nothing else depended on GitHub.
    assert {r.canonical_locator for r in after} == {
        r.canonical_locator for r in before if r.provider == "literature"
    }
    assert world.registry.router(runner=world.runner, classifier=None).providers == (  # type: ignore[arg-type]
        "literature",
    )


def test_no_core_cognition_or_verification_module_names_a_provider_package():
    """AGT-008: cognition/domain code never calls a provider directly -- checked on the import
    graph, so removing `tool_providers.github` cannot break them."""
    forbidden = ("lab_brain.tool_providers.github", "lab_brain.tool_providers.literature")
    for package in ("core", "cognition", "verification", "evidence", "sources", "ingestion"):
        for path in (SRC / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                for name in names:
                    assert not name.startswith(forbidden), f"{path} imports {name}"


def test_the_public_only_capability_is_what_the_egress_gate_reads():
    world = build()
    assert world.github.capabilities().max_sensitivity is SensitivityLabel.PUBLIC
    assert world.github.capabilities().can_snapshot
