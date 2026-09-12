"""Recompute §23.5 (2) coverage-audit deltas from data.

Revision 2 of the M0a audit contained the row "§15.4: hard MUST = 2, registry-covered = 1,
delta = 0". It is arithmetically false and it survived review because the table was prose --
nothing recomputed it. Judged hard-MUST counts now live in
``docs/spec_coverage_audit/<audit>_hard_must_counts.yaml`` and this module derives the coverage
side from the registry, so the audit's arithmetic is checkable rather than asserted.

THE COUNTING RULE, applied uniformly to every section::

    delta = hard_must - (live_must + deferred_must)

  live_must      registry entries for the section with level MUST and no deferred_rationale
  deferred_must  registry entries with level MUST and a deferred_rationale, counted once as
                 deferred and never also as covered
  SHOULD         excluded entirely -- §0.2 makes SHOULD normative and deviation ADR-worthy, but
                 a SHOULD is not a hard MUST and must not pad a hard-MUST coverage count

Only the audit's own sections are considered. The registry spans the whole document; a coverage
audit is scoped to §6–§16 per §23.5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from lab_brain.spec.parser import repo_root, spec_path
from lab_brain.spec.registry import NormativeStatementRegistry, RegistryError

#: Markdown headings of the form "## 9.1 Title" / "### 10.5.1 Title".
_HEADING = re.compile(r"^#{1,4}\s+(\d+(?:\.\d+)*)\.?\s+(.*)$", re.MULTILINE)

#: Bounds of the audited range. §23.5 scopes a coverage audit to the normative architecture
#: chapters; §17's contracts are exercised by the requirement tests instead.
AUDIT_RANGE = (6, 16)


@dataclass(frozen=True)
class SectionCoverage:
    """One section's reconciliation under the counting rule above."""

    section: str
    hard_must: int
    live_must: int
    deferred_must: int
    should: int
    basis: str

    @property
    def covered(self) -> int:
        return self.live_must + self.deferred_must

    @property
    def delta(self) -> int:
        return self.hard_must - self.covered

    @property
    def balances(self) -> bool:
        return self.delta == 0


def hard_must_counts_path(audit: str = "M0a") -> Path:
    return repo_root() / "docs" / "spec_coverage_audit" / f"{audit}_hard_must_counts.yaml"


def load_hard_must_counts(path: Path | None = None) -> dict[str, tuple[int, str]]:
    """Load the judged hard-MUST count and its basis per section."""
    resolved = path or hard_must_counts_path()
    if not resolved.is_file():
        raise RegistryError(f"hard-MUST count file not found: {resolved}")
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegistryError(f"{resolved.name} must contain a top-level mapping")
    rows = data.get("sections")
    if not isinstance(rows, list) or not rows:
        raise RegistryError(f"{resolved.name}: 'sections' must be a non-empty list")

    counts: dict[str, tuple[int, str]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RegistryError(f"{resolved.name}: sections[{index}] must be a mapping")
        section = row.get("section")
        hard_must = row.get("hard_must")
        basis = row.get("basis", "")
        if not isinstance(section, str) or not section:
            raise RegistryError(f"{resolved.name}: sections[{index}] needs a section string")
        if not isinstance(hard_must, int) or hard_must < 0:
            raise RegistryError(f"{resolved.name}: §{section} hard_must must be a non-negative int")
        if not isinstance(basis, str) or not basis.strip():
            raise RegistryError(
                f"{resolved.name}: §{section} needs a `basis` recording how the count was judged; "
                "an unexplained number cannot be reviewed"
            )
        if section in counts:
            raise RegistryError(f"{resolved.name}: §{section} listed twice")
        counts[section] = (hard_must, " ".join(basis.split()))
    return counts


def reconcile(
    registry: NormativeStatementRegistry, counts: dict[str, tuple[int, str]]
) -> tuple[SectionCoverage, ...]:
    """Produce one reconciliation row per audited section."""
    rows: list[SectionCoverage] = []
    for section, (hard_must, basis) in counts.items():
        entries = [s for s in registry.statements if s.section == section]
        rows.append(
            SectionCoverage(
                section=section,
                hard_must=hard_must,
                live_must=sum(1 for s in entries if s.level == "MUST" and not s.is_deferred),
                deferred_must=sum(1 for s in entries if s.level == "MUST" and s.is_deferred),
                should=sum(1 for s in entries if s.level != "MUST"),
                basis=basis,
            )
        )
    return tuple(sorted(rows, key=lambda row: _section_sort_key(row.section)))


def _section_sort_key(section: str) -> list[int]:
    return [int(part) for part in section.split(".")]


def unbalanced(rows: tuple[SectionCoverage, ...]) -> list[str]:
    """Sections whose delta is not zero -- §23.5's pass condition."""
    return [
        f"§{row.section}: hard_must={row.hard_must} but covered={row.covered} "
        f"(live={row.live_must}, deferred={row.deferred_must}); delta={row.delta}"
        for row in rows
        if not row.balances
    ]


def unaudited_sections(
    registry: NormativeStatementRegistry,
    counts: dict[str, tuple[int, str]],
    low: int = AUDIT_RANGE[0],
    high: int = AUDIT_RANGE[1],
) -> list[str]:
    """Registry sections inside the audited range that the count file does not list.

    Catches an audit that reconciles perfectly while omitting a section that *has* registry
    entries. Necessary but not sufficient -- see :func:`unaudited_headings`, which catches the
    worse case where a section reached neither the registry nor the count file.
    """
    missing: set[str] = set()
    for statement in registry.statements:
        head = statement.section.split(".")[0]
        if not head.isdigit() or not (low <= int(head) <= high):
            continue
        if statement.section not in counts:
            missing.add(statement.section)
    return sorted(missing, key=_section_sort_key)


def spec_headings(
    path: Path | None = None,
    low: int = AUDIT_RANGE[0],
    high: int = AUDIT_RANGE[1],
) -> dict[str, str]:
    """Every numbered heading in the audited range, parsed from the specification.

    The source of truth for "which sections exist" has to be the document, not the registry.
    Deriving it from the registry only ever confirms that the sections someone already registered
    were counted -- a chapter of prose that reached neither the registry nor the count file would
    be invisible, and the audit would balance because nobody looked at it.
    """
    text = (path or spec_path()).read_text(encoding="utf-8")
    start = text.index(f"\n# {low}. ")
    end = text.index(f"\n# {high + 1}. ")
    headings: dict[str, str] = {}
    for match in _HEADING.finditer(text[start:end]):
        section, title = match.group(1), match.group(2).strip()
        head = section.split(".")[0]
        if head.isdigit() and low <= int(head) <= high:
            headings[section] = title
    if not headings:
        raise RegistryError(
            f"no §{low}-§{high} headings parsed from the specification; the heading format has "
            "probably changed and this completeness check is no longer checking anything"
        )
    return headings


def unaudited_headings(counts: dict[str, tuple[int, str]], path: Path | None = None) -> list[str]:
    """Spec headings absent from the count file.

    A section with ``hard_must: 0`` still has to be listed, with a basis explaining why it is
    zero. "This section states no obligation" is a reviewable claim; silence is not.
    """
    headings = spec_headings(path)
    return [
        f"§{section} {title}"
        for section, title in sorted(
            ((s, t) for s, t in headings.items() if s not in counts),
            key=lambda pair: _section_sort_key(pair[0]),
        )
    ]


def counted_but_absent_from_spec(
    counts: dict[str, tuple[int, str]], path: Path | None = None
) -> list[str]:
    """Count-file sections with no corresponding spec heading.

    The inverse drift: a section renumbered or removed by a spec amendment would otherwise keep
    contributing a stale row to the reconciliation.
    """
    headings = spec_headings(path)
    return sorted((section for section in counts if section not in headings), key=_section_sort_key)


def render_table(rows: tuple[SectionCoverage, ...]) -> str:
    """Markdown table for the audit document, generated from the same data the test checks."""
    header = (
        "| Section | hard MUST | registry-covered (live) | named deferred "
        "| SHOULD (excluded) | delta |"
    )
    lines = [header, "|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        deferred = str(row.deferred_must) if row.deferred_must else "—"
        should = str(row.should) if row.should else "—"
        lines.append(
            f"| {row.section} | {row.hard_must} | {row.live_must} | {deferred} "
            f"| {should} | {row.delta} |"
        )
    totals = (
        sum(r.hard_must for r in rows),
        sum(r.live_must for r in rows),
        sum(r.deferred_must for r in rows),
        sum(r.should for r in rows),
    )
    lines.append(
        f"| **Total** | **{totals[0]}** | **{totals[1]}** | **{totals[2]}** "
        f"| {totals[3]} | **{totals[0] - totals[1] - totals[2]}** |"
    )
    return "\n".join(lines)


__all__ = [
    "AUDIT_RANGE",
    "SectionCoverage",
    "counted_but_absent_from_spec",
    "hard_must_counts_path",
    "load_hard_must_counts",
    "reconcile",
    "render_table",
    "spec_headings",
    "unaudited_headings",
    "unaudited_sections",
    "unbalanced",
]
