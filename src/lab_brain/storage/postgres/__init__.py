"""PostgreSQL-backed read boundaries.

Writes are not here: they go through the ingestion pipeline and the migrations' triggers, which
is where the invariants that govern them live. What this package holds is the readers that
rebuild stored rows through their models, so a caller cannot receive a row that never revalidated.
"""

from lab_brain.storage.postgres.evidence_units import (
    EvidenceUnitReadError,
    PostgresEvidenceUnitReader,
)

__all__ = ["EvidenceUnitReadError", "PostgresEvidenceUnitReader"]
