"""Machine-readable view over the SAI 3.3 specification.

The specification document is the single source of truth for Requirement IDs and
Requirement-to-Test traceability (SAI 3.3 §25.3, §26). Nothing in this package
restates those tables; it only parses them so that CI can enforce the invariants
demanded by TST-002 / TST-003.
"""

from lab_brain.spec import conformance
from lab_brain.spec.markers import (
    MarkedTest,
    RejectedMarker,
    collect_marked_tests,
    covered_requirement_ids,
    referenced_test_ids,
    rejected_markers,
    tests_root,
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
    spec_issues_dir,
)

__all__ = [
    "DeclaredInvariant",
    "MarkedTest",
    "MilestoneCatalog",
    "MilestoneEntry",
    "NormativeStatement",
    "NormativeStatementRegistry",
    "RegistryError",
    "RejectedMarker",
    "SpecDocument",
    "SpecParseError",
    "SpecRequirement",
    "TraceabilityRow",
    "collect_marked_tests",
    "conformance",
    "covered_requirement_ids",
    "load_milestones",
    "load_registry",
    "load_spec",
    "referenced_test_ids",
    "rejected_markers",
    "repo_root",
    "spec_issues_dir",
    "spec_path",
    "tests_root",
]
