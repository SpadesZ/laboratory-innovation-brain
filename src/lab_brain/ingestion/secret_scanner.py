"""Secret scanning before immutable ingest — SEC-003, §14.5.

    Watcher 在 immutable ingest **前**先做 secret scanning；疑似 credential 不得直接永久封存，
    需 quarantine/redaction policy（SEC-003）。

THE ORDERING IS THE REQUIREMENT. §17.22 states it as a pipeline::

    receive -> SECRET_SCAN -> (quarantine | RAW_STORE) -> parsing stages

and the failure this prevents is specific: once bytes are in a content-addressed, append-only
store, a leaked credential is *permanently* there. Scanning afterwards can only report it. So the
scan runs before the promotion that makes bytes addressable, and a suspected credential takes a
different branch entirely rather than being stored-then-flagged.

WHAT A TIMEOUT MEANS. A scan that did not finish is not a scan that passed. §17.22 is explicit
that a file failing *or timing out* goes to quarantine and surfaces as ``BLOCKED``, not
``FAILED`` -- the distinction matters to a user, because BLOCKED is a policy outcome they can act
on and FAILED invites a retry that will do the same thing.

WHAT THIS IS NOT. A complete secret scanner. The patterns below cover the shapes that appear in a
lab's documents -- provider API keys, private key blocks, connection strings with inline
passwords -- and a real deployment would put a maintained scanner behind this same seam. The
contract this module fixes is the *ordering* and the *branch*, which is what SEC-003 governs;
improving detection later changes no caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lab_brain.core.models.enums import SecretScanStatus

SCANNER_ID = "pattern_scanner"
SCANNER_VERSION = "1.0.0"

#: Redaction marker. Fixed text rather than a per-finding placeholder so a redacted artifact's
#: hash is a function of the original bytes and the findings, and is reproducible.
REDACTION = "[REDACTED:SEC-003]"


@dataclass(frozen=True)
class SecretPattern:
    name: str
    pattern: re.Pattern[str]
    #: Whether a match may be redacted in place and the derivative admitted. A private key block
    #: cannot -- a key with its middle removed is still a disclosed key header and the file's
    #: purpose was to carry it. An inline password in a connection string can.
    redactable: bool


_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern(
        name="private_key_block",
        pattern=re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        redactable=False,
    ),
    SecretPattern(
        name="aws_access_key_id",
        pattern=re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        redactable=True,
    ),
    SecretPattern(
        name="generic_api_key_assignment",
        pattern=re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\b"
            r"\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?"
        ),
        redactable=True,
    ),
    SecretPattern(
        name="connection_string_password",
        pattern=re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:@/]+:([^\s@/]{6,})@"),
        redactable=True,
    ),
    SecretPattern(
        name="bearer_token",
        pattern=re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.=]{20,}"),
        redactable=True,
    ),
)


@dataclass(frozen=True)
class SecretFinding:
    """One suspected credential. Carries an offset, never the matched text.

    Putting the secret into the finding would copy it into logs, error records and the two-tier
    disclosure surface -- re-leaking it through the machinery built to report it.
    """

    pattern_name: str
    start_offset: int
    end_offset: int
    redactable: bool


@dataclass(frozen=True)
class SecretScanResult:
    status: SecretScanStatus
    findings: tuple[SecretFinding, ...]
    scanner_id: str = SCANNER_ID
    scanner_version: str = SCANNER_VERSION
    #: Set when every finding was redactable. This, not the original, is what may be stored.
    redacted_bytes: bytes | None = None

    @property
    def is_clean(self) -> bool:
        return self.status is SecretScanStatus.CLEAN

    @property
    def may_reach_normal_storage(self) -> bool:
        """SEC-003's branch. Only CLEAN or REDACTED bytes reach the permanent normal store."""
        return self.status in {SecretScanStatus.CLEAN, SecretScanStatus.REDACTED}


class SecretScanTimeout(RuntimeError):
    """The scan did not complete. Routed to quarantine, not to retry (§17.22)."""


class SecretScanner:
    """Scans bytes before they become an artifact."""

    scanner_id = SCANNER_ID
    scanner_version = SCANNER_VERSION

    def __init__(self, patterns: tuple[SecretPattern, ...] = _PATTERNS) -> None:
        self._patterns = patterns

    def scan(self, data: bytes) -> SecretScanResult:
        """Scan ``data`` and decide which branch it takes.

        Undecodable bytes are CLEAN, not an error: a binary simulation output has no text to hold
        a credential in the shapes this scanner knows, and failing it would block the most common
        artifact in the lab. A binary-aware scanner behind this seam would change that without
        changing the branch.
        """
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return SecretScanResult(status=SecretScanStatus.CLEAN, findings=())

        findings: list[SecretFinding] = []
        for spec in self._patterns:
            for match in spec.pattern.finditer(text):
                findings.append(
                    SecretFinding(
                        pattern_name=spec.name,
                        start_offset=match.start(),
                        end_offset=match.end(),
                        redactable=spec.redactable,
                    )
                )

        if not findings:
            return SecretScanResult(status=SecretScanStatus.CLEAN, findings=())

        findings.sort(key=lambda finding: finding.start_offset)
        if not all(finding.redactable for finding in findings):
            # One unredactable finding quarantines the whole file. Redacting the rest and storing
            # it would store a file whose reason for existing was the part that cannot be removed.
            return SecretScanResult(status=SecretScanStatus.QUARANTINED, findings=tuple(findings))

        return SecretScanResult(
            status=SecretScanStatus.REDACTED,
            findings=tuple(findings),
            redacted_bytes=self._redact(text, findings),
        )

    def _redact(self, text: str, findings: list[SecretFinding]) -> bytes:
        """Replace each finding with a fixed marker, back to front so offsets stay valid."""
        out = text
        for finding in sorted(findings, key=lambda f: f.start_offset, reverse=True):
            out = out[: finding.start_offset] + REDACTION + out[finding.end_offset :]
        return out.encode("utf-8")


__all__ = [
    "REDACTION",
    "SCANNER_ID",
    "SCANNER_VERSION",
    "SecretFinding",
    "SecretPattern",
    "SecretScanResult",
    "SecretScanTimeout",
    "SecretScanner",
]
