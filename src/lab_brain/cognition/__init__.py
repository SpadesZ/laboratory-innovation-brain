"""Scientific reasoning boundaries (LLM-001).

The one rule this package exists to hold: an LLM produces text and provenance, and writes
nothing. No Attestation, no BeliefRevisionEvent, no EvidenceUnit. Those paths have their own
gates -- EVI-003 refuses an inference typed as fact, §8.2.1 requires a TransitionPolicy -- and a
model that could write belief directly would make every one of them optional.
"""

from lab_brain.cognition.llm import (
    BasisDecision,
    BeliefBasisGate,
    LLMRefusal,
    LLMRefusalReason,
    ModelSlot,
    PromptTemplate,
    ScientificLLM,
    ScientificOutput,
)

__all__ = [
    "BasisDecision",
    "BeliefBasisGate",
    "LLMRefusal",
    "LLMRefusalReason",
    "ModelSlot",
    "PromptTemplate",
    "ScientificLLM",
    "ScientificOutput",
]
