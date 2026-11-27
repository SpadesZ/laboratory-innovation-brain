"""The independent adversarial audit's findings, each held closed (2026-10-20, A1-A13).

The audit's probes asserted each defect while it was present; these tests assert the opposite.
A3 (an administrator approving an alias they control and granting it membership) and the
operator's database credentials (A12's first half) are owner decisions, recorded in the audit
report, not closed here. A6 and A7 are held in tests/integration/test_lab_projects_postgres.py,
A13 in tests/e2e/test_web_accounts_postgres.py.
"""

from __future__ import annotations

import datetime as dt
import html
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.accounts.oversight import Oversight, access_log
from lab_brain.accounts.passwords import new_token, token_hash
from lab_brain.accounts.projects import LABELS, LabProjects
from lab_brain.accounts.service import AccountRefused
from tests.account_fixtures import PASSWORD, Lab
from tests.e2e.test_web_accounts_postgres import _browser, _csrf, _sign_in
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres


@dataclass
class World:
    lab: Lab
    people: dict[str, Any]
    b: dict[str, Browser]
    project: str
    episode: str
    goal: str


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


@pytest.fixture
def world(lab: Lab, tmp_path: Any) -> World:
    """admin (not a member); ada (OWNER at INTERNAL+PUBLIC, opened an INTERNAL question);
    cy (a member at PUBLIC only)."""
    from tests.e2e.test_research_episode_postgres import GOAL, REPORT, _device

    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    cy = lab.member("cy@lab.example", "Cy", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    project = projects.create(
        admin,
        name="Audit project",
        owner_account_id=ada.account_id,
        clearance=["INTERNAL", "PUBLIC"],
    )
    projects.add_member(project, by=admin, member_account_id=cy.account_id, clearance=["PUBLIC"])
    b = {p: _browser(tmp_path, lab.mail) for p in ("admin", "ada", "cy")}
    for person, email in (
        ("admin", "owner@lab.example"),
        ("ada", "ada@uni.example.edu"),
        ("cy", "cy@lab.example"),
    ):
        assert _sign_in(b[person], email).status == 303, person
    device = _device(tmp_path, "mesh-coarse-access")
    started = b["ada"].post(
        "/runs",
        {
            "csrf": _csrf(b["ada"].get(f"/runs/new?project={project}")),
            "project": project,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": [(REPORT.name, REPORT.read_bytes())],
            "verification_input": [(device.name, device.read_bytes())],
        },
    )
    assert started.status == 303, started.text[:500]
    episode = unquote(started.location.split("/episodes/", 1)[1])
    return World(lab, {"admin": admin, "ada": ada, "cy": cy}, b, project, episode, GOAL)


def test_a1_an_administrators_look_names_nothing_above_a_members_clearance(world: World) -> None:
    from tests.e2e.test_research_episode_postgres import REPORT

    admin, db = world.b["admin"], world.lab.connection
    assert admin.get(f"/admin/episodes/{world.episode}").status == 200
    (artifact,) = db.execute(
        "SELECT raw_artifact_id FROM ingestion_items WHERE project_id = %s AND display_name = %s",
        (world.project, f"workspace-upload:{REPORT.name}"),
    ).fetchone()
    assert admin.get(f"/admin/projects/{world.project}/artifacts/{artifact}").status == 200
    public = html.unescape(world.b["cy"].get(f"/projects/{world.project}").text)
    assert world.goal not in public and REPORT.name not in public, "nothing above PUBLIC named"
    assert "a research question classified above what you may read" in public
    assert "a file classified above what you may read" in public
    internal = html.unescape(world.b["ada"].get(f"/projects/{world.project}").text)
    assert world.goal in internal and REPORT.name in internal, "named to whoever may read it"


def test_a2_the_opener_reads_their_question_only_while_cleared_for_it(world: World) -> None:
    ada = world.b["ada"]
    token = _csrf(ada.get("/"))
    LabProjects(world.lab.connection, now=world.lab.clock).change_member(
        world.project,
        by=world.people["admin"],
        actor_id=world.people["ada"].actor_id,
        clearance=["PUBLIC"],
        owner=True,
    )
    assert ada.get(f"/episodes/{world.episode}").status == 404
    assert ada.get(f"/episodes/{world.episode}/runs/1/report.md").status == 404
    assert ada.post(f"/episodes/{world.episode}/continue", {"csrf": token}).status == 404
    assert world.goal not in html.unescape(ada.get("/episodes").text)


def test_a4_the_registration_cap_and_a_failed_message_answer_alike_for_every_address(
    lab: Lab, monkeypatch: Any
) -> None:
    from lab_brain.accounts import service as service_module
    from lab_brain.accounts.mail import MailUnavailable
    from lab_brain.accounts.service import AccountService
    from tests.account_fixtures import BASE_URL, CHEAP

    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    # The cap is reached by one more registration than the hour already holds.
    (already,) = lab.connection.execute("SELECT count(*) FROM accounts").fetchone()
    monkeypatch.setattr(service_module, "MAX_REGISTRATIONS_PER_HOUR", already + 1)
    accounts = lab.service()
    accounts.register(email="filler@spam.example")
    # Both refused alike: the web shows one message per refusal code, whatever the address.
    for email in ("ada@uni.example.edu", "nobody@new.example"):
        with pytest.raises(AccountRefused) as refused:
            accounts.register(email=email)
        assert refused.value.code == "busy", email
    monkeypatch.setattr(service_module, "MAX_REGISTRATIONS_PER_HOUR", 30)

    class Failing:
        def send(self, message: Any) -> None:
            raise MailUnavailable("the relay refused")

    failing = AccountService(
        lab.connection, mailer=Failing(), base_url=BASE_URL, now=lab.clock, cost=CHEAP
    )
    for _ in range(4):  # the known address is throttled after three messages an hour
        failing.register(email="ada@uni.example.edu")
    failing.register(email="nobody@new.example")  # no exception: nothing tells them apart
    assert not [a for a in accounts.all() if a.email == "nobody@new.example"], "nothing kept"


def _two_admins(lab: Lab) -> tuple[Any, Any]:
    first = lab.admin()
    second = lab.member("second@lab.example", "Second", admin=first)
    return first, lab.service().set_role(second.account_id, "ADMIN", by=first)


def test_a5_two_administrators_suspending_each_other_at_once_leave_one(lab: Lab) -> None:
    first, second = _two_admins(lab)
    c1, c2 = psycopg.connect(database_url()), psycopg.connect(database_url())
    outcome: dict[str, str] = {}

    def the_other() -> None:
        try:
            c2.execute(
                "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s",
                (first.account_id,),
            )
            c2.commit()
            outcome["second"] = "committed"
        except psycopg.errors.RaiseException as refused:
            c2.rollback()
            outcome["second"] = str(refused)

    try:
        c1.execute(
            "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s", (second.account_id,)
        )
        other = threading.Thread(target=the_other)
        other.start()
        other.join(timeout=2)
        assert other.is_alive(), "the second change waits for the first"
        c1.commit()
        other.join(timeout=30)
    finally:
        c1.close()
        c2.close()
    assert "last active administrator" in outcome["second"]
    active = lab.connection.execute(
        "SELECT count(*) FROM accounts WHERE system_role = 'ADMIN' AND status = 'ACTIVE'"
    ).fetchone()
    assert active == (1,)


def test_a8_an_unconfirmed_registration_is_not_declined_and_its_address_stays_usable(
    lab: Lab,
) -> None:
    admin = lab.admin()
    accounts = lab.service()
    accounts.register(email="victim@uni.example.edu")
    pending = next(a for a in accounts.all() if a.email == "victim@uni.example.edu")
    with pytest.raises(AccountRefused) as refused:
        accounts.reject(pending.account_id, by=admin)
    assert refused.value.code == "not_verified"
    lab.clock.advance(hours=49)  # the first link has expired
    accounts.register(email="victim@uni.example.edu")  # the address's owner
    owner = accounts.verify_email(lab.link("/verify"), display_name="Victor", password=PASSWORD)
    assert owner.awaiting == "APPROVAL"


def test_a9_the_laboratory_overview_is_a_recorded_read_too(world: World) -> None:
    assert world.b["admin"].get("/admin").status == 200
    rows = world.lab.connection.execute(
        "SELECT project_id, subject FROM admin_access_log WHERE subject = 'laboratory-overview'"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(None, "laboratory-overview")]
    shown = access_log(world.lab.connection, world.project, readable=frozenset(LABELS))
    assert shown == [], "laboratory-wide: no project's members are shown the overview as a look"


def test_a10_members_see_every_look_not_the_latest_fifty(lab: Lab) -> None:
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    project = LabProjects(lab.connection, now=lab.clock).create(
        admin, name="Ring", owner_account_id=ada.account_id, clearance=["INTERNAL"]
    )
    oversight = Oversight(lab.connection, admin, now=lab.clock)
    for _ in range(51):
        oversight.record(project, "project-summary")
        lab.clock.advance(hours=1, minutes=1)
    assert len(access_log(lab.connection, project, readable=frozenset(LABELS))) == 51


def test_a11_a_password_change_ends_an_outstanding_reset_link(lab: Lab) -> None:
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    accounts.request_password_reset(email="ada@uni.example.edu")
    reset = lab.link("/password/reset")
    accounts.change_password(ada, current=PASSWORD, new="a changed passphrase")
    with pytest.raises(AccountRefused) as refused:
        accounts.reset_password(token=reset, password="the attacker's passphrase")
    assert refused.value.code == "token_invalid"


def test_a12_a_session_is_bounded_for_every_writer(lab: Lab) -> None:
    admin = lab.admin()
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    now = lab.clock()
    for last_seen, expires in (
        (now, now + dt.timedelta(days=3650)),
        (now + dt.timedelta(hours=3), now + dt.timedelta(hours=2)),  # seen after it ends
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            lab.connection.execute(
                "INSERT INTO account_sessions (session_hash, account_id, created_at,"
                " last_seen_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
                (token_hash(new_token()), bob.account_id, now, last_seen, expires),
            )
