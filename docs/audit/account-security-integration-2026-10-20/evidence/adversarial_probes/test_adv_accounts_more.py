"""More adversarial probes: the members' view of oversight, recovery links, and sign-in timing.

Each `test_*` PASSES while the defect it names is present, except `test_measure_*`, which only
measures and prints.
"""

from __future__ import annotations

import statistics
import time

import pytest

from lab_brain.accounts.mail import MailUnavailable
from lab_brain.accounts.oversight import Oversight, access_log
from lab_brain.accounts.service import AccountRefused, AccountService
from tests.account_fixtures import BASE_URL, CHEAP, PASSWORD, Lab

pytestmark = pytest.mark.postgres


@pytest.fixture
def lab(db):
    return Lab(db)


# -- K: members are shown only the newest 50 looks; older ones drop out of their view -----------


def test_an_admin_look_drops_out_of_the_members_view_after_fifty_newer_ones(lab):
    from lab_brain.accounts.projects import LabProjects

    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    project = LabProjects(lab.connection, now=lab.clock).create(
        ada, name="P", clearance=["PUBLIC"]
    )
    oversight = Oversight(lab.connection, admin, now=lab.clock)
    oversight.record(project, "material:art:the-one-that-mattered")
    for _ in range(50):
        lab.clock.advance(minutes=61)  # one routine project-summary look an hour, ~2 days
        assert oversight.project(project) is not None
    shown = access_log(lab.connection, project)
    stored = lab.connection.execute(
        "SELECT count(*) FROM admin_access_log WHERE project_id = %s", (project,)
    ).fetchone()[0]
    print("stored looks:", stored, "| shown to members:", len(shown),
          "| material look shown:", any(k == "material:" for _w, k, _q, _a in shown))
    assert stored == 51 and len(shown) == 50
    assert all(kind != "material:" for _who, kind, _q, _at in shown)


# -- L: a reset link outlives a password change ---------------------------------------------------


def test_a_reset_link_still_works_after_the_holder_changes_their_password(lab):
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    accounts.request_password_reset(email="ada@uni.example.edu")  # e.g. a leaked/forwarded mail
    stale = lab.link("/password/reset")
    lab.clock.advance(minutes=5)
    accounts.change_password(ada, current=PASSWORD, new="ada's fresh passphrase 1")
    lab.clock.advance(minutes=5)
    accounts.reset_password(token=stale, password="attacker passphrase 99")
    account, _ = accounts.sign_in(email="ada@uni.example.edu", password="attacker passphrase 99")
    print("signed in after the change with the older link's password:", account.email)
    assert account.email == "ada@uni.example.edu"


# -- A (second form): with mail failing, a throttled known address still answers "done" ----------


class _Failing:
    def send(self, message):  # noqa: ANN001
        raise MailUnavailable("mail server down")


def test_with_mail_failing_a_throttled_known_address_answers_differently(lab):
    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    accounts.register(email="ada@uni.example.edu")  # notices to Ada (REGISTERED counts too)
    accounts.register(email="ada@uni.example.edu")
    failing = AccountService(
        lab.connection, mailer=_Failing(), base_url=BASE_URL, now=lab.clock, cost=CHEAP
    )
    failing.register(email="ada@uni.example.edu")  # throttled: no mail tried, answered as done
    with pytest.raises(AccountRefused) as refused:
        failing.register(email="nobody@new.example")
    print("known (throttled): answered | unknown:", refused.value.code)
    assert refused.value.code == "mail_failed"


# -- sign-in timing, measured (no answer floor on /login) ------------------------------------------


def test_measure_sign_in_timing_known_vs_unknown(lab):
    from lab_brain.accounts.passwords import DEFAULT_COST

    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    # Production cost for the stored hash, as a deployment has it.
    from lab_brain.accounts.passwords import hash_password

    lab.connection.execute(
        "UPDATE accounts SET password_hash = %s WHERE email = 'ada@uni.example.edu'",
        (hash_password(PASSWORD, cost=DEFAULT_COST),),
    )
    accounts = AccountService(lab.connection, mailer=lab.mail, base_url=BASE_URL,
                              now=lab.clock, cost=DEFAULT_COST)

    def once(email: str) -> float:
        started = time.perf_counter()
        with pytest.raises(AccountRefused):
            accounts.sign_in(email=email, password="wrong password here!")
        return time.perf_counter() - started

    known, unknown = [], []
    for i in range(40):
        lab.clock.advance(minutes=20)  # stay clear of the lockout
        lab.connection.execute(
            "UPDATE accounts SET failed_logins = 0, locked_until = NULL"
            " WHERE email = 'ada@uni.example.edu'"
        )
        (known if i % 2 else unknown).append(once("ada@uni.example.edu" if i % 2 else
                                                   f"nobody{i}@new.example"))
        (unknown if i % 2 else known).append(once(f"nobody{i}x@new.example" if i % 2 else
                                                   "ada@uni.example.edu"))
    q = lambda xs: [round(x * 1000, 1) for x in statistics.quantiles(xs, n=4)]  # noqa: E731
    print(f"known   quartiles ms {q(known)}  min {min(known)*1000:.1f}")
    print(f"unknown quartiles ms {q(unknown)}  min {min(unknown)*1000:.1f}")
    wins = sum(k > u for k in known for u in unknown) / (len(known) * len(unknown))
    print(f"P(known slower than unknown) over all pairs: {wins:.2f}")
