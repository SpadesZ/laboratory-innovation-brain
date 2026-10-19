"""Signing in, registering, confirming an address, recovering a password, and one's own account.

Presentation only, escaped by construction (`pages.h`). Every form posts to this workspace with its
CSRF token; a link from an email (`/verify`, `/password/reset`) shows a form, and only the form's
POST uses the token -- a mail scanner's GET consumes nothing.
"""

from __future__ import annotations

import datetime as dt

from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, e, h, page, when_text

Messages.extend(
    {
        "acct.sign_in": ("Sign in", "登入"),
        "acct.sign_out": ("Sign out", "登出"),
        "acct.register": ("Create an account", "註冊帳號"),
        "acct.email": ("Email address", "電子郵件"),
        "acct.email.hint": (
            "A university or a personal address; you confirm it by a link we send there.",
            "可使用學校或個人信箱；我們會寄確認連結到這個地址。",
        ),
        "acct.name": ("Your name", "您的姓名"),
        "acct.password": ("Password", "密碼"),
        "acct.password.new": ("New password", "新密碼"),
        "acct.password.current": ("Current password", "目前密碼"),
        "acct.password.hint": (
            "At least 12 characters. A few unrelated words make a strong one.",
            "至少 12 個字元；幾個不相關的詞組合起來就很安全。",
        ),
        "acct.no_account": ("No account yet?", "還沒有帳號？"),
        "acct.have_account": ("Already registered?", "已經註冊了？"),
        "acct.forgot": ("Forgot your password?", "忘記密碼？"),
        "acct.forgot.title": ("Reset your password", "重設密碼"),
        "acct.forgot.lead": (
            "Enter your address. If it has a confirmed account, we send a link that works once, "
            "for 30 minutes.",
            "請輸入您的電子郵件。若該地址有已確認的帳號，我們會寄出一次性連結，30 分鐘內有效。",
        ),
        "acct.forgot.send": ("Send the link", "寄出連結"),
        "acct.forgot.sent": (
            "If that address has a confirmed account, a reset link is on its way. Check your "
            "inbox (and spam folder).",
            "若該地址有已確認的帳號，重設連結已寄出。請查看收件匣（以及垃圾郵件）。",
        ),
        "acct.reset.title": ("Choose a new password", "設定新密碼"),
        "acct.reset.save": ("Save the new password", "儲存新密碼"),
        "acct.reset.done": (
            "Your password is set. Every earlier sign-in has ended; sign in with the new one.",
            "密碼已設定。之前所有的登入都已結束，請用新密碼登入。",
        ),
        "acct.registered": (
            "Thank you. If the address can be registered, a confirmation link is on its way. "
            "After you confirm it, an administrator reviews your account; you can sign in once "
            "it is approved.",
            "謝謝。若此地址可以註冊，確認連結已寄出。確認後由管理員審核帳號，核准後即可登入。",
        ),
        "acct.verify.title": ("Confirm your email address", "確認電子郵件"),
        "acct.verify.lead": (
            "Confirm this address for your Lab Brain account.",
            "確認此地址屬於您的 Lab Brain 帳號。",
        ),
        "acct.verify.button": ("Confirm my address", "確認我的地址"),
        "acct.verify.done": (
            "Your address is confirmed. An administrator now reviews your account; you will "
            "be able to sign in once it is approved.",
            "地址已確認。接下來由管理員審核帳號，核准後即可登入。",
        ),
        "acct.link_invalid": (
            "This link has expired or has been used. Ask for a new one.",
            "此連結已過期或已使用，請重新申請。",
        ),
        "acct.refused.sign_in_refused": (
            "Not signed in: the address or password is wrong, or the account is temporarily "
            "locked after several attempts. Try again later, or reset your password.",
            "未能登入：電子郵件或密碼不正確，或帳號因多次嘗試而暫時鎖定。請稍後再試，或重設密碼。",
        ),
        "acct.refused.awaiting_verification": (
            "Your address is not confirmed yet. Open the link we sent you.",
            "您的地址尚未確認，請開啟我們寄給您的連結。",
        ),
        "acct.refused.awaiting_approval": (
            "Your address is confirmed; an administrator has not approved the account yet.",
            "地址已確認；管理員尚未核准此帳號。",
        ),
        "acct.refused.suspended": (
            "This account is suspended. Contact the laboratory's administrator.",
            "此帳號已停用，請聯絡實驗室管理員。",
        ),
        "acct.refused.mail_unavailable": (
            "This workspace cannot send email yet, so registration and password reset are "
            "closed. An administrator must configure mail first.",
            "此工作區尚未設定郵件，因此暫停註冊與重設密碼。請管理員先完成郵件設定。",
        ),
        "acct.refused.mail_failed": (
            "The message could not be sent. Nothing was registered; try again later.",
            "郵件無法寄出，未建立任何資料，請稍後再試。",
        ),
        "acct.refused.invalid_email": (
            "That is not an email address.",
            "這不是有效的電子郵件地址。",
        ),
        "acct.refused.invalid_name": ("Please give your name.", "請填寫姓名。"),
        "acct.refused.weak_password": (
            "That password is too weak: {detail}.",
            "密碼強度不足：{detail}。",
        ),
        "acct.refused.wrong_password": ("The current password is not right.", "目前密碼不正確。"),
        "acct.refused.token_invalid": (
            "This link has expired or has been used. Ask for a new one.",
            "此連結已過期或已使用，請重新申請。",
        ),
        "acct.refused.passwords_differ": ("The two passwords differ.", "兩次輸入的密碼不一致。"),
        "acct.repeat": ("Repeat the password", "再次輸入密碼"),
        "acct.no_admin": (
            "This workspace has no administrator yet. The operator creates the first one with "
            "`lab-brain admin bootstrap-admin`.",
            "此工作區尚無管理員。請由維運者以 `lab-brain admin bootstrap-admin` 建立第一位管理員。",
        ),
        "acct.page": ("My account", "我的帳號"),
        "acct.role.ADMIN": ("Administrator", "管理員"),
        "acct.role.MEMBER": ("Member", "成員"),
        "acct.state.PENDING": ("Awaiting approval", "等待核准"),
        "acct.state.ACTIVE": ("Active", "使用中"),
        "acct.state.SUSPENDED": ("Suspended", "已停用"),
        "acct.role": ("Role", "角色"),
        "acct.state": ("Account", "帳號狀態"),
        "acct.since": ("Member since", "加入時間"),
        "acct.change_password": ("Change password", "變更密碼"),
        "acct.password_changed": (
            "Password changed. Sign-ins on other devices have ended.",
            "密碼已變更，其他裝置上的登入都已結束。",
        ),
        "acct.signed_out": ("You are signed out.", "您已登出。"),
    }
)


def _form(action: str, csrf: str, fields: Html, button: str) -> Html:
    return h(
        '<form method="post" action="{}" class="box"><input type="hidden" name="csrf" value="{}">'
        '{}<p><button type="submit">{}</button></p></form>',
        action,
        csrf,
        fields,
        button,
    )


def _field(
    label: str, name: str, kind: str, *, value: str = "", hint: str = "", autocomplete: str = ""
) -> Html:
    return h(
        '<p><label>{}<br><input type="{}" name="{}" value="{}" required{}{}></label>{}</p>',
        label,
        kind,
        name,
        value,
        Html(f' autocomplete="{autocomplete}"' if autocomplete else ""),
        Html(' maxlength="256"' if kind == "password" else ""),
        h('<br><span class="muted">{}</span>', hint) if hint else Html(""),
    )


def _notice(text: str | None, kind: str = "notice") -> Html:
    return h('<p class="box {}" role="alert">{}</p>', kind, text) if text else Html("")


def refusal(m: Messages, code: str, detail: str = "") -> str:
    try:
        return m(f"acct.refused.{code}", detail=detail or "-")
    except KeyError:
        return m("acct.refused.sign_in_refused")


def sign_in_page(
    chrome: Chrome,
    *,
    next_path: str,
    error: str | None = None,
    notice: str | None = None,
    email: str = "",
    no_admin: bool = False,
) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    body = cat(
        [
            h("<h1>{}</h1>", m("acct.sign_in")),
            _notice(m("acct.no_admin")) if no_admin else Html(""),
            _notice(notice),
            _notice(error, "error"),
            _form(
                "/login",
                chrome.csrf,
                cat(
                    [
                        h('<input type="hidden" name="next" value="{}">', next_path),
                        _field(
                            m("acct.email"), "email", "email", value=email, autocomplete="username"
                        ),
                        _field(
                            m("acct.password"),
                            "password",
                            "password",
                            autocomplete="current-password",
                        ),
                    ]
                ),
                m("acct.sign_in"),
            ),
            h(
                '<p><a href="/password/forgot">{}</a></p><p>{} <a href="/register">{}</a></p>',
                m("acct.forgot"),
                m("acct.no_account"),
                m("acct.register"),
            ),
        ]
    )
    return page(m("acct.sign_in"), body, chrome=chrome)


def register_page(
    chrome: Chrome,
    *,
    error: str | None = None,
    email: str = "",
    name: str = "",
    closed: bool = False,
) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    form = (
        _notice(m("acct.refused.mail_unavailable"), "error")
        if closed
        else _form(
            "/register",
            chrome.csrf,
            cat(
                [
                    _field(m("acct.name"), "name", "text", value=name, autocomplete="name"),
                    _field(
                        m("acct.email"),
                        "email",
                        "email",
                        value=email,
                        hint=m("acct.email.hint"),
                        autocomplete="email",
                    ),
                    _field(
                        m("acct.password"),
                        "password",
                        "password",
                        hint=m("acct.password.hint"),
                        autocomplete="new-password",
                    ),
                    _field(m("acct.repeat"), "repeat", "password", autocomplete="new-password"),
                ]
            ),
            m("acct.register"),
        )
    )
    body = cat(
        [
            h("<h1>{}</h1>", m("acct.register")),
            _notice(error, "error"),
            form,
            h('<p>{} <a href="/login">{}</a></p>', m("acct.have_account"), m("acct.sign_in")),
        ]
    )
    return page(m("acct.register"), body, chrome=chrome)


def notice_page(
    chrome: Chrome, *, title: str, text: str, link: tuple[str, str] | None = None
) -> bytes:
    body = cat(
        [
            h("<h1>{}</h1>", title),
            _notice(text),
            h('<p><a href="{}">{}</a></p>', link[0], link[1]) if link else Html(""),
        ]
    )
    return page(title, body, chrome=chrome)


def verify_page(chrome: Chrome, *, token: str) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    body = cat(
        [
            h("<h1>{}</h1><p>{}</p>", m("acct.verify.title"), m("acct.verify.lead")),
            _form(
                "/verify",
                chrome.csrf,
                h('<input type="hidden" name="token" value="{}">', token),
                m("acct.verify.button"),
            ),
        ]
    )
    return page(m("acct.verify.title"), body, chrome=chrome)


def forgot_page(chrome: Chrome, *, notice: str | None = None, error: str | None = None) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    body = cat(
        [
            h("<h1>{}</h1><p>{}</p>", m("acct.forgot.title"), m("acct.forgot.lead")),
            _notice(notice),
            _notice(error, "error"),
            _form(
                "/password/forgot",
                chrome.csrf,
                _field(m("acct.email"), "email", "email", autocomplete="email"),
                m("acct.forgot.send"),
            ),
        ]
    )
    return page(m("acct.forgot.title"), body, chrome=chrome)


def reset_page(chrome: Chrome, *, token: str, error: str | None = None) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    body = cat(
        [
            h("<h1>{}</h1>", m("acct.reset.title")),
            _notice(error, "error"),
            _form(
                "/password/reset",
                chrome.csrf,
                cat(
                    [
                        h('<input type="hidden" name="token" value="{}">', token),
                        _field(
                            m("acct.password.new"),
                            "password",
                            "password",
                            hint=m("acct.password.hint"),
                            autocomplete="new-password",
                        ),
                        _field(m("acct.repeat"), "repeat", "password", autocomplete="new-password"),
                    ]
                ),
                m("acct.reset.save"),
            ),
        ]
    )
    return page(m("acct.reset.title"), body, chrome=chrome)


def account_page(
    chrome: Chrome,
    *,
    name: str,
    email: str,
    role: str,
    status: str,
    since: dt.datetime,
    projects: list[tuple[str, str, str]],
    notice: str | None = None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    assert chrome.csrf is not None
    rows = cat(
        h("<tr><th>{}</th><td>{}</td></tr>", k, v)
        for k, v in (
            (m("acct.name"), e(name)),
            (m("acct.email"), e(email)),
            (m("acct.role"), e(m(f"acct.role.{role}"))),
            (m("acct.state"), e(m(f"acct.state.{status}"))),
            (m("acct.since"), e(when_text(since))),
        )
    )
    mine = cat(
        h(
            '<li><a href="/projects/{}">{}</a> <span class="muted">{}</span></li>',
            pid,
            pname,
            m(f"proj.role.{prole}") if prole in ("OWNER", "MEMBER") else prole,
        )
        for pid, pname, prole in projects
    )
    body = cat(
        [
            h("<h1>{}</h1>", m("acct.page")),
            _notice(notice),
            _notice(error, "error"),
            h('<div class="scroll"><table>{}</table></div>', rows),
            h("<h2>{}</h2><ul>{}</ul>", m("nav.projects"), mine) if projects else Html(""),
            h("<h2>{}</h2>", m("acct.change_password")),
            _form(
                "/account/password",
                chrome.csrf,
                cat(
                    [
                        _field(
                            m("acct.password.current"),
                            "current",
                            "password",
                            autocomplete="current-password",
                        ),
                        _field(
                            m("acct.password.new"),
                            "password",
                            "password",
                            hint=m("acct.password.hint"),
                            autocomplete="new-password",
                        ),
                        _field(m("acct.repeat"), "repeat", "password", autocomplete="new-password"),
                    ]
                ),
                m("acct.change_password"),
            ),
        ]
    )
    return page(m("acct.page"), body, chrome=chrome)
