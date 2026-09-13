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

import hashlib
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

#: Explicit hard-obligation keywords. English forms are matched case-sensitively because a
#: lowercase "must" in prose is not the normative keyword §0.2 defines; the Chinese forms are the
#: spec's own vocabulary. `需` is deliberately absent -- it reads as "requires" in some places and
#: "needs" in others, so an automatic match would manufacture obligations. Occurrences phrased with
#: `需` are adjudicated by hand and recorded in the inventory with `keyword: 需 (manual)`.
_HARD_KEYWORDS = ("MUST NOT", "MUST", "必須", "不得", "不可")
_KEYWORD_RE = re.compile("|".join(re.escape(keyword) for keyword in _HARD_KEYWORDS))


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


def load_keyword_free(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Load the per-section list of registered MUSTs the spec states without a hard keyword.

    These are the false negatives a keyword scan cannot see: a schema rule, a table cell, an
    obligation phrased with 不是 / 不提供 / 都要 / 保存. They are legitimate, and they are also
    where a fabricated count could hide, so each has to name the statement key and quote how the
    section states it. A bare count with no key would be unreviewable.
    """
    resolved = path or hard_must_counts_path()
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    out: dict[str, tuple[str, ...]] = {}
    for row in data["sections"]:
        section = row["section"]
        entries = row.get("keyword_free") or []
        if not isinstance(entries, list):
            raise RegistryError(f"{resolved.name}: §{section} keyword_free must be a list")
        keys: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise RegistryError(f"{resolved.name}: §{section} keyword_free needs mappings")
            key = entry.get("key")
            rationale = entry.get("rationale", "")
            if not isinstance(key, str) or not key.strip():
                raise RegistryError(f"{resolved.name}: §{section} keyword_free entry needs a key")
            if not isinstance(rationale, str) or not rationale.strip():
                raise RegistryError(
                    f"{resolved.name}: §{section} keyword_free '{key}' needs a rationale quoting "
                    "how the section states the obligation without a keyword"
                )
            if key in keys:
                raise RegistryError(f"{resolved.name}: §{section} keyword_free lists {key} twice")
            keys.append(key)
        out[section] = tuple(keys)
    return out


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


@dataclass(frozen=True)
class Occurrence:
    """One explicit hard-obligation keyword occurrence in the audited range.

    Identity is ``{section}#{ordinal}`` -- the ordinal counts keyword matches within the section,
    in document order. ``quote_digest`` covers the containing line, so editing the sentence forces
    the classification to be re-reviewed instead of silently carrying over.
    """

    section: str
    ordinal: int
    keyword: str
    quote: str

    @property
    def occurrence_id(self) -> str:
        return f"{self.section}#{self.ordinal}"

    @property
    def quote_digest(self) -> str:
        normalized = " ".join(self.quote.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def hard_obligation_occurrences(
    path: Path | None = None,
    low: int = AUDIT_RANGE[0],
    high: int = AUDIT_RANGE[1],
) -> tuple[Occurrence, ...]:
    """Every explicit hard-obligation keyword occurrence in §6-§16, in document order.

    Section-level counting let a section be written off as ``hard_must: 0`` with a prose note
    saying the rule was "registered elsewhere", and nothing forced that note to name which
    statement. Occurrence-level inventory does: each match below must be classified, and a
    RESTATEMENT_OF classification has to name a statement_key that resolves.
    """
    text = (path or spec_path()).read_text(encoding="utf-8")
    start = text.index(f"\n# {low}. ")
    end = text.index(f"\n# {high + 1}. ")
    body = text[start:end]

    boundaries = [
        (match.start(), match.group(1))
        for match in _HEADING.finditer(body)
        if match.group(1).split(".")[0].isdigit()
        and low <= int(match.group(1).split(".")[0]) <= high
    ]

    def section_at(position: int) -> str:
        current = str(low)
        for offset, section in boundaries:
            if offset <= position:
                current = section
            else:
                break
        return current

    per_section: dict[str, int] = {}
    occurrences: list[Occurrence] = []
    for line_match in re.finditer(r"^.*$", body, re.MULTILINE):
        line = line_match.group(0)
        if not line.strip() or line.lstrip().startswith("|---"):
            continue
        section = section_at(line_match.start())
        # Skip the heading line itself.
        if _HEADING.match(line):
            continue
        for keyword_match in _KEYWORD_RE.finditer(line):
            keyword = keyword_match.group(0)
            # "MUST NOT" also matches "MUST"; the alternation is ordered so MUST NOT wins, but a
            # nested match can still appear. Skip a MUST that is the head of a MUST NOT.
            head = line[keyword_match.start() : keyword_match.start() + 8]
            if keyword == "MUST" and head == "MUST NOT":
                continue
            ordinal = per_section.get(section, 0) + 1
            per_section[section] = ordinal
            occurrences.append(
                Occurrence(
                    section=section,
                    ordinal=ordinal,
                    keyword=keyword,
                    quote=line.strip(),
                )
            )
    return tuple(occurrences)


def counted_but_absent_from_spec(
    counts: dict[str, tuple[int, str]], path: Path | None = None
) -> list[str]:
    """Count-file sections with no corresponding spec heading.

    The inverse drift: a section renumbered or removed by a spec amendment would otherwise keep
    contributing a stale row to the reconciliation.
    """
    headings = spec_headings(path)
    return sorted((section for section in counts if section not in headings), key=_section_sort_key)


#: The three classifications an occurrence may carry. There is no fourth, and no default: an
#: occurrence the maintainer has not looked at fails CI rather than being assumed benign.
CLASSIFICATIONS = ("REGISTERED", "RESTATEMENT_OF", "NON_NORMATIVE_WITH_RATIONALE")

#: Manual occurrence ids -- the 需-phrased obligations, adjudicated by hand. They carry an extract
#: rather than a whole line, so there is no digest to check against the document.
_MANUAL_ID = re.compile(r"^\d+(?:\.\d+)*#M\d+$")


@dataclass(frozen=True)
class Adjudication:
    """One occurrence plus the classification a maintainer gave it."""

    occurrence_id: str
    section: str
    keyword: str
    quote: str
    classification: str
    target: str
    note: str
    quote_digest: str

    @property
    def is_manual(self) -> bool:
        return bool(_MANUAL_ID.match(self.occurrence_id))


def obligation_inventory_path(audit: str = "M0a") -> Path:
    return repo_root() / "docs" / "spec_coverage_audit" / f"{audit}_obligation_inventory.yaml"


def load_obligation_inventory(path: Path | None = None) -> tuple[Adjudication, ...]:
    """Load the occurrence-level inventory, validating its shape as it goes.

    Shape errors are raised here rather than asserted in a test so that every consumer -- the
    tests, the rebuild script, the audit generator -- sees the same rules. A row missing its
    ``target`` on a REGISTERED classification is not a soft finding; it means the inventory does
    not say what obligation the occurrence discharges, which is the whole point of the file.
    """
    resolved = path or obligation_inventory_path()
    if not resolved.is_file():
        raise RegistryError(f"obligation inventory not found: {resolved}")
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegistryError(f"{resolved.name} must contain a top-level mapping")
    rows = data.get("occurrences")
    if not isinstance(rows, list) or not rows:
        raise RegistryError(f"{resolved.name}: 'occurrences' must be a non-empty list")

    out: list[Adjudication] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RegistryError(f"{resolved.name}: occurrences[{index}] must be a mapping")
        occurrence_id = row.get("occurrence_id")
        if not isinstance(occurrence_id, str) or "#" not in occurrence_id:
            raise RegistryError(f"{resolved.name}: occurrences[{index}] needs an occurrence_id")
        if occurrence_id in seen:
            raise RegistryError(f"{resolved.name}: {occurrence_id} listed twice")
        seen.add(occurrence_id)

        classification = row.get("classification")
        if classification not in CLASSIFICATIONS:
            raise RegistryError(
                f"{resolved.name}: {occurrence_id} has classification {classification!r}; "
                f"must be one of {', '.join(CLASSIFICATIONS)}"
            )
        target = row.get("target", "")
        note = row.get("note", "")
        if classification == "NON_NORMATIVE_WITH_RATIONALE":
            if target:
                raise RegistryError(
                    f"{resolved.name}: {occurrence_id} is NON_NORMATIVE but names a target; a "
                    "keyword doing no normative work cannot discharge a statement"
                )
            if not str(note).strip():
                raise RegistryError(
                    f"{resolved.name}: {occurrence_id} is NON_NORMATIVE_WITH_RATIONALE and has no "
                    "rationale; the classification's own name requires one"
                )
        elif not isinstance(target, str) or not target.strip():
            raise RegistryError(
                f"{resolved.name}: {occurrence_id} is {classification} and names no target "
                "statement_key -- which is the write-off this inventory exists to prevent"
            )
        quote = row.get("quote", "")
        if not isinstance(quote, str) or not quote.strip():
            raise RegistryError(f"{resolved.name}: {occurrence_id} has no quote")

        out.append(
            Adjudication(
                occurrence_id=occurrence_id,
                section=str(row.get("section", occurrence_id.split("#")[0])),
                keyword=str(row.get("keyword", "")),
                quote=quote,
                classification=str(classification),
                target=str(target),
                note=" ".join(str(note).split()),
                quote_digest=str(row.get("quote_digest", "")),
            )
        )
    return tuple(out)


def unclassified_occurrences(
    inventory: tuple[Adjudication, ...], path: Path | None = None
) -> list[str]:
    """Spec occurrences with no row in the inventory.

    This is the guard that makes the inventory complete rather than merely long: a new hard
    obligation added by an amendment appears here until someone adjudicates it.
    """
    adjudicated = {row.occurrence_id for row in inventory}
    return [
        f"{o.occurrence_id} [{o.keyword}] {o.quote[:110]}"
        for o in hard_obligation_occurrences(path)
        if o.occurrence_id not in adjudicated
    ]


def stale_adjudications(inventory: tuple[Adjudication, ...], path: Path | None = None) -> list[str]:
    """Inventory rows whose occurrence no longer exists in the spec.

    The inverse drift. A sentence deleted by an amendment must not leave behind a row that keeps
    asserting the obligation is accounted for.
    """
    present = {o.occurrence_id for o in hard_obligation_occurrences(path)}
    return [
        row.occurrence_id
        for row in inventory
        if not row.is_manual and row.occurrence_id not in present
    ]


def drifted_quotes(inventory: tuple[Adjudication, ...], path: Path | None = None) -> list[str]:
    """Rows whose recorded digest no longer matches the spec line.

    Reworded prose can change what a sentence obliges while keeping its position, so a
    classification must not be inherited across an edit. Manual rows are excluded: their quote is
    an extract from a line, not the line.
    """
    by_id = {o.occurrence_id: o for o in hard_obligation_occurrences(path)}
    drifted: list[str] = []
    for row in inventory:
        if row.is_manual:
            continue
        occurrence = by_id.get(row.occurrence_id)
        if occurrence is None:
            continue  # reported by stale_adjudications
        if row.quote_digest != occurrence.quote_digest:
            drifted.append(
                f"{row.occurrence_id}: recorded {row.quote_digest or '<none>'}, "
                f"spec now {occurrence.quote_digest}"
            )
    return drifted


def unresolved_targets(
    inventory: tuple[Adjudication, ...], registry: NormativeStatementRegistry
) -> list[str]:
    """Named targets that are not statement keys in the registry."""
    keys = {statement.key for statement in registry.statements}
    return [
        f"{row.occurrence_id} -> {row.target}"
        for row in inventory
        if row.target and row.target not in keys
    ]


def doubly_registered(inventory: tuple[Adjudication, ...]) -> list[str]:
    """Statement keys claimed as REGISTERED by more than one occurrence.

    Each statement has one prose home. Two occurrences claiming the same key would let one
    obligation be counted twice, inflating a section's hard_must and manufacturing the coverage to
    match it. Repetition is what RESTATEMENT_OF is for.
    """
    homes: dict[str, list[str]] = {}
    for row in inventory:
        if row.classification == "REGISTERED":
            homes.setdefault(row.target, []).append(row.occurrence_id)
    return [
        f"{target} claimed by {', '.join(ids)}"
        for target, ids in sorted(homes.items())
        if len(ids) > 1
    ]


def registered_per_section(inventory: tuple[Adjudication, ...]) -> dict[str, int]:
    """REGISTERED occurrence count per section -- the derived half of ``hard_must``."""
    counts: dict[str, int] = {}
    for row in inventory:
        if row.classification == "REGISTERED":
            counts[row.section] = counts.get(row.section, 0) + 1
    return counts


def count_disagreements(
    counts: dict[str, tuple[int, str]],
    keyword_free: dict[str, tuple[str, ...]],
    inventory: tuple[Adjudication, ...],
) -> list[str]:
    """Sections where ``hard_must`` is not what the inventory and keyword-free list imply.

    The cross-check that stops ``hard_must`` from being a free-floating number: it must equal the
    REGISTERED occurrences at the section plus the registered MUSTs the spec states without a
    keyword. Two files, maintained separately, forced to agree.
    """
    registered = registered_per_section(inventory)
    problems: list[str] = []
    for section, (hard_must, _) in sorted(counts.items(), key=lambda p: _section_sort_key(p[0])):
        derived = registered.get(section, 0) + len(keyword_free.get(section, ()))
        if hard_must != derived:
            problems.append(
                f"§{section}: hard_must={hard_must} but inventory implies {derived} "
                f"({registered.get(section, 0)} REGISTERED + "
                f"{len(keyword_free.get(section, ()))} keyword-free)"
            )
    return problems


def undeclared_keyword_free(
    keyword_free: dict[str, tuple[str, ...]],
    inventory: tuple[Adjudication, ...],
    registry: NormativeStatementRegistry,
    low: int = AUDIT_RANGE[0],
    high: int = AUDIT_RANGE[1],
) -> list[str]:
    """Registered MUSTs in range that neither have a REGISTERED occurrence nor are declared.

    Without this, a statement could be registered at a section, have no prose occurrence, and go
    unmentioned -- so nobody would ever be asked how the spec actually states it. §10.5's rule,
    which rides entirely on 不是, is exactly that case.
    """
    homes = {row.target for row in inventory if row.classification == "REGISTERED"}
    declared = {key for keys in keyword_free.values() for key in keys}
    missing: list[str] = []
    for statement in registry.statements:
        head = statement.section.split(".")[0]
        if not head.isdigit() or not (low <= int(head) <= high):
            continue
        if statement.level != "MUST":
            continue
        if statement.key not in homes and statement.key not in declared:
            missing.append(f"§{statement.section} {statement.key}")
    return sorted(missing)


def headings_asserting_obligations(
    counts: dict[str, tuple[int, str]], path: Path | None = None
) -> list[str]:
    """Sections whose *heading* carries a hard keyword but whose count is 0.

    Heading lines are excluded from the occurrence scan, on the rule that a title asserting an
    obligation must state it in the body. That rule needs enforcing, or the exclusion becomes a
    place for an obligation to hide: §14.4.1's heading is 「ReviewQueue 必須接回 Verification
    Planner」, and if its body stated nothing the section would count 0 and no scan would object.
    """
    return [
        f"§{section} {title}"
        for section, title in sorted(
            spec_headings(path).items(), key=lambda pair: _section_sort_key(pair[0])
        )
        if _KEYWORD_RE.search(title) and counts.get(section, (0, ""))[0] == 0
    ]


def render_inventory_summary(inventory: tuple[Adjudication, ...]) -> str:
    """Markdown table of the classification totals, for the audit document."""
    lines = ["| Classification | Occurrences |", "|---|---:|"]
    for classification in CLASSIFICATIONS:
        lines.append(
            f"| `{classification}` | "
            f"{sum(1 for row in inventory if row.classification == classification)} |"
        )
    lines.append(f"| **Total** | **{len(inventory)}** |")
    return "\n".join(lines)


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
    "CLASSIFICATIONS",
    "Adjudication",
    "Occurrence",
    "SectionCoverage",
    "count_disagreements",
    "counted_but_absent_from_spec",
    "doubly_registered",
    "drifted_quotes",
    "hard_must_counts_path",
    "hard_obligation_occurrences",
    "headings_asserting_obligations",
    "load_hard_must_counts",
    "load_keyword_free",
    "load_obligation_inventory",
    "obligation_inventory_path",
    "reconcile",
    "registered_per_section",
    "render_inventory_summary",
    "render_table",
    "spec_headings",
    "stale_adjudications",
    "unaudited_headings",
    "unaudited_sections",
    "unbalanced",
    "unclassified_occurrences",
    "undeclared_keyword_free",
    "unresolved_targets",
]
