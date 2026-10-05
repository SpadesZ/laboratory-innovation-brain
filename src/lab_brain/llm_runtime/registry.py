"""PostgreSQL storage for model connections, health, models, probes, runtimes and bindings (`012e`).

Thin, because the rules are the migration's: which lifecycle moves are legal, what a lock may
freeze, what a slot may be bound to, when a runtime may activate and what an active runtime
protects. A refused write raises `RegistryRefused` carrying the database's own sentence, so the
workspace shows the rule that refused, not a paraphrase of it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets as stdlib_secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import PROBE_VERSION, QUALIFICATION_DIGEST, ProbeResult

T = TypeVar("T")


class RegistryRefused(ValueError):
    """The database -- or the registry, for a rule it keeps -- refused the write; the message is the
    rule. `code` names a case a page explains in the researcher's words."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ConnectionRow:
    connection_id: str
    name: str
    provider_kind: str
    base_url: str
    reach: str
    secret_ref: str | None
    secret_fingerprint: str | None
    lifecycle: str
    created_by: str
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True)
class HealthRow:
    check_id: str
    connection_id: str
    outcome: str
    latency_ms: int | None
    detail: str
    checked_at: dt.datetime


@dataclass(frozen=True)
class ModelRow:
    model_profile_id: str
    connection_id: str
    model_name: str
    source: str
    lifecycle: str
    locked_capabilities: tuple[str, ...] | None
    lock_fingerprint: str | None
    locked_at: dt.datetime | None
    locked_by: str | None
    created_at: dt.datetime


@dataclass(frozen=True)
class ProbeRow:
    probe_id: str
    model_profile_id: str
    capability: str
    outcome: str
    probe_version: str
    response_digest: str | None
    latency_ms: int | None
    detail: str
    probed_at: dt.datetime
    #: What the probe demanded where that varies (`012l`); {} for every earlier row.
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeRow:
    runtime_id: str
    name: str
    state: str
    external_labels: tuple[str, ...]
    created_by: str
    created_at: dt.datetime
    activated_by: str | None
    activated_at: dt.datetime | None
    retired_at: dt.datetime | None


@dataclass(frozen=True)
class BindingRow:
    runtime_id: str
    logical_slot: LogicalSlot
    model_profile_id: str
    bound_by: str
    bound_at: dt.datetime


_CONNECTION = (
    "connection_id, name, provider_kind, base_url, reach, secret_ref, secret_fingerprint, "
    "lifecycle, created_by, created_at, updated_at"
)
_MODEL = (
    "model_profile_id, connection_id, model_name, source, lifecycle, locked_capabilities, "
    "lock_fingerprint, locked_at, locked_by, created_at"
)
_PROBE = (
    "probe_id, model_profile_id, capability, outcome, probe_version, response_digest, latency_ms, "
    "detail, probed_at, parameters"
)
_RUNTIME = (
    "runtime_id, name, state, external_labels, created_by, created_at, activated_by, "
    "activated_at, retired_at"
)


def lock_fingerprint(
    connection: ConnectionRow,
    model_name: str,
    capabilities: Iterable[str],
    qualification: Mapping[str, Mapping[str, Any]],
) -> str:
    """The locked ROUTE: endpoint, model, proven capabilities, what was demonstrated for them
    (`qualification`, e.g. ROLE_HYPOTHESIS at 5) and the semantics they were proven under
    (`QUALIFICATION_DIGEST`: probes, role prompts, response contracts). Recorded as
    `model_version` in every inference the route produces."""
    identity = {
        "provider_kind": connection.provider_kind,
        "base_url": connection.base_url,
        "reach": connection.reach,
        "model": model_name,
        "capabilities": sorted(capabilities),
        "qualification": {k: dict(v) for k, v in sorted(qualification.items())},
        "qualification_semantics": QUALIFICATION_DIGEST,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return f"lk:{digest[:16]}"


def qualification_of(
    probes: Mapping[Capability, ProbeRow], capabilities: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """For each locked capability whose passing probe recorded parameters, those parameters: what
    the lock demonstrated beyond the capability's name."""
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(capabilities):
        probe = probes.get(Capability(name))
        if probe is not None and probe.outcome == "PASSED" and probe.parameters:
            out[name] = dict(probe.parameters)
    return out


class SqlLLMRegistry:
    def __init__(self, connection: Any, *, mint: Callable[[str], str] = new_id) -> None:
        self._c = connection
        self._mint = mint

    # -- the fingerprint salt ---------------------------------------------------------------------

    def salt(self) -> str:
        row = self._c.execute("SELECT salt FROM llm_secret_salt").fetchone()
        if row is not None:
            return str(row[0])
        self._c.execute(
            "INSERT INTO llm_secret_salt (salt) VALUES (%s) ON CONFLICT DO NOTHING",
            (stdlib_secrets.token_hex(32),),
        )
        return str(self._c.execute("SELECT salt FROM llm_secret_salt").fetchone()[0])

    # -- connections ------------------------------------------------------------------------------

    def create_connection(
        self,
        *,
        name: str,
        base_url: str,
        reach: str,
        secret_ref: str | None,
        secret_fingerprint: str | None,
        actor_id: str,
        at: dt.datetime,
    ) -> ConnectionRow:
        connection_id = self._mint("llm_connection")
        self._write(
            f"INSERT INTO llm_connections ({_CONNECTION}) VALUES "
            "(%s, %s, 'OPENAI_COMPATIBLE', %s, %s, %s, %s, 'ENABLED', %s, %s, %s)",
            (
                connection_id,
                name,
                base_url,
                reach,
                secret_ref,
                secret_fingerprint,
                actor_id,
                at,
                at,
            ),
        )
        return self._require(self.connection(connection_id))

    def connection(self, connection_id: str) -> ConnectionRow | None:
        row = self._c.execute(
            f"SELECT {_CONNECTION} FROM llm_connections WHERE connection_id = %s", (connection_id,)
        ).fetchone()
        return None if row is None else ConnectionRow(*row)

    def connections(self) -> list[ConnectionRow]:
        rows = self._c.execute(
            f"SELECT {_CONNECTION} FROM llm_connections ORDER BY lifecycle = 'RETIRED', name"
        ).fetchall()
        return [ConnectionRow(*r) for r in rows]

    def set_connection_lifecycle(self, connection_id: str, lifecycle: str, at: dt.datetime) -> None:
        self._write(
            "UPDATE llm_connections SET lifecycle = %s, updated_at = %s WHERE connection_id = %s",
            (lifecycle, at, connection_id),
        )

    def replace_secret(
        self, connection_id: str, secret_ref: str | None, fingerprint: str | None, at: dt.datetime
    ) -> None:
        self._write(
            "UPDATE llm_connections SET secret_ref = %s, secret_fingerprint = %s, updated_at = %s"
            " WHERE connection_id = %s",
            (secret_ref, fingerprint, at, connection_id),
        )

    def record_health(
        self,
        connection_id: str,
        *,
        outcome: str,
        latency_ms: int | None,
        detail: str,
        at: dt.datetime,
    ) -> HealthRow:
        check_id = self._mint("llm_health_check")
        self._write(
            "INSERT INTO llm_connection_health"
            " (check_id, connection_id, outcome, latency_ms, detail, checked_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (check_id, connection_id, outcome, latency_ms, detail, at),
        )
        return HealthRow(check_id, connection_id, outcome, latency_ms, detail, at)

    def health(self, connection_id: str, limit: int = 10) -> list[HealthRow]:
        rows = self._c.execute(
            "SELECT check_id, connection_id, outcome, latency_ms, detail, checked_at"
            " FROM llm_connection_health WHERE connection_id = %s"
            " ORDER BY checked_at DESC, check_id DESC LIMIT %s",
            (connection_id, limit),
        ).fetchall()
        return [HealthRow(*r) for r in rows]

    def latest_health(self, connection_id: str) -> HealthRow | None:
        latest = self.health(connection_id, limit=1)
        return latest[0] if latest else None

    # -- models -----------------------------------------------------------------------------------

    def add_model(
        self, connection_id: str, model_name: str, source: str, at: dt.datetime
    ) -> ModelRow:
        existing = self._c.execute(
            f"SELECT {_MODEL} FROM llm_models WHERE connection_id = %s AND model_name = %s",
            (connection_id, model_name),
        ).fetchone()
        if existing is not None:
            return self._model(existing)
        model_id = self._mint("llm_model")
        self._write(
            f"INSERT INTO llm_models ({_MODEL}) VALUES"
            " (%s, %s, %s, %s, 'DISCOVERED', NULL, NULL, NULL, NULL, %s)",
            (model_id, connection_id, model_name, source, at),
        )
        return self._require(self.model(model_id))

    def model(self, model_profile_id: str) -> ModelRow | None:
        row = self._c.execute(
            f"SELECT {_MODEL} FROM llm_models WHERE model_profile_id = %s", (model_profile_id,)
        ).fetchone()
        return None if row is None else self._model(row)

    def models(self, connection_id: str | None = None) -> list[ModelRow]:
        if connection_id is None:
            rows = self._c.execute(
                f"SELECT {_MODEL} FROM llm_models ORDER BY lifecycle = 'RETIRED', model_name"
            ).fetchall()
        else:
            rows = self._c.execute(
                f"SELECT {_MODEL} FROM llm_models WHERE connection_id = %s"
                " ORDER BY lifecycle = 'RETIRED', model_name",
                (connection_id,),
            ).fetchall()
        return [self._model(r) for r in rows]

    def record_probe(self, model_profile_id: str, result: ProbeResult, at: dt.datetime) -> ProbeRow:
        probe_id = self._mint("llm_probe")

        def write() -> None:
            self._c.execute(
                f"INSERT INTO llm_capability_probes ({_PROBE}) VALUES"
                " (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    probe_id,
                    model_profile_id,
                    result.capability.value,
                    result.outcome.value,
                    PROBE_VERSION,
                    result.response_digest,
                    result.latency_ms,
                    result.detail,
                    at,
                    json.dumps(dict(result.parameters), sort_keys=True),
                ),
            )
            self._c.execute(
                "UPDATE llm_models SET lifecycle = 'TESTED' WHERE model_profile_id = %s"
                " AND lifecycle IN ('DISCOVERED', 'TESTED')",
                (model_profile_id,),
            )

        self._atomic(write)
        return ProbeRow(
            probe_id,
            model_profile_id,
            result.capability.value,
            result.outcome.value,
            PROBE_VERSION,
            result.response_digest,
            result.latency_ms,
            result.detail,
            at,
            dict(result.parameters),
        )

    def latest_probes(self, model_profile_id: str) -> dict[Capability, ProbeRow]:
        rows = self._c.execute(
            f"SELECT DISTINCT ON (capability) {_PROBE} FROM llm_capability_probes"
            " WHERE model_profile_id = %s ORDER BY capability, probed_at DESC, probe_id DESC",
            (model_profile_id,),
        ).fetchall()
        return {Capability(r[2]): ProbeRow(*r) for r in rows}

    def verified_capabilities(self, model_profile_id: str) -> frozenset[Capability]:
        row = self._c.execute(
            "SELECT llm_verified_capabilities(%s)", (model_profile_id,)
        ).fetchone()
        return frozenset(Capability(c) for c in (row[0] or ()))

    def lock(self, model_profile_id: str, *, actor_id: str, at: dt.datetime) -> ModelRow:
        """Lock exactly what the latest probes proved. Only probes run under the probes in force
        (`PROBE_VERSION`) can be locked: a fingerprint is computed under the semantics in force, so
        a lock made now from older evidence -- unlocking a stale model and locking it again without
        testing it -- would pass as current on tests that no longer qualify anything."""
        model = self._require(self.model(model_profile_id))
        connection = self._require(self.connection(model.connection_id))
        verified = sorted(c.value for c in self.verified_capabilities(model_profile_id))
        probes = self.latest_probes(model_profile_id)
        outdated = sorted(
            c for c in verified if probes[Capability(c)].probe_version != PROBE_VERSION
        )
        if outdated:
            ran = sorted({probes[Capability(c)].probe_version for c in outdated})
            raise RegistryRefused(
                f"model {model.model_name}'s latest tests of {', '.join(outdated)} ran under "
                f"{', '.join(ran)}, not the tests in force ({PROBE_VERSION}); test it again before "
                "confirming it",
                code="lock.outdated_tests",
            )
        qualification = qualification_of(probes, verified)
        self._write(
            "UPDATE llm_models SET lifecycle = 'LOCKED', locked_capabilities = %s,"
            " lock_fingerprint = %s, locked_at = %s, locked_by = %s WHERE model_profile_id = %s",
            (
                verified,
                lock_fingerprint(connection, model.model_name, verified, qualification),
                at,
                actor_id,
                model_profile_id,
            ),
        )
        return self._require(self.model(model_profile_id))

    def qualification(self, model: ModelRow) -> dict[str, dict[str, Any]]:
        """What the model's lock demonstrated beyond capability names (its latest probes'
        parameters -- for a locked model, the probes its lock counted)."""
        return qualification_of(
            self.latest_probes(model.model_profile_id), model.locked_capabilities or ()
        )

    def lock_problem(self, model: ModelRow) -> str | None:
        """Why a LOCKED model's lock is not current, or None. Recomputed at every use, never
        stored: the fingerprint the lock would have NOW -- its endpoint, capabilities, what they
        demonstrated, and the qualification semantics in force -- against the one it was given.
        A lock made under an earlier probe, role prompt or response contract does not match and is
        refused until the model is tested again and locked again; the lock itself is left as it
        was (`llm_model_locks` keeps every one)."""
        if model.lifecycle != "LOCKED" or model.lock_fingerprint is None:
            return None
        connection = self.connection(model.connection_id)
        if connection is None:  # pragma: no cover - a foreign key
            return f"model {model.model_name}'s connection is missing"
        current = lock_fingerprint(
            connection,
            model.model_name,
            model.locked_capabilities or (),
            self.qualification(model),
        )
        if current == model.lock_fingerprint:
            return None
        return (
            f"model {model.model_name}'s lock {model.lock_fingerprint} was made under "
            "qualification semantics no longer in force (a probe, role prompt or response contract "
            "changed); "
            "test it again and confirm it again"
        )

    def demonstrated(self, model: ModelRow, capability: Capability, parameter: str) -> int:
        """The value of `parameter` the model's lock demonstrated for `capability` -- 0 when it
        demonstrated none (an earlier probe that recorded no parameters)."""
        value = self.qualification(model).get(capability.value, {}).get(parameter, 0)
        return int(value) if isinstance(value, int) else 0

    def unlock(self, model_profile_id: str) -> None:
        self._write(
            "UPDATE llm_models SET lifecycle = 'TESTED', locked_capabilities = NULL,"
            " lock_fingerprint = NULL, locked_at = NULL, locked_by = NULL"
            " WHERE model_profile_id = %s",
            (model_profile_id,),
        )

    def retire_model(self, model_profile_id: str) -> None:
        self._write(
            "UPDATE llm_models SET lifecycle = 'RETIRED', locked_capabilities = NULL,"
            " lock_fingerprint = NULL, locked_at = NULL, locked_by = NULL"
            " WHERE model_profile_id = %s",
            (model_profile_id,),
        )

    # -- runtimes ---------------------------------------------------------------------------------

    def create_runtime(
        self, *, name: str, external_labels: Sequence[str], actor_id: str, at: dt.datetime
    ) -> RuntimeRow:
        runtime_id = self._mint("llm_runtime")
        self._write(
            "INSERT INTO llm_runtimes (runtime_id, name, state, external_labels, created_by,"
            " created_at) VALUES (%s, %s, 'DRAFT', %s, %s, %s)",
            (runtime_id, name, list(external_labels), actor_id, at),
        )
        return self._require(self.runtime(runtime_id))

    def runtime(self, runtime_id: str) -> RuntimeRow | None:
        row = self._c.execute(
            f"SELECT {_RUNTIME} FROM llm_runtimes WHERE runtime_id = %s", (runtime_id,)
        ).fetchone()
        return None if row is None else self._runtime(row)

    def runtimes(self) -> list[RuntimeRow]:
        rows = self._c.execute(
            f"SELECT {_RUNTIME} FROM llm_runtimes"
            " ORDER BY state = 'ACTIVE' DESC, state = 'DRAFT' DESC, created_at DESC"
        ).fetchall()
        return [self._runtime(r) for r in rows]

    def active_runtime(self) -> RuntimeRow | None:
        row = self._c.execute(
            f"SELECT {_RUNTIME} FROM llm_runtimes WHERE state = 'ACTIVE'"
        ).fetchone()
        return None if row is None else self._runtime(row)

    def bind(
        self,
        runtime_id: str,
        slot: LogicalSlot,
        model_profile_id: str,
        *,
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        self._write(
            "INSERT INTO llm_slot_bindings (runtime_id, logical_slot, model_profile_id, bound_by,"
            " bound_at) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (runtime_id, logical_slot) DO UPDATE SET"
            " model_profile_id = EXCLUDED.model_profile_id, bound_by = EXCLUDED.bound_by,"
            " bound_at = EXCLUDED.bound_at",
            (runtime_id, slot.value, model_profile_id, actor_id, at),
        )

    def unbind(self, runtime_id: str, slot: LogicalSlot) -> None:
        self._write(
            "DELETE FROM llm_slot_bindings WHERE runtime_id = %s AND logical_slot = %s",
            (runtime_id, slot.value),
        )

    def bindings(self, runtime_id: str) -> dict[LogicalSlot, BindingRow]:
        rows = self._c.execute(
            "SELECT runtime_id, logical_slot, model_profile_id, bound_by, bound_at"
            " FROM llm_slot_bindings WHERE runtime_id = %s",
            (runtime_id,),
        ).fetchall()
        return {
            LogicalSlot(r[1]): BindingRow(r[0], LogicalSlot(r[1]), r[2], r[3], r[4]) for r in rows
        }

    def activate(self, runtime_id: str, *, actor_id: str, at: dt.datetime) -> None:
        """One active runtime: the previous one is retired in the same transaction."""

        def write() -> None:
            self._c.execute(
                "UPDATE llm_runtimes SET state = 'RETIRED', retired_at = %s"
                " WHERE state = 'ACTIVE' AND runtime_id <> %s",
                (at, runtime_id),
            )
            self._c.execute(
                "UPDATE llm_runtimes SET state = 'ACTIVE', activated_by = %s, activated_at = %s"
                " WHERE runtime_id = %s",
                (actor_id, at, runtime_id),
            )

        self._atomic(write)

    def retire_runtime(self, runtime_id: str, at: dt.datetime) -> None:
        self._write(
            "UPDATE llm_runtimes SET state = 'RETIRED', retired_at = %s"
            " WHERE runtime_id = %s AND state <> 'RETIRED'",
            (at, runtime_id),
        )

    # -- plumbing ---------------------------------------------------------------------------------

    def _write(self, sql: str, params: Sequence[object]) -> None:
        self._atomic(lambda: self._c.execute(sql, params))

    def _atomic(self, work: Callable[[], object]) -> None:
        try:
            with self._c.transaction():
                work()
        except Exception as exc:  # the database's own rule, surfaced as it said it
            diag = getattr(exc, "diag", None)
            message = getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
            if getattr(exc, "sqlstate", None) is None and diag is None:
                raise
            raise RegistryRefused(message) from exc

    @staticmethod
    def _require(value: T | None) -> T:
        if value is None:  # pragma: no cover - read back in the same session it was written
            raise RegistryRefused("the row vanished after it was written")
        return value

    @staticmethod
    def _model(row: Sequence[Any]) -> ModelRow:
        values = list(row)
        values[5] = tuple(values[5]) if values[5] is not None else None
        return ModelRow(*values)

    @staticmethod
    def _runtime(row: Sequence[Any]) -> RuntimeRow:
        values = list(row)
        values[3] = tuple(values[3] or ())
        return RuntimeRow(*values)


__all__ = [
    "BindingRow",
    "ConnectionRow",
    "HealthRow",
    "ModelRow",
    "ProbeRow",
    "RegistryRefused",
    "RuntimeRow",
    "SqlLLMRegistry",
    "lock_fingerprint",
    "qualification_of",
]
