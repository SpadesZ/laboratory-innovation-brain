"""Accounts: registration, verification, approval, sign-in, sessions, recovery (`012u`).

EVERY DECISION HERE IS THE SERVER'S. Nothing a browser sends names an actor, a role, an account
state or a project the caller may act in: the caller is the account a session token resolves to,
re-read from the database on every request, and an administrator's authority is re-checked against
the stored account each time it is used. The database holds the same rules for every writer
(`012u`): approval only by an active administrator other than the person approved, verification
before approval, the last active administrator kept, tokens used once, events append-only.

VERIFY FIRST. Registration takes an address only. The name and the password are chosen by whoever
opens the emailed link, in the same step that confirms the address; the database refuses a
password on an account whose address is not confirmed (`012v`).

NO ACCOUNT ENUMERATION. Registration and password reset answer the same whether or not an address
is registered; sign-in says only "not signed in" for an unknown address, a wrong password and a
locked account, and tells an account's state (pending, suspended) only to someone who gave its
correct password.

LIFETIMES. A session ends 12 hours after sign-in, or after 2 hours unused, or at sign-out, a
password change or reset, or a suspension. A verification link lasts 48 hours, a reset link 30
minutes, a first-password link 24 hours; each works once. Five wrong passwords in a row lock the
account for 15 minutes.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.accounts.mail import Mailer, MailUnavailable, Message
from lab_brain.accounts.passwords import (
    DEFAULT_COST,
    ScryptCost,
    WeakPassword,
    check_password_policy,
    hash_password,
    needs_rehash,
    new_token,
    normalized_email,
    token_hash,
    verify_password,
)
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.identifiers import new_id

ADMIN = "ADMIN"
MEMBER = "MEMBER"
ROLES = (ADMIN, MEMBER)

SESSION_LIFETIME = dt.timedelta(hours=12)
SESSION_IDLE = dt.timedelta(hours=2)
#: A session's last use is written at most this often: a read per request, a write per minute.
SESSION_TOUCH = dt.timedelta(minutes=1)
VERIFY_LIFETIME = dt.timedelta(hours=48)
RESET_LIFETIME = dt.timedelta(minutes=30)
SETUP_LIFETIME = dt.timedelta(hours=24)
MAX_FAILURES = 5
LOCKOUT = dt.timedelta(minutes=15)
#: Mail an anonymous form can cause: messages to one account, and new registrations, an hour.
THROTTLE_WINDOW = dt.timedelta(hours=1)
MAX_MAILS_PER_HOUR = 3
MAX_REGISTRATIONS_PER_HOUR = 30

_COLUMNS = (
    "account_id, actor_id, email, display_name, system_role, status, email_verified_at,"
    " approved_at, created_at, password_hash, failed_logins, locked_until"
)


@dataclass(frozen=True)
class Account:
    account_id: str
    actor_id: str
    email: str
    display_name: str
    system_role: str
    status: str
    email_verified_at: dt.datetime | None
    approved_at: dt.datetime | None
    created_at: dt.datetime

    @property
    def is_admin(self) -> bool:
        return self.system_role == ADMIN and self.status == "ACTIVE"

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    @property
    def awaiting(self) -> str | None:
        """What a PENDING account waits for: its holder's verification, or an approval."""
        if self.status != "PENDING":
            return None
        return "VERIFICATION" if self.email_verified_at is None else "APPROVAL"


class AccountRefused(Exception):
    """Refused as asked; nothing was written. `code` is stable and names what to show."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def _account(row: Sequence[Any]) -> Account:
    return Account(
        account_id=str(row[0]),
        actor_id=str(row[1]),
        email=str(row[2]),
        display_name=str(row[3]),
        system_role=str(row[4]),
        status=str(row[5]),
        email_verified_at=row[6],
        approved_at=row[7],
        created_at=row[8],
    )


class AccountService:
    def __init__(
        self,
        connection: Any,
        *,
        mailer: Mailer | None,
        base_url: str,
        now: Callable[[], dt.datetime] = utc_now,
        cost: ScryptCost = DEFAULT_COST,
    ) -> None:
        self._c = connection
        self._mailer = mailer
        self._base = base_url.rstrip("/")
        self._now = now
        self._cost = cost

    # -- reading ----------------------------------------------------------------------------------

    def get(self, account_id: str) -> Account | None:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE account_id = %s", (account_id,)
        ).fetchone()
        return None if row is None else _account(row)

    def by_actor(self, actor_id: str) -> Account | None:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE actor_id = %s", (actor_id,)
        ).fetchone()
        return None if row is None else _account(row)

    def all(self) -> list[Account]:
        rows = self._c.execute(
            f"SELECT {_COLUMNS} FROM accounts"
            " ORDER BY CASE status WHEN 'PENDING' THEN 0 WHEN 'ACTIVE' THEN 1 ELSE 2 END,"
            " created_at, account_id"
        ).fetchall()
        return [_account(r) for r in rows]

    def has_admin(self) -> bool:
        return bool(
            self._c.execute(
                "SELECT 1 FROM accounts WHERE system_role = 'ADMIN' AND status = 'ACTIVE' LIMIT 1"
            ).fetchone()
        )

    def mail_configured(self) -> bool:
        return self._mailer is not None

    def events(self, account_id: str) -> list[tuple[str, str | None, dict[str, Any], dt.datetime]]:
        """(kind, who acted -- by name, or None for the operator's command line --, detail, when),
        newest first."""
        rows = self._c.execute(
            "SELECT e.kind, coalesce(a.display_name, x.display_name, e.by_actor_id), e.detail,"
            " e.occurred_at FROM account_events e"
            " LEFT JOIN actors x ON x.actor_id = e.by_actor_id"
            " LEFT JOIN accounts a ON a.actor_id = e.by_actor_id"
            " WHERE e.account_id = %s ORDER BY e.seq DESC",
            (account_id,),
        ).fetchall()
        return [(str(r[0]), r[1], dict(r[2] or {}), r[3]) for r in rows]

    # -- registration -----------------------------------------------------------------------------

    def register(self, *, email: str) -> None:
        """A PENDING account with no name and no password, and a verification link by mail.

        VERIFY FIRST. Whoever opens the link chooses the name and the password (`verify_email`), so
        nothing is ever set by someone who has not shown they read the address's mail: a
        registration of someone else's address holds nothing against its owner. For an address
        registered but never confirmed: a fresh link, and the earlier ones stop working. For a
        confirmed one: a notice to that address. The caller is told the same in every case."""
        mailer = self._require_mail()
        address = normalized_email(email)
        if address is None:
            raise AccountRefused("invalid_email")
        now = self._now()
        # The cap on registrations an hour is checked for EVERY address, known or not: one
        # that answered differently once the cap was reached would tell which addresses have
        # accounts (adversarial audit A4).
        recent = self._c.execute(
            "SELECT count(*) FROM accounts WHERE created_at > %s", (now - THROTTLE_WINDOW,)
        ).fetchone()
        if recent is not None and int(recent[0]) >= MAX_REGISTRATIONS_PER_HOUR:
            raise AccountRefused("busy")
        try:
            self._register(mailer, address, now)
        except AccountRefused as refused:
            # A message that could not be sent is not told either: whether one was due at
            # all -- it is not, to a throttled known address -- would tell. Nothing was
            # kept: the new account's transaction is undone with it.
            if refused.code != "mail_failed":
                raise

    def _register(self, mailer: Mailer, address: str, now: dt.datetime) -> None:
        found = self._c.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE email = %s", (address,)
        ).fetchone()
        if found is not None:
            account = _account(found)
            if self._mailed_recently(account.account_id, now):
                return
            if account.awaiting == "VERIFICATION":
                self._resend_verification(mailer, account)
                return
            with self._c.transaction():
                self.record_event(account.account_id, "REGISTRATION_NOTICE", None, {})
                self._send(
                    mailer,
                    Message(
                        to=address,
                        subject="Lab Brain: a registration with your address",
                        body=(
                            "Someone asked to register a Lab Brain account with this address, "
                            "which already has one. Nothing was changed. If it was you, sign in, "
                            f"or reset your password at {self._base}/password/forgot\n"
                        ),
                    ),
                )
            return
        actor_id = new_id("actor")
        account_id = new_id("account")
        token = new_token()
        # Until its holder names it at verification, the account is labelled by its address.
        label = address[:120]
        with self._c.transaction():
            self._c.execute(
                "INSERT INTO actors (actor_id, actor_type, display_name, active)"
                " VALUES (%s, 'HUMAN', %s, FALSE)",
                (actor_id, label),
            )
            self._c.execute(
                "INSERT INTO accounts (account_id, actor_id, email, display_name, created_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (account_id, actor_id, address, label, now),
            )
            self.record_event(account_id, "REGISTERED", actor_id, {})
            self._token(account_id, "VERIFY_EMAIL", token, now + VERIFY_LIFETIME)
            # Inside the transaction: a link that could not be sent leaves no account behind.
            self._send(mailer, self._verification_message(address, token))

    def verify_email(self, token: str, *, display_name: str, password: str) -> Account:
        """The link's holder confirms the address and, in the same step, chooses the account's
        name and password. A refused name or password changes nothing and leaves the link usable:
        the token is used inside the transaction that a refusal rolls back."""
        name = " ".join(display_name.split())
        if not name or len(name) > 120:
            raise AccountRefused("invalid_name")
        now = self._now()
        with self._c.transaction():
            account_id = self._use(token, ("VERIFY_EMAIL",), now)
            account = self._locked(account_id)
            if account.email_verified_at is not None:
                raise AccountRefused("token_invalid")
            try:
                check_password_policy(password, email=account.email)
            except WeakPassword as weak:
                raise AccountRefused("weak_password", weak.code) from None
            self._c.execute(
                "UPDATE accounts SET email_verified_at = %s, email_verified_by = 'EMAIL_LINK',"
                " display_name = %s WHERE account_id = %s",
                (now, name, account_id),
            )
            self._c.execute(
                "UPDATE actors SET display_name = %s WHERE actor_id = %s", (name, account.actor_id)
            )
            self._set_password(account, password, now)
            self.record_event(account_id, "EMAIL_VERIFIED", account.actor_id, {})
            self.record_event(account_id, "PASSWORD_SET", account.actor_id, {})
        verified = self.get(account_id)
        assert verified is not None
        return verified

    # -- administration ---------------------------------------------------------------------------

    def approve(self, account_id: str, *, by: Account) -> Account:
        admin = self._admin(by)
        with self._c.transaction():
            account = self._locked(account_id)
            if account.actor_id == admin.actor_id:
                raise AccountRefused("not_permitted", "nobody approves their own account")
            if account.approved_at is not None or account.status == "ACTIVE":
                raise AccountRefused("state", f"{account.email} is already approved")
            if account.email_verified_at is None:
                raise AccountRefused("not_verified", f"{account.email} has not verified its email")
            now = self._now()
            self._c.execute(
                "UPDATE accounts SET status = 'ACTIVE', approved_at = %s,"
                " approved_by_actor_id = %s WHERE account_id = %s",
                (now, admin.actor_id, account_id),
            )
            self._c.execute(
                "UPDATE actors SET active = TRUE WHERE actor_id = %s", (account.actor_id,)
            )
            self.record_event(account_id, "APPROVED", admin.actor_id, {})
        self._notify(
            account.email,
            "Lab Brain: your account is approved",
            f"An administrator approved your Lab Brain account. Sign in at {self._base}/login\n",
        )
        approved = self.get(account_id)
        assert approved is not None
        return approved

    def reject(self, account_id: str, *, by: Account) -> Account:
        """Decline a confirmed registration. An unconfirmed one is not declined: it holds
        nothing (no name, no password), its link expires, and its address can be registered
        again -- a declined one could never be (adversarial audit A8)."""
        admin = self._admin(by)
        with self._c.transaction():
            account = self._locked(account_id)
            if account.status != "PENDING":
                raise AccountRefused("state", f"{account.email} is not awaiting approval")
            if account.email_verified_at is None:
                raise AccountRefused("not_verified", f"{account.email} has not confirmed it")
            self._c.execute(
                "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s", (account_id,)
            )
            self.record_event(account_id, "REJECTED", admin.actor_id, {})
        rejected = self.get(account_id)
        assert rejected is not None
        return rejected

    def suspend(self, account_id: str, *, by: Account, reason: str) -> Account:
        admin = self._admin(by)
        why = " ".join(reason.split())
        if not why:
            raise AccountRefused("reason_required")
        with self._c.transaction():
            account = self._locked(account_id)
            if account.actor_id == admin.actor_id:
                raise AccountRefused("not_permitted", "an administrator does not suspend themself")
            if account.status != "ACTIVE":
                raise AccountRefused("state", f"{account.email} is not active")
            self._c.execute(
                "UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s", (account_id,)
            )
            self._c.execute(
                "UPDATE actors SET active = FALSE WHERE actor_id = %s", (account.actor_id,)
            )
            self._revoke_sessions(account_id)
            self.record_event(account_id, "SUSPENDED", admin.actor_id, {"reason": why})
        suspended = self.get(account_id)
        assert suspended is not None
        return suspended

    def reactivate(self, account_id: str, *, by: Account) -> Account:
        admin = self._admin(by)
        with self._c.transaction():
            account = self._locked(account_id)
            if account.status != "SUSPENDED" or account.approved_at is None:
                raise AccountRefused(
                    "state", f"{account.email} is not a suspended, previously approved account"
                )
            self._c.execute(
                "UPDATE accounts SET status = 'ACTIVE', failed_logins = 0, locked_until = NULL"
                " WHERE account_id = %s",
                (account_id,),
            )
            self._c.execute(
                "UPDATE actors SET active = TRUE WHERE actor_id = %s", (account.actor_id,)
            )
            self.record_event(account_id, "REACTIVATED", admin.actor_id, {})
        reactivated = self.get(account_id)
        assert reactivated is not None
        return reactivated

    def set_role(self, account_id: str, role: str, *, by: Account) -> Account:
        """ADMIN or MEMBER. An administrator also administers the deployment's model routes
        (`012f`); the grant follows the role."""
        from lab_brain.interfaces.deployment import revoke_llm_admin

        admin = self._admin(by)
        if role not in ROLES:
            raise AccountRefused("invalid_role")
        with self._c.transaction():
            account = self._locked(account_id)
            if account.actor_id == admin.actor_id:
                raise AccountRefused(
                    "not_permitted", "an administrator does not change their own role"
                )
            if account.status != "ACTIVE":
                raise AccountRefused("state", f"{account.email} is not active")
            if account.system_role == role:
                return account
            self._c.execute(
                "UPDATE accounts SET system_role = %s WHERE account_id = %s", (role, account_id)
            )
            now = self._now()
            if role == ADMIN:
                self._grant_llm_admin(account.actor_id, "ADMIN_ROLE", now)
            else:
                revoke_llm_admin(self._c, account.actor_id, now)
            self.record_event(
                account_id,
                "ROLE_CHANGED",
                admin.actor_id,
                {"from": account.system_role, "to": role},
            )
        changed = self.get(account_id)
        assert changed is not None
        return changed

    def bootstrap_admin(
        self, *, email: str, display_name: str, actor_id: str | None = None
    ) -> tuple[Account, str]:
        """The operator's first administrator, ACTIVE, and a one-time link to set its password.

        Only while there is no active administrator. The operator holds the database credentials
        and vouches for the address (`email_verified_by = OPERATOR`). With `actor_id`, the account
        is bound to an existing person -- their projects, memberships and research history.
        """
        if self.has_admin():
            raise AccountRefused("state", "an active administrator exists; they approve accounts")
        address = normalized_email(email)
        if address is None:
            raise AccountRefused("invalid_email")
        name = " ".join(display_name.split())
        if not name:
            raise AccountRefused("invalid_name")
        now = self._now()
        token = new_token()
        account_id = new_id("account")
        existing = actor_id is not None
        with self._c.transaction():
            if self._c.execute("SELECT 1 FROM accounts WHERE email = %s", (address,)).fetchone():
                raise AccountRefused("state", f"{address} already has an account")
            if actor_id is None:
                actor_id = new_id("actor")
                self._c.execute(
                    "INSERT INTO actors (actor_id, actor_type, display_name, active)"
                    " VALUES (%s, 'HUMAN', %s, TRUE)",
                    (actor_id, name),
                )
            else:
                row = self._c.execute(
                    "SELECT actor_type, active FROM actors WHERE actor_id = %s", (actor_id,)
                ).fetchone()
                if row is None or row[0] != "HUMAN" or not row[1]:
                    raise AccountRefused("state", f"{actor_id} is not an active person")
                if self._c.execute(
                    "SELECT 1 FROM accounts WHERE actor_id = %s", (actor_id,)
                ).fetchone():
                    raise AccountRefused("state", f"{actor_id} already has an account")
            self._c.execute(
                "INSERT INTO accounts (account_id, actor_id, email, display_name, system_role,"
                " status, email_verified_at, email_verified_by, approved_at, created_at)"
                " VALUES (%s, %s, %s, %s, 'ADMIN', 'ACTIVE', %s, 'OPERATOR', %s, %s)",
                (account_id, actor_id, address, name, now, now, now),
            )
            self._grant_llm_admin(actor_id, "OPERATOR_CLI", now)
            self.record_event(
                account_id, "BOOTSTRAPPED", None, {"bound_to_existing_actor": existing}
            )
            self._token(account_id, "SET_PASSWORD", token, now + SETUP_LIFETIME)
        account = self.get(account_id)
        assert account is not None
        return account, token

    # -- signing in -------------------------------------------------------------------------------

    def sign_in(self, *, email: str, password: str) -> tuple[Account, str]:
        """The account and a new session token. Refused -- `sign_in_refused` -- for an unknown
        address, a wrong password or a locked account alike; an account's state is told only to
        someone who gave its correct password."""
        address = normalized_email(email) or ""
        now = self._now()
        with self._c.transaction():
            row = self._c.execute(
                f"SELECT {_COLUMNS} FROM accounts WHERE email = %s FOR UPDATE", (address,)
            ).fetchone()
            if row is None:
                verify_password(password, None)
                raise AccountRefused("sign_in_refused")
            account = _account(row)
            stored, failures, locked_until = row[9], int(row[10]), row[11]
            correct = verify_password(password, stored)
            if locked_until is not None and locked_until > now:
                raise AccountRefused("sign_in_refused")
            if not correct:
                failures += 1
                lock = now + LOCKOUT if failures >= MAX_FAILURES else None
                self._c.execute(
                    "UPDATE accounts SET failed_logins = %s, locked_until = %s"
                    " WHERE account_id = %s",
                    (0 if lock else failures, lock, account.account_id),
                )
                self.record_event(
                    account.account_id, "LOCKED" if lock else "SIGN_IN_REFUSED", None, {}
                )
                return_refusal = True
            else:
                return_refusal = False
        if return_refusal:
            raise AccountRefused("sign_in_refused")
        if account.status == "SUSPENDED":
            raise AccountRefused("suspended" if account.approved_at else "declined")
        if account.status == "PENDING":
            raise AccountRefused(
                "awaiting_verification"
                if account.email_verified_at is None
                else "awaiting_approval"
            )
        token = new_token()
        with self._c.transaction():
            self._c.execute(
                "UPDATE accounts SET failed_logins = 0, locked_until = NULL WHERE account_id = %s",
                (account.account_id,),
            )
            if stored and needs_rehash(stored, cost=self._cost):
                self._c.execute(
                    "UPDATE accounts SET password_hash = %s WHERE account_id = %s",
                    (hash_password(password, cost=self._cost), account.account_id),
                )
            self._c.execute(
                "INSERT INTO account_sessions (session_hash, account_id, created_at, last_seen_at,"
                " expires_at) VALUES (%s, %s, %s, %s, %s)",
                (token_hash(token), account.account_id, now, now, now + SESSION_LIFETIME),
            )
            self.record_event(account.account_id, "SIGNED_IN", account.actor_id, {})
        return account, token

    def session(self, token: str) -> Account | None:
        """The ACTIVE account a session token signs in, or None. Re-read every time: a
        suspension, a password reset or a sign-out ends the session at once."""
        if not token:
            return None
        row = self._c.execute(
            f"SELECT s.session_hash, s.last_seen_at, s.expires_at, s.revoked_at,"
            f" {', '.join('a.' + c.strip() for c in _COLUMNS.split(','))}"
            " FROM account_sessions s JOIN accounts a ON a.account_id = s.account_id"
            " WHERE s.session_hash = %s",
            (token_hash(token),),
        ).fetchone()
        if row is None:
            return None
        now = self._now()
        last_seen, expires, revoked = row[1], row[2], row[3]
        account = _account(row[4:])
        if revoked is not None or expires <= now or now - last_seen >= SESSION_IDLE:
            return None
        if account.status != "ACTIVE":
            return None
        if now - last_seen >= SESSION_TOUCH:
            self._c.execute(
                "UPDATE account_sessions SET last_seen_at = %s WHERE session_hash = %s"
                " AND revoked_at IS NULL",
                (now, row[0]),
            )
        return account

    def sign_out(self, token: str) -> None:
        if not token:
            return
        row = self._c.execute(
            "UPDATE account_sessions SET revoked_at = %s WHERE session_hash = %s"
            " AND revoked_at IS NULL RETURNING account_id",
            (self._now(), token_hash(token)),
        ).fetchone()
        if row is not None:
            account = self.get(str(row[0]))
            self.record_event(str(row[0]), "SIGNED_OUT", account.actor_id if account else None, {})

    # -- passwords --------------------------------------------------------------------------------

    def request_password_reset(self, *, email: str) -> None:
        """A reset link by mail, for a verified account that is not suspended. The caller is told
        the same whether or not there is one -- also when the mail cannot be sent, which is
        recorded rather than shown (a failure only a real account could cause would tell)."""
        self._require_mail()
        address = normalized_email(email)
        if address is None:
            return
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE email = %s", (address,)
        ).fetchone()
        if row is None:
            return
        account = _account(row)
        if account.status == "SUSPENDED" or account.email_verified_at is None:
            return
        now = self._now()
        if self._mailed_recently(account.account_id, now):
            return
        token = new_token()
        with self._c.transaction():
            # One live reset link at a time.
            self._c.execute(
                "UPDATE account_tokens SET used_at = %s WHERE account_id = %s"
                " AND purpose = 'RESET_PASSWORD' AND used_at IS NULL",
                (now, account.account_id),
            )
            self._token(account.account_id, "RESET_PASSWORD", token, now + RESET_LIFETIME)
            self.record_event(account.account_id, "PASSWORD_RESET_REQUESTED", None, {})
        assert self._mailer is not None
        try:
            self._mailer.send(
                Message(
                    to=address,
                    subject="Lab Brain: reset your password",
                    body=(
                        "Set a new password for your Lab Brain account:\n\n"
                        f"{self._base}/password/reset?token={token}\n\n"
                        "The link works once, for 30 minutes. If you did not ask, ignore this "
                        "message; your password is unchanged.\n"
                    ),
                )
            )
        except MailUnavailable as failed:
            self.record_event(
                account.account_id,
                "MAIL_FAILED",
                None,
                {"purpose": "RESET_PASSWORD", "error": str(failed)[:300]},
            )

    def reset_password(self, *, token: str, password: str) -> Account:
        """A reset or first-password link's new password. Every session of the account ends."""
        now = self._now()
        with self._c.transaction():
            account_id, purpose = self._use_with_purpose(
                token, ("RESET_PASSWORD", "SET_PASSWORD"), now
            )
            account = self._locked(account_id)
            if account.status == "SUSPENDED":
                raise AccountRefused("suspended")
            try:
                check_password_policy(password, email=account.email)
            except WeakPassword as weak:
                raise AccountRefused("weak_password", weak.code) from None
            self._set_password(account, password, now)
            self._revoke_sessions(account_id)
            self.record_event(
                account_id,
                "PASSWORD_SET" if purpose == "SET_PASSWORD" else "PASSWORD_RESET",
                account.actor_id,
                {},
            )
        updated = self.get(account_id)
        assert updated is not None
        return updated

    def token_purpose(self, token: str) -> str | None:
        """What a link's token is for, if it can still be used; nothing is consumed."""
        row = self._c.execute(
            "SELECT purpose FROM account_tokens WHERE token_hash = %s AND used_at IS NULL"
            " AND expires_at > %s",
            (token_hash(token), self._now()),
        ).fetchone()
        return None if row is None else str(row[0])

    def change_password(
        self, account: Account, *, current: str, new: str, keep_session: str = ""
    ) -> None:
        """A signed-in person's new password. Every other session of the account ends. A wrong
        current password counts toward the same lockout as a sign-in."""
        now = self._now()
        with self._c.transaction():
            row = self._c.execute(
                "SELECT password_hash, failed_logins, locked_until FROM accounts"
                " WHERE account_id = %s FOR UPDATE",
                (account.account_id,),
            ).fetchone()
            if row is None:
                raise AccountRefused("wrong_password")
            stored, failures, locked_until = row[0], int(row[1]), row[2]
            correct = verify_password(current, stored)
            locked = locked_until is not None and locked_until > now
            if not correct and not locked:
                failures += 1
                lock = now + LOCKOUT if failures >= MAX_FAILURES else None
                self._c.execute(
                    "UPDATE accounts SET failed_logins = %s, locked_until = %s"
                    " WHERE account_id = %s",
                    (0 if lock else failures, lock, account.account_id),
                )
                self.record_event(
                    account.account_id, "LOCKED" if lock else "PASSWORD_CHECK_REFUSED", None, {}
                )
        if locked:
            raise AccountRefused("locked")
        if not correct:
            raise AccountRefused("wrong_password")
        try:
            check_password_policy(new, email=account.email)
        except WeakPassword as weak:
            raise AccountRefused("weak_password", weak.code) from None
        with self._c.transaction():
            self._set_password(account, new, now)
            self._c.execute(
                "UPDATE account_sessions SET revoked_at = %s WHERE account_id = %s"
                " AND revoked_at IS NULL AND session_hash <> %s",
                (now, account.account_id, token_hash(keep_session) if keep_session else ""),
            )
            # A reset link asked for before the change would otherwise still set a password
            # for 30 minutes (adversarial audit A11).
            self._c.execute(
                "UPDATE account_tokens SET used_at = %s WHERE account_id = %s"
                " AND purpose = 'RESET_PASSWORD' AND used_at IS NULL",
                (now, account.account_id),
            )
            self.record_event(account.account_id, "PASSWORD_CHANGED", account.actor_id, {})

    # -- internals --------------------------------------------------------------------------------

    def _resend_verification(self, mailer: Mailer, account: Account) -> None:
        """A new verification link; the earlier ones stop working."""
        now = self._now()
        token = new_token()
        with self._c.transaction():
            self._c.execute(
                "UPDATE account_tokens SET used_at = %s WHERE account_id = %s"
                " AND purpose = 'VERIFY_EMAIL' AND used_at IS NULL",
                (now, account.account_id),
            )
            self._token(account.account_id, "VERIFY_EMAIL", token, now + VERIFY_LIFETIME)
            self.record_event(account.account_id, "VERIFICATION_RESENT", None, {})
            self._send(mailer, self._verification_message(account.email, token))

    def _verification_message(self, address: str, token: str) -> Message:
        # Nothing a registrant typed goes into the message: the address is anyone's to type, so
        # the body must not carry their words to it.
        return Message(
            to=address,
            subject="Lab Brain: confirm your email address",
            body=(
                "Confirm this address for a Lab Brain account, and choose your name and password:"
                f"\n\n{self._base}/verify?token={token}\n\n"
                "The link works once, for 48 hours; any earlier link no longer works. After you "
                "confirm, an administrator approves the account. If you did not register, "
                "ignore this message: without the link, nobody can use the account.\n"
            ),
        )

    def _mailed_recently(self, account_id: str, now: dt.datetime) -> bool:
        """At most MAX_MAILS_PER_HOUR messages to one account an hour, whoever asks."""
        row = self._c.execute(
            "SELECT count(*) FROM account_events WHERE account_id = %s AND occurred_at > %s"
            " AND kind IN ('REGISTERED', 'VERIFICATION_RESENT', 'REGISTRATION_NOTICE',"
            " 'PASSWORD_RESET_REQUESTED')",
            (account_id, now - THROTTLE_WINDOW),
        ).fetchone()
        return row is not None and int(row[0]) >= MAX_MAILS_PER_HOUR

    def _require_mail(self) -> Mailer:
        if self._mailer is None:
            raise AccountRefused("mail_unavailable")
        return self._mailer

    def _send(self, mailer: Mailer, message: Message) -> None:
        try:
            mailer.send(message)
        except MailUnavailable as failed:
            raise AccountRefused("mail_failed", str(failed)) from None

    def _notify(self, to: str, subject: str, body: str) -> None:
        """A courtesy notice: best effort, never a reason to undo what was done."""
        if self._mailer is None:
            return
        try:
            self._mailer.send(Message(to=to, subject=subject, body=body))
        except MailUnavailable:
            return

    def _admin(self, by: Account) -> Account:
        """The acting administrator, as the database holds them NOW."""
        current = self.get(by.account_id)
        if current is None or not current.is_admin:
            raise AccountRefused("not_permitted", "only an active administrator may do this")
        return current

    def _locked(self, account_id: str) -> Account:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE account_id = %s FOR UPDATE", (account_id,)
        ).fetchone()
        if row is None:
            raise AccountRefused("not_found")
        return _account(row)

    def _set_password(self, account: Account, password: str, now: dt.datetime) -> None:
        self._c.execute(
            "UPDATE accounts SET password_hash = %s, password_changed_at = %s, failed_logins = 0,"
            " locked_until = NULL WHERE account_id = %s",
            (hash_password(password, cost=self._cost), now, account.account_id),
        )

    def _grant_llm_admin(self, actor_id: str, through: str, now: dt.datetime) -> None:
        if self._c.execute(
            "SELECT 1 FROM llm_administrators WHERE actor_id = %s AND revoked_at IS NULL",
            (actor_id,),
        ).fetchone():
            return
        self._c.execute(
            "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
            " VALUES (%s, %s, %s)",
            (actor_id, now, through),
        )

    def _revoke_sessions(self, account_id: str) -> None:
        self._c.execute(
            "UPDATE account_sessions SET revoked_at = %s WHERE account_id = %s"
            " AND revoked_at IS NULL",
            (self._now(), account_id),
        )

    def _token(self, account_id: str, purpose: str, token: str, expires: dt.datetime) -> None:
        self._c.execute(
            "INSERT INTO account_tokens (token_hash, account_id, purpose, created_at, expires_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (token_hash(token), account_id, purpose, self._now(), expires),
        )

    def _use(self, token: str, purposes: Sequence[str], now: dt.datetime) -> str:
        return self._use_with_purpose(token, purposes, now)[0]

    def _use_with_purpose(
        self, token: str, purposes: Sequence[str], now: dt.datetime
    ) -> tuple[str, str]:
        row = self._c.execute(
            "UPDATE account_tokens SET used_at = %s WHERE token_hash = %s AND used_at IS NULL"
            " AND expires_at > %s AND purpose = ANY(%s) RETURNING account_id, purpose",
            (now, token_hash(token or ""), now, list(purposes)),
        ).fetchone()
        if row is None:
            raise AccountRefused("token_invalid")
        return str(row[0]), str(row[1])

    def record_event(
        self, account_id: str, kind: str, by_actor_id: str | None, detail: dict[str, Any]
    ) -> None:
        self._c.execute(
            "INSERT INTO account_events (event_id, account_id, kind, by_actor_id, detail,"
            " occurred_at) VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
            (
                new_id("account_event"),
                account_id,
                kind,
                by_actor_id,
                json.dumps(detail),
                self._now(),
            ),
        )


__all__ = [
    "ADMIN",
    "MEMBER",
    "ROLES",
    "Account",
    "AccountRefused",
    "AccountService",
]
