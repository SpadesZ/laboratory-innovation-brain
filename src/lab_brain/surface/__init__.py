"""The user-facing projections of the ingestion path (UX-001 … UX-007).

Everything in this package is a PROJECTION. §17.22 says it of `IngestionItem` and §17.23 says it
of `ErrorRecord`, and the rule generalises: nothing here is a source of truth, nothing here is
writable by a client, and every value is derived from Job / ExecutionSpan / Artifact / ReviewItem
/ Conflict / ReviewQueue.

That is why there is no `state` setter, no health field, and no render path that calls a model.
Each of those would be the one piece of data with no upstream -- which is exactly the piece a UI
writes to when the derivation is inconvenient.
"""

from lab_brain.surface.catalog import (
    GENERIC_REASON_CODE,
    CatalogEntry,
    MessageCatalog,
    RenderedMessage,
    Severity,
    default_catalog,
    render,
)
from lab_brain.surface.disclosure import (
    VIEW_TECHNICAL_SCOPE,
    DiagnosticsService,
    DisclosurePayload,
    ErrorNotFound,
    TechnicalDetail,
    redact,
)
from lab_brain.surface.errors import (
    AUTO_RETRYABLE,
    AuditLog,
    BudgetRefused,
    ErrorClass,
    ErrorRecord,
    Remediation,
    RemediationAction,
    RetryDecision,
    decide_retry,
    may_auto_retry,
    remediations_for,
)
from lab_brain.surface.health import (
    CapabilityAvailability,
    ComponentHealth,
    ComponentStatus,
    SourceHealth,
    SystemHealth,
    derive_health,
)
from lab_brain.surface.ingestion_item import (
    PRECEDENCE,
    DuplicateVerdict,
    IngestionItem,
    ItemState,
    classify_duplicate,
    derive_state,
)

__all__ = [
    "AUTO_RETRYABLE",
    "GENERIC_REASON_CODE",
    "PRECEDENCE",
    "VIEW_TECHNICAL_SCOPE",
    "AuditLog",
    "BudgetRefused",
    "CapabilityAvailability",
    "CatalogEntry",
    "ComponentHealth",
    "ComponentStatus",
    "DiagnosticsService",
    "DisclosurePayload",
    "DuplicateVerdict",
    "ErrorClass",
    "ErrorNotFound",
    "ErrorRecord",
    "IngestionItem",
    "ItemState",
    "MessageCatalog",
    "Remediation",
    "RemediationAction",
    "RenderedMessage",
    "RetryDecision",
    "Severity",
    "SourceHealth",
    "SystemHealth",
    "TechnicalDetail",
    "classify_duplicate",
    "decide_retry",
    "default_catalog",
    "derive_health",
    "derive_state",
    "may_auto_retry",
    "redact",
    "remediations_for",
    "render",
]
