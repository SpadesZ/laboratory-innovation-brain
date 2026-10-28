"""How a research run was started, and the session a signed-in person started it in (`011n`).

Every research run declares its ORIGIN; nothing defaults it:

    WEB_SESSION         the workspace with accounts: a person signed in. The run names the session
                        by its `session_audit_ref` -- a random reference the database mints for each
                        session, separate from the cookie's token and from `session_hash` (the
                        token's SHA-256, the key a session is resolved by). Knowing a reference
                        signs nobody in; it only names one `account_sessions` row for audit.
    OPERATOR_WORKSPACE  the workspace without accounts, started by the operator for one actor.
    OPERATOR_CLI        `lab-brain research run`, or any process that calls the research service
                        with database credentials. It attests no sign-in.
    LEGACY_UNATTESTED   a run stored before `011n`. Read back, never written.

The database holds the rules for every writer: a WEB_SESSION run's session is its own actor's,
active when the run began, the actor an active member of the project cleared for the question --
whatever the system role -- and the origin and reference never change afterwards. Only WEB_SESSION
runs are evidence of an authenticated person's research.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: The form `011n` mints: 'sar:' and 32 lowercase hex digits.
SESSION_AUDIT_REF = re.compile(r"^sar:[0-9a-f]{32}$")


class RunOrigin(StrEnum):
    WEB_SESSION = "WEB_SESSION"
    OPERATOR_WORKSPACE = "OPERATOR_WORKSPACE"
    OPERATOR_CLI = "OPERATOR_CLI"
    LEGACY_UNATTESTED = "LEGACY_UNATTESTED"


class ProvenanceRefused(ValueError):
    """A run's provenance that is not one: a reference without a session origin, or the reverse."""


@dataclass(frozen=True)
class RunProvenance:
    """A run's origin and, for a WEB_SESSION run only, its session's audit reference."""

    origin: RunOrigin
    session_audit_ref: str | None = None

    def __post_init__(self) -> None:
        origin = RunOrigin(self.origin)
        object.__setattr__(self, "origin", origin)
        if origin is RunOrigin.WEB_SESSION:
            if self.session_audit_ref is None or not SESSION_AUDIT_REF.match(
                self.session_audit_ref
            ):
                raise ProvenanceRefused(
                    "a run started in a signed-in session names that session's audit reference"
                )
        elif self.session_audit_ref is not None:
            raise ProvenanceRefused(f"a {origin.value} run names no session")

    @classmethod
    def web_session(cls, session_audit_ref: str) -> RunProvenance:
        return cls(RunOrigin.WEB_SESSION, session_audit_ref)

    @classmethod
    def operator_workspace(cls) -> RunProvenance:
        return cls(RunOrigin.OPERATOR_WORKSPACE)

    @classmethod
    def operator_cli(cls) -> RunProvenance:
        return cls(RunOrigin.OPERATOR_CLI)

    @property
    def attested(self) -> bool:
        """Whether the run is evidence of a person's authenticated session."""
        return self.origin is RunOrigin.WEB_SESSION


def provenance_line(
    provenance: RunProvenance,
    *,
    actor_id: str,
    project_id: str,
    research_run_id: str,
    trace_id: str,
) -> str:
    """The report's provenance sentence for how the run was started. Non-secret only."""
    who = (
        f"by `{actor_id}` in project `{project_id}` (research run `{research_run_id}`, "
        f"trace `{trace_id}`)"
    )
    if provenance.origin is RunOrigin.WEB_SESSION:
        return (
            f"Started {who} in a signed-in workspace session (WEB_SESSION); session audit "
            f"reference `{provenance.session_audit_ref}` -- a non-secret reference to the "
            "session record, never its sign-in token."
        )
    if provenance.origin is RunOrigin.OPERATOR_WORKSPACE:
        return (
            f"Started {who} through the workspace without accounts (OPERATOR_WORKSPACE); no "
            "signed-in session is attested."
        )
    if provenance.origin is RunOrigin.OPERATOR_CLI:
        return (
            f"Started {who} from the operator's command line or a direct caller of the research "
            "service (OPERATOR_CLI); no signed-in session is attested."
        )
    return (
        f"Started {who} before session provenance was recorded (LEGACY_UNATTESTED); no "
        "signed-in session is attested."
    )


__all__ = [
    "SESSION_AUDIT_REF",
    "ProvenanceRefused",
    "RunOrigin",
    "RunProvenance",
    "provenance_line",
]
