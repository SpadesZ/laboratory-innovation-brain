"""The deployment operator's commands (`lab-brain admin ...`): who exists, which projects exist,
who belongs to which with what clearance and approval scopes, and who administers the language-
model routes.

THE OPERATOR IS WHOEVER HOLDS THE DATABASE CREDENTIALS. That is already the trust root of every
command-line process (`LAB_BRAIN_DATABASE_URL`) and of the workspace, which acts as the actor it was
started as. These commands make the operator's decisions explicit and recorded instead of leaving
them to hand-written SQL -- the only way a deployment could be set up before them.

EXPLICIT, AND NEVER IMPLIED. A membership grants exactly the clearance and approval scopes named:
nothing defaults to broad access, `approval_scopes` stays a set of NAMED scopes (`LLM_EGRESS`,
`BUDGET_OVERRUN`, `VIEW_TECHNICAL_DIAGNOSTICS`), and a name the system does not know is refused
rather than stored to grant nothing silently. LLM administration is its own grant (`012f`), to an
active HUMAN actor, revoked rather than deleted. A project is created in PRIVATE mode unless another
mode is named.

Every command is idempotent: run twice with the same arguments, the second run changes nothing and
says so.

THE REVIEW QUEUE IS DECLARED HERE TOO (Causal Warrant Gate V1.1). A project's review-queue policy
-- capacity, SLA, expiry, and the person whose standing decision authorises automatic expiry -- is
what lets a DIAGNOSTIC_WARRANT question be asked at all (`012o` refuses one with no deadline). A
new declaration is a new version; the one it replaces is deactivated, never edited, so every item
already queued keeps the deadline it was given. `flag-analysis` records that a stored conclusion
is wrong or unwarranted without touching it (`012p`).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from lab_brain.core.budget import BUDGET_OVERRUN_SCOPE
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.security.egress import LLM_EGRESS_SCOPE
from lab_brain.surface.disclosure import VIEW_TECHNICAL_SCOPE

PRIVACY_MODES = ("PRIVATE", "RESEARCH", "NOVELTY_AUDIT")

#: The approval scopes the system reads. Anything else would be stored and grant nothing.
KNOWN_SCOPES = (BUDGET_OVERRUN_SCOPE, LLM_EGRESS_SCOPE, VIEW_TECHNICAL_SCOPE)


class OperatorRefused(ValueError):
    """The operator's request is refused as asked. Nothing was written."""


def ensure_actor(c: Any, actor_id: str, display_name: str) -> str:
    """A HUMAN actor, active. Created, renamed, or unchanged."""
    if not actor_id.startswith("act:") or len(actor_id) > 200:
        raise OperatorRefused(f"an actor id looks like act:<name>, not {actor_id!r}")
    row = c.execute(
        "SELECT actor_type, display_name, active FROM actors WHERE actor_id = %s", (actor_id,)
    ).fetchone()
    if row is None:
        c.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name, active)"
            " VALUES (%s, 'HUMAN', %s, TRUE)",
            (actor_id, display_name),
        )
        return f"created actor {actor_id} (HUMAN)"
    if row[0] != "HUMAN":
        raise OperatorRefused(f"{actor_id} is a {row[0]} actor, not a person")
    if not row[2]:
        raise OperatorRefused(
            f"{actor_id} is deactivated; reactivating an account is not done by this command"
        )
    if row[1] == display_name:
        return f"actor {actor_id} unchanged"
    c.execute("UPDATE actors SET display_name = %s WHERE actor_id = %s", (display_name, actor_id))
    return f"actor {actor_id} renamed"


def ensure_project(c: Any, project_id: str, name: str, privacy_mode: str | None = None) -> str:
    """A project. Created PRIVATE unless a mode is named; an existing one is renamed and, when a
    mode is named, set to it."""
    if not project_id.startswith("prj:") or len(project_id) > 200:
        raise OperatorRefused(f"a project id looks like prj:<name>, not {project_id!r}")
    if privacy_mode is not None and privacy_mode not in PRIVACY_MODES:
        raise OperatorRefused(f"a privacy mode is one of {', '.join(PRIVACY_MODES)}")
    row = c.execute(
        "SELECT name, privacy_mode, archived_at FROM projects WHERE project_id = %s", (project_id,)
    ).fetchone()
    if row is None:
        c.execute(
            "INSERT INTO projects (project_id, name, privacy_mode) VALUES (%s, %s, %s)",
            (project_id, name, privacy_mode or "PRIVATE"),
        )
        return f"created project {project_id} ({privacy_mode or 'PRIVATE'} mode)"
    if row[2] is not None:
        raise OperatorRefused(f"project {project_id} is archived")
    wanted = (name, privacy_mode or row[1])
    if (row[0], row[1]) == wanted:
        return f"project {project_id} unchanged"
    c.execute(
        "UPDATE projects SET name = %s, privacy_mode = %s WHERE project_id = %s",
        (*wanted, project_id),
    )
    return f"project {project_id} set to {wanted[1]} mode, named {name!r}"


def set_membership(
    c: Any,
    project_id: str,
    actor_id: str,
    *,
    role: str,
    clearance: Sequence[str],
    scopes: Sequence[str],
) -> str:
    """The actor's membership of the project: exactly this clearance and these scopes, active."""
    labels = sorted(set(clearance))
    unknown = [x for x in labels if x not in {s.value for s in SensitivityLabel}]
    if unknown:
        raise OperatorRefused(f"unknown sensitivity label(s): {', '.join(unknown)}")
    granted = sorted(set(scopes))
    unknown = [x for x in granted if x not in KNOWN_SCOPES]
    if unknown:
        raise OperatorRefused(
            f"unknown approval scope(s): {', '.join(unknown)}; known: {', '.join(KNOWN_SCOPES)}"
        )
    for table, key, value in (
        ("actors", "actor_id", actor_id),
        ("projects", "project_id", project_id),
    ):
        if c.execute(f"SELECT 1 FROM {table} WHERE {key} = %s", (value,)).fetchone() is None:
            raise OperatorRefused(f"no {table[:-1]} {value}")
    row = c.execute(
        "SELECT role, sensitivity_clearance, approval_scopes, active FROM project_memberships"
        " WHERE actor_id = %s AND project_id = %s",
        (actor_id, project_id),
    ).fetchone()
    wanted = (role, labels, granted, True)
    if row is not None and (row[0], sorted(row[1] or ()), sorted(row[2] or ()), row[3]) == wanted:
        return f"membership {actor_id} in {project_id} unchanged"
    c.execute(
        "INSERT INTO project_memberships"
        " (actor_id, project_id, role, sensitivity_clearance, approval_scopes, active)"
        " VALUES (%s, %s, %s, %s, %s, TRUE)"
        " ON CONFLICT (actor_id, project_id) DO UPDATE SET role = EXCLUDED.role,"
        " sensitivity_clearance = EXCLUDED.sensitivity_clearance,"
        " approval_scopes = EXCLUDED.approval_scopes, active = TRUE",
        (actor_id, project_id, role, labels, granted),
    )
    return (
        f"membership {actor_id} in {project_id}: role {role}, clearance "
        f"{', '.join(labels) or 'none'}, scopes {', '.join(granted) or 'none'}"
    )


def grant_llm_admin(c: Any, actor_id: str, at: dt.datetime) -> str:
    current = c.execute(
        "SELECT 1 FROM llm_administrators WHERE actor_id = %s AND revoked_at IS NULL", (actor_id,)
    ).fetchone()
    if current is not None:
        return f"{actor_id} already administers the LLM routes"
    _write(
        c,
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES (%s, %s, 'OPERATOR_CLI')",
        (actor_id, at),
    )
    return f"{actor_id} now administers this deployment's LLM routes"


def revoke_llm_admin(c: Any, actor_id: str, at: dt.datetime) -> str:
    current = c.execute(
        "SELECT granted_at FROM llm_administrators WHERE actor_id = %s AND revoked_at IS NULL",
        (actor_id,),
    ).fetchone()
    if current is None:
        return f"{actor_id} does not administer the LLM routes"
    _write(
        c,
        "UPDATE llm_administrators SET revoked_at = %s WHERE actor_id = %s AND granted_at = %s",
        (max(at, current[0]), actor_id, current[0]),
    )
    return f"{actor_id} no longer administers the LLM routes"


#: The defaults a declaration uses for what it does not name: a warrant question is a short
#: judgment (15 minutes each, `VerificationLoop._ask`), due within three days and closed by expiry
#: after fourteen, when the next run asks it again.
REVIEW_QUEUE_DEFAULTS = {
    "capacity": 50,
    "sla_minutes": 3 * 24 * 60,
    "expiry_minutes": 14 * 24 * 60,
    "reviewer_minutes_per_day": 60,
}


def declare_review_queue(
    c: Any,
    project_id: str,
    *,
    declared_by: str,
    at: dt.datetime,
    capacity: int = REVIEW_QUEUE_DEFAULTS["capacity"],
    sla_minutes: int = REVIEW_QUEUE_DEFAULTS["sla_minutes"],
    expiry_minutes: int = REVIEW_QUEUE_DEFAULTS["expiry_minutes"],
    reviewer_minutes_per_day: int = REVIEW_QUEUE_DEFAULTS["reviewer_minutes_per_day"],
    if_absent: bool = False,
) -> str:
    """The project's active review-queue policy: these numbers, declared by `declared_by`.

    `declared_by` must be an active person in the project: expiry under this policy is that
    person's standing decision (`v3.3-a15`), not the operator's or a service account's.
    """
    if (
        c.execute(
            "SELECT 1 FROM actors a JOIN project_memberships m ON m.actor_id = a.actor_id"
            " WHERE a.actor_id = %s AND a.actor_type = 'HUMAN' AND a.active"
            " AND m.project_id = %s AND m.active",
            (declared_by, project_id),
        ).fetchone()
        is None
    ):
        raise OperatorRefused(
            f"{declared_by} is not an active person in {project_id}; a review queue's expiry is a "
            "member's standing decision"
        )
    if expiry_minutes < sla_minutes or min(sla_minutes, expiry_minutes) <= 0 or capacity < 0:
        raise OperatorRefused(
            "a review queue needs a positive SLA, an expiry no earlier than it, and a capacity of "
            "zero or more"
        )
    current = c.execute(
        "SELECT policy_id, version, capacity, default_sla_minutes, default_expiry_minutes,"
        " reviewer_minutes_per_day, declared_by_actor_id FROM review_queue_policies"
        " WHERE project_id = %s AND active",
        (project_id,),
    ).fetchone()
    wanted = (capacity, sla_minutes, expiry_minutes, reviewer_minutes_per_day, declared_by)
    if current is not None and (if_absent or tuple(current[2:]) == wanted):
        return f"review queue of {project_id} unchanged ({current[0]}@{current[1]})"
    policy_id = f"rqp:{project_id.removeprefix('prj:')}"
    versions = [
        int(v)
        for (v,) in c.execute(
            "SELECT version FROM review_queue_policies WHERE policy_id = %s", (policy_id,)
        ).fetchall()
        if str(v).isdigit()
    ]
    version = str(max(versions, default=0) + 1)
    try:
        with c.transaction():
            c.execute(
                "UPDATE review_queue_policies SET active = FALSE WHERE project_id = %s AND active",
                (project_id,),
            )
            c.execute(
                "INSERT INTO review_queue_policies (policy_id, version, project_id, capacity,"
                " default_sla_minutes, default_expiry_minutes, reviewer_minutes_per_day,"
                " declared_by_actor_id, effective_from, active)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)",
                (
                    policy_id,
                    version,
                    project_id,
                    capacity,
                    sla_minutes,
                    expiry_minutes,
                    reviewer_minutes_per_day,
                    declared_by,
                    at,
                ),
            )
    except Exception as exc:
        diag = getattr(exc, "diag", None)
        if getattr(exc, "sqlstate", None) is None and diag is None:
            raise
        raise OperatorRefused(
            getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
        ) from exc
    replaced = "" if current is None else f", replacing {current[0]}@{current[1]}"
    return (
        f"review queue of {project_id}: {policy_id}@{version} -- capacity {capacity}, due after "
        f"{sla_minutes} min, expires after {expiry_minutes} min, declared by {declared_by}"
        f"{replaced}"
    )


FLAG_KINDS = ("FALSE_CONFIRMATION", "UNWARRANTED_CONFIRMATION")


def flag_analysis(
    c: Any,
    failure_analysis_id: str,
    *,
    kind: str,
    statement: str,
    evidence: Sequence[str],
    recorded_by: str,
) -> str:
    """Flag a stored conclusion, bound to its exact content; the conclusion is not touched."""
    if kind not in FLAG_KINDS:
        raise OperatorRefused(f"a flag is one of {', '.join(FLAG_KINDS)}")
    if not statement.strip() or not [e for e in evidence if e.strip()]:
        raise OperatorRefused("a flag says what is wrong and cites at least one piece of evidence")
    row = c.execute(
        "SELECT project_id, failure_analysis_digest(f) FROM failure_analyses f"
        " WHERE f.failure_analysis_id = %s",
        (failure_analysis_id,),
    ).fetchone()
    if row is None:
        raise OperatorRefused(f"no failure analysis {failure_analysis_id}")
    flag_id = f"flg:{uuid.uuid4()}"
    _write(
        c,
        "INSERT INTO failure_analysis_flags (flag_id, project_id, failure_analysis_id, kind,"
        " statement, evidence_refs, analysis_digest, recorded_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            flag_id,
            row[0],
            failure_analysis_id,
            kind,
            statement.strip(),
            [e.strip() for e in evidence if e.strip()],
            row[1],
            recorded_by,
        ),
    )
    return f"flagged {failure_analysis_id} {kind} ({flag_id})"


def describe(c: Any) -> list[str]:
    """The deployment's actors, projects, memberships and LLM administrators, as text."""
    lines = ["actors:"]
    for r in c.execute(
        "SELECT actor_id, actor_type, display_name, active,"
        " llm_is_administrator(actor_id) FROM actors ORDER BY actor_id"
    ).fetchall():
        admin = ", LLM administrator" if r[4] else ""
        lines.append(f"  {r[0]}  {r[1]}{'' if r[3] else ' (inactive)'}{admin}  {r[2] or ''}")
    lines.append("projects:")
    for r in c.execute(
        "SELECT project_id, privacy_mode, name, archived_at FROM projects ORDER BY project_id"
    ).fetchall():
        lines.append(f"  {r[0]}  {r[1]}{' (archived)' if r[3] else ''}  {r[2]}")
    lines.append("memberships:")
    for r in c.execute(
        "SELECT project_id, actor_id, role, sensitivity_clearance, approval_scopes, active"
        " FROM project_memberships ORDER BY project_id, actor_id"
    ).fetchall():
        lines.append(
            f"  {r[0]}  {r[1]}  {r[2]}{'' if r[5] else ' (inactive)'}  clearance "
            f"{','.join(r[3] or ()) or '-'}  scopes {','.join(r[4] or ()) or '-'}"
        )
    return lines


def _write(c: Any, sql: str, params: Sequence[object]) -> None:
    try:
        with c.transaction():
            c.execute(sql, params)
    except Exception as exc:  # the database's own rule, as it said it
        diag = getattr(exc, "diag", None)
        if getattr(exc, "sqlstate", None) is None and diag is None:
            raise
        raise OperatorRefused(
            getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
        ) from exc


__all__ = [
    "FLAG_KINDS",
    "KNOWN_SCOPES",
    "PRIVACY_MODES",
    "REVIEW_QUEUE_DEFAULTS",
    "OperatorRefused",
    "declare_review_queue",
    "describe",
    "ensure_actor",
    "ensure_project",
    "flag_analysis",
    "grant_llm_admin",
    "revoke_llm_admin",
    "set_membership",
]
