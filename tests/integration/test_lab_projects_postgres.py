"""Projects a member owns, who may work in them, and what an administrator sees (`012u`).

ownership   a member's new project is PRIVATE and theirs: OWNER, their clearance, LLM_EGRESS
membership  an owner or an administrator grants it; an owner at most their own clearance; a
            project keeps an owner; only active accounts join; every change is an event
oversight   an administrator sees every project and person, private ones too, and each look
            is recorded where only an active administrator can appear
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from lab_brain.accounts.oversight import Oversight, access_log
from lab_brain.accounts.projects import LabProjects
from lab_brain.accounts.service import AccountRefused
from tests.account_fixtures import Lab

pytestmark = pytest.mark.postgres


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


def _code(call: Any) -> str:
    with pytest.raises(AccountRefused) as refused:
        call()
    return refused.value.code


def test_a_member_owns_the_project_they_create(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    project_id = projects.create(
        ada, name="  Ring  resonator   drift ", clearance=["INTERNAL", "PUBLIC"]
    )
    row = lab.connection.execute(
        "SELECT name, privacy_mode FROM projects WHERE project_id = %s", (project_id,)
    ).fetchone()
    assert tuple(row) == ("Ring resonator drift", "PRIVATE")
    (owner,) = projects.memberships(project_id)
    assert (owner.actor_id, owner.role, owner.clearance, owner.scopes, owner.active) == (
        ada.actor_id,
        "OWNER",
        ("INTERNAL", "PUBLIC"),
        ("LLM_EGRESS",),
        True,
    )
    assert (
        _code(lambda: projects.create(ada, name=" ", clearance=["INTERNAL"]))
        == "invalid_project_name"
    )
    assert _code(lambda: projects.create(ada, name="x", clearance=[])) == "clearance_required"
    assert (
        _code(lambda: projects.create(ada, name="x", clearance=["TOP_SECRET"]))
        == "invalid_clearance"
    )


def test_membership_is_granted_by_an_owner_within_their_clearance_or_by_an_administrator(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    cy = lab.member("cy@lab.example", "Cy", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    project_id = projects.create(ada, name="Ring", clearance=["INTERNAL"])
    assert (
        _code(
            lambda: projects.add_member(
                project_id, by=bob, member_account_id=cy.account_id, clearance=["INTERNAL"]
            )
        )
        == "not_permitted"
    ), "a non-member cannot add anyone"
    assert (
        _code(
            lambda: projects.add_member(
                project_id, by=ada, member_account_id=bob.account_id, clearance=["CONFIDENTIAL_LAB"]
            )
        )
        == "clearance_exceeds_own"
    )
    granted = projects.add_member(
        project_id, by=ada, member_account_id=bob.account_id, clearance=["INTERNAL"]
    )
    assert (granted.role, granted.clearance) == ("MEMBER", ("INTERNAL",))
    assert (
        _code(
            lambda: projects.add_member(
                project_id, by=bob, member_account_id=cy.account_id, clearance=["INTERNAL"]
            )
        )
        == "not_permitted"
    ), "a member is not an owner"
    by_admin = projects.add_member(
        project_id, by=admin, member_account_id=cy.account_id, clearance=["CONFIDENTIAL_LAB"]
    )
    assert by_admin.clearance == ("CONFIDENTIAL_LAB",), "an administrator grants any clearance"
    assert (
        _code(lambda: projects.remove_member(project_id, by=ada, actor_id=ada.actor_id))
        == "last_owner"
    )
    projects.remove_member(project_id, by=ada, actor_id=bob.actor_id)
    assert not projects.membership(project_id, bob.actor_id).active, "deactivated, never deleted"
    lab.service().suspend(cy.account_id, by=admin, reason="left")
    dee = lab.member("dee@lab.example", "Dee", admin=admin)
    lab.service().suspend(dee.account_id, by=admin, reason="left")
    assert (
        _code(
            lambda: projects.add_member(
                project_id, by=ada, member_account_id=dee.account_id, clearance=["INTERNAL"]
            )
        )
        == "not_found"
    ), "a suspended account joins nothing"
    kinds = [k for k, *_ in lab.service().events(bob.account_id)]
    assert kinds[:2] == ["MEMBERSHIP_REVOKED", "MEMBERSHIP_GRANTED"]


def test_an_administrator_oversees_every_project_and_each_look_is_recorded(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    private = projects.create(ada, name="Private work", clearance=["CONFIDENTIAL_LAB"])
    assert _code(lambda: Oversight(lab.connection, ada, now=lab.clock)) == "not_permitted"
    oversight = Oversight(lab.connection, admin, now=lab.clock)
    listed = {p.project_id: p for p in oversight.projects()}
    assert listed[private].owners == ("Ada",) and listed[private].members == 1
    members = {m.account.email: m for m in oversight.members()}
    assert members["ada@uni.example.edu"].owned == 1
    detail = oversight.project(private)
    assert detail is not None and [m.actor_id for m in detail.memberships] == [ada.actor_id]
    assert oversight.project("prj:nowhere") is None
    looked = access_log(lab.connection, private)
    assert [(who, subject) for who, subject, _ in looked] == [("Lab Owner", f"project {private}")]
    with pytest.raises(psycopg.errors.RaiseException, match="not an active administrator"):
        lab.connection.execute(
            "INSERT INTO admin_access_log (access_id, admin_actor_id, project_id, subject)"
            " VALUES ('aac:x', %s, %s, 'snooping')",
            (ada.actor_id, private),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        lab.connection.execute("DELETE FROM admin_access_log")
