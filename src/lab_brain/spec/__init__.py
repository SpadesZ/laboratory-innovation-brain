"""Machine-readable view over the SAI 3.3 specification.

The specification document is the single source of truth for Requirement IDs and
Requirement-to-Test traceability (SAI 3.3 §25.3, §26). Nothing in this package
restates those tables; it only parses them so that CI can enforce the invariants
demanded by TST-002 / TST-003.
"""

from lab_brain.spec.markers import (
    MarkedTest,
    collect_marked_tests,
    covered_requirement_ids,
    referenced_test_ids,
)
from lab_brain.spec.parser import (
    DeclaredInvariant,
    SpecDocument,
    SpecParseError,
    SpecRequirement,
    TraceabilityRow,
    load_spec,
    repo_root,
    spec_path,
)
from lab_brain.spec.registry import (
    MilestoneCatalog,
    MilestoneEntry,
    NormativeStatement,
    NormativeStatementRegistry,
    RegistryError,
    load_milestones,
    load_registry,
)

__all__ = [
    "DeclaredInvariant",
    "MarkedTest",
    "MilestoneCatalog",
    "MilestoneEntry",
    "NormativeStatement",
    "NormativeStatementRegistry",
    "RegistryError",
    "SpecDocument",
    "SpecParseError",
    "SpecRequirement",
    "TraceabilityRow",
    "collect_marked_tests",
    "covered_requirement_ids",
    "load_milestones",
    "load_registry",
    "load_spec",
    "referenced_test_ids",
    "repo_root",
    "spec_path",
]
