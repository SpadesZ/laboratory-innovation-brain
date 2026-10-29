"""The account-change audit (`011u`): what changed accounts and memberships, by whom, and whether
the application recorded it.

A12 (account-security audit 2026-10-20): a database writer can change a role, a state or a
membership directly in SQL, leaving no account event. `011u` records every such change, by every
writer its triggers bind, in the append-only, hash-chained `account_change_audit`. This module
reads it back and says three things:

    1. whether the chain is intact -- each row's digest recomputed HERE, in Python, from the
       stored columns, not by a database function a writer could replace;
    2. whether it still contains a head the operator copied out earlier (`SEQ:DIGEST`): the one
       check that exposes a superuser or owner who rewrote the table and recomputed the chain;
    3. which changes no application account event explains: no `account_events` row for the same
       account written in the same transaction. Those are direct writes -- the operator's command
       line (`lab-brain admin member`), a migration, or someone with database access.

WHAT IT CANNOT SAY. A superuser or the tables' owner can disable the triggers first; their
change is then not recorded at all, and only a head recorded outside the database, plus the
database's own logs (pgaudit, WAL archived elsewhere), would show it. A writer who also inserts a
matching account event makes its change read "explained"; the audit row still names the login
role and the old and new values. A12 stays an Owner decision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

GENESIS = "0" * 64
_DOMAIN = "lab-brain/account-change-audit/1"

_COLUMNS = (
    "audit_seq, table_name, operation, account_id, actor_id, project_id, old_values::text,"
    " new_values::text, db_session_user, role_setting, application_name, txid,"
    " to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),"
    " previous_seq, previous_digest, row_digest"
)


@dataclass(frozen=True)
class AuditRow:
    seq: int
    table_name: str
    operation: str
    account_id: str | None
    actor_id: str | None
    project_id: str | None
    old_values: str | None
    new_values: str | None
    session_user: str
    role_setting: str
    application_name: str
    txid: int
    recorded_at: str
    previous_seq: int | None
    previous_digest: str
    row_digest: str

    def digest_text(self) -> str:
        """The text `011u`'s `account_change_audit_digest_text` covers, rebuilt here."""
        return "\n".join(
            (
                _DOMAIN,
                self.previous_digest,
                str(self.seq),
                self.table_name,
                self.operation,
                self.account_id or "",
                self.actor_id or "",
                self.project_id or "",
                self.old_values if self.old_values is not None else "null",
                self.new_values if self.new_values is not None else "null",
                self.session_user,
                self.role_setting,
                self.application_name,
                str(self.txid),
                self.recorded_at,
            )
        )

    def recomputed_digest(self) -> str:
        return hashlib.sha256(self.digest_text().encode("utf-8")).hexdigest()

    @property
    def writer(self) -> str:
        role = "" if self.role_setting in ("none", "") else f" as {self.role_setting}"
        app = f" ({self.application_name})" if self.application_name else ""
        return f"{self.session_user}{role}{app}"

    def describe(self) -> str:
        subject = self.account_id or self.actor_id or "(whole table)"
        where = f" in {self.project_id}" if self.project_id else ""
        change = _change(self.old_values, self.new_values)
        return (
            f"#{self.seq} {self.recorded_at} {self.operation} {self.table_name} {subject}{where}"
            f" by {self.writer}, transaction {self.txid}{change}"
        )


def _change(old: str | None, new: str | None) -> str:
    if old is None and new is None:
        return ""
    before: dict[str, Any] = {} if old is None else json.loads(old)
    after: dict[str, Any] = {} if new is None else json.loads(new)
    if after.get("password_replaced") is False:
        del after["password_replaced"]
    keys = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    parts = [f"{k}: {before.get(k)!r} -> {after.get(k)!r}" for k in keys]
    return (": " + "; ".join(parts)) if parts else ""


def _row(values: Sequence[Any]) -> AuditRow:
    return AuditRow(
        seq=int(values[0]),
        table_name=str(values[1]),
        operation=str(values[2]),
        account_id=values[3],
        actor_id=values[4],
        project_id=values[5],
        old_values=values[6],
        new_values=values[7],
        session_user=str(values[8]),
        role_setting=str(values[9]),
        application_name=str(values[10]),
        txid=int(values[11]),
        recorded_at=str(values[12]),
        previous_seq=None if values[13] is None else int(values[13]),
        previous_digest=str(values[14]),
        row_digest=str(values[15]),
    )


def rows(connection: Any, *, since_seq: int | None = None) -> list[AuditRow]:
    return [
        _row(r)
        for r in connection.execute(
            f"SELECT {_COLUMNS} FROM account_change_audit"
            " WHERE %s::bigint IS NULL OR audit_seq > %s ORDER BY audit_seq",
            (since_seq, since_seq),
        ).fetchall()
    ]


@dataclass(frozen=True)
class ChainState:
    rows: int
    head_seq: int | None
    head_digest: str
    problems: tuple[str, ...]

    @property
    def head(self) -> str:
        return f"{self.head_seq if self.head_seq is not None else 0}:{self.head_digest}"

    @property
    def intact(self) -> bool:
        return not self.problems


def verify_chain(connection: Any, *, expect_head: str | None = None) -> ChainState:
    """Walk the chain from its genesis, recomputing every digest; compare with the stored head
    and, when given, with a head (`SEQ:DIGEST`) recorded outside the database earlier."""
    every = rows(connection)
    problems: list[str] = []
    by_previous: dict[int | None, list[AuditRow]] = {}
    for row in every:
        by_previous.setdefault(row.previous_seq, []).append(row)
        if row.recomputed_digest() != row.row_digest:
            problems.append(f"#{row.seq}: its digest is not the digest of its fields")
    for previous, followers in by_previous.items():
        if len(followers) > 1:
            problems.append(
                f"the chain forks after #{previous}: " + ", ".join(f"#{r.seq}" for r in followers)
            )
    walked: list[AuditRow] = []
    seq: int | None = None
    digest = GENESIS
    while True:
        followers = by_previous.get(seq, [])
        if not followers:
            break
        row = followers[0]
        if row.previous_digest != digest:
            problems.append(f"#{row.seq} does not chain to #{seq}'s digest")
        walked.append(row)
        seq, digest = row.seq, row.row_digest
        if len(walked) > len(every):  # pragma: no cover - a cycle; refused, never looped
            problems.append("the chain loops")
            break
    if len(walked) != len(every):
        problems.append(
            f"{len(every) - len(walked)} audit row(s) are not on the chain from its genesis"
        )
    stored = connection.execute(
        "SELECT last_seq, last_digest FROM account_change_audit_head"
    ).fetchone()
    if stored is None or (stored[0], stored[1]) != (seq, digest):
        problems.append("the stored chain head is not the end of the chain")
    if expect_head is not None:
        problems.extend(_expected(expect_head, every))
    return ChainState(len(every), seq, digest, tuple(problems))


def _expected(expect_head: str, every: Sequence[AuditRow]) -> list[str]:
    seq_text, _, digest = expect_head.partition(":")
    try:
        expected_seq = int(seq_text)
    except ValueError:
        return [f"--expect-head is SEQ:DIGEST, not {expect_head!r}"]
    if expected_seq == 0 and digest == GENESIS:
        return []
    found = next((r for r in every if r.seq == expected_seq), None)
    if found is None:
        return [f"the head recorded earlier, #{expected_seq}, is no longer in the audit table"]
    if found.row_digest != digest:
        return [
            f"#{expected_seq}'s digest is not the one recorded earlier: the audit table was "
            "rewritten"
        ]
    return []


def unexplained_changes(connection: Any, *, since_seq: int | None = None) -> list[AuditRow]:
    """Changes of accounts and memberships no application account event explains: none written
    for the same account in the same transaction (a whole-table TRUNCATE never is)."""
    return [
        _row(r)
        for r in connection.execute(
            f"SELECT {_COLUMNS} FROM account_change_audit c"
            " WHERE c.table_name IN ('accounts', 'project_memberships')"
            " AND (%s::bigint IS NULL OR c.audit_seq > %s)"
            " AND NOT EXISTS (SELECT 1 FROM account_change_audit e"
            "   WHERE e.table_name = 'account_events' AND e.operation = 'INSERT'"
            "     AND e.txid = c.txid AND e.account_id IS NOT DISTINCT FROM c.account_id"
            "     AND c.account_id IS NOT NULL)"
            " ORDER BY c.audit_seq",
            (since_seq, since_seq),
        ).fetchall()
    ]


def report(
    connection: Any, *, since_seq: int | None = None, expect_head: str | None = None
) -> tuple[list[str], bool]:
    """The operator's report, and whether the chain (and any expected head) held."""
    chain = verify_chain(connection, expect_head=expect_head)
    lines = [
        f"account change audit: {chain.rows} rows; chain "
        + ("intact" if chain.intact else "BROKEN"),
    ]
    lines += [f"  BROKEN: {p}" for p in chain.problems]
    lines.append(f"head (record it outside the database): {chain.head}")
    unexplained = unexplained_changes(connection, since_seq=since_seq)
    lines.append(
        f"changes with no application account event in their transaction: {len(unexplained)}"
    )
    lines += [f"  {row.describe()}" for row in unexplained]
    lines.append(
        "not detected here: a superuser's or the tables' owner's change with the triggers "
        "disabled (A12 stays an Owner decision)"
    )
    return lines, chain.intact


__all__ = [
    "GENESIS",
    "AuditRow",
    "ChainState",
    "report",
    "rows",
    "unexplained_changes",
    "verify_chain",
]
