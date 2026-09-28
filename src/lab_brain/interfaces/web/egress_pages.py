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
        "eg.title": ("External transfer to AI APIs", "外部 AI API 傳輸設定"),
        "eg.link": ("External transfer setting", "外部傳輸設定"),
        "eg.intro": (
            "Whether this research project's evidence may be sent to an external AI API. The "
            "AI model configuration only supplies models; only this project's own setting lets "
            "its evidence reach one. With no setting, every external AI call for this project is "
            "refused and recorded. Local models need no approval: nothing leaves this machine.",
            "這個研究專案的證據能不能送往外部 AI API。AI 模型配置只提供模型；"
            "只有這個研究專案自己的設定，"
            "才能讓它的證據送往外部 API。沒有設定時，為這個研究專案發出的每一次外部 AI "
            "呼叫都會被拒絕並"
            "留下紀錄。本機模型不需要核准：資料不會離開這台電腦。",
        ),
        "eg.project": ("Research project", "研究專案"),
        "eg.mode": ("Privacy mode", "隱私模式"),
        "eg.private": (
            "This project is in Private Mode: none of its evidence leaves this machine, and no "
            "external transfer can be approved (§14.2). A project's privacy mode is set by the "
            "deployment's operator.",
            "這個研究專案處於私有模式：它的證據不會離開這台電腦，也無法核准任何外部傳輸（§14.2）。"
            "研究專案的隱私模式由部署管理者設定。",
        ),
        "eg.current": ("Current setting", "目前設定"),
        "eg.none": (
            "Nothing approved: none of this project's evidence may reach an external AI API.",
            "尚未核准：這個研究專案的任何證據都不會送往外部 AI API。",
        ),
        "eg.withdrawn": (
            "Version {version}: every approval withdrawn by {actor} ({at}). None of this "
            "project's evidence may reach an external AI API.",
            "第 {version} 版：{actor} 已撤回所有核准（{at}）。這個研究專案的任何證據都不會送往外部 "
            "AI API。",
        ),
        "eg.approved": (
            "Version {version}, set by {actor} ({at}): evidence classified {labels} may reach "
            "{connections}.",
            "第 {version} 版，由 {actor} 設定（{at}）：分級為 {labels} 的證據可以送往 {connections}"
            "。",
        ),
        "eg.routes": (
            "External APIs in the applied AI model configuration",
            "目前套用的 AI 模型配置中的外部 API",
        ),
        "eg.no_routes": (
            "The applied configuration uses no external API, or no configuration is applied.",
            "目前套用的配置沒有使用外部 API，或尚未套用任何配置。",
        ),
        "eg.route.approved": ("approved for this project", "這個研究專案已核准"),
        "eg.route.refused": (
            "NOT approved: this project's evidence is refused there",
            "未核准：這個研究專案的證據不會送到這裡",
        ),
        "eg.declare": ("Change the setting", "變更設定"),
        "eg.declare.intro": (
            "Choose the external AI APIs this project's evidence may reach, and which "
            "classifications may be sent to them. You may approve only classifications you can "
            "read in this project; NDA material never leaves.",
            "選擇這個研究專案的證據可以送往哪些外部 AI API，以及哪些分級可以送出。"
            "你只能核准自己在這個"
            "研究專案有閱讀權限的分級；保密協議（NDA）的資料永遠不會送出。",
        ),
        "eg.connections": ("External AI APIs", "外部 AI API"),
        "eg.labels": ("Classifications that may be sent", "可以送出的分級"),
        "eg.submit": ("Save this setting", "儲存這個設定"),
        "eg.withdraw": ("Withdraw every approval", "撤回所有核准"),
        "eg.no_scope": (
            "You may read this project's setting but not change it: that needs the {scope} "
            "approval in this project, granted by the deployment's operator.",
            "你可以查看這個研究專案的設定，但不能變更：需要這個研究專案的 {scope} 核准權限，"
            "由部署管理者授予。",
        ),
        "eg.no_connections": (
            "There is no external AI API connection in use to approve.",
            "目前沒有使用中的外部 AI API 連線可以核准。",
        ),
        "eg.no_labels": (
            "You cannot read any classification that may be sent.",
            "你沒有任何可送出分級的閱讀權限。",
        ),
        "eg.history": ("History", "變更紀錄"),
        "eg.col.version": ("Version", "版本"),
        "eg.col.by": ("Set by", "設定者"),
        "eg.col.when": ("When", "時間"),
        "eg.col.connections": ("Approved APIs", "核准的 API"),
        "eg.col.labels": ("Classifications", "分級"),
        "eg.status": (
            "External transfer of your research projects",
            "你的研究專案的外部傳輸",
        ),
        "eg.status.none": ("nothing is sent to external APIs", "不送往外部 API"),
        "eg.status.private": ("Private Mode: nothing is sent", "私有模式：不送出任何資料"),
        "eg.status.approved": ("{labels} to {connections}", "{labels} → {connections}"),
        "eg.mode.PRIVATE": ("Private Mode", "私有模式"),
        "eg.mode.RESEARCH": ("Research mode", "研究模式"),
        "eg.mode.NOVELTY_AUDIT": ("Novelty audit mode", "新穎性稽核模式"),
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


def label_names(values: Sequence[str], m: Messages) -> str:
    """Sensitivity labels in the researcher's words (the stored value where there is no name)."""
    names = []
    for value in values:
        try:
            names.append(m(f"sens.{value}"))
        except KeyError:
            names.append(value)
    return ("、" if m.locale == "zh-TW" else ", ").join(names)


def mode_name(mode: str, m: Messages) -> Html:
    try:
        return h(
            '<span class="state state-{}" title="{}">{}</span>', mode, mode, m(f"eg.mode.{mode}")
        )
    except KeyError:
        return state(mode)


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
        labels=label_names(policy.labels, m),
        connections=_names(policy, connections),
    )


def _current(view: EgressView, m: Messages) -> Html:
    policy = view.current
    if policy is None:
        return h('<p class="box">{}</p>', m("eg.none"))
    when = f"{policy.declared_at.astimezone():%Y-%m-%d %H:%M}"
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
            labels=label_names(policy.labels, m),
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
                '<span title="{}">{}</span></label>',
                x,
                Html(" checked") if x in allowed else Html(""),
                x,
                label_names([x], m),
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
            label_names(p.labels, m) or "-",
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
        "<p>{}: {} &middot; {}: {}</p>{}"
        "<h2>{}</h2>{}<h2>{}</h2>{}{}{}",
        m("eg.title"),
        m("eg.intro"),
        problem,
        m("eg.project"),
        e(view.project_name),
        m("eg.mode"),
        mode_name(view.privacy_mode, m),
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
    return page(f"{m('eg.title')}: {view.project_name}", body, chrome=chrome)


__all__ = ["EgressView", "egress_page", "label_names", "mode_name", "summary"]
