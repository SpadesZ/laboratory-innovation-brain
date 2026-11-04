"""The safety layer's vocabulary: a pre-declared protocol, decisions, and frozen records.

DECISIONS. A safe run ends in exactly one of two decisions:

    ENDORSE_PENDING_WARRANT_GATE  the engine's claim passed the adequacy probes and the pre-declared
                                  goodness-of-fit test on every experiment it predicts a signal in;
                                  still only a candidate for the Causal Warrant Gate
    ABSTAIN                       no mechanism is endorsed. The reason says why, and the assessment
                                  carries what a person can act on: open anomaly records, a
                                  reframed question, a stage-1 proposal, a discriminating-
                                  experiment request

ABSTENTION REASONS.

    NO_ENGINE_CLAIM                    the engine itself stopped without a claim
    ADEQUACY_UNVERIFIED                the claim fits what was run, but the budget did not reach
                                       every experiment it predicts a signal in: untested, so not
                                       endorsed (confidence PROVISIONAL)
    CLAIM_INADEQUATE                   the claim fails the adequacy test, and some other hypothesis
                                       the catalog expresses is still adequate: re-investigate
    CATALOG_INCOMPLETE                 nothing the catalog can express is adequate, and the failing
                                       observation was reproduced by a replicate
    CATALOG_INCOMPLETE_UNREPLICATED    the same, but no replicate was affordable: suspected, not
                                       reproduced

CONFIDENCE is ordinal and moves only on discriminating evidence: NONE (no claim, or the claim is
inadequate), PROVISIONAL (a claim not yet through its adequacy probes), ADEQUATE (endorsed). It is
never a probability, and replication of an experiment already run, or a renamed duplicate of a
hypothesis already held, cannot raise it (`discriminating_tests_passed` counts DISTINCT experiments
against DISTINCT forward models).

A PROPOSAL IS NOT A CLAIM. `NewFamilyProposal` is a stage-1 exploratory idea: a tabulated signature
read off the residuals, `stage = STAGE_1_EXPLORATORY_IDEA`, `status = PROPOSAL_NOT_A_CLAIM`. Its
predictions were derived from the data they describe, so they can support nothing until an
experiment NOT used to derive them tests them; it never enters a claim, a handover or a score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from lab_brain.discovery.model import DiscoveryResult, Outcome, stable_digest


class SafetyDecision(StrEnum):
    ENDORSE_PENDING_WARRANT_GATE = "ENDORSE_PENDING_WARRANT_GATE"
    ABSTAIN = "ABSTAIN"


class AbstentionReason(StrEnum):
    NO_ENGINE_CLAIM = "NO_ENGINE_CLAIM"
    ADEQUACY_UNVERIFIED = "ADEQUACY_UNVERIFIED"
    CLAIM_INADEQUATE = "CLAIM_INADEQUATE"
    CATALOG_INCOMPLETE = "CATALOG_INCOMPLETE"
    CATALOG_INCOMPLETE_UNREPLICATED = "CATALOG_INCOMPLETE_UNREPLICATED"


class ConfidenceLevel(StrEnum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    ADEQUATE = "ADEQUATE"

    @property
    def rank(self) -> int:
        return {"NONE": 0, "PROVISIONAL": 1, "ADEQUATE": 2}[self.value]


class ProbePurpose(StrEnum):
    #: An experiment the claim has not been tested on, run before anything is endorsed.
    ADEQUACY_PROBE = "ADEQUACY_PROBE"
    #: A replicate of a probe that failed the claim: is the inadequacy reproduced, or noise?
    PROBE_REPLICATION = "PROBE_REPLICATION"


class RequestPurpose(StrEnum):
    #: Separates two remaining candidates (pairwise; never through a chain).
    DISCRIMINATE_CANDIDATES = "DISCRIMINATE_CANDIDATES"
    #: Separates the stage-1 proposal ("none of the above") from a declared candidate.
    DISCRIMINATE_PROPOSAL = "DISCRIMINATE_PROPOSAL"
    #: An experiment the claim predicts a signal in and was never tested on.
    ADEQUACY_PROBE = "ADEQUACY_PROBE"


#: The stage and status every proposal carries; tests hold that nothing else is ever written.
PROPOSAL_STAGE = "STAGE_1_EXPLORATORY_IDEA"
PROPOSAL_STATUS = "PROPOSAL_NOT_A_CLAIM"


@dataclass(frozen=True)
class SafetyProtocol:
    """Every threshold of the safety layer, fixed before any world is run and hashed.

    alpha_adequacy        a hypothesis is ADEQUATE only if its chi-square fit to every admitted
                          observation has an upper-tail p-value of at least this (ten times the
                          engine's refutation alpha: endorsing asks for more than not-refuted) ...
    z_adequacy            ... and no admitted observation has an entry whose |standardised
                          residual| under that fit exceeds this (the engine's anomaly threshold)
    z_signal              an experiment is one the claim PREDICTS A SIGNAL IN when, at the claim's
                          fitted amplitudes, some entry's predicted value is at least this many
                          sigma from zero; a proposal's signature keeps an entry whose replicate
                          mean is at least this many standard errors from zero
    signal_coverage       the share of the claim's signal experiments that must have been run
                          before it is endorsed (1.0: every one)
    probe_null_experiments  after the signal experiments, also probe experiments the claim predicts
                          nothing in, as the budget allows (an unknown effect can show up there)
    max_probe_replications  replicates spent on failing probes, at most
    discriminating_tau    a requested experiment separates two candidates when one run's predicted
                          outcomes differ by at least this many sigma (worst case over amplitudes);
                          below it, the request states how many replicates would reach it
    max_request_candidates  pairwise requests are built over at most this many best-fitting
                          candidates (pairs grow quadratically)

    None of these was chosen by looking at the frozen evaluation worlds; the values are the
    statistical defaults stated above, fixed on development seeds only.
    """

    protocol_id: str = "lab-brain/discovery-safety-offline"
    version: str = "1.0.0"
    alpha_adequacy: float = 1e-2
    z_adequacy: float = 4.0
    z_signal: float = 3.0
    signal_coverage: float = 1.0
    probe_null_experiments: bool = True
    max_probe_replications: int = 2
    discriminating_tau: float = 5.0
    max_request_candidates: int = 4
    #: Switches for the mutation check and the ablations; the safe arm runs with all on.
    probes: bool = True
    abstain_on_inadequacy: bool = True
    require_coverage: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.alpha_adequacy < 1:
            raise ValueError("alpha_adequacy is a probability")
        if min(self.z_adequacy, self.z_signal, self.discriminating_tau) <= 0:
            raise ValueError("thresholds are positive")
        if not 0 <= self.signal_coverage <= 1:
            raise ValueError("signal_coverage is a share")
        if self.max_probe_replications < 0 or self.max_request_candidates < 2:
            raise ValueError("counts are non-negative, and a request needs two candidates")

    @property
    def digest(self) -> str:
        return stable_digest(self)


SAFETY = SafetyProtocol()


@dataclass(frozen=True)
class AdequacyTest:
    """One hypothesis against every admitted observation, under the pre-declared criterion."""

    hypothesis_id: str
    fingerprint: str
    chi2: float
    n: int
    dof: int
    p_value: float
    worst_observation: str | None
    worst_z: float
    adequate: bool


@dataclass(frozen=True)
class ProbeRecord:
    observation_id: str
    experiment_id: str
    purpose: ProbePurpose
    #: Whether the claim predicts a signal in this experiment (at its fitted amplitudes).
    claim_signal: bool
    #: Largest |standardised residual| of this observation under the claim's refit (worst member).
    max_abs_z_under_claim: float
    #: For a replication: the probe it repeats.
    replicates: str | None = None


@dataclass(frozen=True)
class SignatureEntry:
    experiment_id: str
    entry_id: str
    #: Replicate mean of the admitted readings, and how many there were.
    mean: float
    runs: int
    #: mean / (sigma / sqrt(runs)).
    z: float


@dataclass(frozen=True)
class NewFamilyProposal:
    """A stage-1 exploratory idea: a mechanism family outside the catalog, read off the residuals.

    Never a claim. Its table IS the data it was read from, so it fits them by construction
    (`fits_observed` states that it does, as a consistency check, not as support).
    """

    proposal_id: str
    stage: str
    status: str
    statement: str
    #: Entries with a significant effect: the proposed family's tabulated signature.
    signature: tuple[SignatureEntry, ...]
    #: Observed entries with no significant effect (the family predicts nothing there).
    observed_null: tuple[tuple[str, str], ...]
    #: Available experiments never run: the proposal predicts NOTHING there (unknown).
    unobserved_experiments: tuple[str, ...]
    fits_observed: bool
    fit_p_value: float
    #: The declared hypothesis whose best fit comes closest to the signature, and how close
    #: (standardised, one run of each observed experiment).
    closest_declared: str | None
    closest_separation: float
    required_next: str


@dataclass(frozen=True)
class ExperimentRequest:
    experiment_id: str
    available: bool
    purpose: RequestPurpose
    #: (candidate, candidate, one-run separation in sigma); a pair is listed only for itself.
    pairs: tuple[tuple[str, str, float], ...]
    #: Runs needed for the pair's separation to reach `discriminating_tau` (1 if one run does).
    replicates_needed: int
    rationale: str


@dataclass(frozen=True)
class SafetyAssessment:
    protocol_digest: str
    engine_outcome: Outcome
    engine_claim: tuple[str, ...]
    decision: SafetyDecision
    reason: AbstentionReason | None
    confidence: ConfidenceLevel
    #: The claim's members (or, without a claim, nothing) under the adequacy test, after probes.
    adequacy: tuple[AdequacyTest, ...]
    probes: tuple[ProbeRecord, ...]
    #: Available experiments the claim predicts a signal in, and which of them were run.
    signal_experiments: tuple[str, ...]
    signal_covered: tuple[str, ...]
    #: Nothing the catalog can express is adequate on the admitted data.
    catalog_incomplete: bool
    #: Whether the failing observation was reproduced (None: nothing failed / not tested).
    inadequacy_reproduced: bool | None
    #: Hypotheses the catalog expresses that are still adequate (distinct forward models).
    adequate_alternatives: tuple[str, ...]
    #: Distinct forward models (by fingerprint) the adequacy check held against the data.
    distinct_hypotheses_checked: int
    #: Distinct experiments the claim passed that could have separated it from the noise model
    #: or from a distinct registered rival (replicates and aliases add nothing).
    discriminating_tests_passed: int
    anomalies: tuple[str, ...]
    proposal: NewFamilyProposal | None
    requests: tuple[ExperimentRequest, ...]
    reframed_question: str | None
    spent_by_engine: int
    spent_on_probes: int
    #: Observations excluded as noise (by the engine's noise tests or a probe's replicate): every
    #: test above was run on the observations NOT listed here.
    excluded_as_noise: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def endorsed(self) -> bool:
        return self.decision is SafetyDecision.ENDORSE_PENDING_WARRANT_GATE


@dataclass(frozen=True)
class SafeRun:
    """The scored result (the engine's, extended by the probes and the decision), the engine's own
    result exactly as it ended, and the assessment between them."""

    result: DiscoveryResult
    engine: DiscoveryResult
    assessment: SafetyAssessment


__all__ = [
    "PROPOSAL_STAGE",
    "PROPOSAL_STATUS",
    "SAFETY",
    "AbstentionReason",
    "AdequacyTest",
    "ConfidenceLevel",
    "ExperimentRequest",
    "NewFamilyProposal",
    "ProbePurpose",
    "ProbeRecord",
    "RequestPurpose",
    "SafeRun",
    "SafetyAssessment",
    "SafetyDecision",
    "SafetyProtocol",
    "SignatureEntry",
]
