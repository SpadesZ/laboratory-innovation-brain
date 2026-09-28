"""Runtime readiness: what an activated runtime would actually do, said plainly.

Evaluated on the server from the rows (`012e`) and the credential store, never in a browser:

    slot by slot   which locked model serves it (endpoint, reach, route fingerprint), which roles
                   the router sends there, and what it still lacks
    the Critic     whether it has its own model route or FALLS BACK to REASONING_PRIMARY -- and a
                   fallback, or an ADVERSARIAL slot bound to the same model as PRIMARY, is shown as
                   exactly that: no model-route independence; the critique's independence then
                   rests on the inverted evidence path (§7.3, §7.6)
    EMBEDDING      the built-in local embedder
    egress         the most an EXTERNAL route may carry; each project's own policy (`012f`) decides
                   whether its evidence uses the route at all
    blockers       everything that makes activation (or use) fail closed: an unbound required slot,
                   an unlocked model, a disabled connection, an unreadable credential, a failing or
                   missing health check

`ready` is true only with no blocker. The database checks the structural half again at activation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import (
    BINDABLE_SLOTS,
    BUILTIN_EMBEDDING,
    REQUIRED_SLOTS,
    SLOT_REQUIREMENTS,
    Capability,
    critic_fallback,
    roles_on,
)
from lab_brain.llm_runtime.registry import (
    ConnectionRow,
    ModelRow,
    RuntimeRow,
    SqlLLMRegistry,
)


@dataclass(frozen=True)
class SlotReadiness:
    slot: LogicalSlot
    #: READY | MISSING | FALLBACK | BUILTIN | UNBOUND | BLOCKED
    state: str
    roles: tuple[str, ...]
    requires: tuple[str, ...]
    model: str | None = None
    connection: str | None = None
    reach: str | None = None
    route: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Readiness:
    runtime: RuntimeRow
    slots: tuple[SlotReadiness, ...]
    critic: str
    critic_independent: bool
    egress: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers


def evaluate(
    registry: SqlLLMRegistry,
    runtime: RuntimeRow,
    *,
    secret_problem: Callable[[ConnectionRow], str | None],
) -> Readiness:
    """`secret_problem` answers, for a connection, why its credential cannot be read (or None)."""
    bindings = registry.bindings(runtime.runtime_id)
    locked = [m for m in registry.models() if m.lifecycle == "LOCKED"]
    connections = {c.connection_id: c for c in registry.connections()}
    blockers: list[str] = []
    warnings: list[str] = []
    slots: list[SlotReadiness] = []
    served: dict[LogicalSlot, ModelRow] = {}

    for slot in BINDABLE_SLOTS:
        requires = tuple(sorted(c.value for c in SLOT_REQUIREMENTS[slot]))
        roles = tuple(r.value for r in roles_on(slot))
        binding = bindings.get(slot)
        if binding is None:
            eligible = [m for m in locked if _proves(m, SLOT_REQUIREMENTS[slot])]
            if slot in REQUIRED_SLOTS:
                blockers.append(f"{slot.value} is part of M3's minimum route and is not bound")
                state = "MISSING"
            elif slot is LogicalSlot.REASONING_ADVERSARIAL:
                state = "FALLBACK"
            else:
                state = "UNBOUND"
            notes = () if eligible else (f"no locked model has proven {', '.join(requires)}",)
            slots.append(SlotReadiness(slot, state, roles, requires, notes=notes))
            continue
        model = registry.model(binding.model_profile_id)
        assert model is not None  # a foreign key
        connection = connections[model.connection_id]
        problems: list[str] = []
        if model.lifecycle != "LOCKED":
            problems.append(f"model {model.model_name} is {model.lifecycle}, not LOCKED")
        if connection.lifecycle != "ENABLED":
            problems.append(f"connection {connection.name} is {connection.lifecycle}")
        if connection.secret_ref is not None:
            problem = secret_problem(connection)
            if problem is not None:
                problems.append(f"connection {connection.name}: {problem}")
        health = registry.latest_health(connection.connection_id)
        if health is None:
            problems.append(f"connection {connection.name} has never been health-checked")
        elif health.outcome != "REACHABLE":
            problems.append(
                f"connection {connection.name}'s latest health check was {health.outcome} "
                f"({health.checked_at:%Y-%m-%d %H:%M} UTC)"
            )
        slot_notes = list(problems)
        if not roles:
            slot_notes.append("configured; no role routes to this slot in this version")
        blockers.extend(f"{slot.value}: {p}" for p in problems)
        served[slot] = model
        slots.append(
            SlotReadiness(
                slot,
                "BLOCKED" if problems else "READY",
                roles,
                requires,
                model=model.model_name,
                connection=connection.name,
                reach=connection.reach,
                route=model.lock_fingerprint,
                notes=tuple(slot_notes),
            )
        )

    slots.append(
        SlotReadiness(
            LogicalSlot.EMBEDDING,
            "BUILTIN",
            tuple(r.value for r in roles_on(LogicalSlot.EMBEDDING)),
            (),
            model=BUILTIN_EMBEDDING,
            reach="LOCAL",
            notes=(
                "the built-in local embedder; provider embeddings are not wired in this version",
            ),
        )
    )

    primary = served.get(LogicalSlot.REASONING_PRIMARY)
    adversarial = served.get(LogicalSlot.REASONING_ADVERSARIAL)
    critic, critic_independent = critic_route(primary, adversarial)
    if adversarial is None:
        if primary is not None and Capability.ROLE_CRITIQUE.value not in (
            primary.locked_capabilities or ()
        ):
            blockers.append(
                "the Adversarial Critic falls back to REASONING_PRIMARY, whose model has not "
                "proven ROLE_CRITIQUE"
            )
    elif not critic_independent:
        warnings.append(critic)
    external = sorted(
        {s.connection for s in slots if s.reach == "EXTERNAL" and s.connection is not None}
    )
    egress = egress_route(external, runtime.external_labels)

    return Readiness(
        runtime=runtime,
        slots=tuple(slots),
        critic=critic,
        critic_independent=critic_independent,
        egress=egress,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def critic_route(primary: ModelRow | None, adversarial: ModelRow | None) -> tuple[str, bool]:
    """How the Adversarial Critic is routed, and whether that is a distinct MODEL route."""
    if adversarial is None:
        return (
            f"FALLBACK: REASONING_ADVERSARIAL is not bound, so the Adversarial Critic runs on "
            f"{critic_fallback().value}"
            + (f" ({primary.model_name})" if primary is not None else "")
            + ". That is NOT model-route independence: the critique's independence rests on the "
            "inverted evidence path alone.",
            False,
        )
    if primary is not None and adversarial.model_profile_id == primary.model_profile_id:
        return (
            f"REASONING_ADVERSARIAL is bound to the same locked model as REASONING_PRIMARY "
            f"({primary.model_name}): a separate slot, NOT an independent model route. The "
            "critique's independence rests on the inverted evidence path.",
            False,
        )
    return (
        f"The Adversarial Critic has its own model route: {adversarial.model_name} on "
        "REASONING_ADVERSARIAL, distinct from REASONING_PRIMARY.",
        True,
    )


def egress_route(external: Sequence[str], labels: Sequence[str]) -> str:
    if not external:
        return "Every bound model is LOCAL: no model call leaves this machine."
    return (
        f"External model routes ({', '.join(external)}) may carry at most evidence classified "
        f"{', '.join(labels)} -- and only a project's evidence, only if THAT project's own egress "
        "policy approves the route: this runtime supplies routes, not permission. Anything else "
        "is refused by the egress gate and the refusal is recorded; RESTRICTED_NDA never leaves. "
        "Each call also needs the researcher's own clearance."
    )


def _proves(model: ModelRow, required: frozenset[Capability]) -> bool:
    return {c.value for c in required} <= set(model.locked_capabilities or ())


__all__ = ["Readiness", "SlotReadiness", "critic_route", "egress_route", "evaluate"]
