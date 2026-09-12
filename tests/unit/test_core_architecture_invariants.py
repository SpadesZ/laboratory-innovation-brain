"""Architecture invariants for the core scientific entities.

Deliberately unmarked. These guard the design from the moment the models exist, but the
Requirement they serve -- SYS-001 -- is allocated to M0b: its §26 pass condition names
EpistemicState and Hypothesis, neither of which exists yet, so claiming it here would discharge
half a pass condition. The marked T-SYS-001 in M0b asserts both halves and will reuse these
checks.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lab_brain.core.models import FORBIDDEN_RELATION_FIELDS
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.source_work import SourceWork
from lab_brain.spec import repo_root

CORE_ENTITIES = (Artifact, SourceWork, Claim, Observation, Attestation, RelationJudgment)


def core_package() -> Path:
    return repo_root() / "src" / "lab_brain" / "core"


@pytest.mark.parametrize("model", CORE_ENTITIES, ids=lambda m: m.__name__)
def test_no_core_entity_carries_a_parallel_support_array(model):
    """Support and contradiction live only in RelationJudgment (§17.2, §17.5, SYS-001).

    A parallel array is a second store of the same fact that nothing keeps in step with the
    relation table, and when the two disagree there is no way to tell which one the belief state
    was computed from.
    """
    offending = sorted(set(model.model_fields) & FORBIDDEN_RELATION_FIELDS)
    assert not offending, (
        f"{model.__name__} declares {offending}; support/contradiction is resolved only "
        "through RelationJudgment"
    )


@pytest.mark.parametrize("model", CORE_ENTITIES, ids=lambda m: m.__name__)
def test_core_entities_are_frozen(model):
    """P2 append-only. Correcting a record writes a new one; it does not mutate the old."""
    assert model.model_config.get("frozen") is True, f"{model.__name__} is not frozen"


@pytest.mark.parametrize("model", CORE_ENTITIES, ids=lambda m: m.__name__)
def test_core_entities_forbid_unknown_fields(model):
    """A silently dropped field produces a record that looks complete and is not."""
    assert model.model_config.get("extra") == "forbid", f"{model.__name__} tolerates unknown fields"


def test_core_does_not_import_a_domain_pack():
    """§24.2: core MUST NOT import lab_brain.domains.*.

    A fast local guard on the dependency direction. The full acceptance test is T-EXT-001 in M2,
    which adds a ToyDomain and requires no core modification at all.
    """
    offenders: list[str] = []
    for path in sorted(core_package().rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "lab_brain.domains"
            ):
                offenders.append(f"{path.name}:{node.lineno} -> {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.name}:{node.lineno} -> {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("lab_brain.domains")
                )
    assert not offenders, f"core imports a DomainPack: {offenders}"


#: Terms that would mean a physical quantity had leaked into the domain-agnostic core (§24.1).
#: Matched as whole words on identifiers and string literals, not on prose in comments.
_DOMAIN_LEAK_TERMS = (
    "wavelength",
    "bias_voltage",
    "doping",
    "mesh_convergence",
    "charge_solver",
    "resonance",
    "free_spectral_range",
)


def test_core_declares_no_physical_quantity():
    """§24.1: core must not know Cj, Rs, mesh field names or that 1550 nm is anything.

    Checks identifiers and string literals rather than raw file text, so a docstring explaining
    *why* core avoids these terms does not trip the guard.
    """
    pattern = re.compile("|".join(rf"\b{term}\b" for term in _DOMAIN_LEAK_TERMS))
    offenders: list[str] = []
    for path in sorted(core_package().rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if pattern.search(name.lower()):
                    offenders.append(f"{path.name}:{node.lineno} identifier {name}")
            elif isinstance(node, ast.arg) and pattern.search(node.arg.lower()):
                offenders.append(f"{path.name}:{node.lineno} parameter {node.arg}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                # Docstrings are prose about the boundary, not declarations of it.
                and len(node.value) < 80
                and pattern.search(node.value.lower())
            ):
                offenders.append(f"{path.name}:{node.lineno} literal {node.value!r}")
    assert not offenders, f"domain-specific terms in core: {offenders}"


def test_migration_runner_declares_every_migration_file():
    """AGT-004: an unlisted migration would never be applied, silently diverging environments."""
    import sys

    sys.path.insert(0, str(repo_root() / "scripts"))
    from migrate import APPLY_ORDER  # type: ignore[import-not-found]

    on_disk = {path.name for path in (repo_root() / "migrations").glob("*.sql")}
    assert on_disk == set(APPLY_ORDER), (
        f"migrations on disk {sorted(on_disk)} disagree with APPLY_ORDER {sorted(APPLY_ORDER)}"
    )


def test_condition_schema_migration_precedes_the_tables_that_reference_it():
    """008 must apply before 003: attestations carry an FK to condition_schemas.

    Appendix A's numbering is an index, not an apply order. Getting this wrong makes migration
    failure the *good* outcome -- the bad one is an FK quietly not created.
    """
    import sys

    sys.path.insert(0, str(repo_root() / "scripts"))
    from migrate import APPLY_ORDER  # type: ignore[import-not-found]

    order = list(APPLY_ORDER)
    assert order.index("008_conditions.sql") < order.index(
        "003_claims_observations_attestations.sql"
    )
