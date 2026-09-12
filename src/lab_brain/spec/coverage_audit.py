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

from dataclasses import dataclass
from pathlib import Path

import yaml

from lab_brain.spec.parser import repo_root
from lab_brain.spec.registry import NormativeStatementRegistry, RegistryError


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
    low: int = 6,
    high: int = 16,
) -> list[str]:
    """Registry sections inside the audited range that the count file does not list.

    Without this an audit could reconcile perfectly while silently omitting a whole section --
    the numbers would balance because the section was never counted.
    """
    missing: set[str] = set()
    for statement in registry.statements:
        head = statement.section.split(".")[0]
        if not head.isdigit() or not (low <= int(head) <= high):
            continue
        if statement.section not in counts:
            missing.add(statement.section)
    return sorted(missing, key=_section_sort_key)


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
    "SectionCoverage",
    "hard_must_counts_path",
    "load_hard_must_counts",
    "reconcile",
    "render_table",
    "unaudited_sections",
    "unbalanced",
]
