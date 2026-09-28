"""What the AI model administrator should do next -- computed from the rows, never decided here.

PC-MEF's operator guidance, over Laboratory Brain's own architecture:

    add a model connection -> get its models -> test one -> confirm it (lock)
      -> assign confirmed models to uses (CognitiveRole -> LogicalSlot -> Model)
      -> check the configuration -> apply it

This module is presentation logic and nothing else. Every fact it reads is a stored row or the
server's own readiness evaluation (`llm_runtime.readiness`), passed in as data; every sentence it
chooses is a message key the pages render; every raw rule text it could not name is kept, verbatim,
for the technical details. It never grants, binds, locks or activates: the settings service does,
and the database checks again. It only answers "what is missing, and how is it done".

A readiness blocker it cannot match is NOT dropped: it becomes a checklist item carrying the rule
text as it was said. A checklist that silently omitted a blocker would say "nothing left" while
activation fails -- the one inconsistency no operator can debug.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import BINDABLE_SLOTS, REQUIRED_SLOTS, SLOT_REQUIREMENTS
from lab_brain.llm_runtime.readiness import Readiness
from lab_brain.llm_runtime.registry import ConnectionRow, HealthRow, ModelRow, RuntimeRow

#: The uses shown in the main assignment table, in the order they matter. CODE and VISION have no
#: role routed to them in this version; they stay under the advanced details.
MAIN_SLOTS: tuple[LogicalSlot, ...] = (
    LogicalSlot.REASONING_PRIMARY,
    LogicalSlot.FAST_UTILITY,
    LogicalSlot.REASONING_ADVERSARIAL,
    LogicalSlot.PRIVATE_LOCAL,
)


@dataclass(frozen=True)
class Todo:
    """One line of "still to do / how": two message keys, their values, and the server's own
    words when the line came from a rule it said."""

    what: str
    how: str
    values: Mapping[str, str] = field(default_factory=dict)
    raw: str | None = None


@dataclass(frozen=True)
class ModelLine:
    model: ModelRow
    #: Capabilities whose latest probe passed (what a lock would freeze).
    passed: frozenset[str]


@dataclass(frozen=True)
class ConnectionLine:
    connection: ConnectionRow
    health: HealthRow | None
    credential_problem: str | None
    models: tuple[ModelLine, ...]
    #: The connection's own next step: a message key (see `connection_step`).
    step: str
    #: The model the next step is about (the one to test, or to confirm), if any.
    focus: ModelRow | None


@dataclass(frozen=True)
class SlotLine:
    slot: LogicalSlot
    required: bool
    roles: tuple[str, ...]
    #: The model the shown configuration assigns to this use, if any.
    bound: ModelRow | None
    #: Confirmed models that proved what this use needs: (model, connection name).
    options: tuple[tuple[ModelRow, str], ...]


@dataclass(frozen=True)
class Guide:
    connections: tuple[ConnectionLine, ...]
    #: The configuration being edited (the newest DRAFT), if any.
    draft: RuntimeRow | None
    readiness: Readiness | None
    #: The applied configuration (ACTIVE), and why it cannot be used, if it cannot.
    active: RuntimeRow | None
    active_problem: str | None
    slots: tuple[SlotLine, ...]
    todos: tuple[Todo, ...]
    warnings: tuple[Todo, ...]
    #: The one thing to do next: a message key and its values.
    next_step: str
    next_values: Mapping[str, str]

    @property
    def ready_to_apply(self) -> bool:
        return self.draft is not None and self.readiness is not None and self.readiness.ready


def eligible(
    models: Sequence[ModelRow], connections: Mapping[str, ConnectionRow], slot: LogicalSlot
) -> tuple[tuple[ModelRow, str], ...]:
    """Confirmed models that proved what `slot` needs, on an enabled connection -- PRIVATE_LOCAL
    only on a LOCAL one. The database refuses any other binding; this only avoids offering it."""
    need = {c.value for c in SLOT_REQUIREMENTS[slot]}
    out = []
    for model in models:
        conn = connections.get(model.connection_id)
        if (
            model.lifecycle != "LOCKED"
            or conn is None
            or conn.lifecycle != "ENABLED"
            or not need <= set(model.locked_capabilities or ())
            or (slot is LogicalSlot.PRIVATE_LOCAL and conn.reach != "LOCAL")
        ):
            continue
        out.append((model, conn.name))
    return tuple(sorted(out, key=lambda pair: (pair[1], pair[0].model_name)))


def connection_step(
    connection: ConnectionRow,
    health: HealthRow | None,
    credential_problem: str | None,
    models: Sequence[ModelLine],
) -> tuple[str, ModelRow | None]:
    """The connection's next step, in the order the workflow needs them. The credential comes
    first: with an unreadable key every later step fails with a provider error that does not say
    why."""
    live = [x for x in models if x.model.lifecycle != "RETIRED"]
    if connection.lifecycle == "RETIRED":
        return "llm.cstep.retired", None
    if connection.lifecycle == "DISABLED":
        return "llm.cstep.disabled", None
    if credential_problem:
        return "llm.cstep.credential", None
    if not live:
        if health is not None and health.outcome != "REACHABLE":
            return "llm.cstep.unreachable", None
        return "llm.cstep.fetch", None
    if any(x.model.lifecycle == "LOCKED" for x in live):
        return "llm.cstep.done", None
    tested = [x for x in live if x.model.lifecycle == "TESTED"]
    if tested:
        with_chat = [x for x in tested if "CHAT" in x.passed]
        if with_chat:
            return "llm.cstep.lock", with_chat[0].model
        return "llm.cstep.failed", tested[0].model
    return "llm.cstep.test", None


# -- readiness blockers, in words ----------------------------------------------------------------
#
# Matched loosely on purpose: a rule text these do not match is shown as it was said, never
# dropped (see the module docstring).

_SLOT = "|".join(s.value for s in BINDABLE_SLOTS)
_NOT_BOUND = re.compile(rf"^({_SLOT}) is part of M3's minimum route and is not bound$")
_NOT_LOCKED = re.compile(rf"^({_SLOT}): model (.+) is (\w+), not LOCKED$")
_CONN_STATE = re.compile(rf"^({_SLOT}): connection (\S+) is (DISABLED|RETIRED)$")
_NEVER_CHECKED = re.compile(rf"^({_SLOT}): connection (\S+) has never been health-checked$")
_UNHEALTHY = re.compile(rf"^({_SLOT}): connection (\S+)'s latest health check was (\w+)")
_CREDENTIAL = re.compile(rf"^({_SLOT}): connection (\S+): (.+)$")
_CRITIC = re.compile(r"^the Adversarial Critic falls back to REASONING_PRIMARY")


def blocker_todo(blocker: str) -> Todo:
    """One readiness blocker as a checklist line; the rule text is kept either way."""
    if m := _NOT_BOUND.match(blocker):
        return Todo("llm.todo.slot_empty", "llm.how.slot_empty", {"slot": m.group(1)}, blocker)
    if m := _NOT_LOCKED.match(blocker):
        return Todo(
            "llm.todo.not_locked",
            "llm.how.not_locked",
            {"slot": m.group(1), "model": m.group(2)},
            blocker,
        )
    if m := _CONN_STATE.match(blocker):
        return Todo(
            "llm.todo.conn_off",
            "llm.how.conn_off",
            {"slot": m.group(1), "connection": m.group(2)},
            blocker,
        )
    if m := _NEVER_CHECKED.match(blocker):
        return Todo(
            "llm.todo.never_checked",
            "llm.how.never_checked",
            {"slot": m.group(1), "connection": m.group(2)},
            blocker,
        )
    if m := _UNHEALTHY.match(blocker):
        return Todo(
            "llm.todo.unhealthy",
            "llm.how.unhealthy",
            {"slot": m.group(1), "connection": m.group(2), "outcome": m.group(3)},
            blocker,
        )
    if m := _CREDENTIAL.match(blocker):
        return Todo(
            "llm.todo.credential",
            "llm.how.credential",
            {"slot": m.group(1), "connection": m.group(2)},
            blocker,
        )
    if _CRITIC.match(blocker):
        return Todo("llm.todo.critic", "llm.how.critic", {}, blocker)
    return Todo("llm.todo.raw", "llm.how.raw", {"text": blocker}, blocker)


def build(
    *,
    connections: Sequence[ConnectionRow],
    health: Mapping[str, HealthRow | None],
    credential_problems: Mapping[str, str | None],
    models: Sequence[ModelRow],
    passed: Mapping[str, frozenset[str]],
    runtimes: Sequence[RuntimeRow],
    bindings: Mapping[str, Mapping[LogicalSlot, str]],
    readiness: Readiness | None,
    active_problem: str | None,
    roles: Mapping[LogicalSlot, tuple[str, ...]],
) -> Guide:
    """`readiness`: the evaluation of the newest DRAFT configuration (None without one)."""
    shown = [c for c in connections if c.lifecycle != "RETIRED"]
    by_id = {c.connection_id: c for c in connections}
    lines = []
    for conn in shown:
        own = tuple(
            ModelLine(x, passed.get(x.model_profile_id, frozenset()))
            for x in models
            if x.connection_id == conn.connection_id and x.lifecycle != "RETIRED"
        )
        step, focus = connection_step(
            conn, health.get(conn.connection_id), credential_problems.get(conn.connection_id), own
        )
        lines.append(
            ConnectionLine(
                conn,
                health.get(conn.connection_id),
                credential_problems.get(conn.connection_id),
                own,
                step,
                focus,
            )
        )
    draft = next((r for r in runtimes if r.state == "DRAFT"), None)
    active = next((r for r in runtimes if r.state == "ACTIVE"), None)
    shown_runtime = draft or active
    bound_ids = bindings.get(shown_runtime.runtime_id, {}) if shown_runtime is not None else {}
    model_by_id = {x.model_profile_id: x for x in models}
    slots = tuple(
        SlotLine(
            slot,
            slot in REQUIRED_SLOTS,
            roles.get(slot, ()),
            model_by_id.get(bound_ids[slot]) if slot in bound_ids else None,
            eligible(models, by_id, slot),
        )
        for slot in BINDABLE_SLOTS
    )
    locked = [x for x in models if x.lifecycle == "LOCKED"]

    todos: list[Todo] = []
    warnings: list[Todo] = []
    if not shown:
        todos.append(Todo("llm.todo.no_connection", "llm.how.no_connection"))
    elif not locked:
        for line in lines:
            if line.step in ("llm.cstep.done", "llm.cstep.retired"):
                continue
            todos.append(
                Todo(
                    f"llm.todo.{line.step.rsplit('.', 1)[1]}",
                    f"llm.how.{line.step.rsplit('.', 1)[1]}",
                    {
                        "connection": line.connection.name,
                        "model": line.focus.model_name if line.focus is not None else "",
                    },
                )
            )
    if locked:
        for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
            line_ = next(s for s in slots if s.slot is slot)
            if not line_.options and line_.bound is None:
                todos.append(
                    Todo("llm.todo.no_candidate", "llm.how.no_candidate", {"slot": slot.value})
                )

    editing = draft is not None or active is None
    if editing:
        # What the configuration being built still lacks. Without a draft there is no readiness
        # yet: the two required uses are what it would say first.
        if readiness is not None:
            for blocker in readiness.blockers:
                todo = blocker_todo(blocker)
                if todo.what == "llm.todo.slot_empty" and any(
                    t.what == "llm.todo.no_candidate"
                    and t.values.get("slot") == todo.values["slot"]
                    for t in todos
                ):
                    continue
                todos.append(todo)
            warnings.extend(Todo("llm.warn.raw", "", {"text": w}, w) for w in readiness.warnings)
        elif locked:
            for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
                if not any(
                    t.what == "llm.todo.no_candidate" and t.values.get("slot") == slot.value
                    for t in todos
                ):
                    todos.append(
                        Todo("llm.todo.slot_empty", "llm.how.slot_empty", {"slot": slot.value})
                    )
    if active is not None and active_problem:
        todos.insert(
            0,
            Todo(
                "llm.todo.active_unusable",
                "llm.how.active_unusable",
                {"name": active.name, "reason": active_problem},
                active_problem,
            ),
        )
    primary = next(s for s in slots if s.slot is LogicalSlot.REASONING_PRIMARY)
    critic = next(s for s in slots if s.slot is LogicalSlot.REASONING_ADVERSARIAL)
    if primary.bound is not None and critic.bound is None:
        warnings.insert(0, Todo("llm.warn.critic_fallback", "llm.how.critic_fallback"))

    next_step, values = _next(lines, locked, draft, active, active_problem, readiness, todos)
    return Guide(
        connections=tuple(lines),
        draft=draft,
        readiness=readiness,
        active=active,
        active_problem=active_problem,
        slots=slots,
        todos=tuple(todos),
        warnings=tuple(warnings),
        next_step=next_step,
        next_values=values,
    )


def _next(
    lines: Sequence[ConnectionLine],
    locked: Sequence[ModelRow],
    draft: RuntimeRow | None,
    active: RuntimeRow | None,
    active_problem: str | None,
    readiness: Readiness | None,
    todos: Sequence[Todo],
) -> tuple[str, Mapping[str, str]]:
    """The single next step the page leads with."""
    if active is not None and active_problem and draft is None:
        return "llm.next.fix_active", {"name": active.name}
    if not lines:
        return "llm.next.add", {}
    if not locked:
        line = next(
            (x for x in lines if x.step not in ("llm.cstep.done", "llm.cstep.retired")), lines[0]
        )
        return f"llm.next.{line.step.rsplit('.', 1)[1]}", {
            "connection": line.connection.name,
            "model": line.focus.model_name if line.focus is not None else "",
        }
    if draft is None and active is not None:
        return "llm.next.applied", {"name": active.name}
    if readiness is not None and readiness.ready:
        return "llm.next.apply", {"name": draft.name if draft is not None else ""}
    first = next((t for t in todos), None)
    if first is None:
        return "llm.next.assign", {"slot": LogicalSlot.REASONING_PRIMARY.value}
    if first.what in ("llm.todo.slot_empty", "llm.todo.no_candidate"):
        return (
            "llm.next.assign" if first.what == "llm.todo.slot_empty" else "llm.next.confirm_for",
            {"slot": first.values["slot"]},
        )
    if first.what in ("llm.todo.never_checked", "llm.todo.unhealthy"):
        return "llm.next.check", {}
    return "llm.next.todo", {}


__all__ = [
    "MAIN_SLOTS",
    "ConnectionLine",
    "Guide",
    "ModelLine",
    "SlotLine",
    "Todo",
    "blocker_todo",
    "build",
    "connection_step",
    "eligible",
]
