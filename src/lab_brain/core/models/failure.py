"""§17.6's FailureAnalysis and §17.11's CandidateHeuristic (EPI-002, VS-SP-001).

    §17.6   FailureAnalysis { failure_analysis_id, episode_id, symptom, expected_behavior,
            observed_behavior, candidate_causes[], confirmed_root_cause?, root_cause_evidence_ids[],
            failure_class, fix?, prevention_rule?, resolution_status }
    §17.11  CandidateHeuristic { candidate_id, trigger_pattern, suggested_checks[], rationale,
            source_artifact_ids[], source_locators[], source_episode_ids[], miner_model_version,
            status=PENDING_REVIEW, proposed_scope{}, conflicts_with_existing_rules[] }
    EPI-002 confirmed root cause 必須可以 trace 回 Run/Evidence/Artifact；
            LLM statement 不可作為證據。
    §6.11   Heuristic Miner 的輸出不是直接入庫的 active rule，而是 CandidateHeuristic ... 等待人類
            approval（P16）。

A CONFIRMED CAUSE NAMES ITS EVIDENCE, AND THE MODEL REFUSES ONE THAT DOES NOT.
`confirmed_root_cause` and `resolution_status = CONFIRMED` travel together, and a confirmed analysis
must list at least one `root_cause_evidence_ids` entry -- the attestations `core.root_cause` traced
to a Run and an Artifact. Whether those ids really trace is checked by `confirm_root_cause` and
again by `011l` for any writer of SQL; what the model can check alone, it checks.

A CANDIDATE IS NEVER A RULE. `status` is `PENDING_REVIEW` and cannot be anything else here: approval
is HEU-001's governance (M7), and a candidate this module could mark active would be a rule nobody
approved.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now


class ResolutionStatus(StrEnum):
    #: The loop is still running, or stopped for a reason a person must act on.
    OPEN = "OPEN"
    #: A root cause was confirmed with a traced evidence chain (EPI-002).
    CONFIRMED = "CONFIRMED"
    #: The loop stopped without a confirmable cause: no sufficient action, or none it could run.
    INCONCLUSIVE = "INCONCLUSIVE"


class FailureAnalysis(CoreModel):
    """§17.6, plus `project_id` (SEC-002 scope) and `created_at`."""

    failure_analysis_id: str
    project_id: str
    episode_id: str
    symptom: str
    expected_behavior: str
    observed_behavior: str
    candidate_causes: tuple[str, ...] = Field(min_length=1)
    confirmed_root_cause: str | None = None
    root_cause_evidence_ids: tuple[str, ...] = ()
    failure_class: str
    fix: str | None = None
    prevention_rule: str | None = None
    resolution_status: ResolutionStatus
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_confirmed_cause_names_its_evidence(self) -> Self:
        for name in ("symptom", "expected_behavior", "observed_behavior", "failure_class"):
            if not getattr(self, name).strip():
                raise ValueError(f"failure analysis {self.failure_analysis_id} has a blank {name}")
        if len(set(self.candidate_causes)) != len(self.candidate_causes):
            raise ValueError(f"failure analysis {self.failure_analysis_id} lists a cause twice")
        confirmed = self.resolution_status is ResolutionStatus.CONFIRMED
        if confirmed != (self.confirmed_root_cause is not None):
            raise ValueError(
                f"failure analysis {self.failure_analysis_id} is {self.resolution_status.value} "
                f"with confirmed_root_cause={self.confirmed_root_cause!r}; a cause is confirmed "
                "exactly when the analysis says so"
            )
        if self.confirmed_root_cause is not None:
            if self.confirmed_root_cause not in self.candidate_causes:
                raise ValueError(
                    f"failure analysis {self.failure_analysis_id} confirms "
                    f"{self.confirmed_root_cause}, which was never a candidate cause"
                )
            if not self.root_cause_evidence_ids:
                raise ValueError(
                    f"failure analysis {self.failure_analysis_id} confirms a root cause and names "
                    "no evidence. EPI-002: a confirmed root cause MUST trace to Run / Evidence / "
                    "Artifact"
                )
        elif self.root_cause_evidence_ids:
            raise ValueError(
                f"failure analysis {self.failure_analysis_id} names root-cause evidence for a "
                "cause it does not confirm"
            )
        return self


class CandidateHeuristic(CoreModel):
    """§17.11, plus `project_id`, the failures it was mined from, and `created_at`."""

    candidate_id: str
    project_id: str
    trigger_pattern: str
    suggested_checks: tuple[str, ...] = Field(min_length=1)
    rationale: str
    #: HEU-001: MUST 保存 source_artifact_ids 與 source_locators -- a candidate that could not say
    #: where it came from could not be reviewed.
    source_artifact_ids: tuple[str, ...] = Field(min_length=1)
    source_locators: tuple[str, ...] = Field(min_length=1)
    source_episode_ids: tuple[str, ...] = Field(min_length=1)
    miner_model_version: str
    status: Literal["PENDING_REVIEW"] = "PENDING_REVIEW"
    proposed_scope: dict[str, Any] = Field(default_factory=dict)
    conflicts_with_existing_rules: tuple[str, ...] = ()
    #: The confirmed FailureAnalyses this candidate generalises (§17.7's `derived_from_failures`).
    derived_from_failures: tuple[str, ...] = Field(min_length=1)
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_candidate_cites_where_it_came_from(self) -> Self:
        for name in ("trigger_pattern", "rationale", "miner_model_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"candidate heuristic {self.candidate_id} has a blank {name}")
        return self


__all__ = [
    "CandidateHeuristic",
    "FailureAnalysis",
    "ResolutionStatus",
]
