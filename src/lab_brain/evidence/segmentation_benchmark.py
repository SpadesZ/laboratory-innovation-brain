"""The T-EVI-010 benchmark — evidence-aware segmentation against the fixed-token baseline.

WHY THE PASS CONDITION IS PER CASE AND NOT A THRESHOLD. This is the part of §26's row that is
easy to read past, and it is the reason `SPEC-ISSUE-013` was escalated rather than settled.

Recall and precision over well-formed questions are largely **insensitive** to whether conditions
travelled with their result, because the retriever usually surfaces the neighbouring chunk too.
So a fixed-token splitter scores respectably on the metrics everyone reports, and the corruption
it causes appears much later, in the belief path, as a corroboration that was never valid. A
corpus-level threshold is therefore the one form of pass condition that cannot separate the two
strategies -- which is why the expected outcome is fixed per case, and why the ordinary retrieval
metrics are reported *beside* the boundary ones rather than instead of them.

WHAT THE FIRST RUN ACTUALLY SHOWED, which is stronger than "the metrics are close". On the
locked fixture the fixed-token baseline scores **1.00 boundary completeness, 1.00 condition
retention and a higher precision@5** than the evidence-aware segmenter, while scoring **0.00 on
table context, figure context and locator recovery**.

Both halves have an explanation and both are load-bearing:

  * A 200-token window over a 518-token document produces three units, each large enough to
    contain any probe's fragments incidentally. That is not the Minimum Evidence Boundary §6.22
    defines -- the *smallest* complete unit -- it is the opposite failure, reached by not really
    cutting. Boundary completeness cannot distinguish "kept together deliberately" from "never
    separated because nothing was separated".
  * Three units also flatter precision@k, because retrieving five candidates returns everything.

So on this fixture a corpus-level threshold over the usual metrics would have **selected the
prohibited strategy**. That is the concrete form of the argument `SPEC-ISSUE-013` escalated, and
it is why §26 fixes the outcome per case. Read the report accordingly: the structural columns are
the ones that correspond to a scientific failure; the retrieval columns are reported because §26
requires them and because their *non*-discrimination is itself the finding.

WHAT IS MEASURED, and what each measures that the others do not::

    boundary completeness   does SOME single unit hold every fragment a reader needs together?
    condition retention     of the condition/result probes, how many kept both halves?
    table context           does the retrieved table unit still have headers, units and rows?
    figure context          does the retrieved figure unit still have caption AND prose?
    locator recovery        do the unit's offsets resolve to non-empty text in the source?
    candidate recall        of the units that are relevant, how many were retrieved at k?
    candidate precision     of the units retrieved at k, how many were relevant?
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lab_brain.core.models.enums import EvidenceUnitType
from lab_brain.core.models.evidence_unit import EvidenceUnit
from lab_brain.evidence.retriever import LexicalEvidenceIndex
from lab_brain.ingestion.parsers.structure import ParsedDocument

#: Retrieval depth for recall/precision. Fixed rather than tuned: the benchmark compares
#: segmentation strategies, and a k chosen after seeing the results would be measuring the
#: choice of k.
DEFAULT_K = 5


@dataclass(frozen=True)
class BenchmarkProbe:
    """One case of the locked fixture, with the outcome §26 fixes for it."""

    probe_id: str
    kind: str
    query: str
    #: Fragments that MUST all appear together in one unit's interpretive text. This is the
    #: boundary claim: a strategy that files them separately fails this probe however well it
    #: ranks.
    required_together: tuple[str, ...]
    #: A unit is relevant to this probe if its text contains any of these.
    relevance_markers: tuple[str, ...]


@dataclass
class StrategyReport:
    """One strategy's numbers over the whole probe set."""

    strategy: str
    unit_count: int
    boundary_completeness: float = 0.0
    condition_retention: float = 0.0
    table_context_retention: float = 0.0
    figure_context_retention: float = 0.0
    locator_recovery: float = 0.0
    candidate_recall: float = 0.0
    candidate_precision: float = 0.0
    failed_probes: tuple[str, ...] = ()
    per_probe: dict[str, bool] = field(default_factory=dict)

    def as_row(self) -> str:
        return (
            f"| {self.strategy} | {self.unit_count} | "
            f"{self.boundary_completeness:.2f} | {self.condition_retention:.2f} | "
            f"{self.table_context_retention:.2f} | {self.figure_context_retention:.2f} | "
            f"{self.locator_recovery:.2f} | {self.candidate_recall:.2f} | "
            f"{self.candidate_precision:.2f} |"
        )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _contains_all(unit: EvidenceUnit, fragments: tuple[str, ...]) -> bool:
    text = unit.interpretive_text
    return all(fragment in text for fragment in fragments)


def evaluate(
    strategy: str,
    units: tuple[EvidenceUnit, ...],
    probes: tuple[BenchmarkProbe, ...],
    document: ParsedDocument,
    *,
    project_id: str,
    k: int = DEFAULT_K,
) -> StrategyReport:
    """Score one strategy's units against the probe set."""
    report = StrategyReport(strategy=strategy, unit_count=len(units))
    if not units:
        return report

    index = LexicalEvidenceIndex(index_id=f"idx:{strategy}")
    index.add_all(units, project_id=project_id)
    by_id = {unit.evidence_unit_id: unit for unit in units}

    boundary_hits = 0
    condition_probes = condition_hits = 0
    table_probes = table_hits = 0
    figure_probes = figure_hits = 0
    recall_sum = precision_sum = 0.0
    failed: list[str] = []

    for probe in probes:
        # Boundary completeness is a property of the SEGMENTATION, not of the ranking: does any
        # unit hold the fragments together, whether or not retrieval found it?
        held_together = any(_contains_all(unit, probe.required_together) for unit in units)
        report.per_probe[probe.probe_id] = held_together
        if held_together:
            boundary_hits += 1
        else:
            failed.append(probe.probe_id)

        if probe.kind == "CONDITION_RESULT":
            condition_probes += 1
            condition_hits += int(held_together)

        candidates = index.search(probe.query, project_id=project_id, limit=k)
        retrieved = [by_id[c.evidence_unit_id] for c in candidates]
        relevant = {
            unit.evidence_unit_id
            for unit in units
            if any(marker in unit.interpretive_text for marker in probe.relevance_markers)
        }
        retrieved_ids = {unit.evidence_unit_id for unit in retrieved}
        hits = len(retrieved_ids & relevant)
        recall_sum += _ratio(hits, len(relevant))
        precision_sum += _ratio(hits, len(retrieved_ids))

        if probe.kind == "TABLE":
            table_probes += 1
            # Retention AND retrievability: the table context has to survive *and* the unit
            # holding it has to come back for a query about its contents.
            table_hits += int(
                any(
                    unit.unit_type is EvidenceUnitType.TABLE
                    and unit.table_context is not None
                    and unit.table_context.is_interpretable
                    for unit in retrieved
                )
            )

        if probe.kind == "FIGURE":
            figure_probes += 1
            figure_hits += int(
                any(
                    unit.unit_type is EvidenceUnitType.FIGURE
                    and unit.figure_context is not None
                    and unit.figure_context.is_interpretable
                    for unit in retrieved
                )
            )

    resolvable = sum(
        1
        for unit in units
        if unit.locator.start_offset is not None
        and unit.locator.end_offset is not None
        and document.source_text[unit.locator.start_offset : unit.locator.end_offset].strip()
    )

    report.boundary_completeness = _ratio(boundary_hits, len(probes))
    report.condition_retention = _ratio(condition_hits, condition_probes)
    report.table_context_retention = _ratio(table_hits, table_probes)
    report.figure_context_retention = _ratio(figure_hits, figure_probes)
    report.locator_recovery = _ratio(resolvable, len(units))
    report.candidate_recall = recall_sum / len(probes) if probes else 0.0
    report.candidate_precision = precision_sum / len(probes) if probes else 0.0
    report.failed_probes = tuple(failed)
    return report


def render_report(reports: tuple[StrategyReport, ...], probes: tuple[BenchmarkProbe, ...]) -> str:
    """Markdown, both strategies side by side, with the per-probe detail underneath."""
    lines = [
        "| Strategy | units | boundary | condition | table ctx | figure ctx "
        "| locator | recall@5 | precision@5 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(report.as_row() for report in reports)
    lines.append("")
    lines.append("| Probe | Kind | " + " | ".join(r.strategy for r in reports) + " |")
    lines.append("|---|---|" + "---|" * len(reports))
    for probe in probes:
        cells = [
            "PASS" if report.per_probe.get(probe.probe_id) else "**FAIL**" for report in reports
        ]
        lines.append(f"| `{probe.probe_id}` | {probe.kind} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_K",
    "BenchmarkProbe",
    "StrategyReport",
    "evaluate",
    "render_report",
]
