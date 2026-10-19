"""A person's projects, a project's overview, and the decisions waiting for them.

Presentation only. The primary view of each page says what a researcher needs in words; record
ids, codes and commands sit in a collapsed "details" block for those who need them.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from lab_brain.accounts.projects import LABELS, Membership
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, h, page

Messages.extend(
    {
        "proj.title": ("Projects", "研究專案"),
        "proj.lead": (
            "The projects you own or were added to. Only their members see their research.",
            "您擁有或被加入的專案。只有專案成員看得到其中的研究。",
        ),
        "proj.none": (
            "You are not in any project yet. Create one, or ask a project's owner to add you.",
            "您尚未參與任何專案。可以自行建立，或請專案擁有者把您加入。",
        ),
        "proj.role.OWNER": ("Owner", "擁有者"),
        "proj.role.MEMBER": ("Member", "成員"),
        "proj.create": ("Create a project", "建立專案"),
        "proj.name": ("Project name", "專案名稱"),
        "proj.clearance": (
            "Which classifications may you read in it?",
            "您在此專案可讀取哪些分級？",
        ),
        "proj.clearance.hint": (
            "Research material is classified when it is added; you see what your clearance "
            "names. You can grant others at most your own.",
            "研究資料在加入時會分級；您只看得到授權範圍內的分級。您能授予他人的權限不超過您自己的。",
        ),
        "proj.private": (
            "A new project is private: nothing in it leaves this machine until its owner "
            "declares otherwise.",
            "新專案為私有：除非擁有者另行宣告，專案內容不會離開這台機器。",
        ),
        "proj.created": ("Project created.", "專案已建立。"),
        "proj.members": ("Members", "成員"),
        "proj.member": ("Person", "成員"),
        "proj.role": ("Role", "角色"),
        "proj.readable": ("May read", "可讀取"),
        "proj.inactive": ("removed", "已移除"),
        "proj.add": ("Add a member", "加入成員"),
        "proj.add.email": ("Their account's email address", "對方帳號的電子郵件"),
        "proj.add.owner": (
            "Also an owner (may add and remove members)",
            "同時設為擁有者（可加入或移除成員）",
        ),
        "proj.added": ("Member added.", "已加入成員。"),
        "proj.remove": ("Remove", "移除"),
        "proj.removed": ("Member removed.", "已移除成員。"),
        "proj.you": ("Your place in this project", "您在此專案的身分"),
        "proj.privacy": ("Privacy", "隱私模式"),
        "proj.privacy.PRIVATE": (
            "Private: nothing leaves this machine",
            "私有：資料不會離開這台機器",
        ),
        "proj.privacy.RESEARCH": (
            "Research: external models as the project declares",
            "研究：依專案宣告使用外部模型",
        ),
        "proj.privacy.NOVELTY_AUDIT": ("Novelty audit", "新穎性稽核"),
        "proj.egress": (
            "Which AI models may read this project's evidence",
            "哪些 AI 模型可讀取此專案的證據",
        ),
        "proj.oversight": ("Administrator views of this project", "管理員檢視此專案的紀錄"),
        "proj.oversight.none": (
            "No administrator has opened this project's research.",
            "沒有管理員開啟過此專案的研究內容。",
        ),
        "proj.not_found": (
            "No such project, or you are not a member of it.",
            "找不到此專案，或您不是其成員。",
        ),
        "proj.refused.not_permitted": (
            "Only an owner of this project or an administrator can do that.",
            "只有此專案的擁有者或管理員可以這樣做。",
        ),
        "proj.refused.clearance_exceeds_own": (
            "You can grant at most your own clearance in this project.",
            "您能授予的權限不超過您在此專案的權限。",
        ),
        "proj.refused.clearance_required": (
            "Choose at least one classification.",
            "請至少選擇一個分級。",
        ),
        "proj.refused.invalid_project_name": ("Please give the project a name.", "請為專案命名。"),
        "proj.refused.last_owner": (
            "A project keeps at least one owner.",
            "專案至少要保留一位擁有者。",
        ),
        "proj.refused.not_found": (
            "No active account has that address.",
            "沒有使用此地址的有效帳號。",
        ),
        "proj.refused.invalid_clearance": ("Unknown classification.", "未知的分級。"),
        "label.RESTRICTED_NDA": ("Restricted (NDA)", "限制（保密協議）"),
        "label.CONFIDENTIAL_LAB": ("Confidential (lab)", "機密（實驗室）"),
        "label.INTERNAL": ("Internal", "內部"),
        "label.PUBLIC": ("Public", "公開"),
        "inbox.title": ("Decisions waiting for you", "等您決定的事項"),
        "inbox.lead": (
            "What the research cannot settle without you, across your projects.",
            "研究中必須由您處理才能繼續的事項（涵蓋您參與的專案）。",
        ),
        "inbox.empty": ("Nothing is waiting for you.", "目前沒有等您處理的事項。"),
        "inbox.reviews": (
            "Is this observation evidence for this explanation?",
            "這項觀察能否作為此解釋的證據？",
        ),
        "inbox.reviews.lead": (
            "The system observed an outcome but cannot judge on its own whether it bears on "
            "the explanation as claimed. Your signed answer decides it.",
            "系統觀察到一個結果，但無法自行判斷它是否如所宣稱般支持（或反駁）該解釋；由您簽署的回答決定。",
        ),
        "inbox.explanation": ("Explanation", "解釋"),
        "inbox.claim": ("What is claimed", "宣稱內容"),
        "inbox.due": ("Answer by", "請於此時間前回答"),
        "inbox.claim.SUPPORTS": (
            "Observing “{outcome}” is claimed to support this explanation.",
            "宣稱：觀察到「{outcome}」支持此解釋。",
        ),
        "inbox.claim.CONTRADICTS": (
            "Observing “{outcome}” is claimed to rule this explanation out.",
            "宣稱：觀察到「{outcome}」可排除此解釋。",
        ),
        "inbox.how": ("How to answer", "如何回答"),
        "inbox.how.lead": (
            "Answers are signed with your reviewer key, on your own machine, so nobody can "
            "answer in your name. Run:",
            "回答需用您的審查金鑰在您自己的電腦上簽署，別人無法冒用您的名義。請執行：",
        ),
        "inbox.hidden": (
            "{n} question(s) in your projects concern research classified above what you may "
            "read, or research whose classification was never recorded; they are not shown.",
            "您參與的專案中有 {n} 個問題涉及超出您可讀取分級的研究，或其分級從未記錄，因此未顯示。",
        ),
        "inbox.not_enrolled": (
            "{n} question(s) wait for an enrolled reviewer in your projects. You are not "
            "enrolled to answer them.",
            "您參與的專案中有 {n} 個問題等待已登錄的審查者回答；您尚未登錄為可回答的審查者。",
        ),
        "inbox.episodes": ("Research waiting for an action", "等待下一步的研究"),
        "inbox.episodes.lead": (
            "Research you started that stopped because it needs something only a person can "
            "do or provide.",
            "您啟動的研究因為需要只有人能做或提供的事而暫停。",
        ),
        "inbox.open": ("Open", "開啟"),
        "inbox.pending": ("People waiting for your approval", "等待您核准的人"),
        "inbox.pending.lead": (
            "{n} registration(s) confirmed their address.",
            "{n} 位註冊者已確認電子郵件。",
        ),
        "details": ("Technical details", "技術細節"),
    }
)


def _labels(m: Messages, labels: Sequence[str]) -> str:
    return ", ".join(m(f"label.{x}") for x in labels) or "-"


def _clearance_boxes(
    m: Messages, *, allowed: Sequence[str] = LABELS, checked: Sequence[str] = ("INTERNAL", "PUBLIC")
) -> Html:
    return cat(
        h(
            '<label class="choice"><input type="checkbox" name="clearance" value="{}"{}> {}'
            "</label>",
            label,
            Html(" checked" if label in checked else ""),
            m(f"label.{label}"),
        )
        for label in LABELS
        if label in allowed
    )


def projects_page(
    chrome: Chrome,
    *,
    projects: Sequence[tuple[str, str, str]],
    notice: str | None = None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    listed = (
        h(
            "<ul>{}</ul>",
            cat(
                h(
                    '<li><a href="/projects/{}">{}</a> <span class="badge">{}</span></li>',
                    pid,
                    name,
                    m(f"proj.role.{role}") if role in ("OWNER", "MEMBER") else role,
                )
                for pid, name, role in projects
            ),
        )
        if projects
        else h('<p class="box notice">{}</p>', m("proj.none"))
    )
    body = cat(
        [
            h("<h1>{}</h1><p>{}</p>", m("proj.title"), m("proj.lead")),
            h('<p class="box notice">{}</p>', notice) if notice else Html(""),
            h('<p class="box error" role="alert">{}</p>', error) if error else Html(""),
            listed,
            h("<h2>{}</h2>", m("proj.create")),
            h(
                '<form method="post" action="/projects" class="box">'
                '<input type="hidden" name="csrf" value="{}">'
                '<p><label>{}<br><input type="text" name="name" required maxlength="120">'
                "</label></p>"
                '<fieldset><legend>{}</legend>{}<p class="muted">{}</p></fieldset>'
                '<p class="muted">{}</p><p><button type="submit">{}</button></p></form>',
                chrome.csrf,
                m("proj.name"),
                m("proj.clearance"),
                _clearance_boxes(m),
                m("proj.clearance.hint"),
                m("proj.private"),
                m("proj.create"),
            ),
        ]
    )
    return page(m("proj.title"), body, chrome=chrome)


@dataclass(frozen=True)
class ProjectOverview:
    project_id: str
    name: str
    privacy_mode: str
    created_at: dt.datetime
    memberships: Sequence[Membership]
    mine: Membership | None
    can_manage: bool
    oversight: Sequence[tuple[str, str, dt.datetime]]


def project_page(
    chrome: Chrome, view: ProjectOverview, *, notice: str | None = None, error: str | None = None
) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    rows = []
    for member in view.memberships:
        remove = (
            h(
                '<form method="post" action="/projects/{}/members/remove" class="inline">'
                '<input type="hidden" name="csrf" value="{}">'
                '<input type="hidden" name="actor" value="{}">'
                '<button type="submit" class="secondary">{}</button></form>',
                view.project_id,
                chrome.csrf,
                member.actor_id,
                m("proj.remove"),
            )
            if view.can_manage and member.active
            else Html("")
        )
        rows.append(
            (
                h(
                    "{}{}",
                    member.display_name or member.actor_id,
                    h(' <span class="muted">({})</span>', m("proj.inactive"))
                    if not member.active
                    else Html(""),
                ),
                m(f"proj.role.{member.role}")
                if member.role in ("OWNER", "MEMBER")
                else member.role,
                _labels(m, member.clearance),
                remove,
            )
        )
    table = h(
        '<div class="scroll"><table><thead><tr><th>{}</th><th>{}</th><th>{}</th><th></th></tr>'
        "</thead><tbody>{}</tbody></table></div>",
        m("proj.member"),
        m("proj.role"),
        m("proj.readable"),
        cat(h("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", *r) for r in rows),
    )
    allowed = LABELS if view.mine is None else view.mine.clearance
    add = (
        h(
            '<h3>{}</h3><form method="post" action="/projects/{}/members" class="box">'
            '<input type="hidden" name="csrf" value="{}">'
            '<p><label>{}<br><input type="email" name="email" required></label></p>'
            "<fieldset><legend>{}</legend>{}</fieldset>"
            '<p><label><input type="checkbox" name="owner" value="1"> {}</label></p>'
            '<p><button type="submit">{}</button></p></form>',
            m("proj.add"),
            view.project_id,
            chrome.csrf,
            m("proj.add.email"),
            m("proj.readable"),
            _clearance_boxes(m, allowed=allowed, checked=()),
            m("proj.add.owner"),
            m("proj.add"),
        )
        if view.can_manage
        else Html("")
    )
    you = (
        h(
            "<p>{}: <strong>{}</strong> · {}: {}</p>",
            m("proj.role"),
            m(f"proj.role.{view.mine.role}")
            if view.mine.role in ("OWNER", "MEMBER")
            else view.mine.role,
            m("proj.readable"),
            _labels(m, view.mine.clearance),
        )
        if view.mine is not None
        else Html("")
    )
    looked = (
        h(
            "<ul>{}</ul>",
            cat(
                h("<li>{} — {}</li>", who, at.strftime("%Y-%m-%d %H:%M"))
                for who, _s, at in view.oversight
            ),
        )
        if view.oversight
        else h('<p class="muted">{}</p>', m("proj.oversight.none"))
    )
    body = cat(
        [
            h("<h1>{}</h1>", view.name),
            h('<p class="box notice">{}</p>', notice) if notice else Html(""),
            h('<p class="box error" role="alert">{}</p>', error) if error else Html(""),
            h("<h2>{}</h2>{}", m("proj.you"), you),
            h(
                '<p>{}: {}</p><p><a href="/projects/{}/egress">{}</a></p>',
                m("proj.privacy"),
                m(f"proj.privacy.{view.privacy_mode}"),
                view.project_id,
                m("proj.egress"),
            ),
            h("<h2>{}</h2>{}{}", m("proj.members"), table, add),
            h("<h2>{}</h2>{}", m("proj.oversight"), looked),
            h(
                "<details><summary>{}</summary><p><code>{}</code></p></details>",
                m("details"),
                view.project_id,
            ),
        ]
    )
    return page(view.name, body, chrome=chrome)


@dataclass(frozen=True)
class ReviewQuestion:
    review_id: str
    project_name: str
    statement: str
    mechanism: str
    claim: str
    due: dt.datetime | None
    command: str
    packet: Sequence[str]


@dataclass(frozen=True)
class WaitingEpisode:
    episode_id: str
    project_name: str
    goal: str
    reason: str | None


def inbox_page(
    chrome: Chrome,
    *,
    reviews: Sequence[ReviewQuestion],
    hidden: int,
    not_enrolled: int,
    episodes: Sequence[WaitingEpisode],
    pending: int,
) -> bytes:
    m = chrome.m
    parts = [h("<h1>{}</h1><p>{}</p>", m("inbox.title"), m("inbox.lead"))]
    if pending:
        parts.append(
            h(
                '<h2>{}</h2><p><a href="/admin">{}</a></p>',
                m("inbox.pending"),
                m("inbox.pending.lead", n=pending),
            )
        )
    if reviews or hidden or not_enrolled:
        parts.append(h("<h2>{}</h2><p>{}</p>", m("inbox.reviews"), m("inbox.reviews.lead")))
    for q in reviews:
        parts.append(
            h(
                '<div class="card"><p class="muted">{}</p><p><strong>{}</strong>: {}</p>'
                "<p>{}: {}</p>{}"
                "<details><summary>{}</summary><p>{}</p><pre>{}</pre>"
                "<p>{}</p><pre>{}</pre></details></div>",
                q.project_name,
                m("inbox.explanation"),
                q.statement,
                m("inbox.claim"),
                q.claim,
                h("<p>{}: {}</p>", m("inbox.due"), q.due.strftime("%Y-%m-%d %H:%M UTC"))
                if q.due
                else Html(""),
                m("inbox.how"),
                m("inbox.how.lead"),
                q.command,
                m("details"),
                "\n".join(q.packet),
            )
        )
    if hidden:
        parts.append(h('<p class="box notice">{}</p>', m("inbox.hidden", n=hidden)))
    if not_enrolled:
        parts.append(h('<p class="box notice">{}</p>', m("inbox.not_enrolled", n=not_enrolled)))
    if episodes:
        parts.append(h("<h2>{}</h2><p>{}</p>", m("inbox.episodes"), m("inbox.episodes.lead")))
        parts.append(
            h(
                "<ul>{}</ul>",
                cat(
                    h(
                        '<li><a href="/episodes/{}">{}</a> <span class="muted">{} · {}</span></li>',
                        ep.episode_id,
                        ep.goal,
                        ep.project_name,
                        ep.reason or "-",
                    )
                    for ep in episodes
                ),
            )
        )
    if len(parts) == 1:
        parts.append(h('<p class="box notice">{}</p>', m("inbox.empty")))
    return page(m("inbox.title"), cat(parts), chrome=chrome)


__all__ = [
    "ProjectOverview",
    "ReviewQuestion",
    "WaitingEpisode",
    "inbox_page",
    "project_page",
    "projects_page",
]
