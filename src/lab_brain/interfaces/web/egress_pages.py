"""HTML for a project's own external-model egress policy (`012f`).

The deployment's LLM runtime supplies ROUTES; whether a project's evidence may use an EXTERNAL one
is that project's own decision, declared here by a member holding the `LLM_EGRESS` approval scope
and enforced by the database. Every value shown is a stored row; every button is a form the server
re-checks. Sensitivity labels and identifiers are shown as stored.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lab_brain.interfaces.web import labels
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, e, h, page, state
from lab_brain.llm_runtime.authority import LLM_EGRESS_SCOPE, ProjectEgress
from lab_brain.llm_runtime.registry import ConnectionRow

Messages.extend(
    {
        "eg.title": ("External-model egress", "外部模型外送"),
        "eg.link": ("External-model egress", "外部模型外送設定"),
        "eg.intro": (
            "Whether this project's evidence may be sent to an EXTERNAL language model. The "
            "deployment's LLM runtime supplies routes; only this project's own policy lets its "
            "evidence use one. With no policy, every external model call made for this project is "
            "refused by the egress gate and recorded. LOCAL models need no approval: nothing "
            "leaves this machine.",
            "此專案的證據是否可以送往外部語言模型。部署的 LLM 執行環境只提供路由；只有此專案自己"
            "的政策能讓它的證據使用外部路由。沒有政策時，為此專案發出的每一次外部模型呼叫都會被"
            "外送閘門拒絕並記錄。本機（LOCAL）模型不需要核准：沒有任何內容離開本機。",
        ),
        "eg.project": ("Project", "專案"),
        "eg.mode": ("Privacy mode", "隱私模式"),
        "eg.private": (
            "This project is in Private Mode: none of its evidence leaves this machine, and no "
            "external egress can be approved (§14.2). A project's privacy mode is set by the "
            "deployment's operator.",
            "此專案處於私有模式：它的證據不會離開本機，也無法核准任何外部外送（§14.2）。專案的"
            "隱私模式由部署的管理者設定。",
        ),
        "eg.current": ("Current policy", "目前政策"),
        "eg.none": (
            "No policy declared: none of this project's evidence may reach an external model.",
            "尚未宣告政策：此專案的任何證據都不會送往外部模型。",
        ),
        "eg.withdrawn": (
            "Version {version}: every approval withdrawn by {actor} ({at}). None of this "
            "project's evidence may reach an external model.",
            "第 {version} 版：{actor} 已撤回所有核准（{at}）。此專案的任何證據都不會送往外部模型。",
        ),
        "eg.approved": (
            "Version {version}, declared by {actor} ({at}): evidence classified {labels} may reach "
            "{connections}.",
            "第 {version} 版，由 {actor} 宣告（{at}）：分級為 {labels} 的證據"
            "可送往 {connections}。",
        ),
        "eg.routes": ("The active runtime's external routes", "目前啟用執行環境的外部路由"),
        "eg.no_routes": (
            "The active runtime has no external route, or no runtime is active.",
            "目前啟用的執行環境沒有外部路由，或沒有啟用任何執行環境。",
        ),
        "eg.route.approved": ("approved for this project", "此專案已核准"),
        "eg.route.refused": (
            "NOT approved: this project's evidence is refused on this route",
            "未核准：此專案的證據在此路由上會被拒絕",
        ),
        "eg.declare": ("Declare a new version", "宣告新版本"),
        "eg.declare.intro": (
            "Choose the external connections this project's evidence may reach, and the labels "
            "that may leave to them. You may authorize only labels you are cleared for in this "
            "project; RESTRICTED_NDA never leaves.",
            "選擇此專案的證據可以送往哪些外部連線，以及哪些分級可以外送。你只能核准自己在此專案中"
            "具備權限的分級；RESTRICTED_NDA 永遠不會外送。",
        ),
        "eg.connections": ("External connections", "外部連線"),
        "eg.labels": ("Labels that may leave", "可外送的分級"),
        "eg.submit": ("Declare this policy", "宣告此政策"),
        "eg.withdraw": ("Withdraw every approval", "撤回所有核准"),
        "eg.no_scope": (
            "You may read this project's policy but not declare it: that needs the {scope} "
            "approval scope in this project, granted by the deployment's operator.",
            "你可以查看此專案的政策，但不能宣告：這需要此專案的 {scope} 核准範圍，由部署的管理者"
            "授予。",
        ),
        "eg.no_connections": (
            "There is no enabled EXTERNAL connection to approve.",
            "目前沒有可核准的已啟用外部連線。",
        ),
        "eg.no_labels": (
            "You are not cleared for any label that may leave.",
            "你沒有任何可外送分級的權限。",
        ),
        "eg.history": ("History", "歷史紀錄"),
        "eg.col.version": ("Version", "版本"),
        "eg.col.by": ("Declared by", "宣告者"),
        "eg.col.when": ("When", "時間"),
        "eg.col.connections": ("Approved connections", "核准的連線"),
        "eg.col.labels": ("Labels", "分級"),
        "eg.status": ("External-model egress of your projects", "你的專案的外部模型外送"),
        "eg.status.none": ("no external egress", "不外送"),
        "eg.status.private": ("Private Mode: no egress", "私有模式：不外送"),
        "eg.status.approved": ("{labels} to {connections}", "{labels} → {connections}"),
    }
)


@dataclass(frozen=True)
class EgressView:
    project_id: str
    project_name: str
    privacy_mode: str
    history: Sequence[ProjectEgress]
    #: Every connection, by id, so a policy's approvals are named.
    connections: Mapping[str, ConnectionRow]
    #: The connection ids of the active runtime's EXTERNAL routes.
    routes: Sequence[str]
    may_declare: bool
    #: Labels this actor may authorize here: their clearance, less what never leaves.
    clearance: Sequence[str]

    @property
    def current(self) -> ProjectEgress | None:
        return self.history[0] if self.history else None


def _names(policy: ProjectEgress, connections: Mapping[str, ConnectionRow]) -> str:
    return ", ".join(
        sorted(connections[c].name if c in connections else c for c in policy.connection_ids)
    )


def summary(
    policy: ProjectEgress | None, mode: str, connections: Mapping[str, ConnectionRow], m: Messages
) -> str:
    """One line: what this project lets leave, now."""
    if mode == "PRIVATE":
        return m("eg.status.private")
    if policy is None or policy.withdrawn:
        return m("eg.status.none")
    return m(
        "eg.status.approved",
        labels=", ".join(policy.labels),
        connections=_names(policy, connections),
    )


def _current(view: EgressView, m: Messages) -> Html:
    policy = view.current
    if policy is None:
        return h('<p class="box">{}</p>', m("eg.none"))
    when = f"{policy.declared_at:%Y-%m-%d %H:%M} UTC"
    if policy.withdrawn:
        return h(
            '<p class="box">{}</p>',
            m("eg.withdrawn", version=policy.version, actor=policy.declared_by, at=when),
        )
    return h(
        '<p class="box">{}</p>',
        m(
            "eg.approved",
            version=policy.version,
            actor=policy.declared_by,
            at=when,
            labels=", ".join(policy.labels),
            connections=_names(policy, view.connections),
        ),
    )


def _routes(view: EgressView, m: Messages) -> Html:
    if not view.routes:
        return h('<p class="muted">{}</p>', m("eg.no_routes"))
    approved = set(view.current.connection_ids) if view.current is not None else set()
    if view.privacy_mode == "PRIVATE":
        approved = set()
    return h(
        "<ul>{}</ul>",
        cat(
            h(
                "<li><code>{}</code> {}</li>",
                view.connections[c].name if c in view.connections else c,
                m("eg.route.approved") if c in approved else m("eg.route.refused"),
            )
            for c in view.routes
        ),
    )


def _form(chrome: Chrome, view: EgressView) -> Html:
    m = chrome.m
    if view.privacy_mode == "PRIVATE":
        return Html("")
    if not view.may_declare:
        return h('<p class="muted">{}</p>', m("eg.no_scope", scope=LLM_EGRESS_SCOPE))
    external = sorted(
        (
            c
            for c in view.connections.values()
            if c.reach == "EXTERNAL" and c.lifecycle == "ENABLED"
        ),
        key=lambda c: c.name,
    )
    current = view.current
    chosen = set(current.connection_ids) if current is not None else set()
    allowed = set(current.labels) if current is not None else set()
    action = f"/projects/{view.project_id}/egress"
    csrf = h('<input type="hidden" name="csrf" value="{}">', chrome.csrf or "")
    boxes = (
        cat(
            h(
                '<label class="check"><input type="checkbox" name="connections" value="{}"{}> '
                '<code>{}</code> <span class="muted">{}</span></label>',
                c.connection_id,
                Html(" checked") if c.connection_id in chosen else Html(""),
                c.name,
                c.base_url,
            )
            for c in external
        )
        if external
        else h('<p class="muted">{}</p>', m("eg.no_connections"))
    )
    label_boxes = (
        cat(
            h(
                '<label class="check"><input type="checkbox" name="labels" value="{}"{}> '
                "<code>{}</code></label>",
                x,
                Html(" checked") if x in allowed else Html(""),
                x,
            )
            for x in view.clearance
        )
        if view.clearance
        else h('<p class="muted">{}</p>', m("eg.no_labels"))
    )
    return h(
        '<h2>{}</h2><p class="muted">{}</p><form method="post" action="{}">{}'
        "<label>{}</label>{}<label>{}</label>{}"
        '<button type="submit">{}</button></form>'
        '<form class="inline" method="post" action="{}">{}'
        '<input type="hidden" name="withdraw" value="yes">'
        '<button class="small" type="submit">{}</button></form>',
        m("eg.declare"),
        m("eg.declare.intro"),
        action,
        csrf,
        m("eg.connections"),
        boxes,
        m("eg.labels"),
        label_boxes,
        m("eg.submit"),
        action,
        csrf,
        m("eg.withdraw"),
    )


def _history(view: EgressView, m: Messages) -> Html:
    if not view.history:
        return Html("")
    rows = cat(
        h(
            "<tr><td>{}</td><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td></tr>",
            p.version,
            p.declared_by,
            f"{p.declared_at:%Y-%m-%d %H:%M}",
            _names(p, view.connections) or "-",
            ", ".join(p.labels) or "-",
        )
        for p in view.history
    )
    return h(
        '<h2>{}</h2><div class="scroll"><table><thead><tr><th>{}</th><th>{}</th><th>{}</th>'
        "<th>{}</th><th>{}</th></tr></thead><tbody>{}</tbody></table></div>",
        m("eg.history"),
        m("eg.col.version"),
        m("eg.col.by"),
        m("eg.col.when"),
        m("eg.col.connections"),
        m("eg.col.labels"),
        rows,
    )


def egress_page(chrome: Chrome, view: EgressView, *, error: str | None = None) -> bytes:
    m = chrome.m
    problem = (
        h(
            '<div class="box error">{}{}</div>',
            labels.humanize(error, m.locale),
            labels.technical(m.locale, [], [error]),
        )
        if error
        else Html("")
    )
    body = h(
        '<h1>{}</h1><p class="muted">{}</p>{}'
        "<p>{}: <code>{}</code> {} &middot; {}: {}</p>{}"
        "<h2>{}</h2>{}<h2>{}</h2>{}{}{}",
        m("eg.title"),
        m("eg.intro"),
        problem,
        m("eg.project"),
        view.project_id,
        e(view.project_name),
        m("eg.mode"),
        state(view.privacy_mode),
        h('<p class="box warn">{}</p>', m("eg.private"))
        if view.privacy_mode == "PRIVATE"
        else Html(""),
        m("eg.current"),
        _current(view, m),
        m("eg.routes"),
        _routes(view, m),
        _form(chrome, view),
        _history(view, m),
    )
    return page(f"{m('eg.title')}: {view.project_id}", body, chrome=chrome)


__all__ = ["EgressView", "egress_page", "summary"]
