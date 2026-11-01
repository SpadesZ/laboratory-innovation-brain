"""The discovery loop's vocabulary and frozen record types.

WHAT A DISCOVERY OBJECT CAN BE, AND WHAT IT CAN NEVER BE. Every state below is a statement about
what the loop's own offline tests did, never about what is true:

    hypothesis   PROPOSED           registered; no prospective test evaluated yet
                 UNDER_TEST         registered and evaluated, but not yet through a test it could
                                    have failed with data taken AFTER its registration
                 SURVIVING          not refuted, and through at least one such prospective test
                 REFUTED            failed the pre-registered fit test on admitted data
                 INDISTINGUISHABLE  no available experiment separates it from a surviving member:
                                    reported inside that member's class, never counted twice and
                                    never resolved by fiat
                 STOPPED            still live when the loop stopped without resolving it
    anomaly      UNEXPLAINED        an observation no live hypothesis accounts for within the noise
                                    model, or the sole basis of a refutation when every hypothesis
                                    has failed
                 ACCOMMODATED       fitted by a hypothesis registered after it -- pending a
                                    prospective test; accommodation is not explanation
                 EXPLAINED          the accommodating hypothesis survived a prospective test
                 ATTRIBUTED_TO_NOISE  a pre-registered replication did not reproduce it and the
                                    replicate fits a declared hypothesis
    investigation  REFRAMED records (append-only), and a terminal `Outcome`

There is no CONFIRMED anywhere in this vocabulary, by design and by test
(`tests/unit/test_discovery_governance.py`). The best a discovery run can say is "surviving,
pending the Causal Warrant Gate": a confirmation in this repository needs warranted support, a
signed review or a code-reviewed declaration, and `ConfirmationRule.standing` -- none of which an
offline loop over toy forward models can provide.

Every record is a frozen dataclass and every history is an append-only tuple of `StateEvent`s; the
loop builds new records instead of mutating old ones, and `transition` refuses the moves the rules
forbid (leaving REFUTED except by a recorded reinstatement, or leaving ATTRIBUTED_TO_NOISE).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import cached_property
from typing import Any

from lab_brain.core.canonical_json import canonical_hash


class DiscoveryState(StrEnum):
    PROPOSED = "PROPOSED"
    UNDER_TEST = "UNDER_TEST"
    SURVIVING = "SURVIVING"
    REFUTED = "REFUTED"
    INDISTINGUISHABLE = "INDISTINGUISHABLE"
    STOPPED = "STOPPED"


#: States that keep a hypothesis in the running.
LIVE_STATES = frozenset(
    {
        DiscoveryState.PROPOSED,
        DiscoveryState.UNDER_TEST,
        DiscoveryState.SURVIVING,
        DiscoveryState.INDISTINGUISHABLE,
    }
)


class AnomalyState(StrEnum):
    UNEXPLAINED = "UNEXPLAINED"
    ACCOMMODATED = "ACCOMMODATED"
    EXPLAINED = "EXPLAINED"
    ATTRIBUTED_TO_NOISE = "ATTRIBUTED_TO_NOISE"


class AnomalyKind(StrEnum):
    #: The observation is outside the noise model under every live hypothesis's best fit.
    UNEXPLAINED_OBSERVATION = "UNEXPLAINED_OBSERVATION"
    #: Every hypothesis has failed, and this observation alone carries at least one refutation.
    SOLE_REFUTATION_BASIS = "SOLE_REFUTATION_BASIS"


class ReproductionResult(StrEnum):
    """The pre-registered replication test's three answers."""

    REPRODUCED = "REPRODUCED"
    #: The replicate disagrees with the original AND fits a declared hypothesis.
    NOT_REPRODUCED_NOISE = "NOT_REPRODUCED_NOISE"
    #: The replicate disagrees with the original and is itself unexplained -- not noise: the
    #: effect may be non-stationary. The anomaly stays UNEXPLAINED.
    NOT_REPRODUCED_UNSTABLE = "NOT_REPRODUCED_UNSTABLE"


class ReframingKind(StrEnum):
    WIDEN_MECHANISM_SPACE = "WIDEN_MECHANISM_SPACE"
    CHANGE_OBSERVABLE = "CHANGE_OBSERVABLE"
    QUESTION_THE_MEASUREMENT_CHAIN = "QUESTION_THE_MEASUREMENT_CHAIN"
    NARROW_SCOPE = "NARROW_SCOPE"
    STOP_INSUFFICIENT = "STOP_INSUFFICIENT"


class Outcome(StrEnum):
    """How an investigation ends. None of these is a confirmation."""

    #: One distinguishable class survived a prospective test: hand it to the Causal Warrant Gate.
    SURVIVING_PENDING_WARRANT_GATE = "SURVIVING_PENDING_WARRANT_GATE"
    #: A class of several members that no available experiment separates survived.
    INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE = "INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE"
    #: The surviving explanation is the noise model itself: nothing to hand over.
    NO_EFFECT_BEYOND_NOISE = "NO_EFFECT_BEYOND_NOISE"
    #: The budget or the available experiments cannot discriminate what is still live.
    STOPPED_INSUFFICIENT_VALIDATION = "STOPPED_INSUFFICIENT_VALIDATION"
    #: Every declared explanation failed and anomalies remain unexplained.
    STOPPED_UNEXPLAINED = "STOPPED_UNEXPLAINED"


#: Outcomes that assert an explanation (the noise model included).
CLAIM_OUTCOMES = frozenset(
    {
        Outcome.SURVIVING_PENDING_WARRANT_GATE,
        Outcome.INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE,
        Outcome.NO_EFFECT_BEYOND_NOISE,
    }
)


class MechanismKind(StrEnum):
    PHYSICAL = "PHYSICAL"
    MEASUREMENT_CHAIN = "MEASUREMENT_CHAIN"


class Tier(StrEnum):
    """Where a declared mechanism class sits relative to the investigation's starting set."""

    #: In the initial working set (the catalog prior).
    INITIAL = "INITIAL"
    #: A parameter-regime variant of an initial mechanism; proposed only by expansion.
    VARIANT = "VARIANT"
    #: Declared by the domain but outside the initial prior; reached only by widening.
    EXTENDED = "EXTENDED"


class Origin(StrEnum):
    """Why a hypothesis was registered."""

    INITIAL_CATALOG = "INITIAL_CATALOG"
    REGIME_VARIANT = "REGIME_VARIANT"
    EXTENDED_LIBRARY = "EXTENDED_LIBRARY"
    COMPOSITION = "COMPOSITION"
    MEASUREMENT_CHAIN_REVIEW = "MEASUREMENT_CHAIN_REVIEW"
    #: Added at the end because no available experiment separates it from a survivor.
    INDISTINGUISHABILITY_CLOSURE = "INDISTINGUISHABILITY_CLOSURE"


class Purpose(StrEnum):
    """Why an experiment was run."""

    DISCRIMINATE = "DISCRIMINATE"
    NOISE_TEST = "NOISE_TEST"
    PROSPECTIVE_TEST = "PROSPECTIVE_TEST"
    CHAIN_CHECK = "CHAIN_CHECK"
    #: The single-hypothesis baseline's confirmation-seeking test.
    SINGLE_HYPOTHESIS_TEST = "SINGLE_HYPOTHESIS_TEST"
    #: Before a claim: replicate the observation a rival's refutation rests on alone.
    DECISIVE_REPLICATION = "DECISIVE_REPLICATION"


@dataclass(frozen=True)
class EntrySpec:
    """One scalar an experiment reports, and its declared noise (Gaussian, standard deviation)."""

    entry_id: str
    unit: str
    sigma: float

    def __post_init__(self) -> None:
        if not (self.sigma > 0 and math.isfinite(self.sigma)):
            raise ValueError(f"entry {self.entry_id} declares a non-positive noise sigma")


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    description: str
    #: Cost in budget units. Replicating an experiment costs the same again.
    cost: int
    entries: tuple[EntrySpec, ...]
    #: Declared conditions, for the record (the forward models were evaluated against them).
    conditions: tuple[tuple[str, str], ...] = ()
    #: An experiment whose purpose is to verify the measurement chain itself.
    chain_check: bool = False

    def __post_init__(self) -> None:
        if self.cost < 1:
            raise ValueError(f"experiment {self.experiment_id} must cost at least one unit")
        ids = [e.entry_id for e in self.entries]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError(f"experiment {self.experiment_id} declares no or duplicate entries")

    def entry(self, entry_id: str) -> EntrySpec:
        return next(e for e in self.entries if e.entry_id == entry_id)


@dataclass(frozen=True)
class UnavailableExperiment:
    """A declared experiment this lab cannot run, and why. Never selected; named when it would
    separate what the available ones cannot (CHANGE_OBSERVABLE)."""

    experiment: ExperimentSpec
    reason: str


@dataclass(frozen=True)
class MechanismClass:
    """A typed, declared mechanism class (one parameter regime) with a tabulated forward model.

    The forward model is linear in one amplitude parameter: an experiment's entry is predicted as
    ``amplitude * sensitivity[(experiment, entry)]``, amplitude in ``[lower, upper]``. The domain
    pack evaluates its forward-model functions against each declared experiment's conditions once
    and hands the engine the TABLE -- the engine never calls domain code, and a mechanism's
    identity is its table (`fingerprint`), not its name.
    """

    class_id: str
    #: The mechanism family; two regimes of one family are never composed with each other.
    family: str
    mechanism: str
    regime: str
    statement: str
    kind: MechanismKind
    tier: Tier
    parameter: str
    lower: float
    upper: float
    #: (experiment id, entry id, sensitivity per unit amplitude); zero entries omitted.
    sensitivity: tuple[tuple[str, str, float], ...]
    prior: float = 0.0

    def __post_init__(self) -> None:
        if not self.lower < self.upper:
            raise ValueError(f"mechanism {self.class_id} declares an empty amplitude range")
        if self.lower <= 0.0 <= self.upper:
            raise ValueError(
                f"mechanism {self.class_id}'s amplitude range contains zero; a regime that can "
                "vanish is indistinguishable from the noise model by construction"
            )
        keys = [(e, n) for e, n, _ in self.sensitivity]
        if len(set(keys)) != len(keys):
            raise ValueError(f"mechanism {self.class_id} declares a sensitivity twice")
        if not self.sensitivity:
            raise ValueError(f"mechanism {self.class_id} predicts nothing anywhere")
        if self.prior < 0:
            raise ValueError("a prior weight cannot be negative")

    def coefficient(self, experiment_id: str, entry_id: str) -> float:
        for e, n, c in self.sensitivity:
            if e == experiment_id and n == entry_id:
                return c
        return 0.0

    @cached_property
    def fingerprint(self) -> str:
        """The forward model's identity: its table and its range, whatever it is called."""
        table = sorted((e, n, _num(c)) for e, n, c in self.sensitivity if c != 0.0)
        return canonical_hash(
            {"sensitivity": [list(t) for t in table], "range": [_num(self.lower), _num(self.upper)]}
        )


@dataclass(frozen=True)
class Hypothesis:
    """A candidate explanation: no mechanism (the noise model), one, or a composition of two."""

    hypothesis_id: str
    components: tuple[MechanismClass, ...]

    @property
    def is_null(self) -> bool:
        return not self.components

    @property
    def class_ids(self) -> tuple[str, ...]:
        return tuple(c.class_id for c in self.components)

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(c.family for c in self.components)

    @cached_property
    def fingerprint(self) -> str:
        return canonical_hash(sorted(c.fingerprint for c in self.components))

    @property
    def prior(self) -> float:
        if self.is_null:
            return 0.0
        return math.prod(c.prior for c in self.components)

    @property
    def statement(self) -> str:
        if self.is_null:
            return "No effect beyond the declared noise model."
        return " AND ".join(c.statement for c in self.components)

    @property
    def mechanism(self) -> str:
        if self.is_null:
            return "noise model only"
        return " + ".join(f"{c.mechanism} ({c.regime})" for c in self.components)


NULL_HYPOTHESIS_ID = "hyp:null"


def hypothesis_id_for(components: tuple[MechanismClass, ...]) -> str:
    if not components:
        return NULL_HYPOTHESIS_ID
    return "hyp:" + "+".join(sorted(c.class_id for c in components))


def make_hypothesis(*components: MechanismClass) -> Hypothesis:
    ordered = tuple(sorted(components, key=lambda c: c.class_id))
    families = [c.family for c in ordered]
    if len(set(families)) != len(families):
        raise ValueError("a composition combines two different mechanism families")
    return Hypothesis(hypothesis_id=hypothesis_id_for(ordered), components=ordered)


NULL_HYPOTHESIS = Hypothesis(hypothesis_id=NULL_HYPOTHESIS_ID, components=())


@dataclass(frozen=True)
class Observation:
    observation_id: str
    experiment_id: str
    #: How many times this experiment had been run before in this investigation.
    replicate: int
    #: The loop step at which it was taken. 0 is before the investigation began.
    taken_at: int
    values: tuple[tuple[str, float], ...]
    #: The observation that motivated the investigation. It was selected BECAUSE it looked
    #: anomalous, so it can neither support nor refute anything: it is context.
    motivating: bool = False

    def value(self, entry_id: str) -> float:
        return next(v for e, v in self.values if e == entry_id)


@dataclass(frozen=True)
class StateEvent:
    step: int
    state: str
    reason: str
    basis: tuple[str, ...] = ()


@dataclass(frozen=True)
class HypothesisRecord:
    hypothesis: Hypothesis
    registered_at: int
    origin: Origin
    history: tuple[StateEvent, ...]
    #: The hypothesis this one is an exact duplicate of (identical forward model), if any.
    alias_of: str | None = None

    @property
    def hypothesis_id(self) -> str:
        return self.hypothesis.hypothesis_id

    @property
    def state(self) -> DiscoveryState:
        return DiscoveryState(self.history[-1].state)

    @property
    def is_live(self) -> bool:
        return self.state in LIVE_STATES

    @property
    def ever_refuted(self) -> bool:
        return any(e.state == DiscoveryState.REFUTED for e in self.history)


@dataclass(frozen=True)
class ReproductionTest:
    step: int
    original_observation_id: str
    replicate_observation_id: str
    result: ReproductionResult
    max_disagreement_z: float
    reference_hypothesis_id: str | None


@dataclass(frozen=True)
class AnomalyRecord:
    anomaly_id: str
    kind: AnomalyKind
    observation_id: str
    detected_at: int
    #: Live hypotheses (kind 1) or refuted hypotheses resting on it (kind 2) at detection.
    hypotheses_at_detection: tuple[str, ...]
    max_abs_z: float
    history: tuple[StateEvent, ...]
    tests: tuple[ReproductionTest, ...] = ()

    @property
    def state(self) -> AnomalyState:
        return AnomalyState(self.history[-1].state)

    @property
    def reproduced(self) -> bool:
        return any(t.result is ReproductionResult.REPRODUCED for t in self.tests)


@dataclass(frozen=True)
class ReframingRecord:
    reframing_id: str
    kind: ReframingKind
    step: int
    #: Provenance: every hypothesis refuted by then, and the anomalies that motivated it.
    failed_hypotheses: tuple[str, ...]
    anomalies: tuple[str, ...]
    added_hypotheses: tuple[str, ...]
    considered: int
    rationale: str
    #: Hypotheses the reframing is about without adding them (CHANGE_OBSERVABLE: the class it
    #: cannot separate; NARROW_SCOPE: what fits outside the anomalous experiments).
    subjects: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepRecord:
    step: int
    experiment_id: str
    purpose: Purpose
    utility: float
    cost: int
    budget_after: int
    observation_id: str


class TransitionRefused(RuntimeError):
    """A record was asked to make a move the discovery rules forbid."""


_REINSTATEMENT = "reinstated:"


def transition(
    record: HypothesisRecord, step: int, state: DiscoveryState, reason: str, basis: tuple[str, ...]
) -> HypothesisRecord:
    """Append one state event. Leaving REFUTED needs a recorded reinstatement reason."""
    leaving = record.state is DiscoveryState.REFUTED and state is not DiscoveryState.REFUTED
    if leaving and (
        not reason.startswith(_REINSTATEMENT) or state is not DiscoveryState.UNDER_TEST
    ):
        raise TransitionRefused(
            f"{record.hypothesis_id} is REFUTED; it returns to UNDER_TEST only by a recorded "
            "reinstatement (its refutation basis attributed to noise), never to support"
        )
    if record.state is state and record.history[-1].reason == reason:
        return record
    return replace(record, history=(*record.history, StateEvent(step, state.value, reason, basis)))


def anomaly_transition(
    record: AnomalyRecord, step: int, state: AnomalyState, reason: str, basis: tuple[str, ...]
) -> AnomalyRecord:
    if record.state is AnomalyState.ATTRIBUTED_TO_NOISE and state is not record.state:
        raise TransitionRefused(f"{record.anomaly_id} was attributed to noise; that is terminal")
    if record.state is state and record.history[-1].reason == reason:
        return record
    return replace(record, history=(*record.history, StateEvent(step, state.value, reason, basis)))


def reinstatement_reason(observation_id: str) -> str:
    return f"{_REINSTATEMENT} its refutation depended on {observation_id}, attributed to noise"


@dataclass(frozen=True)
class Budget:
    total: int

    def __post_init__(self) -> None:
        if self.total < 1:
            raise ValueError("a budget is at least one unit")


def _num(value: float) -> str:
    """A float as the fixed decimal string identity hashing uses (the JCS profile has no floats)."""
    return format(round(value, 9), ".9f")


def _for_hashing(value: Any) -> Any:
    if isinstance(value, float):
        return format(value, ".6f")
    if isinstance(value, dict):
        return {k: _for_hashing(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_for_hashing(v) for v in value]
    return value


def stable_digest(value: Any) -> str:
    """The canonical hash of a record tree's JSON form, floats as fixed six-decimal strings."""
    return canonical_hash(_for_hashing(to_jsonable(value)))


def to_jsonable(value: Any) -> Any:
    """A deterministic JSON form of a record tree; floats rounded so diffs are of substance."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Hypothesis):
        # A hypothesis is identified by its components and its forward model; the components'
        # full tables live in the catalog, whose digest the manifest records.
        return {
            "hypothesis_id": value.hypothesis_id,
            "components": list(value.class_ids),
            "fingerprint": value.fingerprint,
        }
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: to_jsonable(getattr(value, name))
            for name, spec in value.__dataclass_fields__.items()
            if spec.repr
        }
    return value


@dataclass(frozen=True)
class GateRequirement:
    """One thing the Causal Warrant Gate still has to establish before anything is confirmed."""

    requirement: str
    where: str


@dataclass(frozen=True)
class RivalStanding:
    hypothesis_id: str
    mechanism: str
    state: str
    #: The observations its refutation rested on (leave-one-out pivotal), if refuted.
    refutation_basis: tuple[str, ...]
    #: The available experiment that separates it best from the candidate class, and by how much
    #: (standardised, worst case over both amplitude ranges, one run).
    best_separating_experiment: str | None
    separation: float


@dataclass(frozen=True)
class GateHandover:
    """What the discovery loop hands to the Causal Warrant Gate -- and what it cannot.

    The candidate class and its rivals map onto the gate's inputs (a hypothesis set of rivals,
    each with a mechanism, a statement and a falsifier: `draft_certificates`). What the loop
    cannot produce is any warrant: a refutation here is a chi-square test over toy forward models,
    not a warranted CONTRADICTS, and survival here is not warranted SUPPORTS. `requirements` names
    what the gate must still establish; `status` is always pending.
    """

    status: str
    outcome: Outcome
    candidate_class: tuple[str, ...]
    candidate_mechanisms: tuple[str, ...]
    #: Per member: the observations taken after its registration that it passed.
    prospective_support: tuple[tuple[str, tuple[str, ...]], ...]
    rivals: tuple[RivalStanding, ...]
    #: Declared library classes never registered here -- the closed-world residual (T9).
    never_considered: tuple[str, ...]
    open_anomalies: tuple[str, ...]
    #: Unavailable declared experiments that would separate members of the candidate class.
    would_separate: tuple[tuple[str, str], ...]
    requirements: tuple[GateRequirement, ...]
    #: More complex declared hypotheses (the class plus a small extra contribution) that no
    #: available experiment separates from a member: not part of the class (parsimony), but not
    #: excluded either.
    cannot_exclude: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class DiscoveryResult:
    """Everything one investigation did, in order, and how it ended. Frozen and replayable."""

    arm: str
    protocol_digest: str
    catalog_ref: str
    budget: int
    spent: int
    outcome: Outcome
    #: The claimed class (hypothesis ids), empty when no claim is made.
    claim: tuple[str, ...]
    hypotheses: tuple[HypothesisRecord, ...]
    observations: tuple[Observation, ...]
    anomalies: tuple[AnomalyRecord, ...]
    reframings: tuple[ReframingRecord, ...]
    steps: tuple[StepRecord, ...]
    handover: GateHandover | None
    #: Decisive replications run before a claim (pre-registered), and their results.
    replications: tuple[ReproductionTest, ...] = ()
    notes: tuple[str, ...] = ()

    def record(self, hypothesis_id: str) -> HypothesisRecord:
        return next(r for r in self.hypotheses if r.hypothesis_id == hypothesis_id)

    @property
    def examined(self) -> tuple[Hypothesis, ...]:
        """Every distinct forward model the run registered and held against data (no aliases)."""
        return tuple(
            r.hypothesis
            for r in self.hypotheses
            if r.alias_of is None and r.origin is not Origin.INDISTINGUISHABILITY_CLOSURE
        )

    def as_json(self) -> Any:
        return to_jsonable(self)

    @property
    def digest(self) -> str:
        return stable_digest(self)


__all__ = [
    "CLAIM_OUTCOMES",
    "LIVE_STATES",
    "NULL_HYPOTHESIS",
    "NULL_HYPOTHESIS_ID",
    "AnomalyKind",
    "AnomalyRecord",
    "AnomalyState",
    "Budget",
    "DiscoveryResult",
    "DiscoveryState",
    "EntrySpec",
    "ExperimentSpec",
    "GateHandover",
    "GateRequirement",
    "Hypothesis",
    "HypothesisRecord",
    "MechanismClass",
    "MechanismKind",
    "Observation",
    "Origin",
    "Outcome",
    "Purpose",
    "ReframingKind",
    "ReframingRecord",
    "ReproductionResult",
    "ReproductionTest",
    "RivalStanding",
    "StateEvent",
    "StepRecord",
    "Tier",
    "TransitionRefused",
    "UnavailableExperiment",
    "anomaly_transition",
    "hypothesis_id_for",
    "make_hypothesis",
    "reinstatement_reason",
    "stable_digest",
    "to_jsonable",
    "transition",
]
