"""What the AI model settings tell an administrator to do next -- `interfaces.web.llm_guide`.

The guide is presentation logic over stored rows and the server's readiness evaluation. These tests
hold its three promises without a database:

    every incomplete stage names ONE next step, in the order the workflow needs it
    no readiness blocker is ever dropped -- an unmatched rule text becomes a checklist line
    a use is offered only models that proved what it needs (the database refuses the rest)
"""

from __future__ import annotations

import datetime as dt

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.web import llm_guide
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.settings_pages import checklist, todo_text
from lab_brain.llm_runtime.capabilities import BINDABLE_SLOTS, SLOT_REQUIREMENTS, roles_on
from lab_brain.llm_runtime.readiness import Readiness
from lab_brain.llm_runtime.registry import ConnectionRow, HealthRow, ModelRow, RuntimeRow

T0 = dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
ALL = (
    "CHAT",
    "STRUCTURED_JSON",
    "ROLE_QUERY",
    "ROLE_HYPOTHESIS",
    "ROLE_SPECIALIST",
    "ROLE_CRITIQUE",
)


def _conn(
    name: str = "lab", *, reach: str = "EXTERNAL", lifecycle: str = "ENABLED"
) -> ConnectionRow:
    return ConnectionRow(
        f"llc:{name}",
        name,
        "OPENAI_COMPATIBLE",
        "http://127.0.0.1:1/v1",
        reach,
        "env:K",
        "****abcd",
        lifecycle,
        "act:a",
        T0,
        T0,
    )


def _model(name: str, lifecycle: str, caps: tuple[str, ...] = (), conn: str = "lab") -> ModelRow:
    locked = lifecycle == "LOCKED"
    return ModelRow(
        f"llm:{name}",
        f"llc:{conn}",
        name,
        "FETCHED",
        lifecycle,
        caps if locked else None,
        "lk:0" if locked else None,
        T0 if locked else None,
        "act:a" if locked else None,
        T0,
    )


def _health(outcome: str = "REACHABLE", conn: str = "lab") -> HealthRow:
    return HealthRow("hc:1", f"llc:{conn}", outcome, 5, "ok", T0)


def _runtime(state: str = "DRAFT", name: str = "config") -> RuntimeRow:
    return RuntimeRow(f"rt:{state}", name, state, ("PUBLIC",), "act:a", T0, None, None, None)


def _readiness(runtime: RuntimeRow, *blockers: str, warnings: tuple[str, ...] = ()) -> Readiness:
    return Readiness(runtime, (), "critic", False, "egress", tuple(blockers), warnings)


def _guide(
    connections=(),  # type: ignore[no-untyped-def]
    models=(),
    passed=None,
    runtimes=(),
    bindings=None,
    readiness=None,
    health=None,
    problems=None,
    active_problem=None,
) -> llm_guide.Guide:
    return llm_guide.build(
        connections=list(connections),
        health=health if health is not None else {c.connection_id: _health() for c in connections},
        credential_problems=problems or {},
        models=list(models),
        passed=passed or {},
        runtimes=list(runtimes),
        bindings=bindings or {},
        readiness=readiness,
        active_problem=active_problem,
        roles={s: tuple(r.value for r in roles_on(s)) for s in BINDABLE_SLOTS},
    )


def test_each_stage_of_the_workflow_names_one_next_step_in_order():
    conn = _conn()
    assert _guide().next_step == "llm.next.add"
    assert [t.what for t in _guide().todos] == ["llm.todo.no_connection"]

    fetched = _guide([conn], health={conn.connection_id: None})
    assert (fetched.next_step, fetched.connections[0].step) == ("llm.next.fetch", "llm.cstep.fetch")

    untested = _guide([conn], [_model("m", "DISCOVERED")])
    assert untested.next_step == "llm.next.test"

    tested = _guide([conn], [_model("m", "TESTED")], passed={"llm:m": frozenset(ALL)})
    assert tested.next_step == "llm.next.lock" and tested.next_values["model"] == "m"
    assert [t.what for t in tested.todos] == ["llm.todo.lock"]

    silent = _guide([conn], [_model("m", "TESTED")], passed={"llm:m": frozenset()})
    assert silent.next_step == "llm.next.failed", "a model that passed nothing is not confirmable"

    locked = _guide([conn], [_model("m", "LOCKED", ALL)])
    assert (locked.next_step, locked.next_values["slot"]) == (
        "llm.next.assign",
        "REASONING_PRIMARY",
    )
    assert [(t.what, t.values["slot"]) for t in locked.todos] == [
        ("llm.todo.slot_empty", "REASONING_PRIMARY"),
        ("llm.todo.slot_empty", "FAST_UTILITY"),
    ]

    draft = _runtime()
    fast_missing = _guide(
        [conn],
        [_model("m", "LOCKED", ALL)],
        runtimes=[draft],
        bindings={draft.runtime_id: {LogicalSlot.REASONING_PRIMARY: "llm:m"}},
        readiness=_readiness(draft, "FAST_UTILITY is part of M3's minimum route and is not bound"),
    )
    assert (fast_missing.next_step, fast_missing.next_values["slot"]) == (
        "llm.next.assign",
        "FAST_UTILITY",
    )
    assert fast_missing.warnings[0].what == "llm.warn.critic_fallback"

    ready = _guide(
        [conn],
        [_model("m", "LOCKED", ALL)],
        runtimes=[draft],
        bindings={draft.runtime_id: {LogicalSlot.REASONING_PRIMARY: "llm:m"}},
        readiness=_readiness(draft),
    )
    assert ready.next_step == "llm.next.apply" and ready.ready_to_apply and not ready.todos

    active = _runtime("ACTIVE", "applied")
    applied = _guide([conn], [_model("m", "LOCKED", ALL)], runtimes=[active])
    assert applied.next_step == "llm.next.applied" and not applied.todos

    broken = _guide([conn], [_model("m", "LOCKED", ALL)], runtimes=[active], active_problem="gone")
    assert broken.next_step == "llm.next.fix_active"
    assert broken.todos[0].what == "llm.todo.active_unusable"


def test_the_credential_comes_before_every_other_connection_step():
    conn = _conn()
    line = _guide([conn], [_model("m", "DISCOVERED")], problems={conn.connection_id: "unset"})
    assert line.connections[0].step == "llm.cstep.credential"
    off = _guide([_conn(lifecycle="DISABLED")], [_model("m", "DISCOVERED")])
    assert off.connections[0].step == "llm.cstep.disabled"
    down = _guide([conn], health={conn.connection_id: _health("UNREACHABLE")})
    assert down.connections[0].step == "llm.cstep.unreachable"


def test_every_readiness_blocker_becomes_a_line_and_none_is_dropped():
    known = {
        "REASONING_PRIMARY: model m is TESTED, not LOCKED": "llm.todo.not_locked",
        "FAST_UTILITY: connection lab is DISABLED": "llm.todo.conn_off",
        "FAST_UTILITY: connection lab has never been health-checked": "llm.todo.never_checked",
        "REASONING_PRIMARY: connection lab's latest health check was UNREACHABLE (x)": (
            "llm.todo.unhealthy"
        ),
        "REASONING_PRIMARY: connection lab: the environment variable K is not set": (
            "llm.todo.credential"
        ),
        "the Adversarial Critic falls back to REASONING_PRIMARY, whose model has not proven "
        "ROLE_CRITIQUE": "llm.todo.critic",
    }
    for blocker, key in known.items():
        todo = llm_guide.blocker_todo(blocker)
        assert (todo.what, todo.raw) == (key, blocker), blocker
    novel = llm_guide.blocker_todo("a rule nobody has named yet")
    assert novel.what == "llm.todo.raw" and novel.raw == "a rule nobody has named yet"

    draft = _runtime()
    guide = _guide(
        [_conn()],
        [_model("m", "LOCKED", ALL)],
        runtimes=[draft],
        readiness=_readiness(draft, "a rule nobody has named yet", *known),
    )
    assert len(guide.todos) == len(known) + 1, "every blocker is a line"
    page = str(checklist(guide.todos, Messages("zh-TW")))
    assert "a rule nobody has named yet" in page, "said as it was said, never dropped"
    assert "尚待處理" in page and "怎麼完成" in page


def test_a_use_is_offered_only_models_that_proved_what_it_needs():
    local = _conn("home", reach="LOCAL")
    remote = _conn("far")
    models = [
        _model("full", "LOCKED", ALL, conn="far"),
        _model("chat-only", "LOCKED", ("CHAT", "STRUCTURED_JSON"), conn="far"),
        _model("untested", "TESTED", conn="far"),
        _model("mine", "LOCKED", ALL, conn="home"),
    ]
    connections = {c.connection_id: c for c in (local, remote)}
    for slot in BINDABLE_SLOTS:
        offered = {m.model_name for m, _ in llm_guide.eligible(models, connections, slot)}
        need = {c.value for c in SLOT_REQUIREMENTS[slot]}
        for model in models:
            proves = model.lifecycle == "LOCKED" and need <= set(model.locked_capabilities or ())
            local_only = slot is LogicalSlot.PRIVATE_LOCAL and model.connection_id != "llc:home"
            assert (model.model_name in offered) == (proves and not local_only), (slot, model)
    disabled = {**connections, "llc:far": _conn("far", lifecycle="DISABLED")}
    assert "full" not in {
        m.model_name for m, _ in llm_guide.eligible(models, disabled, LogicalSlot.REASONING_PRIMARY)
    }


def test_the_checklist_speaks_the_researchers_words_in_both_languages():
    todo = llm_guide.Todo(
        "llm.todo.slot_empty", "llm.how.slot_empty", {"slot": "REASONING_PRIMARY"}
    )
    assert todo_text(todo, Messages("zh-TW")) == (
        "「主要推理」還沒有模型",
        "在步驟 3 替「主要推理」選一個已確認的模型，按「指派」。",
    )
    assert todo_text(todo, Messages("en"))[0] == "Primary reasoning has no model yet"
    fast = llm_guide.Todo("llm.todo.slot_empty", "llm.how.slot_empty", {"slot": "FAST_UTILITY"})
    assert todo_text(fast, Messages("zh-TW"))[0] == "「快速處理」還沒有模型"
