"""G0 independent-holdout workflow, statistics: Wilson and the seeded bootstrap are deterministic.

The values pinned here are known ones (Wilson 8/10 = 0.490..0.943 is the textbook example) or
were computed once by this implementation and fixed, so any change to the draw or the quantile
rule shows up as a failure rather than as a silently different interval in a report.
"""

from __future__ import annotations

import pytest

from lab_brain.evaluation.stats import bootstrap, wilson


@pytest.mark.parametrize(
    ("k", "n", "expected"),
    [
        (8, 10, (0.4902, 0.9433)),
        (0, 10, (0.0, 0.2775)),
        (10, 10, (0.7225, 1.0)),
        (1, 2, (0.0945, 0.9055)),
    ],
)
def test_wilson_matches_known_values(k, n, expected):
    assert wilson(k, n) == expected


def test_wilson_has_no_interval_without_evidence_and_refuses_impossible_counts():
    assert wilson(0, 0) is None
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_bootstrap_is_reproducible_from_its_recorded_seed():
    values = [True] * 7 + [False] * 3
    first = bootstrap(values, seed=7, resamples=1000, label="m")
    assert first == bootstrap(values, seed=7, resamples=1000, label="m") == (0.4, 0.9)
    # The seed is what makes it reproducible -- another seed is another draw.
    assert bootstrap(values, seed=8, resamples=1000, label="m") == (0.4, 1.0)


def test_bootstrap_degenerate_cases():
    assert bootstrap([], seed=1, resamples=10, label="x") is None
    assert bootstrap([True] * 5, seed=1, resamples=200, label="x") == (1.0, 1.0)
    assert bootstrap([False] * 5, seed=1, resamples=200, label="x") == (0.0, 0.0)
    with pytest.raises(ValueError):
        bootstrap([True], seed=1, resamples=0, label="x")
