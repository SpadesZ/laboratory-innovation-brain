"""Adversarial probes: accounts, registration, sessions and the 012u/012v rules.

Each test PASSES while the defect it names is present (it asserts the defective behaviour).
"""

from __future__ import annotations

import psycopg
import pytest

from lab_brain.accounts.service import AccountRefused
from tests.account_fixtures import PASSWORD, Lab
from tests.e2e.test_web_accounts_postgres import _browser, _csrf
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres


@pytest.fixture
def lab(db):
    return Lab(db)


# -- A: the registration cap answers differently for a known and an unknown address -------------


def test_registration_cap_reveals_whether_an_address_has_an_account(lab, tmp_path):
    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    browser = _browser(tmp_path, lab.mail)
    page = browser.get("/register")
    token = _csrf(page)
    # An anonymous requester fills the hourly cap (30 new accounts an hour) with throwaway
    # addresses, until a new address is refused.
    for i in range(40):
        r = browser.post("/register", {"csrf": token, "email": f"filler{i}@spam.example"})
        if r.status == 409:
            break
    print("cap reached after", i, "filler registrations")
    known = browser.post("/register", {"csrf": token, "email": "ada@uni.example.edu"})
    unknown = browser.post("/register", {"csrf": token, "email": "nobody@new.example"})
    print("known:", known.status, "| unknown:", unknown.status)
    print("unknown says:", "Too many registrations" in unknown.text)
    # DEFECT: the known address gets the normal answer, the unknown one a 409 'busy'.
    assert known.status == 200 and "Too many registrations" not in known.text
    assert unknown.status == 409 and "Too many registrations right now" in unknown.text


def test_registration_cap_oracle_at_the_service(lab):
    admin = lab.admin()
    lab.member("ada@uni.example.edu", "Ada", admin=admin)
    accounts = lab.service()
    for i in range(40):
        try:
            accounts.register(email=f"filler{i}@spam.example")
        except AccountRefused:
            break
    print("cap reached after", i, "filler registrations")
    accounts.register(email="ada@uni.example.edu")  # known: answered as usual
    with pytest.raises(AccountRefused) as refused:
        accounts.register(email="nobody@new.example")  # unknown: refused
    print("unknown refused with:", refused.value.code)
    assert refused.value.code == "busy"


# -- B: two administrators demoting each other at once leave the laboratory with none -----------


def _two_admins(lab: Lab):
    first = lab.admin()
    second = lab.member("second@lab.example", "Second", admin=first)
    second = lab.service().set_role(second.account_id, "ADMIN", by=first)
    return first, second


def _active_admins(db) -> int:
    return db.execute(
        "SELECT count(*) FROM accounts WHERE system_role = 'ADMIN' AND status = 'ACTIVE'"
    ).fetchone()[0]


def test_concurrent_demotions_through_the_service_leave_no_active_admin(lab):
    from lab_brain.accounts.service import AccountService
    from tests.account_fixtures import BASE_URL, CHEAP

    first, second = _two_admins(lab)
    c1, c2 = psycopg.connect(database_url()), psycopg.connect(database_url())
    try:
        s1 = AccountService(c1, mailer=lab.mail, base_url=BASE_URL, now=lab.clock, cost=CHEAP)
        s2 = AccountService(c2, mailer=lab.mail, base_url=BASE_URL, now=lab.clock, cost=CHEAP)
        # Two requests in flight at once (the server is threaded): each runs the service's own
        # transaction; neither has committed when the other checks the last-admin rule.
        with c1.transaction(), c2.transaction():
            s1.set_role(second.account_id, "MEMBER", by=first)  # first demotes second
            s2.set_role(first.account_id, "MEMBER", by=second)  # second demotes first
        c1.commit()
        c2.commit()
    finally:
        c1.close()
        c2.close()
    n = _active_admins(lab.connection)
    print("active administrators after both commits:", n)
    assert n == 0  # DEFECT: 012u's "the last active administrator is kept" is broken


def test_concurrent_suspensions_in_sql_leave_no_active_admin(lab):
    first, second = _two_admins(lab)
    c1, c2 = psycopg.connect(database_url()), psycopg.connect(database_url())
    try:
        c1.execute("UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s",
                   (second.account_id,))
        c2.execute("UPDATE accounts SET status = 'SUSPENDED' WHERE account_id = %s",
                   (first.account_id,))
        c1.commit()
        c2.commit()
    finally:
        c1.close()
        c2.close()
    n = _active_admins(lab.connection)
    print("active administrators:", n)
    assert n == 0


# -- C: a declined registration of an unconfirmed address strands that address for good --------


def test_a_declined_unconfirmed_address_can_never_register_again(lab):
    admin = lab.admin()
    accounts = lab.service()
    # A stranger (or a typo) registers victim@uni.example.edu; the administrator declines it,
    # as the dashboard advises for a registration they do not recognise.
    accounts.register(email="victim@uni.example.edu")
    stranded = next(a for a in accounts.all() if a.email == "victim@uni.example.edu")
    accounts.reject(stranded.account_id, by=admin)
    lab.clock.advance(hours=49)  # the one verification link has expired
    sent_before = len(lab.mail.sent)
    accounts.register(email="victim@uni.example.edu")  # the real owner tries to register
    new = lab.mail.sent[sent_before:]
    print("mail to the owner:", [m.subject for m in new])
    assert [m.subject for m in new] == ["Lab Brain: a registration with your address"]
    assert "/verify?token=" not in new[0].body, "no confirmation link: only 'sign in or reset'"
    accounts.request_password_reset(email="victim@uni.example.edu")
    assert len(lab.mail.sent) == sent_before + 1, "and a reset sends nothing"
    for act in (accounts.approve, accounts.reactivate):
        with pytest.raises(AccountRefused) as refused:
            act(stranded.account_id, by=admin)
        print(act.__name__, "->", refused.value.code)
    # Nothing in the service ever deletes or re-opens it: the address is unusable for good.
    assert accounts.get(stranded.account_id).status == "SUSPENDED"


def test_a_declined_registration_still_confirms_and_gets_a_password(lab):
    """Observation (not a policy break): a decline does not end the verification link."""
    admin = lab.admin()
    accounts = lab.service()
    accounts.register(email="later@uni.example.edu")
    pending = next(a for a in accounts.all() if a.email == "later@uni.example.edu")
    accounts.reject(pending.account_id, by=admin)
    confirmed = accounts.verify_email(lab.link("/verify"), display_name="X", password=PASSWORD)
    print("after decline:", confirmed.status, confirmed.email_verified_at is not None)
    assert confirmed.status == "SUSPENDED" and confirmed.email_verified_at is not None
    with pytest.raises(AccountRefused) as refused:
        accounts.sign_in(email="later@uni.example.edu", password=PASSWORD)
    assert refused.value.code == "declined"


# -- D: what 012u's triggers leave to the application ---------------------------------------------


def test_any_writer_makes_any_account_an_administrator_with_no_administrator(lab):
    admin = lab.admin()
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    carol = lab.member("carol@lab.example", "Carol", admin=admin, approve=False)
    # Approval needs an active administrator other than the holder (012u)...
    with pytest.raises(psycopg.errors.RaiseException):
        lab.connection.execute(
            "UPDATE accounts SET approved_at = now(), approved_by_actor_id = actor_id,"
            " status = 'ACTIVE' WHERE account_id = %s",
            (carol.account_id,),
        )
    # ...but promotion to ADMIN, and reactivating a suspended account, need nobody.
    lab.connection.execute(
        "UPDATE accounts SET system_role = 'ADMIN' WHERE account_id = %s", (bob.account_id,)
    )
    lab.service().suspend(bob.account_id, by=admin, reason="left the lab")
    lab.connection.execute(
        "UPDATE accounts SET status = 'ACTIVE' WHERE account_id = %s", (bob.account_id,)
    )
    row = lab.connection.execute(
        "SELECT system_role, status FROM accounts WHERE account_id = %s", (bob.account_id,)
    ).fetchone()
    events = lab.connection.execute(
        "SELECT kind FROM account_events WHERE account_id = %s ORDER BY seq", (bob.account_id,)
    ).fetchall()
    print("bob now:", tuple(row), "events:", [e[0] for e in events])
    assert tuple(row) == ("ADMIN", "ACTIVE")
    assert ("ROLE_CHANGED",) not in [tuple(e) for e in events]


def test_session_lifetime_and_idle_limits_live_only_in_the_application(lab):
    import datetime as dt

    from lab_brain.accounts.passwords import new_token, token_hash

    admin = lab.admin()
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    token = new_token()
    now = lab.clock()
    # A 10-year session, last seen in the future: the database accepts it...
    lab.connection.execute(
        "INSERT INTO account_sessions (session_hash, account_id, created_at, last_seen_at,"
        " expires_at) VALUES (%s, %s, %s, %s, %s)",
        (token_hash(token), bob.account_id, now, now + dt.timedelta(days=3650),
         now + dt.timedelta(days=3650)),
    )
    lab.clock.advance(days=365)
    # ...and the application honours it a year later (neither 12 h nor 2 h idle applies).
    signed = lab.service().session(token)
    print("session a year later:", signed and signed.email)
    assert signed is not None and signed.email == "bob@gmail.example"
