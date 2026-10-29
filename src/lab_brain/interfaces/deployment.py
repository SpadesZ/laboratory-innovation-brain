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

LEAST-PRIVILEGE DATABASE ACCESS (V1.1). `db-roles` grants the services' role row privileges only
and an auditor's role reads, so the database's own rules bind every service: see
`grant_database_roles`. Connecting the services as that role is the deployment's decision.
"""

from __future__ import annotations

import datetime as dt
import re
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


#: The tables `exists` may be asked about, and the columns it may match on.
_EXISTS = {
    "actors": ("actor_id",),
    "project_memberships": ("actor_id", "project_id"),
    "llm_administrators": ("actor_id",),
}


def exists(c: Any, table: str, **match: str) -> bool:
    """Whether any row of `table` matches -- for `--if-absent`, which writes only on a first
    start and leaves what the workspace has managed since exactly as it is."""
    columns = _EXISTS[table]
    if not match or set(match) - set(columns):
        raise ValueError(f"{table} is matched on {columns}")
    where = " AND ".join(f"{k} = %s" for k in match)
    return bool(
        c.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", tuple(match.values())).fetchone()
    )


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


#: A role name this command writes into SQL. GRANT takes no bind parameters, so the name is checked
#: to be a plain lower-case identifier instead.
_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

#: The migrations ledger: written by the migrator, read by anyone, never written by a service.
_LEDGER = "schema_migrations"

#: The Owner's spend administration (`011t`): its members alone create budgets, declare prices and
#: free endpoints, change ceilings and close circuits. Neither the services nor an auditor is one.
SPEND_ADMIN_ROLE = "lab_brain_spend_admin"

#: The spend tables (`011r`, `011t`): the services read them and write them only through the
#: migrator's functions below, never row by row.
_SPEND_TABLES = (
    "llm_spend_budgets",
    "llm_spend_prices",
    "llm_spend_ledger",
    "llm_spend_free_endpoints",
)

#: What the services may do with the money: reserve a request's worst case, settle or retain it.
_SPEND_OPERATIONS = (
    "llm_spend_reserve(text, text, text, text, bigint, integer, bigint)",
    "llm_spend_settle(text, bigint, bigint, bigint)",
    "llm_spend_retain(text, text)",
)

#: What an auditor may read of an account: everything but its password hash and lockout.
_ACCOUNT_COLUMNS = (
    "account_id, actor_id, email, display_name, system_role, status, email_verified_at,"
    " email_verified_by, approved_at, approved_by_actor_id, created_at"
)


def grant_database_roles(c: Any, *, app_role: str, reader_role: str) -> list[str]:
    """Least-privilege database access: the services' role and an auditor's role (V1.1).

    WHY. Every rule the Causal Warrant Gate puts in the database is a trigger or a constraint, and a
    superuser -- or a table's owner -- can step past both: `session_replication_role`, `ALTER
    TABLE ... DISABLE TRIGGER`, and `TRUNCATE`, which fires no row trigger. So the services connect
    as `app_role`: not a superuser, owning nothing, holding row privileges only, and the triggers
    bind it. `reader_role` reads. The migrator, which owns the schema, runs the migrations and this
    command and nothing else.

    The operator creates both roles, and gives `app_role` its login and password, outside version
    control (`CREATE ROLE lab_brain_app LOGIN PASSWORD ...`). Refused, before anything is granted:
    a role that could undo what is granted here -- a superuser; one that can create roles or
    databases, replicate, bypass row security or set `session_replication_role`; one that owns an
    object in this database; or a member of a role that is or does any of those.

    THE MONEY (`011t`). `app_role` reads the spend tables and changes them only by executing
    `llm_spend_reserve`, `llm_spend_settle` and `llm_spend_retain` -- the migrator's SECURITY
    DEFINER functions; its row writes on them are revoked. Budgets, prices, ceilings, circuits and
    free endpoints are the Owner's spend administration (`lab_brain_spend_admin`), so a role that
    is a member of it is refused here as well: the services must not be able to raise their own
    ceiling.

    Idempotent: privileges are revoked first and granted again, so running it twice, or after a
    migration added tables, leaves exactly this set.
    """
    roles = (app_role, reader_role)
    for role in roles:
        if not _ROLE_NAME.match(role):
            raise OperatorRefused(f"a database role here is a plain lower-case name, not {role!r}")
    if app_role == reader_role:
        raise OperatorRefused("the services' role and the auditors' role are different roles")
    for role in roles:
        row = c.execute(
            "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls,"
            " has_parameter_privilege(oid, 'session_replication_role', 'SET')"
            " FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
        if row is None:
            raise OperatorRefused(
                f"database role {role} does not exist; the operator creates it (and its login) "
                "outside version control"
            )
        if row[0] or row[1]:
            raise OperatorRefused(
                f"{role} can create roles or databases, replicate, bypass row security or turn "
                "triggers off; the services' and auditors' roles hold row privileges only"
            )
        administers = c.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)"
            " AND pg_has_role(%s, %s, 'MEMBER')",
            (SPEND_ADMIN_ROLE, role, SPEND_ADMIN_ROLE),
        ).fetchone()
        if administers is not None and administers[0]:
            raise OperatorRefused(
                f"{role} is a member of {SPEND_ADMIN_ROLE}, the Owner's spend administration: the "
                "services' and auditors' roles must not be able to change budgets, prices or "
                "ceilings"
            )
        owned = c.execute(
            "SELECT (SELECT count(*) FROM pg_class WHERE pg_has_role(%s, relowner, 'USAGE'))"
            " + (SELECT count(*) FROM pg_proc WHERE pg_has_role(%s, proowner, 'USAGE'))"
            " + (SELECT count(*) FROM pg_namespace WHERE pg_has_role(%s, nspowner, 'USAGE'))"
            " + (SELECT count(*) FROM pg_roles r WHERE r.rolsuper"
            "    AND pg_has_role(%s, r.oid, 'MEMBER'))",
            (role, role, role, role),
        ).fetchone()
        if owned is not None and int(owned[0]) > 0:
            raise OperatorRefused(
                f"{role} owns, or acts as a role that owns, objects in this database (or is a "
                "member of a superuser): an owner can turn its own tables' triggers off"
            )
    app, reader = (f'"{r}"' for r in roles)
    statements: tuple[str, ...] = (
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        f"GRANT USAGE ON SCHEMA public TO {app}, {reader}",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {app}, {reader}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {app}, {reader}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app}",
        f"REVOKE INSERT, UPDATE, DELETE ON {_LEDGER} FROM {app}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {reader}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app}",
        f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {reader}",
        # Tables later migrations create, when the same migrator creates them.
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public"
        f" GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {reader}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {app}",
    )
    # Accounts (`012u`): an auditor reads who has which account and role, never a password hash,
    # a session or a reset token. Revoked again on every run, since a later migration's tables
    # reach the auditor through the default privileges above.
    if c.execute("SELECT to_regclass('public.accounts')").fetchone()[0] is not None:
        statements += (
            f"REVOKE SELECT ON accounts, account_sessions, account_tokens FROM {reader}",
            f"GRANT SELECT ({_ACCOUNT_COLUMNS}) ON accounts TO {reader}",
        )
    spend = [
        t
        for t in _SPEND_TABLES
        if c.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is not None
    ]
    if spend:
        statements += (
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {', '.join(spend)} FROM {app}",
            *(
                f"REVOKE ALL ON SEQUENCE {seq} FROM {app}"
                for (seq,) in c.execute(
                    "SELECT pg_get_serial_sequence(t, k) FROM (VALUES"
                    " ('public.llm_spend_prices', 'price_id'),"
                    " ('public.llm_spend_ledger', 'entry_id'),"
                    " ('public.llm_spend_free_endpoints', 'declaration_id')) AS v(t, k)"
                    " WHERE to_regclass(t) IS NOT NULL"
                ).fetchall()
                if seq is not None
            ),
        )
    administered = (
        c.execute(
            "SELECT to_regprocedure('llm_spend_declare_budget(text, text, numeric, text,"
            " numeric, integer, integer)')"
        ).fetchone()[0]
        is not None
    )
    if administered:  # 011t: the operations are granted, never PUBLIC
        statements += tuple(f"GRANT EXECUTE ON FUNCTION {f} TO {app}" for f in _SPEND_OPERATIONS)
    try:
        with c.transaction():
            for statement in statements:
                c.execute(statement)
    except Exception as exc:  # the database's own refusal, as it said it
        diag = getattr(exc, "diag", None)
        if getattr(exc, "sqlstate", None) is None and diag is None:
            raise
        raise OperatorRefused(
            getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
        ) from exc
    row = c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
    tables = 0 if row is None else int(row[0])
    lines = [
        f"database role {app_role}: reads and writes rows of {tables} tables -- no TRUNCATE, no "
        f"ownership, {_LEDGER} read-only; the triggers bind it",
        f"database role {reader_role}: reads them",
    ]
    if spend:
        lines.append(
            f"database role {app_role}: the spend tables are read-only to it; it reserves, settles "
            f"and retains through the migrator's functions, and only members of {SPEND_ADMIN_ROLE} "
            "change budgets, prices, ceilings and free endpoints"
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
    "SPEND_ADMIN_ROLE",
    "OperatorRefused",
    "declare_review_queue",
    "describe",
    "ensure_actor",
    "ensure_project",
    "flag_analysis",
    "grant_database_roles",
    "grant_llm_admin",
    "revoke_llm_admin",
    "set_membership",
]
