"""Silicon photonics evidence authority — a partial order, not a ladder (SIM-002, §10.5, ADR-0007).

    §10.5   Core 只有 `EvidenceAuthority` 抽象；「measurement 永遠最高」**不是** core 假設。
            權威是 `(method, calibration, validated_range fit)` 的函數。
    SIM-002 coarse/low-fidelity contradiction 只能標記 CHALLENGED；要 REJECT hypothesis 必須過
            standard/validation fidelity gate。

SIM-002 IS AN AUTHORITY QUESTION, WHICH IS WHY IT IS IMPLEMENTED HERE AND NOT IN CORE. "A coarse
result may challenge but not reject" is a statement about how much weight a fidelity level carries,
and §10.5 puts exactly that in the DomainPack column. The mechanism is already built and locked:
`TransitionPolicy.evaluate` asks `meets(required_authority_rule, candidate)` and DENYs when the
answer is False. So the requirement is discharged by two registered policy records -- an
ACTIVE→CHALLENGED policy whose rule is `SIM_COARSE`, and an ACTIVE→CONTRADICTED policy whose rule
is `SIM_STANDARD` -- plus this comparator ranking coarse below standard. No core file changes, and
the belief transition is still authorised by the one operator §8.2.1 declares.

THE CROSS-FAMILY PAIRS ARE INCOMPARABLE, AND THAT IS THE POINT OF THE WHOLE ADR. A calibrated
measurement and a validation-fidelity simulation do not rank: the measurement is authoritative
about the device that was fabricated, the simulation about the device that was designed, and when
they disagree the answer is §10.6's SIM_TO_REAL_CONFLICT rather than an ordering. A comparator that
returned STRONGER for the measurement would be encoding "measurement is always highest", which
§10.5 names as the thing core must not assume -- and a DomainPack asserting it would be the same
error one layer out.

    §10.6  模擬與量測不一致時，**不得**以「measurement 永遠真」抹平。

`INCOMPARABLE` at a required gate routes to NEED_HUMAN_REVIEW with a
`ReviewItem(AUTHORITY_CONFLICT)` (EPI-004), which is the behaviour this ranking is built to produce
rather than a side effect of it.
"""

from __future__ import annotations

from typing import ClassVar, Final

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.enums import AuthorityComparison, ConditionMatchState, RelationType
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN

#: Simulated fidelity levels, in the sense §10.3's run manifest and SIM-002 use.
SIM_COARSE: Final = "SIM_COARSE"
SIM_STANDARD: Final = "SIM_STANDARD"
SIM_VALIDATION: Final = "SIM_VALIDATION"

#: Measured classes. Calibration is what separates them, per §10.5's
#: `(method, calibration, validated_range fit)`.
MEAS_UNCALIBRATED: Final = "MEAS_UNCALIBRATED"
MEAS_CALIBRATED: Final = "MEAS_CALIBRATED"

AUTHORITY_CLASSES: Final[tuple[str, ...]] = (
    MEAS_CALIBRATED,
    MEAS_UNCALIBRATED,
    SIM_COARSE,
    SIM_STANDARD,
    SIM_VALIDATION,
)

#: The fidelity gate SIM-002 names. A contradiction at or above this may reject a hypothesis;
#: below it, the strongest available move is CHALLENGED.
REJECTION_FIDELITY_GATE: Final = SIM_STANDARD

_FAMILIES: Final[dict[str, str]] = {
    SIM_COARSE: "SIMULATED",
    SIM_STANDARD: "SIMULATED",
    SIM_VALIDATION: "SIMULATED",
    MEAS_UNCALIBRATED: "MEASURED",
    MEAS_CALIBRATED: "MEASURED",
}

_RANK: Final[dict[str, int]] = {
    SIM_COARSE: 1,
    SIM_STANDARD: 2,
    SIM_VALIDATION: 3,
    MEAS_UNCALIBRATED: 1,
    MEAS_CALIBRATED: 2,
}


class SiliconPhotonicsAuthorityPolicy:
    """§10.5.1's comparator for this domain. Two total orders, no edges between them.

    Satisfies the laws `AuthorityPolicyRegistry.register` checks -- reflexive, converse-symmetric,
    transitive where a chain exists, deterministic, closed over the four results, and `meets`
    agreeing with `compare`. Those are verified at registration rather than asserted in a test,
    so a pack whose ranking is not an order cannot be installed.
    """

    policy_id: ClassVar[str] = "auth:silicon_photonics"
    policy_version: ClassVar[str] = "1.0.0"
    authority_classes: ClassVar[tuple[str, ...]] = AUTHORITY_CLASSES

    def compare(self, a: str, b: str) -> AuthorityComparison:
        if a == b:
            # Reflexivity before anything else. An unranked class still ranks with itself, and
            # falling through to INCOMPARABLE here would make every authority threshold
            # unanswerable for it.
            return AuthorityComparison.EQUIVALENT
        if a not in _RANK or b not in _RANK:
            return AuthorityComparison.INCOMPARABLE
        if _FAMILIES[a] != _FAMILIES[b]:
            # §10.6. Not a fallback: simulated and measured evidence genuinely do not rank against
            # each other, and inventing an ordering here is what makes a sim-to-real disagreement
            # disappear instead of being escalated.
            return AuthorityComparison.INCOMPARABLE
        if _RANK[a] == _RANK[b]:
            return AuthorityComparison.EQUIVALENT
        return AuthorityComparison.STRONGER if _RANK[a] > _RANK[b] else AuthorityComparison.WEAKER

    def meets(self, required_rule: str, candidate: str) -> bool:
        """Only by ranking at or above. INCOMPARABLE is neither met nor unmet.

        `evaluate` checks INCOMPARABLE via `compare` *before* asking this, so the question never
        reaches here in that state; returning False for it here would read downstream as a DENY and
        lose the escalation §10.5.1 requires.
        """
        return self.compare(candidate, required_rule) in (
            AuthorityComparison.STRONGER,
            AuthorityComparison.EQUIVALENT,
        )


#: SIM-002, as two registered §8.2.1 policy records.
#:
#: DOMAIN-SCOPED POLICY RECORDS, NOT A NEW MECHANISM. `TransitionPolicy` carries a `domain` field
#: for exactly this, and `evaluate` is unchanged -- what the pack supplies is the *fidelity gate*,
#: which is domain knowledge, while core keeps the operator that applies it.
CHALLENGE_POLICY_ID: Final = "policy:sp-fidelity-challenge"
REJECT_POLICY_ID: Final = "policy:sp-fidelity-reject"
POLICY_VERSION: Final = "1.0.0"


def transition_policies() -> tuple[TransitionPolicy, ...]:
    """The ACTIVE→CHALLENGED and ACTIVE→CONTRADICTED pair SIM-002 turns on.

    NOT PART OF THE `DomainPack` PROTOCOL. §24.3 declares no `register_transition_policies`, and
    adding one would be this implementation inventing normative extension surface. The pack offers
    the records; the composition root registers them into the `transition_policies` store `005b`
    already provides.

    `CONTRADICTED` rather than `REJECTED` because that is the state §8.2's diagram declares --
    §8.2.1's prose says "SUPPORTED/REJECTED" as shorthand and SPEC-ISSUE-010 ruled on it.
    """
    # Spelled out per policy rather than splatted from a shared dict. A `**common` erases every
    # field type, so mypy checks none of the arguments -- and the one place that matters is exactly
    # here: a `candidate_to_state` or a `required_authority_rule` that was silently the wrong type
    # would make the fidelity gate ungoverned while the pack still installed.
    return (
        TransitionPolicy(
            policy_id=CHALLENGE_POLICY_ID,
            domain=DOMAIN,
            version=POLICY_VERSION,
            from_state=BeliefState.ACTIVE,
            candidate_to_state=BeliefState.CHALLENGED,
            required_relation_types=(RelationType.CONTRADICTS,),
            required_condition_match=(
                ConditionMatchState.EXACT,
                ConditionMatchState.COMPATIBLE,
            ),
            # Coarse evidence is enough to raise a challenge. That is the permissive half, and it
            # has to exist: SIM-002 says a low-fidelity contradiction DOES do something.
            required_authority_rule=SIM_COARSE,
            # §10.6: a simulated contradiction while a measurement disagrees is a
            # SIM_TO_REAL_CONFLICT, and neither move may proceed while it is open and blocking.
            blocking_conflict_policy=("SIM_TO_REAL_CONFLICT", "VALIDITY_CONFLICT"),
        ),
        TransitionPolicy(
            policy_id=REJECT_POLICY_ID,
            domain=DOMAIN,
            version=POLICY_VERSION,
            from_state=BeliefState.ACTIVE,
            candidate_to_state=BeliefState.CONTRADICTED,
            required_relation_types=(RelationType.CONTRADICTS,),
            required_condition_match=(
                ConditionMatchState.EXACT,
                ConditionMatchState.COMPATIBLE,
            ),
            # THE GATE. `meets(SIM_STANDARD, SIM_COARSE)` is False because coarse ranks below
            # standard, so `evaluate` returns DENY/AUTHORITY_INSUFFICIENT and the hypothesis is
            # not rejected on a coarse result.
            required_authority_rule=REJECTION_FIDELITY_GATE,
            # Rejecting a hypothesis is the least recoverable move in §8.2, so it also requires
            # corroboration that a single run cannot supply on its own.
            min_independent_attestations=1,
            blocking_conflict_policy=("SIM_TO_REAL_CONFLICT", "VALIDITY_CONFLICT"),
        ),
    )


__all__ = [
    "AUTHORITY_CLASSES",
    "CHALLENGE_POLICY_ID",
    "MEAS_CALIBRATED",
    "MEAS_UNCALIBRATED",
    "POLICY_VERSION",
    "REJECTION_FIDELITY_GATE",
    "REJECT_POLICY_ID",
    "SIM_COARSE",
    "SIM_STANDARD",
    "SIM_VALIDATION",
    "SiliconPhotonicsAuthorityPolicy",
    "transition_policies",
]
