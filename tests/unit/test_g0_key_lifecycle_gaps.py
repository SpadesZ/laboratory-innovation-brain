"""The interaction-signing key's gaps before its lifecycle existed, as the existing API shows them.

Each test uses only what `security.interaction_attestation` already offered (the signer's start-up
`InteractionSigner.from_environment`, the authorities parser, `InteractionTrust.verify`), so it
FAILED before `security.key_lifecycle` was wired in and passes after:

1. a signing key readable by the group or by anyone was accepted at start-up;
2. a signing key that is not pinned in the authorities file (or with none configured) was
   accepted -- every statement it signed would read unverified, silently;
3. a signing key retired by `until=` before now was accepted, and kept signing statements that
   could never verify;
4. a signing key inside a git working tree (where it can be committed) was accepted;
5. there was no way to revoke a compromised key: `revoked=` was refused by the parser, and a key's
   statements verified for as long as it stayed pinned.

Keys are generated in pytest's temporary directories, never in the repository.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from lab_brain.research.run_provenance import RunBinding
from lab_brain.security.interaction_attestation import (
    AUTHORITIES_ENV,
    SIGNING_KEY_ENV,
    InteractionSigner,
    InteractionTrust,
    InteractionUnverified,
    WebInteraction,
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


def _deploy(directory: Path, *, mode: int = 0o600, line: str | None = None) -> dict[str, str]:
    directory.mkdir(mode=0o700, exist_ok=True)
    key = SigningKey.generate()
    path = directory / "interaction.pem"
    key.save(path)
    os.chmod(path, mode)
    authorities = directory / "interaction-authorities"
    authorities.write_text(
        (line if line is not None else f"web:primary ed25519:{key.public_key}") + "\n",
        encoding="utf-8",
    )
    os.chmod(authorities, 0o644)
    return {SIGNING_KEY_ENV: str(path), AUTHORITIES_ENV: str(authorities), "public": key.public_key}


def test_gap_1_a_group_or_world_readable_signing_key_is_refused_at_start_up(tmp_path: Path):
    for mode in (0o640, 0o644, 0o604):
        env = _deploy(tmp_path / f"m{mode:o}", mode=mode)
        with pytest.raises(InteractionUnverified, match="permission"):
            InteractionSigner.from_environment(env)


def test_gap_2_a_signing_key_that_is_not_pinned_is_refused_at_start_up(tmp_path: Path):
    stranger = SigningKey.generate()
    env = _deploy(tmp_path / "a", line=f"web:other ed25519:{stranger.public_key}")
    with pytest.raises(InteractionUnverified, match="not pinned"):
        InteractionSigner.from_environment(env)
    env = _deploy(tmp_path / "b")
    del env[AUTHORITIES_ENV]
    with pytest.raises(InteractionUnverified, match="pins no interaction key"):
        InteractionSigner.from_environment(env)


def test_gap_3_a_retired_signing_key_is_refused_at_start_up(tmp_path: Path):
    env = _deploy(tmp_path / "a")
    Path(env[AUTHORITIES_ENV]).write_text(
        f"web:primary ed25519:{env['public']} until=2026-01-01T00:00:00+00:00\n", encoding="utf-8"
    )
    with pytest.raises(InteractionUnverified, match="retired"):
        InteractionSigner.from_environment(env)


def test_gap_4_a_signing_key_inside_a_git_working_tree_is_refused(tmp_path: Path):
    tree = tmp_path / "checkout"
    tree.mkdir(mode=0o700)
    (tree / ".git").mkdir()
    env = _deploy(tree / "secrets")
    with pytest.raises(InteractionUnverified, match="working tree"):
        InteractionSigner.from_environment(env)


def test_gap_5_a_revoked_key_s_statements_never_verify(tmp_path: Path):
    key = SigningKey.generate()
    signer = InteractionSigner(key, clock=lambda: T)
    attestation = WebInteraction("/runs", "POST", signer).attest(BINDING)
    pinned = InteractionTrust(parse_interaction_authorities(f"web:p ed25519:{key.public_key}"))
    pinned.verify(attestation, BINDING)  # verifies while pinned and not revoked
    # Revoked AFTER the statement's date: it still does not verify, since whoever holds a
    # compromised key chooses `signed_at` and can date a forgery before the revocation.
    revoked = InteractionTrust(
        parse_interaction_authorities(
            f"web:p ed25519:{key.public_key} revoked=2026-10-28T12:00:00+00:00"
        )
    )
    with pytest.raises(InteractionUnverified, match="revoked"):
        revoked.verify(attestation, BINDING)
