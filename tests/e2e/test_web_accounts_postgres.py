"""The workspace with accounts, through a browser's requests: sign-in, roles, and the boundaries.

signed out     every page but the sign-in pages sends the browser to sign in; a form post
               without the right token is refused
the flow       register -> the mailed link (a GET shows a form; only its POST confirms) ->
               an administrator approves -> sign in; the session cookie is HttpOnly,
               SameSite=Strict, a fresh token the server chose
tokens         a form's CSRF token is bound to the session (or signed-out browser) it was
               shown in: another person's, or a signed-out one, is refused
roles          a member reaches neither the laboratory pages nor the model settings; an
               administrator reaches both, and sees every project only through oversight,
               each look shown to the project's members
projects       a member's project is theirs; another member's is "not found", for reading
               and for changing its membership; who owns a new project is the session's
               person whatever the form says
sessions       sign-out, suspension and a password reset end them; an attacker-chosen cookie
               is never adopted; the post-sign-in redirect stays on this workspace
fail closed    without mail, registration and reset are closed
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.accounts.mail import MemoryMailer
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.interfaces.web.app import AccountsConfig
from lab_brain.research.vertical import load_vertical_factory
from tests.account_fixtures import BASE_URL, CHEAP, PASSWORD, Lab
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres


def _browser(tmp_path: Path, mail: MemoryMailer | None) -> Browser:
    return Browser(
        Workspace(
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            accounts=AccountsConfig(mailer=mail, base_url=BASE_URL, cost=CHEAP),
        )
    )


def _csrf(page: Reply) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert found, page.text[:400]
    return found.group(1)


def _sign_in(browser: Browser, email: str, password: str = PASSWORD, next_path: str = "/") -> Reply:
    page = browser.get("/login")
    return browser.post(
        "/login",
        {"csrf": _csrf(page), "email": email, "password": password, "next": next_path},
    )


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


@pytest.fixture
def people(lab: Lab) -> dict[str, Any]:
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    return {"admin": admin, "ada": ada, "bob": bob}


def test_signed_out_every_page_but_the_sign_in_pages_asks_to_sign_in(lab, tmp_path):
    browser = _browser(tmp_path, lab.mail)
    for path in (
        "/",
        "/data",
        "/runs/new",
        "/episodes",
        "/admin",
        "/settings/llm",
        "/inbox",
        "/projects",
        "/account",
        "/status",
    ):
        reply = browser.get(path)
        assert reply.status == 303 and reply.location.startswith("/login?next="), path
    for path in ("/login", "/register", "/password/forgot"):
        assert browser.get(path).status == 200, path
    assert browser.post("/runs", {"csrf": "forged"}).status == 403
    assert browser.post("/admin/accounts/acc:x/approve", {}).status == 403


def test_a_person_registers_confirms_is_approved_and_signs_in(lab, tmp_path, people):
    browser = _browser(tmp_path, lab.mail)
    form = browser.get("/register")
    refused = browser.post(
        "/register",
        {
            "csrf": _csrf(form),
            "name": "Cy",
            "email": "cy@lab.example",
            "password": PASSWORD,
            "repeat": PASSWORD + "x",
        },
    )
    assert refused.status == 409 and "differ" in refused.text
    sent = browser.post(
        "/register",
        {
            "csrf": _csrf(form),
            "name": "Cy",
            "email": "cy@lab.example",
            "password": PASSWORD,
            "repeat": PASSWORD,
        },
    )
    assert sent.status == 200 and "confirmation link is on its way" in sent.text
    token = lab.link("/verify")
    shown = browser.get(f"/verify?token={token}")
    assert shown.status == 200 and lab.service().token_purpose(token) == "VERIFY_EMAIL", (
        "a GET of the link -- a mail scanner's -- consumes nothing"
    )
    confirmed = browser.post("/verify", {"csrf": _csrf(shown), "token": token})
    assert confirmed.status == 200 and "address is confirmed" in confirmed.text
    waiting = _sign_in(browser, "cy@lab.example")
    assert waiting.status == 401 and "has not approved" in waiting.text
    admin = _browser(tmp_path, lab.mail)
    assert _sign_in(admin, "owner@lab.example").status == 303
    dashboard = admin.get("/admin")
    assert dashboard.status == 200 and "cy@lab.example" in dashboard.text
    (cy,) = [a for a in lab.service().all() if a.email == "cy@lab.example"]
    approved = admin.post(f"/admin/accounts/{cy.account_id}/approve", {"csrf": _csrf(dashboard)})
    assert approved.status == 303
    signed_in = _sign_in(browser, "cy@lab.example")
    assert signed_in.status == 303 and signed_in.location == "/"
    (cookie,) = [c for c in signed_in.set_cookies if c.startswith("lb_session=")]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    home = browser.get("/")
    assert home.status == 200 and "Cy" in home.text and "Sign out" in home.text
    assert 'href="/admin"' not in home.text and 'href="/settings/llm"' not in home.text


def test_a_form_token_works_only_in_the_session_it_was_shown_in(lab, tmp_path, people):
    ada, admin = _browser(tmp_path, lab.mail), _browser(tmp_path, lab.mail)
    signed_out_token = _csrf(ada.get("/login"))
    _sign_in(ada, "ada@uni.example.edu")
    _sign_in(admin, "owner@lab.example")
    ada_token = _csrf(ada.get("/projects"))
    target = f"/admin/accounts/{people['bob'].account_id}/suspend"
    for token in (ada_token, signed_out_token):
        assert admin.post(target, {"csrf": token, "reason": "forged"}).status == 403
    assert lab.service().get(people["bob"].account_id).status == "ACTIVE"
    assert (
        ada.post(
            "/projects", {"csrf": signed_out_token, "name": "x", "clearance": "INTERNAL"}
        ).status
        == 403
    )


def test_a_member_reaches_neither_the_laboratory_nor_the_model_settings(lab, tmp_path, people):
    ada = _browser(tmp_path, lab.mail)
    _sign_in(ada, "ada@uni.example.edu")
    token = _csrf(ada.get("/"))
    for path in ("/admin", f"/admin/accounts/{people['bob'].account_id}", "/admin/projects/prj:x"):
        assert ada.get(path).status == 403, path
    assert (
        ada.post(
            f"/admin/accounts/{people['bob'].account_id}/suspend", {"csrf": token, "reason": "x"}
        ).status
        == 403
    )
    assert (
        ada.post(
            f"/admin/accounts/{people['ada'].account_id}/role", {"csrf": token, "role": "ADMIN"}
        ).status
        == 403
    )
    assert ada.get("/settings/llm").status == 403
    assert lab.service().get(people["ada"].account_id).system_role == "MEMBER"


def test_projects_are_their_members_and_oversight_is_shown_to_them(lab, tmp_path, people):
    ada, bob, admin = (_browser(tmp_path, lab.mail) for _ in range(3))
    _sign_in(ada, "ada@uni.example.edu")
    _sign_in(bob, "bob@gmail.example")
    _sign_in(admin, "owner@lab.example")
    page = ada.get("/projects")
    created = ada.post(
        "/projects",
        # A forged owner in the form changes nothing: the owner is the session's person.
        {
            "csrf": _csrf(page),
            "name": "Ring drift",
            "clearance": ["INTERNAL", "PUBLIC"],
            "actor": people["bob"].actor_id,
            "actor_id": people["bob"].actor_id,
        },
    )
    assert created.status == 303
    project_id = unquote(created.location.split("/projects/", 1)[1].split("?", 1)[0])
    owners = lab.connection.execute(
        "SELECT actor_id, role FROM project_memberships WHERE project_id = %s", (project_id,)
    ).fetchall()
    assert [tuple(r) for r in owners] == [(people["ada"].actor_id, "OWNER")]
    assert "Ring drift" in ada.get(f"/projects/{project_id}").text
    for path in (f"/projects/{project_id}", f"/projects/{project_id}/egress"):
        assert bob.get(path).status in (403, 404), path
    assert "Ring drift" not in bob.get("/projects").text
    assert "Ring drift" not in bob.get("/").text
    forged = bob.post(
        f"/projects/{project_id}/members",
        {
            "csrf": _csrf(bob.get("/projects")),
            "email": "bob@gmail.example",
            "clearance": "INTERNAL",
        },
    )
    assert forged.status == 404
    assert lab.connection.execute(
        "SELECT count(*) FROM project_memberships WHERE project_id = %s", (project_id,)
    ).fetchone() == (1,)
    redirected = admin.get(f"/projects/{project_id}")
    assert redirected.status == 303 and unquote(redirected.location) == f"/admin/projects/{project_id}"
    assert "Ring drift" in admin.get(f"/admin/projects/{project_id}").text
    overview = ada.get(f"/projects/{project_id}")
    assert "Lab Owner" in overview.text, "the project's members see who looked"
    added = ada.post(
        f"/projects/{project_id}/members",
        {"csrf": _csrf(overview), "email": "bob@gmail.example", "clearance": "INTERNAL"},
    )
    assert added.status == 303
    assert "Ring drift" in bob.get("/projects").text


def test_sign_out_suspension_and_reset_end_sessions(lab, tmp_path, people):
    ada = _browser(tmp_path, lab.mail)
    # An attacker-chosen cookie is never adopted as the session.
    ada.cookies["lb_session"] = "attacker-chosen-value"
    signed_in = _sign_in(ada, "ada@uni.example.edu")
    assert ada.cookies["lb_session"] != "attacker-chosen-value"
    token = ada.cookies["lb_session"]
    out = ada.post("/logout", {"csrf": _csrf(ada.get("/"))})
    assert out.status == 303 and "lb_session" not in ada.cookies
    ada.cookies["lb_session"] = token
    assert ada.get("/").status == 303, "a signed-out session's cookie signs nobody in"
    _sign_in(ada, "ada@uni.example.edu")
    lab.service().suspend(people["ada"].account_id, by=people["admin"], reason="left")
    assert ada.get("/").status == 303
    lab.service().reactivate(people["ada"].account_id, by=people["admin"])
    _sign_in(ada, "ada@uni.example.edu")
    other = _browser(tmp_path, lab.mail)
    forgot = other.get("/password/forgot")
    sent = other.post("/password/forgot", {"csrf": _csrf(forgot), "email": "ada@uni.example.edu"})
    assert sent.status == 200 and "on its way" in sent.text
    reset_token = lab.link("/password/reset")
    form = other.get(f"/password/reset?token={reset_token}")
    done = other.post(
        "/password/reset",
        {
            "csrf": _csrf(form),
            "token": reset_token,
            "password": "a new passphrase here",
            "repeat": "a new passphrase here",
        },
    )
    assert done.status == 303 and done.location == "/login?reset=1"
    assert ada.get("/").status == 303, "a reset ends every session"
    assert other.get(f"/password/reset?token={reset_token}").status == 410
    assert signed_in.status == 303


@pytest.mark.parametrize(
    "target", ["//evil.example/", "https://evil.example/", "/logout", "\\\\evil"]
)
def test_after_sign_in_the_browser_stays_on_this_workspace(lab, tmp_path, people, target):
    browser = _browser(tmp_path, lab.mail)
    assert _sign_in(browser, "ada@uni.example.edu", next_path=target).location == "/"


def test_without_mail_registration_and_reset_are_closed(lab, tmp_path, people):
    browser = _browser(tmp_path, None)
    page = browser.get("/register")
    assert "cannot send email yet" in page.text and 'name="password"' not in page.text
    refused = browser.post(
        "/register",
        {
            "csrf": _csrf(page),
            "name": "Dee",
            "email": "dee@x.example",
            "password": PASSWORD,
            "repeat": PASSWORD,
        },
    )
    assert refused.status == 409
    assert "cannot send email yet" in browser.get("/password/forgot").text


def test_the_sign_in_page_speaks_traditional_chinese(lab, tmp_path, people):
    browser = _browser(tmp_path, lab.mail)
    page = browser.get("/login")
    switched = browser.post("/locale", {"csrf": _csrf(page), "locale": "zh-TW", "next": "/login"})
    assert switched.status == 303
    assert "忘記密碼" in browser.get("/login").text
    _sign_in(browser, "owner@lab.example")
    assert "實驗室管理" in browser.get("/admin").text
