"""PostgreSQL boundaries for the ingestion/evidence path.

Two directions, deliberately separate classes rather than one "repository".

READS rebuild every row through its model, so a caller cannot receive a row that never
revalidated. `PostgresEvidenceUnitReader` is locked by the M1-P1 hard-lock.

WRITES were, until M1-P2, supplied only by test helpers -- the P2 limitation the M1-P1 readiness
document recorded as open. `PostgresIngestionWriter` closes it. It is a writer, not the other
half of a unit-of-work abstraction: the invariants still live in the migrations, where every
writer meets them, and this class's whole contribution is that a *production* caller now exists
which the ingestion pipeline can be wired to.

The split is not ceremony. A combined class would make it natural for a read to be served from
something the same object just wrote, and the reader's guarantee is precisely that it did not do
that.
"""

from lab_brain.storage.postgres.evidence_units import (
    EvidenceUnitReadError,
    PostgresEvidenceUnitReader,
)
from lab_brain.storage.postgres.ingestion_writer import (
    IngestionWriteError,
    PostgresIngestionWriter,
)

__all__ = [
    "EvidenceUnitReadError",
    "IngestionWriteError",
    "PostgresEvidenceUnitReader",
    "PostgresIngestionWriter",
]
