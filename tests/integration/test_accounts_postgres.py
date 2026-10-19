"""Accounts against PostgreSQL: the flow, the server's checks and the database's own rules (`012u`).

flow          register -> the emailed link verifies -> an administrator approves -> sign in
fail closed   no mailer: registration and reset are refused and nothing is written
enumeration   registration and reset answer alike for a known address; sign-in tells an
              account's state only to its correct password
authority     only an active administrator other than the holder approves; the last active
              administrator is kept; nobody changes their own role or suspends themself
sessions      expire, go idle, end at sign-out, suspension and password reset
lockout       five wrong passwords lock the account for fifteen minutes
tokens        used once, expire; the database refuses a second use
every writer  the triggers hold the approval, bootstrap, last-admin and append-only rules
              for a direct writer too
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from lab_brain.accounts.passwords import token_hash
from lab_brain.accounts.service import AccountRefused
from tests.account_fixtures import PASSWORD, Lab

pytestmark = pytest.mark.postgres


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


def _refused(code: str) -> Any:
    class _Match:
        def __enter__(self) -> None:
            return None

        def __exit__(self, kind: Any, value: Any, tb: Any) -> bool:
            assert isinstance(value, AccountRefused), f"expected {code}, got {value!r}"
            assert value.code == code, f"expected {code}, got {value.code} ({value.detail})"
            return True

    return _Match()


def _count(db: Any, table: str) -> int:
    return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_a_person_registers_verifies_is_approved_and_signs_in(lab):
    admin = lab.admin()
    accounts = lab.service()
    accounts.register(email="  Ada@Uni.Example.EDU ", display_name="Ada", password=PASSWORD)
    (pending,) = [a for a in accounts.all() if a.email == "ada@uni.example.edu"]
    assert (pending.status, pending.awaiting, pending.system_role) == (
        "PENDING",
        "VERIFICATION",
        "MEMBER",
    )
    actor = lab.connection.execute(
        "SELECT actor_type, active FROM actors WHERE actor_id = %s", (pending.actor_id,)
    ).fetchone()
    assert tuple(actor) == ("HUMAN", False), "an actor that cannot act until approved"
    with _refused("awaiting_verification"):
        accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    with _refused("not_verified"):
        accounts.approve(pending.account_id, by=admin)
    verified = accounts.verify_email(lab.link("/verify"))
    assert verified.awaiting == "APPROVAL"
    with _refused("awaiting_approval"):
        accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    approved = accounts.approve(pending.account_id, by=admin)
    assert approved.is_active and not approved.is_admin
    account, token = accounts.sign_in(email="ADA@uni.example.edu", password=PASSWORD)
    assert account.account_id == pending.account_id
    assert accounts.session(token) == approved
    kinds = [k for k, *_ in reversed(accounts.events(pending.account_id))]
    assert kinds == ["REGISTERED", "EMAIL_VERIFIED", "APPROVED", "SIGNED_IN"]
    assert lab.connection.execute("SELECT session_hash FROM account_sessions").fetchone() == (
        token_hash(token),
    ), "only the token's hash is stored"


def test_without_mail_nothing_that_needs_a_message_happens(lab):
    accounts = lab.service(mail=False)
    with _refused("mail_unavailable"):
        accounts.register(email="ada@uni.example.edu", display_name="Ada", password=PASSWORD)
    with _refused("mail_unavailable"):
        accounts.request_password_reset(email="ada@uni.example.edu")
    assert _count(lab.connection, "accounts") == 0


def test_a_known_address_is_not_revealed(lab):
    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    before = _count(lab.connection, "accounts")
    lab.service().register(email="ada@uni.example.edu", display_name="Mallory", password=PASSWORD)
    assert _count(lab.connection, "accounts") == before
    assert "already has one" in lab.mail.sent[-1].body, "the holder is told, the caller is not"
    for email, password in (
        ("ada@uni.example.edu", "not the password at all"),
        ("nobody@else.example", PASSWORD),
    ):
        with _refused("sign_in_refused"):
            lab.service().sign_in(email=email, password=password)
    sent = len(lab.mail.sent)
    lab.service().request_password_reset(email="nobody@else.example")
    assert len(lab.mail.sent) == sent, "no account, no message -- and the same answer"


def test_registration_refuses_a_bad_address_and_a_weak_password(lab):
    for email, password, code in (
        ("not-an-address", PASSWORD, "invalid_email"),
        ("ada@uni.example.edu", "short", "weak_password"),
        ("ada@uni.example.edu", "ada@uni.example.edu", "weak_password"),
        ("ada@uni.example.edu", "aaaaaaaaaaaaaaaa", "weak_password"),
    ):
        with _refused(code):
            lab.service().register(email=email, display_name="Ada", password=password)
    assert _count(lab.connection, "accounts") == 0


def test_approval_is_an_active_administrators_and_never_ones_own(lab):
    admin = lab.admin()
    member = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    lab.member("bob@gmail.example", "Bob", admin=admin, approve=False)
    (bob,) = [a for a in lab.service().all() if a.email == "bob@gmail.example"]
    with _refused("not_permitted"):
        lab.service().approve(bob.account_id, by=member)
    # A demoted or suspended administrator's old Account object grants nothing.
    second = lab.member("cy@lab.example", "Cy", admin=admin)
    second = lab.service().set_role(second.account_id, "ADMIN", by=admin)
    lab.service().set_role(second.account_id, "MEMBER", by=admin)
    with _refused("not_permitted"):
        lab.service().approve(bob.account_id, by=second)
    db = lab.connection
    # The database holds it for a direct writer: approval by a member, and by oneself.
    for approver in (member.actor_id, bob.actor_id):
        with pytest.raises(
            psycopg.errors.RaiseException, match="approved only by an active administrator"
        ):
            db.execute(
                "UPDATE accounts SET status = 'ACTIVE', approved_at = now(),"
                " approved_by_actor_id = %s WHERE account_id = %s",
                (approver, bob.account_id),
            )
    with pytest.raises(psycopg.errors.RaiseException, match="created PENDING"):
        db.execute(
            "INSERT INTO accounts (account_id, actor_id, email, display_name, system_role, status,"
            " email_verified_at, email_verified_by, approved_at)"
            " VALUES ('acc:00000000-0000-0000-0000-000000000001', %s, 'x@y.example', 'X', 'ADMIN',"
            " 'ACTIVE', now(), 'OPERATOR', now())",
            (bob.actor_id,),
        )
    # Past every trigger, the table's own constraint: no approval before verification.
    unverified = lab.service()
    unverified.register(email="dee@lab.example", display_name="Dee", password=PASSWORD)
    (dee,) = [a for a in unverified.all() if a.email == "dee@lab.example"]
    db.execute("SET session_replication_role = replica")
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE accounts SET approved_at = now(), approved_by_actor_id = %s"
                " WHERE account_id = %s",
                (admin.actor_id, dee.account_id),
            )
    finally:
        db.execute("SET session_replication_role = origin")


def test_the_last_active_administrator_is_kept(lab):
    admin = lab.admin()
    member = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    db = lab.connection
    for assignment in ("system_role = 'MEMBER'", "status = 'SUSPENDED'"):
        with pytest.raises(psycopg.errors.RaiseException, match="last active administrator"):
            db.execute(
                f"UPDATE accounts SET {assignment} WHERE account_id = %s", (admin.account_id,)
            )
    with _refused("not_permitted"):
        lab.service().set_role(admin.account_id, "MEMBER", by=admin)
    with _refused("not_permitted"):
        lab.service().suspend(admin.account_id, by=admin, reason="leaving")
    promoted = lab.service().set_role(member.account_id, "ADMIN", by=admin)
    assert promoted.is_admin
    assert db.execute(
        "SELECT granted_through FROM llm_administrators WHERE actor_id = %s AND revoked_at IS NULL",
        (member.actor_id,),
    ).fetchone() == ("ADMIN_ROLE",), "an administrator administers the model routes"
    lab.service().set_role(admin.account_id, "MEMBER", by=promoted)
    assert db.execute(
        "SELECT count(*) FROM llm_administrators WHERE actor_id = %s AND revoked_at IS NULL",
        (admin.actor_id,),
    ).fetchone() == (0,), "and the grant ends with the role"
    with pytest.raises(psycopg.errors.RaiseException, match="last active administrator"):
        db.execute(
            "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s", (member.account_id,)
        )


def test_sessions_expire_go_idle_and_end(lab):
    admin = lab.admin()
    member = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    _, token = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    lab.clock.advance(hours=1, minutes=59)
    assert accounts.session(token) is not None, "used within two hours"
    lab.clock.advance(hours=1, minutes=59)
    assert accounts.session(token) is not None, "and again"
    lab.clock.advance(hours=2)
    assert accounts.session(token) is None, "two hours unused"
    _, token = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    for _ in range(7):
        lab.clock.advance(hours=1, minutes=50)
        accounts.session(token)
    assert accounts.session(token) is None, "twelve hours after sign-in, used or not"
    _, token = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    accounts.sign_out(token)
    assert accounts.session(token) is None
    _, token = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    accounts.suspend(member.account_id, by=admin, reason="left the lab")
    assert accounts.session(token) is None
    with _refused("suspended"):
        accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    assert lab.connection.execute(
        "SELECT active FROM actors WHERE actor_id = %s", (member.actor_id,)
    ).fetchone() == (False,), "the actor's every grant is suspended with it (SEC-002)"
    accounts.reactivate(member.account_id, by=admin)
    _, token = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    assert accounts.session(token) is not None
    db = lab.connection
    with pytest.raises(psycopg.errors.RaiseException, match="stays revoked"):
        db.execute("UPDATE account_sessions SET revoked_at = NULL WHERE revoked_at IS NOT NULL")
    with pytest.raises(psycopg.errors.RaiseException, match="never extended"):
        db.execute("UPDATE account_sessions SET expires_at = expires_at + interval '1 day'")


def test_five_wrong_passwords_lock_the_account_for_fifteen_minutes(lab):
    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    for _ in range(5):
        with _refused("sign_in_refused"):
            accounts.sign_in(email="ada@uni.example.edu", password="a wrong password!")
    with _refused("sign_in_refused"):
        accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    lab.clock.advance(minutes=15)
    account, _ = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    kinds = [k for k, *_ in accounts.events(account.account_id)]
    assert kinds.count("SIGN_IN_REFUSED") == 4 and kinds.count("LOCKED") == 1


def test_a_reset_link_works_once_for_thirty_minutes_and_ends_every_session(lab):
    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    _, before = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    accounts.request_password_reset(email="ada@uni.example.edu")
    first = lab.link("/password/reset")
    accounts.request_password_reset(email="ada@uni.example.edu")
    second = lab.link("/password/reset")
    with _refused("token_invalid"):
        accounts.reset_password(token=first, password="a brand new passphrase")
    assert accounts.token_purpose(second) == "RESET_PASSWORD"
    accounts.reset_password(token=second, password="a brand new passphrase")
    assert accounts.session(before) is None, "a reset ends every session"
    with _refused("token_invalid"):
        accounts.reset_password(token=second, password="yet another passphrase")
    with _refused("sign_in_refused"):
        accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    accounts.sign_in(email="ada@uni.example.edu", password="a brand new passphrase")
    accounts.request_password_reset(email="ada@uni.example.edu")
    late = lab.link("/password/reset")
    lab.clock.advance(minutes=31)
    with _refused("token_invalid"):
        accounts.reset_password(token=late, password="too late a passphrase")
    with pytest.raises(psycopg.errors.RaiseException, match="used at most once"):
        lab.connection.execute(
            "UPDATE account_tokens SET used_at = now() WHERE used_at IS NOT NULL"
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        lab.connection.execute("DELETE FROM account_events")


def test_a_changed_password_keeps_only_the_session_that_changed_it(lab):
    admin = lab.admin()
    member = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    _, here = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    _, elsewhere = accounts.sign_in(email="ada@uni.example.edu", password=PASSWORD)
    with _refused("wrong_password"):
        accounts.change_password(member, current="not it at all!", new="another passphrase")
    accounts.change_password(member, current=PASSWORD, new="another passphrase", keep_session=here)
    assert accounts.session(here) is not None and accounts.session(elsewhere) is None


def test_the_operator_bootstraps_one_administrator_bound_to_an_existing_person(lab):
    db = lab.connection
    # The deployment's researcher, with a project and research history before accounts existed.
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:researcher', 'HUMAN', 'R')"
    )
    account, token = lab.service().bootstrap_admin(
        email="owner@lab.example", display_name="Lab Owner", actor_id="act:researcher"
    )
    assert account.actor_id == "act:researcher" and account.is_admin
    with _refused("sign_in_refused"):
        lab.service().sign_in(email="owner@lab.example", password=PASSWORD)
    assert lab.service().token_purpose(token) == "SET_PASSWORD"
    lab.service().reset_password(token=token, password=PASSWORD)
    lab.service().sign_in(email="owner@lab.example", password=PASSWORD)
    with _refused("state"):
        lab.service().bootstrap_admin(email="second@lab.example", display_name="Second")
    with pytest.raises(psycopg.errors.RaiseException, match="only the first administrator"):
        db.execute(
            "INSERT INTO actors (actor_id, actor_type) VALUES ('act:sneak', 'HUMAN');"
            "INSERT INTO accounts (account_id, actor_id, email, display_name, system_role, status,"
            " email_verified_at, email_verified_by, approved_at)"
            " VALUES ('acc:00000000-0000-0000-0000-000000000002', 'act:sneak', 's@y.example',"
            " 'S', 'ADMIN', 'ACTIVE', now(), 'OPERATOR', now())"
        )
    with pytest.raises(psycopg.errors.RaiseException, match="never change"):
        db.execute("UPDATE accounts SET email = 'other@lab.example'")


def test_the_operator_bootstraps_from_the_command_line_and_only_once(lab):
    import io

    from lab_brain.interfaces import cli
    from tests.postgres_fixtures import database_url

    def run(*argv: str) -> tuple[int, str]:
        out = io.StringIO()
        code = cli.main(
            ["admin", "bootstrap-admin", *argv],
            out=out,
            env={"LAB_BRAIN_DATABASE_URL": database_url()},
            connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
        )
        return code, out.getvalue()

    code, printed = run("--email", "Owner@Lab.example", "--name", "Lab Owner")
    assert code == 0, printed
    assert "owner@lab.example" in printed and "/password/reset?token=" in printed
    token = printed.rsplit("token=", 1)[1].strip()
    assert lab.service().token_purpose(token) == "SET_PASSWORD"
    code, printed = run("--email", "second@lab.example", "--name", "Second")
    assert code == 2 and "active administrator exists" in printed
