"""Observation — an internal backend fact, wired straight to its Run or Artifact (§17.2).

Per §17.2.1 an Observation does **not** need a self-Attestation to exist. Requiring one would
conflate the measurement with a document reporting it, and then "how many sources back this"
would count the lab's own instrument as an external witness.

When an internal result is later written up, that produces a SourceWork plus an Attestation
describing *how the document reports it* — which is a different object with a different
epistemic type.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.condition import ConditionSchemaRef
from lab_brain.core.models.identifiers import new_id


class Observation(CoreModel):
    """A value or event produced by an internal backend."""

    observation_id: str = Field(default_factory=lambda: new_id("observation"))

    #: Exactly one origin. An Observation with neither cannot be reproduced; with both, it is
    #: ambiguous which one to replay.
    run_id: str | None = None
    artifact_id: str | None = None

    #: What was measured or computed. A domain-owned key; core does not interpret it.
    metric_or_event: str

    #: Pointer to the numerical payload (parquet/raw), not the payload itself. Large arrays do
    #: not belong in the entity store (§6.12).
    value_ref: str | None = None
    #: Small scalar results may be carried inline; anything array-shaped uses `value_ref`.
    value: float | int | str | bool | None = None
    unit: str | None = None

    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str
    #: How the value was obtained -- extractor identity and version. Without it a number cannot
    #: be recomputed, and DOM-SP-002's shared-extractor guarantee is unverifiable.
    method_ref: str

    project_id: str
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _exactly_one_origin(self) -> Self:
        origins = [self.run_id, self.artifact_id]
        provided = [origin for origin in origins if origin is not None]
        if len(provided) != 1:
            raise ValueError(
                "Observation requires exactly one of run_id or artifact_id; "
                f"got run_id={self.run_id!r}, artifact_id={self.artifact_id!r}"
            )
        return self

    @model_validator(mode="after")
    def _condition_schema_ref_is_wellformed(self) -> Self:
        # Parsed eagerly so a malformed reference is rejected at the boundary rather than
        # surfacing later as an unresolvable schema during comparison (EVI-005).
        ConditionSchemaRef.parse(self.conditions_schema_version)
        return self

    @property
    def schema_ref(self) -> ConditionSchemaRef:
        return ConditionSchemaRef.parse(self.conditions_schema_version)

    @property
    def origin_id(self) -> str:
        origin = self.run_id or self.artifact_id
        assert origin is not None  # guaranteed by _exactly_one_origin
        return origin


__all__ = ["Observation"]
