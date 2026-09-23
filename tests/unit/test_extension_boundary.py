"""T-EXT-001 — a second domain, with no core source modification (§24.2, §24.5).

    EXT-001    在不修改 core models、core repositories 與 orchestration state machine 的前提下，
               加入一個 ToyDomain 或第二個真實 domain，並能註冊 condition schema、validator、
               tool 與 benchmark。
    T-EXT-001  新增 ToyDomain 時 core package 無 source modification；plugin registration 即運作。

"NO CORE SOURCE MODIFICATION" IS A CLAIM ABOUT A DIFF, AND A TEST CANNOT SEE A DIFF. So it is
checked two ways, and neither is "we didn't change anything":

    behaviourally  `tests/toy_domain.py` -- a domain that lives OUTSIDE `src/` -- installs through
                   `DomainPackRegistry.install` and every registration works. Nothing in `src/`
                   names it, and nothing special-cases it.
    structurally   the import graph is parsed. §24.2's FORBIDDEN edges are checked as edges, and
                   the shipped package is scanned for any mention of the toy domain at all.

THE SECOND ONE IS WHAT SURVIVES. A behavioural test passes on a codebase where core was edited to
make the toy work; the structural half is what makes that visible, because an edit that taught core
about a domain has to name it somewhere.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lab_brain.core.models.enums import AuthorityComparison
from lab_brain.domains import DomainPack, DomainPackRegistry, DomainRegistries
from lab_brain.domains.base import DomainInstallError
from lab_brain.spec import repo_root
from lab_brain.tools.contracts import ToolClass
from lab_brain.verification.planner import VerificationPlanner
from tests.toy_domain import (
    TOY_CAPABILITY,
    TOY_DOMAIN,
    TOY_OBSERVABLE_RAW,
    TOY_SCHEMA_REF,
    TOY_SIDEBAND,
    TOY_TIER_A,
    TOY_TIER_B,
    ToyBenchRequest,
    ToyDomainPack,
    ToyValidateRequest,
)

pytestmark = [pytest.mark.requirement("EXT-001"), pytest.mark.spec_test("T-EXT-001")]

SOURCE_ROOT = repo_root() / "src" / "lab_brain"


def _modules(package: str) -> list[tuple[Path, ast.Module]]:
    root = SOURCE_ROOT / Path(*package.split("."))
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(root.rglob("*.py"))
    ]


def _imported_modules(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
    return found


# ---------------------------------------------------------------------------
# Behavioural half — plugin registration just works
# ---------------------------------------------------------------------------


def test_a_toy_domain_installs_and_every_registration_works():
    """THE clause. One `install` call, eight registrations, no core change and no special case."""
    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    registries = registry.registries

    assert registry.installed() == (TOY_DOMAIN,)
    assert registries.conditions.is_registered(TOY_SCHEMA_REF)
    assert registries.conditions.get_comparator(TOY_SCHEMA_REF).version == "1.0.0"
    assert ("auth:toy_widgets", "1.0.0") in registries.authority.registered()
    assert registries.backend_validity.registered() == ("toy_widgets/widget_validity@1.0.0",)
    assert registries.validators.registered() == ("validate_widget_blips",)
    assert registries.extractors.registered() == ("extract_widget_stiffness",)
    assert registries.capabilities.capability_ids() == (TOY_CAPABILITY,)
    assert registries.tools.tool_ids() == (
        "DOM-TOY-TOOL-001",
        "DOM-TOY-TOOL-004",
        "DOM-TOY-TOOL-006",
    )
    assert registries.benchmarks.registered() == ("bench:toy.widgets",)


def test_the_toy_domain_is_plannable_and_invocable_through_the_shared_machinery():
    """Registration is not enough -- the pack has to be USABLE through core's own surfaces."""
    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    registries = registry.registries

    planned = VerificationPlanner(registries.capabilities).plan(goal=(TOY_OBSERVABLE_RAW,))
    assert [action.capability_id for action in planned] == [TOY_CAPABILITY]

    result = registries.tools.invoke(
        "DOM-TOY-TOOL-001", ToyBenchRequest(project_id="prj:t", trace_id="trc:t", widget_id="w1")
    )
    assert result.tool_id == "DOM-TOY-TOOL-001"

    reported = registries.tools.invoke(
        "DOM-TOY-TOOL-006",
        ToyValidateRequest(project_id="prj:t", trace_id="trc:t", widget_id="w1", blips=2),
    )
    assert reported.report.passed  # type: ignore[attr-defined]


def test_the_toy_authority_ranking_is_verified_by_core_without_core_knowing_the_classes():
    """§10.5.1's laws are checked at registration over classes core has never heard of."""
    registries = DomainRegistries()
    ToyDomainPack().register_evidence_authority_policy(registries.authority)
    comparator = registries.authority.resolve("auth:toy_widgets", "1.0.0")

    assert comparator.compare(TOY_TIER_A, TOY_TIER_B) is AuthorityComparison.STRONGER
    # The INCOMPARABLE pair -- the case §10.5.1 exists for, present in the toy on purpose.
    assert comparator.compare(TOY_SIDEBAND, TOY_TIER_A) is AuthorityComparison.INCOMPARABLE


def test_two_domains_coexist_in_one_set_of_registries():
    """The real question behind "a second domain": two packs, one system, no collision."""
    from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack

    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    registry.install(SiliconPhotonicsPack(runner=lambda request: None))  # type: ignore[arg-type]

    assert registry.installed() == ("silicon_photonics", "toy_widgets")
    tools = registry.registries.tools
    assert {d.domain for d in tools} == {"silicon_photonics", "toy_widgets"}
    assert len(tools.of_class(ToolClass.EXTRACT)) == 2
    # And neither domain's authority comparator knows the other's classes.
    toy = registry.registries.authority.resolve("auth:toy_widgets", "1.0.0")
    assert toy.compare(TOY_TIER_A, "SIM_STANDARD") is AuthorityComparison.INCOMPARABLE


def test_installing_the_same_domain_twice_is_refused():
    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    with pytest.raises(DomainInstallError, match="already installed"):
        registry.install(ToyDomainPack())


def test_something_that_is_not_a_domain_pack_cannot_be_installed():
    """A pack installed through a different shape is one core has to know about specially."""

    class NotAPack:
        id = "nope"
        version = "1.0.0"

    with pytest.raises(DomainInstallError, match="does not satisfy the DomainPack protocol"):
        DomainPackRegistry().install(NotAPack())  # type: ignore[arg-type]


def test_core_starts_with_no_domain_pack_installed():
    """DOM-SP-001's second clause, checked from the other side: empty registries are legal.

    If installing were a side effect of importing, "not installed" would be unreachable and every
    "remove the plugin" claim would be untestable.
    """
    registry = DomainPackRegistry()
    assert registry.installed() == ()
    assert len(registry.registries.tools) == 0
    assert len(registry.registries.capabilities) == 0
    assert len(registry.registries.validators) == 0
    assert VerificationPlanner(registry.registries.capabilities).plan(goal=("anything",)) == ()


# ---------------------------------------------------------------------------
# Structural half — §24.2's forbidden edges, as edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("consumer", "forbidden"),
    [
        # §24.2  FORBIDDEN: core -> domains.silicon_photonics
        ("core", "lab_brain.domains"),
        # ...and core must not reach a provider adapter either. §24.1 keeps solver names out of
        # core, and an import of `tool_providers` is how one arrives.
        ("core", "lab_brain.tool_providers"),
        # §24.2  FORBIDDEN: orchestration -> direct CHARGE/MODE imports
        ("ingestion", "lab_brain.domains"),
        ("evidence", "lab_brain.domains"),
        ("cognition", "lab_brain.domains"),
        ("security", "lab_brain.domains"),
        ("surface", "lab_brain.domains"),
        ("storage", "lab_brain.domains"),
        # The generic tool and verification layers are the interfaces a domain depends ON.
        ("tools", "lab_brain.domains"),
        ("verification", "lab_brain.domains"),
        ("tools", "lab_brain.tool_providers"),
        ("verification", "lab_brain.tool_providers"),
    ],
)
def test_the_forbidden_dependency_directions_hold(consumer: str, forbidden: str):
    offenders = [
        f"{path.relative_to(repo_root()).as_posix()}:{line} -> {module}"
        for path, tree in _modules(consumer)
        for line, module in _imported_modules(tree)
        if module == forbidden or module.startswith(f"{forbidden}.")
    ]
    assert not offenders, f"§24.2 forbids {consumer} -> {forbidden}: {offenders}"


def test_the_allowed_direction_is_actually_used():
    """Non-vacuity. If `domains -> tools` were absent, every check above would pass on nothing.

    §24.2 ALLOWS `domains.silicon_photonics -> core` and `-> tools/simulators interfaces`, and the
    pack genuinely depends on both -- so the prohibitions above are about a graph that has edges
    rather than about an empty one.
    """
    imports = {
        module
        for _, tree in _modules("domains.silicon_photonics")
        for _, module in _imported_modules(tree)
    }
    assert any(module.startswith("lab_brain.tools") for module in imports)
    assert any(module.startswith("lab_brain.core") for module in imports)


def test_the_shipped_package_declares_nothing_about_the_toy_domain():
    """The "no core source modification" half that a behavioural test cannot reach.

    An edit that taught core about a domain has to name it somewhere in CODE. Scanned over the
    whole shipped package rather than over `core/` alone, because the cheapest way to make a second
    domain work is a special case in the registry -- which is not in `core/`.

    IDENTIFIERS AND STRING LITERALS, NOT RAW TEXT. `domains/base.py` and `domains/registry.py`
    explain in prose what EXT-001 asks and why a ToyDomain lives outside `src/` -- and a guard that
    tripped on the explanation would be punishing the documentation for describing the rule.
    The same distinction `test_core_declares_no_physical_quantity` draws, for the same reason.
    """
    needles = {TOY_DOMAIN, "ToyDomainPack", "ToyAuthority", "ToyExtractor", "ToyValidator"}
    mentions: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name in needles:
                    mentions.append(f"{path.name}:{node.lineno} identifier {name}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                # Docstrings are prose about the boundary, not declarations of it.
                and len(node.value) < 80
                and node.value in needles
            ):
                mentions.append(f"{path.name}:{node.lineno} literal {node.value!r}")
    assert not mentions, (
        f"the shipped package declares the toy domain at {mentions}. EXT-001 asks whether a second "
        "domain can be added with no core source modification, and a special case for this one "
        "answers the question with 'no'"
    )


def test_no_vendor_sdk_is_imported_anywhere_in_the_shipped_package():
    """R-1's tripwire. Adding a real backend must be a deliberate act, not an import.

    Not a prohibition on ever doing it: it is what stops a real `lumapi` import landing quietly and
    making the suite unrunnable on every machine without a license seat. TST-001's licensed half is
    open, and this test is where that stays visible.
    """
    vendors = {"lumapi", "lumerical", "lumopt", "lumslurm"}
    offenders = [
        f"{path.relative_to(repo_root()).as_posix()}:{line} -> {module}"
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        for line, module in _imported_modules(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        if module.split(".")[0] in vendors
    ]
    assert not offenders, f"a vendor SDK is imported: {offenders}"


def test_the_mock_never_claims_to_be_a_vendor_solver():
    """A Run stamped with a solver name that never ran is a provenance lie the schema accepts."""
    from lab_brain.tool_providers.lumerical.mock import (
        MOCK_BACKEND_ID,
        MOCK_SOLVER_ID,
    )

    for value in (MOCK_BACKEND_ID, MOCK_SOLVER_ID):
        assert value.startswith("mock."), f"{value!r} does not announce itself as a mock"
        assert "charge" not in value.split(".")[0].lower()


def test_a_domain_pack_is_handed_no_way_to_write_evidence():
    """§24.1's "Core MUST NOT know" column, enforced by what a pack can reach.

    `DomainRegistries` is the whole extension surface. A field on it that led to a repository, a
    connection or the admission gate would let a pack write an Attestation or mutate a projection
    -- so the absences are asserted, not assumed.
    """
    import dataclasses

    forbidden = ("repositor", "store", "connection", "session", "gate", "projection", "event")
    fields = [field.name for field in dataclasses.fields(DomainRegistries)]
    leaks = [name for name in fields if any(term in name.lower() for term in forbidden)]
    assert not leaks, f"DomainRegistries exposes {leaks}; a pack must not reach a writer"

    installed = DomainPackRegistry()
    installed.install(ToyDomainPack())
    pack: DomainPack = installed.require(TOY_DOMAIN)
    assert not any(
        "admit" in name or "persist" in name or "commit" in name
        for name in dir(pack)
        if not name.startswith("_")
    )
