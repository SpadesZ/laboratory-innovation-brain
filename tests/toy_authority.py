"""A reference DomainPack authority comparator, for EPI-004's contract tests.

IT LIVES IN `tests/` AND THAT IS THE POINT. §10.5 is explicit that "measurement is always
strongest" is **not** a core assumption, and AGT-011 forbids core from importing a domain module.
So the only honest place for a concrete ranking is outside `src/lab_brain/` entirely: core declares
the comparator's shape and the laws an order must satisfy, and something else supplies the rules.
If this file were under `src/`, it would become the de facto default that §10.5 exists to prevent.

The ranking below is deliberately *not* silicon photonics. `TIER_A` / `TIER_B` / `SIDEBAND` carry
no physical meaning, because a fixture named `MEASURED` invites the reading that core knows
measurement outranks simulation — and it must not.

WHAT MAKES IT A USEFUL FIXTURE: it has a genuine INCOMPARABLE pair. `SIDEBAND` does not rank
against either tier, which is the case §10.5.1 exists for and the case EPI-004 has to route to
NEED_HUMAN_REVIEW rather than resolve.
"""

from __future__ import annotations

from typing import ClassVar, Final

from lab_brain.core.models.enums import AuthorityComparison

#: Every class this comparator knows about, including the unrankable one. Sorted and explicit so
#: conformance checks quantify over a declared domain rather than whatever a test happened to use.
TOY_AUTHORITY_CLASSES: Final = ("SIDEBAND", "TIER_A", "TIER_B")


class ToyAuthorityPolicy:
    """A total order over two classes, plus one that does not participate in it.

    Satisfies the §10.5.1 laws core checks: reflexive, converse-symmetric, deterministic, and
    closed over the four results. Verified by `partial_order_violations`, not by assertion.
    """

    policy_id: ClassVar[str] = "auth:toy"
    policy_version: ClassVar[str] = "1.0.0"

    #: `SIDEBAND` is absent on purpose -- absence from the ranking is how INCOMPARABLE arises.
    _rank: ClassVar[dict[str, int]] = {"TIER_B": 1, "TIER_A": 2}

    def compare(self, a: str, b: str) -> AuthorityComparison:
        if a == b:
            # Reflexivity, before the ranking lookup. An unranked class still ranks with itself,
            # and the first version of this fixture got it wrong -- `SIDEBAND` fell through to
            # INCOMPARABLE against itself, which `partial_order_violations` caught immediately.
            # Worth keeping as a comment: the law found a bug in the fixture written to exercise
            # it, which is the only real evidence a law-checker works.
            return AuthorityComparison.EQUIVALENT
        if a not in self._rank or b not in self._rank:
            # Not a fallback and not an error: two things that genuinely do not rank. Returning
            # WEAKER here would invent the ordering a belief transition then rests on.
            return AuthorityComparison.INCOMPARABLE
        if self._rank[a] == self._rank[b]:
            return AuthorityComparison.EQUIVALENT
        return (
            AuthorityComparison.STRONGER
            if self._rank[a] > self._rank[b]
            else AuthorityComparison.WEAKER
        )

    def meets(self, required_rule: str, candidate: str) -> bool:
        """`candidate` satisfies `required_rule` only by ranking at or above it.

        INCOMPARABLE is not "meets" and not "does not meet" -- it is unanswerable, and
        `TransitionPolicy.evaluate` checks for it *before* calling this so the question never
        reaches here in that state. Returning `False` for INCOMPARABLE here would read as a DENY
        and lose the distinction §10.5.1 requires.
        """
        return self.compare(candidate, required_rule) in (
            AuthorityComparison.STRONGER,
            AuthorityComparison.EQUIVALENT,
        )


class ToyAuthorityPolicyV2(ToyAuthorityPolicy):
    """The same comparator with the ranking changed, under a new version.

    Exists so tests can show that a version is not cosmetic: `SIDEBAND` now ranks, so a decision
    computed under `1.0.0` and re-derived under `2.0.0` would reach a different answer. That is
    exactly why `v3.3-a12` stores the comparator's version and why the registry refuses to
    substitute one for another.
    """

    policy_version: ClassVar[str] = "2.0.0"
    _rank: ClassVar[dict[str, int]] = {"TIER_B": 1, "TIER_A": 2, "SIDEBAND": 3}


__all__ = [
    "TOY_AUTHORITY_CLASSES",
    "ToyAuthorityPolicy",
    "ToyAuthorityPolicyV2",
]
