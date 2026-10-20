"""A person's research projects, a project's overview, and the decisions waiting for them.

Presentation only. The primary view of each page says what a researcher needs in words; record
ids, codes and commands sit in a collapsed "details" block for those who need them. Classification
levels use the workspace's one vocabulary (`sens.*`), the same as the research data pages.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from lab_brain.accounts.oversight import (
    EPISODE_REPORTS,
    MATERIAL,
    MEMBER_RESEARCH,
    PROJECT_SUMMARY,
)
from lab_brain.accounts.projects import LABELS, OWNER, Membership
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, h, page, when

Messages.extend(
    {
        "proj.title": ("Research projects", "研究專案"),
        "proj.lead": (
            "The research projects you own or were added to. Only their members see their "
            "research.",
            "你擁有或被加入的研究專案。只有研究專案成員看得到其中的研究。",
        ),
        "proj.none": (
            "You are not in any research project yet. Create one, or ask a laboratory "
            "administrator to add you to one.",
            "你尚未參與任何研究專案。可以自行建立，或請實驗室管理員把你加入。",
        ),
        "proj.role.OWNER": ("Owner", "擁有者"),
        "proj.role.MEMBER": ("Member", "成員"),
        "proj.role.legacy": ("Member (recorded as “{role}”)", "成員（紀錄中的角色為「{role}」）"),
        "proj.create": ("Create a research project", "建立研究專案"),
        "proj.name": ("Research project name", "研究專案名稱"),
        "proj.clearance": (
            "Your access in this project — also the most you can give anyone in it",
            "你在此研究專案的可讀取分級（也是你能授予他人的上限）",
        ),
        "proj.clearance.hint": (
            "Tick every level this project's material may need. You cannot raise your own access "
            "later yourself; a laboratory administrator can.",
            "請勾選此研究專案資料可能需要的所有分級。之後你無法自行提高自己的權限；實驗室管理員可以。",
        ),
        "proj.private": (
            "A new project is Private: its evidence is processed only on the laboratory's Lab "
            "Brain server and never sent to an external AI model. Only the system operator can "
            "change a project's privacy mode.",
            "新研究專案為「私有」：證據只在實驗室的 Lab Brain 伺服器上處理，不會送往外部 AI 模型。"
            "只有系統維運者能變更研究專案的隱私模式。",
        ),
        "proj.created": ("Research project created.", "已建立研究專案。"),
        "proj.members": ("Members", "成員"),
        "proj.member": ("Person", "人員"),
        "proj.role": ("Role", "角色"),
        "proj.readable": ("May read", "可讀取分級"),
        "proj.actions": ("Actions", "操作"),
        "proj.you.marker": ("(you)", "（你）"),
        "proj.inactive": ("(removed)", "（已移除）"),
        "proj.add": ("Add a member", "加入成員"),
        "proj.add.email": ("Their account's email address", "對方帳號的電子郵件"),
        "proj.add.owner": (
            "Owner: declares which AI models may read this project's evidence",
            "擁有者：決定哪些 AI 模型可讀取此研究專案的證據",
        ),
        "proj.members.managed": (
            "A laboratory administrator adds, changes and removes members.",
            "成員由實驗室管理員加入、變更與移除。",
        ),
        "proj.change": ("Change access", "變更權限"),
        "proj.change.for": ("Change access for {name}", "變更 {name} 的權限"),
        "proj.change.save": ("Save access", "儲存權限"),
        "proj.added": ("Member added.", "已加入成員。"),
        "proj.changed": ("Access changed.", "已變更權限。"),
        "proj.remove": ("Remove", "移除"),
        "proj.remove.for": ("Remove {name}", "移除 {name}"),
        "proj.removed": ("Member removed.", "已移除成員。"),
        "proj.you": ("Your role and access", "你的角色與權限"),
        "proj.privacy": ("Privacy", "隱私模式"),
        "proj.privacy.PRIVATE": (
            "Private: processed only on the laboratory's server",
            "私有（只在實驗室伺服器處理）",
        ),
        "proj.privacy.RESEARCH": (
            "Research: external AI models as the project declares",
            "研究（依研究專案宣告使用外部 AI 模型）",
        ),
        "proj.privacy.NOVELTY_AUDIT": ("Novelty audit", "新穎性稽核"),
        "proj.egress": (
            "Which AI models may read this project's evidence",
            "哪些 AI 模型可讀取此研究專案的證據",
        ),
        "proj.oversight": ("Administrator views of this project", "管理員檢視此研究專案的紀錄"),
        "proj.oversight.none": (
            "No administrator has opened this project's research.",
            "沒有管理員開啟過此研究專案的研究內容。",
        ),
        "proj.oversight.summary": ("{who} opened the project summary", "{who} 開啟了研究專案摘要"),
        "proj.oversight.reports": (
            "{who} read the reports of “{question}”",
            "{who} 閱讀了「{question}」的研究報告",
        ),
        "proj.oversight.material": (
            "{who} read the file “{name}”",
            "{who} 閱讀了檔案「{name}」",
        ),
        "proj.oversight.member": (
            "{who} viewed a member's list of research",
            "{who} 檢視了某位成員的研究清單",
        ),
        "proj.not_found": (
            "No such research project, or you are not a member of it.",
            "找不到此研究專案，或你不是其成員。",
        ),
        "proj.refused.not_permitted": (
            "Only a laboratory administrator changes a research project's members.",
            "只有實驗室管理員可以變更研究專案的成員。",
        ),
        "proj.refused.clearance_required": (
            "Choose at least one classification level.",
            "請至少選擇一個分級。",
        ),
        "proj.refused.invalid_project_name": (
            "Please give the research project a name.",
            "請為研究專案命名。",
        ),
        "proj.refused.last_owner": (
            "A research project keeps at least one owner.",
            "研究專案至少要保留一位擁有者。",
        ),
        "proj.refused.not_found": (
            "No active account has that email address.",
            "沒有使用此電子郵件的有效帳號。",
        ),
        "proj.refused.already_member": (
            "That person is already a member. To change their role or access, use “Change access” "
            "in their row.",
            "對方已是此研究專案成員。若要變更角色或分級，請使用該列的「變更權限」。",
        ),
        "proj.refused.own_membership": (
            "Your own membership is changed by another laboratory administrator.",
            "你自己的成員資格，需由另一位實驗室管理員變更。",
        ),
        "proj.refused.invalid_clearance": ("Unknown classification level.", "未知的分級。"),
        "inbox.title": ("Decisions waiting for you", "等你決定的事項"),
        "inbox.lead": (
            "What the research cannot settle without you, across your research projects.",
            "研究中必須由你處理才能繼續的事項（涵蓋你參與的研究專案）。",
        ),
        "inbox.empty": ("Nothing is waiting for you.", "目前沒有等你處理的事項。"),
        "inbox.reviews": (
            "Is this observation evidence for this explanation?",
            "這項觀察能否作為此解釋的證據？",
        ),
        "inbox.reviews.lead": (
            "The system observed an outcome but cannot judge on its own whether it bears on the "
            "explanation as claimed. Your signed answer decides it.",
            "系統觀察到一個結果，但無法自行判斷它是否如所宣稱般支持（或排除）此解釋；由你簽署的回答決定。",
        ),
        "inbox.observed": ("Observed", "觀察結果"),
        "inbox.claim.SUPPORTS": (
            "{observable} = {outcome}. This is claimed to support this explanation.",
            "{observable} = {outcome}。此結果被認為支持這個解釋。",
        ),
        "inbox.claim.CONTRADICTS": (
            "{observable} = {outcome}. This is claimed to rule this explanation out.",
            "{observable} = {outcome}。此結果被認為可排除這個解釋。",
        ),
        "inbox.due": ("Answer by", "請於此時間前回答"),
        "inbox.overdue": ("Overdue", "已逾期"),
        "inbox.how": ("How to answer", "如何回答"),
        "inbox.how.meaning": (
            "Answer APPROVED if this observation really bears on the explanation as claimed; "
            "REJECTED if it does not (for example, the check cannot tell this explanation apart "
            "from the others). Your rationale is kept with the answer.",
            "若你判斷這項觀察確實如宣稱般支持（或排除）此解釋，回答 APPROVED；"
            "若不是（例如這項檢查無法"
            "區分此解釋與其他解釋），回答 REJECTED。你的理由會與回答一併保存。",
        ),
        "inbox.how.sign": (
            "Answers are signed with your reviewer key, so nobody can answer in your name. Run:",
            "回答需用你的審查金鑰簽署，別人無法冒用你的名義。請執行：",
        ),
        "inbox.how.key": (
            "You need a reviewer key enrolled in this project: create one with "
            "`lab-brain review keygen`, then ask the project's review authority to enrol it "
            "(`lab-brain review enrol`).",
            "你需要一把已在此研究專案登錄的審查金鑰：先以 `lab-brain review keygen` 產生，"
            "再請研究專案"
            "的審查授權者以 `lab-brain review enrol` 登錄。",
        ),
        "inbox.hidden": (
            "{n} question(s) in your research projects concern research classified above what "
            "you may read, or research whose classification was never recorded; they are not "
            "shown. To see them, ask a laboratory administrator to extend what you may read.",
            "你參與的研究專案中有 {n} 個問題涉及超出你可讀取分級的研究，"
            "或其分級從未記錄，因此未顯示。"
            "若需查看，請實驗室管理員擴充你的可讀取分級。",
        ),
        "inbox.not_enrolled": (
            "{n} question(s) wait for an enrolled reviewer in your research projects. You are not "
            "enrolled to answer them.",
            "你參與的研究專案中有 {n} 個問題等待已登錄的審查者回答；你尚未登錄為可回答的審查者。",
        ),
        "inbox.episodes": ("Research waiting for an action", "等待下一步的研究"),
        "inbox.episodes.lead": (
            "Research you started that stopped because it needs something only a person can do "
            "or provide.",
            "你啟動的研究因為需要只有人能做或提供的事而暫停。",
        ),
        "inbox.pending": ("People waiting for your approval", "等待你核准的人"),
        "inbox.pending.lead": (
            "{n} registration(s) confirmed their email address.",
            "{n} 位註冊者已確認電子郵件。",
        ),
        "details": ("Technical details", "技術細節"),
    }
)


def role_name(m: Messages, role: str) -> str:
    if role in ("OWNER", "MEMBER"):
        return m(f"proj.role.{role}")
    return m("proj.role.legacy", role=role)


def levels(m: Messages, labels: Sequence[str]) -> str:
    if not labels:
        return "-"
    return ("、" if m.locale == "zh-TW" else ", ").join(m(f"sens.{x}") for x in labels)


def clearance_boxes(
    m: Messages,
    *,
    allowed: Sequence[str] = LABELS,
    checked: Sequence[str] = (),
    hints: bool = False,
) -> Html:
    return cat(
        h(
            '<label class="choice"><input type="checkbox" name="clearance" value="{}"{}> {}{}'
            "</label>",
            label,
            Html(" checked" if label in checked else ""),
            m(f"sens.{label}"),
            h(' <span class="muted">— {}</span>', m(f"sens.{label}.hint")) if hints else Html(""),
        )
        for label in LABELS
        if label in allowed
    )


def _notices(notice: str | None, error: str | None) -> Html:
    return cat(
        [
            h('<p class="box notice" role="status">{}</p>', notice) if notice else Html(""),
            h('<p class="box error" role="alert">{}</p>', error) if error else Html(""),
        ]
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
                    role_name(m, role),
                )
                for pid, name, role in projects
            ),
        )
        if projects
        else h('<p class="box notice" role="status">{}</p>', m("proj.none"))
    )
    body = cat(
        [
            h("<h1>{}</h1><p>{}</p>", m("proj.title"), m("proj.lead")),
            _notices(notice, error),
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
                clearance_boxes(m, hints=True),
                m("proj.clearance.hint"),
                m("proj.private"),
                m("proj.create"),
            ),
        ]
    )
    return page(m("proj.title"), body, chrome=chrome)


def members_section(
    chrome: Chrome,
    *,
    project_id: str,
    memberships: Sequence[Membership],
    actor_id: str,
    manage: bool,
    allowed: Sequence[str],
) -> Html:
    """The member table and, for an owner or an administrator, the forms that change it: add a
    person, change a member's access, remove a member. Nobody's own row offers a change."""
    m = chrome.m
    csrf = chrome.csrf or ""
    base = f"/projects/{project_id}/members"
    owners = [x for x in memberships if x.active and x.role == OWNER]
    rows = []
    for member in memberships:
        name = member.display_name or member.actor_id
        mine = member.actor_id == actor_id
        actions = Html("")
        if manage and member.active and not mine:
            change = h(
                '<details><summary aria-label="{}">{}</summary>'
                '<form method="post" action="{}/change">'
                '<input type="hidden" name="csrf" value="{}">'
                '<input type="hidden" name="actor" value="{}"><fieldset><legend>{}</legend>{}'
                '</fieldset><p><label><input type="checkbox" name="owner" value="1"{}> {}'
                "</label></p>"
                '<p><button type="submit">{}</button></p></form></details>',
                m("proj.change.for", name=name),
                m("proj.change"),
                base,
                csrf,
                member.actor_id,
                m("proj.readable"),
                clearance_boxes(m, allowed=allowed, checked=member.clearance),
                Html(" checked" if member.role == OWNER else ""),
                m("proj.add.owner"),
                m("proj.change.save"),
            )
            last_owner = member.role == OWNER and len(owners) == 1
            remove = (
                Html("")
                if last_owner
                else h(
                    '<form method="post" action="{}/remove" class="inline">'
                    '<input type="hidden" name="csrf" value="{}">'
                    '<input type="hidden" name="actor" value="{}">'
                    '<button type="submit" class="danger" aria-label="{}">{}</button></form>',
                    base,
                    csrf,
                    member.actor_id,
                    m("proj.remove.for", name=name),
                    m("proj.remove"),
                )
            )
            actions = cat([change, remove])
        rows.append(
            (
                h(
                    "{}{}{}",
                    name,
                    h(' <span class="muted">{}</span>', m("proj.you.marker")) if mine else Html(""),
                    h(' <span class="muted">{}</span>', m("proj.inactive"))
                    if not member.active
                    else Html(""),
                ),
                role_name(m, member.role),
                levels(m, member.clearance),
                actions,
            )
        )
    table = h(
        '<div class="scroll"><table><thead><tr><th scope="col">{}</th><th scope="col">{}</th>'
        '<th scope="col">{}</th><th scope="col">{}</th></tr></thead><tbody>{}</tbody></table>'
        "</div>",
        m("proj.member"),
        m("proj.role"),
        m("proj.readable"),
        m("proj.actions"),
        cat(h("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", *r) for r in rows),
    )
    add = (
        h(
            '<h3>{}</h3><form method="post" action="{}" class="box">'
            '<input type="hidden" name="csrf" value="{}">'
            '<p><label>{}<br><input type="email" name="email" required></label></p>'
            "<fieldset><legend>{}</legend>{}</fieldset>"
            '<p><label><input type="checkbox" name="owner" value="1"> {}</label></p>'
            '<p><button type="submit">{}</button></p></form>',
            m("proj.add"),
            base,
            csrf,
            m("proj.add.email"),
            m("proj.readable"),
            clearance_boxes(m, allowed=allowed),
            m("proj.add.owner"),
            m("proj.add"),
        )
        if manage
        else h('<p class="muted">{}</p>', m("proj.members.managed"))
    )
    return h("<h2>{}</h2>{}{}", m("proj.members"), table, add)


@dataclass(frozen=True)
class ProjectOverview:
    project_id: str
    name: str
    privacy_mode: str
    created_at: dt.datetime
    memberships: Sequence[Membership]
    mine: Membership | None
    can_manage: bool
    #: (administrator, what they opened, the research question it concerns, when).
    oversight: Sequence[tuple[str, str, str, dt.datetime]]
    actor_id: str = ""


def oversight_line(m: Messages, who: str, kind: str, question: str) -> str:
    if kind == PROJECT_SUMMARY:
        return m("proj.oversight.summary", who=who)
    if kind == EPISODE_REPORTS:
        return m("proj.oversight.reports", who=who, question=question or "-")
    if kind == MATERIAL:
        return m("proj.oversight.material", who=who, name=question or "-")
    assert kind == MEMBER_RESEARCH
    return m("proj.oversight.member", who=who)


def project_page(
    chrome: Chrome, view: ProjectOverview, *, notice: str | None = None, error: str | None = None
) -> bytes:
    m = chrome.m
    allowed = LABELS if view.mine is None or chrome.admin else view.mine.clearance
    you = (
        h(
            "<p>{}：<strong>{}</strong> · {}：{}</p>"
            if m.locale == "zh-TW"
            else "<p>{}: <strong>{}</strong> · {}: {}</p>",
            m("proj.role"),
            role_name(m, view.mine.role),
            m("proj.readable"),
            levels(m, view.mine.clearance),
        )
        if view.mine is not None
        else Html("")
    )
    looked = (
        h(
            "<ul>{}</ul>",
            cat(
                h("<li>{} — {}</li>", oversight_line(m, who, kind, question), when(at))
                for who, kind, question, at in view.oversight
            ),
        )
        if view.oversight
        else h('<p class="muted">{}</p>', m("proj.oversight.none"))
    )
    colon = "：" if m.locale == "zh-TW" else ": "
    body = cat(
        [
            h("<h1>{}</h1>", view.name),
            _notices(notice, error),
            h("<h2>{}</h2>{}", m("proj.you"), you),
            h(
                '<p>{}{}{}</p><p><a href="/projects/{}/egress">{}</a></p>',
                m("proj.privacy"),
                colon,
                m(f"proj.privacy.{view.privacy_mode}"),
                view.project_id,
                m("proj.egress"),
            ),
            members_section(
                chrome,
                project_id=view.project_id,
                memberships=view.memberships,
                actor_id=view.actor_id,
                manage=view.can_manage,
                allowed=allowed,
            ),
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
    overdue: bool = False


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
    if reviews:
        parts.append(h("<h2>{}</h2><p>{}</p>", m("inbox.reviews"), m("inbox.reviews.lead")))
    for q in reviews:
        due = Html("")
        if q.due is not None:
            due = h(
                "<p>{}{}{}{}</p>",
                m("inbox.due"),
                "：" if m.locale == "zh-TW" else ": ",
                when(q.due),
                h(' <span class="badge warn">{}</span>', m("inbox.overdue"))
                if q.overdue
                else Html(""),
            )
        parts.append(
            h(
                '<section class="card"><p class="muted">{}</p><h3>{}</h3><p>{}{}{}</p>{}'
                "<details><summary>{}</summary><p>{}</p><p>{}</p><pre>{}</pre><p>{}</p>"
                "<details><summary>{}</summary><pre>{}</pre></details></details></section>",
                q.project_name,
                q.statement,
                m("inbox.observed"),
                "：" if m.locale == "zh-TW" else ": ",
                q.claim,
                due,
                m("inbox.how"),
                m("inbox.how.meaning"),
                m("inbox.how.sign"),
                q.command,
                m("inbox.how.key"),
                m("details"),
                "\n".join(q.packet),
            )
        )
    if hidden:
        parts.append(h('<p class="box notice" role="status">{}</p>', m("inbox.hidden", n=hidden)))
    if not_enrolled:
        parts.append(
            h(
                '<p class="box notice" role="status">{} {}</p>',
                m("inbox.not_enrolled", n=not_enrolled),
                m("inbox.how.key"),
            )
        )
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
        parts.append(h('<p class="box notice" role="status">{}</p>', m("inbox.empty")))
    return page(m("inbox.title"), cat(parts), chrome=chrome)


__all__ = [
    "ProjectOverview",
    "ReviewQuestion",
    "WaitingEpisode",
    "clearance_boxes",
    "inbox_page",
    "levels",
    "members_section",
    "oversight_line",
    "project_page",
    "projects_page",
    "role_name",
]
