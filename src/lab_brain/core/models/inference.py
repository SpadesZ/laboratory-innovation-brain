"""InferenceProvenance — what every LLM output must carry (LLM-001, §17.14, §7.6).

§17.14 in one line: 所有 LLM 生成/判斷物件必填. And the sentence that explains why the bundle hash
is in the list: *evidence bundle hash 讓同一 prompt/model 但不同 retrieval context 可區分*.

That is the field people leave out. Model, version and prompt id feel like the provenance; they
are not sufficient. The same prompt and the same model over a *different* retrieval context
produce a different answer, and without the bundle hash two contradictory inferences look like
the same inference twice. EVI-006 already makes bundles reproducible; this is what binds an
output to one.

THE READ-SIDE OBLIGATION IS THE HARD HALF. §7.6: 無 provenance 的舊推論不可作為新 belief
transition 的依據. §26's T-LLM-001 row is explicit that admission-only testing is insufficient --
既存於庫中而無 InferenceProvenance 的舊推論不得作為新 belief transition 的依據. So the check
cannot live only where inferences are created: records predating the rule are already in the
store, and they are exactly what the rule is about. `lab_brain.cognition.llm` holds that gate.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now


class LogicalSlot(StrEnum):
    """§7.3's six pluggable model slots plus the embedding slot.

    Logical, not physical: §7.3's heading says so outright -- 6 個可拔 model slots + 1 embedding
    slot（不是 6 顆必備模型）. One model may serve several slots. What the slot records is which
    *role* the call was made in, because §7.6's independent critique path requires changing the
    route, and a record that did not say which route was used could not show that it changed.
    """

    HYPOTHESIS = "HYPOTHESIS"
    CRITIQUE = "CRITIQUE"
    EXTRACTION = "EXTRACTION"
    PLANNING = "PLANNING"
    SUMMARISATION = "SUMMARISATION"
    RELATION = "RELATION"
    EMBEDDING = "EMBEDDING"

    # §7.3's own slot names (M3, migration `003e`). The seven values above were recorded before
    # routing existed and name the FUNCTION a call served; §7.3 names the ROUTE -- which pluggable
    # model a role is sent to -- and M3's roles are routed by it (`lab_brain.cognition.routing`).
    # `003d`'s CHECK accepted only the values above, so §7.3's slots were unrecordable in the
    # field §17.14 defines for them. The fix is additive: M1's records keep their values and stay
    # readable; nothing that wrote one of them changes.
    REASONING_PRIMARY = "REASONING_PRIMARY"
    REASONING_ADVERSARIAL = "REASONING_ADVERSARIAL"
    FAST_UTILITY = "FAST_UTILITY"
    CODE = "CODE"
    PRIVATE_LOCAL = "PRIVATE_LOCAL"
    VISION = "VISION"


class InferenceProvenance(CoreModel):
    """§17.14, field for field.

    EVERY FIELD IS REQUIRED EXCEPT THE THREE §17.14 MARKS OPTIONAL. That is not defensive
    modelling -- an inference whose provenance is half filled in is indistinguishable at read
    time from one that was never checked, and §7.6's rule keys on presence.

    ``evidence_bundle_hash`` is a plain string rather than a reference to a loaded bundle: the
    bundle is EVI-006's object and may be large, while what provenance needs is the identity.
    Storing the hash means an inference can be checked against a bundle without loading it, and
    a bundle that no longer reconstructs to its hash is detectable.
    """

    inference_id: str
    role: str
    logical_slot: LogicalSlot
    provider: str | None = None
    model_id: str
    model_version: str
    prompt_id: str
    prompt_version: str
    #: §17.14.1's canonical bundle hash. The field that distinguishes two runs of one prompt.
    evidence_bundle_hash: str
    source_policy_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime = Field(default_factory=utc_now)
    trace_id: str

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        for name in ("model_id", "model_version", "prompt_id", "prompt_version", "trace_id"):
            if not getattr(self, name).strip():
                raise ValueError(
                    f"inference {self.inference_id} has a blank {name}. §17.14 requires every "
                    "LLM output to record it, and a blank field is indistinguishable at read "
                    "time from a record that was never checked"
                )
        if not self.evidence_bundle_hash.strip():
            raise ValueError(
                f"inference {self.inference_id} records no evidence_bundle_hash. §17.14: the "
                "bundle hash is what lets the same prompt and model over different retrieval "
                "context be told apart -- without it two contradictory inferences look like the "
                "same inference twice"
            )
        return self

    @property
    def model_ref(self) -> str:
        return f"{self.model_id}@{self.model_version}"

    @property
    def prompt_ref(self) -> str:
        return f"{self.prompt_id}@{self.prompt_version}"

    def route_differs_from(self, other: InferenceProvenance) -> bool:
        """§7.6's independence test: did the bundle, the policy or the model route change?

        Three ways to differ, any one of which suffices -- 至少改變 retrieval bundle、reasoning
        policy 或 model route. Provider is deliberately NOT one of them on its own: §7.6 opens by
        saying 不同 provider 不是科學獨立性的充分條件, so two providers running the same prompt
        over the same bundle are not an independent critique.
        """
        return (
            self.evidence_bundle_hash != other.evidence_bundle_hash
            or self.source_policy_version != other.source_policy_version
            or self.model_ref != other.model_ref
            or self.logical_slot is not other.logical_slot
        )


__all__ = ["InferenceProvenance", "LogicalSlot"]
