"""The interaction-signing key's lifecycle (`security.key_lifecycle`), in temporary directories.

Generate (owner-only file, never in a working tree or a directory others can read), pin, rotate,
retire and revoke through the operator's command, `lab-brain interaction-key`; the start-up checks
the web tier runs before it signs; and verification honouring revocation. No key is ever written
inside the repository: every one is made under pytest's `tmp_path`.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import stat
from pathlib import Path

import pytest

from lab_brain.interfaces import cli
from lab_brain.research.run_provenance import ClaimLevel, RunBinding
from lab_brain.security import key_lifecycle as kl
from lab_brain.security.interaction_attestation import (
    AUTHORITIES_ENV,
    PASSPHRASE_ENV,
    SIGNING_KEY_ENV,
    InteractionSigner,
    InteractionTrust,
    InteractionUnverified,
    WebInteraction,
    interaction_key_id,
    parse_interaction_authorities,
)
from lab_brain.security.reviewer_identity import SigningKey

T = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
BINDING = RunBinding(
    research_run_id="rrn:one",
    episode_id="epi:one",
    trace_id="trc:one",
    actor_id="act:ada",
    project_id="prj:rs",
    session_audit_ref="sar:" + "0" * 32,
)
ROOT_ONLY = os.geteuid() == 0


def _private_dir(tmp_path: Path, name: str = "keys") -> Path:
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    return directory


def _cmd(*argv: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(["interaction-key", *argv], out=out, env=env or {})
    return code, out.getvalue()


def _attest(key: SigningKey, at: dt.datetime):  # type: ignore[no-untyped-def]
    return WebInteraction("/runs", "POST", InteractionSigner(key, clock=lambda: at)).attest(BINDING)


def _trust(path: Path) -> InteractionTrust:
    return InteractionTrust.from_file(path)


# -- generate ------------------------------------------------------------------------------------


def test_generate_writes_an_owner_only_key_and_prints_only_its_public_line(tmp_path: Path):
    keys = _private_dir(tmp_path)
    code, text = _cmd("generate", "--out", str(keys / "web.pem"), "--label", "web:primary")
    assert code == 0, text
    pem = (keys / "web.pem").read_text()
    assert stat.S_IMODE((keys / "web.pem").stat().st_mode) == 0o600
    key = SigningKey.load(keys / "web.pem")
    assert f"web:primary ed25519:{key.public_key}" in text
    assert interaction_key_id(key.public_key) in text
    assert "".join(pem.splitlines()[1:-1]) not in text, "the private key is never printed"
    # Never over an existing file.
    again, refused = _cmd("generate", "--out", str(keys / "web.pem"))
    assert again == 2 and "never written over" in refused


def test_generate_refuses_a_working_tree_and_a_directory_others_can_read(tmp_path: Path):
    tree = _private_dir(tmp_path, "checkout")
    (tree / ".git").mkdir()
    code, text = _cmd("generate", "--out", str(tree / "web.pem"))
    assert code == 2 and "working tree" in text and not (tree / "web.pem").exists()
    # This project's own checkout is refused even without looking for `.git`.
    repository = Path(kl.__file__).resolve().parents[3]
    assert kl.working_tree_containing(repository / "secrets" / "web.pem") is not None
    for mode in (0o750, 0o705, 0o755, 0o770):
        loose = tmp_path / f"loose{mode:o}"
        loose.mkdir()
        os.chmod(loose, mode)
        code, text = _cmd("generate", "--out", str(loose / "web.pem"))
        assert code == 2 and "permission" in text, (mode, text)
        assert not (loose / "web.pem").exists()
    with pytest.raises(kl.KeyLifecycleRefused, match="owned by uid"):
        kl.generate_key(_private_dir(tmp_path, "other") / "k.pem", euid=os.geteuid() + 4242)


def test_an_encrypted_key_needs_its_passphrase_from_the_environment(tmp_path: Path):
    keys = _private_dir(tmp_path)
    code, text = _cmd("generate", "--out", str(keys / "web.pem"), "--encrypt")
    assert code == 2 and PASSPHRASE_ENV in text
    phrase = "a long enough passphrase"
    authorities = _private_dir(tmp_path, "trust") / "authorities"
    code, text = _cmd(
        "generate",
        "--out",
        str(keys / "web.pem"),
        "--encrypt",
        "--authorities",
        str(authorities),
        env={PASSPHRASE_ENV: phrase},
    )
    assert code == 0, text
    assert phrase not in text and "ENCRYPTED" in (keys / "web.pem").read_text()
    env = {SIGNING_KEY_ENV: str(keys / "web.pem"), AUTHORITIES_ENV: str(authorities)}
    with pytest.raises(InteractionUnverified, match="not a readable Ed25519 key"):
        InteractionSigner.from_environment(env)
    signer = InteractionSigner.from_environment({**env, PASSPHRASE_ENV: phrase})
    assert signer is not None and phrase not in repr(signer)


# -- rotate, retire, revoke ------------------------------------------------------------------------


def test_rotation_pins_the_new_key_and_retires_the_old_from_the_stated_time(tmp_path: Path):
    keys = _private_dir(tmp_path)
    authorities = _private_dir(tmp_path, "trust") / "authorities"
    authorities.write_text("# the web tier's keys\n")
    code, text = _cmd("generate", "--out", str(keys / "one.pem"), "--authorities", str(authorities))
    assert code == 0, text
    old = SigningKey.load(keys / "one.pem")
    switch = T + dt.timedelta(hours=1)
    code, text = _cmd(
        "rotate",
        "--authorities",
        str(authorities),
        "--out",
        str(keys / "two.pem"),
        "--label",
        "web:second",
        "--at",
        switch.isoformat(),
    )
    assert code == 0, text
    new = SigningKey.load(keys / "two.pem")
    assert f"retired {interaction_key_id(old.public_key)}" in text
    assert authorities.read_text().startswith("# the web tier's keys\n"), "comments are kept"
    assert stat.S_IMODE(authorities.stat().st_mode) == 0o644
    pinned = {a.key_id: a for a in parse_interaction_authorities(authorities.read_text())}
    assert pinned[interaction_key_id(old.public_key)].valid_until == switch
    assert pinned[interaction_key_id(new.public_key)].valid_until is None
    trust = _trust(authorities)
    trust.verify(_attest(old, T), BINDING)  # before the switch: still verifies
    with pytest.raises(InteractionUnverified, match="retired"):
        trust.verify(_attest(old, switch), BINDING)
    trust.verify(_attest(new, switch), BINDING)
    # The retired key no longer starts the web tier once its time has passed.
    old_env = {SIGNING_KEY_ENV: str(keys / "one.pem"), AUTHORITIES_ENV: str(authorities)}
    assert kl.signer_startup_problems(old_env, public_key=old.public_key, now=T) == []
    (problem,) = kl.signer_startup_problems(old_env, public_key=old.public_key, now=switch)
    assert "retired" in problem


def test_revocation_stops_every_statement_of_the_key_even_those_dated_before(tmp_path: Path):
    keys = _private_dir(tmp_path)
    authorities = _private_dir(tmp_path, "trust") / "authorities"
    assert _cmd("generate", "--out", str(keys / "k.pem"), "--authorities", str(authorities))[0] == 0
    key = SigningKey.load(keys / "k.pem")
    before = _attest(key, T)
    _trust(authorities).verify(before, BINDING)
    revoked_at = T + dt.timedelta(days=1)
    code, text = _cmd(
        "revoke",
        "--authorities",
        str(authorities),
        "--key-id",
        interaction_key_id(key.public_key),
        "--at",
        revoked_at.isoformat(),
    )
    assert code == 0 and f"revoked={revoked_at.isoformat()}" in text, text
    trust = _trust(authorities)
    for statement in (before, _attest(key, revoked_at), _attest(key, T - dt.timedelta(days=300))):
        with pytest.raises(InteractionUnverified, match="revoked"):
            trust.verify(statement, BINDING)
    claim = trust.claim("WEB_SESSION", BINDING, before)
    assert claim.level is ClaimLevel.SESSION_RECORDED_UNVERIFIED and "revoked" in claim.reason
    env = {SIGNING_KEY_ENV: str(keys / "k.pem"), AUTHORITIES_ENV: str(authorities)}
    with pytest.raises(InteractionUnverified, match="revoked"):
        InteractionSigner.from_environment(env)
    # Revoked once; an unknown key is refused; a retired key can still be revoked.
    assert _cmd("revoke", "--authorities", str(authorities), "--key-id", claim.key_id or "")[0] == 2
    code, text = _cmd("retire", "--authorities", str(authorities), "--key-id", "ik:" + "0" * 32)
    assert code == 2 and "not pinned" in text


def test_the_authorities_line_takes_each_option_once_with_a_zone():
    key = SigningKey.generate().public_key
    (a,) = parse_interaction_authorities(
        f"web:p ed25519:{key} revoked=2026-11-01T00:00:00+00:00 until=2026-10-01T00:00:00+00:00"
    )
    assert a.revoked_at and a.valid_until and not a.active_at(T)
    assert parse_interaction_authorities(a.line()) == (a,)
    for bad in (
        f"web:p ed25519:{key} revoked=2026-11-01T00:00:00",
        f"web:p ed25519:{key} until=2026-11-01T00:00:00Z until=2026-12-01T00:00:00Z",
        f"web:p ed25519:{key} expires=2026-11-01T00:00:00Z",
        f"web:p ed25519:{key} revoked",
    ):
        with pytest.raises(InteractionUnverified):
            parse_interaction_authorities(bad)
    with pytest.raises(kl.KeyLifecycleRefused, match="label"):
        kl.authority_line("primary", key)


# -- the start-up checks ---------------------------------------------------------------------------


def _deployed(tmp_path: Path) -> tuple[dict[str, str], SigningKey]:
    keys = _private_dir(tmp_path)
    trust = _private_dir(tmp_path, "trust")
    os.chmod(trust, 0o755)
    key = kl.generate_key(keys / "web.pem")
    kl.pin(trust / "authorities", "web:primary", key.public_key)
    return {
        SIGNING_KEY_ENV: str(keys / "web.pem"),
        AUTHORITIES_ENV: str(trust / "authorities"),
    }, key


def test_a_well_deployed_key_starts(tmp_path: Path):
    env, key = _deployed(tmp_path)
    signer = InteractionSigner.from_environment(env)
    assert signer is not None and signer.key_id == interaction_key_id(key.public_key)


def test_start_up_refuses_a_link_a_loose_directory_and_writable_trust_files(tmp_path: Path):
    env, _key = _deployed(tmp_path)
    key_path, authorities = Path(env[SIGNING_KEY_ENV]), Path(env[AUTHORITIES_ENV])
    link = key_path.parent / "link.pem"
    link.symlink_to(key_path)
    with pytest.raises(InteractionUnverified, match="not a regular file"):
        InteractionSigner.from_environment({**env, SIGNING_KEY_ENV: str(link)})
    link.unlink()
    os.chmod(key_path.parent, 0o770)
    with pytest.raises(InteractionUnverified, match=r"directory.*writable"):
        InteractionSigner.from_environment(env)
    os.chmod(key_path.parent, 0o700)
    for mode in (0o664, 0o646):
        os.chmod(authorities, mode)
        with pytest.raises(InteractionUnverified, match="writable by its group or by anyone"):
            InteractionSigner.from_environment(env)
    os.chmod(authorities, 0o644)
    os.chmod(authorities.parent, 0o777)
    with pytest.raises(InteractionUnverified, match="writable"):
        InteractionSigner.from_environment(env)
    os.chmod(authorities.parent, 0o755)
    assert InteractionSigner.from_environment(env) is not None


@pytest.mark.skipif(not ROOT_ONLY, reason="giving a file to another user needs root")
def test_a_service_user_that_owns_its_trust_anchor_is_refused(tmp_path: Path):
    """As a non-root service user (uid 65534, `nobody`): the key must be its own, the
    authorities file and directory must not be."""
    env, key = _deployed(tmp_path)
    key_path, authorities = Path(env[SIGNING_KEY_ENV]), Path(env[AUTHORITIES_ENV])
    service = 65534
    os.chown(key_path, service, -1)
    os.chown(key_path.parent, service, -1)
    assert kl.signer_startup_problems(env, public_key=None, euid=service) == []
    assert kl.signer_startup_problems(env, public_key=key.public_key, euid=service) == []
    os.chown(authorities, service, -1)
    (problem,) = kl.signer_startup_problems(env, public_key=key.public_key, euid=service)
    assert "owned by the service user" in problem
    os.chown(authorities, 0, -1)
    os.chown(authorities.parent, service, -1)
    (problem,) = kl.signer_startup_problems(env, public_key=key.public_key, euid=service)
    assert "could replace the file" in problem
    # The key itself must be the service's: one owned by someone else is refused.
    os.chown(key_path, 0, -1)
    assert any(
        "not by the service user" in p
        for p in kl.signer_startup_problems(env, public_key=None, euid=service)
    )


def test_the_operator_check_refuses_root_and_reports_each_key(tmp_path: Path):
    env, key = _deployed(tmp_path)
    code, text = _cmd("check", env=env)
    if ROOT_ONLY:
        assert code == 2 and "runs as root" in text, text
    else:  # pragma: no cover - when the suite runs as an ordinary user
        assert code in (0, 2)
    assert f"pinned {interaction_key_id(key.public_key)} (web:primary): active" in text
    problems, _notes = kl.check(env, euid=65534 if ROOT_ONLY else None)
    assert any("not by the service user" in p for p in problems) or not ROOT_ONLY
    os.chmod(env[SIGNING_KEY_ENV], 0o644)
    code, text = _cmd("check", env=env)
    assert code == 2 and "REFUSED" in text and "chmod 600" in text
