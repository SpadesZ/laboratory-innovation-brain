"""Projects a member owns, who may work in them, and what an administrator sees (`012u`).

ownership   a member's new project is PRIVATE and theirs: OWNER, their clearance, LLM_EGRESS
membership  only an active administrator grants, changes and revokes it (an owner holds the
            egress authority, not membership); a project keeps an owner; only active accounts
            join; every change is an event;
            nobody grants or changes their own, an administrator included; adding a member
            is never a silent rewrite of their access -- changing it is its own action
oversight   an administrator sees every project and person, private ones too, and each look
            is recorded where only an active administrator can appear
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from lab_brain.accounts.oversight import (
    MEMBER_RESEARCH,
    PROJECT_SUMMARY,
    Oversight,
    access_log,
)
from lab_brain.accounts.projects import LABELS, LabProjects
from lab_brain.accounts.service import AccountRefused
from tests.account_fixtures import Lab

pytestmark = pytest.mark.postgres

ALL_LEVELS = frozenset(LABELS)


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


def _code(call: Any) -> str:
    with pytest.raises(AccountRefused) as refused:
        call()
    return refused.value.code


def test_an_administrator_opens_a_project_for_its_owner_and_nobody_for_themself(lab):
    """Adversarial audit A6: creating a project granted its creator OWNER, any clearance and the
    egress authority -- a self-grant. Now an active administrator opens it, PRIVATE, for an owner
    who is not themself; a member opens none."""
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    assert (
        _code(
            lambda: projects.create(
                ada, name="Mine", owner_account_id=ada.account_id, clearance=["RESTRICTED_NDA"]
            )
        )
        == "admin_only"
    ), "a member opens no project, so grants themself nothing"
    assert (
        _code(
            lambda: projects.create(
                admin, name="Mine", owner_account_id=admin.account_id, clearance=["INTERNAL"]
            )
        )
        == "own_membership"
    ), "nor does an administrator, by opening one"
    project_id = projects.create(
        admin,
        name="  Ring  resonator   drift ",
        owner_account_id=ada.account_id,
        clearance=["INTERNAL", "PUBLIC"],
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
    granted_by = lab.connection.execute(
        "SELECT granted_by_actor_id FROM project_memberships WHERE project_id = %s", (project_id,)
    ).fetchone()
    assert granted_by == (admin.actor_id,), "the grant is the administrator's, not a self-grant"
    for name, clearance, code in (
        (" ", ["INTERNAL"], "invalid_project_name"),
        ("x", [], "clearance_required"),
        ("x", ["TOP_SECRET"], "invalid_clearance"),
    ):
        assert (
            _code(
                lambda name=name, clearance=clearance: projects.create(
                    admin, name=name, owner_account_id=ada.account_id, clearance=clearance
                )
            )
            == code
        )


def test_an_administrator_oversees_every_project_and_each_look_is_recorded(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    private = projects.create(
        admin, name="Private work", owner_account_id=ada.account_id, clearance=["CONFIDENTIAL_LAB"]
    )
    assert _code(lambda: Oversight(lab.connection, ada, now=lab.clock)) == "not_permitted"
    oversight = Oversight(lab.connection, admin, now=lab.clock)
    listed = {p.project_id: p for p in oversight.projects()}
    assert listed[private].owners == ("Ada",) and listed[private].members == 1
    members = {m.account.email: m for m in oversight.members()}
    assert members["ada@uni.example.edu"].owned == 1
    detail = oversight.project(private)
    assert detail is not None and [m.actor_id for m in detail.memberships] == [ada.actor_id]
    assert oversight.project("prj:nowhere") is None
    looked = access_log(lab.connection, private, readable=ALL_LEVELS)
    assert [(who, kind) for who, kind, _q, _at in looked] == [("Lab Owner", PROJECT_SUMMARY)]
    with pytest.raises(psycopg.errors.RaiseException, match="not an active administrator"):
        lab.connection.execute(
            "INSERT INTO admin_access_log (access_id, admin_actor_id, project_id, subject)"
            " VALUES ('aac:x', %s, %s, 'snooping')",
            (ada.actor_id, private),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        lab.connection.execute("DELETE FROM admin_access_log")


def test_nobody_grants_themself_membership_or_changes_their_own_access(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    project_id = projects.create(
        admin, name="Ring", owner_account_id=ada.account_id, clearance=["INTERNAL"]
    )
    assert (
        _code(
            lambda: projects.add_member(
                project_id,
                by=admin,
                member_account_id=admin.account_id,
                clearance=["RESTRICTED_NDA"],
                owner=True,
            )
        )
        == "own_membership"
    ), "an administrator reads a project through recorded oversight, not by joining it"
    # An administrator who is an owner -- another administrator opened the project for them --
    # changes and removes nothing of their own membership there either.
    second = lab.service().set_role(bob.account_id, "ADMIN", by=admin)
    own = projects.create(
        second,
        name="The administrator's own",
        owner_account_id=admin.account_id,
        clearance=["INTERNAL"],
    )
    for call in (
        lambda: projects.change_member(
            own, by=admin, actor_id=admin.actor_id, clearance=["RESTRICTED_NDA"], owner=True
        ),
        lambda: projects.remove_member(own, by=admin, actor_id=admin.actor_id),
    ):
        assert _code(call) == "own_membership", "audit A7: removing it is a change too"
    lab.service().set_role(bob.account_id, "MEMBER", by=admin)
    projects.add_member(
        project_id, by=admin, member_account_id=bob.account_id, clearance=["PUBLIC"]
    )
    assert (
        _code(
            lambda: projects.add_member(
                project_id,
                by=admin,
                member_account_id=bob.account_id,
                clearance=["RESTRICTED_NDA"],
                owner=True,
            )
        )
        == "already_member"
    ), "adding again never silently rewrites an existing member's access"
    assert projects.membership(project_id, bob.actor_id).clearance == ("PUBLIC",)


def test_each_administrator_look_is_recorded_once_an_hour_where_its_members_see_it(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    ring = projects.create(
        admin, name="Ring", owner_account_id=ada.account_id, clearance=["INTERNAL"]
    )
    laser = projects.create(
        admin, name="Laser", owner_account_id=ada.account_id, clearance=["INTERNAL"]
    )
    oversight = Oversight(lab.connection, admin, now=lab.clock)
    oversight.project(ring)
    oversight.project(ring)
    assert len(access_log(lab.connection, ring, readable=ALL_LEVELS)) == 1, (
        "a refresh is not another look"
    )
    lab.clock.advance(hours=1, minutes=1)
    oversight.project(ring)
    assert len(access_log(lab.connection, ring, readable=ALL_LEVELS)) == 2
    oversight.member(ada.account_id)
    for project_id in (ring, laser):
        kinds = [
            kind
            for _w, kind, _q, _at in access_log(lab.connection, project_id, readable=ALL_LEVELS)
        ]
        assert MEMBER_RESEARCH in kinds, (
            "viewing a person's research shows in each of their projects"
        )


def test_only_an_administrator_changes_membership(lab):
    """Central approval: an owner, a member and a non-member change nobody's membership; an
    active administrator grants any clearance, and a demoted one's old Account grants nothing."""
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    cy = lab.member("cy@lab.example", "Cy", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    project_id = projects.create(
        admin, name="Ring", owner_account_id=ada.account_id, clearance=["INTERNAL"]
    )
    for by in (ada, bob):
        assert (
            _code(
                lambda by=by: projects.add_member(
                    project_id, by=by, member_account_id=cy.account_id, clearance=["INTERNAL"]
                )
            )
            == "not_permitted"
        ), "the project's owner, and a non-member, add nobody"
    granted = projects.add_member(
        project_id, by=admin, member_account_id=bob.account_id, clearance=["CONFIDENTIAL_LAB"]
    )
    assert (granted.role, granted.clearance) == ("MEMBER", ("CONFIDENTIAL_LAB",))
    for call in (
        lambda: projects.change_member(
            project_id, by=ada, actor_id=bob.actor_id, clearance=["PUBLIC"], owner=False
        ),
        lambda: projects.remove_member(project_id, by=ada, actor_id=bob.actor_id),
        lambda: projects.remove_member(project_id, by=bob, actor_id=ada.actor_id),
    ):
        assert _code(call) == "not_permitted"
    assert (
        _code(lambda: projects.remove_member(project_id, by=admin, actor_id=ada.actor_id))
        == "last_owner"
    )
    projects.remove_member(project_id, by=admin, actor_id=bob.actor_id)
    assert not projects.membership(project_id, bob.actor_id).active, "deactivated, never deleted"
    second = lab.service().set_role(cy.account_id, "ADMIN", by=admin)
    lab.service().set_role(second.account_id, "MEMBER", by=admin)
    assert (
        _code(
            lambda: projects.add_member(
                project_id, by=second, member_account_id=bob.account_id, clearance=["INTERNAL"]
            )
        )
        == "not_permitted"
    ), "authority is the account as stored now"
    dee = lab.member("dee@lab.example", "Dee", admin=admin)
    lab.service().suspend(dee.account_id, by=admin, reason="left")
    assert (
        _code(
            lambda: projects.add_member(
                project_id, by=admin, member_account_id=dee.account_id, clearance=["INTERNAL"]
            )
        )
        == "not_found"
    ), "a suspended account joins nothing"
    events = lab.service().events(bob.account_id)
    assert [(k, by) for k, by, _d, _at in events[:2]] == [
        ("MEMBERSHIP_REVOKED", "Lab Owner"),
        ("MEMBERSHIP_GRANTED", "Lab Owner"),
    ]


def test_an_administrator_changes_access_and_a_project_keeps_an_owner(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    projects = LabProjects(lab.connection, now=lab.clock)
    project_id = projects.create(
        admin, name="Ring", owner_account_id=ada.account_id, clearance=["INTERNAL", "PUBLIC"]
    )
    projects.add_member(
        project_id, by=admin, member_account_id=bob.account_id, clearance=["PUBLIC"]
    )
    changed = projects.change_member(
        project_id, by=admin, actor_id=bob.actor_id, clearance=["CONFIDENTIAL_LAB"], owner=True
    )
    assert (changed.role, changed.clearance, changed.scopes) == (
        "OWNER",
        ("CONFIDENTIAL_LAB",),
        ("LLM_EGRESS",),
    ), "an owner holds the project's egress authority, and nothing over its membership"
    projects.change_member(
        project_id, by=admin, actor_id=ada.actor_id, clearance=["INTERNAL"], owner=False
    )
    assert (
        _code(
            lambda: projects.change_member(
                project_id, by=admin, actor_id=bob.actor_id, clearance=["INTERNAL"], owner=False
            )
        )
        == "last_owner"
    )
    assert (
        _code(
            lambda: projects.change_member(
                project_id, by=admin, actor_id="act:nobody", clearance=["INTERNAL"], owner=False
            )
        )
        == "not_found"
    )
    assert (
        _code(
            lambda: projects.change_member(
                project_id, by=admin, actor_id=bob.actor_id, clearance=[], owner=True
            )
        )
        == "clearance_required"
    )
    events = lab.service().events(ada.account_id)
    assert [(k, by) for k, by, _d, _at in events[:1]] == [("MEMBERSHIP_CHANGED", "Lab Owner")]
