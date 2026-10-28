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
whatever the system role -- and the origin and reference never change afterwards.

WHAT A SESSION REFERENCE DOES NOT PROVE (`011q`). A reference is not secret: anyone who can read
`account_sessions`, or a report, can copy one, and a database writer with only the application
role's privileges can insert a WEB_SESSION row naming a live session of that session's own actor
at a valid time. `011n` accepts such a row. So WEB_SESSION with a valid reference is recorded as
SESSION_RECORDED_UNVERIFIED, never as an authenticated interaction. The stronger claim needs an
INTERACTION ATTESTATION (`security.interaction_attestation`): a statement the web tier signs, with
an Ed25519 key only it holds, on the authenticated, CSRF-verified request that starts or continues
the run -- binding this run, its episode and trace, actor, project, session reference, route,
method and a nonce. The public keys are pinned OUTSIDE the database. A database writer can store
such a statement, but cannot make one verify. The claim levels (`ClaimLevel`):

    INTERACTION_VERIFIED         the signature verifies under a key pinned for its signing time,
                                 and the statement names exactly this run. The only level that may
                                 be described as "originated from an authenticated interaction".
    SESSION_RECORDED_UNVERIFIED  WEB_SESSION with a valid reference, but no attestation, or one that
                                 does not verify here (including: no key pinned in this deployment).
    OPERATOR_UNATTESTED          OPERATOR_WORKSPACE or OPERATOR_CLI: no sign-in is claimed.
    LEGACY_UNATTESTED            a run stored before `011n`.

THE TRUST ROOT THAT REMAINS. Whoever holds the web tier's signing key, or controls the
deployment's configuration (which keys are pinned), can make a statement verify. A database writer
with migration rights can still change roles and state directly (A12 in the account-security
audit): that is the operator's trust root and the Owner's decision, which this does not defeat. A
stolen session cookie used through the real web tier yields a verified interaction: that is an
authentication risk, not a provenance one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

#: The form `011n` mints: 'sar:' and 32 lowercase hex digits.
SESSION_AUDIT_REF = re.compile(r"^sar:[0-9a-f]{32}$")


class RunOrigin(StrEnum):
    WEB_SESSION = "WEB_SESSION"
    OPERATOR_WORKSPACE = "OPERATOR_WORKSPACE"
    OPERATOR_CLI = "OPERATOR_CLI"
    LEGACY_UNATTESTED = "LEGACY_UNATTESTED"


class ProvenanceRefused(ValueError):
    """A run's provenance that is not one: a reference without a session origin, or the reverse."""


class ClaimLevel(StrEnum):
    """How much a run's record proves about the way it was started -- never more than it can."""

    INTERACTION_VERIFIED = "INTERACTION_VERIFIED"
    SESSION_RECORDED_UNVERIFIED = "SESSION_RECORDED_UNVERIFIED"
    OPERATOR_UNATTESTED = "OPERATOR_UNATTESTED"
    LEGACY_UNATTESTED = "LEGACY_UNATTESTED"


@dataclass(frozen=True)
class RunBinding:
    """The row fields an interaction attestation binds: the run and everything it is tied to."""

    research_run_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    project_id: str
    session_audit_ref: str


@dataclass(frozen=True)
class InteractionAttestation:
    """A signed interaction statement as stored on the run (`011q`): the exact canonical text
    signed, its base64 Ed25519 signature, and the id of the key that signed it. Nothing secret:
    no private key, session token or `session_hash` is part of it."""

    statement: str
    signature: str
    key_id: str


class InteractionAttestor(Protocol):
    """Signs, for the request in hand, the statement binding the run the service is starting.

    Held only by the web tier, built only on an authenticated, CSRF-verified request; the research
    service calls it once, when it knows the run's id, episode and trace, and stores the result
    with the run in the same INSERT."""

    def attest(self, binding: RunBinding) -> InteractionAttestation: ...


@dataclass(frozen=True)
class RunProvenance:
    """A run's origin and, for a WEB_SESSION run only, its session's audit reference -- and, when
    the web tier can sign, the attestor that signs the run's interaction statement."""

    origin: RunOrigin
    session_audit_ref: str | None = None
    #: Present only on a WEB_SESSION provenance built by the web tier with a signing key. Not part
    #: of equality: two provenances naming the same session are the same provenance.
    attestor: InteractionAttestor | None = field(default=None, compare=False, repr=False)

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
        if self.attestor is not None and origin is not RunOrigin.WEB_SESSION:
            raise ProvenanceRefused(f"a {origin.value} run has no web interaction to attest")

    @classmethod
    def web_session(
        cls, session_audit_ref: str, attestor: InteractionAttestor | None = None
    ) -> RunProvenance:
        return cls(RunOrigin.WEB_SESSION, session_audit_ref, attestor)

    @classmethod
    def operator_workspace(cls) -> RunProvenance:
        return cls(RunOrigin.OPERATOR_WORKSPACE)

    @classmethod
    def operator_cli(cls) -> RunProvenance:
        return cls(RunOrigin.OPERATOR_CLI)

    @property
    def attested(self) -> bool:
        """Whether the run names a signed-in session (`011n`). NOT, by itself, evidence that the
        run originated from an authenticated interaction: only a verified interaction attestation
        is (`ClaimLevel.INTERACTION_VERIFIED`)."""
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
        # Deliberately no claim of authentication: whether the run originated from an
        # authenticated interaction is the interaction attestation's claim level, verified when
        # the report is shown (`security.interaction_attestation`), never this stored sentence.
        return (
            f"Recorded {who} with origin WEB_SESSION, naming session audit reference "
            f"`{provenance.session_audit_ref}` -- a non-secret reference to the session record, "
            "never its sign-in token. A session reference alone does not show an authenticated "
            "interaction; the session provenance block states the verified claim level."
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
    "ClaimLevel",
    "InteractionAttestation",
    "InteractionAttestor",
    "ProvenanceRefused",
    "RunBinding",
    "RunOrigin",
    "RunProvenance",
    "provenance_line",
]
