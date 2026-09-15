"""Evidence authority as a partial order (ADR-0007, §10.5, §10.5.1).

CORE OWNS THE ABSTRACTION AND NONE OF THE RULES. §10.5 is explicit that "measurement is always
strongest" is **not** a core assumption -- authority is a function of
``(method, calibration, validated_range fit)``, which is domain knowledge. So core declares the
comparator's shape and a DomainPack supplies it (§24.1: nothing here may mention a solver or a
physical quantity).

A PARTIAL ORDER, AND THAT IS THE POINT. §10.5.1:

    Authority is a PARTIAL ORDER, not a total order.
    INCOMPARABLE is a legitimate result and MUST NOT be silently coerced into an ordering.

Two pieces of evidence can genuinely fail to be rankable -- a calibrated measurement outside its
validated range against a simulation inside its own is the standard case. A comparator that
returned WEAKER there would be inventing a ranking, and the belief transition built on it would be
unfalsifiable rather than merely wrong. `TransitionPolicy.evaluate` therefore routes INCOMPARABLE
to NEED_HUMAN_REVIEW instead of guessing (§8.2.1).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lab_brain.core.models.enums import AuthorityComparison


@runtime_checkable
class AuthorityPolicy(Protocol):
    """§10.5.1's comparator. DomainPack **MUST** expose ``compare``.

    Typed as a Protocol because core must not import a DomainPack (§24.2) and must not ship a
    default ranking: a default would become the de facto rule and §10.5 exists to say there is no
    universal one.
    """

    @property
    def policy_version(self) -> str:
        """Versioned, because a belief transition records which comparator authorised it.

        Without this, re-deriving a past decision would compare today's authority rules against
        yesterday's evidence and call the difference a bug in the record.
        """
        ...

    def compare(self, a: str, b: str) -> AuthorityComparison:
        """Rank two ``authority_class`` values, or report that they do not rank."""
        ...

    def meets(self, required_rule: str, candidate: str) -> bool:
        """Whether ``candidate`` satisfies ``required_rule`` (§10.5.1)."""
        ...


__all__ = ["AuthorityPolicy"]
