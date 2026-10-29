"""A12's explicit boundary (`011u`): a direct SQL change of an account or membership is EVIDENT,
not prevented; the services' role cannot erase the evidence; a superuser still can.

Against the real server. The test database's own user is a SUPERUSER, so every claim about what
the services' role can or cannot do is made by connecting AS a throwaway non-superuser role that
`lab-brain admin db-roles` (`deployment.grant_database_roles`) granted exactly as a deployment's
`lab_brain_app` is granted -- dropped afterwards. What is proven:

1. the services' role CAN still change an account's role directly (A12 is not closed), and the
   change is recorded with its login role, old and new values and transaction, and listed as
   explained by no account event;
2. the application's own changes (approval, role change, suspension, memberships) are each
   explained by the account event their transaction wrote: the report lists none of them;
3. the services' role cannot update, delete, truncate or forge an audit row, move the chain head,
   turn a trigger off, or set `session_replication_role`;
4. a superuser CAN still bypass it, as documented: with a trigger disabled its change is not
   recorded; a deleted audit row breaks the chain; a full rewrite that also moves the head is
   detected only by a head recorded outside the database earlier. All undone (rolled back).
"""

from __future__ import annotations

import io
import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from lab_brain.accounts import change_audit
from lab_brain.accounts.projects import LabProjects
from lab_brain.interfaces import cli, deployment
from tests.account_fixtures import Lab
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


@pytest.fixture
def app_role(db: Any) -> Iterator[tuple[str, str]]:
    """A login role granted as the services' role is, and its password."""
    suffix = secrets.token_hex(4)
    app, reader = f"lbt_a12_app_{suffix}", f"lbt_a12_reader_{suffix}"
    password = secrets.token_hex(24)
    db.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(app), sql.Literal(password)
        )
    )
    db.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(reader)))
    try:
        deployment.grant_database_roles(db, app_role=app, reader_role=reader)
        yield app, password
    finally:
        for role in (app, reader):
            db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _as(role: str, password: str) -> Any:
    params = {**conninfo_to_dict(database_url()), "user": role, "password": password}
    return psycopg.connect(**params, autocommit=True, connect_timeout=5)


def _last_seq(db: Any) -> int:
    (seq,) = db.execute("SELECT coalesce(max(audit_seq), 0) FROM account_change_audit").fetchone()
    return int(seq)


def _people(lab: Lab) -> tuple[Any, Any]:
    admin = lab.admin()
    member = lab.member("ada@lab.example", "Ada", admin=admin)
    return admin, member


def test_a_direct_role_change_by_the_services_role_is_recorded_and_unexplained(db, lab, app_role):
    _admin, member = _people(lab)
    since = _last_seq(db)
    app, password = app_role
    with _as(app, password) as as_app:
        assert as_app.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone() == (False,)
        # A12 is NOT closed: the services' role can still make itself an administrator.
        as_app.execute(
            "UPDATE accounts SET system_role = 'ADMIN' WHERE account_id = %s", (member.account_id,)
        )
        as_app.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance)"
            " VALUES (%s, 'prj:test', 'owner', ARRAY['RESTRICTED_NDA'])",
            (member.actor_id,),
        )
    assert db.execute(
        "SELECT system_role FROM accounts WHERE account_id = %s", (member.account_id,)
    ).fetchone() == ("ADMIN",)
    recorded = change_audit.rows(db, since_seq=since)
    assert [(r.table_name, r.operation, r.session_user) for r in recorded] == [
        ("accounts", "UPDATE", app),
        ("project_memberships", "INSERT", app),
    ]
    role_change = recorded[0]
    assert role_change.account_id == member.account_id
    assert '"system_role": "MEMBER"' in (role_change.old_values or "")
    assert '"system_role": "ADMIN"' in (role_change.new_values or "")
    assert recorded[1].account_id == member.account_id  # the membership's account, resolved
    assert recorded[0].txid != recorded[1].txid  # each autocommit statement its own transaction
    unexplained = change_audit.unexplained_changes(db, since_seq=since)
    assert [r.seq for r in unexplained] == [r.seq for r in recorded]
    assert "system_role: 'MEMBER' -> 'ADMIN'" in unexplained[0].describe()
    assert change_audit.verify_chain(db).intact

    out = io.StringIO()
    code = cli.main(
        ["admin", "account-audit", "--since-seq", str(since)],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    text = out.getvalue()
    assert code == 0, text
    assert "chain intact" in text and "no application account event in their transaction: 2" in text
    assert f"UPDATE accounts {member.account_id} by {app}" in text
    assert "A12 stays an Owner decision" in text


def test_the_application_s_own_changes_are_each_explained_by_their_event(db, lab):
    since = _last_seq(db)
    admin, member = _people(lab)
    other = lab.member("bea@lab.example", "Bea", admin=admin)
    accounts = lab.service()
    accounts.set_role(member.account_id, "ADMIN", by=admin)
    accounts.set_role(member.account_id, "MEMBER", by=admin)
    accounts.suspend(other.account_id, by=admin, reason="left the laboratory")
    accounts.reactivate(other.account_id, by=admin)
    projects = LabProjects(db, now=lab.clock)
    project = projects.create(
        admin, name="Ring resonators", owner_account_id=member.account_id, clearance=["INTERNAL"]
    )
    projects.add_member(
        project, by=admin, member_account_id=other.account_id, clearance=["INTERNAL"]
    )
    projects.change_member(
        project, by=admin, actor_id=other.actor_id, clearance=["PUBLIC"], owner=False
    )
    projects.remove_member(project, by=admin, actor_id=other.actor_id)
    recorded = change_audit.rows(db, since_seq=since)
    changed = {(r.table_name, r.operation) for r in recorded if r.table_name != "account_events"}
    assert changed == {
        ("accounts", "INSERT"),
        ("accounts", "UPDATE"),
        ("project_memberships", "INSERT"),
        ("project_memberships", "UPDATE"),
    }
    assert change_audit.unexplained_changes(db, since_seq=since) == []
    assert change_audit.verify_chain(db).intact


def test_the_services_role_cannot_erase_alter_forge_or_skip_the_audit(db, lab, app_role):
    _people(lab)
    before = change_audit.verify_chain(db)
    assert before.intact and before.rows > 0
    (seq,) = db.execute("SELECT max(audit_seq) FROM account_change_audit").fetchone()
    app, password = app_role
    refused = {
        "update": f"UPDATE account_change_audit SET new_values = '{{}}' WHERE audit_seq = {seq}",
        "delete": f"DELETE FROM account_change_audit WHERE audit_seq = {seq}",
        "truncate": "TRUNCATE account_change_audit",
        "forge": (
            "INSERT INTO account_change_audit (table_name, operation, account_id, db_session_user,"
            " role_setting, application_name, txid, recorded_at, previous_digest, row_digest)"
            f" VALUES ('account_events', 'INSERT', 'acc:x', 'lab_brain_app', 'none', '', 1, now(),"
            f" '{'0' * 64}', '{'1' * 64}')"
        ),
        "move the head": "UPDATE account_change_audit_head SET last_seq = 1",
        "reset the head": "DELETE FROM account_change_audit_head",
        "disable the recording": "ALTER TABLE accounts DISABLE TRIGGER account_change_audit_update",
        "disable the seal": "ALTER TABLE account_change_audit DISABLE TRIGGER USER",
        "replica mode": "SET session_replication_role = replica",
        "drop": "DROP TABLE account_change_audit",
        "replace the function": (
            "CREATE OR REPLACE FUNCTION account_change_audit_record_row() RETURNS TRIGGER"
            " AS $$ BEGIN RETURN NULL; END; $$ LANGUAGE plpgsql"
        ),
    }
    with _as(app, password) as as_app:
        for what, statement in refused.items():
            with pytest.raises(psycopg.Error) as caught:
                as_app.execute(statement)
            message = str(caught.value)
            assert any(
                word in message
                for word in ("append-only", "011u", "permission denied", "must be owner")
            ), (what, message)
    after = change_audit.verify_chain(db)
    assert after.intact and after.rows == before.rows and after.head == before.head


def test_a_superuser_can_still_bypass_it_as_documented(db, lab):
    """The documented limit, asserted honestly: a superuser (or the tables' owner) steps past
    every trigger here. Undone at the end -- the transaction is rolled back."""
    _admin, member = _people(lab)
    (is_super,) = db.execute(
        "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert is_super, "this test documents what a superuser can do"
    recorded_earlier = change_audit.verify_chain(db)
    assert recorded_earlier.intact
    head_copied_out = recorded_earlier.head
    with db.transaction(force_rollback=True):
        # 1. With the recording trigger disabled, a role change leaves no audit row.
        db.execute("ALTER TABLE accounts DISABLE TRIGGER account_change_audit_update")
        rows_before = change_audit.verify_chain(db).rows
        db.execute(
            "UPDATE accounts SET system_role = 'ADMIN' WHERE account_id = %s", (member.account_id,)
        )
        assert change_audit.verify_chain(db).rows == rows_before
        # 2. Deleting the latest audit row, with its guard disabled, breaks the chain: detected.
        db.execute(
            "ALTER TABLE account_change_audit DISABLE TRIGGER account_change_audit_append_only"
        )
        (last,) = db.execute("SELECT max(audit_seq) FROM account_change_audit").fetchone()
        (previous_seq, previous_digest) = db.execute(
            "SELECT previous_seq, previous_digest FROM account_change_audit WHERE audit_seq = %s",
            (last,),
        ).fetchone()
        db.execute("DELETE FROM account_change_audit WHERE audit_seq = %s", (last,))
        broken = change_audit.verify_chain(db)
        assert not broken.intact
        assert any("stored chain head" in p for p in broken.problems)
        # 3. Moving the head too makes the database's own view consistent again: only the head
        #    recorded outside the database earlier exposes the rewrite.
        db.execute(
            "ALTER TABLE account_change_audit_head DISABLE TRIGGER"
            " account_change_audit_head_moves_by_seal"
        )
        db.execute(
            "UPDATE account_change_audit_head SET last_seq = %s, last_digest = %s",
            (previous_seq, previous_digest),
        )
        rewritten = change_audit.verify_chain(db)
        assert rewritten.intact, rewritten.problems
        against_copy = change_audit.verify_chain(db, expect_head=head_copied_out)
        assert not against_copy.intact
        assert any("no longer in the audit table" in p for p in against_copy.problems)
    # Rolled back: the triggers are enabled, the row is back, the role unchanged.
    assert change_audit.verify_chain(db, expect_head=head_copied_out).intact
    assert db.execute(
        "SELECT system_role FROM accounts WHERE account_id = %s", (member.account_id,)
    ).fetchone() == ("MEMBER",)
    (enabled,) = db.execute(
        "SELECT bool_and(tgenabled = 'A') FROM pg_trigger"
        " WHERE tgname LIKE 'account_change_audit%%' AND NOT tgisinternal"
    ).fetchone()
    assert enabled, "every audit trigger is ENABLE ALWAYS (replica mode does not skip it)"


def test_a_head_that_no_longer_matches_makes_the_command_refuse(db, lab):
    _people(lab)
    out = io.StringIO()
    code = cli.main(
        ["admin", "account-audit", "--expect-head", f"1:{'f' * 64}"],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    assert code == 2, out.getvalue()
    assert "BROKEN" in out.getvalue()


def test_two_concurrent_writers_extend_one_chain_never_a_fork(db, lab):
    """The head's row lock serializes the seal: a second writer waits for the first to commit,
    then chains onto ITS row -- even though its own sequence number was drawn earlier."""
    import threading

    _admin, member = _people(lab)
    other = lab.member("bea@lab.example", "Bea", admin=_admin)
    first = psycopg.connect(database_url())
    second = psycopg.connect(database_url(), autocommit=True)
    try:
        first.execute(
            "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s", (member.account_id,)
        )  # holds the head's lock until it commits
        done = threading.Event()

        def write() -> None:
            second.execute(
                "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s",
                (other.account_id,),
            )
            done.set()

        thread = threading.Thread(target=write)
        thread.start()
        assert not done.wait(0.5), "the second writer waited for the first's chain row"
        first.commit()
        thread.join(5)
        assert done.is_set()
    finally:
        first.close()
        second.close()
    chain = change_audit.verify_chain(db)
    assert chain.intact, chain.problems
