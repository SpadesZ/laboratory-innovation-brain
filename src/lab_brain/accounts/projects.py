"""Research projects, and who may work in them.

TWO SYSTEM ROLES, NO THIRD. ADMIN and MEMBER are the only system roles. A project membership's
role (OWNER or MEMBER) is not a system role and carries no authority over membership: OWNER
only holds the project's LLM_EGRESS scope -- the authority to DECLARE whether its evidence may
reach an external model, a separate and explicit decision (`/projects/<id>/egress`).

MEMBERSHIP IS AN ADMINISTRATOR'S. Who belongs to a project, at which classification levels, and
who holds its egress authority, is granted, changed and revoked by an active administrator
only -- the laboratory's central approval. Nobody grants themself membership or changes their
own access, an administrator included: an administrator reads every project through recorded
oversight (`accounts.oversight`), and joining one is another administrator's decision. Adding
someone who is already a member is refused rather than silently rewriting their access;
changing it is its own, explicit action. A project keeps at least one active owner. Every
grant, change and revocation is an account event naming who made it. Memberships are
deactivated, never deleted.

A MEMBER may open a new project for their own work: it is created PRIVATE, they are its owner
with the clearance they choose for it, and it appears at once in the administrators' overview.
Anyone else joins it only by an administrator.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.accounts.service import Account, AccountRefused, AccountService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.identifiers import new_id
from lab_brain.security.egress import LLM_EGRESS_SCOPE

OWNER = "OWNER"
MEMBER_ROLE = "MEMBER"
LABELS = tuple(s.value for s in SensitivityLabel)


@dataclass(frozen=True)
class Membership:
    project_id: str
    actor_id: str
    role: str
    clearance: tuple[str, ...]
    scopes: tuple[str, ...]
    active: bool
    display_name: str | None
    email: str | None


class LabProjects:
    def __init__(self, connection: Any, *, now: Callable[[], dt.datetime] = utc_now) -> None:
        self._c = connection
        self._now = now
        self._accounts = AccountService(connection, mailer=None, base_url="", now=now)

    def memberships(self, project_id: str) -> list[Membership]:
        rows = self._c.execute(
            "SELECT m.project_id, m.actor_id, m.role, m.sensitivity_clearance,"
            " m.approval_scopes, m.active, coalesce(a.display_name, x.display_name), a.email"
            " FROM project_memberships m JOIN actors x ON x.actor_id = m.actor_id"
            " LEFT JOIN accounts a ON a.actor_id = m.actor_id"
            " WHERE m.project_id = %s ORDER BY m.active DESC, m.role <> 'OWNER', m.actor_id",
            (project_id,),
        ).fetchall()
        return [
            Membership(
                str(r[0]),
                str(r[1]),
                str(r[2]),
                tuple(sorted(r[3] or ())),
                tuple(sorted(r[4] or ())),
                bool(r[5]),
                r[6],
                r[7],
            )
            for r in rows
        ]

    def membership(self, project_id: str, actor_id: str) -> Membership | None:
        return next((m for m in self.memberships(project_id) if m.actor_id == actor_id), None)

    def create(self, owner: Account, *, name: str, clearance: Sequence[str]) -> str:
        """A new PRIVATE project, owned by `owner` with exactly this clearance in it."""
        current = self._accounts.get(owner.account_id)
        if current is None or not current.is_active:
            raise AccountRefused("not_permitted", "only an active account creates projects")
        title = " ".join(name.split())
        if not title or len(title) > 120:
            raise AccountRefused("invalid_project_name")
        labels = self._labels(clearance)
        if not labels:
            raise AccountRefused("clearance_required")
        project_id = new_id("project")
        now = self._now()
        with self._c.transaction():
            self._c.execute(
                "INSERT INTO projects (project_id, name, privacy_mode, created_at)"
                " VALUES (%s, %s, 'PRIVATE', %s)",
                (project_id, title, now),
            )
            self._grant(project_id, current.actor_id, OWNER, labels, (LLM_EGRESS_SCOPE,), current)
            self._accounts.record_event(
                current.account_id,
                "PROJECT_CREATED",
                current.actor_id,
                {"project_id": project_id},
            )
        return project_id

    def add_member(
        self,
        project_id: str,
        *,
        by: Account,
        member_account_id: str,
        clearance: Sequence[str],
        owner: bool = False,
    ) -> Membership:
        acting = self._authority(project_id, by)
        member = self._accounts.get(member_account_id)
        if member is None or not member.is_active:
            raise AccountRefused("not_found", "only an active account joins a project")
        if member.actor_id == acting.actor_id:
            raise AccountRefused("own_membership", "nobody grants themself membership")
        existing = self.membership(project_id, member.actor_id)
        if existing is not None and existing.active:
            raise AccountRefused("already_member", member.display_name)
        labels = self._required(clearance)
        with self._c.transaction():
            self._grant(
                project_id,
                member.actor_id,
                OWNER if owner else MEMBER_ROLE,
                labels,
                (LLM_EGRESS_SCOPE,) if owner else (),
                acting,
            )
            self._accounts.record_event(
                member.account_id,
                "MEMBERSHIP_GRANTED",
                acting.actor_id,
                {"project_id": project_id, "clearance": list(labels), "owner": owner},
            )
        granted = self.membership(project_id, member.actor_id)
        assert granted is not None
        return granted

    def change_member(
        self,
        project_id: str,
        *,
        by: Account,
        actor_id: str,
        clearance: Sequence[str],
        owner: bool,
    ) -> Membership:
        """A member's role and clearance, set explicitly -- never one's own."""
        acting = self._authority(project_id, by)
        if actor_id == acting.actor_id:
            raise AccountRefused("own_membership", "nobody changes their own access")
        target = self.membership(project_id, actor_id)
        if target is None or not target.active:
            raise AccountRefused("not_found")
        labels = self._required(clearance)
        if target.role == OWNER and not owner and not self._other_owner(project_id, actor_id):
            raise AccountRefused("last_owner", "a project keeps at least one active owner")
        member = self._accounts.by_actor(actor_id)
        with self._c.transaction():
            self._grant(
                project_id,
                actor_id,
                OWNER if owner else MEMBER_ROLE,
                labels,
                (LLM_EGRESS_SCOPE,) if owner else (),
                acting,
            )
            if member is not None:
                self._accounts.record_event(
                    member.account_id,
                    "MEMBERSHIP_CHANGED",
                    acting.actor_id,
                    {"project_id": project_id, "clearance": list(labels), "owner": owner},
                )
        changed = self.membership(project_id, actor_id)
        assert changed is not None
        return changed

    def remove_member(self, project_id: str, *, by: Account, actor_id: str) -> None:
        acting = self._authority(project_id, by)
        target = self.membership(project_id, actor_id)
        if target is None or not target.active:
            raise AccountRefused("not_found")
        if target.role == OWNER and not self._other_owner(project_id, actor_id):
            raise AccountRefused("last_owner", "a project keeps at least one active owner")
        member = self._accounts.by_actor(actor_id)
        with self._c.transaction():
            self._c.execute(
                "UPDATE project_memberships SET active = FALSE"
                " WHERE project_id = %s AND actor_id = %s",
                (project_id, actor_id),
            )
            if member is not None:
                self._accounts.record_event(
                    member.account_id,
                    "MEMBERSHIP_REVOKED",
                    acting.actor_id,
                    {"project_id": project_id},
                )

    def owned_or_assigned(self, actor_id: str) -> list[tuple[str, str, str]]:
        """(project id, name, role) of every active membership."""
        rows = self._c.execute(
            "SELECT p.project_id, p.name, m.role FROM project_memberships m"
            " JOIN projects p ON p.project_id = m.project_id"
            " WHERE m.actor_id = %s AND m.active ORDER BY p.name, p.project_id",
            (actor_id,),
        ).fetchall()
        return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]

    # -- internals --------------------------------------------------------------------------------

    def _authority(self, project_id: str, by: Account) -> Account:
        """The acting account, re-read: an active administrator -- nobody else changes
        membership."""
        current = self._accounts.get(by.account_id)
        if current is None or not current.is_admin:
            raise AccountRefused("not_permitted", "only an administrator changes membership")
        if (
            self._c.execute(
                "SELECT 1 FROM projects WHERE project_id = %s", (project_id,)
            ).fetchone()
            is None
        ):
            raise AccountRefused("not_found")
        return current

    def _other_owner(self, project_id: str, actor_id: str) -> bool:
        return any(
            m.active and m.role == OWNER and m.actor_id != actor_id
            for m in self.memberships(project_id)
        )

    def _required(self, clearance: Sequence[str]) -> tuple[str, ...]:
        """The labels asked for: at least one, and known. The acting administrator may grant
        any."""
        labels = self._labels(clearance)
        if not labels:
            raise AccountRefused("clearance_required")
        return labels

    @staticmethod
    def _labels(clearance: Sequence[str]) -> tuple[str, ...]:
        labels = tuple(sorted(set(clearance)))
        unknown = [x for x in labels if x not in LABELS]
        if unknown:
            raise AccountRefused("invalid_clearance", ", ".join(unknown))
        return labels

    def _grant(
        self,
        project_id: str,
        actor_id: str,
        role: str,
        labels: Sequence[str],
        scopes: Sequence[str],
        by: Account,
    ) -> None:
        self._c.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
            " approval_scopes, granted_at, granted_by_actor_id, active)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)"
            " ON CONFLICT (actor_id, project_id) DO UPDATE SET role = EXCLUDED.role,"
            " sensitivity_clearance = EXCLUDED.sensitivity_clearance,"
            " approval_scopes = EXCLUDED.approval_scopes, granted_at = EXCLUDED.granted_at,"
            " granted_by_actor_id = EXCLUDED.granted_by_actor_id, active = TRUE",
            (actor_id, project_id, role, list(labels), list(scopes), self._now(), by.actor_id),
        )


__all__ = ["LABELS", "MEMBER_ROLE", "OWNER", "LabProjects", "Membership"]
