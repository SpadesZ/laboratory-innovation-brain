"""Proportions with honest uncertainty: a Wilson score interval and a seeded percentile bootstrap.

Both are deterministic. The Wilson interval is closed form; the bootstrap draws from
`random.Random(f"{seed}:{label}")`, whose string seeding is specified (SHA-512 of the string) and
therefore reproduces across processes and platforms for a given CPython major version -- the seed
and the resample count are frozen in the protocol manifest and printed in every report, so anyone
can rerun the same draw. Neither is a claim about a population the cases were not sampled from: an
interval over a handful of authored cases describes those cases' sampling noise and nothing more.

    wilson(k, n)         95% Wilson score interval; None when n == 0 (no evidence, no interval)
    bootstrap(v, ...)    percentile interval over `resamples` resamples of the per-case 0/1
                         values, with replacement, at the nearest-rank quantiles; None when empty

Values are rounded to 4 decimals so a report diff is a diff of substance, not of float noise.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

#: The two-sided 95% normal quantile, written out rather than computed so the scorer source hash
#: pins the exact constant every report used.
Z_95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """The Wilson score interval for k successes in n trials. Refuses k outside 0..n."""
    if not 0 <= k <= n:
        raise ValueError(f"k={k} is not within 0..n={n}")
    if n == 0:
        return None
    p = k / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def bootstrap(
    values: Sequence[bool],
    *,
    seed: int,
    resamples: int,
    label: str,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """A seeded percentile bootstrap of the mean of 0/1 per-case values.

    `label` (the metric name) is part of the RNG seed, so each metric gets its own reproducible
    stream and adding a metric never shifts another metric's interval.
    """
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not values:
        return None
    rng = random.Random(f"{seed}:{label}")
    n = len(values)
    ones = [1 if v else 0 for v in values]
    means = sorted(sum(ones[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    tail = (1 - confidence) / 2
    low = means[max(0, math.ceil(tail * resamples) - 1)]
    high = means[min(resamples - 1, math.ceil((1 - tail) * resamples) - 1)]
    return round(low, 4), round(high, 4)
