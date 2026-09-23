"""Verification planning over Capability descriptors (§9.5, VER-002).

Domain-free, like `lab_brain.tools`: nothing here knows a backend name, a solver or a physical
quantity. The planner reads descriptors and matches `requires` / `produces`; what those strings
mean is a DomainPack's business.
"""

from lab_brain.verification.capability_registry import (
    CapabilityNotRegistered,
    CapabilityRegistrationError,
    CapabilityRegistry,
    CostEstimator,
)
from lab_brain.verification.planner import (
    NO_DESCRIPTOR,
    REQUIRES_UNSATISFIED,
    UNAVAILABLE,
    PlannedAction,
    PlanningRefused,
    VerificationPlanner,
)

__all__ = [
    "NO_DESCRIPTOR",
    "REQUIRES_UNSATISFIED",
    "UNAVAILABLE",
    "CapabilityNotRegistered",
    "CapabilityRegistrationError",
    "CapabilityRegistry",
    "CostEstimator",
    "PlannedAction",
    "PlanningRefused",
    "VerificationPlanner",
]
