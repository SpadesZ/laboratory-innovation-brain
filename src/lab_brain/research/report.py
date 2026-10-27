"""The episode report: one coherent, honest account of what a research episode did and found.

EVERY FIELD IS READ FROM AN AUTHORITATIVE RESULT OR A DURABLE ROW; NOTHING HERE DECIDES. The
orchestrator fills it from what the services returned (ingestion results, admitted attestations,
the debate outcome, the belief projections, the verification loop's plans and steps) and from the
rows they wrote. The only computed text is the conclusion's wording, which is a fixed template over
the belief states -- not a model, and never stronger than the states say.

WHAT DID NOT HAPPEN IS PART OF THE REPORT. `not_performed` lists what this episode did not do and
why -- no language model, no simulator, no network -- so a reader never has to infer an absence
from silence, and `pending` lists the verification actions that would decide the question but
cannot run here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageStatus:
    stage: str
    status: str  # DONE | SKIPPED | REFUSED | FAILED | PARTIAL
    detail: str


@dataclass(frozen=True)
class InputStatus:
    name: str
    role: str  # "document" | "verification input"
    declared_kind: str
    artifact_id: str | None
    state: str
    job_id: str | None = None
    run_id: str | None = None
    evidence_units: int = 0
    statements: int = 0
    detail: str = ""


@dataclass(frozen=True)
class EvidenceLine:
    attestation_id: str
    source: str
    locator: str
    trust_class: str
    excerpt: str
    origin: str  # "internal document" | "external literature"


@dataclass(frozen=True)
class LiteratureLine:
    title: str
    locator: str
    trust_class: str
    license: str
    retention: str
    status: str
    admitted_attestation_id: str | None
    note: str


@dataclass(frozen=True)
class LiteratureSection:
    provider: str
    description: str
    query: str
    egress_policy: str
    discovered: int
    consulted: tuple[LiteratureLine, ...]
    refusals: tuple[str, ...] = ()


@dataclass(frozen=True)
class HypothesisLine:
    hypothesis_id: str
    mechanism: str
    statement: str
    #: The author's prose falsifier: its explanation, not adjudicated.
    falsifier: str
    minimal_test: str
    predictions: tuple[str, ...]
    final_state: str
    objections: tuple[str, ...] = ()
    #: The designated typed falsifier(s), rendered: what verification adjudicates. Empty in a report
    #: stored before it was recorded.
    machine_falsifiers: tuple[str, ...] = ()
    #: PRE_OBSERVATION: proposed before its author was shown any check this episode observed.
    #: POST_SCREENING: proposed after its author was shown screening readings (`012y`) -- those
    #: readings can never support it; only a prospective, different check or a person can.
    origin: str = "PRE_OBSERVATION"


@dataclass(frozen=True)
class CoverageLine:
    """A low-cost executable check no Stage A hypothesis discriminated on, and what became of it."""

    observable: str
    check: str
    #: CERTIFIED (a new rival now predicts it) | DECLINED (with a reason) | REFUSED (a rival was
    #: proposed and the admission gate refused it) | UNADDRESSED (the review did not complete)
    disposition: str
    #: The certified mechanism, or the reason given, or why it stayed unaddressed.
    detail: str


@dataclass(frozen=True)
class ReliabilitySection:
    """How the debate's model replies were kept honest, from its durable record (`012x`)."""

    policy: str
    replies: int
    refused: int
    repaired: int
    #: NOT_NEEDED | DONE | FAILED | BUDGET_BLOCKED | DISABLED
    coverage_status: str
    coverage: tuple[CoverageLine, ...] = ()
    #: "role, attempt n: the parser's reason", for every refused reply.
    refusals: tuple[str, ...] = ()
    #: Optional calls and retries not made because they would have left the Critic short.
    withheld_for_critic: tuple[str, ...] = ()
    #: Admitted rivals making exactly the same discriminating claims (`cognition.overlap`): kept,
    #: never merged, and named so a reader can judge whether they are one mechanism.
    overlap: tuple[str, ...] = ()
    #: The digest of the device structure summary the Hypothesis Engine was shown, if any.
    structure_summary: str | None = None


@dataclass(frozen=True)
class ScreeningReadingLine:
    observable: str
    outcome: str
    #: The outcome the domain declares a sound design shows.
    reference: str
    #: NORMAL | ABNORMAL
    finding: str
    observation_id: str


@dataclass(frozen=True)
class ScreeningCheckLine:
    """One check a screening stage selected: what ran, what it read, and its provenance."""

    rank: int
    check: str
    #: EXECUTED | AWAITING_RESOURCE | BUDGET_BLOCKED | FAILED | NOT_RUN
    status: str
    estimated_cost: str
    readings: tuple[ScreeningReadingLine, ...] = ()
    job_id: str | None = None
    run_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class ScreeningCandidateLine:
    """A capability the screening stage considered, and why it did or did not take it."""

    check: str
    disposition: str
    detail: str


@dataclass(frozen=True)
class PostScreeningLine:
    """What the review after an abnormal reading did with it."""

    #: CERTIFIED (a new rival accounts for it) | DECLINED | REFUSED (admission refused the rival)
    disposition: str
    #: The readings answered, as "check: observable = outcome".
    readings: tuple[str, ...]
    hypothesis_id: str | None
    #: The certified mechanism, or the reason given, or why it was refused.
    detail: str
    grounding: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScreeningSection:
    """The exploratory screening stage (`012y`): an outcome-independent look where no hypothesis
    looked. Exploratory evidence: it moved no belief and supports nothing proposed after it."""

    policy: str
    #: DONE | FAILED | DISABLED
    status: str
    plan_id: str | None
    unaddressed: tuple[str, ...]
    candidates: tuple[ScreeningCandidateLine, ...]
    checks: tuple[ScreeningCheckLine, ...]
    #: NOT_NEEDED | DONE | FAILED | BUDGET_BLOCKED | RESERVED_FOR_CRITIC
    review_status: str
    review: tuple[PostScreeningLine, ...] = ()
    #: Screened checks verification did not run again on the same input.
    not_repeated: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class UsageLine:
    """What one model's calls in this run were metered at, as the PROVIDER reported it."""

    model: str
    slot: str
    calls: int
    #: Calls whose reply carried the provider's usage; the token sums cover exactly these.
    metered_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class DebateSection:
    debate_id: str
    reasoner: str
    rounds: int
    stop_reason: str
    positions: tuple[str, ...]
    critic_evidence: int
    inverted_evidence: int
    alternatives_named: tuple[str, ...]
    surviving: tuple[str, ...]
    contradicted: tuple[str, ...]
    gate: str
    #: `None` in a report of a debate recorded before `012x`.
    reliability: ReliabilitySection | None = None


@dataclass(frozen=True)
class BeliefLine:
    hypothesis_id: str
    mechanism: str
    state: str
    moves: tuple[str, ...]


@dataclass(frozen=True)
class PlanLine:
    plan_id: str
    decision: str
    chosen: str | None
    summary: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class ActionLine:
    capability_id: str
    action_type: str
    status: str
    job_id: str | None
    run_id: str | None
    backend: str
    outcomes: tuple[str, ...]
    output_artifacts: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class PendingAction:
    capability_id: str
    action_type: str
    best_next: bool
    would_decide: tuple[str, ...]
    estimated_cost: str
    blocked_because: str
    requires: str


@dataclass(frozen=True)
class Conclusion:
    status: str  # CONFIRMED | PROVISIONAL | INCONCLUSIVE | NOT_REACHED
    statement: str
    confirmed_hypothesis: str | None = None
    ruled_out: tuple[str, ...] = ()
    still_competing: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContinuationSection:
    """A continued episode: which run of it this is, what it resumed from and over which reasoning,
    and what earlier runs already did -- so a reader never mistakes a continuation for a fresh
    episode, or a check an earlier run executed for one this run skipped."""

    run_ordinal: int
    resumed_from: str
    reasoning: str
    earlier_runs: tuple[str, ...]
    earlier_checks: tuple[str, ...]
    superseded_jobs: tuple[str, ...] = ()
    recovered: tuple[str, ...] = ()


@dataclass(frozen=True)
class EpisodeReport:
    episode_id: str
    project_id: str
    actor_id: str
    trace_id: str
    goal: str
    domain: str
    started_at: dt.datetime
    finished_at: dt.datetime
    episode_state: str
    stages: tuple[StageStatus, ...]
    inputs: tuple[InputStatus, ...]
    verification_input: str | None
    evidence: tuple[EvidenceLine, ...]
    literature: LiteratureSection | None
    hypotheses: tuple[HypothesisLine, ...]
    debate: DebateSection | None
    belief: tuple[BeliefLine, ...]
    plans: tuple[PlanLine, ...]
    completed: tuple[ActionLine, ...]
    pending: tuple[PendingAction, ...]
    human_actions: tuple[str, ...]
    conclusion: Conclusion
    failure_analysis: str | None
    heuristic_candidates: tuple[str, ...]
    next_steps: tuple[str, ...]
    provenance: tuple[str, ...]
    deployment: tuple[str, ...]
    not_performed: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Set when this run CONTINUED an episode (`research.continuation`); `None` for an opening run.
    continuation: ContinuationSection | None = None
    #: This run's model calls by model, with the provider-reported token counts (`execution_spans`).
    #: Empty when the run called no model or the report predates it.
    usage: tuple[UsageLine, ...] = ()
    #: The exploratory screening stage, when this run's debate had one. `None` otherwise, and in a
    #: report stored before screening existed.
    screening: ScreeningSection | None = None


__all__ = [
    "ActionLine",
    "BeliefLine",
    "Conclusion",
    "ContinuationSection",
    "CoverageLine",
    "DebateSection",
    "EpisodeReport",
    "EvidenceLine",
    "HypothesisLine",
    "InputStatus",
    "LiteratureLine",
    "LiteratureSection",
    "PendingAction",
    "PlanLine",
    "PostScreeningLine",
    "ReliabilitySection",
    "ScreeningCandidateLine",
    "ScreeningCheckLine",
    "ScreeningReadingLine",
    "ScreeningSection",
    "StageStatus",
    "UsageLine",
]
