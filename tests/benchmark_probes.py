"""The five locked T-EVI-010 probes, and the expected outcome §26 fixes for each.

Shared by ``tests/contract/test_evidence_benchmark.py`` and ``scripts/run_benchmark.py`` so the
test and the published report cannot disagree about what was measured.

The kinds map one-to-one onto §26's (a)-(e). ``EXPECTED_EVIDENCE_AWARE`` is the pass condition:
per case, not a score.
"""

from __future__ import annotations

from lab_brain.evidence.segmentation_benchmark import BenchmarkProbe
from tests.evidence_fixtures import CONDITION_SENTENCE, RESULT_SENTENCE

PROBES: tuple[BenchmarkProbe, ...] = (
    # (a) The condition/result split trap. Each sentence is well-formed alone; together they are
    #     a measurement, apart they are two unrelated true statements.
    BenchmarkProbe(
        probe_id="a.condition_result",
        kind="CONDITION_RESULT",
        query="junction capacitance reverse bias decreased",
        required_together=(CONDITION_SENTENCE, RESULT_SENTENCE),
        relevance_markers=("junction capacitance", "Reverse bias"),
    ),
    # (b) A table value that cannot be read without its header, unit and row.
    BenchmarkProbe(
        probe_id="b.table_value_needs_header_unit_row",
        kind="TABLE",
        query="extracted small-signal parameters Cj Rs split bias",
        required_together=("0.345", "Cj", "pF/mm"),
        relevance_markers=("0.345", "18.9"),
    ),
    # (c) A figure whose caption says what the axes are, not what the figure shows.
    BenchmarkProbe(
        probe_id="c.figure_needs_surrounding_prose",
        kind="FIGURE",
        query="capacitance curves indistinguishable series resistance differs splits",
        required_together=(
            "Junction capacitance versus reverse bias",
            "indistinguishable within measurement uncertainty",
        ),
        relevance_markers=("Fig. 2", "Figure 2"),
    ),
    # (d) A legitimately oversized unit. The §5 discussion is one continuous argument, so a
    #     fallback subdivision must keep the pieces interpretable rather than merely shorter.
    BenchmarkProbe(
        probe_id="d.oversized_unit_fallback",
        kind="OVERSIZED",
        query="contact resistance mesh artefact discriminate transmission line",
        required_together=("contact-resistance contribution",),
        relevance_markers=("contact resistance", "mesh artefact", "contact-resistance"),
    ),
    # (e) Values the document explicitly does not record. Nothing may supply them.
    BenchmarkProbe(
        probe_id="e.missing_value_stays_unknown",
        kind="MISSING_VALUE",
        query="wafer identifier implant dose recorded",
        required_together=("Wafer identifier and implant dose were not recorded",),
        relevance_markers=("not recorded by the measurement script",),
    ),
)

#: §26's pass condition, per case. The evidence-aware segmenter MUST hold every probe's fragments
#: together. This is the whole benchmark gate -- there is deliberately no corpus-level threshold,
#: because a threshold cannot separate the two strategies (see the benchmark module docstring).
EXPECTED_EVIDENCE_AWARE: dict[str, bool] = {probe.probe_id: True for probe in PROBES}

__all__ = ["EXPECTED_EVIDENCE_AWARE", "PROBES"]
