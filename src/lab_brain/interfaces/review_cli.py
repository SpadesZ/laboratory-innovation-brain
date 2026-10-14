"""`lab-brain review`: a person answers DIAGNOSTIC_WARRANT reviews (Causal Warrant Gate).

    list      the project's outstanding warrant reviews, oldest first
    show      one review's packet: what was claimed, what was observed, what the rivals said
    resolve   APPROVED (the outcome does bear on the mechanism as claimed) or REJECTED, with a
              rationale, SIGNED with the reviewer's enrolled key (`--key`) -- written atomically
              by `diagnostic_warrant_resolve`; with APPROVED, `--is-class` also states that the
              hypothesis IS a declared class
    expire    close the project's overdue reviews through OPS-002's declared expiry path
              (`ReviewExpiryProcessor`), so the episode may ask again; an expired question is
              closed by expiry, never answered late (`research run` sweeps the same way first)

    keygen    a new Ed25519 private key, written owner-only, and its public key printed -- for a
              reviewer to have enrolled, or for an authority to pin
    enrol     an AUTHORITY enrols a reviewer's public key for one person in one project, signing
              it with the authority key the deployment pins (`LAB_BRAIN_REVIEW_AUTHORITIES`)
    revoke    an authority revokes an enrolment; answers signed from then on do not count
    keys      the project's enrolled reviewer keys, and whether each verifies here

WHO ANSWERED IS PROVED, NOT CLAIMED (V1.1). `--actor` names who you say you are; the answer counts
only if it is signed with a key an authority enrolled for that person in that project, and the
signature is checked every time the answer is read. A database writer can write an answer row as
anyone; it cannot make one that verifies.

THE DOMAIN'S ATTRIBUTION IS PART OF THE PACKET. When the observed outcome is a declared class's
signature, `show` says so: the recorded failure confirmed a mechanism on exactly such an outcome,
and the reviewer must see that the domain attributes it elsewhere. Approving the link does not make
the hypothesis that class -- only `--is-class` does, and the confirmation rule reads nothing else.

WHAT A REVIEWER IS ASKED. Whether one observed outcome bears on one hypothesis's mechanism the way
its author declared: for SUPPORTS, that the mechanism produces it and the rivals do not; for
CONTRADICTS, that the mechanism cannot. The packet shows the declared effect, the outcome observed,
the check that observed it, and every rival's declared effect on the same observable -- a rival
affirming the same outcome is the first thing that makes a SUPPORTS non-discriminating. It shows
the hypothesis's author for accountability, never as a reason: the answer is about the link.

WHO MAY ANSWER. An active human member of the project with an enrolled, unrevoked key; never the
person who ran the episode or the hypothesis's author. The database refuses anyone else, and
refuses a second answer to the same review. A grant warrants exactly one relation and nothing
beyond it. Resuming the episode afterwards is the existing continuation path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import uuid
from collections.abc import Callable, Mapping
from importlib.metadata import entry_points
from pathlib import Path
from types import MappingProxyType
from typing import Any, TextIO

from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.models.reviewer import is_public_key, key_id
from lab_brain.core.models.warrant import DiagnosticDeclarationSet
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore, WarrantStoreError
from lab_brain.core.review_expiry import ReviewExpiryProcessor
from lab_brain.research.vertical import ENTRY_POINT_GROUP
from lab_brain.security.reviewer_identity import (
    AUTHORITIES_ENV,
    IdentityUnverified,
    ReviewerSigner,
    ReviewerTrust,
    SigningKey,
    passphrase_from,
    sign_enrolment,
    sign_revocation,
)


def add_review_parser(sub: Any) -> None:
    review = sub.add_parser("review", help="answer diagnostic warrant reviews")
    actions = review.add_subparsers(dest="review_command", required=True)
    listed = actions.add_parser("list", help="outstanding diagnostic warrant reviews")
    shown = actions.add_parser("show", help="one review's packet")
    shown.add_argument("review_id")
    expired = actions.add_parser("expire", help="close overdue reviews so they may be asked again")
    keys = actions.add_parser("keys", help="the project's enrolled reviewer keys")
    generated = actions.add_parser("keygen", help="a new Ed25519 key for a reviewer or authority")
    generated.add_argument("--out", required=True, help="where to write the private key (new file)")
    enrolled = actions.add_parser("enrol", help="(authority) enrol a reviewer's public key")
    enrolled.add_argument("--reviewer", required=True, help="the person the key answers for")
    enrolled.add_argument("--public-key", required=True, help="their key, as `keygen` printed it")
    enrolled.add_argument("--authority-key", required=True, help="the authority's private key")
    revoked = actions.add_parser("revoke", help="(authority) revoke a reviewer key enrolment")
    revoked.add_argument("enrolment_id")
    revoked.add_argument("--reason", required=True)
    revoked.add_argument("--authority-key", required=True, help="the authority's private key")
    resolved = actions.add_parser("resolve", help="answer one review")
    resolved.add_argument("review_id")
    resolved.add_argument(
        "--key", required=True, help="your enrolled reviewer private key; it signs the answer"
    )
    resolved.add_argument("--outcome", required=True, choices=("APPROVED", "REJECTED"))
    resolved.add_argument("--rationale", required=True)
    resolved.add_argument(
        "--rival",
        action="append",
        default=[],
        help="a rival hypothesis id the outcome was weighed against (repeatable)",
    )
    resolved.add_argument(
        "--is-class",
        default=None,
        help=(
            "with APPROVED: state that the hypothesis IS this declared class (its dds: reference, "
            "as `review show` prints it) -- e.g. a paraphrase of a catalog mechanism"
        ),
    )
    for parser in (listed, shown, resolved, expired, keys, enrolled, revoked):
        parser.add_argument("--project", required=True)
        parser.add_argument(
            "--actor",
            required=True,
            help="who you are; for enrol and revoke, the authority --authority-key is pinned for",
        )


def _member(connection: Any, actor_id: str, project_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM actors a JOIN project_memberships m ON m.actor_id = a.actor_id"
        " WHERE a.actor_id = %s AND a.active AND a.actor_type = 'HUMAN'"
        " AND m.project_id = %s AND m.active",
        (actor_id, project_id),
    ).fetchone()
    return row is not None


def _installed_declarations() -> tuple[DiagnosticDeclarationSet, ...]:
    """Every diagnostic declaration set the installed product verticals register.

    Built with no backends: a vertical's declarations are data, and reading them executes nothing.
    A vertical that cannot be built this way contributes nothing rather than failing the packet.
    """
    found: list[DiagnosticDeclarationSet] = []
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            vertical = entry.load()(
                outputs=None, jobs=None, broker=None, now=lambda: dt.datetime.now(dt.UTC)
            )
        except Exception:  # pragma: no cover - a vertical that needs its backends to build
            continue
        found.extend(vertical.declaration_sets)
    return tuple(found)


def _attribution(link: tuple[str, str, str, str], mechanism: str) -> list[str]:
    lines = []
    for declarations in _installed_declarations():
        owner = declarations.signature_of(link)
        if owner is None:
            continue
        ref = declarations.domain_ref(owner)
        lines.append(
            f"  domain says  {link[3]} on {link[0]} is the declared signature of "
            f"'{owner.mechanism}' ({ref})"
        )
        if owner.mechanism != mechanism:
            lines.append(
                "               approving the link does not make this hypothesis that mechanism; "
                f"if it IS, say so with --is-class {ref}"
            )
    return lines


def _packet(connection: Any, project_id: str, relation_id: str) -> list[str]:
    relation = connection.execute(
        "SELECT r.relation_type, r.to_entity_id, r.from_entity_id, r.attributes,"
        " h.mechanism, h.statement, h.inference_provenance_id"
        " FROM relation_judgments r JOIN hypotheses h ON h.hypothesis_id = r.to_entity_id"
        " WHERE r.project_id = %s AND r.relation_id = %s",
        (project_id, relation_id),
    ).fetchone()
    if relation is None:
        return [f"  relation {relation_id} not found"]
    kind, hypothesis_id, observation_id, attributes, mechanism, statement, inference = relation
    prediction = connection.execute(
        "SELECT observable_ref, outcome_space_id, outcome_space_version, expected_outcome"
        " FROM predictions WHERE prediction_id = %s",
        (attributes.get("prediction_id"),),
    ).fetchone()
    lines = [
        f"  hypothesis   {hypothesis_id}",
        f"  mechanism    {mechanism}",
        f"  statement    {statement}",
        f"  authored by  {inference or 'a person'} (accountability, not a reason)",
        f"  claims       observing {attributes.get('outcome')} {kind} it",
        f"  observed     {observation_id} by {attributes.get('capability_id')} "
        f"(run {attributes.get('run_id')})",
    ]
    if prediction is None:
        return lines
    observable, space, version, outcome = prediction
    lines.append(f"  observable   {observable} in {space}@{version}")
    lines.extend(
        _attribution((str(observable), str(space), str(version), str(outcome)), str(mechanism))
    )
    rivals = connection.execute(
        "SELECT p.hypothesis_id, h.mechanism, p.expected_outcome,"
        " p.relation_effect_if_observed -> 0 ->> 'relation_type'"
        " FROM predictions p JOIN hypotheses h ON h.hypothesis_id = p.hypothesis_id"
        " WHERE h.hypothesis_set_id = (SELECT hypothesis_set_id FROM hypotheses"
        "   WHERE hypothesis_id = %s)"
        " AND p.hypothesis_id <> %s AND p.observable_ref = %s"
        " ORDER BY p.hypothesis_id, p.expected_outcome",
        (hypothesis_id, hypothesis_id, observable),
    ).fetchall()
    if not rivals:
        lines.append("  rivals       none declares anything about this observable")
    for rival_id, rival_mechanism, rival_outcome, effect in rivals:
        marker = (
            "  <- also affirms what was observed"
            if (rival_outcome == outcome and effect in ("SUPPORTS", "PREDICTS"))
            else ""
        )
        lines.append(
            f"  rival        {rival_id} ({rival_mechanism}): {rival_outcome} {effect}{marker}"
        )
    return lines


def run_keygen(args: argparse.Namespace, *, out: TextIO, env: Mapping[str, str]) -> int:
    """A new key, never over an existing file. Needs no database: nothing is recorded."""
    key = SigningKey.generate()
    try:
        key.save(args.out, passphrase_from(env))
    except FileExistsError:
        print(f"lab-brain: {args.out} exists; a key is never overwritten", file=out)
        return 1
    print(f"private key  {Path(args.out).resolve()} (keep it; nobody else needs it)", file=out)
    print(f"public key   {key.public_key}", file=out)
    print(f"key id       {key.key_id}", file=out)
    print(
        f"  as a reviewer: give the public key to a review authority to enrol. As an authority: "
        f"pin `<act:you> ed25519:{key.public_key}` in the file {AUTHORITIES_ENV} names.",
        file=out,
    )
    return 0


def _load_key(path: str, env: Mapping[str, str]) -> SigningKey:
    return SigningKey.load(path, passphrase_from(env))


def _authority(
    args: argparse.Namespace, trust: ReviewerTrust, env: Mapping[str, str]
) -> SigningKey:
    key = _load_key(args.authority_key, env)
    pinned = trust.authority(key.key_id)
    if pinned is None or pinned.actor_id != args.actor:
        raise IdentityUnverified(
            f"{key.key_id} is not pinned as {args.actor}'s review authority in this deployment "
            f"({AUTHORITIES_ENV})"
        )
    return key


def _keys(
    store: SqlDiagnosticWarrantStore, project_id: str, trust: ReviewerTrust, out: TextIO
) -> int:
    enrolments = store.enrolments(project_id)
    if not enrolments:
        print(f"No reviewer key is enrolled in {project_id}.", file=out)
    for e in enrolments:
        revoked = store.revocations(project_id, e.enrolment_id)
        try:
            trust.verify_enrolment(e)
            status = "verifies"
        except IdentityUnverified as refused:
            status = f"DOES NOT VERIFY: {refused}"
        if revoked:
            status = f"revoked from {revoked[0].effective_at.isoformat()} ({revoked[0].reason})"
        print(
            f"{e.enrolment_id}  {e.actor_id}  {e.key_id}  by {e.authority_actor_id}  {status}",
            file=out,
        )
    return 0


def _signer(
    store: SqlDiagnosticWarrantStore,
    args: argparse.Namespace,
    trust: ReviewerTrust,
    env: Mapping[str, str],
) -> ReviewerSigner:
    """The answering person's enrolled key, checked here before anything is written."""
    key = _load_key(args.key, env)
    for enrolment in store.enrolments(args.project, args.actor):
        if enrolment.public_key != key.public_key:
            continue
        if store.revocations(args.project, enrolment.enrolment_id):
            raise IdentityUnverified(f"{key.key_id} was revoked; it answers nothing")
        trust.verify_enrolment(enrolment)
        return ReviewerSigner(actor_id=args.actor, enrolment_id=enrolment.enrolment_id, key=key)
    raise IdentityUnverified(
        f"{key.key_id} is not enrolled for {args.actor} in {args.project}; a review authority "
        "enrols it (`lab-brain review enrol`)"
    )


def run_review(
    args: argparse.Namespace,
    connection: Any,
    *,
    out: TextIO,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    mint: Callable[[str], str] = lambda kind: f"{kind}:{uuid.uuid4()}",
    trust: ReviewerTrust | None = None,
    env: Mapping[str, str] = MappingProxyType({}),
) -> int:
    trust = trust or ReviewerTrust()
    store = SqlDiagnosticWarrantStore(connection)
    if args.review_command in ("enrol", "revoke"):
        # An authority need not be a member of the project; its pinned key is its standing.
        try:
            authority = _authority(args, trust, env)
            if args.review_command == "enrol":
                if not is_public_key(args.public_key):
                    raise IdentityUnverified("--public-key is not a base64 Ed25519 public key")
                enrolment = sign_enrolment(
                    authority,
                    authority_actor_id=args.actor,
                    enrolment_id=mint("enr"),
                    project_id=args.project,
                    actor_id=args.reviewer,
                    public_key=args.public_key,
                    enrolled_at=now(),
                )
                trust.verify_enrolment(enrolment)
                store.enrol(enrolment)
                print(
                    f"enrolled {key_id(args.public_key)} for {args.reviewer} in {args.project} "
                    f"({enrolment.enrolment_id})",
                    file=out,
                )
                return 0
            target = store.enrolment(args.project, args.enrolment_id)
            if target is None:
                raise IdentityUnverified(f"no enrolment {args.enrolment_id} in {args.project}")
            revocation = sign_revocation(
                authority,
                authority_actor_id=args.actor,
                revocation_id=mint("rvk"),
                enrolment_id=target.enrolment_id,
                project_id=args.project,
                effective_at=now(),
                reason=args.reason,
            )
            trust.verify_revocation(revocation)
            store.revoke(revocation)
            print(f"revoked {target.enrolment_id} ({target.actor_id}, {target.key_id})", file=out)
            return 0
        except (IdentityUnverified, WarrantStoreError, ValueError) as refused:
            print(f"lab-brain: {refused}", file=out)
            return 1
    if not _member(connection, args.actor, args.project):
        # One sentence for every refusal, as `inbox` does: it says nothing about the project.
        print(f"No reviews for {args.actor} in {args.project}.", file=out)
        return 1
    if args.review_command == "keys":
        return _keys(store, args.project, trust, out)
    if args.review_command == "list":
        pending = store.outstanding(args.project)
        if not pending:
            print("No diagnostic warrant review is outstanding.", file=out)
        for item in pending:
            due = item.due_at.isoformat() if item.due_at else "no deadline"
            lapsed = (
                "  EXPIRED unanswered -- `review expire` closes it"
                if item.expires_at is not None and item.expires_at <= now()
                else ""
            )
            print(f"{item.review_id}  relation {item.subject_id}  due {due}{lapsed}", file=out)
        return 0
    if args.review_command == "expire":
        swept = ReviewExpiryProcessor(reviews=SqlReviewItemStore(connection)).sweep(
            project_id=args.project, now=now(), actor_id=args.actor, trace_id=mint("trace")
        )
        for event in swept.expired:
            print(f"expired {event.subject_id} ({event.event_id})", file=out)
        for review_id, why in sorted(swept.refused.items()):
            print(f"not expired {review_id}: {why}", file=out)
        if not swept.expired and not swept.refused:
            print("No review is overdue.", file=out)
        return 1 if swept.refused else 0
    review = next(
        (r for r in store.outstanding(args.project) if r.review_id == args.review_id), None
    )
    if args.review_command == "show":
        if review is None:
            print(f"No outstanding review {args.review_id} in {args.project}.", file=out)
            return 1
        print(f"{review.review_id}  ({review.status.value})", file=out)
        for line in _packet(connection, args.project, review.subject_id):
            print(line, file=out)
        return 0
    if review is None:
        print(f"No outstanding review {args.review_id} in {args.project}.", file=out)
        return 1
    try:
        grant = store.resolve(
            resolution_id=mint("res"),
            grant_id=mint("dwg"),
            review_id=review.review_id,
            project_id=args.project,
            outcome=ReviewOutcome(args.outcome),
            signer=_signer(store, args, trust, env),
            rationale=args.rationale,
            considered_rival_ids=tuple(args.rival),
            resolved_at=now(),
            identifies_class_ref=args.is_class,
        )
    except (WarrantStoreError, IdentityUnverified) as refused:
        print(f"lab-brain: {refused}", file=out)
        return 1
    print(
        f"{review.review_id}: {grant.verdict.value} ({grant.grant_id}) for {grant.relation_id}. "
        "Resume the episode to let it count.",
        file=out,
    )
    return 0


__all__ = ["add_review_parser", "run_keygen", "run_review"]
