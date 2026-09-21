"""The scientific LLM boundary, both sides of it (LLM-001, §7.6, §17.14, §14.3).

§26's T-LLM-001 row is unusually explicit about what is NOT enough:

    Hypothesis/Critique/Relation 缺 model/prompt/bundle provenance 時 admission fail；**且既存於
    庫中而無 InferenceProvenance 的舊推論不得作為新 belief transition 的依據 -- 以該推論為唯一
    basis 的 transition 被拒絕，理由可追溯（§7.6）。僅測 admission 不足以通過。**

Two gates, and the second is the one that is easy to skip.

WRITE SIDE (`ScientificLLM.invoke`). Nothing reaches a model without a bundle, and nothing comes
back without provenance. The provenance is built HERE from the call's own inputs rather than
accepted from the model's reply -- a model asked to describe its own provenance is being asked to
be its own witness, and a hallucinated `prompt_version` is as easy to produce as a hallucinated
number.

READ SIDE (`BeliefBasisGate`). Inferences predating the rule are already in the store, and they
are exactly what §7.6 is about. A transition resting SOLELY on an inference with no provenance is
refused, with a reason a human can trace. "Solely" is the operative word and it is not a
convenience: §7.6 forbids such an inference being 依據, and a transition that also rests on a
measured attestation is not resting on the inference alone. Refusing that case too would make
legacy records unusable rather than untrustworthy, which is a different and unrequested policy.

NO LLM MUTATES EVIDENCE OR BELIEF. This module returns text and provenance. It writes no
Attestation, no BeliefRevisionEvent and no EvidenceUnit; those paths have their own gates
(EVI-003 refuses an inference typed as fact, §8.2.1 requires a TransitionPolicy). An LLM that
could write belief directly would make every other gate optional.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.base import utc_now
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.inference import InferenceProvenance, LogicalSlot


class LLMRefusalReason(StrEnum):
    """Machine-readable, for the same reason `RefusalReason` is."""

    NO_EVIDENCE_BUNDLE = "NO_EVIDENCE_BUNDLE"
    SLOT_NOT_CONFIGURED = "SLOT_NOT_CONFIGURED"
    PROMPT_VERSION_MISSING = "PROMPT_VERSION_MISSING"
    BUNDLE_HASH_MISMATCH = "BUNDLE_HASH_MISMATCH"
    #: §7.6 read side. A stored inference with no provenance is the sole basis of a transition.
    INFERENCE_WITHOUT_PROVENANCE = "INFERENCE_WITHOUT_PROVENANCE"
    #: §7.6. A critique that changed nothing about the route is not an independent critique.
    CRITIQUE_ROUTE_UNCHANGED = "CRITIQUE_ROUTE_UNCHANGED"


class LLMRefusal(Exception):
    """A scientific LLM call or a belief basis was refused."""

    def __init__(self, reason: LLMRefusalReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ModelSlot:
    """A configured model behind a logical slot (§7.3)."""

    logical_slot: LogicalSlot
    model_id: str
    model_version: str
    provider: str | None = None


@dataclass(frozen=True)
class PromptTemplate:
    """A versioned prompt. Versioned because §17.14 records the version, and a prompt that
    changed without its version changing makes every past inference unreproducible."""

    prompt_id: str
    prompt_version: str
    template: str


@dataclass(frozen=True)
class ScientificOutput:
    """What a scientific call returns: the text, and the provenance that makes it citable."""

    text: str
    provenance: InferenceProvenance

    @property
    def inference_id(self) -> str:
        return self.provenance.inference_id


#: The transport: (prompt text, slot) -> completion. Injected, so core imports no provider SDK
#: (§24.2, SRC-001's boundary applied to models).
Completion = Callable[[str, ModelSlot], str]


class ScientificLLM:
    """The only way a scientific LLM output is produced.

    A registry of slots rather than a model handle: §7.3's slots are logical and pluggable, and
    a class holding one model could not record *which* route a call used -- which §7.6's
    independent critique path needs.
    """

    def __init__(
        self,
        *,
        slots: Sequence[ModelSlot],
        prompts: Sequence[PromptTemplate],
        complete: Completion,
        source_policy_version: str | None = None,
    ) -> None:
        self._slots = {slot.logical_slot: slot for slot in slots}
        self._prompts = {p.prompt_id: p for p in prompts}
        self._complete = complete
        self._source_policy_version = source_policy_version

    @property
    def configured_slots(self) -> frozenset[LogicalSlot]:
        return frozenset(self._slots)

    def invoke(
        self,
        *,
        inference_id: str,
        slot: LogicalSlot,
        role: str,
        prompt_id: str,
        bundle: EvidenceBundle | None,
        trace_id: str,
        parameters: dict[str, object] | None = None,
        now: dt.datetime | None = None,
    ) -> ScientificOutput:
        """Make a scientific call. Refuses before spending anything if provenance is impossible.

        ORDER: bundle, slot, prompt -- then the call. Every refusal happens before the model is
        reached, because a call whose provenance cannot be recorded has produced an output that
        may not be used, and having spent budget on it is the only remaining consequence.
        """
        if bundle is None:
            raise LLMRefusal(
                LLMRefusalReason.NO_EVIDENCE_BUNDLE,
                f"inference {inference_id} has no EvidenceBundle. §17.14 requires the canonical "
                "bundle hash, and without it the same prompt over different retrieval context "
                "is indistinguishable -- two contradictory answers would look like one answer "
                "twice",
            )
        configured = self._slots.get(slot)
        if configured is None:
            raise LLMRefusal(
                LLMRefusalReason.SLOT_NOT_CONFIGURED,
                f"no model is configured for slot {slot.value}. §7.3's slots are pluggable and "
                "may be empty; a call into an empty one must refuse rather than silently route "
                "to another slot's model, which would make the recorded route a fiction",
            )
        prompt = self._prompts.get(prompt_id)
        if prompt is None:
            raise LLMRefusal(
                LLMRefusalReason.PROMPT_VERSION_MISSING,
                f"prompt {prompt_id} is not registered, so no prompt_version could be recorded "
                "and the inference would be unreproducible (§17.14)",
            )

        text = self._complete(prompt.template, configured)

        # Built from the CALL's inputs, never from the model's reply. A model asked to describe
        # its own provenance is being asked to be its own witness.
        provenance = InferenceProvenance(
            inference_id=inference_id,
            role=role,
            logical_slot=slot,
            provider=configured.provider,
            model_id=configured.model_id,
            model_version=configured.model_version,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.prompt_version,
            evidence_bundle_hash=bundle.canonical_hash,
            source_policy_version=self._source_policy_version,
            parameters=dict(parameters or {}),
            created_at=now or utc_now(),
            trace_id=trace_id,
        )
        return ScientificOutput(text=text, provenance=provenance)

    def critique(
        self,
        *,
        original: InferenceProvenance,
        inference_id: str,
        prompt_id: str,
        bundle: EvidenceBundle | None,
        trace_id: str,
        slot: LogicalSlot = LogicalSlot.CRITIQUE,
        now: dt.datetime | None = None,
    ) -> ScientificOutput:
        """§7.6's independent critique path.

        Refuses a critique whose route is identical to the original's. 不同 provider 不是科學
        獨立性的充分條件 -- the same prompt and model over the same bundle, run again, is the
        same inference a second time, and presenting it as independent corroboration is exactly
        the self-citation EVI-003 and §6.17 exist to prevent.
        """
        output = self.invoke(
            inference_id=inference_id,
            slot=slot,
            role="critic",
            prompt_id=prompt_id,
            bundle=bundle,
            trace_id=trace_id,
            now=now,
        )
        if not output.provenance.route_differs_from(original):
            raise LLMRefusal(
                LLMRefusalReason.CRITIQUE_ROUTE_UNCHANGED,
                f"critique {inference_id} used the same bundle, policy and model route as "
                f"{original.inference_id}. §7.6 requires at least one of retrieval bundle, "
                "reasoning policy or model route to change; running the same inference twice is "
                "not independent corroboration",
            )
        return output


@dataclass(frozen=True)
class BasisDecision:
    """Whether a set of basis references may support a belief transition."""

    permitted: bool
    reason_code: str
    detail: str


class BeliefBasisGate:
    """§7.6's read side: 無 provenance 的舊推論不可作為新 belief transition 的依據.

    THE GATE THE §26 ROW INSISTS ON. Records predating the rule are already stored, so a check
    that only ran at creation would never see them -- and they are precisely what the rule is
    about. This one reads the store.

    SOLE BASIS, not any basis. §7.6 forbids such an inference being *the* 依據. A transition that
    also rests on a measured attestation is not resting on the inference alone, and refusing that
    case would make legacy records unusable rather than untrustworthy -- a different policy, and
    not the one the spec states.
    """

    def __init__(
        self,
        *,
        load_provenance: Callable[[str], InferenceProvenance | None],
        is_inference: Callable[[str], bool],
    ) -> None:
        self._load_provenance = load_provenance
        #: Whether a basis reference names an inference at all. Separate from the loader because
        #: "not an inference" and "an inference with no provenance" are opposite answers, and a
        #: single `load -> None` would collapse them into the same one.
        self._is_inference = is_inference

    def evaluate(self, basis_refs: Sequence[str]) -> BasisDecision:
        if not basis_refs:
            return BasisDecision(
                permitted=False,
                reason_code="NO_BASIS",
                detail=(
                    "a belief transition with no basis has nothing to be traceable to (§8.2.1)"
                ),
            )

        unprovenanced = [
            ref
            for ref in basis_refs
            if self._is_inference(ref) and self._load_provenance(ref) is None
        ]
        if not unprovenanced:
            return BasisDecision(
                permitted=True,
                reason_code="BASIS_TRACEABLE",
                detail="every inference in the basis carries InferenceProvenance",
            )

        non_inference = [ref for ref in basis_refs if not self._is_inference(ref)]
        provenanced = [
            ref
            for ref in basis_refs
            if self._is_inference(ref) and self._load_provenance(ref) is not None
        ]
        if non_inference or provenanced:
            return BasisDecision(
                permitted=True,
                reason_code="BASIS_TRACEABLE_WITHOUT_LEGACY",
                detail=(
                    f"{sorted(unprovenanced)} carry no InferenceProvenance and are not the sole "
                    f"basis; the transition rests on {sorted(non_inference + provenanced)}"
                ),
            )

        return BasisDecision(
            permitted=False,
            reason_code=LLMRefusalReason.INFERENCE_WITHOUT_PROVENANCE.value,
            detail=(
                f"the transition rests solely on {sorted(unprovenanced)}, which carry no "
                "InferenceProvenance. §7.6: 無 provenance 的舊推論不可作為新 belief transition "
                "的依據 -- nothing records which model, prompt or evidence produced them, so "
                "the belief could not be replayed or contaminated-rolled-back (§6.18)"
            ),
        )

    def require(self, basis_refs: Sequence[str]) -> None:
        """Raise rather than return, for callers on the write path."""
        decision = self.evaluate(basis_refs)
        if not decision.permitted:
            raise LLMRefusal(LLMRefusalReason.INFERENCE_WITHOUT_PROVENANCE, decision.detail)


__all__ = [
    "BasisDecision",
    "BeliefBasisGate",
    "Completion",
    "LLMRefusal",
    "LLMRefusalReason",
    "ModelSlot",
    "PromptTemplate",
    "ScientificLLM",
    "ScientificOutput",
]
