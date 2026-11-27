"""Egress and licence gating (SEC-001, SEC-004).

Both fail closed, and both are careful about what a refusal records: an audit trail that quotes
the restricted material it blocked has copied that material somewhere with weaker access control
than the store it came from.
"""

from lab_brain.security.egress import (
    CodeAdmission,
    CodeArtifact,
    CodePolicy,
    EgressAuditLog,
    EgressDecision,
    EgressGate,
    EgressOutcome,
    EgressPolicy,
    EgressRequest,
    PrivacyMode,
    evaluate_and_audit,
    may_enter_generation_context,
)

__all__ = [
    "CodeAdmission",
    "CodeArtifact",
    "CodePolicy",
    "EgressAuditLog",
    "EgressDecision",
    "EgressGate",
    "EgressOutcome",
    "EgressPolicy",
    "EgressRequest",
    "PrivacyMode",
    "evaluate_and_audit",
    "may_enter_generation_context",
]
