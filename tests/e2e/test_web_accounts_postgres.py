"""The workspace with accounts, through a browser's requests: sign-in, roles, and the boundaries.

signed out     every page but the sign-in pages sends the browser to sign in; a form post
               without the right token acts on nothing and asks to sign in again
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

import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.accounts.mail import MemoryMailer
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.interfaces.web.app import WITHHELD, AccountsConfig
from lab_brain.research.vertical import load_vertical_factory
from tests.account_fixtures import BASE_URL, CHEAP, PASSWORD, Lab
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres


def _browser(tmp_path: Path, mail: MemoryMailer | None, floor: float = 0.0) -> Browser:
    return Browser(
        Workspace(
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            accounts=AccountsConfig(mailer=mail, base_url=BASE_URL, cost=CHEAP, answer_floor=floor),
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
    runs = lab.connection.execute("SELECT count(*) FROM research_runs").fetchone()
    for path, form in (("/runs", {"csrf": "forged"}), ("/admin/accounts/acc:x/approve", {})):
        reply = browser.post(path, form)
        assert reply.status == 303 and reply.location.startswith("/login?expired=1"), path
    assert lab.connection.execute("SELECT count(*) FROM research_runs").fetchone() == runs


def test_a_person_registers_confirms_is_approved_and_signs_in(lab, tmp_path, people):
    browser = _browser(tmp_path, lab.mail)
    form = browser.get("/register")
    assert 'name="password"' not in form.text, "registration takes no password: verify first"
    sent = browser.post("/register", {"csrf": _csrf(form), "email": "cy@lab.example"})
    assert sent.status == 200 and "confirmation link is on its way" in sent.text
    token = lab.link("/verify")
    shown = browser.get(f"/verify?token={token}")
    assert shown.status == 200 and lab.service().token_purpose(token) == "VERIFY_EMAIL", (
        "a GET of the link -- a mail scanner's -- consumes nothing"
    )
    assert 'name="password"' in shown.text and 'name="name"' in shown.text
    for fields, expected in (
        ({"name": "Cy", "password": PASSWORD, "repeat": PASSWORD + "x"}, "differ"),
        ({"name": "Cy", "password": "short", "repeat": "short"}, "at least 12 characters"),
        ({"name": " ", "password": PASSWORD, "repeat": PASSWORD}, "give your name"),
    ):
        refused = browser.post("/verify", {"csrf": _csrf(shown), "token": token, **fields})
        assert refused.status == 409 and expected in refused.text, fields
        assert lab.service().token_purpose(token) == "VERIFY_EMAIL", "the link still works"
    confirmed = browser.post(
        "/verify",
        {
            "csrf": _csrf(shown),
            "token": token,
            "name": "Cy",
            "password": PASSWORD,
            "repeat": PASSWORD,
        },
    )
    assert confirmed.status == 200 and "address is confirmed" in confirmed.text
    again = browser.post(
        "/verify",
        {
            "csrf": _csrf(shown),
            "token": token,
            "name": "Mallory",
            "password": PASSWORD,
            "repeat": PASSWORD,
        },
    )
    assert again.status == 410, "the link works once"
    waiting = _sign_in(browser, "cy@lab.example")
    assert waiting.status == 401 and "has not approved" in waiting.text
    admin = _browser(tmp_path, lab.mail)
    assert _sign_in(admin, "owner@lab.example").status == 303
    dashboard = admin.get("/admin")
    assert (
        dashboard.status == 200
        and "cy@lab.example" in dashboard.text
        and "Mallory" not in dashboard.text
    )
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
    overview = ada.get(f"/projects/{project_id}")
    assert "A laboratory administrator adds, changes and removes members." in overview.text
    by_owner = ada.post(
        f"/projects/{project_id}/members",
        {"csrf": _csrf(overview), "email": "bob@gmail.example", "clearance": "INTERNAL"},
    )
    assert by_owner.status == 409 and "Only a laboratory administrator" in by_owner.text
    assert lab.connection.execute(
        "SELECT count(*) FROM project_memberships WHERE project_id = %s", (project_id,)
    ).fetchone() == (1,)
    redirected = admin.get(f"/projects/{project_id}")
    assert (
        redirected.status == 303 and unquote(redirected.location) == f"/admin/projects/{project_id}"
    )
    oversight = admin.get(f"/admin/projects/{project_id}")
    assert "Ring drift" in oversight.text
    assert "Lab Owner" in ada.get(f"/projects/{project_id}").text, "members see who looked"
    added = admin.post(
        f"/projects/{project_id}/members",
        {"csrf": _csrf(oversight), "email": "bob@gmail.example", "clearance": "INTERNAL"},
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
    "target",
    [
        "//evil.example/",
        "https://evil.example/",
        "/logout",
        "\\\\evil",
        "/\t/evil.example/",
        "/\n/evil.example/",
        "/\\evil.example/",
        "javascript:alert(1)",
    ],
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


@pytest.mark.parametrize("target", ["/\t/evil.example/", "//evil.example", "https://x.example/"])
def test_the_language_switch_stays_on_this_workspace(lab, tmp_path, target):
    browser = _browser(tmp_path, lab.mail)
    page = browser.get("/login")
    switched = browser.post("/locale", {"csrf": _csrf(page), "locale": "zh-TW", "next": target})
    assert switched.status == 303 and switched.location == "/"


def test_a_form_from_an_ended_session_asks_to_sign_in_again_and_returns(lab, tmp_path, people):
    ada = _browser(tmp_path, lab.mail)
    _sign_in(ada, "ada@uni.example.edu")
    page = ada.get("/projects")
    token = _csrf(page)
    lab.service().sign_out(ada.cookies["lb_session"])
    refused = ada.post(
        "/projects",
        {"csrf": token, "name": "Lost work", "clearance": "INTERNAL"},
        headers={"Referer": "http://127.0.0.1:8765/projects"},
    )
    assert refused.status == 303
    assert refused.location == "/login?expired=1&next=/projects"
    notice = ada.get(refused.location)
    assert "Your sign-in ended" in notice.text and 'name="next" value="/projects"' in notice.text
    assert lab.connection.execute(
        "SELECT count(*) FROM projects WHERE name = 'Lost work'"
    ).fetchone() == (0,), "nothing of the form is acted on"
    back = ada.post(
        "/login",
        {
            "csrf": _csrf(notice),
            "email": "ada@uni.example.edu",
            "password": "a wrong password!",
            "next": "/projects",
        },
    )
    assert back.status == 401 and 'name="next" value="/projects"' in back.text, (
        "a failed attempt keeps where the person was going"
    )
    again = ada.post(
        "/login",
        {
            "csrf": _csrf(back),
            "email": "ada@uni.example.edu",
            "password": PASSWORD,
            "next": "/projects",
        },
    )
    assert again.status == 303 and again.location == "/projects"
    # Signed in again, a form from before says what happened instead of a bare refusal.
    stale = ada.post("/projects", {"csrf": token, "name": "Old tab", "clearance": "INTERNAL"})
    assert stale.status == 403 and "This form is out of date" in stale.text
    # Signed out, a form sent from another site's page returns to this workspace's home.
    elsewhere = _browser(tmp_path, lab.mail).post(
        "/projects",
        {"csrf": token},
        headers={"Referer": "https://evil.example/projects"},
    )
    assert elsewhere.location == "/login?expired=1&next=/"


def test_a_member_sees_the_systems_state_without_its_technical_details(lab, tmp_path, people):
    ada, admin = _browser(tmp_path, lab.mail), _browser(tmp_path, lab.mail)
    _sign_in(ada, "ada@uni.example.edu")
    _sign_in(admin, "owner@lab.example")
    member_view, admin_view = ada.get("/status"), admin.get("/status")
    assert member_view.status == 200 and admin_view.status == 200
    assert "schema_migrations=" in admin_view.text
    assert "schema_migrations=" not in member_view.text
    assert str(tmp_path) not in member_view.text, "no server path"


def test_registration_and_reset_take_as_long_for_a_known_address_as_for_any(lab, tmp_path, people):
    import time

    browser = _browser(tmp_path, lab.mail, floor=0.4)
    page = browser.get("/register")
    for path, fields in (
        ("/register", {"name": "X", "password": PASSWORD, "repeat": PASSWORD}),
        ("/password/forgot", {}),
    ):
        for email in ("ada@uni.example.edu", "nobody@new.example"):
            started = time.monotonic()
            reply = browser.post(path, {"csrf": _csrf(page), "email": email, **fields})
            assert reply.status == 200, (path, email)
            assert time.monotonic() - started >= 0.4, (path, email)


def test_an_administrator_manages_membership_from_oversight_and_nobody_else(lab, tmp_path, people):
    ada, admin = _browser(tmp_path, lab.mail), _browser(tmp_path, lab.mail)
    _sign_in(ada, "ada@uni.example.edu")
    _sign_in(admin, "owner@lab.example")
    created = ada.post(
        "/projects",
        {"csrf": _csrf(ada.get("/projects")), "name": "Ring", "clearance": ["INTERNAL", "PUBLIC"]},
    )
    project_id = unquote(created.location.split("/projects/", 1)[1].split("?", 1)[0])
    oversight = admin.get(f"/admin/projects/{project_id}")
    added = admin.post(
        f"/projects/{project_id}/members",
        {"csrf": _csrf(oversight), "email": "bob@gmail.example", "clearance": "PUBLIC"},
    )
    assert unquote(added.location) == f"/admin/projects/{project_id}?done=added"
    again = admin.post(
        f"/projects/{project_id}/members",
        {"csrf": _csrf(oversight), "email": "bob@gmail.example", "clearance": "INTERNAL"},
    )
    assert again.status == 409 and "already a member" in again.text
    overview = ada.get(f"/projects/{project_id}")
    assert "Change access" not in overview.text, "the owner is offered no membership change"
    for path, fields in (
        ("change", {"actor": people["bob"].actor_id, "clearance": "INTERNAL", "owner": "1"}),
        ("remove", {"actor": people["bob"].actor_id}),
    ):
        refused = ada.post(
            f"/projects/{project_id}/members/{path}", {"csrf": _csrf(overview), **fields}
        )
        assert refused.status == 409 and "Only a laboratory administrator" in refused.text, path
    changed = admin.post(
        f"/projects/{project_id}/members/change",
        {
            "csrf": _csrf(oversight),
            "actor": people["bob"].actor_id,
            "clearance": ["INTERNAL", "PUBLIC"],
            "owner": "1",
        },
    )
    assert unquote(changed.location) == f"/admin/projects/{project_id}?done=changed"
    assert "Access changed." in admin.get(changed.location).text
    self_grant = admin.post(
        f"/projects/{project_id}/members",
        {"csrf": _csrf(oversight), "email": "owner@lab.example", "clearance": "INTERNAL"},
    )
    assert self_grant.status == 409 and "another laboratory administrator" in self_grant.text
    removed = admin.post(
        f"/projects/{project_id}/members/remove",
        {"csrf": _csrf(oversight), "actor": people["ada"].actor_id},
    )
    assert unquote(removed.location) == f"/admin/projects/{project_id}?done=removed"
    roles = lab.connection.execute(
        "SELECT actor_id, role, active FROM project_memberships WHERE project_id = %s",
        (project_id,),
    ).fetchall()
    assert sorted(tuple(r) for r in roles) == sorted(
        [(people["ada"].actor_id, "OWNER", False), (people["bob"].actor_id, "OWNER", True)]
    )


def test_an_administrator_reads_everything_each_read_recorded_and_writes_nothing(
    lab, tmp_path, people
):
    """Complete laboratory-wide read for an ADMIN -- every report in full, classified excerpts
    included, its export, the research file itself -- each recorded where the project's members
    see it. The same administrator still cannot add data, start or continue research, or
    declare egress in a project they are not a member of."""
    from tests.e2e.test_research_episode_postgres import GOAL, REPORT, _device

    ada, bob, admin = (_browser(tmp_path, lab.mail) for _ in range(3))
    _sign_in(ada, "ada@uni.example.edu")
    _sign_in(bob, "bob@gmail.example")
    _sign_in(admin, "owner@lab.example")
    created = ada.post(
        "/projects",
        {
            "csrf": _csrf(ada.get("/projects")),
            "name": "Rs anomaly",
            "clearance": ["INTERNAL", "PUBLIC"],
        },
    )
    project_id = unquote(created.location.split("/projects/", 1)[1].split("?", 1)[0])
    device = _device(tmp_path, "mesh-coarse-access")
    started = ada.post(
        "/runs",
        {
            "csrf": _csrf(ada.get(f"/runs/new?project={project_id}")),
            "project": project_id,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": [(REPORT.name, REPORT.read_bytes())],
            "verification_input": [(device.name, device.read_bytes())],
        },
    )
    assert started.status == 303, started.text[:1000]
    episode = unquote(started.location.split("/episodes/", 1)[1])
    own_export = ada.get(f"/episodes/{episode}/runs/1/report.md")
    assert own_export.status == 200 and WITHHELD not in own_export.text

    def recorded() -> set[str]:
        return {
            row[0]
            for row in lab.connection.execute(
                "SELECT subject FROM admin_access_log WHERE project_id = %s", (project_id,)
            ).fetchall()
        }

    # Each way in records the look on its own: the export, opened directly, first.
    export = admin.get(f"/admin/episodes/{episode}/runs/1/report.md")
    assert export.status == 200 and export.text == own_export.text
    assert f"episode-reports:{episode}" in recorded()
    read = admin.get(f"/admin/episodes/{episode}")
    assert read.status == 200 and WITHHELD not in read.text, "nothing withheld from an ADMIN"
    oversight = admin.get(f"/admin/projects/{project_id}")
    (item_id,) = lab.connection.execute(
        "SELECT raw_artifact_id FROM ingestion_items WHERE project_id = %s AND display_name = %s",
        (project_id, f"workspace-upload:{REPORT.name}"),
    ).fetchone()
    held = {
        r[0]
        for r in lab.connection.execute(
            "SELECT artifact_id FROM artifact_occurrences WHERE project_id = %s", (project_id,)
        ).fetchall()
    }
    assert len(held) > 1, "the run's own input and outputs are artifacts of the project too"
    for artifact_id in held:
        assert f"/admin/projects/{project_id}/artifacts/{artifact_id}" in oversight.text
    material = admin.get(f"/admin/projects/{project_id}/artifacts/{item_id}")
    first_line = REPORT.read_text(encoding="utf-8").splitlines()[0]
    assert material.status == 200 and html.escape(first_line, quote=False) in material.text
    assert {f"material:{item_id}", "project-summary"} <= recorded()
    seen = ada.get(f"/projects/{project_id}").text
    assert f"read the file “{REPORT.name}”" in seen and "read the reports of" in seen

    # Reading is all an administrator's global authority gives.
    token = _csrf(admin.get("/"))
    assert admin.get(f"/episodes/{episode}").status == 404
    assert admin.post(f"/episodes/{episode}/continue", {"csrf": token}).status == 404
    assert (
        admin.post(
            "/data",
            {"csrf": token, "project": project_id, "kind": "measurement", "sensitivity": "PUBLIC"},
            {"files": [("x.csv", b"a,b\n1,2\n")]},
        ).status
        == 403
    )
    assert (
        admin.post(
            "/runs", {"csrf": token, "project": project_id, "goal": "x", "sensitivity": "PUBLIC"}
        ).status
        == 403
    )
    assert admin.post(f"/projects/{project_id}/egress", {"csrf": token}).status == 404
    runs = lab.connection.execute(
        "SELECT count(*) FROM research_runs WHERE project_id = %s", (project_id,)
    ).fetchone()
    assert runs == (1,), "nothing was written by the administrator"
    for path in (
        f"/admin/episodes/{episode}",
        f"/admin/episodes/{episode}/runs/1/report.md",
        f"/admin/projects/{project_id}/artifacts/{item_id}",
    ):
        assert bob.get(path).status == 403, f"a member does not reach {path}"
