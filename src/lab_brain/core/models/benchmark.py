"""§17.19.2's BenchmarkPolicy and DisagreementMetric (LLM-002, VER-008).

    §15.4    門檻由校準產生（LLM-002）：hard gates 必須引用版本化的 BenchmarkPolicy，且校準證據
             可追溯。校準前不得任意 hard-code 門檻數字。
    §9.1     Disagreement metrics ... MUST be deterministic, versioned and defined over the
             declared OutcomeSpace. Core does not hard-code one universal distance.

A THRESHOLD IS A MEASUREMENT, NOT A PREFERENCE. The rule this module exists for is that no number a
gate enforces may be typed by a person: it is produced by running a fixed benchmark and read off the
result, and the policy records where it came from -- `benchmark_set_id`, `sample_size`,
`calibration_artifact_refs`, `calibrated_at`. A policy missing any of them is not "a policy with
defaults"; it cannot be constructed. So "no hard gate before calibration" holds by type: a gate can
only be armed with a `BenchmarkPolicy`, and a `BenchmarkPolicy` is by construction a calibrated one.

A DISAGREEMENT METRIC IS A DECLARATION, AND CORE SHIPS NONE. The object here names a metric and
binds it to one declared OutcomeSpace version; the implementation lives in a DomainPack and is
resolved by `lab_brain.verification.disagreement.DisagreementMetricRegistry`, which tabulates it
over the declared outcomes at registration. ``deterministic`` is typed `Literal[True]`: §17.19.2
writes `deterministic:true` as part of the schema, and a declaration that could say `False` would
be a declaration of a metric the ranking must not use.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel


class MetricDirection(StrEnum):
    """Which side of the threshold passes. §17.19.2's `direction?`."""

    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


class BenchmarkPolicy(CoreModel):
    """§17.19.2, field for field. Every field is what makes a threshold traceable to a benchmark.

    ``direction`` is optional because §17.19.2 marks it so -- a policy can record a calibrated
    distribution before anyone decides which side is good. A gate cannot be armed with such a policy
    (`lab_brain.cognition.debate_metrics.DebateGate` refuses), because a threshold with no side is a
    number with no meaning.
    """

    policy_id: str
    domain: str
    benchmark_set_id: str
    metric_key: str
    threshold: Decimal
    direction: MetricDirection | None = None
    calibrated_at: dt.datetime
    sample_size: int = Field(ge=1)
    calibration_artifact_refs: tuple[str, ...] = Field(min_length=1)
    version: str
    active: bool = False

    @model_validator(mode="after")
    def _a_threshold_says_where_it_came_from(self) -> Self:
        for name in ("policy_id", "domain", "benchmark_set_id", "metric_key", "version"):
            if not getattr(self, name).strip():
                raise ValueError(
                    f"benchmark policy {self.policy_id!r} has a blank {name}. LLM-002: a hard gate "
                    "must reference a versioned BenchmarkPolicy whose calibration evidence is "
                    "traceable, and a blank identity is traceable to nothing"
                )
        if any(not ref.strip() for ref in self.calibration_artifact_refs):
            raise ValueError(
                f"benchmark policy {self.policy_id}@{self.version} lists a blank calibration "
                "artifact reference; §15.4 requires the calibration evidence to be traceable"
            )
        if len(set(self.calibration_artifact_refs)) != len(self.calibration_artifact_refs):
            raise ValueError(
                f"benchmark policy {self.policy_id}@{self.version} cites a calibration artifact "
                "twice, which inflates how much evidence the threshold appears to rest on"
            )
        if not self.threshold.is_finite():
            raise ValueError(f"benchmark policy {self.policy_id} has a non-finite threshold")
        return self

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"

    def passes(self, value: Decimal) -> bool:
        """Whether ``value`` is on the passing side. Refuses a policy with no declared side."""
        if self.direction is None:
            raise ValueError(
                f"benchmark policy {self.ref} records a calibrated threshold for {self.metric_key} "
                "but no direction; a gate cannot decide which side of a threshold passes when the "
                "policy does not say"
            )
        if self.direction is MetricDirection.AT_LEAST:
            return value >= self.threshold
        return value <= self.threshold


class DisagreementMetric(CoreModel):
    """§17.19.2's DisagreementMetric declaration (VER-008).

    ``outcome_space_version`` is not in §17.19.2's block, and it is here for VER-004's reason: a
    metric defined over one version of an OutcomeSpace is undefined on outcomes a later version
    added, so binding by id alone would let a ranking apply a metric to outcomes it was never
    defined on. `schema_drift.UNBOUND` records the difference.
    """

    metric_id: str
    outcome_space_id: str
    outcome_space_version: str
    #: Where the domain implementation lives, for audit. Resolved by the registry, never imported
    #: by core.
    implementation_ref: str
    version: str
    deterministic: Literal[True] = True

    @model_validator(mode="after")
    def _a_metric_is_named_and_versioned(self) -> Self:
        for name in (
            "metric_id",
            "outcome_space_id",
            "outcome_space_version",
            "implementation_ref",
            "version",
        ):
            if not getattr(self, name).strip():
                raise ValueError(
                    f"disagreement metric {self.metric_id!r} has a blank {name}. VER-008: a metric "
                    "used for ranking MUST be bound to a declared OutcomeSpace and MUST carry a "
                    "version"
                )
        return self

    @property
    def ref(self) -> str:
        return f"{self.metric_id}@{self.version}"

    @property
    def outcome_space_ref(self) -> str:
        return f"{self.outcome_space_id}@{self.outcome_space_version}"


__all__ = ["BenchmarkPolicy", "DisagreementMetric", "MetricDirection"]
