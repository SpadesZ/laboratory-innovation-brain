"""License seats and the state a job parks in when there are none (§10.7, OPS-001, UX-007).

    §10.7  - resource_requirements(含 license seat)
           - WAITING_RESOURCE 狀態用於 license/seat 競用
    §17.24 A Lumerical seat shortage surfaces as degraded availability, not as an error.

THE ONE RULE THIS MODULE EXISTS TO HOLD: **no seat is not a failure.** A simulation that could not
start because the vendor's license pool was full did not fail -- it did not run. Recording it as
FAILED corrupts three things at once: §6.10's failure analysis acquires a failure that says
nothing about the physics, UX-002 pages an engineer for a queue that is working, and the Job's
`attempt_count` burns down towards `max_attempts` for a reason no retry can fix.

So the outcome of a contended acquisition is `ResourceUnavailable`, the Job moves to
WAITING_RESOURCE (an existing §17.16 state, not a new one), and the same logical Job resumes when
a seat frees. `Job.attempt_count` is untouched by waiting.

IN-MEMORY HERE, DURABLE IN `007c`. This module is the deterministic broker the M2 exit gate's
"license/resource queue mock" is written against; `007c_capabilities.sql` carries `resource_pools`
and `resource_leases` with the ceiling enforced by a trigger under an advisory lock. Both exist for
the reason `006` gives about duplicate callbacks: a check-then-insert is correct for one scheduler
and wrong for two, so the Python broker is the contract and the database is where the ceiling is
actually held. `PostgresResourceBroker` in `lab_brain.storage.postgres.resources` implements the
same protocol over those tables.

NOT A SECOND QUEUE. §10.7 puts queueing on the Job. This owns *seats*: how many exist, who holds
one, and what happens when there are none. A job waiting for a seat is WAITING_RESOURCE in `jobs`,
exactly as it was before this module existed -- which is why the exit gate can require that the Job
IDENTITY survives the wait.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel


class ResourceError(RuntimeError):
    """A resource request cannot be answered at all -- a wiring error, not contention."""


class ResourceUnavailable(Exception):
    """Every seat is held. **Not an error**; the caller parks the Job in WAITING_RESOURCE.

    An exception rather than a `None` return, and the distinction is the same one
    `AuthorityResolutionError` draws: a caller handed `None` has to remember to check it, and the
    place that forgets is the place a simulation proceeds believing it holds a seat.

    Carries the numbers a UX-007 health view needs, so the caller does not have to ask again.
    """

    def __init__(self, resource_id: str, requested: int, available: int, held_by: int) -> None:
        super().__init__(
            f"{resource_id}: {requested} seat(s) requested, {available} free, {held_by} lease(s) "
            "held. This is contention, not a failure -- the job waits (§10.7, §17.24)"
        )
        self.resource_id = resource_id
        self.requested = requested
        self.available = available
        self.held_by = held_by


class ResourceDemand(CoreModel):
    """What one execution needs from a finite external resource.

    Lands on `Job.resource_requirements` (§17.16's JSONB), which is why it serialises to a plain
    mapping rather than being a set of columns: §17.16 declares the field as an object and core
    must not learn that "a Lumerical seat" is a thing (§24.1).
    """

    resource_id: str
    seats: int = Field(default=1, ge=1)
    #: §9.4's `license_seat_s`, estimated. Carried so the CostVector the BudgetGate sees can
    #: include the seat time, rather than the seat being free in the ledger and scarce in reality.
    estimated_seat_s: int = Field(default=0, ge=0)

    def as_requirements(self) -> dict[str, object]:
        """The `Job.resource_requirements` payload. One key per field, no nesting."""
        return {
            "resource_id": self.resource_id,
            "seats": self.seats,
            "estimated_seat_s": self.estimated_seat_s,
        }

    @classmethod
    def from_requirements(cls, payload: dict[str, object]) -> ResourceDemand | None:
        """Read a demand back off a reloaded Job, or `None` if it declared none.

        `None` rather than a zero-seat default: a job with no resource requirement and a job whose
        requirement was lost in a round-trip must not look the same, because the second would
        dispatch without taking a seat.
        """
        resource_id = payload.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            return None
        seats = payload.get("seats", 1)
        estimated = payload.get("estimated_seat_s", 0)
        return cls(
            resource_id=resource_id,
            seats=int(seats) if isinstance(seats, int) else 1,
            estimated_seat_s=int(estimated) if isinstance(estimated, int) else 0,
        )


class ResourceLease(CoreModel):
    """One held allocation. Retained after release, never deleted.

    "Who was holding the seats when my job was refused one" is the question a contention incident
    actually asks, and a DELETE answers it with silence -- the same reasoning §14.4 gives for
    `Actor.active` rather than removing the row.
    """

    lease_id: str
    resource_id: str
    #: The Job holding it. A lease belongs to a Job rather than to an execution, because the whole
    #: point is that the Job survives suspend/resume and the execution does not.
    job_id: str
    seats: int = Field(ge=1)
    acquired_at: dt.datetime
    released_at: dt.datetime | None = None

    @model_validator(mode="after")
    def _released_after_acquired(self) -> Self:
        if self.released_at is not None and self.released_at < self.acquired_at:
            raise ValueError(f"lease {self.lease_id} was released before it was acquired")
        return self

    @property
    def held(self) -> bool:
        return self.released_at is None


@runtime_checkable
class ResourceBroker(Protocol):
    """Acquire and release seats. Implemented in memory here and over `007c` in storage."""

    def declared(self, resource_id: str) -> int:
        """Total seats for this resource, or raise `ResourceError` if it is not declared."""
        ...

    def available(self, resource_id: str) -> int: ...

    def acquire(
        self, resource_id: str, *, job_id: str, seats: int, now: dt.datetime, lease_id: str
    ) -> ResourceLease:
        """Take seats, or raise `ResourceUnavailable`."""
        ...

    def release(self, lease_id: str, *, now: dt.datetime) -> ResourceLease: ...


class InMemoryResourceBroker:
    """A deterministic seat pool. The "mock" the M2 exit gate names.

    DETERMINISTIC, not merely fake: no clock, no randomness, no iteration over a set. Two runs of
    the same acquisition sequence produce the same leases in the same order, which is what lets a
    contention test assert an outcome rather than a probability.

    THREE SITUATIONS THAT LOOK ALIKE AND ARE NOT, because collapsing any two of them produces a
    job that waits forever while the health page says the queue is busy:

        contention        seats exist and are all held. `ResourceUnavailable` -> the job parks in
                          WAITING_RESOURCE and resumes when one is released (§10.7).
        no seats declared the pool exists with `total_seats = 0`. This deployment does not have the
                          capability at all -- which is this environment, with no Lumerical seat
                          (R-1). `availability_for` reports UNAVAILABLE, the Capability descriptor
                          carries that, and the planner does not select it (§17.24). An
                          acquisition raises `ResourceError` rather than parking, because nothing
                          will ever be released to unpark it.
        undeclared        a demand naming a resource nobody declared. A wiring error, and it
                          raises for the same reason: waiting behind a resource that does not
                          exist is indistinguishable from waiting behind a busy one.
    """

    def __init__(self, pools: dict[str, int] | None = None) -> None:
        self._pools: dict[str, int] = dict(pools or {})
        self._leases: dict[str, ResourceLease] = {}

    def declare(self, resource_id: str, seats: int) -> None:
        if seats < 0:
            raise ResourceError(f"resource {resource_id} cannot declare {seats} seats")
        if resource_id in self._pools and self._pools[resource_id] != seats:
            raise ResourceError(
                f"resource {resource_id} is already declared with {self._pools[resource_id]} "
                f"seat(s); re-declaring it as {seats} would change a ceiling that leases were "
                "granted against"
            )
        self._pools[resource_id] = seats

    def declared(self, resource_id: str) -> int:
        if resource_id not in self._pools:
            raise ResourceError(
                f"resource {resource_id!r} is not declared. A job demanding an undeclared "
                "resource would park in WAITING_RESOURCE behind something nobody will ever "
                "release, which looks exactly like a busy queue (§10.7)"
            )
        return self._pools[resource_id]

    def held(self, resource_id: str) -> int:
        return sum(
            lease.seats
            for lease in self._leases.values()
            if lease.resource_id == resource_id and lease.held
        )

    def available(self, resource_id: str) -> int:
        return max(0, self.declared(resource_id) - self.held(resource_id))

    def leases_for(self, resource_id: str) -> tuple[ResourceLease, ...]:
        """Every lease ever granted for this resource, oldest id first. Deterministic."""
        return tuple(
            sorted(
                (lease for lease in self._leases.values() if lease.resource_id == resource_id),
                key=lambda lease: lease.lease_id,
            )
        )

    def acquire(
        self, resource_id: str, *, job_id: str, seats: int, now: dt.datetime, lease_id: str
    ) -> ResourceLease:
        declared = self.declared(resource_id)
        if seats < 1:
            raise ResourceError(f"{resource_id}: a lease of {seats} seat(s) is not a lease")
        if seats > declared:
            # Distinct from contention on purpose. Four seats in a two-seat pool, or any seat in a
            # zero-seat pool, is a demand no release can ever satisfy -- so parking the job would
            # hide a capability this deployment does not have as a busy queue, which is exactly
            # the confusion §17.24 draws a line through.
            why = (
                "this deployment has no seats for that resource"
                if declared == 0
                else "the demand exceeds the pool"
            )
            raise ResourceError(
                f"{resource_id} declares {declared} seat(s) and a lease of {seats} was requested. "
                f"No release can satisfy this, so it is a configuration error rather than "
                f"contention: {why}. WAITING_RESOURCE would hide it as a busy queue "
                "(§10.7, §17.24)"
            )
        if any(
            lease.held and lease.resource_id == resource_id and lease.job_id == job_id
            for lease in self._leases.values()
        ):
            raise ResourceError(
                f"job {job_id} already holds a lease on {resource_id}. A duplicate acquisition "
                "would consume the pool twice for one execution -- §12.4's idempotent callback, "
                "one resource over"
            )
        if lease_id in self._leases:
            raise ResourceError(f"lease {lease_id} already exists")

        free = self.available(resource_id)
        if free < seats:
            raise ResourceUnavailable(
                resource_id,
                requested=seats,
                available=free,
                held_by=sum(
                    1
                    for lease in self._leases.values()
                    if lease.resource_id == resource_id and lease.held
                ),
            )
        lease = ResourceLease(
            lease_id=lease_id,
            resource_id=resource_id,
            job_id=job_id,
            seats=seats,
            acquired_at=now,
        )
        self._leases[lease_id] = lease
        return lease

    def release(self, lease_id: str, *, now: dt.datetime) -> ResourceLease:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise ResourceError(f"no lease {lease_id}")
        if not lease.held:
            # Idempotent rather than an error: a release delivered twice is the same class of event
            # as a duplicate completion callback (§12.4), and the second must not be a failure.
            return lease
        released = lease.model_copy(update={"released_at": now})
        self._leases[lease_id] = released
        return released


def availability_for(broker: ResourceBroker, resource_id: str) -> str:
    """UX-007's reading of a pool: AVAILABLE, DEGRADED or UNAVAILABLE -- never an error.

    Returns the `Availability` value as a string so `tools` does not import a core model merely to
    describe a seat count; the caller maps it. DEGRADED for an exhausted pool with seats declared
    (§17.24's seat shortage) and UNAVAILABLE only when the pool holds no seats at all -- that is
    not contention, it is a capability this deployment does not have.
    """
    declared = broker.declared(resource_id)
    if declared == 0:
        return "UNAVAILABLE"
    return "AVAILABLE" if broker.available(resource_id) > 0 else "DEGRADED"


__all__ = [
    "InMemoryResourceBroker",
    "ResourceBroker",
    "ResourceDemand",
    "ResourceError",
    "ResourceLease",
    "ResourceUnavailable",
    "availability_for",
]
