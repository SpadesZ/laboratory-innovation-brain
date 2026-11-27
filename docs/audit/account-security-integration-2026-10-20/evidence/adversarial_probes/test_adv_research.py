"""Adversarial probes: projects, oversight, clearance and the ADMIN's limits, through the web.

Each test PASSES while the defect it names is present (it asserts the defective behaviour).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

import pytest

from lab_brain.accounts.projects import LabProjects
from tests.account_fixtures import PASSWORD, Lab
from tests.e2e.test_web_accounts_postgres import _browser, _csrf, _sign_in
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres


@dataclass
class World:
    lab: Lab
    people: dict[str, Any]
    b: dict[str, Browser]
    project: str
    episode: str


@pytest.fixture
def world(db, tmp_path) -> World:
    """admin (ADMIN, not a member); ada (OWNER, INTERNAL+PUBLIC, opened an INTERNAL question);
    cy (member at PUBLIC only); bob (active, outside the project)."""
    from tests.e2e.test_research_episode_postgres import GOAL, REPORT, _device

    lab = Lab(db)
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    cy = lab.member("cy@lab.example", "Cy", admin=admin)
    projects = LabProjects(db, now=lab.clock)
    project = projects.create(ada, name="Matrix project", clearance=["INTERNAL", "PUBLIC"])
    projects.add_member(project, by=admin, member_account_id=cy.account_id, clearance=["PUBLIC"])
    b = {p: _browser(tmp_path, lab.mail) for p in ("admin", "ada", "bob", "cy")}
    for person, email in (
        ("admin", "owner@lab.example"),
        ("ada", "ada@uni.example.edu"),
        ("bob", "bob@gmail.example"),
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
    people = {"admin": admin, "ada": ada, "bob": bob, "cy": cy}
    return World(lab, people, b, project, episode)


def _goal() -> str:
    from tests.e2e.test_research_episode_postgres import GOAL

    return GOAL


# -- E: an administrator's look shows a classified question to members not cleared for it ------


def test_an_admin_look_shows_an_internal_question_to_a_public_only_member(world):
    db, cy, goal = world.lab.connection, world.b["cy"], _goal()
    label = db.execute(
        "SELECT question_label FROM research_runs WHERE episode_id = %s AND ordinal = 1",
        (world.episode,),
    ).fetchone()[0]
    clearance = db.execute(
        "SELECT sensitivity_clearance FROM project_memberships WHERE project_id = %s"
        " AND actor_id = %s",
        (world.project, world.people["cy"].actor_id),
    ).fetchone()[0]
    print("question label:", label, "| cy's clearance:", clearance)
    assert label == "INTERNAL" and clearance == ["PUBLIC"]
    # Cy has no way to the question: the episode is not theirs, and not at their level.
    assert cy.get(f"/episodes/{world.episode}").status == 404
    assert goal not in cy.get(f"/projects/{world.project}").text
    assert goal not in cy.get("/").text and goal not in cy.get("/inbox").text
    # An administrator opens the episode for oversight ...
    assert world.b["admin"].get(f"/admin/episodes/{world.episode}").status == 200
    # ... and the project page now tells Cy the INTERNAL question, word for word.
    page = cy.get(f"/projects/{world.project}").text
    line = next(x for x in page.split("<li>") if "read the reports of" in x)
    print("cy sees:", html.unescape(line.split("</li>")[0]))
    assert goal in html.unescape(page)


# -- F: the opener keeps reading a question and report above their current clearance -----------


def test_the_opener_reads_an_internal_question_and_report_after_losing_internal(world):
    from lab_brain.interfaces.web.app import WITHHELD

    lab, ada, goal = world.lab, world.b["ada"], _goal()
    LabProjects(lab.connection, now=lab.clock).change_member(
        world.project,
        by=world.people["admin"],
        actor_id=world.people["ada"].actor_id,
        clearance=["PUBLIC"],
        owner=True,
    )
    page = ada.get(f"/episodes/{world.episode}")
    export = ada.get(f"/episodes/{world.episode}/runs/1/report.md")
    print("episode page:", page.status, "| export:", export.status, len(export.text), "chars")
    withheld = export.text.count(WITHHELD)
    shown = [x for x in export.text.splitlines() if x.strip() and WITHHELD not in x]
    print("excerpts withheld:", withheld, "| other report lines still shown:", len(shown))
    print("e.g.:", [x[:90] for x in shown if "ypothes" in x][:3])
    assert page.status == 200 and goal in html.unescape(page.text)
    assert export.status == 200 and goal in export.text and len(shown) > 20
    # The service itself refuses to continue it at this clearance -- the label is known.
    refused = ada.post(f"/episodes/{world.episode}/continue", {"csrf": _csrf(page)})
    print("continue:", refused.status)
    assert refused.status == 409 and "INTERNAL" in html.unescape(refused.text)


# -- G: nobody changes their own membership -- an administrator removes their own ----------------


def test_an_administrator_removes_their_own_membership(world):
    lab = world.lab
    admin = world.people["admin"]
    second = lab.service().set_role(world.people["bob"].account_id, "ADMIN", by=admin)
    LabProjects(lab.connection, now=lab.clock).add_member(
        world.project, by=second, member_account_id=admin.account_id, clearance=["PUBLIC"]
    )
    browser = world.b["admin"]
    overview = browser.get(f"/projects/{world.project}")
    assert overview.status == 200
    removed = browser.post(
        f"/projects/{world.project}/members/remove",
        {"csrf": _csrf(overview), "actor": admin.actor_id},
    )
    row = lab.connection.execute(
        "SELECT active FROM project_memberships WHERE project_id = %s AND actor_id = %s",
        (world.project, admin.actor_id),
    ).fetchone()
    print("remove own membership:", removed.status, unquote(removed.location), "active:", row[0])
    assert removed.status == 303 and row == (False,)
    # The same administrator is refused when they try to change their own access:
    change = browser.post(
        f"/projects/{world.project}/members/change",
        {"csrf": _csrf(overview), "actor": admin.actor_id, "clearance": "PUBLIC"},
    )
    print("change own access (for contrast):", change.status)


# -- H: membership without central approval: creating a project grants it to oneself ------------


def test_a_member_grants_themself_membership_any_clearance_and_egress_by_creating_a_project(
    world,
):
    from lab_brain.accounts.projects import LABELS

    db, bob = world.lab.connection, world.b["bob"]
    created = bob.post(
        "/projects",
        {"csrf": _csrf(bob.get("/projects")), "name": "Bob side project", "clearance": LABELS},
    )
    project = unquote(created.location.split("/projects/", 1)[1].split("?", 1)[0])
    row = db.execute(
        "SELECT role, sensitivity_clearance, approval_scopes, granted_by_actor_id"
        " FROM project_memberships WHERE project_id = %s",
        (project,),
    ).fetchone()
    print("bob's self-made membership:", tuple(row))
    assert row[0] == "OWNER" and sorted(row[1]) == sorted(LABELS)
    assert row[2] == ["LLM_EGRESS"] and row[3] == world.people["bob"].actor_id
    # An administrator does the same: their own membership, granted by themself.
    admin = world.b["admin"]
    made = admin.post(
        "/projects", {"csrf": _csrf(admin.get("/projects")), "name": "Admin's", "clearance": LABELS}
    )
    mine = unquote(made.location.split("/projects/", 1)[1].split("?", 1)[0])
    granted = db.execute(
        "SELECT role, granted_by_actor_id FROM project_memberships WHERE project_id = %s",
        (mine,),
    ).fetchone()
    print("admin's self-made membership:", tuple(granted))
    assert tuple(granted) == ("OWNER", world.people["admin"].actor_id)


# -- I: the ADMIN reaches research writes and egress through an account they approve themself ---


def test_an_admin_writes_research_and_declares_egress_in_any_project_via_a_self_approved_account(
    world, tmp_path
):
    from lab_brain.core.models.identifiers import new_id

    lab, db, admin = world.lab, world.lab.connection, world.b["admin"]
    admin_actor = world.people["admin"].actor_id
    # 1. The administrator registers a second address they read, and confirms it.
    anon = _browser(tmp_path, lab.mail)
    assert anon.post(
        "/register", {"csrf": _csrf(anon.get("/register")), "email": "alias@owner-home.example"}
    ).status == 200
    token = lab.link("/verify")
    form = anon.get(f"/verify?token={token}")
    assert anon.post(
        "/verify",
        {"csrf": _csrf(form), "token": token, "name": "Research Assistant",
         "password": PASSWORD, "repeat": PASSWORD},
    ).status == 200
    alias = db.execute(
        "SELECT account_id, actor_id FROM accounts WHERE email = 'alias@owner-home.example'"
    ).fetchone()
    # 2. They approve it and add it to Ada's project as an OWNER (LLM_EGRESS), from oversight.
    dash = admin.get("/admin")
    assert admin.post(f"/admin/accounts/{alias[0]}/approve", {"csrf": _csrf(dash)}).status == 303
    oversight = admin.get(f"/admin/projects/{world.project}")
    added = admin.post(
        f"/projects/{world.project}/members",
        {"csrf": _csrf(oversight), "email": "alias@owner-home.example",
         "clearance": ["INTERNAL", "PUBLIC"], "owner": "1"},
    )
    assert added.status == 303
    # 3. An external route the administrator configured (they administer the model routes).
    connection_id = new_id("llm_connection")
    db.execute(
        "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
        " created_by, created_at, updated_at) VALUES (%s, 'admins-endpoint', 'OPENAI_COMPATIBLE',"
        " 'https://llm.admin-choice.example/v1', 'EXTERNAL', %s, now(), now())",
        (connection_id, admin_actor),
    )
    # 4. Signed in as the alias: research data into Ada's project, and its egress declared.
    sock = _browser(tmp_path, lab.mail)
    assert _sign_in(sock, "alias@owner-home.example").status == 303
    data = sock.post(
        "/data",
        {"csrf": _csrf(sock.get(f"/data?project={world.project}")), "project": world.project,
         "kind": "measurement", "sensitivity": "INTERNAL"},
        {"files": [("fabricated.csv", b"V,I\n0,0\n1,9\n")]},
    )
    # Egress needs a project the operator set to RESEARCH mode (web-made projects are PRIVATE).
    db.execute("UPDATE projects SET privacy_mode = 'RESEARCH' WHERE project_id = %s",
               (world.project,))
    egress = sock.post(
        f"/projects/{world.project}/egress",
        {"csrf": _csrf(sock.get(f"/projects/{world.project}/egress")),
         "connections": connection_id, "labels": ["INTERNAL", "PUBLIC"]},
    )
    policy = db.execute(
        "SELECT approved_connection_ids, permitted_labels, declared_by_actor_id"
        " FROM project_llm_egress_policies WHERE project_id = %s ORDER BY version DESC LIMIT 1",
        (world.project,),
    ).fetchone()
    items = db.execute(
        "SELECT count(*) FROM ingestion_items WHERE project_id = %s AND actor_id = %s",
        (world.project, alias[1]),
    ).fetchone()
    print("data:", data.status, "| egress:", egress.status, "| policy:", tuple(policy or ()))
    print("items added by the alias:", items)
    assert data.status == 303 and items[0] >= 1
    assert egress.status == 303 and policy[0] == [connection_id] and policy[2] == alias[1]
    # Every step was the same administrator's; nothing required a second person.
    who = db.execute(
        "SELECT kind, by_actor_id FROM account_events WHERE account_id = %s"
        " AND kind IN ('APPROVED', 'MEMBERSHIP_GRANTED')",
        (alias[0],),
    ).fetchall()
    print("approved/granted by:", [tuple(r) for r in who])
    assert {r[1] for r in who} == {admin_actor}


# -- J: not every administrator read of a project is recorded ------------------------------------


def test_not_every_admin_read_is_recorded(world):
    db, admin = world.lab.connection, world.b["admin"]

    def rows() -> int:
        return db.execute(
            "SELECT count(*) FROM admin_access_log WHERE project_id = %s", (world.project,)
        ).fetchone()[0]

    dash = admin.get("/admin")
    print("dashboard names the private project:", "Matrix project" in dash.text,
          "| rows:", rows())
    assert "Matrix project" in dash.text and "Ada" in dash.text and rows() == 0
    for _ in range(3):
        assert admin.get(f"/admin/episodes/{world.episode}").status == 200
        assert admin.get(f"/admin/episodes/{world.episode}/runs/1/report.md").status == 200
    print("6 full report reads -> rows:", rows())
    assert rows() == 1
