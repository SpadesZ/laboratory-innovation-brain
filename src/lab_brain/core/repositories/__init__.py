"""Repository contracts and the in-memory implementation.

Cognition and retrieval depend on these contracts, never on a backend (§6.6, ADR-0001). The
PostgreSQL implementation lives in ``lab_brain.storage.postgres`` and must pass the same
conformance suite.
"""

from lab_brain.core.repositories.belief_events import (
    BeliefEventError,
    BeliefEventStore,
    InMemoryBeliefEventStore,
    SqlBeliefEventStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.budget import (
    CostLedger,
    InMemoryBudgetApprovalClaims,
    InMemoryCostLedger,
    NonDurableClaimStoreError,
    SqlBudgetApprovalClaims,
    SqlCostLedger,
    require_durable_connection,
)
from lab_brain.core.repositories.evidence import (
    EvidenceStoreError,
    SqlAttestationStore,
    SqlRelationStore,
)
from lab_brain.core.repositories.jobs import (
    IdempotencyKeyMismatch,
    InMemoryJobStore,
    JobStore,
    JobStoreError,
    SqlJobStore,
)
from lab_brain.core.repositories.memory import (
    InMemoryArtifactRepository,
    InMemoryAttestationRepository,
    InMemoryClaimRepository,
    InMemoryEvidenceBundleRepository,
    InMemoryObservationRepository,
    InMemoryRelationRepository,
    InMemorySourceWorkRepository,
)
from lab_brain.core.repositories.observability import (
    InMemorySpanRepository,
    SpanLifecycleError,
    SpanRepository,
    SqlSpanRepository,
    TraceCorruptionError,
    TraceView,
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
    "BeliefEventError",
    "BeliefEventStore",
    "ClaimRepository",
    "CostLedger",
    "DuplicateIdentityError",
    "EvidenceBundleRepository",
    "EvidenceStoreError",
    "IdempotencyKeyMismatch",
    "InMemoryArtifactRepository",
    "InMemoryAttestationRepository",
    "InMemoryBeliefEventStore",
    "InMemoryBudgetApprovalClaims",
    "InMemoryClaimRepository",
    "InMemoryCostLedger",
    "InMemoryEvidenceBundleRepository",
    "InMemoryJobStore",
    "InMemoryObservationRepository",
    "InMemoryRelationRepository",
    "InMemorySourceWorkRepository",
    "InMemorySpanRepository",
    "JobStore",
    "JobStoreError",
    "NonDurableClaimStoreError",
    "ObservationRepository",
    "RelationRepository",
    "RepositoryError",
    "SourceWorkRepository",
    "SpanLifecycleError",
    "SpanRepository",
    "SqlAttestationStore",
    "SqlBeliefEventStore",
    "SqlBudgetApprovalClaims",
    "SqlCostLedger",
    "SqlJobStore",
    "SqlRelationStore",
    "SqlSpanRepository",
    "SqlTransitionPolicyStore",
    "TraceCorruptionError",
    "TraceView",
    "require_durable_connection",
]
