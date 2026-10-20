"""Independent-attestation counting — EVI-004, §6.17.

    DEPENDENCE_UNKNOWN 對 independent-attestation count 的貢獻固定為 0。
    它保留為 supporting context，但不足以滿足 min_independent_attestations。
    若因此無法達到門檻，TransitionPolicy MUST 回傳 NEED_MORE_EVIDENCE 或 NEED_HUMAN_REVIEW，
    不得猜測為獨立。

Three rules, and the third is the one that makes the first two mean something:

  1. attestations of the same work count once, however many manifestations exist;
  2. an unknown relation contributes **zero**, not one and not a fraction;
  3. when the count falls short *because* of rule 2, the caller must be told which -- a shortfall
     caused by genuinely absent evidence and one caused by unresolved dependence lead to
     different outcomes (NEED_MORE_EVIDENCE vs NEED_HUMAN_REVIEW), and collapsing them loses the
     escalation signal.

Rule 2 is counter-intuitive and deliberate. The intuition is that an unknown relation is probably
independent -- most papers are unrelated -- so counting it as 1 is "usually right". But the cost
is asymmetric: counting an unknown as independent inflates corroboration exactly when the sources
*are* related, which is the case that matters, and the error is invisible because every
attestation is individually real.

WHAT THIS MODULE DOES NOT DECIDE. Whether the threshold is met is a ``TransitionPolicy``
question; this returns a count and the reason it is what it is. Duplicating the policy's
comparison here would give two places that decide whether a belief may move.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lab_brain.core.models.enums import IndependenceBasis, IndependenceRelation

#: Relations that make two attestations count as one. ``CITES`` and ``DERIVED_FROM`` are here for
#: the reason §6.2 gives: a paper citing a measurement is not a second measurement.
DEPENDENT_RELATIONS = frozenset(
    {
        IndependenceRelation.SAME_WORK,
        IndependenceRelation.CITES,
        IndependenceRelation.DERIVED_FROM,
    }
)


@dataclass(frozen=True)
class IndependenceCount:
    """A corroboration count with its reasoning attached."""

    independent: int
    #: Attestations excluded because their relation is UNKNOWN. §6.17 fixes their contribution
    #: at 0; they are counted here so the shortfall's *cause* is reportable.
    unknown: int
    #: Attestations folded into an earlier one as the same work or a citation of it.
    dependent: int
    basis: IndependenceBasis

    @property
    def total_considered(self) -> int:
        return self.independent + self.unknown + self.dependent

    @property
    def shortfall_is_resolvable(self) -> bool:
        """True when resolving the unknowns could change the answer.

        This is what distinguishes NEED_HUMAN_REVIEW from NEED_MORE_EVIDENCE: if unknowns exist,
        somebody can resolve them and the count may rise. If there are none, the only remedy is
        more evidence.
        """
        return self.unknown > 0


def count_independent_attestations(
    attestation_ids: Sequence[str],
    *,
    source_work_of: Mapping[str, str | None],
    relations: Mapping[tuple[str, str], IndependenceRelation],
    basis: IndependenceBasis = IndependenceBasis.WORK,
) -> IndependenceCount:
    """Count how many of ``attestation_ids`` are mutually independent supports.

    ``relations`` is keyed on unordered pairs; both orderings are consulted so the caller does not
    have to record each pair twice.

    An attestation with **no recorded source work** is treated as UNKNOWN rather than
    independent. That is the same asymmetry as rule 2: "we did not resolve where this came from"
    is not evidence that it came from somewhere new.
    """
    if basis not in {IndependenceBasis.WORK}:
        # §6.17: v3.3 implements WORK-level independence only. A policy declaring a stronger
        # basis MUST escalate rather than pretend the requirement is met, so this refuses to
        # produce a number that would be read as one.
        raise ValueError(
            f"independence basis {basis} is not implemented in v3.3 (§6.17 models WORK only); "
            "a policy declaring it MUST return NEED_HUMAN_REVIEW rather than receive a count"
        )

    seen_works: set[str] = set()
    independent = 0
    unknown = 0
    dependent = 0
    accepted: list[str] = []

    for attestation_id in attestation_ids:
        work = source_work_of.get(attestation_id)
        if work is None:
            unknown += 1
            continue

        if work in seen_works:
            dependent += 1
            continue

        related_to_accepted = False
        has_unknown_relation = False
        for earlier in accepted:
            relation = relations.get((attestation_id, earlier)) or relations.get(
                (earlier, attestation_id)
            )
            if relation in DEPENDENT_RELATIONS:
                related_to_accepted = True
                break
            if relation is IndependenceRelation.UNKNOWN:
                has_unknown_relation = True

        if related_to_accepted:
            dependent += 1
            continue
        if has_unknown_relation:
            # Contributes 0, and is reported as unknown rather than dependent -- the distinction
            # is what `shortfall_is_resolvable` reads.
            unknown += 1
            continue

        independent += 1
        seen_works.add(work)
        accepted.append(attestation_id)

    return IndependenceCount(
        independent=independent, unknown=unknown, dependent=dependent, basis=basis
    )


__all__ = [
    "DEPENDENT_RELATIONS",
    "IndependenceCount",
    "count_independent_attestations",
]
