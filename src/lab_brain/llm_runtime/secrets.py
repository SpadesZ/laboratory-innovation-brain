"""Model-provider credentials: referenced, never stored here, never shown.

The database holds a REFERENCE (`secret_ref`) and a FINGERPRINT (`****abcd`), never a credential:

    env:NAME                  the credential is the environment variable NAME of the process that
                              runs the workspace (the operator sets it; nothing here writes it)
    wincred:lab-brain/llm/ID  the credential is a generic credential in the operating system's
                              store (Windows Credential Manager, protected per user by the OS)

A credential typed into the workspace is written ONLY to the operating system's credential store.
Where there is none -- any platform but Windows, in this version -- storing one FAILS CLOSED: the
operator is told to set an environment variable and reference it. There is no plaintext file, no
reversible encoding and no fallback.

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
from dataclasses import dataclass
from typing import Any, Protocol

ENV = "env"
WINCRED = "wincred"

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_WINCRED_NAME = re.compile(r"^lab-brain/llm/[0-9a-f-]{36}$")

#: Shapes of provider keys. A reference that looks like one is refused: it IS the key.
_KEY_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
)


class SecretError(ValueError):
    """A secret reference is malformed, looks like a credential, or cannot be stored."""


class SecretUnavailable(RuntimeError):
    """The referenced credential cannot be read here, or no secure store is available."""


@dataclass(frozen=True)
class SecretRef:
    scheme: str
    name: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.name}"


def looks_like_credential(text: str) -> bool:
    return any(shape.search(text) for shape in _KEY_SHAPES)


def parse_secret_ref(text: str) -> SecretRef:
    """`env:NAME` or `wincred:lab-brain/llm/<uuid>`; anything else is refused -- a pasted key
    above all."""
    value = text.strip()
    if looks_like_credential(value):
        raise SecretError(
            "that looks like a credential itself, not a reference to one; it was not saved"
        )
    scheme, _, name = value.partition(":")
    if scheme == ENV and _ENV_NAME.match(name):
        return SecretRef(ENV, name)
    if scheme == WINCRED and _WINCRED_NAME.match(name):
        return SecretRef(WINCRED, name)
    raise SecretError("a secret reference is env:VARIABLE_NAME")


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
    """A secure store the OPERATING SYSTEM protects. Never a file this program writes."""

    name: str

    def available(self) -> bool: ...

    def write(self, target: str, secret: str) -> None: ...

    def read(self, target: str) -> str | None: ...

    def delete(self, target: str) -> None: ...


#: "Use this platform's own credential store" -- distinct from `None`, which means "none at all".
PLATFORM_STORE: Any = object()


class SecretStore:
    """Resolves references, and stores a typed-in credential only where the OS protects it.

    `credentials` is `PLATFORM_STORE` by default (Windows Credential Manager where there is one),
    or an explicit store, or `None` for NO credential store: never silently the platform's."""

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

    def resolve(self, ref: SecretRef) -> str:
        if ref.scheme == ENV:
            value = self._environ.get(ref.name)
            if not value:
                raise SecretUnavailable(
                    f"the environment variable {ref.name} is not set for this workspace"
                )
            return value
        if ref.scheme == WINCRED:
            if self._credentials is None or not self._credentials.available():
                raise SecretUnavailable("this machine has no operating-system credential store")
            stored = self._credentials.read(ref.name)
            if not stored:
                raise SecretUnavailable(f"the credential store holds nothing under {ref}")
            return stored
        raise SecretUnavailable(f"unknown secret scheme {ref.scheme!r}")

    def store(self, secret: str) -> SecretRef:
        """Put a typed-in credential in the OS store. FAILS CLOSED where there is none."""
        if not secret.strip():
            raise SecretError("the credential is empty")
        if self._credentials is None or not self._credentials.available():
            raise SecretUnavailable(
                "no secure credential store is available on this machine, so a typed-in "
                "credential cannot be kept; set an environment variable for the workspace and "
                "reference it as env:NAME"
            )
        target = f"lab-brain/llm/{uuid.uuid4()}"
        self._credentials.write(target, secret.strip())
        return SecretRef(WINCRED, target)

    def forget(self, ref: SecretRef) -> None:
        if (
            ref.scheme == WINCRED
            and self._credentials is not None
            and self._credentials.available()
        ):
            self._credentials.delete(ref.name)


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
            raise SecretUnavailable(f"the credential store refused the write ({_last_error()})")

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
    "PLATFORM_STORE",
    "WINCRED",
    "CredentialStore",
    "SecretError",
    "SecretRef",
    "SecretStore",
    "SecretUnavailable",
    "WindowsCredentialStore",
    "default_credential_store",
    "fingerprint",
    "looks_like_credential",
    "parse_secret_ref",
    "redact",
]
