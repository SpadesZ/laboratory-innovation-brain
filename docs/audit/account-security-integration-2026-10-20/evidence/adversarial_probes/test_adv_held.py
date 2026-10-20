"""Suspicions that turned out to hold: each test PASSES because the defence works."""

from __future__ import annotations

from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.accounts.projects import LabProjects
from lab_brain.accounts.service import AccountRefused
from tests.account_fixtures import Lab
from tests.e2e.test_web_accounts_postgres import _browser, _csrf, _sign_in

pytestmark = pytest.mark.postgres


@pytest.fixture
def lab(db):
    return Lab(db)


def _upload(browser, project: str, name: str) -> None:
    page = browser.get(f"/data?project={project}")
    r = browser.post(
        "/data",
        {"csrf": _csrf(page), "project": project, "kind": "measurement", "sensitivity": "PUBLIC"},
        # Distinct bytes per file: identical bytes are one content-addressed artifact.
        {"files": [(name, f"V,I\n0,1\n# {name}\n".encode())]},
    )
    assert r.status == 303, r.text[:300]


def test_held_demoted_admin_cross_project_ids_markup_and_no_third_role(lab, tmp_path):
    first = lab.admin()
    second = lab.service().set_role(
        lab.member("second@lab.example", "Second", admin=first).account_id, "ADMIN", by=first
    )
    ada = lab.member("ada@uni.example.edu", "<script>alert(1)</script>", admin=first)
    bob = lab.member("bob@gmail.example", "Bob", admin=first)
    lab.member("pending@lab.example", "Pending", admin=first, approve=False)
    projects = LabProjects(lab.connection, now=lab.clock)
    p = projects.create(ada, name='<img src=x onerror="alert(2)">', clearance=["PUBLIC"])
    q = projects.create(bob, name="Q", clearance=["PUBLIC"])
    ada_b, bob_b, adm = (_browser(tmp_path, lab.mail) for _ in range(3))
    _sign_in(ada_b, "ada@uni.example.edu")
    _sign_in(bob_b, "bob@gmail.example")
    _sign_in(adm, "second@lab.example")
    _upload(ada_b, p, "p.csv")
    _upload(bob_b, q, "q.csv")
    (q_artifact,) = lab.connection.execute(
        "SELECT artifact_id FROM artifact_occurrences WHERE project_id = %s", (q,)
    ).fetchone()

    # Markup typed by a person is escaped wherever an administrator sees it.
    dash = adm.get("/admin").text
    assert "<script>alert(1)</script>" not in dash and "&lt;script&gt;" in dash
    assert '<img src=x onerror="alert(2)">' not in dash

    # An id from another project, in the URL or a form, finds nothing and records nothing.
    before = lab.connection.execute("SELECT count(*) FROM admin_access_log").fetchone()[0]
    assert adm.get(f"/admin/projects/{p}/artifacts/{q_artifact}").status == 404
    assert lab.connection.execute("SELECT count(*) FROM admin_access_log").fetchone()[0] == before
    over = adm.get(f"/admin/projects/{p}")
    moved = adm.post(
        f"/projects/{p}/members/change",
        {"csrf": _csrf(over), "actor": bob.actor_id, "clearance": "PUBLIC", "owner": "1"},
    )
    assert moved.status == 409
    pend = adm.post(
        f"/projects/{p}/members",
        {"csrf": _csrf(over), "email": "pending@lab.example", "clearance": "PUBLIC"},
    )
    assert pend.status == 409

    # OWNER is not a system role, at the service or in the database.
    with pytest.raises(AccountRefused):
        lab.service().set_role(bob.account_id, "OWNER", by=first)
    with pytest.raises(psycopg.errors.CheckViolation):
        lab.connection.execute(
            "UPDATE accounts SET system_role = 'OWNER' WHERE account_id = %s", (bob.account_id,)
        )

    # An administrator demoted mid-session loses the laboratory on the very next request.
    token = _csrf(adm.get("/admin"))
    lab.service().set_role(second.account_id, "MEMBER", by=first)
    assert adm.get("/admin").status == 403
    assert adm.get(f"/admin/projects/{p}").status == 403
    assert adm.post(f"/admin/accounts/{bob.account_id}/suspend",
                    {"csrf": token, "reason": "x"}).status == 403
    assert lab.service().get(bob.account_id).status == "ACTIVE"
    assert unquote(adm.get(f"/projects/{p}").location or "") == ""  # 404 page, no redirect


def test_held_token_and_session_edges(lab, tmp_path):
    admin = lab.admin()
    accounts = lab.service()
    accounts.register(email="new@lab.example")
    first_link = lab.link("/verify")
    accounts.register(email="new@lab.example")  # a fresh link ends the first
    with pytest.raises(AccountRefused):
        accounts.verify_email(first_link, display_name="N", password="a fine passphrase 1")
    second_link = lab.link("/verify")
    with pytest.raises(AccountRefused):  # refused password: link stays usable
        accounts.verify_email(second_link, display_name="N", password="short")
    acct = accounts.verify_email(second_link, display_name="N", password="a fine passphrase 1")
    with pytest.raises(AccountRefused):  # used once
        accounts.verify_email(second_link, display_name="N", password="a fine passphrase 2")
    # A password is never set before the address is confirmed, by any writer.
    accounts.register(email="other@lab.example")
    with pytest.raises(psycopg.errors.CheckViolation):
        lab.connection.execute(
            "UPDATE accounts SET password_hash = 'scrypt$1$1$1$AA==$AA=='"
            " WHERE email = 'other@lab.example'"
        )
    # Pending, declined and suspended accounts get no session, whatever the password.
    with pytest.raises(AccountRefused) as pending:
        accounts.sign_in(email="new@lab.example", password="a fine passphrase 1")
    assert pending.value.code == "awaiting_approval"
    accounts.approve(acct.account_id, by=admin)
    _account, token = accounts.sign_in(email="new@lab.example", password="a fine passphrase 1")
    accounts.suspend(acct.account_id, by=admin, reason="test")
    accounts.reactivate(acct.account_id, by=admin)
    assert accounts.session(token) is None, "a suspension's revocation survives reactivation"
