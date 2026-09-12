"""Parse Requirement IDs and the traceability matrix out of SAI 3.3.

SAI 3.3 §0.6 forbids resolving spec conflicts by picking "the paragraph that looks
most like code". The practical consequence for tooling is that the spec prose must
stay the only place requirements are declared -- so this module reads the document
rather than mirroring it into YAML that could silently drift.

Sources parsed:
  §24.5  EXT-001 (declared in prose, deliberately absent from the §25.3 table)
  §25.3  First Vertical Requirements  -> 51 rows
  §26    Requirement-to-Test Traceability -> 52 rows
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Requirement ID namespaces. §23.2 declares the namespace list; ``GH`` is used by
#: §25.3/§26 (GH-001..GH-003) without appearing in the §23.2 table. That gap is
#: recorded as a spec observation in docs/spec_coverage_audit/, not silently fixed.
REQUIREMENT_NAMESPACES = (
    "SYS",
    "ART",
    "EVI",
    "EPI",
    "VER",
    "SIM",
    "DOM-SP",
    "SEC",
    "OPS",
    "COST",
    "SRC",
    "LLM",
    "EXT",
    "UX",
    "TST",
    "GH",
)

REQUIREMENT_ID_RE = re.compile(
    r"^(?:" + "|".join(re.escape(ns) for ns in REQUIREMENT_NAMESPACES) + r")-\d{3}$"
)

TEST_ID_RE = re.compile(r"^T-[A-Z0-9-]+$")

_EXT_001_RE = re.compile(r"\*\*(EXT-001)\*\*[：:]\s*(.+?)(?:\n\n|\Z)", re.DOTALL)

#: The spec asserts the requirement/test count invariant twice, in the change summary
#: and again in §26. Both are parsed so the number cannot drift from the tables it
#: describes without CI noticing.
_INVARIANT_SUMMARY_RE = re.compile(
    r"Requirement\s*↔\s*Test\s*不變式[：:]\s*(\d+)\s*↔\s*(\d+)"
)
_INVARIANT_SECTION_RE = re.compile(r"\*\*(\d+)\s*requirements?\s*↔\s*(\d+)\s*tests?")


class SpecParseError(RuntimeError):
    """The specification could not be parsed into the shape CI depends on."""


@dataclass(frozen=True)
class SpecRequirement:
    """One normative requirement as declared by the specification prose."""

    requirement_id: str
    statement: str
    section: str

    @property
    def namespace(self) -> str:
        return self.requirement_id.rsplit("-", 1)[0]


@dataclass(frozen=True)
class TraceabilityRow:
    """One row of the §26 Requirement-to-Test matrix."""

    requirement_id: str
    test_id: str
    test_type: str
    pass_condition: str


@dataclass(frozen=True)
class DeclaredInvariant:
    """The "N requirements <-> N tests" count the spec asserts about itself."""

    requirement_count: int
    test_count: int
    source_section: str


@dataclass(frozen=True)
class SpecDocument:
    """Parsed, read-only projection of the specification."""

    path: Path
    version: str
    requirements: dict[str, SpecRequirement]
    traceability: tuple[TraceabilityRow, ...]
    declared_invariants: tuple[DeclaredInvariant, ...]

    @property
    def requirement_ids(self) -> frozenset[str]:
        return frozenset(self.requirements)

    @property
    def test_ids(self) -> frozenset[str]:
        return frozenset(row.test_id for row in self.traceability)

    def tests_for(self, requirement_id: str) -> tuple[str, ...]:
        return tuple(
            row.test_id for row in self.traceability if row.requirement_id == requirement_id
        )

    def requirements_for(self, test_id: str) -> tuple[str, ...]:
        return tuple(
            row.requirement_id for row in self.traceability if row.test_id == test_id
        )


def repo_root() -> Path:
    """Repository root, resolved from this file's location."""
    return Path(__file__).resolve().parents[3]


def spec_path() -> Path:
    """Canonical in-repo location of the specification document."""
    return repo_root() / "docs" / "spec" / "SAI_3.3.md"


def _section_slice(text: str, start_heading: str, end_heading: str) -> str:
    start = text.find(start_heading)
    if start == -1:
        raise SpecParseError(f"heading not found in spec: {start_heading!r}")
    end = text.find(end_heading, start + len(start_heading))
    if end == -1:
        raise SpecParseError(f"heading not found in spec: {end_heading!r}")
    return text[start:end]


def _table_rows(block: str) -> list[list[str]]:
    """Return markdown table data rows (header and separator rows removed)."""
    rows: list[list[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":", ""} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _strip_emphasis(value: str) -> str:
    return value.replace("**", "").strip()


def parse_version(text: str) -> str:
    match = re.search(r"^\*\*版本\*\*[：:]\s*(\S+)", text, re.MULTILINE)
    if not match:
        raise SpecParseError("spec version header not found")
    return match.group(1)


def parse_requirements(text: str) -> dict[str, SpecRequirement]:
    """Parse §25.3 (51 rows) plus the §24.5 prose declaration of EXT-001."""
    block = _section_slice(
        text,
        "## 25.3 First Vertical Requirements",
        "## 25.4 Vertical Slice Definition of Done",
    )
    requirements: dict[str, SpecRequirement] = {}
    for cells in _table_rows(block):
        if len(cells) < 2:
            continue
        requirement_id = _strip_emphasis(cells[0])
        if not REQUIREMENT_ID_RE.match(requirement_id):
            continue
        if requirement_id in requirements:
            raise SpecParseError(f"duplicate requirement in §25.3: {requirement_id}")
        requirements[requirement_id] = SpecRequirement(
            requirement_id=requirement_id,
            statement=_strip_emphasis(cells[1]),
            section="25.3",
        )

    ext_block = _section_slice(
        text, "## 24.5 Extensibility Acceptance Test", "# 25. Silicon Photonics First Vertical"
    )
    ext_match = _EXT_001_RE.search(ext_block)
    if not ext_match:
        raise SpecParseError("EXT-001 declaration not found in §24.5")
    requirements[ext_match.group(1)] = SpecRequirement(
        requirement_id=ext_match.group(1),
        statement=" ".join(ext_match.group(2).split()),
        section="24.5",
    )
    return requirements


def parse_traceability(text: str) -> tuple[TraceabilityRow, ...]:
    """Parse the §26 Requirement-to-Test matrix."""
    block = _section_slice(
        text,
        "# 26. Requirement-to-Test Traceability",
        "## 26.1 Milestone Gate Order",
    )
    rows: list[TraceabilityRow] = []
    for cells in _table_rows(block):
        if len(cells) < 4:
            continue
        requirement_id = _strip_emphasis(cells[0])
        test_id = _strip_emphasis(cells[1])
        if not REQUIREMENT_ID_RE.match(requirement_id):
            continue
        if not TEST_ID_RE.match(test_id):
            raise SpecParseError(
                f"malformed Test ID for {requirement_id} in §26: {test_id!r}"
            )
        rows.append(
            TraceabilityRow(
                requirement_id=requirement_id,
                test_id=test_id,
                test_type=_strip_emphasis(cells[2]),
                pass_condition=_strip_emphasis(cells[3]),
            )
        )
    if not rows:
        raise SpecParseError("§26 traceability matrix parsed as empty")
    return tuple(rows)


def parse_declared_invariants(text: str) -> tuple[DeclaredInvariant, ...]:
    """Parse the self-asserted requirement/test counts from the change summary and §26."""
    found: list[DeclaredInvariant] = []
    summary = _INVARIANT_SUMMARY_RE.search(text)
    if summary:
        found.append(
            DeclaredInvariant(
                requirement_count=int(summary.group(1)),
                test_count=int(summary.group(2)),
                source_section="change-summary",
            )
        )
    section = _INVARIANT_SECTION_RE.search(text)
    if section:
        found.append(
            DeclaredInvariant(
                requirement_count=int(section.group(1)),
                test_count=int(section.group(2)),
                source_section="26",
            )
        )
    if not found:
        raise SpecParseError("no declared requirement/test count invariant found in spec")
    return tuple(found)


@lru_cache(maxsize=1)
def load_spec(path: Path | None = None) -> SpecDocument:
    """Load and parse the specification. Cached; the document is read-only."""
    resolved = path or spec_path()
    if not resolved.is_file():
        raise SpecParseError(f"specification not found at {resolved}")
    text = resolved.read_text(encoding="utf-8")
    return SpecDocument(
        path=resolved,
        version=parse_version(text),
        requirements=parse_requirements(text),
        traceability=parse_traceability(text),
        declared_invariants=parse_declared_invariants(text),
    )
