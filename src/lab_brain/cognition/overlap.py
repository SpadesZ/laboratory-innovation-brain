"""Which admitted rivals overlap: the same testable claims under different names.

THE FINDING IT ANSWERS. In a real run, a Critic's second round added three alternatives whose
mechanism names differed from the existing ones -- so §8's distinctness check (`mechanism_key`:
whitespace and case only) admitted them -- while their text largely restated what was already in
the set. Each one adds review work later and no new way to be wrong.

WHAT IS COMPUTED, AND WHAT IS NOT DONE WITH IT. Two certificates OVERLAP when they make exactly the
same discriminating predictions -- the same (observable, outcome, SUPPORTS/CONTRADICTS) set -- so no
check this domain declares could ever tell them apart. Their mechanism words are compared too
(Jaccard over `roles.content_terms`) and reported beside it. Nothing is merged, dropped or refused
here: "contact discontinuity" and "probe contact resistance" can share every prediction a pack
declares and still be different physics, and deciding that two mechanisms are one is a scientific
judgment this module must not make. The pairs are recorded on the debate and shown to a reader.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from lab_brain.cognition.roles import DISCRIMINATING_EFFECTS, content_terms
from lab_brain.core.models.hypothesis_set import HypothesisCertificate


def signature(certificate: HypothesisCertificate) -> frozenset[tuple[str, str, str]]:
    """The certificate's discriminating claims: (observable, expected outcome, effect)."""
    return frozenset(
        (p.observable_ref, p.expected_outcome, t.relation_type.value)
        for p in certificate.predictions
        for t in p.relation_effect_if_observed
        if t.relation_type in DISCRIMINATING_EFFECTS
    )


def term_overlap(a: HypothesisCertificate, b: HypothesisCertificate) -> Decimal:
    """Jaccard similarity of the two mechanisms' and statements' content words, to 2 places."""
    x = content_terms(f"{a.hypothesis.mechanism} {a.hypothesis.statement}")
    y = content_terms(f"{b.hypothesis.mechanism} {b.hypothesis.statement}")
    if not x and not y:
        return Decimal(0)
    return (Decimal(len(x & y)) / Decimal(len(x | y))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )


def overlapping_pairs(certificates: Sequence[HypothesisCertificate]) -> list[dict[str, object]]:
    """Every pair with an identical, non-empty discriminating signature, in id order."""
    ordered = sorted(certificates, key=lambda c: c.hypothesis_id)
    pairs: list[dict[str, object]] = []
    for i, a in enumerate(ordered):
        claims = signature(a)
        if not claims:
            continue
        for b in ordered[i + 1 :]:
            if signature(b) != claims:
                continue
            pairs.append(
                {
                    "hypotheses": [a.hypothesis_id, b.hypothesis_id],
                    "mechanisms": [a.hypothesis.mechanism, b.hypothesis.mechanism],
                    "shared_claims": sorted("|".join(c) for c in claims),
                    "term_overlap": str(term_overlap(a, b)),
                }
            )
    return pairs


__all__ = ["overlapping_pairs", "signature", "term_overlap"]
