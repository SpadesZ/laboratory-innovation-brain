"""T-VER-004: a plausible outcome comes from a declared, versioned OutcomeSpace and passes the
domain's explicit constraints and ValidationReport; the planner may not invent outcomes.

    T-VER-004  outcome outside declared OutcomeSpace 或被 explicit constraint/ValidationReport 排除時
               不可算 plausible；合法 outcome version 可重現 sufficiency result。

§9.1's four clauses, each refused on its own:

    1 DECLARED_OUTCOME       not a member of the declared space version
    2 NOT_EXCLUDED           explicitly excluded, or outside a declared validity bound
    3 DOMAIN_VALIDATOR       the DomainPack validator's report FAILs the outcome (or no validator)
    4 CAPABILITY_CAN_YIELD   the producing capability cannot yield it now
"""

from __future__ import annotations

import pytest

from lab_brain.core.models.capability import Availability
from lab_brain.core.sufficiency import InsufficientReason
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.verification.plausibility import (
    PlausibilityClause,
    assess_outcome,
    outcome_validator_id,
)
from lab_brain.verification.sufficiency import assess_action
from tests.vertical_units import CONDITIONS, exact_match, registries, rival, targets


def _space(regs, space_id: str = sp.SPACE_CONNECTIVITY):  # type: ignore[no-untyped-def]
    return regs.disagreement_metrics.outcome_space(space_id, sp.SPACE_VERSION)


def _assess(
    regs,
    outcome: str,
    *,
    space=None,
    capability_id=sp.CAP_INSPECT_CONNECTIVITY,  # type: ignore[no-untyped-def]
    observable=sp.OBS_CONNECTIVITY,
    conditions=None,
    validator="registered",
):
    return assess_outcome(
        outcome,
        space=space or _space(regs),
        observable_ref=observable,
        capability=regs.capabilities.resolve(capability_id),
        conditions=CONDITIONS if conditions is None else conditions,
        validator=(
            regs.validators.resolve(outcome_validator_id("silicon_photonics"))
            if validator == "registered"
            else validator
        ),
    )


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_a_declared_outcome_that_passes_every_clause_is_plausible():
    regs = registries()
    for outcome in ("CONTINUOUS", "DISCONTINUOUS"):
        verdict = _assess(regs, outcome)
        assert verdict.plausible, verdict.detail
        assert verdict.failed_clause is None


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_an_invented_outcome_is_not_plausible():
    verdict = _assess(registries(), "PARTIALLY_CONNECTED")
    assert not verdict.plausible
    assert verdict.failed_clause is PlausibilityClause.DECLARED_OUTCOME


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_an_explicitly_excluded_or_out_of_bounds_outcome_is_not_plausible():
    regs = registries()
    space = _space(regs)
    excluded = space.model_copy(update={"explicit_exclusions": ("DISCONTINUOUS",)})
    verdict = _assess(regs, "DISCONTINUOUS", space=excluded)
    assert not verdict.plausible and verdict.failed_clause is PlausibilityClause.NOT_EXCLUDED

    bounded = space.model_copy(update={"validity_bounds": {"device_length_um": {"max": "300"}}})
    verdict = _assess(regs, "DISCONTINUOUS", space=bounded)
    assert not verdict.plausible and verdict.failed_clause is PlausibilityClause.NOT_EXCLUDED
    assert "above the declared maximum" in verdict.detail


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_the_domain_validator_can_refuse_and_its_absence_is_a_refusal():
    regs = registries()
    # No device length: the domain rule FAILs the outcome (EVI-001's normalization basis).
    verdict = _assess(regs, "DISCONTINUOUS", conditions={})
    assert not verdict.plausible and verdict.failed_clause is PlausibilityClause.DOMAIN_VALIDATOR
    assert "sp.rule.normalization_basis_present@1.0.0" in verdict.detail
    # Read in another space than the one the pack declares for the observable.
    wrong = _space(regs, sp.SPACE_MESH)
    verdict = _assess(regs, "STABLE", space=wrong)
    assert not verdict.plausible and verdict.failed_clause is PlausibilityClause.DOMAIN_VALIDATOR
    # Clause 3 unanswered is clause 3 refused.
    verdict = _assess(regs, "DISCONTINUOUS", validator=None)
    assert not verdict.plausible and verdict.failed_clause is PlausibilityClause.DOMAIN_VALIDATOR


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_a_capability_that_cannot_yield_the_outcome_now_makes_it_implausible():
    regs = registries()
    # A capability the pack does not declare as a producer of this observable.
    verdict = _assess(regs, "DISCONTINUOUS", capability_id=sp.CAP_MESH_SENSITIVITY)
    assert not verdict.plausible
    assert verdict.failed_clause is PlausibilityClause.CAPABILITY_CAN_YIELD
    # The declared producer, UNAVAILABLE.
    regs.capabilities.set_availability(sp.CAP_INSPECT_CONNECTIVITY, Availability.UNAVAILABLE)
    verdict = _assess(regs, "DISCONTINUOUS")
    assert not verdict.plausible
    assert verdict.failed_clause is PlausibilityClause.CAPABILITY_CAN_YIELD


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_a_legal_outcome_version_reproduces_the_sufficiency_result():
    regs = registries()

    def assess(state):  # type: ignore[no-untyped-def]
        spaces = {
            (s.outcome_space_id, s.version): s for s in regs.disagreement_metrics.declared_spaces()
        }
        return assess_action(
            regs.capabilities.resolve(sp.CAP_INSPECT_CONNECTIVITY),
            hypotheses=(state,),
            targets=targets(),
            spaces=spaces,
            conditions=CONDITIONS,
            validator=regs.validators.resolve(outcome_validator_id("silicon_photonics")),
            authority_policy=sp.VerticalAuthorityPolicy(),
            projected_condition_match=exact_match(),
        )

    first = assess(rival("contact"))
    assert first.sufficient
    for _ in range(5):
        again = assess(rival("contact"))
        assert again.sufficient == first.sufficient
        assert [(d.hypothesis_id, d.to_state, d.outcome) for d in again.discriminating] == [
            (d.hypothesis_id, d.to_state, d.outcome) for d in first.discriminating
        ]
    # The same predictions bound to a version nobody declared: the space does not resolve, so
    # nothing about those outcomes can be sufficient -- the planner does not guess a vocabulary.
    unresolved = assess(rival("contact", version="9.9.9"))
    assert not unresolved.sufficient
    assert unresolved.reason == InsufficientReason.OUTCOME_SPACE_UNRESOLVED.value


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_a_capability_the_pack_never_declared_as_a_producer_cannot_yield_its_outcome():
    """A second descriptor claiming to produce the observable is refused by the domain's own
    producer rule (clause 4), not merely by its `produces` list."""
    regs = registries()
    genuine = regs.capabilities.resolve(sp.CAP_INSPECT_CONNECTIVITY)
    regs.capabilities.register(
        genuine.model_copy(update={"capability_id": "cap:sp.unvetted_connectivity_reader"})
    )
    verdict = _assess(regs, "DISCONTINUOUS", capability_id="cap:sp.unvetted_connectivity_reader")
    assert not verdict.plausible
    assert verdict.failed_clause is PlausibilityClause.CAPABILITY_CAN_YIELD
    assert "sp.rule.declared_producer@1.0.0" in verdict.detail


@pytest.mark.requirement("VER-004")
@pytest.mark.spec_test("T-VER-004")
def test_an_action_whose_every_outcome_is_implausible_is_not_sufficient():
    """No device length: the domain rule refuses every outcome, so nothing the inspection could
    return may be counted -- the action is insufficient, and the plan says why."""
    regs = registries()
    spaces = {
        (s.outcome_space_id, s.version): s for s in regs.disagreement_metrics.declared_spaces()
    }
    assessed = assess_action(
        regs.capabilities.resolve(sp.CAP_INSPECT_CONNECTIVITY),
        hypotheses=(rival("contact"),),
        targets=targets(),
        spaces=spaces,
        conditions={},
        validator=regs.validators.resolve(outcome_validator_id("silicon_photonics")),
        authority_policy=sp.VerticalAuthorityPolicy(),
        projected_condition_match=exact_match(),
    )
    assert not assessed.sufficient
    assert assessed.reason == "NO_PLAUSIBLE_OUTCOME"
    assert {v.outcome for v in assessed.implausible} == {"CONTINUOUS", "DISCONTINUOUS"}
