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

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

from lab_brain.core.models.enums import AuthorityComparison


@runtime_checkable
class AuthorityPolicy(Protocol):
    """§10.5.1's comparator. DomainPack **MUST** expose ``compare``.

    Typed as a Protocol because core must not import a DomainPack (§24.2) and must not ship a
    default ranking: a default would become the de facto rule and §10.5 exists to say there is no
    universal one.
    """

    @property
    def policy_id(self) -> str:
        """Identity, because `v3.3-a12` requires the comparator to be *uniquely locatable*.

        A version alone does not identify a comparator: versions are per-policy, so two
        DomainPack comparators both at ``1.0.0`` are indistinguishable in a stored authorization.
        §17.14.1 forbids the cheaper alternative of storing the comparison results instead --
        that would make the authority rules unfalsifiable, which is what §10.5.1 refuses.
        """
        ...

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


class AuthorityResolutionError(RuntimeError):
    """A comparator could not be resolved by identity and version, so nothing may proceed.

    Raised rather than returning ``None`` at the registry boundary. A caller handed ``None`` has
    to remember to check it, and the one place that forgets is the place a belief transition
    proceeds without the authority rules it was supposed to be judged under.
    """


class AuthorityPolicyRegistry:
    """Resolve a DomainPack comparator by ``(policy_id, policy_version)``, or fail closed.

    WHY A REGISTRY AND NOT A DICT. `v3.3-a12` requires a stored `Decision` to name its comparator
    by uniquely locatable identity *and* version, and P9's re-derivation has to get back exactly
    that one. A bare mapping returns ``None`` both for "no such comparator" and for "that version
    is gone", and both then read as "no comparator took part" -- the one reading that must never
    be inferred. So resolution distinguishes them and refuses either way.

    CORE OWNS NO RANKING. Registration is the only way a comparator enters, there is no default,
    and there is no "latest": asking for ``1.0.0`` when only ``2.0.0`` is registered is an error,
    not an upgrade. §8.2.1's determinism guarantee holds within one version and says nothing
    across two, so substituting one would make a re-derivation confirm a decision it never checked.
    """

    def __init__(self) -> None:
        self._by_identity: dict[tuple[str, str], AuthorityPolicy] = {}

    def register(self, policy: AuthorityPolicy) -> AuthorityPolicy:
        """Register a comparator under its own declared identity and version.

        The identity is read off the comparator rather than passed in, so a registry entry cannot
        disagree with the object it holds -- that disagreement is what would let a stored
        `Decision` resolve to something reporting a different version than it has.
        """
        key = (policy.policy_id, policy.policy_version)
        existing = self._by_identity.get(key)
        if existing is not None and existing is not policy:
            raise AuthorityResolutionError(
                f"a different comparator is already registered as {key[0]}@{key[1]}. Authority "
                "rules are versioned precisely so that a change gets a new version; replacing one "
                "in place would make every past decision re-derive against rules it never saw"
            )
        self._by_identity[key] = policy
        return policy

    def resolve(self, policy_id: str, policy_version: str) -> AuthorityPolicy:
        """Return that exact comparator, or raise. Never guesses, never falls back."""
        found = self._by_identity.get((policy_id, policy_version))
        if found is not None:
            return found

        other_versions = sorted(
            version for (registered, version) in self._by_identity if registered == policy_id
        )
        if other_versions:
            raise AuthorityResolutionError(
                f"comparator {policy_id} is registered at {', '.join(other_versions)} but not at "
                f"{policy_version}. There is no nearest version: §8.2.1's determinism guarantee "
                "holds within one version, so re-deriving under another would confirm a decision "
                "nobody ever computed"
            )
        raise AuthorityResolutionError(
            f"no comparator is registered as {policy_id}. Core ships no default authority "
            "ranking -- §10.5 is explicit that there is no universal one -- so there is "
            "nothing to fall back to (AGT-011, §24.1)"
        )

    def get(self, policy_id: str, policy_version: str) -> AuthorityPolicy | None:
        """Mapping-shaped accessor, for callers that legitimately treat absence as a value.

        `verify_stored_revision` is one: it has its own fail-closed branch with its own reason
        code, and raising through it would replace `COMPARATOR_UNRESOLVED` with a different
        exception type for the same condition.
        """
        return self._by_identity.get((policy_id, policy_version))

    def registered(self) -> tuple[tuple[str, str], ...]:
        """Every registered identity, sorted. Deterministic, for diagnostics and conformance."""
        return tuple(sorted(self._by_identity))

    def as_mapping(self) -> Mapping[tuple[str, str], AuthorityPolicy]:
        """A read-only view keyed by ``(policy_id, policy_version)``.

        This is what `verify_stored_revision` takes, and it is a *view* rather than a copy so a
        DomainPack registered after the view was taken is still resolvable -- a copy would make
        wiring order decide whether a stored Decision could be re-derived.

        Read-only because the seam is a consumer: a verifier that could register a comparator
        could satisfy its own check.
        """
        return MappingProxyType(self._by_identity)


#: The four legal results, which the laws below quantify over.
_ORDERINGS: Final = (
    AuthorityComparison.STRONGER,
    AuthorityComparison.WEAKER,
    AuthorityComparison.EQUIVALENT,
    AuthorityComparison.INCOMPARABLE,
)

#: Keyed by `object` on purpose. The values consulted here come from a foreign comparator and
#: are only known to be members after the `_ORDERINGS` check above; typing the key as
#: `AuthorityComparison` would force a cast that asserts what is being verified.
_CONVERSE: Final[Mapping[object, AuthorityComparison]] = MappingProxyType(
    {
        AuthorityComparison.STRONGER: AuthorityComparison.WEAKER,
        AuthorityComparison.WEAKER: AuthorityComparison.STRONGER,
        AuthorityComparison.EQUIVALENT: AuthorityComparison.EQUIVALENT,
        AuthorityComparison.INCOMPARABLE: AuthorityComparison.INCOMPARABLE,
    }
)


def partial_order_violations(policy: AuthorityPolicy, classes: Sequence[str]) -> tuple[str, ...]:
    """Check the laws that make a comparator an order at all, over ``classes``.

    CORE OWNS THE LAWS AND NONE OF THE RULES. §10.5 makes authority domain knowledge, so core
    cannot check *which* class outranks which -- that is a DomainPack's to state and AGT-011
    forbids core from holding an opinion. What core can check is that the comparator is an
    order at all, and none of these laws names a class or a physical quantity:

    - **reflexive** -- ``compare(a, a)`` is EQUIVALENT. A class that does not rank against itself
      makes every authority threshold unanswerable.
    - **converse** -- ``compare(b, a)`` is the converse of ``compare(a, b)``. A comparator saying
      `a` is STRONGER than `b` *and* `b` STRONGER than `a` has no ordering to speak of, and
      whichever call happened to be made first would decide a belief.
    - **deterministic** -- repeated calls on one pair agree. §8.2.1's guarantee that a stored
      Decision re-derives is only ever as good as the comparator's.
    - **closed over the four results** -- every call returns an `AuthorityComparison`. A ``None``
      or a bare string gets coerced by the caller into whichever branch it falls through to,
      which is the silent coercion §10.5.1 forbids.

    Returns descriptions rather than raising, so a conformance test reports every violation at
    once instead of the first.

    NOT CHECKED: transitivity. It needs every triple, and a partial order may legitimately contain
    INCOMPARABLE pairs that break naive chains -- asserting it would forbid exactly the partial
    orders §10.5.1 exists to permit.
    """
    violations: list[str] = []
    ordered = sorted(set(classes))

    for a in ordered:
        reflexive = policy.compare(a, a)
        if reflexive is not AuthorityComparison.EQUIVALENT:
            violations.append(
                f"compare({a!r}, {a!r}) is {reflexive} and must be EQUIVALENT: a class that does "
                "not rank against itself makes every authority threshold unanswerable"
            )

    for a in ordered:
        for b in ordered:
            # Deliberately typed as `object`. `AuthorityPolicy` is a structural Protocol
            # implemented by code core does not own, so the annotation on `compare` is a request,
            # not a guarantee -- and mypy reports the check below as unreachable if this is
            # narrowed, which would be true of a conforming comparator and is exactly the
            # assumption this function exists to stop making.
            forward: object = policy.compare(a, b)
            if forward not in _ORDERINGS:
                violations.append(
                    f"compare({a!r}, {b!r}) returned {forward!r}, which is not an "
                    "AuthorityComparison; the caller would coerce it into whichever branch it "
                    "fell through to"
                )
                continue
            if policy.compare(a, b) is not forward:
                violations.append(
                    f"compare({a!r}, {b!r}) is not deterministic; §8.2.1's guarantee that a "
                    "stored Decision re-derives is only as good as this comparator's"
                )
            backward: object = policy.compare(b, a)
            expected = _CONVERSE[forward]
            if backward is not expected:
                violations.append(
                    f"compare({a!r}, {b!r}) is {forward} but compare({b!r}, {a!r}) is "
                    f"{backward}, not {expected}; without the converse law whichever call is "
                    "made first would decide the belief"
                )

    return tuple(violations)


__all__ = [
    "AuthorityPolicy",
    "AuthorityPolicyRegistry",
    "AuthorityResolutionError",
    "partial_order_violations",
]
