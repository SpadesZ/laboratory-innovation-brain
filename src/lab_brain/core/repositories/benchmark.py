"""Durable storage for OutcomeSpaces and BenchmarkPolicies (§17.19.2, LLM-002, VER-004/VER-008).

WHAT `activate` IS. A calibrated policy version is immutable; the one thing that moves is `active`,
and at most one version per (domain, benchmark set, metric) may be active -- `010c`'s partial unique
index. Activating a version therefore deactivates the current one in the same transaction: two
active thresholds for one gate would make the gate's answer depend on which row a reader found
first, and a window with none would disarm it silently.

`active_for` IS HOW A GATE IS ARMED, AND `None` MEANS "NOT CALIBRATED". There is no default
threshold anywhere in this package. A gate that finds no active policy reports ADVISORY and does not
enforce (§15.4: 校準前不得任意 hard-code 門檻數字).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.models.benchmark import BenchmarkPolicy
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class BenchmarkStoreError(RepositoryError):
    """An outcome-space or benchmark-policy write violated an invariant."""


@runtime_checkable
class BenchmarkStore(Protocol):
    def add_outcome_space(self, space: OutcomeSpace) -> OutcomeSpace: ...

    def outcome_space(self, outcome_space_id: str, version: str) -> OutcomeSpace | None: ...

    def add_policy(self, policy: BenchmarkPolicy) -> BenchmarkPolicy: ...

    def policy(self, policy_id: str, version: str) -> BenchmarkPolicy | None: ...

    def activate(self, policy_id: str, version: str) -> BenchmarkPolicy: ...

    def active_for(
        self, *, domain: str, benchmark_set_id: str, metric_key: str
    ) -> BenchmarkPolicy | None: ...


class InMemoryBenchmarkStore:
    """Backend-free implementation. Refuses what `010c` refuses."""

    def __init__(self) -> None:
        self._spaces: dict[tuple[str, str], OutcomeSpace] = {}
        self._policies: dict[tuple[str, str], BenchmarkPolicy] = {}

    def add_outcome_space(self, space: OutcomeSpace) -> OutcomeSpace:
        key = (space.outcome_space_id, space.version)
        existing = self._spaces.get(key)
        if existing is not None and existing != space:
            raise BenchmarkStoreError(f"outcome space {space.ref} is immutable")
        self._spaces[key] = space
        return space

    def outcome_space(self, outcome_space_id: str, version: str) -> OutcomeSpace | None:
        return self._spaces.get((outcome_space_id, version))

    def add_policy(self, policy: BenchmarkPolicy) -> BenchmarkPolicy:
        key = (policy.policy_id, policy.version)
        existing = self._policies.get(key)
        if existing is not None:
            if existing.model_copy(update={"active": policy.active}) != policy:
                raise BenchmarkStoreError(
                    f"benchmark policy {policy.ref} is immutable except for `active`; a "
                    "re-calibration is a new version"
                )
            return existing
        if policy.active and self._active_key_taken(policy):
            raise BenchmarkStoreError(
                f"another version is already active for {policy.metric_key}; use activate()"
            )
        self._policies[key] = policy
        return policy

    def policy(self, policy_id: str, version: str) -> BenchmarkPolicy | None:
        return self._policies.get((policy_id, version))

    def activate(self, policy_id: str, version: str) -> BenchmarkPolicy:
        target = self._policies.get((policy_id, version))
        if target is None:
            raise BenchmarkStoreError(f"no benchmark policy {policy_id}@{version} to activate")
        for key, other in list(self._policies.items()):
            if other.active and _same_gate(other, target):
                self._policies[key] = other.model_copy(update={"active": False})
        activated = target.model_copy(update={"active": True})
        self._policies[(policy_id, version)] = activated
        return activated

    def active_for(
        self, *, domain: str, benchmark_set_id: str, metric_key: str
    ) -> BenchmarkPolicy | None:
        for policy in self._policies.values():
            if policy.active and (policy.domain, policy.benchmark_set_id, policy.metric_key) == (
                domain,
                benchmark_set_id,
                metric_key,
            ):
                return policy
        return None

    def _active_key_taken(self, policy: BenchmarkPolicy) -> bool:
        return any(p.active and _same_gate(p, policy) for p in self._policies.values())


def _same_gate(a: BenchmarkPolicy, b: BenchmarkPolicy) -> bool:
    return (a.domain, a.benchmark_set_id, a.metric_key) == (
        b.domain,
        b.benchmark_set_id,
        b.metric_key,
    )


_SPACE_COLUMNS = (
    "outcome_space_id",
    "version",
    "domain",
    "action_type",
    "hypothesis_type",
    "schema_version",
    "outcomes",
    "order_or_metric_ref",
    "explicit_exclusions",
    "validity_bounds",
)

_POLICY_COLUMNS = (
    "policy_id",
    "version",
    "domain",
    "benchmark_set_id",
    "metric_key",
    "threshold",
    "direction",
    "calibrated_at",
    "sample_size",
    "calibration_artifact_refs",
    "active",
)


class SqlBenchmarkStore:
    """PostgreSQL implementation over `010c`."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_outcome_space(self, space: OutcomeSpace) -> OutcomeSpace:
        s = space
        self._connection.execute(
            f"INSERT INTO outcome_spaces ({', '.join(_SPACE_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_SPACE_COLUMNS))}) "
            "ON CONFLICT (outcome_space_id, version) DO NOTHING",
            (
                s.outcome_space_id,
                s.version,
                s.domain,
                s.action_type,
                s.hypothesis_type,
                s.schema_version,
                list(s.outcomes),
                s.order_or_metric_ref,
                list(s.explicit_exclusions),
                json.dumps(s.validity_bounds),
            ),
        )
        stored = self.outcome_space(s.outcome_space_id, s.version)
        if stored != s:
            raise BenchmarkStoreError(f"outcome space {s.ref} is already declared differently")
        return s

    def outcome_space(self, outcome_space_id: str, version: str) -> OutcomeSpace | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_SPACE_COLUMNS)} FROM outcome_spaces "
            "WHERE outcome_space_id = %s AND version = %s",
            (outcome_space_id, version),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_SPACE_COLUMNS, row, strict=True))
        return OutcomeSpace.model_validate(values)

    def add_policy(self, policy: BenchmarkPolicy) -> BenchmarkPolicy:
        p = policy
        self._connection.execute(
            f"INSERT INTO benchmark_policies ({', '.join(_POLICY_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_POLICY_COLUMNS))}) "
            "ON CONFLICT (policy_id, version) DO NOTHING",
            (
                p.policy_id,
                p.version,
                p.domain,
                p.benchmark_set_id,
                p.metric_key,
                p.threshold,
                p.direction.value if p.direction is not None else None,
                p.calibrated_at,
                p.sample_size,
                list(p.calibration_artifact_refs),
                p.active,
            ),
        )
        stored = self.policy(p.policy_id, p.version)
        if stored is None or stored.model_copy(update={"active": p.active}) != p:
            raise BenchmarkStoreError(f"benchmark policy {p.ref} is already recorded differently")
        return stored

    def policy(self, policy_id: str, version: str) -> BenchmarkPolicy | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_POLICY_COLUMNS)} FROM benchmark_policies "
            "WHERE policy_id = %s AND version = %s",
            (policy_id, version),
        ).fetchone()
        return None if row is None else _policy_from_row(row)

    def activate(self, policy_id: str, version: str) -> BenchmarkPolicy:
        target = self.policy(policy_id, version)
        if target is None:
            raise BenchmarkStoreError(f"no benchmark policy {policy_id}@{version} to activate")
        transaction = getattr(self._connection, "transaction", None)
        if transaction is None:  # pragma: no cover
            raise BenchmarkStoreError("activation needs a transactional connection")
        with transaction():
            self._connection.execute(
                "UPDATE benchmark_policies SET active = FALSE "
                "WHERE domain = %s AND benchmark_set_id = %s AND metric_key = %s AND active",
                (target.domain, target.benchmark_set_id, target.metric_key),
            )
            self._connection.execute(
                "UPDATE benchmark_policies SET active = TRUE WHERE policy_id = %s AND version = %s",
                (policy_id, version),
            )
        activated = self.policy(policy_id, version)
        assert activated is not None
        return activated

    def active_for(
        self, *, domain: str, benchmark_set_id: str, metric_key: str
    ) -> BenchmarkPolicy | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_POLICY_COLUMNS)} FROM benchmark_policies "
            "WHERE domain = %s AND benchmark_set_id = %s AND metric_key = %s AND active",
            (domain, benchmark_set_id, metric_key),
        ).fetchone()
        return None if row is None else _policy_from_row(row)


def _policy_from_row(row: tuple[object, ...]) -> BenchmarkPolicy:
    values: dict[str, Any] = dict(zip(_POLICY_COLUMNS, row, strict=True))
    values["threshold"] = Decimal(str(values["threshold"]))
    return BenchmarkPolicy.model_validate(values)


__all__ = [
    "BenchmarkStore",
    "BenchmarkStoreError",
    "InMemoryBenchmarkStore",
    "SqlBenchmarkStore",
]
