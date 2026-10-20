"""Accounts for tests: a controllable clock, a cheap password cost, an in-memory mailbox.

The cost is low so a suite that registers dozens of people stays fast; the production cost is
pinned in `tests/unit/test_account_passwords.py`. Every account here is made through the service's
own flow -- registration, the emailed link, an administrator's approval -- except the first
administrator, made as the operator makes them (`bootstrap_admin`).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from lab_brain.accounts.mail import MemoryMailer
from lab_brain.accounts.passwords import ScryptCost
from lab_brain.accounts.service import Account, AccountService

CHEAP = ScryptCost(n=2**10, r=8, p=1)
BASE_URL = "http://127.0.0.1:8765"
PASSWORD = "correct horse battery staple"
T0 = dt.datetime(2026, 10, 20, 9, 0, tzinfo=dt.UTC)


@dataclass
class Clock:
    at: dt.datetime = T0

    def __call__(self) -> dt.datetime:
        return self.at

    def advance(self, **delta: float) -> None:
        self.at = self.at + dt.timedelta(**delta)


@dataclass
class Lab:
    connection: Any
    clock: Clock = field(default_factory=Clock)
    mail: MemoryMailer = field(default_factory=MemoryMailer)

    def service(self, *, mail: bool = True) -> AccountService:
        return AccountService(
            self.connection,
            mailer=self.mail if mail else None,
            base_url=BASE_URL,
            now=self.clock,
            cost=CHEAP,
        )

    def link(self, path: str) -> str:
        """The token in the latest mailed link to `path`."""
        for message in reversed(self.mail.sent):
            found = re.search(
                re.escape(f"{BASE_URL}{path}?token=") + r"([A-Za-z0-9_-]+)", message.body
            )
            if found:
                return found.group(1)
        raise AssertionError(f"no mailed link to {path}")

    def admin(self, email: str = "owner@lab.example", name: str = "Lab Owner") -> Account:
        account, token = self.service().bootstrap_admin(email=email, display_name=name)
        self.service().reset_password(token=token, password=PASSWORD)
        return account

    def member(
        self, email: str, name: str, *, admin: Account, verify: bool = True, approve: bool = True
    ) -> Account:
        accounts = self.service()
        accounts.register(email=email)
        account = next(a for a in accounts.all() if a.email == email)
        if verify:
            account = accounts.verify_email(
                self.link("/verify"), display_name=name, password=PASSWORD
            )
        if verify and approve:
            account = accounts.approve(account.account_id, by=admin)
        return account
