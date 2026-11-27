"""§15.4's Structured Debate metrics, and the gate that may only be armed by calibration (LLM-002).

    §15.4  Structured Debate 是否減少 groupthink 必須可證偽。最低指標：
             - Stage A position pairwise semantic diversity
             - Critic evidence-bundle divergence
             - Critic 改變最終 hypothesis set 的比例
             - surviving-hypothesis diversity
             - additional evidence cost
           門檻由校準產生：hard gates 必須引用版本化的 BenchmarkPolicy。

EVERY METRIC IS DECIMAL, DETERMINISTIC AND NAMED WITH A VERSION. The debate record stores the
values and `METRIC_VERSIONS` beside them, so a calibrated threshold is always compared with a value
computed the same way it was calibrated. Values are quantised to four places: a threshold read off
one run must compare identically against a value from the next, and binary floating point would
make that depend on the platform.

"SEMANTIC" DIVERSITY GOES THROUGH THE EMBEDDING SLOT. §7.3 routes "similarity" work to EMBEDDING,
and the deployment's embedder is what is used -- in this repository the deterministic hashing
embedder EVI-007 already declares, named in the metric version with its EmbeddingSpace. It is a
lexical-semantic proxy and the version string says which one; it does not claim to be a model.

THERE IS NO NUMBER HERE A GATE COULD USE. `DebateGate` finds the active `BenchmarkPolicy` for the
domain's benchmark set and delegates to `core.benchmark_gate.evaluate_gate`; with none active it
reports ADVISORY. `tests/unit/test_benchmark_gate.py` parses this module and fails if a comparison
against a numeric literal appears in it.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

from lab_brain.core.benchmark_gate import GateVerdict, evaluate_gate
from lab_brain.core.repositories.benchmark import BenchmarkStore
from lab_brain.evidence.dense_index import EmbeddingSpace, cosine

POSITION_DIVERSITY = "position_diversity"
CRITIC_BUNDLE_DIVERGENCE = "critic_bundle_divergence"
SURVIVING_DIVERSITY = "surviving_hypothesis_diversity"
CRITIC_CHANGED_FINAL_SET = "critic_changed_final_set"
ADDITIONAL_EVIDENCE_COST = "additional_evidence_cost"

_PLACES = Decimal("0.0001")

Embed = Callable[[str], Sequence[float]]


def _quantise(value: Fraction | float) -> Decimal:
    if isinstance(value, Fraction):
        exact = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        exact = Decimal(repr(value))
    return exact.quantize(_PLACES, rounding=ROUND_HALF_EVEN)


def bundle_divergence(primary: Sequence[str], inverted: Sequence[str]) -> Decimal | None:
    """Critic evidence-bundle divergence: the share of the evidence the Critic ADDED.

    |inverted - primary| / |inverted ∪ primary|. 0 when the Critic's own retrieval found nothing the
    primary retrieval lacked, rising towards 1 as its evidence outweighs what the positions were
    formed from. Not Jaccard distance, deliberately: the inverted retrieval EXCLUDES the primary
    evidence, so a Jaccard distance would be 1 for every non-empty retrieval and would measure only
    whether the Critic found anything at all. `None` when both are empty.
    """
    left, right = frozenset(primary), frozenset(inverted)
    union = left | right
    if not union:
        return None
    return _quantise(Fraction(len(right - left), len(union)))


def mean_pairwise_distance(texts: Sequence[str], embed: Embed) -> Decimal | None:
    """Mean (1 - cosine) over every pair. `None` for fewer than two texts -- not measurable."""
    if len(texts) < 2:
        return None
    vectors = [embed(t) for t in texts]
    distances = [
        min(1.0, max(0.0, 1.0 - cosine(a, b))) for a, b in itertools.combinations(vectors, 2)
    ]
    return _quantise(sum(distances) / len(distances))


def metric_versions(space: EmbeddingSpace) -> dict[str, str]:
    embedding = f"cosine@{space.model}:{space.version}/{space.dimensions}"
    return {
        POSITION_DIVERSITY: f"mean-pairwise-{embedding}",
        SURVIVING_DIVERSITY: f"mean-pairwise-{embedding}",
        CRITIC_BUNDLE_DIVERGENCE: "critic-new-evidence-share@1.0.0",
        ADDITIONAL_EVIDENCE_COST: "whitespace-tokens@1.0.0+attestations-not-in-primary@1.0.0",
    }


class DebateGate:
    """LLM-002's gates for one domain's debates, armed only by an active calibrated policy."""

    def __init__(self, benchmarks: BenchmarkStore, *, domain: str, benchmark_set_id: str) -> None:
        self._benchmarks = benchmarks
        self._domain = domain
        self._benchmark_set_id = benchmark_set_id

    @property
    def benchmark_set_id(self) -> str:
        return self._benchmark_set_id

    def evaluate(self, metric_key: str, value: Decimal | None) -> GateVerdict:
        policy = self._benchmarks.active_for(
            domain=self._domain, benchmark_set_id=self._benchmark_set_id, metric_key=metric_key
        )
        return evaluate_gate(metric_key, value, policy)


__all__ = [
    "ADDITIONAL_EVIDENCE_COST",
    "CRITIC_BUNDLE_DIVERGENCE",
    "CRITIC_CHANGED_FINAL_SET",
    "POSITION_DIVERSITY",
    "SURVIVING_DIVERSITY",
    "DebateGate",
    "Embed",
    "bundle_divergence",
    "mean_pairwise_distance",
    "metric_versions",
]
