"""Repository contracts and the in-memory implementation.

Cognition and retrieval depend on these contracts, never on a backend (§6.6, ADR-0001). The
PostgreSQL implementation lives in ``lab_brain.storage.postgres`` and must pass the same
conformance suite.
"""

from lab_brain.core.repositories.memory import (
    InMemoryArtifactRepository,
    InMemoryAttestationRepository,
    InMemoryClaimRepository,
    InMemoryEvidenceBundleRepository,
    InMemoryObservationRepository,
    InMemoryRelationRepository,
    InMemorySourceWorkRepository,
)
from lab_brain.core.repositories.protocols import (
    ArtifactRepository,
    AttestationRepository,
    ClaimRepository,
    DuplicateIdentityError,
    EvidenceBundleRepository,
    ObservationRepository,
    RelationRepository,
    RepositoryError,
    SourceWorkRepository,
)

__all__ = [
    "ArtifactRepository",
    "AttestationRepository",
    "ClaimRepository",
    "DuplicateIdentityError",
    "EvidenceBundleRepository",
    "InMemoryArtifactRepository",
    "InMemoryAttestationRepository",
    "InMemoryClaimRepository",
    "InMemoryEvidenceBundleRepository",
    "InMemoryObservationRepository",
    "InMemoryRelationRepository",
    "InMemorySourceWorkRepository",
    "ObservationRepository",
    "RelationRepository",
    "RepositoryError",
    "SourceWorkRepository",
]
