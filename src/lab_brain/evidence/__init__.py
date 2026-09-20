"""Evidence layer — extraction, normalization, condition matching, retrieval.

Domain-agnostic like ``core``: this package defines *how* conditions are registered and
compared, never *what* a condition means. Comparison semantics arrive from a DomainPack
(§6.19, §24.1).
"""

from lab_brain.evidence.condition_schema_registry import (
    ConditionComparator,
    ConditionSchemaRegistry,
)
from lab_brain.evidence.independence import (
    DEPENDENT_RELATIONS,
    IndependenceCount,
    count_independent_attestations,
)
from lab_brain.evidence.retriever import (
    CandidateResolver,
    IndexDivergence,
    LexicalEvidenceIndex,
    ResolvedCandidate,
)

__all__ = [
    "DEPENDENT_RELATIONS",
    "CandidateResolver",
    "ConditionComparator",
    "ConditionSchemaRegistry",
    "IndependenceCount",
    "IndexDivergence",
    "LexicalEvidenceIndex",
    "ResolvedCandidate",
    "count_independent_attestations",
]
