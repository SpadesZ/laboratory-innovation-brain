"""Durable Capability descriptors and the license seat pool (`007c`, §9.5, §17.18, §10.7).

TWO STORES, ONE MIGRATION, AND THEY ARE HERE TOGETHER FOR A REASON. A Capability declares a license
constraint and a seat pool is what that constraint contends for; splitting them across two modules
would mean the descriptor's `license_constraints` and the pool's `resource_id` agreed only by
convention.

WHY THE SEAT CEILING IS THE DATABASE'S AND NOT THIS MODULE'S. `InMemoryResourceBroker` checks
`available() >= seats` and inserts, which is correct for one scheduler and wrong for two: both read
"one seat free", both dispatch, and the vendor's license manager refuses the second execution at a
point where the Job has already been told it is RUNNING. `007c`'s trigger takes an advisory lock
per resource and re-counts inside it, so the loser loses the INSERT rather than the race -- the same
argument `006` makes about `runs.job_id UNIQUE` and duplicate callbacks.

So this broker does NOT re-implement the check. It attempts the insert and translates the
constraint violation into `ResourceUnavailable`, which is the outcome the caller already knows how
to handle: the Job parks in WAITING_RESOURCE.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lab_brain.core.models.capability import ActionType, Availability, Capability
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError
from lab_brain.tools.resources import ResourceError, ResourceLease, ResourceUnavailable


class CapabilityStoreError(RepositoryError):
    """A capability or resource write violated a `007c` invariant."""


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list | tuple) else ()


def _int(value: object) -> int:
    """A row value as an int, refusing rather than coercing something that is not a number.

    The driver's row type is `object` because `SqlConnection` is a structural Protocol (core keeps
    no hard dependency on psycopg). Narrowing here rather than casting means a column that changed
    type is a loud failure at the read instead of an int() of something surprising.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise CapabilityStoreError(f"expected a numeric column value, got {value!r}")
    return int(value)


def _when(value: object) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        raise CapabilityStoreError(f"expected a timestamp column value, got {value!r}")
    return value


def _when_or_none(value: object) -> dt.datetime | None:
    return None if value is None else _when(value)


def _lease(row: tuple[Any, ...]) -> ResourceLease:
    return ResourceLease(
        lease_id=_text(row[0]),
        resource_id=_text(row[1]),
        job_id=_text(row[2]),
        seats=_int(row[3]),
        acquired_at=_when(row[4]),
        released_at=_when_or_none(row[5]),
    )


class PostgresCapabilityStore:
    """§17.18 descriptors, durable. Reconstructed through the model on every read.

    THROUGH THE MODEL, not into a dict: `Capability`'s validators are the ones that refuse a
    descriptor producing nothing or requiring what it produces, and a row that bypassed them on the
    way out would be a descriptor the planner trusted and the constructor would have rejected. The
    same rule `PostgresEvidenceUnitReader` follows for the locked M1-P1 reason.
    """

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def upsert(self, capability: Capability) -> Capability:
        """Write a descriptor. Availability is the only field an existing row may change.

        §17.18 versions the CONTRACT; availability is state -- a license server going busy is not a
        new capability. Everything else is immutable, so a change arrives as a new `version` and a
        past plan stays reproducible.
        """
        existing = self.get(capability.capability_id)
        if existing is not None and existing.model_dump(
            exclude={"availability", "earliest_available_at"}
        ) != capability.model_dump(exclude={"availability", "earliest_available_at"}):
            raise CapabilityStoreError(
                f"capability {capability.capability_id} is already stored with a different "
                f"contract (version {existing.version}). §17.18 versions the descriptor so that a "
                "change gets a new version; replacing one in place would make every plan that "
                "cited it unreproducible"
            )
        self._connection.execute(
            """
            INSERT INTO capabilities (
                capability_id, domain, action_type, backend_id, requires, produces,
                authority_class, availability, conditions_schema_version, privacy_constraints,
                license_constraints, irreversible, earliest_available_at,
                estimate_cost_contract, version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (capability_id) DO UPDATE
               SET availability = EXCLUDED.availability,
                   earliest_available_at = EXCLUDED.earliest_available_at
            """,
            (
                capability.capability_id,
                capability.domain,
                capability.action_type.value,
                capability.backend_id,
                list(capability.requires),
                list(capability.produces),
                capability.authority_class,
                capability.availability.value,
                capability.conditions_schema_version,
                list(capability.privacy_constraints),
                list(capability.license_constraints),
                capability.irreversible,
                capability.earliest_available_at,
                capability.estimate_cost_contract,
                capability.version,
            ),
        )
        reloaded = self.get(capability.capability_id)
        assert reloaded is not None  # just inserted
        return reloaded

    def get(self, capability_id: str) -> Capability | None:
        row = self._connection.execute(
            """
            SELECT capability_id, domain, action_type, backend_id, requires, produces,
                   authority_class, availability, conditions_schema_version, privacy_constraints,
                   license_constraints, irreversible, earliest_available_at,
                   estimate_cost_contract, version
              FROM capabilities WHERE capability_id = %s
            """,
            (capability_id,),
        ).fetchone()
        return None if row is None else self._build(row)

    def list_all(self) -> tuple[Capability, ...]:
        rows = self._connection.execute(
            """
            SELECT capability_id, domain, action_type, backend_id, requires, produces,
                   authority_class, availability, conditions_schema_version, privacy_constraints,
                   license_constraints, irreversible, earliest_available_at,
                   estimate_cost_contract, version
              FROM capabilities ORDER BY capability_id
            """
        ).fetchall()
        return tuple(self._build(row) for row in rows)

    def set_availability(self, capability_id: str, availability: Availability) -> Capability:
        self._connection.execute(
            "UPDATE capabilities SET availability = %s WHERE capability_id = %s",
            (availability.value, capability_id),
        )
        reloaded = self.get(capability_id)
        if reloaded is None:
            raise CapabilityStoreError(f"no capability {capability_id}")
        return reloaded

    @staticmethod
    def _build(row: tuple[Any, ...]) -> Capability:
        return Capability(
            capability_id=_text(row[0]),
            domain=None if row[1] is None else _text(row[1]),
            action_type=ActionType(_text(row[2])),
            backend_id=_text(row[3]),
            requires=_tuple(row[4]),
            produces=_tuple(row[5]),
            authority_class=_text(row[6]),
            availability=Availability(_text(row[7])),
            conditions_schema_version=None if row[8] is None else _text(row[8]),
            privacy_constraints=_tuple(row[9]),
            license_constraints=_tuple(row[10]),
            irreversible=bool(row[11]),
            earliest_available_at=row[12],
            estimate_cost_contract=_text(row[13]),
            version=_text(row[14]),
        )


class PostgresResourceBroker:
    """§10.7's seat pool over `007c`. The ceiling is the trigger's; this translates the refusal.

    Satisfies `lab_brain.tools.resources.ResourceBroker`, so `run_simulation` cannot tell it apart
    from the in-memory one -- which is what lets the same contention test run against both.
    """

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def declare(self, resource_id: str, *, display_name: str, seats: int) -> None:
        self._connection.execute(
            """
            INSERT INTO resource_pools (resource_id, display_name, total_seats)
            VALUES (%s, %s, %s)
            ON CONFLICT (resource_id) DO UPDATE SET total_seats = EXCLUDED.total_seats
            """,
            (resource_id, display_name, seats),
        )

    def declared(self, resource_id: str) -> int:
        row = self._connection.execute(
            "SELECT total_seats FROM resource_pools WHERE resource_id = %s", (resource_id,)
        ).fetchone()
        if row is None:
            raise ResourceError(
                f"resource {resource_id!r} is not declared. A job demanding an undeclared "
                "resource would park in WAITING_RESOURCE behind something nobody will ever "
                "release, which looks exactly like a busy queue (§10.7)"
            )
        return _int(row[0])

    def held(self, resource_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(SUM(seats), 0) FROM resource_leases "
            "WHERE resource_id = %s AND released_at IS NULL",
            (resource_id,),
        ).fetchone()
        return 0 if row is None else _int(row[0])

    def available(self, resource_id: str) -> int:
        return max(0, self.declared(resource_id) - self.held(resource_id))

    def acquire(
        self, resource_id: str, *, job_id: str, seats: int, now: dt.datetime, lease_id: str
    ) -> ResourceLease:
        """Attempt the insert; let `007c` decide. See the module docstring.

        The capacity check happens INSIDE the trigger's advisory lock, so two schedulers cannot
        both observe a free seat. What this method does with the failure is the whole point: a
        ceiling violation becomes `ResourceUnavailable` (the job parks) while a demand the pool can
        never satisfy becomes `ResourceError` (a configuration problem), exactly as the in-memory
        broker distinguishes them.
        """
        declared = self.declared(resource_id)
        if seats < 1:
            raise ResourceError(f"{resource_id}: a lease of {seats} seat(s) is not a lease")
        if seats > declared:
            raise ResourceError(
                f"{resource_id} declares {declared} seat(s) and a lease of {seats} was requested. "
                "No release can satisfy this, so it is a configuration error rather than "
                "contention (§10.7, §17.24)"
            )
        try:
            self._connection.execute(
                "INSERT INTO resource_leases (lease_id, resource_id, job_id, seats, acquired_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (lease_id, resource_id, job_id, seats, now),
            )
        except Exception as refused:
            message = str(refused)
            if "would exceed the pool" in message or "resource_leases_one_held_per_job" in message:
                raise ResourceUnavailable(
                    resource_id,
                    requested=seats,
                    available=self.available(resource_id),
                    held_by=self.held(resource_id),
                ) from refused
            raise
        return ResourceLease(
            lease_id=lease_id,
            resource_id=resource_id,
            job_id=job_id,
            seats=seats,
            acquired_at=now,
        )

    def release(self, lease_id: str, *, now: dt.datetime) -> ResourceLease:
        row = self._connection.execute(
            "UPDATE resource_leases SET released_at = COALESCE(released_at, %s) "
            "WHERE lease_id = %s "
            "RETURNING lease_id, resource_id, job_id, seats, acquired_at, released_at",
            (now, lease_id),
        ).fetchone()
        if row is None:
            raise ResourceError(f"no lease {lease_id}")
        return _lease(row)

    def leases_for(self, resource_id: str) -> tuple[ResourceLease, ...]:
        rows = self._connection.execute(
            "SELECT lease_id, resource_id, job_id, seats, acquired_at, released_at "
            "FROM resource_leases WHERE resource_id = %s ORDER BY lease_id",
            (resource_id,),
        ).fetchall()
        return tuple(_lease(row) for row in rows)


__all__ = ["CapabilityStoreError", "PostgresCapabilityStore", "PostgresResourceBroker"]
