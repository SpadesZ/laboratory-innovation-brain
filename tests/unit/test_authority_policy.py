"""EPI-004: the AuthorityPolicy comparator, its laws, and INCOMPARABLE as a first-class result.

    §10.5.1  Authority is a PARTIAL ORDER, not a total order.
             INCOMPARABLE is a legitimate result and MUST NOT be silently coerced into an
             ordering.

    §25.3    DomainPack MUST expose AuthorityPolicy.compare returning
             STRONGER/WEAKER/EQUIVALENT/INCOMPARABLE. INCOMPARABLE at a required transition gate
             MUST yield NEED_HUMAN_REVIEW + ReviewItem(AUTHORITY_CONFLICT); no silent
             promotion/rejection.

THE DIVISION OF LABOUR THIS MODULE IS TESTING. Core owns the comparator's *shape* and the laws
that make it an order; a DomainPack owns the ranking. So there are two kinds of test below and
they must not be confused:

- laws (`partial_order_violations`) — reflexive, converse, deterministic, closed over the four
  results. None of them mentions a physical quantity, which is how core can check them at all.
- consequences (`TransitionPolicy.evaluate`) — INCOMPARABLE reaches NEED_HUMAN_REVIEW and blocks
  promotion *and* rejection, and is never resolved into an ordering.

The fixture comparator lives in `tests/toy_authority.py` rather than under `src/`: a concrete
ranking shipped in core would become the default §10.5 exists to forbid (AGT-011).
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from lab_brain.core.authority import (
    AuthorityConformanceError,
    AuthorityPolicyRegistry,
    AuthorityResolutionError,
    partial_order_violations,
)
from lab_brain.core.models import BeliefState, TransitionOutcome, TransitionReason
from lab_brain.core.models.enums import AuthorityComparison
from tests.contract.test_transition_policy import hypothesis, policy, relation, summary
from tests.toy_authority import (
    TOY_AUTHORITY_CLASSES,
    ToyAuthorityPolicy,
    ToyAuthorityPolicyV2,
)

pytestmark = [pytest.mark.requirement("EPI-004"), pytest.mark.spec_test("T-EPI-004")]


def run(comparator=None, **overrides):  # type: ignore[no-untyped-def]
    """Evaluate a transition whose policy requires `TIER_A` authority."""
    pol = overrides.pop("pol", None) or policy(required_authority_rule="TIER_A")
    hyp = overrides.pop("hyp", None) or hypothesis(admitted_authority_classes=("TIER_A",))
    return pol.evaluate(
        hyp,
        (relation(),),
        comparator,
        (),
        summary(),
        overrides.pop("candidate_to_state", pol.candidate_to_state),
    )


# --------------------------------------------------------------------------------------------
# The four results. T-EPI-004: "authority fixtures cover stronger/weaker/equivalent/incomparable".
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("TIER_A", "TIER_B", AuthorityComparison.STRONGER),
        ("TIER_B", "TIER_A", AuthorityComparison.WEAKER),
        ("TIER_A", "TIER_A", AuthorityComparison.EQUIVALENT),
        ("TIER_B", "TIER_B", AuthorityComparison.EQUIVALENT),
        ("SIDEBAND", "TIER_A", AuthorityComparison.INCOMPARABLE),
        ("TIER_A", "SIDEBAND", AuthorityComparison.INCOMPARABLE),
        ("SIDEBAND", "SIDEBAND", AuthorityComparison.EQUIVALENT),
    ],
)
def test_the_comparator_covers_all_four_results(a, b, expected):
    """All four, including both directions of the incomparable pair.

    `SIDEBAND` against itself is EQUIVALENT rather than INCOMPARABLE: a class always ranks with
    itself, or no threshold involving it could ever be answered.
    """
    assert ToyAuthorityPolicy().compare(a, b) is expected


def test_the_comparator_satisfies_the_partial_order_laws():
    """Checked by core, over the DomainPack's own declared class set.

    Core checks the laws and none of the rules, which is the only division §10.5 permits: it
    cannot know whether `TIER_A` outranks `TIER_B`, but it can know that a comparator claiming
    both directions at once is not an order.
    """
    assert partial_order_violations(ToyAuthorityPolicy(), TOY_AUTHORITY_CLASSES) == ()


def test_the_laws_catch_a_comparator_that_is_not_an_order():
    """The law-checker has to be able to fail, or it is decoration.

    Each of these is a real way a hand-written comparator goes wrong, and none of them is
    detectable by reading the return type.
    """

    class AlwaysStronger:
        policy_id = "auth:broken"
        policy_version = "1.0.0"

        def compare(self, a: str, b: str) -> AuthorityComparison:
            return AuthorityComparison.STRONGER

        def meets(self, required_rule: str, candidate: str) -> bool:
            return True

    violations = partial_order_violations(AlwaysStronger(), ("X", "Y"))
    assert violations, "a comparator that always says STRONGER is not an order"
    assert any("EQUIVALENT" in v for v in violations), "reflexivity is violated"
    assert any("converse" in v or "not WEAKER" in v for v in violations)


def test_the_laws_catch_a_non_deterministic_comparator():
    """§8.2.1's guarantee that a stored Decision re-derives is only as good as the comparator's."""

    class Flipping:
        policy_id = "auth:flipping"
        policy_version = "1.0.0"

        def __init__(self) -> None:
            self._calls = 0

        def compare(self, a: str, b: str) -> AuthorityComparison:
            if a == b:
                return AuthorityComparison.EQUIVALENT
            self._calls += 1
            return (
                AuthorityComparison.STRONGER
                if self._calls % 2
                else AuthorityComparison.INCOMPARABLE
            )

        def meets(self, required_rule: str, candidate: str) -> bool:
            return True

    violations = partial_order_violations(Flipping(), ("X", "Y"))
    assert any("deterministic" in v for v in violations)


def test_the_laws_catch_a_comparator_returning_something_else_entirely():
    """A `None` or a bare string is coerced by the caller into whichever branch it falls through
    to, which is precisely the silent coercion §10.5.1 forbids."""

    class NotAnEnum:
        policy_id = "auth:stringly"
        policy_version = "1.0.0"

        def compare(self, a: str, b: str):  # type: ignore[no-untyped-def]
            return "EQUIVALENT" if a == b else None

        def meets(self, required_rule: str, candidate: str) -> bool:
            return True

    violations = partial_order_violations(NotAnEnum(), ("X", "Y"))
    assert any("not an AuthorityComparison" in v for v in violations)


def test_identical_inputs_and_version_give_identical_comparisons():
    """Determinism across instances, not just within one.

    Two instances of the same version must agree, because a stored Decision names a version and a
    re-derivation resolves a fresh object from the registry -- not the instance that computed it.
    """
    first, second = ToyAuthorityPolicy(), ToyAuthorityPolicy()
    for a in TOY_AUTHORITY_CLASSES:
        for b in TOY_AUTHORITY_CLASSES:
            assert first.compare(a, b) is second.compare(a, b)


def test_a_new_version_may_rank_differently_and_that_is_why_versions_exist():
    """`SIDEBAND` is unrankable at 1.0.0 and ranked at 2.0.0.

    Pinned because it is the whole justification for storing the comparator's version in a
    Decision: the same inputs reach different answers, so substituting a version would confirm a
    decision nobody computed.
    """
    assert ToyAuthorityPolicy().compare("SIDEBAND", "TIER_A") is AuthorityComparison.INCOMPARABLE
    assert ToyAuthorityPolicyV2().compare("SIDEBAND", "TIER_A") is AuthorityComparison.STRONGER
    assert ToyAuthorityPolicy().policy_version != ToyAuthorityPolicyV2().policy_version


def test_core_ships_no_authority_ranking():
    """AGT-011 / §24.1, asserted rather than trusted.

    The comparator fixture lives in `tests/`. If a concrete ranking ever appears under `src/`, it
    becomes the de facto universal rule §10.5 exists to deny, and it will get imported by
    something that does not realise it is a placeholder.

    Scoped to authority **class names**, not to prose. The first version of this test also banned
    the phrase "measurement is always" and failed on `core/authority.py`'s own module docstring,
    which quotes §10.5 saying that measurement-is-always-strongest is *not* a core assumption.
    Banning a quotation of the prohibition would have deleted the clearest statement of the rule
    in order to satisfy a guard about breaking it. A class name is a ranking; a sentence saying
    there is no universal ranking is documentation.
    """
    import inspect

    import lab_brain.core.authority as core_authority

    source = inspect.getsource(core_authority)
    for class_name in ("MEASURED", "SIMULATED", "REPORTED", "TIER_A", "TIER_B"):
        assert class_name not in source, (
            f"core/authority.py names the authority class {class_name!r}; core owns the "
            "abstraction and none of the rules"
        )


# --------------------------------------------------------------------------------------------
# The consequence. INCOMPARABLE at a required gate must escalate, never resolve.
# --------------------------------------------------------------------------------------------


def test_incomparable_at_a_required_gate_yields_need_human_review():
    """The pass condition of T-EPI-004."""
    decision = run(
        ToyAuthorityPolicy(),
        hyp=hypothesis(admitted_authority_classes=("SIDEBAND",)),
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE


def test_incomparable_produces_a_review_item_spec_for_an_authority_conflict():
    """§8.2.1's `review_item_spec`, carrying `AUTHORITY_CONFLICT`.

    This is the **typed pending interface**, not a created ReviewItem. Persisting one needs the
    `Conflict` / ReviewItem storage that is `EPI-006` and UX-005, so EPI-004 stays IN_PROGRESS
    rather than claiming a pass condition it only half meets. The spec is what makes the handoff
    typed instead of a TODO comment.
    """
    decision = run(
        ToyAuthorityPolicy(),
        hyp=hypothesis(admitted_authority_classes=("SIDEBAND",), stakes="HIGH"),
    )
    spec = decision.review_item_spec
    assert spec is not None
    assert spec.subject_type == "AUTHORITY_CONFLICT"
    assert spec.subject_id == hypothesis().hypothesis_id
    assert spec.stakes == "HIGH"
    assert spec.reason is TransitionReason.AUTHORITY_INCOMPARABLE


@pytest.mark.parametrize(
    "candidate_to_state",
    [BeliefState.SUPPORTED, BeliefState.CONTRADICTED],
)
def test_incomparable_blocks_rejection_as_well_as_promotion(candidate_to_state):
    """ "No silent promotion/rejection" is two obligations and only one is obvious.

    A CONTRADICTED transition is as much a belief change as a SUPPORTED one; a gate that escalated
    promotions and let rejections through would satisfy the sentence as usually read and violate
    what it says.
    """
    decision = run(
        ToyAuthorityPolicy(),
        pol=policy(
            required_authority_rule="TIER_A",
            candidate_to_state=candidate_to_state,
        ),
        hyp=hypothesis(admitted_authority_classes=("SIDEBAND",)),
        candidate_to_state=candidate_to_state,
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert not decision.permits_transition


def test_incomparable_is_never_resolved_into_an_ordering():
    """The comparator is asked, and its INCOMPARABLE is carried through rather than reinterpreted.

    Asserted on the *outcome* rather than by inspecting calls: a gate that translated
    INCOMPARABLE into "does not meet" would produce DENY, which looks like a decision and is
    actually a guess.
    """
    decision = run(
        ToyAuthorityPolicy(),
        hyp=hypothesis(admitted_authority_classes=("SIDEBAND",)),
    )
    assert decision.outcome is not TransitionOutcome.DENY
    assert decision.outcome is not TransitionOutcome.ALLOW


def test_a_satisfied_authority_rule_still_allows():
    """The gate must be passable, or no belief could ever be promoted on authority grounds."""
    decision = run(ToyAuthorityPolicy())
    assert decision.outcome is TransitionOutcome.ALLOW


def test_insufficient_but_comparable_authority_denies_rather_than_escalating():
    """A rankable shortfall is a decision, not a question for a human.

    The distinction is the point of the partial order: `TIER_B` is genuinely weaker than `TIER_A`,
    so the policy can answer. `SIDEBAND` is not weaker, so it cannot.
    """
    decision = run(
        ToyAuthorityPolicy(),
        hyp=hypothesis(admitted_authority_classes=("TIER_B",)),
    )
    assert decision.outcome is TransitionOutcome.DENY
    assert decision.reason_code is TransitionReason.AUTHORITY_INSUFFICIENT


# --------------------------------------------------------------------------------------------
# Resolution. A comparator that cannot be located by identity and version fails closed.
# --------------------------------------------------------------------------------------------


def test_a_missing_comparator_at_a_required_gate_escalates_rather_than_passing():
    """No comparator is not "no authority requirement"."""
    decision = run(None)
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE


def test_a_required_rule_with_no_admitted_classes_escalates():
    """A rule with nothing to test against cannot be satisfied and must not be treated as met."""
    decision = run(ToyAuthorityPolicy(), hyp=hypothesis(admitted_authority_classes=()))
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW


def test_the_registry_resolves_a_comparator_by_identity_and_version():
    registry = AuthorityPolicyRegistry()
    registered = registry.register(ToyAuthorityPolicy())

    assert registry.resolve("auth:toy", "1.0.0") is registered
    assert registry.registered() == (("auth:toy", "1.0.0"),)


def test_the_registry_refuses_an_unregistered_comparator():
    """Core ships no default, so there is nothing to fall back to."""
    registry = AuthorityPolicyRegistry()
    with pytest.raises(AuthorityResolutionError, match="no comparator is registered"):
        registry.resolve("auth:nobody", "1.0.0")


def test_the_registry_refuses_a_different_version_and_does_not_substitute():
    """The failure mode that would be quietest: resolving 1.0.0 to the 2.0.0 that is present.

    `ToyAuthorityPolicyV2` really does rank `SIDEBAND` differently, so the substitution would not
    merely be untidy -- it would re-derive a decision to a different answer and report agreement.
    """
    registry = AuthorityPolicyRegistry()
    registry.register(ToyAuthorityPolicyV2())

    with pytest.raises(AuthorityResolutionError, match=r"registered at 2\.0\.0 but not at 1\.0\.0"):
        registry.resolve("auth:toy", "1.0.0")


def test_the_registry_refuses_to_replace_a_comparator_in_place():
    """Versioning is only a guarantee if a version cannot be redefined."""

    class Impostor(ToyAuthorityPolicy):
        pass

    registry = AuthorityPolicyRegistry()
    registry.register(ToyAuthorityPolicy())

    with pytest.raises(AuthorityResolutionError, match="already registered"):
        registry.register(Impostor())


def test_registering_the_same_comparator_twice_is_harmless():
    """Idempotent registration, so wiring a DomainPack twice is not an error."""
    registry = AuthorityPolicyRegistry()
    comparator = ToyAuthorityPolicy()
    registry.register(comparator)
    registry.register(comparator)
    assert registry.registered() == (("auth:toy", "1.0.0"),)


def test_the_registry_view_is_what_the_p9_verifier_consumes():
    """EPI-004's resolution feeding `v3.3-a12`'s re-derivation, keyed exactly as the seam expects.

    The stored `Decision` records `(authority_policy_id, authority_policy_version)`, and
    `verify_stored_revision` looks the comparator up by that pair. If these two ever disagreed
    about the key, every authorization computed with a comparator would become unverifiable --
    and it would fail as `COMPARATOR_UNRESOLVED`, which reads like a missing DomainPack rather
    than a wiring bug.
    """
    registry = AuthorityPolicyRegistry()
    comparator = registry.register(ToyAuthorityPolicy())
    view = registry.as_mapping()

    assert view[("auth:toy", "1.0.0")] is comparator
    assert view.get(("auth:toy", "9.9.9")) is None


def test_the_registry_view_is_read_only():
    """A verifier that could register a comparator could satisfy its own check."""
    registry = AuthorityPolicyRegistry()
    view = registry.as_mapping()

    with pytest.raises(TypeError):
        view[("auth:anything", "1.0.0")] = ToyAuthorityPolicy()  # type: ignore[index]


def test_the_registry_view_reflects_later_registrations():
    """A view, not a copy: wiring order must not decide whether a Decision can be re-derived."""
    registry = AuthorityPolicyRegistry()
    view = registry.as_mapping()
    registry.register(ToyAuthorityPolicy())

    assert ("auth:toy", "1.0.0") in view


# --------------------------------------------------------------------------------------------
# Transitivity. The P10 audit's finding: the earlier version declined this check and said so.
# --------------------------------------------------------------------------------------------


class Pairwise:
    """Declare the STRONGER/EQUIVALENT pairs; everything else is INCOMPARABLE.

    The converse is derived rather than declared, so these fixtures cannot fail the converse law
    by accident -- each one fails exactly the law it is written to fail.
    """

    policy_id = "auth:probe"
    policy_version = "1.0.0"
    authority_classes: ClassVar[tuple[str, ...]] = ("A", "B", "C")
    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {}

    def compare(self, a: str, b: str) -> AuthorityComparison:
        if a == b:
            return AuthorityComparison.EQUIVALENT
        if (a, b) in self.pairs:
            return self.pairs[(a, b)]
        if (b, a) in self.pairs:
            forward = self.pairs[(b, a)]
            return (
                AuthorityComparison.WEAKER if forward is AuthorityComparison.STRONGER else forward
            )
        return AuthorityComparison.INCOMPARABLE

    def meets(self, required_rule: str, candidate: str) -> bool:
        return self.compare(candidate, required_rule) in (
            AuthorityComparison.STRONGER,
            AuthorityComparison.EQUIVALENT,
        )


class Cyclic(Pairwise):
    """`A>B, B>C, C>A`. Passed the old checker and is not an order under any reading."""

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.STRONGER,
        ("B", "C"): AuthorityComparison.STRONGER,
        ("C", "A"): AuthorityComparison.STRONGER,
    }


class BrokenChain(Pairwise):
    """`A>B, B>C`, and `A` INCOMPARABLE to `C`. The chain exists and does not compose."""

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.STRONGER,
        ("B", "C"): AuthorityComparison.STRONGER,
    }


class InconsistentEquivalence(Pairwise):
    """`A~B, B~C`, and `A` INCOMPARABLE to `C`. Equivalence used as close-enough."""

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.EQUIVALENT,
        ("B", "C"): AuthorityComparison.EQUIVALENT,
    }


class MixedChainNotStrict(Pairwise):
    """`A>B, B~C`, and `A~C`. Dominating via a STRONGER step must stay strict."""

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.STRONGER,
        ("B", "C"): AuthorityComparison.EQUIVALENT,
        ("A", "C"): AuthorityComparison.EQUIVALENT,
    }


class GenuinePartialOrder(Pairwise):
    """`A>B`, and `C` unrankable against both. Must remain legal.

    The control case. Without it, a transitivity check that simply demanded every pair rank would
    pass every test above while forbidding the partial orders §10.5.1 exists to permit.
    """

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.STRONGER,
    }


@pytest.mark.parametrize(
    ("broken", "expected_in_message"),
    [
        (Cyclic, "must be STRONGER -- it is WEAKER"),
        (BrokenChain, "must be STRONGER -- it is INCOMPARABLE"),
        (InconsistentEquivalence, "must be EQUIVALENT -- it is INCOMPARABLE"),
        (MixedChainNotStrict, "must be STRONGER -- it is EQUIVALENT"),
    ],
)
def test_the_laws_catch_a_comparator_whose_chains_do_not_compose(broken, expected_in_message):
    """Each of these passed the previous checker, which declined transitivity entirely.

    The old docstring argued that INCOMPARABLE pairs break naive chains. That is true and it was
    beside the point: the fix is to require transitivity *conditionally*. The audit was right that
    the argument was a rationalisation for not doing the harder thing.
    """
    violations = partial_order_violations(broken(), broken.authority_classes)
    assert violations, f"{broken.__name__} is not an order and must be refused"
    assert any("transitivity" in v for v in violations)
    assert any(expected_in_message in v for v in violations), violations


def test_an_incomparable_pair_generates_no_chain_requirement():
    """The control. A genuine partial order must stay legal.

    This is the test that keeps the transitivity check honest: without it, demanding that every
    pair rank would satisfy every case above while forbidding exactly what §10.5.1 permits.
    """
    assert partial_order_violations(GenuinePartialOrder(), ("A", "B", "C")) == ()


def test_the_declared_toy_comparators_are_transitive():
    """`SIDEBAND` is INCOMPARABLE to both tiers, so it forms no chains -- which is allowed."""
    assert partial_order_violations(ToyAuthorityPolicy(), TOY_AUTHORITY_CLASSES) == ()
    assert partial_order_violations(ToyAuthorityPolicyV2(), TOY_AUTHORITY_CLASSES) == ()


# --------------------------------------------------------------------------------------------
# `meets` must agree with `compare`. A divergence is a silent promotion, not an untidiness.
# --------------------------------------------------------------------------------------------


class MeetsAlwaysTrue(Pairwise):
    """`compare(B, A) = WEAKER` but `meets(A, B) = True`.

    §10.5.1 declares `meets` as well as `compare`, so it is not this project's to delete -- the
    maintainer ruling is to keep it and add the law. This fixture is why the law matters:
    `evaluate` checks INCOMPARABLE with `compare` and then asks `meets` for the threshold, so a
    divergence produces an ALLOW on insufficient authority.
    """

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.STRONGER,
    }

    def meets(self, required_rule: str, candidate: str) -> bool:
        return True


class MeetsRefusesEquivalent(Pairwise):
    """The other direction: `compare` says EQUIVALENT and `meets` says no.

    Under-permissive rather than over-permissive, and still a divergence: it would DENY a
    transition the authority rules allow, and a DENY reads as a decision rather than a bug.
    """

    pairs: ClassVar[dict[tuple[str, str], AuthorityComparison]] = {
        ("A", "B"): AuthorityComparison.EQUIVALENT,
    }

    def meets(self, required_rule: str, candidate: str) -> bool:
        return self.compare(candidate, required_rule) is AuthorityComparison.STRONGER


@pytest.mark.parametrize("diverging", [MeetsAlwaysTrue, MeetsRefusesEquivalent])
def test_the_laws_catch_meets_diverging_from_compare(diverging):
    violations = partial_order_violations(diverging(), ("A", "B"))
    assert any("meets(" in v for v in violations), violations


def test_a_meets_divergence_cannot_reach_an_allow():
    """The consequence, not only the law.

    A comparator whose `meets` over-permits must not be registerable, so it cannot be resolved for
    a stored Decision and cannot reach `evaluate`. Asserted on the registry rather than by calling
    `evaluate` with it: the point is that the divergence is stopped before it decides anything.
    """
    registry = AuthorityPolicyRegistry()
    with pytest.raises(AuthorityConformanceError, match="meets"):
        registry.register(MeetsAlwaysTrue())
    assert registry.registered() == ()


# --------------------------------------------------------------------------------------------
# Registration enforces conformance, rather than a suite a DomainPack may choose to run.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "broken",
    [Cyclic, BrokenChain, InconsistentEquivalence, MixedChainNotStrict, MeetsAlwaysTrue],
)
def test_the_registry_refuses_a_non_conformant_comparator(broken):
    """A conformance suite a DomainPack is merely encouraged to run is one it will not run."""
    registry = AuthorityPolicyRegistry()
    with pytest.raises(AuthorityConformanceError):
        registry.register(broken())
    assert registry.registered() == (), "a refused comparator must not be half-registered"


def test_the_registry_refuses_a_comparator_declaring_no_classes():
    """An empty declaration passes every law trivially, which is worse than failing one."""

    class Undeclared(Pairwise):
        authority_classes: ClassVar[tuple[str, ...]] = ()

    with pytest.raises(AuthorityConformanceError, match="declares no authority_classes"):
        AuthorityPolicyRegistry().register(Undeclared())


def test_conformance_is_checked_over_the_comparators_own_declared_classes():
    """Core cannot enumerate a domain's vocabulary, so the DomainPack declares it.

    A comparator may narrow its declaration and pass -- over `("A", "B")` this one really is an
    order. What it cannot do is narrow it *invisibly*: the declaration is a field in the
    comparator, so shipping a set smaller than the classes it handles shows up in a diff rather
    than in a belief transition.
    """

    class NarrowDeclaration(Cyclic):
        authority_classes: ClassVar[tuple[str, ...]] = ("A", "B")

    registry = AuthorityPolicyRegistry()
    registry.register(NarrowDeclaration())

    assert partial_order_violations(NarrowDeclaration(), ("A", "B", "C")), (
        "still broken over the full set, which is why the declaration is the DomainPack's "
        "responsibility"
    )


def test_registration_is_deterministic_in_the_declared_order():
    """`partial_order_violations` sorts and de-duplicates, so the listing order cannot decide."""

    class Reordered(ToyAuthorityPolicy):
        policy_version: ClassVar[str] = "1.0.0-reordered"
        authority_classes: ClassVar[tuple[str, ...]] = tuple(reversed(TOY_AUTHORITY_CLASSES))

    assert AuthorityPolicyRegistry().register(Reordered()) is not None
    assert partial_order_violations(Reordered(), TOY_AUTHORITY_CLASSES) == partial_order_violations(
        Reordered(), tuple(reversed(TOY_AUTHORITY_CLASSES))
    )
