"""What an administrator sees of the whole laboratory: people, projects, research, results.

READ-ONLY, AND RECORDED. Oversight answers who works on what, in which state each piece of research
stands and what it concluded -- for every project, including private ones -- and nothing here
writes a scientific record. Each time an administrator opens a project or a person's research, the
access is written to `admin_access_log` (append-only; only an active administrator may appear in
it, `012u`), so a member can be told who looked.

CLASSIFICATION STILL HOLDS. Oversight lists every document's name, kind and classification, and
every result; the text of an evidence excerpt is shown to an administrator only where their own
membership's clearance in that project would show it to anyone (`Workspace._authorized`).
Administrative authority is oversight of the research, not a key to its classified material.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lab_brain.accounts.projects import LabProjects, Membership
from lab_brain.accounts.service import Account, AccountRefused, AccountService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.identifiers import new_id


@dataclass(frozen=True)
class MemberSummary:
    account: Account
    owned: int
    assigned: int
    episodes: int
    last_activity: dt.datetime | None


@dataclass(frozen=True)
class ProjectSummary:
    project_id: str
    name: str
    privacy_mode: str
    created_at: dt.datetime
    archived: bool
    owners: tuple[str, ...]
    members: int
    episodes: int
    open_episodes: int
    last_activity: dt.datetime | None


@dataclass(frozen=True)
class EpisodeSummary:
    episode_id: str
    project_id: str
    goal: str
    state: str
    outcome_status: str | None
    opened_by: str
    question_label: str | None
    started: dt.datetime
    runs: int
    last_outcome: str | None


@dataclass(frozen=True)
class DataSummary:
    item_id: str
    file_name: str
    kind: str
    label: str
    submitted_by: str
    submitted_at: dt.datetime


@dataclass(frozen=True)
class ProjectDetail:
    summary: ProjectSummary
    memberships: tuple[Membership, ...]
    episodes: tuple[EpisodeSummary, ...]
    data: tuple[DataSummary, ...]


#: What an administrator opened, as `admin_access_log.subject` records it.
PROJECT_SUMMARY = "project-summary"
EPISODE_REPORTS = "episode-reports:"
MEMBER_RESEARCH = "member-research:"
_SUBJECTS = (PROJECT_SUMMARY, EPISODE_REPORTS, MEMBER_RESEARCH)

_EPISODES = (
    "SELECT e.episode_id, e.project_id, e.goal, e.state, e.outcome_status,"
    " coalesce(a.display_name, x.display_name, r.actor_id),"
    " (SELECT q.question_label FROM research_runs q WHERE q.episode_id = e.episode_id"
    "   AND q.question_label IS NOT NULL ORDER BY q.ordinal DESC LIMIT 1),"
    " e.start_time,"
    " (SELECT count(*) FROM research_runs c WHERE c.episode_id = e.episode_id),"
    " (SELECT l.outcome FROM research_runs l WHERE l.episode_id = e.episode_id"
    "   ORDER BY l.ordinal DESC LIMIT 1)"
    " FROM research_episodes e"
    " JOIN research_runs r ON r.episode_id = e.episode_id AND r.ordinal = 1"
    " JOIN actors x ON x.actor_id = r.actor_id"
    " LEFT JOIN accounts a ON a.actor_id = r.actor_id"
)


def _episode(r: Any) -> EpisodeSummary:
    return EpisodeSummary(
        str(r[0]), str(r[1]), str(r[2]), str(r[3]), r[4], str(r[5]), r[6], r[7], int(r[8]), r[9]
    )


class Oversight:
    def __init__(
        self, connection: Any, admin: Account, *, now: Callable[[], dt.datetime] = utc_now
    ) -> None:
        self._c = connection
        self._now = now
        current = AccountService(connection, mailer=None, base_url="", now=now).get(
            admin.account_id
        )
        if current is None or not current.is_admin:
            raise AccountRefused("not_permitted", "oversight is an active administrator's")
        self.admin = current

    def members(self) -> list[MemberSummary]:
        accounts = AccountService(self._c, mailer=None, base_url="", now=self._now).all()
        out = []
        for account in accounts:
            row = self._c.execute(
                "SELECT count(*) FILTER (WHERE role = 'OWNER' AND active),"
                " count(*) FILTER (WHERE role <> 'OWNER' AND active)"
                " FROM project_memberships WHERE actor_id = %s",
                (account.actor_id,),
            ).fetchone()
            activity = self._c.execute(
                "SELECT count(DISTINCT episode_id) FILTER (WHERE ordinal = 1), max(started_at)"
                " FROM research_runs WHERE actor_id = %s",
                (account.actor_id,),
            ).fetchone()
            out.append(
                MemberSummary(account, int(row[0]), int(row[1]), int(activity[0] or 0), activity[1])
            )
        return out

    def projects(self) -> list[ProjectSummary]:
        rows = self._c.execute(
            "SELECT p.project_id, p.name, p.privacy_mode, p.created_at, p.archived_at IS NOT NULL,"
            " coalesce(array_agg(DISTINCT coalesce(a.display_name, x.display_name, m.actor_id))"
            "   FILTER (WHERE m.role = 'OWNER' AND m.active), '{}'),"
            " count(DISTINCT m.actor_id) FILTER (WHERE m.active),"
            " (SELECT count(*) FROM research_episodes e WHERE e.project_id = p.project_id),"
            " (SELECT count(*) FROM research_episodes e WHERE e.project_id = p.project_id"
            "   AND e.state NOT IN ('COMPLETED', 'ABANDONED')),"
            " (SELECT max(r.started_at) FROM research_runs r WHERE r.project_id = p.project_id)"
            " FROM projects p"
            " LEFT JOIN project_memberships m ON m.project_id = p.project_id"
            " LEFT JOIN actors x ON x.actor_id = m.actor_id"
            " LEFT JOIN accounts a ON a.actor_id = m.actor_id"
            " GROUP BY p.project_id ORDER BY p.name, p.project_id"
        ).fetchall()
        return [
            ProjectSummary(
                str(r[0]),
                str(r[1]),
                str(r[2]),
                r[3],
                bool(r[4]),
                tuple(sorted(r[5] or ())),
                int(r[6]),
                int(r[7]),
                int(r[8]),
                r[9],
            )
            for r in rows
        ]

    def project(self, project_id: str) -> ProjectDetail | None:
        summary = next((p for p in self.projects() if p.project_id == project_id), None)
        if summary is None:
            return None
        self.record(project_id, PROJECT_SUMMARY)
        episodes = [
            _episode(r)
            for r in self._c.execute(
                _EPISODES + " WHERE e.project_id = %s ORDER BY e.start_time DESC", (project_id,)
            ).fetchall()
        ]
        data = [
            DataSummary(str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), r[5])
            for r in self._c.execute(
                "SELECT d.item_id, d.file_name, d.declared_kind, d.declared_label,"
                " coalesce(a.display_name, x.display_name, d.actor_id), d.declared_at"
                " FROM research_data_declarations d JOIN actors x ON x.actor_id = d.actor_id"
                " LEFT JOIN accounts a ON a.actor_id = d.actor_id"
                " WHERE d.project_id = %s ORDER BY d.declared_at DESC, d.item_id",
                (project_id,),
            ).fetchall()
        ]
        return ProjectDetail(
            summary,
            tuple(LabProjects(self._c, now=self._now).memberships(project_id)),
            tuple(episodes),
            tuple(data),
        )

    def member(
        self, account_id: str
    ) -> tuple[Account, list[tuple[str, str, str]], list[EpisodeSummary]] | None:
        account = AccountService(self._c, mailer=None, base_url="", now=self._now).get(account_id)
        if account is None:
            return None
        projects = LabProjects(self._c, now=self._now).owned_or_assigned(account.actor_id)
        episodes = [
            _episode(r)
            for r in self._c.execute(
                _EPISODES + " WHERE r.actor_id = %s ORDER BY e.start_time DESC",
                (account.actor_id,),
            ).fetchall()
        ]
        # The page lists this person's research in every project, so every one of those
        # projects' members is told an administrator looked -- not only a log with no project.
        self.record(None, f"{MEMBER_RESEARCH}{account_id}")
        for listed in sorted({p for p, _n, _r in projects} | {e.project_id for e in episodes}):
            self.record(listed, f"{MEMBER_RESEARCH}{account_id}")
        return account, projects, episodes

    def episode_project(self, episode_id: str) -> str | None:
        row = self._c.execute(
            "SELECT project_id FROM research_episodes WHERE episode_id = %s", (episode_id,)
        ).fetchone()
        return None if row is None else str(row[0])

    def record(self, project_id: str | None, subject: str) -> None:
        """One record per administrator, project and subject an hour: a refresh or a language
        switch is not another look."""
        if self._c.execute(
            "SELECT 1 FROM admin_access_log WHERE admin_actor_id = %s"
            " AND project_id IS NOT DISTINCT FROM %s AND subject = %s AND accessed_at > %s",
            (self.admin.actor_id, project_id, subject, self._now() - dt.timedelta(hours=1)),
        ).fetchone():
            return
        self._c.execute(
            "INSERT INTO admin_access_log (access_id, admin_actor_id, project_id, subject,"
            " accessed_at) VALUES (%s, %s, %s, %s, %s)",
            (new_id("admin_access"), self.admin.actor_id, project_id, subject, self._now()),
        )


def access_log(connection: Any, project_id: str) -> list[tuple[str, str, str, dt.datetime]]:
    """The administrator accesses to a project, for its members: (who, what -- PROJECT_SUMMARY,
    EPISODE_REPORTS or MEMBER_RESEARCH --, the research question it concerns or "", when)."""
    rows = connection.execute(
        "SELECT coalesce(a.display_name, l.admin_actor_id), l.subject,"
        " coalesce(e.goal, ''), l.accessed_at"
        " FROM admin_access_log l LEFT JOIN accounts a ON a.actor_id = l.admin_actor_id"
        " LEFT JOIN research_episodes e ON l.subject = %s || e.episode_id"
        " WHERE l.project_id = %s ORDER BY l.accessed_at DESC LIMIT 50",
        (EPISODE_REPORTS, project_id),
    ).fetchall()
    return [
        (str(r[0]), next(k for k in _SUBJECTS if str(r[1]).startswith(k)), str(r[2]), r[3])
        for r in rows
        if any(str(r[1]).startswith(k) for k in _SUBJECTS)
    ]


__all__ = [
    "EPISODE_REPORTS",
    "MEMBER_RESEARCH",
    "PROJECT_SUMMARY",
    "DataSummary",
    "EpisodeSummary",
    "MemberSummary",
    "Oversight",
    "ProjectDetail",
    "ProjectSummary",
    "access_log",
]
