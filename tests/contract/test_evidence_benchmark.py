"""T-EVI-010 — the locked benchmark, per-case (EVI-010, §26).

Pass condition (§26), the benchmark half: the fixture's five cases each have a fixed expected
outcome, and the report publishes seven metrics **for both strategies** so regression against the
locked fixture is visible.

What this file asserts:

  * each of the five cases holds, for the evidence-aware segmenter -- the actual gate;
  * every required metric is computed and in range, so the published report cannot silently
    lose a column;
  * the baseline is *measured*, and where it differs is exactly where a scientific failure lives
    rather than where a ranking is annoying.

What it deliberately does NOT assert: that the evidence-aware strategy beats the baseline on
recall or precision. §26 provides no such threshold and inventing one would be this file's
opinion rather than the specification's -- and worse, it would be an opinion the baseline can
satisfy, because the two strategies are genuinely close on those metrics. That closeness is the
finding, not a problem with the fixture.
"""

from __future__ import annotations

import pytest

from lab_brain.evidence.segmentation_benchmark import evaluate, render_report
from lab_brain.ingestion.fixed_token_baseline import BaselineRun, FixedTokenBaselineSegmenter
from tests.benchmark_probes import EXPECTED_EVIDENCE_AWARE, PROBES
from tests.evidence_fixtures import parse_fixture, segment_fixture

PROJECT = "prj:test"

pytestmark = [pytest.mark.requirement("EVI-010"), pytest.mark.spec_test("T-EVI-010")]


@pytest.fixture(scope="module")
def reports():
    document = parse_fixture()
    aware = evaluate(
        "evidence-aware",
        segment_fixture().units,
        PROBES,
        document,
        project_id=PROJECT,
    )
    baseline = evaluate(
        "fixed-token",
        FixedTokenBaselineSegmenter().segment(
            document, run=BaselineRun(reason="T-EVI-010 comparison")
        ),
        PROBES,
        document,
        project_id=PROJECT,
    )
    return aware, baseline


@pytest.mark.parametrize("probe_id", sorted(EXPECTED_EVIDENCE_AWARE))
def test_each_locked_case_holds_for_the_evidence_aware_segmenter(reports, probe_id):
    """THE gate. One test per case, so a failure names which boundary was lost."""
    aware, _ = reports
    assert aware.per_probe.get(probe_id) is EXPECTED_EVIDENCE_AWARE[probe_id], (
        f"probe {probe_id} did not hold. The fragments it requires together were filed into "
        f"different evidence units. Failed probes: {aware.failed_probes}"
    )


def test_boundary_completeness_is_total_for_the_evidence_aware_segmenter(reports):
    """The aggregate of the five cases above, reported as its own metric."""
    aware, _ = reports
    assert aware.boundary_completeness == 1.0
    assert aware.failed_probes == ()


def test_every_required_metric_is_reported_for_both_strategies(reports):
    """§26 names seven metrics. A report that quietly dropped one would still look complete."""
    for report in reports:
        for metric in (
            "boundary_completeness",
            "condition_retention",
            "table_context_retention",
            "figure_context_retention",
            "locator_recovery",
            "candidate_recall",
            "candidate_precision",
        ):
            value = getattr(report, metric)
            assert isinstance(value, float), f"{report.strategy}.{metric} is not a number"
            assert 0.0 <= value <= 1.0, f"{report.strategy}.{metric} = {value} is out of range"


def test_condition_retention_and_context_retention_are_total(reports):
    """The three retention metrics, each corresponding to one §6.22 rule."""
    aware, _ = reports
    assert aware.condition_retention == 1.0, "rule 1: a condition was severed from its result"
    assert aware.table_context_retention == 1.0, "rule 5: a table lost its header/unit context"
    assert aware.figure_context_retention == 1.0, "rule 6: a figure lost its explanatory prose"


def test_every_unit_has_a_locator_that_resolves(reports):
    """Rule 7's locator half, over the whole corpus rather than per probe."""
    aware, _ = reports
    assert aware.locator_recovery == 1.0


def test_the_baseline_destroys_every_structural_context(reports):
    """Where the two strategies actually separate on this fixture.

    A fixed-token splitter reads the document as a string of tokens, so a table stops being a
    table and a figure stops being a figure. All three structural metrics go to zero: no
    header/unit context, no caption-plus-prose binding, and no locator that resolves -- because
    a token offset into a concatenated string is not a position in the document.
    """
    aware, baseline = reports
    assert baseline.unit_count > 0, "the baseline produced nothing to compare against"

    assert baseline.table_context_retention == 0.0
    assert baseline.figure_context_retention == 0.0
    assert baseline.locator_recovery == 0.0
    assert aware.table_context_retention == 1.0
    assert aware.figure_context_retention == 1.0
    assert aware.locator_recovery == 1.0


def test_the_ordinary_retrieval_metrics_do_not_punish_the_baseline(reports):
    """THE finding, and the reason §26's pass condition is per case rather than a threshold.

    On this fixture the baseline scores 1.00 boundary completeness, 1.00 condition retention and
    a *higher* precision@5 than the evidence-aware segmenter -- while losing every structural
    context above. Both halves of that are worth pinning:

    **Why its boundary score is 1.00.** A 200-token window over a 518-token document cuts it
    into three pieces, each large enough to contain any probe's fragments incidentally. That is
    not the Minimum Evidence Boundary §6.22 defines -- which is the *smallest* complete unit --
    it is the opposite failure, reached by not really cutting at all. The metric cannot tell the
    two apart, which is exactly its limitation.

    **Why its precision is higher.** With three units, retrieving five candidates returns
    everything, and "everything" contains all the relevant material. Fewer, larger units flatter
    precision@k for the same reason they flatter boundary completeness.

    So a corpus-level threshold on these metrics would have *selected the prohibited strategy*.
    That is the concrete form of the argument SPEC-ISSUE-013 escalated, and it is asserted here
    rather than described, so that a future change which makes the ordinary metrics separate the
    two strategies fails this test and forces the argument to be re-examined.
    """
    aware, baseline = reports

    assert baseline.boundary_completeness >= aware.boundary_completeness
    assert baseline.condition_retention >= aware.condition_retention
    assert baseline.candidate_recall >= aware.candidate_recall
    assert baseline.candidate_precision >= aware.candidate_precision, (
        "the baseline no longer matches or beats the evidence-aware segmenter on the ordinary "
        "retrieval metrics. If that is a real improvement, good -- but the argument that "
        "thresholds cannot separate these strategies now rests on different evidence and the "
        "benchmark's framing needs revisiting"
    )


def test_the_baseline_under_cuts_this_fixture_and_the_report_says_so(reports):
    """The degenerate-window observation, pinned so it cannot be read as a tuned result.

    Recorded as a test rather than a comment because it is the premise of the test above: the
    baseline's flattering numbers come from producing very few, very large units, and if the
    fixture ever grows enough that the window genuinely cuts it, the interpretation changes.
    """
    aware, baseline = reports
    assert baseline.unit_count < aware.unit_count / 3, (
        f"the baseline produced {baseline.unit_count} units against the segmenter's "
        f"{aware.unit_count}; it is no longer under-cutting this fixture, so its boundary and "
        "precision scores can no longer be explained by unit size alone"
    )


def test_the_report_renders_both_strategies_and_every_probe(reports):
    """The published artifact. A report missing a row is a report nobody can regress against."""
    rendered = render_report(reports, PROBES)
    for report in reports:
        assert report.strategy in rendered
    for probe in PROBES:
        assert probe.probe_id in rendered
    assert "recall@5" in rendered and "precision@5" in rendered
