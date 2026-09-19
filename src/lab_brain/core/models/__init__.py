"""Core scientific state entities — domain-agnostic (§24.1).

The canonical path (SYS-001), in order:

    Artifact / SourceWork -> Claim / Observation -> Attestation -> RelationJudgment
      -> TransitionPolicy -> BeliefRevisionEvent -> EpistemicStateProjection

M0a implements the first four. The belief-event half arrives in M0b.

Nothing here may mention a physical quantity, a solver, or a default wavelength. If a field
would only make sense to a photonics researcher, it belongs in a DomainPack condition schema.
"""

from lab_brain.core.models.access import Actor, ArtifactOccurrence, ProjectMembership
from lab_brain.core.models.artifact import Artifact, RightsMetadata
from lab_brain.core.models.attestation import (
    FORBIDDEN_RELATION_FIELDS,
    Attestation,
    EvidenceField,
    ExtractionProvenance,
    Uncertainty,
)
from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.belief_event import (
    BELIEF_TERMINAL_STATES,
    BeliefRevisionEvent,
    BeliefState,
    BeliefTargetType,
)
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.condition import (
    ConditionMatch,
    ConditionMismatch,
    ConditionSchemaError,
    ConditionSchemaRef,
    ConditionSchemaRegistration,
)
from lab_brain.core.models.cost import (
    CAPPED_DIMENSIONS,
    BudgetCaps,
    CostEntry,
    CostKind,
    CostVector,
    DependencyRisk,
)
from lab_brain.core.models.enums import (
    FACTUAL_EPISTEMIC_TYPES,
    FAIL_CLOSED_SENSITIVITY,
    HIGH_WEIGHT_FIELD_STATUSES,
    IMPLEMENTED_INDEPENDENCE_BASES,
    ActorType,
    AuthorityComparison,
    ClaimIdentityStatus,
    ConditionMatchState,
    EpistemicType,
    ExtractionStatus,
    FieldStatus,
    IndependenceBasis,
    IndependenceRelation,
    LicenseClass,
    RelationType,
    SecretScanStatus,
    SensitivityLabel,
    SourceOrigin,
    SourceWorkStatus,
    SourceWorkType,
    TrustClass,
    VerificationStatus,
)
from lab_brain.core.models.evidence_bundle import (
    BUNDLE_SCHEMA_VERSION,
    IDENTITY_EXCLUDED_FIELDS,
    EvidenceBundle,
    ResearchIntent,
)
from lab_brain.core.models.execution_span import (
    SUBJECT_FIELD_FOR_TYPE,
    TERMINAL_SPAN_STATUSES,
    ExecutionSpan,
    SpanStatus,
    SpanType,
)
from lab_brain.core.models.governance_event import (
    GovernanceEvent,
    GovernanceEventType,
    GovernanceSubjectType,
    ResolutionEventKind,
)
from lab_brain.core.models.hypothesis import (
    FORBIDDEN_HYPOTHESIS_FIELDS,
    FORBIDDEN_STATUS_FIELDS,
    Hypothesis,
)
from lab_brain.core.models.identifiers import (
    ContentHashError,
    artifact_id_for,
    compute_content_hash,
    compute_content_hash_from_path,
    compute_content_hash_from_stream,
    content_hash_for,
    new_id,
    parse_content_hash,
)
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.prediction import (
    PREDICTION_EFFECT_TYPES,
    OutcomeSpace,
    Prediction,
    PredictionAdmissionError,
    RelationJudgmentTemplate,
)
from lab_brain.core.models.relation import (
    EPISTEMIC_RELATION_TYPES,
    IDENTITY_RELATION_TYPES,
    RelationJudgment,
)
from lab_brain.core.models.source_work import (
    RetractionCheck,
    SourceWork,
    WorkIdentifier,
)
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    ReviewItemSpec,
    TransitionDecision,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)

__all__ = [
    "BELIEF_TERMINAL_STATES",
    "BUNDLE_SCHEMA_VERSION",
    "CAPPED_DIMENSIONS",
    "EPISTEMIC_RELATION_TYPES",
    "FACTUAL_EPISTEMIC_TYPES",
    "FAIL_CLOSED_SENSITIVITY",
    "FORBIDDEN_HYPOTHESIS_FIELDS",
    "FORBIDDEN_RELATION_FIELDS",
    "FORBIDDEN_STATUS_FIELDS",
    "HIGH_WEIGHT_FIELD_STATUSES",
    "IDENTITY_EXCLUDED_FIELDS",
    "IDENTITY_RELATION_TYPES",
    "IMPLEMENTED_INDEPENDENCE_BASES",
    "PREDICTION_EFFECT_TYPES",
    "SUBJECT_FIELD_FOR_TYPE",
    "TERMINAL_SPAN_STATUSES",
    "Actor",
    "ActorType",
    "Artifact",
    "ArtifactOccurrence",
    "Attestation",
    "AuthorityComparison",
    "BeliefRevisionEvent",
    "BeliefState",
    "BeliefTargetType",
    "BudgetCaps",
    "Claim",
    "ClaimIdentityStatus",
    "ConditionMatch",
    "ConditionMatchState",
    "ConditionMismatch",
    "ConditionSchemaError",
    "ConditionSchemaRef",
    "ConditionSchemaRegistration",
    "ContentHashError",
    "CoreModel",
    "CostEntry",
    "CostKind",
    "CostVector",
    "DependencyRisk",
    "EpistemicType",
    "EvidenceBundle",
    "EvidenceField",
    "ExecutionSpan",
    "ExtractionProvenance",
    "ExtractionStatus",
    "FieldStatus",
    "GovernanceEvent",
    "GovernanceEventType",
    "GovernanceSubjectType",
    "Hypothesis",
    "HypothesisView",
    "IndependenceBasis",
    "IndependenceRelation",
    "IndependenceSummary",
    "LicenseClass",
    "Observation",
    "OutcomeSpace",
    "Prediction",
    "PredictionAdmissionError",
    "ProjectMembership",
    "RelationJudgment",
    "RelationJudgmentTemplate",
    "RelationType",
    "ResearchIntent",
    "ResolutionEventKind",
    "RetractionCheck",
    "ReviewItemSpec",
    "RightsMetadata",
    "SecretScanStatus",
    "SensitivityLabel",
    "SourceOrigin",
    "SourceWork",
    "SourceWorkStatus",
    "SourceWorkType",
    "SpanStatus",
    "SpanType",
    "TransitionDecision",
    "TransitionOutcome",
    "TransitionPolicy",
    "TransitionReason",
    "TrustClass",
    "Uncertainty",
    "VerificationStatus",
    "WorkIdentifier",
    "artifact_id_for",
    "compute_content_hash",
    "compute_content_hash_from_path",
    "compute_content_hash_from_stream",
    "content_hash_for",
    "new_id",
    "parse_content_hash",
    "utc_now",
]
