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
    Material,
    MemberSummary,
    ProjectDetail,
    ProjectSummary,
)
from lab_brain.accounts.service import Account
from lab_brain.interfaces.web.account_pages import state_name
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.lab_pages import levels, members_section, role_name
from lab_brain.interfaces.web.pages import Chrome, Html, cat, h, page, when
from lab_brain.interfaces.web.workspace_pages import episode_state, kind_name, outcome_name

Messages.extend(
    {
        "admin.title": ("Laboratory", "實驗室管理"),
        "admin.only": (
            "This page is for the laboratory's administrators.",
            "此頁面僅供實驗室管理員使用。",
        ),
        "admin.llm_only": (
            "AI model settings are managed by the laboratory's administrators. Whether a "
            "project's evidence may reach an external model is that project's own setting, "
            "on its page.",
            "AI 模型設定由實驗室管理員管理。研究專案證據能否送往外部模型，是該研究專案自己的設定，"
            "請到研究專案頁面查看。",
        ),
        "admin.pending": ("Waiting for your approval", "等待你核准"),
        "admin.pending.lead": (
            "These people confirmed their email address. Approve only someone you know belongs "
            "to the laboratory: an approved member can create research projects and be added to "
            "others.",
            "這些人已確認電子郵件。請只核准你確認屬於本實驗室的人：核准後即可建立研究專案，"
            "也能被加入其他研究專案。",
        ),
        "admin.pending.none": ("Nobody is waiting for approval.", "目前沒有等待核准的人。"),
        "admin.unconfirmed": (
            "Registered, email not confirmed yet ({n})",
            "已註冊、尚未確認電子郵件（{n}）",
        ),
        "admin.unconfirmed.lead": (
            "They cannot be approved until they open the link sent to their address. An "
            "unconfirmed registration holds nothing -- no name, no password -- and its link "
            "expires after 48 hours; nothing needs to be done about one you do not recognise.",
            "對方須先開啟寄到信箱的連結才能核准。未確認的註冊沒有姓名也沒有密碼，"
            "連結 48 小時後失效；不認得的註冊不需要處理。",
        ),
        "admin.approve": ("Approve", "核准"),
        "admin.reject": ("Decline", "婉拒"),
        "admin.people": ("People", "人員"),
        "admin.projects": ("Research projects", "研究專案"),
        "admin.name": ("Name", "姓名"),
        "admin.email": ("Email", "電子郵件"),
        "admin.role": ("Role", "角色"),
        "admin.state": ("State", "狀態"),
        "admin.owns": ("Projects owned", "擁有的研究專案"),
        "admin.in": ("Projects joined", "參與的研究專案"),
        "admin.research": ("Research", "研究"),
        "admin.research.count": ("Research started", "發起的研究"),
        "admin.last": ("Last research", "最近研究"),
        "admin.never": ("none yet", "尚無"),
        "admin.owners": ("Owners", "擁有者"),
        "admin.members": ("Members", "成員數"),
        "admin.open": ("Ongoing", "進行中"),
        "admin.suspend": ("Suspend", "停用"),
        "admin.suspend.reason": ("Why (kept in the account's record)", "原因（記錄在帳號紀錄中）"),
        "admin.suspend.effect": (
            "They are signed out at once and cannot sign in until reactivated. Their research "
            "and records stay as they are.",
            "對方會立即被登出，重新啟用前無法登入。其研究與紀錄維持原樣。",
        ),
        "admin.reactivate": ("Reactivate", "重新啟用"),
        "admin.make_admin": ("Make administrator", "設為管理員"),
        "admin.make_admin.effect": (
            "An administrator approves and suspends accounts, manages every research project's "
            "members, and may read any project's research -- each look is recorded and shown "
            "to that project's members. An administrator cannot change research records.",
            "管理員可核准與停用帳號、管理所有研究專案的成員，並可閱讀任何研究專案的研究內容"
            "（每次檢視都會被記錄並顯示給該研究專案成員）。管理員無法修改研究紀錄。",
        ),
        "admin.make_member": ("Make member", "改為一般成員"),
        "admin.make_member.effect": (
            "They lose administration at once; their memberships of research projects stay.",
            "對方立即失去管理權限；其研究專案成員身分不變。",
        ),
        "admin.done": ("Done.", "已完成。"),
        "admin.history": ("Account history", "帳號紀錄"),
        "admin.what": ("What happened", "事件"),
        "admin.self": (
            "This is your own account. Another administrator changes your role or state.",
            "這是你自己的帳號；你的角色或狀態需由其他管理員變更。",
        ),
        "admin.oversight_note": (
            "An administrator reads every project here in full, classified material included. "
            "Each look is recorded and shown to the project's members. Nothing here changes "
            "research.",
            "管理員可在此完整閱讀每個研究專案，包含機密分級的資料。每次檢視都會被記錄，並顯示給"
            "該研究專案成員。這裡的任何操作都不會修改研究內容。",
        ),
        "admin.export": ("Download (Markdown)", "下載（Markdown）"),
        "admin.unnamed": ("Stored by the research ({media})", "研究過程儲存（{media}）"),
        "origin.UPLOAD": ("Uploaded file", "上傳的檔案"),
        "origin.WATCHER_FILESYSTEM": ("Watched folder", "監看資料夾"),
        "origin.WATCHER_GIT": ("Watched repository", "監看儲存庫"),
        "origin.RUN_OUTPUT": ("Research run output", "研究執行的產出"),
        "origin.EXTERNAL_CONNECTOR": ("External source", "外部來源"),
        "origin.DERIVED": ("Derived by the system", "系統衍生"),
        "admin.material.unreadable": (
            "The file's stored content could not be read.",
            "無法讀取此檔案的儲存內容。",
        ),
        "admin.goal": ("Question", "研究問題"),
        "admin.opened_by": ("Started by", "發起人"),
        "admin.result": ("Result", "結果"),
        "admin.runs": ("Runs", "執行次數"),
        "admin.data": ("Research material", "研究資料"),
        "admin.data.none": ("No material has been added.", "尚未加入任何資料。"),
        "admin.research.none": ("No research has been started.", "尚未開始任何研究。"),
        "admin.projects.none": ("No research project yet.", "尚無研究專案。"),
        "admin.file": ("File", "檔案"),
        "admin.kind": ("Kind", "類型"),
        "admin.label": ("Classification", "分級"),
        "admin.by": ("By", "執行者"),
        "admin.when": ("When", "時間"),
        "admin.reports": ("Recorded reports", "已記錄的報告"),
        "admin.reports.none": (
            "No report has been recorded for this question yet.",
            "此研究問題尚未記錄任何報告。",
        ),
        "admin.report.n": ("Report {n}", "第 {n} 份報告"),
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
        "admin.since": ("Registered", "註冊時間"),
        "event.REGISTERED": ("Registered", "註冊"),
        "event.BOOTSTRAPPED": ("Created as the first administrator", "建立為第一位管理員"),
        "event.EMAIL_VERIFIED": ("Confirmed the email address", "確認電子郵件"),
        "event.APPROVED": ("Approved", "核准"),
        "event.REJECTED": ("Declined", "婉拒"),
        "event.SUSPENDED": ("Suspended", "停用"),
        "event.REACTIVATED": ("Reactivated", "重新啟用"),
        "event.ROLE_CHANGED": ("Role changed", "變更角色"),
        "event.PASSWORD_SET": ("Password set", "設定密碼"),
        "event.PASSWORD_RESET_REQUESTED": ("Asked for a password reset", "申請重設密碼"),
        "event.PASSWORD_RESET": ("Password reset", "重設密碼"),
        "event.PASSWORD_CHANGED": ("Password changed", "變更密碼"),
        "event.SIGNED_IN": ("Signed in", "登入"),
        "event.SIGN_IN_REFUSED": ("Sign-in refused", "登入失敗"),
        "event.LOCKED": ("Locked after failed attempts", "多次失敗後暫時鎖定"),
        "event.SIGNED_OUT": ("Signed out", "登出"),
        "event.PROJECT_CREATED": ("Created a research project", "建立研究專案"),
        "event.MEMBERSHIP_GRANTED": ("Added to a research project", "被加入研究專案"),
        "event.MEMBERSHIP_CHANGED": ("Access in a research project changed", "研究專案權限變更"),
        "event.MEMBERSHIP_REVOKED": ("Removed from a research project", "被移出研究專案"),
        "event.VERIFICATION_RESENT": ("Confirmation link sent again", "重新寄出確認連結"),
        "event.REGISTRATION_NOTICE": (
            "Someone tried to register this address again",
            "有人嘗試以此地址再次註冊",
        ),
        "event.MAIL_FAILED": ("A message could not be sent", "郵件寄送失敗"),
        "event.PASSWORD_CHECK_REFUSED": (
            "Wrong current password when changing it",
            "變更密碼時目前密碼錯誤",
        ),
        "event.by_operator": ("the operator's command line", "維運者命令列"),
    }
)


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
        cat(h('<th scope="col">{}</th>', c) for c in head),
        cat(h("<tr>{}</tr>", cat(h("<td>{}</td>", c) for c in row)) for row in rows),
    )


def _notices(notice: str | None, error: str | None) -> Html:
    return cat(
        [
            h('<p class="box notice" role="status">{}</p>', notice) if notice else Html(""),
            h('<p class="box error" role="alert">{}</p>', error) if error else Html(""),
        ]
    )


def _last(m: Messages, at: dt.datetime | None) -> Html | str:
    return when(at) if at is not None else m("admin.never")


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
    confirmed = [a for a in pending if a.email_verified_at is not None]
    unconfirmed = [a for a in pending if a.email_verified_at is None]

    def decide(a: Account) -> Html:
        return cat(
            [
                _post(f"/admin/accounts/{a.account_id}/approve", csrf, m("admin.approve")),
                _post(
                    f"/admin/accounts/{a.account_id}/reject",
                    csrf,
                    m("admin.reject"),
                    kind="secondary",
                ),
            ]
        )

    waiting = (
        cat(
            [
                h('<p class="muted">{}</p>', m("admin.pending.lead")),
                _table(
                    [m("admin.name"), m("admin.email"), m("admin.since"), ""],
                    [(a.display_name, a.email, when(a.created_at), decide(a)) for a in confirmed],
                ),
            ]
        )
        if confirmed
        else h('<p class="muted">{}</p>', m("admin.pending.none"))
    )
    later = (
        h(
            '<details><summary>{}</summary><p class="muted">{}</p>{}</details>',
            m("admin.unconfirmed", n=len(unconfirmed)),
            m("admin.unconfirmed.lead"),
            _table(
                [m("admin.email"), m("admin.since")],
                [(a.email, when(a.created_at)) for a in unconfirmed],
            ),
        )
        if unconfirmed
        else Html("")
    )
    people = _table(
        [
            m("admin.name"),
            m("admin.email"),
            m("admin.role"),
            m("admin.state"),
            m("admin.owns"),
            m("admin.in"),
            m("admin.research.count"),
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
                state_name(m, s.account),
                s.owned,
                s.assigned,
                s.episodes,
                _last(m, s.last_activity),
            )
            for s in members
            if s.account.status != "PENDING"
        ],
    )
    listed = (
        _table(
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
                    _last(m, p.last_activity),
                )
                for p in projects
            ],
        )
        if projects
        else h('<p class="muted">{}</p>', m("admin.projects.none"))
    )
    body = cat(
        [
            h("<h1>{}</h1>", m("admin.title")),
            _notices(notice, error),
            h("<h2>{}</h2>{}{}", m("admin.pending"), waiting, later),
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
        return h('<p class="muted">{}</p>', m("admin.research.none"))
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
                episode_state(ep.state, m),
                outcome_name(ep.outcome_status, m),
                ep.runs,
                when(ep.started),
            )
            for ep in episodes
        ],
    )


def event_name(m: Messages, kind: str) -> str:
    try:
        return m(f"event.{kind}")
    except KeyError:
        return kind


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
    if self_view:
        actions.append(h('<p class="muted">{}</p>', m("admin.self")))
    elif account.status == "ACTIVE":
        actions.append(
            h(
                '<div class="box">{}<p class="muted">{}</p></div>',
                _post(
                    f"/admin/accounts/{account.account_id}/suspend",
                    csrf,
                    m("admin.suspend"),
                    extra=h(
                        '<label>{}<br><input type="text" name="reason" required'
                        ' maxlength="300"></label> ',
                        m("admin.suspend.reason"),
                    ),
                    kind="danger",
                ),
                m("admin.suspend.effect"),
            )
        )
        target = "MEMBER" if account.system_role == "ADMIN" else "ADMIN"
        actions.append(
            h(
                '<div class="box">{}<p class="muted">{}</p></div>',
                _post(
                    f"/admin/accounts/{account.account_id}/role",
                    csrf,
                    m("admin.make_member" if target == "MEMBER" else "admin.make_admin"),
                    extra=h('<input type="hidden" name="role" value="{}">', target),
                    kind="secondary",
                ),
                m("admin.make_member.effect" if target == "MEMBER" else "admin.make_admin.effect"),
            )
        )
    elif account.status == "SUSPENDED" and account.approved_at is not None:
        actions.append(
            _post(f"/admin/accounts/{account.account_id}/reactivate", csrf, m("admin.reactivate"))
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
                state_name(m, account),
            ),
            _notices(notice, error),
            h('<div class="actions">{}</div>', cat(actions)) if actions else Html(""),
            h("<h2>{}</h2>", m("nav.projects")),
            _table(
                [m("proj.name"), m("proj.role")],
                [
                    (h('<a href="/admin/projects/{}">{}</a>', pid, name), role_name(m, role))
                    for pid, name, role in projects
                ],
            )
            if projects
            else h('<p class="muted">{}</p>', m("admin.projects.none")),
            h("<h2>{}</h2>{}", m("admin.research"), _episodes(m, episodes)),
            h(
                "<details><summary>{}</summary>{}</details>",
                m("admin.history"),
                _table(
                    [m("admin.when"), m("admin.what"), m("admin.by")],
                    [
                        (when(at), event_name(m, kind), by or m("event.by_operator"))
                        for kind, by, _d, at in history
                    ],
                ),
            ),
        ]
    )
    return page(account.display_name, body, chrome=chrome)


def project_oversight_page(
    chrome: Chrome,
    detail: ProjectDetail,
    *,
    actor_id: str,
    allowed: Sequence[str],
    notice: str | None = None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    s = detail.summary
    data = (
        _table(
            [m("admin.file"), m("admin.kind"), m("admin.label"), m("admin.by"), m("admin.when")],
            [
                (
                    h(
                        '<a href="/admin/projects/{}/artifacts/{}">{}</a>',
                        s.project_id,
                        d.artifact_id,
                        d.file_name or m("admin.unnamed", media=d.media_type),
                    ),
                    (kind_name(d.kind, m) if d.kind else m(f"origin.{d.origin}")),
                    levels(m, (d.label,) if d.label else ()),
                    d.submitted_by,
                    when(d.submitted_at),
                )
                for d in detail.data
            ],
        )
        if detail.data
        else h('<p class="muted">{}</p>', m("admin.data.none"))
    )
    colon = "：" if m.locale == "zh-TW" else ": "
    body = cat(
        [
            h('<h1>{}</h1><p class="muted">{}</p>', s.name, m("admin.oversight_note")),
            _notices(notice, error),
            h("<p>{}{}{}</p>", m("proj.privacy"), colon, m(f"proj.privacy.{s.privacy_mode}")),
            members_section(
                chrome,
                project_id=s.project_id,
                memberships=detail.memberships,
                actor_id=actor_id,
                manage=True,
                allowed=allowed,
            ),
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
    chrome: Chrome,
    *,
    episode_id: str,
    goal: str,
    project_name: str,
    reports: Sequence[tuple[int, str]],
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
            cat(
                h(
                    '<h3>{}</h3><p><a href="/admin/episodes/{}/runs/{}/report.md">{}</a></p>'
                    "<pre>{}</pre>",
                    m("admin.report.n", n=ordinal),
                    episode_id,
                    ordinal,
                    m("admin.export"),
                    text,
                )
                for ordinal, text in reports
            )
            if reports
            else h('<p class="muted">{}</p>', m("admin.reports.none")),
        ]
    )
    return page(goal, body, chrome=chrome)


def material_page(
    chrome: Chrome, *, project_id: str, project_name: str, material: Material, text: str | None
) -> bytes:
    m = chrome.m
    d = material.summary
    title = d.file_name or m("admin.unnamed", media=d.media_type)
    colon = "：" if m.locale == "zh-TW" else ": "
    body = cat(
        [
            h(
                '<h1>{}</h1><p class="muted"><a href="/admin/projects/{}">{}</a> · {}</p>',
                title,
                project_id,
                project_name,
                m("admin.oversight_note"),
            ),
            h(
                "<p>{}{}{} · {}{}{} · {}{}{} {}</p>",
                m("admin.kind"),
                colon,
                (kind_name(d.kind, m) if d.kind else m(f"origin.{d.origin}")),
                m("admin.label"),
                colon,
                levels(m, (d.label,) if d.label else ()),
                m("admin.by"),
                colon,
                d.submitted_by or "-",
                when(d.submitted_at),
            ),
            h("<pre>{}</pre>", text)
            if text is not None
            else h('<p class="box error" role="alert">{}</p>', m("admin.material.unreadable")),
            h(
                "<details><summary>{}</summary><p><code>{}</code></p></details>",
                m("details"),
                d.artifact_id,
            ),
        ]
    )
    return page(title, body, chrome=chrome)
