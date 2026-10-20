"""System health, derived (UX-007, §17.24, §14.4.1, §17.18, §17.21, §17.19.1).

§17.24 names the four inputs and then the rule:

    component status <- Capability.availability (17.18)
                      + ExternalSourceAdapter.healthcheck() -> SourceHealth (17.21)
                      + Job queue depth + ReviewQueue depth (17.19.1)

    A Lumerical seat shortage surfaces as degraded availability, not as an error.

THE LAST LINE IS THE REQUIREMENT, not a footnote. A seat shortage is the system working: the
queue is doing its job, the work is waiting, nothing is broken. Reporting it as an error sends an
engineer to investigate a healthy system, and -- worse -- an operator who sees "error" for a
routine contention eventually stops reading the health page at all. So `WAITING_RESOURCE` jobs
raise *utilisation* and lower *availability*; they never produce ERROR.

THERE IS NO WRITABLE HEALTH FIELD. `SystemHealth` is constructed by `derive_health` from the four
inputs and nothing else. A settable status is what §17.24 forbids ("不是手維護的") and it fails in
a specific way: somebody marks a component healthy during an incident to stop the alerts, and the
page then says what the last human believed rather than what is true.

HUMAN REVIEW IS A CAPABILITY, NOT A FREE RESOURCE. §14.4.1 is explicit --
`HumanReviewCapability.availability <- ReviewQueue capacity + actor schedule` -- so a full review
queue degrades the *system*, visibly, rather than silently making every uncertain item wait
forever. That is why ReviewQueue depth is one of the four inputs and not a separate page.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.job import Job, JobState


class ComponentStatus(StrEnum):
    """How a component is doing.

    ``DEGRADED`` carries the weight. Without it every contention has to be reported as either
    healthy (which hides it) or unavailable (which overstates it), and §17.24's seat-shortage
    rule has nowhere to land.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SourceHealth:
    """§17.21's `healthcheck()` return."""

    provider_id: str
    reachable: bool
    detail: str = ""


@dataclass(frozen=True)
class CapabilityAvailability:
    """The slice of §17.18's Capability that health reads.

    ``concurrency_limit`` of None means unmetered -- a capability with no seat constraint, like a
    local parser. Distinguished from 0, which means no seats at all: the first can never be
    contended, the second is always exhausted, and collapsing them would make an unmetered
    capability report as permanently unavailable.
    """

    capability_id: str
    available: bool
    concurrency_limit: int | None = None
    earliest_available_at: str | None = None


@dataclass(frozen=True)
class ComponentHealth:
    """One row of the health view. Derived; there is no constructor a UI should call."""

    component_id: str
    status: ComponentStatus
    reason_code: str | None = None
    queue_depth: int = 0
    waiting_on_resource: int = 0


@dataclass(frozen=True)
class SystemHealth:
    """The whole view. Overall status is the worst component, never an independent field."""

    components: tuple[ComponentHealth, ...]
    job_queue_depth: int
    review_queue_depth: int
    review_queue_capacity: int

    @property
    def overall(self) -> ComponentStatus:
        if any(c.status is ComponentStatus.UNAVAILABLE for c in self.components):
            return ComponentStatus.UNAVAILABLE
        if any(c.status is ComponentStatus.DEGRADED for c in self.components):
            return ComponentStatus.DEGRADED
        return ComponentStatus.HEALTHY

    @property
    def review_capacity_remaining(self) -> int:
        return max(0, self.review_queue_capacity - self.review_queue_depth)

    def component(self, component_id: str) -> ComponentHealth | None:
        return next((c for c in self.components if c.component_id == component_id), None)


def derive_health(
    *,
    capabilities: Sequence[CapabilityAvailability],
    adapters: Sequence[SourceHealth],
    jobs: Sequence[Job],
    review_queue_depth: int,
    review_queue_capacity: int,
) -> SystemHealth:
    """Build the health view from authoritative state. Pure; nothing here is stored.

    Called with live inputs every time rather than cached, because a cached health view is a
    manually maintained one with an expiry: it says what was true when the cache was written, and
    the whole requirement is that it says what is true.
    """
    components: list[ComponentHealth] = []

    waiting = [j for j in jobs if j.state is JobState.WAITING_RESOURCE]
    active = [j for j in jobs if j.is_active]

    for capability in capabilities:
        blocked = [j for j in waiting if j.capability_id == capability.capability_id]
        running = [j for j in active if j.capability_id == capability.capability_id]

        if not capability.available:
            status = ComponentStatus.UNAVAILABLE
            reason = "CAPABILITY_UNAVAILABLE"
        elif blocked:
            # §17.24's seat shortage. DEGRADED, never an error: the queue is working and the
            # work is waiting, which is a healthy system under contention.
            status = ComponentStatus.DEGRADED
            reason = "AWAITING_RESOURCE"
        elif (
            capability.concurrency_limit is not None
            and capability.concurrency_limit > 0
            and len(running) >= capability.concurrency_limit
        ):
            status = ComponentStatus.DEGRADED
            reason = "AT_CONCURRENCY_LIMIT"
        else:
            status = ComponentStatus.HEALTHY
            reason = None

        components.append(
            ComponentHealth(
                component_id=capability.capability_id,
                status=status,
                reason_code=reason,
                queue_depth=len(running),
                waiting_on_resource=len(blocked),
            )
        )

    for adapter in adapters:
        components.append(
            ComponentHealth(
                component_id=adapter.provider_id,
                status=(
                    ComponentStatus.HEALTHY if adapter.reachable else ComponentStatus.UNAVAILABLE
                ),
                reason_code=None if adapter.reachable else "EXTERNAL_SERVICE_UNAVAILABLE",
            )
        )

    # §14.4.1: human review is a Capability whose availability falls with queue depth. A full
    # queue is a degraded system, visibly -- not an invisible backlog.
    review_status = ComponentStatus.HEALTHY
    review_reason: str | None = None
    if review_queue_capacity <= 0 or review_queue_depth >= review_queue_capacity:
        review_status = ComponentStatus.DEGRADED
        review_reason = "REVIEW_QUEUE_FULL"
    components.append(
        ComponentHealth(
            component_id="capability:human_review",
            status=review_status,
            reason_code=review_reason,
            queue_depth=review_queue_depth,
        )
    )

    return SystemHealth(
        components=tuple(components),
        job_queue_depth=len(active),
        review_queue_depth=review_queue_depth,
        review_queue_capacity=review_queue_capacity,
    )


__all__ = [
    "CapabilityAvailability",
    "ComponentHealth",
    "ComponentStatus",
    "SourceHealth",
    "SystemHealth",
    "derive_health",
]
