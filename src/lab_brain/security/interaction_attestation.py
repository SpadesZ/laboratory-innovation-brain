"""Interaction attestation: the web tier's signature that a research run came from a real request.

THE GAP THIS CLOSES. `011n` binds a WEB_SESSION run to a `session_audit_ref` and checks, for every
writer, that it names a live session of the run's own actor, an active cleared member of the
project. But a reference is not a secret: it is readable in `account_sessions` and printed in
reports. A database writer with only the application role's privileges can insert a WEB_SESSION
row naming a live session of that session's own actor, in a project they belong to, at a valid
time -- and `011n` accepts it. A valid session reference therefore does not, by itself, prove
that a run originated through an authenticated user interaction.

WHAT IS SIGNED. On an authenticated, CSRF-verified web request that starts or continues a run, the
web tier signs -- with an Ed25519 key it reads from the file `LAB_BRAIN_INTERACTION_SIGNING_KEY`
names -- a canonical JSON statement (RFC 8785 profile, `core.canonical_json`):

    kind, version             `lab-brain/research-interaction`, 1
    research_run_id, episode_id, trace_id, actor_id, project_id, session_audit_ref
    route, method             the request that started it: `POST /runs`, or
                              `POST /episodes/<episode_id>/continue` for this episode
    csrf_verified             true -- the statement is never built for a request that failed it
    signed_at                 ISO 8601 with offset, the web tier's clock
    nonce                     128 random bits, hex

The statement, its signature and the key id are stored on the run row (`011q`), never changed, and
the database CHECKS that the statement's fields are the row's own columns (its trace that of the
row's episode, its nonce used once): a valid signature for one run cannot be pasted onto another.

WHERE TRUST COMES FROM. The database cannot verify Ed25519, and must not be asked to: anything it
holds a database writer can rewrite. Verification is here, against public keys pinned OUTSIDE the
database, in the file `LAB_BRAIN_INTERACTION_AUTHORITIES` names -- one line per key,
`web:<label> ed25519:<base64 public key> [until=<ISO time with zone>]`, like the review
authorities (`security.reviewer_identity`). `until` retires a key without erasing it: statements
it signed before then still verify, none after. That is how keys rotate. With no key pinned,
nothing verifies; with no signing key, web runs are still recorded, at SESSION_RECORDED_UNVERIFIED
-- fail closed for the CLAIM, not for the product.

THE CLAIM LEVELS (`research.run_provenance.ClaimLevel`) are computed here, whenever a run or
report is shown -- never read from a stored field a writer could set:

    INTERACTION_VERIFIED         the signature verifies under a key pinned and valid at
                                 `signed_at`, and the statement names exactly this run, episode,
                                 trace, actor, project and session, by an allowed route.
    SESSION_RECORDED_UNVERIFIED  WEB_SESSION, but no statement, or one that does not verify here.
    OPERATOR_UNATTESTED          OPERATOR_WORKSPACE / OPERATOR_CLI.
    LEGACY_UNATTESTED            stored before session provenance existed.

WHAT REMAINS TRUSTED, PLAINLY. (1) Whoever holds the web tier's signing key, or controls the
deployment's configuration (the authorities file and the environment naming it), can make a
statement verify; that is the deployment's root of trust, outside a database writer's reach.
(2) A12 (account-security audit 2026-10-20, §7/§8): a database writer with migration rights can
change roles, memberships and account state directly. That is the operator trust root and an
OWNER DECISION; this module does not defeat it and does not claim to. (3) A stolen session cookie
used through the real web tier produces a verified interaction -- the request really was
authenticated by that cookie. That is an authentication risk, not a provenance one.

SECRETS. Nothing here writes or prints the private key, a session token or a `session_hash`; the
statement carries only the non-secret `session_audit_ref`.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from lab_brain.core.canonical_json import canonicalize
from lab_brain.research.run_provenance import (
    SESSION_AUDIT_REF,
    ClaimLevel,
    InteractionAttestation,
    RunBinding,
    RunOrigin,
)
from lab_brain.security.reviewer_identity import SigningKey

if TYPE_CHECKING:
    from lab_brain.research.report import EpisodeReport

#: The deployment setting naming the web tier's private signing key (PEM, PKCS8, Ed25519).
SIGNING_KEY_ENV = "LAB_BRAIN_INTERACTION_SIGNING_KEY"
#: The passphrase of that key, when it is encrypted.
PASSPHRASE_ENV = "LAB_BRAIN_INTERACTION_KEY_PASSPHRASE"
#: The deployment setting naming the pinned interaction public keys.
AUTHORITIES_ENV = "LAB_BRAIN_INTERACTION_AUTHORITIES"

STATEMENT_KIND = "lab-brain/research-interaction"
STATEMENT_VERSION = 1
#: The route that opens a run, and the one that continues an episode.
START_ROUTE = "/runs"
CONTINUE_ROUTE = "/episodes/{episode_id}/continue"
METHOD = "POST"

_FIELDS = frozenset(
    {
        "kind",
        "version",
        "research_run_id",
        "episode_id",
        "trace_id",
        "actor_id",
        "project_id",
        "session_audit_ref",
        "route",
        "method",
        "csrf_verified",
        "signed_at",
        "nonce",
    }
)
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_KEY_ID = re.compile(r"^ik:[0-9a-f]{32}$")


class InteractionUnverified(ValueError):
    """An interaction statement does not verify, or nothing it needs is configured."""


def interaction_key_id(public_key: str) -> str:
    """A pinned key's identity: `ik:` and the first 128 bits of SHA-256 over its raw bytes."""
    raw = base64.b64decode(public_key, validate=True)
    if len(raw) != 32:
        raise InteractionUnverified("not a base64 Ed25519 public key")
    return f"ik:{hashlib.sha256(raw).hexdigest()[:32]}"


# -- the statement ------------------------------------------------------------------------------


@dataclass(frozen=True)
class InteractionStatement:
    """The statement the web tier signs. `text()` is the exact bytes signed and stored."""

    research_run_id: str
    episode_id: str
    trace_id: str
    actor_id: str
    project_id: str
    session_audit_ref: str
    route: str
    method: str
    signed_at: dt.datetime
    nonce: str
    csrf_verified: bool = True
    kind: str = STATEMENT_KIND
    version: int = STATEMENT_VERSION

    def as_object(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "version": self.version,
            "research_run_id": self.research_run_id,
            "episode_id": self.episode_id,
            "trace_id": self.trace_id,
            "actor_id": self.actor_id,
            "project_id": self.project_id,
            "session_audit_ref": self.session_audit_ref,
            "route": self.route,
            "method": self.method,
            "csrf_verified": self.csrf_verified,
            "signed_at": self.signed_at.isoformat(),
            "nonce": self.nonce,
        }

    def text(self) -> str:
        return canonicalize(self.as_object())

    @property
    def binding(self) -> RunBinding:
        return RunBinding(
            research_run_id=self.research_run_id,
            episode_id=self.episode_id,
            trace_id=self.trace_id,
            actor_id=self.actor_id,
            project_id=self.project_id,
            session_audit_ref=self.session_audit_ref,
        )

    @classmethod
    def parse(cls, text: str) -> InteractionStatement:
        """The statement `text` encodes -- refused unless it is exactly its canonical form, so the
        bytes verified are the bytes stored and no two texts mean the same statement."""
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise InteractionUnverified(f"the interaction statement is not JSON: {exc}") from exc
        if not isinstance(data, dict) or set(data) != _FIELDS:
            raise InteractionUnverified("the interaction statement does not have its fields")
        strings = _FIELDS - {"version", "csrf_verified"}
        if any(not isinstance(data[k], str) for k in strings):
            raise InteractionUnverified("an interaction statement field is not text")
        if data["version"] != STATEMENT_VERSION or isinstance(data["version"], bool):
            raise InteractionUnverified(f"unknown interaction statement version {data['version']}")
        if data["kind"] != STATEMENT_KIND:
            raise InteractionUnverified(f"not an interaction statement: {data['kind']!r}")
        if data["csrf_verified"] is not True:
            raise InteractionUnverified("the statement does not say its request passed CSRF")
        if not _NONCE.match(data["nonce"]):
            raise InteractionUnverified("the statement's nonce is not 128 random bits in hex")
        if not SESSION_AUDIT_REF.match(data["session_audit_ref"]):
            raise InteractionUnverified("the statement names no session audit reference")
        try:
            signed_at = dt.datetime.fromisoformat(data["signed_at"])
        except ValueError as exc:
            raise InteractionUnverified(f"the statement's signing time: {exc}") from exc
        if signed_at.tzinfo is None:
            raise InteractionUnverified("the statement's signing time has no time zone")
        statement = cls(
            research_run_id=data["research_run_id"],
            episode_id=data["episode_id"],
            trace_id=data["trace_id"],
            actor_id=data["actor_id"],
            project_id=data["project_id"],
            session_audit_ref=data["session_audit_ref"],
            route=data["route"],
            method=data["method"],
            signed_at=signed_at,
            nonce=data["nonce"],
        )
        if statement.text() != text:
            raise InteractionUnverified("the interaction statement is not in its canonical form")
        return statement


# -- the pinned keys ----------------------------------------------------------------------------


@dataclass(frozen=True)
class InteractionAuthority:
    """One pinned web-tier key: its label, its public key, and when it was retired."""

    label: str
    public_key: str
    #: Statements signed at or after this time under this key do not verify (rotation).
    valid_until: dt.datetime | None = None

    @property
    def key_id(self) -> str:
        return interaction_key_id(self.public_key)


def parse_interaction_authorities(text: str) -> tuple[InteractionAuthority, ...]:
    """`web:<label> ed25519:<base64> [until=<ISO time>]` per line, `#` comments.

    A malformed line is refused, never skipped: a trust anchor that silently dropped a line would
    be a different trust anchor from the one its operator wrote."""
    found: list[InteractionAuthority] = []
    for number, line in enumerate(text.splitlines(), start=1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        parts = body.split()
        if (
            len(parts) not in (2, 3)
            or not parts[0].startswith("web:")
            or not parts[1].startswith("ed25519:")
            or (len(parts) == 3 and not parts[2].startswith("until="))
        ):
            raise InteractionUnverified(
                f"interaction authorities line {number} is not "
                "`web:<label> ed25519:<base64 key> [until=<ISO time>]`"
            )
        public_key = parts[1].removeprefix("ed25519:")
        try:
            interaction_key_id(public_key)
        except (ValueError, InteractionUnverified) as exc:
            raise InteractionUnverified(
                f"interaction authorities line {number} has no Ed25519 key"
            ) from exc
        until: dt.datetime | None = None
        if len(parts) == 3:
            try:
                until = dt.datetime.fromisoformat(parts[2].removeprefix("until="))
            except ValueError as exc:
                raise InteractionUnverified(
                    f"interaction authorities line {number}: {exc}"
                ) from exc
            if until.tzinfo is None:
                raise InteractionUnverified(
                    f"interaction authorities line {number}: `until` needs a time zone"
                )
        found.append(InteractionAuthority(parts[0], public_key, until))
    ids = [a.key_id for a in found]
    if len(set(ids)) != len(ids):
        raise InteractionUnverified("an interaction key is pinned twice")
    return tuple(found)


@dataclass(frozen=True)
class Claim:
    """A run's claim level, and -- in English, non-secret -- why it is not higher."""

    level: ClaimLevel
    reason: str
    key_id: str | None = None

    @property
    def authenticated_interaction(self) -> bool:
        """The only claim that may be described as an authenticated interaction."""
        return self.level is ClaimLevel.INTERACTION_VERIFIED


class InteractionTrust:
    """The deployment's pinned interaction keys and the verification that rests on them."""

    def __init__(self, authorities: Sequence[InteractionAuthority] = (), *, note: str = "") -> None:
        self._by_key: Mapping[str, InteractionAuthority] = {a.key_id: a for a in authorities}
        #: Why no key is pinned, when a configured file could not be read (shown, never secret).
        self._note = note

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> InteractionTrust:
        return cls(parse_interaction_authorities(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def configured_at(cls, path: str) -> InteractionTrust:
        """The keys in the file at `path`, or none for an empty path. A named file that cannot be
        read or parsed raises: a deployment that meant to pin a key must hear that it did not."""
        return cls() if not path.strip() else cls.from_file(path.strip())

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> InteractionTrust:
        return cls.configured_at((os.environ if env is None else env).get(AUTHORITIES_ENV, ""))

    @classmethod
    def for_display(cls, env: Mapping[str, str] | None = None) -> InteractionTrust:
        """As `from_environment`, but a broken authorities file pins nothing instead of raising:
        a page still renders, and every run on it reads as not verified (fail closed)."""
        try:
            return cls.from_environment(env)
        except (OSError, InteractionUnverified) as exc:
            return cls(note=f"the pinned interaction keys could not be read ({type(exc).__name__})")

    @property
    def configured(self) -> bool:
        return bool(self._by_key)

    @property
    def authorities(self) -> tuple[InteractionAuthority, ...]:
        return tuple(sorted(self._by_key.values(), key=lambda a: a.key_id))

    def verify(self, attestation: InteractionAttestation, binding: RunBinding) -> None:
        """Raise `InteractionUnverified` unless `attestation` is a statement a pinned key signed,
        while valid, for exactly `binding`, by an allowed route and method."""
        if not self._by_key:
            raise InteractionUnverified(
                "this deployment pins no interaction key"
                + (f": {self._note}" if self._note else f" ({AUTHORITIES_ENV})")
            )
        authority = self._by_key.get(attestation.key_id)
        if authority is None:
            raise InteractionUnverified(
                f"the statement is signed by {attestation.key_id}, which is not a pinned key"
            )
        statement = InteractionStatement.parse(attestation.statement)
        if statement.binding != binding:
            raise InteractionUnverified(
                "the statement names another run, episode, trace, actor, project or session"
            )
        allowed = {START_ROUTE, CONTINUE_ROUTE.format(episode_id=binding.episode_id)}
        if statement.method != METHOD or statement.route not in allowed:
            raise InteractionUnverified(
                f"the statement's request {statement.method} {statement.route} does not start or "
                "continue this run"
            )
        if authority.valid_until is not None and statement.signed_at >= authority.valid_until:
            raise InteractionUnverified(
                f"the statement is dated after key {authority.key_id} was retired "
                f"({authority.valid_until.isoformat()})"
            )
        try:
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(authority.public_key, validate=True)
            ).verify(
                base64.b64decode(attestation.signature, validate=True),
                attestation.statement.encode("utf-8"),
            )
        except (InvalidSignature, ValueError) as exc:
            raise InteractionUnverified("the statement's signature does not verify") from exc

    def claim(
        self,
        origin: str,
        binding: RunBinding | None,
        attestation: InteractionAttestation | None,
    ) -> Claim:
        """The claim level a run's record supports here, and why it is not higher."""
        run_origin = RunOrigin(origin)
        if run_origin is RunOrigin.LEGACY_UNATTESTED:
            return Claim(ClaimLevel.LEGACY_UNATTESTED, "stored before session provenance existed")
        if run_origin is not RunOrigin.WEB_SESSION:
            return Claim(ClaimLevel.OPERATOR_UNATTESTED, f"{run_origin.value} claims no sign-in")
        if binding is None:  # pragma: no cover - a WEB_SESSION record always names its session
            return Claim(ClaimLevel.SESSION_RECORDED_UNVERIFIED, "no session is named")
        if attestation is None:
            return Claim(
                ClaimLevel.SESSION_RECORDED_UNVERIFIED,
                "no interaction attestation is recorded for this run",
            )
        try:
            self.verify(attestation, binding)
        except InteractionUnverified as refused:
            return Claim(ClaimLevel.SESSION_RECORDED_UNVERIFIED, str(refused), attestation.key_id)
        return Claim(
            ClaimLevel.INTERACTION_VERIFIED,
            "signed by a pinned web-tier key on an authenticated, CSRF-verified request",
            attestation.key_id,
        )


def interaction_claim(report: EpisodeReport, trust: InteractionTrust | None = None) -> Claim:
    """The claim level of the run that wrote `report`, verified NOW against the pinned keys
    (`trust`, or this deployment's from the environment) -- never a level a stored field asserts."""
    trust = InteractionTrust.for_display() if trust is None else trust
    sp = report.session_provenance
    if sp is None:
        return Claim(ClaimLevel.LEGACY_UNATTESTED, "stored before session provenance existed")
    binding = (
        RunBinding(
            research_run_id=sp.research_run_id,
            episode_id=report.episode_id,
            trace_id=sp.trace_id,
            actor_id=sp.actor_id,
            project_id=sp.project_id,
            session_audit_ref=sp.session_audit_ref,
        )
        if sp.session_audit_ref is not None
        else None
    )
    attestation = (
        InteractionAttestation(
            sp.interaction_statement, sp.interaction_signature, sp.interaction_key_id
        )
        if sp.interaction_statement is not None
        and sp.interaction_signature is not None
        and sp.interaction_key_id is not None
        else None
    )
    return trust.claim(sp.origin, binding, attestation)


def audit_claims(
    connection: Any, trust: InteractionTrust, *, project_id: str | None = None
) -> dict[str, Claim]:
    """research run id -> its verified claim level, from the audit view `research_run_session_audit`
    (`011n`, extended by `011q`). The view says what the database can; this says what the pinned
    keys verify."""
    rows = connection.execute(
        "SELECT research_run_id, episode_id, trace_id, actor_id, project_id, run_origin,"
        " session_audit_ref, interaction_statement, interaction_signature, interaction_key_id"
        " FROM research_run_session_audit WHERE %s::text IS NULL OR project_id = %s",
        (project_id, project_id),
    ).fetchall()
    claims: dict[str, Claim] = {}
    for run_id, episode, trace, actor, project, origin, ref, text, signature, kid in rows:
        binding = (
            None
            if ref is None
            else RunBinding(str(run_id), str(episode), str(trace), str(actor), str(project), ref)
        )
        attestation = (
            None if text is None else InteractionAttestation(str(text), str(signature), str(kid))
        )
        claims[str(run_id)] = trust.claim(str(origin), binding, attestation)
    return claims


# -- signing, in the web tier only -------------------------------------------------------------


class InteractionSigner:
    """The web tier's private key. Never written to the database, a log, a page or an export."""

    def __init__(self, key: SigningKey, *, clock: Callable[[], dt.datetime] | None = None) -> None:
        self._key = key
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def __repr__(self) -> str:  # never the key
        return f"InteractionSigner(key_id={self.key_id!r})"

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> InteractionSigner | None:
        """The configured signing key, or None when none is configured (web runs are then
        recorded at SESSION_RECORDED_UNVERIFIED). A key that is named but unreadable raises: an
        operator who meant to sign must hear that nothing will be."""
        env = os.environ if env is None else env
        path = env.get(SIGNING_KEY_ENV, "").strip()
        if not path:
            return None
        passphrase = env.get(PASSPHRASE_ENV)
        try:
            key = SigningKey.load(path, passphrase.encode("utf-8") if passphrase else None)
        except (OSError, ValueError) as exc:
            raise InteractionUnverified(
                f"{SIGNING_KEY_ENV} names a file that is not a readable Ed25519 key "
                f"({type(exc).__name__})"
            ) from None
        return cls(key)

    @property
    def public_key(self) -> str:
        return self._key.public_key

    @property
    def key_id(self) -> str:
        return interaction_key_id(self._key.public_key)

    def sign(self, statement: InteractionStatement) -> InteractionAttestation:
        text = statement.text()
        return InteractionAttestation(
            statement=text, signature=self._key.sign(text.encode("utf-8")), key_id=self.key_id
        )

    def now(self) -> dt.datetime:
        return self._clock()


@dataclass(frozen=True)
class WebInteraction:
    """`research.run_provenance.InteractionAttestor` for one authenticated web request.

    Built by the web tier only after the request's session resolved and its CSRF token matched;
    `csrf_verified` is not a parameter, because there is no other kind of request to build it
    for."""

    route: str
    method: str
    signer: InteractionSigner

    def attest(self, binding: RunBinding) -> InteractionAttestation:
        return self.signer.sign(
            InteractionStatement(
                research_run_id=binding.research_run_id,
                episode_id=binding.episode_id,
                trace_id=binding.trace_id,
                actor_id=binding.actor_id,
                project_id=binding.project_id,
                session_audit_ref=binding.session_audit_ref,
                route=self.route,
                method=self.method,
                signed_at=self.signer.now(),
                nonce=secrets.token_hex(16),
            )
        )


def is_key_id(value: str) -> bool:
    return bool(_KEY_ID.match(value))


__all__ = [
    "AUTHORITIES_ENV",
    "CONTINUE_ROUTE",
    "METHOD",
    "PASSPHRASE_ENV",
    "SIGNING_KEY_ENV",
    "START_ROUTE",
    "STATEMENT_KIND",
    "STATEMENT_VERSION",
    "Claim",
    "ClaimLevel",
    "InteractionAuthority",
    "InteractionSigner",
    "InteractionStatement",
    "InteractionTrust",
    "InteractionUnverified",
    "WebInteraction",
    "audit_claims",
    "interaction_claim",
    "interaction_key_id",
    "is_key_id",
    "parse_interaction_authorities",
]
