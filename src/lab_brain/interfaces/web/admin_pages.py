"""The laboratory overview, for administrators: who is waiting, everyone, every project.

Presentation only. Every action is a POST with the session's CSRF token, and the server decides
again whether the signed-in person may take it (`accounts.service`). Nothing here edits research:
an administrator manages accounts and membership and reads research for oversight -- each look is
recorded and shown to the project's members.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from lab_brain.accounts.oversight import (
    EpisodeSummary,
    MemberSummary,
    ProjectDetail,
    ProjectSummary,
)
from lab_brain.accounts.service import Account
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, h, page

Messages.extend(
    {
        "admin.title": ("Laboratory", "實驗室管理"),
        "admin.pending": ("Waiting for approval", "等待核准"),
        "admin.pending.none": ("Nobody is waiting for approval.", "目前沒有等待核准的人。"),
        "admin.unverified": ("not confirmed yet", "尚未確認信箱"),
        "admin.approve": ("Approve", "核准"),
        "admin.reject": ("Decline", "婉拒"),
        "admin.people": ("People", "成員"),
        "admin.projects": ("Projects", "專案"),
        "admin.name": ("Name", "姓名"),
        "admin.email": ("Email", "電子郵件"),
        "admin.role": ("Role", "角色"),
        "admin.state": ("State", "狀態"),
        "admin.owns": ("Owns", "擁有"),
        "admin.in": ("In", "參與"),
        "admin.research": ("Research", "研究"),
        "admin.last": ("Last active", "最近活動"),
        "admin.owners": ("Owners", "擁有者"),
        "admin.members": ("Members", "成員數"),
        "admin.open": ("Ongoing", "進行中"),
        "admin.suspend": ("Suspend", "停用"),
        "admin.suspend.reason": ("Why (kept in the account's record)", "原因（記錄在帳號紀錄中）"),
        "admin.reactivate": ("Reactivate", "重新啟用"),
        "admin.make_admin": ("Make administrator", "設為管理員"),
        "admin.make_member": ("Make member", "改為一般成員"),
        "admin.done": ("Done.", "已完成。"),
        "admin.history": ("Account history", "帳號紀錄"),
        "admin.oversight_note": (
            "Opening a project's research here is recorded and shown to its members. Evidence "
            "excerpts stay under the project's clearance.",
            "在此開啟專案研究會被記錄，並顯示給該專案成員。證據摘錄仍依專案分級授權顯示。",
        ),
        "admin.goal": ("Question", "研究問題"),
        "admin.opened_by": ("Started by", "發起人"),
        "admin.result": ("Latest result", "最新結果"),
        "admin.runs": ("Runs", "執行次數"),
        "admin.data": ("Research material", "研究資料"),
        "admin.file": ("File", "檔案"),
        "admin.kind": ("Kind", "類型"),
        "admin.label": ("Classification", "分級"),
        "admin.by": ("Added by", "加入者"),
        "admin.when": ("When", "時間"),
        "admin.reports": ("Recorded reports", "已記錄的報告"),
        "admin.refused.not_permitted": (
            "Only an active administrator can do that, and not to their own account.",
            "只有有效的管理員可以這樣做，且不能用於自己的帳號。",
        ),
        "admin.refused.state": (
            "The account is not in a state that allows this: {detail}",
            "帳號目前的狀態不允許此操作：{detail}",
        ),
        "admin.refused.not_verified": (
            "The person has not confirmed their address yet.",
            "對方尚未確認電子郵件。",
        ),
        "admin.refused.reason_required": (
            "Give the reason for the suspension.",
            "請填寫停用原因。",
        ),
        "admin.refused.not_found": ("No such account.", "找不到此帳號。"),
        "admin.refused.invalid_role": ("Unknown role.", "未知的角色。"),
    }
)


def _when(at: dt.datetime | None) -> str:
    return at.strftime("%Y-%m-%d %H:%M") if at else "-"


def _post(action: str, csrf: str, label: str, *, extra: Html | None = None, kind: str = "") -> Html:
    return h(
        '<form method="post" action="{}" class="inline">'
        '<input type="hidden" name="csrf" value="{}">'
        '{}<button type="submit"{}>{}</button></form>',
        action,
        csrf,
        extra if extra is not None else Html(""),
        Html(f' class="{kind}"' if kind else ""),
        label,
    )


def _table(head: Sequence[str], rows: Sequence[Sequence[object]]) -> Html:
    return h(
        '<div class="scroll"><table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></div>',
        cat(h("<th>{}</th>", c) for c in head),
        cat(h("<tr>{}</tr>", cat(h("<td>{}</td>", c) for c in row)) for row in rows),
    )


def dashboard_page(
    chrome: Chrome,
    *,
    members: Sequence[MemberSummary],
    projects: Sequence[ProjectSummary],
    notice: str | None = None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    csrf = chrome.csrf or ""
    pending = [s.account for s in members if s.account.status == "PENDING"]
    waiting = (
        _table(
            [m("admin.name"), m("admin.email"), m("admin.since"), ""],
            [
                (
                    a.display_name,
                    a.email,
                    _when(a.created_at),
                    cat(
                        [
                            _post(
                                f"/admin/accounts/{a.account_id}/approve", csrf, m("admin.approve")
                            )
                            if a.email_verified_at
                            else h('<span class="muted">{}</span>', m("admin.unverified")),
                            _post(
                                f"/admin/accounts/{a.account_id}/reject",
                                csrf,
                                m("admin.reject"),
                                kind="secondary",
                            ),
                        ]
                    ),
                )
                for a in pending
            ],
        )
        if pending
        else h('<p class="muted">{}</p>', m("admin.pending.none"))
    )
    people = _table(
        [
            m("admin.name"),
            m("admin.email"),
            m("admin.role"),
            m("admin.state"),
            m("admin.owns"),
            m("admin.in"),
            m("admin.research"),
            m("admin.last"),
        ],
        [
            (
                h(
                    '<a href="/admin/accounts/{}">{}</a>',
                    s.account.account_id,
                    s.account.display_name,
                ),
                s.account.email,
                m(f"acct.role.{s.account.system_role}"),
                m(f"acct.state.{s.account.status}"),
                s.owned,
                s.assigned,
                s.episodes,
                _when(s.last_activity),
            )
            for s in members
            if s.account.status != "PENDING"
        ],
    )
    listed = _table(
        [
            m("proj.name"),
            m("admin.owners"),
            m("admin.members"),
            m("admin.research"),
            m("admin.open"),
            m("admin.last"),
        ],
        [
            (
                h('<a href="/admin/projects/{}">{}</a>', p.project_id, p.name),
                ", ".join(p.owners) or "-",
                p.members,
                p.episodes,
                p.open_episodes,
                _when(p.last_activity),
            )
            for p in projects
        ],
    )
    body = cat(
        [
            h("<h1>{}</h1>", m("admin.title")),
            h('<p class="box notice">{}</p>', notice) if notice else Html(""),
            h('<p class="box error" role="alert">{}</p>', error) if error else Html(""),
            h("<h2>{}</h2>{}", m("admin.pending"), waiting),
            h("<h2>{}</h2>{}", m("admin.people"), people),
            h(
                '<h2>{}</h2><p class="muted">{}</p>{}',
                m("admin.projects"),
                m("admin.oversight_note"),
                listed,
            ),
        ]
    )
    return page(m("admin.title"), body, chrome=chrome)


def _episodes(m: Messages, episodes: Sequence[EpisodeSummary]) -> Html:
    if not episodes:
        return Html("<p>-</p>")
    return _table(
        [
            m("admin.goal"),
            m("admin.opened_by"),
            m("admin.state"),
            m("admin.result"),
            m("admin.runs"),
            m("admin.when"),
        ],
        [
            (
                h('<a href="/admin/episodes/{}">{}</a>', ep.episode_id, ep.goal),
                ep.opened_by,
                ep.state,
                ep.last_outcome or "-",
                ep.runs,
                _when(ep.started),
            )
            for ep in episodes
        ],
    )


def member_page(
    chrome: Chrome,
    *,
    account: Account,
    projects: Sequence[tuple[str, str, str]],
    episodes: Sequence[EpisodeSummary],
    history: Sequence[tuple[str, str | None, dict[str, object], dt.datetime]],
    self_view: bool,
    notice: str | None = None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    csrf = chrome.csrf or ""
    actions: list[Html] = []
    if not self_view:
        if account.status == "ACTIVE":
            actions.append(
                _post(
                    f"/admin/accounts/{account.account_id}/suspend",
                    csrf,
                    m("admin.suspend"),
                    extra=h(
                        '<label>{} <input type="text" name="reason" required'
                        ' maxlength="300"></label> ',
                        m("admin.suspend.reason"),
                    ),
                    kind="secondary",
                )
            )
            target = "MEMBER" if account.system_role == "ADMIN" else "ADMIN"
            actions.append(
                _post(
                    f"/admin/accounts/{account.account_id}/role",
                    csrf,
                    m("admin.make_member" if target == "MEMBER" else "admin.make_admin"),
                    extra=h('<input type="hidden" name="role" value="{}">', target),
                )
            )
        elif account.status == "SUSPENDED" and account.approved_at is not None:
            actions.append(
                _post(
                    f"/admin/accounts/{account.account_id}/reactivate", csrf, m("admin.reactivate")
                )
            )
        elif account.status in ("PENDING", "SUSPENDED") and account.email_verified_at:
            actions.append(
                _post(f"/admin/accounts/{account.account_id}/approve", csrf, m("admin.approve"))
            )
    body = cat(
        [
            h(
                "<h1>{}</h1><p>{} · {} · {}</p>",
                account.display_name,
                account.email,
                m(f"acct.role.{account.system_role}"),
                m(f"acct.state.{account.status}"),
            ),
            h('<p class="box notice">{}</p>', notice) if notice else Html(""),
            h('<p class="box error" role="alert">{}</p>', error) if error else Html(""),
            h('<div class="actions">{}</div>', cat(actions)) if actions else Html(""),
            h("<h2>{}</h2>", m("nav.projects")),
            _table(
                [m("proj.name"), m("proj.role")],
                [
                    (
                        h('<a href="/admin/projects/{}">{}</a>', pid, name),
                        m(f"proj.role.{role}") if role in ("OWNER", "MEMBER") else role,
                    )
                    for pid, name, role in projects
                ],
            )
            if projects
            else Html("<p>-</p>"),
            h("<h2>{}</h2>{}", m("admin.research"), _episodes(m, episodes)),
            h(
                "<details><summary>{}</summary>{}</details>",
                m("admin.history"),
                _table(
                    [m("admin.when"), m("admin.state"), m("admin.by")],
                    [(_when(at), kind, by or "-") for kind, by, _d, at in history],
                ),
            ),
        ]
    )
    return page(account.display_name, body, chrome=chrome)


def project_oversight_page(chrome: Chrome, detail: ProjectDetail) -> bytes:
    m = chrome.m
    s = detail.summary
    members = _table(
        [m("proj.member"), m("proj.role"), m("proj.readable")],
        [
            (
                (member.display_name or member.actor_id)
                + ("" if member.active else f" ({m('proj.inactive')})"),
                m(f"proj.role.{member.role}")
                if member.role in ("OWNER", "MEMBER")
                else member.role,
                ", ".join(m(f"label.{x}") for x in member.clearance) or "-",
            )
            for member in detail.memberships
        ],
    )
    data = (
        _table(
            [m("admin.file"), m("admin.kind"), m("admin.label"), m("admin.by"), m("admin.when")],
            [
                (d.file_name, d.kind, m(f"label.{d.label}"), d.submitted_by, _when(d.submitted_at))
                for d in detail.data
            ],
        )
        if detail.data
        else Html("<p>-</p>")
    )
    body = cat(
        [
            h('<h1>{}</h1><p class="muted">{}</p>', s.name, m("admin.oversight_note")),
            h("<p>{}: {}</p>", m("proj.privacy"), m(f"proj.privacy.{s.privacy_mode}")),
            h("<h2>{}</h2>{}", m("proj.members"), members),
            h("<h2>{}</h2>{}", m("admin.research"), _episodes(m, detail.episodes)),
            h("<h2>{}</h2>{}", m("admin.data"), data),
            h(
                "<details><summary>{}</summary><p><code>{}</code></p></details>",
                m("details"),
                s.project_id,
            ),
        ]
    )
    return page(s.name, body, chrome=chrome)


def episode_oversight_page(
    chrome: Chrome, *, goal: str, project_name: str, reports: Sequence[tuple[int, str]]
) -> bytes:
    m = chrome.m
    body = cat(
        [
            h(
                '<h1>{}</h1><p class="muted">{} · {}</p>',
                goal,
                project_name,
                m("admin.oversight_note"),
            ),
            h("<h2>{}</h2>", m("admin.reports")),
            cat(h("<h3>#{}</h3><pre>{}</pre>", ordinal, text) for ordinal, text in reports)
            if reports
            else Html("<p>-</p>"),
        ]
    )
    return page(goal, body, chrome=chrome)


Messages.extend({"admin.since": ("Registered", "註冊時間")})
