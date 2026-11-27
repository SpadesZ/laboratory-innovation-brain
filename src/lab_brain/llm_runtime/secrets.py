"""Model-provider credentials: referenced, never stored here, never shown.

The database holds a REFERENCE (`secret_ref`) and a FINGERPRINT (`****abcd`), never a credential:

    env:NAME                  the credential is the environment variable NAME of the process that
                              runs the workspace (the operator sets it; nothing here writes it)
    wincred:lab-brain/llm/ID  the credential is a generic credential in the operating system's
                              store (Windows Credential Manager, protected per user by the OS)
    file:lab-brain/llm/ID     the credential is a file in this deployment's credential directory
                              (`DirectoryCredentialStore`: the container deployment's own volume)

A credential typed into the workspace is written ONLY to the credential store this process was
given: Windows Credential Manager where the workspace runs on Windows, the credential directory
where the deployment provides one (`lab-brain web --credential-dir`). With neither, storing one
FAILS CLOSED: the operator is told to set an environment variable and reference it. There is no
reversible encoding and no fallback.

WHAT PROTECTS A STORED KEY -- said as it is, never more. Windows Credential Manager is the
operating system's store for this user. The credential directory is FILESYSTEM ISOLATION, NOT
ENCRYPTION: a directory only the workspace's user may enter (0700), one file per key readable only
by that user (0600) where the filesystem honours POSIX modes, on a volume only the workspace
container mounts, outside every route the web server answers, never in the image, never in the
database. Anyone who can read that volume -- root on the host, a Docker administrator -- can read
the keys.

The fingerprint is HMAC-SHA256 under this deployment's salt, first four hex digits: enough to tell
"which key is this" and to notice a rotation, and it contains no character of the key. A credential
leaves this module only to the provider client that sends it, and every provider message is
redacted of it before it is shown or recorded.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import re
import sys
import uuid
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ENV = "env"
WINCRED = "wincred"
FILE = "file"

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
#: The one name shape a stored credential has, in either store: an opaque id and nothing else.
_STORED_NAME = re.compile(
    r"^lab-brain/llm/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)

#: The longest pasted key accepted. Provider keys are well under it; anything longer is not a key.
MAX_KEY_LENGTH = 4096

#: Shapes of provider keys. A reference that looks like one is refused: it IS the key.
_KEY_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
)


class SecretError(ValueError):
    """A secret reference is malformed, looks like a credential, or cannot be stored.

    `code` names the case for a page to explain in its own words; the message never contains a
    credential."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


class SecretUnavailable(RuntimeError):
    """The referenced credential cannot be read here, or no secure store is available."""

    def __init__(self, message: str, *, code: str = "unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SecretRef:
    scheme: str
    name: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.name}"


def looks_like_credential(text: str) -> bool:
    return any(shape.search(text) for shape in _KEY_SHAPES)


def parse_secret_ref(text: str) -> SecretRef:
    """`env:NAME`, `wincred:lab-brain/llm/<uuid>` or `file:lab-brain/llm/<uuid>`; anything else is
    refused -- a pasted key above all."""
    value = text.strip()
    if looks_like_credential(value):
        raise SecretError(
            "that looks like a credential itself, not a reference to one; it was not saved",
            code="looks_like_key",
        )
    scheme, _, name = value.partition(":")
    if scheme == ENV and _ENV_NAME.match(name):
        return SecretRef(ENV, name)
    if scheme in (WINCRED, FILE) and _STORED_NAME.match(name):
        return SecretRef(scheme, name)
    raise SecretError(
        "a secret reference is env:VARIABLE_NAME, or a stored credential's reference",
        code="ref_invalid",
    )


def check_pasted_key(secret: str) -> str:
    """A key as pasted, trimmed -- or refused, without repeating it: empty, too long, or with a
    space, a line break or another control character inside (a key has none; a paste that does
    is a paste of something else)."""
    value = secret.strip()
    if not value:
        raise SecretError("the credential is empty", code="empty")
    if len(value) > MAX_KEY_LENGTH or any(ch.isspace() or not ch.isprintable() for ch in value):
        raise SecretError(
            "that is not a single API key (it is too long, or has spaces, line breaks or control "
            "characters inside); nothing was saved",
            code="invalid",
        )
    return value


def fingerprint(secret: str, salt: str) -> str:
    digest = hmac.new(salt.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()
    return "****" + digest[:4]


def redact(text: str, secrets: Iterable[str]) -> str:
    """`text` with every given secret, and anything shaped like a credential, replaced."""
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    for shape in _KEY_SHAPES:
        out = shape.sub("[redacted]", out)
    return out


class CredentialStore(Protocol):
    """Where a typed-in credential is kept. The OPERATING SYSTEM's store, or the deployment's
    credential directory -- never a file in the repository, the image or the database.

    `scheme` is the reference scheme it answers to; `protection` says, for a page to repeat
    accurately, what protects what it holds: "os" (the operating system's credential store) or
    "filesystem" (filesystem permissions and isolation, not encryption)."""

    name: str

    def available(self) -> bool: ...

    def write(self, target: str, secret: str) -> None: ...

    def read(self, target: str) -> str | None: ...

    def delete(self, target: str) -> None: ...


#: "Use this platform's own credential store" -- distinct from `None`, which means "none at all".
PLATFORM_STORE: Any = object()


def _scheme_of(store: CredentialStore) -> str:
    return str(getattr(store, "scheme", WINCRED))


class SecretStore:
    """Resolves references, and stores a typed-in credential only in the store it was given.

    `credentials` is `PLATFORM_STORE` by default (Windows Credential Manager where there is one),
    or an explicit store (the deployment's `DirectoryCredentialStore`), or `None` for NO
    credential store: never silently the platform's."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        credentials: CredentialStore | None = PLATFORM_STORE,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._credentials: CredentialStore | None = (
            default_credential_store() if credentials is PLATFORM_STORE else credentials
        )

    @property
    def secure_store(self) -> str | None:
        """The name of the store a typed-in credential would go to, or `None` if there is none."""
        if self._credentials is None or not self._credentials.available():
            return None
        return self._credentials.name

    @property
    def store_protection(self) -> str | None:
        """What protects a stored credential here: "os", "filesystem", or `None` (no store)."""
        if self.secure_store is None:
            return None
        return str(getattr(self._credentials, "protection", "os"))

    def _store_for(self, ref: SecretRef) -> CredentialStore:
        store = self._credentials
        if store is None or not store.available():
            raise SecretUnavailable(
                "this workspace has no credential store to read a stored credential from",
                code="store_unavailable",
            )
        if _scheme_of(store) != ref.scheme:
            raise SecretUnavailable(
                f"this workspace keeps credentials as {_scheme_of(store)}:, not {ref.scheme}:",
                code="store_unavailable",
            )
        return store

    def resolve(self, ref: SecretRef) -> str:
        if ref.scheme == ENV:
            value = self._environ.get(ref.name)
            if not value:
                raise SecretUnavailable(
                    f"the environment variable {ref.name} is not set for this workspace",
                    code="env_unset",
                )
            return value
        if ref.scheme in (WINCRED, FILE):
            stored = self._store_for(ref).read(ref.name)
            if not stored:
                raise SecretUnavailable(
                    f"the credential store holds nothing under {ref}", code="missing"
                )
            return stored
        raise SecretUnavailable(f"unknown secret scheme {ref.scheme!r}", code="ref_invalid")

    def store(self, secret: str) -> SecretRef:
        """Keep a typed-in credential in this workspace's store, under a fresh opaque id. FAILS
        CLOSED where there is none."""
        value = check_pasted_key(secret)
        store = self._credentials
        if store is None or not store.available():
            raise SecretUnavailable(
                "no secure credential store is available on this machine, so a typed-in "
                "credential cannot be kept; set an environment variable for the workspace and "
                "reference it as env:NAME",
                code="store_unavailable",
            )
        ref = SecretRef(_scheme_of(store), f"lab-brain/llm/{uuid.uuid4()}")
        try:
            store.write(ref.name, value)
        except (OSError, SecretUnavailable):
            # Never the store's own message: nothing it raised may carry the credential out.
            with suppress(Exception):
                store.delete(ref.name)
            raise SecretUnavailable(
                "the credential store could not keep the credential; nothing was saved",
                code="write_failed",
            ) from None
        return ref

    def forget(self, ref: SecretRef) -> None:
        """Delete a stored credential. `env:` references are the operator's and are never
        touched; a reference to another kind of store than this one is left alone."""
        store = self._credentials
        if (
            ref.scheme in (WINCRED, FILE)
            and store is not None
            and store.available()
            and _scheme_of(store) == ref.scheme
        ):
            store.delete(ref.name)


# -- the deployment's credential directory (the container deployment) ------------------------------


class DirectoryCredentialStore:
    """Keys a researcher pasted, one file each, in a directory this deployment dedicates to them.

    FILESYSTEM ISOLATION, NOT ENCRYPTION (module docstring). The directory is created 0700 and each
    file 0600, written to a temporary file and moved into place, so a key is never half written.
    A file is named by the opaque id of its reference and holds the key and nothing else: no
    connection, provider or project is recorded beside it. Nothing here logs, prints or raises a
    key; an error names the operation, never the content."""

    name = "this deployment's credential directory"
    scheme = FILE
    protection = "filesystem"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def available(self) -> bool:
        try:
            self._ensure()
        except OSError:
            return False
        return os.access(self._root, os.W_OK | os.X_OK)

    def _ensure(self) -> None:
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The mode a volume or an existing directory came with is not trusted: set it again.
        with suppress(OSError):
            os.chmod(self._root, 0o700)

    def _path(self, target: str) -> Path:
        match = _STORED_NAME.fullmatch(target)
        if match is None:
            raise SecretError("not a stored credential's name", code="ref_invalid")
        return self._root / match.group(1)

    def write(self, target: str, secret: str) -> None:
        path = self._path(target)
        self._ensure()
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(secret.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            with suppress(OSError):
                os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except BaseException:
            with suppress(OSError):
                temporary.unlink()
            raise

    def read(self, target: str) -> str | None:
        try:
            data = self._path(target).read_bytes()
        except FileNotFoundError:
            return None
        return data.decode("utf-8").strip() or None

    def delete(self, target: str) -> None:
        with suppress(FileNotFoundError):
            self._path(target).unlink()


# -- Windows Credential Manager, through the OS API (no dependency) --------------------------------


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", ctypes.c_uint64),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class WindowsCredentialStore:
    """Generic credentials in Windows Credential Manager, protected by the OS for this user."""

    name = "Windows Credential Manager"
    scheme = WINCRED
    protection = "os"

    def available(self) -> bool:
        return sys.platform == "win32"

    def _api(self) -> Any:
        # Reached through getattr: these names exist only on Windows, where this is called.
        return getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)  # noqa: B009

    def write(self, target: str, secret: str) -> None:
        blob = secret.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIAL(
            Type=_CRED_TYPE_GENERIC,
            TargetName=target,
            Comment="Laboratory Innovation Brain model-provider credential",
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=_CRED_PERSIST_LOCAL_MACHINE,
            UserName="lab-brain",
        )
        if not self._api().CredWriteW(ctypes.byref(credential), 0):
            raise SecretUnavailable(
                f"the credential store refused the write ({_last_error()})", code="write_failed"
            )

    def read(self, target: str) -> str | None:
        pointer = ctypes.POINTER(_CREDENTIAL)()
        api = self._api()
        if not api.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if _last_error() == _ERROR_NOT_FOUND:
                return None
            raise SecretUnavailable(f"the credential store refused the read ({_last_error()})")
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            api.CredFree(pointer)

    def delete(self, target: str) -> None:
        api = self._api()
        if api.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            return
        error = _last_error()
        if error != _ERROR_NOT_FOUND:
            raise SecretUnavailable(f"the credential store refused the delete ({error})")


def _last_error() -> int:
    return int(getattr(ctypes, "get_last_error")())  # noqa: B009 - Windows-only name


def default_credential_store() -> CredentialStore | None:
    store = WindowsCredentialStore()
    return store if store.available() else None


__all__ = [
    "ENV",
    "FILE",
    "MAX_KEY_LENGTH",
    "PLATFORM_STORE",
    "WINCRED",
    "CredentialStore",
    "DirectoryCredentialStore",
    "SecretError",
    "SecretRef",
    "SecretStore",
    "SecretUnavailable",
    "WindowsCredentialStore",
    "check_pasted_key",
    "default_credential_store",
    "fingerprint",
    "looks_like_credential",
    "parse_secret_ref",
    "redact",
]
