"""The discovery loop's numerics are exact where they claim to be: box least squares and chi-square.

Pinned against known chi-square quantiles and against a brute-force grid over the box, so a change
to the active-set enumeration or the incomplete-gamma evaluation shows up as a failure rather than
as a quietly different refutation threshold.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from lab_brain.discovery.numerics import MAX_VARIABLES, box_lsq, chi2_sf


@pytest.mark.parametrize(
    ("x", "dof", "expected"),
    [
        (3.841458820694124, 1, 0.05),
        (10.827566170662733, 1, 0.001),
        (5.991464547107979, 2, 0.05),
        (18.307038053275146, 10, 0.05),
        (29.58829844507442, 10, 0.001),
        (0.454936423119572, 1, 0.5),
    ],
)
def test_chi2_tail_matches_textbook_quantiles(x, dof, expected):
    assert chi2_sf(x, dof) == pytest.approx(expected, rel=1e-6)


def test_chi2_tail_edge_cases():
    assert chi2_sf(0.0, 3) == 1.0
    assert chi2_sf(-1.0, 3) == 1.0
    assert 0.0 <= chi2_sf(1e4, 2) < 1e-300 or chi2_sf(1e4, 2) == 0.0
    with pytest.raises(ValueError):
        chi2_sf(1.0, 0)


def _objective(columns, y, x):
    return math.fsum(
        (sum(xi * c[j] for xi, c in zip(x, columns, strict=True)) - y[j]) ** 2
        for j in range(len(y))
    )


@pytest.mark.parametrize("k", [1, 2, 3])
def test_box_lsq_is_never_beaten_by_a_grid_over_the_box(k):
    rng = random.Random(f"box:{k}")
    for _ in range(25):
        n = rng.randint(k, 6)
        columns = [[rng.uniform(-3, 3) for _ in range(n)] for _ in range(k)]
        y = [rng.uniform(-10, 10) for _ in range(n)]
        lower = [rng.uniform(-2, 0) for _ in range(k)]
        upper = [lo + rng.uniform(0.1, 3) for lo in lower]
        x, value = box_lsq(columns, y, lower, upper)
        assert all(lo - 1e-9 <= v <= hi + 1e-9 for v, lo, hi in zip(x, lower, upper, strict=True))
        assert value == pytest.approx(_objective(columns, y, x), abs=1e-7)
        steps = 12
        grid = [
            [lo + (hi - lo) * i / steps for i in range(steps + 1)]
            for lo, hi in zip(lower, upper, strict=True)
        ]
        best_grid = min(_objective(columns, y, point) for point in itertools.product(*grid))
        assert value <= best_grid + 1e-7


def test_box_lsq_interior_solution_is_ordinary_least_squares():
    columns = [[1.0, 0.0, 1.0], [0.0, 1.0, 1.0]]
    y = [1.0, 2.0, 3.0]
    x, value = box_lsq(columns, y, [-10, -10], [10, 10])
    assert x == pytest.approx((1.0, 2.0))
    assert value == pytest.approx(0.0, abs=1e-12)


def test_box_lsq_refuses_what_it_cannot_do_exactly():
    with pytest.raises(ValueError):
        box_lsq([[1.0]] * (MAX_VARIABLES + 1), [1.0], [0.0] * 5, [1.0] * 5)
    with pytest.raises(ValueError):
        box_lsq([[1.0]], [1.0], [2.0], [1.0])
    with pytest.raises(ValueError):
        box_lsq([[1.0, 2.0]], [1.0], [0.0], [1.0])


def test_box_lsq_with_no_variables_is_the_residual_norm():
    assert box_lsq([], [3.0, 4.0], [], []) == ((), 25.0)
