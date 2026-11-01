"""Exact small-problem numerics for the discovery loop: box-constrained least squares, chi-square.

No dependency beyond the standard library, and nothing approximate where exactness is cheap:

    box_lsq(columns, y, lower, upper)   min ||sum_i x_i * column_i - y||^2 over a box, for at
                                        most a handful of variables, by enumerating every active
                                        set (each variable at its lower bound, its upper bound or
                                        free) and solving the free subsystem exactly. A strictly
                                        convex quadratic over a box has one minimiser, so the best
                                        feasible candidate IS the minimiser; for a degenerate one
                                        the first in enumeration order is returned, which is
                                        deterministic. Variables are limited to `MAX_VARIABLES`
                                        because the enumeration is 3^k.
    chi2_sf(x, dof)                     the upper tail of the chi-square distribution, through the
                                        regularised incomplete gamma function (series below a+1,
                                        Lentz continued fraction above) -- the textbook pair, exact
                                        to double precision for the sizes used here.

Determinism matters more than speed: the same inputs give bit-identical outputs on one interpreter,
so a seeded benchmark reproduces exactly.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

#: The enumeration is 3^k active sets; four variables (a composition of two mechanisms against
#: another composition of two) is the largest problem the loop poses.
MAX_VARIABLES = 4

_PIVOT_EPS = 1e-12
_FEASIBILITY_EPS = 1e-9


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when the system is singular."""
    n = len(rhs)
    a = [[*row, rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < _PIVOT_EPS:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            if factor:
                for c in range(col, n + 1):
                    a[r][c] -= factor * a[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (a[r][n] - sum(a[r][c] * x[c] for c in range(r + 1, n))) / a[r][r]
    return x


def box_lsq(
    columns: Sequence[Sequence[float]],
    y: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
) -> tuple[tuple[float, ...], float]:
    """The box-constrained least-squares minimiser and its objective value (see module doc)."""
    k = len(columns)
    if k > MAX_VARIABLES:
        raise ValueError(f"box_lsq handles at most {MAX_VARIABLES} variables, got {k}")
    if not (len(lower) == len(upper) == k):
        raise ValueError("one lower and one upper bound per variable")
    if any(lo > hi for lo, hi in zip(lower, upper, strict=True)):
        raise ValueError("a lower bound exceeds its upper bound")
    n = len(y)
    if any(len(column) != n for column in columns):
        raise ValueError("every column must have one value per observation entry")
    gram = [
        [math.fsum(a * b for a, b in zip(ci, cj, strict=True)) for cj in columns] for ci in columns
    ]
    proj = [math.fsum(a * b for a, b in zip(ci, y, strict=True)) for ci in columns]
    yy = math.fsum(v * v for v in y)
    if k == 0:
        return (), yy

    def objective(x: Sequence[float]) -> float:
        quad = math.fsum(gram[i][j] * x[i] * x[j] for i in range(k) for j in range(k))
        lin = math.fsum(proj[i] * x[i] for i in range(k))
        return max(0.0, quad - 2.0 * lin + yy)

    best: tuple[tuple[float, ...], float] | None = None
    for status in itertools.product((0, 1, 2), repeat=k):  # 0 lower, 1 upper, 2 free
        x = [lower[i] if s == 0 else upper[i] if s == 1 else 0.0 for i, s in enumerate(status)]
        free = [i for i, s in enumerate(status) if s == 2]
        if free:
            sub = [[gram[i][j] for j in free] for i in free]
            rhs = [
                proj[i] - math.fsum(gram[i][j] * x[j] for j in range(k) if j not in free)
                for i in free
            ]
            solved = _solve(sub, rhs)
            if solved is None:
                continue
            if any(
                not (lower[i] - _FEASIBILITY_EPS <= v <= upper[i] + _FEASIBILITY_EPS)
                for i, v in zip(free, solved, strict=True)
            ):
                continue
            for i, v in zip(free, solved, strict=True):
                x[i] = min(upper[i], max(lower[i], v))
        value = objective(x)
        if best is None or value < best[1] - 1e-12:
            best = (tuple(x), value)
    assert best is not None  # the all-bounds active sets are always feasible
    return best


def _gamma_series(a: float, x: float) -> float:
    """Regularised lower incomplete gamma P(a, x) by its series (x < a + 1)."""
    term = 1.0 / a
    total = term
    denominator = a
    for _ in range(10_000):
        denominator += 1.0
        term *= x / denominator
        total += term
        if abs(term) < abs(total) * 1e-15:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_continued_fraction(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) by Lentz's continued fraction (x >= a + 1)."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 10_000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, dof: int) -> float:
    """P(X >= x) for X ~ chi-square(dof). Refuses a non-positive dof."""
    if dof < 1:
        raise ValueError("dof must be at least 1")
    if x <= 0.0:
        return 1.0
    a = dof / 2.0
    half = x / 2.0
    if half < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _gamma_series(a, half)))
    return max(0.0, min(1.0, _gamma_continued_fraction(a, half)))


__all__ = ["MAX_VARIABLES", "box_lsq", "chi2_sf"]
