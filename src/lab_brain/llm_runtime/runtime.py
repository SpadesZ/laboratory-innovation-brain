"""The LLM settings workflow, and the active runtime the research service reasons with.

`LLMSettings` is the operation behind each step of the workspace's LLM settings:

    Connection -> Fetch/declare model -> Capability test -> Lock -> Slot binding -> Readiness
    -> Activate

Every step writes through `SqlLLMRegistry`, whose rules are the database's; this layer adds what
the database cannot see -- a URL's host, a credential in the operating system's store, what a
provider actually answered.

`load_active_runtime` turns the ACTIVE runtime into the `ReasoningRuntime` the research service
builds its one `ScientificLLM` from. With no active runtime it returns `None`, and the service
uses its explicit fallback, the local catalog reasoner. With an active runtime that cannot be used
-- a credential that is no longer readable -- it RAISES: a research run is refused rather than
silently reasoned by something other than what is active.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import urlsplit

from lab_brain.cognition.llm import ModelSlot
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.authority import ProjectEgressPolicies, is_administrator
from lab_brain.llm_runtime.capabilities import BUILTIN_EMBEDDING, Capability, roles_on
from lab_brain.llm_runtime.contracts import contract_for
from lab_brain.llm_runtime.probes import PROBE_ORDER, run_probe
from lab_brain.llm_runtime.provider import (
    OpenAICompatibleClient,
    ProviderError,
    is_this_machine_url,
)
from lab_brain.llm_runtime.readiness import Readiness, critic_route, egress_route, evaluate
from lab_brain.llm_runtime.registry import (
    ConnectionRow,
    HealthRow,
    ModelRow,
    ProbeRow,
    RegistryRefused,
    RuntimeRow,
    SqlLLMRegistry,
)
from lab_brain.llm_runtime.secrets import (
    SecretError,
    SecretStore,
    SecretUnavailable,
    fingerprint,
    looks_like_credential,
    parse_secret_ref,
    redact,
)
from lab_brain.research.reasoning import ReasoningRuntime
from lab_brain.security.egress import EgressPolicy
from lab_brain.security.external import ExternalReach

_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")

T = TypeVar("T")

#: Evidence labels an EXTERNAL route may be declared to carry. Never RESTRICTED_NDA (§14.1).
EXTERNAL_LABELS: tuple[str, ...] = (
    SensitivityLabel.PUBLIC.value,
    SensitivityLabel.INTERNAL.value,
    SensitivityLabel.CONFIDENTIAL_LAB.value,
)


class SettingsRefused(ValueError):
    """A settings step cannot be taken as asked. Nothing was written."""


class RuntimeUnavailable(RuntimeError):
    """A runtime is active and cannot be used: research is refused, not silently re-routed."""


ClientFactory = Callable[[str, str | None, float], OpenAICompatibleClient]


def _client(base_url: str, key: str | None, timeout: float) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(base_url, key, timeout=timeout)


class LLMSettings:
    """Every step that changes configuration -- or probes, or records health -- is deployment
    administration: it refuses an actor who is not a current LLM administrator (`012f`), before
    anything is written or sent. Reads (the registry, a readiness evaluation) are not."""

    def __init__(
        self,
        connection: Any,
        *,
        secrets: SecretStore,
        actor_id: str,
        clock: Callable[[], dt.datetime] = utc_now,
        client: ClientFactory = _client,
        timeout: float = 120.0,
        local_hosts: Iterable[str] = (),
    ) -> None:
        self.registry = SqlLLMRegistry(connection)
        self._db = connection
        self._secrets = secrets
        self._actor = actor_id
        self._clock = clock
        self._client = client
        self._timeout = timeout
        #: Host names besides loopback that are this machine: the Docker host of a containerised
        #: workspace (`host.docker.internal`), and only when the deployment says it is one.
        self._local_hosts = frozenset(h.lower() for h in local_hosts)

    @property
    def is_administrator(self) -> bool:
        return is_administrator(self._db, self._actor)

    def _require_admin(self) -> None:
        if not self.is_administrator:
            raise SettingsRefused(
                f"{self._actor} is not an LLM administrator of this deployment. The language-model "
                "routes are deployment configuration, granted by the deployment's operator "
                f"(lab-brain admin llm-admin {self._actor}); project membership does not grant it"
            )

    # -- 1. connection ----------------------------------------------------------------------------

    def add_connection(
        self,
        *,
        name: str,
        base_url: str,
        reach: str,
        secret_mode: str,
        env_name: str = "",
        secret_value: str = "",
    ) -> ConnectionRow:
        self._require_admin()
        name = name.strip().lower()
        base_url = base_url.strip().rstrip("/")
        if not _NAME.match(name) or looks_like_credential(name):
            raise SettingsRefused(
                "a connection name is 1-48 lower-case letters, digits, '.', '_' or '-'"
            )
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SettingsRefused("the base URL is http:// or https:// and names a host")
        if "@" in parts.netloc or parts.query or parts.fragment:
            raise SettingsRefused(
                "the base URL carries no credentials, query or fragment; the credential is "
                "referenced separately"
            )
        if reach not in ("LOCAL", "EXTERNAL"):
            raise SettingsRefused("reach is LOCAL or EXTERNAL")
        if reach == "LOCAL" and not is_this_machine_url(base_url, self._local_hosts):
            also = "".join(f", or {h}" for h in sorted(self._local_hosts))
            raise SettingsRefused(
                "LOCAL may only be declared of this machine (127.0.0.1, localhost or "
                f"[::1]{also}); a model on any other host is EXTERNAL"
            )
        if any(c.name == name for c in self.registry.connections()):
            raise SettingsRefused(f"a connection named {name} already exists")
        secret_ref, secret_fingerprint = self._secret(secret_mode, env_name, secret_value)
        try:
            return self.registry.create_connection(
                name=name,
                base_url=base_url,
                reach=reach,
                secret_ref=secret_ref,
                secret_fingerprint=secret_fingerprint,
                actor_id=self._actor,
                at=self._clock(),
            )
        except RegistryRefused as refused:
            raise SettingsRefused(str(refused)) from None

    def replace_secret(
        self, connection_id: str, *, secret_mode: str, env_name: str = "", secret_value: str = ""
    ) -> None:
        self._require_admin()
        connection = self._connection(connection_id)
        ref, print_ = self._secret(secret_mode, env_name, secret_value)
        self._refusing(
            lambda: self.registry.replace_secret(
                connection.connection_id, ref, print_, self._clock()
            )
        )

    def set_connection_lifecycle(self, connection_id: str, lifecycle: str) -> None:
        self._require_admin()
        if lifecycle not in ("ENABLED", "DISABLED", "RETIRED"):
            raise SettingsRefused("a connection is ENABLED, DISABLED or RETIRED")
        connection = self._connection(connection_id)
        self._refusing(
            lambda: self.registry.set_connection_lifecycle(
                connection.connection_id, lifecycle, self._clock()
            )
        )

    def check_health(self, connection_id: str) -> HealthRow:
        """Whether the endpoint answers with this credential. Recorded; changes no lifecycle."""
        self._require_admin()
        connection = self._connection(connection_id)
        outcome, detail, latency, _ = self._list(connection)
        return self.registry.record_health(
            connection.connection_id,
            outcome=outcome,
            latency_ms=latency,
            detail=detail,
            at=self._clock(),
        )

    # -- 2. models --------------------------------------------------------------------------------

    def fetch_models(self, connection_id: str) -> list[ModelRow]:
        self._require_admin()
        connection = self._enabled(connection_id)
        outcome, detail, latency, names = self._list(connection)
        self.registry.record_health(
            connection.connection_id,
            outcome=outcome,
            latency_ms=latency,
            detail=detail,
            at=self._clock(),
        )
        if outcome != "REACHABLE":
            raise SettingsRefused(f"the model list could not be fetched: {outcome} {detail}")
        at = self._clock()
        return [self.registry.add_model(connection.connection_id, n, "FETCHED", at) for n in names]

    def declare_model(self, connection_id: str, model_name: str) -> ModelRow:
        self._require_admin()
        connection = self._enabled(connection_id)
        name = model_name.strip()
        if not name or len(name) > 200 or looks_like_credential(name):
            raise SettingsRefused("a model name is 1-200 characters and is not a credential")
        return self._refusing(
            lambda: self.registry.add_model(
                connection.connection_id, name, "DECLARED", self._clock()
            )
        )

    # -- 3. capability test, 4. lock --------------------------------------------------------------

    def test_model(
        self, model_profile_id: str, capabilities: Sequence[Capability] | None = None
    ) -> list[ProbeRow]:
        self._require_admin()
        model = self._model(model_profile_id)
        if model.lifecycle in ("LOCKED", "RETIRED"):
            raise SettingsRefused(
                f"model {model.model_name} is {model.lifecycle}; unlock it to test it again"
            )
        connection = self._enabled(model.connection_id)
        key = self._key(connection)
        client = self._client(connection.base_url, key, self._timeout)
        wanted = [c for c in PROBE_ORDER if capabilities is None or c in capabilities]
        rows = []
        for capability in wanted:
            result = run_probe(client, model.model_name, capability)
            clean = type(result)(
                result.capability,
                result.outcome,
                redact(result.detail, [key or ""]),
                result.latency_ms,
                result.response_digest,
            )
            rows.append(self.registry.record_probe(model.model_profile_id, clean, self._clock()))
        return rows

    def lock(self, model_profile_id: str) -> ModelRow:
        self._require_admin()
        model = self._model(model_profile_id)
        return self._refusing(
            lambda: self.registry.lock(
                model.model_profile_id, actor_id=self._actor, at=self._clock()
            )
        )

    def unlock(self, model_profile_id: str) -> None:
        self._require_admin()
        model = self._model(model_profile_id)
        self._refusing(lambda: self.registry.unlock(model.model_profile_id))

    def retire_model(self, model_profile_id: str) -> None:
        self._require_admin()
        model = self._model(model_profile_id)
        self._refusing(lambda: self.registry.retire_model(model.model_profile_id))

    # -- 5. binding, 6. readiness, 7. activation --------------------------------------------------

    def create_runtime(self, name: str, external_labels: Sequence[str]) -> RuntimeRow:
        self._require_admin()
        labels = [x for x in EXTERNAL_LABELS if x in set(external_labels)]
        if set(external_labels) - set(EXTERNAL_LABELS):
            raise SettingsRefused(
                "an external route may carry PUBLIC, INTERNAL or CONFIDENTIAL_LAB evidence; "
                "RESTRICTED_NDA never leaves this machine"
            )
        if not name.strip():
            raise SettingsRefused("a runtime needs a name")
        return self._refusing(
            lambda: self.registry.create_runtime(
                name=name.strip()[:80],
                external_labels=labels or [SensitivityLabel.PUBLIC.value],
                actor_id=self._actor,
                at=self._clock(),
            )
        )

    def bind(self, runtime_id: str, slot: LogicalSlot, model_profile_id: str) -> None:
        self._require_admin()
        self._runtime(runtime_id)
        self._model(model_profile_id)
        self._refusing(
            lambda: self.registry.bind(
                runtime_id, slot, model_profile_id, actor_id=self._actor, at=self._clock()
            )
        )

    def unbind(self, runtime_id: str, slot: LogicalSlot) -> None:
        self._require_admin()
        self._runtime(runtime_id)
        self._refusing(lambda: self.registry.unbind(runtime_id, slot))

    def readiness(self, runtime_id: str, *, live: bool = False) -> Readiness:
        """`live` first checks the health of every connection the runtime binds (recorded)."""
        runtime = self._runtime(runtime_id)
        if live:
            self._require_admin()
            bound = {
                m.connection_id
                for b in self.registry.bindings(runtime_id).values()
                if (m := self.registry.model(b.model_profile_id)) is not None
            }
            for connection_id in sorted(bound):
                self.check_health(connection_id)
        return evaluate(self.registry, runtime, secret_problem=self._secret_problem)

    def activate(self, runtime_id: str) -> Readiness:
        """Live readiness first; activation only with no blocker. The database checks again."""
        self._require_admin()
        readiness = self.readiness(runtime_id, live=True)
        if not readiness.ready:
            raise SettingsRefused("not ready: " + "; ".join(readiness.blockers))
        self._refusing(
            lambda: self.registry.activate(runtime_id, actor_id=self._actor, at=self._clock())
        )
        return readiness

    def retire_runtime(self, runtime_id: str) -> None:
        self._require_admin()
        self._runtime(runtime_id)
        self._refusing(lambda: self.registry.retire_runtime(runtime_id, self._clock()))

    # -- plumbing ---------------------------------------------------------------------------------

    def _secret(self, mode: str, env_name: str, secret_value: str) -> tuple[str | None, str | None]:
        if mode == "none":
            return None, None
        try:
            if mode == "env":
                ref = parse_secret_ref(f"env:{env_name.strip()}")
            elif mode == "store":
                ref = self._secrets.store(secret_value)
            else:
                raise SettingsRefused("the credential is none, an environment variable, or stored")
            value = self._secrets.resolve(ref)
        except (SecretError, SecretUnavailable) as refused:
            raise SettingsRefused(str(refused)) from None
        return str(ref), fingerprint(value, self.registry.salt())

    def _key(self, connection: ConnectionRow) -> str | None:
        if connection.secret_ref is None:
            return None
        try:
            return self._secrets.resolve(parse_secret_ref(connection.secret_ref))
        except (SecretError, SecretUnavailable) as unavailable:
            raise SettingsRefused(f"{connection.name}: {unavailable}") from None

    def credential_problem(self, connection: ConnectionRow) -> str | None:
        """Why this connection's credential cannot be read now, or None. A read: nothing is
        written, sent or shown of the credential itself."""
        return self._secret_problem(connection)

    def _secret_problem(self, connection: ConnectionRow) -> str | None:
        try:
            self._key(connection)
        except SettingsRefused as refused:
            return str(refused).split(": ", 1)[-1]
        return None

    def _list(self, connection: ConnectionRow) -> tuple[str, str, int | None, list[str]]:
        try:
            key = self._key(connection)
        except SettingsRefused as refused:
            return "SECRET_UNAVAILABLE", str(refused), None, []
        client = self._client(connection.base_url, key, min(self._timeout, 20.0))
        started = self._clock()
        try:
            names = client.list_models()
        except ProviderError as failed:
            return failed.failure.value, failed.detail, None, []
        latency = int((self._clock() - started).total_seconds() * 1000)
        return "REACHABLE", f"{len(names)} model(s) listed", max(latency, 0), names

    def _connection(self, connection_id: str) -> ConnectionRow:
        connection = self.registry.connection(connection_id)
        if connection is None:
            raise SettingsRefused(f"no connection {connection_id}")
        return connection

    def _enabled(self, connection_id: str) -> ConnectionRow:
        connection = self._connection(connection_id)
        if connection.lifecycle != "ENABLED":
            raise SettingsRefused(f"connection {connection.name} is {connection.lifecycle}")
        return connection

    def _model(self, model_profile_id: str) -> ModelRow:
        model = self.registry.model(model_profile_id)
        if model is None:
            raise SettingsRefused(f"no model {model_profile_id}")
        return model

    def _runtime(self, runtime_id: str) -> RuntimeRow:
        runtime = self.registry.runtime(runtime_id)
        if runtime is None:
            raise SettingsRefused(f"no runtime {runtime_id}")
        return runtime

    @staticmethod
    def _refusing(work: Callable[[], T]) -> T:
        try:
            return work()
        except RegistryRefused as refused:
            raise SettingsRefused(str(refused)) from None


# -- the active runtime, for the research service -------------------------------------------


@dataclass(frozen=True)
class _Route:
    client: OpenAICompatibleClient
    model: str


class RouteCompletion:
    """The `Completion` transport of an active runtime: `ScientificLLM` calls it, after the gates,
    with the prompt it digested; it sends that prompt to the slot's model with the role's
    response contract."""

    def __init__(self, routes: dict[LogicalSlot, _Route]) -> None:
        self._routes = routes

    def __call__(self, material: str, slot: ModelSlot) -> str:
        route = self._routes[slot.logical_slot]
        return route.client.chat(route.model, material, system=contract_for(material)).text


def load_active_runtime(
    connection: Any, secrets: SecretStore, *, timeout: float = 180.0
) -> ReasoningRuntime | None:
    registry = SqlLLMRegistry(connection)
    active = registry.active_runtime()
    if active is None:
        return None
    slots: list[ModelSlot] = []
    routes: dict[LogicalSlot, _Route] = {}
    served: dict[LogicalSlot, ModelRow] = {}
    lines: list[str] = []
    #: EXTERNAL connection id -> the provider name its `ModelSlot` records.
    external: dict[str, str] = {}
    for slot, binding in sorted(registry.bindings(active.runtime_id).items()):
        model = registry.model(binding.model_profile_id)
        connection_row = registry.connection(model.connection_id) if model is not None else None
        if model is None or connection_row is None or model.lock_fingerprint is None:
            raise RuntimeUnavailable(f"runtime {active.name}: {slot.value} has no locked model")
        if connection_row.lifecycle != "ENABLED":
            raise RuntimeUnavailable(
                f"runtime {active.name}: connection {connection_row.name} is "
                f"{connection_row.lifecycle}"
            )
        key: str | None = None
        if connection_row.secret_ref is not None:
            try:
                key = secrets.resolve(parse_secret_ref(connection_row.secret_ref))
            except (SecretError, SecretUnavailable) as unavailable:
                raise RuntimeUnavailable(
                    f"the active LLM runtime {active.name} cannot be used: "
                    f"{connection_row.name}: {unavailable}"
                ) from None
        reach = ExternalReach(connection_row.reach)
        slots.append(
            ModelSlot(
                slot,
                model.model_name,
                model.lock_fingerprint,
                provider=connection_row.name,
                reach=reach,
            )
        )
        routes[slot] = _Route(
            OpenAICompatibleClient(connection_row.base_url, key, timeout=timeout), model.model_name
        )
        served[slot] = model
        if reach is ExternalReach.EXTERNAL:
            external[connection_row.connection_id] = connection_row.name
        roles = ", ".join(r.value for r in roles_on(slot)) or "no role in this version"
        lines.append(
            f"{slot.value}: `{model.model_name}` via `{connection_row.name}` "
            f"({connection_row.reach}, route `{model.lock_fingerprint}`), serving {roles}."
        )
    critic, _ = critic_route(
        served.get(LogicalSlot.REASONING_PRIMARY), served.get(LogicalSlot.REASONING_ADVERSARIAL)
    )
    description = (
        f"Reasoner: the active LLM runtime `{active.name}` (`{active.runtime_id}`), activated by "
        f"`{active.activated_by}`. Every model call passed the budget gate, the egress gate and "
        "the typed role parsers, and is recorded in InferenceProvenance with the route below; "
        "the local catalog reasoner was not used.",
        *lines,
        f"EMBEDDING: the built-in local embedder ({BUILTIN_EMBEDDING}).",
        critic,
        egress_route(sorted(external.values()), active.external_labels),
    )
    # A global runtime supplies ROUTES, never permission. Each call's policy is the policy of the
    # project the evidence belongs to, read when the gate asks: that project's own declaration and
    # privacy mode, narrowed to these routes and to what this runtime lets any project send.
    ceiling = frozenset(SensitivityLabel(x) for x in active.external_labels)
    policies = ProjectEgressPolicies(connection)

    def policy(project_id: str) -> EgressPolicy | None:
        if not external:
            return None
        return policies.effective(project_id, routes=external, ceiling=ceiling)

    def statement(project_id: str) -> str:
        return policies.statement(project_id, routes=external, ceiling=ceiling)

    return ReasoningRuntime(
        runtime_id=active.runtime_id,
        name=active.name,
        slots=tuple(slots),
        complete=RouteCompletion(routes),
        egress_policy=policy,
        description=description,
        egress_statement=statement,
    )


__all__ = [
    "EXTERNAL_LABELS",
    "LLMSettings",
    "RouteCompletion",
    "RuntimeUnavailable",
    "SettingsRefused",
    "load_active_runtime",
]
