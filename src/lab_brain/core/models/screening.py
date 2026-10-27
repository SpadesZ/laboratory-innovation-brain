"""Exploratory screening: a governed, outcome-independent look where no hypothesis is looking.

THE FAILURE IT ANSWERS. A real model proposed five well-formed rivals for a device whose cathode via
never reached metal; asked about the one cheap check none of them predicted, it declined,
correctly, because the evidence did not point there. Verification plans only over what hypotheses
predict (§9.1: "Absence of a declared prediction is not evidence of discriminative power"), so a
seconds-long design inspection that would have shown the fault was never run.

WHY THIS IS NOT A VERIFICATION ACTION. VER-001 makes every verification action carry a predicted
discriminatory outcome, and §9.1 makes an action no hypothesis predicts NOT sufficient. A screening
check has no prediction by definition, so it can never be a VerificationPlan's chosen action and is
never recorded as one (`011k` would refuse it, rightly). It is a different operation with a
different claim: "this low-cost reading was taken because nobody was looking there", never "this
check discriminates between rivals". `docs/spec_issues/SPEC-ISSUE-016-exploratory-screening.md`
records the boundary and the decision it needs.

WHAT A SCREENING RESULT MAY DO, AND WHAT IT MAY NOT.

    may     be on record as an Observation and an Attestation traced to its Run and Artifact,
            normal or abnormal alike (nothing is discarded)
    may     stop a confirmation: the confirmation rule reads every outcome the episode observed,
            so a declared signature of another mechanism blocks a candidate (`ConfirmationRule`)
    may     open a new hypothesis-generation cycle when the outcome differs from the domain's
            declared reference outcome (an ABNORMAL finding)
    may not SUPPORT, CONFIRM or upgrade anything. It instantiates no relation at all, and a
            hypothesis proposed after viewing it is recorded as conditioned on it: SQL refuses any
            SUPPORTS relation to that hypothesis from the screened observation, from an
            observation made before the hypothesis existed, or from a repeat of the same
            deterministic reading on the same input (`012y`)

Every record here is append-only and project-scoped; the tables in `012y` are the durable half.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.capability import ActionType
from lab_brain.core.models.cost import CostVector

#: The action tiers a screening check may come from: readings of what is already there. A
#: simulation, a measurement, a fabrication or a person's review is never run to "just look".
SCREENING_ACTION_TYPES: frozenset[ActionType] = frozenset(
    {
        ActionType.EXISTING_EVIDENCE_LOOKUP,
        ActionType.ANALYTICAL_RULE_CHECK,
        ActionType.HISTORICAL_CASE_COMPARISON,
    }
)


def inputs_key(capability_id: str, input_artifacts: Sequence[str]) -> str:
    """One identity for "this check on these inputs": what `ALREADY_SCREENED` deduplicates on."""
    return canonical_hash([capability_id, sorted(input_artifacts)])


class ScreeningPolicy(CoreModel):
    """The declared, versioned bounds of one screening stage. Every number is fixed in advance.

    `max_checks` and `max_wall_clock_s` bound how much is run; the per-check cost rules bound what
    may be run at all. Nothing here is tuned per device or per case: the same policy screens every
    episode it is configured for.
    """

    policy_id: str
    version: str
    #: At most this many checks per screening stage, whatever else is eligible.
    max_checks: int = Field(ge=1, le=5)
    #: The sum of the selected checks' ESTIMATED wall-clock seconds may not exceed this.
    max_wall_clock_s: int = Field(ge=1)
    #: A per-check ceiling: a check estimated above it is ineligible.
    max_check_wall_clock_s: int = Field(ge=1)
    #: Stop executing further checks once one has failed, been budget-blocked or found no seat.
    stop_on_failure: bool = True

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if self.max_check_wall_clock_s > self.max_wall_clock_s:
            raise ValueError(
                f"screening policy {self.ref} allows one check {self.max_check_wall_clock_s}s but "
                f"the whole stage only {self.max_wall_clock_s}s; the per-check ceiling is the "
                "smaller bound"
            )
        return self


class ScreeningNorm(CoreModel):
    """A DomainPack's declaration that one capability may be used for screening, and what a normal
    reading of each observable it produces looks like.

    The reference outcome is domain knowledge about every device -- a design rule check that
    passes -- never a fact about a particular device or case. A capability with no declaration is
    never screened: its result could not be read as normal or abnormal.
    """

    capability_id: str
    #: observable -> the outcome a sound design shows there (one of its OutcomeSpace's outcomes).
    reference_outcomes: dict[str, str]
    #: The domain's one-line reason this reading is worth taking when nobody predicts it.
    purpose: str
    #: The pack's statement that executing it reaches nothing outside this machine. Checked again
    #: against the Run's recorded environment after execution.
    execution: str = "LOCAL_NO_EGRESS"

    @model_validator(mode="after")
    def _declared(self) -> Self:
        if not self.reference_outcomes:
            raise ValueError(f"screening norm for {self.capability_id} declares no observable")
        if self.execution != "LOCAL_NO_EGRESS":
            raise ValueError(
                f"screening norm for {self.capability_id} declares execution {self.execution!r}; "
                "only a local reading that sends nothing out may be screened"
            )
        return self


class CandidateDisposition(StrEnum):
    """Why a capability was or was not selected. Every considered capability gets exactly one."""

    SELECTED = "SELECTED"
    #: Some admitted hypothesis already makes a SUPPORTS/CONTRADICTS prediction over every
    #: observable it produces: verification, not screening, will decide whether to run it.
    ADDRESSED_BY_HYPOTHESIS = "ADDRESSED_BY_HYPOTHESIS"
    NOT_DECLARED_FOR_SCREENING = "NOT_DECLARED_FOR_SCREENING"
    ACTION_TYPE_NOT_SCREENABLE = "ACTION_TYPE_NOT_SCREENABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NO_WORKFLOW = "NO_WORKFLOW"
    INPUT_MISSING = "INPUT_MISSING"
    LICENSED = "LICENSED"
    IRREVERSIBLE = "IRREVERSIBLE"
    NEEDS_PERSON_OR_MONEY = "NEEDS_PERSON_OR_MONEY"
    PRIVACY_CONSTRAINED = "PRIVACY_CONSTRAINED"
    OVER_CHECK_CEILING = "OVER_CHECK_CEILING"
    #: The same reading of the same input was already taken in this episode.
    ALREADY_SCREENED = "ALREADY_SCREENED"
    OVER_STAGE_BUDGET = "OVER_STAGE_BUDGET"
    OVER_MAX_CHECKS = "OVER_MAX_CHECKS"


class ScreeningCandidate(CoreModel):
    capability_id: str
    action_type: ActionType
    observables: tuple[str, ...]
    estimated_cost: CostVector
    disposition: CandidateDisposition
    #: For a SELECTED candidate: its execution order, from 1.
    rank: int | None = None
    detail: str = ""


class ScreeningPlan(CoreModel):
    """Which low-cost readings a screening stage takes, and the full argument for that choice.

    Like a VerificationPlan it records every candidate considered and why each was or was not
    taken; unlike one it claims no sufficiency and names no hypothesis it would decide.
    """

    plan_id: str
    project_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    hypothesis_set_id: str
    policy_id: str
    policy_version: str
    #: The hypotheses whose predictions defined "where nobody is looking", as of this plan.
    considered_hypothesis_ids: tuple[str, ...]
    #: Every observable no admitted hypothesis discriminates on, as of this plan.
    unaddressed_observables: tuple[str, ...]
    input_artifacts: tuple[str, ...]
    candidates: tuple[ScreeningCandidate, ...]
    created_at: dt.datetime

    @property
    def selected(self) -> tuple[ScreeningCandidate, ...]:
        return tuple(
            sorted(
                (c for c in self.candidates if c.disposition is CandidateDisposition.SELECTED),
                key=lambda c: c.rank or 0,
            )
        )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [c.capability_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError(f"screening plan {self.plan_id} lists a capability twice")
        ranks = [c.rank for c in self.selected]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(
                f"screening plan {self.plan_id}'s selected checks are ranked {ranks}, not 1..n"
            )
        for c in self.candidates:
            if (c.disposition is CandidateDisposition.SELECTED) != (c.rank is not None):
                raise ValueError(
                    f"screening plan {self.plan_id}: {c.capability_id} has a rank only if selected"
                )
        return self


class ScreeningStatus(StrEnum):
    EXECUTED = "EXECUTED"
    AWAITING_RESOURCE = "AWAITING_RESOURCE"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"
    FAILED = "FAILED"
    #: Selected, then not run because the stage stopped first (a failure before it).
    NOT_RUN = "NOT_RUN"


class ScreeningFinding(StrEnum):
    #: The observed outcome is the domain's declared reference outcome.
    NORMAL = "NORMAL"
    #: The observed outcome differs from the declared reference outcome.
    ABNORMAL = "ABNORMAL"


class ScreeningObservation(CoreModel):
    """One screening check's result: the reading, its provenance, and how it compares with the
    domain's reference. Exploratory evidence; it relates to no hypothesis."""

    screening_observation_id: str
    plan_id: str
    project_id: str
    episode_id: str
    rank: int
    capability_id: str
    status: ScreeningStatus
    job_id: str | None = None
    run_id: str | None = None
    #: One per observable the check produced; empty unless EXECUTED.
    readings: tuple[ScreeningReading, ...] = ()
    estimated_cost: CostVector
    #: `core.warrant.evidence_line` of the Run: a repeat of the same reading has the same line.
    evidence_line: str | None = None
    detail: str = ""
    recorded_at: dt.datetime

    @property
    def abnormal(self) -> tuple[ScreeningReading, ...]:
        return tuple(r for r in self.readings if r.finding is ScreeningFinding.ABNORMAL)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        executed = self.status is ScreeningStatus.EXECUTED
        if executed and (self.run_id is None or not self.readings or self.evidence_line is None):
            raise ValueError(
                f"screening observation {self.screening_observation_id} is EXECUTED without a "
                "Run, a reading and its evidence line"
            )
        if not executed and self.readings:
            raise ValueError(
                f"screening observation {self.screening_observation_id} is {self.status.value} "
                "and reports readings; nothing executed, so nothing was observed"
            )
        return self


class ScreeningReading(CoreModel):
    observable_ref: str
    outcome_space_id: str
    outcome_space_version: str
    outcome: str
    reference_outcome: str
    finding: ScreeningFinding
    observation_id: str
    attestation_id: str
    method_ref: str
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _finding_follows(self) -> Self:
        expected = (
            ScreeningFinding.NORMAL
            if self.outcome == self.reference_outcome
            else ScreeningFinding.ABNORMAL
        )
        if self.finding is not expected:
            raise ValueError(
                f"reading of {self.observable_ref}: outcome {self.outcome} against reference "
                f"{self.reference_outcome} is {expected.value}, not {self.finding.value}"
            )
        return self


ScreeningObservation.model_rebuild()


class ConditionedHypothesis(CoreModel):
    """A hypothesis proposed AFTER its author was shown screening observations.

    Its provenance, for every later reader: which observations it was conditioned on. Those
    observations cannot support it, and nothing it later gains from a repeat of the same reading
    of the same input counts either (`012y`).
    """

    hypothesis_id: str
    project_id: str
    episode_id: str
    plan_id: str
    screening_observation_ids: tuple[str, ...] = Field(min_length=1)
    #: The model call that proposed it, having been shown those observations.
    inference_id: str
    recorded_at: dt.datetime


__all__ = [
    "SCREENING_ACTION_TYPES",
    "CandidateDisposition",
    "ConditionedHypothesis",
    "ScreeningCandidate",
    "ScreeningFinding",
    "ScreeningNorm",
    "ScreeningObservation",
    "ScreeningPlan",
    "ScreeningPolicy",
    "ScreeningReading",
    "ScreeningStatus",
    "inputs_key",
]
