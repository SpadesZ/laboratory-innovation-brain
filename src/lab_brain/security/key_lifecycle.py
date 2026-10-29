"""The interaction-signing key's lifecycle: generate, pin, rotate, retire, revoke, and check.

The web tier signs every research run it starts for a signed-in person with an Ed25519 key
(`security.interaction_attestation`). That key, and the authorities file pinning its public half,
are this deployment's root of trust for the claim INTERACTION_VERIFIED. This module is the
operator's tooling for them and the checks the web tier runs before it signs anything.

THE FILES. Neither lives in the database, and neither is ever written into a git working tree.
    signing key        PEM (PKCS8) Ed25519, optionally passphrase-encrypted; mode 0600, owned by
                       the service user; named by `LAB_BRAIN_INTERACTION_SIGNING_KEY`.
    authorities        one line per pinned key, `web:<label> ed25519:<base64> [until=<time>]
                       [revoked=<time>]`; owned by the operator, read-only to the service; named
                       by `LAB_BRAIN_INTERACTION_AUTHORITIES`.

RETIRE vs REVOKE -- the two ways a key stops counting, and why they differ.
    retire (`until=T`)   planned rotation. Statements dated before T still verify, none after.
                         Safe only while the key is NOT suspected compromised: its holder is the
                         web tier, which dates statements with its own clock.
    revoke (`revoked=T`) suspected or known compromise. NONE of the key's statements verifies any
                         more, including those dated before T. A statement's `signed_at` is chosen
                         by whoever holds the key; a thief can date a forgery a year before the
                         revocation, and nothing outside the statement records when it was really
                         made. So the only sound reading of "from T on, this key is not trusted"
                         is "this key's signature proves nothing", and runs it signed fall to
                         SESSION_RECORDED_UNVERIFIED (fail closed for the claim; the records stay).
                         T records when the operator acted.

THE START-UP CHECKS (`signer_startup_problems`, run by `InteractionSigner.from_environment`).
A named signing key is refused -- the web tier does not start -- when:
    - the key file is missing, a symbolic link or not a regular file;
    - it is readable or writable by its group or by anyone (any of the mode bits 077);
    - it is not owned by the user the service runs as;
    - its directory is writable by its group or by anyone (someone else could replace it);
    - it is inside a git working tree, or inside this project's source checkout;
    - no authorities file is configured, the file cannot be read or parsed, or it, or its
      directory, is writable by its group or by anyone;
    - the service user (when it is not root) owns the authorities file or its directory, and could
      therefore rewrite or replace the trust anchor it verifies against;
    - the key is not pinned there, is revoked, or was retired at or before now.
WHAT CANNOT BE CHECKED PORTABLY, PLAINLY. A process running as root can write every file, so when
the service runs as root the "not writable by the service user" check proves nothing: the web tier
still starts (the remaining checks hold), and `lab-brain interaction-key check`, which the
deployment runs as the service user, REFUSES root. POSIX ACLs, Linux capabilities, mount options
and a file system that ignores modes are not inspected; the checks read `stat` only.

Nothing here prints or stores the private key or its passphrase. The passphrase is read from
`LAB_BRAIN_INTERACTION_KEY_PASSPHRASE`, never from the command line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from lab_brain.security.interaction_attestation import (
    AUTHORITIES_ENV,
    PASSPHRASE_ENV,
    SIGNING_KEY_ENV,
    InteractionAuthority,
    InteractionUnverified,
    interaction_key_id,
    parse_interaction_authorities,
)
from lab_brain.security.reviewer_identity import IdentityUnverified, SigningKey

_LABEL = re.compile(r"^web:[a-z0-9][a-z0-9._-]{0,62}$")
#: This project's own source checkout, wherever it is installed from.
_SOURCE_ROOT = Path(__file__).resolve().parents[3]


class KeyLifecycleRefused(ValueError):
    """An operator's key or authorities change, or a check, is refused, and why."""


# -- what the checks read ------------------------------------------------------------------------


def working_tree_containing(path: str | os.PathLike[str]) -> Path | None:
    """The git working tree (or this project's source checkout) `path` lies in, if any."""
    target = Path(path).resolve()
    for directory in (target, *target.parents):
        if (directory / ".git").exists():
            return directory
        if (directory / "pyproject.toml").is_file() and (directory / "src" / "lab_brain").is_dir():
            return directory
    if target.is_relative_to(_SOURCE_ROOT) and (_SOURCE_ROOT / "src" / "lab_brain").is_dir():
        return _SOURCE_ROOT
    return None


def _loose_directory(path: Path) -> str | None:
    info = path.stat()
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and not info.st_mode & stat.S_ISVTX:
        return f"{path} is writable by its group or by anyone (mode {info.st_mode & 0o777:03o})"
    return None


def key_file_problems(path: str | os.PathLike[str], *, euid: int | None = None) -> list[str]:
    """Why the private key at `path` may not be used as the service's signing key (none: may)."""
    euid = os.geteuid() if euid is None else euid
    target = Path(path)
    try:
        info = target.lstat()
    except OSError as exc:
        return [f"the signing key {target} cannot be read ({type(exc).__name__})"]
    problems: list[str] = []
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        problems.append(f"the signing key {target} is not a regular file (a link is refused)")
        return problems
    if info.st_mode & 0o077:
        problems.append(
            f"the signing key {target} has permission {info.st_mode & 0o777:03o}; it must be "
            "readable by its owner only (chmod 600)"
        )
    if info.st_uid != euid:
        problems.append(
            f"the signing key {target} is owned by uid {info.st_uid}, not by the service user "
            f"(uid {euid})"
        )
    loose = _loose_directory(target.resolve().parent)
    if loose:
        problems.append(f"the signing key's directory: {loose}")
    tree = working_tree_containing(target)
    if tree is not None:
        problems.append(
            f"the signing key {target} is inside the working tree {tree}, where it can be "
            "committed; keep it outside every repository"
        )
    return problems


def trust_file_problems(
    path: str | os.PathLike[str], *, euid: int | None = None, refuse_root: bool = False
) -> list[str]:
    """Why the authorities file at `path` is not a trust anchor the service cannot rewrite."""
    euid = os.geteuid() if euid is None else euid
    target = Path(path)
    try:
        info = target.stat()
    except OSError as exc:
        return [f"the interaction authorities file {target} cannot be read ({type(exc).__name__})"]
    problems: list[str] = []
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        problems.append(
            f"the interaction authorities file {target} is writable by its group or by anyone "
            f"(mode {info.st_mode & 0o777:03o})"
        )
    directory = target.resolve().parent
    loose = _loose_directory(directory)
    if loose:
        problems.append(f"the interaction authorities file's directory: {loose}")
    if euid == 0:
        if refuse_root:
            problems.append(
                "the service runs as root, which can rewrite any file: the interaction "
                "authorities cannot be read-only to it; run the web tier as its own user"
            )
    else:
        if info.st_uid == euid:
            problems.append(
                f"the interaction authorities file {target} is owned by the service user (uid "
                f"{euid}), who could rewrite the keys it is verified against; the operator owns it"
            )
        if directory.stat().st_uid == euid:
            problems.append(
                f"the interaction authorities file's directory {directory} is owned by the "
                f"service user (uid {euid}), who could replace the file"
            )
    return problems


def signer_startup_problems(
    env: Mapping[str, str],
    *,
    public_key: str | None,
    euid: int | None = None,
    now: dt.datetime | None = None,
    refuse_root: bool = False,
) -> list[str]:
    """Why the signing key `env` names may not sign here. With `public_key` None, the key file
    alone (checked before it is opened); with it, the authorities that must pin it as well."""
    path = env.get(SIGNING_KEY_ENV, "").strip()
    if not path:
        return [f"{SIGNING_KEY_ENV} names no signing key"]
    if public_key is None:
        return key_file_problems(path, euid=euid)
    authorities = env.get(AUTHORITIES_ENV, "").strip()
    if not authorities:
        return [
            f"this deployment pins no interaction key ({AUTHORITIES_ENV}): every statement the "
            "signing key made would read unverified"
        ]
    problems = trust_file_problems(authorities, euid=euid, refuse_root=refuse_root)
    if problems:
        return problems
    try:
        pinned = parse_interaction_authorities(Path(authorities).read_text(encoding="utf-8"))
    except (OSError, InteractionUnverified) as exc:
        return [f"the interaction authorities file {authorities} cannot be used: {exc}"]
    key_id = interaction_key_id(public_key)
    authority = next((a for a in pinned if a.key_id == key_id), None)
    if authority is None:
        return [
            f"the signing key {key_id} is not pinned in {authorities}: every statement it made "
            "would read unverified"
        ]
    now = now or dt.datetime.now(dt.UTC)
    if authority.revoked_at is not None:
        return [
            f"the signing key {key_id} was revoked ({authority.revoked_at.isoformat()}); "
            "generate and pin a new one"
        ]
    if authority.valid_until is not None and authority.valid_until <= now:
        return [
            f"the signing key {key_id} was retired ({authority.valid_until.isoformat()}); "
            "configure the key that replaced it"
        ]
    return []


# -- generating a key ------------------------------------------------------------------------------


def generate_key(
    out: str | os.PathLike[str], *, passphrase: bytes | None = None, euid: int | None = None
) -> SigningKey:
    """A new Ed25519 key, written to `out` (0600, never over a file). Refused inside a git
    working tree, or in a directory its group or anyone may read or write, or one another user
    owns: a private key is born where only its owner can reach it."""
    euid = os.geteuid() if euid is None else euid
    target = Path(out)
    tree = working_tree_containing(target)
    if tree is not None:
        raise KeyLifecycleRefused(
            f"{target} is inside the working tree {tree}; a private key is never written into a "
            "repository (choose a directory outside it, e.g. /etc/lab-brain/keys)"
        )
    directory = target.resolve().parent
    try:
        info = directory.stat()
    except OSError as exc:
        raise KeyLifecycleRefused(f"the directory {directory} cannot be used: {exc}") from exc
    if info.st_mode & 0o077:
        raise KeyLifecycleRefused(
            f"the directory {directory} has permission {info.st_mode & 0o777:03o}; a private key "
            "is written only into a directory its owner alone can read (chmod 700)"
        )
    if info.st_uid != euid:
        raise KeyLifecycleRefused(
            f"the directory {directory} is owned by uid {info.st_uid}, not by you (uid {euid})"
        )
    if target.exists() or target.is_symlink():
        raise KeyLifecycleRefused(f"{target} exists; a key is never written over a file")
    key = SigningKey.generate()
    key.save(target, passphrase)
    return key


def authority_line(label: str, public_key: str) -> str:
    if not _LABEL.match(label):
        raise KeyLifecycleRefused(
            f"a key's label is `web:` and a short lower-case name, not {label!r}"
        )
    return InteractionAuthority(label, public_key).line()


# -- changing the authorities file ---------------------------------------------------------------


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    parse_interaction_authorities(text)  # refuse to edit a file that does not parse
    return text.splitlines()


def _write_lines(path: Path, lines: Sequence[str]) -> None:
    """Atomically: a reader sees the old file or the new one, never half of either."""
    text = "".join(f"{line}\n" for line in lines)
    parse_interaction_authorities(text)
    descriptor, temporary = tempfile.mkstemp(dir=path.resolve().parent, prefix=".authorities-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _edit(
    path: str | os.PathLike[str],
    key_id: str,
    change: Callable[[InteractionAuthority], InteractionAuthority],
) -> InteractionAuthority:
    target = Path(path)
    lines = _read_lines(target)
    changed: InteractionAuthority | None = None
    out: list[str] = []
    for line in lines:
        body, hash_, comment = line.partition("#")
        if body.strip():
            (authority,) = parse_interaction_authorities(body)
            if authority.key_id == key_id:
                changed = change(authority)
                line = changed.line() + (f"  #{comment}" if hash_ else "")
        out.append(line)
    if changed is None:
        raise KeyLifecycleRefused(f"{key_id} is not pinned in {target}")
    _write_lines(target, out)
    return changed


def pin(path: str | os.PathLike[str], label: str, public_key: str) -> str:
    """Append `public_key` to the authorities file (created if absent). Refused if pinned."""
    line = authority_line(label, public_key)
    target = Path(path)
    lines = _read_lines(target)
    _write_lines(target, [*lines, line])
    return line


def retire(path: str | os.PathLike[str], key_id: str, at: dt.datetime) -> InteractionAuthority:
    """`until=at` on `key_id` (an earlier `until` stands). Its statements dated before `at` still
    verify. For planned rotation only; a key that may be compromised is revoked."""

    def change(authority: InteractionAuthority) -> InteractionAuthority:
        if authority.valid_until is not None and authority.valid_until <= at:
            return authority
        return replace(authority, valid_until=at)

    return _edit(path, key_id, change)


def revoke(path: str | os.PathLike[str], key_id: str, at: dt.datetime) -> InteractionAuthority:
    """`revoked=at` on `key_id`: none of its statements verifies any more (see the module)."""

    def change(authority: InteractionAuthority) -> InteractionAuthority:
        if authority.revoked_at is not None:
            raise KeyLifecycleRefused(
                f"{key_id} was revoked already ({authority.revoked_at.isoformat()})"
            )
        return replace(authority, revoked_at=at)

    return _edit(path, key_id, change)


@dataclass(frozen=True)
class Rotation:
    new_line: str
    new_key_id: str
    retired: tuple[str, ...]


def rotate(
    path: str | os.PathLike[str],
    out: str | os.PathLike[str],
    *,
    label: str,
    at: dt.datetime,
    passphrase: bytes | None = None,
    euid: int | None = None,
) -> Rotation:
    """A new key at `out`, pinned; every other key still active at `at` retired `until=at`."""
    pinned = parse_interaction_authorities(
        Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    )
    authority_line(label, "A" * 43 + "=")  # the label, checked before a key is made
    key = generate_key(out, passphrase=passphrase, euid=euid)
    line = pin(path, label, key.public_key)
    retired = tuple(
        a.key_id
        for a in pinned
        if a.key_id != interaction_key_id(key.public_key) and a.active_at(at)
    )
    for key_id in retired:
        retire(path, key_id, at)
    return Rotation(line, interaction_key_id(key.public_key), retired)


# -- the operator's check -------------------------------------------------------------------------


def check(
    env: Mapping[str, str], *, euid: int | None = None, now: dt.datetime | None = None
) -> tuple[list[str], list[str]]:
    """(problems, notes) for this deployment's signing key and authorities, as the service user
    would use them -- stricter than start-up in one respect: it refuses a service running as root.
    """
    now = now or dt.datetime.now(dt.UTC)
    notes: list[str] = []
    authorities = env.get(AUTHORITIES_ENV, "").strip()
    if authorities:
        try:
            for a in parse_interaction_authorities(Path(authorities).read_text(encoding="utf-8")):
                state = (
                    f"revoked {a.revoked_at.isoformat()}"
                    if a.revoked_at
                    else f"retired {a.valid_until.isoformat()}"
                    if a.valid_until and a.valid_until <= now
                    else f"active, retires {a.valid_until.isoformat()}"
                    if a.valid_until
                    else "active"
                )
                notes.append(f"pinned {a.key_id} ({a.label}): {state}")
        except (OSError, InteractionUnverified):
            pass  # reported as a problem below
    if not env.get(SIGNING_KEY_ENV, "").strip():
        problems = (
            trust_file_problems(authorities, euid=euid, refuse_root=True) if authorities else []
        )
        notes.append(
            f"{SIGNING_KEY_ENV} is not set: web runs are recorded SESSION_RECORDED_UNVERIFIED"
        )
        return problems, notes
    problems = signer_startup_problems(env, public_key=None, euid=euid)
    if problems:
        return problems, notes
    passphrase = env.get(PASSPHRASE_ENV)
    try:
        key = SigningKey.load(
            env[SIGNING_KEY_ENV].strip(), passphrase.encode("utf-8") if passphrase else None
        )
    except (OSError, ValueError, IdentityUnverified) as exc:
        return [f"the signing key cannot be opened ({type(exc).__name__})"], notes
    notes.append(f"signing key {interaction_key_id(key.public_key)}")
    return (
        signer_startup_problems(
            env, public_key=key.public_key, euid=euid, now=now, refuse_root=True
        ),
        notes,
    )


# -- the command line ----------------------------------------------------------------------------


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """`lab-brain interaction-key ...`: no database; the operator's files only."""
    parser = sub.add_parser(
        "interaction-key",
        help=(
            "the web tier's interaction-signing key: generate, rotate, retire, revoke, check "
            "(files only, never the database)"
        ),
    )
    commands = parser.add_subparsers(dest="key_command", required=True)

    def encrypt(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--encrypt",
            action="store_true",
            help=f"encrypt the key with the passphrase in {PASSPHRASE_ENV} (never an argument)",
        )

    def at(p: argparse.ArgumentParser) -> None:
        p.add_argument("--at", help="ISO time with a zone (default now)")

    gen = commands.add_parser("generate", help="a new key file (0600) and its authorities line")
    gen.add_argument("--out", required=True, help="the private key's path, outside any repository")
    gen.add_argument("--label", default="web:primary")
    gen.add_argument("--authorities", help="also pin the key in this authorities file")
    encrypt(gen)
    rot = commands.add_parser(
        "rotate", help="a new key, pinned; every other active key retired from --at"
    )
    rot.add_argument("--authorities", required=True)
    rot.add_argument("--out", required=True)
    rot.add_argument("--label", required=True)
    at(rot)
    encrypt(rot)
    for name, text in (
        ("retire", "planned: statements dated before --at still verify"),
        ("revoke", "compromise: none of the key's statements verifies any more"),
    ):
        p = commands.add_parser(name, help=text)
        p.add_argument("--authorities", required=True)
        p.add_argument("--key-id", required=True, help="ik:<32 hex>")
        at(p)
    chk = commands.add_parser(
        "check", help="run the start-up checks as this user; exit 2 on any problem"
    )
    chk.add_argument("--key", help=f"default: {SIGNING_KEY_ENV}")
    chk.add_argument("--authorities", help=f"default: {AUTHORITIES_ENV}")


def _time(value: str | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.UTC).replace(microsecond=0)
    try:
        at = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise KeyLifecycleRefused(f"--at {value!r}: {exc}") from exc
    if at.tzinfo is None:
        raise KeyLifecycleRefused("--at needs a time zone, e.g. 2026-11-01T09:00:00+08:00")
    return at


def _passphrase(args: argparse.Namespace, env: Mapping[str, str]) -> bytes | None:
    if not getattr(args, "encrypt", False):
        return None
    value = env.get(PASSPHRASE_ENV, "")
    if len(value) < 12:
        raise KeyLifecycleRefused(
            f"--encrypt reads a passphrase of 12 or more characters from {PASSPHRASE_ENV}"
        )
    return value.encode("utf-8")


def run(args: argparse.Namespace, *, out: TextIO, env: Mapping[str, str]) -> int:
    """The `interaction-key` command. 0 done, 2 refused (with the reason on `out`)."""
    try:
        if args.key_command == "generate":
            key = generate_key(args.out, passphrase=_passphrase(args, env))
            line = (
                pin(args.authorities, args.label, key.public_key)
                if args.authorities
                else authority_line(args.label, key.public_key)
            )
            print(
                f"private key written to {args.out} (0600); key id "
                f"{interaction_key_id(key.public_key)}",
                file=out,
            )
            print(
                ("pinned in " + args.authorities + ":") if args.authorities else "pin this line:",
                file=out,
            )
            print(line, file=out)
        elif args.key_command == "rotate":
            rotation = rotate(
                args.authorities,
                args.out,
                label=args.label,
                at=_time(args.at),
                passphrase=_passphrase(args, env),
            )
            print(f"new key {rotation.new_key_id} written to {args.out} and pinned:", file=out)
            print(rotation.new_line, file=out)
            for key_id in rotation.retired:
                print(f"retired {key_id} until {_time(args.at).isoformat()}", file=out)
            print(f"point {SIGNING_KEY_ENV} at {args.out} and restart the web tier", file=out)
        elif args.key_command in ("retire", "revoke"):
            change = retire if args.key_command == "retire" else revoke
            authority = change(args.authorities, args.key_id, _time(args.at))
            print(authority.line(), file=out)
        else:
            merged = dict(env)
            if args.key:
                merged[SIGNING_KEY_ENV] = args.key
            if args.authorities:
                merged[AUTHORITIES_ENV] = args.authorities
            problems, notes = check(merged)
            for note in notes:
                print(note, file=out)
            for problem in problems:
                print(f"REFUSED: {problem}", file=out)
            if problems:
                return 2
            print("ok: the signing key may sign here", file=out)
    except (KeyLifecycleRefused, InteractionUnverified, IdentityUnverified, OSError) as refused:
        print(f"lab-brain: {refused}", file=out)
        return 2
    return 0


__all__ = [
    "KeyLifecycleRefused",
    "Rotation",
    "add_parser",
    "authority_line",
    "check",
    "generate_key",
    "key_file_problems",
    "pin",
    "retire",
    "revoke",
    "rotate",
    "run",
    "signer_startup_problems",
    "trust_file_problems",
    "working_tree_containing",
]
