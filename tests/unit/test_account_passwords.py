"""Passwords and tokens: the standard library's scrypt and `secrets`, and nothing of our own."""

from __future__ import annotations

import pytest

from lab_brain.accounts import passwords
from lab_brain.accounts.mail import mailer_from
from lab_brain.accounts.passwords import ScryptCost, WeakPassword


def test_the_production_cost_is_scrypt_at_owasps_minimum():
    stored = passwords.hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$32768$8$1$")
    assert passwords.verify_password("correct horse battery staple", stored)
    assert not passwords.verify_password("correct horse battery stapl", stored)
    assert passwords.hash_password("correct horse battery staple") != stored, "a fresh salt"


def test_a_cheaper_or_malformed_hash_is_flagged_and_never_verifies_by_accident():
    cheap = passwords.hash_password("correct horse battery staple", cost=ScryptCost(n=2**10))
    assert passwords.verify_password("correct horse battery staple", cheap)
    assert passwords.needs_rehash(cheap) and not passwords.needs_rehash(
        passwords.hash_password("x" * 12)
    )
    for stored in (None, "", "plain", "scrypt$3$8$1$AA==$AA==", "scrypt$1024$8$1$!!$AA=="):
        assert not passwords.verify_password("anything at all", stored)


@pytest.mark.parametrize(
    ("password", "email"),
    [
        ("short", ""),
        ("x" * 257, ""),
        ("ada@uni.example.edu", "ada@uni.example.edu"),
        ("abababababab", ""),
    ],
)
def test_the_policy_refuses_weak_passwords(password, email):
    with pytest.raises(WeakPassword):
        passwords.check_password_policy(password, email=email)


def test_tokens_are_random_and_only_their_digest_is_kept():
    first, second = passwords.new_token(), passwords.new_token()
    assert first != second and len(first) >= 43
    assert passwords.token_hash(first) != first and len(passwords.token_hash(first)) == 64


def test_any_domain_is_an_address_and_addresses_are_normalised():
    assert passwords.normalized_email("  Ada@Uni.Example.EDU ") == "ada@uni.example.edu"
    assert passwords.normalized_email("someone@gmail.com") == "someone@gmail.com"
    for bad in ("no-at-sign", "a@b", "two@@signs.example", "spa ce@x.example", ""):
        assert passwords.normalized_email(bad) is None


def test_mail_fails_closed_until_configured(tmp_path):
    assert mailer_from({}) is None
    assert mailer_from({}, outbox=tmp_path) is not None
    with pytest.raises(ValueError, match="LAB_BRAIN_SMTP_FROM"):
        mailer_from({"LAB_BRAIN_SMTP_HOST": "smtp.example"})
    smtp = mailer_from(
        {
            "LAB_BRAIN_SMTP_HOST": "smtp.example",
            "LAB_BRAIN_SMTP_FROM": "lab@example.org",
            "LAB_BRAIN_SMTP_PORT": "465",
        }
    )
    assert getattr(smtp, "implicit_tls", None) is True
