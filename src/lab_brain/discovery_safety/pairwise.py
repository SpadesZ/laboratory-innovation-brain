"""Distinguishability as a pairwise relation, never closed transitively.

"No available experiment separates A from B" is a statement about the PAIR. It is not transitive:
with one-run predictions 0, 0.75 and 1.5 and a threshold of 1, A~B (0.75 < 1) and B~C (0.75 < 1),
yet A and C are separated by 1.5 >= 1. Merging through the chain would declare A and C inseparable
when an experiment separates them -- and, the other way round, would let a claim of A borrow the
standing of C. Everything the safety layer counts or requests is therefore built from pairs:

    distinct_forward_models   one representative per forward model (a renamed duplicate is the
                              same model and is never counted twice)
    indistinguishable_pairs   every unordered pair no available experiment separates, as pairs
    direct_neighbours         the hypotheses indistinguishable from ONE given hypothesis -- its
                              direct neighbours only, never their neighbours

The frozen engine's `SeparationOracle.classes` takes connected components (the transitive
closure) on purpose, as the conservative reading for the claim it reports; this module does not
use it, and `tests/unit/test_discovery_safety_pairwise.py` shows on the counterexample that the two
readings differ.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.model import Hypothesis


def distinct_forward_models(hypotheses: Iterable[Hypothesis]) -> tuple[Hypothesis, ...]:
    """One hypothesis per forward model, the smallest id of each, sorted by id."""
    chosen: dict[str, Hypothesis] = {}
    for h in hypotheses:
        kept = chosen.get(h.fingerprint)
        if kept is None or h.hypothesis_id < kept.hypothesis_id:
            chosen[h.fingerprint] = h
    return tuple(sorted(chosen.values(), key=lambda h: h.hypothesis_id))


def indistinguishable_pairs(
    hypotheses: Sequence[Hypothesis], oracle: SeparationOracle
) -> tuple[tuple[str, str], ...]:
    """Every unordered pair (sorted ids) the available protocol cannot separate. Pairs only."""
    models = distinct_forward_models(hypotheses)
    out = []
    for i, a in enumerate(models):
        for b in models[i + 1 :]:
            if not oracle.distinguishable(a, b):
                out.append((a.hypothesis_id, b.hypothesis_id))
    return tuple(out)


def direct_neighbours(
    hypothesis: Hypothesis, others: Sequence[Hypothesis], oracle: SeparationOracle
) -> tuple[str, ...]:
    """The hypotheses that no available experiment separates from `hypothesis` itself."""
    return tuple(
        sorted(
            h.hypothesis_id
            for h in distinct_forward_models(others)
            if h.fingerprint != hypothesis.fingerprint and not oracle.distinguishable(hypothesis, h)
        )
    )


__all__ = ["direct_neighbours", "distinct_forward_models", "indistinguishable_pairs"]
