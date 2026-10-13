"""`lab-brain review`: a person answers DIAGNOSTIC_WARRANT reviews (Causal Warrant Gate).

    list      the project's outstanding warrant reviews, oldest first
    show      one review's packet: what was claimed, what was observed, what the rivals said
    resolve   APPROVED (the outcome does bear on the mechanism as claimed) or REJECTED, with a
              rationale -- written atomically by `diagnostic_warrant_resolve`

WHAT A REVIEWER IS ASKED. Whether one observed outcome bears on one hypothesis's mechanism the way
its author declared: for SUPPORTS, that the mechanism produces it and the rivals do not; for
CONTRADICTS, that the mechanism cannot. The packet shows the declared effect, the outcome observed,
the check that observed it, and every rival's declared effect on the same observable -- a rival
affirming the same outcome is the first thing that makes a SUPPORTS non-discriminating. It shows
the hypothesis's author for accountability, never as a reason: the answer is about the link.

WHO MAY ANSWER. An active human member of the project; the database refuses anyone else, and
refuses a second answer to the same review. A grant warrants exactly one relation and nothing
beyond it. Resuming the episode afterwards is the existing continuation path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any, TextIO

from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore, WarrantStoreError


def add_review_parser(sub: Any) -> None:
    review = sub.add_parser("review", help="answer diagnostic warrant reviews")
    actions = review.add_subparsers(dest="review_command", required=True)
    listed = actions.add_parser("list", help="outstanding diagnostic warrant reviews")
    shown = actions.add_parser("show", help="one review's packet")
    shown.add_argument("review_id")
    resolved = actions.add_parser("resolve", help="answer one review")
    resolved.add_argument("review_id")
    resolved.add_argument("--outcome", required=True, choices=("APPROVED", "REJECTED"))
    resolved.add_argument("--rationale", required=True)
    resolved.add_argument(
        "--rival",
        action="append",
        default=[],
        help="a rival hypothesis id the outcome was weighed against (repeatable)",
    )
    for parser in (listed, shown, resolved):
        parser.add_argument("--project", required=True)
        parser.add_argument("--actor", required=True)


def _member(connection: Any, actor_id: str, project_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM actors a JOIN project_memberships m ON m.actor_id = a.actor_id"
        " WHERE a.actor_id = %s AND a.active AND a.actor_type = 'HUMAN'"
        " AND m.project_id = %s AND m.active",
        (actor_id, project_id),
    ).fetchone()
    return row is not None


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


def run_review(
    args: argparse.Namespace,
    connection: Any,
    *,
    out: TextIO,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    mint: Callable[[str], str] = lambda kind: f"{kind}:{uuid.uuid4()}",
) -> int:
    if not _member(connection, args.actor, args.project):
        # One sentence for every refusal, as `inbox` does: it says nothing about the project.
        print(f"No reviews for {args.actor} in {args.project}.", file=out)
        return 1
    store = SqlDiagnosticWarrantStore(connection)
    if args.review_command == "list":
        pending = store.outstanding(args.project)
        if not pending:
            print("No diagnostic warrant review is outstanding.", file=out)
        for item in pending:
            due = item.due_at.isoformat() if item.due_at else "no deadline"
            print(f"{item.review_id}  relation {item.subject_id}  due {due}", file=out)
        return 0
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
            actor_id=args.actor,
            rationale=args.rationale,
            considered_rival_ids=tuple(args.rival),
            resolved_at=now(),
        )
    except WarrantStoreError as refused:
        print(f"lab-brain: {refused}", file=out)
        return 1
    print(
        f"{review.review_id}: {grant.verdict.value} ({grant.grant_id}) for {grant.relation_id}. "
        "Resume the episode to let it count.",
        file=out,
    )
    return 0


__all__ = ["add_review_parser", "run_review"]
