"""Evidence layer — extraction, normalization, condition matching, retrieval.

Domain-agnostic like ``core``: this package defines *how* conditions are registered and
compared, never *what* a condition means. Comparison semantics arrive from a DomainPack
(§6.19, §24.1).
"""

from lab_brain.evidence.condition_schema_registry import (
    ConditionComparator,
    ConditionSchemaRegistry,
)

__all__ = ["ConditionComparator", "ConditionSchemaRegistry"]
